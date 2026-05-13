"""REQ-692/T01: stop-hook bash failure fail-open diagnostics."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
SESSION_ID = "MST-AGI-036-20260513T120000000Z-hookfail"


def _copy_hook_project(tmp_path: Path) -> Path:
    project_root = tmp_path
    (project_root / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    (project_root / "hooks").mkdir(parents=True, exist_ok=True)
    (project_root / "scripts").mkdir(parents=True, exist_ok=True)

    shutil.copy2(HOOK, project_root / "hooks" / "mst-stop-hook.sh")
    shutil.copytree(REPO_ROOT / "hooks" / "lib", project_root / "hooks" / "lib")
    for script_name in ("_snapshot_probe.py", "_flow_logger.py", "_hook_patterns.py"):
        shutil.copy2(REPO_ROOT / "scripts" / script_name, project_root / "scripts" / script_name)
    return project_root


def _write_state(project_root: Path, payload: dict) -> None:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{SESSION_ID}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_hook(project_root: Path, payload: dict, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    if not HOOK.is_file():
        pytest.skip(f"hook not found: {HOOK}")
    return subprocess.run(
        ["bash", str(project_root / "hooks" / "mst-stop-hook.sh")],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MST_SESSION_ID": SESSION_ID, **(env or {})},
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must always emit a decision JSON"
    return json.loads(result.stdout)


def _last_flow_event(project_root: Path, session_id: str = SESSION_ID) -> dict:
    flow_path = project_root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
    assert flow_path.is_file()
    return json.loads(flow_path.read_text(encoding="utf-8").splitlines()[-1])


def test_err_trap_returns_allow(tmp_path):
    project_root = _copy_hook_project(tmp_path)

    result = _run_hook(
        project_root,
        {"mst_session_id": SESSION_ID, "session_id": SESSION_ID, "hook_event_name": "Stop"},
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": "Traceback (most recent call last):\nboom\n", "MST_STOP_HOOK_TEST_JUDGE_EXIT": "1"},
    )

    payload = _stdout_json(result)
    assert payload == {"decision": "approve", "reason": "hook judge startup failure fail-open"}
    assert "Traceback" not in result.stdout
    assert "judge_invalid_output" in result.stderr


def test_invalid_judge_output_does_not_write_hook_failure_event(tmp_path):
    project_root = _copy_hook_project(tmp_path)

    result = _run_hook(
        project_root,
        {"mst_session_id": SESSION_ID, "session_id": SESSION_ID, "hook_event_name": "Stop"},
        env={"MST_STOP_HOOK_TEST_JUDGE_STDOUT": "diagnostic only\n", "MST_STOP_HOOK_TEST_JUDGE_EXIT": "0"},
    )

    payload = _stdout_json(result)
    assert payload == {"decision": "approve", "reason": "hook judge startup failure fail-open"}
    flow_path = project_root / ".gran-maestro" / "state" / SESSION_ID / "flow-detail.ndjson"
    assert not flow_path.exists()


def test_helper_missing_graceful_fallback(tmp_path):
    project_root = _copy_hook_project(tmp_path)
    _write_state(
        project_root,
        {
            "workflow_active": True,
            "current_skill": "mst:agile",
            "active_req": "REQ-692",
            "iteration": 1,
            "agile_loop_active": True,
        },
    )

    result = _run_hook(
        project_root,
        {
            "mst_session_id": SESSION_ID,
            "session_id": SESSION_ID,
            "last_assistant_message": "계속할까요?",
            "agile_auto_mode": True,
        },
    )

    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "hook judge startup failure fail-open"
    assert "judge_invalid_output" in result.stderr
