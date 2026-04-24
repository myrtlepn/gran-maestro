#!/usr/bin/env bash
set -Eeuo pipefail

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

SNAPSHOT_PROBE_SCRIPT="$(resolve_repo_script "_snapshot_probe.py")"
FLOW_LOGGER_SCRIPT="$(resolve_repo_script "_flow_logger.py")"
HOOK_PATTERNS_SCRIPT="$(resolve_repo_script "_hook_patterns.py")"

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
    printf '[mst-stop-hook] helper_failed helper=%s exit=%s %s\n' "$helper" "$status" "$detail" >&2
  else
    printf '[mst-stop-hook] helper_failed helper=%s exit=%s\n' "$helper" "$status" >&2
  fi
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

DECISION_EMITTED="false"
SESSION_ID="unknown"
SESSION_ID_SOURCE=""
SESSION_ID_RESOLUTION_FAILED="true"
HOOK_EVENT_NAME=""
TRANSCRIPT_PATH=""
SNAPSHOT_PRESENT="false"
SNAPSHOT_PATH="${PROJECT_ROOT}/.gran-maestro/state/unknown/snapshot.json"
SNAPSHOT_DIGEST=""
STDIN_DIGEST=""
SNAPSHOT_CURRENT_SKILL=""
SNAPSHOT_CURRENT_STEP=""
SNAPSHOT_TOTAL_STEPS=""
SNAPSHOT_STATUS=""
SNAPSHOT_RETURN_TO_SKILL=""
SNAPSHOT_RETURN_TO_STEP=""

emit_approve_json() {
  local reason="$1"
  python3 - "$reason" <<'PY'
import json
import sys

reason = sys.argv[1]
print(json.dumps({"decision": "approve", "reason": reason}, ensure_ascii=False))
PY
}

reason_with_snapshot_meta() {
  local reason="$1"
  case "$reason" in
    *snapshot_present=*)
      printf '%s\n' "$reason"
      ;;
    *)
      printf '%s snapshot_present=%s\n' "$reason" "${SNAPSHOT_PRESENT:-unknown}"
      ;;
  esac
}

emit_approve_decision() {
  local reason
  reason="$(reason_with_snapshot_meta "$1")"
  DECISION_EMITTED="true"
  emit_approve_json "$reason"
}

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

emit_unhandled_path_fallback() {
  local exit_code="${1:-0}"
  local data
  data="$(python3 - "$exit_code" "${SNAPSHOT_DIGEST:-}" "${SNAPSHOT_CURRENT_SKILL:-}" "${SNAPSHOT_CURRENT_STEP:-}" "${SNAPSHOT_TOTAL_STEPS:-}" "${SNAPSHOT_STATUS:-}" <<'PY'
import json
import sys

payload = {
    "exit_code": sys.argv[1],
    "snapshot_digest": sys.argv[2],
    "current_skill": sys.argv[3],
    "current_step": sys.argv[4],
    "total_steps": sys.argv[5],
    "status": sys.argv[6],
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
)"
  append_flow_event "unhandled_path" "$data"
  emit_approve_decision "unhandled_path fallback"
}

on_stop_hook_err() {
  local exit_code="${1:-$?}"
  local line="${2:-${BASH_LINENO[0]:-}}"
  local command="${3:-${BASH_COMMAND:-unknown}}"
  local funcname="${FUNCNAME[*]:-}"
  local source="${BASH_SOURCE[*]:-}"
  local signal=""
  local data safe_command

  trap - ERR
  set +e

  if [ "${DECISION_EMITTED:-false}" = "true" ]; then
    exit 0
  fi

  if printf '%s' "$exit_code" | grep -Eq '^[0-9]+$' && [ "$exit_code" -ge 128 ]; then
    signal="$((exit_code - 128))"
  fi

  data="$(python3 - "$exit_code" "$line" "$command" "$funcname" "$source" "$signal" "$PPID" "${SESSION_ID:-unknown}" <<'PY'
import json
import sys

payload = {
    "exit_code": sys.argv[1],
    "line": sys.argv[2],
    "command": sys.argv[3],
    "funcname": sys.argv[4],
    "source": sys.argv[5],
    "signal": sys.argv[6],
    "ppid": sys.argv[7],
    "session_id": sys.argv[8],
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
)"

  append_flow_event "hook_failure" "$data"
  safe_command="$(sanitize_log_value "$command")"
  printf '[mst-stop-hook] hook_failure event_type=hook_failure exit_code=%s line=%s cmd=%s signal=%s ppid=%s session_id=%s\n' \
    "$(sanitize_log_value "$exit_code")" \
    "$(sanitize_log_value "$line")" \
    "$safe_command" \
    "$(sanitize_log_value "$signal")" \
    "$(sanitize_log_value "$PPID")" \
    "$(sanitize_log_value "${SESSION_ID:-unknown}")" >&2
  emit_approve_decision "hook_failure: line=$line cmd=$safe_command"
  exit 0
}

on_stop_hook_exit() {
  local exit_code="$?"
  trap - EXIT
  if [ "${DECISION_EMITTED:-false}" != "true" ]; then
    emit_unhandled_path_fallback "$exit_code"
    exit 0
  fi
  exit "$exit_code"
}

trap on_stop_hook_exit EXIT
trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

SNAPSHOT_PROBE_EXPORTS=""
if [ -f "$SNAPSHOT_PROBE_SCRIPT" ]; then
  SNAPSHOT_PROBE_STATUS=0
  trap - ERR
  set +e
  SNAPSHOT_PROBE_EXPORTS="$(printf '%s' "$STDIN_RAW" | python3 "$SNAPSHOT_PROBE_SCRIPT" --project-root "$PROJECT_ROOT" --format shell 2>/dev/null)"
  SNAPSHOT_PROBE_STATUS=$?
  set -e
  trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
  if [ "$SNAPSHOT_PROBE_STATUS" -eq 0 ]; then
    SNAPSHOT_PROBE_EVAL_STATUS=0
    if eval "$SNAPSHOT_PROBE_EXPORTS"; then
      :
    else
      SNAPSHOT_PROBE_EVAL_STATUS=$?
      warn_helper_failed "snapshot_probe" "$SNAPSHOT_PROBE_EVAL_STATUS" "invalid_exports"
      debug_log "warn" "reason=snapshot_probe_invalid_exports"
    fi
  else
    warn_helper_failed "snapshot_probe" "$SNAPSHOT_PROBE_STATUS" "path=$(sanitize_log_value "$SNAPSHOT_PROBE_SCRIPT")"
    debug_log "warn" "reason=snapshot_probe_failed"
  fi
else
  warn_helper_failed "snapshot_probe" "127" "missing path=$(sanitize_log_value "$SNAPSHOT_PROBE_SCRIPT")"
  debug_log "warn" "reason=snapshot_probe_missing path=$SNAPSHOT_PROBE_SCRIPT"
fi

if [ "${MST_STOP_HOOK_TEST_INJECT_FAILURE:-}" = "after_snapshot_probe" ]; then
  python3 -c 'raise SystemExit("REQ-692 injected failure after_snapshot_probe")'
fi

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
  emit_approve_decision "stop_hook_active_true"
  exit 0
fi

contains_allow_pattern() {
  local text="$1"
  printf '%s' "$text" | grep -Eiq -- '"tool_name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|"name"[[:space:]]*:[[:space:]]*"AskUserQuestion"|workflow complete|final answer delivered|user requested stop'
}

extract_return_to() {
  local text="$1"
  printf '%s' "$text" | grep -oE 'return_to=[a-zA-Z0-9_:/-]+' | tail -1 | sed 's/return_to=//' || true
}

read_status_field() {
  local status_file="$1"
  local status
  trap - ERR
  set +e
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
  status=$?
  return "$status"
}

# Exit 0 + print value: owner_ppid present
# Exit 2: owner_ppid field absent (legacy file)
# Exit 1: parse error
read_owner_ppid_field() {
  local status_file="$1"
  local status
  trap - ERR
  set +e
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
  status=$?
  return "$status"
}

# Exit 0 + print value: owner_session_id present
# Exit 2: owner_session_id field absent/null/empty
# Exit 1: parse error or invalid type
read_owner_session_id_field() {
  local status_file="$1"
  local status
  trap - ERR
  set +e
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

owner_session_id = payload.get("owner_session_id")
if owner_session_id is None:
    raise SystemExit(2)
if not isinstance(owner_session_id, str):
    raise SystemExit(1)
owner_session_id = owner_session_id.strip()
if not owner_session_id:
    raise SystemExit(2)
print(owner_session_id)
PY
  status=$?
  return "$status"
}

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
  local requests_root plans_root status_file status owner_session_id_value owner_session_id_exit owner_ppid_value owner_ppid_exit
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
      # Non-terminal: owner_session_id is authoritative for session isolation.
      owner_session_id_exit=0
      trap - ERR
      set +e
      owner_session_id_value="$(read_owner_session_id_field "$status_file")"
      owner_session_id_exit=$?
      set -e
      trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
      if [ "$owner_session_id_exit" -eq 0 ]; then
        if [ "$owner_session_id_value" = "${SESSION_ID:-}" ]; then
          debug_log "info" "active_request_session_detected status=$status file=$status_file owner_session_id=$owner_session_id_value"
          return 0
        else
          debug_log "info" "skipping_foreign_session_request status=$status file=$status_file owner_session_id=$owner_session_id_value current_session_id=${SESSION_ID:-unknown}"
          continue
        fi
      elif [ "$owner_session_id_exit" -ne 2 ]; then
        printf '[mst-stop-hook] warn: failed to parse owner_session_id from %s\n' "$status_file" >&2
        debug_log "warn" "reason=owner_session_id_parse_failed file=$status_file"
        continue
      fi

      # Legacy fallback: owner_ppid-only files are accepted with a warning.
      owner_ppid_exit=0
      trap - ERR
      set +e
      owner_ppid_value="$(read_owner_ppid_field "$status_file")"
      owner_ppid_exit=$?
      set -e
      trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
      if [ "$owner_ppid_exit" -eq 0 ]; then
        printf '[mst-stop-hook] warn: legacy owner_ppid fallback for %s; owner_session_id missing\n' "$status_file" >&2
        if [ "$owner_ppid_value" = "$PPID" ]; then
          debug_log "warn" "active_request_legacy_owner_ppid_fallback status=$status file=$status_file owner_ppid=$owner_ppid_value"
          return 0
        else
          debug_log "info" "skipping_foreign_session_request_legacy_owner_ppid status=$status file=$status_file owner_ppid=$owner_ppid_value"
          continue
        fi
      elif [ "$owner_ppid_exit" -eq 2 ]; then
        debug_log "info" "skipping_legacy_request_without_owner status=$status file=$status_file"
        continue
      else
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
      # Non-terminal: owner_session_id is authoritative for session isolation.
      owner_session_id_exit=0
      trap - ERR
      set +e
      owner_session_id_value="$(read_owner_session_id_field "$status_file")"
      owner_session_id_exit=$?
      set -e
      trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
      if [ "$owner_session_id_exit" -eq 0 ]; then
        if [ "$owner_session_id_value" = "${SESSION_ID:-}" ]; then
          debug_log "info" "active_plan_session_detected status=$status file=$status_file owner_session_id=$owner_session_id_value"
          return 0
        else
          debug_log "info" "skipping_foreign_session_plan status=$status file=$status_file owner_session_id=$owner_session_id_value current_session_id=${SESSION_ID:-unknown}"
          continue
        fi
      elif [ "$owner_session_id_exit" -ne 2 ]; then
        printf '[mst-stop-hook] warn: failed to parse owner_session_id from %s\n' "$status_file" >&2
        debug_log "warn" "reason=owner_session_id_parse_failed file=$status_file"
        continue
      fi

      # Legacy fallback: owner_ppid-only files are accepted with a warning.
      owner_ppid_exit=0
      trap - ERR
      set +e
      owner_ppid_value="$(read_owner_ppid_field "$status_file")"
      owner_ppid_exit=$?
      set -e
      trap 'on_stop_hook_err "$?" "$LINENO" "$BASH_COMMAND"' ERR
      if [ "$owner_ppid_exit" -eq 0 ]; then
        printf '[mst-stop-hook] warn: legacy owner_ppid fallback for %s; owner_session_id missing\n' "$status_file" >&2
        if [ "$owner_ppid_value" = "$PPID" ]; then
          debug_log "warn" "active_plan_legacy_owner_ppid_fallback status=$status file=$status_file owner_ppid=$owner_ppid_value"
          return 0
        else
          debug_log "info" "skipping_foreign_session_plan_legacy_owner_ppid status=$status file=$status_file owner_ppid=$owner_ppid_value"
          continue
        fi
      elif [ "$owner_ppid_exit" -eq 2 ]; then
        debug_log "info" "skipping_legacy_plan_without_owner status=$status file=$status_file"
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

emit_block_decision() {
  local reason
  reason="$(reason_with_snapshot_meta "$1")"
  DECISION_EMITTED="true"
  emit_block_json "$reason"
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

is_int_value() {
  printf '%s' "$1" | grep -Eq '^-?[0-9]+$'
}

is_mst_snapshot_skill() {
  local skill="$1"
  case "$skill" in
    mst:*|agile|request|resume|recover|review|approve|accept|feedback|cancel|intent|list|inspect|priority|explore|debug|discussion|ideation|plan|agile-plan)
      return 0
      ;;
  esac
  return 1
}

run_snapshot_guard() {
  local reason persisted_block_count

  if [ "${SESSION_ID_RESOLUTION_FAILED:-false}" = "true" ]; then
    if [ "${HOOK_EVENT_NAME:-}" = "Stop" ]; then
      debug_log "allow" "reason=session_id_resolution_failed"
      emit_approve_decision "session_id_resolution_failed"
      exit 0
    fi
    return 0
  fi

  if [ "${SNAPSHOT_PRESENT:-false}" != "true" ]; then
    if [ "${HOOK_EVENT_NAME:-}" != "Stop" ]; then
      debug_log "info" "reason=no_mst_session_fallthrough session_id=${SESSION_ID:-unknown}"
      return 0
    fi
    debug_log "allow" "reason=no-mst-session session_id=${SESSION_ID:-unknown}"
    emit_approve_decision "no-mst-session"
    exit 0
  fi

  if ! is_mst_snapshot_skill "${SNAPSHOT_CURRENT_SKILL:-}"; then
    debug_log "allow" "reason=non_mst_skill skill=${SNAPSHOT_CURRENT_SKILL:-}"
    emit_approve_decision "non-mst-skill"
    exit 0
  fi

  if [ -n "${SNAPSHOT_RETURN_TO_SKILL:-}" ]; then
    reason="[RETURN-TO] snapshot return_to=${SNAPSHOT_RETURN_TO_SKILL}/${SNAPSHOT_RETURN_TO_STEP}. Do NOT stop or pause."
    reason="$reason You MUST immediately return to mst:${SNAPSHOT_RETURN_TO_SKILL} and continue from step ${SNAPSHOT_RETURN_TO_STEP}."
    persisted_block_count="$(persist_block_state "$reason" 2>/dev/null || printf '%s' "$(( ${BLOCK_COUNT:-0} + 1 ))")"
    debug_log "block" "reason=snapshot_return_to skill=$SNAPSHOT_RETURN_TO_SKILL step=$SNAPSHOT_RETURN_TO_STEP block_count=$persisted_block_count"
    emit_block_decision "$reason"
    exit 0
  fi

  if is_int_value "${SNAPSHOT_CURRENT_STEP:-}" && is_int_value "${SNAPSHOT_TOTAL_STEPS:-}" && [ "$SNAPSHOT_CURRENT_STEP" -lt "$SNAPSHOT_TOTAL_STEPS" ]; then
    reason="[SNAPSHOT][step_progress] skill ${SNAPSHOT_CURRENT_SKILL:-unknown} step $((SNAPSHOT_CURRENT_STEP + 1))/${SNAPSHOT_TOTAL_STEPS} 계속 진행."
    reason="$reason Do not stop; emit the next tool call now."
    persisted_block_count="$(persist_block_state "$reason" 2>/dev/null || printf '%s' "$(( ${BLOCK_COUNT:-0} + 1 ))")"
    debug_log "block" "reason=snapshot_step_progress skill=${SNAPSHOT_CURRENT_SKILL:-} step=${SNAPSHOT_CURRENT_STEP:-} total=${SNAPSHOT_TOTAL_STEPS:-} block_count=$persisted_block_count"
    emit_block_decision "$reason"
    exit 0
  fi

  case "${SNAPSHOT_STATUS:-}" in
    committed|completed|done)
      debug_log "allow" "reason=snapshot_completion skill=${SNAPSHOT_CURRENT_SKILL:-}"
      emit_approve_decision "completion"
      exit 0
      ;;
  esac

  emit_unhandled_path_fallback "0"
  exit 0
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
    emit_block_decision "boundary_violation:${boundary_violation}"
    exit 0
  done <<EOF
$(exit_boundary_requests)
EOF
}

run_snapshot_guard

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
    emit_block_decision "$REASON"
    debug_log "block" "reason=state_missing_active_session_detected"
    exit 0
  fi
  append_audit_entry "pass_through" "" "workflow_inactive"
  debug_log "allow" "reason=workflow_inactive state_status=$STATE_STATUS"
  emit_approve_decision "workflow_inactive"
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
  emit_approve_decision "sentinel_allowed"
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

if [ -f "$HOOK_PATTERNS_SCRIPT" ]; then
  HOOK_PATTERNS_JSON=""
  HOOK_PATTERNS_STATUS=0
  set +e
  HOOK_PATTERNS_JSON="$(printf '%s' "$STDIN_RAW" | python3 "$HOOK_PATTERNS_SCRIPT" detect --stdin \
    --last-message "$LAST_ASSISTANT_MESSAGE" \
    --agile-loop-active "$AGILE_LOOP_ACTIVE" \
    --agile-auto-mode-active "$AGILE_AUTO_MODE_ACTIVE" \
    --steering-disabled "$STEERING_DISABLED" \
    --agile-guard-active "$AGILE_GUARD_ACTIVE" \
    --stop-intent-force-block "$STOP_INTENT_FORCE_BLOCK" \
    --allow-pattern-found "$ALLOW_PATTERN_FOUND" \
    --block-count "$BLOCK_COUNT" \
    --next-source "$NEXT_SOURCE" \
    --active-req "$ACTIVE_REQ" \
    --current-skill "$CURRENT_SKILL" \
    --route-allow-whitelist)"
  HOOK_PATTERNS_STATUS=$?
  set -e
  if [ "$HOOK_PATTERNS_STATUS" -eq 0 ] && [ -n "$HOOK_PATTERNS_JSON" ]; then
    HOOK_PATTERNS_INFO=""
    HOOK_PATTERNS_PARSE_STATUS=0
    set +e
    HOOK_PATTERNS_INFO="$(python3 - "$HOOK_PATTERNS_JSON" <<'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)

def field(name):
    value = payload.get(name)
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

print(f"{field('decision')}\t{field('pattern_id')}\t{field('reason')}")
PY
    )"
    HOOK_PATTERNS_PARSE_STATUS=$?
    set -e
    if [ "$HOOK_PATTERNS_PARSE_STATUS" -ne 0 ]; then
      warn_helper_failed "hook_patterns" "$HOOK_PATTERNS_PARSE_STATUS" "invalid_json"
      debug_log "warn" "reason=hook_patterns_json_parse_failed status=$HOOK_PATTERNS_PARSE_STATUS"
      emit_unhandled_path_fallback "$HOOK_PATTERNS_PARSE_STATUS"
      exit 0
    fi
    HOOK_PATTERN_DECISION="$(printf '%s' "$HOOK_PATTERNS_INFO" | cut -f1)"
    HOOK_PATTERN_ID="$(printf '%s' "$HOOK_PATTERNS_INFO" | cut -f2)"
    HOOK_PATTERN_REASON="$(printf '%s' "$HOOK_PATTERNS_INFO" | cut -f3-)"

    if [ "$HOOK_PATTERN_DECISION" = "allow" ] && [ "$HOOK_PATTERN_ID" = "agile_allow_pattern_whitelisted" ]; then
      append_audit_entry "allowed" "" "agile_allow_pattern_whitelisted"
      debug_log "allow" "reason=agile_allow_pattern_whitelisted workflow_active=$WORKFLOW_ACTIVE current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE"
      emit_approve_decision "agile_allow_pattern_whitelisted"
      exit 0
    fi

    if [ "$HOOK_PATTERN_DECISION" = "block" ]; then
      REASON="$HOOK_PATTERN_REASON"
      PERSISTED_BLOCK_COUNT="$(persist_block_state "$REASON" 2>/dev/null || printf '%s' "$((BLOCK_COUNT + 1))")"
      append_block_audit_entry "$REASON"
      emit_block_decision "$REASON"
      case "$HOOK_PATTERN_ID" in
        self_pause_rationalization)
          debug_log "block" "reason=self_pause_rationalization_detected current_skill=$CURRENT_SKILL agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
          ;;
        agile_text_question_in_auto_mode)
          debug_log "block" "reason=agile_text_question_in_auto_mode agile_loop_active=$AGILE_LOOP_ACTIVE agile_auto_mode=$AGILE_AUTO_MODE_ACTIVE current_skill=$CURRENT_SKILL block_count=$PERSISTED_BLOCK_COUNT"
          ;;
        agile_allow_pattern_missing_marker)
          debug_log "block" "reason=agile_allow_pattern_missing_marker current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT"
          ;;
        *)
          debug_log "block" "reason=hook_pattern_detected pattern_id=$HOOK_PATTERN_ID block_count=$PERSISTED_BLOCK_COUNT"
          ;;
      esac
      exit 0
    fi
  else
    warn_helper_failed "hook_patterns" "$HOOK_PATTERNS_STATUS" "path=$(sanitize_log_value "$HOOK_PATTERNS_SCRIPT")"
    debug_log "warn" "reason=hook_patterns_helper_failed status=$HOOK_PATTERNS_STATUS"
    emit_unhandled_path_fallback "$HOOK_PATTERNS_STATUS"
    exit 0
  fi
else
  warn_helper_failed "hook_patterns" "127" "missing path=$(sanitize_log_value "$HOOK_PATTERNS_SCRIPT")"
  debug_log "warn" "reason=hook_patterns_helper_missing path=$HOOK_PATTERNS_SCRIPT"
  emit_unhandled_path_fallback "127"
  exit 0
fi

if [ "$HAS_NEXT_ACTION" != "true" ]; then
  if [ "$STOP_INTENT_FORCE_BLOCK" != "true" ] && [ "$ALLOW_PATTERN_FOUND" = "true" ]; then
    append_audit_entry "allowed" "" "explicit_allow_pattern_no_next_action"
    debug_log "allow" "reason=explicit_allow_pattern_no_next_action workflow_active=$WORKFLOW_ACTIVE"
    emit_approve_decision "explicit_allow_pattern_no_next_action"
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
  emit_block_decision "$REASON"
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
  emit_block_decision "$REASON"
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
emit_block_decision "$REASON"
debug_log "block" "reason=workflow_active current_skill=$CURRENT_SKILL active_req=$ACTIVE_REQ next_skill=$NEXT_SKILL next_source=$NEXT_SOURCE next_auto=$NEXT_AUTO agile_loop_active=$AGILE_LOOP_ACTIVE block_count=$PERSISTED_BLOCK_COUNT last_block_reason=$LAST_BLOCK_REASON"
exit 0
