#!/usr/bin/env bash

MST_HISTORY_ZERO_HASH="0000000000000000000000000000000000000000000000000000000000000000"
MST_HISTORY_SHA256_BACKEND="${MST_HISTORY_SHA256_BACKEND:-}"
MST_HISTORY_VERIFIED_SESSION_ID="${MST_HISTORY_VERIFIED_SESSION_ID:-}"
MST_HISTORY_VERIFIED_HEAD="${MST_HISTORY_VERIFIED_HEAD:-}"
MST_HISTORY_VERIFIED_FINGERPRINT="${MST_HISTORY_VERIFIED_FINGERPRINT:-}"
MST_HISTORY_VERIFIED_SEQ="${MST_HISTORY_VERIFIED_SEQ:-}"

mst_history_sanitize_session_id() {
  local session_id="${1:-}"
  case "$session_id" in
    ''|*/*|*'..'*|*[!A-Za-z0-9._-]*)
      return 1
      ;;
  esac
  printf '%s\n' "$session_id"
}

mst_history_session_dir() {
  local project_root="$1" session_id="$2"
  printf '%s/.gran-maestro/sessions/%s\n' "$project_root" "$session_id"
}

mst_history_heads_dir() {
  local claude_home
  claude_home="${MST_CLAUDE_HOME:-${HOME:-}}"
  [ -n "$claude_home" ] || return 1
  printf '%s/.claude/gran-maestro-policy/ledger-heads\n' "$claude_home"
}

mst_history_sha256_backend() {
  if [ -n "$MST_HISTORY_SHA256_BACKEND" ]; then
    printf '%s\n' "$MST_HISTORY_SHA256_BACKEND"
    return 0
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    MST_HISTORY_SHA256_BACKEND="sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    MST_HISTORY_SHA256_BACKEND="shasum"
  elif command -v openssl >/dev/null 2>&1; then
    MST_HISTORY_SHA256_BACKEND="openssl"
  else
    MST_HISTORY_SHA256_BACKEND="python"
  fi

  printf '%s\n' "$MST_HISTORY_SHA256_BACKEND"
}

mst_history_sha256_text() {
  case "$(mst_history_sha256_backend)" in
    sha256sum)
      sha256sum | awk '{print $1}'
      ;;
    shasum)
      shasum -a 256 | awk '{print $1}'
      ;;
    openssl)
      openssl dgst -sha256 | awk '{print $NF}'
      ;;
    *)
      python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
      ;;
  esac
}

mst_history_canonical_json() {
  python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin),sort_keys=True,separators=(",",":")))'
}

mst_history_timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ
}

mst_history_acquire_lock() {
  local lock="$1" tries="${MST_HISTORY_LOCK_TRIES:-20}"
  while ! mkdir "$lock" 2>/dev/null; do
    sleep 0.05
    tries=$((tries - 1))
    [ "$tries" -le 0 ] && return 1
  done
  return 0
}

mst_history_release_lock() {
  rmdir "$1" 2>/dev/null || true
}

mst_history_write_head() {
  local path="$1" value="$2" tmp_path
  mkdir -p "$(dirname "$path")" || return 1
  tmp_path="${path}.tmp.$$"
  printf '%s\n' "$value" > "$tmp_path" || return 1
  mv "$tmp_path" "$path"
}

mst_history_verify_state_path() {
  printf '%s/history.verify\n' "$1"
}

mst_history_file_fingerprint() {
  local path="$1"
  if [ ! -f "$path" ]; then
    printf 'missing\n'
    return 0
  fi
  stat -f '%z:%m:%i' "$path" 2>/dev/null || return 1
}

mst_history_last_nonempty_line() {
  local path="$1"
  [ -f "$path" ] || return 0
  tail -n 1 "$path" 2>/dev/null || true
}

mst_history_extract_json_string() {
  local key="$1" json="$2"
  printf '%s\n' "$json" | sed -n "s/.*\"${key}\":\"\\([^\"]*\\)\".*/\\1/p"
}

mst_history_extract_json_number() {
  local key="$1" json="$2"
  printf '%s\n' "$json" | sed -n "s/.*\"${key}\":\\([0-9][0-9]*\\).*/\\1/p"
}

mst_history_read_head_value() {
  local path="$1" fallback="${2:-}"
  if [ -f "$path" ]; then
    tr -d '[:space:]' < "$path"
    return 0
  fi
  printf '%s\n' "$fallback"
}

mst_history_write_verify_state() {
  local session_dir="$1" session_id="$2" head_hash="$3" history_file="$4" seq="$5" state_path fingerprint tmp_path
  state_path="$(mst_history_verify_state_path "$session_dir")"
  fingerprint="$(mst_history_file_fingerprint "$history_file")" || return 1
  tmp_path="${state_path}.tmp.$$"
  printf '%s\t%s\t%s\n' "$head_hash" "$fingerprint" "$seq" > "$tmp_path" || return 1
  mv "$tmp_path" "$state_path"
  MST_HISTORY_VERIFIED_SESSION_ID="$session_id"
  MST_HISTORY_VERIFIED_HEAD="$head_hash"
  MST_HISTORY_VERIFIED_FINGERPRINT="$fingerprint"
  MST_HISTORY_VERIFIED_SEQ="$seq"
}

mst_history_fast_verify_unlocked() {
  local project_root="$1" session_id="$2"
  local session_dir history_file local_head mirror_head heads_dir state_path cached_head cached_fingerprint
  local cached_seq local_value mirror_value current_fingerprint last_line last_hash

  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  history_file="${session_dir}/history.ndjson"
  local_head="${session_dir}/history.head"
  heads_dir="$(mst_history_heads_dir)" || return 1
  mirror_head="${heads_dir}/${session_id}.head"
  state_path="$(mst_history_verify_state_path "$session_dir")"

  [ -f "$state_path" ] || return 1
  IFS=$'\t' read -r cached_head cached_fingerprint cached_seq < "$state_path" || return 1
  [ -n "$cached_head" ] || return 1
  [ -n "$cached_fingerprint" ] || return 1
  [ -n "$cached_seq" ] || return 1
  [ -f "$local_head" ] || return 1
  [ -f "$mirror_head" ] || return 1

  local_value="$(mst_history_read_head_value "$local_head")"
  mirror_value="$(mst_history_read_head_value "$mirror_head")"
  [ "$local_value" = "$mirror_value" ] || return 1
  [ "$local_value" = "$cached_head" ] || return 1

  current_fingerprint="$(mst_history_file_fingerprint "$history_file")" || return 1
  [ "$current_fingerprint" = "$cached_fingerprint" ] || return 1

  if [ "$current_fingerprint" = "missing" ]; then
    [ "$local_value" = "$MST_HISTORY_ZERO_HASH" ] || return 1
    MST_HISTORY_VERIFIED_SESSION_ID="$session_id"
    MST_HISTORY_VERIFIED_HEAD="$local_value"
    MST_HISTORY_VERIFIED_FINGERPRINT="$current_fingerprint"
    MST_HISTORY_VERIFIED_SEQ="$cached_seq"
    return 0
  fi

  last_line="$(mst_history_last_nonempty_line "$history_file")"
  [ -n "$last_line" ] || return 1
  last_hash="$(mst_history_extract_json_string "event_hash" "$last_line")"
  [ -n "$last_hash" ] || return 1
  [ "$last_hash" = "$local_value" ] || return 1
  MST_HISTORY_VERIFIED_SESSION_ID="$session_id"
  MST_HISTORY_VERIFIED_HEAD="$local_value"
  MST_HISTORY_VERIFIED_FINGERPRINT="$current_fingerprint"
  MST_HISTORY_VERIFIED_SEQ="$cached_seq"
  return 0
}

mst_history_current_seq() {
  local history_file="$1" session_id="$2"
  if [ -n "${MST_HISTORY_VERIFIED_SEQ:-}" ] && [ "${MST_HISTORY_VERIFIED_SESSION_ID:-}" = "$session_id" ]; then
    printf '%s\n' "$MST_HISTORY_VERIFIED_SEQ"
    return 0
  fi
  if [ -f "$history_file" ]; then
    wc -l < "$history_file" | tr -d ' '
    return 0
  fi
  printf '0\n'
}

mst_history_locked_state_matches_token() {
  local session_id="$1" history_file="$2" local_head="$3" mirror_head="$4"
  local local_value mirror_value current_fingerprint

  [ "${MST_HISTORY_VERIFIED_SESSION_ID:-}" = "$session_id" ] || return 1
  [ -n "${MST_HISTORY_VERIFIED_HEAD:-}" ] || return 1
  [ -n "${MST_HISTORY_VERIFIED_FINGERPRINT:-}" ] || return 1
  [ -n "${MST_HISTORY_VERIFIED_SEQ:-}" ] || return 1
  [ -f "$local_head" ] || return 1
  [ -f "$mirror_head" ] || return 1

  local_value="$(mst_history_read_head_value "$local_head")"
  mirror_value="$(mst_history_read_head_value "$mirror_head")"
  [ "$local_value" = "$mirror_value" ] || return 1
  [ "$local_value" = "$MST_HISTORY_VERIFIED_HEAD" ] || return 1

  current_fingerprint="$(mst_history_file_fingerprint "$history_file")" || return 1
  [ "$current_fingerprint" = "$MST_HISTORY_VERIFIED_FINGERPRINT" ]
}

mst_history_verify_chain_unlocked() {
  local project_root="$1" session_id="$2" session_dir history_file local_head mirror_head heads_dir
  session_id="$(mst_history_sanitize_session_id "$session_id")" || {
    printf 'history ledger mismatch: invalid session_id\n' >&2
    return 1
  }

  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  history_file="${session_dir}/history.ndjson"
  local_head="${session_dir}/history.head"
  heads_dir="$(mst_history_heads_dir)" || {
    printf 'history ledger mismatch: HOME not set\n' >&2
    return 1
  }
  mirror_head="${heads_dir}/${session_id}.head"

  if mst_history_fast_verify_unlocked "$project_root" "$session_id"; then
    return 0
  fi

  python3 - "$history_file" "$local_head" "$mirror_head" "$MST_HISTORY_ZERO_HASH" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

history_path = Path(sys.argv[1])
local_head_path = Path(sys.argv[2])
mirror_head_path = Path(sys.argv[3])
zero_hash = sys.argv[4]


def read_head(path: Path):
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def fail(message: str):
    print(f"history ledger mismatch: {message}", file=sys.stderr)
    raise SystemExit(1)


expected_prev = zero_hash
expected_seq = 1
last_hash = zero_hash

if history_path.exists():
    with history_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception as exc:
                fail(f"invalid json line={line_no}: {exc}")
            if not isinstance(row, dict):
                fail(f"row is not object line={line_no}")
            if row.get("seq") != expected_seq:
                fail(f"seq line={line_no}")
            if row.get("prev_hash") != expected_prev:
                fail(f"prev_hash line={line_no}")
            event = row.get("event")
            if not isinstance(event, dict):
                fail(f"event line={line_no}")
            canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
            computed = hashlib.sha256((expected_prev + "\n" + canonical).encode("utf-8")).hexdigest()
            if row.get("event_hash") != computed:
                fail(f"event_hash line={line_no}")
            expected_prev = computed
            last_hash = computed
            expected_seq += 1

local_head = read_head(local_head_path)
mirror_head = read_head(mirror_head_path)
has_entries = expected_seq > 1

if (
    not has_entries
    and not history_path.exists()
    and local_head is None
    and mirror_head is not None
    and mirror_head != zero_hash
):
    mirror_head_path.write_text(zero_hash + "\n", encoding="utf-8")
    mirror_head = zero_hash

if has_entries and local_head is None:
    fail("missing history.head")
if has_entries and mirror_head is None:
    fail("missing home mirror head")
if local_head is not None and local_head != last_hash:
    fail("history.head")
if mirror_head is not None and mirror_head != last_hash:
    fail("home mirror head")
PY
  if [ "$?" -eq 0 ]; then
    mst_history_write_verify_state \
      "$session_dir" \
      "$session_id" \
      "$(mst_history_read_head_value "$local_head" "$MST_HISTORY_ZERO_HASH")" \
      "$history_file" \
      "$(wc -l < "$history_file" 2>/dev/null | tr -d ' ' || printf '0')" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

mst_history_verify_chain() {
  local project_root="$1" session_id="$2" session_dir lock status
  session_id="$(mst_history_sanitize_session_id "$session_id")" || {
    printf 'history ledger mismatch: invalid session_id\n' >&2
    return 1
  }
  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  mkdir -p "$session_dir" || return 1
  lock="${session_dir}/history.lock"
  mst_history_acquire_lock "$lock" || {
    printf 'history ledger mismatch: lock timeout\n' >&2
    return 1
  }
  mst_history_verify_chain_unlocked "$project_root" "$session_id"
  status=$?
  mst_history_release_lock "$lock"
  return "$status"
}

mst_history_init_session() {
  local project_root="$1" session_id="$2" session_dir heads_dir local_head mirror_head
  [ -n "${session_id:-}" ] || return 0
  session_id="$(mst_history_sanitize_session_id "$session_id")" || return 1
  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  heads_dir="$(mst_history_heads_dir)" || return 1
  mkdir -p "$session_dir" "$heads_dir" || return 1
  local_head="${session_dir}/history.head"
  mirror_head="${heads_dir}/${session_id}.head"
  [ -f "$local_head" ] || mst_history_write_head "$local_head" "$MST_HISTORY_ZERO_HASH" || return 1
  [ -f "$mirror_head" ] || mst_history_write_head "$mirror_head" "$MST_HISTORY_ZERO_HASH" || return 1
}

mst_history_next_row() {
  local history_file="$1" prev_hash="$2" event_json="$3"
  local canonical_event event_hash seq
  canonical_event="$(printf '%s' "$event_json" | mst_history_canonical_json)" || return 1
  event_hash="$(printf '%s\n%s' "$prev_hash" "$canonical_event" | mst_history_sha256_text)" || return 1
  if [ -f "$history_file" ]; then
    seq="$(wc -l < "$history_file" | tr -d ' ')"
    case "$seq" in ''|*[!0-9]*) seq=0 ;; esac
    seq=$((seq + 1))
  else
    seq=1
  fi

  python3 - "$seq" "$prev_hash" "$event_hash" "$canonical_event" <<'PY'
import json
import sys

seq = int(sys.argv[1])
prev_hash = sys.argv[2]
event_hash = sys.argv[3]
event = json.loads(sys.argv[4])
row = {
    "seq": seq,
    "prev_hash": prev_hash,
    "event_hash": event_hash,
    "event": event,
}
for key in ("tool", "args_sha256", "timestamp"):
    if key in event:
        row[key] = event[key]
print(json.dumps(row, sort_keys=True, separators=(",", ":")))
PY
}

mst_history_append_event() {
  local project_root="$1" session_id="$2" event_json="$3"
  local session_dir history_file local_head mirror_head heads_dir lock prev_hash row event_hash seq status

  [ -n "${session_id:-}" ] || return 0
  session_id="$(mst_history_sanitize_session_id "$session_id")" || {
    printf 'history ledger mismatch: invalid session_id\n' >&2
    return 1
  }
  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  heads_dir="$(mst_history_heads_dir)" || {
    printf 'history ledger mismatch: HOME not set\n' >&2
    return 1
  }
  history_file="${session_dir}/history.ndjson"
  local_head="${session_dir}/history.head"
  mirror_head="${heads_dir}/${session_id}.head"
  lock="${session_dir}/history.lock"

  mkdir -p "$session_dir" "$heads_dir" || return 1
  mst_history_acquire_lock "$lock" || {
    printf 'history ledger mismatch: lock timeout\n' >&2
    return 1
  }

  mst_history_verify_chain_unlocked "$project_root" "$session_id"
  status=$?
  if [ "$status" -ne 0 ]; then
    mst_history_release_lock "$lock"
    return "$status"
  fi

  if [ -f "$local_head" ]; then
    prev_hash="$(mst_history_read_head_value "$local_head")"
  else
    prev_hash="$MST_HISTORY_ZERO_HASH"
  fi

  row="$(mst_history_next_row "$history_file" "$prev_hash" "$event_json")"
  status=$?
  if [ "$status" -ne 0 ]; then
    mst_history_release_lock "$lock"
    return "$status"
  fi

  printf '%s\n' "$row" >> "$history_file" || {
    mst_history_release_lock "$lock"
    return 1
  }
  event_hash="$(mst_history_extract_json_string "event_hash" "$row")" || {
    mst_history_release_lock "$lock"
    return 1
  }
  [ -n "$event_hash" ] || {
    mst_history_release_lock "$lock"
    return 1
  }
  seq="$(mst_history_extract_json_number "seq" "$row")"
  [ -n "$seq" ] || seq="$(mst_history_current_seq "$history_file")"
  mst_history_write_head "$local_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_head "$mirror_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_verify_state "$session_dir" "$session_id" "$event_hash" "$history_file" "$seq" >/dev/null 2>&1 || true

  mst_history_release_lock "$lock"
}

mst_history_append_events_batch() {
  local project_root="$1" session_id="$2"
  shift 2 || true
  local session_dir history_file local_head mirror_head heads_dir lock prev_hash rows last_row event_hash seq status

  [ "$#" -gt 0 ] || return 0
  [ -n "${session_id:-}" ] || return 0
  session_id="$(mst_history_sanitize_session_id "$session_id")" || {
    printf 'history ledger mismatch: invalid session_id\n' >&2
    return 1
  }
  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  heads_dir="$(mst_history_heads_dir)" || {
    printf 'history ledger mismatch: HOME not set\n' >&2
    return 1
  }
  history_file="${session_dir}/history.ndjson"
  local_head="${session_dir}/history.head"
  mirror_head="${heads_dir}/${session_id}.head"
  lock="${session_dir}/history.lock"

  mkdir -p "$session_dir" "$heads_dir" || return 1
  mst_history_acquire_lock "$lock" || {
    printf 'history ledger mismatch: lock timeout\n' >&2
    return 1
  }

  mst_history_verify_chain_unlocked "$project_root" "$session_id"
  status=$?
  if [ "$status" -ne 0 ]; then
    mst_history_release_lock "$lock"
    return "$status"
  fi

  prev_hash="$(mst_history_read_head_value "$local_head" "$MST_HISTORY_ZERO_HASH")"
  seq="$(mst_history_current_seq "$history_file" "$session_id")"
  case "$seq" in ''|*[!0-9]*) seq=0 ;; esac

  rows="$(python3 - "$prev_hash" "$seq" "$@" <<'PY'
import hashlib
import json
import sys

prev_hash = sys.argv[1]
seq = int(sys.argv[2])

for raw_event in sys.argv[3:]:
    event = json.loads(raw_event)
    canonical_event = json.dumps(event, sort_keys=True, separators=(",", ":"))
    event_hash = hashlib.sha256((prev_hash + "\n" + canonical_event).encode("utf-8")).hexdigest()
    seq += 1
    row = {
        "seq": seq,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "event": event,
    }
    for key in ("tool", "args_sha256", "timestamp"):
        if key in event:
            row[key] = event[key]
    print(json.dumps(row, sort_keys=True, separators=(",", ":")))
    prev_hash = event_hash
PY
)"
  status=$?
  if [ "$status" -ne 0 ] || [ -z "$rows" ]; then
    mst_history_release_lock "$lock"
    return 1
  fi

  printf '%s\n' "$rows" >> "$history_file" || {
    mst_history_release_lock "$lock"
    return 1
  }
  last_row="$(printf '%s\n' "$rows" | tail -n 1)"
  event_hash="$(mst_history_extract_json_string "event_hash" "$last_row")" || {
    mst_history_release_lock "$lock"
    return 1
  }
  [ -n "$event_hash" ] || {
    mst_history_release_lock "$lock"
    return 1
  }
  seq="$(mst_history_extract_json_number "seq" "$last_row")"
  [ -n "$seq" ] || seq="$(mst_history_current_seq "$history_file" "$session_id")"
  mst_history_write_head "$local_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_head "$mirror_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_verify_state "$session_dir" "$session_id" "$event_hash" "$history_file" "$seq" >/dev/null 2>&1 || true

  mst_history_release_lock "$lock"
}

mst_history_json_escape() {
  local value="${1-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  value="${value//$'\f'/\\f}"
  value="${value//$'\b'/\\b}"
  printf '%s' "$value"
}

mst_history_tool_call_event_json() {
  local stdin_raw="$1" timestamp args_json args_sha tool tool_escaped
  timestamp="$(mst_history_timestamp)"
  if [ -n "${MST_HOOK_TOOL_INPUT_CANONICAL:-}" ]; then
    args_json="$MST_HOOK_TOOL_INPUT_CANONICAL"
  else
    args_json="$(MST_HOOK_STDIN_RAW="$stdin_raw" python3 - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}
print(json.dumps(tool_input, sort_keys=True, separators=(",", ":")))
PY
)" || return 1
  fi
  args_sha="$(printf '%s' "$args_json" | mst_history_sha256_text)" || return 1
  if [ -n "${MST_HOOK_TOOL_NAME:-}" ]; then
    tool="${MST_HOOK_TOOL_NAME}"
  else
    tool="$(MST_HOOK_STDIN_RAW="$stdin_raw" python3 - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
tool = payload.get("tool_name")
if not isinstance(tool, str) or not tool.strip():
    tool = "unknown"
print(tool.strip())
PY
)" || return 1
  fi
  tool_escaped="$(mst_history_json_escape "${tool:-unknown}")"
  printf '{"args_sha256":"%s","timestamp":"%s","tool":"%s","type":"tool_call"}\n' "$args_sha" "$timestamp" "$tool_escaped"
}

mst_history_append_tool_call() {
  local project_root="$1" session_id="$2" stdin_raw="$3"
  local session_dir history_file local_head mirror_head heads_dir lock prev_hash event_json event_hash row status
  local timestamp args_json args_sha tool tool_escaped
  [ -n "${session_id:-}" ] || return 0
  session_id="$(mst_history_sanitize_session_id "$session_id")" || {
    printf 'history ledger mismatch: invalid session_id\n' >&2
    return 1
  }

  timestamp="$(mst_history_timestamp)"
  if [ -n "${MST_HOOK_TOOL_INPUT_CANONICAL:-}" ]; then
    args_json="$MST_HOOK_TOOL_INPUT_CANONICAL"
  else
    args_json="$(MST_HOOK_STDIN_RAW="$stdin_raw" python3 - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}
print(json.dumps(tool_input, sort_keys=True, separators=(",", ":")))
PY
)" || return 1
  fi
  args_sha="$(printf '%s' "$args_json" | mst_history_sha256_text)" || return 1
  tool="${MST_HOOK_TOOL_NAME:-unknown}"
  [ -n "$tool" ] || tool="unknown"
  tool_escaped="$(mst_history_json_escape "$tool")"
  event_json="$(printf '{"args_sha256":"%s","timestamp":"%s","tool":"%s","type":"tool_call"}' "$args_sha" "$timestamp" "$tool_escaped")"

  session_dir="$(mst_history_session_dir "$project_root" "$session_id")"
  heads_dir="$(mst_history_heads_dir)" || {
    printf 'history ledger mismatch: HOME not set\n' >&2
    return 1
  }
  history_file="${session_dir}/history.ndjson"
  local_head="${session_dir}/history.head"
  mirror_head="${heads_dir}/${session_id}.head"
  lock="${session_dir}/history.lock"

  mkdir -p "$session_dir" "$heads_dir" || return 1
  mst_history_acquire_lock "$lock" || {
    printf 'history ledger mismatch: lock timeout\n' >&2
    return 1
  }

  if ! mst_history_locked_state_matches_token "$session_id" "$history_file" "$local_head" "$mirror_head"; then
    mst_history_verify_chain_unlocked "$project_root" "$session_id"
    status=$?
    if [ "$status" -ne 0 ]; then
      mst_history_release_lock "$lock"
      return "$status"
    fi
  fi

  prev_hash="$(mst_history_read_head_value "$local_head" "$MST_HISTORY_ZERO_HASH")"
  event_hash="$(printf '%s\n%s' "$prev_hash" "$event_json" | mst_history_sha256_text)" || {
    mst_history_release_lock "$lock"
    return 1
  }

  status="$(mst_history_current_seq "$history_file" "$session_id")"
  case "$status" in ''|*[!0-9]*) status=0 ;; esac
  status=$((status + 1))

  row="$(printf '{"args_sha256":"%s","event":%s,"event_hash":"%s","prev_hash":"%s","seq":%s,"timestamp":"%s","tool":"%s"}' \
    "$args_sha" "$event_json" "$event_hash" "$prev_hash" "$status" "$timestamp" "$tool_escaped")"

  printf '%s\n' "$row" >> "$history_file" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_head "$local_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_head "$mirror_head" "$event_hash" || {
    mst_history_release_lock "$lock"
    return 1
  }
  mst_history_write_verify_state "$session_dir" "$session_id" "$event_hash" "$history_file" "$status" >/dev/null 2>&1 || true

  mst_history_release_lock "$lock"
}

mst_history_verify_or_block() {
  local project_root="$1" session_id="$2"
  [ -n "${session_id:-}" ] || return 0
  mst_history_verify_chain "$project_root" "$session_id" || return 2
}
