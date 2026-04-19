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
