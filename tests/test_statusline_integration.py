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


def _run_statusline(
    workspace: Path,
    payload: str = "{}",
    *,
    ppid: Optional[str] = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    if ppid is None:
        env.pop("MST_STATE_PPID", None)
    else:
        env["MST_STATE_PPID"] = ppid

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
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


def _write_state(workspace: Path, payload: dict) -> None:
    state_dir = workspace / ".gran-maestro" / "tmp"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"mst-state-{os.getpid()}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_flow_events(workspace: Path, events: list[dict]) -> Path:
    path = workspace / ".gran-maestro" / "logs" / "flow.ndjson"
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
    skill: str = "mst:flow-current",
    step: Optional[int] = 2,
    total_steps: Optional[int] = 5,
    event_type: str = "enter",
    timestamp: Optional[str] = None,
    extras: Optional[dict] = None,
    **overrides,
) -> dict:
    event_extras = dict(extras or {})
    if resource_id:
        event_extras.setdefault("resource_id", resource_id)
    event = {
        "timestamp": timestamp or _iso_ago(minutes=30),
        "session_id": session_id,
        "skill": skill,
        "event_type": event_type,
        "extras": event_extras,
    }
    if step is not None:
        event["step"] = step
    if total_steps is not None:
        event["total_steps"] = total_steps
    event.update(overrides)
    return event


def _write_run(
    workspace: Path,
    task_id: str,
    provider: str,
    heartbeat: str,
    *,
    skill: str = "",
    started_by_pid: Optional[int] = os.getpid(),
) -> Path:
    path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "pid": 12345,
        "phase": "running",
        "provider": provider,
        "model": "test-model",
        "worktree_dir": str(workspace),
        "last_heartbeat": heartbeat,
    }
    if started_by_pid is not None:
        payload["started_by_pid"] = started_by_pid
    if skill:
        payload["skill"] = skill
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_statusline_cross_session_isolation(tmp_path):
    workspace = tmp_path / "workspace"
    current_ppid = str(os.getpid())
    foreign_ppid = "11111"

    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:current",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id=current_ppid,
    )
    _write_run(
        workspace,
        "REQ-670-CURRENT",
        "codex",
        _iso_ago(seconds=30),
        started_by_pid=int(current_ppid),
    )
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:foreign",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id=foreign_ppid,
    )
    _write_run(
        workspace,
        "REQ-670-FOREIGN",
        "gemini",
        _iso_ago(seconds=30),
        started_by_pid=int(foreign_ppid),
    )

    current_result = _run_statusline(workspace, ppid=current_ppid)
    current_line = _last_line(current_result)
    foreign_result = _run_statusline(workspace, ppid=foreign_ppid)
    foreign_line = _last_line(foreign_result)

    assert re.fullmatch(
        r"current\([0-9]+s\) > \[codex:REQ-670-CURRENT\([0-9]+s\)\]",
        current_line,
    ), current_line
    assert "FOREIGN" not in current_line
    assert "foreign" not in current_line

    assert re.fullmatch(
        r"foreign\([0-9]+s\) > \[gemini:REQ-670-FOREIGN\([0-9]+s\)\]",
        foreign_line,
    ), foreign_line
    assert "CURRENT" not in foreign_line
    assert "current" not in foreign_line


def test_statusline_legacy_default_snapshot_fallback_drops_legacy_run(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:legacy",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [],
        },
        session_id="default",
    )
    _write_run(
        workspace,
        "REQ-670-LEGACY-RUN",
        "codex",
        _iso_ago(seconds=30),
        started_by_pid=None,
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(r"legacy\([0-9]+s\)", last_line), last_line
    assert "REQ-670-LEGACY-RUN" not in last_line
    assert result.stderr == ""


def test_resource_id_flow_result_is_primary_over_newer_ppid_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "step": 9,
            "total": 9,
            "skillStack": [],
        },
    )
    _write_flow_events(
        workspace,
        [
            _flow_event(
                resource_id="REQ-781",
                skill="mst:flow-current",
                step=2,
                total_steps=5,
                timestamp=_iso_ago(hours=3),
            ),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert line == "flow-current[2/5] (REQ-781)"
    assert "snapshot-legacy" not in line
    assert "9/9" not in line


def test_incomplete_resource_id_flow_is_not_merged_with_snapshot_values(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "step": 7,
            "total": 8,
            "skillStack": [],
        },
    )
    _write_flow_events(
        workspace,
        [
            _flow_event(
                resource_id="REQ-781",
                skill="mst:flow-current",
                step=2,
                total_steps=None,
            ),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert line == "snapshot-legacy[7/8]"
    assert "flow-current" not in line
    assert "REQ-781" not in line


def test_flow_resource_id_uses_extras_before_legacy_event_mirror(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [],
        },
    )
    event = _flow_event(
        resource_id="REQ-781",
        event={"resource_id": "REQ-LEGACY"},
    )
    event["resource_id"] = "REQ-TOP"
    _write_flow_events(workspace, [event])

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert line == "flow-current[2/5] (REQ-781)"
    assert "REQ-LEGACY" not in line
    assert "REQ-TOP" not in line


def test_flow_resource_id_ignores_top_level_without_canonical_or_legacy_mirror(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [],
        },
    )
    event = _flow_event(resource_id="")
    event["resource_id"] = "REQ-TOP"
    _write_flow_events(workspace, [event])

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert re.fullmatch(r"snapshot-legacy\([1-9]s\)", line), line
    assert "REQ-TOP" not in line


def test_flow_resource_id_allows_legacy_event_mirror_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [],
        },
    )
    event = _flow_event(resource_id="", event={"resource_id": "REQ-LEGACY"})
    _write_flow_events(workspace, [event])

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert line == "flow-current[2/5] (REQ-LEGACY)"
    assert "snapshot-legacy" not in line


def test_terminal_supersession_is_limited_to_same_resource_and_skill(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "mst:snapshot-legacy",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [],
        },
    )
    _write_flow_events(
        workspace,
        [
            _flow_event(resource_id="REQ-781", skill="mst:closed", step=1, total_steps=5),
            _flow_event(
                resource_id="REQ-781",
                skill="mst:closed",
                step=5,
                total_steps=5,
                event_type="commit",
            ),
            _flow_event(resource_id="REQ-781", skill="mst:survives-skill", step=2, total_steps=5),
            _flow_event(resource_id="REQ-782", skill="mst:survives-resource", step=3, total_steps=5),
        ],
    )

    result = _run_statusline(workspace, json.dumps({"session_id": "current-session"}))
    line = _mst_line(result)

    assert line == "survives-resource[3/5] (REQ-782)"
    assert "closed" not in line
    assert "snapshot-legacy" not in line


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


def test_end_to_end_chain(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=0),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
            ],
        },
    )
    _write_run(
        workspace,
        "REQ-700-T01",
        "gemini",
        _iso_ago(seconds=30),
        skill="mst:gemini",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(
        r"plan\(8m\) > request\(15m\) > codex\([0-9]+s\) > "
        r"\[gemini:REQ-700-T01\(3[0-9]s\)\]",
        last_line,
    ), last_line


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_snapshot_state_does_not_intercept_idle",
        "legacy_snapshot_missing_entered_at",
        "missing_run_dir_snapshot_only",
        "dispatch_register_without_skill",
        "transcript_fallback_without_state_snapshot_or_dispatch",
    ],
)
def test_regression_scenarios(tmp_path, scenario):
    workspace = tmp_path / "workspace"
    payload = "{}"

    if scenario == "missing_snapshot_state_does_not_intercept_idle":
        _write_state(
            workspace,
            {"current_skill": "mst:current", "updated_at": _iso_ago(minutes=5)},
        )
        expected = r"MST idle"

    elif scenario == "legacy_snapshot_missing_entered_at":
        _write_snapshot(
            workspace,
            {
                "currentSkill": "codex",
                "enteredAt": _iso_ago(seconds=1),
                "skillStack": [{"skill": "legacy", "step": 1}],
            },
        )
        expected = r"legacy > codex\([0-9]+s\)"

    elif scenario == "missing_run_dir_snapshot_only":
        _write_snapshot(
            workspace,
            {
                "currentSkill": "request",
                "enteredAt": _iso_ago(minutes=2),
                "skillStack": [
                    {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
                ],
            },
        )
        expected = r"plan\(8m\) > request\(2m\)"

    elif scenario == "dispatch_register_without_skill":
        (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
        register = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--provider",
            "gemini",
            "--task-id",
            "REQ-700-T01",
            "--pid",
            "12345",
            "--model",
            "test-model",
            "--worktree-dir",
            str(workspace),
            "--started-by-pid",
            str(os.getpid()),
        )
        assert register.returncode == 0, register.stderr
        run_path = workspace / ".gran-maestro" / "run" / "REQ-700-T01.json"
        run_payload = json.loads(run_path.read_text(encoding="utf-8"))
        assert run_payload.get("skill", "") == ""
        run_payload["last_heartbeat"] = _iso_ago(seconds=30)
        run_path.write_text(json.dumps(run_payload, ensure_ascii=False), encoding="utf-8")
        expected = r"\[gemini:REQ-700-T01\(3[0-9]s\)\]"

    elif scenario == "transcript_fallback_without_state_snapshot_or_dispatch":
        transcript_path = workspace / "session.jsonl"
        _write_transcript(transcript_path)
        payload = json.dumps({"transcript_path": str(transcript_path)})
        expected = r"transcript\(4m\) \(REQ-668\)"

    else:
        raise AssertionError(f"unhandled scenario: {scenario}")

    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert re.fullmatch(expected, last_line), last_line


def test_truncate_with_dispatch(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=20)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
                {"skill": "review", "step": 3, "enteredAt": _iso_ago(minutes=12)},
                {"skill": "approve", "step": 4, "enteredAt": _iso_ago(minutes=10)},
                {"skill": "dispatch", "step": 5, "enteredAt": _iso_ago(minutes=8)},
            ],
        },
    )
    _write_run(
        workspace,
        "REQ-800-T01",
        "codex",
        _iso_ago(minutes=2),
        skill="mst:codex",
    )
    _write_run(
        workspace,
        "REQ-800-T02",
        "gemini",
        _iso_ago(minutes=3),
        skill="mst:gemini",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(
        r"plan\(20m\) > \.\.\. > codex\([0-9]+s\) > "
        r"\[codex:REQ-800-T01\(2m\), gemini:REQ-800-T02\(3m\)\]",
        last_line,
    ), last_line
