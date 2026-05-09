from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import session as session_cmds
from scripts.mst_cmds import stop_judge
from scripts.mst_cmds._provenance import require_user_tty


ZERO_HASH = "0" * 64
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass
class LedgerDiagnosis:
    ok: bool
    reason: str
    mismatch_seq: int | None
    last_valid_seq: int
    last_valid_hash: str
    valid_lines: list[str]
    total_lines: int


@dataclass
class HistoryValidationError(Exception):
    code: str
    message: str
    details: dict


@dataclass
class HistoryReadResult:
    session_id: str
    root_mst_id: str
    history_file: Path
    local_head: Path
    mirror_head: Path
    verify_state: Path
    rows: list[dict]
    projections: list[dict]
    tail_hash: str
    tail_seq: int
    verify: dict


STATE_INCONSISTENCY_HISTORY_CODES = {
    "history_head_missing",
    "history_mirror_head_missing",
    "history_verify_missing",
    "history_head_mismatch",
    "history_mirror_head_mismatch",
    "history_verify_mismatch",
    "history_verify_stale",
}
STATE_INCONSISTENCY_PAYLOAD_KEYS = {
    "status",
    "code",
    "message",
    "failure_class",
    "terminal_event",
    "created_new_session",
    "prompt_summary_used_as_source",
    "mst_session_id",
    "root_mst_id",
    "session_id",
}


def _project_root() -> Path:
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR.parent.resolve()
    return Path.cwd().resolve()


def _policy_home() -> Path:
    explicit = os.environ.get("MST_POLICY_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    claude_home = Path(os.environ.get("MST_CLAUDE_HOME", str(Path.home()))).expanduser()
    return claude_home / ".claude" / "gran-maestro-policy"


def _allowlist_path() -> Path:
    explicit = os.environ.get("MST_POLICY_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve() / "allowlist.json"
    return Path.home().expanduser() / ".claude" / "gran-maestro-policy" / "allowlist.json"


def _project_key(project_root: Path) -> str:
    return hashlib.sha256(os.path.realpath(project_root).encode()).hexdigest()[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _sanitize_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or "/" in value or ".." in value or not SESSION_ID_RE.match(value):
        raise ValueError("invalid session_id")
    return value


def _history_paths(project_root: Path, policy_home: Path, session_id: str) -> tuple[Path, Path, Path, Path]:
    session_dir = _common.sessions_dir(project_root) / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = policy_home / "ledger-heads" / f"{session_id}.head"
    verify_state = session_dir / "history.verify"
    return history_file, local_head, mirror_head, verify_state


def _normalize_history_event(session_id: str, event: dict) -> dict:
    parsed = session_cmds.validate_mst_session_id(session_id)
    normalized = dict(event)
    normalized.pop("session_id", None)
    normalized["mst_session_id"] = parsed.mst_session_id
    existing_root = normalized.get("root_mst_id")
    if existing_root is not None and existing_root != parsed.root_mst_id:
        raise ValueError("root_mst_id mismatch")
    normalized["root_mst_id"] = parsed.root_mst_id
    existing_schema = normalized.get("schema_version")
    if existing_schema is not None and existing_schema != 1:
        raise ValueError("schema_version mismatch")
    normalized["schema_version"] = 1

    event_type = normalized.get("event_type") or normalized.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("event_type is required")
    normalized["event_type"] = event_type.strip()

    created_at = normalized.get("created_at") or normalized.get("timestamp")
    if not isinstance(created_at, str) or not created_at.strip():
        created_at = _utc_now()
    normalized["created_at"] = created_at.strip()

    idempotency_key = normalized.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        stable_event = {
            key: value
            for key, value in normalized.items()
            if key not in {"timestamp", "created_at", "idempotency_key"}
        }
        stable_json = json.dumps(stable_event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        idempotency_key = f"{parsed.mst_session_id}:{normalized['event_type']}:{_sha256_text(stable_json)}"
    normalized["idempotency_key"] = idempotency_key.strip()
    return normalized


def _history_has_idempotency_key(history_file: Path, idempotency_key: str) -> bool:
    if not idempotency_key or not history_file.is_file():
        return False
    for line in history_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = row.get("event") if isinstance(row, dict) else None
        if isinstance(event, dict) and event.get("idempotency_key") == idempotency_key:
            return True
    return False


def append_history_event(project_root: Path, policy_home: Path, session_id: str, event: dict) -> Path:
    parsed = session_cmds.validate_mst_session_id(session_id)
    history_file, local_head, mirror_head, verify_state = _history_paths(project_root, policy_home, parsed.mst_session_id)
    diagnosis = _diagnose_ledger(history_file, local_head, mirror_head)
    if not diagnosis.ok:
        raise RuntimeError(f"cannot append event to unhealthy ledger: {diagnosis.reason}")
    normalized = _normalize_history_event(parsed.mst_session_id, event)
    if _history_has_idempotency_key(history_file, normalized["idempotency_key"]):
        return history_file
    event_hash = _sha256_text(diagnosis.last_valid_hash + "\n" + _canonical_event(normalized))
    row = {
        "schema_version": normalized["schema_version"],
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": normalized["event_type"],
        "created_at": normalized["created_at"],
        "idempotency_key": normalized["idempotency_key"],
        "event": normalized,
        "event_hash": event_hash,
        "prev_hash": diagnosis.last_valid_hash,
        "seq": diagnosis.last_valid_seq + 1,
    }
    for key in ("timestamp", "tool", "args_sha256"):
        if key in normalized:
            row[key] = normalized[key]
    history_file.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    _write_heads(local_head, mirror_head, event_hash)
    _write_verify_state(verify_state, event_hash, history_file, diagnosis.last_valid_seq + 1)
    return history_file


def _history_error(code: str, message: str, *, session_id: str | None = None, **details: object) -> HistoryValidationError:
    payload = {key: value for key, value in details.items() if value is not None}
    if code in STATE_INCONSISTENCY_HISTORY_CODES:
        mst_session_id = None
        root_mst_id = None
        if session_id:
            try:
                parsed = session_cmds.validate_mst_session_id(session_id)
            except session_cmds.MstSessionIdValidationError:
                pass
            else:
                mst_session_id = parsed.mst_session_id
                root_mst_id = parsed.root_mst_id
        return HistoryValidationError(
            code,
            message,
            _common.state_inconsistency_failure_payload(
                code=code,
                message=message,
                mst_session_id=mst_session_id,
                root_mst_id=root_mst_id,
                **payload,
            ),
        )
    return HistoryValidationError(code, message, {"session_id": session_id, **payload} if session_id else payload)


def _emit_history_error(error: HistoryValidationError, *, json_mode: bool) -> None:
    if error.code in STATE_INCONSISTENCY_HISTORY_CODES:
        details = {
            key: value
            for key, value in error.details.items()
            if key not in STATE_INCONSISTENCY_PAYLOAD_KEYS
        }
        payload = _common.state_inconsistency_failure_payload(
            code=error.code,
            message=error.message,
            mst_session_id=error.details.get("mst_session_id"),
            root_mst_id=error.details.get("root_mst_id"),
            **details,
        )
    else:
        payload = {
            "status": "error",
            "code": error.code,
            "message": error.message,
            **error.details,
        }
    if json_mode:
        payload.setdefault("external_control_surface", "history")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"{error.code}: {error.message}", file=sys.stderr)


def _validate_history_session_id(raw_session_id: str) -> session_cmds.StructuredMstSessionId:
    try:
        return session_cmds.validate_mst_session_id(raw_session_id)
    except session_cmds.MstSessionIdValidationError as exc:
        raise _history_error("invalid_mst_session_id", str(exc), session_id=str(raw_session_id or "")) from exc


def _require_hash(value: object, *, field: str, session_id: str, seq: int | None = None) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise _history_error(f"history_{field}_invalid", f"invalid {field}", session_id=session_id, seq=seq)
    return value


def _event_field(row: dict, event: dict, key: str) -> object:
    if key in event:
        return event.get(key)
    return row.get(key)


def _project_history_row(
    row: dict,
    event: dict,
    *,
    parsed: session_cmds.StructuredMstSessionId,
    expected_seq: int,
    expected_prev: str,
    line_no: int,
) -> dict:
    session_id = parsed.mst_session_id
    seq = row.get("seq")
    if seq != expected_seq:
        raise _history_error("history_seq_mismatch", "seq does not match chain order", session_id=session_id, line=line_no, expected_seq=expected_seq, actual_seq=seq)
    prev_hash = _require_hash(row.get("prev_hash"), field="prev_hash", session_id=session_id, seq=expected_seq)
    if prev_hash != expected_prev:
        raise _history_error("history_prev_hash_mismatch", "prev_hash does not match previous event_hash", session_id=session_id, seq=expected_seq)
    event_hash = _require_hash(row.get("event_hash"), field="event_hash", session_id=session_id, seq=expected_seq)
    computed = _sha256_text(expected_prev + "\n" + _canonical_event(event))
    if event_hash != computed:
        raise _history_error("history_event_hash_mismatch", "event_hash does not match canonical event", session_id=session_id, seq=expected_seq)

    row_session_id = row.get("mst_session_id")
    if isinstance(row_session_id, str) and row_session_id and row_session_id != session_id:
        raise _history_error("history_row_session_mismatch", "top-level mst_session_id does not match session key", session_id=session_id, seq=expected_seq)
    event_session_id = _event_field(row, event, "mst_session_id")
    if event_session_id != session_id:
        raise _history_error("history_row_session_mismatch", "event mst_session_id does not match session key", session_id=session_id, seq=expected_seq)

    root_mst_id = _event_field(row, event, "root_mst_id")
    if root_mst_id != parsed.root_mst_id:
        raise _history_error("history_row_root_mismatch", "event root_mst_id does not match mst_session_id root", session_id=session_id, seq=expected_seq)

    schema_version = _event_field(row, event, "schema_version")
    if schema_version != 1:
        raise _history_error("history_schema_version_invalid", "schema_version must be 1", session_id=session_id, seq=expected_seq)

    event_type = _event_field(row, event, "event_type") or event.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise _history_error("history_event_type_missing", "event_type is required", session_id=session_id, seq=expected_seq)
    created_at = _event_field(row, event, "created_at") or event.get("timestamp") or row.get("timestamp")
    if not isinstance(created_at, str) or not created_at.strip():
        raise _history_error("history_created_at_missing", "created_at is required", session_id=session_id, seq=expected_seq)
    idempotency_key = _event_field(row, event, "idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise _history_error("history_idempotency_key_missing", "idempotency_key is required", session_id=session_id, seq=expected_seq)

    return {
        "schema_version": schema_version,
        "mst_session_id": session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": event_type,
        "created_at": created_at,
        "seq": expected_seq,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "idempotency_key": idempotency_key,
    }


def _read_verify_state(path: Path, *, session_id: str) -> dict:
    if not path.exists():
        raise _history_error("history_verify_missing", "history.verify is missing", session_id=session_id)
    parts = path.read_text(encoding="utf-8").strip().split("\t")
    if len(parts) != 3:
        raise _history_error("history_verify_invalid", "history.verify must contain head, fingerprint, and seq", session_id=session_id)
    head, fingerprint, raw_seq = parts
    _require_hash(head, field="verify_head", session_id=session_id)
    try:
        seq = int(raw_seq)
    except ValueError as exc:
        raise _history_error("history_verify_invalid", "history.verify seq is not an integer", session_id=session_id) from exc
    return {"event_hash": head, "fingerprint": fingerprint, "seq": seq}


def _load_validated_history(
    *,
    project_root: Path,
    policy_home: Path,
    raw_session_id: str,
    check_split: bool = True,
) -> HistoryReadResult:
    parsed = _validate_history_session_id(raw_session_id)
    session_id = parsed.mst_session_id
    history_file, local_head, mirror_head, verify_state = _history_paths(project_root, policy_home, session_id)
    session_dir = history_file.parent
    if not session_dir.is_dir():
        raise _history_error("history_session_missing", "session directory is missing", session_id=session_id)
    if not history_file.is_file():
        raise _history_error("history_file_missing", "history.ndjson is missing", session_id=session_id)

    expected_prev = ZERO_HASH
    expected_seq = 1
    raw_rows: list[dict] = []
    projections: list[dict] = []
    lines = history_file.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _history_error("history_json_invalid", f"invalid JSON line {line_no}: {exc}", session_id=session_id, line=line_no) from exc
        if not isinstance(row, dict):
            raise _history_error("history_row_invalid", "history row must be a JSON object", session_id=session_id, line=line_no)
        event = row.get("event")
        if not isinstance(event, dict):
            raise _history_error("history_event_invalid", "history row event must be a JSON object", session_id=session_id, line=line_no)
        projection = _project_history_row(
            row,
            event,
            parsed=parsed,
            expected_seq=expected_seq,
            expected_prev=expected_prev,
            line_no=line_no,
        )
        raw = dict(row)
        raw.setdefault("session_id", session_id)
        raw_rows.append(raw)
        projections.append(projection)
        expected_prev = projection["event_hash"]
        expected_seq += 1

    if not projections:
        raise _history_error("history_empty", "history.ndjson contains no events", session_id=session_id)

    tail_hash = projections[-1]["event_hash"]
    tail_seq = projections[-1]["seq"]
    local_value = _read_head(local_head)
    mirror_value = _read_head(mirror_head)
    if local_value is None:
        raise _history_error("history_head_missing", "local history.head is missing", session_id=session_id)
    if mirror_value is None:
        raise _history_error("history_mirror_head_missing", "policy mirror head is missing", session_id=session_id)
    _require_hash(local_value, field="head", session_id=session_id)
    _require_hash(mirror_value, field="mirror_head", session_id=session_id)
    if local_value != tail_hash:
        raise _history_error("history_head_mismatch", "local history.head does not match ledger tail", session_id=session_id, expected=tail_hash, actual=local_value)
    if mirror_value != tail_hash:
        raise _history_error("history_mirror_head_mismatch", "policy mirror head does not match ledger tail", session_id=session_id, expected=tail_hash, actual=mirror_value)

    verify = _read_verify_state(verify_state, session_id=session_id)
    if verify["event_hash"] != tail_hash:
        raise _history_error("history_verify_mismatch", "history.verify head does not match ledger tail", session_id=session_id, expected=tail_hash, actual=verify["event_hash"])
    current_fingerprint = _file_fingerprint(history_file)
    if verify["fingerprint"] != current_fingerprint:
        raise _history_error("history_verify_stale", "history.verify fingerprint does not match history.ndjson", session_id=session_id, expected=current_fingerprint, actual=verify["fingerprint"])
    if verify["seq"] != tail_seq:
        raise _history_error("history_verify_mismatch", "history.verify seq does not match ledger tail", session_id=session_id, expected=tail_seq, actual=verify["seq"])

    result = HistoryReadResult(
        session_id=session_id,
        root_mst_id=parsed.root_mst_id,
        history_file=history_file,
        local_head=local_head,
        mirror_head=mirror_head,
        verify_state=verify_state,
        rows=raw_rows,
        projections=projections,
        tail_hash=tail_hash,
        tail_seq=tail_seq,
        verify=verify,
    )
    if check_split:
        _detect_split_ledger(project_root=project_root, policy_home=policy_home, result=result)
    return result


def _history_summary(result: HistoryReadResult) -> dict:
    return {
        "status": "ok",
        "mst_session_id": result.session_id,
        "root_mst_id": result.root_mst_id,
        "tail": {"event_hash": result.tail_hash, "seq": result.tail_seq},
        "local_head": {"path": str(result.local_head), "event_hash": _read_head(result.local_head)},
        "mirror_head": {"path": str(result.mirror_head), "event_hash": _read_head(result.mirror_head)},
        "verify": result.verify,
        "history_path": str(result.history_file),
    }


def _history_str_field(row: dict, event: dict, *keys: str) -> str:
    for key in keys:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _history_flow_signatures(result: HistoryReadResult) -> set[tuple[str, ...]]:
    signatures: set[tuple[str, ...]] = set()
    for row in result.rows:
        event = row.get("event")
        if not isinstance(event, dict):
            continue
        flow_correlation_id = _history_str_field(row, event, "flow_correlation_id")
        if flow_correlation_id:
            signatures.add(("flow_correlation_id", result.root_mst_id, flow_correlation_id))
        parent_session = _history_str_field(row, event, "parent_mst_session_id", "parent_session_id")
        parent_invocation = _history_str_field(
            row,
            event,
            "parent_invocation_id",
            "parent_invocation",
            "invocation_parent_id",
        )
        if parent_session and parent_invocation:
            signatures.add(("parent_lineage", result.root_mst_id, parent_session, parent_invocation))
    return signatures


def _split_signature_details(signature: tuple[str, ...]) -> dict:
    kind = signature[0]
    if kind == "flow_correlation_id":
        return {"flow_correlation_id": signature[2]}
    if kind == "parent_lineage":
        return {
            "flow_correlation_id": ":".join(signature[1:]),
            "parent_mst_session_id": signature[2],
            "parent_invocation_id": signature[3],
        }
    return {"flow_correlation_id": ":".join(signature[1:])}


def _detect_split_ledger(
    *,
    project_root: Path,
    policy_home: Path,
    result: HistoryReadResult,
) -> None:
    signatures = _history_flow_signatures(result)
    if not signatures:
        return
    sessions_dir = _common.sessions_dir(project_root)
    if not sessions_dir.is_dir():
        return

    split_sessions = {result.session_id}
    matched_signature: tuple[str, ...] | None = None
    for session_dir in sorted(path for path in sessions_dir.iterdir() if path.is_dir()):
        if session_dir.name == result.session_id:
            continue
        try:
            other = _load_validated_history(
                project_root=project_root,
                policy_home=policy_home,
                raw_session_id=session_dir.name,
                check_split=False,
            )
        except HistoryValidationError:
            continue
        if other.root_mst_id != result.root_mst_id:
            continue
        overlap = signatures & _history_flow_signatures(other)
        if not overlap:
            continue
        matched_signature = sorted(overlap)[0]
        split_sessions.add(other.session_id)

    if len(split_sessions) > 1:
        details = _split_signature_details(matched_signature or sorted(signatures)[0])
        raise _history_error(
            "history_split_ledger_violation",
            "flow correlation is present in multiple mst_session_id ledgers",
            session_id=result.session_id,
            mst_session_id=result.session_id,
            root_mst_id=result.root_mst_id,
            split_sessions=sorted(split_sessions),
            **details,
        )


def _print_history_log_table(rows: list[dict]) -> None:
    print("seq | mst_session_id | root_mst_id | event_type | created_at | event_hash | idempotency_key")
    for row in rows:
        print(
            " | ".join(
                [
                    str(row["seq"]),
                    str(row["mst_session_id"]),
                    str(row["root_mst_id"]),
                    str(row["event_type"]),
                    str(row["created_at"]),
                    str(row["event_hash"]),
                    str(row["idempotency_key"]),
                ]
            )
        )


def _read_head(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _empty_allowlist() -> dict:
    return {"version": 1, "entries": []}


def _load_allowlist(path: Path) -> dict:
    if not path.exists():
        return _empty_allowlist()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_allowlist()
    if not isinstance(data, dict):
        return _empty_allowlist()
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"version": 1, "entries": [entry for entry in entries if isinstance(entry, dict)]}


def _save_allowlist(path: Path, data: dict) -> None:
    normalized = {
        "version": 1,
        "entries": data.get("entries") if isinstance(data.get("entries"), list) else [],
    }
    _atomic_write_text(path, json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def _parse_expiry(value: object) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _print_allowlist(data: dict) -> None:
    now = datetime.now(timezone.utc)
    print("ID | Tool | Args Pattern | Expires | Status")
    for entry in data.get("entries", []):
        expires_at = entry.get("expires_at")
        expiry = _parse_expiry(expires_at)
        status = "expired" if expiry is not None and now >= expiry else "active"
        print(
            " | ".join(
                [
                    str(entry.get("id") or "-"),
                    str(entry.get("tool") or "-"),
                    str(entry.get("args_pattern") or "*"),
                    str(expires_at or "never"),
                    status,
                ]
            )
        )


def _write_heads(local_head: Path, mirror_head: Path, head_hash: str) -> None:
    _atomic_write_text(local_head, head_hash + "\n")
    _atomic_write_text(mirror_head, head_hash + "\n")


def _write_verify_state(verify_state: Path, head_hash: str, history_file: Path, seq: int) -> None:
    _atomic_write_text(verify_state, f"{head_hash}\t{_file_fingerprint(history_file)}\t{seq}\n")


def _diagnose_ledger(history_file: Path, local_head: Path, mirror_head: Path) -> LedgerDiagnosis:
    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    valid_lines: list[str] = []

    lines = history_file.read_text(encoding="utf-8").splitlines() if history_file.is_file() else []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            return LedgerDiagnosis(False, f"invalid json line={line_no}: {exc}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if not isinstance(row, dict):
            return LedgerDiagnosis(False, f"row is not object line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if row.get("seq") != expected_seq:
            return LedgerDiagnosis(False, f"seq line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        if row.get("prev_hash") != expected_prev:
            return LedgerDiagnosis(False, f"prev_hash line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        event = row.get("event")
        if not isinstance(event, dict):
            return LedgerDiagnosis(False, f"event line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        computed = _sha256_text(expected_prev + "\n" + _canonical_event(event))
        if row.get("event_hash") != computed:
            return LedgerDiagnosis(False, f"event_hash line={line_no}", line_no, expected_seq - 1, last_hash, valid_lines, len(lines))
        valid_lines.append(line)
        expected_prev = computed
        last_hash = computed
        expected_seq += 1

    local_value = _read_head(local_head)
    mirror_value = _read_head(mirror_head)
    has_entries = expected_seq > 1
    if has_entries and local_value is None:
        return LedgerDiagnosis(False, "missing history.head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if has_entries and mirror_value is None:
        return LedgerDiagnosis(False, "missing home mirror head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if local_value is not None and local_value != last_hash:
        return LedgerDiagnosis(False, "history.head", None, expected_seq - 1, last_hash, valid_lines, len(lines))
    if mirror_value is not None and mirror_value != last_hash:
        return LedgerDiagnosis(False, "home mirror head", None, expected_seq - 1, last_hash, valid_lines, len(lines))

    return LedgerDiagnosis(True, "ok", None, expected_seq - 1, last_hash, valid_lines, len(lines))


def _confirm_or_abort(args: argparse.Namespace, message: str) -> bool:
    if bool(getattr(args, "yes", False)):
        return True
    answer = input(f"{message} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _read_session_history(session_dir: Path) -> list[dict]:
    history_file = session_dir / "history.ndjson"
    if not history_file.is_file():
        return []

    rows: list[dict] = []
    for line in history_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            row = dict(row)
            row.setdefault("session_id", session_dir.name)
            rows.append(row)
    return rows


def _event_timestamp(row: dict) -> str:
    event = row.get("event")
    if isinstance(event, dict):
        return str(event.get("timestamp") or row.get("timestamp") or "")
    return str(row.get("timestamp") or "")


def _event_type(row: dict) -> str:
    event = row.get("event")
    return str(event.get("type") or "") if isinstance(event, dict) else ""


def _rule_or_tool(row: dict) -> str:
    event = row.get("event")
    if not isinstance(event, dict):
        return "-"
    return str(event.get("rule_id") or event.get("tool") or event.get("tool_name") or event.get("repair_target") or "-")


def _event_note(row: dict) -> str:
    event = row.get("event")
    if not isinstance(event, dict):
        return "-"
    return str(event.get("reason") or event.get("message") or event.get("trigger") or "-")


def _print_hook_log_table(rows: list[dict]) -> None:
    print("시간 | 세션 | 이벤트 | 룰/도구 | 비고")
    for row in rows:
        print(
            " | ".join(
                [
                    _event_timestamp(row),
                    str(row.get("session_id") or "-"),
                    _event_type(row) or "-",
                    _rule_or_tool(row),
                    _event_note(row),
                ]
            )
        )


def _backup_history(history_file: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = history_file.with_name(f"{history_file.name}.bak.{timestamp}")
    suffix = 0
    while backup.exists():
        suffix += 1
        backup = history_file.with_name(f"{history_file.name}.bak.{timestamp}.{suffix}")
    shutil.copy2(history_file, backup)
    return backup


def _append_repair_event(project_root: Path, policy_home: Path, session_id: str, payload: dict) -> None:
    event = {
        "event_type": "repair_executed",
        "type": "repair_executed",
        "created_at": _utc_now(),
        **payload,
    }
    append_history_event(project_root, policy_home, session_id, event)


def _repair_session(args: argparse.Namespace) -> int:
    project_root = _project_root()
    policy_home = _policy_home()
    session_id = _sanitize_session_id(args.session)
    history_file, local_head, mirror_head, verify_state = _history_paths(project_root, policy_home, session_id)

    diagnosis = _diagnose_ledger(history_file, local_head, mirror_head)
    if diagnosis.ok:
        print(f"복구 불필요: ledger integrity OK (session={session_id})")
        return 0

    mismatch = f"seq={diagnosis.mismatch_seq}" if diagnosis.mismatch_seq is not None else diagnosis.reason
    print(f"history ledger mismatch: {mismatch}", file=sys.stderr)
    print(f"recommended truncate seq: {diagnosis.last_valid_seq}", file=sys.stderr)
    print(f"rerun: mst hook repair --session {session_id} --truncate-to {diagnosis.last_valid_seq} --yes", file=sys.stderr)

    truncate_to = getattr(args, "truncate_to", None)
    if truncate_to is None:
        return 2
    if truncate_to < 0 or truncate_to > diagnosis.last_valid_seq:
        print(f"invalid --truncate-to {truncate_to}; maximum valid seq is {diagnosis.last_valid_seq}", file=sys.stderr)
        return 2
    if not history_file.is_file():
        print(f"history file not found: {history_file}", file=sys.stderr)
        return 2
    if not _confirm_or_abort(args, f"truncate {history_file} to seq {truncate_to}?"):
        print("repair aborted", file=sys.stderr)
        return 1

    backup = _backup_history(history_file)
    retained = diagnosis.valid_lines[:truncate_to]
    _atomic_write_text(history_file, ("\n".join(retained) + "\n") if retained else "")
    head_hash = ZERO_HASH if truncate_to == 0 else json.loads(retained[-1])["event_hash"]
    _write_heads(local_head, mirror_head, head_hash)
    _write_verify_state(verify_state, head_hash, history_file, truncate_to)

    print(f"truncated session={session_id} to seq={truncate_to}")
    print(f"backup={backup}")
    print(f"mirror_head={mirror_head}")
    return 0


def _read_manifest(policy_dir: Path) -> dict:
    manifest_path = policy_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"manifest invalid: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("manifest invalid: unsupported version")
    if not isinstance(payload.get("rules"), list):
        raise ValueError("manifest invalid: rules must be a list")
    return payload


def _manifest_mismatches(policy_dir: Path, payload: dict) -> list[str]:
    errors: list[str] = []
    for item in payload.get("rules", []):
        if not isinstance(item, dict):
            errors.append("invalid manifest rule entry")
            continue
        rel = str(item.get("path") or "")
        expected = str(item.get("sha256") or "")
        if rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"invalid path: {rel}")
            continue
        rule_path = policy_dir / rel
        if not rule_path.is_file():
            errors.append(f"missing rule file: {rel}")
            continue
        actual = _sha256_file(rule_path)
        if actual != expected:
            errors.append(f"sha256 mismatch: {rel} expected={expected} actual={actual}")
    return errors


def _recalculated_manifest(policy_dir: Path) -> dict:
    rules_dir = policy_dir / "rules.d"
    rules = []
    for rule_file in sorted(rules_dir.glob("*.json")):
        rules.append(
            {
                "path": rule_file.relative_to(policy_dir).as_posix(),
                "sha256": _sha256_file(rule_file),
                "last_modified": _utc_now(),
            }
        )
    return {"version": 1, "rules": rules}


def _select_repair_event_session(project_root: Path) -> str:
    sessions_dir = _common.sessions_dir(project_root)
    candidates = sorted(path.name for path in sessions_dir.iterdir() if path.is_dir()) if sessions_dir.is_dir() else []
    return candidates[0] if len(candidates) == 1 else "manifest-repair"


def _repair_manifest(args: argparse.Namespace) -> int:
    if getattr(args, "truncate_to", None) is not None:
        print("--truncate-to is only valid with --session", file=sys.stderr)
        return 2

    project_root = _project_root()
    policy_home = _policy_home()
    policy_dir = policy_home / "projects" / _project_key(project_root)
    manifest_path = policy_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    try:
        payload = _read_manifest(policy_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors = _manifest_mismatches(policy_dir, payload)
    if not errors:
        print(f"복구 불필요: manifest sha256 OK ({manifest_path})")
        return 0

    for error in errors:
        print(error, file=sys.stderr)
    if not _confirm_or_abort(args, f"recalculate manifest {manifest_path}?"):
        print("repair aborted", file=sys.stderr)
        return 1

    new_payload = _recalculated_manifest(policy_dir)
    _atomic_write_text(manifest_path, json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n")
    os.chmod(manifest_path, 0o600)

    session_id = _select_repair_event_session(project_root)
    _append_repair_event(
        project_root,
        policy_home,
        session_id,
        {"repair_target": "manifest", "manifest_path": str(manifest_path), "trigger": "user_cli"},
    )
    print(f"manifest repaired: {manifest_path}")
    print(f"repair_event_session={session_id}")
    return 0


def cmd_hook_repair(args: argparse.Namespace) -> int:
    try:
        require_user_tty()
        if args.session:
            return _repair_session(args)
        if args.manifest:
            return _repair_manifest(args)
        print("one of --session or --manifest is required", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cmd_hook_log(args: argparse.Namespace) -> int:
    sessions_dir = _common.BASE_DIR / "sessions"
    if args.session:
        try:
            result = _load_validated_history(
                project_root=_project_root(),
                policy_home=_policy_home(),
                raw_session_id=args.session,
            )
        except HistoryValidationError as exc:
            _emit_history_error(exc, json_mode=bool(args.json))
            return 2
        rows = result.rows
    else:
        rows = []
        if sessions_dir.is_dir():
            for session_dir in sorted(path for path in sessions_dir.iterdir() if path.is_dir()):
                try:
                    result = _load_validated_history(
                        project_root=_project_root(),
                        policy_home=_policy_home(),
                        raw_session_id=session_dir.name,
                    )
                except HistoryValidationError:
                    continue
                rows.extend(result.rows)

    if args.type:
        rows = [row for row in rows if _event_type(row) == args.type]
    rows.sort(key=_event_timestamp)

    limit = max(0, int(args.limit))
    if limit:
        rows = rows[-limit:]
    else:
        rows = []

    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        _print_hook_log_table(rows)
    return 0


def cmd_history_log(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    rows = sorted(result.projections, key=lambda row: row["seq"])
    limit = max(0, int(args.limit))
    if limit:
        rows = rows[-limit:]
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        _print_history_log_table(rows)
    return 0


def cmd_history_verify(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    payload = _history_summary(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"ok session={result.session_id} seq={result.tail_seq} head={result.tail_hash}")
    return 0


def cmd_history_head(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    payload = {
        "status": "ok",
        "mst_session_id": result.session_id,
        "root_mst_id": result.root_mst_id,
        "head": {"event_hash": result.tail_hash, "seq": result.tail_seq},
        "local_head": str(result.local_head),
        "mirror_head": str(result.mirror_head),
        "verify_state": str(result.verify_state),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(result.tail_hash)
    return 0


def cmd_hook_allow(args: argparse.Namespace) -> int:
    if not (args.list or args.remove):
        try:
            require_user_tty()
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 2

    allowlist_path = _allowlist_path()
    data = _load_allowlist(allowlist_path)

    if args.list:
        _print_allowlist(data)
        return 0

    if args.remove:
        before = len(data["entries"])
        data["entries"] = [entry for entry in data["entries"] if entry.get("id") != args.remove]
        if len(data["entries"]) == before:
            print(f"Not found: {args.remove}", file=sys.stderr)
            return 1
        _save_allowlist(allowlist_path, data)
        print(f"Removed: {args.remove}")
        return 0

    if not args.tool:
        print("--tool required for add", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    expires_at = _format_utc(now + timedelta(minutes=args.expires)) if args.expires is not None else None
    entry = {
        "id": f"alw_{secrets.token_hex(4)}",
        "tool": args.tool,
        "args_pattern": args.args_pattern or "*",
        "expires_at": expires_at,
        "added_by_tty": True,
        "created_at": _format_utc(now),
    }
    data.setdefault("entries", []).append(entry)
    _save_allowlist(allowlist_path, data)
    print(f"Added: {entry['id']}")
    return 0


def cmd_hook_stop(args: argparse.Namespace) -> int:
    if getattr(args, "stop_subcommand", None) == "judge":
        return stop_judge.cmd_hook_stop_judge(args)
    print("hook stop requires a subcommand", file=sys.stderr)
    return 2


def register(subparsers):
    hook = subparsers.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="subcommand")
    repair = hook_sub.add_parser("repair")
    mode = repair.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session")
    mode.add_argument("--manifest", action="store_true")
    repair.add_argument("--truncate-to", type=int)
    repair.add_argument("--yes", action="store_true")
    repair.set_defaults(func=cmd_hook_repair)

    log = hook_sub.add_parser(
        "log",
        description=(
            "Show hook event rows as a backward-compatible subset of canonical history. "
            "DOD-005 source of truth is mst.py history log --session MST_SESSION_ID: "
            "the single mst_session_id ledger under .gran-maestro/sessions/{mst_session_id}/history.*. "
            "This command must not use PPID, Claude hook session_id, or global/default ledger fallback."
        ),
    )
    log.add_argument("--session", help="Optional mst_session_id; when provided, read only that validated session ledger.")
    log.add_argument("--type", help="Filter by hook event type.")
    log.add_argument("--limit", type=int, default=50, help="Maximum rows to print; defaults to 50.")
    log.add_argument("--json", action="store_true", help="Emit NDJSON rows.")
    log.set_defaults(func=cmd_hook_log)

    history = subparsers.add_parser(
        "history",
        description=(
            "Inspect the DOD-005 single history ledger keyed only by mst_session_id. "
            "Queries validate append-only seq/prev_hash/event_hash rows, local history.head, "
            "policy mirror head, and history.verify for the same session key; split-ledger "
            "violations and legacy fallback inputs fail closed."
        ),
    )
    history_sub = history.add_subparsers(dest="subcommand")

    history_log = history_sub.add_parser(
        "log",
        description=(
            "Read event rows from one .gran-maestro/sessions/{mst_session_id}/history.ndjson ledger. "
            "Every returned row is read-time validated for schema_version, mst_session_id, root_mst_id, "
            "event_type, created_at, seq, prev_hash, event_hash, and idempotency_key. "
            "No PPID, Claude hook session_id, owner_session_id, global hook ledger, or default history fallback is used."
        ),
    )
    history_log.add_argument("--session", required=True, help="Structured mst_session_id that selects the single canonical ledger.")
    history_log.add_argument("--limit", type=int, default=0, help="Maximum rows to print; 0 prints all validated rows.")
    history_log.add_argument("--json", action="store_true", help="Emit validated projection rows as NDJSON.")
    history_log.set_defaults(func=cmd_history_log)

    history_verify = history_sub.add_parser(
        "verify",
        description=(
            "Verify append-only head state for one mst_session_id ledger. "
            "The command compares the ledger tail seq/hash with local history.head, active policy mirror head, "
            "and history.verify for the same session key, returning structured non-success for missing, stale, mismatch, "
            "corrupt, or split-ledger violation states instead of repairing or falling back."
        ),
    )
    history_verify.add_argument("--session", required=True, help="Structured mst_session_id whose ledger head/verify state is checked.")
    history_verify.add_argument("--json", action="store_true", help="Emit the verification summary or error as JSON.")
    history_verify.set_defaults(func=cmd_history_verify)

    history_head = history_sub.add_parser(
        "head",
        description=(
            "Show the append-only head for one mst_session_id ledger after validating history.ndjson, "
            "local history.head, active policy mirror head, and history.verify. "
            "The head is session-key scoped and never resolved through legacy process/session fallback."
        ),
    )
    history_head.add_argument("--session", required=True, help="Structured mst_session_id whose canonical ledger head is shown.")
    history_head.add_argument("--json", action="store_true", help="Emit the head summary or error as JSON.")
    history_head.set_defaults(func=cmd_history_head)

    allow = hook_sub.add_parser("allow")
    allow.add_argument("tool", nargs="?")
    allow.add_argument("--args-pattern")
    allow.add_argument("--expires", type=int)
    allow.add_argument("--list", action="store_true")
    allow.add_argument("--remove")
    allow.set_defaults(func=cmd_hook_allow)

    stop = hook_sub.add_parser("stop")
    stop_sub = stop.add_subparsers(dest="stop_subcommand")
    judge = stop_sub.add_parser("judge")
    judge.add_argument("--stdin-file", required=True, help="Path to the captured Stop hook stdin payload JSON.")
    judge.add_argument(
        "--hook-timeout-ms",
        type=int,
        default=stop_judge.DEFAULT_HOOK_TIMEOUT_MS,
        help="Timeout budget passed by the shell wrapper for fail-safe diagnostics.",
    )
    judge.set_defaults(func=cmd_hook_stop)
