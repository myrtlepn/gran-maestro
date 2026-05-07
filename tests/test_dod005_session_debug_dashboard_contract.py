from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from typing import Any


SID = "MST-AGI-031-20260507T003754000Z-dod005aa"
OTHER_SID = "MST-AGI-031-20260507T003755000Z-dod005bb"
SOURCE_HEAD = "a" * 64
CURRENT_HEAD = "b" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod005"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "515151"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD005"
RAW_PROMPT_SENTINEL = "RAW_PROMPT_SENTINEL_MUST_NOT_LEAK_DOD005"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD005"
LLM_SUMMARY_SENTINEL = "LLM_SUMMARY_SENTINEL_MUST_NOT_LEAK_DOD005"

REQUIRED_ROOT_FIELDS = {
    "schema_version",
    "generated_at",
    "mst_session_id",
    "summary",
    "panels",
    "selected_detail",
    "evidence_paths",
}

REQUIRED_SUMMARY_CARDS = {
    "identity",
    "current_work",
    "prompt",
    "writers",
    "integrity",
    "projection",
}

REQUIRED_PANEL_IDS = [
    "summary",
    "identity",
    "prompt_timeline",
    "current_work",
    "execution_flow",
    "writer_coverage",
    "integrity_freshness",
    "policy_block",
]

REQUIRED_PANEL_LABELS = {
    "summary": "Summary",
    "identity": "Identity Mapping",
    "prompt_timeline": "Prompt Timeline",
    "current_work": "Current Work",
    "execution_flow": "Execution Flow",
    "writer_coverage": "Writer Coverage",
    "integrity_freshness": "Integrity & Freshness",
    "policy_block": "Policy/Block",
}

FORBIDDEN_KEYS = {
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


def _session_debug_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.session_debug")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-005 Session Debug projection module is missing: "
            "expected scripts.mst_cmds.session_debug"
        ) from exc


def _project_session_debug(fixture: dict[str, Any], *, selected_panel_id: str = "summary") -> dict[str, Any]:
    module = _session_debug_module()
    fn = getattr(module, "project_session_debug_dashboard", None)
    assert callable(fn), (
        "scripts.mst_cmds.session_debug.project_session_debug_dashboard "
        "must be callable"
    )
    payload = fn({**fixture, "selected_panel_id": selected_panel_id})
    assert isinstance(payload, dict), "Session Debug projection must return a JSON object payload"
    return payload


def _writer_coverage_projection() -> dict[str, Any]:
    module = importlib.import_module("scripts.mst_cmds.writer_coverage")
    fn = getattr(module, "project_writer_coverage")
    return fn(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "source_history_head": SOURCE_HEAD,
            "generated_at": "2026-05-07T00:37:52.000Z",
            "identity": _identity_context(),
            "writer_matrix": [
                _writer_row("cli_invocation", ["mst.invocation_end"]),
                _writer_row("prompt_writer", ["prompt.submitted"]),
                _writer_row("hook_lifecycle_ledger", ["hook.UserPromptSubmit.start"]),
            ],
            "observed_events": [
                _event("cli_invocation", "mst.invocation_end"),
                _event("prompt_writer", "prompt.submitted"),
                _event("hook_lifecycle_ledger", "hook.UserPromptSubmit.start"),
            ],
            "raw_history_rows": [{"event": {"payload": RAW_HISTORY_SENTINEL}}],
        }
    )


def _current_work_projection() -> dict[str, Any]:
    module = importlib.import_module("scripts.mst_cmds.current_work_handoff")
    fn = getattr(module, "project_current_work_handoff")
    return fn(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "generated_at": "2026-05-07T00:37:53.000Z",
            "source_history_head": SOURCE_HEAD,
            "current_history_head": SOURCE_HEAD,
            "identity": _identity_context(),
            "active_workflow": {
                "skill": "mst:request",
                "source_id": "REQ-826",
                "status": "active",
                "evidence_path": ".gran-maestro/requests/REQ-826/tasks/01/spec.md",
            },
            "task_sources": [
                {
                    "kind": "request_task",
                    "id": "REQ-826/T01",
                    "title": "Session Debug contract tests",
                    "status": "active",
                    "owner": "codex-dev",
                    "phase": "red-first",
                    "source": "spec.md",
                    "evidence_path": ".gran-maestro/requests/REQ-826/tasks/01/spec.md",
                }
            ],
            "next_action_source": {
                "action_type": "continue_skill",
                "label": "Implement Session Debug IA",
                "target": "REQ-826/T02",
                "command_hint": "/mst:request REQ-826",
                "reason": "DOD-005 red-first contract is fixed",
                "confidence": 1.0,
                "evidence_path": ".gran-maestro/requests/REQ-826/tasks/02/spec.md",
            },
            "blocker_sources": [],
            "raw_history_rows": [{"event": {"payload": RAW_HISTORY_SENTINEL}}],
            "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        }
    )


def _prompt_timeline_projection() -> dict[str, Any]:
    module = importlib.import_module("scripts.mst_cmds.prompt_correlation")
    fn = getattr(module, "project_prompt_timeline")
    return fn(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "generated_at": "2026-05-07T00:37:53.500Z",
            "source_history_head": CURRENT_HEAD,
            "current_history_head": CURRENT_HEAD,
            "history_rows": [
                {
                    "seq": 1,
                    "event_hash": SOURCE_HEAD,
                    "prev_hash": "0" * 64,
                    "event": {"event_type": "skill.step", "payload": RAW_HISTORY_SENTINEL},
                },
                {
                    "seq": 2,
                    "event_hash": CURRENT_HEAD,
                    "prev_hash": SOURCE_HEAD,
                    "event": {
                        "event_type": "prompt.submitted",
                        "created_at": "2026-05-07T00:37:53.000Z",
                        "mst_session_id": SID,
                        "prompt_digest": "sha256:" + ("c" * 64),
                        "prompt_size_bytes": 4096,
                        "prompt_excerpt": {
                            "text": "Implement DOD-005 Session Debug without raw payload leaks.",
                            "max_chars": 120,
                            "truncated": True,
                            "omitted_bytes": 3976,
                        },
                        "transcript_path": f"/tmp/{TRANSCRIPT_STEM}.jsonl",
                        "history_head_before": SOURCE_HEAD,
                        "idempotency_key": f"{SID}:prompt.submitted:sha256:{'c' * 64}",
                        "source": "UserPromptSubmit",
                    },
                },
                {
                    "seq": 3,
                    "event_hash": "d" * 64,
                    "prev_hash": CURRENT_HEAD,
                    "event": {"event_type": "policy_block", "status": "blocked"},
                },
            ],
            "raw_prompt_text": RAW_PROMPT_SENTINEL,
            "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        }
    )


def _identity_context() -> dict[str, Any]:
    return {
        "env": {"MST_SESSION_ID": SID, "MST_STATE_PPID": OWNER_PID},
        "context": {
            "mst_session_id": SID,
            "session_id": HOOK_UUID,
            "owner_session_id": OWNER_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_STEM}.jsonl",
        },
        "legacy_diagnostics": {
            "hook_session_id": HOOK_UUID,
            "owner_session_id": OWNER_SESSION_ID,
            "owner_pid": OWNER_PID,
            "hook_transcript_stem": TRANSCRIPT_STEM,
        },
    }


def _writer_row(writer_id: str, events: list[str]) -> dict[str, Any]:
    return {
        "writer_id": writer_id,
        "surface": writer_id,
        "expected": True,
        "expected_events": events,
        "required_when": "DOD-005 projection reuse fixture",
        "identity_classification": "canonical selector + diagnostics",
        "delivery_type": "return_payload",
        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
    }


def _event(writer_id: str, event_type: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "writer_id": writer_id,
        "event_type": event_type,
        "mst_session_id": SID,
        "source_history_head": SOURCE_HEAD,
        "created_at": "2026-05-07T00:37:53.000Z",
        "write_status": "success",
        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
    }


def _session_debug_fixture(**overrides: Any) -> dict[str, Any]:
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "generated_at": "2026-05-07T00:37:54.000Z",
        "source_history_head": SOURCE_HEAD,
        "current_history_head": SOURCE_HEAD,
        "identity": _identity_context(),
        "writer_coverage": _writer_coverage_projection(),
        "current_work_handoff": _current_work_projection(),
        "prompt_timeline": _prompt_timeline_projection(),
        "execution_flow": {
            "current_node": "red_first_contract",
            "last_transition": "task_assigned",
            "next_action": "implement_projection",
            "node_health": {"status": "unknown", "reason": "verifier_not_in_scope"},
            "edge_health": {"status": "unknown", "reason": "verifier_not_in_scope"},
            "evidence_path": ".gran-maestro/requests/REQ-826/tasks/01/spec.md",
        },
        "integrity": {
            "status": "unknown",
            "reason": "verifier_not_in_scope",
            "source_history_head": SOURCE_HEAD,
            "current_history_head": SOURCE_HEAD,
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        "policy_blocks": [
            {
                "indicator": "policy_block",
                "status": "blocked",
                "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson#policy_block",
            }
        ],
        "raw_ledger_rows": [{"payload": RAW_HISTORY_SENTINEL}],
        "raw_prompt_text": RAW_PROMPT_SENTINEL,
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "llm_summary": LLM_SUMMARY_SENTINEL,
    }
    fixture.update(overrides)
    return fixture


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _assert_no_raw_or_hud_leak(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for sentinel in (
        RAW_HISTORY_SENTINEL,
        RAW_PROMPT_SENTINEL,
        RAW_TRANSCRIPT_SENTINEL,
        LLM_SUMMARY_SENTINEL,
    ):
        assert sentinel not in encoded

    forbidden_hits: list[str] = []
    hud_hits: list[str] = []
    for path, value in _walk_json(payload):
        if isinstance(value, dict):
            for key in value:
                if key in FORBIDDEN_KEYS:
                    forbidden_hits.append(f"{path}.{key}")
        if isinstance(value, str) and value.lower() in {"hud", "statusline"}:
            hud_hits.append(path)
    assert not forbidden_hits, "forbidden raw payload keys leaked: " + ", ".join(forbidden_hits)
    assert not hud_hits, "HUD/statusline leaked into Session Debug dashboard contract: " + ", ".join(hud_hits)


def _panel_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    panels = payload.get("panels")
    assert isinstance(panels, list), "panels must be a bounded registry list"
    by_id: dict[str, dict[str, Any]] = {}
    for panel in panels:
        assert isinstance(panel, dict), f"panel registry row must be an object: {panel!r}"
        panel_id = panel.get("id")
        assert isinstance(panel_id, str) and panel_id, f"panel id is required: {panel!r}"
        by_id[panel_id] = panel
    return by_id


def _assert_common_contract(payload: dict[str, Any]) -> None:
    assert REQUIRED_ROOT_FIELDS <= payload.keys(), f"missing root fields: {REQUIRED_ROOT_FIELDS - payload.keys()}"
    assert payload["schema_version"] == 1
    assert payload["mst_session_id"] == SID
    assert isinstance(payload["generated_at"], str) and payload["generated_at"].strip()
    assert isinstance(payload["evidence_paths"], list)
    assert payload["evidence_paths"], "Session Debug projection must expose bounded evidence paths"
    assert isinstance(payload["selected_detail"], dict)
    assert isinstance(payload["selected_detail"].get("evidence_paths"), list)
    for path in payload["evidence_paths"] + payload["selected_detail"].get("evidence_paths", []):
        assert isinstance(path, str) and path.startswith(".gran-maestro/"), f"invalid evidence path: {path!r}"
    _assert_no_raw_or_hud_leak(payload)


def test_session_debug_payload_has_bounded_root_schema_summary_cards_and_no_raw_payload() -> None:
    payload = _project_session_debug(_session_debug_fixture())

    _assert_common_contract(payload)
    summary = payload["summary"]
    assert isinstance(summary, dict), "summary must be a bounded deterministic card model"
    assert REQUIRED_SUMMARY_CARDS <= summary.keys(), f"missing summary cards: {REQUIRED_SUMMARY_CARDS - summary.keys()}"
    assert summary["identity"]["canonical_mst_session_id"] == SID
    assert summary["current_work"]["status"] in {"active", "blocked", "empty", "unknown"}
    assert summary["prompt"]["latest_prompt_digest"].startswith("sha256:")
    assert summary["writers"]["status"] in {"ok", "warning", "error", "unknown"}
    assert summary["integrity"]["status"] in {"ok", "stale", "mismatch", "no_history", "unknown"}
    assert summary["projection"]["status"] in {"fresh", "stale", "identity_mismatch", "no_history", "unknown"}


def test_panel_registry_is_complete_single_surface_and_excludes_hud_statusline_boundary() -> None:
    payload = _project_session_debug(_session_debug_fixture())
    panels = _panel_by_id(payload)

    assert list(panels) == REQUIRED_PANEL_IDS
    for panel_id, label in REQUIRED_PANEL_LABELS.items():
        row = panels[panel_id]
        assert row.get("label") == label
        assert isinstance(row.get("status"), str) and row["status"]
    assert "hud" not in panels
    assert "statusline" not in panels
    _assert_common_contract(payload)


def test_selected_drilldown_details_reuse_dod002_dod003_dod004_bounded_projections() -> None:
    fixture = _session_debug_fixture()
    payload = _project_session_debug(fixture)
    panel_details = payload.get("panel_details")
    assert isinstance(panel_details, dict)
    assert list(panel_details) == REQUIRED_PANEL_IDS

    writer_detail = panel_details["writer_coverage"]
    assert writer_detail["panel_id"] == "writer_coverage"
    assert writer_detail.get("writers") == fixture["writer_coverage"]["writers"]
    assert writer_detail.get("source_projection") == "DOD-002"

    current_detail = panel_details["current_work"]
    assert current_detail["panel_id"] == "current_work"
    assert current_detail.get("current_task_stack") == fixture["current_work_handoff"]["current_task_stack"]
    assert current_detail.get("next_action") == fixture["current_work_handoff"]["next_action"]
    assert current_detail.get("projection_freshness") == fixture["current_work_handoff"]["projection_freshness"]
    assert current_detail.get("source_projection") == "DOD-003"

    prompt_detail = panel_details["prompt_timeline"]
    assert prompt_detail["panel_id"] == "prompt_timeline"
    assert prompt_detail.get("prompt_anchors") == fixture["prompt_timeline"]["prompt_anchors"]
    assert prompt_detail.get("source_projection") == "DOD-004"

    selected_prompt_detail = _project_session_debug(fixture, selected_panel_id="prompt_timeline")["selected_detail"]
    assert selected_prompt_detail == prompt_detail


def test_identity_execution_integrity_and_policy_panels_are_bounded_and_deterministic() -> None:
    fixture = _session_debug_fixture()

    identity_detail = _project_session_debug(fixture, selected_panel_id="identity")["selected_detail"]
    assert identity_detail["panel_id"] == "identity"
    assert identity_detail["canonical_mst_session_id"] == SID
    assert identity_detail.get("diagnostic_only_identifiers")
    for field in ("lookup_key", "partition_key", "repair_source", "migration_source"):
        assert identity_detail.get(field, SID) not in DIAGNOSTIC_ONLY_VALUES

    execution_detail = _project_session_debug(fixture, selected_panel_id="execution_flow")["selected_detail"]
    assert execution_detail["panel_id"] == "execution_flow"
    assert execution_detail.get("current_node") == "red_first_contract"
    assert execution_detail.get("node_health", {}).get("status") == "unknown"
    assert execution_detail.get("edge_health", {}).get("reason") == "verifier_not_in_scope"

    integrity_detail = _project_session_debug(fixture, selected_panel_id="integrity_freshness")["selected_detail"]
    assert integrity_detail["panel_id"] == "integrity_freshness"
    assert integrity_detail.get("source_history_head") == SOURCE_HEAD
    assert integrity_detail.get("status") in {"ok", "stale", "mismatch", "no_history", "unknown"}
    assert "hash_chain_verified" not in integrity_detail, "DOD-005 must not claim DOD-008 full verifier completion"

    policy_detail = _project_session_debug(fixture, selected_panel_id="policy_block")["selected_detail"]
    assert policy_detail["panel_id"] == "policy_block"
    assert policy_detail.get("indicators", {}).get("policy_block") is True
    assert policy_detail.get("empty_state") is False


def test_empty_no_history_fallback_is_deterministic_and_still_uses_debug_shell() -> None:
    payload = _project_session_debug(
        _session_debug_fixture(
            source_history_head=None,
            current_history_head=None,
            writer_coverage=None,
            current_work_handoff=None,
            prompt_timeline=None,
            execution_flow=None,
            integrity=None,
            policy_blocks=[],
            raw_ledger_rows=[],
        )
    )

    _assert_common_contract(payload)
    assert payload["summary"]["identity"]["canonical_mst_session_id"] == SID
    assert payload["summary"]["current_work"]["status"] in {"empty", "unknown"}
    assert payload["summary"]["prompt"]["status"] in {"no_history", "not_seen", "unknown"}
    assert payload["summary"]["projection"]["status"] in {"no_history", "unknown"}
    assert payload["selected_detail"]["panel_id"] == "summary"
    assert "no_history" in json.dumps(payload, sort_keys=True)
