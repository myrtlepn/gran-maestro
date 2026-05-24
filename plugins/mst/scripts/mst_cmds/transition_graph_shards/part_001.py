from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from typing import Any
REQUIRED_GRAPH_FIELDS = {
    "schema_version",
    "id",
    "version",
    "hash",
    "states",
    "transitions",
    "semantic_invariants",
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
REQUIRED_LIFECYCLE_MAPPING_IDS = {
    "blocked.resume_confirmed",
    "terminal.user_cancelled.lifecycle",
    "terminal.completed.reject_split",
}
GRAPH_ID = "mst-transition-graph"
VIEW_KIND = "mst-transition-graph-view"
def compute_graph_hash(graph: dict[str, Any]) -> str:
    without_hash = copy.deepcopy(graph)
    without_hash.pop("hash", None)
    encoded = json.dumps(without_hash, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
def load_transition_graph(path: str | Path) -> dict[str, Any]:
    graph_path = Path(path)
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"transition graph must be a JSON object: {graph_path}")
    return payload
def _iso_utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _diag(
    code: str,
    *,
    field: str,
    path: str,
    reason: str,
    graph: dict[str, Any],
    source: str | None,
) -> dict[str, Any]:
    return {
        "code": code,
        "field": field,
        "path": path,
        "reason": reason,
        "source": source,
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
    }
def _failure(
    diagnostics: list[dict[str, Any]],
    *,
    graph: dict[str, Any],
    source: str | None,
    drift_detected: bool = False,
) -> dict[str, Any]:
    return {
        "status": "validation_failed",
        "accepted": False,
        "fail_closed": True,
        "created_new_session": False,
        "silent_migration": False,
        "default_pass": False,
        "target": "transition_graph",
        "source": source,
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "drift_detected": drift_detected,
        "diagnostics": diagnostics,
    }
def _ok(graph: dict[str, Any], *, source: str | None) -> dict[str, Any]:
    return {
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "created_new_session": False,
        "target": "transition_graph",
        "source": source,
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "diagnostics": [],
    }
def _attempt_failure(
    diagnostics: list[dict[str, Any]],
    *,
    graph: dict[str, Any],
    envelope: dict[str, Any] | None = None,
    transition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = envelope if isinstance(envelope, dict) else {}
    transition_id = envelope.get("attempted_transition")
    return {
        "status": "validation_failed",
        "accepted": False,
        "fail_closed": True,
        "created_new_session": False,
        "silent_migration": False,
        "default_pass": False,
        "target": "attempted_transition",
        "mst_session_id": envelope.get("mst_session_id"),
        "root_mst_id": envelope.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "current_state": envelope.get("current_state"),
        "transition": transition_id,
        "target_state": transition.get("to") if isinstance(transition, dict) else None,
        "on_reject": transition.get("on_reject") if isinstance(transition, dict) else None,
        "diagnostics": diagnostics,
    }
def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)
def _declared_evidence(graph: dict[str, Any]) -> set[str]:
    producers = graph.get("evidence_producers")
    return set(producers) if isinstance(producers, dict) else set()
def _declared_guards(graph: dict[str, Any]) -> set[str] | None:
    guards = graph.get("guards")
    if isinstance(guards, dict):
        return set(guards)
    if isinstance(guards, list) and all(isinstance(item, str) for item in guards):
        return set(guards)
    return None
def _lifecycle_mappings(graph: dict[str, Any]) -> dict[str, Any]:
    mappings = graph.get("lifecycle_mappings")
    return mappings if isinstance(mappings, dict) else {}
def _reachable_nonterminal_states(states: dict[str, Any], transitions: dict[str, Any]) -> set[str]:
    reachable = {"active"} if "active" in states else set()
    changed = True
    while changed:
        changed = False
        for transition in transitions.values():
            if not isinstance(transition, dict):
                continue
            from_states = transition.get("from")
            to_state = transition.get("to")
            if not isinstance(from_states, list) or not isinstance(to_state, str):
                continue
            if any(state in reachable for state in from_states) and to_state not in reachable:
                reachable.add(to_state)
                changed = True
    return {
        name
        for name, state in states.items()
        if isinstance(state, dict) and state.get("terminal") is False and name in reachable
    }
def _validate_generated_view_coverage(
    graph: dict[str, Any],
    generated_view: dict[str, Any],
    *,
    source: str | None,
) -> list[dict[str, Any]]:
    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    covered_states = set(generated_view.get("covered_states") or [])
    covered_transitions = set(generated_view.get("covered_transitions") or [])
    missing_states = sorted(set(states) - covered_states)
    missing_transitions = sorted(set(transitions) - covered_transitions)
    diagnostics: list[dict[str, Any]] = []
    if missing_states or missing_transitions:
        diagnostics.append(
            _diag(
                "generated_view_coverage",
                field="generated_view",
                path="generated_view",
                reason="generated graph view does not cover all states and transitions",
                graph=graph,
                source=source,
            )
            | {
                "missing_states": missing_states,
                "missing_transitions": missing_transitions,
            }
        )

    nodes = generated_view.get("nodes")
    if isinstance(nodes, list):
        node_ids = {
            item.get("id")
            for item in nodes
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        missing_node_states = sorted(set(states) - node_ids)
        if missing_node_states:
            diagnostics.append(
                _diag(
                    "generated_view_coverage",
                    field="nodes",
                    path="generated_view.nodes",
                    reason="generated graph view nodes do not cover all graph states",
                    graph=graph,
                    source=source,
                )
                | {"missing_states": missing_node_states}
            )

    edges = generated_view.get("edges")
    if isinstance(edges, list):
        edge_transitions = {
            item.get("transition") or item.get("transition_id")
            for item in edges
            if isinstance(item, dict) and isinstance(item.get("transition") or item.get("transition_id"), str)
        }
        missing_edge_transitions = sorted(set(transitions) - edge_transitions)
        if missing_edge_transitions:
            diagnostics.append(
                _diag(
                    "generated_view_coverage",
                    field="edges",
                    path="generated_view.edges",
                    reason="generated graph view edges do not cover all graph transitions",
                    graph=graph,
                    source=source,
                )
                | {"missing_transitions": missing_edge_transitions}
            )
    return diagnostics
def _mapping_sources(mapping: dict[str, Any]) -> list[str]:
    sources = mapping.get("from")
    if isinstance(sources, list):
        return [str(source) for source in sources if isinstance(source, str) and source.strip()]
    if isinstance(sources, str) and sources.strip():
        return [sources.strip()]
    return []
def _mapping_reject_targets(mapping: dict[str, Any]) -> list[str]:
    on_reject = mapping.get("on_reject")
    if isinstance(on_reject, str) and on_reject.strip():
        return [on_reject.strip()]
    if isinstance(on_reject, dict):
        return [value for value in on_reject.values() if isinstance(value, str) and value.strip()]
    return []
def _validate_lifecycle_mapping_payload(
    graph: dict[str, Any],
    *,
    source: str | None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    evidence_keys = _declared_evidence(graph)
    guard_names = _declared_guards(graph)
    mappings_raw = graph.get("lifecycle_mappings")
    mappings = mappings_raw if isinstance(mappings_raw, dict) else {}

    if not isinstance(mappings_raw, dict):
        diagnostics.append(
            _diag(
                "lifecycle_mapping",
                field="lifecycle_mappings",
                path="lifecycle_mappings",
                reason="lifecycle_mappings must be an object containing equivalent lifecycle records",
                graph=graph,
                source=source,
            )
        )
    for mapping_id in sorted(REQUIRED_LIFECYCLE_MAPPING_IDS - set(mappings)):
        diagnostics.append(
            _diag(
                "lifecycle_mapping",
                field="lifecycle_mappings",
                path=f"lifecycle_mappings.{mapping_id}",
                reason="required equivalent lifecycle mapping is missing",
                graph=graph,
                source=source,
            )
        )

    for mapping_id, mapping in mappings.items():
        path = f"lifecycle_mappings.{mapping_id}"
        if not isinstance(mapping, dict):
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="lifecycle_mappings",
                    path=path,
                    reason="lifecycle mapping must be an object",
                    graph=graph,
                    source=source,
                )
            )
            continue
        for field in sorted(REQUIRED_LIFECYCLE_MAPPING_FIELDS - set(mapping)):
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field=field,
                    path=f"{path}.{field}",
                    reason=f"{field} is required for equivalent lifecycle mapping",
                    graph=graph,
                    source=source,
                )
            )
        if mapping.get("id") != mapping_id:
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="id",
                    path=f"{path}.id",
                    reason="lifecycle mapping id must match its object key",
                    graph=graph,
                    source=source,
                )
                | {"actual": mapping.get("id"), "expected": mapping_id}
            )
        from_states = _mapping_sources(mapping)
        if not from_states:
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="from",
                    path=f"{path}.from",
                    reason="lifecycle mapping from must include one or more source states or *",
                    graph=graph,
                    source=source,
                )
            )
        for state in from_states:
            if state != "*" and state not in states:
                diagnostics.append(
                    _diag(
                        "lifecycle_mapping",
                        field="from",
                        path=f"{path}.from",
                        reason=f"lifecycle mapping references undefined source state: {state}",
                        graph=graph,
                        source=source,
                    )
                )
        to_state = mapping.get("to")
        if not isinstance(to_state, str) or to_state not in states:
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="to",
                    path=f"{path}.to",
                    reason=f"lifecycle mapping target state is undefined: {to_state}",
                    graph=graph,
                    source=source,
                )
            )
        elif isinstance(states.get(to_state), dict) and mapping.get("terminal") != states[to_state].get("terminal"):
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="terminal",
                    path=f"{path}.terminal",
                    reason="lifecycle mapping terminal flag must match its target state",
                    graph=graph,
                    source=source,
                )
            )
        for bool_field in ("auto_allowed", "write_allowed"):
            if not isinstance(mapping.get(bool_field), bool):
                diagnostics.append(
                    _diag(
                        "lifecycle_mapping",
                        field=bool_field,
                        path=f"{path}.{bool_field}",
                        reason=f"{bool_field} must be a bool",
                        graph=graph,
                        source=source,
                    )
                )
        guards = mapping.get("guards")
        if not _string_list(guards):
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="guards",
                    path=f"{path}.guards",
                    reason="lifecycle mapping guards must be a list of guard names",
                    graph=graph,
                    source=source,
                )
            )
        elif guard_names is not None:
            for guard in guards:
                if guard not in guard_names:
                    diagnostics.append(
                        _diag(
                            "lifecycle_mapping",
                            field="guards",
                            path=f"{path}.guards",
                            reason=f"lifecycle mapping guard is not declared: {guard}",
                            graph=graph,
                            source=source,
                        )
                    )
        required_evidence = mapping.get("required_evidence")
        if not _string_list(required_evidence):
            diagnostics.append(
                _diag(
                    "lifecycle_mapping",
                    field="required_evidence",
                    path=f"{path}.required_evidence",
                    reason="lifecycle mapping required_evidence must be a list of evidence keys",
                    graph=graph,
                    source=source,
                )
            )
        elif evidence_keys:
            for evidence in required_evidence:
                if evidence not in evidence_keys:
                    diagnostics.append(
                        _diag(
                            "lifecycle_mapping",
                            field="required_evidence",
                            path=f"{path}.required_evidence",
                            reason=f"lifecycle mapping required evidence has no declared producer: {evidence}",
                            graph=graph,
                            source=source,
                        )
                    )
        for target in _mapping_reject_targets(mapping):
            if target not in transitions:
                diagnostics.append(
                    _diag(
                        "lifecycle_mapping",
                        field="on_reject",
                        path=f"{path}.on_reject",
                        reason=f"lifecycle mapping on_reject references undefined transition: {target}",
                        graph=graph,
                        source=source,
                    )
                )
        for string_field in ("ledger_event_family", "projection_rule", "reject_failure_path"):
            if not isinstance(mapping.get(string_field), str) or not mapping.get(string_field).strip():
                diagnostics.append(
                    _diag(
                        "lifecycle_mapping",
                        field=string_field,
                        path=f"{path}.{string_field}",
                        reason=f"{string_field} must be a non-empty string",
                        graph=graph,
                        source=source,
                    )
                )
    return diagnostics
def _paths_match(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    actual_path = Path(actual)
    expected_path = Path(expected)
    if not actual_path.is_absolute() and expected_path.as_posix().endswith(actual_path.as_posix()):
        return True
    if not expected_path.is_absolute() and actual_path.as_posix().endswith(expected_path.as_posix()):
        return True
    return False
def build_generated_graph_view(
    graph: dict[str, Any],
    source_graph_path: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    nodes = [
        {
            "id": state_id,
            "label": state_id,
            "terminal": state.get("terminal") if isinstance(state, dict) else None,
        }
        for state_id, state in states.items()
    ]
    edges: list[dict[str, Any]] = []
    for transition_id, transition in transitions.items():
        if not isinstance(transition, dict):
            continue
        from_states = transition.get("from") if isinstance(transition.get("from"), list) else []
        to_state = transition.get("to")
        for from_state in from_states:
            if not isinstance(from_state, str) or not isinstance(to_state, str):
                continue
            edges.append(
                {
                    "id": f"{transition_id}:{from_state}->{to_state}",
                    "source": from_state,
                    "target": to_state,
                    "transition": transition_id,
                    "label": transition_id,
                    "auto_allowed": transition.get("auto_allowed"),
                    "write_allowed": transition.get("write_allowed"),
                }
            )
    return {
        "schema_version": 1,
        "kind": VIEW_KIND,
        "source_graph_path": source_graph_path,
        "source_graph": {
            "id": graph.get("id"),
            "version": graph.get("version"),
            "hash": graph.get("hash"),
        },
        "generated_at": generated_at or _iso_utc_now(),
        "covered_states": list(states),
        "covered_transitions": list(transitions),
        "nodes": nodes,
        "edges": edges,
    }
def graph_consumer_identity(graph: dict[str, Any], consumer: str = "generated_view_builder") -> dict[str, Any]:
    return {
        "consumer": consumer,
        "graph_id": graph.get("id") if isinstance(graph, dict) else None,
        "graph_version": graph.get("version") if isinstance(graph, dict) else None,
        "graph_hash": graph.get("hash") if isinstance(graph, dict) else None,
    }
def _canonical_graph_identity(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": graph.get("id") if isinstance(graph, dict) else None,
        "graph_version": graph.get("version") if isinstance(graph, dict) else None,
        "graph_hash": graph.get("hash") if isinstance(graph, dict) else None,
    }
def _consumer_actual_identity(consumer: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": consumer.get("graph_id"),
        "graph_version": consumer.get("graph_version"),
        "graph_hash": consumer.get("graph_hash"),
    }
def validate_graph_consumer_identities(
    graph: dict[str, Any],
    consumers: list[dict[str, Any]] | dict[str, dict[str, Any]],
) -> dict[str, Any]:
    expected_identity = _canonical_graph_identity(graph)
    diagnostics: list[dict[str, Any]] = []

    if isinstance(consumers, dict):
        consumer_items = list(consumers.items())
    elif isinstance(consumers, list):
        consumer_items = [(None, consumer) for consumer in consumers]
    else:
        consumer_items = [(None, consumers)]

    for fallback_name, consumer in consumer_items:
        consumer_name = fallback_name
        if isinstance(consumer, dict) and isinstance(consumer.get("consumer"), str):
            consumer_name = consumer["consumer"]

        if not isinstance(consumer, dict):
            diagnostics.append(
                _diag(
                    "graph_consumer_identity_mismatch",
                    field="consumer",
                    path=f"consumers.{consumer_name or '<unknown>'}",
                    reason="graph consumer identity must be an object",
                    graph=graph,
                    source="graph_consumer_identity_sync",
                )
                | {
                    "consumer": consumer_name,
                    "expected_identity": expected_identity,
                    "actual_identity": None,
                }
            )
            continue

        actual_identity = _consumer_actual_identity(consumer)
        missing_fields = [
            field
            for field in ("graph_id", "graph_version", "graph_hash")
            if not isinstance(actual_identity.get(field), str) or not str(actual_identity.get(field)).strip()
        ]
        mismatched_fields = [
            field
            for field in ("graph_id", "graph_version", "graph_hash")
            if field not in missing_fields and actual_identity.get(field) != expected_identity.get(field)
        ]
        if missing_fields or mismatched_fields:
            code = (
                "graph_consumer_hash_mismatch"
                if not missing_fields and mismatched_fields == ["graph_hash"]
                else "graph_consumer_identity_mismatch"
            )
            diagnostics.append(
                _diag(
                    code,
                    field="graph_identity",
                    path=f"consumers.{consumer_name or '<unknown>'}",
                    reason="graph consumer identity does not match canonical graph",
                    graph=graph,
                    source="graph_consumer_identity_sync",
                )
                | {
                    "consumer": consumer_name,
                    "expected_identity": expected_identity,
                    "actual_identity": actual_identity,
                    "missing_fields": missing_fields,
                    "mismatched_fields": mismatched_fields,
                }
            )

    if diagnostics:
        return _failure(diagnostics, graph=graph, source="graph_consumer_identity_sync", drift_detected=True)

    return _ok(graph, source="graph_consumer_identity_sync") | {
        "target": "graph_consumer_identity_sync",
        "consumer_count": len(consumer_items),
        "expected_identity": expected_identity,
    }
def validate_generated_graph_view(
    graph: dict[str, Any],
    view: dict[str, Any],
    source_graph_path: str | None = None,
) -> dict[str, Any]:
    source_graph = view.get("source_graph") if isinstance(view, dict) else None
    diagnostics: list[dict[str, Any]] = []
    drift_detected = False
    if not isinstance(source_graph, dict):
        drift_detected = True
        diagnostics.append(
            _diag(
                "generated_view_source",
                field="source_graph",
                path="source_graph",
                reason="generated graph view must include source graph identity",
                graph=graph,
                source=source_graph_path,
            )
        )
    else:
        for field in ("id", "version", "hash"):
            if source_graph.get(field) != graph.get(field):
                drift_detected = True
                diagnostics.append(
                    _diag(
                        "generated_view_drift",
                        field=f"source_graph.{field}",
                        path=f"source_graph.{field}",
                        reason="generated graph view source identity does not match canonical graph",
                        graph=graph,
                        source=source_graph_path,
                    )
                )
    if isinstance(view, dict):
        view_kind = view.get("kind")
        if view_kind is not None and view_kind != VIEW_KIND:
            drift_detected = True
            diagnostics.append(
                _diag(
                    "generated_view_provenance",
                    field="kind",
                    path="kind",
                    reason=f"generated graph view kind must be {VIEW_KIND}",
                    graph=graph,
                    source=source_graph_path,
                )
                | {"actual": view_kind, "expected": VIEW_KIND}
            )

        generated_at = view.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at.strip():
            drift_detected = True
            diagnostics.append(
                _diag(
                    "generated_view_provenance",
                    field="generated_at",
                    path="generated_at",
                    reason="generated graph view must include generated_at",
                    graph=graph,
                    source=source_graph_path,
                )
            )

        view_source_path = view.get("source_graph_path")
        if source_graph_path and (
            not isinstance(view_source_path, str)
            or not view_source_path.strip()
            or not _paths_match(view_source_path, source_graph_path)
        ):
            drift_detected = True
            reason = (
                "generated graph view must include source graph path"
                if not isinstance(view_source_path, str) or not view_source_path.strip()
                else "generated graph view source path does not match canonical graph path"
            )
            diagnostics.append(
                _diag(
                    "generated_view_drift",
                    field="source_graph_path",
                    path="source_graph_path",
                    reason=reason,
                    graph=graph,
                    source=source_graph_path,
                )
                | {"actual": view_source_path, "expected": source_graph_path}
            )
        diagnostics.extend(_validate_generated_view_coverage(graph, view, source=source_graph_path))
    if diagnostics:
        return _failure(diagnostics, graph=graph, source=source_graph_path, drift_detected=drift_detected)
    return {
        "status": "ok",
        "source_graph_path": source_graph_path,
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "covered_states": list(view.get("covered_states") or []),
        "covered_transitions": list(view.get("covered_transitions") or []),
        "drift_detected": False,
        "fail_closed": False,
    }
def validate_transition_graph(
    graph: dict[str, Any],
    generated_view: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(graph, dict):
        graph = {}
        diagnostics.append(
            _diag(
                "payload",
                field="payload",
                path="$",
                reason="transition graph must be an object",
                graph=graph,
                source=source,
            )
        )

    for field in sorted(REQUIRED_GRAPH_FIELDS - set(graph)):
        diagnostics.append(
            _diag(
                field,
                field=field,
                path=field,
                reason=f"{field} is required",
                graph=graph,
                source=source,
            )
        )

    if graph.get("schema_version") != 1:
        diagnostics.append(
            _diag(
                "schema_version",
                field="schema_version",
                path="schema_version",
                reason="schema_version must be 1",
                graph=graph,
                source=source,
            )
        )
    if graph.get("id") != GRAPH_ID:
        diagnostics.append(
            _diag(
                "id",
                field="id",
                path="id",
                reason=f"id must be {GRAPH_ID}",
                graph=graph,
                source=source,
            )
        )

    states = graph.get("states")
    transitions = graph.get("transitions")
    evidence_keys = _declared_evidence(graph)
    guard_names = _declared_guards(graph)

    if not isinstance(states, dict) or not states:
        diagnostics.append(
            _diag(
                "states",
                field="states",
                path="states",
                reason="states must be a non-empty object",
                graph=graph,
                source=source,
            )
        )
        states = {}
    for state_name, state in states.items():
        if not isinstance(state, dict) or not isinstance(state.get("terminal"), bool):
            diagnostics.append(
                _diag(
                    "state.terminal",
                    field="terminal",
                    path=f"states.{state_name}.terminal",
                    reason="state terminal must be a bool",
                    graph=graph,
                    source=source,
                )
            )

    if not isinstance(transitions, dict) or not transitions:
        diagnostics.append(
            _diag(
                "transitions",
                field="transitions",
                path="transitions",
                reason="transitions must be a non-empty object",
                graph=graph,
                source=source,
            )
        )
        transitions = {}

    for transition_name, transition in transitions.items():
        path = f"transitions.{transition_name}"
        if not isinstance(transition, dict):
            diagnostics.append(
                _diag(
                    "transition",
                    field="transition",
                    path=path,
                    reason="transition must be an object",
                    graph=graph,
                    source=source,
                )
            )
            continue
        for field in sorted(REQUIRED_TRANSITION_FIELDS - set(transition)):
            diagnostics.append(
                _diag(
                    field,
                    field=field,
                    path=f"{path}.{field}",
                    reason=f"{field} is required",
                    graph=graph,
                    source=source,
                )
            )
        from_states = transition.get("from")
        if not _string_list(from_states):
            diagnostics.append(
                _diag(
                    "from",
                    field="from",
                    path=f"{path}.from",
                    reason="from must be a non-empty list of state ids",
                    graph=graph,
                    source=source,
                )
            )
        else:
            for state in from_states:
                if state not in states:
                    diagnostics.append(
                        _diag(
                            "unsupported_state",
                            field="from",
                            path=f"{path}.from",
                            reason=f"from references undefined state: {state}",
                            graph=graph,
                            source=source,
                        )
                    )
        to_state = transition.get("to")
        if not isinstance(to_state, str) or not to_state.strip() or to_state not in states:
            diagnostics.append(
                _diag(
                    "unsupported_state",
                    field="to",
                    path=f"{path}.to",
                    reason=f"to references undefined state: {to_state}",
                    graph=graph,
                    source=source,
                )
            )
        guards = transition.get("guards")
        if not _string_list(guards):
            diagnostics.append(
                _diag(
                    "guards",
                    field="guards",
                    path=f"{path}.guards",
                    reason="guards must be a list of guard names",
                    graph=graph,
                    source=source,
                )
            )
        elif guard_names is not None:
            for guard in guards:
                if guard not in guard_names:
                    diagnostics.append(
                        _diag(
                            "guard",
                            field="guards",
                            path=f"{path}.guards",
                            reason=f"guard is not declared: {guard}",
                            graph=graph,
                            source=source,
                        )
                    )
        required_evidence = transition.get("required_evidence")
        if not _string_list(required_evidence):
            diagnostics.append(
                _diag(
                    "required_evidence",
                    field="required_evidence",
                    path=f"{path}.required_evidence",
                    reason="required_evidence must be a list of evidence keys",
                    graph=graph,
                    source=source,
                )
            )
        elif evidence_keys:
            for evidence in required_evidence:
                if evidence not in evidence_keys:
                    diagnostics.append(
                        _diag(
                            "evidence_producer",
                            field="required_evidence",
                            path=f"{path}.required_evidence",
                            reason=f"required evidence has no declared producer: {evidence}",
                            graph=graph,
                            source=source,
                        )
                    )
        on_reject = transition.get("on_reject")
        if not isinstance(on_reject, str) or not on_reject.strip():
            diagnostics.append(
                _diag(
                    "on_reject",
                    field="on_reject",
                    path=f"{path}.on_reject",
                    reason="on_reject is required",
                    graph=graph,
                    source=source,
                )
            )
        elif on_reject not in transitions:
            diagnostics.append(
                _diag(
                    "on_reject",
                    field="on_reject",
                    path=f"{path}.on_reject",
                    reason=f"on_reject references undefined transition: {on_reject}",
                    graph=graph,
                    source=source,
                )
            )
        for bool_field in ("auto_allowed", "write_allowed"):
            if not isinstance(transition.get(bool_field), bool):
                diagnostics.append(
                    _diag(
                        bool_field,
                        field=bool_field,
                        path=f"{path}.{bool_field}",
                        reason=f"{bool_field} must be a bool",
                        graph=graph,
                        source=source,
                    )
                )

    if isinstance(states, dict) and isinstance(transitions, dict) and states and transitions:
        reachable = _reachable_nonterminal_states(states, transitions)
        for state_name, state in states.items():
            if isinstance(state, dict) and state.get("terminal") is False and state_name not in reachable:
                diagnostics.append(
                    _diag(
                        "unreachable_nonterminal_state",
                        field="states",
                        path=f"states.{state_name}",
                        reason="nonterminal state is not reachable from active",
                        graph=graph,
                        source=source,
                    )
                )

    diagnostics.extend(_validate_lifecycle_mapping_payload(graph, source=source))

    if isinstance(graph.get("hash"), str) and len(graph["hash"]) == 64:
        computed_hash = compute_graph_hash(graph)
        if graph["hash"] != computed_hash:
            diagnostics.append(
                _diag(
                    "hash",
                    field="hash",
                    path="hash",
                    reason="graph hash does not match canonical payload",
                    graph=graph,
                    source=source,
                )
                | {"computed_hash": computed_hash}
            )
    else:
        diagnostics.append(
            _diag(
                "hash",
                field="hash",
                path="hash",
                reason="hash must be a 64 character sha256 hex string",
                graph=graph,
                source=source,
            )
        )

    if generated_view is not None:
        diagnostics.extend(_validate_generated_view_coverage(graph, generated_view, source=source))

    if diagnostics:
        return _failure(diagnostics, graph=graph, source=source)
    return _ok(graph, source=source)
def validate_equivalent_lifecycle_mappings(
    graph: dict[str, Any],
    source: str | None = None,
) -> dict[str, Any]:
    graph = graph if isinstance(graph, dict) else {}
    diagnostics = _validate_lifecycle_mapping_payload(graph, source=source)
    if diagnostics:
        return _failure(diagnostics, graph=graph, source=source)
    return _ok(graph, source=source) | {
        "target": "equivalent_lifecycle_mappings",
        "mappings": _lifecycle_mappings(graph),
    }
def _terminal_entry_records(state_name: str, graph: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    for transition_id, transition in transitions.items():
        if isinstance(transition, dict) and transition.get("to") == state_name:
            records.append(
                {
                    "coverage": "graph_transition",
                    "id": transition_id,
                    "required_evidence": list(transition.get("required_evidence") or []),
                }
            )
    for mapping_id, mapping in _lifecycle_mappings(graph).items():
        if isinstance(mapping, dict) and mapping.get("to") == state_name:
            records.append(
                {
                    "coverage": "lifecycle_mapping",
                    "id": mapping_id,
                    "required_evidence": list(mapping.get("required_evidence") or []),
                }
            )
    return records
def _outgoing_records(state_name: str, graph: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    for transition_id, transition in transitions.items():
        from_states = transition.get("from") if isinstance(transition, dict) else None
        if isinstance(from_states, list) and state_name in from_states:
            records.append({"coverage": "graph_transition", "id": transition_id})
    for mapping_id, mapping in _lifecycle_mappings(graph).items():
        from_states = _mapping_sources(mapping) if isinstance(mapping, dict) else []
        if state_name in from_states or "*" in from_states:
            records.append({"coverage": "lifecycle_mapping", "id": mapping_id})
    return records
def validate_state_inventory_coverage(
    graph: dict[str, Any],
    source: str | None = None,
) -> dict[str, Any]:
    graph = graph if isinstance(graph, dict) else {}
    graph_validation = validate_transition_graph(graph, source=source)
    if graph_validation.get("accepted") is not True:
        return _failure(list(graph_validation.get("diagnostics") or []), graph=graph, source=source)

    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    terminal_states = sorted(
        state_name for state_name, state in states.items() if isinstance(state, dict) and state.get("terminal") is True
    )
    nonterminal_states = sorted(
        state_name for state_name, state in states.items() if isinstance(state, dict) and state.get("terminal") is False
    )
    terminal_entry_coverage: dict[str, dict[str, Any]] = {}
    nonterminal_continuation_coverage: dict[str, list[dict[str, Any]]] = {}
    gaps: list[dict[str, Any]] = []

    for state_name in nonterminal_states:
        records = _outgoing_records(state_name, graph)
        nonterminal_continuation_coverage[state_name] = records
        if not records:
            gaps.append(
                _diag(
                    "state_inventory",
                    field="states",
                    path=f"states.{state_name}",
                    reason="nonterminal state has no graph transition or lifecycle continuation/recovery path",
                    graph=graph,
                    source=source,
                )
            )
    for state_name in terminal_states:
        records = _terminal_entry_records(state_name, graph)
        if records:
            terminal_entry_coverage[state_name] = records[0]
        else:
            gaps.append(
                _diag(
                    "state_inventory",
                    field="states",
                    path=f"states.{state_name}",
                    reason="terminal state has no graph transition or equivalent lifecycle entry evidence",
                    graph=graph,
                    source=source,
                )
            )

    result = _ok(graph, source=source) | {
        "target": "state_inventory_coverage",
        "terminal_states": terminal_states,
        "nonterminal_states": nonterminal_states,
        "terminal_entry_coverage": terminal_entry_coverage,
        "nonterminal_continuation_coverage": nonterminal_continuation_coverage,
        "gaps": gaps,
    }
    if gaps:
        return result | {
            "status": "validation_failed",
            "accepted": False,
            "fail_closed": True,
            "diagnostics": gaps,
        }
    return result
def build_transition_graph_evidence_result(
    graph: dict[str, Any],
    source: str | None = None,
) -> dict[str, Any]:
    graph = graph if isinstance(graph, dict) else {}
    graph_result = validate_transition_graph(graph, source=source)
    inventory_result = validate_state_inventory_coverage(graph, source=source)
    diagnostics = list(graph_result.get("diagnostics") or []) + list(inventory_result.get("diagnostics") or [])
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    lifecycle_ids = sorted(_lifecycle_mappings(graph))
    gaps = [
        {
            "code": item.get("code"),
            "field": item.get("field"),
            "path": item.get("path"),
            "reason": item.get("reason"),
        }
        for item in diagnostics
        if isinstance(item, dict)
    ]
    severity = "info" if not gaps else "high"
    return {
        "status": "ok" if not gaps else "validation_failed",
        "accepted": not gaps,
        "fail_closed": bool(gaps),
        "dod_id": "DOD-001",
        "mapped_dod": "DOD-001",
        "completed_dods": ["DOD-001"],
        "cross_references": ["DOD-004", "DOD-005"],
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "checked_transitions": sorted(transitions) + lifecycle_ids,
        "gaps": gaps,
        "severity": severity,
        "evidence_ref": source,
        "recommended_action": (
            "no action required; DOD-004/DOD-005 impacts remain cross-references only"
            if not gaps
            else "fix listed DOD-001 transition graph gaps before claiming completion"
        ),
    }
def _attempt_diag(code: str, *, field: str, path: str, reason: str, graph: dict[str, Any]) -> dict[str, Any]:
    return _diag(code, field=field, path=path, reason=reason, graph=graph, source="attempted_transition")
def _graph_identity(envelope: dict[str, Any]) -> dict[str, Any]:
    identity = envelope.get("graph")
    if isinstance(identity, dict):
        return identity
    return {
        "id": envelope.get("graph_id"),
        "version": envelope.get("graph_version"),
        "hash": envelope.get("graph_hash"),
    }
def _value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True
def _explicit_guard_value(envelope: dict[str, Any], guard: str) -> Any:
    for field in ("guard_results", "guards", "guard_inputs"):
        values = envelope.get(field)
        if isinstance(values, dict) and guard in values:
            return values[guard]
    return None
def _coerce_guard_pass(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "ok", "pass", "passed", "accepted"}:
            return True
        if normalized in {"0", "false", "fail", "failed", "rejected", "error"}:
            return False
    if isinstance(value, dict):
        for key in ("passed", "accepted", "ok", "result"):
            if isinstance(value.get(key), bool):
                return bool(value[key])
        status = value.get("status")
        if isinstance(status, str):
            return _coerce_guard_pass(status)
    return bool(value)
