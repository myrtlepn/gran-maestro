import re

from scripts._skill_state import _normalize_stack, apply_event


ISO_8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")


def test_enter_records_entered_at():
    snapshot = {
        "sessionId": "default",
        "currentSkill": "A",
        "currentStep": 2,
        "totalSteps": 3,
        "enterCount": 1,
        "skillStack": [],
        "status": "active",
    }

    updated = apply_event(snapshot, "enter", skill="B", step=1, total=5)

    assert len(updated["skillStack"]) == 1
    frame = updated["skillStack"][0]
    assert frame["skill"] == "A"
    assert frame["step"] == 2
    assert ISO_8601_UTC_RE.match(frame["enteredAt"])
    assert frame["enteredAt"] == updated["enteredAt"] == updated["updatedAt"]


def test_normalize_stack_backward_compat():
    stack = [
        {"skill": "without-time", "step": 1},
        {"skill": "with-time", "step": 2, "enteredAt": "2026-04-18T10:11:12.000Z"},
        {"skill": "bad-time", "step": 3, "enteredAt": 123},
    ]

    assert _normalize_stack(stack) == [
        {"skill": "without-time", "step": 1},
        {"skill": "with-time", "step": 2, "enteredAt": "2026-04-18T10:11:12.000Z"},
        {"skill": "bad-time", "step": 3},
    ]
