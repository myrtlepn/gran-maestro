#!/usr/bin/env bash
set -euo pipefail

# Claude Code version guard: ${CLAUDE_PLUGIN_ROOT} 미지원 버전 감지 시 fail-open
required_claude_version="0.0.0"  # placeholder: REF-014 후속 검증으로 확정 (도메인 E)
if command -v claude >/dev/null 2>&1; then
  detected_claude_version="$(claude --version 2>/dev/null | head -1 | awk '{print $NF}' || true)"
  if [ -n "$detected_claude_version" ] && [ -n "$required_claude_version" ] && [ "$required_claude_version" != "0.0.0" ]; then
    # version_lt: 사용 가능한 버전 비교 함수가 없으므로 sort -V로 비교
    lower_version="$(printf '%s\n%s\n' "$detected_claude_version" "$required_claude_version" | sort -V | head -1)"
    if [ "$lower_version" = "$detected_claude_version" ] && [ "$detected_claude_version" != "$required_claude_version" ]; then
      echo "[mst-session-init] error: Claude Code $detected_claude_version is below required $required_claude_version for plugin hooks. Update Claude Code." >&2
      # fail-open: 세션은 계속 동작
      exit 0
    fi
  fi
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
STATE_FILE=""
SESSION_BRIDGE_FILE="${MST_TMP}/claude-session-${PPID}.id"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"
MST_HOOK_LOG_PREFIX="mst-session-init"

STDIN_RAW="$(cat || true)"
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
  exit 0
fi
MST_SESSION_ID="$MST_CANONICAL_SESSION_ID"
export MST_SESSION_ID
STATE_FILE="${MST_TMP}/mst-state-${MST_SESSION_ID}.json"
mkdir -p "$MST_TMP"
echo "$PPID" > "${MST_TMP}/mst-session-anchor-${PPID}.pid" 2>/dev/null || true
MST_LEDGER_HOOK_EVENT="SessionStart"
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

# DOD-006 compatibility anchor: sync_plugin_cache() is defined in hooks/lib/session_init_maintenance.bash and sourced here.
# shellcheck source=/dev/null
source "${script_dir}/lib/session_init_runtime.bash"

sync_plugin_cache() {
  session_init_sync_plugin_cache "$@"
}

sync_run_markers() {
  session_init_sync_run_markers "$@"
}

cleanup_stale_markers
sync_plugin_cache
sync_run_markers
clear_next_action_from_plan_json
check_hook_version_mismatch
if ! write_initial_state; then
  echo "[mst-session-init] warning: failed to initialize state file." >&2
fi
if ! write_session_bridge; then
  echo "[mst-session-init] warning: failed to write session bridge file." >&2
fi
if ! init_history_sentinel; then
  echo "[mst-session-init] warning: failed to initialize history ledger sentinels." >&2
fi
if ! append_session_lifecycle_events; then
  echo "[mst-session-init] warning: failed to append session lifecycle history events." >&2
fi

# === Auto-gardening trigger (PLN-475 / REQ-633-T03) ===
# config.gardening.auto_archive.enabled=true일 때만 백그라운드로 실행
# 24h 가드 (session_init_guard_seconds)로 중복 실행 방지
_gardening_trigger_auto_archive() {
  command -v python3 >/dev/null 2>&1 || return 0

  local config_file="${PROJECT_ROOT:-$PWD}/.gran-maestro/config.resolved.json"
  [ -f "$config_file" ] || return 0

  local enabled
  enabled="$(CONFIG_FILE="$config_file" python3 -c "
import json
import os
try:
    d = json.load(open(os.environ['CONFIG_FILE']))
    v = d.get('gardening', {}).get('auto_archive', {}).get('enabled', False)
    print('true' if v else 'false')
except Exception:
    print('false')
" 2>/dev/null || printf 'false')"
  [ "$enabled" = "true" ] || return 0

  local guard_seconds
  guard_seconds="$(CONFIG_FILE="$config_file" python3 -c "
import json
import os
try:
    d = json.load(open(os.environ['CONFIG_FILE']))
    print(d.get('gardening', {}).get('auto_archive', {}).get('session_init_guard_seconds', 86400))
except Exception:
    print(86400)
" 2>/dev/null || printf '86400')"
  case "$guard_seconds" in
    ''|*[!0-9]*) guard_seconds=86400 ;;
  esac

  local stamp_file="${PROJECT_ROOT:-$PWD}/.gran-maestro/tmp/gardening-last-run"
  local now last_run
  now="$(date +%s 2>/dev/null || printf '0')"
  last_run="$(cat "$stamp_file" 2>/dev/null || printf '0')"
  case "$last_run" in
    ''|*[!0-9]*) last_run=0 ;;
  esac
  case "$now" in
    ''|*[!0-9]*) now=0 ;;
  esac

  if [ "$((now - last_run))" -lt "$guard_seconds" ]; then
    return 0
  fi

  mkdir -p "$(dirname "$stamp_file")" 2>/dev/null || return 0
  printf '%s\n' "$now" > "$stamp_file" 2>/dev/null || return 0

  local plugin_root="${PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
  (python3 "$plugin_root/scripts/mst.py" gardening auto-archive --silent >/dev/null 2>&1 &)
  return 0
}
_gardening_trigger_auto_archive || true

exit 0
