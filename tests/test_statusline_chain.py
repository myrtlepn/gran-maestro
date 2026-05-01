import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_statusline(workspace: Path, payload: str = "{}", env_overrides: Optional[dict] = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    if env_overrides:
        env.update({key: str(value) for key, value in env_overrides.items()})

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _last_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines[-1]


def _mst_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    counter_pattern = re.compile(r"^\[CORE-BLOCK:\d+\] \[POLICY-BLOCK:\d+\] ")
    for line in reversed(lines):
        if not counter_pattern.match(line):
            return line
    raise AssertionError(f"statusline output has no MST line: {result.stdout!r}")


def _iso_ago(**kwargs) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


def _snapshot_path(workspace: Path, session_id: Optional[str] = None) -> Path:
    if session_id is None:
        session_id = str(os.getpid())
    return workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"


def _write_snapshot(workspace: Path, payload: dict, session_id: Optional[str] = None) -> Path:
    path = _snapshot_path(workspace, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_state(workspace: Path, payload: dict, *, ppid: Optional[int] = None) -> None:
    state_dir = workspace / ".gran-maestro" / "tmp"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"mst-state-{ppid or os.getpid()}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": _iso_ago(minutes=4),
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Skill",
                    "input": {"skill": "mst:transcript", "args": "REQ-668"},
                }
            ]
        },
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_snapshot_for_current_ppid(workspace: Path, skill: str) -> None:
    _write_snapshot(
        workspace,
        {
            "currentSkill": skill,
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
    )


def _write_flow_events(workspace: Path, events: list[dict]) -> Path:
    path = workspace / ".gran-maestro" / "logs" / "flow.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    return path


def _write_flow_events_at(workspace: Path, filename: str, events: list[dict]) -> Path:
    path = workspace / ".gran-maestro" / "logs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    return path


def _flow_event(
    *,
    resource_id: str,
    session_id: str = "current-session",
    skill: str = "mst:agile-plan",
    step: int = 1,
    total_steps: int = 3,
    event_type: str = "enter",
    extras: Optional[dict] = None,
    **overrides,
) -> dict:
    event_extras = dict(extras or {})
    if resource_id:
        event_extras.setdefault("resource_id", resource_id)
    event = {
        "timestamp": _iso_ago(seconds=5),
        "session_id": session_id,
        "skill": skill,
        "step": step,
        "total_steps": total_steps,
        "event_type": event_type,
        "extras": event_extras,
    }
    event.update(overrides)
    return event


def _write_resource_owner(workspace: Path, resource_id: str, owner_ppid: int = None) -> None:
    if owner_ppid is None:
        owner_ppid = os.getpid()
    base = workspace / ".gran-maestro"
    if resource_id.startswith("AGI-"):
        path = base / "agile" / resource_id / "session.json"
    elif resource_id.startswith("REQ-"):
        path = base / "requests" / resource_id / "request.json"
    elif resource_id.startswith("PLN-"):
        path = base / "plans" / resource_id / "plan.json"
    else:
        raise ValueError(f"unsupported resource id: {resource_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"id": resource_id, "owner_ppid": owner_ppid}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_chain_render_from_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [
                {"skill": "plan", "step": 4, "enteredAt": _iso_ago(minutes=8)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
            ],
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(r"plan\(8m\) > request\(15m\) > codex\([2-9]s\)", last_line), last_line


def test_snapshot_path_is_scoped_to_current_ppid(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:plan",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id=str(os.getpid()),
    )
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:request",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id="11111",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert "plan(" in last_line
    assert "request" not in last_line


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        ({"seconds": 45}, r"scale\(4[5-9]s\)"),
        ({"minutes": 8}, r"scale\(8m\)"),
        ({"hours": 2}, r"scale\(2h\)"),
        ({"days": 3}, r"scale\(3d\)"),
    ],
)
def test_format_elapsed_scale_in_snapshot_chain(tmp_path, delta, expected):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "scale",
            "enteredAt": _iso_ago(**delta),
            "skillStack": [],
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(expected, last_line), last_line


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 5, 6])
def test_snapshot_chain_truncate_after_four_nodes(tmp_path, depth):
    workspace = tmp_path / "workspace"
    nodes = [f"skill{i}" for i in range(1, depth + 1)]
    stack = [
        {"skill": skill, "step": index, "enteredAt": _iso_ago(minutes=8)}
        for index, skill in enumerate(nodes[:-1], start=1)
    ]
    _write_snapshot(
        workspace,
        {
            "currentSkill": nodes[-1],
            "enteredAt": _iso_ago(minutes=8),
            "skillStack": stack,
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    if depth <= 3:
        expected = " > ".join(f"{skill}(8m)" for skill in nodes)
    else:
        expected = f"{nodes[0]}(8m) > ... > {nodes[-1]}(8m)"
    assert last_line == expected


@pytest.mark.parametrize("case", ["missing", "invalid", "empty"])
def test_bad_or_empty_snapshot_falls_back_to_idle(tmp_path, case):
    workspace = tmp_path / "workspace"
    path = _snapshot_path(workspace)
    if case == "invalid":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
    elif case == "empty":
        _write_snapshot(workspace, {"currentSkill": "", "skillStack": []})

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert last_line == "MST idle"


def test_bad_snapshot_skips_state_and_uses_transcript_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    path = _snapshot_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    _write_state(
        workspace,
        {
            "current_skill": "mst:state",
            "updated_at": _iso_ago(minutes=6),
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(transcript_path)

    result = _run_statusline(workspace, json.dumps({"transcript_path": str(transcript_path)}))
    last_line = _last_line(result)

    assert re.fullmatch(r"transcript\(4m\) \(REQ-668\)", last_line), last_line
    assert "state" not in last_line


def test_snapshot_wins_over_state_and_transcript_fallbacks(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
    )
    _write_state(
        workspace,
        {
            "current_skill": "mst:state",
            "updated_at": _iso_ago(minutes=6),
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(transcript_path)

    result = _run_statusline(workspace, json.dumps({"transcript_path": str(transcript_path)}))
    last_line = _last_line(result)

    assert re.fullmatch(r"snapshot\([2-9]s\)", last_line), last_line
    assert "state" not in last_line
    assert "transcript" not in last_line


def test_default_snapshot_path_is_used_as_graceful_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:request",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id="default",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(r"request\([2-9]s\)", last_line), last_line


def test_flow_resource_event_takes_priority_over_stale_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:stale-snapshot")
    _write_flow_events(
        workspace,
        [
            _flow_event(resource_id="AGI-028", skill="mst:agile-plan", step=2, total_steps=4),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert last_line == "agile-plan[2/4] (AGI-028)"
    assert "stale-snapshot" not in last_line


def test_flow_scope_prefers_current_session_over_newer_foreign_event(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:stale-snapshot")
    _write_flow_events(
        workspace,
        [
            _flow_event(resource_id="REQ-775", skill="mst:current", session_id="current-session"),
            _flow_event(resource_id="REQ-999", skill="mst:foreign", session_id="foreign-session"),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert last_line == "current[1/3] (REQ-775)"
    assert "foreign" not in last_line
    assert "REQ-999" not in last_line


def test_flow_scope_falls_back_to_resource_owner_ppid(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:stale-snapshot")
    _write_resource_owner(workspace, "PLN-602")
    _write_resource_owner(workspace, "PLN-999", owner_ppid=99999)
    owned = _flow_event(resource_id="PLN-602", skill="mst:owned", session_id="")
    owned.pop("session_id")
    foreign = _flow_event(resource_id="PLN-999", skill="mst:foreign", session_id="")
    foreign.pop("session_id")
    _write_flow_events(workspace, [owned, foreign])

    result = _run_statusline(workspace, json.dumps({"session_id": "unmatched-session"}))
    last_line = _mst_line(result)

    assert last_line == "owned[1/3] (PLN-602)"
    assert "foreign" not in last_line


@pytest.mark.parametrize(
    ("scope_key", "terminal_update"),
    [
        ("session_id", {"event_type": "commit"}),
        ("owner_session_id", {"status": "completed"}),
        ("session_id", {"status": "done"}),
    ],
)
def test_flow_scope_rejects_explicit_foreign_session_before_ppid_fallback(tmp_path, scope_key, terminal_update):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:stale-snapshot")
    _write_resource_owner(workspace, "REQ-775")
    current = _flow_event(resource_id="REQ-775", skill="mst:current", session_id="current-session")
    terminal = _flow_event(resource_id="REQ-775", skill="mst:current", session_id="current-session", **terminal_update)
    foreign = _flow_event(resource_id="REQ-999", skill="mst:foreign", session_id="")
    foreign.pop("session_id")
    foreign[scope_key] = "foreign-session"
    _write_resource_owner(workspace, "REQ-999")
    _write_flow_events(workspace, [current, terminal, foreign])

    result = _run_statusline(workspace, json.dumps({"session_id": "unmatched-session"}))
    last_line = _mst_line(result)

    assert re.fullmatch(r"stale-snapshot\([2-9]s\)", last_line), last_line
    assert "foreign" not in last_line
    assert "REQ-999" not in last_line


def test_flow_terminal_event_supersedes_previous_non_terminal_frame(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    _write_flow_events(
        workspace,
        [
            _flow_event(resource_id="REQ-775", skill="mst:phase", step=1, total_steps=3),
            _flow_event(resource_id="REQ-775", skill="mst:phase", step=3, total_steps=3),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert re.fullmatch(r"legacy\([2-9]s\)", last_line), last_line


@pytest.mark.parametrize(
    "terminal_update",
    [
        {"event_type": "commit"},
        {"status": "completed"},
        {"status": "done"},
    ],
)
def test_flow_terminal_event_type_or_status_supersedes_previous_enter_in_current_session(tmp_path, terminal_update):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    _write_flow_events(
        workspace,
        [
            _flow_event(resource_id="REQ-775", skill="mst:phase", step=1, total_steps=3),
            _flow_event(resource_id="REQ-775", skill="mst:phase", step=1, total_steps=3, **terminal_update),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert re.fullmatch(r"legacy\([2-9]s\)", last_line), last_line
    assert "phase" not in last_line
    assert "REQ-775" not in last_line


@pytest.mark.parametrize(
    ("resource_id", "event"),
    [
        ("AGI-028", _flow_event(resource_id="AGI-028")),
        ("REQ-775", _flow_event(resource_id="", extras={"resource_id": "REQ-775"})),
        ("PLN-602", _flow_event(resource_id="PLN-602")),
    ],
)
def test_flow_accepts_agi_req_pln_resource_id_locations(tmp_path, resource_id, event):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:stale-snapshot")
    _write_flow_events(workspace, [event])

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert last_line == f"agile-plan[1/3] ({resource_id})"


def test_state_set_producer_resource_id_is_consumed_and_terminal_supersedes(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / ".gran-maestro").mkdir()
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", "202604")
    ppid = os.getpid()
    session_id = "producer-session"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    _write_state(
        workspace,
        {
            "workflow_active": True,
            "current_skill": "mst:plan",
            "active_req": "",
            "next_action": {"source_id": "PLN-775", "source": "REQ-should-not-win"},
        },
        ppid=ppid,
    )
    env = dict(os.environ)
    env["MST_STATE_PPID"] = str(ppid)
    env["MST_SNAPSHOT_SESSION_ID"] = session_id
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env.pop("MST_FLOW_LOG_DIR", None)

    enter_result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "state",
            "set",
            "--skill",
            "mst:plan",
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
    assert enter_result.returncode == 0, enter_result.stderr

    result = _run_statusline(
        workspace,
        json.dumps({"session_id": session_id}),
        env_overrides={"MST_STATE_PPID": str(ppid)},
    )
    assert _mst_line(result) == "plan[1/2] (PLN-775)"

    commit_result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "state",
            "set",
            "--skill",
            "mst:plan",
            "--step",
            "2",
            "--total",
            "2",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert commit_result.returncode == 0, commit_result.stderr
    events_path = workspace / ".gran-maestro" / "logs" / "flow-202604.ndjson"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event_type"] for event in events] == ["enter", "enter", "commit"]
    assert all(event["extras"].get("resource_id") == "PLN-775" for event in events)

    result = _run_statusline(
        workspace,
        json.dumps({"session_id": session_id}),
        env_overrides={"MST_STATE_PPID": str(ppid)},
    )
    last_line = _mst_line(result)
    assert re.fullmatch(r"legacy\([2-9]s\)", last_line), last_line


def test_flow_detail_log_is_not_authoritative_source(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    path = workspace / ".gran-maestro" / "logs" / "flow-detail.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_flow_event(resource_id="AGI-999", skill="mst:wrong"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert re.fullmatch(r"legacy\([2-9]s\)", last_line), last_line


def test_flow_prefers_latest_rotated_month_over_fixture_file(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    _write_flow_events(workspace, [_flow_event(resource_id="REQ-111", skill="mst:fixture")])
    _write_flow_events_at(
        workspace,
        "flow-202604.ndjson",
        [_flow_event(resource_id="REQ-222", skill="mst:older-month")],
    )
    _write_flow_events_at(
        workspace,
        "flow-202605.ndjson",
        [_flow_event(resource_id="REQ-333", skill="mst:latest-month")],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert last_line == "latest-month[1/3] (REQ-333)"


def test_flow_reconcile_uses_last_1000_lines_window(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot_for_current_ppid(workspace, "mst:legacy")
    out_of_window = _flow_event(resource_id="REQ-775", skill="mst:outside-window")
    filler = [
        {"event_type": "enter", "session_id": "current-session", "skill": "mst:filler"}
        for _ in range(1000)
    ]
    _write_flow_events(workspace, [out_of_window, *filler])

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    last_line = _mst_line(result)

    assert re.fullmatch(r"legacy\([2-9]s\)", last_line), last_line
