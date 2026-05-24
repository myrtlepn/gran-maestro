from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_STATUS = (
    "ok",
    "not_applicable",
    "not_seen",
    "stale",
    "identity_mismatch",
    "write_failed",
    "schema_invalid",
    "unknown",
)

ROW_FIELDS = (
    "writer_id",
    "expected",
    "observed",
    "status",
    "last_event_type",
    "last_event",
    "last_success_at",
    "last_error_at",
    "last_error",
    "last_source_head",
    "reason",
    "evidence_path",
)

DEFAULT_WRITER_MATRIX = (
    {
        "writer_id": "cli_invocation",
        "expected": True,
        "expected_events": ("mst.invocation_start", "mst.invocation_end", "mst.invocation_error"),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    },
    {
        "writer_id": "state_writer",
        "expected": True,
        "expected_events": ("skill.enter", "skill.step", "skill.exit", "state.evidence"),
        "evidence_path": ".gran-maestro/state/{mst_session_id}/snapshot.json",
    },
    {
        "writer_id": "dispatch_writer",
        "expected": True,
        "expected_events": ("dispatch.register", "dispatch.heartbeat"),
        "evidence_path": ".gran-maestro/run/*",
    },
    {
        "writer_id": "bash_history_writer",
        "expected": True,
        "expected_events": ("tool_call",),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    },
    {
        "writer_id": "policy_writer",
        "expected": True,
        "expected_events": ("policy_block", "confirm_requested", "core_block", "override_granted"),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    },
    {
        "writer_id": "stop_continuation_writer",
        "expected": True,
        "expected_events": ("continue.*", "terminal.*", "action.*", "guard.*", "context.*"),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/execution-flow.json",
    },
    {
        "writer_id": "prompt_writer",
        "expected": True,
        "expected_events": ("prompt.submitted",),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    },
    {
        "writer_id": "hook_lifecycle_ledger",
        "expected": True,
        "expected_events": ("hook.*.start", "hook.*.complete"),
        "evidence_path": ".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    },
)


class _HashableDict(dict):
    __hash__ = object.__hash__


class _HashableList(list):
    __hash__ = object.__hash__


def _hashable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _HashableDict((key, _hashable_json(child)) for key, child in value.items())
    if isinstance(value, list):
        return _HashableList(_hashable_json(child) for child in value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_context(fixture_or_context: Any) -> dict[str, Any]:
    if isinstance(fixture_or_context, dict):
        return fixture_or_context
    if isinstance(fixture_or_context, (str, Path)):
        try:
            payload = json.loads(Path(fixture_or_context).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _safe_mst_session_id(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or "/" in text or ".." in text:
        return ""
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in text):
        return ""
    return text


def _context_mst_session_id(identity: dict[str, Any]) -> str:
    context = identity.get("context")
    if isinstance(context, dict):
        value = _safe_mst_session_id(context.get("mst_session_id"))
        if value:
            return value
    return ""


def _canonical_selector(context: dict[str, Any]) -> str:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    env_value = _safe_mst_session_id(env.get("MST_SESSION_ID"))
    context_value = _context_mst_session_id(identity)
    if env_value and context_value and env_value == context_value:
        return env_value
    if env_value:
        return env_value
    if context_value:
        return context_value
    return _safe_mst_session_id(context.get("canonical_mst_session_id")) or _safe_mst_session_id(context.get("mst_session_id"))


def _legacy_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    diagnostics = identity.get("legacy_diagnostics") if isinstance(identity.get("legacy_diagnostics"), dict) else {}
    result = dict(diagnostics)

    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    if isinstance(env.get("MST_STATE_PPID"), str) and env["MST_STATE_PPID"].strip():
        result.setdefault("owner_pid", env["MST_STATE_PPID"].strip())

    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
    if isinstance(structured.get("session_id"), str) and structured["session_id"].strip():
        result.setdefault("hook_session_id", structured["session_id"].strip())
    if isinstance(structured.get("owner_session_id"), str) and structured["owner_session_id"].strip():
        result.setdefault("owner_session_id", structured["owner_session_id"].strip())
    transcript_path = structured.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path.strip():
        name = Path(transcript_path).name
        stem = name[:-6] if name.endswith(".jsonl") else Path(name).stem
        if stem:
            result.setdefault("hook_transcript_stem", stem)
    return result


def _writer_matrix(context: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = context.get("writer_matrix")
    if isinstance(matrix, list):
        return [row for row in matrix if isinstance(row, dict) and isinstance(row.get("writer_id"), str)]
    return [dict(row) for row in DEFAULT_WRITER_MATRIX]


def _observed_events(context: dict[str, Any]) -> list[dict[str, Any]]:
    events = context.get("observed_events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    for key in ("history_rows", "rows", "raw_history_rows"):
        rows = context.get(key)
        if not isinstance(rows, list):
            continue
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = row.get("event")
            if isinstance(event, dict):
                merged = dict(event)
                for source_key, target_key in (
                    ("event_type", "event_type"),
                    ("created_at", "created_at"),
                    ("timestamp", "timestamp"),
                    ("event_hash", "source_history_head"),
                ):
                    if source_key in row and target_key not in merged:
                        merged[target_key] = row[source_key]
                result.append(merged)
            else:
                result.append(row)
        return result
    return []


def _event_created_at(event: dict[str, Any]) -> str | None:
    value = event.get("created_at") or event.get("timestamp")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _event_type(event: dict[str, Any]) -> str | None:
    value = event.get("event_type") or event.get("type")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _source_head(event: dict[str, Any]) -> Any:
    for key in ("source_history_head", "last_source_head", "history_head"):
        value = event.get(key)
        if value is not None:
            return value
    return None


def _evidence_path(matrix_row: dict[str, Any], event: dict[str, Any] | None, mst_session_id: str) -> str:
    if event is not None and isinstance(event.get("evidence_path"), str) and event["evidence_path"].strip():
        return event["evidence_path"].strip()
    value = matrix_row.get("evidence_path")
    if isinstance(value, str) and value.strip():
        return value.strip().replace("{mst_session_id}", mst_session_id)
    return f".gran-maestro/sessions/{mst_session_id}/history.ndjson" if mst_session_id else ".gran-maestro/sessions/history.ndjson"


def _is_success(event: dict[str, Any]) -> bool:
    value = str(event.get("write_status") or "success").strip().lower()
    return value in {"", "success", "ok", "written"}


def _is_error(event: dict[str, Any]) -> bool:
    value = str(event.get("write_status") or "").strip().lower()
    return value in {"error", "failed", "failure", "write_failed"}


def _is_unknown(event: dict[str, Any]) -> bool:
    value = str(event.get("write_status") or "").strip().lower()
    return value in {"unknown", "indeterminate"}


def _schema_invalid(event: dict[str, Any]) -> bool:
    return event.get("schema_version") != 1 or _event_type(event) is None


def _event_type_matches(pattern: Any, event_type: str | None) -> bool:
    if not isinstance(pattern, str) or not event_type:
        return False
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


def _event_matches_writer(matrix_row: dict[str, Any], event: dict[str, Any], writer_id: str) -> bool:
    if event.get("writer_id") == writer_id:
        return True
    expected_events = matrix_row.get("expected_events")
    if isinstance(expected_events, (list, tuple)):
        event_type = _event_type(event)
        return any(_event_type_matches(pattern, event_type) for pattern in expected_events)
    return False


def _reason(status: str, writer_id: str, event: dict[str, Any] | None, source_history_head: Any) -> str | None:
    if status == "ok":
        return None
    if status == "not_applicable":
        return "writer is not required for this session context"
    if status == "not_seen":
        return "expected writer has no matching event in bounded scan"
    if status == "stale":
        actual = _source_head(event or {})
        return f"writer source head does not match projection source_history_head: expected {source_history_head} observed {actual}"
    if status == "identity_mismatch":
        return "observed writer event mst_session_id does not match canonical mst_session_id"
    if status == "write_failed":
        event_reason = event.get("reason") if isinstance(event, dict) else None
        return event_reason if isinstance(event_reason, str) and event_reason.strip() else "writer reported write failure"
    if status == "schema_invalid":
        event_reason = event.get("reason") if isinstance(event, dict) else None
        return event_reason if isinstance(event_reason, str) and event_reason.strip() else "writer event schema is invalid"
    return "writer status could not be determined from bounded diagnostics"


def _bounded_event(event: dict[str, Any] | None, mst_session_id: str, matrix_row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event_mst_session_id = _safe_mst_session_id(event.get("mst_session_id")) or mst_session_id
    return {
        "event_type": _event_type(event),
        "created_at": _event_created_at(event),
        "write_status": str(event.get("write_status") or "success").strip().lower() or "success",
        "mst_session_id": event_mst_session_id,
        "source_history_head": _source_head(event),
        "reason": event.get("reason") if isinstance(event.get("reason"), str) and event.get("reason").strip() else None,
        "evidence_path": _evidence_path(matrix_row, event, event_mst_session_id),
    }


def _row_for_writer(
    matrix_row: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    mst_session_id: str,
    source_history_head: Any,
) -> dict[str, Any]:
    writer_id = str(matrix_row.get("writer_id") or "").strip()
    expected = bool(matrix_row.get("expected", True))
    matches = [event for event in events if _event_matches_writer(matrix_row, event, writer_id)]
    observed = bool(matches)
    last_event = matches[-1] if matches else None
    last_event_type = _event_type(last_event) if last_event is not None else None
    last_source_head = _source_head(last_event) if last_event is not None else None
    last_success_at = None
    last_error_at = None
    last_error_event = None
    for event in matches:
        if _is_success(event):
            last_success_at = _event_created_at(event)
        if _is_error(event) or _schema_invalid(event):
            last_error_at = _event_created_at(event)
            last_error_event = event

    if not expected and not observed:
        status = "not_applicable"
    elif expected and not observed:
        status = "not_seen"
    elif last_event is None:
        status = "unknown"
    elif _schema_invalid(last_event):
        status = "schema_invalid"
    elif _is_error(last_event):
        status = "write_failed"
    elif _safe_mst_session_id(last_event.get("mst_session_id")) != mst_session_id:
        status = "identity_mismatch"
    elif source_history_head is not None and last_source_head is not None and last_source_head != source_history_head:
        status = "stale"
    elif _is_unknown(last_event):
        status = "unknown"
    else:
        status = "ok"

    if status in {"identity_mismatch", "write_failed", "schema_invalid"} and last_event is not None:
        last_error_event = last_event
        if last_error_at is None:
            last_error_at = _event_created_at(last_event)

    row = {
        "writer_id": writer_id,
        "expected": expected,
        "observed": observed,
        "status": status,
        "last_event_type": last_event_type,
        "last_event": _bounded_event(last_event, mst_session_id, matrix_row),
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "last_error": _bounded_event(last_error_event, mst_session_id, matrix_row),
        "last_source_head": last_source_head,
        "reason": _reason(status, writer_id, last_event, source_history_head),
        "evidence_path": _evidence_path(matrix_row, last_event, mst_session_id),
    }
    return {field: row[field] for field in ROW_FIELDS}


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {status: 0 for status in ALLOWED_STATUS}
    for row in rows:
        status = row.get("status")
        if status in by_status:
            by_status[status] += 1
    return {
        "total": len(rows),
        "ok": by_status["ok"],
        "not_applicable": by_status["not_applicable"],
        "non_ok": len(rows) - by_status["ok"],
        "by_status": by_status,
    }


def project_writer_coverage(fixture_or_context: Any) -> dict[str, Any]:
    """Return a bounded, read-only writer coverage projection.

    The projection selects the canonical session from MST_SESSION_ID or
    structured mst_session_id only. Legacy hook/process identifiers are carried
    exclusively in legacy_diagnostics and never used as lookup keys.
    """
    context = _load_context(fixture_or_context)
    mst_session_id = _canonical_selector(context)
    source_history_head = context.get("source_history_head")
    generated_at = context.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        generated_at = _utc_now()

    events = _observed_events(context)
    rows = [
        _row_for_writer(
            matrix_row,
            events,
            mst_session_id=mst_session_id,
            source_history_head=source_history_head,
        )
        for matrix_row in _writer_matrix(context)
    ]
    return _hashable_json({
        "schema_version": 1,
        "mst_session_id": mst_session_id,
        "canonical_mst_session_id": mst_session_id,
        "lookup_key": mst_session_id,
        "partition_key": mst_session_id,
        "source_history_head": source_history_head,
        "generated_at": generated_at.strip(),
        "legacy_diagnostics": _legacy_diagnostics(context),
        "summary": _summary(rows),
        "writers": rows,
    })
