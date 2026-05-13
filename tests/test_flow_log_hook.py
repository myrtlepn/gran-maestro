from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._flow_logger import (
    _rotated_filename,
    append_event,
    append_hook_event,
    flow_detail_path,
    flow_log_path,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MST_SESSION_ID = "MST-AGI-036-20260513T120000000Z-flowtest"
HOOK_FIELDS = {
    "timestamp",
    "session_id",
    "ppid",
    "hook_event",
    "decision",
    "layer",
    "reason",
    "anchor",
    "return_to",
    "duration_ms",
    "snapshot_digest",
    "snapshot_diff",
    "stdin_json_digest",
    "error",
    "schema_version",
}


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _last_json_line(path: Path) -> dict:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_append_hook_event_schema(tmp_path):
    project_root = _workspace(tmp_path)

    path = append_hook_event(
        project_root,
        "test-s",
        hook_event="Stop",
        decision="allow",
        layer="1",
        reason="ok",
        anchor="#layer-1",
        return_to={"skill": "agile", "step": 2},
        duration_ms=47,
        snapshot_digest="sha256:snapshot",
        snapshot_diff="+step 1->2",
        stdin_json_digest="sha256:stdin",
        error=None,
        ppid="1234",
    )

    assert path == flow_detail_path(project_root, "test-s")
    event = _last_json_line(path)
    assert set(event) == HOOK_FIELDS
    assert isinstance(event["timestamp"], str)
    assert event["timestamp"].endswith("Z")
    assert event["session_id"] == "test-s"
    assert event["ppid"] == "1234"
    assert event["hook_event"] == "Stop"
    assert event["decision"] == "allow"
    assert event["layer"] == "1"
    assert event["reason"] == "ok"
    assert event["anchor"] == "#layer-1"
    assert event["return_to"] == {"skill": "agile", "step": 2}
    assert event["duration_ms"] == 47
    assert event["snapshot_digest"] == "sha256:snapshot"
    assert event["snapshot_diff"] == "+step 1->2"
    assert event["stdin_json_digest"] == "sha256:stdin"
    assert event["error"] is None
    assert event["schema_version"] == 1


def test_rotated_filename_month_suffix(monkeypatch):
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")

    assert _rotated_filename("flow.ndjson") == "flow-202604.ndjson"
    assert _rotated_filename("flow-detail.ndjson") == "flow-detail-202604.ndjson"


def test_flow_log_path_rotate_param(tmp_path, monkeypatch):
    project_root = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")

    assert flow_log_path(project_root, rotate=True) == (
        project_root / ".gran-maestro" / "logs" / "flow-202604.ndjson"
    )
    assert flow_log_path(project_root) == project_root / ".gran-maestro" / "logs" / "flow.ndjson"
    assert flow_log_path(project_root, rotate=False) == project_root / ".gran-maestro" / "logs" / "flow.ndjson"


def test_flow_detail_path_rotate_param(tmp_path, monkeypatch):
    project_root = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")

    path = flow_detail_path(project_root, "test-s", rotate=True)

    assert path.parent == project_root / ".gran-maestro" / "state" / "test-s"
    assert path.name == "flow-detail-202604.ndjson"
    assert flow_detail_path(project_root, "test-s").name == "flow-detail.ndjson"


def test_cmd_state_set_uses_rotation(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")
    env = dict(os.environ)
    env["MST_SESSION_ID"] = MST_SESSION_ID
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env.pop("MST_STATE_PPID", None)
    env.pop("MST_SNAPSHOT_SESSION_ID", None)
    env.pop("MST_FLOW_LOG_DIR", None)

    result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "state",
            "set",
            "--skill",
            "demo",
            "--step",
            "1",
            "--total",
            "2",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["currentSkill"] == "demo"
    rotated = workspace / ".gran-maestro" / "logs" / "flow-202604.ndjson"
    assert rotated.exists()
    events = [json.loads(line) for line in rotated.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[-1]["event_type"] == "enter"
    assert not (workspace / ".gran-maestro" / "logs" / "flow.ndjson").exists()


def test_cmd_state_set_records_workflow_resource_id_on_enter_and_commit(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")
    state_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{MST_SESSION_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "workflow_active": True,
                "current_skill": "mst:plan",
                "active_req": "REQ-775",
                "next_action": {"source_id": "PLN-775", "source": "AGI-775"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["MST_SESSION_ID"] = MST_SESSION_ID
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env.pop("MST_STATE_PPID", None)
    env.pop("MST_SNAPSHOT_SESSION_ID", None)
    env.pop("MST_FLOW_LOG_DIR", None)

    for step in (1, 2):
        result = subprocess.run(
            [
                sys.executable,
                str(MST_SCRIPT),
                "state",
                "set",
                "--skill",
                "demo",
                "--step",
                str(step),
                "--total",
                "2",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    rotated = workspace / ".gran-maestro" / "logs" / "flow-202604.ndjson"
    events = [json.loads(line) for line in rotated.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == ["enter", "enter", "commit"]
    assert all(event["extras"].get("resource_id") == "REQ-775" for event in events)


def _run_state_set_with_workflow_payload(
    workspace: Path,
    payload: dict,
    *,
    session_id: str,
    step: int = 1,
    total: int = 2,
) -> list[dict]:
    state_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ)
    env["MST_SESSION_ID"] = session_id
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env.pop("MST_STATE_PPID", None)
    env.pop("MST_SNAPSHOT_SESSION_ID", None)
    env.pop("MST_FLOW_LOG_DIR", None)

    result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "state",
            "set",
            "--skill",
            "demo",
            "--step",
            str(step),
            "--total",
            str(total),
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    rotated = workspace / ".gran-maestro" / "logs" / "flow-202604.ndjson"
    assert rotated.exists()
    return [json.loads(line) for line in rotated.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "active_req": " req-778 ",
                "active_agi": "AGI-028",
                "active_plan": "PLN-605",
                "next_action": {"source_id": "REQ-LOWER"},
            },
            "REQ-778",
        ),
        (
            {
                "active_req": "AGI-NOT-REQ",
                "active_agi": " agi-028 ",
                "active_plan": "PLN-605",
                "next_action": {"source_id": "REQ-LOWER"},
            },
            "AGI-028",
        ),
        (
            {
                "active_req": "",
                "active_agi": "not-agi",
                "agi_id": "AGI-FALLBACK",
                "active_plan": "PLN-605",
                "next_action": {"source_id": "REQ-LOWER"},
            },
            "AGI-FALLBACK",
        ),
        (
            {
                "active_req": "",
                "active_agi": "",
                "active_plan": " pln-605 ",
                "next_action": {"source_id": "REQ-LOWER"},
            },
            "PLN-605",
        ),
        (
            {
                "active_req": "",
                "active_agi": "",
                "active_plan": "bad-plan",
                "plan_id": "PLN-FALLBACK",
                "next_action": {"source_id": "REQ-LOWER"},
            },
            "PLN-FALLBACK",
        ),
        (
            {
                "active_req": "bad-req",
                "active_agi": "bad-agi",
                "active_plan": "bad-plan",
                "next_action": {
                    "source_id": " req-source-id ",
                    "source": "AGI-SOURCE",
                    "resource_id": "PLN-RESOURCE",
                },
            },
            "REQ-SOURCE-ID",
        ),
        (
            {
                "active_req": "",
                "active_agi": "",
                "active_plan": "",
                "next_action": {
                    "source_id": "bad-source-id",
                    "source": " agi-source ",
                    "resource_id": "PLN-RESOURCE",
                },
            },
            "AGI-SOURCE",
        ),
        (
            {
                "active_req": "",
                "active_agi": "",
                "active_plan": "",
                "next_action": {
                    "source_id": "bad-source-id",
                    "source": "bad-source",
                    "resource_id": " pln-resource ",
                },
            },
            "PLN-RESOURCE",
        ),
    ],
)
def test_cmd_state_set_resource_id_priority_and_normalization(tmp_path, monkeypatch, payload, expected):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")

    events = _run_state_set_with_workflow_payload(
        workspace,
        payload,
        session_id=MST_SESSION_ID,
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "enter"
    assert events[0]["extras"].get("resource_id") == expected


def test_cmd_state_set_omits_invalid_resource_id_tokens(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")

    events = _run_state_set_with_workflow_payload(
        workspace,
        {
            "active_req": "REQ lowercase invalid space inside",
            "active_agi": "AGI_028",
            "agi_id": "AGI-",
            "active_plan": "PLAN-605",
            "plan_id": "PLN-",
            "next_action": {
                "source_id": "REQ-*",
                "source": "../REQ-778",
                "resource_id": "REQ-778!",
            },
        },
        session_id=MST_SESSION_ID,
    )

    assert len(events) == 1
    assert events[0]["event_type"] == "enter"
    assert "resource_id" not in events[0]["extras"]


def test_append_event_and_flow_detail_path_default_compatibility(tmp_path):
    project_root = _workspace(tmp_path)
    signature = inspect.signature(append_event)
    assert list(signature.parameters) == [
        "project_root",
        "session_id",
        "event_type",
        "data",
        "snapshot_path",
        "stdin_digest",
        "ppid",
    ]

    path = append_event(project_root, "test-s", "legacy", {"value": 1})

    assert path == project_root / ".gran-maestro" / "state" / "test-s" / "flow-detail.ndjson"
    assert flow_detail_path(project_root, "test-s") == path
    event = _last_json_line(path)
    assert event["event_type"] == "legacy"
    assert event["session_id"] == "test-s"
    assert event["data"] == {"value": 1}


def test_month_env_fallback(monkeypatch):
    expected = datetime.now(timezone.utc).strftime("%Y%m")
    for value in (None, "", "abc", "2026-04"):
        if value is None:
            monkeypatch.delenv("MST_FLOW_LOG_MONTH", raising=False)
        else:
            monkeypatch.setenv("MST_FLOW_LOG_MONTH", value)
        assert _rotated_filename("flow.ndjson") == f"flow-{expected}.ndjson"


def test_append_hook_event_fail_open(tmp_path, monkeypatch, capsys):
    project_root = _workspace(tmp_path)
    read_only_dir = tmp_path / "read-only-logs"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o555)
    monkeypatch.setenv("MST_FLOW_LOG_DIR", str(read_only_dir))

    try:
        path = append_hook_event(
            project_root,
            "test-s",
            hook_event="Stop",
            decision="fail_open",
            layer="unhandled",
        )
    finally:
        read_only_dir.chmod(0o755)

    captured = capsys.readouterr()
    assert path is None
    assert captured.err.startswith("[flow-logger] append failed:")
