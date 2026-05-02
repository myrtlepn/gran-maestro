from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.mst_cmds import cleanup


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), f"cleanup.{name} contract helper is missing"
    return value


def _cleanup_api_or_skip(name: str):
    value = getattr(cleanup, name, None)
    if not callable(value):
        pytest.skip(f"cleanup.{name} is not implemented yet")
    return value


def _decision_rows() -> list[dict]:
    return json.loads((FIXTURES / "cleanup_decision_table.json").read_text(encoding="utf-8"))


def _marker(row: dict) -> dict | None:
    if row["marker_validity"] == "missing":
        return None
    return {
        "session_id": "marker-sid",
        "pid": 43210,
        "start_time": 1000.0,
        "mode": row["marker_mode"],
        "created_at": "2026-05-03T00:00:00Z",
    }


def test_decision_table_fixture_has_all_32_combinations() -> None:
    rows = _decision_rows()
    combinations = {
        (row["entrypoint"], row["marker_mode"], row["marker_validity"])
        for row in rows
    }

    assert len(rows) == 32
    assert [row["row"] for row in rows] == list(range(1, 33))
    assert len(combinations) == 32


def test_required_decision_table_contract_api_exists() -> None:
    _require_cleanup_api("decide_cleanup_action")
    _require_cleanup_api("should_stophook_single_shot_fallthrough")
    _require_cleanup_api("filter_stophook_kill_candidates")


@pytest.mark.parametrize("row", _decision_rows(), ids=lambda row: f"row-{row['row']}")
def test_cleanup_decision_table_matches_fixture(row: dict) -> None:
    decide = _cleanup_api_or_skip("decide_cleanup_action")
    actual = decide(
        entrypoint=row["entrypoint"],
        marker=_marker(row),
        marker_validity=row["marker_validity"],
        hook_session_id="marker-sid",
        hook_target_pid=43210,
        hook_process_pid=os.getpid(),
    )

    assert actual["action"] == row["expected_action"]


def test_stophook_single_shot_fallthrough_requires_all_safety_conditions() -> None:
    should_fallthrough = _cleanup_api_or_skip("should_stophook_single_shot_fallthrough")
    marker = {
        "session_id": "hook-sid",
        "pid": 5555,
        "mode": "single-shot",
        "start_time": 1000.0,
    }

    assert should_fallthrough(marker, hook_session_id="hook-sid", hook_target_pid=5555) is True
    assert should_fallthrough(marker, hook_session_id="other-sid", hook_target_pid=5555) is False
    assert should_fallthrough({**marker, "mode": "marathon"}, hook_session_id="hook-sid", hook_target_pid=5555) is False
    assert should_fallthrough(marker, hook_session_id="hook-sid", hook_target_pid=None) is False
    assert should_fallthrough(marker, hook_session_id="hook-sid", hook_target_pid="not-an-int") is False
    assert should_fallthrough(marker, hook_session_id="hook-sid", hook_target_pid=9999) is False


def test_stophook_kill_candidates_exclude_marker_and_hook_pids() -> None:
    filter_candidates = _cleanup_api_or_skip("filter_stophook_kill_candidates")
    hook_pid = os.getpid()
    marker_pid = hook_pid + 1000

    assert filter_candidates([hook_pid, marker_pid, 99999], marker_pid=marker_pid, hook_process_pid=hook_pid) == [99999]
