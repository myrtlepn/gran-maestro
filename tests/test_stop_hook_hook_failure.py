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
SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"


def _copy_hook_project(tmp_path: Path) -> Path:
    project_root = tmp_path
    (project_root / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    (project_root / "hooks").mkdir(parents=True, exist_ok=True)
    (project_root / "scripts").mkdir(parents=True, exist_ok=True)

    shutil.copy2(HOOK, project_root / "hooks" / "mst-stop-hook.sh")
    for script_name in ("_snapshot_probe.py", "_flow_logger.py", "_hook_patterns.py"):
        shutil.copy2(REPO_ROOT / "scripts" / script_name, project_root / "scripts" / script_name)
    return project_root


def _write_state(project_root: Path, payload: dict) -> None:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"
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
        env={**os.environ, **(env or {})},
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
        {"session_id": SESSION_ID, "hook_event_name": "Stop"},
        env={"MST_STOP_HOOK_TEST_INJECT_FAILURE": "after_snapshot_probe"},
    )

    payload = _stdout_json(result)
    assert payload["decision"] == "allow"
    assert payload["reason"].startswith("hook_failure:")
    assert "snapshot_present=" in payload["reason"]
    hook_failure_lines = [
        line for line in result.stderr.splitlines() if "[mst-stop-hook] hook_failure" in line
    ]
    assert len(hook_failure_lines) == 1


def test_hook_failure_event_fields(tmp_path):
    project_root = _copy_hook_project(tmp_path)

    result = _run_hook(
        project_root,
        {"session_id": SESSION_ID, "hook_event_name": "Stop"},
        env={"MST_STOP_HOOK_TEST_INJECT_FAILURE": "after_snapshot_probe"},
    )

    _stdout_json(result)
    event = _last_flow_event(project_root)
    assert event["event_type"] == "hook_failure"
    assert event["session_id"] == SESSION_ID
    for field in ("exit_code", "line", "command", "funcname", "source", "signal", "ppid", "session_id"):
        assert field in event["data"]
    assert event["data"]["exit_code"] != 0
    assert event["data"]["line"]
    assert "REQ-692 injected failure" in event["data"]["command"]
    assert event["data"]["ppid"]
    assert event["data"]["session_id"] == SESSION_ID


def test_helper_missing_graceful_fallback(tmp_path):
    project_root = _copy_hook_project(tmp_path)
    (project_root / "scripts" / "_hook_patterns.py").unlink()
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
            "session_id": SESSION_ID,
            "last_assistant_message": "계속할까요?",
            "agile_auto_mode": True,
        },
    )

    payload = _stdout_json(result)
    assert payload["decision"] == "allow"
    assert "unhandled_path fallback" in payload["reason"]
    assert "[mst-stop-hook] helper_failed helper=hook_patterns" in result.stderr

    event = _last_flow_event(project_root)
    assert event["event_type"] == "unhandled_path"
    assert event["session_id"] == SESSION_ID
