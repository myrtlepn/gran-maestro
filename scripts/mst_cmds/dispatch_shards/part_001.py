from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.mst_cmds import _common
from scripts.mst_cmds import cleanup as cleanup_mod
from scripts.mst_cmds import resolve_model as resolve_model_mod
from scripts.mst_cmds import session as session_mod
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
        return ""
    parts = text.rsplit(") ", 1)
    if len(parts) != 2:
        return ""
    fields = parts[1].split()
    return fields[19] if len(fields) > 19 else ""
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
)


def _json_object_or_empty(raw: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_text(value) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


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
    label = _safe_text(explicit_label)
    if label:
        return label
    label = _safe_text(skill)
    if label:
        return label
    return _safe_text(task_id) or "dispatch"


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


def _sync_attempt_payload(payload: dict) -> dict:
    attempt_id = _safe_text(payload.get("attempt_id"))
    if not attempt_id:
        return payload
    attempts = _ensure_attempts(payload)
    current = _attempt_snapshot(payload)
    replaced = False
    for index, attempt in enumerate(attempts):
        if _safe_text(attempt.get("attempt_id")) == attempt_id:
            attempts[index] = current
            replaced = True
            break
    if not replaced:
        attempts.append(current)
    payload["attempts"] = attempts
    return payload


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
        "provider_task_id": payload.get("provider_task_id") or os.environ.get("MST_PROVIDER_TASK_ID"),
        "pid": payload.get("pid"),
        "ppid": os.getppid(),
        "started_by_pid": payload.get("started_by_pid"),
        "phase": payload.get("phase"),
        "status": payload.get("phase") or "running",
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
def _resolve_provider_model(provider: str, explicit_model: str | None) -> str | None:
    if isinstance(explicit_model, str) and explicit_model.strip():
        return explicit_model.strip()

    config = resolve_model_mod._load_resolve_model_config()
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg, dict) else {}
    provider_cfg = providers_cfg.get(provider) if isinstance(providers_cfg, dict) else None

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

    fallback = resolve_model_mod._resolve_provider_default_model(provider, provider_cfg)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None
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
    last_heartbeat = str(payload.get("last_heartbeat", ""))
    age_sec = _heartbeat_age_seconds(last_heartbeat, now)
    is_stale = phase not in _TERMINAL_PHASES and age_sec >= stale_threshold

    if phase in _TERMINAL_PHASES:
        status = payload_status or phase
    elif is_stale:
        status = "stale"
    else:
        status = payload_status or "running"

    return {
        "task_id": task_id,
        "pid": payload.get("pid"),
        "provider": payload.get("provider"),
        "skill": payload.get("skill", ""),
        "model": payload.get("model"),
        "phase": phase,
        "status": status,
        "last_heartbeat": last_heartbeat,
        "age_sec": age_sec,
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
def cmd_dispatch_build(args):
    provider = str(args.provider).strip().lower()
    if provider == "claude":
        print(
            "Error: dispatch build does not support provider 'claude'. Use Task-based claude dispatch.",
            file=sys.stderr,
        )
        return 1

    resolved_model = _resolve_provider_model(provider, args.model)
    if not isinstance(resolved_model, str) or not resolved_model:
        print(f"Error: failed to resolve model for provider '{provider}'", file=sys.stderr)
        return 1

    prompt_file = Path(args.prompt_file).resolve()
    if not prompt_file.exists():
        print(f"Error: prompt file not found: {prompt_file}", file=sys.stderr)
        return 1

    worktree_dir = Path(args.worktree_dir).resolve()
    log_file = Path(args.log_file).resolve()
    task_id = str(args.task_id).strip()
    if not task_id:
        print("Error: task id is required", file=sys.stderr)
        return 1

    mst_script = _common._mst_script_path().resolve()
    q = shlex.quote
    session_bootstrap_cmd = _dispatch_session_bootstrap_cmd(
        _skill_dispatch_session_id(prompt_file, log_file, worktree_dir)
    )

    register_cmd = (
        f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch register '
        f"--task-id {q(task_id)} --pid $$ --provider {q(provider)} "
        f"--model {q(resolved_model)} --worktree-dir {q(str(worktree_dir))} "
        f'--started-by-pid "${{MST_STATE_PPID:-$PPID}}" '
        f"--running-log-path {q(str(log_file))} --context-file {q(str(prompt_file))}"
    )

    gemini_failure_cmd = ""
    if provider == "codex":
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" codex exec --full-auto -m {q(resolved_model)} -C {q(str(worktree_dir))} '
            f"\"$(cat {q(str(prompt_file))})\""
        )
    else:
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" gemini -p \"$(cat {q(str(prompt_file))})\" --model {q(resolved_model)} '
            "--approval-mode yolo --sandbox=false"
        )
        gemini_failure_cmd = (
            'MST_GEMINI_FAILURE_KIND=""; '
            f"if grep -Eiq '(429|rate.?limit|quota|resource exhausted)' {q(str(log_file))}; then MST_GEMINI_FAILURE_KIND=rate_limit; "
            f"elif grep -Eiq '(timed? ?out|timeout|deadline exceeded)' {q(str(log_file))}; then MST_GEMINI_FAILURE_KIND=timeout; "
            f"elif [ ! -s {q(str(log_file))} ]; then MST_GEMINI_FAILURE_KIND=empty_result; "
            'elif [ "$EC" -ne 0 ]; then MST_GEMINI_FAILURE_KIND=nonzero_exit; fi; '
            f"MST_GEMINI_EVIDENCE_ID={q(task_id + ':gemini-failure')}; "
            'MST_GEMINI_CODEX_FALLBACK_CONDITION="${MST_GEMINI_FAILURE_KIND:+codex_fallback_required}"; '
            f'echo "GEMINI_FAILURE_KIND:${{MST_GEMINI_FAILURE_KIND:-none}}" >> {q(str(log_file))}; '
            f'echo "GEMINI_CODEX_FALLBACK_CONDITION:${{MST_GEMINI_CODEX_FALLBACK_CONDITION:-none}}" >> {q(str(log_file))}; '
            f'echo "GEMINI_EVIDENCE_ID:$MST_GEMINI_EVIDENCE_ID" >> {q(str(log_file))}; '
        )
    dispatch_attempt_cmd = (
        'MST_DISPATCH_FAILURE_KIND="${MST_GEMINI_FAILURE_KIND:-}"; '
        f'if [ -z "$MST_DISPATCH_FAILURE_KIND" ] && grep -Eiq \'(timed? ?out|timeout|deadline exceeded)\' {q(str(log_file))}; then MST_DISPATCH_FAILURE_KIND=timeout; '
        f'elif [ -z "$MST_DISPATCH_FAILURE_KIND" ] && [ ! -s {q(str(log_file))} ]; then MST_DISPATCH_FAILURE_KIND=empty_result; '
        'elif [ -z "$MST_DISPATCH_FAILURE_KIND" ] && [ "$EC" -ne 0 ]; then MST_DISPATCH_FAILURE_KIND=nonzero_exit; fi; '
        'MST_DISPATCH_FALLBACK_CONDITION="${MST_GEMINI_CODEX_FALLBACK_CONDITION:-none}"; '
        "printf 'DISPATCH_ATTEMPT_METADATA: task_id=%s provider=%s model=%s "
        "prompt_file=%s output_log=%s mst_session_id=%s exit_code=%s failure_kind=%s fallback=%s\\n' "
        f"{q(task_id)} {q(provider)} {q(resolved_model)} {q(str(prompt_file))} {q(str(log_file))} "
        '"$MST_SESSION_ID" "$EC" "${MST_DISPATCH_FAILURE_KIND:-none}" "$MST_DISPATCH_FALLBACK_CONDITION" '
        f">> {q(str(log_file))}; "
    )

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

    command = (
        f"{session_bootstrap_cmd}; "
        f"{register_cmd}; "
        'HB_INTERVAL="${MST_DISPATCH_HEARTBEAT_INTERVAL:-120}"; '
        "set -o pipefail; "
        "(SLEEP_PID=; trap '[ -n \"$SLEEP_PID\" ] && kill \"$SLEEP_PID\" 2>/dev/null; exit 0' TERM INT; "
        "while kill -0 $$ 2>/dev/null; do sleep \"$HB_INTERVAL\" & SLEEP_PID=$!; "
        "wait \"$SLEEP_PID\" || exit 0; SLEEP_PID=; "
        f"{heartbeat_cmd} || true; done) & HB_PID=$!; "
        f"{cli_cmd} < /dev/null 2>&1 | tee {q(str(log_file))}; "
        "EC=${PIPESTATUS[0]}; "
        "kill \"$HB_PID\" 2>/dev/null || true; wait \"$HB_PID\" 2>/dev/null || true; "
        f"{gemini_failure_cmd}"
        f"{dispatch_attempt_cmd}"
        f"echo \"EXIT_CODE:$EC\" >> {q(str(log_file))}; "
        f"{final_heartbeat_cmd}; "
        "exit $EC"
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
def cmd_dispatch_preflight(args):
    provider = str(args.provider).strip().lower()
    executable = provider
    if shutil.which(executable) is None:
        print(f"Error: required binary '{executable}' not found in PATH", file=sys.stderr)
        return 1

    resolved_model = _resolve_provider_model(provider, args.model)
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

    print(
        json.dumps(
            {"provider": provider, "binary": executable, "model": resolved_model, "stdin": stdin_kind},
            ensure_ascii=False,
        )
    )
    return 0
