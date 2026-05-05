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
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SID = "MST-AGI-030-20260506T010203000Z-dod017aa"
ROOT = "AGI-030"
REQ = "REQ-820"
LEDGER_PATH = f".gran-maestro/sessions/{SID}/history.ndjson"
GRAPH_ID = "mst-transition-graph"
GRAPH_VERSION = "2026-05-05.dod016-contract"
GRAPH_HASH = "8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79"

REQUIRED_EVENT_FAMILIES = {
    "skill.enter",
    "skill.step",
    "skill.exit",
    "skill.recover",
    "continue.*",
    "guard.*",
    "terminal.*",
    "context.compacted",
    "context.rehydrated",
    "action.*",
    "blocker.*",
}

REQUIRED_HEAD_FIELDS = {
    "ledger_path",
    "mst_session_id",
    "last_event_id",
    "last_event_seq",
    "cumulative_hash",
    "event_count",
    "ledger_schema_version",
    "history_head",
}

DECISION_CONSUMERS = {
    "validator_judgement",
    "next_action_decision",
    "auto_write",
    "handoff_consumption",
}


def _execution_flow_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.execution_flow")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-017 execution-flow module is missing: expected scripts.mst_cmds.execution_flow"
        ) from exc


def _call_required(module: object, name: str, *args: object, **kwargs: object) -> Any:
    fn = getattr(module, name, None)
    assert callable(fn), f"scripts.mst_cmds.execution_flow.{name} must be callable"
    return fn(*args, **kwargs)


def _transition_graph_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.transition_graph")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-016 transition graph module is missing: expected scripts.mst_cmds.transition_graph"
        ) from exc


def _json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    encoded = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev_hash}\n{encoded}".encode("utf-8")).hexdigest()


def _event_family(event_type: str) -> str:
    if event_type in {"skill.enter", "skill.step", "skill.exit", "skill.recover"}:
        return event_type
    if event_type in {"context.compacted", "context.rehydrated"}:
        return event_type
    if "." in event_type:
        return f"{event_type.split('.', 1)[0]}.*"
    return event_type


def _history_head(events: list[dict[str, Any]]) -> dict[str, Any]:
    cumulative_hash = "0" * 64
    last_event_id = ""
    rows = []
    for seq, event in enumerate(events, 1):
        last_event_id = str(event["event_id"])
        cumulative_hash = _event_hash(cumulative_hash, event)
        rows.append(
            {
                "schema_version": 1,
                "seq": seq,
                "event_hash": cumulative_hash,
                "prev_hash": rows[-1]["event_hash"] if rows else "0" * 64,
                "event": event,
            }
        )
    return {
        "ledger_path": LEDGER_PATH,
        "mst_session_id": SID,
        "last_event_id": last_event_id,
        "last_event_seq": len(events),
        "cumulative_hash": cumulative_hash,
        "event_count": len(events),
        "ledger_schema_version": 1,
        "history_head": cumulative_hash,
        "rows": rows,
    }


def _event(event_type: str, seq: int, **payload: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "event_id": f"evt-{seq:03d}",
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "event_type": event_type,
        "created_at": f"2026-05-06T01:02:{seq:02d}.000Z",
        "idempotency_key": f"{SID}:{event_type}:{seq:03d}",
    }
    base.update(payload)
    return base


def _required_family_events() -> list[dict[str, Any]]:
    return [
        _event("skill.enter", 1, skill="mst:request", artifact_id=REQ, step=1),
        _event("skill.step", 2, skill="mst:request", artifact_id=REQ, step=2),
        _event("action.queued", 3, next_action={"skill": "mst:approve", "source_id": REQ}),
        _event("continue.queued_action", 4, transition="continue.queued_action"),
        _event("action.started", 5, action_id="approve-req-820"),
        _event("context.compacted", 6, current_node="mst:request.step-2"),
        _event("skill.recover", 7, skill="mst:request", artifact_id=REQ, step=2),
        _event("context.rehydrated", 8, rehydration_transition="continue.rehydrate_retry"),
        _event("guard.inspect_only_verification", 9, mismatch_subject="projection_head"),
        _event("blocker.detected", 10, blocker={"type": "state_inconsistency", "critical": False}),
        _event("blocker.resolved", 11, blocker={"type": "state_inconsistency"}),
        _event("action.completed", 12, action_id="approve-req-820"),
        _event("skill.exit", 13, skill="mst:request", artifact_id=REQ, status="done"),
        _event("terminal.completed", 14, transition="terminal.completed"),
    ]


def _ledger_fixture(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    event_list = events or _required_family_events()
    head = _history_head(event_list)
    return {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "ledger_path": LEDGER_PATH,
        "verified": True,
        "source": {key: value for key, value in head.items() if key != "rows"},
        "rows": head["rows"],
    }


def _source_head() -> dict[str, Any]:
    return dict(_ledger_fixture()["source"])


def _projection_fixture(*, stale: bool = False) -> dict[str, Any]:
    source = _source_head()
    history_head = "f" * 64 if stale else source["history_head"]
    return {
        "schema_version": 1,
        "projection_schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "source": {
            **source,
            "source_hash": source["cumulative_hash"],
            "history_head": history_head,
            "projection_created_at": "2026-05-06T01:03:00.000Z",
        },
        "projection_hash": _json_hash({"sid": SID, "history_head": history_head}),
        "current_node": "mst:request.step-2",
        "last_transition": "continue.rehydrate_retry",
        "next_action": {"skill": "mst:approve", "source_id": REQ},
        "nodes": [
            {"id": "mst:request.step-1", "kind": "skill.enter", "artifact_id": REQ},
            {"id": "mst:request.step-2", "kind": "skill.step", "artifact_id": REQ},
            {"id": "handoff.compacted", "kind": "context.compacted"},
            {"id": "handoff.rehydrated", "kind": "context.rehydrated"},
        ],
        "edges": [
            {
                "from": "mst:request.step-1",
                "to": "mst:request.step-2",
                "transition": "continue.queued_action",
            },
            {
                "from": "handoff.compacted",
                "to": "handoff.rehydrated",
                "transition": "continue.rehydrate_retry",
            },
        ],
        "coverage": {
            "recognized_event_families": sorted(REQUIRED_EVENT_FAMILIES),
            "missing_event_families": [],
            "required_event_families": sorted(REQUIRED_EVENT_FAMILIES),
        },
        "views": {
            "execution_flow_json": f".gran-maestro/sessions/{SID}/execution-flow.json",
            "execution_flow_d2": f".gran-maestro/sessions/{SID}/execution-flow.d2",
            "dashboard_flow_view": f"/dashboard/sessions/{SID}/flow",
            "cli_flow_view": f"mst.py session flow {SID}",
        },
        "handoff_summary": {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "history_head": history_head,
            "current_node": "mst:request.step-2",
            "last_transition": "context.compacted",
            "next_action": {"skill": "mst:approve", "source_id": REQ},
            "critical_blocker": None,
            "flow_view": {
                "execution_flow_json": f".gran-maestro/sessions/{SID}/execution-flow.json",
                "execution_flow_d2": f".gran-maestro/sessions/{SID}/execution-flow.d2",
            },
        },
    }


def _base_graph() -> dict[str, Any]:
    graph = {
        "schema_version": 1,
        "id": GRAPH_ID,
        "version": GRAPH_VERSION,
        "states": {
            "active": {"terminal": False},
            "inspecting": {"terminal": False},
            "blocked": {"terminal": False},
            "completed": {"terminal": True},
            "failed": {"terminal": True},
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
            "terminal.state_inconsistency": {
                "from": ["active", "inspecting"],
                "to": "failed",
                "auto_allowed": False,
                "write_allowed": True,
                "guards": ["state_contract_failed"],
                "required_evidence": ["mismatch_subject", "history_head"],
                "on_reject": "terminal.repeat_failure_limit",
            },
        },
        "evidence_producers": {
            "next_action": ["state_snapshot", "recover_bundle"],
            "history_head": ["history_ledger"],
            "mismatch_subject": ["validator"],
            "objective_check_result": ["mst.py agile objective-check"],
        },
        "semantic_invariants": [],
    }
    graph["hash"] = GRAPH_HASH
    return graph


def _diagnostic_codes(result: dict[str, Any]) -> set[str]:
    diagnostics = result.get("diagnostics")
    assert isinstance(diagnostics, list) and diagnostics, result
    return {
        str(item.get("code") or item.get("field") or "")
        for item in diagnostics
        if isinstance(item, dict)
    }


def _assert_fail_closed(result: object, *, expected_code: str | None = None) -> dict[str, Any]:
    assert isinstance(result, dict), f"result must be a structured dict, got {type(result).__name__}"
    assert result.get("status") in {"error", "failed", "validation_failed", "rejected", "stale", "inspect_only"}, result
    assert result.get("accepted") is not True, result
    assert result.get("fail_closed") is True, result
    assert result.get("trusted_output_generated") is not True, result
    if expected_code is not None:
        assert expected_code in _diagnostic_codes(result), result
    return result


def test_ledger_replay_accepts_required_event_families() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    result = _call_required(module, "replay_ledger_execution_flow", ledger)
    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("source_kind") == "verified_history_ledger", result
    assert result.get("mst_session_id") == SID, result
    assert result.get("history_head") == ledger["source"]["history_head"], result
    assert set(result.get("recognized_event_families") or []) >= REQUIRED_EVENT_FAMILIES, result
    assert result.get("missing_event_families") == [], result
    assert result.get("derived_artifact") is True, result
    assert result.get("current_node"), result
    assert isinstance(result.get("nodes"), list) and result["nodes"], result
    assert isinstance(result.get("edges"), list) and result["edges"], result

    incomplete_events = [
        event for event in _required_family_events() if _event_family(event["event_type"]) != "blocker.*"
    ]
    missing = _call_required(module, "replay_ledger_execution_flow", _ledger_fixture(incomplete_events))
    _assert_fail_closed(missing, expected_code="missing_event_family")
    assert "blocker.*" in set(missing.get("missing_event_families") or []), missing


def test_generated_execution_flow_is_derived_only() -> None:
    module = _execution_flow_module()
    envelope = {
        "schema_version": 1,
        "mst_session_id": SID,
        "verified_history_ledger": _ledger_fixture(),
        "dod016_transition_graph": _base_graph(),
        "generated_artifacts": {
            "execution_flow_json": _projection_fixture(),
            "execution_flow_d2": "mst_request_step_1 -> mst_request_step_2: continue.queued_action",
            "dashboard_cli_view": {"current_node": "mst:request.step-2"},
            "compaction_handoff_summary": _projection_fixture()["handoff_summary"],
            "snapshot_cache": {"next_action": {"skill": "mst:wrong"}},
            "prompt_summary": {"next_action": {"skill": "mst:wrong"}},
        },
        "decision_consumers": sorted(DECISION_CONSUMERS),
    }
    result = _call_required(module, "validate_execution_flow_source_boundary", envelope)
    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("source_of_truth") == {
        "actual_execution_flow": "verified_history_ledger",
        "transition_authority": "dod016_transition_graph",
    }, result
    assert result.get("generated_artifacts_used_for_decision") is False, result
    assert set(result.get("decision_sources") or []) == {"verified_history_ledger", "dod016_transition_graph"}, result
    assert set(result.get("rejected_sources") or []) >= {
        "execution-flow.json",
        "execution-flow.d2",
        "dashboard/CLI view",
        "compaction handoff summary",
        "snapshot/cache/prompt summary",
    }, result
    artifact_roles = result.get("artifact_roles")
    assert isinstance(artifact_roles, dict), result
    for name in (
        "execution_flow_json",
        "execution_flow_d2",
        "dashboard_cli_view",
        "compaction_handoff_summary",
        "snapshot_cache",
        "prompt_summary",
    ):
        assert artifact_roles.get(name) in {"derived_only", "display_only", "auxiliary_only"}, result


def test_source_ledger_head_requires_minimum_evidence() -> None:
    module = _execution_flow_module()
    valid = _call_required(module, "validate_source_ledger_head", _source_head())
    assert isinstance(valid, dict), valid
    assert valid.get("status") == "ok", valid
    assert valid.get("accepted") is True, valid

    for field in sorted(REQUIRED_HEAD_FIELDS):
        invalid = _source_head()
        invalid.pop(field)
        result = _call_required(module, "validate_source_ledger_head", invalid)
        _assert_fail_closed(result, expected_code="missing_source_ledger_head_field")
        assert result.get("missing_fields") == [field], result
        assert result.get("projection_generation_allowed") is False, result
        assert result.get("projection_consumption_allowed") is False, result


def test_stale_projection_rejects_decision_consumption() -> None:
    module = _execution_flow_module()
    stale_projection = _projection_fixture(stale=True)
    current_head = _source_head()
    result = _call_required(
        module,
        "validate_projection_consumption",
        stale_projection,
        current_head,
        consumers=sorted(DECISION_CONSUMERS),
    )
    _assert_fail_closed(result, expected_code="stale_projection")
    assert result.get("stale") is True, result
    assert result.get("read_only") is True, result
    assert result.get("regenerate_required") is True, result
    assert result.get("source_history_head") == stale_projection["source"]["history_head"], result
    assert result.get("current_history_head") == current_head["history_head"], result
    consumer_permissions = result.get("consumer_permissions")
    assert isinstance(consumer_permissions, dict), result
    assert set(consumer_permissions) >= DECISION_CONSUMERS, result
    assert not any(consumer_permissions[consumer] for consumer in DECISION_CONSUMERS), result
    assert result.get("on_stale_transition") in {
        "guard.inspect_only_verification",
        "terminal.state_inconsistency",
    }, result


def test_projection_generator_writes_json_with_source_provenance() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    with tempfile.TemporaryDirectory() as raw:
        output_dir = Path(raw) / ".gran-maestro" / "sessions" / SID
        result = _call_required(
            module,
            "generate_execution_flow_artifacts",
            ledger,
            output_dir,
            projection_created_at="2026-05-06T01:03:00.000Z",
        )
        assert isinstance(result, dict), result
        assert result.get("status") == "ok", result
        json_path = Path(result["paths"]["execution_flow_json"])
        assert json_path == output_dir / "execution-flow.json", result
        assert json_path.is_file(), result
        projection = json.loads(json_path.read_text(encoding="utf-8"))

    assert projection.get("schema_version") == 1, projection
    assert projection.get("projection_schema_version") == 1, projection
    assert projection.get("projection_kind") == "dod017.execution-flow", projection
    assert projection.get("mst_session_id") == SID, projection
    assert projection.get("root_mst_id") == ROOT, projection
    source = projection.get("source")
    assert isinstance(source, dict), projection
    assert source.get("ledger_path") == ledger["source"]["ledger_path"], projection
    assert source.get("history_head") == ledger["source"]["history_head"], projection
    assert source.get("source_hash") == ledger["source"]["cumulative_hash"], projection
    assert projection.get("projection_created_at") == "2026-05-06T01:03:00.000Z", projection
    assert source.get("projection_created_at") == projection.get("projection_created_at"), projection
    assert isinstance(projection.get("projection_hash"), str) and len(projection["projection_hash"]) == 64, projection
    assert projection["projection_hash"] == _call_required(module, "compute_projection_hash", projection), projection
    assert projection.get("current_node"), projection
    assert projection.get("last_transition") == "terminal.completed", projection
    assert projection.get("next_action") == {"skill": "mst:approve", "source_id": REQ}, projection
    assert isinstance(projection.get("nodes"), list) and projection["nodes"], projection
    assert isinstance(projection.get("edges"), list) and projection["edges"], projection
    assert "blocker" in projection, projection


def test_projection_generator_writes_d2_with_provenance_status() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    with tempfile.TemporaryDirectory() as raw:
        output_dir = Path(raw) / ".gran-maestro" / "sessions" / SID
        result = _call_required(
            module,
            "generate_execution_flow_artifacts",
            ledger,
            output_dir,
            projection_created_at="2026-05-06T01:03:00.000Z",
        )
        assert result.get("status") == "ok", result
        d2_path = Path(result["paths"]["execution_flow_d2"])
        assert d2_path == output_dir / "execution-flow.d2", result
        assert d2_path.is_file(), result
        d2 = d2_path.read_text(encoding="utf-8")

    assert "source ledger:" in d2, d2
    assert ledger["source"]["ledger_path"] in d2, d2
    assert ledger["source"]["history_head"] in d2, d2
    assert "coverage:" in d2, d2
    assert "stale: false" in d2, d2
    assert "regenerate_required: false" in d2, d2
    assert "drift: false" in d2, d2
    assert "mst:request" in d2, d2
    assert "continue.queued_action" in d2, d2
    assert "context.compacted" in d2, d2


def test_projection_hash_tracks_generated_payload() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    first = _call_required(
        module,
        "build_execution_flow_projection",
        ledger,
        projection_created_at="2026-05-06T01:03:00.000Z",
    )
    assert first.get("status") == "ok", first
    first_payload = first["projection"]

    changed_events = _required_family_events()
    changed_events.insert(3, _event("skill.step", 15, skill="mst:approve", artifact_id=REQ, step=1))
    second = _call_required(
        module,
        "build_execution_flow_projection",
        _ledger_fixture(changed_events),
        projection_created_at="2026-05-06T01:03:00.000Z",
    )
    assert second.get("status") == "ok", second
    second_payload = second["projection"]

    assert first_payload["source"].keys() == second_payload["source"].keys(), (first_payload, second_payload)
    assert first_payload["projection_hash"] != second_payload["projection_hash"], (first_payload, second_payload)
    assert first_payload["projection_hash"] == _call_required(module, "compute_projection_hash", first_payload), first_payload
    assert second_payload["projection_hash"] == _call_required(module, "compute_projection_hash", second_payload), second_payload


def test_projection_generation_requires_verified_ledger_source() -> None:
    module = _execution_flow_module()
    invalid = _ledger_fixture()
    invalid["verified"] = False
    with tempfile.TemporaryDirectory() as raw:
        output_dir = Path(raw) / ".gran-maestro" / "sessions" / SID
        result = _call_required(module, "generate_execution_flow_artifacts", invalid, output_dir)
        _assert_fail_closed(result, expected_code="ledger_not_verified")
        assert not (output_dir / "execution-flow.json").exists(), result
        assert not (output_dir / "execution-flow.d2").exists(), result
        assert result.get("ledger_path") == invalid["source"]["ledger_path"], result
        assert result.get("current_head_evidence") == invalid["source"], result


def test_dashboard_flow_view_reports_execution_flow_provenance() -> None:
    module = _execution_flow_module()
    projection = _projection_fixture()
    current_head = _source_head()

    result = _call_required(module, "build_dashboard_flow_view", projection, current_head)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("view_kind") == "dod017.execution-flow.dashboard-view", result
    assert result.get("display_only") is True, result
    assert result.get("next_action_authority") is False, result
    assert result.get("transition_authority") == "dod016_transition_graph", result
    source = result.get("source")
    assert isinstance(source, dict), result
    assert source.get("ledger_path") == LEDGER_PATH, result
    assert source.get("history_head") == current_head["history_head"], result
    assert source.get("projection_schema_version") == 1, result
    assert source.get("projection_hash") == projection["projection_hash"], result
    assert source.get("source_kind") == "verified_history_ledger", result
    status = result.get("projection_status")
    assert isinstance(status, dict), result
    assert status.get("stale") is False, result
    assert status.get("drift") is False, result
    assert status.get("regenerate_required") is False, result
    assert status.get("read_only") is False, result
    coverage = result.get("coverage")
    assert isinstance(coverage, dict), result
    assert coverage.get("node_count") == len(projection["nodes"]), result
    assert coverage.get("edge_count") == len(projection["edges"]), result
    assert coverage.get("recognized_event_families") == projection["coverage"]["recognized_event_families"], result
    assert coverage.get("missing_event_families") == projection["coverage"]["missing_event_families"], result


def test_cli_flow_view_marks_stale_projection_read_only() -> None:
    module = _execution_flow_module()
    stale_projection = _projection_fixture(stale=True)
    current_head = _source_head()

    result = _call_required(module, "render_cli_flow_view", stale_projection, current_head)

    _assert_fail_closed(result, expected_code="stale_projection")
    assert result.get("view_kind") == "dod017.execution-flow.cli-view", result
    assert result.get("display_only") is True, result
    assert result.get("read_only") is True, result
    assert result.get("regenerate_required") is True, result
    assert result.get("next_action_authority") is False, result
    assert result.get("transition_authority") == "dod016_transition_graph", result
    text = result.get("text")
    assert isinstance(text, str), result
    lowered = text.lower()
    assert "stale" in lowered, text
    assert "read-only" in lowered, text
    assert "regenerate-required" in lowered, text
    assert "display-only" in lowered, text
    assert "not next-action authority" in lowered, text
    assert stale_projection["source"]["history_head"] in text, text
    assert current_head["history_head"] in text, text


def test_graph_and_execution_flow_views_are_separate_artifacts() -> None:
    module = _execution_flow_module()
    graph_view = {
        "schema_version": 1,
        "kind": "mst-transition-graph-view",
        "source_graph_path": "templates/state-machine/mst-transition-graph.json",
        "source_graph": {"id": GRAPH_ID, "version": GRAPH_VERSION, "hash": GRAPH_HASH},
        "covered_states": ["active", "inspecting", "completed", "failed"],
        "covered_transitions": ["continue.queued_action", "terminal.completed"],
    }
    projection = _projection_fixture()

    result = _call_required(module, "separate_graph_and_execution_flow_views", graph_view, projection)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("separated") is True, result
    assert result.get("transition_authority") == "dod016_transition_graph", result
    possible = result.get("possible_transition_graph")
    actual = result.get("actual_execution_flow")
    assert isinstance(possible, dict), result
    assert isinstance(actual, dict), result
    assert possible.get("label") == "DOD-016 possible-transition graph", result
    assert actual.get("label") == "DOD-017 actual execution-flow", result
    assert possible.get("schema_id") == "mst-transition-graph-view", result
    assert actual.get("schema_id") == "dod017.execution-flow", result
    assert possible.get("source_provenance") != actual.get("source_provenance"), result
    assert possible["source_provenance"].get("graph_hash") == GRAPH_HASH, result
    assert actual["source_provenance"].get("ledger_path") == LEDGER_PATH, result
    assert actual["source_provenance"].get("history_head") == projection["source"]["history_head"], result
    assert possible.get("source_of_truth") == "dod016_transition_graph", result
    assert actual.get("source_of_truth") == "verified_history_ledger", result
    assert actual.get("display_only") is True, result
    assert actual.get("next_action_authority") is False, result


def test_projection_never_authorizes_forbidden_graph_transition() -> None:
    module = _execution_flow_module()
    graph_module = _transition_graph_module()
    graph = _base_graph()
    projection = _projection_fixture()
    projection["edges"].append(
        {
            "from": "inspecting",
            "to": "completed",
            "transition": "terminal.completed",
            "projection_claim": "actual flow observed this transition",
        }
    )
    attempt = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "current_state": "inspecting",
        "attempted_transition": "terminal.completed",
        "evidence": {"objective_check_result": {"done": True}, "history_head": _source_head()["history_head"]},
    }

    graph_result = graph_module.validate_attempted_transition(copy.deepcopy(attempt), graph)
    assert isinstance(graph_result, dict), graph_result
    assert graph_result.get("accepted") is False, graph_result
    assert graph_result.get("fail_closed") is True, graph_result

    result = _call_required(
        module,
        "evaluate_projection_transition_authority",
        attempt,
        projection,
        graph,
    )
    _assert_fail_closed(result, expected_code="transition_graph_rejected")
    assert result.get("authority") == "dod016_transition_graph", result
    assert result.get("projection_authorized") is False, result
    assert result.get("projection_used_as_authority") is False, result
    assert result.get("attempted_transition") == "terminal.completed", result
    assert result.get("on_reject") == "continue.queued_action", result


def test_hook_hot_path_never_full_replays_or_renders() -> None:
    module = _execution_flow_module()
    calls: list[str] = []

    def forbidden(name: str) -> Callable[..., None]:
        def _inner(*_args: object, **_kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"hook hot path must not call {name}")

        return _inner

    envelope = {
        "schema_version": 1,
        "mst_session_id": SID,
        "hook_event_name": "Stop",
        "cursor_state": {"status": "stale", "history_head": "0" * 64},
        "cache_state": {"status": "miss"},
        "current_head_evidence": _source_head(),
        "queued_action": {"skill": "mst:approve", "source_id": REQ},
    }
    operations = {
        "full_ledger_replay": forbidden("full_ledger_replay"),
        "execution_flow_projection": forbidden("execution_flow_projection"),
        "d2_render": forbidden("d2_render"),
        "dashboard_render": forbidden("dashboard_render"),
    }
    result = _call_required(module, "evaluate_hook_hot_path", envelope, operations=operations)
    assert calls == [], calls
    assert isinstance(result, dict), result
    assert result.get("status") in {"inspect_only", "state_inconsistency", "validation_failed"}, result
    assert result.get("hot_path_full_ledger_replay") is False, result
    assert result.get("hot_path_execution_flow_projection") is False, result
    assert result.get("hot_path_d2_rendering") is False, result
    assert result.get("hot_path_dashboard_rendering") is False, result
    assert result.get("write_allowed") is False, result
    assert result.get("next_route") in {"guard.inspect_only_verification", "terminal.state_inconsistency"}, result


def test_hook_hot_path_uses_cursor_cache_for_current_flow_state() -> None:
    module = _execution_flow_module()
    head = _source_head()
    next_action = {"skill": "mst:approve", "source_id": REQ}
    envelope = {
        "schema_version": 1,
        "mst_session_id": SID,
        "hook_event_name": "PreToolUse",
        "cursor_state": {
            "status": "fresh",
            "history_head": head["history_head"],
            "current_node": "mst:request.step-2",
            "last_transition": "continue.queued_action",
            "next_action": next_action,
            "provenance": {
                "source": "history.verify cursor",
                "history_head": head["history_head"],
            },
        },
        "cache_state": {
            "status": "hit",
            "history_head": head["history_head"],
            "current_node": "mst:request.step-2",
            "last_transition": "continue.queued_action",
            "next_action": next_action,
            "provenance": {
                "source": "per-session current-state cache",
                "history_head": head["history_head"],
            },
        },
        "current_head_evidence": head,
        "queued_action": next_action,
    }
    calls: list[str] = []
    operations = {
        "full_ledger_replay": lambda *_args, **_kwargs: calls.append("full_ledger_replay"),
        "execution_flow_projection": lambda *_args, **_kwargs: calls.append("execution_flow_projection"),
        "d2_render": lambda *_args, **_kwargs: calls.append("d2_render"),
        "dashboard_render": lambda *_args, **_kwargs: calls.append("dashboard_render"),
    }

    result = _call_required(module, "evaluate_hook_hot_path", envelope, operations=operations)

    assert calls == [], calls
    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("accepted") is True, result
    assert result.get("fail_closed") is False, result
    assert result.get("current_node") == "mst:request.step-2", result
    assert result.get("last_transition") == "continue.queued_action", result
    assert result.get("next_action") == next_action, result
    assert result.get("history_head") == head["history_head"], result
    assert result.get("current_history_head") == head["history_head"], result
    assert result.get("hot_path_current_state_source") in {"cursor_state", "cache_state"}, result
    provenance = result.get("provenance")
    assert isinstance(provenance, dict), result
    assert provenance.get("cursor_state", {}).get("source") == "history.verify cursor", result
    assert provenance.get("cache_state", {}).get("source") == "per-session current-state cache", result
    assert result.get("hot_path_full_ledger_replay") is False, result
    assert result.get("hot_path_execution_flow_projection") is False, result
    assert result.get("hot_path_d2_rendering") is False, result
    assert result.get("hot_path_dashboard_rendering") is False, result


def test_hook_cache_miss_routes_to_inspect_only_without_replay() -> None:
    module = _execution_flow_module()
    head = _source_head()
    calls: list[str] = []

    def forbidden(name: str) -> Callable[..., None]:
        def _inner(*_args: object, **_kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"hook cache miss must not recover by {name}")

        return _inner

    envelope = {
        "schema_version": 1,
        "mst_session_id": SID,
        "hook_event_name": "PreToolUse",
        "cursor_state": {"status": "missing"},
        "cache_state": {"status": "miss"},
        "current_head_evidence": head,
        "queued_action": {"skill": "mst:approve", "source_id": REQ},
    }
    operations = {
        "full_ledger_replay": forbidden("full_ledger_replay"),
        "execution_flow_projection": forbidden("execution_flow_projection"),
        "d2_render": forbidden("d2_render"),
        "dashboard_render": forbidden("dashboard_render"),
    }

    result = _call_required(module, "evaluate_hook_hot_path", envelope, operations=operations)

    assert calls == [], calls
    _assert_fail_closed(result, expected_code="hook_current_state_cache_missing")
    assert result.get("status") == "inspect_only", result
    assert result.get("next_route") == "guard.inspect_only_verification", result
    assert result.get("next_safe_action") == "inspect-only state/history consistency verification", result
    assert result.get("mismatch_subject") in {"cursor_state", "cache_state", "hook_current_state_cache"}, result
    assert result.get("write_allowed") is False, result
    assert result.get("hot_path_full_ledger_replay") is False, result
    assert result.get("hot_path_execution_flow_projection") is False, result
    assert result.get("hot_path_d2_rendering") is False, result
    assert result.get("hot_path_dashboard_rendering") is False, result


def test_compaction_handoff_contains_cursor_provenance_and_flow_paths() -> None:
    module = _execution_flow_module()
    projection = _projection_fixture()
    current_head = _source_head()

    result = _call_required(
        module,
        "build_compaction_handoff_summary",
        projection,
        current_head,
        auto=True,
    )

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    handoff = result.get("handoff")
    assert isinstance(handoff, dict), result
    assert handoff["schema_version"] == 1
    assert handoff["mst_session_id"] == SID
    assert handoff["root_mst_id"] == ROOT
    assert handoff["history_head"] == current_head["history_head"]
    assert handoff["current_node"] == projection["current_node"]
    assert handoff["last_transition"] == projection["last_transition"]
    assert handoff["rehydration_transition"] == "continue.rehydrate_retry"
    assert handoff["next_action"] == projection["next_action"]
    assert handoff["auto"] is True
    assert "blocker" in handoff
    assert "critical_blocker" in handoff
    assert set(handoff.keys()) >= {
        "current_node",
        "last_transition",
        "next_action",
        "blocker",
        "critical_blocker",
        "history_head",
        "flow_view",
    }
    assert handoff["flow_view"] == {
        "execution_flow_json": f".gran-maestro/sessions/{SID}/execution-flow.json",
        "execution_flow_d2": f".gran-maestro/sessions/{SID}/execution-flow.d2",
    }
    assert "nodes" not in handoff
    assert "edges" not in handoff
    assert result.get("derived_from") == "verified_execution_flow_projection"
    assert result.get("trusted_output_generated") is True


def test_rehydration_context_prefers_verified_handoff_over_llm_summary() -> None:
    module = _execution_flow_module()
    current_head = _source_head()
    handoff = _projection_fixture()["handoff_summary"]
    handoff["last_transition"] = "context.compacted"
    handoff["auto"] = True
    llm_summary = {
        "current_node": "llm.summary.wrong",
        "last_transition": "terminal.completed",
        "next_action": {"skill": "mst:wrong", "source_id": "REQ-000"},
        "critical_blocker": {"type": "llm_guess"},
        "flow_view": {
            "execution_flow_json": ".gran-maestro/sessions/wrong/execution-flow.json",
            "execution_flow_d2": ".gran-maestro/sessions/wrong/execution-flow.d2",
        },
    }
    core = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "auto": True,
        "continuation": {
            "mode": "continue_unless_critical",
            "next_action": {"skill": "mst:approve", "source_id": REQ},
            "critical_blocker": None,
        },
        "current_skill": "mst:request",
        "current_step": 2,
        "total_steps": 5,
        "history_last_event_id": current_head["history_head"],
    }

    result = _call_required(
        module,
        "assemble_rehydration_continuation_context",
        core,
        handoff,
        llm_summary,
        current_head,
    )

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("context_delivery_order") == [
        "core_rehydration",
        "execution_flow_handoff",
        "prompt_summary",
    ]
    budgeted = result.get("budgeted_context")
    assert isinstance(budgeted, dict), result
    consumed = budgeted.get("execution_flow_handoff")
    assert isinstance(consumed, dict), result
    for field in ("current_node", "last_transition", "next_action", "critical_blocker", "flow_view"):
        assert consumed[field] == handoff[field], (field, consumed, handoff, result)
    assert consumed["current_node"] != llm_summary["current_node"]
    assert consumed["last_transition"] != llm_summary["last_transition"]
    assert consumed["next_action"] != llm_summary["next_action"]
    assert consumed["flow_view"] != llm_summary["flow_view"]
    assert result.get("prompt_summary_used_as_source") is False
    assert result.get("source_precedence") == [
        "verified_history_ledger",
        "verified_execution_flow_handoff",
        "prompt_summary_diagnostic_only",
    ]
    assert result.get("next_action_execution_allowed") is True
    assert result.get("write_allowed") is True


def test_context_compaction_and_rehydration_events_share_session_ledger() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    handoff = _projection_fixture()["handoff_summary"]

    result = _call_required(module, "append_context_handoff_evidence_events", ledger, handoff)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    updated = result.get("ledger")
    assert isinstance(updated, dict), result
    rows = updated.get("rows")
    assert isinstance(rows, list), result
    events = [row.get("event") for row in rows if isinstance(row, dict)]
    context_events = [
        event for event in events
        if isinstance(event, dict) and event.get("event_type") in {"context.compacted", "context.rehydrated"}
    ]
    assert {event["event_type"] for event in context_events} >= {"context.compacted", "context.rehydrated"}
    assert {event["mst_session_id"] for event in context_events} == {SID}
    assert {event["root_mst_id"] for event in context_events} == {ROOT}
    assert result.get("mst_session_id") == SID
    assert result.get("same_session_ledger") is True
    assert result.get("event_append_evidence") == {
        "compacted": "context.compacted",
        "rehydrated": "context.rehydrated",
        "handoff_generated": True,
        "handoff_consumed": True,
    }
    rehydrated = [event for event in context_events if event["event_type"] == "context.rehydrated"][-1]
    assert rehydrated["execution_flow_handoff"]["history_head"] == handoff["history_head"]
    assert rehydrated["prompt_summary_used_as_source"] is False


def test_stale_handoff_blocks_auto_write_and_next_action() -> None:
    module = _execution_flow_module()
    current_head = _source_head()
    handoff = _projection_fixture()["handoff_summary"]
    handoff["history_head"] = "e" * 64

    result = _call_required(module, "validate_compaction_handoff_consumption", handoff, current_head)

    _assert_fail_closed(result, expected_code="stale_handoff")
    assert result.get("stale") is True, result
    assert result.get("write_allowed") is False, result
    assert result.get("auto_write_allowed") is False, result
    assert result.get("next_action_execution_allowed") is False, result
    assert result.get("on_stale_transition") == "guard.inspect_only_verification", result
    assert result.get("source_history_head") == "e" * 64, result
    assert result.get("current_history_head") == current_head["history_head"], result
    diagnostic = result["diagnostics"][0]
    assert diagnostic["field"] == "history_head"
    assert diagnostic["reason"]


def test_compaction_handoff_does_not_modify_claude_code_core() -> None:
    module = _execution_flow_module()
    changed_paths = [
        "scripts/mst_cmds/execution_flow.py",
        "scripts/mst_cmds/state.py",
        "hooks/mst-stop-hook.sh",
        "tests/test_dod017_execution_flow_projection_contract.py",
    ]

    result = _call_required(module, "validate_gran_maestro_owned_handoff_scope", changed_paths)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("claude_code_core_modified") is False, result
    assert result.get("allowed_surface") == "gran_maestro_owned", result

    forbidden = _call_required(
        module,
        "validate_gran_maestro_owned_handoff_scope",
        ["/Users/brandev/git/claude-code/src/query.ts"],
    )
    _assert_fail_closed(forbidden, expected_code="claude_code_core_scope_violation")
    assert forbidden.get("claude_code_core_modified") is True, forbidden


TESTS: list[Callable[[], None]] = [
    test_ledger_replay_accepts_required_event_families,
    test_generated_execution_flow_is_derived_only,
    test_source_ledger_head_requires_minimum_evidence,
    test_projection_generator_writes_json_with_source_provenance,
    test_projection_generator_writes_d2_with_provenance_status,
    test_stale_projection_rejects_decision_consumption,
    test_projection_hash_tracks_generated_payload,
    test_projection_generation_requires_verified_ledger_source,
    test_dashboard_flow_view_reports_execution_flow_provenance,
    test_cli_flow_view_marks_stale_projection_read_only,
    test_graph_and_execution_flow_views_are_separate_artifacts,
    test_projection_never_authorizes_forbidden_graph_transition,
    test_hook_hot_path_never_full_replays_or_renders,
    test_hook_hot_path_uses_cursor_cache_for_current_flow_state,
    test_hook_cache_miss_routes_to_inspect_only_without_replay,
    test_compaction_handoff_contains_cursor_provenance_and_flow_paths,
    test_rehydration_context_prefers_verified_handoff_over_llm_summary,
    test_context_compaction_and_rehydration_events_share_session_ledger,
    test_stale_handoff_blocks_auto_write_and_next_action,
    test_compaction_handoff_does_not_modify_claude_code_core,
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
