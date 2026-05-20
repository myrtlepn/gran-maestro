from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
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
REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
HOOK_PLUGIN_PATH = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOK_CONFIG_PATH = REPO_ROOT / "hooks" / "hooks.json"
DISPATCH_RESULT_KEYS = {
    "agi_id",
    "sprint",
    "status",
    "pln_id",
    "req_id",
    "commit_sha",
    "sprint_kind",
    "exit_code",
    "failure_reason",
    "result_recorded",
    "retrospective_recorded",
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


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_request_fixture(workspace: Path, *, req_id: str, task_num: str) -> Path:
    request_dir = workspace / ".gran-maestro" / "requests" / req_id
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "id": req_id,
                "status": "phase2_execution",
                "current_phase": 2,
                "tasks": [
                    {
                        "id": f"{req_id}-{task_num}",
                        "task_num": task_num,
                        "status": "pending",
                    }
                ],
                "background_task_ids": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return request_path


def _seed_agile_session(workspace: Path, *, agi_id: str) -> Path:
    session_dir = workspace / ".gran-maestro" / "agile" / agi_id
    (session_dir / "sprints").mkdir(parents=True, exist_ok=True)
    (session_dir / "index").mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"id": agi_id}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return session_dir


def _single_trace_file(traces_dir: Path) -> Path:
    traces = sorted(traces_dir.glob("*.md"))
    assert len(traces) == 1, traces
    return traces[0]


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


def test_dod007_hook_canonical_source_uses_plugin_registration_and_repo_hooks_only() -> None:
    plugin_manifest = _read_json(HOOK_PLUGIN_PATH)
    hook_config = _read_json(HOOK_CONFIG_PATH)

    assert plugin_manifest.get("hooks") == "./hooks/hooks.json"

    commands: list[str] = []
    for entries in hook_config.get("hooks", {}).values():
        assert isinstance(entries, list), entries
        for entry in entries:
            hooks = entry.get("hooks")
            assert isinstance(hooks, list), entry
            for hook in hooks:
                command = hook.get("command")
                assert isinstance(command, str) and command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"), hook
                commands.append(command)

    assert commands, hook_config
    assert ".claude/hooks/" not in json.dumps(
        {"plugin_manifest": plugin_manifest, "hook_config": hook_config},
        ensure_ascii=False,
        sort_keys=True,
    )
    for command in commands:
        relative = command.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1]
        assert (REPO_ROOT / relative).exists(), command


def test_dod007_dispatch_compatibility_preserves_completion_log_trace_and_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    req_id = "REQ-913"
    agi_id = "AGI-040"
    pln_id = "PLN-737"
    task_num = "02"
    task_id = "REQ-913-T02"
    attempt_id = "REQ-913-02-A1"

    _seed_request_fixture(workspace, req_id=req_id, task_num=task_num)
    _seed_agile_session(workspace, agi_id=agi_id)

    log_dir = workspace / ".gran-maestro" / "agile" / agi_id / "sprints" / "S07"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_result = _run_mst(
        workspace,
        "run",
        "--task-id",
        task_id,
        "--provider",
        "claude",
        "--model",
        "sonnet",
        "--log-dir",
        str(log_dir),
        "--trace",
        f"{req_id}/{task_id}",
        "--",
        sys.executable,
        "-c",
        "print('status=completed')",
    )
    assert run_result.returncode == 0, run_result.stderr

    state_path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    state_payload = _read_json(state_path)
    assert state_payload["phase"] == "done"
    assert state_payload["task_id"] == task_id

    running_log_path = log_dir / "running.log"
    assert running_log_path.exists(), running_log_path
    running_log = running_log_path.read_text(encoding="utf-8")
    assert any(token in running_log for token in ("status=completed", "phase", "done", "failure")), running_log

    trace_path = _single_trace_file(log_dir / "traces")
    trace_text = trace_path.read_text(encoding="utf-8")
    assert task_id in trace_path.name
    assert f"task_id: {task_id}" in trace_text
    assert f"trace_label: {req_id}/{task_id}" in trace_text
    assert f"running_log_path: {running_log_path}" in trace_text

    record_result = _run_mst(
        workspace,
        "request",
        "record-phase2-dispatch-attempt",
        req_id,
        "--task-num",
        task_num,
        "--task-id",
        task_id,
        "--attempt-id",
        attempt_id,
        "--dispatched-at",
        "2026-05-20T02:16:10Z",
        "--agent",
        "codex-dev",
        "--worktree-path",
        str(workspace),
        "--log-path",
        str(running_log_path),
        "--expected-task-status-before",
        "pending",
        "--status",
        "done",
        "--run-state-path",
        str(state_path),
        "--json",
    )
    assert record_result.returncode == 0, record_result.stderr

    request_payload = _read_json(workspace / ".gran-maestro" / "requests" / req_id / "request.json")
    background_attempt = request_payload["background_task_ids"][0]
    task_attempt = request_payload["tasks"][0]["attempts"][0]
    assert background_attempt["task_id"] == task_id
    assert task_attempt["task_id"] == task_id
    assert task_attempt["task_num"] == task_num
    assert task_attempt["log_path"] == str(running_log_path)
    assert task_attempt["run_state_path"] == str(state_path)

    dispatch_result = _run_mst(
        workspace,
        "agile",
        "dispatch-result",
        agi_id,
        "--sprint",
        "7",
        "--status",
        "success",
        "--exit-code",
        "0",
        "--pln",
        pln_id,
        "--req",
        req_id,
        "--json",
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr

    dispatch_result_path = log_dir / "dispatch-result.json"
    dispatch_payload = _read_json(dispatch_result_path)
    assert set(dispatch_payload) == DISPATCH_RESULT_KEYS
    assert dispatch_payload["status"] == "success"
    assert dispatch_payload["req_id"] == req_id
    assert dispatch_payload["pln_id"] == pln_id


def test_dod007_scope_guard_keeps_dispatch_evidence_inside_existing_surfaces() -> None:
    request_source = (REPO_ROOT / "scripts" / "mst_cmds" / "request.py").read_text(encoding="utf-8")
    request_writer_source = (
        REPO_ROOT / "scripts" / "mst_cmds" / "_common_shards" / "part_001.py"
    ).read_text(encoding="utf-8")
    agile_dispatch_source = (
        REPO_ROOT / "scripts" / "mst_cmds" / "agile_shards" / "part_003.py"
    ).read_text(encoding="utf-8")

    for required_surface in (
        "record-phase2-dispatch-attempt",
        "background_task_ids",
        "attempt_id",
        "dispatch-result.json",
    ):
        assert (
            required_surface in request_source
            or required_surface in request_writer_source
            or required_surface in agile_dispatch_source
        )

    for forbidden_scope in (
        "claude -p /mst:resume",
        "queue drain",
        "queue claim",
        "shell injection",
        "malicious path fixture",
        "parallel worktree isolation",
        "--trace-path",
        "--evidence-id",
    ):
        assert forbidden_scope not in request_source
        assert forbidden_scope not in request_writer_source
        assert forbidden_scope not in agile_dispatch_source
