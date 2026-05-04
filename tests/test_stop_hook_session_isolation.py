"""REQ-691/T01: stop-hook owner_session_id isolation tests."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
SID_A = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
SID_B = "MST-AGI-030-20260503T130813382Z-z9y8x7w6"


def _init_project_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_inactive_state(project_root: Path, session_id: str) -> None:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json"
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
        input=json.dumps({"mst_session_id": session_id, "session_id": "claude-diagnostic", "last_assistant_message": ""}),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must emit a decision JSON"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_owner_session_id_match_is_diagnostic_only(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root, SID_A)
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
    assert payload["decision"] == "approve"
    assert "active workflow session detected" not in payload["reason"]


def test_owner_session_id_foreign_session_allows(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root, SID_B)
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


def test_legacy_owner_ppid_is_diagnostic_only(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_inactive_state(project_root, SID_A)
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
    assert payload["decision"] == "approve"
    assert "active workflow session detected" not in payload["reason"]
    assert "owner_ppid-only workflow state ignored" in result.stderr


def main() -> int:
    tests = [
        test_owner_session_id_match_is_diagnostic_only,
        test_owner_session_id_foreign_session_allows,
        test_legacy_owner_ppid_is_diagnostic_only,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as raw:
            test(Path(raw))
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
