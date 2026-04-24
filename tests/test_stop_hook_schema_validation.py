"""REQ-694/T01: stop-hook Claude Code schema validation tests."""

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
VALID_STOP_DECISIONS = {"approve", "block"}
STOP_HOOK_SCHEMA_FIELDS = {
    "decision",
    "reason",
    "continue",
    "suppressOutput",
    "stopReason",
    "systemMessage",
}


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


def _write_snapshot(project_root: Path, session_id: str, payload: dict) -> Path:
    path = project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _run_hook(
    project_root: Path,
    payload: dict,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
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


def _assert_valid_stop_decision(payload: dict) -> None:
    if "decision" in payload:
        assert payload["decision"] in VALID_STOP_DECISIONS


def _assert_stop_hook_schema(payload: dict) -> None:
    assert set(payload).issubset(STOP_HOOK_SCHEMA_FIELDS)
    _assert_valid_stop_decision(payload)
    if "reason" in payload:
        assert isinstance(payload["reason"], str)
    if "continue" in payload:
        assert isinstance(payload["continue"], bool)
    if "suppressOutput" in payload:
        assert isinstance(payload["suppressOutput"], bool)
    if "stopReason" in payload:
        assert isinstance(payload["stopReason"], str)
    if "systemMessage" in payload:
        assert isinstance(payload["systemMessage"], str)


def test_no_mst_session_decision_is_approve_or_block(tmp_path):
    project_root = _copy_hook_project(tmp_path)

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert "no-mst-session" in payload["reason"]
    _assert_valid_stop_decision(payload)


def test_completion_path_decision_valid(tmp_path):
    project_root = _copy_hook_project(tmp_path)
    _write_snapshot(
        project_root,
        SESSION_ID,
        {
            "sessionId": SESSION_ID,
            "currentSkill": "mst:agile",
            "currentStep": 3,
            "totalSteps": 3,
            "status": "committed",
        },
    )

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert "completion" in payload["reason"]
    _assert_valid_stop_decision(payload)


def test_stop_hook_output_schema_validation(tmp_path):
    project_root = _copy_hook_project(tmp_path)

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    _assert_stop_hook_schema(payload)
