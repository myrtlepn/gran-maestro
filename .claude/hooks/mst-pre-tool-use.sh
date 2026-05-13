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

case "$script_dir" in
  *'${CLAUDE_PLUGIN_ROOT}'*)
    printf '[mst-hook] warning: unexpected execution path. Possible ${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open.\n' >&2
    exit 0
    ;;
esac

if [ ! -f "$script_dir/lib/bootstrap.bash" ] || [ ! -f "$script_dir/lib/session_identity.bash" ] || [ ! -f "$script_dir/lib/logging.bash" ]; then
  printf '[mst-hook] warning: unexpected execution path. Possible ${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open.\n' >&2
  exit 0
fi

# shellcheck source=/dev/null
source "$script_dir/lib/bootstrap.bash"
# shellcheck source=/dev/null
source "$script_dir/lib/session_identity.bash"
# shellcheck source=/dev/null
source "$script_dir/lib/logging.bash"

mst_validate_hook_script_dir_or_exit "$script_dir"
PROJECT_ROOT="$(mst_resolve_project_root)"
MST_TMP="${PROJECT_ROOT}/.gran-maestro/tmp"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"
BOUNDARY_LOG_FILE="${PROJECT_ROOT}/.gran-maestro/logs/boundary-guard.log"
HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
MST_HOOK_LOG_PREFIX="mst-pre-tool-use"

STDIN_RAW="$(cat || true)"
if ! MST_HOOK_STDIN_RAW="$STDIN_RAW" python3 - <<'PY' >/dev/null 2>&1
import json
import os
import sys

raw = os.environ.get("MST_HOOK_STDIN_RAW", "")
try:
    payload = json.loads(raw or "{}")
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(payload, dict) else 1)
PY
then
  printf '[policy-block] payload_parse_failure invalid hook payload JSON\n' >&2
  exit 2
fi
MST_CANONICAL_SESSION_ID=""
if mst_resolve_canonical_mst_session_id "$MST_HOOK_LOG_PREFIX" "require-env-for-stdin" "$STDIN_RAW"; then
  MST_CANONICAL_SESSION_ID="$MST_RESOLVED_CANONICAL_SESSION_ID"
  MST_SESSION_RESOLUTION_STATUS=0
else
  MST_SESSION_RESOLUTION_STATUS=$?
fi
if [ "$MST_SESSION_RESOLUTION_STATUS" -eq 1 ]; then
  exit 1
fi
if [ "$MST_SESSION_RESOLUTION_STATUS" -ne 0 ]; then
  mkdir -p "$MST_TMP" 2>/dev/null || true
  mst_warn_legacy_session_id_mismatch_once "$PROJECT_ROOT" "$MST_TMP" "$STDIN_RAW" "$MST_HOOK_LOG_PREFIX" "$PPID" ""
  exit 0
fi
MST_SESSION_ID="$MST_CANONICAL_SESSION_ID"
export MST_SESSION_ID
mkdir -p "$MST_TMP"
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

if [ "${MST_PRE_TOOL_USE_TEST_BOOTSTRAP:-0}" != "1" ] && [[ ! "$STDIN_RAW" =~ \"tool_name\"[[:space:]]*:[[:space:]]*\"Skill\" ]]; then
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
import re

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

STRUCTURED_RE = re.compile(
    r"^MST-[A-Z][A-Z0-9]*-[0-9]+-[0-9]{8}T[0-9]{9}Z-[a-z0-9]{8,}$"
)


def structured_session_id(value):
    text = clean(value)
    if not text or "/" in text or ".." in text:
        return ""
    return text if STRUCTURED_RE.match(text) else ""


session_id = structured_session_id(os.environ.get("MST_SESSION_ID")) or structured_session_id(payload.get("mst_session_id"))
claude_session_id = clean(payload.get("session_id"))
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
    "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
        session_id,
        claude_session_id,
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
MST_HOOK_CLAUDE_SESSION_ID="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f2)"
MST_HOOK_TOOL_NAME="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f3)"
MST_HOOK_FILE_PATH="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f4)"
MST_HOOK_COMMAND="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f5)"
MST_HOOK_SKILL_NAME="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f6)"
MST_HOOK_ARGS_TEXT="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f7)"
MST_HOOK_TOOL_INPUT_CANONICAL="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f8)"
MST_HOOK_STDIN_DIGEST="$(printf '%s' "$HOOK_PAYLOAD_INFO" | cut -f9)"
export MST_HOOK_TOOL_NAME MST_HOOK_FILE_PATH MST_HOOK_COMMAND MST_HOOK_SKILL_NAME
export MST_HOOK_ARGS_TEXT MST_HOOK_TOOL_INPUT_CANONICAL MST_HOOK_STDIN_DIGEST MST_HOOK_CLAUDE_SESSION_ID
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
  return 0
}

emit_block_json() {
  local reason="$1"
  local detail_text="${2:-}"
  local recovery_command="${3:-}"
  local retry_criterion="${4:-}"
  local log_location="${5:-}"
  python3 - "$reason" "$detail_text" "$recovery_command" "$retry_criterion" "$log_location" <<'PYJSON'
import json
import sys

reason = str(sys.argv[1] or "").strip() or "boundary_violation:unknown"
summary = str(sys.argv[2] or "").strip()
recovery_command = str(sys.argv[3] or "").strip()
retry_criterion = str(sys.argv[4] or "").strip()
log_location = str(sys.argv[5] or "").strip()

payload = {"decision": "block", "reason": reason}
details = {}
if summary:
    details["summary"] = summary
if recovery_command:
    details["recovery_command"] = recovery_command
if retry_criterion:
    details["retry_criterion"] = retry_criterion
if log_location:
    details["log_location"] = log_location
if details:
    payload["details"] = details

print(json.dumps(payload, ensure_ascii=False))
PYJSON
}

trim_text() {
  local value="${1:-}"
  printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

first_line_trimmed() {
  local value="${1:-}" first_line
  first_line="$(printf '%s' "$value" | head -n 1 2>/dev/null || true)"
  trim_text "$first_line"
}

REPAIR_LAST_STATUS=""
REPAIR_LAST_STDERR_HEAD=""
REPAIR_LAST_REASON_TOKEN=""
REPAIR_PRE_DIAGNOSIS=""
REPAIR_LAST_RECOVERY_COMMAND=""
REPAIR_LAST_TASK_ID=""
REPAIR_LAST_TASK_BRANCH=""
REPAIR_LAST_WORKTREE_PATH=""
REPAIR_ATTEMPTED="false"

reset_repair_state() {
  REPAIR_LAST_STATUS=""
  REPAIR_LAST_STDERR_HEAD=""
  REPAIR_LAST_REASON_TOKEN=""
  REPAIR_PRE_DIAGNOSIS=""
  REPAIR_LAST_RECOVERY_COMMAND=""
  REPAIR_LAST_TASK_ID=""
  REPAIR_LAST_TASK_BRANCH=""
  REPAIR_LAST_WORKTREE_PATH=""
}

diagnose_repair_blocker() {
  local _req_id="$1" _task_id="$2" _task_branch="$3" _detected_base="$4" _worktree_path="$5"
  local branch_hit="" registered_path=""

  if [ -z "$_detected_base" ]; then
    printf 'base_not_verified\n'
    return 0
  fi
  if ! (cd "$PROJECT_ROOT" && git rev-parse --verify "$_detected_base" >/dev/null 2>&1); then
    printf 'base_not_verified\n'
    return 0
  fi

  branch_hit="$(cd "$PROJECT_ROOT" && git branch --list "$_task_branch" 2>/dev/null || true)"
  if [ -n "$(trim_text "$branch_hit")" ]; then
    printf 'branch_conflict\n'
    return 0
  fi

  registered_path="$(
    cd "$PROJECT_ROOT" && git worktree list --porcelain 2>/dev/null | awk -v target_branch="refs/heads/${_task_branch}" '
      $1 == "worktree" { current_path = $2 }
      $1 == "branch" && $2 == target_branch { print current_path; exit }
    ' || true
  )"
  if [ -n "$(trim_text "$registered_path")" ] && [ "$(trim_text "$registered_path")" != "$_worktree_path" ]; then
    printf 'worktree_registered_elsewhere\n'
    return 0
  fi

  printf 'none\n'
}

resolve_repair_block_reason() {
  if [ -n "${REPAIR_PRE_DIAGNOSIS:-}" ] && [ "${REPAIR_PRE_DIAGNOSIS:-}" != "none" ]; then
    printf '%s\n' "$REPAIR_PRE_DIAGNOSIS"
    return 0
  fi
  if [ -n "${REPAIR_LAST_REASON_TOKEN:-}" ]; then
    printf '%s\n' "$REPAIR_LAST_REASON_TOKEN"
    return 0
  fi
  printf 'repair_failed\n'
}

build_repair_detail_summary() {
  local reason_token="$1" boundary_violation="$2"
  case "$reason_token" in
    base_not_verified)
      printf '워크트리 복구 사전 진단 실패: 기준 브랜치(%s)를 확인할 수 없습니다.\n기준 브랜치 ref를 확인한 뒤 동일 도구를 다시 호출하세요.' "${DETECTED_BASE:-unknown}"
      ;;
    branch_conflict)
      printf '워크트리 복구 사전 진단 실패: 대상 브랜치(%s)가 이미 존재합니다.\n브랜치 충돌 해소 후 동일 도구를 다시 호출하세요.' "${REPAIR_LAST_TASK_BRANCH:-unknown}"
      ;;
    worktree_registered_elsewhere)
      printf '워크트리 복구 사전 진단 실패: 브랜치(%s)가 다른 경로에 이미 연결되어 있습니다.\n기존 worktree 정리 후 동일 도구를 다시 호출하세요.' "${REPAIR_LAST_TASK_BRANCH:-unknown}"
      ;;
    create_failed:*)
      if [ -n "${REPAIR_LAST_STDERR_HEAD:-}" ]; then
        printf '워크트리 자동 생성 실패: %s\nstderr: %s' "$reason_token" "${REPAIR_LAST_STDERR_HEAD}"
      else
        printf '워크트리 자동 생성 실패: %s\nstderr 정보가 비어 있습니다.' "$reason_token"
      fi
      ;;
    repair_failed)
      printf '워크트리 자동 복구 1회 시도가 완료되지 않았습니다.\n원인 분류 정보가 부족하여 수동 복구 명령 실행이 필요합니다.'
      ;;
    *)
      printf '경계 조건 위반이 감지되었습니다: %s\n로그를 확인한 뒤 동일 도구를 다시 호출하세요.' "${boundary_violation:-unknown}"
      ;;
  esac
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
  local task_id worktree_path task_branch create_status create_stderr_file create_stderr_head pre_diagnosis

  reset_repair_state
  [ -n "$detected_base" ] || {
    REPAIR_LAST_REASON_TOKEN="repair_failed"
    return 1
  }

  while IFS= read -r task_id; do
    [ -n "$task_id" ] || continue
    worktree_path="${PROJECT_ROOT}/.gran-maestro/worktrees/${req_id}-${task_id}"
    task_branch="$(cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree branch-name --req "$req_id" --task "$task_id" --base "$detected_base")"
    REPAIR_LAST_TASK_ID="$task_id"
    REPAIR_LAST_TASK_BRANCH="$task_branch"
    REPAIR_LAST_WORKTREE_PATH="$worktree_path"
    REPAIR_LAST_RECOVERY_COMMAND="mst.py worktree create --path \"$worktree_path\" --branch \"$task_branch\" --base \"$detected_base\""

    pre_diagnosis="$(diagnose_repair_blocker "$req_id" "$task_id" "$task_branch" "$detected_base" "$worktree_path")"
    REPAIR_PRE_DIAGNOSIS="$pre_diagnosis"
    if [ "$pre_diagnosis" != "none" ]; then
      REPAIR_LAST_REASON_TOKEN="$pre_diagnosis"
      debug_log "boundary_entry_repair_pre_diagnosis" "req=$req_id task=$task_id diagnosis=$pre_diagnosis"
      continue
    fi

    if [ ! -e "${worktree_path}/.git" ]; then
      create_stderr_file="$(mktemp "${MST_TMP}/boundary-create-stderr.XXXXXX" 2>/dev/null || true)"
      set +e
      if [ -n "$create_stderr_file" ]; then
        cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree create --path "$worktree_path" --branch "$task_branch" --base "$detected_base" >/dev/null 2>"$create_stderr_file"
      else
        cd "$PROJECT_ROOT" && python3 "$MST_SCRIPT" worktree create --path "$worktree_path" --branch "$task_branch" --base "$detected_base" >/dev/null 2>/dev/null
      fi
      create_status=$?
      set -e
      create_stderr_head=""
      if [ -n "$create_stderr_file" ] && [ -f "$create_stderr_file" ]; then
        create_stderr_head="$(first_line_trimmed "$(cat "$create_stderr_file" 2>/dev/null || true)")"
        rm -f "$create_stderr_file" 2>/dev/null || true
      fi
      if [ "$create_status" -ne 0 ]; then
        REPAIR_LAST_STATUS="$create_status"
        REPAIR_LAST_STDERR_HEAD="$create_stderr_head"
        REPAIR_LAST_REASON_TOKEN="create_failed:${create_status}"
        debug_log "boundary_entry_repair_failed" "req=$req_id task=$task_id status=$create_status stderr=$(sanitize_log_value "$create_stderr_head")"
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

if [ "${MST_PRE_TOOL_USE_SOURCE_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

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

if [ "$BOUNDARY_OK" = "true" ]; then
  debug_log "boundary_entry_pass" "req=$REQ_ID"
  exit 0
fi

if [ "$BOUNDARY_VIOLATION" = "worktree_missing" ] && [ "$BOUNDARY_RETRY" = "true" ]; then
  REPAIR_ATTEMPTED="true"
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
BLOCK_REASON="boundary_violation:${BOUNDARY_VIOLATION}"
BLOCK_DETAIL_TEXT="경계 조건 위반이 감지되었습니다: ${BOUNDARY_VIOLATION}\n로그를 확인한 뒤 동일 도구를 다시 호출하세요."
BLOCK_RECOVERY_COMMAND=""
BLOCK_RETRY_CRITERION=""
if [ "$REPAIR_ATTEMPTED" = "true" ] && [ "$BOUNDARY_VIOLATION" = "worktree_missing" ]; then
  BLOCK_REASON="$(resolve_repair_block_reason)"
  BLOCK_DETAIL_TEXT="$(build_repair_detail_summary "$BLOCK_REASON" "$BOUNDARY_VIOLATION")"
  BLOCK_RECOVERY_COMMAND="${REPAIR_LAST_RECOVERY_COMMAND:-}"
  if [ -n "$BLOCK_RECOVERY_COMMAND" ]; then
    BLOCK_RETRY_CRITERION="복구 명령 1회 실행 후 동일 도구 재호출"
  fi
fi
emit_block_json "$BLOCK_REASON" "$BLOCK_DETAIL_TEXT" "$BLOCK_RECOVERY_COMMAND" "$BLOCK_RETRY_CRITERION" ".gran-maestro/logs/boundary-guard.log"
exit 0
