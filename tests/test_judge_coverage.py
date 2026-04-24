"""REQ-695/T01 T7: stop-hook judge branch matrix coverage."""

from __future__ import annotations

import pytest

from tests.fixtures.hook_harness import read_flow_detail, run_hook, stdout_json
from tests.fixtures.session_helper import init_project_root, make_session_id
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot


def _hook_payload(session_id: str, hook_event_name: str = "Stop") -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": hook_event_name,
        "last_assistant_message": "현재 단계 종료를 시도합니다.",
    }


def _infer_layer(reason: str) -> str:
    if "no-mst-session" in reason:
        return "snapshot_absent"
    if "return_to" in reason:
        return "snapshot_return_to"
    if "step_progress" in reason:
        return "snapshot_step_progress"
    if "completion" in reason:
        return "snapshot_completion"
    if "non-mst-skill" in reason:
        return "snapshot_namespace"
    if "unhandled_path" in reason:
        return "unhandled_path"
    return "pass_through"


def _build_snapshot_from_kwargs(snapshot_kwargs: dict) -> dict:
    snapshot_kwargs = dict(snapshot_kwargs)
    snapshot_kwargs.pop("payload_overrides", None)
    payload = build_snapshot(
        snapshot_kwargs["skill"],
        snapshot_kwargs["step"],
        snapshot_kwargs["total"],
        return_to=snapshot_kwargs.get("return_to"),
        completed=snapshot_kwargs.get("completed", False),
    )
    if "status" in snapshot_kwargs:
        payload["status"] = snapshot_kwargs["status"]
    return payload


@pytest.mark.parametrize(
    (
        "label",
        "hook_event_name",
        "snapshot_kwargs",
        "return_to",
        "completed",
        "expected_decision",
    ),
    [
        ("mode_on_no_snapshot", "Stop", None, None, False, "allow"),
        ("mode_off_no_snapshot", "Other", None, None, False, "allow"),
        ("mst_step_progress", "Stop", {"skill": "agile-plan", "step": 1, "total": 3}, None, False, "block"),
        (
            "mst_return_to",
            "Stop",
            {"skill": "agile-plan", "step": 3, "total": 5},
            {"skill": "agile-plan", "step": 3},
            False,
            "block",
        ),
        ("mst_committed", "Stop", {"skill": "agile-plan", "step": 3, "total": 3}, None, True, "allow"),
        ("namespace_out", "Stop", {"skill": "external-tool", "step": 1, "total": 2}, None, False, "allow"),
        ("unhandled_active_at_total", "Stop", {"skill": "agile-plan", "step": 3, "total": 3}, None, False, "allow"),
        ("mst_string_return_to", "Stop", {"skill": "mst:request", "step": 2, "total": 2}, "agile/4", False, "block"),
        (
            "mode_off_with_snapshot",
            "Other",
            {
                "skill": "agile-plan",
                "step": 1,
                "total": 3,
                "payload_overrides": {"stop_hook_active": True},
            },
            None,
            False,
            "allow",
        ),
        ("failed_status", "Stop", {"skill": "agile-plan", "step": 3, "total": 3, "status": "failed"}, None, False, "allow"),
        (
            "committed_with_return_to",
            "Stop",
            {"skill": "agile-plan", "step": 3, "total": 3},
            {"skill": "agile-plan", "step": 3},
            True,
            "block",
        ),
        (
            "out_of_namespace_with_return_to",
            "Stop",
            {"skill": "external-tool", "step": 1, "total": 2},
            {"skill": "agile-plan", "step": 3},
            False,
            "allow",
        ),
    ],
)
def test_judge_branch_matrix(
    tmp_path,
    label,
    hook_event_name,
    snapshot_kwargs,
    return_to,
    completed,
    expected_decision,
):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()
    payload_overrides = {}
    if snapshot_kwargs is not None:
        snapshot_kwargs = dict(snapshot_kwargs)
        payload_overrides = snapshot_kwargs.pop("payload_overrides", {})
        if return_to is not None:
            snapshot_kwargs["return_to"] = return_to
        if completed:
            snapshot_kwargs["completed"] = completed
        write_snapshot(
            project_root,
            session_id,
            _build_snapshot_from_kwargs(snapshot_kwargs),
        )

    hook_payload = _hook_payload(session_id, hook_event_name)
    hook_payload.update(payload_overrides)
    result = run_hook(project_root, hook_payload)

    payload = stdout_json(result)
    assert payload["decision"] in {"allow", "block"}
    assert payload["decision"] == expected_decision
    assert _infer_layer(payload["reason"])

    if label == "unhandled_active_at_total":
        assert "unhandled_path" in payload["reason"]
        assert any(
            event.get("event_type") == "unhandled_path"
            for event in read_flow_detail(project_root, session_id)
        )
