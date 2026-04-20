from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-689"
REQ_ID = "REQ-689"
TASK_ID = "sprint-01"
BRANCH = f"gran-maestro/{AGI_ID}/{TASK_ID}"


def _run_git(repo_root: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or repo_root,
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


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def _session_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "session.json"


def _request_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "requests" / REQ_ID / "request.json"


def _sprint_result_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S00" / "result.json"


def _final_report_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "final-report.md"


def _meta_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / f"{TASK_ID}.meta.json"


def _worktree_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / AGI_ID / TASK_ID


def _relative_worktree_path() -> str:
    return f".gran-maestro/worktrees/{AGI_ID}/{TASK_ID}"


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


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str) -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    add = _run_git(repo_root, "add", relative_path)
    assert add.returncode == 0, add.stderr
    commit = _run_git(repo_root, "commit", "-m", message)
    assert commit.returncode == 0, commit.stderr


def _write_worktree_meta(repo_root: Path, *, state: str) -> None:
    _write_json(
        _meta_path(repo_root),
        {
            "taskId": TASK_ID,
            "agi_id": AGI_ID,
            "path": _relative_worktree_path(),
            "branch": BRANCH,
            "state": state,
        },
    )


def _mark_request_accepted(repo_root: Path) -> None:
    request = _read_json(_request_path(repo_root))
    request["status"] = "accepted"
    _write_json(_request_path(repo_root), request)


def _ensure_lingering_cleaned_worktree(repo_root: Path) -> None:
    worktree_path = _worktree_path(repo_root)
    if not worktree_path.exists():
        if _branch_exists(repo_root, BRANCH):
            add_worktree = _run_git(repo_root, "worktree", "add", str(worktree_path), BRANCH)
        else:
            add_worktree = _run_git(repo_root, "worktree", "add", "-b", BRANCH, str(worktree_path), "master")
        assert add_worktree.returncode == 0, add_worktree.stderr

    _write_worktree_meta(repo_root, state="cleaned")


@pytest.fixture
def req689_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    _commit_file(repo_root, "app.txt", "base\n", "initial commit")
    rename = _run_git(repo_root, "branch", "-M", "master")
    assert rename.returncode == 0, rename.stderr

    _write_json(
        _session_path(repo_root),
        {
            "id": AGI_ID,
            "status": "active",
            "auto_mode": True,
            "current_sprint": 1,
            "created_at": "2026-04-21T00:00:00Z",
            "updated_at": "2026-04-21T00:00:00Z",
        },
    )
    _write_json(_sprint_result_path(repo_root), {"sprint_id": "S00", "req_id": REQ_ID, "status": "done"})
    _write_json(
        _request_path(repo_root),
        {"id": REQ_ID, "title": "REQ-689 integration request", "status": "executing", "current_phase": 4},
    )

    add_worktree = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        BRANCH,
        str(_worktree_path(repo_root)),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    _write_worktree_meta(repo_root, state="active")
    return repo_root


def test_req689_finalize_orphan_cleanup_update_e2e(req689_repo: Path) -> None:
    update_blocked = _run_mst(req689_repo, "agile", "update", AGI_ID, "--status", "completed")

    assert update_blocked.returncode != 0
    assert f'pending_reqs=["{REQ_ID}"]' in update_blocked.stderr
    assert "active_worktrees=[" in update_blocked.stderr
    assert str(_worktree_path(req689_repo).resolve(strict=False)) in update_blocked.stderr
    assert _read_json(_session_path(req689_repo))["status"] == "active"

    first_finalize = _run_mst(req689_repo, "agile", "finalize", AGI_ID, "--json")

    assert first_finalize.returncode == 2, first_finalize.stderr
    first_payload = _payload(first_finalize)
    assert first_payload["pending_accept_reqs"] == [REQ_ID]
    assert "[finalize] pending accept: REQ-689" in first_finalize.stderr
    pending_report = _final_report_path(req689_repo).read_text(encoding="utf-8")
    assert "- status: pending_accept" in pending_report
    assert f'- pending_accept_reqs: ["{REQ_ID}"]' in pending_report

    _mark_request_accepted(req689_repo)
    _ensure_lingering_cleaned_worktree(req689_repo)

    default_preview = _run_mst(req689_repo, "worktree", "detect-orphans", "--json")
    assert default_preview.returncode == 0, default_preview.stderr
    assert [orphan["taskId"] for orphan in _payload(default_preview)["orphans"]] == [TASK_ID]

    scoped_preview = _run_mst(req689_repo, "worktree", "detect-orphans", "--scope", AGI_ID, "--json")
    prefixed_preview = _run_mst(
        req689_repo,
        "worktree",
        "detect-orphans",
        "--prefix",
        f"worktrees/{AGI_ID}/",
        "--json",
    )
    assert scoped_preview.returncode == 0, scoped_preview.stderr
    assert prefixed_preview.returncode == 0, prefixed_preview.stderr
    assert [orphan["taskId"] for orphan in _payload(scoped_preview)["orphans"]] == [TASK_ID]
    assert _payload(scoped_preview)["orphans"] == _payload(prefixed_preview)["orphans"]

    scoped_cleanup = _run_mst(
        req689_repo,
        "worktree",
        "detect-orphans",
        "--scope",
        AGI_ID,
        "--clean",
        "--json",
    )

    assert scoped_cleanup.returncode == 0, scoped_cleanup.stderr
    cleanup_payload = _payload(scoped_cleanup)
    assert cleanup_payload["cleaned"] == [TASK_ID]
    assert cleanup_payload["failed"] == []
    assert not _worktree_path(req689_repo).exists()
    assert not _meta_path(req689_repo).exists()
    assert _worktree_path(req689_repo).resolve(strict=False) not in _worktree_roots(req689_repo)
    assert not _branch_exists(req689_repo, BRANCH)

    scoped_empty = _run_mst(req689_repo, "worktree", "detect-orphans", "--scope", AGI_ID, "--json")
    assert scoped_empty.returncode == 0, scoped_empty.stderr
    assert _payload(scoped_empty)["orphans"] == []

    second_finalize = _run_mst(req689_repo, "agile", "finalize", AGI_ID, "--json")

    assert second_finalize.returncode == 0, second_finalize.stderr
    second_payload = _payload(second_finalize)
    assert second_payload["pending_accept_reqs"] == []
    assert (
        second_payload["removed_worktrees"]
        or second_payload["orphan_cleanup"]["cleaned"]
        or cleanup_payload["cleaned"] == [TASK_ID]
    )
    ok_report = _final_report_path(req689_repo).read_text(encoding="utf-8")
    assert "- status: ok" in ok_report
    assert "- pending_accept_reqs: []" in ok_report
    assert "## Worktree Cleanup" in ok_report
    assert "## Orphan Cleanup" in ok_report

    update_completed = _run_mst(req689_repo, "agile", "update", AGI_ID, "--status", "completed")

    assert update_completed.returncode == 0, update_completed.stderr
    assert _read_json(_session_path(req689_repo))["status"] == "completed"


def test_req689_import_and_help_smoke() -> None:
    worktree = importlib.import_module("scripts.mst_cmds.worktree")
    agile = importlib.import_module("scripts.mst_cmds.agile")
    assert callable(worktree.cmd_worktree_detect_orphans)
    assert callable(agile.cmd_agile_finalize)

    detect_help = subprocess.run(
        [sys.executable, str(MST), "worktree", "detect-orphans", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    finalize_help = subprocess.run(
        [sys.executable, str(MST), "agile", "finalize", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert detect_help.returncode == 0, detect_help.stderr
    assert "--scope" in detect_help.stdout
    assert "--prefix" in detect_help.stdout
    assert finalize_help.returncode == 0, finalize_help.stderr
    assert "agi_id" in finalize_help.stdout
    assert "--json" in finalize_help.stdout
