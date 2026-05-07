from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from typing import Any


SID = "MST-AGI-031-20260507T010203000Z-dod007aa"
OTHER_SID = "MST-AGI-031-20260507T010204000Z-dod007bb"
SOURCE_HEAD = "a" * 64
CURRENT_HEAD = "b" * 64
BROKEN_HEAD = "c" * 64
EVENT_HASH = "d" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "919191"
RAW_PROMPT_SENTINEL = "RAW_PROMPT_SENTINEL_MUST_NOT_LEAK_DOD007"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD007"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD007"

REQUIRED_AXES = {
    "transition_order",
    "step_bounds",
    "stack_linkage",
    "guard_evidence",
    "history_linkage",
    "projection_freshness",
    "writer_coverage",
    "identity_boundary",
    "current_work_handoff",
    "prompt_correlation",
    "ki001_sprint_close_targeting",
}

TIER_A_AXES = {
    "transition_order",
    "step_bounds",
    "stack_linkage",
    "guard_evidence",
    "history_linkage",
    "projection_freshness",
    "writer_coverage",
}

ALLOWED_STATUS = {"pass", "fail", "unknown"}
DIAGNOSTIC_ONLY_VALUES = {HOOK_UUID, TRANSCRIPT_STEM, OWNER_PID, "legacy-owner-session-dod007"}
FORBIDDEN_PAYLOAD_KEYS = {
    "raw_ledger",
    "raw_ledger_rows",
    "ledger_rows",
    "raw_history",
    "raw_history_rows",
    "history_rows",
    "raw_prompt",
    "raw_prompt_text",
    "full_prompt",
    "full_prompt_text",
    "raw_transcript",
    "transcript_text",
    "llm_summary",
    "semantic_summary",
}


def _health_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.state_machine_health")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-007 state-machine health validator is missing: "
            "expected scripts.mst_cmds.state_machine_health.validate_state_machine_health"
        ) from exc


def _validate(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _health_module()
    fn = getattr(module, "validate_state_machine_health", None)
    assert callable(fn), (
        "scripts.mst_cmds.state_machine_health.validate_state_machine_health "
        "must be callable"
    )
    payload = fn(fixture)
    assert isinstance(payload, dict), "state-machine health validator must return a JSON object"
    return payload


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _axis(payload: dict[str, Any], axis_name: str) -> dict[str, Any]:
    axes = payload.get("axes")
    assert isinstance(axes, list), "health payload must expose axes as a deterministic array"
    matches = [item for item in axes if isinstance(item, dict) and item.get("axis") == axis_name]
    assert len(matches) == 1, f"expected exactly one {axis_name!r} axis result: {axes!r}"
    return matches[0]


def _assert_axis_schema(axis: dict[str, Any]) -> None:
    assert set(axis) >= {"axis", "status", "code", "reason"}, axis
    assert axis["axis"] in REQUIRED_AXES, axis
    assert axis["status"] in ALLOWED_STATUS, axis
    assert isinstance(axis["code"], str) and axis["code"].strip(), axis
    assert isinstance(axis["reason"], str) and axis["reason"].strip(), axis
    assert "evidence_path" in axis or "event_hash" in axis, axis
    if "evidence_path" in axis:
        assert isinstance(axis["evidence_path"], str) and axis["evidence_path"].startswith(".gran-maestro/"), axis
    if "event_hash" in axis:
        assert isinstance(axis["event_hash"], str) and len(axis["event_hash"]) == 64, axis


def _assert_axis(payload: dict[str, Any], axis_name: str, status: str, code: str | set[str]) -> dict[str, Any]:
    axis = _axis(payload, axis_name)
    _assert_axis_schema(axis)
    assert axis["status"] == status, axis
    if isinstance(code, set):
        assert axis["code"] in code, axis
    else:
        assert axis["code"] == code, axis
    return axis


def _assert_no_raw_payload_leak(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert RAW_PROMPT_SENTINEL not in encoded
    assert RAW_TRANSCRIPT_SENTINEL not in encoded
    assert RAW_HISTORY_SENTINEL not in encoded
    assert len(encoded) < 30000

    forbidden_key_hits: list[str] = []
    for path, value in _walk_json(payload):
        if not isinstance(value, dict):
            continue
        for key in value:
            if key in FORBIDDEN_PAYLOAD_KEYS:
                forbidden_key_hits.append(f"{path}.{key}")
    assert not forbidden_key_hits, "raw health payload keys leaked: " + ", ".join(forbidden_key_hits)


def _assert_diagnostic_only_values_are_confined(payload: dict[str, Any]) -> None:
    violations: list[str] = []
    for path, value in _walk_json(payload):
        if value not in DIAGNOSTIC_ONLY_VALUES:
            continue
        if ".legacy_diagnostics" in path or ".diagnostics" in path:
            continue
        violations.append(f"{path} leaked diagnostic-only identity {value!r}")
    assert not violations, "\n".join(violations)


def _event(event_type: str, seq: int, **payload: Any) -> dict[str, Any]:
    event = {
        "event_id": f"evt-{seq:03d}",
        "event_type": event_type,
        "mst_session_id": SID,
        "created_at": f"2026-05-07T01:02:{seq:02d}.000Z",
        "event_hash": f"{seq:064x}"[-64:],
        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
    }
    event.update(payload)
    return event


def _identity_context(*, env_sid: str | None = SID, structured_sid: str | None = SID) -> dict[str, Any]:
    env = {
        "MST_STATE_PPID": OWNER_PID,
        "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias",
    }
    if env_sid is not None:
        env["MST_SESSION_ID"] = env_sid
    context = {
        "session_id": HOOK_UUID,
        "owner_session_id": "legacy-owner-session-dod007",
        "owner_pid": OWNER_PID,
        "transcript_path": f"/tmp/{TRANSCRIPT_STEM}.jsonl",
    }
    if structured_sid is not None:
        context["mst_session_id"] = structured_sid
    return {
        "env": env,
        "context": context,
        "legacy_diagnostics": {
            "hook_session_id": HOOK_UUID,
            "owner_pid": OWNER_PID,
            "hook_transcript_stem": TRANSCRIPT_STEM,
        },
    }


def _snapshot(*, current_step: int = 2, total_steps: int | None = 4, legacy_only: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "mst_session_id": SID,
        "sessionId": SID,
        "root_mst_id": "AGI-031",
        "currentSkill": "mst:request",
        "currentStep": current_step,
        "status": "active",
        "skillStack": [{"skill": "mst:plan", "step": 1}],
        "returnTo": {"skill": "mst:plan", "step": 1},
        "workflow": {
            "current_skill": "mst:request",
            "current_step": current_step,
            "status": "active",
        },
        "history": {"last_event_id": "evt-003", "history_head": SOURCE_HEAD},
        "evidence_path": f".gran-maestro/state/{SID}/snapshot.json",
    }
    if total_steps is not None:
        payload["totalSteps"] = total_steps
        payload["workflow"]["total_steps"] = total_steps
    if legacy_only:
        payload.pop("schema_version")
        payload.pop("mst_session_id")
        payload.pop("workflow")
        payload.pop("history")
        payload["sessionId"] = HOOK_UUID
    return payload


def _writer_rows(*, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    statuses = statuses or ["ok", "not_applicable"]
    return [
        {
            "writer_id": f"writer_{index}",
            "expected": True,
            "observed": status in {"ok", "not_applicable"},
            "status": status,
            "reason": f"writer coverage fixture status {status}",
            "evidence_path": f".gran-maestro/sessions/{SID}/writer-coverage.json",
        }
        for index, status in enumerate(statuses, 1)
    ]


def _base_fixture(**overrides: Any) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "fixture_id": "healthy_reuse_surfaces",
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "identity": _identity_context(),
        "source_surfaces": {
            "execution_flow": "scripts/mst_cmds/execution_flow.py",
            "state": "scripts/mst_cmds/state.py",
            "skill_state": "scripts/_skill_state.py",
            "current_work_handoff": "scripts/mst_cmds/current_work_handoff.py",
            "writer_coverage": "scripts/mst_cmds/writer_coverage.py",
            "prompt_correlation": "scripts/mst_cmds/prompt_correlation.py",
        },
        "events": [
            _event("skill.enter", 1, skill="mst:request", stack_frame_id="frame-1", step=1, total_steps=4),
            _event("skill.step", 2, skill="mst:request", stack_frame_id="frame-1", step=2, total_steps=4),
            _event("skill.exit", 3, skill="mst:request", stack_frame_id="frame-1", status="done"),
            _event("terminal.completed", 4, safe_to_resume=False, paused=False),
        ],
        "snapshot": _snapshot(),
        "guard_outcomes": [
            {
                "event_type": "guard.policy_block",
                "reason": "policy block was observed in bounded timeline",
                "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                "event_hash": EVENT_HASH,
            },
            {
                "event_type": "guard.confirm_requested",
                "reason": "confirmation outcome was recorded",
                "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                "event_hash": EVENT_HASH,
            },
            {
                "event_type": "guard.override_consumed",
                "reason": "override outcome was recorded",
                "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                "event_hash": EVENT_HASH,
            },
        ],
        "history_linkage": {
            "projection_source_head": SOURCE_HEAD,
            "verified_ledger_head": SOURCE_HEAD,
            "snapshot_history_head": SOURCE_HEAD,
            "mirror_head": SOURCE_HEAD,
            "verify_head": SOURCE_HEAD,
            "hash_chain_valid": True,
            "event_hash": EVENT_HASH,
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        "execution_flow_projection": {
            "source_history_head": SOURCE_HEAD,
            "current_verified_head": SOURCE_HEAD,
            "stale": False,
            "regenerate_required": False,
            "evidence_path": f".gran-maestro/sessions/{SID}/execution-flow.json",
        },
        "current_work_handoff": {
            "source_history_head": SOURCE_HEAD,
            "current_history_head": SOURCE_HEAD,
            "safe_to_resume": False,
            "paused": False,
            "next_action": {"action_type": "approve_request", "target": "REQ-828"},
            "continue": {"queued_action": {"action_type": "approve_request", "target": "REQ-828"}},
            "evidence_path": f".gran-maestro/sessions/{SID}/current-work.json",
        },
        "writer_coverage": {
            "source_history_head": SOURCE_HEAD,
            "writers": _writer_rows(),
            "evidence_path": f".gran-maestro/sessions/{SID}/writer-coverage.json",
        },
        "prompt_timeline": {
            "source_head": SOURCE_HEAD,
            "prompt_anchors": {
                "items": [
                    {
                        "event_type": "prompt.submitted",
                        "event_hash": EVENT_HASH,
                        "history_head_before": SOURCE_HEAD,
                        "following_events": {
                            "items": [
                                {
                                    "event_type": "skill.step",
                                    "event_hash": BROKEN_HEAD,
                                    "correlation_range": {"from_seq": 10, "to_seq": 11},
                                    "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                                }
                            ]
                        },
                    }
                ]
            },
            "raw_prompt_text": RAW_PROMPT_SENTINEL,
            "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
            "raw_history_rows": [{"event": {"payload": RAW_HISTORY_SENTINEL}}],
            "evidence_paths": [f".gran-maestro/sessions/{SID}/prompt-timeline.json"],
        },
        "known_issues": [
            {
                "id": "KI-001",
                "status": "observed",
                "cleanup_target": "request_worktree",
                "active_branch": "AGI-031/REQ-828/t01",
                "project_root": "/Users/brandev/mygit/gran-maestro",
                "destructive_cleanup_performed": False,
                "evidence_path": ".gran-maestro/agile/AGI-031/known-issues.json",
            }
        ],
        "raw_history_rows": [{"event": {"payload": RAW_HISTORY_SENTINEL}}],
    }
    fixture.update(overrides)
    return fixture


def test_health_payload_schema_covers_required_axes_with_bounded_evidence() -> None:
    payload = _validate(_base_fixture())

    assert payload.get("schema_version") == 1, payload
    assert payload.get("status") in ALLOWED_STATUS, payload
    emitted_axes = {item.get("axis") for item in payload.get("axes", []) if isinstance(item, dict)}
    assert REQUIRED_AXES <= emitted_axes, emitted_axes
    assert TIER_A_AXES <= emitted_axes, emitted_axes
    for axis_name in sorted(REQUIRED_AXES):
        _assert_axis_schema(_axis(payload, axis_name))
    _assert_no_raw_payload_leak(payload)
    _assert_diagnostic_only_values_are_confined(payload)


def test_transition_order_reports_allowed_exit_after_step_and_terminal_resume_cases() -> None:
    payload = _validate(_base_fixture())
    _assert_axis(payload, "transition_order", "pass", "transition_order_valid")

    exit_after_step = _base_fixture(
        fixture_id="exit_after_step_same_frame",
        events=[
            _event("skill.enter", 1, skill="mst:request", stack_frame_id="frame-1", step=1, total_steps=4),
            _event("skill.exit", 2, skill="mst:request", stack_frame_id="frame-1", status="done"),
            _event("skill.step", 3, skill="mst:request", stack_frame_id="frame-1", step=2, total_steps=4),
        ],
    )
    _assert_axis(_validate(exit_after_step), "transition_order", "fail", "transition_step_after_exit")

    terminal_resume = _base_fixture(
        fixture_id="terminal_resume_safe_continuation",
        events=[
            _event("skill.enter", 1, skill="mst:request", stack_frame_id="frame-1", step=1, total_steps=4),
            _event("terminal.completed", 2, safe_to_resume=True, paused=False),
            _event("continue.queued_action", 3, stack_frame_id="frame-1"),
        ],
        current_work_handoff={
            **_base_fixture()["current_work_handoff"],
            "safe_to_resume": True,
            "next_action": {"action_type": "continue_skill", "target": "REQ-828/T01"},
        },
    )
    _assert_axis(_validate(terminal_resume), "transition_order", "fail", "terminal_resume_safe_continuation")


def test_step_bounds_separates_pass_fail_and_unknown_cases() -> None:
    cases = [
        (_snapshot(current_step=2, total_steps=4), "pass", "step_bounds_valid"),
        (_snapshot(current_step=-1, total_steps=4), "fail", "step_negative"),
        (_snapshot(current_step=5, total_steps=4), "fail", "step_exceeds_total"),
        (_snapshot(current_step=2, total_steps=None), "unknown", "step_total_missing"),
    ]

    for snapshot, status, code in cases:
        payload = _validate(_base_fixture(snapshot=snapshot))
        _assert_axis(payload, "step_bounds", status, code)


def test_stack_linkage_reports_return_to_mismatch_and_legacy_only_snapshot_boundary() -> None:
    _assert_axis(_validate(_base_fixture()), "stack_linkage", "pass", "stack_linkage_valid")

    mismatched = _snapshot()
    mismatched["returnTo"] = {"skill": "mst:other", "step": 3}
    _assert_axis(
        _validate(_base_fixture(fixture_id="stack_return_to_mismatch", snapshot=mismatched)),
        "stack_linkage",
        "fail",
        "stack_return_to_mismatch",
    )

    legacy_only = _validate(_base_fixture(fixture_id="legacy_only_snapshot", snapshot=_snapshot(legacy_only=True)))
    _assert_axis(
        legacy_only,
        "stack_linkage",
        "unknown",
        {"legacy_snapshot_only", "legacy_snapshot_mutation_boundary"},
    )


def test_guard_evidence_requires_reason_and_evidence_for_guard_outcomes() -> None:
    _assert_axis(_validate(_base_fixture()), "guard_evidence", "pass", "guard_evidence_present")

    missing_evidence = _base_fixture(
        fixture_id="guard_outcome_missing_policy_or_writer_evidence",
        guard_outcomes=[
            {
                "event_type": "guard.policy_block",
                "reason": "",
                "evidence_path": "",
                "event_hash": "",
            }
        ],
        writer_coverage={"writers": _writer_rows(statuses=["not_seen"])},
    )
    _assert_axis(_validate(missing_evidence), "guard_evidence", "fail", "guard_evidence_missing")


def test_history_linkage_reports_hash_chain_head_and_mirror_mismatches() -> None:
    _assert_axis(_validate(_base_fixture()), "history_linkage", "pass", "history_linkage_valid")

    broken_chain = _base_fixture(
        fixture_id="history_hash_chain_broken",
        history_linkage={**_base_fixture()["history_linkage"], "hash_chain_valid": False},
    )
    _assert_axis(_validate(broken_chain), "history_linkage", "fail", "history_hash_chain_broken")

    head_mismatch = _base_fixture(
        fixture_id="snapshot_history_head_mismatch",
        history_linkage={**_base_fixture()["history_linkage"], "snapshot_history_head": BROKEN_HEAD},
    )
    _assert_axis(_validate(head_mismatch), "history_linkage", "fail", "history_head_mismatch")

    mirror_mismatch = _base_fixture(
        fixture_id="history_mirror_verify_mismatch",
        history_linkage={**_base_fixture()["history_linkage"], "mirror_head": CURRENT_HEAD},
    )
    _assert_axis(_validate(mirror_mismatch), "history_linkage", "fail", "history_mirror_verify_mismatch")


def test_projection_freshness_accepts_fresh_or_marked_stale_and_fails_unmarked_stale() -> None:
    _assert_axis(_validate(_base_fixture()), "projection_freshness", "pass", "projection_fresh")

    marked_stale = _base_fixture(
        fixture_id="projection_marked_stale",
        execution_flow_projection={
            **_base_fixture()["execution_flow_projection"],
            "source_history_head": SOURCE_HEAD,
            "current_verified_head": CURRENT_HEAD,
            "stale": True,
            "regenerate_required": True,
        },
        current_work_handoff={
            **_base_fixture()["current_work_handoff"],
            "source_history_head": SOURCE_HEAD,
            "current_history_head": CURRENT_HEAD,
            "projection_freshness": {"status": "stale"},
        },
    )
    _assert_axis(_validate(marked_stale), "projection_freshness", "pass", "projection_stale_marked")

    unmarked_stale = _base_fixture(
        fixture_id="projection_source_head_changed_without_stale_marker",
        execution_flow_projection={
            **_base_fixture()["execution_flow_projection"],
            "source_history_head": SOURCE_HEAD,
            "current_verified_head": CURRENT_HEAD,
            "stale": False,
            "regenerate_required": False,
        },
        current_work_handoff={
            **_base_fixture()["current_work_handoff"],
            "source_history_head": SOURCE_HEAD,
            "current_history_head": CURRENT_HEAD,
            "projection_freshness": {"status": "fresh"},
        },
    )
    _assert_axis(_validate(unmarked_stale), "projection_freshness", "fail", "projection_stale_unmarked")


def test_writer_coverage_reuses_dod002_matrix_and_fails_missing_or_invalid_writers() -> None:
    passing = _base_fixture(writer_coverage={"writers": _writer_rows(statuses=["ok", "not_applicable"])})
    _assert_axis(_validate(passing), "writer_coverage", "pass", "writer_coverage_satisfied")

    for status in ("not_seen", "write_failed", "schema_invalid"):
        failing = _base_fixture(writer_coverage={"writers": _writer_rows(statuses=[status])})
        _assert_axis(_validate(failing), "writer_coverage", "fail", f"writer_{status}")


def test_identity_boundary_keeps_canonical_selector_and_diagnostic_conflicts_separate() -> None:
    payload = _validate(_base_fixture())
    _assert_axis(payload, "identity_boundary", "pass", "canonical_identity_valid")

    for field in ("lookup_key", "partition_key", "mutation_selector", "recovery_selector", "repair_source"):
        if field in payload:
            assert payload[field] in {SID, f"state_machine_health:{SID}"}, payload

    conflict = _base_fixture(
        fixture_id="canonical_diagnostic_identity_conflict",
        identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID),
    )
    conflict_payload = _validate(conflict)
    _assert_axis(conflict_payload, "identity_boundary", "fail", "canonical_diagnostic_identity_conflict")
    _assert_diagnostic_only_values_are_confined(conflict_payload)


def test_current_work_handoff_reports_unsafe_resume_paused_continue_and_missing_queued_action() -> None:
    terminal_resume = _base_fixture(
        current_work_handoff={**_base_fixture()["current_work_handoff"], "safe_to_resume": True}
    )
    _assert_axis(_validate(terminal_resume), "current_work_handoff", "fail", "terminal_safe_to_resume_true")

    paused_continue = _base_fixture(
        current_work_handoff={
            **_base_fixture()["current_work_handoff"],
            "paused": True,
            "next_action": {"action_type": "continue_skill", "target": "REQ-828/T01"},
        }
    )
    _assert_axis(_validate(paused_continue), "current_work_handoff", "fail", "paused_continue_mismatch")

    queued_missing = _base_fixture(
        current_work_handoff={
            **_base_fixture()["current_work_handoff"],
            "next_action": {"action_type": "approve_request", "target": "REQ-828"},
            "continue": {"queued_action": {"action_type": "run_request", "target": "REQ-999"}},
        }
    )
    _assert_axis(_validate(queued_missing), "current_work_handoff", "fail", "queued_action_not_reflected")


def test_prompt_correlation_gap_fails_without_leaking_raw_prompt_transcript_or_history() -> None:
    gap = _base_fixture(
        fixture_id="prompt_correlation_gap",
        prompt_timeline={
            **_base_fixture()["prompt_timeline"],
            "prompt_anchors": {
                "items": [
                    {
                        "event_type": "prompt.submitted",
                        "event_hash": EVENT_HASH,
                        "history_head_before": SOURCE_HEAD,
                        "following_events": {"items": []},
                    }
                ]
            },
        },
    )

    payload = _validate(gap)
    _assert_axis(
        payload,
        "prompt_correlation",
        "fail",
        {"prompt_correlation_gap", "prompt_writer_coverage_missing"},
    )
    _assert_no_raw_payload_leak(payload)


def test_ki001_sprint_close_targeting_is_validation_case_not_destructive_cleanup() -> None:
    targeted_root = _base_fixture(
        fixture_id="ki001_sprint_close_targets_project_root_master",
        known_issues=[
            {
                "id": "KI-001",
                "status": "observed",
                "cleanup_target": "project_root",
                "active_branch": "master",
                "project_root": "/Users/brandev/mygit/gran-maestro",
                "destructive_cleanup_performed": False,
                "evidence_path": ".gran-maestro/agile/AGI-031/known-issues.json",
            }
        ],
    )
    payload = _validate(targeted_root)
    axis = _assert_axis(payload, "ki001_sprint_close_targeting", "fail", "ki001_sprint_close_cleanup_target")
    assert axis.get("cleanup_performed") is not True, axis
    assert payload.get("destructive_cleanup_performed") is not True, payload


def test_health_contract_reuses_existing_surfaces_without_dashboard_or_hud_expansion() -> None:
    payload = _validate(_base_fixture())

    surfaces = payload.get("source_surfaces")
    assert isinstance(surfaces, dict), payload
    assert {
        "execution_flow",
        "state",
        "skill_state",
        "current_work_handoff",
        "writer_coverage",
        "prompt_correlation",
    } <= set(surfaces), surfaces
    assert "dashboard_route" not in payload
    assert "dashboard_tab" not in payload
    assert "dashboard_panel" not in payload
    assert "hud_display_model" not in payload
    assert payload.get("requires_new_dashboard_route") is not True
    assert payload.get("requires_new_hud_display_model") is not True


def test_fixture_catalog_keeps_pac15_final_evidence_hooks_verifiable_later() -> None:
    payload = _validate(_base_fixture())

    catalog = payload.get("fixture_catalog")
    assert isinstance(catalog, list) and catalog, payload
    catalog_ids = {item.get("id") for item in catalog if isinstance(item, dict)}
    assert {
        "transition_order",
        "step_bounds",
        "stack_linkage",
        "guard_evidence",
        "history_linkage",
        "projection_freshness",
        "writer_coverage",
        "identity_boundary",
        "current_work_handoff",
        "prompt_correlation",
        "ki001_sprint_close_targeting",
    } <= catalog_ids
    for item in catalog:
        assert isinstance(item, dict), item
        assert item.get("pac") in {f"PAC-{index}" for index in range(1, 16)}, item
        assert isinstance(item.get("evidence_path"), str) and item["evidence_path"].startswith(".gran-maestro/"), item
