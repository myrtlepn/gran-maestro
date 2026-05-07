from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterator
from typing import Any


SID = "MST-AGI-031-20260508T010203000Z-dod008aa"
OTHER_SID = "MST-AGI-031-20260508T010204000Z-dod008bb"
ZERO_HEAD = "0" * 64
OLD_HEAD = "a" * 64
CURRENT_HEAD = "b" * 64
BROKEN_HEAD = "c" * 64
EVENT_HASH = "d" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod008"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "818181"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD008"
RAW_PROMPT_SENTINEL = "RAW_PROMPT_SENTINEL_MUST_NOT_LEAK_DOD008"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD008"
RAW_LEDGER_SENTINEL = "RAW_LEDGER_SENTINEL_MUST_NOT_LEAK_DOD008"
LLM_JUDGEMENT_SENTINEL = "LLM_JUDGEMENT_SENTINEL_MUST_NOT_LEAK_DOD008"

REQUIRED_DETAIL_FIELDS = {
    "panel_id",
    "source_projection",
    "history_integrity",
    "projection_freshness",
    "identity_boundary",
    "source_history_head",
    "current_history_head",
    "verified_history_head",
    "generated_at",
    "evidence_paths",
}

INTEGRITY_STATUS = {"pass", "fail", "unknown", "ok", "mismatch", "stale", "invalid"}
FRESHNESS_STATUS = {"fresh", "stale", "invalid", "unknown", "pass", "fail"}
IDENTITY_STATUS = {"pass", "fail", "invalid", "unknown"}

FORBIDDEN_PAYLOAD_KEYS = {
    "raw_ledger",
    "raw_ledger_rows",
    "ledger_rows",
    "raw_history",
    "raw_history_rows",
    "history_rows",
    "full_history",
    "full_history_events",
    "full_history_payload",
    "full_history_event_payload",
    "raw_prompt",
    "raw_prompt_text",
    "full_prompt",
    "full_prompt_text",
    "prompt_text",
    "raw_transcript",
    "raw_transcript_content",
    "transcript",
    "transcript_text",
    "llm_judgement",
    "llm_judgment",
    "llm_summary",
    "semantic_summary",
    "generated_summary",
}

DIAGNOSTIC_ONLY_VALUES = {
    HOOK_UUID,
    OWNER_SESSION_ID,
    TRANSCRIPT_STEM,
    OWNER_PID,
}


def _session_debug_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.session_debug")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-008 must reuse Session Debug: expected scripts.mst_cmds.session_debug"
        ) from exc


def _current_work_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.current_work_handoff")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-008 must reuse current-work handoff: expected scripts.mst_cmds.current_work_handoff"
        ) from exc


def _health_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.state_machine_health")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-008 must reuse DOD-007 health validation: expected scripts.mst_cmds.state_machine_health"
        ) from exc


def _project_session_debug(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _session_debug_module()
    fn = getattr(module, "project_session_debug_dashboard", None)
    assert callable(fn), "project_session_debug_dashboard must remain callable"
    payload = fn({**fixture, "selected_panel_id": "integrity_freshness"})
    assert isinstance(payload, dict), "Session Debug projection must return a JSON object"
    return payload


def _integrity_detail(fixture: dict[str, Any]) -> dict[str, Any]:
    payload = _project_session_debug(fixture)
    detail = payload.get("selected_detail")
    assert isinstance(detail, dict), "integrity_freshness selected_detail must be an object"
    assert detail.get("panel_id") == "integrity_freshness", detail
    return detail


def _project_current_work(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _current_work_module()
    fn = getattr(module, "project_current_work_handoff", None)
    assert callable(fn), "project_current_work_handoff must remain callable"
    payload = fn(fixture)
    assert isinstance(payload, dict), "current-work handoff must return a JSON object"
    return payload


def _validate_health(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _health_module()
    fn = getattr(module, "validate_state_machine_health", None)
    assert callable(fn), "validate_state_machine_health must remain callable"
    payload = fn(fixture)
    assert isinstance(payload, dict), "state-machine health must return a JSON object"
    return payload


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _canonical_history_event(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _history_event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_history_event(event)).encode("utf-8")).hexdigest()


def _event(seq: int, event_type: str, **overrides: Any) -> dict[str, Any]:
    event = {
        "schema_version": 1,
        "event_id": f"evt-{seq:03d}",
        "idempotency_key": f"{SID}:{event_type}:{seq}",
        "event_type": event_type,
        "type": event_type,
        "mst_session_id": SID,
        "root_mst_id": "AGI-031",
        "artifact_id": "REQ-832/T01",
        "created_at": f"2026-05-08T01:02:{seq:02d}.000Z",
    }
    event.update(overrides)
    return event


def _ledger_rows(*, corrupt: str | None = None) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    prev_hash = ZERO_HEAD
    for seq, event_type in enumerate(("skill.enter", "skill.step", "terminal.completed"), 1):
        event = _event(seq, event_type)
        event_hash = _history_event_hash(prev_hash, event)
        row = {
            "seq": seq,
            "prev_hash": prev_hash,
            "event_hash": event_hash,
            "event": event,
            "mst_session_id": SID,
            "timestamp": event["created_at"],
        }
        rows.append(row)
        prev_hash = event_hash

    if corrupt == "prev_hash":
        rows[1] = {**rows[1], "prev_hash": BROKEN_HEAD}
    elif corrupt == "event_hash":
        rows[1] = {**rows[1], "event_hash": BROKEN_HEAD}
    return rows, rows[-1]["event_hash"]


def _identity_context(*, env_sid: str | None = SID, structured_sid: str | None = SID) -> dict[str, Any]:
    env: dict[str, Any] = {
        "MST_STATE_PPID": OWNER_PID,
        "MST_SNAPSHOT_SESSION_ID": "legacy-snapshot-alias-dod008",
    }
    if env_sid is not None:
        env["MST_SESSION_ID"] = env_sid
    context: dict[str, Any] = {
        "session_id": HOOK_UUID,
        "owner_session_id": OWNER_SESSION_ID,
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
            "owner_session_id": OWNER_SESSION_ID,
            "owner_pid": OWNER_PID,
            "hook_transcript_stem": TRANSCRIPT_STEM,
        },
    }


def _task_frame() -> dict[str, Any]:
    return {
        "kind": "request_task",
        "id": "REQ-832/T01",
        "title": "DOD-008 red-first contract tests",
        "status": "active",
        "owner": "codex-dev",
        "phase": "red-first",
        "source": "spec.md",
        "evidence_path": ".gran-maestro/requests/REQ-832/tasks/01/spec.md",
    }


def _base_fixture(**overrides: Any) -> dict[str, Any]:
    rows, head = _ledger_rows()
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "fixture_id": "dod008_valid_history_integrity_freshness",
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "generated_at": "2026-05-08T01:03:00.000Z",
        "source_history_head": head,
        "current_history_head": head,
        "current_verified_head": head,
        "verified_history_head": head,
        "history_head_evidence_path": f".gran-maestro/sessions/{SID}/history.head",
        "identity": _identity_context(),
        "history_ledger": {
            "ledger_path": f".gran-maestro/sessions/{SID}/history.ndjson",
            "rows": rows,
            "verified_ledger_head": head,
            "sidecar_head": head,
            "mirror_head": head,
            "policy_mirror_head": head,
            "verify_head": head,
            "verify_seq": len(rows),
            "evidence_path": f".gran-maestro/sessions/{SID}/history.verify",
        },
        "history_linkage": {
            "projection_source_head": head,
            "verified_ledger_head": head,
            "snapshot_history_head": head,
            "sidecar_head": head,
            "mirror_head": head,
            "policy_mirror_head": head,
            "verify_head": head,
            "hash_chain_valid": True,
            "event_hash": head,
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        "execution_flow_projection": {
            "source_history_head": head,
            "current_verified_head": head,
            "generated_at": "2026-05-08T01:02:59.000Z",
            "stale": False,
            "regenerate_required": False,
            "evidence_path": f".gran-maestro/sessions/{SID}/execution-flow.json",
        },
        "active_workflow": {
            "skill": "mst:request",
            "source_id": "REQ-832",
            "auto": True,
            "status": "active",
            "evidence_path": ".gran-maestro/requests/REQ-832/tasks/01/spec.md",
        },
        "task_sources": [_task_frame()],
        "next_action_source": {
            "action_type": "continue_skill",
            "label": "Continue DOD-008 red-first tests",
            "target": "REQ-832/T01",
            "command_hint": "/mst:request --plan PLN-660 -a",
            "reason": "contract test task is active",
            "confidence": 1.0,
            "evidence_path": ".gran-maestro/requests/REQ-832/tasks/01/spec.md",
        },
        "blocker_sources": [],
        "writer_coverage": {
            "source_history_head": head,
            "generated_at": "2026-05-08T01:02:58.000Z",
            "writers": [
                {
                    "writer_id": "cli_invocation",
                    "expected": True,
                    "observed": True,
                    "status": "ok",
                    "reason": "bounded fixture writer observed",
                    "evidence_path": f".gran-maestro/sessions/{SID}/writer-coverage.json",
                }
            ],
            "evidence_path": f".gran-maestro/sessions/{SID}/writer-coverage.json",
        },
        "prompt_timeline": {
            "source_head": head,
            "prompt_anchors": {
                "total": 1,
                "items": [
                    {
                        "event_type": "prompt.submitted",
                        "prompt_digest": "sha256:" + ("e" * 64),
                        "event_hash": EVENT_HASH,
                        "history_head_before": OLD_HEAD,
                        "following_events": {
                            "items": [
                                {
                                    "event_type": "skill.step",
                                    "event_hash": head,
                                    "correlation_range": {"from_seq": 1, "to_seq": 3},
                                    "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                                }
                            ]
                        },
                    }
                ],
            },
            "evidence_paths": [f".gran-maestro/sessions/{SID}/prompt-timeline.json"],
        },
        "policy_blocks": [],
        "raw_history_rows": [{"seq": 99, "event": {"payload": RAW_HISTORY_SENTINEL}}],
        "raw_ledger_rows": [{"seq": 100, "event": {"payload": RAW_LEDGER_SENTINEL}}],
        "raw_prompt_text": RAW_PROMPT_SENTINEL,
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "llm_judgement": LLM_JUDGEMENT_SENTINEL,
    }
    fixture.update(overrides)
    return fixture


def _with_ledger(**overrides: Any) -> dict[str, Any]:
    fixture = _base_fixture()
    ledger = {**fixture["history_ledger"], **overrides}
    linkage = {
        **fixture["history_linkage"],
        "verified_ledger_head": ledger.get("verified_ledger_head"),
        "sidecar_head": ledger.get("sidecar_head"),
        "mirror_head": ledger.get("mirror_head"),
        "policy_mirror_head": ledger.get("policy_mirror_head"),
        "verify_head": ledger.get("verify_head"),
    }
    return _base_fixture(history_ledger=ledger, history_linkage=linkage)


def _corrupt_ledger(kind: str) -> dict[str, Any]:
    rows, head = _ledger_rows(corrupt=kind)
    return _with_ledger(
        rows=rows,
        verified_ledger_head=head,
        sidecar_head=head,
        mirror_head=head,
        policy_mirror_head=head,
        verify_head=head,
    )


def _assert_evidence(value: Any, label: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{label} evidence_path must be a non-empty string"
    assert value.startswith(".gran-maestro/"), f"{label} evidence_path must be repo-relative: {value!r}"


def _assert_result_schema(result: dict[str, Any], *, allowed_status: set[str], label: str) -> None:
    assert set(result) >= {"status", "code", "reason"}, result
    assert result["status"] in allowed_status, result
    assert isinstance(result["code"], str) and result["code"].strip(), result
    assert isinstance(result["reason"], str) and result["reason"].strip(), result
    assert "evidence_path" in result or "event_hash" in result, result
    if "evidence_path" in result:
        _assert_evidence(result["evidence_path"], label)
    if "event_hash" in result:
        assert isinstance(result["event_hash"], str) and len(result["event_hash"]) == 64, result


def _assert_detail_schema(detail: dict[str, Any]) -> None:
    assert REQUIRED_DETAIL_FIELDS <= detail.keys(), f"missing DOD-008 detail fields: {REQUIRED_DETAIL_FIELDS - detail.keys()}"
    assert detail["panel_id"] == "integrity_freshness"
    assert detail["source_projection"] == "DOD-008"
    assert isinstance(detail["verified_history_head"], str) and len(detail["verified_history_head"]) == 64
    assert isinstance(detail["generated_at"], str) and detail["generated_at"].strip()
    assert isinstance(detail["evidence_paths"], list) and detail["evidence_paths"], detail
    for index, path in enumerate(detail["evidence_paths"]):
        _assert_evidence(path, f"evidence_paths[{index}]")

    history_integrity = detail["history_integrity"]
    projection_freshness = detail["projection_freshness"]
    identity_boundary = detail["identity_boundary"]
    assert isinstance(history_integrity, dict), "history_integrity must be a bounded object"
    assert isinstance(projection_freshness, dict), "projection_freshness must be a bounded object"
    assert isinstance(identity_boundary, dict), "identity_boundary must be a bounded object"
    _assert_result_schema(history_integrity, allowed_status=INTEGRITY_STATUS, label="history_integrity")
    _assert_result_schema(projection_freshness, allowed_status=FRESHNESS_STATUS, label="projection_freshness")
    _assert_result_schema(identity_boundary, allowed_status=IDENTITY_STATUS, label="identity_boundary")


def _assert_no_raw_payload_leak(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for sentinel in (
        RAW_HISTORY_SENTINEL,
        RAW_PROMPT_SENTINEL,
        RAW_TRANSCRIPT_SENTINEL,
        RAW_LEDGER_SENTINEL,
        LLM_JUDGEMENT_SENTINEL,
    ):
        assert sentinel not in encoded
    assert len(encoded) < 30000

    forbidden_hits: list[str] = []
    for path, value in _walk_json(payload):
        if not isinstance(value, dict):
            continue
        for key in value:
            if key in FORBIDDEN_PAYLOAD_KEYS:
                forbidden_hits.append(f"{path}.{key}")
    assert not forbidden_hits, "raw DOD-008 payload keys leaked: " + ", ".join(forbidden_hits)


def _assert_diagnostic_only_values_confined(payload: dict[str, Any]) -> None:
    violations: list[str] = []
    for path, value in _walk_json(payload):
        if value not in DIAGNOSTIC_ONLY_VALUES:
            continue
        if ".legacy_diagnostics" in path or ".diagnostics" in path or ".diagnostic_only_identifiers" in path:
            continue
        violations.append(f"{path} leaked diagnostic-only identity {value!r}")
    assert not violations, "\n".join(violations)


def _health_axis(payload: dict[str, Any], axis_name: str) -> dict[str, Any]:
    axes = payload.get("axes")
    assert isinstance(axes, list), "health payload must expose axes as a deterministic array"
    matches = [item for item in axes if isinstance(item, dict) and item.get("axis") == axis_name]
    assert len(matches) == 1, f"expected exactly one {axis_name!r} axis result"
    return matches[0]


def test_dod008_integrity_freshness_detail_has_bounded_schema_for_valid_chain() -> None:
    detail = _integrity_detail(_base_fixture())

    _assert_detail_schema(detail)
    assert detail["history_integrity"]["status"] in {"pass", "ok"}, detail
    assert detail["history_integrity"]["code"] in {"history_integrity_valid", "history_linkage_valid"}, detail
    assert detail["history_integrity"].get("verified_history_head") == detail["verified_history_head"]
    assert detail["projection_freshness"]["status"] in {"pass", "fresh"}, detail
    assert detail["projection_freshness"]["code"] == "projection_fresh", detail
    assert detail["projection_freshness"].get("source_history_head") == detail["source_history_head"]
    assert detail["projection_freshness"].get("current_history_head") == detail["current_history_head"]
    _assert_no_raw_payload_leak(detail)


def test_corrupt_hash_chain_is_invalid_without_raw_ledger_rows() -> None:
    for fixture in (_corrupt_ledger("prev_hash"), _corrupt_ledger("event_hash")):
        detail = _integrity_detail(fixture)
        _assert_detail_schema(detail)
        integrity = detail["history_integrity"]
        assert integrity["status"] in {"fail", "invalid"}, integrity
        assert integrity["code"] in {
            "history_hash_chain_broken",
            "history_prev_hash_mismatch",
            "history_event_hash_mismatch",
        }, integrity
        assert "corrupt" in integrity["reason"].lower() or "hash" in integrity["reason"].lower(), integrity
        _assert_no_raw_payload_leak(detail)


def test_sidecar_mirror_policy_and_verify_head_mismatches_are_distinct_from_corruption() -> None:
    cases = {
        "history_sidecar_head_mismatch": _with_ledger(sidecar_head=BROKEN_HEAD),
        "history_mirror_head_mismatch": _with_ledger(mirror_head=BROKEN_HEAD),
        "history_policy_mirror_head_mismatch": _with_ledger(policy_mirror_head=BROKEN_HEAD),
        "history_verify_head_mismatch": _with_ledger(verify_head=BROKEN_HEAD),
    }

    for expected_code, fixture in cases.items():
        detail = _integrity_detail(fixture)
        _assert_detail_schema(detail)
        integrity = detail["history_integrity"]
        assert integrity["status"] in {"fail", "mismatch", "stale"}, integrity
        assert integrity["code"] == expected_code, integrity
        assert integrity["code"] != "history_hash_chain_broken", integrity
        assert integrity.get("verified_history_head") == detail["verified_history_head"]
        _assert_no_raw_payload_leak(detail)


def test_missing_ledger_sidecar_verify_and_legacy_snapshot_only_are_unknown_not_fail() -> None:
    cases = {
        "history_ledger_missing": _base_fixture(history_ledger=None, history_linkage={}),
        "history_sidecar_missing": _with_ledger(sidecar_head=None),
        "history_verify_missing": _with_ledger(verify_head=None),
        "legacy_snapshot_only": _base_fixture(
            schema_version=1,
            history_ledger=None,
            history_linkage={},
            source_history_head=None,
            current_history_head=None,
            snapshot={"sessionId": HOOK_UUID, "history": {"last_event_id": OLD_HEAD}},
        ),
    }

    for expected_code, fixture in cases.items():
        detail = _integrity_detail(fixture)
        _assert_detail_schema(detail)
        integrity = detail["history_integrity"]
        assert integrity["status"] == "unknown", integrity
        assert integrity["code"] == expected_code, integrity
        assert "missing" in integrity["reason"].lower() or "legacy" in integrity["reason"].lower(), integrity
        _assert_no_raw_payload_leak(detail)


def test_projection_freshness_reports_fresh_stale_and_missing_metadata_deterministically() -> None:
    rows, current_head = _ledger_rows()
    stale_fixture = _base_fixture(
        source_history_head=OLD_HEAD,
        current_history_head=current_head,
        current_verified_head=current_head,
        verified_history_head=current_head,
        history_ledger={**_base_fixture()["history_ledger"], "rows": rows, "verified_ledger_head": current_head},
        execution_flow_projection={
            **_base_fixture()["execution_flow_projection"],
            "source_history_head": OLD_HEAD,
            "current_verified_head": current_head,
            "generated_at": "2026-05-08T01:01:00.000Z",
            "stale": False,
            "regenerate_required": False,
        },
    )
    cases = {
        "projection_fresh": (_base_fixture(), {"pass", "fresh"}),
        "projection_stale": (stale_fixture, {"stale", "invalid", "fail"}),
        "projection_generated_at_missing": (_base_fixture(generated_at=None), {"unknown"}),
        "projection_source_history_head_missing": (_base_fixture(source_history_head=None), {"unknown"}),
    }

    for expected_code, (fixture, statuses) in cases.items():
        detail = _integrity_detail(fixture)
        _assert_detail_schema(detail)
        freshness = detail["projection_freshness"]
        assert freshness["status"] in statuses, freshness
        assert freshness["code"] == expected_code, freshness
        _assert_no_raw_payload_leak(detail)


def test_identity_mismatch_is_separate_and_legacy_ids_are_not_fallback_selectors() -> None:
    fixture = _base_fixture(identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID))
    detail = _integrity_detail(fixture)

    _assert_detail_schema(detail)
    identity = detail["identity_boundary"]
    assert identity["status"] in {"fail", "invalid"}, identity
    assert identity["code"] in {"canonical_mst_session_id_mismatch", "canonical_identity_mismatch"}, identity
    assert detail["history_integrity"]["code"] != identity["code"], detail
    assert detail["projection_freshness"]["code"] != identity["code"], detail
    for field in ("lookup_key", "partition_key", "repair_source", "recovery_selector", "fallback_identity"):
        if field in detail:
            assert detail[field] not in DIAGNOSTIC_ONLY_VALUES, detail
        if field in identity:
            assert identity[field] not in DIAGNOSTIC_ONLY_VALUES, identity
    _assert_diagnostic_only_values_confined(detail)
    _assert_no_raw_payload_leak(detail)


def test_current_work_and_session_debug_use_same_projection_source_head_basis() -> None:
    fixture = _base_fixture()
    current_work = _project_current_work(fixture)
    detail = _integrity_detail(fixture)

    _assert_detail_schema(detail)
    current_freshness = current_work["projection_freshness"]
    debug_freshness = detail["projection_freshness"]
    assert debug_freshness["source_history_head"] == current_freshness["source_history_head"]
    assert debug_freshness["current_history_head"] == current_freshness["current_history_head"]
    assert detail["source_history_head"] == current_freshness["source_history_head"]
    assert detail["current_history_head"] == current_freshness["current_history_head"]
    assert debug_freshness.get("basis") == "verified_ledger_head"
    _assert_no_raw_payload_leak({"current_work": current_work, "detail": detail})


def test_dod007_health_axes_share_dod008_head_and_evidence_basis() -> None:
    fixture = _base_fixture()
    detail = _integrity_detail(fixture)
    health = _validate_health(fixture)

    _assert_detail_schema(detail)
    history_axis = _health_axis(health, "history_linkage")
    freshness_axis = _health_axis(health, "projection_freshness")
    for axis in (history_axis, freshness_axis):
        assert axis.get("dod008_evidence"), axis
        evidence = axis["dod008_evidence"]
        assert isinstance(evidence, dict), evidence
        assert evidence.get("verified_history_head") == detail["verified_history_head"], evidence
        assert evidence.get("source_history_head") == detail["source_history_head"], evidence
        assert evidence.get("current_history_head") == detail["current_history_head"], evidence
        assert "evidence_path" in evidence or "event_hash" in evidence, evidence
    assert history_axis["event_hash"] == detail["history_integrity"].get("event_hash")
    assert freshness_axis["evidence_path"] == detail["projection_freshness"].get("evidence_path")
    _assert_no_raw_payload_leak(health)


def test_existing_debug_and_hud_boundaries_are_reused_without_new_surfaces() -> None:
    payload = _project_session_debug(_base_fixture())
    panel_ids = [item.get("id") for item in payload.get("panels", []) if isinstance(item, dict)]

    assert panel_ids == [
        "summary",
        "identity",
        "prompt_timeline",
        "current_work",
        "execution_flow",
        "writer_coverage",
        "integrity_freshness",
        "policy_block",
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).lower()
    assert "dashboard_route" not in payload
    assert "dashboard_tab" not in payload
    assert "hud_display_model" not in payload
    assert '"hud"' not in encoded
    assert '"statusline"' not in encoded
    _assert_no_raw_payload_leak(payload)


def test_raw_history_prompt_transcript_full_ledger_and_llm_judgement_are_excluded() -> None:
    detail = _integrity_detail(_base_fixture())

    _assert_detail_schema(detail)
    _assert_no_raw_payload_leak(detail)
    encoded = json.dumps(detail, sort_keys=True, separators=(",", ":")).lower()
    assert "llm" not in encoded
    assert "judgement" not in encoded
    assert "judgment" not in encoded
