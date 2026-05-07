from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVENT_TYPE = "prompt.submitted"
SOURCE = "UserPromptSubmit"
SCHEMA_VERSION = 1
MAX_EXCERPT_CHARS = 240
MAX_ANCHORS = 20
MAX_FOLLOWING_EVENTS = 50
ZERO_HASH = "0" * 64
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MST_SESSION_RE = re.compile(r"^MST-([A-Z][A-Z0-9]*-\d+)-\d{8}T\d{9}Z-[a-z0-9]{8,}$")
CORRELATION_BASIS = ("ledger_order", "timestamp", "head_relation")
FORBIDDEN_EVENT_KEYS = {
    "prompt",
    "prompt_text",
    "raw_prompt",
    "raw_prompt_text",
    "full_prompt",
    "raw_transcript",
    "raw_history",
    "history_rows",
    "ledger_rows",
    "llm_summary",
    "semantic_summary",
    "prompt_summary",
}


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


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _identity(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("identity") if isinstance(context.get("identity"), dict) else {}


def _identity_env(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    return identity.get("env") if isinstance(identity.get("env"), dict) else {}


def _identity_structured(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    return identity.get("context") if isinstance(identity.get("context"), dict) else {}


def _valid_mst_session_id(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if "/" in text or ".." in text:
        return ""
    return text if MST_SESSION_RE.fullmatch(text) else ""


def _root_mst_id(mst_session_id: str) -> str:
    match = MST_SESSION_RE.fullmatch(mst_session_id)
    return match.group(1) if match else ""


def _identity_resolution(context: dict[str, Any]) -> dict[str, Any]:
    env_value = _valid_mst_session_id(_identity_env(context).get("MST_SESSION_ID"))
    structured_value = _valid_mst_session_id(_identity_structured(context).get("mst_session_id"))
    if env_value and structured_value and env_value != structured_value:
        return {
            "ok": False,
            "code": "mst_session_id_mismatch",
            "mst_session_id": None,
            "legacy_diagnostics": _legacy_diagnostics(context),
        }
    mst_session_id = env_value or structured_value
    if not mst_session_id:
        return {
            "ok": False,
            "code": "missing_canonical_mst_session_id",
            "mst_session_id": None,
            "legacy_diagnostics": _legacy_diagnostics(context),
        }
    return {
        "ok": True,
        "code": "ok",
        "mst_session_id": mst_session_id,
        "legacy_diagnostics": _legacy_diagnostics(context),
    }


def _legacy_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    diagnostics = identity.get("legacy_diagnostics") if isinstance(identity.get("legacy_diagnostics"), dict) else {}
    result = dict(diagnostics)
    env = _identity_env(context)
    structured = _identity_structured(context)

    for source_key, target_key in (
        ("MST_STATE_PPID", "owner_pid"),
        ("MST_SNAPSHOT_SESSION_ID", "snapshot_session_id"),
    ):
        value = _safe_text(env.get(source_key))
        if value:
            result.setdefault(target_key, value)
    for source_key, target_key in (
        ("session_id", "hook_session_id"),
        ("owner_session_id", "owner_session_id"),
        ("owner_pid", "owner_pid"),
        ("owner_ppid", "owner_ppid"),
        ("ppid", "owner_ppid"),
    ):
        value = _safe_text(structured.get(source_key))
        if value:
            result.setdefault(target_key, value)
    transcript_path = _safe_text(structured.get("transcript_path") or context.get("transcript_path"))
    if transcript_path:
        name = Path(transcript_path).name
        stem = name[:-6] if name.endswith(".jsonl") else Path(name).stem
        if stem:
            result.setdefault("hook_transcript_stem", stem)
    return result


def _prompt_bytes(context: dict[str, Any]) -> bytes:
    value = context.get("prompt_bytes")
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, list) and all(isinstance(item, int) and 0 <= item <= 255 for item in value):
        return bytes(value)
    for key in ("prompt_text", "prompt", "user_prompt", "input", "text"):
        candidate = context.get(key)
        if isinstance(candidate, str):
            return candidate.encode("utf-8")
    return b""


def _prompt_digest(prompt_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(prompt_bytes).hexdigest()


def _prompt_excerpt(prompt_bytes: bytes, max_chars: int) -> dict[str, Any]:
    max_chars = max(1, min(MAX_EXCERPT_CHARS, int(max_chars or MAX_EXCERPT_CHARS)))
    text = prompt_bytes.decode("utf-8", errors="replace")
    excerpt_text = text[:max_chars]
    excerpt_bytes = excerpt_text.encode("utf-8")
    return {
        "text": excerpt_text,
        "max_chars": max_chars,
        "truncated": len(text) > max_chars,
        "omitted_bytes": max(0, len(prompt_bytes) - len(excerpt_bytes)),
    }


def _head_value(value: Any) -> str | None:
    if value is None:
        return None
    text = _safe_text(value)
    if not text or text == ZERO_HASH:
        return None
    return text if HASH_RE.fullmatch(text) else None


def _history_head_from_rows(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        value = _head_value(row.get("event_hash"))
        if value:
            return value
    return None


def _history_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = context.get("history_rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    rows = context.get("raw_history_rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _history_paths(project_root: Path, mst_session_id: str) -> tuple[Path, Path]:
    history_file = project_root / ".gran-maestro" / "sessions" / mst_session_id / "history.ndjson"
    head_file = history_file.parent / "history.head"
    return history_file, head_file


def _read_history_rows(project_root: Path, mst_session_id: str) -> list[dict[str, Any]]:
    history_file, _ = _history_paths(project_root, mst_session_id)
    if not history_file.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in history_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_current_head(project_root: Path, mst_session_id: str) -> str | None:
    rows = _read_history_rows(project_root, mst_session_id)
    if rows:
        return _history_head_from_rows(rows)
    _, head_file = _history_paths(project_root, mst_session_id)
    if not head_file.is_file():
        return None
    try:
        return _head_value(head_file.read_text(encoding="utf-8"))
    except OSError:
        return None


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(value, encoding="utf-8")
    tmp_path.replace(path)


def _mirror_head_path(policy_home: Path, mst_session_id: str) -> Path:
    return policy_home / "ledger-heads" / f"{mst_session_id}.head"


def _history_lock_path(project_root: Path, mst_session_id: str) -> Path:
    history_file, _ = _history_paths(project_root, mst_session_id)
    return history_file.parent / "history.lock"


def _acquire_history_lock(lock_path: Path) -> bool:
    for _ in range(20):
        try:
            lock_path.mkdir(parents=True)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False


def _release_history_lock(lock_path: Path) -> None:
    try:
        lock_path.rmdir()
    except OSError:
        pass


def _verify_history_chain(project_root: Path, policy_home: Path, mst_session_id: str) -> tuple[bool, str | None]:
    history_file, local_head = _history_paths(project_root, mst_session_id)
    mirror_head = _mirror_head_path(policy_home, mst_session_id)
    expected_prev = ZERO_HASH
    last_hash = ZERO_HASH
    expected_seq = 1
    if history_file.exists():
        try:
            with history_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict) or row.get("seq") != expected_seq:
                        return False, "seq"
                    if row.get("prev_hash") != expected_prev:
                        return False, "prev_hash"
                    event = row.get("event")
                    if not isinstance(event, dict):
                        return False, "event"
                    computed = _event_hash(expected_prev, event)
                    if row.get("event_hash") != computed:
                        return False, "event_hash"
                    expected_prev = computed
                    last_hash = computed
                    expected_seq += 1
        except (OSError, json.JSONDecodeError):
            return False, "history_read"

    local_value = _head_value(local_head.read_text(encoding="utf-8")) if local_head.exists() else None
    mirror_value = _head_value(mirror_head.read_text(encoding="utf-8")) if mirror_head.exists() else None
    has_entries = expected_seq > 1
    if has_entries and (local_value != last_hash or mirror_value != last_hash):
        return False, "head"
    if not has_entries and (local_value is not None or mirror_value is not None):
        return False, "empty_head"
    return True, None


def _append_history_event(project_root: Path, policy_home: Path, mst_session_id: str, event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    history_file, local_head = _history_paths(project_root, mst_session_id)
    mirror_head = _mirror_head_path(policy_home, mst_session_id)
    lock_path = _history_lock_path(project_root, mst_session_id)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_history_lock(lock_path):
        raise RuntimeError("history ledger mismatch: lock timeout")
    try:
        ok, reason = _verify_history_chain(project_root, policy_home, mst_session_id)
        if not ok:
            raise RuntimeError(f"history ledger mismatch: {reason}")
        rows = _read_history_rows(project_root, mst_session_id)
        for row in rows:
            row_event = row.get("event") if isinstance(row.get("event"), dict) else {}
            if row_event.get("idempotency_key") == event.get("idempotency_key"):
                return False, row

        prev_hash = _head_value(local_head.read_text(encoding="utf-8")) if local_head.exists() else None
        prev_hash = prev_hash or ZERO_HASH
        normalized = dict(event)
        normalized["schema_version"] = SCHEMA_VERSION
        normalized["mst_session_id"] = mst_session_id
        normalized["root_mst_id"] = _root_mst_id(mst_session_id)
        normalized["event_type"] = normalized.get("event_type") or normalized.get("type") or EVENT_TYPE
        normalized["created_at"] = _safe_text(normalized.get("created_at")) or _utc_now()
        normalized["history_head_before"] = None if prev_hash == ZERO_HASH else prev_hash
        normalized["idempotency_key"] = _idempotency_key(mst_session_id, str(normalized.get("prompt_digest") or ""), _head_value(normalized.get("history_head_before")))
        event_hash = _event_hash(prev_hash, normalized)
        row = {
            "schema_version": SCHEMA_VERSION,
            "seq": len(rows) + 1,
            "prev_hash": prev_hash,
            "event_hash": event_hash,
            "event": normalized,
            "mst_session_id": mst_session_id,
            "root_mst_id": normalized["root_mst_id"],
            "event_type": normalized["event_type"],
            "created_at": normalized["created_at"],
            "idempotency_key": normalized["idempotency_key"],
        }
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        _write_text_atomic(mirror_head, event_hash + "\n")
        _write_text_atomic(local_head, event_hash + "\n")
        verify_path = history_file.parent / "history.verify"
        _write_text_atomic(verify_path, f"{event_hash}\t{_file_fingerprint(history_file)}\t{row['seq']}\n")
        return True, row
    finally:
        _release_history_lock(lock_path)


def _transcript_path(context: dict[str, Any]) -> str:
    structured = _identity_structured(context)
    return _safe_text(context.get("transcript_path") or structured.get("transcript_path"))


def _idempotency_key(mst_session_id: str, prompt_digest: str, history_head_before: str | None) -> str:
    head = history_head_before if history_head_before is not None else "null"
    return f"{mst_session_id}:{EVENT_TYPE}:{prompt_digest}:head={head}:source={SOURCE}"


def _event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key not in FORBIDDEN_EVENT_KEYS}


def build_prompt_submitted_event(fixture: dict[str, Any]) -> dict[str, Any]:
    context = _load_context(fixture)
    resolution = _identity_resolution(context)
    if not resolution["ok"]:
        raise ValueError(str(resolution["code"]))
    mst_session_id = str(resolution["mst_session_id"])
    prompt_bytes = _prompt_bytes(context)
    digest = _prompt_digest(prompt_bytes)
    rows = _history_rows(context)
    head_before = _head_value(context.get("history_head_before"))
    if "history_head_before" not in context:
        head_before = _history_head_from_rows(rows)
    max_chars = context.get("excerpt_max_chars", MAX_EXCERPT_CHARS)
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_type": EVENT_TYPE,
        "type": EVENT_TYPE,
        "created_at": _safe_text(context.get("created_at")) or _utc_now(),
        "mst_session_id": mst_session_id,
        "canonical_mst_session_id": mst_session_id,
        "lookup_key": mst_session_id,
        "partition_key": mst_session_id,
        "prompt_digest": digest,
        "prompt_size_bytes": len(prompt_bytes),
        "prompt_excerpt": _prompt_excerpt(prompt_bytes, max_chars),
        "transcript_path": _transcript_path(context),
        "history_head_before": head_before,
        "idempotency_key": _idempotency_key(mst_session_id, digest, head_before),
        "source": SOURCE,
        "writer_id": "prompt_writer",
        "write_status": "success",
    }
    return _sanitize_event(event)


def _find_existing_prompt(
    rows: list[dict[str, Any]],
    *,
    idempotency_key: str = "",
    digest: str = "",
    source: str = SOURCE,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for row in rows:
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            continue
        if event.get("event_type") != EVENT_TYPE:
            continue
        if idempotency_key and event.get("idempotency_key") == idempotency_key:
            return row, event
        if not idempotency_key and digest and event.get("prompt_digest") == digest and event.get("source") == source:
            return row, event
    return None


def _result_error(code: str, context: dict[str, Any], *, event: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "code": code,
        "appended": False,
        "duplicate": False,
        "mutation_performed": False,
        "event": event,
        "legacy_diagnostics": _legacy_diagnostics(context),
    }


def _bounded_return_rows(rows: list[dict[str, Any]], appended_row: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if appended_row is None:
        return []
    return [appended_row]


def _append_in_memory(context: dict[str, Any], event: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    existing = _find_existing_prompt(rows, idempotency_key=event["idempotency_key"])
    if existing is not None:
        row, existing_event = existing
        return {
            "status": "ok",
            "code": "duplicate",
            "appended": False,
            "duplicate": True,
            "mutation_performed": False,
            "event": _sanitize_event(dict(existing_event)),
            "history_head_before": existing_event.get("history_head_before"),
            "history_head_after": row.get("event_hash") or _history_head_from_rows(rows),
            "history_rows": _bounded_return_rows(rows, row),
        }
    if context.get("simulate_append_failure") is True:
        return _result_error("write_failed", context, event=event)

    prev_hash = event["history_head_before"] or ZERO_HASH
    event_hash = _event_hash(prev_hash, event)
    seq_values = [row.get("seq") for row in rows if isinstance(row.get("seq"), int)]
    row = {
        "schema_version": SCHEMA_VERSION,
        "seq": (max(seq_values) if seq_values else 0) + 1,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "timestamp": event["created_at"],
        "created_at": event["created_at"],
        "event_type": EVENT_TYPE,
        "mst_session_id": event["mst_session_id"],
        "idempotency_key": event["idempotency_key"],
        "event": event,
    }
    return {
        "status": "ok",
        "code": "appended",
        "appended": True,
        "duplicate": False,
        "mutation_performed": True,
        "event": event,
        "history_head_before": event["history_head_before"],
        "history_head_after": event_hash,
        "history_rows": _bounded_return_rows(rows, row),
    }


def append_prompt_submitted(fixture: dict[str, Any]) -> dict[str, Any]:
    context = _load_context(fixture)
    resolution = _identity_resolution(context)
    if not resolution["ok"]:
        return _result_error(str(resolution["code"]), context)

    mst_session_id = str(resolution["mst_session_id"])
    project_root_value = _safe_text(context.get("project_root"))
    project_root = Path(project_root_value).resolve() if project_root_value else None
    rows = _read_history_rows(project_root, mst_session_id) if project_root else _history_rows(context)

    if project_root and "history_head_before" not in context:
        context = dict(context)
        context["history_head_before"] = _read_current_head(project_root, mst_session_id)
    event = build_prompt_submitted_event(context)
    existing = _find_existing_prompt(rows, idempotency_key=event["idempotency_key"])
    if existing is not None:
        row, existing_event = existing
        return {
            "status": "ok",
            "code": "duplicate",
            "appended": False,
            "duplicate": True,
            "mutation_performed": False,
            "event": _sanitize_event(dict(existing_event)),
            "history_head_before": existing_event.get("history_head_before"),
            "history_head_after": row.get("event_hash") or _history_head_from_rows(rows),
            "history_rows": _bounded_return_rows(rows, row),
        }

    if context.get("simulate_append_failure") is True:
        return _result_error("write_failed", context, event=event)
    if not project_root:
        return _append_in_memory(context, event, rows)

    policy_home = _safe_text(context.get("policy_home")) or os.environ.get("MST_POLICY_HOME", "").strip()
    if policy_home:
        policy_path = Path(policy_home).expanduser().resolve()
    else:
        claude_home = Path(os.environ.get("MST_CLAUDE_HOME", str(Path.home()))).expanduser()
        policy_path = claude_home / ".claude" / "gran-maestro-policy"
    try:
        before_rows = _read_history_rows(project_root, mst_session_id)
        appended_row_status, appended_row = _append_history_event(project_root, policy_path, mst_session_id, event)
        after_rows = _read_history_rows(project_root, mst_session_id)
    except Exception:
        return _result_error("write_failed", context, event=event)

    after_existing = _find_existing_prompt(
        after_rows,
        idempotency_key=appended_row.get("event", {}).get("idempotency_key") or event["idempotency_key"],
    )
    if after_existing is None:
        return _result_error("write_failed", context, event=event)
    row, persisted_event = after_existing
    appended = appended_row_status and len(after_rows) > len(before_rows)
    if appended_row.get("event_hash") and row.get("event_hash") != appended_row.get("event_hash"):
        appended = False
    return {
        "status": "ok",
        "code": "appended" if appended else "duplicate",
        "appended": appended,
        "duplicate": not appended,
        "mutation_performed": appended,
        "event": _sanitize_event(dict(persisted_event)),
        "history_head_before": persisted_event.get("history_head_before"),
        "history_head_after": row.get("event_hash") or _history_head_from_rows(after_rows),
        "evidence_path": f".gran-maestro/sessions/{mst_session_id}/history.ndjson",
    }


def _freshness(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    resolution = _identity_resolution(context)
    source_head = _head_value(context.get("source_history_head"))
    current_head = _head_value(context.get("current_history_head"))
    if not resolution["ok"] and resolution["code"] == "mst_session_id_mismatch":
        status = "identity_mismatch"
    elif source_head is None and current_head is None:
        status = "no_history"
    elif source_head is not None and current_head is not None:
        status = "fresh" if source_head == current_head else "stale"
    else:
        status = "unknown"
    return {
        "status": status,
        "source_head": source_head,
        "current_head": current_head,
        "evidence_path": f".gran-maestro/sessions/{mst_session_id}/history.head" if mst_session_id else ".gran-maestro/sessions/history.head",
    }


def _bounded_prompt_excerpt(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    text = _safe_text(value.get("text"))
    raw_max_chars = value.get("max_chars")
    max_chars = max(1, min(MAX_EXCERPT_CHARS, int(raw_max_chars) if isinstance(raw_max_chars, int) else MAX_EXCERPT_CHARS))
    bounded_text = text[:max_chars]
    return {
        "text": bounded_text,
        "max_chars": max_chars,
        "truncated": bool(value.get("truncated")) or len(text) > max_chars,
        "omitted_bytes": value.get("omitted_bytes") if isinstance(value.get("omitted_bytes"), int) else max(0, len(text.encode("utf-8")) - len(bounded_text.encode("utf-8"))),
    }


def _safe_following_row(row: dict[str, Any], anchor_hash: str | None) -> dict[str, Any]:
    event = row.get("event") if isinstance(row.get("event"), dict) else {}
    prev_hash = row.get("prev_hash")
    event_hash = row.get("event_hash")
    return {
        "seq": row.get("seq"),
        "event_type": row.get("event_type") or event.get("event_type") or event.get("type"),
        "created_at": row.get("created_at") or row.get("timestamp") or event.get("created_at") or event.get("timestamp"),
        "timestamp": row.get("timestamp") or row.get("created_at") or event.get("timestamp") or event.get("created_at"),
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "mst_session_id": row.get("mst_session_id") or event.get("mst_session_id"),
        "head_relation": "direct_child" if anchor_hash and prev_hash == anchor_hash else "after_anchor",
    }


def _bounded_paths(context: dict[str, Any], mst_session_id: str) -> list[str]:
    paths: list[str] = [f".gran-maestro/sessions/{mst_session_id}/history.ndjson"] if mst_session_id else []
    writer_coverage = context.get("writer_coverage")
    if isinstance(writer_coverage, dict):
        writers = writer_coverage.get("writers")
        if isinstance(writers, list):
            for writer in writers:
                if not isinstance(writer, dict):
                    continue
                path = _safe_text(writer.get("evidence_path"))
                if path and path not in paths:
                    paths.append(path)
    return paths[:10]


def project_prompt_timeline(fixture: dict[str, Any]) -> dict[str, Any]:
    context = _load_context(fixture)
    resolution = _identity_resolution(context)
    mst_session_id = str(resolution["mst_session_id"] or _valid_mst_session_id(context.get("canonical_mst_session_id")) or _valid_mst_session_id(context.get("mst_session_id")) or "")
    rows = _history_rows(context)
    prompt_rows = [
        row for row in rows
        if isinstance(row.get("event"), dict)
        and (row["event"].get("event_type") or row["event"].get("type")) == EVENT_TYPE
    ]
    anchors: list[dict[str, Any]] = []
    for row in prompt_rows[:MAX_ANCHORS]:
        event = row["event"]
        row_seq = row.get("seq")
        anchor_hash = row.get("event_hash")
        following_rows = [
            candidate for candidate in rows
            if isinstance(candidate.get("seq"), int)
            and isinstance(row_seq, int)
            and candidate["seq"] > row_seq
        ]
        following_items = [_safe_following_row(candidate, anchor_hash) for candidate in following_rows[:MAX_FOLLOWING_EVENTS]]
        first_semantic = following_items[0] if following_items else None
        anchors.append(
            {
                "seq": row_seq,
                "event_hash": anchor_hash,
                "event_type": EVENT_TYPE,
                "created_at": event.get("created_at") or row.get("created_at") or row.get("timestamp"),
                "timestamp": row.get("timestamp") or event.get("created_at"),
                "prompt_digest": event.get("prompt_digest"),
                "prompt_size_bytes": event.get("prompt_size_bytes"),
                "prompt_excerpt": _bounded_prompt_excerpt(event.get("prompt_excerpt")),
                "transcript_path": event.get("transcript_path"),
                "history_head_before": event.get("history_head_before"),
                "idempotency_key": event.get("idempotency_key"),
                "source": event.get("source"),
                "head_relation": {
                    "history_head_before": event.get("history_head_before"),
                    "prompt_prev_hash": row.get("prev_hash"),
                    "prompt_event_hash": anchor_hash,
                    "matches_previous_head": event.get("history_head_before") == row.get("prev_hash"),
                },
                "following_events": {
                    "max_items": MAX_FOLLOWING_EVENTS,
                    "total": len(following_rows),
                    "truncated": len(following_rows) > MAX_FOLLOWING_EVENTS,
                    "items": following_items,
                },
                "first_semantic_event": first_semantic,
            }
        )

    following_event_types = [
        item.get("event_type")
        for anchor in anchors
        for item in anchor["following_events"]["items"]
        if isinstance(item, dict)
    ]
    generated_at = _safe_text(context.get("generated_at")) or _utc_now()
    source_head = _head_value(context.get("source_history_head")) or _history_head_from_rows(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "mst_session_id": mst_session_id,
        "canonical_mst_session_id": mst_session_id,
        "generated_at": generated_at,
        "source_head": source_head,
        "correlation_basis": list(CORRELATION_BASIS),
        "projection_freshness": _freshness(context, mst_session_id),
        "prompt_anchors": {
            "max_items": MAX_ANCHORS,
            "total": len(prompt_rows),
            "truncated": len(prompt_rows) > MAX_ANCHORS,
            "items": anchors,
        },
        "policy_block_indicators": {
            "count": sum(1 for event_type in following_event_types if event_type == "policy_block"),
            "event_types": sorted({str(event_type) for event_type in following_event_types if event_type == "policy_block"}),
        },
        "core_block_indicators": {
            "count": sum(1 for event_type in following_event_types if event_type == "core_block"),
            "event_types": sorted({str(event_type) for event_type in following_event_types if event_type == "core_block"}),
        },
        "evidence_paths": _bounded_paths(context, mst_session_id),
    }


def _context_from_hook_payload(payload: dict[str, Any], project_root: Path) -> dict[str, Any]:
    env = {
        key: value
        for key in ("MST_SESSION_ID", "MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID")
        if (value := os.environ.get(key))
    }
    context_payload = {
        key: payload.get(key)
        for key in ("mst_session_id", "session_id", "owner_session_id", "owner_pid", "owner_ppid", "pid", "ppid", "transcript_path")
        if key in payload
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": _utc_now(),
        "identity": {
            "env": env,
            "context": context_payload,
            "legacy_diagnostics": {},
        },
        "prompt": payload.get("prompt") if isinstance(payload.get("prompt"), str) else payload.get("prompt_text", ""),
        "transcript_path": _safe_text(payload.get("transcript_path")),
        "source": SOURCE,
        "project_root": str(project_root),
    }


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="prompt_correlation")
    sub = parser.add_subparsers(dest="command")
    append_parser = sub.add_parser("append-user-prompt")
    append_parser.add_argument("--project-root", default=".")
    append_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command != "append-user-prompt":
        parser.print_help(sys.stderr)
        return 2

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    project_root = Path(args.project_root).resolve()
    result = append_prompt_submitted(_context_from_hook_payload(payload, project_root))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
