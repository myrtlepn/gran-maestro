#!/usr/bin/env bash
set -euo pipefail

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="$PWD" ;;
esac
case "$script_dir" in
  /*) ;;
  *) script_dir="$(cd "$script_dir" && pwd)" ;;
esac

_mst_hooks_dir_is_valid() {
  local dir="$1" parent
  case "$dir" in
    *'${CLAUDE_PLUGIN_ROOT}'*) return 1 ;;
    */.claude/plugins/cache/*/hooks) return 0 ;;
    */.claude/plugins/marketplaces/*/hooks) return 0 ;;
  esac
  if [ -f "$dir/lib/sha256.bash" ]; then
    return 0
  fi
  case "$dir" in
    */.claude/hooks)
      parent="${dir%/.claude/hooks}"
      [ -d "$parent/.gran-maestro" ] && return 0
      ;;
    */hooks)
      parent="${dir%/hooks}"
      { [ -d "$parent/.gran-maestro" ] || [ -e "$parent/.git" ]; } && return 0
      if [ -n "${BATS_TEST_TMPDIR:-}" ]; then
        case "$dir" in
          "$BATS_TEST_TMPDIR"/master-baseline/hooks) return 0 ;;
        esac
      fi
      ;;
  esac
  return 1
}

case "$script_dir" in
  *'${CLAUDE_PLUGIN_ROOT}'*)
    echo "[mst-hook] warning: unexpected execution path. Possible \${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open." >&2
    exit 0
    ;;
esac

if [ ! -f "$script_dir/lib/sha256.bash" ] && ! _mst_hooks_dir_is_valid "$script_dir"; then
  echo "[mst-hook] warning: unexpected execution path. Possible \${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open." >&2
  exit 0
fi

resolve_project_root() {
  local git_top candidate parent
  git_top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

  if [ -f "${git_top}/.git" ]; then
    candidate="$git_top"
    while [ -n "$candidate" ] && [ "$candidate" != "/" ]; do
      if [ -d "${candidate}/.gran-maestro" ] && [ -e "${candidate}/.git" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      parent="$(dirname "$candidate")"
      if [ "$parent" = "$candidate" ]; then
        break
      fi
      candidate="$parent"
    done
  fi

  printf '%s\n' "$git_top"
}

PROJECT_ROOT="$(resolve_project_root)"
MST_TMP="${PROJECT_ROOT}/.gran-maestro/tmp"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"
BOUNDARY_LOG_FILE="${PROJECT_ROOT}/.gran-maestro/logs/boundary-guard.log"
HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
mkdir -p "$MST_TMP"

STDIN_RAW="$(cat || true)"
MST_LEDGER_HOOK_EVENT="PreToolUse"
if [ -f "${script_dir}/lib/ledger.bash" ]; then
  # shellcheck source=/dev/null
  source "${script_dir}/lib/ledger.bash" 2>/dev/null || true
fi
if declare -F emit_ledger_start >/dev/null 2>&1 && declare -F emit_ledger_complete >/dev/null 2>&1; then
  emit_ledger_start "$MST_LEDGER_HOOK_EVENT" || true
  _mst_ledger_complete_once() {
    local status="${1:-$?}"
    [ "${MST_LEDGER_COMPLETED:-0}" = "1" ] && return 0
    MST_LEDGER_COMPLETED=1
    emit_ledger_complete "$MST_LEDGER_HOOK_EVENT" "$status" || true
  }
  trap '_mst_ledger_exit_code=$?; _mst_ledger_complete_once "$_mst_ledger_exit_code"; exit "$_mst_ledger_exit_code"' EXIT
fi

HOOK_DIR="$script_dir"

if [[ ! "$STDIN_RAW" =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"Skill\" ]]; then
  if declare -F _mst_ledger_complete_once >/dev/null 2>&1; then
    _mst_ledger_complete_once 0
    trap - EXIT
  fi
  exec python3 "${HOOK_DIR}/lib/pre_tool_use_fast.py" "$PROJECT_ROOT" <<<"$STDIN_RAW"
fi

parse_hook_payload() {
  MST_HOOK_STDIN_RAW="$STDIN_RAW" python3 - <<'PY' 2>/dev/null || printf '\t\t\t\t\t{}\t\n'
import hashlib
import json
import os

raw = os.environ.get("MST_HOOK_STDIN_RAW", "")
try:
    payload = json.loads(raw or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}

def clean(value):
    if not isinstance(value, str):
        return ""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()

session_id = clean(payload.get("session_id"))
tool_name = clean(payload.get("tool_name"))
file_path = clean(tool_input.get("file_path") or tool_input.get("path"))
command = clean(tool_input.get("command"))
skill_name = ""
for key in ("skill_name", "skill", "name"):
    value = tool_input.get(key)
    if isinstance(value, str) and value.strip():
        skill_name = clean(value)
        break

args_value = tool_input.get("args")
if isinstance(args_value, str):
    args_text = clean(args_value)
else:
    try:
        args_text = clean(json.dumps(args_value, ensure_ascii=False))
    except Exception:
        args_text = clean(str(args_value or ""))

tool_input_canonical = json.dumps(tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
stdin_digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()

print(
    "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
        session_id,
        tool_name,
        file_path,
        command,
        skill_name,
        args_text,
        tool_input_canonical,
        stdin_digest,
    )
)
PY
}

# T02: 정책 무결성 (sha256 + rule engine + hardcoded core preflight)
if [ -f "${HOOK_DIR}/lib/sha256.bash" ]; then
  # shellcheck source=/dev/null
  source "${HOOK_DIR}/lib/sha256.bash"
fi
HOOK_PAYLOAD_INFO="$(parse_hook_payload)"
SESSION_ID="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f1)"
MST_HOOK_TOOL_NAME="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f2)"
MST_HOOK_FILE_PATH="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f3)"
MST_HOOK_COMMAND="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f4)"
MST_HOOK_SKILL_NAME="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f5)"
MST_HOOK_ARGS_TEXT="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f6)"
MST_HOOK_TOOL_INPUT_CANONICAL="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f7)"
MST_HOOK_STDIN_DIGEST="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f8)"
export MST_HOOK_TOOL_NAME MST_HOOK_FILE_PATH MST_HOOK_COMMAND MST_HOOK_SKILL_NAME
export MST_HOOK_ARGS_TEXT MST_HOOK_TOOL_INPUT_CANONICAL MST_HOOK_STDIN_DIGEST
if [ -f "${HOOK_DIR}/lib/rule_engine.bash" ]; then
  # shellcheck source=/dev/null
  source "${HOOK_DIR}/lib/rule_engine.bash"
fi

# T01: history ledger (verify + append-on-exit)
resolve_history_lib() {
  local script_dir candidate
  script_dir="$HOOK_DIR"

  for candidate in \
    "${script_dir}/lib/history.bash" \
    "$(cd "$script_dir/.." && pwd)/hooks/lib/history.bash" \
    "$(cd "$script_dir/../.." && pwd)/hooks/lib/history.bash" \
    "${PROJECT_ROOT}/hooks/lib/history.bash"; do
    if [ -f "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

HISTORY_LIB="$(resolve_history_lib || true)"
if [ -z "$HISTORY_LIB" ]; then
  echo "[mst-pre-tool-use] history ledger mismatch: missing history library" >&2
  exit 2
fi
source "$HISTORY_LIB"


resolve_mst_script() {
  local script_dir candidate
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  candidate="$(cd "$script_dir/.." && pwd)/scripts/mst.py"
  if [ -f "$candidate" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  candidate="$(cd "$script_dir/../.." && pwd)/scripts/mst.py"
  if [ -f "$candidate" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  printf '%s\n' "${PROJECT_ROOT}/scripts/mst.py"
}

MST_SCRIPT="$(resolve_mst_script)"

resolve_repo_script() {
  local script_name="$1"
  local script_dir candidate
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  candidate="$(cd "$script_dir/.." && pwd)/scripts/$script_name"
  if [ -f "$candidate" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  candidate="$(cd "$script_dir/../.." && pwd)/scripts/$script_name"
  if [ -f "$candidate" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  printf '%s\n' "${PROJECT_ROOT}/scripts/$script_name"
}

FLOW_LOGGER_SCRIPT="$(resolve_repo_script "_flow_logger.py")"

debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
}

sanitize_log_value() {
  local value="${1:-}"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  value="${value//$'\t'/ }"
  printf '%s' "$value"
}

warn_helper_failed() {
  local helper="$1"
  local status="${2:-1}"
  local detail="${3:-}"

  helper="$(sanitize_log_value "$helper")"
  status="$(sanitize_log_value "$status")"
  detail="$(sanitize_log_value "$detail")"
  if [ -n "$detail" ]; then
    printf '[mst-pre-tool-use] helper_failed helper=%s exit=%s %s\n' "$helper" "$status" "$detail" >&2
  else
    printf '[mst-pre-tool-use] helper_failed helper=%s exit=%s\n' "$helper" "$status" >&2
  fi
}

SNAPSHOT_PATH="${PROJECT_ROOT}/.gran-maestro/state/${SESSION_ID:-unknown}/snapshot.json"
STDIN_DIGEST="${MST_HOOK_STDIN_DIGEST:-}"

if ! mst_history_verify_or_block "$PROJECT_ROOT" "${SESSION_ID:-}"; then
  exit 2
fi

if declare -F gm_policy_preflight >/dev/null 2>&1; then
  gm_policy_preflight
fi

HISTORY_APPEND_ENABLED=1
append_history_on_exit() {
  local status=$?
  trap - EXIT
  if [ "${HISTORY_APPEND_ENABLED:-0}" = "1" ] && [ "$status" -ne 2 ]; then
    if ! mst_history_append_tool_call "$PROJECT_ROOT" "${SESSION_ID:-}" "$STDIN_RAW"; then
      echo "[mst-pre-tool-use] history ledger mismatch: append failed" >&2
      status=2
    fi
  fi
  if declare -F _mst_ledger_complete_once >/dev/null 2>&1; then
    _mst_ledger_complete_once "$status"
  fi
  exit "$status"
}
trap append_history_on_exit EXIT

append_flow_event() {
  local event_type="$1"
  local data="$2"
  local status

  if [ ! -f "$FLOW_LOGGER_SCRIPT" ]; then
    warn_helper_failed "flow_logger" "127" "missing path=$(sanitize_log_value "$FLOW_LOGGER_SCRIPT")"
    return 0
  fi

  if python3 "$FLOW_LOGGER_SCRIPT" append \
    --project-root "$PROJECT_ROOT" \
    --session-id "${SESSION_ID:-unknown}" \
    --event-type "$event_type" \
    --data "$data" \
    --snapshot-path "${SNAPSHOT_PATH:-}" \
    --stdin-digest "${STDIN_DIGEST:-}" \
    --ppid "$PPID" >/dev/null 2>&1; then
    return 0
  fi

  status=$?
  warn_helper_failed "flow_logger" "$status" "event_type=$(sanitize_log_value "$event_type")"
  return 0
}

resolve_durable_owner_session_id() {
  python3 - "$PROJECT_ROOT" <<'PY'
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
base_dir = project_root / ".gran-maestro"
request_terminal = {"done", "completed", "accepted", "cancelled"}
plan_terminal = {"done", "completed", "cancelled"}
values = []


def add_owner(path, terminal_statuses=None, require_active=False):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    status = str(payload.get("status") or "").strip().lower()
    if terminal_statuses is not None and status in terminal_statuses:
        return
    if require_active and status != "active":
        return

    owner_session_id = payload.get("owner_session_id")
    if isinstance(owner_session_id, str) and owner_session_id.strip():
        values.append(owner_session_id.strip())


for path in sorted((base_dir / "requests").glob("REQ-*/request.json")):
    add_owner(path, request_terminal)

for path in sorted((base_dir / "plans").glob("PLN-*/plan.json")):
    add_owner(path, plan_terminal)

for path in sorted((base_dir / "agile").glob("AGI-*/session.json")):
    add_owner(path, require_active=True)

unique = []
for value in values:
    if value not in unique:
        unique.append(value)

if len(unique) == 1:
    print(unique[0])
    raise SystemExit(0)
if not unique:
    raise SystemExit(2)
raise SystemExit(3)
PY
}

warn_session_id_mismatch_once_if_any() {
  local durable_session_id durable_exit sentinel check_output check_status verdict stdin_sid snapshot_sid durable_sid data

  [ -n "${SESSION_ID:-}" ] || return 0
  sentinel="${MST_TMP}/mst-mismatch-warn-${PPID}-${SESSION_ID}.flag"
  if [ -f "$sentinel" ]; then
    return 0
  fi
  if [ ! -e "${PROJECT_ROOT}/.gran-maestro/requests" ] && [ ! -e "${PROJECT_ROOT}/.gran-maestro/plans" ] && [ ! -e "${PROJECT_ROOT}/.gran-maestro/agile" ]; then
    return 0
  fi

  durable_exit=0
  set +e
  durable_session_id="$(resolve_durable_owner_session_id)"
  durable_exit=$?
  set -e
  if [ "$durable_exit" -ne 0 ]; then
    return 0
  fi

  check_status=0
  set +e
  check_output="$(MST_HOOK_STDIN_RAW="$STDIN_RAW" python3 - "${SNAPSHOT_PATH:-}" "$durable_session_id" "mst-pre-tool-use" <<'PY'
import json
import os
import sys
from pathlib import Path

snapshot_path = Path(sys.argv[1]) if sys.argv[1] else None
durable_sid = str(sys.argv[2] or "").strip()
hook_name = str(sys.argv[3] or "").strip()


def emit_skip():
    print("SKIP")


try:
    payload = json.loads(os.environ.get("MST_HOOK_STDIN_RAW", "") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

stdin_sid = payload.get("session_id")
stdin_sid = stdin_sid.strip() if isinstance(stdin_sid, str) else ""
if not stdin_sid or not durable_sid or snapshot_path is None or not snapshot_path.is_file():
    emit_skip()
    raise SystemExit(0)

snapshot_sid = ""
try:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
except Exception:
    snapshot = {}
if isinstance(snapshot, dict):
    for key in ("session_id", "sessionId"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            snapshot_sid = value.strip()
            break
if not snapshot_sid:
    snapshot_sid = snapshot_path.parent.name.strip()

if not snapshot_sid:
    emit_skip()
    raise SystemExit(0)

if len({stdin_sid, snapshot_sid, durable_sid}) == 1:
    emit_skip()
    raise SystemExit(0)

data = {
    "stdin_sid": stdin_sid,
    "snapshot_sid": snapshot_sid,
    "durable_sid": durable_sid,
    "hook": hook_name,
}
print(
    "MISMATCH\t{}\t{}\t{}\t{}".format(
        stdin_sid,
        snapshot_sid,
        durable_sid,
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
)
PY
)"
  check_status=$?
  set -e

  if [ "$check_status" -ne 0 ]; then
    printf '[mst-pre-tool-use] warn: session_id_mismatch_check_failed exit=%s\n' "$(sanitize_log_value "$check_status")" >&2
    return 0
  fi

  verdict="$(printf '%s' "$check_output" | cut -f1)"
  if [ "$verdict" != "MISMATCH" ]; then
    return 0
  fi

  if ! ( set -C; : > "$sentinel" ) 2>/dev/null; then
    return 0
  fi

  stdin_sid="$(printf '%s' "$check_output" | cut -f2)"
  snapshot_sid="$(printf '%s' "$check_output" | cut -f3)"
  durable_sid="$(printf '%s' "$check_output" | cut -f4)"
  data="$(printf '%s' "$check_output" | cut -f5-)"

  printf '[session-id mismatch] stdin=%s snapshot=%s durable=%s hook=mst-pre-tool-use\n' \
    "$(sanitize_log_value "$stdin_sid")" \
    "$(sanitize_log_value "$snapshot_sid")" \
    "$(sanitize_log_value "$durable_sid")" >&2
  append_flow_event "session_id_mismatch" "$data"
}

log_boundary_event() {
  local event_type="${1:-event}"
  local task_id="${2:-unknown}"
  local result="${3:-unknown}"
  local message="${4:-}"
  local ts log_dir

  event_type="${event_type//$'\n'/ }"
  task_id="${task_id//$'\n'/ }"
  result="${result//$'\n'/ }"
  message="${message//$'\n'/ }"
  event_type="${event_type//$'\r'/ }"
  task_id="${task_id//$'\r'/ }"
  result="${result//$'\r'/ }"
  message="${message//$'\r'/ }"

  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +%FT%TZ)"
  log_dir="$(dirname "$BOUNDARY_LOG_FILE")"
  mkdir -p "$log_dir" 2>/dev/null || return 0
  printf '%s | %s | %s | %s | %s | %s\n' \
    "$ts" "$HOOK_NAME" "$event_type" "$task_id" "$result" "$message" \
    >> "$BOUNDARY_LOG_FILE" 2>/dev/null || true
}

emit_block_json() {
  local reason="$1"
  python3 - "$reason" <<'PYJSON'
import json
import sys

print(json.dumps({"decision": "block", "reason": sys.argv[1]}, ensure_ascii=False))
PYJSON
}

parse_hook_info() {
  local req_id="" should_check="false"
  if [[ "${MST_HOOK_ARGS_TEXT:-}" =~ (REQ-[0-9]+) ]]; then
    req_id="${BASH_REMATCH[1]}"
  fi
  if [ "${MST_HOOK_TOOL_NAME:-}" = "Skill" ] && { [ "${MST_HOOK_SKILL_NAME:-}" = "mst:approve" ] || [ "${MST_HOOK_SKILL_NAME:-}" = "/mst:approve" ]; } && [ -n "$req_id" ]; then
    should_check="true"
  fi
  printf '%s\t%s\t%s\t%s\n' "$should_check" "${MST_HOOK_TOOL_NAME:-}" "${MST_HOOK_SKILL_NAME:-}" "$req_id"
}

run_boundary_check() {
  local req_id="$1" phase="$2"
  local output status
  set +e
  output="$(cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree check-boundary --req "$req_id" --phase "$phase" --ppid "$PPID")"
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    debug_log "boundary_check_nonzero" "phase=$phase req=$req_id status=$status"
  fi
  printf '%s\n' "$output"
}

parse_boundary_info() {
  local raw="$1"
  python3 - "$raw" <<'PYJSON' 2>/dev/null || printf 'false\tunknown\tfalse\t\t\t\n'
import json
import sys

try:
    payload = json.loads(sys.argv[1] or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

def text(value):
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\n", " ").strip()

print(
    "{}\t{}\t{}\t{}\t{}\t{}".format(
        "true" if payload.get("ok") is True else "false",
        text(payload.get("violation") or "unknown"),
        "true" if payload.get("retry_possible") is True else "false",
        text(payload.get("detected_base")),
        text(payload.get("owner_ppid")),
        text(payload.get("current_ppid")),
    )
)
PYJSON
}

entry_missing_tasks() {
  local req_id="$1"
  python3 - "$PROJECT_ROOT" "$req_id" <<'PYJSON'
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
req_id = sys.argv[2]
request_path = project_root / ".gran-maestro" / "requests" / req_id / "request.json"
try:
    data = json.loads(request_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if not isinstance(data, dict):
    raise SystemExit(0)

tasks = data.get("tasks")
if not isinstance(tasks, list):
    raise SystemExit(0)

for task in tasks:
    if not isinstance(task, dict):
        continue
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        continue
    meta_path = project_root / ".gran-maestro" / "worktrees" / f"{req_id}-{task_id}.meta.json"
    if not meta_path.exists():
        print(task_id)
PYJSON
}

write_active_meta() {
  local req_id="$1" task_id="$2" worktree_path="$3" branch="$4"
  python3 - "$PROJECT_ROOT" "$req_id" "$task_id" "$worktree_path" "$branch" <<'PYJSON'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1])
req_id = sys.argv[2]
task_id = sys.argv[3]
worktree_path = sys.argv[4]
branch = sys.argv[5]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
task_key = f"{req_id}-{task_id}"
meta_path = project_root / ".gran-maestro" / "worktrees" / f"{task_key}.meta.json"
meta_path.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "taskId": task_key,
    "path": worktree_path,
    "branch": branch,
    "state": "active",
    "created_at": now,
    "last_activity_at": now,
}
tmp_path = Path(str(meta_path) + ".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp_path, meta_path)
PYJSON
}

repair_entry_once() {
  local req_id="$1" detected_base="$2"
  local task_id worktree_path task_branch create_status

  [ -n "$detected_base" ] || return 1

  while IFS= read -r task_id; do
    [ -n "$task_id" ] || continue
    worktree_path="${PROJECT_ROOT}/.gran-maestro/worktrees/${req_id}-${task_id}"
    task_branch="$(cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree branch-name --req "$req_id" --task "$task_id" --base "$detected_base")"

    if [ ! -e "${worktree_path}/.git" ]; then
      set +e
      cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree create --path "$worktree_path" --branch "$task_branch" --base "$detected_base" >/dev/null
      create_status=$?
      set -e
      if [ "$create_status" -ne 0 ]; then
        debug_log "boundary_entry_repair_failed" "req=$req_id task=$task_id status=$create_status"
        continue
      fi
    fi

    if [ -e "${worktree_path}/.git" ]; then
      write_active_meta "$req_id" "$task_id" "$worktree_path" "$task_branch"
      debug_log "boundary_entry_repair_meta_written" "req=$req_id task=$task_id path=$worktree_path"
    fi
  done <<EOF
$(entry_missing_tasks "$req_id")
EOF
}

warn_session_id_mismatch_once_if_any

HOOK_INFO="$(parse_hook_info)"
SHOULD_CHECK="$(printf '%s' "$HOOK_INFO" | cut -f1)"
TOOL_NAME="$(printf '%s' "$HOOK_INFO" | cut -f2)"
SKILL_NAME="$(printf '%s' "$HOOK_INFO" | cut -f3)"
REQ_ID="$(printf '%s' "$HOOK_INFO" | cut -f4)"

if [ "$SHOULD_CHECK" != "true" ]; then
  debug_log "pre_tool_pass" "tool=$TOOL_NAME skill=$SKILL_NAME"
  exit 0
fi

BOUNDARY_RAW="$(run_boundary_check "$REQ_ID" "entry")"
BOUNDARY_INFO="$(parse_boundary_info "$BOUNDARY_RAW")"
BOUNDARY_OK="$(printf '%s' "$BOUNDARY_INFO" | cut -f1)"
BOUNDARY_VIOLATION="$(printf '%s' "$BOUNDARY_INFO" | cut -f2)"
BOUNDARY_RETRY="$(printf '%s' "$BOUNDARY_INFO" | cut -f3)"
DETECTED_BASE="$(printf '%s' "$BOUNDARY_INFO" | cut -f4)"
OWNER_PPID="$(printf '%s' "$BOUNDARY_INFO" | cut -f5)"
CURRENT_PPID="$(printf '%s' "$BOUNDARY_INFO" | cut -f6)"

if [ "$BOUNDARY_OK" != "true" ]; then
  [ -n "$BOUNDARY_VIOLATION" ] || BOUNDARY_VIOLATION="unknown"
  log_boundary_event "detected" "$REQ_ID" "$BOUNDARY_VIOLATION" "entry boundary violation detected"
fi

if [ "$BOUNDARY_VIOLATION" = "session_mismatch" ]; then
  printf '[boundary] session_mismatch ppid=%s owner=%s, skip enforcement\n' "${CURRENT_PPID:-$PPID}" "${OWNER_PPID:-unknown}" >&2
  debug_log "boundary_session_mismatch" "req=$REQ_ID owner=$OWNER_PPID current=$CURRENT_PPID"
  exit 0
fi

if [ "$BOUNDARY_OK" = "true" ]; then
  debug_log "boundary_entry_pass" "req=$REQ_ID"
  exit 0
fi

if [ "$BOUNDARY_VIOLATION" = "worktree_missing" ] && [ "$BOUNDARY_RETRY" = "true" ]; then
  repair_entry_once "$REQ_ID" "$DETECTED_BASE"
  BOUNDARY_RAW="$(run_boundary_check "$REQ_ID" "entry")"
  BOUNDARY_INFO="$(parse_boundary_info "$BOUNDARY_RAW")"
  BOUNDARY_OK="$(printf '%s' "$BOUNDARY_INFO" | cut -f1)"
  BOUNDARY_VIOLATION="$(printf '%s' "$BOUNDARY_INFO" | cut -f2)"
  if [ "$BOUNDARY_OK" = "true" ]; then
    log_boundary_event "retry_success" "$REQ_ID" "ok" "entry repair succeeded"
    debug_log "boundary_entry_repair_pass" "req=$REQ_ID"
    exit 0
  fi
  [ -n "$BOUNDARY_VIOLATION" ] || BOUNDARY_VIOLATION="unknown"
  log_boundary_event "retry_failed" "$REQ_ID" "$BOUNDARY_VIOLATION" "entry repair failed"
fi

[ -n "$BOUNDARY_VIOLATION" ] || BOUNDARY_VIOLATION="unknown"
debug_log "boundary_entry_block" "req=$REQ_ID violation=$BOUNDARY_VIOLATION"
log_boundary_event "blocked" "$REQ_ID" "$BOUNDARY_VIOLATION" "boundary_violation:${BOUNDARY_VIOLATION}"
emit_block_json "boundary_violation:${BOUNDARY_VIOLATION}"
exit 0
