from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.worktree import cmd_worktree_create, cmd_worktree_remove

REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_iso_utc(value: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


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
    _write_file(
        repo_root / ".claude" / "hooks" / "mst-session-init.sh",
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _write_file(
        repo_root / ".claude" / "hooks" / "mst-stop-hook.sh",
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _write_file(
        repo_root / ".claude" / "settings.local.json",
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"]}}, ensure_ascii=False, indent=2),
    )
    return repo_root


def _create_worktree(master_repo: Path, worktree_path: Path, branch: str) -> None:
    add_worktree = _run_git(
        master_repo,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr


def test_create_writes_active_meta(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-682-T01"
    branch = "gran-maestro/master/REQ-682-T01"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(worktree_path),
            branch=branch,
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(worktree_path.resolve(strict=False))

    meta = _read_json(meta_path)
    assert meta["taskId"] == task_id
    assert meta["path"] == str(worktree_path.resolve(strict=False))
    assert meta["branch"] == branch
    assert meta["state"] == "active"
    assert meta["created_at"] == meta["last_activity_at"]
    _assert_iso_utc(meta["created_at"])


def test_create_preserves_existing_created_at(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-682-T02"
    branch = "gran-maestro/master/REQ-682-T02"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    created_at = "2026-01-01T00:00:00Z"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path.resolve(strict=False)),
            "branch": branch,
            "state": "cleaned",
            "created_at": created_at,
            "last_activity_at": created_at,
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(worktree_path),
            branch=branch,
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""

    meta = _read_json(meta_path)
    assert meta["created_at"] == created_at
    assert meta["last_activity_at"] != created_at
    assert meta["state"] == "active"


def test_remove_marks_existing_meta_cleaned(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-682-T03"
    branch = "gran-maestro/master/REQ-682-T03"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    created_at = "2026-01-01T00:00:00Z"
    last_activity_at = "2026-01-02T00:00:00Z"

    _create_worktree(master_repo, worktree_path, branch)
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path.resolve(strict=False)),
            "branch": branch,
            "state": "active",
            "created_at": created_at,
            "last_activity_at": last_activity_at,
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(worktree_path),
            force=True,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(worktree_path.resolve(strict=False))

    meta = _read_json(meta_path)
    assert meta["taskId"] == task_id
    assert meta["path"] == str(worktree_path.resolve(strict=False))
    assert meta["branch"] == branch
    assert meta["state"] == "cleaned"
    assert meta["created_at"] == created_at
    assert meta["last_activity_at"] != last_activity_at
    _assert_iso_utc(meta["last_activity_at"])


def test_remove_without_meta_silent_skip(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-682-T04"
    branch = "gran-maestro/master/REQ-682-T04"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"

    _create_worktree(master_repo, worktree_path, branch)

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(worktree_path),
            force=True,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(worktree_path.resolve(strict=False))
    assert not meta_path.exists()


def test_cli_create_remove_then_exit_boundary_passes(master_repo: Path, tmp_path: Path) -> None:
    req_id = "REQ-682"
    task_id = "T03"
    full_task_id = f"{req_id}-{task_id}"
    branch = f"gran-maestro/master/{full_task_id}"
    worktree_path = tmp_path / "worktrees" / full_task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{full_task_id}.meta.json"

    _write_json(
        master_repo / ".gran-maestro" / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "status": "done",
            "current_phase": 5,
            "detected_base": "master",
            "tasks": [{"id": task_id, "status": "committed"}],
        },
    )

    create = _run_mst(
        master_repo,
        "worktree",
        "create",
        "--path",
        str(worktree_path),
        "--branch",
        branch,
        "--base",
        "master",
    )
    assert create.returncode == 0, create.stderr
    assert create.stdout.strip() == str(worktree_path.resolve(strict=False))

    active_meta = _read_json(meta_path)
    assert active_meta["state"] == "active"
    assert active_meta["taskId"] == full_task_id
    assert active_meta["branch"] == branch

    remove = _run_mst(
        master_repo,
        "worktree",
        "remove",
        "--path",
        str(worktree_path),
        "--force",
    )
    assert remove.returncode == 0, remove.stderr
    assert remove.stdout.strip() == str(worktree_path.resolve(strict=False))

    cleaned_meta = _read_json(meta_path)
    assert cleaned_meta["state"] == "cleaned"
    assert cleaned_meta["created_at"] == active_meta["created_at"]
    assert cleaned_meta["last_activity_at"] >= active_meta["last_activity_at"]

    boundary = _run_mst(
        master_repo,
        "worktree",
        "check-boundary",
        "--req",
        req_id,
        "--phase",
        "exit",
    )
    assert boundary.returncode == 0, boundary.stderr
    payload = json.loads(boundary.stdout)
    assert payload["ok"] is True
    assert payload["violation"] is None
    assert payload["retry_possible"] is False
    assert payload["detected_base"] == "master"
