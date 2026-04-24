"""REQ-690/T01: stop-hook snapshot guard and fail-open logging tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
FLOW_LOGGER = REPO_ROOT / "scripts" / "_flow_logger.py"
SNAPSHOT_PROBE = REPO_ROOT / "scripts" / "_snapshot_probe.py"
SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"


def _init_project_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_snapshot(project_root: Path, session_id: str, payload: dict) -> Path:
    path = project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _run_hook(project_root: Path, payload: dict) -> subprocess.CompletedProcess:
    if not HOOK.is_file():
        pytest.skip(f"hook not found: {HOOK}")
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must always emit a decision JSON"
    return json.loads(result.stdout)


def test_snapshot_present_step_progress_blocks(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_snapshot(
        project_root,
        SESSION_ID,
        {
            "sessionId": SESSION_ID,
            "currentSkill": "mst:agile",
            "currentStep": 1,
            "totalSteps": 3,
            "status": "active",
        },
    )

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "step_progress" in payload["reason"]
    assert "snapshot_present=true" in payload["reason"]


def test_snapshot_present_return_to_blocks(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_snapshot(
        project_root,
        SESSION_ID,
        {
            "sessionId": SESSION_ID,
            "currentSkill": "mst:request",
            "currentStep": 2,
            "totalSteps": 2,
            "status": "active",
            "returnTo": {"skill": "agile", "step": 4},
        },
    )

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "return_to" in payload["reason"]
    assert "snapshot_present=true" in payload["reason"]


def test_snapshot_present_committed_allows(tmp_path):
    project_root = _init_project_root(tmp_path)
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
    assert payload["decision"] == "approve"
    assert "completion" in payload["reason"]
    assert "snapshot_present=true" in payload["reason"]


def test_snapshot_absent_allows(tmp_path):
    project_root = _init_project_root(tmp_path)

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert "no-mst-session" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]


def test_unhandled_path_fail_open_logs(tmp_path):
    project_root = _init_project_root(tmp_path)
    _write_snapshot(
        project_root,
        SESSION_ID,
        {
            "sessionId": SESSION_ID,
            "currentSkill": "mst:agile",
            "currentStep": 3,
            "totalSteps": 3,
            "status": None,
        },
    )

    result = _run_hook(project_root, {"session_id": SESSION_ID, "hook_event_name": "Stop"})

    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert "unhandled_path fallback" in payload["reason"]

    flow_path = project_root / ".gran-maestro" / "state" / SESSION_ID / "flow-detail.ndjson"
    assert flow_path.is_file()
    event = json.loads(flow_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event_type"] == "unhandled_path"
    assert event["session_id"] == SESSION_ID
    assert event["data"]["snapshot_digest"]
    assert event["data"]["stdin_digest"]
    assert event["data"]["ppid"]
    assert event["data"]["snapshot_dump"]["currentSkill"] == "mst:agile"


def test_flow_logger_mkdir_and_append(tmp_path):
    session_id = "NEW"
    result = subprocess.run(
        [
            sys.executable,
            str(FLOW_LOGGER),
            "append",
            "--project-root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--event-type",
            "test",
            "--data",
            '{"k":"v"}',
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    flow_path = tmp_path / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
    event = json.loads(flow_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event_type"] == "test"
    assert event["data"] == {"k": "v"}


def test_session_id_fallback_from_transcript_path(tmp_path):
    _init_project_root(tmp_path)
    transcript_path = tmp_path / "foo" / "bar" / f"{SESSION_ID}.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SNAPSHOT_PROBE),
            "--project-root",
            str(tmp_path),
        ],
        input=json.dumps({"transcript_path": str(transcript_path)}),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["session_id"] == SESSION_ID
    assert payload["session_id_source"] == "transcript_path"
    assert payload["snapshot_present"] is False
