#!/usr/bin/env bash
set -Eeuo pipefail

# Pre-defined emit functions exposed for source-time test harnesses.
# Claude Code Stop hook strict schema: stdout JSON contains decision + reason only.
if [ -z "${HOOK_JUDGE_TIMEOUT_MARKER:-}" ]; then
  _MST_DECISION_TOKEN="${BASHPID:-$$}-$(date +%s%N 2>/dev/null || printf '%s' "${RANDOM:-0}")"
  HOOK_JUDGE_TIMEOUT_RUNTIME_DIR="${HOOK_JUDGE_TIMEOUT_RUNTIME_DIR:-${TMPDIR:-/tmp}}"
  HOOK_JUDGE_TIMEOUT_MARKER="${HOOK_JUDGE_TIMEOUT_RUNTIME_DIR}/mst-stop-hook-timeout-${_MST_DECISION_TOKEN}.emitted"
  HOOK_JUDGE_TIMEOUT_DONE="${HOOK_JUDGE_TIMEOUT_RUNTIME_DIR}/mst-stop-hook-timeout-${_MST_DECISION_TOKEN}.done"
fi

claim_judge_timeout_emit() {
  if mkdir "$HOOK_JUDGE_TIMEOUT_MARKER" 2>/dev/null; then
    HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED="true"
    return 0
  fi
  return 1
}

emit_approve_json() {
  local reason="${1:-approved}" details_anchor="${2:-}"
  DECISION_EMIT_WRITTEN="false"
  if [ "${HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED:-false}" != "true" ] && ! claim_judge_timeout_emit; then
    return 0
  fi
  [ -n "$details_anchor" ] && printf '[stop-hook] anchor=%s\n' "$details_anchor" >&2
  python3 - "$reason" <<'PY'
import json
import sys
reason = sys.argv[1] if len(sys.argv) > 1 else "approved"
print(json.dumps({"decision": "approve", "reason": reason.strip() or "approved"}, ensure_ascii=False))
PY
  [ -n "${HOOK_JUDGE_TIMEOUT_DONE:-}" ] && : > "$HOOK_JUDGE_TIMEOUT_DONE" 2>/dev/null || true
  HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED="emitted"
  DECISION_EMIT_WRITTEN="true"
}

emit_block_json() {
  local reason="${1:-stop blocked (reason unspecified)}" details_anchor="${2:-}"
  DECISION_EMIT_WRITTEN="false"
  if [ "${HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED:-false}" != "true" ] && ! claim_judge_timeout_emit; then
    return 0
  fi
  [ -n "$details_anchor" ] && printf '[stop-hook] anchor=%s\n' "$details_anchor" >&2
  python3 - "$reason" <<'PY'
import json
import sys
reason = sys.argv[1] if len(sys.argv) > 1 else ""
print(json.dumps({"decision": "block", "reason": reason.strip() or "stop blocked (reason unspecified)"}, ensure_ascii=False))
PY
  [ -n "${HOOK_JUDGE_TIMEOUT_DONE:-}" ] && : > "$HOOK_JUDGE_TIMEOUT_DONE" 2>/dev/null || true
  HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED="emitted"
  DECISION_EMIT_WRITTEN="true"
}

if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

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

if [ ! -f "$script_dir/lib/bootstrap.bash" ] || [ ! -f "$script_dir/lib/logging.bash" ]; then
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
MST_HOOK_LOG_PREFIX="mst-stop-hook"
mkdir -p "$MST_TMP"

STDIN_RAW="$(cat || true)"
if mst_resolve_canonical_mst_session_id "$MST_HOOK_LOG_PREFIX" "allow-stdin-without-env" "$STDIN_RAW"; then
  export MST_SESSION_ID="$MST_RESOLVED_CANONICAL_SESSION_ID"
  MST_LEDGER_HOOK_EVENT="Stop"
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
fi

resolve_mst_script() {
  local candidate
  candidate="$(cd "$script_dir/.." && pwd)/scripts/mst.py"
  [ -f "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  candidate="$(cd "$script_dir/../.." && pwd)/scripts/mst.py"
  [ -f "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  printf '%s\n' "${PROJECT_ROOT}/scripts/mst.py"
}

resolve_hook_judge_timeout_ms() {
  python3 - "$PROJECT_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

def coerce(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
        return value if value > 0 else None
    return None

env_value = coerce(os.environ.get("MST_HOOK_JUDGE_TIMEOUT_MS"))
if env_value is not None:
    print(env_value)
    raise SystemExit(0)

root = Path(sys.argv[1])
for path in (
    root / ".gran-maestro" / "config.resolved.json",
    root / ".gran-maestro" / "config.json",
    root / "templates" / "defaults" / "config.json",
):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        current = data
        for part in "hook.judge_timeout_ms".split("."):
            current = current[part]
        value = coerce(current)
    except Exception:
        value = None
    if value is not None:
        print(value)
        raise SystemExit(0)
print(500)
PY
}

epoch_ms() {
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

kill_process_tree() {
  local pid="$1" child_pids
  child_pids="$(pgrep -P "$pid" 2>/dev/null || true)"
  [ -n "$child_pids" ] && kill -TERM $child_pids 2>/dev/null || true
  kill -TERM "$pid" 2>/dev/null || true
}

append_timeout_event() {
  local budget_ms="$1" observed_ms="$2"
  MST_STOP_HOOK_STDIN_FILE="$stdin_file" python3 - "$PROJECT_ROOT" "$budget_ms" "$observed_ms" <<'PY' 2>/dev/null || true
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
budget_ms = int(sys.argv[2])
observed_ms = int(sys.argv[3])
try:
    payload = json.loads(Path(os.environ["MST_STOP_HOOK_STDIN_FILE"]).read_text(encoding="utf-8") or "{}")
except Exception:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

safe_mst_re = re.compile(r"^MST-[A-Z][A-Z0-9]*-[0-9]+-[0-9]{8}T[0-9]{9}Z-[a-z0-9]{8,}$")
session_id = os.environ.get("MST_SESSION_ID") or payload.get("mst_session_id") or "unknown"
session_id = str(session_id or "unknown")
if "/" in session_id or ".." in session_id or not safe_mst_re.match(session_id):
    session_id = "unknown"
path = root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
path.parent.mkdir(parents=True, exist_ok=True)
entry = {
    "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "event_type": "judge_timeout",
    "session_id": session_id,
    "data": {"budget_ms": budget_ms, "fail_open": True, "hook": "stop-hook", "observed_ms_approx": observed_ms},
}
path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

validate_judge_stdout() {
  local stdout_capture="$1" final_file="$2"
  python3 - "$stdout_capture" "$final_file" <<'PY'
import json
import sys
from pathlib import Path

stdout_path = Path(sys.argv[1])
final_path = Path(sys.argv[2])
try:
    raw = stdout_path.read_text(encoding="utf-8")
except OSError:
    raw = ""
lines = [line for line in raw.splitlines() if line.strip()]
if len(lines) != 1 or "Traceback" in raw:
    raise SystemExit(1)
try:
    payload = json.loads(lines[0])
except Exception:
    raise SystemExit(1)
if not isinstance(payload, dict) or set(payload) != {"decision", "reason"}:
    raise SystemExit(1)
if payload.get("decision") not in {"approve", "block"}:
    raise SystemExit(1)
reason = payload.get("reason")
if not isinstance(reason, str) or not reason.strip():
    raise SystemExit(1)
final_path.write_text(json.dumps({"decision": payload["decision"], "reason": reason}, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

emit_final_file_once() {
  local final_file="$1"
  if claim_judge_timeout_emit; then
    cat "$final_file"
    : > "$HOOK_JUDGE_TIMEOUT_DONE" 2>/dev/null || true
    HOOK_JUDGE_TIMEOUT_EMIT_CLAIMED="emitted"
  fi
}

MST_SCRIPT="$(resolve_mst_script)"
HOOK_JUDGE_TIMEOUT_MS="$(resolve_hook_judge_timeout_ms)"
HOOK_JUDGE_TIMEOUT_RUNTIME_DIR="${TMPDIR:-/tmp}"
HOOK_JUDGE_TIMEOUT_MARKER="${HOOK_JUDGE_TIMEOUT_RUNTIME_DIR}/mst-stop-hook-timeout-$$.emitted"
HOOK_JUDGE_TIMEOUT_DONE="${HOOK_JUDGE_TIMEOUT_RUNTIME_DIR}/mst-stop-hook-timeout-$$.done"
rm -rf "$HOOK_JUDGE_TIMEOUT_MARKER" "$HOOK_JUDGE_TIMEOUT_DONE" 2>/dev/null || true

runtime_dir="$(mktemp -d "${TMPDIR:-/tmp}/mst-stop-hook.XXXXXX")"
stdin_file="${runtime_dir}/stdin.json"
stdout_capture="${runtime_dir}/judge.stdout"
stderr_capture="${runtime_dir}/judge.stderr"
status_file="${runtime_dir}/judge.status"
final_file="${runtime_dir}/final.json"
cleanup_runtime() {
  rm -rf "$runtime_dir" "$HOOK_JUDGE_TIMEOUT_MARKER" "$HOOK_JUDGE_TIMEOUT_DONE" 2>/dev/null || true
}
trap cleanup_runtime EXIT

printf '%s' "$STDIN_RAW" > "$stdin_file"

start_ms="$(epoch_ms)"
(
  set +e
  if [ -n "${MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS:-}" ]; then
    python3 - "${MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS}" <<'PY'
import sys
import time
try:
    ms = max(0, int(str(sys.argv[1]).strip()))
except Exception:
    ms = 0
time.sleep(ms / 1000.0)
PY
  fi
  if [ -n "${MST_STOP_HOOK_TEST_JUDGE_STDOUT+x}" ]; then
    printf '%b' "${MST_STOP_HOOK_TEST_JUDGE_STDOUT}"
    exit "${MST_STOP_HOOK_TEST_JUDGE_EXIT:-0}"
  fi
  export MST_STOP_HOOK_WRAPPER=1
  export MST_STOP_HOOK_PARENT_PPID="$PPID"
  python3 "$MST_SCRIPT" hook stop judge --stdin-file "$stdin_file" --hook-timeout-ms "$HOOK_JUDGE_TIMEOUT_MS"
) >"$stdout_capture" 2>"$stderr_capture" &
judge_pid="$!"

timed_out="false"
while kill -0 "$judge_pid" 2>/dev/null; do
  now_ms="$(epoch_ms)"
  if [ "$((now_ms - start_ms))" -gt "$HOOK_JUDGE_TIMEOUT_MS" ]; then
    timed_out="true"
    kill_process_tree "$judge_pid"
    break
  fi
  sleep 0.01
done

set +e
wait "$judge_pid" 2>/dev/null
judge_status=$?
set -e
printf '%s\n' "$judge_status" > "$status_file"

if [ -s "$stderr_capture" ]; then
  cat "$stderr_capture" >&2
fi

if [ "$timed_out" = "true" ]; then
  observed_ms="$(( $(epoch_ms) - start_ms ))"
  python3 - "$HOOK_JUDGE_TIMEOUT_MS" "$final_file" <<'PY'
import json
import sys
budget = int(sys.argv[1])
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"decision": "approve", "reason": f"hook judge timeout (>{budget}ms) fail-open"}, ensure_ascii=False) + "\n")
PY
  append_timeout_event "$HOOK_JUDGE_TIMEOUT_MS" "$observed_ms"
  printf '[mst-stop-hook] judge_timeout budget_ms=%s observed_ms_approx=%s fail_open=true\n' "$HOOK_JUDGE_TIMEOUT_MS" "$observed_ms" >&2
  emit_final_file_once "$final_file"
  exit 0
fi

if [ "$judge_status" -eq 0 ] && validate_judge_stdout "$stdout_capture" "$final_file"; then
  emit_final_file_once "$final_file"
  exit 0
fi

printf '[mst-stop-hook] judge_invalid_output exit=%s fallback=startup_failure\n' "$judge_status" >&2
python3 - "$final_file" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"decision": "approve", "reason": "hook judge startup failure fail-open"}, ensure_ascii=False) + "\n")
PY
emit_final_file_once "$final_file"
exit 0
