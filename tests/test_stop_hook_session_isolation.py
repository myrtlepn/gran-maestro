"""REQ-691/T01: stop-hook owner_session_id isolation tests."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
SID_A = "123e4567-e89b-42d3-a456-426614174000"
SID_B = "123e4567-e89b-42d3-a456-426614174001"


def _init_project_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_inactive_state(project_root: Path) -> None:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"
    state_path.write_text(
        json.dumps(
            {
                "workflow_active": False,
                "agile_loop_active": False,
                "current_skill": "",
                "active_req": "",
            }
        ),
        encoding="utf-8",
    )


def _write_request(project_root: Path, req_id: str, payload: dict) -> Path:
    request_path = project_root / ".gran-maestro" / "requests" / req_id / "request.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return request_path


def _run_hook(project_root: Path, session_id: str) -> subprocess.CompletedProcess:
    if not HOOK.is_file():
        pytest.skip(f"hook not found: {HOOK}")
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"session_id": session_id, "last_assistant_message": ""}),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must emit a decision JSON"
    return json.loads(result.stdout)


def test_owner_session_id_match_blocks_missing_local_state(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root)
    _write_request(
        project_root,
        "REQ-SID-A",
        {
            "id": "REQ-SID-A",
            "status": "phase1_analysis",
            "owner_ppid": 99999,
            "owner_session_id": SID_A,
        },
    )

    result = _run_hook(project_root, SID_A)

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "active workflow session detected" in payload["reason"]


def test_owner_session_id_foreign_session_allows(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root)
    _write_request(
        project_root,
        "REQ-SID-A",
        {
            "id": "REQ-SID-A",
            "status": "phase1_analysis",
            "owner_ppid": os.getpid(),
            "owner_session_id": SID_A,
        },
    )

    result = _run_hook(project_root, SID_B)

    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert "workflow_inactive" in payload["reason"]


def test_legacy_owner_ppid_fallback_warns_and_blocks(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root)
    _write_request(
        project_root,
        "REQ-LEGACY",
        {
            "id": "REQ-LEGACY",
            "status": "phase1_analysis",
            "owner_ppid": os.getpid(),
        },
    )

    result = _run_hook(project_root, SID_A)

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "active workflow session detected" in payload["reason"]
    assert "legacy owner_ppid fallback" in result.stderr
