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
STATE_FILE="${MST_TMP}/mst-state-${PPID}.json"
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

HOOK_INFO="$(printf '%s' "$STDIN_RAW" | python3 -c 'import json, sys
raw = sys.stdin.read() or ""
stop_active = "unknown"
agile_auto_mode = "unknown"
last_msg = ""

def parse_bool(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "y", "on"):
            return "true"
        if text in ("0", "false", "no", "n", "off"):
            return "false"
    return "unknown"

try:
    payload = json.loads(raw)
except Exception:
    payload = {}

if isinstance(payload, dict):
    value = payload.get("stop_hook_active")
    if value is True:
        stop_active = "true"
    elif value is False:
        stop_active = "false"

    for key in ("agile_auto_mode", "agileAutoMode", "AUTO_MODE", "auto_mode"):
        parsed = parse_bool(payload.get(key))
        if parsed != "unknown":
            agile_auto_mode = parsed
            break

    candidates = [
        payload.get("last_assistant_message"),
        payload.get("assistant_message"),
        payload.get("message"),
        payload.get("reason"),
    ]

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            last_msg = candidate.strip()
            break

print(f"{stop_active}\t{agile_auto_mode}\t{last_msg}")
' 2>/dev/null || printf 'unknown\tunknown\t\n')"

STOP_HOOK_ACTIVE="$(printf '%s' "$HOOK_INFO" | cut -f1)"
AGILE_AUTO_MODE_HINT="$(printf '%s' "$HOOK_INFO" | cut -f2)"
LAST_ASSISTANT_MESSAGE="$(printf '%s' "$HOOK_INFO" | cut -f3-)"

append_audit_entry() {
  local classification="${1:-}"
  local declared_reason="${2:-}"
  local block_reason="${3:-}"

  python3 - "$PROJECT_ROOT" "$classification" "$declared_reason" "$block_reason" "$STOP_HOOK_ACTIVE" "$LAST_ASSISTANT_MESSAGE" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1])
classification = str(sys.argv[2] or "").strip()
declared_reason_input = str(sys.argv[3] or "").strip()
block_reason = str(sys.argv[4] or "").strip() or None
stop_hook_active_raw = str(sys.argv[5] or "").strip().lower()
last_assistant_message = str(sys.argv[6] or "")

try:
    agile_root = project_root / ".gran-maestro" / "agile"
    active_sessions = []
    for session_path in sorted(agile_root.glob("AGI-*/session.json")):
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status", "")).strip().lower() != "active":
            continue
        updated_at = payload.get("updated_at")
        updated_at_key = str(updated_at).strip() if isinstance(updated_at, str) else ""
        active_sessions.append((updated_at_key, session_path.parent.name))

    if not active_sessions:
        raise SystemExit(0)

    active_sessions.sort(key=lambda item: item[0])
    agi_id = active_sessions[-1][1]
    audit_path = agile_root / agi_id / "stop-audit.ndjson"

    line_count = 0
    if audit_path.is_file():
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
        except Exception:
            line_count = 0
    event_id = f"SAT-{line_count + 1:06d}"

    sentinel_match = re.search(r"\[MST\s+stop_intent\s+reason=([^\s\]]+)(?:\s+detail=\"([^\"]*)\")?\]", last_assistant_message)
    sentinel_raw = None
    declared_reason = None
    if sentinel_match:
        sentinel_raw = sentinel_match.group(0)
        parsed_reason = sentinel_match.group(1).strip()
        declared_reason = parsed_reason or None
    if declared_reason_input:
        declared_reason = declared_reason_input

    stop_hook_active_at_entry = None
    if stop_hook_active_raw == "true":
        stop_hook_active_at_entry = True
    elif stop_hook_active_raw == "false":
        stop_hook_active_at_entry = False

    classification_value = classification if classification in {"blocked", "allowed", "pass_through"} else "pass_through"
    outcome_map = {
        "blocked": "block",
        "allowed": "allow",
        "pass_through": "pass_through",
    }
    entry = {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "agi_id": agi_id,
        "sprint": None,
        "hook_stage": "Stop",
        "stop_hook_active_at_entry": stop_hook_active_at_entry,
        "declared_reason": declared_reason,
        "classification": classification_value,
        "block_reason": block_reason,
        "sentinel_raw": sentinel_raw,
        "pm_last_turn_snippet": last_assistant_message[:200],
        "retry_history_ref": None,
        "outcome": outcome_map.get(classification_value, "pass_through"),
    }

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")
except SystemExit:
    pass
except Exception as exc:
    print(f"[stop-audit] append failed: {exc}", file=sys.stderr)
PY
}

classify_stop_intent() {
  python3 - "$PROJECT_ROOT" "$LAST_ASSISTANT_MESSAGE" <<'PY'
import json
import re
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
pm_last_turn = str(sys.argv[2] or "")

sentinel_match = re.search(
    r"\[MST\s+stop_intent\s+reason=([^\s\]]+)(?:\s+detail=\"([^\"]*)\")?\]",
    pm_last_turn,
)
if not sentinel_match:
    print("none\t\t")
    raise SystemExit(0)

declared_reason = sentinel_match.group(1).strip()
if not declared_reason:
    print("none\t\t")
    raise SystemExit(0)

policy_path = project_root / "hooks" / "stop-agile-gate-reasons.json"
try:
    with open(policy_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    allowed_enum = payload.get("allowed_enum")
    if not isinstance(allowed_enum, list):
        raise ValueError("allowed_enum must be a list")
    allowed = {str(item).strip() for item in allowed_enum if str(item).strip()}
except Exception:
    print("none\t\t")
    raise SystemExit(0)

if declared_reason not in allowed:
    print(f"blocked\t{declared_reason}\tarbitrary_stop")
    raise SystemExit(0)

if declared_reason == "unrecoverable_external_failure":
    if not re.search(r"retry|재시도|다시\s*시도|retried|attempt", pm_last_turn, re.IGNORECASE):
        print(f"blocked\t{declared_reason}\tinsufficient_recovery_attempt")
        raise SystemExit(0)
    print(f"allowed\t{declared_reason}\t")
    raise SystemExit(0)

if declared_reason == "fatal_user_judgment_required":
    if "?" not in pm_last_turn:
        print(f"blocked\t{declared_reason}\tambiguous_user_question")
        raise SystemExit(0)
    print(f"allowed\t{declared_reason}\t")
    raise SystemExit(0)

print(f"allowed\t{declared_reason}\t")
PY
}

append_block_audit_entry() {
  local fallback_reason="${1:-}"
  local effective_block_reason="$fallback_reason"
  if [ -n "${STOP_INTENT_BLOCK_REASON:-}" ]; then
    effective_block_reason="$STOP_INTENT_BLOCK_REASON"
  fi

  append_audit_entry "blocked" "${STOP_INTENT_DECLARED_REASON:-}" "$effective_block_reason"
}

if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  append_audit_entry "pass_through" "" "stop_hook_active_true"
  debug_log "allow" "reason=stop_hook_active_true"
  exit 0
fi

contains_allow_pattern() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- '"tool_name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|"name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|workflow complete|final answer delivered|user requested stop'
}

contains_agile_allow_marker() {
  local text="$1"
  printf '%s' "$text" | grep -Fq "[스티어링 체크포인트]" \
    || printf '%s' "$text" | grep -Fq "[비상 스티어링]" \
    || printf '%s' "$text" | grep -Fq "[Sprint 0]" \
    || printf '%s' "$text" | grep -Fq "[자동 중단]"
}

extract_return_to() {
  local text="$1"
  printf '%s' "$text" | grep -oE 'return_to=[a-zA-Z0-9_:/-]+' | tail -1 | sed 's/return_to=//' || true
}

contains_agile_text_question() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- '계속할까요|진행할까요|계속[[:space:]]*진행하시겠습니까|멈추고|중단할까요|요약하고[[:space:]]*계속|정리하고[[:space:]]*계속|컨텍스트.*길|자연스러운[[:space:]]*단락|여기서[[:space:]]*(단락|끊|마무리|정지)|수동[[:space:]]*재호출|다시[[:space:]]*호출|세션[[:space:]]*교체|자연스럽게[[:space:]]*(멈|쉬|끊)'
}

contains_self_pause_rationalization() {
  local text="$1"
  if printf '%s' "$text" | grep -E -i -q 'stash[^[:cntrl:]]{0,20}squash[^[:cntrl:]]{0,20}부담|반복[[:space:]]*stash|paused로[[:space:]]*전환|명시적으로[[:space:]]*paused|Sprint[^[:cntrl:]]{0,40}paused[^[:cntrl:]]{0,20}boundary|sprint[[:space:]]*[0-9]+[[:space:]]*boundary|새[[:space:]]*세션에서[^\n]*재개|--resume[^\n]{0,30}재개[[:space:]]*권장|추천[[:space:]]*경로[^\n]{0,30}재개[[:space:]]*시점|사용자[[:space:]]*검토에[[:space:]]*자연스러운[[:space:]]*지점|자연스러운[[:space:]]*검토[[:space:]]*지점'; then
    return 0
  fi
  return 1
}

read_status_field() {
  local status_file="$1"
  python3 - "$status_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    raise SystemExit(1)

if not isinstance(payload, dict):
    raise SystemExit(1)

status = payload.get("status", "")
if status is None:
    status = ""
elif not isinstance(status, str):
    status = str(status)

print(status.strip().lower())
PY
}

# Exit 0 + print value: owner_ppid present
# Exit 2: owner_ppid field absent (legacy file)
# Exit 1: parse error
read_owner_ppid_field() {
  local status_file="$1"
  python3 - "$status_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    raise SystemExit(1)

if not isinstance(payload, dict):
    raise SystemExit(1)

owner_ppid = payload.get("owner_ppid")
if owner_ppid is None:
    raise SystemExit(2)

if isinstance(owner_ppid, bool):
    raise SystemExit(1)
try:
    print(int(owner_ppid))
except (TypeError, ValueError):
    raise SystemExit(1)
PY
}

# Exit 0: file mtime is within window; Exit 1: outside window or error
_file_age_within_window() {
  local status_file="$1" window_sec="$2"
  python3 - "$status_file" "$window_sec" <<'PY'
import os
import sys
import time

path = sys.argv[1]
try:
    window = int(sys.argv[2])
except (ValueError, IndexError):
    window = 900
try:
    age = time.time() - os.path.getmtime(path)
    sys.exit(0 if age <= window else 1)
except OSError:
    sys.exit(1)
PY
}

MST_STOP_STATE_GUARD_WINDOW_SEC="${MST_STOP_STATE_GUARD_WINDOW_SEC:-900}"

is_request_terminal_status() {
  local status="$1"
  case "$status" in
    done|completed|accepted|cancelled)
      return 0
      ;;
  esac
  return 1
}

is_plan_terminal_status() {
  local status="$1"
  case "$status" in
    done|completed|cancelled)
      return 0
      ;;
  esac
  return 1
}

has_active_workflow_session() {
  local requests_root plans_root status_file status owner_ppid_value owner_ppid_exit
  requests_root="${PROJECT_ROOT}/.gran-maestro/requests"
  plans_root="${PROJECT_ROOT}/.gran-maestro/plans"

  if [ -d "$requests_root" ]; then
    for status_file in "$requests_root"/*/request.json; do
      [ -f "$status_file" ] || continue
      if ! status="$(read_status_field "$status_file")"; then
        printf '[mst-stop-hook] warn: failed to parse status from %s\n' "$status_file" >&2
        debug_log "warn" "reason=request_status_parse_failed file=$status_file"
        continue
      fi
      if is_request_terminal_status "$status"; then
        continue
      fi
      # Non-terminal: check owner_ppid for session isolation
      owner_ppid_exit=0
      owner_ppid_value="$(read_owner_ppid_field "$status_file")" || owner_ppid_exit=$?
      if [ "$owner_ppid_exit" -eq 0 ]; then
        # owner_ppid present — check if it matches current session
        if [ "$owner_ppid_value" = "$PPID" ]; then
          debug_log "info" "active_request_session_detected status=$status file=$status_file"
          return 0
        else
          debug_log "info" "skipping_foreign_session_request status=$status file=$status_file owner_ppid=$owner_ppid_value"
          continue
        fi
      elif [ "$owner_ppid_exit" -eq 2 ]; then
        # Legacy file: no owner_ppid — stale prevention path only, never authoritative active for current session
        if _file_age_within_window "$status_file" "$MST_STOP_STATE_GUARD_WINDOW_SEC"; then
          debug_log "info" "skipping_recent_legacy_request_without_owner status=$status file=$status_file"
        else
          debug_log "info" "skipping_stale_legacy_request status=$status file=$status_file"
        fi
        continue
      else
        # JSON parse error — skip gracefully, do not block
        printf '[mst-stop-hook] warn: failed to parse owner_ppid from %s\n' "$status_file" >&2
        debug_log "warn" "reason=owner_ppid_parse_failed file=$status_file"
        continue
      fi
    done
  fi

  if [ -d "$plans_root" ]; then
    for status_file in "$plans_root"/*/plan.json; do
      [ -f "$status_file" ] || continue
      if ! status="$(read_status_field "$status_file")"; then
        printf '[mst-stop-hook] warn: failed to parse status from %s\n' "$status_file" >&2
        debug_log "warn" "reason=plan_status_parse_failed file=$status_file"
        continue
      fi
      if is_plan_terminal_status "$status"; then
        continue
      fi
      # Non-terminal: check owner_ppid for session isolation
      owner_ppid_exit=0
      owner_ppid_value="$(read_owner_ppid_field "$status_file")" || owner_ppid_exit=$?
      if [ "$owner_ppid_exit" -eq 0 ]; then
        if [ "$owner_ppid_value" = "$PPID" ]; then
          debug_log "info" "active_plan_session_detected status=$status file=$status_file"
          return 0
        else
          debug_log "info" "skipping_foreign_session_plan status=$status file=$status_file owner_ppid=$owner_ppid_value"
          continue
        fi
      elif [ "$owner_ppid_exit" -eq 2 ]; then
        if _file_age_within_window "$status_file" "$MST_STOP_STATE_GUARD_WINDOW_SEC"; then
          debug_log "info" "skipping_recent_legacy_plan_without_owner status=$status file=$status_file"
        else
          debug_log "info" "skipping_stale_legacy_plan status=$status file=$status_file"
        fi
        continue
      else
        printf '[mst-stop-hook] warn: failed to parse owner_ppid from %s\n' "$status_file" >&2
        debug_log "warn" "reason=owner_ppid_parse_failed file=$status_file"
        continue
      fi
    done
  fi

  return 1
}

emit_block_json() {
  local reason="$1"
  python3 - "$reason" <<'PY'
import json
import sys

reason = sys.argv[1]
print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
PY
}

persist_block_state() {
  local reason="$1"
  python3 - "$STATE_FILE" "$reason" <<'PY'
import json
import os
import sys

path = sys.argv[1]
reason = sys.argv[2]

payload = {}
if os.path.isfile(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        payload = {}

if not isinstance(payload, dict):
    payload = {}

block_count = payload.get("block_count")
if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
    block_count = 0

block_count += 1
payload["block_count"] = block_count
payload["last_block_reason"] = reason if isinstance(reason, str) else ""

tmp_path = f"{path}.tmp"
try:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)
except Exception:
    pass

print(block_count)
PY
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
  python3 - "$raw" <<'PY'
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
PY
}

exit_boundary_requests() {
  python3 - "$PROJECT_ROOT" <<'PY'
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
requests_root = project_root / ".gran-maestro" / "requests"
if not requests_root.is_dir():
    raise SystemExit(0)

for request_path in sorted(requests_root.glob("REQ-*/request.json")):
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(data, dict):
        continue
    try:
        phase = int(data.get("current_phase"))
    except (TypeError, ValueError):
        continue
    status = str(data.get("status") or "").strip().lower()
    owner_ppid = data.get("owner_ppid")
    if owner_ppid is None:
        continue
    if phase == 5 and status == "done":
        req_id = str(data.get("id") or request_path.parent.name).strip()
        if req_id:
            print(req_id)
PY
}

exit_repair_targets() {
  local req_id="$1"
  python3 - "$PROJECT_ROOT" "$req_id" <<'PY'
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

retry_states = {"cleaning", "pre_merge", "clean_failed"}
for task in tasks:
    if not isinstance(task, dict):
        continue
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        continue
    meta_path = project_root / ".gran-maestro" / "worktrees" / f"{req_id}-{task_id}.meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(meta, dict):
        continue
    state = str(meta.get("state") or "").strip()
    path = str(meta.get("path") or "").strip()
    if state in retry_states and path:
        print(f"{task_id}\t{path}")
PY
}

mark_exit_meta_cleaned() {
  local req_id="$1" task_id="$2"
  python3 - "$PROJECT_ROOT" "$req_id" "$task_id" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1])
req_id = sys.argv[2]
task_id = sys.argv[3]
meta_path = project_root / ".gran-maestro" / "worktrees" / f"{req_id}-{task_id}.meta.json"
try:
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
payload["state"] = "cleaned"
payload["last_activity_at"] = now
tmp_path = Path(str(meta_path) + ".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(tmp_path, meta_path)
PY
}

repair_exit_once() {
  local req_id="$1"
  local task_id worktree_path remove_status

  while IFS=$'\t' read -r task_id worktree_path; do
    [ -n "${task_id:-}" ] || continue
    [ -n "${worktree_path:-}" ] || continue

    if [ -e "$worktree_path" ]; then
      set +e
      cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree remove --path "$worktree_path" --force >/dev/null
      remove_status=$?
      set -e
      if [ "$remove_status" -ne 0 ]; then
        debug_log "boundary_exit_repair_failed" "req=$req_id task=$task_id status=$remove_status path=$worktree_path"
        continue
      fi
    fi

    if [ ! -e "$worktree_path" ]; then
      mark_exit_meta_cleaned "$req_id" "$task_id"
      debug_log "boundary_exit_repair_meta_cleaned" "req=$req_id task=$task_id path=$worktree_path"
    fi
  done <<EOF
$(exit_repair_targets "$req_id")
EOF
}

run_exit_boundary_guard() {
  local req_id boundary_raw boundary_info boundary_ok boundary_violation boundary_retry owner_ppid current_ppid

  while IFS= read -r req_id; do
    [ -n "$req_id" ] || continue

    boundary_raw="$(run_boundary_check "$req_id" "exit")"
    boundary_info="$(parse_boundary_info "$boundary_raw")"
    boundary_ok="$(printf '%s' "$boundary_info" | cut -f1)"
    boundary_violation="$(printf '%s' "$boundary_info" | cut -f2)"
    boundary_retry="$(printf '%s' "$boundary_info" | cut -f3)"
    owner_ppid="$(printf '%s' "$boundary_info" | cut -f5)"
    current_ppid="$(printf '%s' "$boundary_info" | cut -f6)"

    if [ "$boundary_ok" != "true" ]; then
      [ -n "$boundary_violation" ] || boundary_violation="unknown"
      log_boundary_event "detected" "$req_id" "$boundary_violation" "exit boundary violation detected"
    fi

    if [ "$boundary_violation" = "session_mismatch" ]; then
      printf '[boundary] session_mismatch ppid=%s owner=%s, skip enforcement\n' "${current_ppid:-$PPID}" "${owner_ppid:-unknown}" >&2
      debug_log "boundary_session_mismatch" "phase=exit req=$req_id owner=$owner_ppid current=$current_ppid"
      continue
    fi

    if [ "$boundary_ok" = "true" ]; then
      debug_log "boundary_exit_pass" "req=$req_id"
      continue
    fi

    if [ "$boundary_violation" = "not_cleaned" ] && [ "$boundary_retry" = "true" ]; then
      repair_exit_once "$req_id"
      boundary_raw="$(run_boundary_check "$req_id" "exit")"
      boundary_info="$(parse_boundary_info "$boundary_raw")"
      boundary_ok="$(printf '%s' "$boundary_info" | cut -f1)"
      boundary_violation="$(printf '%s' "$boundary_info" | cut -f2)"
      if [ "$boundary_ok" = "true" ]; then
        log_boundary_event "retry_success" "$req_id" "ok" "exit repair succeeded"
        debug_log "boundary_exit_repair_pass" "req=$req_id"
        continue
      fi
      [ -n "$boundary_violation" ] || boundary_violation="unknown"
      log_boundary_event "retry_failed" "$req_id" "$boundary_violation" "exit repair failed"
    fi

    [ -n "$boundary_violation" ] || boundary_violation="unknown"
    debug_log "boundary_exit_block" "req=$req_id violation=$boundary_violation"
    log_boundary_event "blocked" "$req_id" "$boundary_violation" "boundary_violation:${boundary_violation}"
    emit_block_json "boundary_violation:${boundary_violation}"
    exit 0
  done <<EOF
$(exit_boundary_requests)
EOF
}

run_exit_boundary_guard

STATE_INFO="$(python3 - "$STATE_FILE" <<'PY'
import json
import os
import sys

def emit(
    status,
    workflow_active=False,
    current_skill="",
    active_req="",
    iteration=0,
    next_skill="",
    next_source="",
    next_auto=False,
    source_skill="",
    has_next_action=False,
    updated_at="",
    agile_loop_active=False,
    block_count=0,
    last_block_reason="",
    steering_disabled=False,
):
    if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
        block_count = 0
    if not isinstance(last_block_reason, str):
        last_block_reason = ""
    last_block_reason = last_block_reason.replace("\t", " ").replace("\n", " ").strip()
    print(
        "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
            status,
            "true" if workflow_active else "false",
            current_skill,
            active_req,
            iteration,
            next_skill,
            next_source,
            "true" if next_auto else "false",
            source_skill,
            "true" if has_next_action else "false",
            updated_at,
            "true" if agile_loop_active else "false",
            block_count,
            last_block_reason,
            "true" if steering_disabled else "false",
        )
    )

path = sys.argv[1]
if not os.path.isfile(path):
    emit("missing")
    raise SystemExit(0)

try:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
except Exception:
    emit("invalid")
    raise SystemExit(0)

if not isinstance(payload, dict):
    emit("invalid")
    raise SystemExit(0)

workflow_active = bool(payload.get("workflow_active"))
current_skill = payload.get("current_skill") if isinstance(payload.get("current_skill"), str) else ""
active_req = payload.get("active_req") if isinstance(payload.get("active_req"), str) else ""
updated_at = payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else ""
agile_loop_active = payload.get("agile_loop_active")
if not isinstance(agile_loop_active, bool):
    agile_loop_active = False

block_count = payload.get("block_count")
if not isinstance(block_count, int) or isinstance(block_count, bool) or block_count < 0:
    block_count = 0

last_block_reason = payload.get("last_block_reason")
if not isinstance(last_block_reason, str):
    last_block_reason = ""

steering_disabled = payload.get("steering_disabled")
if not isinstance(steering_disabled, bool):
    steering_disabled = False

iteration = payload.get("iteration")
if not isinstance(iteration, int):
    iteration = 0

next_skill = ""
next_source = ""
next_auto = False
source_skill = ""
has_next_action = False

next_action = payload.get("next_action")
if isinstance(next_action, dict):
    has_next_action = True
    skill_candidates = [
        next_action.get("expected_skill"),
        next_action.get("skill"),
    ]
    source_candidates = [
        next_action.get("source_id"),
        next_action.get("source"),
    ]

    for candidate in skill_candidates:
        if isinstance(candidate, str) and candidate.strip():
            next_skill = candidate.strip()
            break

    for candidate in source_candidates:
        if isinstance(candidate, str) and candidate.strip():
            next_source = candidate.strip()
            break

    source_skill_value = next_action.get("source_skill")
    if isinstance(source_skill_value, str) and source_skill_value.strip():
        source_skill = source_skill_value.strip()

    auto_candidates = [next_action.get("auto_mode"), next_action.get("auto")]
    for candidate in auto_candidates:
        if candidate is True:
            next_auto = True
            break

emit(
    "valid",
    workflow_active=workflow_active,
    current_skill=current_skill,
    active_req=active_req,
    iteration=iteration,
    next_skill=next_skill,
    next_source=next_source,
    next_auto=next_auto,
    source_skill=source_skill,
    has_next_action=has_next_action,
    updated_at=updated_at,
    agile_loop_active=agile_loop_active,
    block_count=block_count,
    last_block_reason=last_block_reason,
    steering_disabled=steering_disabled,
)
PY
)"

STATE_STATUS="$(printf '%s' "$STATE_INFO" | cut -f1)"
WORKFLOW_ACTIVE="$(printf '%s' "$STATE_INFO" | cut -f2)"
CURRENT_SKILL="$(printf '%s' "$STATE_INFO" | cut -f3)"
ACTIVE_REQ="$(printf '%s' "$STATE_INFO" | cut -f4)"
ITERATION="$(printf '%s' "$STATE_INFO" | cut -f5)"
NEXT_SKILL="$(printf '%s' "$STATE_INFO" | cut -f6)"
NEXT_SOURCE="$(printf '%s' "$STATE_INFO" | cut -f7)"
NEXT_AUTO="$(printf '%s' "$STATE_INFO" | cut -f8)"
SOURCE_SKILL="$(printf '%s' "$STATE_INFO" | cut -f9)"
HAS_NEXT_ACTION="$(printf '%s' "$STATE_INFO" | cut -f10)"
UPDATED_AT="$(printf '%s' "$STATE_INFO" | cut -f11)"
AGILE_LOOP_ACTIVE="$(printf '%s' "$STATE_INFO" | cut -f12)"
BLOCK_COUNT="$(printf '%s' "$STATE_INFO" | cut -f13)"
LAST_BLOCK_REASON="$(printf '%s' "$STATE_INFO" | cut -f14)"
STEERING_DISABLED="$(printf '%s' "$STATE_INFO" | cut -f15)"

if [ "$WORKFLOW_ACTIVE" != "true" ] && [ "$AGILE_LOOP_ACTIVE" != "true" ]; then
  if has_active_workflow_session; then
    REASON="active workflow session detected but PPID state missing; continue workflow"
    append_block_audit_entry "$REASON"
    emit_block_json "$REASON"
    debug_log "block" "reason=state_missing_active_session_detected"
    exit 0
  fi
  append_audit_entry "pass_through" "" "workflow_inactive"
  debug_log "allow" "reason=workflow_inactive state_status=$STATE_STATUS"
  exit 0
fi

CLASSIFY_INFO="$(classify_stop_intent)"
STOP_INTENT_CLASSIFICATION="$(printf '%s' "$CLASSIFY_INFO" | cut -f1)"
STOP_INTENT_DECLARED_REASON="$(printf '%s' "$CLASSIFY_INFO" | cut -f2)"
STOP_INTENT_BLOCK_REASON="$(printf '%s' "$CLASSIFY_INFO" | cut -f3)"
STOP_INTENT_FORCE_BLOCK="false"

if [ "$STOP_INTENT_CLASSIFICATION" = "allowed" ]; then
  append_audit_entry "allowed" "$STOP_INTENT_DECLARED_REASON" ""
  debug_log "allow" "reason=sentinel_allowed declared=$STOP_INTENT_DECLARED_REASON"
  exit 0
fi

if [ "$STOP_INTENT_CLASSIFICATION" = "blocked" ]; then
  STOP_INTENT_FORCE_BLOCK="true"
  debug_log "info" "sentinel_blocked declared=$STOP_INTENT_DECLARED_REASON block_reason=$STOP_INTENT_BLOCK_REASON"
fi

if ! printf '%s' "$BLOCK_COUNT" | grep -Eq '^[0-9]+$'; then
  BLOCK_COUNT="0"
fi

AGILE_GUARD_ACTIVE="false"
if [ "$AGILE_LOOP_ACTIVE" = "true" ] || [ "$CURRENT_SKILL" = "mst:agile" ]; then
  AGILE_GUARD_ACTIVE="true"
fi

RETURN_TO_RAW="$(extract_return_to "$LAST_ASSISTANT_MESSAGE")"
if [ -z "$RETURN_TO_RAW" ] || [ "$RETURN_TO_RAW" = "null" ]; then
  RETURN_TO_RAW="$(extract_return_to "$STDIN_RAW")"
fi
RETURN_TO_SKILL=""
RETURN_TO_STEP=""
if [ -n "$RETURN_TO_RAW" ] && [ "$RETURN_TO_RAW" != "null" ]; then
  RETURN_TO_SKILL="$(printf '%s' "$RETURN_TO_RAW" | cut -d'/' -f1)"
  RETURN_TO_STEP="$(printf '%s' "$RETURN_TO_RAW" | cut -d'/' -f2)"
  debug_log "info" "return_to_detected skill=$RETURN_TO_SKILL step=$RETURN_TO_STEP raw=$RETURN_TO_RAW"
fi

AGILE_AUTO_MODE_ACTIVE="false"
if [ "$AGILE_AUTO_MODE_HINT" = "true" ]; then
  AGILE_AUTO_MODE_ACTIVE="true"
elif [ "$AGILE_AUTO_MODE_HINT" = "false" ]; then
  AGILE_AUTO_MODE_ACTIVE="false"
elif [ "$NEXT_AUTO" = "true" ]; then
  AGILE_AUTO_MODE_ACTIVE="true"
fi

ALLOW_PATTERN_FOUND="false"
if contains_allow_pattern "$LAST_ASSISTANT_MESSAGE" || contains_allow_pattern "$STDIN_RAW"; then
  ALLOW_PATTERN_FOUND="true"
fi

AGILE_ALLOW_CONTEXT="${LAST_ASSISTANT_MESSAGE}
${STDIN_RAW}"

if [ "$AGILE_LOOP_ACTIVE" = "true" ] && [ "$AGILE_AUTO_MODE_ACTIVE" = "true" ]; then
  SELF_PAUSE_CONTEXT="${LAST_ASSISTANT_MESSAGE}
${STDIN_RAW}"
  if contains_self_pause_rationalization "$SELF_PAUSE_CONTEXT"; then
    NEXT_BLOCK_COUNT=$((BLOCK_COUNT + 1))
    REASON="[CRITICAL][SELF-PAUSE-DETECTED] 자발 정지 시도 감지: 합리화 텍스트(stash/squash 부담, paused 전환, Sprint boundary 등)가 발견됨."
    REASON="$REASON Sprint loop가 active인 상태에서 자발적 상태 전이 명령(예: 'mst.py agile update --status paused')을 호출해 루프를 종료하려는 행위는 금지된다."
    REASON="$REASON 상태 전이 명령을 호출하지 말고 즉시 다음 sprint step의 tool call을 emit하라."
    REASON="$REASON Consecutive block count: $NEXT_BLOCK_COUNT."
    if [ "$NEXT_BLOCK_COUNT" -ge 3 ]; then
      REASON="[자동 중단] $REASON Escalate to user for steering."
    fi
    PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$NEXT_BLOCK_COUNT")"
    append_block_audit_entry "$REASON"
    emit_block_json "$REASON"
    debug_log "block" "reason=self_pause_rationalization_detected current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
    exit 0
  fi
fi

if [ "$AGILE_LOOP_ACTIVE" = "true" ] && { [ "$AGILE_AUTO_MODE_ACTIVE" = "true" ] || [ "$STEERING_DISABLED" = "true" ]; } && contains_agile_text_question "$AGILE_ALLOW_CONTEXT"; then
  NEXT_BLOCK_COUNT=$((BLOCK_COUNT + 1))
  REASON="Sprint loop active in AUTO_MODE=true or STEERING_DISABLED=true; text-based question patterns are blocked."
  REASON="$REASON Remove phrases like '계속할까요?', '진행할까요?', '멈추고' and continue autonomously."
  REASON="$REASON Consecutive block count: $NEXT_BLOCK_COUNT."
  if [ "$NEXT_BLOCK_COUNT" -ge 3 ]; then
    REASON="[자동 중단] $REASON Escalate to user for steering."
  fi
  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$NEXT_BLOCK_COUNT")"
  append_block_audit_entry "$REASON"
  emit_block_json "$REASON"
  debug_log "block" "reason=agile_text_question_in_auto_mode agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE current_skill=$CURRENT_SKILL block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

if [ "$STOP_INTENT_FORCE_BLOCK" != "true" ] && [ "$ALLOW_PATTERN_FOUND" = "true" ] && [ "$AGILE_GUARD_ACTIVE" = "true" ] && contains_agile_allow_marker "$AGILE_ALLOW_CONTEXT"; then
  append_audit_entry "allowed" "" "agile_allow_pattern_whitelisted"
  debug_log "allow" "reason=agile_allow_pattern_whitelisted workflow_active=$WORKFLOW_ACTIVE current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE"
  exit 0
fi

if [ "$STOP_INTENT_FORCE_BLOCK" != "true" ] && [ "$ALLOW_PATTERN_FOUND" = "true" ] && [ "$AGILE_GUARD_ACTIVE" = "true" ]; then
  NEXT_BLOCK_COUNT=$((BLOCK_COUNT + 1))
  REMAINING_DODS="continue current sprint backlog"
  if [ -n "$NEXT_SOURCE" ]; then
    REMAINING_DODS="$NEXT_SOURCE"
  elif [ -n "$ACTIVE_REQ" ]; then
    REMAINING_DODS="$ACTIVE_REQ"
  fi

  REASON="Sprint loop active; remaining DoDs: $REMAINING_DODS."
  REASON="$REASON AskUserQuestion is allowed only with agile whitelist markers."
  if [ -n "$CURRENT_SKILL" ]; then
    REASON="$REASON Current skill: $CURRENT_SKILL."
  fi
  if [ -n "$ACTIVE_REQ" ]; then
    REASON="$REASON Active request: $ACTIVE_REQ."
  fi
  REASON="$REASON Consecutive block count: $NEXT_BLOCK_COUNT."

  if [ "$NEXT_BLOCK_COUNT" -ge 3 ]; then
    REASON="[자동 중단] $REASON Escalate to user for steering."
  fi

  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$NEXT_BLOCK_COUNT")"
  append_block_audit_entry "$REASON"
  emit_block_json "$REASON"
  debug_log "block" "reason=agile_allow_pattern_missing_marker current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

if [ "$HAS_NEXT_ACTION" != "true" ]; then
  if [ "$STOP_INTENT_FORCE_BLOCK" != "true" ] && [ "$ALLOW_PATTERN_FOUND" = "true" ]; then
    append_audit_entry "allowed" "" "explicit_allow_pattern_no_next_action"
    debug_log "allow" "reason=explicit_allow_pattern_no_next_action workflow_active=$WORKFLOW_ACTIVE"
    exit 0
  fi
else
  if [ "$NEXT_AUTO" = "true" ]; then
    debug_log "block_decision" "reason=next_action_auto_override skip_allow_pattern=true next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE"
  else
    debug_log "block_decision" "reason=next_action_present skip_allow_pattern=true next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO"
  fi
fi

if [ -n "$RETURN_TO_SKILL" ] && [ "$HAS_NEXT_ACTION" != "true" ]; then
  REASON="[RETURN-TO] Sub-skill returned with return_to=$RETURN_TO_RAW. Do NOT stop or pause."
  REASON="$REASON You MUST immediately return to mst:$RETURN_TO_SKILL and continue from step $RETURN_TO_STEP."
  REASON="$REASON The sub-skill has completed; resume the parent skill's flow at the indicated step."
  REASON="$REASON [CRITICAL][NO-SELF-MOTIVATED-PAUSE] Any pause, summary, or confirmation question is forbidden. Emit the next tool call NOW."
  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$((BLOCK_COUNT + 1))")"
  append_block_audit_entry "$REASON"
  emit_block_json "$REASON"
  debug_log "block" "reason=return_to_detected return_to_skill=$RETURN_TO_SKILL return_to_step=$RETURN_TO_STEP current_skill=$CURRENT_SKILL block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

if [ "$AGILE_GUARD_ACTIVE" = "true" ] && [ "$HAS_NEXT_ACTION" != "true" ]; then
  REASON="[AGILE-CONTINUE] Sprint loop active (agile_loop_active=$AGILE_LOOP_ACTIVE, skill=$CURRENT_SKILL). Do NOT stop or pause."
  REASON="$REASON You MUST immediately continue the current sprint loop: run objective-check, then proceed to the next sprint step."
  REASON="$REASON Specifically: execute 'python3 ... agile objective-check {AGI_ID} --json' or the next pending step in the sprint backlog."
  REASON="$REASON [CRITICAL][NO-SELF-MOTIVATED-PAUSE] Any pause, summary, or confirmation question is forbidden. Emit the next tool call NOW."
  PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$((BLOCK_COUNT + 1))")"
  append_block_audit_entry "$REASON"
  emit_block_json "$REASON"
  debug_log "block" "reason=agile_loop_no_next_action_continue current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
  exit 0
fi

REASON="Workflow active, continue current skill and context without stopping."
if [ -n "$CURRENT_SKILL" ]; then
  REASON="$REASON Current skill: $CURRENT_SKILL."
fi
if [ -n "$ACTIVE_REQ" ]; then
  REASON="$REASON Active request: $ACTIVE_REQ."
fi
if [ "$ITERATION" != "0" ]; then
  REASON="$REASON Iteration: $ITERATION."
fi
if [ -n "$UPDATED_AT" ]; then
  REASON="$REASON Last update: $UPDATED_AT."
fi
if [ "$HAS_NEXT_ACTION" = "true" ] && [ -n "$NEXT_SKILL" ]; then
  NEXT_ARGS="-a"
  if [ -n "$NEXT_SOURCE" ]; then
    NEXT_ARGS="-a $NEXT_SOURCE"
  fi
  REASON="$REASON You MUST call Skill(skill: \"$NEXT_SKILL\", args: \"$NEXT_ARGS\") immediately."
  if [ -n "$SOURCE_SKILL" ]; then
    REASON="$REASON Transition source_skill: $SOURCE_SKILL."
  fi
elif [ "$HAS_NEXT_ACTION" = "true" ]; then
  REASON="$REASON Next action is pending; do not stop."
elif [ -n "$NEXT_SKILL" ]; then
  REASON="$REASON Workflow active, continue current skill before transitioning to $NEXT_SKILL."
fi
REASON="$REASON Do not stop; emit the next tool call now."

PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$((BLOCK_COUNT + 1))")"
append_block_audit_entry "$REASON"
emit_block_json "$REASON"
debug_log "block" "reason=workflow_active current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT last_block_reason=$LAST_BLOCK_REASON"
exit 0
