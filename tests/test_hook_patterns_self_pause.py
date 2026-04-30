from __future__ import annotations

import pytest

from scripts._hook_patterns import SELF_PAUSE_RE


@pytest.mark.parametrize(
    "message",
    [
        "wakeup 사이클로 다음 Sprint를 재개하겠습니다",
        "wakeup cycle after this sprint",
        "25분 뒤 재개하겠습니다",
        "다음 사이클에 재개하겠습니다",
        "다음 턴에서 재개하겠습니다",
        "자동 재개 경로로 넘기겠습니다",
        "자동 재진입을 예약하겠습니다",
        "wakeup을 사용하겠습니다",
        "wakeup를 호출하겠습니다",
        "ScheduleWakeup을 호출하겠습니다",
        "wakeup 차단 후 종료하겠습니다",
    ],
)
def test_new_patterns(message):
    assert SELF_PAUSE_RE.search(message), message


@pytest.mark.parametrize(
    "message",
    [
        "Sprint boundary에서 stash와 squash 부담 때문에 paused로 전환합니다",
        "새 세션에서 --resume으로 재개 권장",
        "사용자 검토에 자연스러운 지점입니다",
    ],
)
def test_legacy_patterns_preserved(message):
    assert SELF_PAUSE_RE.search(message), message
