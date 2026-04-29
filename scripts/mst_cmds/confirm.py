from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from hooks.lib import pre_tool_use_fast as hooklib
from scripts.mst_cmds import _common
from scripts.mst_cmds._provenance import require_user_tty


APPEND_GRANTED = "granted"
APPEND_ALREADY_GRANTED = "already_granted"
APPEND_ALREADY_CONSUMED = "already_consumed"
APPEND_EXPIRED = "expired"
APPEND_MISMATCH = "mismatch"
APPEND_MISSING = "missing"
APPEND_LEDGER_ERROR = "ledger_error"


def _project_root() -> Path:
    base_dir = _common.BASE_DIR
    if base_dir is not None:
        return base_dir.parent.resolve()
    return Path.cwd().resolve()


def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home()).expanduser()


def _sessions_dir(project_root: Path) -> Path:
    return project_root / ".gran-maestro" / "sessions"


def _candidate_session_ids(project_root: Path) -> list[str]:
    ids: list[str] = []
    env_sid = os.environ.get("MST_SESSION_ID", "").strip()
    if env_sid:
        ids.append(env_sid)

    sessions_dir = _sessions_dir(project_root)
    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.iterdir()):
            if path.is_dir() and path.name not in ids:
                ids.append(path.name)
    return ids


def _pending_records(project_root: Path, session_ids: Iterable[str]) -> list[tuple[str, dict]]:
    records: list[tuple[str, dict]] = []
    for sid in session_ids:
        clean_sid = hooklib.sanitize_session_id(sid)
        if clean_sid is None:
            continue
        payload = hooklib.read_pending_confirm(hooklib.pending_confirm_path(project_root, clean_sid))
        if isinstance(payload, dict):
            records.append((clean_sid, payload))
    return records


def _is_expired(payload: dict) -> bool:
    expires_at = hooklib.parse_utc(str(payload.get("expires_at") or ""))
    return expires_at is not None and expires_at <= hooklib.utc_now()


def _active_pending_records(project_root: Path) -> list[tuple[str, dict]]:
    active: list[tuple[str, dict]] = []
    for sid, payload in _pending_records(project_root, _candidate_session_ids(project_root)):
        if payload.get("consumed") is False and not _is_expired(payload):
            active.append((sid, payload))
    return active


def _find_pending(project_root: Path, pending_id: str) -> tuple[Optional[str], Optional[dict], str]:
    matches = []
    records = _pending_records(project_root, _candidate_session_ids(project_root))
    for sid, payload in records:
        if payload.get("id") == pending_id:
            matches.append((sid, payload))
    if not matches:
        return None, None, "pending id mismatch"
    sid, payload = matches[0]
    consumed = payload.get("consumed")
    if consumed is True:
        return sid, payload, "already consumed"
    if consumed == "expired" or _is_expired(payload):
        return sid, payload, "expired"
    if consumed is not False:
        return sid, payload, "already consumed"
    return sid, payload, ""


def _has_active_override_grant(project_root: Path, sid: str, pending_id: str) -> bool:
    grants = 0
    consumes = 0
    for event in hooklib.load_history_events(project_root, sid, {}):
        event_id = str(
            event.get("pending_id")
            or event.get("override_id")
            or event.get("confirm_id")
            or event.get("id")
            or ""
        )
        if event_id != pending_id:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "override_granted":
            grants += 1
        elif event_type == "override_consumed":
            consumes += 1
    return grants > consumes


def _append_override_granted(project_root: Path, home: Path, sid: str, payload: dict) -> tuple[int, str]:
    history_file, _, _, _ = hooklib.history_paths(project_root, home, sid)
    lock_dir = history_file.parent / "history.lock"
    pending_path = hooklib.pending_confirm_path(project_root, sid)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    if not hooklib.acquire_lock(lock_dir):
        print("history ledger mismatch: lock timeout", file=sys.stderr)
        return 2, APPEND_LEDGER_ERROR
    try:
        try:
            current = json.loads(pending_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return 1, APPEND_MISSING
        if not isinstance(current, dict):
            return 1, APPEND_MISSING
        if current.get("consumed") is not False:
            return 1, APPEND_ALREADY_CONSUMED
        if _is_expired(current):
            return 1, APPEND_EXPIRED
        if current.get("id") != payload.get("id"):
            return 1, APPEND_MISMATCH
        if current.get("tool") != payload.get("tool"):
            return 1, APPEND_MISMATCH
        if current.get("args_sha256") != payload.get("args_sha256"):
            return 1, APPEND_MISMATCH

        ok, _, _ = hooklib.verify_history(project_root, home, sid)
        if not ok:
            return 2, APPEND_LEDGER_ERROR
        pending_id = str(payload.get("id") or "")
        if pending_id and _has_active_override_grant(project_root, sid, pending_id):
            return 0, APPEND_ALREADY_GRANTED
        timestamp = hooklib.format_utc(hooklib.utc_now())
        append_status = hooklib.append_event_after_verified(
            project_root,
            home,
            sid,
            {
                "args_sha256": str(payload.get("args_sha256") or ""),
                "pending_id": str(payload.get("id") or ""),
                "timestamp": timestamp,
                "tool": str(payload.get("tool") or "unknown"),
                "type": "override_granted",
            },
        )
        if append_status:
            return append_status, APPEND_LEDGER_ERROR
        return 0, APPEND_GRANTED
    finally:
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def _cmd_confirm_list(project_root: Path) -> int:
    print("id tool args_sha256 expires_at")
    for _sid, payload in _active_pending_records(project_root):
        print(
            "{} {} {} {}".format(
                str(payload.get("id") or ""),
                str(payload.get("tool") or ""),
                str(payload.get("args_sha256") or "")[:12],
                str(payload.get("expires_at") or ""),
            )
        )
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    project_root = _project_root()
    if bool(getattr(args, "list", False)):
        return _cmd_confirm_list(project_root)

    pending_id = str(getattr(args, "pending_id", "") or "").strip()
    if not pending_id:
        print("pending id mismatch; inspect hook log with mst hook log", file=sys.stderr)
        return 1

    try:
        require_user_tty()
    except SystemExit as exc:
        print(f"{exc}; inspect hook log with mst hook log", file=sys.stderr)
        return 1

    sid, payload, error = _find_pending(project_root, pending_id)
    if error:
        print(f"{error}; inspect hook log with mst hook log", file=sys.stderr)
        return 1
    if sid is None or payload is None:
        print("pending id mismatch; inspect hook log with mst hook log", file=sys.stderr)
        return 1

    status, append_state = _append_override_granted(project_root, _home(), sid, payload)
    if append_state == APPEND_ALREADY_GRANTED:
        print(f"already granted ({pending_id})")
        return 0
    if append_state == APPEND_ALREADY_CONSUMED:
        print("already consumed; hook consumed this confirm before grant was appended", file=sys.stderr)
        return status
    if append_state == APPEND_EXPIRED:
        print("pending expired; inspect hook log with mst hook log", file=sys.stderr)
        return status
    if append_state == APPEND_MISMATCH:
        print("pending changed for a different command; inspect hook log with mst hook log", file=sys.stderr)
        return status
    if append_state == APPEND_MISSING:
        print("pending missing or corrupt; inspect hook log with mst hook log", file=sys.stderr)
        return status
    if status:
        return status
    print(
        "override granted: pending_id={} tool={} args_sha256={}".format(
            pending_id,
            str(payload.get("tool") or "unknown"),
            str(payload.get("args_sha256") or ""),
        )
    )
    return 0


def register(subparsers):
    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("pending_id", nargs="?")
    confirm.add_argument("--list", action="store_true", dest="list")
