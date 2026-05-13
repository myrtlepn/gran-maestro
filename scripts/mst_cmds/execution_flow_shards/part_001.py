from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from scripts.mst_cmds import _common
from scripts.mst_cmds import session as session_cmds
ZERO_HASH = "0" * 64
SOURCE_KIND = "verified_history_ledger"
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
PROJECTION_SCHEMA_VERSION = 1
PROJECTION_KIND = "dod017.execution-flow"
def _diagnostic(code: str, *, field: str = "", reason: str = "", **details: Any) -> dict[str, Any]:
    payload = {
        "code": code,
        "field": field or code,
        "reason": reason or code,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload
def _failure(
    code: str,
    *,
    diagnostics: list[dict[str, Any]] | None = None,
    status: str = "validation_failed",
    **details: Any,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "accepted": False,
        "fail_closed": True,
        "trusted_output_generated": False,
        "projection_generation_allowed": False,
        "projection_consumption_allowed": False,
        "diagnostics": diagnostics or [_diagnostic(code)],
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload
def _ok(**details: Any) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "diagnostics": [],
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload
def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _canonical_hash_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prev_hash}\n{_canonical_json(event)}".encode("utf-8")).hexdigest()
def _event_family(event_type: str) -> str:
    if event_type in {"skill.enter", "skill.step", "skill.exit", "skill.recover"}:
        return event_type
    if event_type in {"context.compacted", "context.rehydrated"}:
        return event_type
    if "." in event_type:
        return f"{event_type.split('.', 1)[0]}.*"
    return event_type
def _row_event(row: dict[str, Any]) -> dict[str, Any]:
    event = row.get("event")
    return event if isinstance(event, dict) else {}
def _source_from_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    source = ledger.get("source")
    if isinstance(source, dict):
        return dict(source)
    head = ledger.get("head")
    if isinstance(head, dict):
        return dict(head)
    return {key: ledger.get(key) for key in REQUIRED_HEAD_FIELDS if key in ledger}
def _ledger_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ledger.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []
def _validate_rows_against_source(ledger: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _ledger_rows(ledger)
    if not rows:
        return [_diagnostic("history_rows_missing", field="rows", reason="verified ledger rows are required")]

    expected_prev = ZERO_HASH
    diagnostics: list[dict[str, Any]] = []
    for expected_seq, row in enumerate(rows, 1):
        event = _row_event(row)
        if not event:
            diagnostics.append(
                _diagnostic("history_event_missing", field="rows.event", reason="history row event is required", seq=expected_seq)
            )
            break
        if row.get("seq") != expected_seq:
            diagnostics.append(
                _diagnostic(
                    "history_seq_mismatch",
                    field="seq",
                    reason="history row seq must preserve append order",
                    expected=expected_seq,
                    actual=row.get("seq"),
                )
            )
            break
        if row.get("prev_hash") != expected_prev:
            diagnostics.append(
                _diagnostic(
                    "history_prev_hash_mismatch",
                    field="prev_hash",
                    reason="history row prev_hash must match prior event hash",
                    expected=expected_prev,
                    actual=row.get("prev_hash"),
                    seq=expected_seq,
                )
            )
            break
        computed = _event_hash(expected_prev, event)
        if row.get("event_hash") != computed:
            diagnostics.append(
                _diagnostic(
                    "history_event_hash_mismatch",
                    field="event_hash",
                    reason="history row event_hash must match canonical event hash",
                    expected=computed,
                    actual=row.get("event_hash"),
                    seq=expected_seq,
                )
            )
            break
        expected_prev = computed

    if diagnostics:
        return diagnostics

    tail = rows[-1]
    event = _row_event(tail)
    comparisons = {
        "last_event_seq": len(rows),
        "event_count": len(rows),
        "cumulative_hash": tail.get("event_hash"),
        "history_head": tail.get("event_hash"),
        "last_event_id": event.get("event_id"),
    }
    for field, expected in comparisons.items():
        if source.get(field) != expected:
            diagnostics.append(
                _diagnostic(
                    "source_ledger_head_mismatch",
                    field=field,
                    reason="source ledger head evidence does not match verified row tail",
                    expected=expected,
                    actual=source.get(field),
                )
            )
    return diagnostics
def validate_source_ledger_head(source_head: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source_head, dict):
        return _failure(
            "source_ledger_head_invalid",
            diagnostics=[
                _diagnostic(
                    "source_ledger_head_invalid",
                    field="source_head",
                    reason="source ledger head must be a JSON object",
                )
            ],
        )

    missing = sorted(field for field in REQUIRED_HEAD_FIELDS if field not in source_head)
    if missing:
        return _failure(
            "missing_source_ledger_head_field",
            diagnostics=[
                _diagnostic(
                    "missing_source_ledger_head_field",
                    field=field,
                    reason="required source ledger head field is missing",
                )
                for field in missing
            ],
            missing_fields=missing,
            ledger_path=source_head.get("ledger_path"),
            mst_session_id=source_head.get("mst_session_id"),
            current_head_evidence=source_head,
        )

    diagnostics: list[dict[str, Any]] = []
    for field in ("ledger_path", "mst_session_id", "last_event_id", "cumulative_hash", "history_head"):
        value = source_head.get(field)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                _diagnostic("invalid_source_ledger_head_field", field=field, reason="field must be a non-empty string")
            )
    for field in ("last_event_seq", "event_count", "ledger_schema_version"):
        value = source_head.get(field)
        if not isinstance(value, int) or value < 1:
            diagnostics.append(
                _diagnostic("invalid_source_ledger_head_field", field=field, reason="field must be a positive integer")
            )
    for field in ("cumulative_hash", "history_head"):
        value = source_head.get(field)
        if isinstance(value, str) and value and len(value) != 64:
            diagnostics.append(
                _diagnostic("invalid_source_ledger_head_field", field=field, reason="field must be a 64-character hash")
            )
    if source_head.get("history_head") != source_head.get("cumulative_hash"):
        diagnostics.append(
            _diagnostic(
                "source_ledger_head_mismatch",
                field="history_head",
                reason="history_head must match cumulative_hash",
                expected=source_head.get("cumulative_hash"),
                actual=source_head.get("history_head"),
            )
        )
    if source_head.get("event_count") != source_head.get("last_event_seq"):
        diagnostics.append(
            _diagnostic(
                "source_ledger_head_mismatch",
                field="event_count",
                reason="event_count must match last_event_seq",
                expected=source_head.get("last_event_seq"),
                actual=source_head.get("event_count"),
            )
        )

    if diagnostics:
        return _failure(
            "invalid_source_ledger_head_field",
            diagnostics=diagnostics,
            ledger_path=source_head.get("ledger_path"),
            mst_session_id=source_head.get("mst_session_id"),
            current_head_evidence=source_head,
        )
    return _ok(
        source_kind=SOURCE_KIND,
        ledger_path=source_head["ledger_path"],
        mst_session_id=source_head["mst_session_id"],
        history_head=source_head["history_head"],
        event_count=source_head["event_count"],
        projection_generation_allowed=True,
        projection_consumption_allowed=True,
    )
def replay_ledger_execution_flow(ledger: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return _failure("ledger_invalid", diagnostics=[_diagnostic("ledger_invalid", field="ledger", reason="ledger must be a JSON object")])
    if ledger.get("verified") is not True:
        return _failure(
            "ledger_not_verified",
            diagnostics=[_diagnostic("ledger_not_verified", field="verified", reason="history ledger must be verified before replay")],
            trusted_projection_payload=None,
        )

    source = _source_from_ledger(ledger)
    head_result = validate_source_ledger_head(source)
    if head_result.get("status") != "ok":
        return head_result | {"trusted_projection_payload": None}

    row_diagnostics = _validate_rows_against_source(ledger, source)
    if row_diagnostics:
        return _failure(
            row_diagnostics[0]["code"],
            diagnostics=row_diagnostics,
            ledger_path=source.get("ledger_path"),
            mst_session_id=source.get("mst_session_id"),
            current_head_evidence=source,
            trusted_projection_payload=None,
        )

    rows = _ledger_rows(ledger)
    recognized = sorted({_event_family(str(_row_event(row).get("event_type") or "")) for row in rows})
    missing = sorted(REQUIRED_EVENT_FAMILIES - set(recognized))
    if missing:
        return _failure(
            "missing_event_family",
            diagnostics=[
                _diagnostic(
                    "missing_event_family",
                    field="event_type",
                    reason="required execution-flow event family is missing",
                    missing_event_family=family,
                )
                for family in missing
            ],
            ledger_path=source.get("ledger_path"),
            mst_session_id=source.get("mst_session_id"),
            missing_event_families=missing,
            recognized_event_families=recognized,
            current_head_evidence=source,
            trusted_projection_payload=None,
        )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    previous_node_id = ""
    last_transition = None
    next_action = None
    blocker = None
    root_mst_id = ledger.get("root_mst_id")
    for row in rows:
        event = _row_event(row)
        event_type = str(event.get("event_type") or "")
        seq = int(row["seq"])
        event_id = str(event.get("event_id") or f"seq-{seq}")
        node_id = event.get("current_node") if isinstance(event.get("current_node"), str) else f"{event_type}:{seq}"
        node = {
            "id": node_id,
            "kind": event_type,
            "event_id": event_id,
            "seq": seq,
            "event_hash": row.get("event_hash"),
            "artifact_id": event.get("artifact_id"),
            "skill": event.get("skill"),
        }
        nodes.append({key: value for key, value in node.items() if value is not None})
        replay_rows.append(
            {
                "event_id": event_id,
                "seq": seq,
                "event_hash": row.get("event_hash"),
                "prev_hash": row.get("prev_hash"),
                "event_type": event_type,
            }
        )
        if event_type.startswith(("continue.", "guard.", "terminal.")) or isinstance(event.get("transition"), str):
            last_transition = event.get("transition") if isinstance(event.get("transition"), str) else event_type
        candidate_next = event.get("next_action")
        if isinstance(candidate_next, dict):
            next_action = candidate_next
        candidate_blocker = event.get("blocker")
        if isinstance(candidate_blocker, dict):
            blocker = candidate_blocker
        if previous_node_id:
            edges.append(
                {
                    "from": previous_node_id,
                    "to": str(node_id),
                    "transition": last_transition or event_type,
                    "event_id": event_id,
                    "seq": seq,
                    "event_hash": row.get("event_hash"),
                }
            )
        previous_node_id = str(node_id)

    return _ok(
        source_kind=SOURCE_KIND,
        source_of_truth=SOURCE_KIND,
        derived_artifact=True,
        generated_artifacts_used_for_decision=False,
        mst_session_id=source["mst_session_id"],
        root_mst_id=root_mst_id,
        ledger_path=source["ledger_path"],
        history_head=source["history_head"],
        source=source,
        recognized_event_families=recognized,
        missing_event_families=[],
        current_node=nodes[-1]["id"] if nodes else None,
        last_transition=last_transition,
        next_action=next_action,
        blocker=blocker,
        nodes=nodes,
        edges=edges,
        rows=replay_rows,
    )
def compute_projection_hash(projection: dict[str, Any]) -> str:
    payload = dict(projection)
    payload.pop("projection_hash", None)
    return hashlib.sha256(_canonical_hash_json(payload).encode("utf-8")).hexdigest()
def _source_with_projection_metadata(source: dict[str, Any], projection_created_at: str) -> dict[str, Any]:
    enriched = dict(source)
    enriched["source_kind"] = SOURCE_KIND
    enriched["source_hash"] = source.get("cumulative_hash")
    enriched["projection_created_at"] = projection_created_at
    return enriched
def _artifact_views(source: dict[str, Any]) -> dict[str, Any]:
    ledger_path = Path(str(source.get("ledger_path") or "history.ndjson"))
    session_dir = ledger_path.parent
    mst_session_id = str(source.get("mst_session_id") or "")
    return {
        "execution_flow_json": str(session_dir / "execution-flow.json"),
        "execution_flow_d2": str(session_dir / "execution-flow.d2"),
        "dashboard_flow_view": f"/dashboard/sessions/{mst_session_id}/flow" if mst_session_id else "",
        "cli_flow_view": f"mst.py session flow {mst_session_id}" if mst_session_id else "",
    }
def _projection_handoff_summary(projection: dict[str, Any]) -> dict[str, Any]:
    views = projection.get("views") if isinstance(projection.get("views"), dict) else {}
    blocker = projection.get("blocker")
    critical_blocker = blocker if isinstance(blocker, dict) and blocker.get("critical") is True else None
    return {
        "schema_version": 1,
        "mst_session_id": projection.get("mst_session_id"),
        "root_mst_id": projection.get("root_mst_id"),
        "history_head": projection.get("source", {}).get("history_head") if isinstance(projection.get("source"), dict) else None,
        "current_node": projection.get("current_node"),
        "last_transition": projection.get("last_transition"),
        "rehydration_transition": "continue.rehydrate_retry",
        "next_action": projection.get("next_action"),
        "auto": bool(projection.get("auto")),
        "blocker": blocker,
        "critical_blocker": critical_blocker,
        "flow_view": {
            "execution_flow_json": views.get("execution_flow_json"),
            "execution_flow_d2": views.get("execution_flow_d2"),
        },
    }
def build_execution_flow_projection(
    ledger: dict[str, Any],
    *,
    projection_created_at: str | None = None,
) -> dict[str, Any]:
    replay = replay_ledger_execution_flow(ledger)
    if replay.get("status") != "ok":
        source = _source_from_ledger(ledger) if isinstance(ledger, dict) else {}
        payload = dict(replay)
        payload.setdefault("ledger_path", source.get("ledger_path"))
        payload.setdefault("mst_session_id", source.get("mst_session_id"))
        payload.setdefault("current_head_evidence", source)
        payload["trusted_projection_payload"] = None
        return payload

    created_at = projection_created_at or _iso_utc_now()
    source = _source_with_projection_metadata(dict(replay.get("source") or {}), created_at)
    projection: dict[str, Any] = {
        "schema_version": 1,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "projection_kind": PROJECTION_KIND,
        "mst_session_id": replay.get("mst_session_id"),
        "root_mst_id": replay.get("root_mst_id"),
        "source": source,
        "projection_created_at": created_at,
        "current_node": replay.get("current_node"),
        "last_transition": replay.get("last_transition"),
        "next_action": replay.get("next_action"),
        "nodes": replay.get("nodes") or [],
        "edges": replay.get("edges") or [],
        "blocker": replay.get("blocker"),
        "coverage": {
            "recognized_event_families": replay.get("recognized_event_families") or [],
            "missing_event_families": replay.get("missing_event_families") or [],
            "required_event_families": sorted(REQUIRED_EVENT_FAMILIES),
        },
        "stale": False,
        "read_only": False,
        "regenerate_required": False,
        "derived_artifact": True,
        "source_of_truth": SOURCE_KIND,
        "views": _artifact_views(source),
    }
    projection["handoff_summary"] = _projection_handoff_summary(projection)
    projection["projection_hash"] = compute_projection_hash(projection)
    return _ok(
        projection=projection,
        projection_hash=projection["projection_hash"],
        ledger_path=source.get("ledger_path"),
        mst_session_id=source.get("mst_session_id"),
        history_head=source.get("history_head"),
        trusted_projection_payload=projection,
    )
def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
def _d2_identifier(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"n_{text}"
    return text
def render_execution_flow_d2(
    projection: dict[str, Any],
    current_head: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    head = current_head if isinstance(current_head, dict) else source
    validation = validate_projection_consumption(projection, head, consumers=DECISION_CONSUMERS)
    stale = validation.get("stale") is True
    regenerate_required = validation.get("regenerate_required") is True
    coverage = projection.get("coverage") if isinstance(projection.get("coverage"), dict) else {}
    recognized = coverage.get("recognized_event_families") if isinstance(coverage.get("recognized_event_families"), list) else []
    nodes = projection.get("nodes") if isinstance(projection.get("nodes"), list) else []
    edges = projection.get("edges") if isinstance(projection.get("edges"), list) else []

    lines = [
        f"# source ledger: {source.get('ledger_path')}",
        f"# history_head: {source.get('history_head')}",
        f"# projection_hash: {projection.get('projection_hash')}",
        f"# coverage: {len(recognized)}/{len(REQUIRED_EVENT_FAMILIES)} event families",
        f"# stale: {str(stale).lower()}",
        f"# drift: {str(stale).lower()}",
        f"# regenerate_required: {str(regenerate_required).lower()}",
        f"# read_only: {str(validation.get('read_only') is True).lower()}",
        "",
    ]
    id_map: dict[str, str] = {}
    for index, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"node-{index}")
        d2_id = _d2_identifier(node_id, f"node_{index}")
        id_map[node_id] = d2_id
        label_parts = [node_id]
        kind = node.get("kind")
        if isinstance(kind, str) and kind.strip() and kind not in node_id:
            label_parts.append(kind)
        skill = node.get("skill")
        if isinstance(skill, str) and skill.strip() and skill not in label_parts:
            label_parts.append(skill)
        lines.append(f'{d2_id}: "{ " | ".join(label_parts) }"')
    if nodes and edges:
        lines.append("")
    for index, edge in enumerate(edges, 1):
        if not isinstance(edge, dict):
            continue
        source_id = str(edge.get("from") or "")
        target_id = str(edge.get("to") or "")
        from_id = id_map.get(source_id) or _d2_identifier(source_id, f"edge_{index}_from")
        to_id = id_map.get(target_id) or _d2_identifier(target_id, f"edge_{index}_to")
        label = str(edge.get("transition") or edge.get("event_type") or "transition")
        lines.append(f'{from_id} -> {to_id}: "{label}"')
    return _ok(
        d2="\n".join(lines).rstrip() + "\n",
        stale=stale,
        drift=stale,
        regenerate_required=regenerate_required,
        read_only=validation.get("read_only") is True,
        validation=validation,
    )
def write_execution_flow_d2(
    projection: dict[str, Any],
    output_dir: str | Path,
    current_head: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rendered = render_execution_flow_d2(projection, current_head)
    if rendered.get("status") != "ok":
        return rendered
    path = Path(output_dir) / "execution-flow.d2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(rendered["d2"]), encoding="utf-8")
    return rendered | {"path": str(path)}
def generate_execution_flow_artifacts(
    ledger: dict[str, Any],
    output_dir: str | Path,
    *,
    projection_created_at: str | None = None,
) -> dict[str, Any]:
    built = build_execution_flow_projection(ledger, projection_created_at=projection_created_at)
    if built.get("status") != "ok":
        return built

    projection = built["projection"]
    out = Path(output_dir)
    json_path = out / "execution-flow.json"
    d2_path = out / "execution-flow.d2"
    projection = dict(projection)
    views = dict(projection.get("views") or {})
    views["execution_flow_json"] = str(json_path)
    views["execution_flow_d2"] = str(d2_path)
    projection["views"] = views
    projection["handoff_summary"] = _projection_handoff_summary(projection)
    projection["projection_hash"] = compute_projection_hash(projection)
    _write_json(json_path, projection)
    d2_result = write_execution_flow_d2(projection, out, projection.get("source") if isinstance(projection.get("source"), dict) else None)
    if d2_result.get("status") != "ok":
        try:
            json_path.unlink()
        except FileNotFoundError:
            pass
        return d2_result
    return _ok(
        projection=projection,
        projection_hash=projection["projection_hash"],
        paths={
            "execution_flow_json": str(json_path),
            "execution_flow_d2": str(d2_path),
        },
        trusted_output_generated=True,
        derived_artifact=True,
    )
def validate_projection_consumption(
    projection: dict[str, Any],
    current_head: dict[str, Any],
    *,
    consumers: Iterable[str] | None = None,
) -> dict[str, Any]:
    consumers_set = set(consumers or DECISION_CONSUMERS)
    current = validate_source_ledger_head(current_head)
    if current.get("status") != "ok":
        return current | {
            "consumer_permissions": {consumer: False for consumer in sorted(consumers_set)},
            "trusted_projection_payload": None,
        }
    source = projection.get("source") if isinstance(projection, dict) else None
    source = source if isinstance(source, dict) else {}
    source_history_head = source.get("history_head")
    source_hash = source.get("source_hash") or source.get("cumulative_hash")
    stale = (
        source_history_head != current_head.get("history_head")
        or source_hash != current_head.get("cumulative_hash")
        or source.get("ledger_path") != current_head.get("ledger_path")
        or source.get("mst_session_id") != current_head.get("mst_session_id")
    )
    if stale:
        return _failure(
            "stale_projection",
            diagnostics=[
                _diagnostic(
                    "stale_projection",
                    field="source.history_head",
                    reason="projection source ledger head does not match current verified ledger head",
                    expected=current_head.get("history_head"),
                    actual=source_history_head,
                )
            ],
            status="stale",
            stale=True,
            read_only=True,
            regenerate_required=True,
            ledger_path=current_head.get("ledger_path") or source.get("ledger_path"),
            mst_session_id=current_head.get("mst_session_id") or source.get("mst_session_id"),
            source_history_head=source_history_head,
            current_history_head=current_head.get("history_head"),
            source_cumulative_hash=source_hash,
            current_cumulative_hash=current_head.get("cumulative_hash"),
            consumer_permissions={consumer: False for consumer in sorted(consumers_set)},
            on_stale_transition="guard.inspect_only_verification",
            trusted_projection_payload=None,
        )
    return _ok(
        stale=False,
        read_only=False,
        regenerate_required=False,
        source_history_head=source_history_head,
        current_history_head=current_head.get("history_head"),
        consumer_permissions={consumer: True for consumer in sorted(consumers_set)},
        trusted_projection_payload=projection,
    )
def _handoff_flow_view(handoff: dict[str, Any]) -> dict[str, Any]:
    flow_view = handoff.get("flow_view")
    return dict(flow_view) if isinstance(flow_view, dict) else {}
def _handoff_cursor_payload(handoff: dict[str, Any]) -> dict[str, Any]:
    blocker = handoff.get("blocker")
    critical_blocker = handoff.get("critical_blocker")
    return {
        "schema_version": 1,
        "mst_session_id": handoff.get("mst_session_id"),
        "root_mst_id": handoff.get("root_mst_id"),
        "history_head": handoff.get("history_head"),
        "current_node": handoff.get("current_node"),
        "last_transition": handoff.get("last_transition"),
        "rehydration_transition": handoff.get("rehydration_transition") or "continue.rehydrate_retry",
        "next_action": handoff.get("next_action"),
        "auto": bool(handoff.get("auto")),
        "blocker": blocker if blocker is not None else None,
        "critical_blocker": critical_blocker if critical_blocker is not None else None,
        "flow_view": {
            "execution_flow_json": _handoff_flow_view(handoff).get("execution_flow_json"),
            "execution_flow_d2": _handoff_flow_view(handoff).get("execution_flow_d2"),
        },
    }
def build_compaction_handoff_summary(
    projection: dict[str, Any],
    current_head: dict[str, Any],
    *,
    auto: bool | None = None,
) -> dict[str, Any]:
    validation = validate_projection_consumption(projection, current_head, consumers={"handoff_consumption"})
    if validation.get("status") != "ok":
        payload = dict(validation)
        payload["handoff_generation_allowed"] = False
        payload["trusted_output_generated"] = False
        return payload

    handoff = _projection_handoff_summary(projection)
    if auto is not None:
        handoff["auto"] = bool(auto)
    required = [
        "mst_session_id",
        "root_mst_id",
        "history_head",
        "current_node",
        "last_transition",
        "next_action",
        "flow_view",
    ]
    missing = [field for field in required if handoff.get(field) in (None, "", {})]
    flow_view = _handoff_flow_view(handoff)
    for field in ("execution_flow_json", "execution_flow_d2"):
        if flow_view.get(field) in (None, ""):
            missing.append(f"flow_view.{field}")
    if missing:
        return _failure(
            "handoff_required_field_missing",
            diagnostics=[
                _diagnostic(
                    "handoff_required_field_missing",
                    field=field,
                    reason="compaction handoff requires concise cursor and provenance fields",
                )
                for field in missing
            ],
            handoff_generation_allowed=False,
            trusted_output_generated=False,
        )

    concise = _handoff_cursor_payload(handoff)
    return _ok(
        handoff=concise,
        derived_from="verified_execution_flow_projection",
        source_kind=SOURCE_KIND,
        trusted_output_generated=True,
        handoff_generation_allowed=True,
        prompt_summary_used_as_source=False,
    )
