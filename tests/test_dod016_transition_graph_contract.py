from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_CANDIDATES = (
    REPO_ROOT / "templates" / "state-machine" / "mst-transition-graph.json",
    REPO_ROOT / "templates" / "state-machine" / "mst-transition-graph.yaml",
    REPO_ROOT / "templates" / "state-machine" / "mst-transition-graph.yml",
)
GENERATED_VIEW_CANDIDATES = (
    REPO_ROOT / "templates" / "state-machine" / "mst-transition-graph.d2",
    REPO_ROOT / "dashboard" / "mst-transition-graph.json",
    REPO_ROOT / "dashboard" / "mst-transition-graph.d2",
    REPO_ROOT / ".gran-maestro" / "generated" / "mst-transition-graph.json",
    REPO_ROOT / ".gran-maestro" / "generated" / "mst-transition-graph.d2",
)

SID = "MST-AGI-030-20260505T060708000Z-dod016aa"
ROOT = "AGI-030"
GRAPH_ID = "mst-transition-graph"

CORE_STATES = {"active", "inspecting", "blocked", "completed", "failed", "cancelled"}
CORE_TRANSITIONS = {
    "continue.queued_action",
    "continue.rehydrate_retry",
    "guard.inspect_only_verification",
    "terminal.completed",
    "terminal.security_confirmation_required",
}
REQUIRED_GRAPH_FIELDS = {
    "schema_version",
    "id",
    "version",
    "hash",
    "states",
    "transitions",
    "semantic_invariants",
}
REQUIRED_LIFECYCLE_MAPPING_FIELDS = {
    "id",
    "from",
    "to",
    "terminal",
    "auto_allowed",
    "write_allowed",
    "guards",
    "required_evidence",
    "on_reject",
    "ledger_event_family",
    "projection_rule",
    "reject_failure_path",
}
REQUIRED_TRANSITION_FIELDS = {
    "from",
    "to",
    "guards",
    "required_evidence",
    "on_reject",
    "auto_allowed",
    "write_allowed",
}


def _json_hash(payload: dict) -> str:
    without_hash = copy.deepcopy(payload)
    without_hash.pop("hash", None)
    encoded = json.dumps(without_hash, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_machine_readable(path: Path) -> dict:
    if path.suffix == ".json":
        return _read_json(path)
    try:
        import yaml  # type: ignore
    except Exception as exc:
        raise AssertionError(
            f"{path} is YAML but no YAML parser is available; use JSON or provide PyYAML in the test env"
        ) from exc
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} must contain a mapping/object"
    return payload


def _canonical_graph_path() -> Path:
    for path in GRAPH_CANDIDATES:
        if path.is_file():
            return path
    searched = "\n".join(f"- {path}" for path in GRAPH_CANDIDATES)
    raise AssertionError(f"DOD-016 canonical transition graph artifact is missing. Searched:\n{searched}")


def _load_canonical_graph() -> tuple[Path, dict]:
    path = _canonical_graph_path()
    return path, _load_machine_readable(path)


def _transition_graph_module():
    try:
        return importlib.import_module("scripts.mst_cmds.transition_graph")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-016 mst.py transition graph validator module is missing: "
            "expected scripts.mst_cmds.transition_graph"
        ) from exc


def _call_required(module: object, name: str, *args, **kwargs):
    fn = getattr(module, name, None)
    assert callable(fn), f"scripts.mst_cmds.transition_graph.{name} must be callable"
    return fn(*args, **kwargs)


def _transitions(graph: dict) -> dict:
    transitions = graph.get("transitions")
    assert isinstance(transitions, dict), "graph.transitions must be an object keyed by transition id"
    return transitions


def _states(graph: dict) -> dict:
    states = graph.get("states")
    assert isinstance(states, dict), "graph.states must be an object keyed by state id"
    return states


def _assert_structured_non_success(result: object, *, expected_code: str) -> dict:
    assert isinstance(result, dict), f"validator result must be a structured dict, got {type(result).__name__}"
    assert result.get("status") in {"error", "failed", "validation_failed", "rejected"}, result
    assert result.get("accepted") is not True, result
    diagnostics = result.get("diagnostics")
    assert isinstance(diagnostics, list) and diagnostics, result
    codes = {str(item.get("code") or item.get("field") or "") for item in diagnostics if isinstance(item, dict)}
    assert expected_code in codes, f"missing diagnostic {expected_code!r}: {result}"
    assert result.get("fail_closed") is True, result
    assert result.get("created_new_session") is False, result
    return result


def _base_graph() -> dict:
    graph = {
        "schema_version": 1,
        "id": GRAPH_ID,
        "version": "2026-05-05.dod016-contract",
        "states": {
            "active": {"terminal": False},
            "inspecting": {"terminal": False},
            "blocked": {"terminal": False},
            "completed": {"terminal": True},
            "failed": {"terminal": True},
            "cancelled": {"terminal": True},
        },
        "transitions": {
            "continue.queued_action": {
                "from": ["active"],
                "to": "active",
                "auto_allowed": True,
                "write_allowed": True,
                "guards": ["next_action_present", "no_critical_blocker"],
                "required_evidence": ["next_action", "history_head"],
                "on_reject": "guard.inspect_only_verification",
            },
            "continue.rehydrate_retry": {
                "from": ["active", "inspecting"],
                "to": "active",
                "auto_allowed": True,
                "write_allowed": True,
                "guards": ["core_rehydration_available", "history_head_matches_snapshot"],
                "required_evidence": ["mst_session_id", "root_mst_id", "history_last_event_id"],
                "on_reject": "terminal.state_inconsistency",
            },
            "guard.inspect_only_verification": {
                "from": ["active", "inspecting"],
                "to": "inspecting",
                "auto_allowed": True,
                "write_allowed": False,
                "guards": ["state_inconsistency_suspected"],
                "required_evidence": ["mismatch_subject"],
                "on_reject": "terminal.state_inconsistency",
            },
            "terminal.completed": {
                "from": ["active"],
                "to": "completed",
                "auto_allowed": True,
                "write_allowed": True,
                "guards": ["all_required_dod_done", "no_next_action", "history_verified"],
                "required_evidence": ["objective_check_result", "history_head"],
                "on_reject": "continue.queued_action",
            },
            "terminal.security_confirmation_required": {
                "from": ["active", "inspecting"],
                "to": "blocked",
                "auto_allowed": False,
                "write_allowed": True,
                "guards": ["action_is_destructive_or_external", "classifier_failed_or_permission_unknown"],
                "required_evidence": ["action_scope", "classifier_failure_kind", "next_safe_action"],
                "on_reject": "terminal.state_inconsistency",
            },
            "terminal.state_inconsistency": {
                "from": ["active", "inspecting", "blocked"],
                "to": "failed",
                "auto_allowed": False,
                "write_allowed": True,
                "guards": ["state_contract_failed"],
                "required_evidence": ["mismatch_subject", "history_head"],
                "on_reject": "terminal.repeat_failure_limit",
            },
            "terminal.repeat_failure_limit": {
                "from": ["active", "inspecting", "blocked"],
                "to": "failed",
                "auto_allowed": False,
                "write_allowed": True,
                "guards": ["repeat_limit_exceeded"],
                "required_evidence": ["reject_loop_key", "attempt_count", "limit"],
                "on_reject": "terminal.state_inconsistency",
            },
        },
        "evidence_producers": {
            "next_action": ["state_snapshot", "recover_bundle"],
            "history_head": ["history_ledger"],
            "mst_session_id": ["session_metadata", "hook_env"],
            "root_mst_id": ["session_metadata"],
            "history_last_event_id": ["state_snapshot", "history_ledger"],
            "objective_check_result": ["mst.py agile objective-check"],
            "mismatch_subject": ["validator"],
            "action_scope": ["hook_boundary_classifier"],
            "classifier_failure_kind": ["hook_boundary_classifier"],
            "next_safe_action": ["hook_boundary_classifier"],
            "reject_loop_key": ["transition_validator"],
            "attempt_count": ["transition_validator"],
            "limit": ["transition_validator"],
            "user_confirmation": ["confirmation_command"],
            "confirmed_action_scope": ["confirmation_command"],
            "history_head_verified": ["history_ledger"],
            "user_cancel_request": ["cancel_command"],
            "cancel_scope": ["cancel_command"],
            "failed_guard": ["transition_validator"],
        },
        "lifecycle_mappings": {
            "blocked.resume_confirmed": {
                "id": "blocked.resume_confirmed",
                "from": ["blocked"],
                "to": "active",
                "terminal": False,
                "auto_allowed": True,
                "write_allowed": True,
                "guards": ["user_confirmation_verified", "history_verified", "next_action_present"],
                "required_evidence": [
                    "user_confirmation",
                    "confirmed_action_scope",
                    "mst_session_id",
                    "history_head_verified",
                    "next_action",
                ],
                "on_reject": "guard.inspect_only_verification",
                "ledger_event_family": "external_lifecycle",
                "projection_rule": "display blocked node to active continuation edge after confirmed evidence",
                "reject_failure_path": "guard.inspect_only_verification",
            },
            "terminal.user_cancelled.lifecycle": {
                "id": "terminal.user_cancelled.lifecycle",
                "from": ["*"],
                "to": "cancelled",
                "terminal": True,
                "auto_allowed": False,
                "write_allowed": True,
                "guards": ["user_cancel_requested", "history_verified"],
                "required_evidence": ["user_cancel_request", "mst_session_id", "history_head", "cancel_scope"],
                "on_reject": "guard.inspect_only_verification",
                "ledger_event_family": "external_lifecycle",
                "projection_rule": "display terminal cancelled node only when cancel lifecycle evidence is ledger-backed",
                "reject_failure_path": "terminal.state_inconsistency",
            },
            "terminal.completed.reject_split": {
                "id": "terminal.completed.reject_split",
                "from": ["active"],
                "to": "inspecting",
                "terminal": False,
                "auto_allowed": True,
                "write_allowed": False,
                "guards": ["completion_reject_reason_classified"],
                "required_evidence": ["objective_check_result", "history_head", "failed_guard"],
                "on_reject": {
                    "no_next_action": "continue.queued_action",
                    "history_verified": "guard.inspect_only_verification",
                    "objective_check_result": "guard.inspect_only_verification",
                    "confirmed_mismatch": "terminal.state_inconsistency",
                },
                "ledger_event_family": "transition",
                "projection_rule": "display completion attempt edge plus reject-specific continuation or inspect edge",
                "reject_failure_path": "terminal.state_inconsistency",
            },
        },
        "semantic_invariants": [
            "all transition from/to states are declared",
            "nonterminal states are reachable from active",
            "rejected transitions define on_reject",
            "required evidence keys have producers",
            "generated graph view covers all graph states and transitions",
            "auto_allowed does not bypass destructive or external action guards",
        ],
    }
    graph["hash"] = _json_hash(graph)
    return graph


def _attempt_envelope(
    *,
    evidence: dict | None = None,
    transition: str = "terminal.completed",
    current_state: str = "active",
) -> dict:
    graph = _base_graph()
    return {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "graph": {"id": graph["id"], "version": graph["version"], "hash": graph["hash"]},
        "current_state": current_state,
        "attempted_transition": transition,
        "evidence": evidence or {"objective_check_result": {"done": False}, "history_head": "a" * 64},
        "guard_inputs": {
            "all_required_dod_done": False,
            "no_next_action": False,
            "history_verified": True,
        },
    }


def _invalid_graph_cases() -> list[tuple[str, str, dict, dict | None]]:
    base = _base_graph()

    missing_field = copy.deepcopy(base)
    missing_field.pop("schema_version")

    unsupported_state = copy.deepcopy(base)
    unsupported_state["transitions"]["continue.queued_action"]["to"] = "ghost"

    unreachable_nonterminal = copy.deepcopy(base)
    unreachable_nonterminal["states"]["orphan_review"] = {"terminal": False}

    reject_without_on_reject = copy.deepcopy(base)
    reject_without_on_reject["transitions"]["terminal.completed"].pop("on_reject")

    invalid_evidence = copy.deepcopy(base)
    invalid_evidence["transitions"]["continue.queued_action"]["required_evidence"].append("unknown_evidence_key")

    invalid_lifecycle = copy.deepcopy(base)
    invalid_lifecycle["lifecycle_mappings"]["blocked.resume_confirmed"].pop("ledger_event_family")

    view_gap = copy.deepcopy(base)
    generated_view = {
        "schema_version": 1,
        "source_graph": {"id": GRAPH_ID, "version": base["version"], "hash": base["hash"]},
        "covered_states": ["active"],
        "covered_transitions": ["continue.queued_action"],
    }

    return [
        ("missing schema_version", "schema_version", missing_field, None),
        ("unsupported state reference", "unsupported_state", unsupported_state, None),
        ("unreachable nonterminal state", "unreachable_nonterminal_state", unreachable_nonterminal, None),
        ("reject without on_reject", "on_reject", reject_without_on_reject, None),
        ("invalid evidence producer", "evidence_producer", invalid_evidence, None),
        ("invalid lifecycle mapping", "lifecycle_mapping", invalid_lifecycle, None),
        ("generated view coverage gap", "generated_view_coverage", view_gap, generated_view),
    ]


def test_graph_artifact_defines_machine_readable_contract() -> None:
    graph_path, graph = _load_canonical_graph()

    assert graph_path.suffix in {".json", ".yaml", ".yml"}, graph_path
    assert REQUIRED_GRAPH_FIELDS <= set(graph), f"missing graph fields: {REQUIRED_GRAPH_FIELDS - set(graph)}"
    assert graph["schema_version"] == 1, graph
    assert graph["id"] == GRAPH_ID, graph
    assert isinstance(graph["version"], str) and graph["version"].strip(), graph
    assert isinstance(graph["hash"], str) and re.fullmatch(r"[0-9a-f]{64}", graph["hash"]), graph
    assert graph["hash"] == _json_hash(graph), "graph hash must pin the canonical machine-readable payload"

    states = _states(graph)
    assert CORE_STATES <= set(states), f"missing DOD-016 core states: {CORE_STATES - set(states)}"
    for state_name, state in states.items():
        assert isinstance(state, dict), f"state {state_name} must be an object"
        assert isinstance(state.get("terminal"), bool), f"state {state_name} must declare terminal bool"

    transitions = _transitions(graph)
    assert CORE_TRANSITIONS <= set(transitions), f"missing DOD-016 core transitions: {CORE_TRANSITIONS - set(transitions)}"
    for transition_name, transition in transitions.items():
        assert REQUIRED_TRANSITION_FIELDS <= set(transition), (
            f"{transition_name} missing fields: {REQUIRED_TRANSITION_FIELDS - set(transition)}"
        )
        from_states = transition["from"]
        assert isinstance(from_states, list) and from_states, f"{transition_name}.from must be a non-empty list"
        assert all(state in states for state in from_states), f"{transition_name}.from references undefined state"
        assert transition["to"] in states, f"{transition_name}.to references undefined state"
        assert isinstance(transition["guards"], list), f"{transition_name}.guards must be a list"
        assert isinstance(transition["required_evidence"], list), f"{transition_name}.required_evidence must be a list"
        assert transition["on_reject"] in transitions, f"{transition_name}.on_reject must reference another transition"
        assert isinstance(transition["auto_allowed"], bool), f"{transition_name}.auto_allowed must be bool"
        assert isinstance(transition["write_allowed"], bool), f"{transition_name}.write_allowed must be bool"

    invariants = graph["semantic_invariants"]
    assert isinstance(invariants, list) and invariants, "semantic_invariants must list machine-checkable rules"
    assert "terminal.security_confirmation_required" in transitions
    security = transitions["terminal.security_confirmation_required"]
    assert security["auto_allowed"] is False, "auto_allowed must not grant destructive/external action permission"


def test_state_inventory_and_terminal_entry_coverage() -> None:
    module = _transition_graph_module()
    graph_path, graph = _load_canonical_graph()
    result = _call_required(module, "validate_state_inventory_coverage", graph, source=str(graph_path))

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("graph_version") == graph["version"], result
    assert result.get("graph_hash") == graph["hash"], result
    assert set(result.get("terminal_states") or []) >= {"completed", "failed", "cancelled"}, result
    assert set(result.get("nonterminal_states") or []) >= {"active", "inspecting", "blocked"}, result
    assert result.get("gaps") == [], result
    terminal_entries = result.get("terminal_entry_coverage")
    assert isinstance(terminal_entries, dict), result
    for state in result["terminal_states"]:
        entry = terminal_entries.get(state)
        assert isinstance(entry, dict), (state, result)
        assert entry.get("coverage") in {"graph_transition", "lifecycle_mapping"}, (state, entry)
        assert entry.get("required_evidence"), (state, entry)


def test_equivalent_lifecycle_mappings_cover_known_gap_candidates() -> None:
    module = _transition_graph_module()
    graph_path, graph = _load_canonical_graph()

    result = _call_required(module, "validate_equivalent_lifecycle_mappings", graph, source=str(graph_path))
    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    mappings = result.get("mappings")
    assert isinstance(mappings, dict), result

    for mapping_id in (
        "blocked.resume_confirmed",
        "terminal.user_cancelled.lifecycle",
        "terminal.completed.reject_split",
    ):
        mapping = mappings.get(mapping_id)
        assert isinstance(mapping, dict), result
        assert REQUIRED_LIFECYCLE_MAPPING_FIELDS <= set(mapping), (
            mapping_id,
            REQUIRED_LIFECYCLE_MAPPING_FIELDS - set(mapping),
        )
        assert mapping["required_evidence"], mapping
        assert mapping["ledger_event_family"], mapping
        assert mapping["projection_rule"], mapping
        assert mapping["reject_failure_path"], mapping

    missing = copy.deepcopy(graph)
    missing["lifecycle_mappings"]["terminal.user_cancelled.lifecycle"].pop("projection_rule")
    failed = _call_required(module, "validate_equivalent_lifecycle_mappings", missing, source="fixture:missing")
    _assert_structured_non_success(failed, expected_code="lifecycle_mapping")


def test_graph_schema_invariants_fail_closed() -> None:
    module = _transition_graph_module()

    for label, expected_code, graph, generated_view in _invalid_graph_cases():
        result = _call_required(
            module,
            "validate_transition_graph",
            graph,
            generated_view=generated_view,
            source=f"fixture:{label}",
        )
        _assert_structured_non_success(result, expected_code=expected_code)
        assert result.get("silent_migration") is not True, result
        assert result.get("default_pass") is not True, result


def test_transition_validator_requires_explicit_envelope() -> None:
    module = _transition_graph_module()
    graph = _base_graph()

    accepted = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(
            transition="continue.queued_action",
            evidence={"next_action": {"skill": "mst:approve", "source": "REQ-819"}, "history_head": "b" * 64},
        ),
        graph,
    )
    assert isinstance(accepted, dict), accepted
    assert accepted.get("status") == "accepted", accepted
    assert accepted.get("accepted") is True, accepted
    assert accepted.get("graph_version") == graph["version"], accepted
    assert accepted.get("graph_hash") == graph["hash"], accepted
    assert accepted.get("transition") == "continue.queued_action", accepted
    assert accepted.get("current_state") == "active", accepted

    rejected = _call_required(module, "validate_attempted_transition", _attempt_envelope(), graph)
    assert isinstance(rejected, dict), rejected
    assert rejected.get("status") == "rejected", rejected
    assert rejected.get("accepted") is False, rejected
    assert rejected.get("graph_version") == graph["version"], rejected
    assert rejected.get("graph_hash") == graph["hash"], rejected
    assert rejected.get("transition") == "terminal.completed", rejected
    assert rejected.get("on_reject") == "continue.queued_action", rejected
    assert "all_required_dod_done" in set(rejected.get("failed_guards") or []), rejected
    assert set(rejected.get("required_evidence") or []) >= {"objective_check_result", "history_head"}, rejected

    missing_hash = _attempt_envelope()
    missing_hash["graph"].pop("hash")
    failed = _call_required(module, "validate_attempted_transition", missing_hash, graph)
    _assert_structured_non_success(failed, expected_code="graph.hash")


def test_transition_validator_splits_completion_reject_paths() -> None:
    module = _transition_graph_module()
    graph = _base_graph()

    no_next_action_failed = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(
            evidence={
                "objective_check_result": {"done": True},
                "history_head": "c" * 64,
                "next_action": {"skill": "mst:continue", "source": "REQ-896"},
            }
        ),
        graph,
    )
    assert no_next_action_failed.get("status") == "rejected", no_next_action_failed
    assert no_next_action_failed.get("on_reject") == "continue.queued_action", no_next_action_failed
    assert no_next_action_failed.get("write_permission_granted") is False, no_next_action_failed
    assert no_next_action_failed.get("auto_terminal_write") is False, no_next_action_failed

    missing_history = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(evidence={"objective_check_result": {"done": True}}),
        graph,
    )
    assert missing_history.get("status") == "rejected", missing_history
    assert missing_history.get("on_reject") == "guard.inspect_only_verification", missing_history
    assert "history_head" in set(missing_history.get("missing_evidence") or []), missing_history
    assert missing_history.get("write_permission_granted") is False, missing_history

    stale_history = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(
            evidence={
                "objective_check_result": {"done": True},
                "history_head": {"value": "d" * 64, "stale": True},
            }
        ),
        graph,
    )
    assert stale_history.get("status") == "rejected", stale_history
    assert stale_history.get("on_reject") == "guard.inspect_only_verification", stale_history
    assert "history_head" in set(stale_history.get("stale_evidence") or []), stale_history

    confirmed_mismatch = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(
            evidence={
                "objective_check_result": {"done": True},
                "history_head": "e" * 64,
                "mismatch_subject": {"kind": "session", "confirmed": True},
            },
            transition="continue.rehydrate_retry",
        ),
        graph,
    )
    assert confirmed_mismatch.get("status") == "rejected", confirmed_mismatch
    assert confirmed_mismatch.get("on_reject") == "terminal.state_inconsistency", confirmed_mismatch
    assert "mismatch_subject" in set(confirmed_mismatch.get("mismatched_evidence") or []), confirmed_mismatch
    assert confirmed_mismatch.get("auto_terminal_write") is False, confirmed_mismatch

    unsupported_terminal = _call_required(
        module,
        "validate_attempted_transition",
        _attempt_envelope(transition="terminal.unsupported", current_state="active"),
        graph,
    )
    _assert_structured_non_success(unsupported_terminal, expected_code="attempted_transition")


def test_dod001_evidence_result_has_required_summary_fields() -> None:
    module = _transition_graph_module()
    graph_path, graph = _load_canonical_graph()
    result = _call_required(module, "build_transition_graph_evidence_result", graph, source=str(graph_path))

    assert isinstance(result, dict), result
    assert result.get("dod_id") == "DOD-001", result
    assert result.get("status") == "ok", result
    assert result.get("graph_version") == graph["version"], result
    assert result.get("graph_hash") == graph["hash"], result
    assert result.get("checked_transitions"), result
    assert isinstance(result.get("gaps"), list), result
    assert result.get("severity") in {"info", "low", "medium", "high", "critical"}, result
    assert result.get("evidence_ref") == str(graph_path), result
    assert result.get("recommended_action"), result
    assert result.get("mapped_dod") == "DOD-001", result
    assert set(result.get("cross_references") or []) >= {"DOD-004", "DOD-005"}, result
    assert result.get("completed_dods") == ["DOD-001"], result


def test_repeated_on_reject_loop_is_bounded() -> None:
    module = _transition_graph_module()
    graph = _base_graph()
    attempts = [
        {
            "mst_session_id": SID,
            "attempted_transition": "terminal.completed",
            "failed_guard": "all_required_dod_done",
            "evidence_fingerprint": "objective_check_result=false;history_head=cccc",
            "on_reject": "continue.queued_action",
        }
        for _ in range(4)
    ]

    results = []
    prior: list[dict] = []
    for attempt in attempts:
        result = _call_required(module, "apply_on_reject_loop_guard", attempt, prior, graph, limit=3)
        assert isinstance(result, dict), result
        results.append(result)
        prior.append({**attempt, "result": result})

    assert [result.get("attempt_count") for result in results[:3]] == [1, 2, 3], results
    assert all(result.get("idempotency_key") for result in results), results
    assert results[0]["idempotency_key"] == results[1]["idempotency_key"] == results[2]["idempotency_key"], results
    terminal = results[-1]
    assert terminal.get("status") in {"terminal", "blocked", "rejected"}, terminal
    assert terminal.get("terminal_transition") in {
        "terminal.repeat_failure_limit",
        "terminal.state_inconsistency",
    }, terminal
    assert terminal.get("completed") is not True, terminal
    assert terminal.get("on_reject_retry_allowed") is False, terminal


def test_hook_boundary_uses_graph_on_reject_continuation() -> None:
    module = _transition_graph_module()
    graph = _base_graph()
    reject_result = {
        "status": "rejected",
        "accepted": False,
        "mst_session_id": SID,
        "graph_version": graph["version"],
        "graph_hash": graph["hash"],
        "transition": "terminal.completed",
        "failed_guards": ["all_required_dod_done", "no_next_action"],
        "required_evidence": ["objective_check_result", "history_head"],
        "on_reject": "continue.queued_action",
        "next_action": {"skill": "mst:approve", "source": "REQ-819"},
    }

    boundaries = [
        ("Stop", {"last_assistant_message": "All done.", "attempted_transition": "terminal.completed"}),
        ("Stop", {"last_assistant_message": "I will stop here for now.", "attempted_transition": "self_paced_stop"}),
        ("PreToolUse", {"tool_name": "AskUserQuestion", "attempted_transition": "user_wait"}),
        ("Stop", {"last_assistant_message": "Marking this completed early.", "attempted_transition": "premature_completed"}),
    ]
    for boundary, fixture in boundaries:
        block = _call_required(module, "build_hook_continuation_block", boundary, fixture, reject_result, graph)
        assert isinstance(block, dict), block
        assert block.get("decision") == "block", block
        assert block.get("hook_boundary") == boundary, block
        assert block.get("attempted_transition") in {
            "terminal.completed",
            "self_paced_stop",
            "user_wait",
            "premature_completed",
        }, block
        assert block.get("on_reject_transition") == "continue.queued_action", block
        assert block.get("graph_version") == graph["version"], block
        assert block.get("graph_hash") == graph["hash"], block
        assert isinstance(block.get("continuation"), dict), block
        assert block["continuation"].get("required_response") in {"continue", "inspect_only"}, block
        assert block["continuation"].get("next_action"), block

    normal = _call_required(
        module,
        "build_hook_pass_result",
        "Stop",
        {"last_assistant_message": "No graph violation; normal pass."},
        graph,
    )
    assert isinstance(normal, dict), normal
    assert normal.get("decision") == "approve", normal
    assert normal.get("full_state_prompt_injection") is False, normal
    assert normal.get("hot_path_full_graph_validation") is False, normal
    assert normal.get("hot_path_d2_rendering") is False, normal
    assert normal.get("hot_path_full_ledger_replay") is False, normal


def test_generated_graph_view_detects_drift_without_dod017_artifacts() -> None:
    module = _transition_graph_module()
    graph_path, graph = _load_canonical_graph()
    view_path = next((path for path in GENERATED_VIEW_CANDIDATES if path.is_file()), None)
    searched = "\n".join(f"- {path}" for path in GENERATED_VIEW_CANDIDATES)
    assert view_path is not None, f"DOD-016 generated graph view is missing. Searched:\n{searched}"
    view = _load_machine_readable(view_path) if view_path.suffix == ".json" else {"raw": view_path.read_text(encoding="utf-8")}

    result = _call_required(module, "validate_generated_graph_view", graph, view, source_graph_path=str(graph_path))
    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("source_graph_path") == str(graph_path), result
    assert result.get("graph_version") == graph["version"], result
    assert result.get("graph_hash") == graph["hash"], result
    assert set(result.get("covered_states") or []) >= set(_states(graph)), result
    assert set(result.get("covered_transitions") or []) >= set(_transitions(graph)), result
    assert result.get("drift_detected") is False, result

    drifted = copy.deepcopy(view)
    if isinstance(drifted.get("source_graph"), dict):
        drifted["source_graph"]["hash"] = "0" * 64
    else:
        drifted["source_graph"] = {"id": GRAPH_ID, "version": graph["version"], "hash": "0" * 64}
    drift_result = _call_required(module, "validate_generated_graph_view", graph, drifted, source_graph_path=str(graph_path))
    assert isinstance(drift_result, dict), drift_result
    assert drift_result.get("status") in {"error", "failed", "validation_failed"}, drift_result
    assert drift_result.get("drift_detected") is True, drift_result
    assert drift_result.get("fail_closed") is True, drift_result

    with tempfile.TemporaryDirectory() as raw:
        sandbox = Path(raw)
        _write_json(sandbox / "mst-transition-graph.json", graph)
        _write_json(sandbox / "mst-transition-graph-view.json", {"source_graph": {"hash": graph["hash"]}})
        forbidden_json = sandbox / "execution-flow.json"
        forbidden_d2 = sandbox / "execution-flow.d2"
        scan = _call_required(module, "scan_no_dod017_execution_flow_artifacts", sandbox)
        assert isinstance(scan, dict), scan
        assert scan.get("status") == "ok", scan
        assert scan.get("found") == [], scan
        _write_json(forbidden_json, {"schema_version": 1})
        forbidden_d2.write_text("active -> completed\n", encoding="utf-8")
        scan = _call_required(module, "scan_no_dod017_execution_flow_artifacts", sandbox)
        assert isinstance(scan, dict), scan
        assert scan.get("status") in {"error", "failed", "validation_failed"}, scan
        assert scan.get("fail_closed") is True, scan
        assert {Path(path).name for path in scan.get("found") or []} >= {"execution-flow.json", "execution-flow.d2"}, scan


TESTS: list[Callable[[], None]] = [
    test_graph_artifact_defines_machine_readable_contract,
    test_state_inventory_and_terminal_entry_coverage,
    test_equivalent_lifecycle_mappings_cover_known_gap_candidates,
    test_graph_schema_invariants_fail_closed,
    test_transition_validator_requires_explicit_envelope,
    test_transition_validator_splits_completion_reject_paths,
    test_dod001_evidence_result_has_required_summary_fields,
    test_repeated_on_reject_loop_is_bounded,
    test_hook_boundary_uses_graph_on_reject_continuation,
    test_generated_graph_view_detects_drift_without_dod017_artifacts,
]


def _selected_tests(pattern: str | None) -> Iterable[Callable[[], None]]:
    if not pattern:
        return TESTS
    terms = [term.strip() for term in re.split(r"\s+or\s+", pattern) if term.strip()]
    return [test for test in TESTS if any(term in test.__name__ for term in terms)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", dest="pattern", default=None)
    args = parser.parse_args()

    selected = list(_selected_tests(args.pattern))
    if not selected:
        print(f"No tests selected for -k {args.pattern!r}", file=sys.stderr)
        return 5

    failures = 0
    for test in selected:
        try:
            test()
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}", file=sys.stderr)
            traceback.print_exc()
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
