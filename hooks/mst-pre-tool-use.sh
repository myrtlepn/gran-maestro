#!/usr/bin/env bash
set -euo pipefail

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

debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
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
  printf '%s' "$STDIN_RAW" | python3 -c '
import json
import re
import sys

raw = sys.stdin.read() or ""
try:
    payload = json.loads(raw)
except Exception:
    payload = {}

if not isinstance(payload, dict):
    payload = {}

tool_name = str(payload.get("tool_name") or "").strip()
tool_input = payload.get("tool_input")
if not isinstance(tool_input, dict):
    tool_input = {}

skill_name = ""
for key in ("skill_name", "skill", "name"):
    value = tool_input.get(key)
    if isinstance(value, str) and value.strip():
        skill_name = value.strip()
        break

args_value = tool_input.get("args")
if isinstance(args_value, str):
    args_text = args_value
else:
    try:
        args_text = json.dumps(args_value, ensure_ascii=False)
    except Exception:
        args_text = str(args_value or "")

match = re.search(r"\bREQ-\d+\b", args_text)
req_id = match.group(0) if match else ""
should_check = tool_name == "Skill" and skill_name in {"mst:approve", "/mst:approve"} and bool(req_id)
print("{}\t{}\t{}\t{}".format("true" if should_check else "false", tool_name, skill_name, req_id))
' 2>/dev/null || printf 'false\t\t\t\n'
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
