from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def run_check_boundary(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(MST), "worktree", "check-boundary", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return result, payload


def test_entry_missing(tmp_path: Path) -> None:
    meta_path = tmp_path / ".gran-maestro" / "worktrees" / "REQ-679-T01.meta.json"
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-679" / "request.json",
        {
            "id": "REQ-679",
            "status": "phase2_execution",
            "current_phase": 2,
            "detected_base": "main",
            "tasks": [{"id": "T01"}],
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-679",
        "--phase",
        "entry",
        "--task-id",
        "T01",
    )

    assert result.returncode == 0
    assert payload["ok"] is False
    assert payload["violation"] == "worktree_missing"
    assert payload["retry_possible"] is True
    assert payload["detected_base"] == "main"
    assert str(meta_path) in payload["reason"]


def test_exit_not_cleaned(tmp_path: Path) -> None:
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-679" / "request.json",
        {
            "id": "REQ-679",
            "status": "done",
            "current_phase": 5,
            "tasks": [{"id": "T01"}],
        },
    )
    write_json(
        tmp_path / ".gran-maestro" / "worktrees" / "REQ-679-T01.meta.json",
        {
            "taskId": "REQ-679-T01",
            "path": ".gran-maestro/worktrees/REQ-679-T01",
            "branch": "gran-maestro/main/REQ-679-T01",
            "state": "clean_failed",
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-679",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is False
    assert payload["violation"] == "not_cleaned"
    assert payload["retry_possible"] is True
    assert payload["detected_base"] is None


def test_exit_all_committed_tasks_with_no_meta_gracefully_bypasses(tmp_path: Path) -> None:
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-682" / "request.json",
        {
            "id": "REQ-682",
            "status": "done",
            "current_phase": 5,
            "detected_base": "main",
            "tasks": [
                {"id": "T01", "status": "committed"},
                {"id": "T02", "status": "committed"},
            ],
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-682",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["violation"] is None
    assert payload["retry_possible"] is False
    assert payload["detected_base"] == "main"
    assert "legacy_no_meta" in payload["reason"]
    assert "phase2 ready terminal status" in payload["reason"]
    assert "all tasks committed" not in payload["reason"]


def test_exit_all_done_tasks_with_no_meta_gracefully_bypasses(tmp_path: Path) -> None:
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-682" / "request.json",
        {
            "id": "REQ-682",
            "status": "done",
            "current_phase": 5,
            "tasks": [
                {"id": "T01", "status": "done"},
                {"id": "T02", "status": "done"},
            ],
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-682",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["violation"] is None
    assert payload["retry_possible"] is False
    assert "legacy_no_meta" in payload["reason"]
    assert "phase2 ready terminal status" in payload["reason"]
    assert "all tasks committed" not in payload["reason"]


def test_exit_phase2_ready_tasks_with_completed_no_meta_gracefully_bypasses(tmp_path: Path) -> None:
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-682" / "request.json",
        {
            "id": "REQ-682",
            "status": "done",
            "current_phase": 5,
            "tasks": [
                {"id": "T01", "status": "committed"},
                {"id": "T02", "status": "completed"},
                {"id": "T03", "status": "done"},
                {"id": "T04", "status": "accepted"},
            ],
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-682",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["violation"] is None
    assert payload["retry_possible"] is False
    assert "legacy_no_meta" in payload["reason"]
    assert "phase2 ready terminal status" in payload["reason"]
    assert "all tasks committed" not in payload["reason"]


def test_exit_partial_meta_absence_keeps_worktree_missing_violation(tmp_path: Path) -> None:
    missing_meta_path = tmp_path / ".gran-maestro" / "worktrees" / "REQ-682-T02.meta.json"
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-682" / "request.json",
        {
            "id": "REQ-682",
            "status": "done",
            "current_phase": 5,
            "detected_base": "main",
            "tasks": [
                {"id": "T01", "status": "committed"},
                {"id": "T02", "status": "committed"},
            ],
        },
    )
    write_json(
        tmp_path / ".gran-maestro" / "worktrees" / "REQ-682-T01.meta.json",
        {
            "taskId": "REQ-682-T01",
            "path": ".gran-maestro/worktrees/REQ-682-T01",
            "branch": "gran-maestro/main/REQ-682-T01",
            "state": "cleaned",
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-682",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is False
    assert payload["violation"] == "worktree_missing"
    assert payload["retry_possible"] is True
    assert str(missing_meta_path) in payload["reason"]


def test_exit_incomplete_task_status_with_no_meta_keeps_worktree_missing_violation(tmp_path: Path) -> None:
    missing_meta_path = tmp_path / ".gran-maestro" / "worktrees" / "REQ-682-T01.meta.json"
    write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-682" / "request.json",
        {
            "id": "REQ-682",
            "status": "done",
            "current_phase": 5,
            "detected_base": "main",
            "tasks": [
                {"id": "T01", "status": "pending"},
                {"id": "T02", "status": "committed"},
            ],
        },
    )

    result, payload = run_check_boundary(
        tmp_path,
        "--req",
        "REQ-682",
        "--phase",
        "exit",
    )

    assert result.returncode == 0
    assert payload["ok"] is False
    assert payload["violation"] == "worktree_missing"
    assert payload["retry_possible"] is True
    assert str(missing_meta_path) in payload["reason"]
