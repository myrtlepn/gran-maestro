from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-688"


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
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _session_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "session.json"


def _events_path(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "events.ndjson"


def _read_session(repo_root: Path) -> dict:
    return _read_json(_session_path(repo_root))


def _read_events(repo_root: Path) -> list[dict]:
    path = _events_path(repo_root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_sprint_result(repo_root: Path, req_id: str) -> None:
    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "sprints" / "S00" / "result.json",
        {"req_id": req_id},
    )


def _write_request(repo_root: Path, req_id: str, status: str) -> None:
    _write_json(
        repo_root / ".gran-maestro" / "requests" / req_id / "request.json",
        {"id": req_id, "status": status},
    )


def _write_active_worktree(repo_root: Path) -> Path:
    worktree_path = repo_root / ".gran-maestro" / "worktrees" / AGI_ID / "sprint-01"
    meta_path = repo_root / ".gran-maestro" / "worktrees" / f"{AGI_ID}-sprint-01.meta.json"
    _write_json(
        meta_path,
        {
            "state": "active",
            "path": str(worktree_path),
            "taskId": "REQ-688/T03",
            "branch": "req-688-t03",
        },
    )
    return worktree_path


@pytest.fixture
def agile_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    session = {
        "id": AGI_ID,
        "status": "active",
        "auto_mode": True,
        "current_sprint": 1,
        "steering_every": 3,
        "objective": {
            "path": "objective/objective.md",
            "version": 1,
        },
        "created_at": "2026-04-21T00:00:00Z",
        "updated_at": "2026-04-21T00:00:00Z",
    }
    _write_json(_session_path(repo_root), session)
    return repo_root


def test_agile_update_auto_mode_pause_blocked(agile_repo: Path) -> None:
    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "paused")

    assert result.returncode != 0
    assert "자발 정지 시도 차단" in result.stderr
    assert _read_session(agile_repo)["status"] == "active"
    assert _read_events(agile_repo) == []


def test_agile_update_paused_to_active_records_event(agile_repo: Path) -> None:
    session = _read_session(agile_repo)
    session["status"] = "paused"
    _write_json(_session_path(agile_repo), session)

    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "active")

    assert result.returncode == 0, result.stderr
    assert _read_session(agile_repo)["status"] == "active"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update"
    assert events[-1]["fields"] == {"status": "active"}


def test_agile_update_pause_with_user_requested_records_event(agile_repo: Path) -> None:
    result = _run_mst(
        agile_repo,
        "agile",
        "update",
        AGI_ID,
        "--status",
        "paused",
        "--user-requested",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{AGI_ID}\n"
    assert _read_session(agile_repo)["status"] == "paused"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update"
    assert events[-1]["fields"] == {"status": "paused"}


def test_agile_update_pause_with_authorized_env_records_event(
    agile_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MST_AGILE_PAUSE_AUTHORIZED", "1")

    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "paused")

    assert result.returncode == 0, result.stderr
    assert _read_session(agile_repo)["status"] == "paused"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update"
    assert events[-1]["fields"] == {"status": "paused"}


@pytest.mark.parametrize(
    ("args", "field_path", "expected"),
    [
        (("--current-sprint", "3"), ("current_sprint",), 3),
        (("--steering-every", "5"), ("steering_every",), 5),
        (("--objective-version", "2"), ("objective", "version"), 2),
    ],
)
def test_agile_update_individual_field_updates(
    agile_repo: Path,
    args: tuple[str, str],
    field_path: tuple[str, ...],
    expected: int,
) -> None:
    result = _run_mst(agile_repo, "agile", "update", AGI_ID, *args)

    assert result.returncode == 0, result.stderr
    data = _read_session(agile_repo)
    for key in field_path:
        data = data[key]
    assert data == expected
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update"


def test_agile_update_combined_field_updates(agile_repo: Path) -> None:
    result = _run_mst(
        agile_repo,
        "agile",
        "update",
        AGI_ID,
        "--current-sprint",
        "3",
        "--steering-every",
        "5",
        "--objective-version",
        "2",
    )

    assert result.returncode == 0, result.stderr
    session = _read_session(agile_repo)
    assert session["current_sprint"] == 3
    assert session["steering_every"] == 5
    assert session["objective"]["version"] == 2
    events = _read_events(agile_repo)
    assert events[-1]["fields"] == {
        "current_sprint": 3,
        "steering_every": 5,
        "objective_version": 2,
    }


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--current-sprint", "-1"), "Error: current_sprint must be >= 0"),
        (("--steering-every", "-1"), "Error: --steering-every must be >= 1"),
    ],
)
def test_agile_update_rejects_invalid_numeric_fields(
    agile_repo: Path,
    args: tuple[str, str],
    message: str,
) -> None:
    result = _run_mst(agile_repo, "agile", "update", AGI_ID, *args)

    assert result.returncode != 0
    assert result.stderr == f"{message}\n"
    assert _read_session(agile_repo)["current_sprint"] == 1
    assert _read_session(agile_repo)["steering_every"] == 3


def test_agile_update_no_fields(agile_repo: Path) -> None:
    result = _run_mst(agile_repo, "agile", "update", AGI_ID)

    assert result.returncode != 0
    assert result.stderr == "Error: no fields to update\n"
    assert _read_session(agile_repo)["status"] == "active"


def test_agile_update_completed_baseline(agile_repo: Path) -> None:
    """T03 may replace or extend this when completed-status guard logic lands."""
    result = _run_mst(
        agile_repo,
        "agile",
        "update",
        AGI_ID,
        "--status",
        "completed",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert _read_session(agile_repo)["status"] == "completed"


def test_agile_update_completed_blocked_by_pending_req(agile_repo: Path) -> None:
    req_id = "REQ-XXX"
    _write_sprint_result(agile_repo, req_id)
    _write_request(agile_repo, req_id, "executing")

    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "completed")

    assert result.returncode != 0
    assert 'pending_reqs=["REQ-XXX"]' in result.stderr
    assert "active_worktrees=[]" in result.stderr
    assert _read_session(agile_repo)["status"] == "active"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update.blocked"
    assert events[-1]["pending_reqs"] == [req_id]


def test_agile_update_completed_forced(agile_repo: Path) -> None:
    req_id = "REQ-XXX"
    _write_sprint_result(agile_repo, req_id)
    _write_request(agile_repo, req_id, "executing")

    result = _run_mst(
        agile_repo,
        "agile",
        "update",
        AGI_ID,
        "--status",
        "completed",
        "--force",
    )

    assert result.returncode == 0, result.stderr
    assert _read_session(agile_repo)["status"] == "completed"
    events = _read_events(agile_repo)
    assert events[-2]["event"] == "agile.update.forced"
    assert events[-2]["pending_reqs"] == [req_id]
    assert events[-1]["event"] == "agile.update"
    assert events[-1]["fields"] == {"status": "completed"}


def test_agile_update_completed_blocked_by_active_worktree(agile_repo: Path) -> None:
    worktree_path = _write_active_worktree(agile_repo)

    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "completed")

    assert result.returncode != 0
    assert "pending_reqs=[]" in result.stderr
    assert "active_worktrees=[" in result.stderr
    assert str(worktree_path) in result.stderr
    assert _read_session(agile_repo)["status"] == "active"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update.blocked"
    assert events[-1]["active_worktrees"] == [str(worktree_path)]


def test_agile_update_completed_clean(agile_repo: Path) -> None:
    req_id = "REQ-DONE"
    _write_sprint_result(agile_repo, req_id)
    _write_request(agile_repo, req_id, "accepted")

    result = _run_mst(agile_repo, "agile", "update", AGI_ID, "--status", "completed")

    assert result.returncode == 0, result.stderr
    assert _read_session(agile_repo)["status"] == "completed"
    events = _read_events(agile_repo)
    assert events[-1]["event"] == "agile.update"
    assert events[-1]["fields"] == {"status": "completed"}
