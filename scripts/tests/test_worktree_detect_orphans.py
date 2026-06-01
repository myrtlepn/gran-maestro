from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.worktree import cmd_worktree_detect_orphans


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _worktree_roots(repo_root: Path) -> set[Path]:
    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    assert result.returncode == 0, result.stderr
    return {
        Path(line.split(" ", 1)[1]).resolve(strict=False)
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    }


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = _run_git(repo_root, "branch", "--list", branch)
    assert result.returncode == 0, result.stderr
    return bool(result.stdout.strip())


@pytest.fixture
def master_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "master-repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr

    config_email = _run_git(repo_root, "config", "user.email", "tester@example.com")
    assert config_email.returncode == 0, config_email.stderr

    config_name = _run_git(repo_root, "config", "user.name", "Test User")
    assert config_name.returncode == 0, config_name.stderr

    initial_commit = _run_git(repo_root, "commit", "--allow-empty", "-m", "initial commit")
    assert initial_commit.returncode == 0, initial_commit.stderr

    rename_branch = _run_git(repo_root, "branch", "-M", "master")
    assert rename_branch.returncode == 0, rename_branch.stderr

    (repo_root / ".gran-maestro" / "worktrees").mkdir(parents=True, exist_ok=True)
    return repo_root


def _run_detect_orphans(
    *,
    clean: bool,
    as_json: bool,
    scope: str | None = None,
    prefix: str | None = None,
) -> int:
    return cmd_worktree_detect_orphans(
        argparse.Namespace(
            clean=clean,
            json=as_json,
            scope=scope,
            prefix=prefix,
        )
    )


def test_detect_orphans_archives_cleaned_meta_with_lingering_worktree(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T01"
    branch = "gran-maestro/main/REQ-681-T01"
    worktree_path = tmp_path / task_id
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == [task_id]
    assert payload["orphans"][0]["taskId"] == task_id
    assert payload["orphans"][0]["worktree_listed"] is True
    assert payload["orphans"][0]["branch_exists"] is True
    assert not meta_path.exists()
    archived = list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json"))
    assert len(archived) == 1
    archived_meta = json.loads(archived[0].read_text(encoding="utf-8"))
    assert archived_meta["state"] == "cleaned"
    assert archived_meta["taskId"] == task_id
    assert not worktree_path.exists()
    assert worktree_path.resolve(strict=False) not in _worktree_roots(master_repo)
    assert not _branch_exists(master_repo, branch)


def test_detect_orphans_migrates_cleaned_meta_without_artifacts(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T02"
    branch = "gran-maestro/main/REQ-681-T02"
    worktree_path = tmp_path / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == []
    assert payload["orphans"] == []
    assert not meta_path.exists()
    archived = list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["taskId"] == task_id


def test_detect_orphans_archives_branch_only_cleaned_meta_orphan(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T03"
    branch = "gran-maestro/main/REQ-681-T03"
    worktree_path = tmp_path / task_id
    create_branch = _run_git(master_repo, "branch", branch, "master")
    assert create_branch.returncode == 0, create_branch.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == [task_id]
    assert payload["orphans"][0]["worktree_listed"] is False
    assert payload["orphans"][0]["branch_exists"] is True
    assert payload["orphans"][0]["path_exists"] is False
    assert payload["orphans"][0]["classification"] == "branch_only_orphan"
    assert payload["orphans"][0]["reason"] == "orphan_resource_detected"
    assert payload["orphans"][0]["next_action"] == "none"
    assert payload["orphans"][0]["destructive_cleanup_performed"] is True
    assert payload["orphans"][0]["ownership_evidence"]["branch_exists"] is True
    assert {
        item["kind"] for item in payload["orphans"][0]["affected_resources"]
    } == {"worktree_path", "branch", "worktree_meta"}
    assert not meta_path.exists()
    archived = list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["taskId"] == task_id
    assert not _branch_exists(master_repo, branch)


def test_detect_orphans_migrates_legacy_cleaned_meta_idempotently(master_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    task_id = "REQ-799-T03-IDEMPOTENT"
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    original_dt = datetime.fromisoformat("2026-04-20T00:00:00+00:00")
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(tmp_path / task_id),
            "branch": "gran-maestro/main/REQ-799-T03-IDEMPOTENT",
            "state": "cleaned",
        },
    )
    os.utime(meta_path, (original_dt.timestamp(), original_dt.timestamp()))

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    first_exit = _run_detect_orphans(clean=False, as_json=True)
    first = capsys.readouterr()
    first_payload = json.loads(first.out)

    assert first_exit == 0, first.err
    assert first_payload["orphans"] == []
    assert not meta_path.exists()
    archived = list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown" / "2026-04").glob("*.meta.json"))
    assert len(archived) == 1
    archived_meta = json.loads(archived[0].read_text(encoding="utf-8"))
    assert archived_meta["taskId"] == task_id
    assert archived_meta["state"] == "cleaned"
    assert archived_meta["original_mtime"] == original_dt.timestamp()
    assert "migrated_at" in archived_meta

    second_exit = _run_detect_orphans(clean=False, as_json=True)
    second = capsys.readouterr()
    second_payload = json.loads(second.out)

    assert second_exit == 0, second.err
    assert second_payload["orphans"] == []
    assert len(list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json"))) == 1



def test_detect_orphans_empty_state(master_repo: Path, monkeypatch, capsys) -> None:
    """AC-001 (REQ-689/T01): meta 없음 + `--json` 기본 실행 → orphans/cleaned/failed 모두 빈 배열."""
    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=False, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["orphans"] == []
    assert payload["cleaned"] == []
    assert payload["failed"] == []


def test_detect_orphans_ignores_active_meta_by_default(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC-004 (REQ-689/T01): state="active" meta는 기본 옵션(--scope 미지정) 하에서 제외.
    T02 `--scope`/`--prefix` 옵션 도입 후에도 이 기본 동작이 회귀 없이 유지되어야 한다.
    """
    task_id = "REQ-689-T02-ACTIVE"
    branch = "gran-maestro/main/REQ-689-T02-ACTIVE"
    worktree_path = tmp_path / task_id
    create_branch = _run_git(master_repo, "branch", branch, "master")
    assert create_branch.returncode == 0, create_branch.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "active",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=False, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["orphans"] == []
    assert payload["cleaned"] == []
    assert meta_path.exists()


def test_detect_orphans_scope_includes_active_agi_meta(
    master_repo: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC-001 (REQ-689/T02): --scope includes matching active AGI meta."""
    task_id = "REQ-689-T02-SCOPE"
    agi_id = "AGI-123"
    branch = "gran-maestro/AGI-123/sprint-01"
    worktree_path = master_repo / ".gran-maestro" / "worktrees" / agi_id / "sprint-01"
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "agi_id": agi_id,
            "path": ".gran-maestro/worktrees/AGI-123/sprint-01",
            "branch": branch,
            "state": "active",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=False, as_json=True, scope=agi_id)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert [orphan["taskId"] for orphan in payload["orphans"]] == [task_id]
    assert payload["orphans"][0]["worktree_listed"] is True
    assert payload["orphans"][0]["path_exists"] is True
    assert meta_path.exists()


def test_detect_orphans_scope_clean_removes_active_worktree(
    master_repo: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC-002 (REQ-689/T02): --scope --clean cleans matching active AGI meta."""
    task_id = "REQ-689-T02-SCOPE-CLEAN"
    agi_id = "AGI-123"
    branch = "gran-maestro/AGI-123/sprint-clean"
    worktree_path = master_repo / ".gran-maestro" / "worktrees" / agi_id / "sprint-clean"
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "agi_id": agi_id,
            "path": ".gran-maestro/worktrees/AGI-123/sprint-clean",
            "branch": branch,
            "state": "active",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True, scope=agi_id)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == [task_id]
    assert not worktree_path.exists()
    assert not meta_path.exists()
    assert worktree_path.resolve(strict=False) not in _worktree_roots(master_repo)


def test_detect_orphans_scope_includes_fs_only_sprint_worktree(
    master_repo: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC-003 (REQ-689/T02): --scope includes sprint-* worktrees without meta."""
    agi_id = "AGI-456"
    branch = "gran-maestro/AGI-456/sprint-02"
    worktree_path = master_repo / ".gran-maestro" / "worktrees" / agi_id / "sprint-02"
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=False, as_json=True, scope=agi_id)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert len(payload["orphans"]) == 1
    assert payload["orphans"][0]["taskId"] == "<fs-orphan:sprint-02>"
    assert payload["orphans"][0]["meta_path"] is None
    assert payload["orphans"][0]["worktree_listed"] is True
    assert payload["orphans"][0]["path_exists"] is True
    assert payload["orphans"][0]["classification"] == "registered_orphan_worktree"
    assert payload["orphans"][0]["next_action"] == "rerun_with_clean_after_confirming_ownership_or_scope"
    assert payload["orphans"][0]["destructive_cleanup_performed"] is False
    assert payload["orphans"][0]["ownership_evidence"]["worktree_listed"] is True
    assert {
        item["kind"] for item in payload["orphans"][0]["affected_resources"]
    } == {"worktree_path"}


def test_detect_orphans_prefix_includes_matching_active_meta(
    master_repo: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC-004 (REQ-689/T02): --prefix includes active meta by relative path."""
    task_id = "REQ-689-T02-PREFIX"
    agi_id = "AGI-123"
    branch = "gran-maestro/AGI-123/sprint-prefix"
    worktree_path = master_repo / ".gran-maestro" / "worktrees" / agi_id / "sprint-prefix"
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "agi_id": agi_id,
            "path": ".gran-maestro/worktrees/AGI-123/sprint-prefix",
            "branch": branch,
            "state": "active",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=False, as_json=True, prefix="worktrees/AGI-123/")
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert [orphan["taskId"] for orphan in payload["orphans"]] == [task_id]
    assert payload["orphans"][0]["worktree_listed"] is True
    assert payload["orphans"][0]["path_exists"] is True
    assert meta_path.exists()


def test_detect_orphans_help_lists_scope_and_prefix() -> None:
    """AC-007 (REQ-689/T02): CLI help exposes --scope and --prefix."""
    result = subprocess.run(
        ["python3", "scripts/mst.py", "worktree", "detect-orphans", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--scope" in result.stdout
    assert "--prefix" in result.stdout


def test_worktree_module_import_smoke() -> None:
    """AC-005 (REQ-689/T01): worktree 모듈 import 기본 smoke."""
    import importlib

    module = importlib.import_module("scripts.mst_cmds.worktree")
    assert hasattr(module, "cmd_worktree_detect_orphans")
    assert callable(module.cmd_worktree_detect_orphans)
