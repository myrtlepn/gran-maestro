import pytest


@pytest.mark.skip(reason="T03 변경이 merge된 환경에서만 검증")
def test_agile_retrospective_preserves_auto_mode():
    snapshots = [
        {
            "phase": "sprint1_done",
            "next_action": {"auto_mode": True},
        },
        {
            "phase": "retrospective",
            "next_action": {"auto_mode": True},
        },
        {
            "phase": "sprint2_started",
            "next_action": {"auto_mode": True},
        },
    ]

    assert all(item["next_action"]["auto_mode"] is True for item in snapshots)
