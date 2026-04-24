"""DOD-004 T4: block_count escalation regression tests for _hook_patterns.detect."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._hook_patterns import detect  # noqa: E402


def _detect(last_message: str, block_count: int = 0) -> dict:
    payload = {
        "block_count": block_count,
        "agile_loop_active": True,
        "agile_auto_mode_active": True,
        "agile_guard_active": True,
    }
    return detect(payload, raw_stdin="", last_message=last_message)


def test_first_block_increments_to_1():
    result = _detect("반복 stash 상태로 전환하려 합니다.", block_count=0)
    assert result["decision"] == "block"
    assert "Consecutive block count: 1." in result["reason"]
    assert "[자동 중단]" not in result["reason"]
    assert "Escalate to user for steering." not in result["reason"]


def test_escalation_at_threshold():
    result = _detect("반복 stash 상태로 전환하려 합니다.", block_count=2)
    assert result["decision"] == "block"
    assert "Consecutive block count: 3." in result["reason"]
    assert "[자동 중단]" in result["reason"]
    assert "Escalate to user for steering." in result["reason"]


def test_escalation_persists_above_threshold():
    result = _detect("반복 stash 상태로 전환하려 합니다.", block_count=4)
    assert result["decision"] == "block"
    assert "Consecutive block count: 5." in result["reason"]
    assert "[자동 중단]" in result["reason"]
    assert "Escalate to user for steering." in result["reason"]


def test_escalation_on_agile_text_question_path():
    result = _detect("계속할까요?", block_count=2)
    assert result["decision"] == "block"
    assert "Consecutive block count: 3." in result["reason"]
    assert "[자동 중단]" in result["reason"]
    assert "Escalate to user for steering." in result["reason"]
