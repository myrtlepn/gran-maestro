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


def _infer_guard_pass(guard: str, envelope: dict[str, Any], evidence: dict[str, Any]) -> bool:
    explicit = _coerce_guard_pass(_explicit_guard_value(envelope, guard))
    if explicit is not None:
        return explicit
    if guard == "next_action_present":
        return _value_present(evidence.get("next_action"))
    if guard == "no_critical_blocker":
        return not _value_present(evidence.get("critical_blocker"))
    if guard == "all_required_dod_done":
        result = evidence.get("objective_check_result")
        if isinstance(result, dict):
            for key in ("done", "passed", "accepted", "ok"):
                if isinstance(result.get(key), bool):
                    return bool(result[key])
        return bool(result)
    if guard == "no_next_action":
        return not _value_present(evidence.get("next_action"))
    if guard == "history_verified":
        return _value_present(evidence.get("history_head"))
    if guard == "core_rehydration_available":
        return _value_present(evidence.get("mst_session_id") or envelope.get("mst_session_id")) and _value_present(
            evidence.get("root_mst_id") or envelope.get("root_mst_id")
        )
    if guard == "history_head_matches_snapshot":
        history_head = evidence.get("history_head")
        last_event_id = evidence.get("history_last_event_id")
        return _value_present(last_event_id) and (not _value_present(history_head) or history_head == last_event_id)
    if guard == "state_inconsistency_suspected":
        return _value_present(evidence.get("mismatch_subject"))
    if guard == "action_is_destructive_or_external":
        return _value_present(evidence.get("action_scope"))
    if guard == "classifier_failed_or_permission_unknown":
        return _value_present(evidence.get("classifier_failure_kind"))
    if guard == "state_contract_failed":
        return _value_present(evidence.get("mismatch_subject"))
    if guard == "repeat_limit_exceeded":
        return _value_present(evidence.get("reject_loop_key")) and _value_present(evidence.get("attempt_count"))
    return True


def _guard_checks(
    transition: dict[str, Any],
    envelope: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    failed: list[str] = []
    for guard in transition.get("guards") or []:
        passed = _infer_guard_pass(str(guard), envelope, evidence)
        check = {
            "guard": guard,
            "passed": passed,
            "source": "explicit" if _explicit_guard_value(envelope, str(guard)) is not None else "inferred",
        }
        checks.append(check)
        if not passed:
            failed.append(str(guard))
    return checks, failed


def _any_bool(envelope: dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(envelope.get(name) is True for name in names)


def validate_attempted_transition(envelope: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(graph, dict):
        graph = {}
    if not isinstance(envelope, dict):
        diagnostics.append(
            _attempt_diag(
                "payload",
                field="payload",
                path="$",
                reason="attempted transition envelope must be an object",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph)

    graph_validation = validate_transition_graph(graph, source="attempted_transition.graph")
    if graph_validation.get("accepted") is not True:
        return _attempt_failure(list(graph_validation.get("diagnostics") or []), graph=graph, envelope=envelope)

    identity = _graph_identity(envelope)
    for field in ("id", "version", "hash"):
        expected = graph.get(field)
        actual = identity.get(field)
        if not _value_present(actual):
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"graph {field} is required in the explicit attempt envelope",
                    graph=graph,
                )
            )
        elif actual != expected:
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"attempt envelope graph {field} does not match canonical graph",
                    graph=graph,
                )
                | {"actual": actual, "expected": expected}
            )

    for field in ("mst_session_id", "root_mst_id", "current_state", "attempted_transition"):
        if not _value_present(envelope.get(field)):
            diagnostics.append(
                _attempt_diag(
                    field,
                    field=field,
                    path=field,
                    reason=f"{field} is required in the explicit attempt envelope",
                    graph=graph,
                )
            )

    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    current_state = envelope.get("current_state")
    transition_id = envelope.get("attempted_transition")
    transition = transitions.get(transition_id) if isinstance(transition_id, str) else None
    if isinstance(current_state, str) and current_state not in states:
        diagnostics.append(
            _attempt_diag(
                "current_state",
                field="current_state",
                path="current_state",
                reason=f"current_state is not declared in the graph: {current_state}",
                graph=graph,
            )
        )
    if not isinstance(transition, dict):
        diagnostics.append(
            _attempt_diag(
                "attempted_transition",
                field="attempted_transition",
                path="attempted_transition",
                reason=f"attempted_transition is not declared in the graph: {transition_id}",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph, envelope=envelope)
    if isinstance(current_state, str) and current_state not in (transition.get("from") or []):
        diagnostics.append(
            _attempt_diag(
                "transition.from",
                field="from",
                path=f"transitions.{transition_id}.from",
                reason=f"transition {transition_id} is not allowed from {current_state}",
                graph=graph,
            )
        )

    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
        diagnostics.append(
            _attempt_diag(
                "evidence",
                field="evidence",
                path="evidence",
                reason="evidence map is required in the explicit attempt envelope",
                graph=graph,
            )
        )

    required_evidence = [str(item) for item in transition.get("required_evidence") or []]
    missing_evidence = [key for key in required_evidence if key not in evidence or not _value_present(evidence.get(key))]
    for key in missing_evidence:
        diagnostics.append(
            _attempt_diag(
                "required_evidence",
                field="required_evidence",
                path=f"evidence.{key}",
                reason=f"required evidence is missing: {key}",
                graph=graph,
            )
        )

    guard_results, failed_guards = _guard_checks(transition, envelope, evidence)
    for guard in failed_guards:
        diagnostics.append(
            _attempt_diag(
                f"guard.{guard}",
                field="guards",
                path=f"transitions.{transition_id}.guards",
                reason=f"guard failed: {guard}",
                graph=graph,
            )
        )
    auto_requested = _any_bool(envelope, ("auto", "auto_attempt", "auto_continuation", "auto_requested"))
    write_requested = _any_bool(envelope, ("write", "write_attempt", "write_requested", "mutation_attempt"))
    if auto_requested and transition.get("auto_allowed") is not True:
        diagnostics.append(
            _attempt_diag(
                "auto_allowed",
                field="auto_allowed",
                path=f"transitions.{transition_id}.auto_allowed",
                reason="transition is not allowed for automatic continuation",
                graph=graph,
            )
        )
    if write_requested and transition.get("write_allowed") is not True:
        diagnostics.append(
            _attempt_diag(
                "write_allowed",
                field="write_allowed",
                path=f"transitions.{transition_id}.write_allowed",
                reason="transition is not allowed to authorize write mutation",
                graph=graph,
            )
        )

    base = {
        "mst_session_id": envelope.get("mst_session_id"),
        "root_mst_id": envelope.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "current_state": current_state,
        "transition": transition_id,
        "target_state": transition.get("to"),
        "required_evidence": required_evidence,
        "required_evidence_checks": [
            {"key": key, "present": key not in missing_evidence} for key in required_evidence
        ],
        "guard_results": guard_results,
        "auto_allowed": transition.get("auto_allowed"),
        "write_allowed": transition.get("write_allowed"),
        "auto_requested": auto_requested,
        "write_requested": write_requested,
        "write_permission_granted": bool(transition.get("write_allowed")),
        "auto_continuation_allowed": bool(transition.get("auto_allowed")),
        "created_new_session": False,
    }
    if diagnostics:
        return {
            **base,
            "status": "rejected",
            "accepted": False,
            "fail_closed": True,
            "failed_guards": failed_guards,
            "missing_evidence": missing_evidence,
            "on_reject": transition.get("on_reject"),
            "diagnostics": diagnostics,
        }
    return {
        **base,
        "status": "accepted",
        "accepted": True,
        "fail_closed": False,
        "failed_guards": [],
        "missing_evidence": [],
        "on_reject": None,
        "diagnostics": [],
    }


def _normalized_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _reject_loop_fingerprint(attempt: dict[str, Any]) -> str:
    fingerprint = attempt.get("evidence_fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return fingerprint.strip()
    evidence = attempt.get("evidence")
    if isinstance(evidence, dict):
        return hashlib.sha256(_normalized_json(evidence).encode("utf-8")).hexdigest()
    return hashlib.sha256(_normalized_json(attempt.get("required_evidence") or {}).encode("utf-8")).hexdigest()


def _reject_loop_key(attempt: dict[str, Any]) -> str:
    parts = [
        str(attempt.get("mst_session_id") or ""),
        str(attempt.get("attempted_transition") or attempt.get("transition") or ""),
        str(attempt.get("failed_guard") or ",".join(attempt.get("failed_guards") or []) or ""),
        _reject_loop_fingerprint(attempt),
    ]
    encoded = "\x1f".join(parts)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"reject-loop:{digest}"


def apply_on_reject_loop_guard(
    attempt: dict[str, Any],
    prior: list[dict[str, Any]],
    graph: dict[str, Any],
    limit: int = 3,
) -> dict[str, Any]:
    if not isinstance(attempt, dict):
        attempt = {}
    prior = prior if isinstance(prior, list) else []
    idempotency_key = _reject_loop_key(attempt)
    previous_count = 0
    for item in prior:
        if not isinstance(item, dict):
            continue
        prior_key = item.get("idempotency_key")
        result = item.get("result")
        if not isinstance(prior_key, str) and isinstance(result, dict):
            prior_key = result.get("idempotency_key")
        if prior_key is None:
            prior_key = _reject_loop_key(item)
        if prior_key == idempotency_key:
            previous_count += 1
    attempt_count = previous_count + 1
    terminal_transition = (
        "terminal.repeat_failure_limit"
        if isinstance(graph.get("transitions"), dict) and "terminal.repeat_failure_limit" in graph["transitions"]
        else "terminal.state_inconsistency"
    )
    base = {
        "idempotency_key": idempotency_key,
        "mst_session_id": attempt.get("mst_session_id"),
        "attempted_transition": attempt.get("attempted_transition") or attempt.get("transition"),
        "failed_guard": attempt.get("failed_guard"),
        "evidence_fingerprint": _reject_loop_fingerprint(attempt),
        "attempt_count": attempt_count,
        "limit": limit,
        "completed": False,
        "created_new_session": False,
        "graph_id": graph.get("id") if isinstance(graph, dict) else None,
        "graph_version": graph.get("version") if isinstance(graph, dict) else None,
        "graph_hash": graph.get("hash") if isinstance(graph, dict) else None,
    }
    if attempt_count > limit:
        return {
            **base,
            "status": "terminal",
            "accepted": False,
            "fail_closed": True,
            "terminal_transition": terminal_transition,
            "on_reject_retry_allowed": False,
            "critical_blocker": {
                "type": terminal_transition.removeprefix("terminal."),
                "idempotency_key": idempotency_key,
                "attempt_count": attempt_count,
                "limit": limit,
            },
            "diagnostics": [
                _attempt_diag(
                    "reject_loop_limit",
                    field="on_reject",
                    path="on_reject",
                    reason="repeated on_reject attempt exceeded the configured limit",
                    graph=graph if isinstance(graph, dict) else {},
                )
            ],
        }
    return {
        **base,
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "terminal_transition": None,
        "on_reject_retry_allowed": True,
        "diagnostics": [],
    }


def _fixture_value(fixture: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = fixture.get(key)
        if _value_present(value):
            return value
    tool_input = fixture.get("tool_input")
    if isinstance(tool_input, dict):
        for key in keys:
            value = tool_input.get(key)
            if _value_present(value):
                return value
    return None


def classify_hook_attempt(boundary: str, fixture: dict[str, Any]) -> str | None:
    fixture = fixture if isinstance(fixture, dict) else {}
    explicit = fixture.get("attempted_transition")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    tool_name = str(_fixture_value(fixture, "tool_name", "name") or "").strip()
    message = str(
        _fixture_value(fixture, "last_assistant_message", "assistant_message", "message", "reason") or ""
    ).lower()
    if boundary == "PreToolUse" and tool_name == "AskUserQuestion":
        return "user_wait"
    if boundary == "PreToolUse" and tool_name == "ScheduleWakeup":
        return "self_paced_stop"
    if "askuserquestion" in message:
        return "user_wait"
    if "schedulewakeup" in message or "stop here" in message or "pause" in message:
        return "self_paced_stop"
    if "premature" in message and "complete" in message:
        return "premature_completed"
    if "final answer" in message or "workflow complete" in message or "completed" in message or "all done" in message:
        return "terminal.completed"
    return None


def _graph_transition(graph: dict[str, Any], transition_id: Any) -> dict[str, Any]:
    transitions = graph.get("transitions") if isinstance(graph, dict) else None
    if not isinstance(transitions, dict) or not isinstance(transition_id, str):
        return {}
    transition = transitions.get(transition_id)
    return transition if isinstance(transition, dict) else {}


def _required_response_for_transition(transition_id: str | None) -> str:
    if not isinstance(transition_id, str):
        return "inspect_only"
    if transition_id.startswith("continue."):
        return "continue"
    if transition_id.startswith("guard."):
        return "inspect_only"
    return "terminal_blocker"


def _first_string(values: Any) -> str | None:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(values, str) and values.strip():
        return values.strip()
    return None


def build_hook_continuation_block(
    boundary: str,
    fixture: dict[str, Any],
    reject_result: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    fixture = fixture if isinstance(fixture, dict) else {}
    reject_result = reject_result if isinstance(reject_result, dict) else {}
    graph = graph if isinstance(graph, dict) else {}

    attempted_transition = classify_hook_attempt(str(boundary or ""), fixture) or reject_result.get("transition")
    graph_transition = reject_result.get("transition")
    on_reject = reject_result.get("on_reject")
    on_reject_transition = _graph_transition(graph, on_reject)
    required_evidence = list(reject_result.get("required_evidence") or on_reject_transition.get("required_evidence") or [])
    failed_guard = _first_string(reject_result.get("failed_guards")) or _first_string(
        reject_result.get("failed_guard")
    )
    next_action = (
        reject_result.get("next_action")
        or fixture.get("next_action")
        or fixture.get("queued_action")
        or {"transition": on_reject}
    )
    required_response = _required_response_for_transition(on_reject if isinstance(on_reject, str) else None)

    return {
        "decision": "block",
        "reason": "graph_transition_rejected",
        "hook_boundary": boundary,
        "attempted_transition": attempted_transition,
        "graph_transition": graph_transition,
        "failed_guard": failed_guard,
        "failed_guards": list(reject_result.get("failed_guards") or ([] if failed_guard is None else [failed_guard])),
        "required_evidence": required_evidence,
        "on_reject_transition": on_reject,
        "mst_session_id": reject_result.get("mst_session_id") or fixture.get("mst_session_id"),
        "root_mst_id": reject_result.get("root_mst_id") or fixture.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "same_session_evidence": bool(reject_result.get("mst_session_id") or fixture.get("mst_session_id")),
        "continuation": {
            "required_response": required_response,
            "transition": on_reject,
            "next_action": next_action,
            "write_allowed": on_reject_transition.get("write_allowed"),
            "auto_allowed": on_reject_transition.get("auto_allowed"),
        },
        "full_state_prompt_injection": False,
        "hot_path_full_graph_validation": False,
        "hot_path_d2_rendering": False,
        "hot_path_full_ledger_replay": False,
    }


def build_hook_pass_result(boundary: str, fixture: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    fixture = fixture if isinstance(fixture, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    return {
        "decision": "approve",
        "reason": "graph_transition_pass",
        "hook_boundary": boundary,
        "attempted_transition": classify_hook_attempt(str(boundary or ""), fixture),
        "mst_session_id": fixture.get("mst_session_id"),
        "root_mst_id": fixture.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "full_state_prompt_injection": False,
        "hot_path_full_graph_validation": False,
        "hot_path_d2_rendering": False,
        "hot_path_full_ledger_replay": False,
    }


def validate_hook_attempted_transition(envelope: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Validate a hook boundary attempt with cached graph lookup only.

    This intentionally avoids validate_transition_graph(), generated view checks,
    and ledger replay so hook hot paths can fail closed without doing heavy work.
    """

    graph = graph if isinstance(graph, dict) else {}
    envelope = envelope if isinstance(envelope, dict) else {}
    diagnostics: list[dict[str, Any]] = []
    identity = _graph_identity(envelope)
    for field in ("id", "version", "hash"):
        expected = graph.get(field)
        actual = identity.get(field)
        if not _value_present(actual) or actual != expected:
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"hook attempt graph {field} does not match pinned graph",
                    graph=graph,
                )
                | {"actual": actual, "expected": expected}
            )

    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transition_id = envelope.get("attempted_transition")
    current_state = envelope.get("current_state")
    transition = transitions.get(transition_id) if isinstance(transition_id, str) else None
    if not isinstance(current_state, str) or current_state not in states:
        diagnostics.append(
            _attempt_diag(
                "current_state",
                field="current_state",
                path="current_state",
                reason="hook attempt current_state is missing or not declared",
                graph=graph,
            )
        )
    if not isinstance(transition, dict):
        diagnostics.append(
            _attempt_diag(
                "attempted_transition",
                field="attempted_transition",
                path="attempted_transition",
                reason="hook attempted_transition is missing or not declared",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph, envelope=envelope)
    if isinstance(current_state, str) and current_state not in (transition.get("from") or []):
        diagnostics.append(
            _attempt_diag(
                "transition.from",
                field="from",
                path=f"transitions.{transition_id}.from",
                reason=f"transition {transition_id} is not allowed from {current_state}",
                graph=graph,
            )
        )

    evidence = envelope.get("evidence") if isinstance(envelope.get("evidence"), dict) else {}
    required_evidence = [str(item) for item in transition.get("required_evidence") or []]
    missing_evidence = [key for key in required_evidence if key not in evidence or not _value_present(evidence.get(key))]
    for key in missing_evidence:
        diagnostics.append(
            _attempt_diag(
                "required_evidence",
                field="required_evidence",
                path=f"evidence.{key}",
                reason=f"required evidence is missing: {key}",
                graph=graph,
            )
        )
    guard_results, failed_guards = _guard_checks(transition, envelope, evidence)
    for guard in failed_guards:
        diagnostics.append(
            _attempt_diag(
                f"guard.{guard}",
                field="guards",
                path=f"transitions.{transition_id}.guards",
                reason=f"guard failed: {guard}",
                graph=graph,
            )
        )

    base = {
        "mst_session_id": envelope.get("mst_session_id"),
        "root_mst_id": envelope.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "current_state": current_state,
        "transition": transition_id,
        "target_state": transition.get("to"),
        "required_evidence": required_evidence,
        "guard_results": guard_results,
        "created_new_session": False,
    }
    if diagnostics:
        return {
            **base,
            "status": "rejected",
            "accepted": False,
            "fail_closed": True,
            "failed_guards": failed_guards,
            "missing_evidence": missing_evidence,
            "on_reject": transition.get("on_reject"),
            "diagnostics": diagnostics,
        }
    return {
        **base,
        "status": "accepted",
        "accepted": True,
        "fail_closed": False,
        "failed_guards": [],
        "missing_evidence": [],
        "on_reject": None,
        "diagnostics": [],
    }


def scan_no_dod017_execution_flow_artifacts(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    found = sorted(str(path) for path in base.rglob("execution-flow.*") if path.is_file())
    if found:
        return {
            "status": "validation_failed",
            "accepted": False,
            "fail_closed": True,
            "created_new_session": False,
            "target": "dod017_no_go_scope",
            "found": found,
            "diagnostics": [
                {
                    "code": "dod017_execution_flow_artifact",
                    "field": "path",
                    "path": path,
                    "reason": "DOD-017 execution-flow artifacts are out of scope for DOD-016",
                }
                for path in found
            ],
        }
    return {
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "created_new_session": False,
        "target": "dod017_no_go_scope",
        "found": [],
        "diagnostics": [],
    }
