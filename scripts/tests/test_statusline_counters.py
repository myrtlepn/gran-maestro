from __future__ import annotations

import json
from pathlib import Path

from scripts.mst_cmds.statusline_counters import format_line, read_counters


SID = "73100000-0000-4000-8000-000000000001"


def _history_path(project_root: Path, session_id: str = SID) -> Path:
    return project_root / ".gran-maestro" / "sessions" / session_id / "history.ndjson"


def _write_history(project_root: Path, event_types: list[str]) -> None:
    history_path = _history_path(project_root)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8") as handle:
        for seq, event_type in enumerate(event_types, start=1):
            row = {"seq": seq, "event": {"type": event_type}}
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def test_counts_all_statusline_counter_event_types(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        [
            "policy_block",
            "core_block",
            "policy_block",
            "confirm_requested",
            "confirm_requested",
            "confirm_requested",
            "override_granted",
            "warn_auto_allow",
            "warn_auto_allow",
            "warn_auto_allow",
            "warn_auto_allow",
            "tool_call",
        ],
    )

    assert read_counters(SID, tmp_path) == {
        "CORE-BLOCK": 1,
        "POLICY-BLOCK": 2,
        "PENDING": 3,
        "OVERRIDE": 1,
        "WARN": 4,
    }
    assert (
        format_line(SID, tmp_path)
        == "[CORE-BLOCK:1] [POLICY-BLOCK:2] [PENDING:3] [OVERRIDE:1] [WARN:4]"
    )


def test_pending_counts_confirm_requested_events(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        [
            "confirm_requested",
            "confirm_requested",
            "confirm_requested",
        ],
    )

    assert read_counters(SID, tmp_path)["PENDING"] == 3
    assert (
        format_line(SID, tmp_path)
        == "[CORE-BLOCK:0] [POLICY-BLOCK:0] [PENDING:3] [OVERRIDE:0] [WARN:0]"
    )


def test_pending_counts_both_aliases(tmp_path: Path) -> None:
    _write_history(
        tmp_path,
        [
            "confirm_requested",
            "pending_confirm_created",
            "confirm_requested",
        ],
    )

    assert read_counters(SID, tmp_path)["PENDING"] == 3
    assert (
        format_line(SID, tmp_path)
        == "[CORE-BLOCK:0] [POLICY-BLOCK:0] [PENDING:3] [OVERRIDE:0] [WARN:0]"
    )


def test_missing_history_file_formats_zero_counters(tmp_path: Path) -> None:
    assert read_counters(SID, tmp_path) == {
        "CORE-BLOCK": 0,
        "POLICY-BLOCK": 0,
        "PENDING": 0,
        "OVERRIDE": 0,
        "WARN": 0,
    }
    assert (
        format_line(SID, tmp_path)
        == "[CORE-BLOCK:0] [POLICY-BLOCK:0] [PENDING:0] [OVERRIDE:0] [WARN:0]"
    )


def test_malformed_ndjson_lines_are_skipped(tmp_path: Path) -> None:
    history_path = _history_path(tmp_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"event": {"type": "core_block"}}),
                "{not-json",
                json.dumps({"event": {"type": "warn_auto_allow"}}),
                json.dumps({"event": "not-an-object"}),
                json.dumps({"event": {"type": "policy_block"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert (
        format_line(SID, tmp_path)
        == "[CORE-BLOCK:1] [POLICY-BLOCK:1] [PENDING:0] [OVERRIDE:0] [WARN:1]"
    )
