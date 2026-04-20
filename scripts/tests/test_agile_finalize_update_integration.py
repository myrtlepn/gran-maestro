from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-688"
REQ_ID = "REQ-688"


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


def _meta_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / "sprint-01.meta.json"


def _worktree_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / AGI_ID / "sprint-01"


def _events(repo_root: Path) -> list[dict]:
    events_path = repo_root / ".gran-maestro" / "agile" / AGI_ID / "events.ndjson"
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str) -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    add = _run_git(repo_root, "add", relative_path)
    assert add.returncode == 0, add.stderr
    commit = _run_git(repo_root, "commit", "-m", message)
    assert commit.returncode == 0, commit.stderr


def _mark_request_accepted(repo_root: Path) -> None:
    request = _read_json(_request_path(repo_root))
    request["status"] = "accepted"
    _write_json(_request_path(repo_root), request)


def _mark_worktree_cleaned(repo_root: Path) -> None:
    meta = _read_json(_meta_path(repo_root)) if _meta_path(repo_root).exists() else {}
    meta.update(
        {
            "taskId": "sprint-01",
            "agi_id": AGI_ID,
            "path": str(_worktree_path(repo_root)),
            "state": "cleaned",
        }
    )
    _write_json(_meta_path(repo_root), meta)
    shutil.rmtree(_worktree_path(repo_root), ignore_errors=True)


@pytest.fixture
def finalize_update_repo(tmp_path: Path) -> Path:
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
    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S00" / "result.json",
        {"sprint_id": "S00", "req_id": REQ_ID, "status": "done"},
    )
    _write_json(
        _request_path(repo_root),
        {"id": REQ_ID, "title": "Integration request", "status": "executing", "current_phase": 4},
    )

    worktree_path = _worktree_path(repo_root)
    add_worktree = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        f"gran-maestro/{AGI_ID}/sprint-01",
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    _write_json(
        _meta_path(repo_root),
        {
            "taskId": "sprint-01",
            "agi_id": AGI_ID,
            "path": str(worktree_path),
            "branch": f"gran-maestro/{AGI_ID}/sprint-01",
            "state": "active",
        },
    )
    return repo_root


def test_finalize_then_update_completed_e2e(finalize_update_repo: Path) -> None:
    update_blocked = _run_mst(
        finalize_update_repo,
        "agile",
        "update",
        AGI_ID,
        "--status",
        "completed",
    )

    assert update_blocked.returncode != 0
    assert f'pending_reqs=["{REQ_ID}"]' in update_blocked.stderr
    assert "active_worktrees=[" in update_blocked.stderr
    assert str(_worktree_path(finalize_update_repo)) in update_blocked.stderr
    assert _read_json(_session_path(finalize_update_repo))["status"] == "active"

    first_finalize = _run_mst(finalize_update_repo, "agile", "finalize", AGI_ID, "--json")

    assert first_finalize.returncode == 2, first_finalize.stderr
    first_payload = _payload(first_finalize)
    assert first_payload["pending_accept_reqs"] == [REQ_ID]
    assert "removed_worktrees" in first_payload
    assert "orphan_cleanup" in first_payload
    assert "boundary_ok" in first_payload
    assert "[finalize] pending accept: REQ-688" in first_finalize.stderr
    assert "agile.finalize.pending_accept" in [event["event"] for event in _events(finalize_update_repo)]

    _mark_request_accepted(finalize_update_repo)
    _mark_worktree_cleaned(finalize_update_repo)

    second_finalize = _run_mst(finalize_update_repo, "agile", "finalize", AGI_ID, "--json")

    assert second_finalize.returncode == 0, second_finalize.stderr
    second_payload = _payload(second_finalize)
    assert second_payload["pending_accept_reqs"] == []
    assert "removed_worktrees" in second_payload
    assert isinstance(second_payload["removed_worktrees"], list)

    update_completed = _run_mst(
        finalize_update_repo,
        "agile",
        "update",
        AGI_ID,
        "--status",
        "completed",
    )

    assert update_completed.returncode == 0, update_completed.stderr
    assert _read_json(_session_path(finalize_update_repo))["status"] == "completed"
