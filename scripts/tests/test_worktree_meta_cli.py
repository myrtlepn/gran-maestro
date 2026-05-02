from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds import worktree as worktree_cmd
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


def _archive_meta_path(master_repo: Path, session_token: str, meta_filename: str) -> Path:
    now_month = datetime.utcnow().strftime("%Y-%m")
    return master_repo / ".gran-maestro" / "worktrees" / ".archive" / session_token / now_month / meta_filename


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


def test_remove_marks_existing_meta_cleaned_and_archived(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-682-T03"
    branch = "gran-maestro/master/REQ-682-T03"
    session_id = "session-REQ-682"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    archive_path = _archive_meta_path(master_repo, session_id, meta_path.name)
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
            "session_id": session_id,
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
    assert not meta_path.exists()

    meta = _read_json(archive_path)
    assert meta["taskId"] == task_id
    assert meta["path"] == str(worktree_path.resolve(strict=False))
    assert meta["branch"] == branch
    assert meta["state"] == "cleaned"
    assert meta["session_id"] == session_id
    assert meta["created_at"] == created_at
    assert meta["last_activity_at"] != last_activity_at
    assert meta["archived_at"] == meta["last_activity_at"]
    _assert_iso_utc(meta["last_activity_at"])
    _assert_iso_utc(meta["archived_at"])


def test_remove_archives_meta_without_session_under_lineage_unknown(
    master_repo: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    task_id = "REQ-682-T05"
    branch = "gran-maestro/master/REQ-682-T05"
    worktree_path = tmp_path / "worktrees" / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    archive_path = _archive_meta_path(master_repo, "lineage-unknown", meta_path.name)

    _create_worktree(master_repo, worktree_path, branch)
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path.resolve(strict=False)),
            "branch": branch,
            "state": "active",
            "session_id": "",
            "owner_session_id": "",
            "created_at": "2026-01-01T00:00:00Z",
            "last_activity_at": "2026-01-01T00:00:00Z",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(argparse.Namespace(path=str(worktree_path), force=True))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert not meta_path.exists()
    assert archive_path.exists()
    assert _read_json(archive_path)["state"] == "cleaned"


def test_archive_target_collision_preserves_existing_file(master_repo: Path) -> None:
    meta_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-682-T06.meta.json"
    meta_data = {"session_id": "session-collision"}
    now = datetime.fromisoformat("2026-05-03T00:00:00+00:00")
    existing = master_repo / ".gran-maestro" / "worktrees" / ".archive" / "session-collision" / "2026-05" / meta_path.name
    _write_json(existing, {"existing": True})

    target = worktree_cmd._worktree_meta_archive_target(master_repo, meta_path, meta_data, now)

    assert target.name == "REQ-682-T06.meta.1.json"
    assert _read_json(existing) == {"existing": True}


def test_archive_session_token_sanitizes_path_segments(master_repo: Path) -> None:
    meta_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-799-T04.meta.json"
    target = worktree_cmd._worktree_meta_archive_target(
        master_repo,
        meta_path,
        {"session_id": "../evil/session"},
        datetime.fromisoformat("2026-05-03T00:00:00+00:00"),
    )

    archive_root = master_repo / ".gran-maestro" / "worktrees" / ".archive"
    assert target.parent == archive_root / "evil-session" / "2026-05"
    assert archive_root in target.parents


def test_move_meta_to_archive_falls_back_to_shutil_move_on_exdev(
    master_repo: Path, monkeypatch
) -> None:
    meta_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-682-T07.meta.json"
    target = master_repo / ".gran-maestro" / "worktrees" / ".archive" / "session-exdev" / "2026-05" / meta_path.name
    _write_json(meta_path, {"taskId": "REQ-682-T07"})
    moved: list[tuple[str, str]] = []

    def fake_rename(self: Path, other: Path) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def fake_move(src: str, dst: str) -> str:
        moved.append((src, dst))
        return shutil.copy2(src, dst) or dst

    monkeypatch.setattr(Path, "rename", fake_rename)
    monkeypatch.setattr(worktree_cmd.shutil, "move", fake_move)

    worktree_cmd._move_meta_to_archive(meta_path, target)

    assert moved == [(str(meta_path), str(target))]
    assert target.exists()


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

    assert not meta_path.exists()
    archive_files = list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json"))
    assert len(archive_files) == 1
    cleaned_meta = _read_json(archive_files[0])
    assert cleaned_meta["state"] == "cleaned"
    assert cleaned_meta["created_at"] == active_meta["created_at"]
    assert cleaned_meta["last_activity_at"] >= active_meta["last_activity_at"]
    assert cleaned_meta["archived_at"] == cleaned_meta["last_activity_at"]

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



def _write_archive_meta(master_repo: Path, session: str, month: str, name: str, data: dict, mtime: float) -> Path:
    meta_path = master_repo / ".gran-maestro" / "worktrees" / ".archive" / session / month / name
    _write_json(meta_path, data)
    os.utime(meta_path, (mtime, mtime))
    return meta_path


def test_archive_retention_uses_or_days_or_count_matrix(master_repo: Path, monkeypatch) -> None:
    from datetime import timezone
    import os

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    now = datetime.fromisoformat("2026-05-03T00:00:00+00:00")
    old = datetime.fromisoformat("2026-03-01T00:00:00+00:00").timestamp()
    recent = datetime.fromisoformat("2026-05-02T00:00:00+00:00").timestamp()
    middle = datetime.fromisoformat("2026-04-01T00:00:00+00:00").timestamp()

    recent_file = _write_archive_meta(master_repo, "session-a", "2026-05", "recent.meta.json", {}, recent)
    count_file = _write_archive_meta(master_repo, "session-a", "2026-04", "count.meta.json", {}, middle)
    delete_file = _write_archive_meta(master_repo, "session-a", "2026-03", "delete.meta.json", {}, old)

    payload = worktree_cmd.prune_worktree_meta_archive(
        master_repo,
        retention_days=30,
        retention_count=2,
        apply=False,
        now=now,
    )

    kept_paths = {item["path"] for item in payload["kept"]}
    deleted_paths = {item["path"] for item in payload["deleted"]}
    assert kept_paths == {str(recent_file), str(count_file)}
    assert deleted_paths == {str(delete_file)}
    assert recent_file.exists()
    assert count_file.exists()
    assert delete_file.exists()

    apply_payload = worktree_cmd.prune_worktree_meta_archive(
        master_repo,
        retention_days=30,
        retention_count=2,
        apply=True,
        now=now,
    )
    assert {item["path"] for item in apply_payload["deleted"]} == {str(delete_file)}
    assert recent_file.exists()
    assert count_file.exists()
    assert not delete_file.exists()


def test_archive_retention_none_and_zero_semantics(master_repo: Path, monkeypatch) -> None:
    import os

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    now = datetime.fromisoformat("2026-05-03T00:00:00+00:00")
    old = datetime.fromisoformat("2026-03-01T00:00:00+00:00").timestamp()
    meta_path = _write_archive_meta(master_repo, "session-old", "2026-03", "old.meta.json", {}, old)

    disabled = worktree_cmd.prune_worktree_meta_archive(
        master_repo,
        retention_days=None,
        retention_count=None,
        apply=True,
        now=now,
    )
    assert disabled["deleted"] == []
    assert meta_path.exists()

    strict = worktree_cmd.prune_worktree_meta_archive(
        master_repo,
        retention_days=0,
        retention_count=0,
        apply=True,
        now=now,
    )
    assert [item["session_token"] for item in strict["deleted"]] == ["session-old"]
    assert not meta_path.exists()


def test_archive_retention_prefers_migrated_at_then_original_mtime_over_stat(master_repo: Path, monkeypatch) -> None:
    import os

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    now = datetime.fromisoformat("2026-05-03T00:00:00+00:00")
    old_stat = datetime.fromisoformat("2026-03-01T00:00:00+00:00").timestamp()
    recent_stat = datetime.fromisoformat("2026-05-01T00:00:00+00:00").timestamp()

    lineage_unknown_original = _write_archive_meta(
        master_repo,
        "lineage-unknown",
        "2026-03",
        "original.meta.json",
        {"migrated_at": "2026-05-02T00:00:00Z", "original_mtime": "2026-02-01T00:00:00Z"},
        recent_stat,
    )
    lineage_unknown_stat = _write_archive_meta(
        master_repo,
        "lineage-unknown",
        "2026-05",
        "stat.meta.json",
        {},
        recent_stat,
    )
    session_migrated = _write_archive_meta(
        master_repo,
        "session-migrated",
        "2026-03",
        "m.meta.json",
        {"migrated_at": "2026-05-02T00:00:00Z", "original_mtime": "2026-02-01T00:00:00Z"},
        old_stat,
    )

    payload = worktree_cmd.prune_worktree_meta_archive(
        master_repo,
        retention_days=30,
        retention_count=None,
        apply=False,
        now=now,
    )

    kept_paths = {item["path"] for item in payload["kept"]}
    deleted_paths = {item["path"] for item in payload["deleted"]}
    assert str(lineage_unknown_original) in kept_paths
    assert str(lineage_unknown_stat) in kept_paths
    assert str(session_migrated) in kept_paths
    assert not deleted_paths
    assert lineage_unknown_original.exists() and lineage_unknown_stat.exists() and session_migrated.exists()


def test_migrate_legacy_cleaned_meta_is_idempotent_and_records_times(master_repo: Path, monkeypatch) -> None:
    import os

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    meta_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-799-T02.meta.json"
    original_dt = datetime.fromisoformat("2026-04-15T12:00:00+00:00")
    _write_json(meta_path, {"taskId": "REQ-799-T02", "state": "cleaned"})
    os.utime(meta_path, (original_dt.timestamp(), original_dt.timestamp()))

    payload = worktree_cmd.migrate_legacy_cleaned_worktree_meta(
        master_repo,
        now=datetime.fromisoformat("2026-05-03T01:02:03+00:00"),
    )
    assert len(payload["migrated"]) == 1
    assert not meta_path.exists()
    target = Path(payload["migrated"][0]["target"])
    assert target.parent.name == "2026-04"
    assert target.parent.parent.name == "lineage-unknown"
    migrated_meta = _read_json(target)
    assert migrated_meta["original_mtime"] == original_dt.timestamp()
    assert migrated_meta["migrated_at"] == "2026-05-03T01:02:03Z"

    first_target = target
    second = worktree_cmd.migrate_legacy_cleaned_worktree_meta(master_repo)
    assert second["migrated"] == []
    assert first_target.exists()
    assert list((master_repo / ".gran-maestro" / "worktrees" / ".archive" / "lineage-unknown").glob("*/*.meta.json")) == [first_target]


def test_default_config_has_worktree_archive_retention_values() -> None:
    defaults = _read_json(REPO_ROOT / "templates" / "defaults" / "config.json")
    assert defaults["worktree"]["archive_retention_days"] == 30
    assert defaults["worktree"]["archive_retention_count"] == 100
