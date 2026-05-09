#!/usr/bin/env bash

if [ -n "${MST_SESSION_IDENTITY_BASH_SOURCED:-}" ]; then
  return 0
fi
MST_SESSION_IDENTITY_BASH_SOURCED=1

MST_RESOLVED_CANONICAL_SESSION_ID=""

mst_is_structured_mst_session_id() {
  local value="${1:-}"
  case "$value" in
    ''|*/*|*'..'*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
  [[ "$value" =~ ^MST-[A-Z][A-Z0-9]*-[0-9]+-[0-9]{8}T[0-9]{9}Z-[a-z0-9]{8,}$ ]]
}

mst_extract_stdin_mst_session_id_literal() {
  local raw="$1" rest value
  case "$raw" in
    *\"mst_session_id\"*)
      rest="${raw#*\"mst_session_id\"}"
      rest="${rest#*:}"
      rest="${rest#*\"}"
      value="${rest%%\"*}"
      value="${value//$'\n'/}"
      value="${value//$'\r'/}"
      value="${value//$'\t'/}"
      case "$value" in
        ""|*[!A-Za-z0-9_-]*) return 0 ;;
      esac
      if mst_is_structured_mst_session_id "$value"; then
        printf '%s\n' "$value"
      fi
      ;;
  esac
}

mst_resolve_canonical_mst_session_id() {
  local hook_name="$1" stdin_policy="$2" stdin_raw="$3"
  local env_raw="${MST_SESSION_ID:-}" env_id="" stdin_id=""

  MST_RESOLVED_CANONICAL_SESSION_ID=""
  if [ -n "$env_raw" ] && mst_is_structured_mst_session_id "$env_raw"; then
    env_id="$env_raw"
  fi
  stdin_id="$(mst_extract_stdin_mst_session_id_literal "$stdin_raw" || true)"

  if [ -n "$env_id" ] && [ -n "$stdin_id" ] && [ "$env_id" != "$stdin_id" ]; then
    printf '[%s] error: mst_session_id mismatch: env:MST_SESSION_ID=%s stdin:mst_session_id=%s\n' "$hook_name" "$env_id" "$stdin_id" >&2
    return 1
  fi
  if [ -n "$env_raw" ] && [ -z "$env_id" ]; then
    printf '[%s] diagnostic: ignoring invalid MST_SESSION_ID; no canonical parent mst_session_id.\n' "$hook_name" >&2
    return 2
  fi
  if [ -n "$env_id" ]; then
    MST_RESOLVED_CANONICAL_SESSION_ID="$env_id"
    return 0
  fi
  if [ -n "$stdin_id" ]; then
    case "$stdin_policy" in
      allow-stdin-without-env)
        MST_RESOLVED_CANONICAL_SESSION_ID="$stdin_id"
        return 0
        ;;
      require-env-for-stdin)
        printf '[%s] diagnostic: structured hook stdin mst_session_id ignored without inherited MST_SESSION_ID.\n' "$hook_name" >&2
        return 2
        ;;
    esac
  fi

  printf '[%s] diagnostic: missing canonical parent MST_SESSION_ID/mst_session_id; no hook identity mutation.\n' "$hook_name" >&2
  return 2
}

mst_warn_legacy_session_id_mismatch_once() {
  local project_root="$1" mst_tmp="$2" stdin_raw="$3" hook_name="$4" ppid_value="${5:-}" stdin_digest="${6:-}" snapshot_lookup_sid="${7:-}"
  MST_HOOK_STDIN_RAW="$stdin_raw" python3 - "$project_root" "$mst_tmp" "$hook_name" "$ppid_value" "$stdin_digest" "$snapshot_lookup_sid" <<'PY' || true
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SAFE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TERMINAL_REQUEST = {"done", "completed", "accepted", "cancelled"}
TERMINAL_PLAN = {"done", "completed", "cancelled"}


def safe_text(value):
    text = str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    return text


def safe_session_id(value):
    text = safe_text(value)
    return "" if not text or "/" in text or ".." in text or not SAFE_RE.fullmatch(text) else text


def flow_safe_session_id(value):
    cleaned = []
    for char in str(value or ""):
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "unknown"


def load_json(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def snapshot_session_id(snapshot_path):
    payload = load_json(snapshot_path)
    if payload:
        for key in ("session_id", "sessionId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return snapshot_path.parent.name.strip()


def durable_owner_session_id(project_root):
    base_dir = project_root / ".gran-maestro"
    values = []

    def add_owner(path, terminal_statuses=None, require_active=False):
        payload = load_json(path)
        if not payload:
            return
        status = str(payload.get("status") or "").strip().lower()
        if terminal_statuses is not None and status in terminal_statuses:
            return
        if require_active and status != "active":
            return
        owner = payload.get("owner_session_id")
        if isinstance(owner, str) and owner.strip():
            values.append(owner.strip())

    for path in sorted((base_dir / "requests").glob("REQ-*/request.json")):
        add_owner(path, TERMINAL_REQUEST)
    for path in sorted((base_dir / "plans").glob("PLN-*/plan.json")):
        add_owner(path, TERMINAL_PLAN)
    for path in sorted((base_dir / "agile").glob("AGI-*/session.json")):
        add_owner(path, require_active=True)

    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else ""


def append_flow_event(project_root, session_id, data):
    path = project_root / ".gran-maestro" / "state" / flow_safe_session_id(session_id) / "flow-detail.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "event_type": "session_id_mismatch",
        "session_id": flow_safe_session_id(session_id),
        "data": data,
    }
    with path.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def main():
    project_root = Path(sys.argv[1]).resolve()
    mst_tmp = Path(sys.argv[2])
    hook_name = safe_text(sys.argv[3]) or "mst-hook"
    ppid_value = safe_text(sys.argv[4])
    stdin_digest = safe_text(sys.argv[5])
    snapshot_lookup_sid = safe_session_id(sys.argv[6])

    try:
        payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return

    stdin_sid = safe_session_id(payload.get("session_id"))
    if not stdin_sid:
        return

    state_root = project_root / ".gran-maestro" / "state"
    snapshot_path = state_root / stdin_sid / "snapshot.json"
    if not snapshot_path.is_file() and snapshot_lookup_sid:
        fallback_snapshot = state_root / snapshot_lookup_sid / "snapshot.json"
        if fallback_snapshot.is_file():
            snapshot_path = fallback_snapshot
    if not snapshot_path.is_file():
        return

    durable_sid = durable_owner_session_id(project_root)
    if not durable_sid:
        return

    snapshot_sid = snapshot_session_id(snapshot_path)
    if not snapshot_sid:
        return
    if stdin_sid == snapshot_sid and stdin_sid == durable_sid:
        return

    mst_tmp.mkdir(parents=True, exist_ok=True)
    sentinel = mst_tmp / f"mst-mismatch-warn-{ppid_value or 'unknown'}-{stdin_sid}.flag"
    try:
        fd = os.open(str(sentinel), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
    except FileExistsError:
        return
    except Exception:
        return

    data = {
        "stdin_sid": stdin_sid,
        "snapshot_sid": snapshot_sid,
        "durable_sid": durable_sid,
        "hook": hook_name,
    }
    if ppid_value:
        data["ppid"] = ppid_value
    if stdin_digest:
        data["stdin_digest"] = stdin_digest

    print(
        f"[session-id mismatch] stdin={safe_text(stdin_sid)} snapshot={safe_text(snapshot_sid)} durable={safe_text(durable_sid)} hook={safe_text(hook_name)}",
        file=sys.stderr,
    )
    append_flow_event(project_root, stdin_sid, data)


try:
    main()
except Exception:
    pass
PY
}
