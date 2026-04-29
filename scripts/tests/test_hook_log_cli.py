from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_PY = REPO_ROOT / "scripts" / "mst.py"


def _clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_"))}


def _run(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_PY), *args],
        cwd=project_root,
        env=_clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _make_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".gran-maestro").mkdir(parents=True)
    return project_root


def _write_history(project_root: Path, sid: str, events: list[dict]) -> None:
    session_dir = project_root / ".gran-maestro" / "sessions" / sid
    session_dir.mkdir(parents=True)
    rows = []
    for index, event in enumerate(events, 1):
        rows.append({"event": event, "event_hash": f"hash-{sid}-{index}", "prev_hash": f"prev-{sid}-{index}", "seq": index, "timestamp": event["timestamp"]})
    session_dir.joinpath("history.ndjson").write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def _event(event_type: str, timestamp: str, *, rule_id: str | None = None, tool: str | None = None, reason: str | None = None) -> dict:
    event = {"type": event_type, "timestamp": timestamp}
    if rule_id is not None:
        event["rule_id"] = rule_id
    if tool is not None:
        event["tool"] = tool
    if reason is not None:
        event["reason"] = reason
    return event


def _table_rows(stdout: str) -> list[str]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines[0] == "시간 | 세션 | 이벤트 | 룰/도구 | 비고"
    return lines[1:]


def test_single_session_prints_five_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(
        project_root,
        "sid-one",
        [_event("tool_call", f"2026-04-29T00:00:0{index}Z", tool=f"Tool{index}") for index in range(1, 6)],
    )

    result = _run(project_root, "hook", "log", "--session", "sid-one", "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 5
    assert all(" | sid-one | tool_call | Tool" in row for row in rows)


def test_type_filter_prints_only_matching_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    events = []
    for index in range(1, 11):
        event_type = "core_block" if index % 2 == 0 else "tool_call"
        events.append(_event(event_type, f"2026-04-29T00:00:{index:02d}Z", rule_id=f"rule-{index}"))
    _write_history(project_root, "sid-filter", events)

    result = _run(project_root, "hook", "log", "--session", "sid-filter", "--type", "core_block", "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 5
    assert all(" | core_block | " in row for row in rows)
    assert not any(" | tool_call | " in row for row in rows)


def test_all_sessions_are_sorted_by_timestamp(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(project_root, "sid-b", [_event("tool_call", "2026-04-29T00:00:03Z", tool="B")])
    _write_history(project_root, "sid-a", [_event("tool_call", "2026-04-29T00:00:01Z", tool="A")])
    _write_history(project_root, "sid-c", [_event("tool_call", "2026-04-29T00:00:02Z", tool="C")])

    result = _run(project_root, "hook", "log", "--limit", "100")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert [row.split(" | ")[1] for row in rows] == ["sid-a", "sid-c", "sid-b"]
    assert [row.split(" | ")[0] for row in rows] == ["2026-04-29T00:00:01Z", "2026-04-29T00:00:02Z", "2026-04-29T00:00:03Z"]


def test_json_outputs_ndjson(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    _write_history(
        project_root,
        "sid-json",
        [
            _event("core_block", "2026-04-29T00:00:01Z", rule_id="core-1", reason="blocked"),
            _event("policy_block", "2026-04-29T00:00:02Z", rule_id="policy-1", reason="denied"),
        ],
    )

    result = _run(project_root, "hook", "log", "--session", "sid-json", "--json")

    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2
    assert [row["event"]["type"] for row in rows] == ["core_block", "policy_block"]
    assert all(row["session_id"] == "sid-json" for row in rows)


def test_limit_returns_latest_events(tmp_path: Path) -> None:
    project_root = _make_project(tmp_path)
    start = datetime(2026, 4, 29, tzinfo=timezone.utc)
    _write_history(
        project_root,
        "sid-limit",
        [
            _event("tool_call", (start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"), tool=f"Tool{index}")
            for index in range(100)
        ],
    )

    result = _run(project_root, "hook", "log", "--session", "sid-limit", "--limit", "10")

    assert result.returncode == 0, result.stderr
    rows = _table_rows(result.stdout)
    assert len(rows) == 10
    assert rows[0].startswith("2026-04-29T01:30:00Z | ")
    assert rows[-1].startswith("2026-04-29T01:39:00Z | ")
