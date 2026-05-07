from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from typing import Any

from scripts.mst_cmds.current_work_handoff import project_current_work_handoff


SID = "MST-AGI-031-20260507T020304000Z-dod006aa"
OTHER_SID = "MST-AGI-031-20260507T020305000Z-dod006bb"
ROOT_ID = "AGI-031"
SOURCE_HEAD = "a" * 64
STALE_HEAD = "b" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod006"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "626262"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD006"
RAW_PROMPT_SENTINEL = "RAW_PROMPT_SENTINEL_MUST_NOT_LEAK_DOD006"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD006"
LLM_SUMMARY_SENTINEL = "LLM_SUMMARY_SENTINEL_MUST_NOT_LEAK_DOD006"

ALLOWED_ROOT_FIELDS = {
    "schema_version",
    "generated_at",
    "mst_session_id",
    "root_id",
    "current_skill",
    "current_step",
    "total_steps",
    "stack_depth",
    "next_action",
    "blocker",
    "source_head",
    "projection_freshness",
    "compact_text",
    "evidence_paths",
    "truncated",
    "reason",
}

ALLOWED_FRESHNESS_STATUS = {
    "fresh",
    "stale",
    "identity_mismatch",
    "no_history",
    "unknown",
}

FORBIDDEN_PAYLOAD_KEYS = {
    "active_workflow",
    "current_task_stack",
    "blockers",
    "legacy_diagnostics",
    "lookup_key",
    "partition_key",
    "recovery_selector",
    "session_debug",
    "session_debug_payload",
    "debug_dashboard",
    "browser_detail",
    "raw_ledger",
    "raw_ledger_rows",
    "ledger_rows",
    "raw_history",
    "raw_history_rows",
    "history_rows",
    "full_history",
    "full_history_events",
    "full_history_event_payload",
    "raw_prompt",
    "raw_prompt_text",
    "full_prompt",
    "full_prompt_text",
    "prompt_text",
    "raw_transcript",
    "raw_transcript_content",
    "transcript_text",
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


def _compact_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.hud_statusline_compact")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-006 compact projection module is missing: "
            "expected scripts.mst_cmds.hud_statusline_compact"
        ) from exc


def _project_compact(source: dict[str, Any] | None) -> dict[str, Any]:
    module = _compact_module()
    fn = getattr(module, "project_hud_statusline_compact", None)
    assert callable(fn), (
        "scripts.mst_cmds.hud_statusline_compact.project_hud_statusline_compact "
        "must be callable"
    )
    payload = fn(source, generated_at="2026-05-07T02:04:00Z")
    assert isinstance(payload, dict), "DOD-006 compact projection must return a JSON object"
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


def _task_frame(index: int = 1, *, title: str | None = None) -> dict[str, Any]:
    return {
        "kind": "request_task",
        "id": f"REQ-827/T{index:02d}",
        "title": title or f"HUD statusline compact contract fixture {index}",
        "status": "active" if index == 1 else "pending",
        "owner": "codex-dev",
        "phase": "red-first",
        "source": "spec.md",
        "evidence_path": f".gran-maestro/requests/REQ-827/tasks/{index:02d}/spec.md",
    }


def _source_fixture(**overrides: Any) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "generated_at": "2026-05-07T02:03:59Z",
        "source_history_head": SOURCE_HEAD,
        "current_history_head": SOURCE_HEAD,
        "identity": _identity_context(),
        "active_workflow": {
            "skill": "mst:request",
            "source_id": "REQ-827",
            "auto": True,
            "status": "active",
            "current_step": 2,
            "total_steps": 5,
            "evidence_path": ".gran-maestro/requests/REQ-827/tasks/01/spec.md",
        },
        "task_sources": [_task_frame(index) for index in range(1, 4)],
        "next_action_source": {
            "action_type": "approve_request",
            "label": "Approve REQ-827",
            "target": "REQ-827",
            "command_hint": "/mst:approve -a REQ-827",
            "reason": "DOD-006 compact red-first contract is ready",
            "confidence": 1.0,
            "evidence_path": ".gran-maestro/requests/REQ-827/request.json",
        },
        "blocker_sources": [],
        "raw_history_rows": [{"payload": RAW_HISTORY_SENTINEL}],
        "raw_prompt_text": RAW_PROMPT_SENTINEL,
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "llm_summary": LLM_SUMMARY_SENTINEL,
    }
    fixture.update(overrides)
    return fixture


def _current_work_projection(**overrides: Any) -> dict[str, Any]:
    projection = dict(project_current_work_handoff(_source_fixture(**overrides)))
    projection["root_id"] = ROOT_ID
    workflow = projection.get("active_workflow")
    if isinstance(workflow, dict):
        projection["current_step"] = workflow.get("current_step", 2)
        projection["total_steps"] = workflow.get("total_steps", 5)
    projection["session_debug_payload"] = {
        "panel_id": "hud",
        "raw_prompt_text": RAW_PROMPT_SENTINEL,
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "llm_summary": LLM_SUMMARY_SENTINEL,
    }
    return projection


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _max_depth(value: Any) -> int:
    if isinstance(value, dict):
        if not value:
            return 1
        return 1 + max(_max_depth(child) for child in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(_max_depth(child) for child in value)
    return 0


def _assert_no_forbidden_payload(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for sentinel in (
        RAW_HISTORY_SENTINEL,
        RAW_PROMPT_SENTINEL,
        RAW_TRANSCRIPT_SENTINEL,
        LLM_SUMMARY_SENTINEL,
    ):
        assert sentinel not in encoded
    for diagnostic_value in DIAGNOSTIC_ONLY_VALUES:
        assert diagnostic_value not in encoded

    forbidden_hits: list[str] = []
    for path, value in _walk_json(payload):
        if isinstance(value, dict):
            for key in value:
                if key in FORBIDDEN_PAYLOAD_KEYS:
                    forbidden_hits.append(f"{path}.{key}")
    assert not forbidden_hits, "forbidden compact payload keys leaked: " + ", ".join(forbidden_hits)


def _assert_common_compact_contract(payload: dict[str, Any]) -> None:
    assert set(payload) == ALLOWED_ROOT_FIELDS
    assert payload["schema_version"] == 1
    assert payload["mst_session_id"] == SID or payload["mst_session_id"] in {"unknown", OTHER_SID}
    assert payload["projection_freshness"] in ALLOWED_FRESHNESS_STATUS
    assert isinstance(payload["stack_depth"], int) and payload["stack_depth"] >= 0
    assert isinstance(payload["compact_text"], str) and payload["compact_text"].startswith("MST ")
    assert len(payload["compact_text"]) <= 160
    assert isinstance(payload["evidence_paths"], list)
    assert len(payload["evidence_paths"]) <= 5
    assert isinstance(payload["truncated"], bool)
    assert _max_depth(payload) <= 2
    assert len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")) <= 4096

    for path, value in _walk_json(payload):
        if isinstance(value, list):
            assert len(value) <= 5, f"{path} has more than 5 items"
        if isinstance(value, str):
            max_length = 160 if path == "$.compact_text" else 80
            assert len(value) <= max_length, f"{path} exceeds {max_length} chars"
    _assert_no_forbidden_payload(payload)


def test_compact_payload_uses_dod003_projection_subset_and_root_allowlist_only() -> None:
    payload = _project_compact(_current_work_projection())

    _assert_common_compact_contract(payload)
    assert payload["root_id"] == ROOT_ID
    assert payload["current_skill"] == "mst:request"
    assert payload["current_step"] == 2
    assert payload["total_steps"] == 5
    assert payload["stack_depth"] == 3
    assert payload["next_action"] == "Approve REQ-827"
    assert payload["blocker"] is None
    assert payload["source_head"] == SOURCE_HEAD
    assert payload["projection_freshness"] == "fresh"


def test_compact_payload_is_bounded_and_marks_right_truncation() -> None:
    long_text = "X" * 180
    payload = _project_compact(
        _current_work_projection(
            task_sources=[_task_frame(index, title=f"{long_text}-{index}") for index in range(1, 12)],
            next_action_source={
                "action_type": "continue_skill",
                "label": "Continue " + long_text,
                "target": "REQ-827/T02",
                "command_hint": "/mst:request " + long_text,
                "reason": "long source fields must be bounded",
                "confidence": 0.9,
                "evidence_path": ".gran-maestro/requests/REQ-827/tasks/02/" + ("nested/" * 12) + "spec.md",
            },
        )
    )

    _assert_common_compact_contract(payload)
    assert payload["truncated"] is True
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert "…" in encoded
    assert "X" * 81 not in encoded
    assert len(payload["evidence_paths"]) == 5


def test_compact_text_uses_deterministic_order_and_missing_field_fallbacks() -> None:
    payload = _project_compact(_current_work_projection())

    assert (
        payload["compact_text"]
        == "MST AGI-031 mst:request 2/5 stack:3 next:Approve REQ-827 "
        "blocker:none fresh:fresh head:aaaaaaaa"
    )

    missing = _project_compact(
        _current_work_projection(
            active_workflow={"skill": "mst:request", "source_id": "REQ-827", "status": "active"},
            next_action_source=None,
            source_history_head=None,
            current_history_head=None,
        )
    )

    _assert_common_compact_contract(missing)
    assert "stack:3" in missing["compact_text"]
    assert "next:unknown" in missing["compact_text"]
    assert "blocker:none" in missing["compact_text"]
    assert "fresh:no_history" in missing["compact_text"]


def test_blocker_compact_fields_and_text_make_blocked_state_visible() -> None:
    payload = _project_compact(
        _current_work_projection(
            blocker_sources=[
                {
                    "blocker_type": "pending_dependency",
                    "status": "blocked",
                    "message": "REQ-827/T02 waits for red-first evidence",
                    "evidence_path": ".gran-maestro/requests/REQ-827/tasks/02/spec.md",
                    "recoverable": True,
                    "next_action_type": "wait_for_user",
                }
            ]
        )
    )

    _assert_common_compact_contract(payload)
    assert payload["blocker"] == {
        "code": "pending_dependency",
        "type": "pending_dependency",
        "status": "blocked",
        "recoverable": True,
        "next_action_type": "wait_for_user",
        "evidence_path": ".gran-maestro/requests/REQ-827/tasks/02/spec.md",
    }
    assert "blocker:pending_dependency" in payload["compact_text"]
    assert "fresh:fresh" in payload["compact_text"]


def test_freshness_short_statuses_do_not_claim_full_dod008_verification() -> None:
    cases = {
        "fresh": {},
        "stale": {"current_history_head": STALE_HEAD},
        "identity_mismatch": {"identity": _identity_context(env_sid=SID, structured_sid=OTHER_SID)},
        "no_history": {"source_history_head": None, "current_history_head": None},
        "unknown": {"current_history_head": None},
    }

    for expected_status, overrides in cases.items():
        payload = _project_compact(_current_work_projection(**overrides))
        _assert_common_compact_contract(payload)
        assert payload["projection_freshness"] == expected_status
        assert "dod008" not in json.dumps(payload, sort_keys=True).lower()
        assert "hash_chain_verified" not in payload


def test_identity_uses_canonical_session_or_display_root_not_diagnostic_values() -> None:
    payload = _project_compact(_current_work_projection())

    _assert_common_compact_contract(payload)
    assert payload["mst_session_id"] == SID
    assert payload["root_id"] == ROOT_ID
    assert HOOK_UUID not in payload["compact_text"]
    assert OWNER_SESSION_ID not in payload["compact_text"]
    assert TRANSCRIPT_STEM not in payload["compact_text"]
    assert OWNER_PID not in payload["compact_text"]


def test_missing_source_schema_invalid_and_external_hud_unavailable_have_safe_fallbacks() -> None:
    missing_source = _project_compact(None)
    _assert_common_compact_contract(missing_source)
    assert missing_source["mst_session_id"] == "unknown"
    assert missing_source["root_id"] == "unknown"
    assert missing_source["stack_depth"] == 0
    assert missing_source["projection_freshness"] == "no_history"
    assert (
        missing_source["compact_text"]
        == "MST unknown stack:0 next:unknown blocker:missing_source fresh:no_history"
    )

    schema_invalid = _project_compact(_current_work_projection(schema_version=0))
    _assert_common_compact_contract(schema_invalid)
    assert schema_invalid["projection_freshness"] == "unknown"
    assert schema_invalid["blocker"]["code"] == "schema_invalid"
    assert "blocker:schema_invalid" in schema_invalid["compact_text"]

    external_hud_unavailable = dict(_current_work_projection())
    external_hud_unavailable["external_hud"] = {"available": False, "raw_output": RAW_HISTORY_SENTINEL}
    fallback = _project_compact(external_hud_unavailable)
    _assert_common_compact_contract(fallback)
    assert fallback["reason"] in {"external_hud_unavailable", "current_work_projection"}
    assert RAW_HISTORY_SENTINEL not in json.dumps(fallback, sort_keys=True)
