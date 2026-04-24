from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
FLOW_FIELDS = {
    "timestamp",
    "session_id",
    "skill",
    "step",
    "total_steps",
    "event_type",
    "parent_skill",
    "parent_step",
    "duration_ms",
    "extras",
    "schema_version",
}


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _run_state_set(
    workspace: Path,
    flow_dir: Path | str,
    *,
    session_id: str = "test-s-1",
    skill: str = "demo",
    step: int = 2,
    total: int = 4,
    return_to: str | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["MST_FLOW_LOG_DIR"] = str(flow_dir)
    env["MST_SNAPSHOT_SESSION_ID"] = session_id
    env.pop("MST_STATE_PPID", None)

    command = [
        sys.executable,
        str(MST_SCRIPT),
        "state",
        "set",
        "--skill",
        skill,
        "--step",
        str(step),
        "--total",
        str(total),
    ]
    if return_to is not None:
        command.extend(["--return-to", return_to])

    return subprocess.run(
        command,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _read_flow_events(flow_dir: Path) -> list[dict]:
    path = flow_dir / "flow.ndjson"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_state_set_appends_enter_event(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set(workspace, flow_dir, skill="demo", step=2, total=4)

    assert result.returncode == 0, result.stderr
    events = _read_flow_events(flow_dir)
    assert events[-1]["skill"] == "demo"
    assert events[-1]["step"] == 2
    assert events[-1]["total_steps"] == 4
    assert events[-1]["event_type"] == "enter"
    assert events[-1]["schema_version"] == 1


def test_enter_event_full_schema(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set(workspace, flow_dir, skill="demo", step=2, total=4)

    assert result.returncode == 0, result.stderr
    event = _read_flow_events(flow_dir)[-1]
    assert FLOW_FIELDS <= set(event)
    assert isinstance(event["timestamp"], str)
    assert event["timestamp"].endswith("Z")
    assert event["duration_ms"] is None or isinstance(event["duration_ms"], (int, float))
    assert isinstance(event["extras"], dict)


def test_final_step_emits_commit_after_enter(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set(workspace, flow_dir, skill="demo", step=3, total=3)

    assert result.returncode == 0, result.stderr
    events = _read_flow_events(flow_dir)
    assert [event["event_type"] for event in events[-2:]] == ["enter", "commit"]
    commit = events[-1]
    assert commit["duration_ms"] is None or commit["duration_ms"] >= 0


def test_parent_skill_parsed_from_return_to(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    result = _run_state_set(
        workspace,
        flow_dir,
        skill="child",
        step=1,
        total=2,
        return_to="parent/3",
    )

    assert result.returncode == 0, result.stderr
    event = _read_flow_events(flow_dir)[-1]
    assert event["parent_skill"] == "parent"
    assert event["parent_step"] == 3


def test_append_failure_is_warn_only(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "not-a-directory"
    flow_dir.write_text("blocks mkdir", encoding="utf-8")

    result = _run_state_set(workspace, flow_dir, skill="demo", step=2, total=4)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["currentSkill"] == "demo"
    assert payload["currentStep"] == 2
    assert "[flow-logger] append failed:" in result.stderr


def test_duration_ms_uses_previous_enter(tmp_path):
    workspace = _workspace(tmp_path)
    flow_dir = tmp_path / "logs"

    first = _run_state_set(workspace, flow_dir, skill="demo", step=1, total=4)
    assert first.returncode == 0, first.stderr
    time.sleep(0.01)
    second = _run_state_set(workspace, flow_dir, skill="demo", step=2, total=4)

    assert second.returncode == 0, second.stderr
    events = _read_flow_events(flow_dir)
    assert events[-1]["event_type"] == "enter"
    assert isinstance(events[-1]["duration_ms"], (int, float))
    assert events[-1]["duration_ms"] >= 0
