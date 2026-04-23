"""REQ-691/T01: _hook_patterns.py helper detection contract tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "_hook_patterns.py"


def _run_helper(stdin_payload: dict, last_message: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "detect",
            "--stdin",
            "--last-message",
            last_message,
        ],
        input=json.dumps(stdin_payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )


def _detect(stdin_payload: dict, last_message: str = "") -> dict:
    result = _run_helper(stdin_payload, last_message)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "helper must emit one JSON line"
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "message",
    [
        "Sprint 3 boundary에서 stash/squash 부담이 커서 paused로 전환하겠습니다",
        "사용자 검토에 자연스러운 지점이므로 새 세션에서 --resume으로 재개 권장",
    ],
)
def test_self_pause_rationalization_positive(message):
    payload = _detect({}, message)

    assert payload["decision"] == "block"
    assert payload["pattern_id"] == "self_pause_rationalization"
    assert "SELF-PAUSE-DETECTED" in payload["reason"]


def test_self_pause_rationalization_negative():
    payload = _detect({}, "Sprint 작업을 계속 진행하고 다음 tool call을 실행합니다")

    assert payload == {
        "decision": "allow",
        "reason": "no_pattern_match",
        "pattern_id": None,
    }


def test_agile_text_question_positive_requires_auto_context():
    payload = _detect(
        {
            "last_assistant_message": "계속할까요?",
            "agile_loop_active": True,
            "agile_auto_mode_active": True,
        }
    )

    assert payload["decision"] == "block"
    assert payload["pattern_id"] == "agile_text_question_in_auto_mode"
    assert "text-based question patterns are blocked" in payload["reason"]


def test_agile_text_question_negative_when_auto_context_absent():
    payload = _detect(
        {
            "last_assistant_message": "계속할까요?",
            "agile_loop_active": False,
            "agile_auto_mode_active": True,
        }
    )

    assert payload["decision"] == "allow"
    assert payload["pattern_id"] is None


def test_agile_allow_missing_marker_positive():
    payload = _detect(
        {
            "last_assistant_message": '{"tool_name":"AskUserQuestion","question":"방향 선택"}',
            "allow_pattern_found": True,
            "agile_guard_active": True,
            "stop_intent_force_block": False,
            "current_skill": "mst:agile",
            "active_req": "REQ-691",
            "next_source": "Sprint 3",
        }
    )

    assert payload["decision"] == "block"
    assert payload["pattern_id"] == "agile_allow_pattern_missing_marker"
    assert "AskUserQuestion is allowed only with agile whitelist markers" in payload["reason"]


def test_agile_allow_missing_marker_negative_with_whitelist_marker():
    payload = _detect(
        {
            "last_assistant_message": (
                "[스티어링 체크포인트]\n"
                '{"tool_name":"AskUserQuestion","question":"방향 선택"}'
            ),
            "allow_pattern_found": True,
            "agile_guard_active": True,
            "stop_intent_force_block": False,
        }
    )

    assert payload["decision"] == "allow"
    assert payload["pattern_id"] is None


def test_pattern_priority_self_pause_wins_over_question():
    payload = _detect(
        {
            "last_assistant_message": (
                "Sprint 3 boundary에서 paused로 전환하겠습니다. 계속할까요?"
            ),
            "agile_loop_active": True,
            "agile_auto_mode_active": True,
        }
    )

    assert payload["decision"] == "block"
    assert payload["pattern_id"] == "self_pause_rationalization"
