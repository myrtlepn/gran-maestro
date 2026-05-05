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


def validate_compaction_handoff_consumption(
    handoff: dict[str, Any],
    current_head: dict[str, Any],
) -> dict[str, Any]:
    current = validate_source_ledger_head(current_head)
    if current.get("status") != "ok":
        payload = dict(current)
        payload.update(
            {
                "write_allowed": False,
                "auto_write_allowed": False,
                "next_action_execution_allowed": False,
                "trusted_handoff_payload": None,
            }
        )
        return payload
    if not isinstance(handoff, dict):
        return _failure(
            "handoff_invalid",
            diagnostics=[_diagnostic("handoff_invalid", field="handoff", reason="handoff must be a JSON object")],
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            trusted_handoff_payload=None,
        )

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
                    reason="handoff is missing required cursor/provenance field",
                )
                for field in missing
            ],
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            trusted_handoff_payload=None,
        )

    mismatches = []
    comparisons = {
        "mst_session_id": current_head.get("mst_session_id"),
        "history_head": current_head.get("history_head"),
    }
    for field, expected in comparisons.items():
        if handoff.get(field) != expected:
            mismatches.append(
                _diagnostic(
                    "stale_handoff",
                    field=field,
                    reason="compaction handoff provenance does not match current verified ledger head",
                    expected=expected,
                    actual=handoff.get(field),
                )
            )
    if mismatches:
        return _failure(
            "stale_handoff",
            diagnostics=mismatches,
            status="stale",
            stale=True,
            read_only=True,
            regenerate_required=True,
            source_history_head=handoff.get("history_head"),
            current_history_head=current_head.get("history_head"),
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            on_stale_transition="guard.inspect_only_verification",
            next_safe_action="inspect-only state/history consistency verification",
            mismatch_subject="compaction_handoff.history_head",
            trusted_handoff_payload=None,
        )

    critical_blocker = handoff.get("critical_blocker")
    blocker_present = isinstance(critical_blocker, dict) and bool(critical_blocker)
    return _ok(
        stale=False,
        read_only=False,
        regenerate_required=False,
        source_history_head=handoff.get("history_head"),
        current_history_head=current_head.get("history_head"),
        write_allowed=not blocker_present,
        auto_write_allowed=not blocker_present and bool(handoff.get("auto")),
        next_action_execution_allowed=not blocker_present,
        trusted_handoff_payload=_handoff_cursor_payload(handoff),
        prompt_summary_used_as_source=False,
    )


def assemble_rehydration_continuation_context(
    core_rehydration: dict[str, Any],
    verified_handoff: dict[str, Any],
    prompt_summary: dict[str, Any] | None,
    current_head: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_compaction_handoff_consumption(verified_handoff, current_head)
    if validation.get("status") != "ok":
        payload = dict(validation)
        payload["context_delivery_order"] = ["core_rehydration", "execution_flow_handoff", "prompt_summary"]
        payload["write_allowed"] = False
        payload["next_action_execution_allowed"] = False
        return payload

    handoff = validation["trusted_handoff_payload"]
    core = dict(core_rehydration) if isinstance(core_rehydration, dict) else {}
    budgeted_context = {
        "execution_flow_handoff": handoff,
        "prompt_summary": prompt_summary if isinstance(prompt_summary, dict) else {},
        "omissions": [
            "full execution-flow nodes omitted; use flow_view.execution_flow_json for details",
            "full execution-flow D2 omitted; use flow_view.execution_flow_d2 for details",
        ],
    }
    return _ok(
        schema_version=1,
        core_rehydration=core,
        budgeted_context=budgeted_context,
        context_delivery_order=["core_rehydration", "execution_flow_handoff", "prompt_summary"],
        source_precedence=[
            "verified_history_ledger",
            "verified_execution_flow_handoff",
            "prompt_summary_diagnostic_only",
        ],
        prompt_summary_used_as_source=False,
        write_allowed=validation.get("write_allowed") is True,
        auto_write_allowed=validation.get("auto_write_allowed") is True,
        next_action_execution_allowed=validation.get("next_action_execution_allowed") is True,
        continuation={
            "mode": "continue_unless_critical",
            "next_action": handoff.get("next_action"),
            "last_transition": handoff.get("rehydration_transition") or "continue.rehydrate_retry",
            "critical_blocker": handoff.get("critical_blocker"),
        },
    )


def _append_ledger_row(rows: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any]:
    prev_hash = rows[-1].get("event_hash") if rows else ZERO_HASH
    seq = len(rows) + 1
    event_hash = _event_hash(str(prev_hash), event)
    row = {
        "schema_version": 1,
        "seq": seq,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "mst_session_id": event.get("mst_session_id"),
        "root_mst_id": event.get("root_mst_id"),
        "event_type": event.get("event_type"),
        "created_at": event.get("created_at"),
        "idempotency_key": event.get("idempotency_key"),
        "event": event,
    }
    rows.append(row)
    return row


def append_context_handoff_evidence_events(
    ledger: dict[str, Any],
    handoff: dict[str, Any],
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return _failure("ledger_invalid", diagnostics=[_diagnostic("ledger_invalid", field="ledger", reason="ledger must be a JSON object")])
    if ledger.get("verified") is not True:
        return _failure(
            "ledger_not_verified",
            diagnostics=[_diagnostic("ledger_not_verified", field="verified", reason="history ledger must be verified before context event append")],
        )
    source = _source_from_ledger(ledger)
    head_result = validate_source_ledger_head(source)
    if head_result.get("status") != "ok":
        return head_result
    consumption = validate_compaction_handoff_consumption(handoff, source)
    if consumption.get("status") != "ok":
        return consumption

    session_id = str(source["mst_session_id"])
    root_mst_id = str(ledger.get("root_mst_id") or handoff.get("root_mst_id") or "")
    timestamp = created_at or _iso_utc_now()
    updated = dict(ledger)
    rows = [dict(row) for row in _ledger_rows(ledger)]
    handoff_payload = consumption["trusted_handoff_payload"]
    compacted_event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(f"{session_id}:context.compacted:{source['history_head']}".encode("utf-8")).hexdigest()[:24],
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "event_type": "context.compacted",
        "type": "context.compacted",
        "created_at": timestamp,
        "idempotency_key": f"{session_id}:context.compacted:{source['history_head']}",
        "history_head": source["history_head"],
        "execution_flow_handoff": handoff_payload,
        "handoff_generation_evidence": {
            "source": "verified_execution_flow_projection",
            "history_head": source["history_head"],
            "flow_view": handoff_payload.get("flow_view"),
        },
    }
    compacted_row = _append_ledger_row(rows, compacted_event)
    rehydrated_event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(f"{session_id}:context.rehydrated:{compacted_row['event_hash']}".encode("utf-8")).hexdigest()[:24],
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "event_type": "context.rehydrated",
        "type": "context.rehydrated",
        "created_at": timestamp,
        "idempotency_key": f"{session_id}:context.rehydrated:{compacted_row['event_hash']}",
        "history_head": compacted_row["event_hash"],
        "execution_flow_handoff": handoff_payload,
        "handoff_consumption_evidence": {
            "source": "verified_execution_flow_handoff",
            "handoff_history_head": handoff_payload.get("history_head"),
            "prompt_summary_used_as_source": False,
        },
        "prompt_summary_used_as_source": False,
        "rehydration_transition": handoff_payload.get("rehydration_transition") or "continue.rehydrate_retry",
        "next_action": handoff_payload.get("next_action"),
    }
    rehydrated_row = _append_ledger_row(rows, rehydrated_event)
    new_source = dict(source)
    new_source.update(
        {
            "last_event_id": rehydrated_event["event_id"],
            "last_event_seq": len(rows),
            "cumulative_hash": rehydrated_row["event_hash"],
            "event_count": len(rows),
            "history_head": rehydrated_row["event_hash"],
        }
    )
    updated["source"] = new_source
    updated["rows"] = rows
    updated["verified"] = True
    return _ok(
        ledger=updated,
        mst_session_id=session_id,
        root_mst_id=root_mst_id,
        same_session_ledger=True,
        history_head=rehydrated_row["event_hash"],
        event_append_evidence={
            "compacted": "context.compacted",
            "rehydrated": "context.rehydrated",
            "handoff_generated": True,
            "handoff_consumed": True,
        },
    )


def validate_gran_maestro_owned_handoff_scope(changed_paths: Iterable[str]) -> dict[str, Any]:
    allowed_prefixes = (
        "scripts/",
        "hooks/",
        "skills/",
        "dashboard/",
        "tests/",
        "docs/",
        "frontend/",
        "templates/",
        "src/",
        ".gran-maestro/",
    )
    forbidden: list[str] = []
    for raw_path in changed_paths:
        path = str(raw_path)
        normalized = path.replace("\\", "/")
        if "/claude-code/" in normalized or normalized.startswith("claude-code/"):
            forbidden.append(path)
            continue
        relative = normalized.lstrip("/")
        if relative.startswith(allowed_prefixes):
            continue
        parts = normalized.split("/gran-maestro/", 1)
        if len(parts) == 2 and parts[1].startswith(allowed_prefixes):
            continue
    if forbidden:
        return _failure(
            "claude_code_core_scope_violation",
            diagnostics=[
                _diagnostic(
                    "claude_code_core_scope_violation",
                    field="changed_paths",
                    reason="DOD-017 handoff wiring must not modify Claude Code core source",
                    path=path,
                )
                for path in forbidden
            ],
            claude_code_core_modified=True,
            allowed_surface="gran_maestro_owned",
            changed_paths=list(changed_paths),
        )
    return _ok(
        claude_code_core_modified=False,
        allowed_surface="gran_maestro_owned",
        changed_paths=list(changed_paths),
    )


def _coverage_summary(projection: dict[str, Any]) -> dict[str, Any]:
    coverage = projection.get("coverage") if isinstance(projection.get("coverage"), dict) else {}
    recognized = coverage.get("recognized_event_families")
    missing = coverage.get("missing_event_families")
    required = coverage.get("required_event_families")
    nodes = projection.get("nodes") if isinstance(projection.get("nodes"), list) else []
    edges = projection.get("edges") if isinstance(projection.get("edges"), list) else []
    return {
        "recognized_event_families": list(recognized) if isinstance(recognized, list) else [],
        "missing_event_families": list(missing) if isinstance(missing, list) else [],
        "required_event_families": list(required) if isinstance(required, list) else sorted(REQUIRED_EVENT_FAMILIES),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _projection_display_status(projection: dict[str, Any], current_head: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validation = validate_projection_consumption(projection, current_head, consumers=DECISION_CONSUMERS)
    stale = validation.get("stale") is True
    status = {
        "stale": stale,
        "drift": stale,
        "regenerate_required": validation.get("regenerate_required") is True,
        "read_only": validation.get("read_only") is True,
        "source_history_head": validation.get("source_history_head"),
        "current_history_head": validation.get("current_history_head"),
        "on_stale_transition": validation.get("on_stale_transition"),
    }
    return validation, status


def build_dashboard_flow_view(projection: dict[str, Any], current_head: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    validation, projection_status = _projection_display_status(projection, current_head)
    coverage = _coverage_summary(projection)
    status = "ok" if validation.get("status") in {"ok", "stale"} else validation.get("status", "validation_failed")
    return {
        "status": status,
        "accepted": validation.get("status") in {"ok", "stale"},
        "fail_closed": validation.get("status") not in {"ok", "stale"},
        "view_kind": "dod017.execution-flow.dashboard-view",
        "schema_version": 1,
        "projection_kind": projection.get("projection_kind") or PROJECTION_KIND,
        "mst_session_id": projection.get("mst_session_id"),
        "root_mst_id": projection.get("root_mst_id"),
        "source": {
            "source_kind": source.get("source_kind") or SOURCE_KIND,
            "ledger_path": source.get("ledger_path"),
            "history_head": source.get("history_head"),
            "source_hash": source.get("source_hash") or source.get("cumulative_hash"),
            "projection_schema_version": projection.get("projection_schema_version"),
            "projection_hash": projection.get("projection_hash"),
            "projection_created_at": projection.get("projection_created_at") or source.get("projection_created_at"),
        },
        "projection_status": projection_status,
        "coverage": coverage,
        "current_node": projection.get("current_node"),
        "last_transition": projection.get("last_transition"),
        "next_action": projection.get("next_action"),
        "blocker": projection.get("blocker"),
        "views": projection.get("views") if isinstance(projection.get("views"), dict) else {},
        "display_only": True,
        "derived_artifact": True,
        "next_action_authority": False,
        "transition_authority": "dod016_transition_graph",
        "decision_sources": [SOURCE_KIND, "dod016_transition_graph"],
        "consumer_permissions": validation.get("consumer_permissions", {}),
        "diagnostics": validation.get("diagnostics", []),
    }


def render_cli_flow_view(projection: dict[str, Any], current_head: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )
    validation, projection_status = _projection_display_status(projection, current_head)
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    stale = projection_status["stale"]
    state = "stale/read-only/regenerate-required" if stale else "fresh/display-only"
    text = "\n".join(
        [
            "DOD-017 actual execution-flow (display-only)",
            f"session: {projection.get('mst_session_id')}",
            f"source ledger: {source.get('ledger_path')}",
            f"projection history_head: {source.get('history_head')}",
            f"current history_head: {current_head.get('history_head') if isinstance(current_head, dict) else None}",
            f"projection_hash: {projection.get('projection_hash')}",
            f"status: {state}",
            f"read-only: {str(projection_status['read_only']).lower()}",
            f"regenerate-required: {str(projection_status['regenerate_required']).lower()}",
            "authority: DOD-016 transition graph + verified ledger only; this projection is not next-action authority",
        ]
    )
    payload = dict(validation)
    payload.update(
        {
            "view_kind": "dod017.execution-flow.cli-view",
            "display_only": True,
            "derived_artifact": True,
            "next_action_authority": False,
            "transition_authority": "dod016_transition_graph",
            "read_only": projection_status["read_only"],
            "regenerate_required": projection_status["regenerate_required"],
            "stale": projection_status["stale"],
            "drift": projection_status["drift"],
            "text": text,
        }
    )
    return payload


def separate_graph_and_execution_flow_views(
    graph_view: dict[str, Any],
    execution_flow_projection: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(graph_view, dict):
        return _failure(
            "graph_view_invalid",
            diagnostics=[_diagnostic("graph_view_invalid", field="graph_view", reason="graph view must be a JSON object")],
        )
    if not isinstance(execution_flow_projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )

    graph_source = graph_view.get("source_graph") if isinstance(graph_view.get("source_graph"), dict) else {}
    flow_source = (
        execution_flow_projection.get("source")
        if isinstance(execution_flow_projection.get("source"), dict)
        else {}
    )
    possible = {
        "label": "DOD-016 possible-transition graph",
        "schema_id": graph_view.get("kind") or "mst-transition-graph-view",
        "artifact_kind": "possible-transition graph",
        "source_of_truth": "dod016_transition_graph",
        "source_provenance": {
            "graph_id": graph_source.get("id"),
            "graph_version": graph_source.get("version"),
            "graph_hash": graph_source.get("hash"),
            "source_graph_path": graph_view.get("source_graph_path"),
        },
        "coverage": {
            "covered_states": list(graph_view.get("covered_states") or []),
            "covered_transitions": list(graph_view.get("covered_transitions") or []),
        },
        "transition_authority": True,
    }
    actual = {
        "label": "DOD-017 actual execution-flow",
        "schema_id": execution_flow_projection.get("projection_kind") or PROJECTION_KIND,
        "artifact_kind": "actual execution-flow",
        "source_of_truth": SOURCE_KIND,
        "source_provenance": {
            "ledger_path": flow_source.get("ledger_path"),
            "history_head": flow_source.get("history_head"),
            "source_hash": flow_source.get("source_hash") or flow_source.get("cumulative_hash"),
            "projection_hash": execution_flow_projection.get("projection_hash"),
            "projection_schema_version": execution_flow_projection.get("projection_schema_version"),
        },
        "coverage": _coverage_summary(execution_flow_projection),
        "display_only": True,
        "next_action_authority": False,
    }
    return _ok(
        separated=True,
        possible_transition_graph=possible,
        actual_execution_flow=actual,
        transition_authority="dod016_transition_graph",
        display_context="dod017.execution-flow",
    )


def validate_execution_flow_source_boundary(envelope: dict[str, Any]) -> dict[str, Any]:
    ledger = envelope.get("verified_history_ledger") if isinstance(envelope, dict) else None
    graph = envelope.get("dod016_transition_graph") if isinstance(envelope, dict) else None
    if not isinstance(ledger, dict):
        return _failure(
            "verified_history_ledger_missing",
            diagnostics=[
                _diagnostic(
                    "verified_history_ledger_missing",
                    field="verified_history_ledger",
                    reason="actual execution-flow source must be the verified history ledger",
                )
            ],
        )
    if not isinstance(graph, dict):
        return _failure(
            "dod016_transition_graph_missing",
            diagnostics=[
                _diagnostic(
                    "dod016_transition_graph_missing",
                    field="dod016_transition_graph",
                    reason="transition authority must be the DOD-016 graph",
                )
            ],
        )
    return _ok(
        source_of_truth={
            "actual_execution_flow": SOURCE_KIND,
            "transition_authority": "dod016_transition_graph",
        },
        generated_artifacts_used_for_decision=False,
        decision_sources=[SOURCE_KIND, "dod016_transition_graph"],
        rejected_sources=[
            "execution-flow.json",
            "execution-flow.d2",
            "dashboard/CLI view",
            "compaction handoff summary",
            "snapshot/cache/prompt summary",
        ],
        artifact_roles={
            "execution_flow_json": "derived_only",
            "execution_flow_d2": "display_only",
            "dashboard_cli_view": "display_only",
            "compaction_handoff_summary": "derived_only",
            "snapshot_cache": "auxiliary_only",
            "prompt_summary": "auxiliary_only",
        },
        decision_consumers=list(envelope.get("decision_consumers") or []),
    )


def evaluate_projection_transition_authority(
    attempt: dict[str, Any],
    projection: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    from scripts.mst_cmds import transition_graph

    graph_result = transition_graph.validate_attempted_transition(dict(attempt), graph)
    transition_id = attempt.get("attempted_transition")
    transition = graph.get("transitions", {}).get(transition_id) if isinstance(graph.get("transitions"), dict) else None
    if graph_result.get("accepted") is not True:
        return _failure(
            "transition_graph_rejected",
            diagnostics=[
                _diagnostic(
                    "transition_graph_rejected",
                    field="attempted_transition",
                    reason="DOD-016 transition graph rejected the attempted transition",
                    attempted_transition=transition_id,
                )
            ],
            attempted_transition=transition_id,
            authority="dod016_transition_graph",
            projection_authorized=False,
            projection_used_as_authority=False,
            on_reject=transition.get("on_reject") if isinstance(transition, dict) else graph_result.get("on_reject"),
            graph_result=graph_result,
            trusted_projection_payload=None,
        )
    return _ok(
        attempted_transition=transition_id,
        authority="dod016_transition_graph",
        projection_authorized=False,
        projection_used_as_authority=False,
        graph_result=graph_result,
        projection_observed=projection,
    )


def evaluate_hook_hot_path(envelope: dict[str, Any], *, operations: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = envelope if isinstance(envelope, dict) else {}
    cursor = payload.get("cursor_state") if isinstance(payload.get("cursor_state"), dict) else None
    cache = payload.get("cache_state") if isinstance(payload.get("cache_state"), dict) else None
    current_head = payload.get("current_head_evidence") if isinstance(payload.get("current_head_evidence"), dict) else {}
    queued_action = payload.get("queued_action") if isinstance(payload.get("queued_action"), dict) else None
    no_full_work = {
        "hot_path_full_ledger_replay": False,
        "hot_path_execution_flow_projection": False,
        "hot_path_d2_rendering": False,
        "hot_path_dashboard_rendering": False,
    }

    head_result = validate_source_ledger_head(current_head)
    if head_result.get("status") != "ok":
        return dict(head_result) | no_full_work | {
            "status": "validation_failed",
            "accepted": False,
            "fail_closed": True,
            "write_allowed": False,
            "next_route": "terminal.state_inconsistency",
            "next_safe_action": "inspect-only state/history consistency verification",
            "mismatch_subject": "current_head_evidence",
            "mst_session_id": payload.get("mst_session_id"),
            "current_history_head": current_head.get("history_head"),
            "queued_action": queued_action,
        }

    current_history_head = current_head.get("history_head")
    current_cumulative_hash = current_head.get("cumulative_hash")
    current_session_id = current_head.get("mst_session_id")
    valid_statuses = {"ok", "fresh", "hit", "valid", "current"}
    stale_statuses = {"stale", "miss", "missing", "invalid", "mismatch", "expired"}

    diagnostics: list[dict[str, Any]] = []

    def state_status(state: dict[str, Any] | None) -> str:
        if state is None:
            return "missing"
        return str(state.get("status") or "").strip().lower() or "missing"

    def state_history_head(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("history_head") or state.get("current_history_head") or source.get("history_head") or provenance.get("history_head")

    def state_cumulative_hash(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("cumulative_hash") or state.get("source_hash") or source.get("cumulative_hash") or source.get("source_hash") or provenance.get("cumulative_hash")

    def state_session_id(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("mst_session_id") or source.get("mst_session_id") or provenance.get("mst_session_id")

    def provenance_for(state: dict[str, Any] | None, default_source: str) -> dict[str, Any]:
        if not isinstance(state, dict):
            return {"source": default_source, "status": "missing"}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        merged = dict(provenance)
        merged.setdefault("source", state.get("source_name") or state.get("source_kind") or default_source)
        merged.setdefault("status", state_status(state))
        merged.setdefault("history_head", state_history_head(state))
        return {key: value for key, value in merged.items() if value not in (None, "")}

    def validate_current_state(name: str, state: dict[str, Any] | None) -> None:
        status_value = state_status(state)
        if status_value not in valid_statuses:
            code = "hook_current_state_cache_missing" if status_value in stale_statuses else "hook_current_state_cache_invalid"
            diagnostics.append(
                _diagnostic(
                    code,
                    field=name,
                    reason="hook hot path requires fresh precomputed current-state cursor/cache",
                    actual=status_value,
                    expected=sorted(valid_statuses),
                )
            )
            return
        state_head = state_history_head(state)
        if state_head != current_history_head:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_stale",
                    field=f"{name}.history_head",
                    reason="hook current-state cursor/cache history_head does not match current ledger head evidence",
                    expected=current_history_head,
                    actual=state_head,
                )
            )
        state_hash = state_cumulative_hash(state)
        if state_hash is not None and state_hash != current_cumulative_hash:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_stale",
                    field=f"{name}.cumulative_hash",
                    reason="hook current-state cursor/cache cumulative_hash does not match current ledger head evidence",
                    expected=current_cumulative_hash,
                    actual=state_hash,
                )
            )
        state_sid = state_session_id(state)
        if state_sid is not None and state_sid != current_session_id:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_mismatch",
                    field=f"{name}.mst_session_id",
                    reason="hook current-state cursor/cache belongs to a different MST session",
                    expected=current_session_id,
                    actual=state_sid,
                )
            )

    validate_current_state("cursor_state", cursor)
    validate_current_state("cache_state", cache)
    if diagnostics:
        first_field = str(diagnostics[0].get("field") or "hook_current_state_cache")
        return _failure(
            diagnostics[0]["code"],
            diagnostics=diagnostics,
            status="inspect_only",
            **no_full_work,
            mst_session_id=payload.get("mst_session_id") or current_session_id,
            current_history_head=current_history_head,
            history_head=current_history_head,
            current_head_evidence=current_head,
            write_allowed=False,
            next_route="guard.inspect_only_verification",
            on_stale_transition="guard.inspect_only_verification",
            next_safe_action="inspect-only state/history consistency verification",
            mismatch_subject=first_field.split(".", 1)[0],
            queued_action=queued_action,
            trusted_cursor_state=None,
        )

    source_state = cursor if isinstance(cursor, dict) else cache
    cache_state = cache if isinstance(cache, dict) else cursor
    next_action = source_state.get("next_action") if isinstance(source_state.get("next_action"), dict) else None
    return _ok(
        **no_full_work,
        mst_session_id=payload.get("mst_session_id") or current_session_id,
        current_history_head=current_history_head,
        history_head=current_history_head,
        current_head_evidence=current_head,
        current_node=source_state.get("current_node"),
        last_transition=source_state.get("last_transition"),
        next_action=next_action or queued_action,
        queued_action=queued_action,
        write_allowed=True,
        next_route="continue.queued_action" if queued_action else None,
        hot_path_current_state_source="cursor_state" if isinstance(cursor, dict) else "cache_state",
        provenance={
            "cursor_state": provenance_for(cursor, "cursor_state"),
            "cache_state": provenance_for(cache_state, "cache_state"),
        },
        trusted_cursor_state={
            "cursor_state": cursor,
            "cache_state": cache,
        },
    )


def validate_source_ledger_for_projection(ledger: dict[str, Any], projection_source: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return _failure("ledger_invalid", diagnostics=[_diagnostic("ledger_invalid", field="ledger", reason="ledger must be a JSON object")])
    if ledger.get("verified") is not True:
        return _failure(
            "ledger_not_verified",
            diagnostics=[_diagnostic("ledger_not_verified", field="verified", reason="history ledger must be verified before projection source validation")],
            trusted_projection_payload=None,
        )
    current_head = _source_from_ledger(ledger)
    head_result = validate_source_ledger_head(current_head)
    if head_result.get("status") != "ok":
        return head_result | {"trusted_projection_payload": None}
    row_diagnostics = _validate_rows_against_source(ledger, current_head)
    if row_diagnostics:
        return _failure(
            row_diagnostics[0]["code"],
            diagnostics=row_diagnostics,
            ledger_path=current_head.get("ledger_path"),
            mst_session_id=current_head.get("mst_session_id"),
            current_head_evidence=current_head,
            trusted_projection_payload=None,
        )
    if projection_source is None:
        return validate_source_ledger_head(current_head)
    return validate_projection_consumption({"source": projection_source}, current_head, consumers=DECISION_CONSUMERS)


def validate_source_ledger_projection_source(
    ledger: dict[str, Any],
    projection_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_source_ledger_for_projection(ledger, projection_source)


def resolve_canonical_mst_session_identity(
    payload: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    env = env if env is not None else os.environ
    env_value = str(env.get("MST_SESSION_ID") or "").strip()
    payload_value = payload.get("mst_session_id")
    payload_value = payload_value.strip() if isinstance(payload_value, str) else ""
    legacy_diagnostics: dict[str, Any] = {}
    for key in ("MST_STATE_PPID", "session_id", "hook_transcript_uuid", "transcript_uuid"):
        value = env.get(key) if key.startswith("MST_") else payload.get(key)
        if isinstance(value, str) and value.strip():
            legacy_diagnostics[key] = value.strip()

    if env_value and payload_value and env_value != payload_value:
        return _failure(
            "canonical_mst_session_id_mismatch",
            diagnostics=[
                _diagnostic(
                    "canonical_mst_session_id_mismatch",
                    field="mst_session_id",
                    reason="MST_SESSION_ID and payload mst_session_id must match",
                    expected=env_value,
                    actual=payload_value,
                )
            ],
            canonical_mst_session_id=None,
            legacy_diagnostics=legacy_diagnostics,
        )

    candidate = env_value or payload_value
    if not candidate:
        return _common.session_identity_non_success_payload("execution-flow replay") | {
            "fail_closed": True,
            "accepted": False,
            "legacy_diagnostics": legacy_diagnostics or _common.legacy_session_diagnostics(),
        }

    try:
        parsed = session_cmds.validate_mst_session_id(candidate)
    except Exception as exc:
        return _failure(
            "invalid_mst_session_id",
            diagnostics=[
                _diagnostic("invalid_mst_session_id", field="mst_session_id", reason=str(exc), actual=candidate)
            ],
            canonical_mst_session_id=None,
            legacy_diagnostics=legacy_diagnostics,
        )
    return _ok(
        canonical_mst_session_id=parsed.mst_session_id,
        mst_session_id=parsed.mst_session_id,
        root_mst_id=parsed.root_mst_id,
        identity_source="MST_SESSION_ID" if env_value else "mst_session_id",
        ignored_legacy_identity_sources=sorted(legacy_diagnostics),
        legacy_diagnostics=legacy_diagnostics,
    )


def resolve_canonical_mst_session_id(
    payload: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return resolve_canonical_mst_session_identity(payload, env)


def load_verified_history_source(project_root: str | Path, policy_home: str | Path, mst_session_id: str) -> dict[str, Any]:
    from scripts.mst_cmds import hook

    try:
        history = hook._load_validated_history(
            project_root=Path(project_root),
            policy_home=Path(policy_home),
            raw_session_id=mst_session_id,
        )
    except hook.HistoryValidationError as exc:
        return _failure(
            exc.code,
            diagnostics=[_diagnostic(exc.code, field="history", reason=exc.message)],
            current_head_evidence=exc.details,
            trusted_projection_payload=None,
        )

    source = {
        "ledger_path": str(history.history_file),
        "mst_session_id": history.session_id,
        "last_event_id": _row_event(history.rows[-1]).get("event_id") or history.tail_hash,
        "last_event_seq": history.tail_seq,
        "cumulative_hash": history.tail_hash,
        "event_count": history.tail_seq,
        "ledger_schema_version": 1,
        "history_head": history.tail_hash,
    }
    return {
        "schema_version": 1,
        "mst_session_id": history.session_id,
        "root_mst_id": history.root_mst_id,
        "ledger_path": str(history.history_file),
        "verified": True,
        "source": source,
        "rows": history.rows,
    }
