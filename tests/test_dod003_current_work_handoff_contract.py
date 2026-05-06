from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from typing import Any


SID = "MST-AGI-031-20260507T010203000Z-dod003aa"
OTHER_SID = "MST-AGI-031-20260507T010204000Z-dod003bb"
SOURCE_HEAD = "a" * 64
STALE_HEAD = "b" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod003"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "919191"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD003"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD003"

REQUIRED_ROOT_FIELDS = {
    "schema_version",
    "mst_session_id",
    "canonical_mst_session_id",
    "generated_at",
    "source_history_head",
    "projection_freshness",
    "active_workflow",
    "current_task_stack",
    "next_action",
    "blockers",
    "legacy_diagnostics",
    "evidence_paths",
}

REQUIRED_STACK_FRAME_FIELDS = {
    "kind",
    "id",
    "title",
    "status",
    "owner",
    "phase",
    "source",
    "evidence_path",
}

REQUIRED_NEXT_ACTION_FIELDS = {
    "action_type",
    "label",
    "target",
    "command_hint",
    "reason",
    "confidence",
    "evidence_path",
}

REQUIRED_BLOCKER_FIELDS = {
    "blocker_type",
    "status",
    "message",
    "evidence_path",
    "recoverable",
    "next_action_type",
}

ALLOWED_FRESHNESS_STATUS = {
    "fresh",
    "stale",
    "identity_mismatch",
    "no_history",
    "unknown",
}

ALLOWED_NEXT_ACTION_TYPE = {
    "continue_skill",
    "resume_workflow",
    "run_request",
    "approve_request",
    "accept_request",
    "resume_agile_sprint",
    "resolve_blocker",
    "wait_for_user",
    "no_action_available",
    "unknown",
}

ALLOWED_BLOCKER_TYPE = {
    "pending_dependency",
    "failed_validation",
    "missing_accept",
    "protected_branch",
    "stale_projection",
    "identity_mismatch",
    "policy_blocked",
    "missing_source",
    "schema_invalid",
    "unknown",
}

EXPECTED_BLOCKER_TYPES = {
    "pending_dependency",
    "failed_validation",
    "missing_accept",
    "stale_projection",
    "identity_mismatch",
    "missing_source",
    "schema_invalid",
}

DIAGNOSTIC_ONLY_VALUES = {
    HOOK_UUID,
    OWNER_SESSION_ID,
    TRANSCRIPT_STEM,
    OWNER_PID,
}

FORBIDDEN_PAYLOAD_KEYS = {
    "raw_ledger",
    "raw_ledger_rows",
    "ledger_rows",
    "raw_history",
    "raw_history_rows",
    "history_rows",
    "raw_transcript",
    "transcript",
    "transcript_text",
    "full_history",
    "full_history_events",
    "full_history_event_payload",
    "full_prompt_text",
}


def _current_work_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.current_work_handoff")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-003 current-work handoff projection module is missing: "
            "expected scripts.mst_cmds.current_work_handoff"
        ) from exc


def _project_current_work_handoff(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _current_work_module()
    fn = getattr(module, "project_current_work_handoff", None)
    assert callable(fn), (
        "scripts.mst_cmds.current_work_handoff.project_current_work_handoff "
        "must be callable"
    )
    payload = fn(fixture)
    assert isinstance(payload, dict), "current-work handoff projection must return a JSON object payload"
    return payload


def _identity_context(*, env_sid: str | None = SID, structured_sid: str | None = SID) -> dict[str, Any]:
    env: dict[str, Any] = {"MST_STATE_PPID": OWNER_PID}
    if env_sid is not None:
        env["MST_SESSION_ID"] = env_sid
    context: dict[str, Any] = {
        "session_id": HOOK_UUID,
        "owner_session_id": OWNER_SESSION_ID,
        "transcript_path": f"/tmp/{TRANSCRIPT_STEM}.jsonl",
    }
    if structured_sid is not None:
        context["mst_session_id"] = structured_sid
    return {
        "env": env,
        "context": context,
        "legacy_diagnostics": {
            "hook_session_id": HOOK_UUID,
            "owner_session_id": OWNER_SESSION_ID,
            "owner_pid": OWNER_PID,
            "hook_transcript_stem": TRANSCRIPT_STEM,
        },
    }


def _task_frame(index: int = 1, *, status: str = "pending") -> dict[str, Any]:
    return {
        "kind": "request_task",
        "id": f"REQ-824/T{index:02d}",
        "title": f"Current-work handoff regression fixture {index}",
        "status": status,
        "owner": "codex-dev",
        "phase": "phase1",
        "source": "request.json",
        "evidence_path": f".gran-maestro/requests/REQ-824/tasks/{index:02d}/spec.md",
    }


def _base_fixture(**overrides: Any) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "generated_at": "2026-05-07T01:03:00.000Z",
        "source_history_head": SOURCE_HEAD,
        "current_history_head": SOURCE_HEAD,
        "identity": _identity_context(),
        "active_workflow": {
            "skill": "mst:request",
            "source_id": "REQ-824",
            "auto": True,
            "status": "active",
            "evidence_path": ".gran-maestro/tmp/mst-state-919191.json",
        },
        "task_sources": [_task_frame()],
        "resume_queue": {
            "skill": "mst:approve",
            "args": "-a REQ-824",
            "source_skill": "mst:request",
            "source_id": "REQ-824",
            "auto": True,
            "evidence_path": ".gran-maestro/queue/current.json",
        },
        "next_action_source": {
            "action_type": "approve_request",
            "label": "Approve REQ-824",
            "target": "REQ-824",
            "command_hint": "/mst:approve -a REQ-824",
            "reason": "request spec is ready and auto_approve is true",
            "confidence": 1.0,
            "evidence_path": ".gran-maestro/requests/REQ-824/request.json",
        },
        "blocker_sources": [],
        "writer_coverage": {
            "source_history_head": SOURCE_HEAD,
            "generated_at": "2026-05-07T01:02:59.000Z",
            "writers": [],
        },
        "raw_history_rows": [
            {
                "seq": index,
                "event": {
                    "event_type": "tool_call",
                    "payload": RAW_HISTORY_SENTINEL,
                },
            }
            for index in range(1, 40)
        ],
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "full_history_event_payload": {"payload": RAW_HISTORY_SENTINEL},
    }
    fixture.update(overrides)
    return fixture


def _scenario_fixture(name: str) -> dict[str, Any]:
    if name == "normal_active_workflow":
        return _base_fixture()
    if name == "stop_continuation":
        return _base_fixture(
            active_workflow={
                "skill": "mst:resume",
                "source_id": "stop-recover",
                "auto": True,
                "status": "active",
                "evidence_path": ".gran-maestro/state/MST-AGI-031/snapshot.json",
            },
            next_action_source={
                "action_type": "continue_skill",
                "label": "Continue request flow",
                "target": "REQ-824/T01",
                "command_hint": "/mst:request (continue from step 2)",
                "reason": "stop hook continuation has a bounded return-to frame",
                "confidence": 0.9,
                "evidence_path": ".gran-maestro/state/MST-AGI-031/snapshot.json",
            },
        )
    if name == "recover_resume":
        return _base_fixture(
            active_workflow={
                "skill": "mst:recover",
                "source_id": "AGI-031",
                "auto": True,
                "status": "active",
                "evidence_path": ".gran-maestro/state/MST-AGI-031/snapshot.json",
            },
            next_action_source={
                "action_type": "resume_workflow",
                "label": "Resume DOD-003 request",
                "target": "REQ-824",
                "command_hint": "/mst:resume --wakeup-hint stop-recover",
                "reason": "recover envelope points at the current request task",
                "confidence": 0.85,
                "evidence_path": ".gran-maestro/state/MST-AGI-031/snapshot.json",
            },
        )
    if name == "context_compaction":
        return _base_fixture(
            active_workflow={
                "skill": "mst:request",
                "source_id": "REQ-824",
                "auto": True,
                "status": "rehydrating",
                "evidence_path": ".gran-maestro/sessions/MST-AGI-031/execution-flow.json",
            },
            execution_flow={
                "last_transition": "context.compacted",
                "current_node": "mst:request.step-2",
                "handoff_summary": {"bounded": True, "raw_history_rows": RAW_HISTORY_SENTINEL},
            },
        )
    if name == "stale_source_head":
        return _base_fixture(current_history_head=STALE_HEAD)
    if name == "identity_mismatch":
        return _base_fixture(identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID))
    if name == "blocker":
        return _base_fixture(
            blocker_sources=[
                {
                    "blocker_type": "pending_dependency",
                    "status": "blocked",
                    "message": "REQ-824/T02 waits for red-first regression",
                    "evidence_path": ".gran-maestro/requests/REQ-824/tasks/02/spec.md",
                    "recoverable": True,
                    "next_action_type": "wait_for_user",
                }
            ]
        )
    if name == "missing_source":
        return _base_fixture(task_sources=[], active_workflow=None, source_history_head=None)
    if name == "schema_invalid":
        return _base_fixture(schema_version=0)
    raise AssertionError(f"unknown fixture: {name}")


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _assert_evidence_path(value: Any, label: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{label} evidence_path must be a non-empty string"
    assert value.startswith(".gran-maestro/"), f"{label} evidence_path must be repo-relative: {value!r}"
    assert RAW_HISTORY_SENTINEL not in value
    assert RAW_TRANSCRIPT_SENTINEL not in value


def _assert_no_raw_payload_leak(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert RAW_HISTORY_SENTINEL not in encoded
    assert RAW_TRANSCRIPT_SENTINEL not in encoded
    assert len(encoded) < 20000

    forbidden_key_hits = []
    for path, value in _walk_json(payload):
        if isinstance(value, dict):
            for key in value:
                if key in FORBIDDEN_PAYLOAD_KEYS:
                    forbidden_key_hits.append(f"{path}.{key}")
    assert not forbidden_key_hits, "raw handoff payload keys leaked: " + ", ".join(forbidden_key_hits)


def _assert_diagnostics_confined(payload: dict[str, Any]) -> None:
    violations: list[str] = []
    for path, value in _walk_json(payload):
        if value not in DIAGNOSTIC_ONLY_VALUES:
            continue
        if ".legacy_diagnostics" in path or ".diagnostics" in path:
            continue
        violations.append(f"{path} leaked diagnostic-only identity {value!r}")
    assert not violations, "\n".join(violations)


def _assert_common_payload_contract(payload: dict[str, Any]) -> None:
    assert REQUIRED_ROOT_FIELDS <= payload.keys(), f"missing root fields: {REQUIRED_ROOT_FIELDS - payload.keys()}"
    assert payload["schema_version"] == 1
    assert payload["mst_session_id"] == SID
    assert payload["canonical_mst_session_id"] == SID
    assert isinstance(payload["generated_at"], str) and payload["generated_at"].strip()
    assert isinstance(payload["legacy_diagnostics"], dict)
    assert isinstance(payload["evidence_paths"], list)
    assert payload["evidence_paths"], "handoff must expose bounded evidence paths"
    for index, path in enumerate(payload["evidence_paths"]):
        _assert_evidence_path(path, f"evidence_paths[{index}]")

    freshness = payload["projection_freshness"]
    assert isinstance(freshness, dict), "projection_freshness must be an object"
    assert freshness.get("status") in ALLOWED_FRESHNESS_STATUS
    assert freshness.get("status") != "dod008_verified"
    assert freshness.get("dod008_verified") is not True
    _assert_evidence_path(freshness.get("evidence_path"), "projection_freshness")

    active_workflow = payload["active_workflow"]
    assert active_workflow is None or isinstance(active_workflow, dict)
    if isinstance(active_workflow, dict):
        _assert_evidence_path(active_workflow.get("evidence_path"), "active_workflow")

    next_action = payload["next_action"]
    assert isinstance(next_action, dict), "next_action must be an object"
    assert REQUIRED_NEXT_ACTION_FIELDS <= next_action.keys()
    assert next_action["action_type"] in ALLOWED_NEXT_ACTION_TYPE
    assert isinstance(next_action["label"], str) and next_action["label"].strip()
    assert isinstance(next_action["target"], str)
    assert isinstance(next_action["command_hint"], str)
    assert isinstance(next_action["reason"], str) and next_action["reason"].strip()
    assert isinstance(next_action["confidence"], (int, float))
    assert 0 <= float(next_action["confidence"]) <= 1
    _assert_evidence_path(next_action["evidence_path"], "next_action")

    blockers = payload["blockers"]
    assert isinstance(blockers, list), "blockers must be a deterministic array"
    for index, blocker in enumerate(blockers):
        assert isinstance(blocker, dict), f"blockers[{index}] must be an object"
        assert REQUIRED_BLOCKER_FIELDS <= blocker.keys()
        assert blocker["blocker_type"] in ALLOWED_BLOCKER_TYPE
        assert isinstance(blocker["status"], str) and blocker["status"].strip()
        assert isinstance(blocker["message"], str) and blocker["message"].strip()
        assert isinstance(blocker["recoverable"], bool)
        assert blocker["next_action_type"] in ALLOWED_NEXT_ACTION_TYPE
        _assert_evidence_path(blocker["evidence_path"], f"blockers[{index}]")

    _assert_no_raw_payload_leak(payload)
    _assert_diagnostics_confined(payload)


def test_selector_uses_only_canonical_mst_session_id_and_confines_diagnostic_values() -> None:
    payload = _project_current_work_handoff(_base_fixture())

    assert payload["mst_session_id"] == SID
    assert payload["canonical_mst_session_id"] == SID
    for field in ("lookup_key", "partition_key", "recovery_selector", "repair_source"):
        if field in payload:
            assert payload[field] in {SID, f"current_work:{SID}"}, f"{field} must not use diagnostic-only identity"
    assert payload["legacy_diagnostics"]["hook_session_id"] == HOOK_UUID
    assert payload["legacy_diagnostics"]["owner_session_id"] == OWNER_SESSION_ID
    assert payload["legacy_diagnostics"]["owner_pid"] == OWNER_PID
    assert payload["legacy_diagnostics"]["hook_transcript_stem"] == TRANSCRIPT_STEM
    _assert_common_payload_contract(payload)


def test_structured_mst_session_id_is_allowed_when_env_mst_session_id_is_absent() -> None:
    payload = _project_current_work_handoff(
        _base_fixture(
            identity=_identity_context(env_sid=None, structured_sid=SID),
            mst_session_id=None,
            canonical_mst_session_id=None,
        )
    )

    assert payload["mst_session_id"] == SID
    assert payload["canonical_mst_session_id"] == SID
    _assert_common_payload_contract(payload)


def test_current_task_stack_frames_have_required_fields_and_bounded_metadata() -> None:
    payload = _project_current_work_handoff(_base_fixture())
    stack = payload["current_task_stack"]

    assert isinstance(stack, dict), "current_task_stack must be an object"
    assert isinstance(stack.get("max_items"), int) and stack["max_items"] > 0
    assert stack["max_items"] <= 20
    assert isinstance(stack.get("truncated"), bool)
    assert isinstance(stack.get("total"), int) and stack["total"] >= 1
    assert isinstance(stack.get("items"), list) and stack["items"]
    assert len(stack["items"]) <= stack["max_items"]

    for index, frame in enumerate(stack["items"]):
        assert isinstance(frame, dict), f"current_task_stack.items[{index}] must be an object"
        assert REQUIRED_STACK_FRAME_FIELDS <= frame.keys(), (
            f"stack frame missing fields: {REQUIRED_STACK_FRAME_FIELDS - frame.keys()}"
        )
        for field in REQUIRED_STACK_FRAME_FIELDS - {"evidence_path"}:
            assert isinstance(frame[field], str) and frame[field].strip(), f"frame.{field} must be non-empty"
        _assert_evidence_path(frame["evidence_path"], f"current_task_stack.items[{index}]")

    _assert_common_payload_contract(payload)


def test_current_task_stack_truncates_without_substituting_raw_history() -> None:
    payload = _project_current_work_handoff(_base_fixture(task_sources=[_task_frame(i) for i in range(1, 35)]))
    stack = payload["current_task_stack"]

    assert stack["max_items"] <= 20
    assert stack["total"] == 34
    assert stack["truncated"] is True
    assert len(stack["items"]) == stack["max_items"]
    _assert_common_payload_contract(payload)


def test_next_action_is_deterministic_object_with_allowed_enum() -> None:
    payload = _project_current_work_handoff(_base_fixture())
    next_action = payload["next_action"]

    assert next_action["action_type"] == "approve_request"
    assert next_action["label"] == "Approve REQ-824"
    assert next_action["target"] == "REQ-824"
    assert next_action["command_hint"] == "/mst:approve -a REQ-824"
    assert next_action["confidence"] == 1.0
    _assert_common_payload_contract(payload)


def test_blockers_are_empty_when_no_blocker_source_exists() -> None:
    payload = _project_current_work_handoff(_base_fixture(blocker_sources=[]))

    assert payload["blockers"] == []
    _assert_common_payload_contract(payload)


def test_blockers_cover_required_non_success_types_with_reason_and_next_action() -> None:
    blocker_sources = [
        {
            "blocker_type": blocker_type,
            "status": "blocked",
            "message": f"{blocker_type} fixture",
            "evidence_path": f".gran-maestro/requests/REQ-824/blockers/{blocker_type}.json",
            "recoverable": blocker_type not in {"schema_invalid"},
            "next_action_type": "resolve_blocker",
        }
        for blocker_type in sorted(EXPECTED_BLOCKER_TYPES)
        if blocker_type not in {"stale_projection", "identity_mismatch", "missing_source", "schema_invalid"}
    ]
    payload = _project_current_work_handoff(_base_fixture(blocker_sources=blocker_sources))
    emitted = {blocker["blocker_type"] for blocker in payload["blockers"]}

    assert {"pending_dependency", "failed_validation", "missing_accept"} <= emitted
    _assert_common_payload_contract(payload)


def test_projection_freshness_statuses_are_deterministic_and_do_not_claim_dod008_completion() -> None:
    cases = {
        "fresh": _base_fixture(),
        "stale": _base_fixture(current_history_head=STALE_HEAD),
        "identity_mismatch": _base_fixture(identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID)),
        "no_history": _base_fixture(source_history_head=None, current_history_head=None),
        "unknown": _base_fixture(current_history_head=None),
    }

    for expected_status, fixture in cases.items():
        payload = _project_current_work_handoff(fixture)
        freshness = payload["projection_freshness"]
        assert freshness["status"] == expected_status
        assert freshness.get("source_history_head") == payload.get("source_history_head")
        assert freshness.get("current_history_head") is None or isinstance(freshness["current_history_head"], str)
        assert freshness.get("dod008_verified") is not True
        _assert_common_payload_contract(payload)


def test_reentry_failure_fixtures_emit_structured_blocker_instead_of_successful_handoff() -> None:
    cases = {
        "stale_source_head": "stale_projection",
        "identity_mismatch": "identity_mismatch",
        "missing_source": "missing_source",
        "schema_invalid": "schema_invalid",
    }

    for fixture_name, expected_blocker_type in cases.items():
        payload = _project_current_work_handoff(_scenario_fixture(fixture_name))
        blockers = payload["blockers"]
        assert any(blocker["blocker_type"] == expected_blocker_type for blocker in blockers), (
            f"{fixture_name} must emit {expected_blocker_type} blocker"
        )
        if expected_blocker_type != "stale_projection":
            assert payload["projection_freshness"]["status"] in {
                expected_blocker_type,
                "identity_mismatch",
                "no_history",
                "unknown",
            }
        _assert_common_payload_contract(payload)


def test_required_normal_stop_recover_compaction_and_error_fixtures_are_bounded() -> None:
    for fixture_name in (
        "normal_active_workflow",
        "stop_continuation",
        "recover_resume",
        "context_compaction",
        "stale_source_head",
        "identity_mismatch",
        "blocker",
        "missing_source",
        "schema_invalid",
    ):
        payload = _project_current_work_handoff(_scenario_fixture(fixture_name))
        assert payload["next_action"]["action_type"] in ALLOWED_NEXT_ACTION_TYPE
        _assert_common_payload_contract(payload)
