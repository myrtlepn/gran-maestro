from __future__ import annotations
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.mst_cmds import _common
from scripts.mst_cmds import cleanup as cleanup_mod
from scripts.mst_cmds import host as host_mod
from scripts.mst_cmds import resolve_model as resolve_model_mod
from scripts.mst_cmds import reasoning_effort as reasoning_effort_mod
from scripts.mst_cmds import session as session_mod
from scripts.mst_cmds import native_delegation as native_delegation_mod
from scripts.mst_cmds._common import (
    _parse_utc_datetime,
    _plugin_root,
    load_json,
    resolve_started_by_pid,
    run_dir,
    save_json,
)
_TERMINAL_PHASES = {"done", "terminated", "failed"}
_DELEGATE_EVENTS_KEY = "delegate_io_attention_events"
_DELEGATE_MONITOR_KEY = "delegate_monitor"
_DELEGATE_EVENT_TTL = timedelta(minutes=10)
_DELEGATE_EVENT_COOLDOWN = timedelta(minutes=2)
_DELEGATE_TAIL_BYTES = 2048
_PERSISTED_EXTERNAL_AUTH_PROVIDERS = {"codex", "claude", "agy"}
_DELEGATE_ALLOWED_ACTIONS = ["observe", "wait", "mark_blocked", "terminate_gracefully"]
_DELEGATE_FORBIDDEN_REASONS = [
    "stdin_write_disallowed",
    "stdin_transport_change_disallowed",
    "provider_prompt_auto_answer_disallowed",
    "remediation_command_disallowed",
]
_PROMPT_LIKE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"do you want to continue",
        r"continue\?\s*(?:\[y/n\]|\[y/N\]|\(y/n\)|yes/no)?",
        r"press enter",
        r"type\s+(?:yes|y)\b",
        r"waiting for (?:input|stdin)",
        r"read(?:ing)? additional input from stdin",
        r"approval required",
        r"permission required",
        r"\[(?:y/N|Y/n|yes/no)\]",
    )
]
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
def _delegate_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
def _process_start_time(pid: int) -> str:
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        parts = text.rsplit(") ", 1)
        if len(parts) == 2:
            fields = parts[1].split()
            if len(fields) > 19:
                return "proc:" + fields[19]
    try:
        observed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = observed.stdout.strip() if observed.returncode == 0 else ""
    return "ps:" + value if value else ""
def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
def _default_process_identity(pid: int) -> dict:
    return {"pid": pid, "pid_start_time": _process_start_time(pid), "pid_alive": _pid_is_alive(pid)}
def _redact_delegate_tail(text: str) -> str:
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*[^\s]+",
        r"\1=[REDACTED]",
        text,
    )
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-[REDACTED]", redacted)
    return redacted[-_DELEGATE_TAIL_BYTES:]
def _normalized_tail_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
_LIFECYCLE_ATTEMPT_FIELDS = (
    "attempt_id",
    "task_id",
    "provider",
    "provider_task_id",
    "skill",
    "label",
    "model",
    "reasoning_effort",
    "reasoning_effort_source",
    "phase",
    "status",
    "started_at",
    "last_heartbeat",
    "terminated_at",
    "exit_code",
    "structured_error",
    "worktree_dir",
    "log_path",
    "running_log_path",
    "stdout_log_path",
    "stderr_log_path",
    "transcript_summary_path",
    "trace_path",
    "output_path",
    "parent_session_id",
    "mst_session_id",
    "root_mst_id",
    "schema_version",
    "fallback_from",
    "fallback_to",
    "context_files_read",
    "label_evidence",
    "trace_label_evidence",
    "attempt_sequence",
    "current_attempt",
    "security_evidence",
    "execution_transport",
    "launch_surface",
    "requested_launch_surface",
    "launch_surface_status",
    "route_reason",
    "route_fingerprint",
    "orca_launch_status",
    "orca_worktree_selector",
    "orca_terminal_title",
    "orca_terminal_handle",
    "orca_reconciliation_required",
    "orca_cleanup_status",
)

def _json_object_or_empty(raw: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_text(value) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _json_safe_original_evidence(value) -> str:
    raw = value if isinstance(value, str) else str(value or "")
    normalized_newlines = raw.replace("\r\n", "\n").replace("\r", "\n")
    return json.dumps(normalized_newlines, ensure_ascii=False)[1:-1]


def _normalize_security_token(value, *, default: str) -> str:
    raw = value if isinstance(value, str) else str(value or "")
    normalized = unicodedata.normalize("NFKC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    safe = "".join(ch if ch.isascii() and (ch.isalnum() or ch in {"-", "_", "."}) else "-" for ch in normalized)
    safe = re.sub(r"-{2,}", "-", safe).strip("-._")
    return safe or default


def _label_source_value(task_id: str, skill: str = "", explicit_label: str | None = None) -> str:
    label = _safe_text(explicit_label)
    if label:
        return label
    label = _safe_text(skill)
    if label:
        return label
    return _safe_text(task_id) or "dispatch"


def _trace_label_evidence(trace: str) -> dict:
    parts = [part.strip() for part in str(trace).split("/") if part.strip()]
    raw_label = parts[-1] if parts else "trace"
    normalized = _normalize_security_token(raw_label, default="trace")
    return {
        "field": "trace_label",
        "normalized": normalized,
        "original_redacted": _json_safe_original_evidence(str(trace)),
        "changed": normalized != _safe_text(raw_label),
    }


def _provider_network_guard_evidence(env: dict[str, str] | None = None) -> dict | None:
    source = os.environ if env is None else env
    mode = _safe_text(source.get("MST_PROVIDER_NETWORK_GUARD")).lower()
    if mode not in {"deny", "disabled", "local-only"}:
        return None
    return {
        "provider_network_guard": {
            "mode": mode,
            "actual_provider_network_call": False,
            "evidence_source": "local_fixture_guard",
        }
    }


def _label_evidence(
    task_id: str,
    skill: str = "",
    explicit_label: str | None = None,
    *,
    attempt_id: str = "",
    existing_payload: dict | None = None,
) -> dict:
    raw_label = _label_source_value(task_id, skill, explicit_label)
    normalized = _normalize_security_token(raw_label, default="dispatch")
    evidence = {
        "field": "label",
        "normalized": normalized,
        "original_redacted": _json_safe_original_evidence(raw_label),
        "changed": normalized != _safe_text(raw_label),
    }
    attempts = _ensure_attempts(existing_payload) if isinstance(existing_payload, dict) else []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        other_attempt_id = _safe_text(attempt.get("attempt_id"))
        if other_attempt_id and other_attempt_id == _safe_text(attempt_id):
            continue
        other_evidence = attempt.get("label_evidence") if isinstance(attempt.get("label_evidence"), dict) else {}
        other_normalized = _safe_text(other_evidence.get("normalized")) or _normalize_security_token(
            str(attempt.get("label") or ""),
            default="dispatch",
        )
        other_original = _safe_text(other_evidence.get("original_redacted")) or _json_safe_original_evidence(
            str(attempt.get("label") or "")
        )
        if other_normalized == normalized and other_original != evidence["original_redacted"]:
            evidence["collision"] = {
                "attempt_id": other_attempt_id or None,
                "normalized": normalized,
                "other_original_redacted": other_original,
            }
            break
    return evidence


def _lifecycle_attempt_id(task_id: str, explicit_attempt_id: str | None = None, existing_payload: dict | None = None) -> str:
    attempt_id = _safe_text(explicit_attempt_id)
    if attempt_id:
        return attempt_id
    if isinstance(existing_payload, dict):
        existing_attempt_id = _safe_text(existing_payload.get("attempt_id"))
        if existing_attempt_id:
            return existing_attempt_id
    task_prefix = _safe_text(task_id) or "dispatch-task"
    return f"{task_prefix}-attempt-{uuid.uuid4().hex[:12]}"


def _lifecycle_label(task_id: str, skill: str = "", explicit_label: str | None = None) -> str:
    return _normalize_security_token(_label_source_value(task_id, skill, explicit_label), default="dispatch")


def _parent_session_id(raw_context: str, session_id: str, explicit_parent_session_id: str | None = None) -> str:
    parent_session_id = _safe_text(explicit_parent_session_id)
    if parent_session_id:
        return parent_session_id

    context = _json_object_or_empty(raw_context)
    for candidate in (
        context.get("parent_session_id"),
        context.get("source_session_id"),
        context.get("session_parent_id"),
    ):
        text = _safe_text(candidate)
        if text:
            return text

    core = context.get("core_rehydration") if isinstance(context.get("core_rehydration"), dict) else {}
    for candidate in (
        core.get("parent_session_id"),
        core.get("source_session_id"),
        core.get("session_parent_id"),
    ):
        text = _safe_text(candidate)
        if text:
            return text

    return session_id


def _context_file_candidates(raw_context: str, explicit_paths: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    if explicit_paths:
        candidates.extend(str(path) for path in explicit_paths if _safe_text(path))

    context = _json_object_or_empty(raw_context)

    def _append_from(value) -> None:
        if isinstance(value, str):
            text = _safe_text(value)
            if text:
                candidates.append(text)
            return
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = _safe_text(item.get("path"))
                    if text:
                        candidates.append(text)
                else:
                    text = _safe_text(item)
                    if text:
                        candidates.append(text)

    for key in ("context_files", "context_file_paths", "context_files_read"):
        _append_from(context.get(key))

    core = context.get("core_rehydration") if isinstance(context.get("core_rehydration"), dict) else {}
    for key in ("context_files", "context_file_paths", "context_files_read"):
        _append_from(core.get(key))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = _safe_text(candidate)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _context_file_metadata(path_value: str) -> dict:
    path = Path(path_value)
    entry = {"path": str(path), "exists": False, "hash": None, "version": None}
    try:
        stat_result = path.stat()
    except OSError:
        return entry
    if not path.is_file():
        return entry
    entry["exists"] = True
    entry["hash"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    entry["version"] = f"{int(stat_result.st_size)}:{int(stat_result.st_mtime_ns)}"
    return entry


def _collect_context_files_read(raw_context: str, explicit_paths: list[str] | None = None) -> list[dict]:
    return [_context_file_metadata(path) for path in _context_file_candidates(raw_context, explicit_paths)]


def _status_from_final_state(
    *,
    exit_code: int | None,
    explicit_status: str | None = None,
    output_path: str | None = None,
    fallback_from: str | None = None,
) -> str:
    status = _safe_text(explicit_status).lower()
    if status:
        return status
    if exit_code is not None and int(exit_code) != 0:
        return "failed"
    output = _safe_text(output_path)
    if output:
        try:
            if Path(output).exists() and Path(output).stat().st_size == 0:
                return "empty_result"
        except OSError:
            pass
    if _safe_text(fallback_from):
        return "fallback_completed"
    return "completed"


def _structured_error_payload(
    *,
    explicit_structured_error_json: str | None = None,
    explicit_structured_error_message: str | None = None,
    exit_code: int | None = None,
    status: str = "",
) -> dict | None:
    raw_json = _safe_text(explicit_structured_error_json)
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            payload = {"kind": "invalid_structured_error_json", "raw": raw_json}
        if isinstance(payload, dict):
            return payload
        return {"kind": "invalid_structured_error_payload", "raw": payload}

    message = _safe_text(explicit_structured_error_message)
    normalized_status = _safe_text(status).lower()
    if message:
        payload = {"kind": normalized_status or "error", "message": message}
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        return payload

    if exit_code is not None and int(exit_code) != 0:
        return {
            "kind": "non_zero_exit",
            "exit_code": int(exit_code),
            "message": f"command exited with code {int(exit_code)}",
        }

    return None


def _attempt_snapshot(payload: dict) -> dict:
    snapshot = {}
    for field in _LIFECYCLE_ATTEMPT_FIELDS:
        if field in payload:
            snapshot[field] = payload[field]
    return json.loads(json.dumps(snapshot, ensure_ascii=False))


def _ensure_attempts(payload: dict) -> list[dict]:
    attempts = payload.get("attempts")
    normalized: list[dict] = []
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict):
                normalized.append(dict(attempt))
    return normalized


def _attempt_sequence_value(attempt: dict) -> int | None:
    try:
        sequence = int(attempt.get("attempt_sequence"))
    except (TypeError, ValueError):
        return None
    return sequence if sequence > 0 else None


def _next_attempt_sequence(attempts: list[dict]) -> int:
    sequences = [sequence for sequence in (_attempt_sequence_value(attempt) for attempt in attempts) if sequence]
    return (max(sequences) + 1) if sequences else 1


def _sync_attempt_payload(payload: dict) -> dict:
    attempt_id = _safe_text(payload.get("attempt_id"))
    if not attempt_id:
        return payload
    attempts = _ensure_attempts(payload)
    replaced = False
    for index, attempt in enumerate(attempts):
        if _safe_text(attempt.get("attempt_id")) == attempt_id:
            sequence = _attempt_sequence_value(attempt) or _attempt_sequence_value(payload) or index + 1
            payload["attempt_sequence"] = sequence
            current = _attempt_snapshot(payload)
            current["attempt_sequence"] = sequence
            current["current_attempt"] = True
            attempts[index] = current
            replaced = True
            break
    if not replaced:
        sequence = _next_attempt_sequence(attempts)
        payload["attempt_sequence"] = sequence
        current = _attempt_snapshot(payload)
        current["attempt_sequence"] = sequence
        current["current_attempt"] = True
        attempts.append(current)
    for attempt in attempts:
        attempt["current_attempt"] = _safe_text(attempt.get("attempt_id")) == attempt_id
    payload["current_attempt"] = True
    payload["attempts"] = attempts
    return payload


def _attempt_by_id(payload: dict, attempt_id: str) -> dict | None:
    target = _safe_text(attempt_id)
    if not target:
        return None
    for attempt in _ensure_attempts(payload):
        if _safe_text(attempt.get("attempt_id")) == target:
            return attempt
    return None


def _restore_attempt_as_current(payload: dict, attempt_id: str) -> dict:
    attempt = _attempt_by_id(payload, attempt_id)
    if not attempt:
        return payload
    attempts = _ensure_attempts(payload)
    preserved = {
        "attempts": attempts,
        "finalization_evidence": payload.get("finalization_evidence"),
        "next_execution": payload.get("next_execution"),
        "continuation": payload.get("continuation"),
        "auto": payload.get("auto"),
    }
    for field in _LIFECYCLE_ATTEMPT_FIELDS:
        if field in attempt:
            payload[field] = attempt[field]
    payload["attempts"] = preserved["attempts"]
    for key in ("finalization_evidence", "next_execution", "continuation", "auto"):
        if preserved.get(key) is not None:
            payload[key] = preserved[key]
    return payload


def _is_terminal_lifecycle(payload: dict) -> bool:
    return native_delegation_mod.lifecycle_is_terminal(payload)


def _incoming_final_status(args, payload: dict) -> tuple[str, int | None, dict | None]:
    exit_code: int | None = None
    if getattr(args, "exit_code", None) is not None:
        exit_code = int(getattr(args, "exit_code"))
    status = _status_from_final_state(
        exit_code=exit_code,
        explicit_status=getattr(args, "status", None),
        output_path=str(getattr(args, "output_path", None) or payload.get("output_path") or ""),
        fallback_from=str(getattr(args, "fallback_from", None) or payload.get("fallback_from") or ""),
    )
    structured_error = _structured_error_payload(
        explicit_structured_error_json=getattr(args, "structured_error_json", None),
        explicit_structured_error_message=getattr(args, "structured_error_message", None),
        exit_code=exit_code,
        status=status,
    )
    return status, exit_code, structured_error


def _same_finalization(payload: dict, status: str, exit_code: int | None, structured_error: dict | None) -> bool:
    return (
        _safe_text(payload.get("status")).lower() == status
        and payload.get("exit_code") == exit_code
        and (payload.get("structured_error") if payload.get("structured_error") is not None else None) == structured_error
    )


def _record_finalization_evidence(
    payload: dict,
    *,
    reason: str,
    incoming_attempt_id: str,
    current_attempt_id: str,
    incoming_status: str | None = None,
    incoming_exit_code: int | None = None,
) -> dict:
    evidence = payload.get("finalization_evidence")
    if not isinstance(evidence, list):
        evidence = []
    entry = {
        "reason": reason,
        "incoming_attempt_id": incoming_attempt_id,
        "current_attempt_id": current_attempt_id,
        "current_status": _safe_text(payload.get("status")) or "unknown",
        "current_phase": _safe_text(payload.get("phase")) or "unknown",
    }
    if incoming_status is not None:
        entry["incoming_status"] = incoming_status
    if incoming_exit_code is not None:
        entry["incoming_exit_code"] = incoming_exit_code
    evidence.append(entry)
    payload["finalization_evidence"] = evidence
    return payload


def _guard_idempotent_heartbeat(payload: dict, args) -> tuple[bool, dict]:
    incoming_attempt_id = _safe_text(getattr(args, "attempt_id", None))
    current_attempt_id = _safe_text(payload.get("attempt_id"))
    if not incoming_attempt_id or not current_attempt_id:
        return False, payload

    current_is_terminal = _is_terminal_lifecycle(payload)
    if getattr(args, "final", False):
        incoming_status, incoming_exit_code, incoming_error = _incoming_final_status(args, payload)
        if current_is_terminal and incoming_attempt_id == current_attempt_id:
            reason = (
                "identical_duplicate_finalization"
                if _same_finalization(payload, incoming_status, incoming_exit_code, incoming_error)
                else "conflicting_duplicate_finalization"
            )
            return True, _record_finalization_evidence(
                payload,
                reason=reason,
                incoming_attempt_id=incoming_attempt_id,
                current_attempt_id=current_attempt_id,
                incoming_status=incoming_status,
                incoming_exit_code=incoming_exit_code,
            )
        if current_is_terminal and incoming_attempt_id != current_attempt_id:
            if _safe_text(getattr(args, "fallback_from", None)) == current_attempt_id:
                return False, payload
            return True, _record_finalization_evidence(
                payload,
                reason="stale_finalization_for_non_current_attempt",
                incoming_attempt_id=incoming_attempt_id,
                current_attempt_id=current_attempt_id,
                incoming_status=incoming_status,
                incoming_exit_code=incoming_exit_code,
            )
        return False, payload

    if current_is_terminal:
        reason = (
            "late_heartbeat_for_terminal_attempt"
            if incoming_attempt_id == current_attempt_id
            else "out_of_order_heartbeat_for_terminal_task"
        )
        return True, _record_finalization_evidence(
            payload,
            reason=reason,
            incoming_attempt_id=incoming_attempt_id,
            current_attempt_id=current_attempt_id,
        )
    return False, payload


def _set_attempt_fallback_to(payload: dict, from_attempt_id: str, to_attempt_id: str) -> dict:
    from_attempt = _safe_text(from_attempt_id)
    to_attempt = _safe_text(to_attempt_id)
    if not from_attempt or not to_attempt:
        return payload
    attempts = _ensure_attempts(payload)
    updated = False
    for attempt in attempts:
        if _safe_text(attempt.get("attempt_id")) == from_attempt:
            attempt["fallback_to"] = to_attempt
            updated = True
            break
    if _safe_text(payload.get("attempt_id")) == from_attempt:
        payload["fallback_to"] = to_attempt
        updated = True
    if updated:
        payload["attempts"] = attempts
    return payload


def _apply_lifecycle_paths(
    payload: dict,
    *,
    running_log_path: str | None = None,
    stdout_log_path: str | None = None,
    stderr_log_path: str | None = None,
    transcript_summary_path: str | None = None,
    trace_path: str | None = None,
    output_path: str | None = None,
) -> dict:
    if _safe_text(running_log_path):
        payload["running_log_path"] = _safe_text(running_log_path)
        payload["log_path"] = _safe_text(running_log_path)
    if _safe_text(stdout_log_path):
        payload["stdout_log_path"] = _safe_text(stdout_log_path)
    if _safe_text(stderr_log_path):
        payload["stderr_log_path"] = _safe_text(stderr_log_path)
    if _safe_text(transcript_summary_path):
        payload["transcript_summary_path"] = _safe_text(transcript_summary_path)
    if _safe_text(trace_path):
        payload["trace_path"] = _safe_text(trace_path)
    if _safe_text(output_path):
        payload["output_path"] = _safe_text(output_path)
    return payload


def _stream_sample(path: Path | str | None) -> dict:
    if path is None:
        return {
            "redacted_tail": "",
            "output_offset": 0,
            "normalized_tail_hash": _normalized_tail_hash(""),
            "mtime_ns": 0,
            "prompt_like": False,
        }
    stream_path = Path(path)
    try:
        stat_result = stream_path.stat()
        size = int(stat_result.st_size)
        with stream_path.open("rb") as handle:
            handle.seek(max(0, size - _DELEGATE_TAIL_BYTES))
            raw = handle.read(_DELEGATE_TAIL_BYTES)
    except OSError:
        size = 0
        stat_result = None
        raw = b""
    tail = raw.decode("utf-8", errors="replace")
    redacted = _redact_delegate_tail(tail)
    return {
        "redacted_tail": redacted,
        "output_offset": size,
        "normalized_tail_hash": _normalized_tail_hash(redacted),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", 0) if stat_result is not None else 0),
        "prompt_like": any(pattern.search(redacted) for pattern in _PROMPT_LIKE_PATTERNS),
    }
def _delegate_streams(stream_paths: dict) -> dict:
    return {
        "stdout": _stream_sample(stream_paths.get("stdout") or stream_paths.get("combined")),
        "stderr": _stream_sample(stream_paths.get("stderr") or stream_paths.get("combined")),
    }
def _delegate_signature(streams: dict) -> dict:
    return {
        name: {
            "output_offset": sample.get("output_offset", 0),
            "normalized_tail_hash": sample.get("normalized_tail_hash", ""),
            "mtime_ns": sample.get("mtime_ns", 0),
        }
        for name, sample in streams.items()
    }
def _has_expired(value: str, now: datetime) -> bool:
    parsed = _parse_utc_datetime(value)
    return parsed is not None and parsed <= now
def _is_suppressed_delegate_state(state: dict, identity: dict) -> bool:
    phase = str(state.get("phase") or "").strip().lower()
    if phase in _TERMINAL_PHASES or state.get("terminated_at"):
        return True
    try:
        state_pid = int(state.get("pid"))
    except (TypeError, ValueError):
        return True
    if state_pid != int(identity.get("pid") or -1):
        return True
    if identity.get("pid_alive") is not True:
        return True
    state_start = str(state.get("pid_start_time") or "").strip()
    identity_start = str(identity.get("pid_start_time") or "").strip()
    if not state_start or not identity_start or state_start != identity_start:
        return True
    return False
def _delegate_evidence(state: dict, streams: dict, idle_windows: int, identity: dict) -> dict:
    stream_evidence = {
        name: {
            "redacted_tail": sample.get("redacted_tail", ""),
            "output_offset": sample.get("output_offset", 0),
            "normalized_tail_hash": sample.get("normalized_tail_hash", ""),
            "mtime_ns": sample.get("mtime_ns", 0),
        }
        for name, sample in streams.items()
    }
    return {
        "phase": str(state.get("phase") or ""),
        "pid_alive": identity.get("pid_alive") is True,
        "last_heartbeat": state.get("last_heartbeat"),
        "idle_windows": idle_windows,
        "streams": stream_evidence,
        "output_offsets": {name: sample["output_offset"] for name, sample in stream_evidence.items()},
        "normalized_tail_hashes": {name: sample["normalized_tail_hash"] for name, sample in stream_evidence.items()},
    }
def _build_delegate_event(
    *,
    state: dict,
    signal_name: str,
    reason_codes: list[str],
    evidence: dict,
    now: datetime,
) -> dict:
    observed_at = now.isoformat()
    expires_at = (now + _DELEGATE_EVENT_TTL).isoformat()
    cooldown_until = (now + _DELEGATE_EVENT_COOLDOWN).isoformat()
    dedup_source = {
        "task_id": state.get("task_id"),
        "pid_start_time": state.get("pid_start_time"),
        "signal": signal_name,
        "reason_codes": sorted(reason_codes),
        "hashes": evidence.get("normalized_tail_hashes", {}),
    }
    dedup_key = hashlib.sha256(json.dumps(dedup_source, sort_keys=True).encode("utf-8")).hexdigest()
    event_id = "evt-" + hashlib.sha256(f"{dedup_key}:{observed_at}".encode("utf-8")).hexdigest()[:24]
    return {
        "event_id": event_id,
        "task_id": str(state.get("task_id") or ""),
        "provider": str(state.get("provider") or ""),
        "pid": int(state.get("pid")),
        "pid_start_time": str(state.get("pid_start_time") or ""),
        "kind": "delegate_io_attention",
        "signal": signal_name,
        "reason_codes": reason_codes,
        "confidence": 0.82 if signal_name == "stdin_prompt_suspected" else 0.68,
        "observed_at": observed_at,
        "expires_at": expires_at,
        "dedup_key": dedup_key,
        "evidence": evidence,
        "allowed_actions": list(_DELEGATE_ALLOWED_ACTIONS),
        "forbidden_reasons": list(_DELEGATE_FORBIDDEN_REASONS),
        "attempt_count": 1,
        "max_attempts": 3,
        "cooldown_until": cooldown_until,
    }
def _coalesce_or_cooldown(events: list, event: dict, now: datetime) -> tuple[bool, bool]:
    for existing in events:
        if not isinstance(existing, dict):
            continue
        if existing.get("dedup_key") == event.get("dedup_key") and not _has_expired(str(existing.get("expires_at") or ""), now):
            coalesce = existing.get("coalesce")
            if not isinstance(coalesce, dict):
                coalesce = {"count": 1}
            count = coalesce.get("count")
            if not isinstance(count, int) or count < 1:
                count = 1
            coalesce["count"] = count + 1
            coalesce["last_seen_at"] = now.isoformat()
            existing["coalesce"] = coalesce
            return True, False
        cooldown_until = existing.get("cooldown_until")
        cooldown_dt = _parse_utc_datetime(cooldown_until)
        if cooldown_dt is not None and cooldown_dt > now:
            return False, True
    return False, False
def evaluate_delegate_io_attention(
    state: dict,
    stream_paths: dict,
    *,
    process_identity: dict | None = None,
    now: datetime | None = None,
) -> dict:
    now_dt = _delegate_now(now)
    updated = dict(state)
    streams = _delegate_streams(stream_paths)
    signature = _delegate_signature(streams)
    monitor = dict(updated.get(_DELEGATE_MONITOR_KEY) if isinstance(updated.get(_DELEGATE_MONITOR_KEY), dict) else {})
    previous_signature = monitor.get("signature") if isinstance(monitor.get("signature"), dict) else None
    idle_windows = int(monitor.get("idle_windows") or 0) if signature == previous_signature else 0
    if signature == previous_signature:
        idle_windows += 1
    monitor["signature"] = signature
    monitor["idle_windows"] = idle_windows
    monitor["last_observed_at"] = now_dt.isoformat()
    updated[_DELEGATE_MONITOR_KEY] = monitor

    identity = process_identity
    if identity is None:
        try:
            identity = _default_process_identity(int(updated.get("pid")))
        except (TypeError, ValueError):
            identity = {"pid": updated.get("pid"), "pid_start_time": "", "pid_alive": False}

    appended: list[dict] = []
    coalesced: list[str] = []
    suppressed: list[str] = []

    if _is_suppressed_delegate_state(updated, identity):
        return {"state": updated, "appended": appended, "coalesced": coalesced, "suppressed": ["guard"]}

    prompt_streams = [name for name, sample in streams.items() if sample.get("prompt_like")]
    signal_name = ""
    reason_codes: list[str] = []
    if prompt_streams:
        signal_name = "stdin_prompt_suspected"
        reason_codes = [f"prompt_like_{name}" for name in prompt_streams]
    elif idle_windows >= 2 and any(int(sample.get("output_offset") or 0) > 0 for sample in streams.values()):
        signal_name = "output_stalled"
        reason_codes = ["output_unchanged", "idle_windows_threshold"]
    else:
        return {"state": updated, "appended": appended, "coalesced": coalesced, "suppressed": suppressed}

    evidence = _delegate_evidence(updated, streams, idle_windows, identity)
    event = _build_delegate_event(
        state=updated,
        signal_name=signal_name,
        reason_codes=reason_codes,
        evidence=evidence,
        now=now_dt,
    )
    events = updated.get(_DELEGATE_EVENTS_KEY)
    if not isinstance(events, list):
        events = []
    coalesced_existing, cooldown = _coalesce_or_cooldown(events, event, now_dt)
    if coalesced_existing:
        coalesced.append(str(event["dedup_key"]))
    elif cooldown:
        suppressed.append("cooldown")
    else:
        events.append(event)
        appended.append(event)
    updated[_DELEGATE_EVENTS_KEY] = events
    return {"state": updated, "appended": appended, "coalesced": coalesced, "suppressed": suppressed}
def record_delegate_io_attention(
    state_path: Path,
    stream_paths: dict,
    *,
    process_identity: dict | None = None,
) -> dict:
    payload = load_json(state_path)
    if not isinstance(payload, dict):
        return {"state": {}, "appended": [], "coalesced": [], "suppressed": ["missing_state"]}
    result = evaluate_delegate_io_attention(payload, stream_paths, process_identity=process_identity)
    if result.get("appended") or result.get("coalesced") or result.get("state", {}).get(_DELEGATE_MONITOR_KEY) != payload.get(_DELEGATE_MONITOR_KEY):
        save_json(state_path, result["state"])
    return result
def _skill_dispatch_session_id(prompt_file: Path, log_file: Path, worktree_dir: Path) -> str:
    for path in (prompt_file, log_file):
        try:
            relative = path.resolve().relative_to(worktree_dir / ".gran-maestro")
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) >= 2 and parts[0] in {"ideation", "discussion", "debug"}:
            candidate = str(parts[1]).strip()
            if _common.is_path_safe_mst_session_id(candidate):
                return candidate
    return ""
def _dispatch_session_bootstrap_cmd(fallback_session_id: str = "") -> str:
    normalize_context_py = """
import json
import os
import sys

sid = os.environ.get("MST_SESSION_ID", "").strip()
raw = os.environ.get("MST_CONTEXT_JSON", "").strip()
payload = {}

def _root_from_session(session_id):
    if not session_id.startswith("MST-"):
        return ""
    try:
        root, _started_at, _random = session_id[4:].rsplit("-", 2)
    except ValueError:
        return ""
    return root

def _require_matching_session(candidate, source):
    if isinstance(candidate, str) and candidate.strip() and candidate.strip() != sid:
        print(f"Error: MST_SESSION_ID and structured mst_session_id mismatch ({source})", file=sys.stderr)
        sys.exit(2)

def _require_matching_root(candidate, source):
    root = _root_from_session(sid)
    if isinstance(candidate, str) and candidate.strip() and candidate.strip() != root:
        print(f"Error: MST_CONTEXT_JSON root_mst_id mismatch ({source})", file=sys.stderr)
        sys.exit(2)

if raw:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: MST_CONTEXT_JSON must be a JSON object: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(parsed, dict):
        print("Error: MST_CONTEXT_JSON must be a JSON object", file=sys.stderr)
        sys.exit(2)
    if parsed.get("schema_version") is not None and parsed.get("schema_version") != 1:
        print("Error: MST_CONTEXT_JSON schema_version mismatch", file=sys.stderr)
        sys.exit(2)
    _require_matching_session(parsed.get("mst_session_id"), "context")
    _require_matching_root(parsed.get("root_mst_id"), "context")
    core = parsed.get("core_rehydration")
    if isinstance(core, dict):
        if core.get("schema_version") is not None and core.get("schema_version") != 1:
            print("Error: MST_CONTEXT_JSON core_rehydration schema_version mismatch", file=sys.stderr)
            sys.exit(2)
        _require_matching_session(core.get("mst_session_id"), "core_rehydration")
        _require_matching_root(core.get("root_mst_id"), "core_rehydration")
        next_execution = core.get("next_execution")
        if isinstance(next_execution, dict):
            env = next_execution.get("env")
            if isinstance(env, dict):
                _require_matching_session(env.get("MST_SESSION_ID"), "next_execution.env")
                env["MST_SESSION_ID"] = sid
            context = next_execution.get("context")
            if isinstance(context, dict):
                _require_matching_session(context.get("mst_session_id"), "next_execution.context")
                context["mst_session_id"] = sid
    payload = dict(parsed)
payload.setdefault("schema_version", 1)
payload["mst_session_id"] = sid
payload.setdefault("root_mst_id", _root_from_session(sid))
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
""".strip()
    q = shlex.quote
    fallback_assignment = shlex.quote(fallback_session_id) if fallback_session_id else ""
    return (
        f'MST_SESSION_ID="${{MST_SESSION_ID:-{fallback_assignment}}}"; '
        "export MST_SESSION_ID; "
        'if [ -z "$MST_SESSION_ID" ]; then '
        'echo "Error: missing MST_SESSION_ID before dispatch spawn" >&2; exit 2; '
        "fi; "
        f'MST_CONTEXT_JSON="$(python3 -c {q(normalize_context_py)})" || exit 2; '
        "export MST_CONTEXT_JSON"
    )
def _dispatch_state_path(task_id: str) -> Path:
    return run_dir() / f"{task_id}.json"
def _canonical_dispatch_fields(session_id: str) -> dict:
    try:
        return _common.canonical_state_payload_fields(session_id)
    except ValueError:
        if not _common.is_path_safe_mst_session_id(session_id):
            raise
        return {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": "",
        }
def _dispatch_required_session_context() -> dict[str, str]:
    return session_mod.child_env_with_required_session_context()
def _dispatch_payload_error(payload: dict, session_id: str) -> str | None:
    canonical_fields = _canonical_dispatch_fields(session_id)
    existing_session_id = payload.get("mst_session_id")
    if (
        isinstance(existing_session_id, str)
        and existing_session_id.strip()
        and existing_session_id.strip() != canonical_fields["mst_session_id"]
    ):
        return (
            "dispatch mst_session_id mismatch: "
            f"env={canonical_fields['mst_session_id']} payload={existing_session_id.strip()}"
        )
    existing_schema_version = payload.get("schema_version")
    if existing_schema_version is not None and existing_schema_version != canonical_fields["schema_version"]:
        return "dispatch schema_version mismatch"
    existing_root_mst_id = payload.get("root_mst_id")
    if (
        isinstance(existing_root_mst_id, str)
        and existing_root_mst_id.strip()
        and existing_root_mst_id.strip() != canonical_fields["root_mst_id"]
    ):
        return (
            "dispatch root_mst_id mismatch: "
            f"session={canonical_fields['root_mst_id']} payload={existing_root_mst_id.strip()}"
        )
    return None
def _continuation_policy_from_context(raw_context: str) -> dict:
    try:
        context = json.loads(raw_context or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(context, dict):
        return {}
    core = context.get("core_rehydration")
    if not isinstance(core, dict):
        core = context
    policy: dict = {}
    if core.get("auto") is True:
        policy["auto"] = True
    continuation = core.get("continuation")
    if isinstance(continuation, dict):
        policy["continuation"] = continuation
    return policy
def _dispatch_context_envelope(
    *,
    session_id: str,
    task_id: str,
    raw_context: str,
    command: str | None = None,
) -> dict:
    canonical_fields = _canonical_dispatch_fields(session_id)
    policy = _continuation_policy_from_context(raw_context)
    next_execution_context = {
        "mst_session_id": canonical_fields["mst_session_id"],
        "root_mst_id": canonical_fields["root_mst_id"],
    }
    if policy.get("auto") is True:
        next_execution_context["auto"] = True
    envelope = {
        **canonical_fields,
        **policy,
        "child_artifact_id": task_id,
        "task_id": task_id,
        "external_control_surface": "dispatch",
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
        "next_execution": {
            "env": {
                "MST_SESSION_ID": canonical_fields["mst_session_id"],
                "MST_CONTEXT_JSON": raw_context,
            },
            "context": next_execution_context,
        },
    }
    if command is not None:
        envelope["command"] = command
    return envelope
def _emit_dispatch_validation_failure(exc: _common.ContractValidationError) -> int:
    return _common.emit_validation_failure(
        target=exc.target,
        field=exc.field,
        reason=exc.reason,
        code=exc.code,
        external_control_surface="dispatch",
        prompt_summary_used_as_source=False,
    )
def _emit_dispatch_payload_mismatch(payload_error: str) -> int:
    field = "mst_session_id"
    if "root_mst_id" in payload_error:
        field = "root_mst_id"
    elif "schema_version" in payload_error:
        field = "schema_version"
    return _common.emit_validation_failure(
        target="dispatch_envelope",
        field=field,
        reason=payload_error,
        external_control_surface="dispatch",
        prompt_summary_used_as_source=False,
    )
def _emit_dispatch_value_error(exc: ValueError) -> int | None:
    message = str(exc)
    if "mismatch" not in message:
        return None
    field = "mst_session_id"
    if "root_mst_id" in message or "root" in message:
        field = "root_mst_id"
    elif "schema_version" in message:
        field = "schema_version"
    return _common.emit_validation_failure(
        target="dispatch_envelope",
        field=field,
        reason=message,
        external_control_surface="dispatch",
        prompt_summary_used_as_source=False,
    )
def _history_head_for_session(session_id: str) -> str:
    try:
        head = session_mod.session_history_head_path(_common.BASE_DIR, session_id).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head if re.fullmatch(r"[0-9a-f]{64}", head) else ""
def _append_dispatch_history_event(session_id: str, payload: dict, event_type: str) -> None:
    try:
        session_path = session_mod.session_metadata_path(_common.BASE_DIR, session_id)
    except ValueError:
        return
    if not session_path.is_file():
        return
    task_id = str(payload.get("task_id") or payload.get("child_artifact_id") or "").strip()
    if not task_id:
        return
    canonical_fields = _canonical_dispatch_fields(session_id)
    idempotency_key = f"{session_id}:{event_type}:{task_id}:{payload.get('phase', '')}:{payload.get('last_heartbeat', '')}"
    event = {
        **canonical_fields,
        "event_type": event_type,
        "type": event_type,
        "skill": str(payload.get("skill") or "mst:dispatch"),
        "artifact_id": task_id,
        "resource_id": task_id,
        "child_artifact_id": task_id,
        "external_control_surface": "dispatch",
        "history_head": _history_head_for_session(session_id) or None,
        "new_session_fallback": False,
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
        "provider": payload.get("provider"),
        "execution_transport": payload.get("execution_transport"),
        "launch_surface": payload.get("launch_surface"),
        "requested_launch_surface": payload.get("requested_launch_surface"),
        "launch_surface_status": payload.get("launch_surface_status"),
        "route_fingerprint": payload.get("route_fingerprint"),
        "orca_launch_status": payload.get("orca_launch_status"),
        "orca_terminal_handle": payload.get("orca_terminal_handle"),
        "orca_cleanup_status": payload.get("orca_cleanup_status"),
        "provider_task_id": payload.get("provider_task_id") or os.environ.get("MST_PROVIDER_TASK_ID"),
        "pid": payload.get("pid"),
        "ppid": os.getppid(),
        "started_by_pid": payload.get("started_by_pid"),
        "phase": payload.get("phase"),
        "status": payload.get("status") or payload.get("phase") or "running",
        "idempotency_key": idempotency_key,
        "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
        "created_at": _now_iso(),
    }
    if isinstance(payload.get("continuation"), dict):
        event["continuation"] = payload["continuation"]
        next_action = payload["continuation"].get("next_action")
        if isinstance(next_action, dict):
            event["next_action"] = next_action
    try:
        session_mod.write_session_history_event(_common.BASE_DIR, session_id, event)
    except Exception as exc:
        print(f"[dispatch] warning: failed to append dispatch history event ({exc})", file=sys.stderr)
def _coerce_positive_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
def _load_dispatch_config() -> dict:
    config_paths = [
        _common.BASE_DIR / "config.resolved.json",
        _plugin_root() / "templates" / "defaults" / "config.json",
    ]
    for path in config_paths:
        payload = load_json(path)
        if isinstance(payload, dict):
            dispatch = payload.get("dispatch")
            if isinstance(dispatch, dict):
                return dispatch
    return {}
def _dispatch_stale_threshold(args) -> int:
    if getattr(args, "stale_threshold", None) is not None:
        return _coerce_positive_int(args.stale_threshold, 60)
    dispatch_cfg = _load_dispatch_config()
    return _coerce_positive_int(dispatch_cfg.get("stale_threshold_sec"), 60)
def _resolve_provider_model(
    provider: str,
    explicit_model: str | None,
    *,
    requested_provider: str | None = None,
) -> str | None:
    if isinstance(explicit_model, str) and explicit_model.strip():
        return explicit_model.strip()

    normalized_provider = str(provider or "").strip().lower()
    requested = str(requested_provider or normalized_provider).strip().lower()
    config = resolve_model_mod._load_resolve_model_config()
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg, dict) else {}
    provider_cfg = providers_cfg.get(normalized_provider) if isinstance(providers_cfg, dict) else None
    if not isinstance(provider_cfg, dict) and requested != normalized_provider:
        provider_cfg = providers_cfg.get(requested) if isinstance(providers_cfg, dict) else None

    if isinstance(provider_cfg, dict):
        default_tier = provider_cfg.get("default_tier")
        if isinstance(default_tier, str):
            resolved = provider_cfg.get(default_tier)
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
            return None

        for candidate in ("premium", "economy", "default"):
            resolved = provider_cfg.get(candidate)
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        return None

    fallback = resolve_model_mod._resolve_provider_default_model(normalized_provider, provider_cfg)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def _resolve_provider_execution(
    provider: str,
    explicit_model: str | None,
    explicit_reasoning_effort: str | None = None,
    *,
    selector: str = "default",
    requested_provider: str | None = None,
) -> dict:
    return reasoning_effort_mod.resolve_execution(
        requested_provider or provider,
        selector,
        explicit_model=explicit_model,
        explicit_reasoning_effort=explicit_reasoning_effort,
    )


def _normalize_dispatch_provider(provider: str) -> tuple[str, str | None]:
    normalized = str(provider or "").strip().lower()
    if normalized == "gemini":
        return "agy", "gemini"
    return normalized, None


def _provider_executable(provider: str) -> str:
    if provider == "agy":
        return "agy"
    return provider


def _stdin_kind() -> str:
    try:
        mode = os.fstat(0).st_mode
    except OSError:
        return "unknown"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISFIFO(mode):
        return "pipe"
    if stat.S_ISCHR(mode):
        return "char-device"
    if stat.S_ISREG(mode):
        return "regular-file"
    return "other"
def _heartbeat_age_seconds(last_heartbeat: str, now: datetime) -> int:
    heartbeat_dt = _parse_utc_datetime(last_heartbeat)
    if heartbeat_dt is None:
        return 10**9
    delta = now - heartbeat_dt
    if delta.total_seconds() < 0:
        return 0
    return int(delta.total_seconds())
def _build_status_row(path: Path, stale_threshold: int, now: datetime) -> dict | None:
    payload = load_json(path)
    if not isinstance(payload, dict):
        return None

    task_id = str(payload.get("task_id") or path.stem)
    phase = str(payload.get("phase", "running"))
    payload_status = _safe_text(payload.get("status")).lower()
    terminal = _is_terminal_lifecycle(payload)
    reconciliation_action = (
        payload.get("reconciliation_action")
        if isinstance(payload.get("reconciliation_action"), dict)
        else None
    )
    reconciliation_actionable = bool(
        reconciliation_action
        and (
            _safe_text(reconciliation_action.get("status")).lower() == "pending"
            or reconciliation_action.get("completion_accepted") is False
        )
    )
    reconciliation_invariant_gap = bool(
        terminal
        and (
            payload.get("provider_reconciliation_required") is True
            or reconciliation_actionable
        )
    )
    last_heartbeat = str(payload.get("last_heartbeat", ""))
    age_sec = _heartbeat_age_seconds(last_heartbeat, now)
    is_stale = not terminal and age_sec >= stale_threshold
    execution_transport = str(payload.get("execution_transport") or "external").strip().lower()
    provider_state = _safe_text(payload.get("provider_state")).lower() or "unknown"
    parent_heartbeat = str(payload.get("parent_heartbeat") or "")
    parent_age_sec = _heartbeat_age_seconds(parent_heartbeat, now)
    reconciliation_required = False

    if terminal:
        status = payload_status or phase
    elif execution_transport == "native":
        provider_live = provider_state in {"running", "active", "queued", "attached", "spawned"}
        provider_terminal = provider_state in {"completed", "failed", "cancelled", "canceled", "terminal", "not_found"}
        if parent_age_sec >= stale_threshold:
            status = "orphaned"
            reconciliation_required = True
        elif provider_live:
            status = "running"
        elif provider_terminal or is_stale or provider_state in {"unknown", "indeterminate"}:
            status = "reconciling"
            reconciliation_required = True
        else:
            status = payload_status or "reconciling"
            reconciliation_required = status == "reconciling"
    elif payload.get("provider_reconciliation_required") or (
        reconciliation_actionable
    ):
        status = payload_status or phase or "reconciling"
        reconciliation_required = True
    elif is_stale:
        status = "stale"
    else:
        status = payload_status or "running"

    return {
        "task_id": task_id,
        "attempt_id": payload.get("attempt_id"),
        "pid": payload.get("pid"),
        "pid_start_time": payload.get("pid_start_time"),
        "provider": payload.get("provider"),
        "provider_task_id": payload.get("provider_task_id"),
        "external_claim_id": payload.get("external_claim_id"),
        "provider_pid": payload.get("provider_pid"),
        "provider_pgid": payload.get("provider_pgid"),
        "provider_pid_start_time": payload.get("provider_pid_start_time"),
        "provider_exec_release_status": payload.get("provider_exec_release_status"),
        "provider_exec_authorized_at": payload.get("provider_exec_authorized_at"),
        "provider_exec_released_at": payload.get("provider_exec_released_at"),
        "execution_transport": execution_transport,
        "launch_surface": str(payload.get("launch_surface") or "direct"),
        "requested_launch_surface": str(
            payload.get("requested_launch_surface") or "direct"
        ),
        "launch_surface_status": str(
            payload.get("launch_surface_status") or "disabled"
        ),
        "route_reason": payload.get("route_reason"),
        "route_fingerprint": payload.get("route_fingerprint"),
        "orca_launch_status": payload.get("orca_launch_status"),
        "orca_terminal_handle": payload.get("orca_terminal_handle"),
        "orca_terminal_title": payload.get("orca_terminal_title"),
        "orca_reconciliation_required": bool(
            payload.get("orca_reconciliation_required")
        ),
        "orca_cleanup_status": payload.get("orca_cleanup_status"),
        "completion_signal": payload.get("completion_signal"),
        "exit_code": payload.get("exit_code"),
        "skill": payload.get("skill", ""),
        "model": payload.get("model"),
        "phase": phase,
        "status": status,
        "last_heartbeat": last_heartbeat,
        "age_sec": age_sec,
        "parent_heartbeat": parent_heartbeat or None,
        "parent_age_sec": parent_age_sec,
        "provider_state": provider_state,
        "reconciliation_required": reconciliation_required,
        "reconciliation_invariant_gap": reconciliation_invariant_gap,
        "reconciliation_action": reconciliation_action,
        "worktree_dir": payload.get("worktree_dir"),
    }
def _collect_dispatch_rows(stale_threshold: int) -> list[dict]:
    directory = run_dir()
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        row = _build_status_row(path, stale_threshold, now)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda item: item.get("task_id", ""))
    return rows


def _posix_path(value) -> str:
    text = Path(str(value)).as_posix()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _matches_any_glob(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = _posix_path(path)
    return any(fnmatch.fnmatch(normalized, _posix_path(pattern)) for pattern in patterns)


def _git_output(worktree_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(worktree_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _absolute_git_path(base: Path, path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = (base / path).resolve(strict=False)
    return path.resolve(strict=False)


def _git_text(worktree_dir: Path, args: list[str]) -> tuple[bool, str]:
    result = _git_output(worktree_dir, args)
    output = result.stdout.strip() or result.stderr.strip()
    return result.returncode == 0, output


def _git_worktree_roots(repo_root: Path) -> set[Path]:
    ok, output = _git_text(repo_root, ["worktree", "list", "--porcelain"])
    if not ok:
        return set()
    roots: set[Path] = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            roots.add(Path(line[len("worktree "):]).resolve(strict=False))
    return roots


def validate_required_dispatch_worktree(target_value: str | Path | None) -> dict:
    if not target_value or not str(target_value).strip():
        return {
            "ok": False,
            "reason": "missing_worktree_dir",
            "message": "작업 worktree 경로가 필요합니다 (--worktree-dir).",
            "worktree_dir": None,
        }

    target_path = Path(str(target_value)).expanduser().resolve(strict=False)
    ok_root, root_output = _git_text(target_path, ["rev-parse", "--show-toplevel"])
    if not ok_root or not root_output:
        return {
            "ok": False,
            "reason": "not_git_worktree",
            "message": f"등록된 git worktree가 아닙니다: {target_path}",
            "worktree_dir": str(target_path),
        }

    worktree_root = Path(root_output).resolve(strict=False)
    ok_common, common_output = _git_text(worktree_root, ["rev-parse", "--git-common-dir"])
    if not ok_common or not common_output:
        return {
            "ok": False,
            "reason": "git_metadata_unavailable",
            "message": f"worktree git metadata를 확인할 수 없습니다: {worktree_root}",
            "worktree_dir": str(worktree_root),
        }

    common_dir = _absolute_git_path(worktree_root, common_output)
    primary_root = common_dir.parent.resolve(strict=False)
    if worktree_root == primary_root:
        return {
            "ok": False,
            "reason": "primary_checkout",
            "message": f"원본 primary checkout은 dispatch 작업 디렉토리로 사용할 수 없습니다: {worktree_root}",
            "worktree_dir": str(worktree_root),
        }

    if worktree_root not in _git_worktree_roots(worktree_root):
        return {
            "ok": False,
            "reason": "unregistered_worktree",
            "message": f"git worktree list에 등록되지 않은 경로입니다: {worktree_root}",
            "worktree_dir": str(worktree_root),
        }

    return {
        "ok": True,
        "reason": "registered_linked_worktree",
        "message": "registered linked worktree",
        "worktree_dir": str(worktree_root),
    }


def _git_status_entries(worktree_dir: Path) -> tuple[list[dict], str]:
    inside = _git_output(worktree_dir, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return [], "not_git_worktree"

    result = _git_output(worktree_dir, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if result.returncode != 0:
        return [], "git_status_failed"

    raw_entries = result.stdout.split("\0")
    entries: list[dict] = []
    index = 0
    while index < len(raw_entries):
        raw = raw_entries[index]
        if not raw:
            index += 1
            continue
        status = raw[:2]
        path_text = raw[3:] if len(raw) > 3 else ""
        if path_text:
            entries.append({"status": status, "path": _posix_path(path_text)})
        index += 2 if status[:1] in {"R", "C"} else 1
    return entries, ""


def _dirty_entry_category(status: str, path: str, generated_allowlist: list[str] | tuple[str, ...]) -> str:
    if _matches_any_glob(path, generated_allowlist):
        return "generated_allowlisted"
    if status == "??":
        return "untracked"
    if len(status) >= 1 and status[0] not in {" ", "?"}:
        return "staged"
    if len(status) >= 2 and status[1] != " ":
        return "unstaged"
    return "dirty"


def _isolation_metadata(mst_session_id: str = "", task_id: str = "", attempt_id: str = "") -> dict:
    metadata = {}
    if _safe_text(mst_session_id):
        metadata["mst_session_id"] = _safe_text(mst_session_id)
    if _safe_text(task_id):
        metadata["task_id"] = _safe_text(task_id)
    if _safe_text(attempt_id):
        metadata["attempt_id"] = _safe_text(attempt_id)
    return metadata


def _write_isolation_diagnostic(path: Path | str | None, payload: dict) -> None:
    if path is None:
        return
    diagnostic_path = Path(path)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def classify_dirty_tree(worktree_dir: Path | str, *, generated_allowlist: list[str] | tuple[str, ...] = ()) -> dict:
    worktree = Path(worktree_dir).resolve()
    raw_entries, status_error = _git_status_entries(worktree)
    dirty_entries = []
    for entry in raw_entries:
        path = str(entry.get("path") or "")
        status = str(entry.get("status") or "")
        category = _dirty_entry_category(status, path, generated_allowlist)
        dirty_entries.append(
            {
                "path": path,
                "status": status,
                "category": category,
                "allowlisted": category == "generated_allowlisted",
            }
        )
    return {
        "worktree_dir": str(worktree),
        "status": "dirty" if dirty_entries else "clean",
        "git_status_error": status_error or None,
        "dirty_entries": dirty_entries,
        "generated_allowlist": list(generated_allowlist),
    }


def dispatch_dirty_tree_precheck(
    worktree_dir: Path | str,
    *,
    diagnostic_path: Path | str | None = None,
    generated_allowlist: list[str] | tuple[str, ...] = (),
    mst_session_id: str = "",
    task_id: str = "",
    attempt_id: str = "",
) -> dict:
    classification = classify_dirty_tree(worktree_dir, generated_allowlist=generated_allowlist)
    evidence = {
        **_isolation_metadata(mst_session_id, task_id, attempt_id),
        "kind": "dirty_tree_precheck",
        "status": "clean",
        "mutation_allowed": True,
        **classification,
    }
    if classification["dirty_entries"]:
        evidence["status"] = "non_success"
        evidence["mutation_allowed"] = False
        evidence["structured_error"] = {
            "kind": "dirty_tree_precheck",
            "message": "dirty tree blocks implementation dispatch mutation",
        }
        _write_isolation_diagnostic(diagnostic_path, evidence)
    return evidence


def _clean_tree_fingerprint(worktree_dir: Path) -> dict:
    head = _git_output(worktree_dir, ["rev-parse", "HEAD"])
    status = _git_output(worktree_dir, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    return {
        "head": head.stdout.strip() if head.returncode == 0 else "",
        "status_sha256": hashlib.sha256(status.stdout.encode("utf-8")).hexdigest() if status.returncode == 0 else "",
    }


def guarded_dispatch_mutation(
    worktree_dir: Path | str,
    mutation,
    *,
    diagnostic_path: Path | str | None = None,
    generated_allowlist: list[str] | tuple[str, ...] = (),
    before_mutation=None,
    mst_session_id: str = "",
    task_id: str = "",
    attempt_id: str = "",
) -> dict:
    worktree = Path(worktree_dir).resolve()
    precheck = dispatch_dirty_tree_precheck(
        worktree,
        generated_allowlist=generated_allowlist,
        mst_session_id=mst_session_id,
        task_id=task_id,
        attempt_id=attempt_id,
    )
    if not precheck.get("mutation_allowed"):
        _write_isolation_diagnostic(diagnostic_path, precheck)
        return {**precheck, "mutation_executed": False}

    fingerprint = _clean_tree_fingerprint(worktree)
    if callable(before_mutation):
        before_mutation()

    revalidation = dispatch_dirty_tree_precheck(
        worktree,
        generated_allowlist=generated_allowlist,
        mst_session_id=mst_session_id,
        task_id=task_id,
        attempt_id=attempt_id,
    )
    if not revalidation.get("mutation_allowed"):
        evidence = {
            **_isolation_metadata(mst_session_id, task_id, attempt_id),
            "kind": "toctou_revalidation",
            "status": "non_success",
            "mutation_allowed": False,
            "mutation_executed": False,
            "precheck": precheck,
            "pre_mutation_fingerprint": fingerprint,
            "revalidation": revalidation,
            "structured_error": {
                "kind": "toctou_dirty_tree_change",
                "message": "worktree changed after precheck and before mutation",
            },
        }
        _write_isolation_diagnostic(diagnostic_path, evidence)
        return evidence

    mutation()
    return {
        **_isolation_metadata(mst_session_id, task_id, attempt_id),
        "kind": "toctou_revalidation",
        "status": "completed",
        "mutation_allowed": True,
        "mutation_executed": True,
        "precheck": precheck,
        "pre_mutation_fingerprint": fingerprint,
        "revalidation": revalidation,
    }


def _resource_values(scope: dict, key: str) -> list[str]:
    value = scope.get(key)
    if not isinstance(value, list):
        return []
    return [_posix_path(item) for item in value if _safe_text(item)]


def _logical_resource_group(value: str) -> str:
    normalized = _posix_path(value).lower()
    if normalized.startswith(".claude/hooks") or normalized.startswith("hooks/") or normalized == "hooks":
        return "hook canonical/copy set"
    if "manifest-agent" in normalized or normalized == "manifest":
        return "manifest-agent list"
    if "version" in normalized:
        return "version set"
    if any(token in normalized for token in ("config", "dashboard", "defaults")):
        return "config/dashboard/defaults"
    return normalized


def evaluate_parallel_scope_conflicts(task_scopes: list[dict]) -> dict:
    conflicts: list[dict] = []
    normalized_scopes = []
    for index, scope in enumerate(task_scopes):
        normalized_scopes.append(
            {
                "task_id": _safe_text(scope.get("task_id")) or f"task-{index + 1}",
                "exact_files": _resource_values(scope, "exact_files"),
                "globs": _resource_values(scope, "globs"),
                "generated_outputs": _resource_values(scope, "generated_outputs"),
                "logical_resources": [
                    _logical_resource_group(item)
                    for item in _resource_values(scope, "logical_resources")
                ],
            }
        )

    for left_index, left in enumerate(normalized_scopes):
        for right in normalized_scopes[left_index + 1 :]:
            left_exact = set(left["exact_files"])
            right_exact = set(right["exact_files"])
            for path in sorted(left_exact & right_exact):
                conflicts.append({"type": "exact_file", "path": path, "tasks": [left["task_id"], right["task_id"]]})

            for path in sorted((left_exact | set(left["generated_outputs"])) & set(right["generated_outputs"])):
                conflicts.append({"type": "generated_output", "path": path, "tasks": [left["task_id"], right["task_id"]]})
            for path in sorted(set(left["generated_outputs"]) & (right_exact | set(right["generated_outputs"]))):
                if not any(
                    conflict.get("type") == "generated_output" and conflict.get("path") == path
                    for conflict in conflicts
                ):
                    conflicts.append({"type": "generated_output", "path": path, "tasks": [left["task_id"], right["task_id"]]})

            for path in sorted(left_exact):
                for pattern in right["globs"]:
                    if fnmatch.fnmatch(path, pattern):
                        conflicts.append(
                            {"type": "glob_overlap", "path": path, "glob": pattern, "tasks": [left["task_id"], right["task_id"]]}
                        )
            for path in sorted(right_exact):
                for pattern in left["globs"]:
                    if fnmatch.fnmatch(path, pattern):
                        conflicts.append(
                            {"type": "glob_overlap", "path": path, "glob": pattern, "tasks": [left["task_id"], right["task_id"]]}
                        )

            for resource in sorted(set(left["logical_resources"]) & set(right["logical_resources"])):
                conflicts.append(
                    {
                        "type": "logical_resource",
                        "resource_group": resource,
                        "tasks": [left["task_id"], right["task_id"]],
                    }
                )

    return {
        "kind": "parallel_scope_conflict",
        "status": "non_success" if conflicts else "clean",
        "mutation_allowed": not conflicts,
        "conflicts": conflicts,
        "task_scopes": normalized_scopes,
    }


def _path_boundary(
    path: Path,
    *,
    repo_root: Path,
    worktree_root: Path,
    home_root: Path,
    plugin_cache_root: Path,
    temp_root: Path,
) -> str:
    resolved = path.resolve(strict=False)
    roots = [
        ("worktree-local", worktree_root.resolve(strict=False)),
        ("repo-local", repo_root.resolve(strict=False)),
        ("user-global", home_root.resolve(strict=False)),
        ("plugin-cache", plugin_cache_root.resolve(strict=False)),
        ("temp-dir", temp_root.resolve(strict=False)),
    ]
    for name, root in roots:
        try:
            resolved.relative_to(root)
            return name
        except ValueError:
            continue
    return "external"


def evaluate_shared_state_boundaries(
    writes: list[dict],
    *,
    repo_root: Path | str,
    worktree_root: Path | str,
    home_root: Path | str,
    plugin_cache_root: Path | str,
    temp_root: Path | str,
) -> dict:
    entries: list[dict] = []
    metadata_by_path: dict[str, set[tuple[str, str, str]]] = {}
    for write in writes:
        path = Path(str(write.get("path") or "")).resolve(strict=False)
        metadata = (
            _safe_text(write.get("mst_session_id")),
            _safe_text(write.get("task_id")),
            _safe_text(write.get("attempt_id")),
        )
        entry = {
            "path": str(path),
            "boundary": _path_boundary(
                path,
                repo_root=Path(repo_root),
                worktree_root=Path(worktree_root),
                home_root=Path(home_root),
                plugin_cache_root=Path(plugin_cache_root),
                temp_root=Path(temp_root),
            ),
            "mst_session_id": metadata[0],
            "task_id": metadata[1],
            "attempt_id": metadata[2],
            "metadata_complete": all(metadata),
        }
        entries.append(entry)
        metadata_by_path.setdefault(str(path), set()).add(metadata)

    mixed_paths = [
        {"path": path, "metadata_count": len(metadata)}
        for path, metadata in sorted(metadata_by_path.items())
        if len(metadata) > 1
    ]
    metadata_mixed = bool(mixed_paths) or any(not entry["metadata_complete"] for entry in entries)
    return {
        "kind": "shared_state_boundary",
        "status": "non_success" if metadata_mixed else "clean",
        "mutation_allowed": not metadata_mixed,
        "metadata_mixed": metadata_mixed,
        "mixed_paths": mixed_paths,
        "writes": entries,
    }


def _dispatch_prompt_hash(prompt_file: Path) -> str:
    return "sha256:" + hashlib.sha256(prompt_file.read_bytes()).hexdigest()


def _load_dispatch_external_authorization(task_id: str) -> dict:
    if _common.BASE_DIR is None:
        raise native_delegation_mod.LifecycleConflict(".gran-maestro base directory is required")
    path = native_delegation_mod.native_state_path(_common.BASE_DIR, task_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise native_delegation_mod.LifecycleConflict(
            f"persisted external authorization not found for task {task_id}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise native_delegation_mod.LifecycleConflict(
            f"persisted external authorization is unreadable for task {task_id}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise native_delegation_mod.LifecycleConflict(
            f"persisted external authorization is invalid for task {task_id}"
        )
    return payload


def validate_dispatch_external_authorization(
    *,
    task_id: str,
    provider: str,
    expected_attempt_id: str,
    worktree_dir: Path | str,
    prompt_file: Path | str,
    model: str | None = None,
    reasoning_effort: str | None = None,
    running_log_path: Path | str | None = None,
) -> dict:
    """Bind dispatch build/execution to one current persisted external attempt."""

    normalized_provider, _legacy = _normalize_dispatch_provider(provider)
    expected = _safe_text(expected_attempt_id)
    if not expected:
        raise native_delegation_mod.LifecycleConflict(
            "dispatch build requires --expected-attempt-id for protected external execution"
        )

    state = _load_dispatch_external_authorization(task_id)
    native_delegation_mod._validate_persisted_session_identity(state)
    current_attempt = _safe_text(state.get("attempt_id"))
    if current_attempt != expected:
        raise native_delegation_mod.LifecycleConflict(
            f"dispatch authorization attempt CAS mismatch: expected {expected}, current {current_attempt or 'missing'}"
        )
    if state.get("current_attempt") is not True:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization is not the current attempt")

    phase = _safe_text(state.get("phase")).lower()
    if phase == "reconciling" or state.get("provider_reconciliation_required"):
        raise native_delegation_mod.LifecycleConflict(
            "dispatch authorization is reconciling; external execution is forbidden"
        )
    if state.get("execution_transport") != "external":
        raise native_delegation_mod.LifecycleConflict(
            "dispatch authorization points to a native current attempt"
        )
    if phase != "planned":
        raise native_delegation_mod.LifecycleConflict(
            f"dispatch authorization cannot execute from phase '{phase or 'missing'}'"
        )
    status = _safe_text(state.get("status")).lower()
    if status in {"stale", "orphaned", "reconciling", "cancel_requested"}:
        raise native_delegation_mod.LifecycleConflict(
            f"dispatch authorization has non-runnable status '{status}'"
        )
    expires_at = native_delegation_mod._parse_iso_datetime(state.get("external_claim_expires_at"))
    if expires_at is not None and datetime.now(timezone.utc) >= expires_at:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization is stale and expired")
    if state.get("external_claim_id") or state.get("external_claimed_at"):
        raise native_delegation_mod.LifecycleConflict("dispatch authorization was already claimed")
    if _safe_text(state.get("task_id")) != task_id:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization task mismatch")
    if _safe_text(state.get("provider")).lower() != normalized_provider:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization provider mismatch")
    persisted_model = state.get("model")
    requested_model = str(model) if model is not None else None
    if (str(persisted_model) if persisted_model is not None else None) != requested_model:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization model mismatch")
    persisted_effort = state.get("reasoning_effort")
    requested_effort = str(reasoning_effort) if reasoning_effort is not None else None
    if (str(persisted_effort) if persisted_effort is not None else None) != requested_effort:
        raise native_delegation_mod.LifecycleConflict(
            "dispatch authorization reasoning effort mismatch"
        )

    requested_worktree = Path(worktree_dir).resolve(strict=False)
    persisted_worktree = Path(_safe_text(state.get("worktree_dir"))).resolve(strict=False)
    if requested_worktree != persisted_worktree:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization worktree mismatch")

    requested_prompt = Path(prompt_file).resolve(strict=False)
    persisted_prompt_text = _safe_text(state.get("prompt_file"))
    if not persisted_prompt_text or Path(persisted_prompt_text).resolve(strict=False) != requested_prompt:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization prompt path mismatch")
    if not requested_prompt.is_file():
        raise native_delegation_mod.LifecycleConflict(f"prompt file not found: {requested_prompt}")
    if _safe_text(state.get("prompt_hash")) != _dispatch_prompt_hash(requested_prompt):
        raise native_delegation_mod.LifecycleConflict("dispatch authorization prompt hash mismatch")

    if running_log_path is not None:
        requested_log = Path(running_log_path).resolve(strict=False)
        persisted_log_text = _safe_text(state.get("running_log_path"))
        if not persisted_log_text or Path(persisted_log_text).resolve(strict=False) != requested_log:
            raise native_delegation_mod.LifecycleConflict(
                "dispatch authorization running_log_path mismatch"
            )

    guard = state.get("worktree_guard")
    if not isinstance(guard, dict) or guard.get("ok") is not True:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization is missing worktree evidence")

    decision = native_delegation_mod._validate_persisted_route(state)
    if decision.get("route") != "external":
        raise native_delegation_mod.LifecycleConflict("persisted route does not authorize external dispatch")
    decision_provider = _safe_text(decision.get("provider")).lower()
    if decision_provider and _normalize_dispatch_provider(decision_provider)[0] != normalized_provider:
        raise native_delegation_mod.LifecycleConflict("dispatch authorization route provider mismatch")
    return state


def _emit_dispatch_authorization_failure(exc: Exception) -> int:
    print(
        json.dumps(
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 2


def _emit_dispatch_orca_worker_failure(args, exc: Exception, *, reason_code: str) -> int:
    """Persist an outer-controller wakeup before the Orca worker exits."""

    try:
        native_delegation_mod.record_orca_worker_failure(
            base_dir=_common.BASE_DIR,
            task_id=str(args.task_id).strip(),
            expected_attempt_id=args.expected_attempt_id,
            reason_code=reason_code,
        )
    except (
        TypeError,
        ValueError,
        native_delegation_mod.LifecycleConflict,
    ):
        pass
    return _emit_dispatch_authorization_failure(exc)


def cmd_dispatch_authorize_external(args):
    """Persist a central-planner external decision before dispatch build."""

    session_id = None
    session_context_json = None
    if os.environ.get("MST_SESSION_ID", "").strip() or os.environ.get("MST_CONTEXT_JSON", "").strip():
        try:
            child_env = _dispatch_required_session_context()
        except ValueError as exc:
            return _emit_dispatch_authorization_failure(
                native_delegation_mod.LifecycleConflict(str(exc))
            )
        session_id = child_env["MST_SESSION_ID"]
        session_context_json = child_env["MST_CONTEXT_JSON"]
        os.environ["MST_SESSION_ID"] = session_id
        os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]

    requested_provider = str(args.provider).strip().lower()
    provider, _legacy_provider = _normalize_dispatch_provider(requested_provider)
    try:
        execution = _resolve_provider_execution(
            provider,
            args.model,
            args.reasoning_effort,
            selector=args.selector,
            requested_provider=_legacy_provider,
        )
    except reasoning_effort_mod.ReasoningEffortError as exc:
        return _emit_dispatch_authorization_failure(
            native_delegation_mod.LifecycleConflict(str(exc))
        )
    resolved_model = execution.get("model")
    if not isinstance(resolved_model, str) or not resolved_model:
        return _emit_dispatch_authorization_failure(
            native_delegation_mod.LifecycleConflict(
                f"failed to resolve model for provider '{provider}'"
            )
        )
    prompt_file = Path(args.prompt_file).resolve(strict=False)
    worktree_dir = Path(args.worktree_dir).resolve(strict=False)
    if not prompt_file.is_file():
        return _emit_dispatch_authorization_failure(
            native_delegation_mod.LifecycleConflict(f"prompt file not found: {prompt_file}")
        )
    if _common.BASE_DIR is None:
        return _emit_dispatch_authorization_failure(
            native_delegation_mod.LifecycleConflict(".gran-maestro base directory is required")
        )

    host = str(host_mod.build_host_context(host="auto").get("host") or "headless")
    external_available = shutil.which(_provider_executable(provider)) is not None
    try:
        route = native_delegation_mod.resolve_delegation_route(
            base_dir=_common.BASE_DIR,
            host=host,
            provider=provider,
            scope=args.scope,
            capability_status=args.capability_status,
            external_adapter_available=external_available,
            worktree_dir=worktree_dir,
        )
        if route.get("route") != "external":
            raise native_delegation_mod.LifecycleConflict(
                "central delegation route does not authorize external dispatch "
                f"(route={route.get('route')}, reason={route.get('reason_code')})"
            )
        state = native_delegation_mod.start_external_attempt(
            base_dir=_common.BASE_DIR,
            task_id=args.task_id,
            provider=provider,
            worktree_dir=worktree_dir,
            idempotency_key=args.idempotency_key,
            route_reason=str(route.get("reason_code") or "external_authorized"),
            scope=args.scope,
            read_only=bool(args.read_only),
            prompt_file=prompt_file,
            running_log_path=args.running_log_path,
            trace_path=args.trace_path,
            output_path=args.output_path,
            model=resolved_model,
            reasoning_effort=execution.get("reasoning_effort"),
            reasoning_effort_source=execution.get("reasoning_effort_source"),
            mst_session_id=session_id,
            attempt_id=args.attempt_id,
            route_decision=route,
            mst_context_json=session_context_json,
        )
    except (native_delegation_mod.LifecycleConflict, native_delegation_mod.ExternalAdapterUnavailable) as exc:
        return _emit_dispatch_authorization_failure(exc)

    print(json.dumps(state, ensure_ascii=False))
    return 0


def cmd_dispatch_validate_authorization(args):
    try:
        state = validate_dispatch_external_authorization(
            task_id=str(args.task_id).strip(),
            provider=args.provider,
            expected_attempt_id=args.expected_attempt_id,
            worktree_dir=args.worktree_dir,
            prompt_file=args.prompt_file,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
        )
    except native_delegation_mod.LifecycleConflict as exc:
        return _emit_dispatch_authorization_failure(exc)
    print(
        json.dumps(
            {
                "status": "authorized",
                "task_id": state.get("task_id"),
                "attempt_id": state.get("attempt_id"),
                "provider": state.get("provider"),
                "execution_transport": state.get("execution_transport"),
                "launch_surface": state.get("launch_surface"),
                "launch_surface_status": state.get("launch_surface_status"),
                "orca_launch_status": state.get("orca_launch_status"),
                "orca_worktree_selector": state.get("orca_worktree_selector"),
                "route_fingerprint": state.get("route_fingerprint"),
                "model": state.get("model"),
                "reasoning_effort": state.get("reasoning_effort"),
                "reasoning_effort_source": state.get("reasoning_effort_source"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _dispatch_split_external_disabled(command_name: str) -> int:
    print(
        json.dumps(
            {
                "status": "central_runner_required",
                "blocked_command": command_name,
                "action": "use_dispatch_run_external",
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 2


def cmd_dispatch_claim_external(args):
    """Reject the obsolete split claim/spawn protocol."""

    return _dispatch_split_external_disabled("claim-external")


def _dispatch_external_monitor_callback(current: dict, running_log: Path) -> dict:
    try:
        owner_pid = int(current.get("pid"))
    except (TypeError, ValueError):
        owner_pid = os.getpid()
    result = evaluate_delegate_io_attention(
        current,
        {"combined": running_log},
        process_identity={
            "pid": owner_pid,
            "pid_start_time": str(current.get("pid_start_time") or ""),
            "pid_alive": _pid_is_alive(owner_pid),
        },
    )
    monitored = result.get("state") if isinstance(result, dict) else None
    if not isinstance(monitored, dict):
        return {}
    return {
        field: monitored[field]
        for field in ("delegate_monitor", "delegate_io_attention_events")
        if field in monitored
    }


def cmd_dispatch_run_external(args):
    """Run a protected external attempt through the single Python supervisor."""

    try:
        os.environ["MST_CONTEXT_JSON"] = (
            native_delegation_mod.load_persisted_mst_context(
                base_dir=_common.BASE_DIR,
                task_id=str(args.task_id).strip(),
                expected_attempt_id=args.expected_attempt_id,
                inherited_context=os.environ.get("MST_CONTEXT_JSON"),
            )
        )
    except native_delegation_mod.LifecycleConflict as exc:
        return _emit_dispatch_orca_worker_failure(
            args, exc, reason_code="orca_context_restore_failed"
        )
    try:
        child_env = _dispatch_required_session_context()
    except ValueError as exc:
        return _emit_dispatch_orca_worker_failure(
            args,
            native_delegation_mod.LifecycleConflict(str(exc)),
            reason_code="orca_context_validation_failed",
        )
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    timeout = args.timeout
    if timeout is None:
        raw_timeout = os.environ.get("MST_EXTERNAL_RUN_TIMEOUT", "").strip()
        if raw_timeout:
            try:
                timeout = max(0, int(raw_timeout))
            except ValueError:
                return _emit_dispatch_orca_worker_failure(
                    args,
                    native_delegation_mod.LifecycleConflict(
                        "MST_EXTERNAL_RUN_TIMEOUT must be an integer number of seconds"
                    ),
                    reason_code="orca_worker_timeout_config_invalid",
                )

    try:
        state = native_delegation_mod.run_persisted_external_adapter(
            base_dir=_common.BASE_DIR,
            task_id=str(args.task_id).strip(),
            expected_attempt_id=args.expected_attempt_id,
            idempotency_key=args.idempotency_key,
            binary=args.binary,
            timeout=timeout,
            monitor_callback=_dispatch_external_monitor_callback,
        )
    except (
        TypeError,
        ValueError,
        native_delegation_mod.LifecycleConflict,
        native_delegation_mod.ExternalAdapterUnavailable,
    ) as exc:
        return _emit_dispatch_orca_worker_failure(
            args, exc, reason_code="orca_external_adapter_failed"
        )
    _append_dispatch_history_event(session_id, state, "dispatch.external_run")
    if state.get("launch_surface") == "orca" and native_delegation_mod.lifecycle_is_terminal(
        state
    ):
        state = native_delegation_mod.mark_orca_cleanup_ready(
            base_dir=_common.BASE_DIR,
            task_id=str(args.task_id).strip(),
            expected_attempt_id=args.expected_attempt_id,
        )
    print(json.dumps(state, ensure_ascii=False))
    if state.get("phase") == "done":
        return 0
    try:
        provider_exit = int(state.get("exit_code") or 0)
    except (TypeError, ValueError):
        provider_exit = 0
    return provider_exit if 0 < provider_exit <= 255 else 3


def cmd_dispatch_launch_external(args):
    """Create one background Orca terminal for the protected external runner."""

    try:
        child_env = _dispatch_required_session_context()
    except ValueError as exc:
        return _emit_dispatch_authorization_failure(
            native_delegation_mod.LifecycleConflict(str(exc))
        )
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    try:
        state = native_delegation_mod.launch_external_via_orca(
            base_dir=_common.BASE_DIR,
            task_id=str(args.task_id).strip(),
            expected_attempt_id=args.expected_attempt_id,
            idempotency_key=args.idempotency_key,
        )
        if state.get("launch_surface") == "direct" and state.get("phase") == "planned":
            state = native_delegation_mod.run_persisted_external_adapter(
                base_dir=_common.BASE_DIR,
                task_id=str(args.task_id).strip(),
                expected_attempt_id=args.expected_attempt_id,
                idempotency_key=f"{args.idempotency_key}:direct-fallback-run",
                timeout=args.timeout,
                monitor_callback=_dispatch_external_monitor_callback,
            )
        elif (
            state.get("launch_surface") == "orca"
            and state.get("orca_launch_status") == "created"
        ):
            state = native_delegation_mod.wait_for_orca_cleanup_ready(
                base_dir=_common.BASE_DIR,
                task_id=str(args.task_id).strip(),
                expected_attempt_id=args.expected_attempt_id,
            )
            if state.get("orca_cleanup_status") in {
                "ready_to_close",
                "ready_to_preserve",
            }:
                state = native_delegation_mod.finalize_orca_terminal(
                    base_dir=_common.BASE_DIR,
                    task_id=str(args.task_id).strip(),
                    expected_attempt_id=args.expected_attempt_id,
                )
    except (
        TypeError,
        ValueError,
        native_delegation_mod.LifecycleConflict,
        native_delegation_mod.ExternalAdapterUnavailable,
    ) as exc:
        return _emit_dispatch_authorization_failure(exc)

    _append_dispatch_history_event(session_id, state, "dispatch.orca_launch")
    print(json.dumps(state, ensure_ascii=False))
    if state.get("phase") in {"planned", "running", "done"} and state.get(
        "orca_launch_status"
    ) in {"created", "closed"}:
        return 0
    if state.get("phase") == "done":
        return 0
    if state.get("status") == "launch_fallback_required":
        return 4
    return 3


def cmd_dispatch_heartbeat_external(args):
    return _dispatch_split_external_disabled("heartbeat-external")


def cmd_dispatch_finalize_external(args):
    return _dispatch_split_external_disabled("finalize-external")


def cmd_dispatch_build(args):
    requested_provider = str(args.provider).strip().lower()
    provider, legacy_provider = _normalize_dispatch_provider(requested_provider)

    try:
        execution = _resolve_provider_execution(
            provider,
            args.model,
            args.reasoning_effort,
            selector=args.selector,
            requested_provider=legacy_provider,
        )
    except reasoning_effort_mod.ReasoningEffortError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    resolved_model = execution.get("model")
    if not isinstance(resolved_model, str) or not resolved_model:
        print(f"Error: failed to resolve model for provider '{provider}'", file=sys.stderr)
        return 1

    prompt_file = Path(args.prompt_file).resolve()
    if not prompt_file.exists():
        print(f"Error: prompt file not found: {prompt_file}", file=sys.stderr)
        return 1

    worktree_dir = Path(args.worktree_dir).resolve()
    require_worktree = bool(getattr(args, "require_worktree", False))
    if require_worktree:
        worktree_validation = validate_required_dispatch_worktree(worktree_dir)
        if not worktree_validation.get("ok"):
            print(
                f"Error: worktree guard failed: {worktree_validation.get('message')}",
                file=sys.stderr,
            )
            return 2
    log_file = Path(args.log_file).resolve()
    task_id = str(args.task_id).strip()
    if not task_id:
        print("Error: task id is required", file=sys.stderr)
        return 1

    authorization = None
    expected_attempt_id = _safe_text(getattr(args, "expected_attempt_id", None))
    orca_enabled = bool(
        native_delegation_mod._resolved_delegation_settings(_common.BASE_DIR).get(
            "orca_enabled"
        )
    )
    protected_provider = provider in _PERSISTED_EXTERNAL_AUTH_PROVIDERS and (
        provider != "agy" or bool(expected_attempt_id) or orca_enabled
    )
    if protected_provider:
        if expected_attempt_id:
            try:
                authorization = validate_dispatch_external_authorization(
                    task_id=task_id,
                    provider=provider,
                    expected_attempt_id=expected_attempt_id,
                    worktree_dir=worktree_dir,
                    prompt_file=prompt_file,
                    model=resolved_model,
                    reasoning_effort=execution.get("reasoning_effort"),
                    running_log_path=log_file,
                )
            except native_delegation_mod.LifecycleConflict as exc:
                return _emit_dispatch_authorization_failure(exc)
        else:
            host = str(host_mod.build_host_context(host="auto").get("host") or "headless")
            if host == provider:
                return _emit_dispatch_authorization_failure(
                    native_delegation_mod.LifecycleConflict(
                        "same-host dispatch build requires a persisted external/fallback "
                        "authorization and --expected-attempt-id"
                    )
                )
            route = native_delegation_mod.resolve_delegation_route(
                base_dir=_common.BASE_DIR,
                host=host,
                provider=provider,
                scope="implementation",
                capability_status="unknown",
                external_adapter_available=shutil.which(_provider_executable(provider)) is not None,
                worktree_dir=worktree_dir,
            )
            if route.get("route") != "external":
                return _emit_dispatch_authorization_failure(
                    native_delegation_mod.LifecycleConflict(
                        "headless/cross-provider dispatch build is not externally routable "
                        f"(route={route.get('route')}, reason={route.get('reason_code')})"
                    )
                )

            # Compatibility callers historically invoked `dispatch build`
            # directly. Keep that surface, but never emit the old unclaimed
            # `dispatch register` wrapper for Codex/Claude. Persist the same
            # centrally-routed authorization that the explicit
            # `authorize-external` command creates, then let the generated
            # wrapper atomically consume it with `claim-external`.
            try:
                session_id = None
                if os.environ.get("MST_SESSION_ID", "").strip() or os.environ.get(
                    "MST_CONTEXT_JSON", ""
                ).strip():
                    child_env = _dispatch_required_session_context()
                    session_id = child_env["MST_SESSION_ID"]
                if not session_id:
                    raise native_delegation_mod.LifecycleConflict(
                        "dispatch build auto-authorization requires canonical MST_SESSION_ID"
                    )
                authorization = native_delegation_mod.start_external_attempt(
                    base_dir=_common.BASE_DIR,
                    task_id=task_id,
                    provider=provider,
                    worktree_dir=worktree_dir,
                    idempotency_key=f"{task_id}:dispatch-build-auto-authorize:v1",
                    route_reason=str(route.get("reason_code") or "external_authorized"),
                    scope="implementation" if require_worktree else "analysis",
                    read_only=not require_worktree,
                    prompt_file=prompt_file,
                    running_log_path=log_file,
                    model=resolved_model,
                    reasoning_effort=execution.get("reasoning_effort"),
                    reasoning_effort_source=execution.get("reasoning_effort_source"),
                    mst_session_id=session_id,
                    route_decision=route,
                )
            except (ValueError, native_delegation_mod.LifecycleConflict) as exc:
                return _emit_dispatch_authorization_failure(exc)
            expected_attempt_id = _safe_text(authorization.get("attempt_id"))
            if not expected_attempt_id:
                return _emit_dispatch_authorization_failure(
                    native_delegation_mod.LifecycleConflict(
                        "auto-authorized external attempt is missing attempt_id"
                    )
                )

    mst_script = _common._mst_script_path().resolve()
    q = shlex.quote
    session_bootstrap_cmd = _dispatch_session_bootstrap_cmd(
        _skill_dispatch_session_id(prompt_file, log_file, worktree_dir)
    )

    protected_external = authorization is not None and provider in _PERSISTED_EXTERNAL_AUTH_PROVIDERS
    trace_path = None
    output_path = None
    prompt_snapshot_path = None
    if protected_external:
        trace_path = Path(_safe_text(authorization.get("trace_path"))).resolve(strict=False)
        output_path = Path(_safe_text(authorization.get("output_path"))).resolve(strict=False)
        prompt_snapshot_path = Path(
            _safe_text(authorization.get("prompt_snapshot_path"))
        ).resolve(strict=False)
        if (
            not _safe_text(authorization.get("trace_path"))
            or not _safe_text(authorization.get("output_path"))
            or not _safe_text(authorization.get("prompt_snapshot_path"))
        ):
            return _emit_dispatch_authorization_failure(
                native_delegation_mod.LifecycleConflict(
                    "dispatch authorization is missing prompt/trace/output artifact bindings"
                )
            )
        register_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch claim-external '
            f"--task-id {q(task_id)} --provider {q(provider)} "
            f"--expected-attempt-id {q(expected_attempt_id)} --model {q(resolved_model)} "
            f"--worktree-dir {q(str(worktree_dir))} --prompt-file {q(str(prompt_file))} "
            f"--prompt-snapshot-path {q(str(prompt_snapshot_path))} "
            f"--scope {q(str(authorization.get('scope') or 'implementation'))} "
            f"--read-only {'true' if authorization.get('read_only') else 'false'} "
            f"--running-log-path {q(str(log_file))} --trace-path {q(str(trace_path))} "
            f"--output-path {q(str(output_path))} --pid $$ "
            f'--started-by-pid "${{MST_STATE_PPID:-$PPID}}" '
            f"--idempotency-key {q(task_id + ':' + expected_attempt_id + ':claim:v1')} "
            ">/dev/null || exit $?"
        )
    else:
        register_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch register '
            f"--task-id {q(task_id)} --pid $$ --provider {q(provider)} "
            f"--model {q(resolved_model)} --worktree-dir {q(str(worktree_dir))} "
            f'--started-by-pid "${{MST_STATE_PPID:-$PPID}}" '
            f"--running-log-path {q(str(log_file))} --context-file {q(str(prompt_file))}"
        )

    provider_failure_cmd = ""
    authorization_read_only = bool(
        isinstance(authorization, dict) and authorization.get("read_only")
    )
    resolved_effort = execution.get("reasoning_effort")
    if provider == "codex":
        # `--full-auto` was removed from recent Codex CLI releases. Keep the
        # permission policy explicit using the supported sandbox flag.
        permission_args = (
            "--sandbox read-only"
            if authorization_read_only
            else "--sandbox workspace-write"
        )
        codex_effort_config = f'model_reasoning_effort="{resolved_effort}"'
        effort_args = (
            f"-c {q(codex_effort_config)} "
            if resolved_effort
            else ""
        )
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" codex exec {permission_args} -m {q(resolved_model)} '
            f"{effort_args}-C {q(str(worktree_dir))} -"
        )
        prompt_redirect = f"< {q(str(prompt_snapshot_path if protected_external else prompt_file))}"
    elif provider == "claude":
        # Contract literals retained for security/inventory checks:
        # --permission-mode plan / --permission-mode acceptEdits
        permission_mode = "plan" if authorization_read_only else "acceptEdits"
        effort_args = f"--effort {q(str(resolved_effort))} " if resolved_effort else ""
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" claude -p '  # MST_EXTERNAL_FALLBACK_ONLY
            f"--model {q(resolved_model)} {effort_args}--permission-mode {permission_mode} --add-dir {q(str(worktree_dir))}"
        )
        prompt_redirect = f"< {q(str(prompt_snapshot_path if protected_external else prompt_file))}"
    else:
        effort_args = f"--effort {q(str(resolved_effort))} " if resolved_effort else ""
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" agy --print \"$(cat {q(str(prompt_file))})\" '
            f"{effort_args}--dangerously-skip-permissions --add-dir {q(str(worktree_dir))}"
        )
        prompt_redirect = "< /dev/null"
        legacy_note = ""
        if legacy_provider:
            legacy_note = f'echo "PROVIDER_DEPRECATION:{legacy_provider}->agy" >> {q(str(log_file))}; '
        provider_failure_cmd = (
            'MST_PROVIDER_FAILURE_KIND=""; '
            f"if grep -Eiq '(429|rate.?limit|quota|resource exhausted)' {q(str(log_file))}; then MST_PROVIDER_FAILURE_KIND=rate_limit; "
            f"elif grep -Eiq '(timed? ?out|timeout|deadline exceeded)' {q(str(log_file))}; then MST_PROVIDER_FAILURE_KIND=timeout; "
            f"elif [ ! -s {q(str(log_file))} ]; then MST_PROVIDER_FAILURE_KIND=empty_result; "
            'elif [ "$EC" -ne 0 ]; then MST_PROVIDER_FAILURE_KIND=nonzero_exit; fi; '
            f"MST_PROVIDER_EVIDENCE_ID={q(task_id + ':agy-failure')}; "
            'MST_PROVIDER_FALLBACK_CONDITION="${MST_PROVIDER_FAILURE_KIND:+codex_fallback_required}"; '
            f'echo "PROVIDER_FAILURE_KIND:${{MST_PROVIDER_FAILURE_KIND:-none}}" >> {q(str(log_file))}; '
            f'echo "PROVIDER_CODEX_FALLBACK_CONDITION:${{MST_PROVIDER_FALLBACK_CONDITION:-none}}" >> {q(str(log_file))}; '
            f'echo "PROVIDER_EVIDENCE_ID:$MST_PROVIDER_EVIDENCE_ID" >> {q(str(log_file))}; '
            f"{legacy_note}"
        )
    dispatch_attempt_cmd = (
        'MST_DISPATCH_FAILURE_KIND="${MST_PROVIDER_FAILURE_KIND:-}"; '
        f'if [ -z "$MST_DISPATCH_FAILURE_KIND" ] && grep -Eiq \'(timed? ?out|timeout|deadline exceeded)\' {q(str(log_file))}; then MST_DISPATCH_FAILURE_KIND=timeout; '
        f'elif [ -z "$MST_DISPATCH_FAILURE_KIND" ] && [ ! -s {q(str(log_file))} ]; then MST_DISPATCH_FAILURE_KIND=empty_result; '
        'elif [ -z "$MST_DISPATCH_FAILURE_KIND" ] && [ "${IO_EC:-0}" -ne 0 ]; then MST_DISPATCH_FAILURE_KIND=output_io; '
        'elif [ -z "$MST_DISPATCH_FAILURE_KIND" ] && [ "$EC" -ne 0 ]; then MST_DISPATCH_FAILURE_KIND=nonzero_exit; fi; '
        'MST_DISPATCH_FALLBACK_CONDITION="${MST_PROVIDER_FALLBACK_CONDITION:-none}"; '
        "printf 'DISPATCH_ATTEMPT_METADATA: task_id=%s provider=%s model=%s "
        "prompt_file=%s output_log=%s mst_session_id=%s exit_code=%s io_exit_code=%s failure_kind=%s fallback=%s\\n' "
        f"{q(task_id)} {q(provider)} {q(resolved_model)} {q(str(prompt_file))} {q(str(log_file))} "
        '"$MST_SESSION_ID" "$EC" "${IO_EC:-0}" "${MST_DISPATCH_FAILURE_KIND:-none}" "$MST_DISPATCH_FALLBACK_CONDITION" '
        f">> {q(str(log_file))}; "
    )

    if protected_external:
        heartbeat_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch heartbeat-external '
            f"--task-id {q(task_id)} --expected-attempt-id {q(expected_attempt_id)} "
            f"--pid $$ --log-file {q(str(log_file))}"
        )
        final_heartbeat_cmd = (
            'MST_EXTERNAL_COMPLETION_SIGNAL=process_exit; '
            'if [ "$EC" -eq 124 ]; then MST_EXTERNAL_COMPLETION_SIGNAL=process_timeout; '
            'elif [ "$EC" -eq 130 ] || [ "$EC" -eq 137 ] || [ "$EC" -eq 143 ]; '
            'then MST_EXTERNAL_COMPLETION_SIGNAL=process_cancelled; fi; '
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch finalize-external '
            f"--task-id {q(task_id)} --expected-attempt-id {q(expected_attempt_id)} "
            f'--pid $$ --exit-code "$EC" --io-exit-code "${{IO_EC:-0}}" '
            f'--completion-signal "$MST_EXTERNAL_COMPLETION_SIGNAL" '
            f"--running-log-path {q(str(log_file))} --trace-path {q(str(trace_path))} "
            f"--output-path {q(str(output_path))} "
            f"--idempotency-key {q(task_id + ':' + expected_attempt_id + ':finalize:v1')}"
        )
    else:
        heartbeat_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch heartbeat '
            f"--task-id {q(task_id)} --log-file {q(str(log_file))} "
            f"--running-log-path {q(str(log_file))}"
        )
        final_heartbeat_cmd = (
            f'{heartbeat_cmd} --final --exit-code "$EC" '
            '--failure-kind "${MST_DISPATCH_FAILURE_KIND:-none}" '
            '--fallback-condition "$MST_DISPATCH_FALLBACK_CONDITION"'
        )
    validate_worktree_cmd = ""
    if require_worktree:
        validate_worktree_cmd = (
            f"python3 {q(str(mst_script))} dispatch validate-worktree "
            f"--worktree-dir {q(str(worktree_dir))} >/dev/null || exit $?; "
        )

    if protected_external:
        execution_cmd = (
            'PROVIDER_PID=; MST_CANCEL_SIGNAL=; '
            'mst_forward_provider() { MST_CANCEL_SIGNAL="$1"; '
            'if [ -n "$PROVIDER_PID" ]; then '
            'kill "-$1" -- "-$PROVIDER_PID" 2>/dev/null '
            '|| kill "-$1" "$PROVIDER_PID" 2>/dev/null || true; fi; }; '
            "trap 'mst_forward_provider TERM' TERM; "
            "trap 'mst_forward_provider INT' INT; "
            "set -m; "
            f"{cli_cmd} {prompt_redirect} > {q(str(log_file))} 2>&1 & PROVIDER_PID=$!; "
            "set +m; "
            'wait "$PROVIDER_PID"; EC=$?; '
            'if [ -n "$MST_CANCEL_SIGNAL" ]; then '
            'wait "$PROVIDER_PID" 2>/dev/null || true; '
            'if [ "$MST_CANCEL_SIGNAL" = INT ]; then EC=130; else EC=143; fi; fi; '
            "trap - TERM INT; "
            "IO_EC=0; "
            f"cp {q(str(log_file))} {q(str(output_path))} || IO_EC=$?; "
        )
    else:
        execution_cmd = (
            f"{cli_cmd} {prompt_redirect} 2>&1 | tee {q(str(log_file))}; "
            'PIPE_STATUSES=("${PIPESTATUS[@]}"); '
            'EC="${PIPE_STATUSES[0]:-1}"; IO_EC="${PIPE_STATUSES[1]:-1}"; '
        )

    command = (
        f"{session_bootstrap_cmd}; "
        f"{validate_worktree_cmd}"
        f"{register_cmd}; "
        'HB_INTERVAL="${MST_DISPATCH_HEARTBEAT_INTERVAL:-120}"; '
        "set -o pipefail; "
        "(SLEEP_PID=; trap '[ -n \"$SLEEP_PID\" ] && kill \"$SLEEP_PID\" 2>/dev/null; exit 0' TERM INT; "
        "while kill -0 $$ 2>/dev/null; do sleep \"$HB_INTERVAL\" & SLEEP_PID=$!; "
        "wait \"$SLEEP_PID\" || exit 0; SLEEP_PID=; "
        f"{heartbeat_cmd} || true; done) & HB_PID=$!; "
        f"{execution_cmd}"
        "kill \"$HB_PID\" 2>/dev/null || true; wait \"$HB_PID\" 2>/dev/null || true; "
        f"{provider_failure_cmd}"
        f"{dispatch_attempt_cmd}"
        f"echo \"EXIT_CODE:$EC\" >> {q(str(log_file))}; "
        'MST_FINALIZE_EC=0; '
        f"{final_heartbeat_cmd} || MST_FINALIZE_EC=$?; "
        'if [ "$EC" -ne 0 ]; then exit "$EC"; fi; '
        'if [ "$MST_FINALIZE_EC" -ne 0 ]; then exit "$MST_FINALIZE_EC"; fi; '
        "exit 0"
    )
    if protected_external:
        # A single Python supervisor owns claim, exact prompt-byte delivery,
        # provider process-group reaping, atomic output publication, and
        # finalization.  The generated shell never reopens lifecycle paths.
        launch_command = (
            "launch-external"
            if authorization.get("launch_surface") == "orca"
            else "run-external"
        )
        central_run_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch {launch_command} '
            f"--task-id {q(task_id)} --expected-attempt-id {q(expected_attempt_id)} "
            f"--idempotency-key {q(task_id + ':' + expected_attempt_id + ':' + launch_command + ':v2')}"
        )
        command = (
            f"{session_bootstrap_cmd}; "
            f"{validate_worktree_cmd}"
            f"{central_run_cmd}"
        )
    if os.environ.get("MST_SESSION_ID", "").strip() and os.environ.get("MST_CONTEXT_JSON", "").strip():
        try:
            child_env = session_mod.child_env_with_required_session_context()
        except ValueError as exc:
            if isinstance(exc, _common.ContractValidationError):
                return _emit_dispatch_validation_failure(exc)
            validation_result = _emit_dispatch_value_error(exc)
            if validation_result is not None:
                return validation_result
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                _dispatch_context_envelope(
                    session_id=child_env["MST_SESSION_ID"],
                    task_id=task_id,
                    raw_context=child_env["MST_CONTEXT_JSON"],
                    command=command,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(command)
    return 0


def cmd_dispatch_validate_worktree(args):
    payload = validate_required_dispatch_worktree(getattr(args, "worktree_dir", None))
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    elif payload.get("ok"):
        print(payload.get("message") or "ok")
    else:
        print(payload.get("message") or "worktree validation failed", file=sys.stderr)
    return 0 if payload.get("ok") else 2
def cmd_dispatch_preflight(args):
    requested_provider = str(args.provider).strip().lower()
    provider, legacy_provider = _normalize_dispatch_provider(requested_provider)
    executable = _provider_executable(provider)
    if shutil.which(executable) is None:
        if provider == "agy":
            payload = {
                "provider": provider,
                "binary": executable,
                "failure_kind": "missing_cli",
                "evidence_id": f"dispatch-preflight:{provider}:missing_cli",
                "skip_reason": "required_binary_missing",
            }
            if legacy_provider:
                payload["deprecated_alias"] = legacy_provider
            print(json.dumps(payload, ensure_ascii=False))
        print(f"Error: required binary '{executable}' not found in PATH", file=sys.stderr)
        return 1

    try:
        execution = _resolve_provider_execution(
            provider,
            args.model,
            args.reasoning_effort,
            selector=args.selector,
            requested_provider=legacy_provider,
        )
    except reasoning_effort_mod.ReasoningEffortError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    resolved_model = execution.get("model")
    if not isinstance(resolved_model, str) or not resolved_model:
        print(f"Error: failed to resolve model for provider '{provider}'", file=sys.stderr)
        return 1

    stdin_kind = _stdin_kind()
    print(f"[dispatch] stdin={stdin_kind}", file=sys.stderr)
    if stdin_kind in {"pipe", "socket"}:
        print(
            f"[dispatch] warning: stdin is {stdin_kind}; background CLI must close stdin explicitly.",
            file=sys.stderr,
        )

    payload = {
        "provider": provider,
        "binary": executable,
        "model": resolved_model,
        "reasoning_effort": execution.get("reasoning_effort"),
        "reasoning_effort_source": execution.get("reasoning_effort_source"),
        "stdin": stdin_kind,
    }
    if legacy_provider:
        payload["deprecated_alias"] = legacy_provider
    print(json.dumps(payload, ensure_ascii=False))
    return 0
