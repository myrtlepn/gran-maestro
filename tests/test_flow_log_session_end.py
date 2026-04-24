from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from scripts import _flow_logger


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MONTH = "202604"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _run_state_set_sequence(
    workspace: Path,
    flow_dir: Path,
    *,
    session_id: str = "test-session-end",
    disable_atexit: bool = False,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["MST_FLOW_LOG_DIR"] = str(flow_dir)
    env["MST_FLOW_LOG_MONTH"] = MONTH
    env["MST_SNAPSHOT_SESSION_ID"] = session_id
    env["MST_STATE_PPID"] = "12345"
    if disable_atexit:
        env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    else:
        env.pop("MST_FLOW_DISABLE_ATEXIT", None)

    result = None
    for step in range(1, 4):
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
                "3",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            return result
    assert result is not None
    return result


def _read_flow_events(flow_dir: Path) -> list[dict]:
    path = flow_dir / f"flow-{MONTH}.ndjson"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_atexit_writes_flow_session_end(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set_sequence(workspace, flow_dir)

    assert result.returncode == 0, result.stderr
    events = _read_flow_events(flow_dir)
    assert any(event["event_type"] == "flow_session_end" for event in events)


def test_env_disable_skips_atexit(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set_sequence(workspace, flow_dir, disable_atexit=True)

    assert result.returncode == 0, result.stderr
    events = _read_flow_events(flow_dir)
    assert not any(event["event_type"] == "flow_session_end" for event in events)


def test_partial_failure_continues(tmp_path, monkeypatch, capsys):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"
    monkeypatch.setenv("MST_FLOW_LOG_DIR", str(flow_dir))
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", MONTH)
    monkeypatch.delenv("MST_FLOW_DISABLE_ATEXIT", raising=False)
    _flow_logger._fsync_counters.clear()

    paths = [
        workspace / ".gran-maestro" / "state" / f"session-{index}" / "flow-detail.ndjson"
        for index in range(1, 4)
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"event_type":"existing"}\n', encoding="utf-8")
        _flow_logger._fsync_counters[str(path)] = 1

    with patch("scripts._flow_logger.os.fsync", side_effect=[None, OSError("disk"), None]):
        _flow_logger._session_end_flush()

    captured = capsys.readouterr()
    events = _read_flow_events(flow_dir)
    session_end_events = [event for event in events if event["event_type"] == "flow_session_end"]
    assert len(session_end_events) == 2
    assert captured.err.count("[flow-logger] session end flush failed:") == 1


def test_session_end_event_schema(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set_sequence(workspace, flow_dir, session_id="schema-session")

    assert result.returncode == 0, result.stderr
    event = next(event for event in _read_flow_events(flow_dir) if event["event_type"] == "flow_session_end")
    assert event["skill"] == "_session"
    assert event["step"] == 0
    assert event["total_steps"] == 0
    assert event["schema_version"] == 1
    assert event["session_id"] == "schema-session"
