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
STATE_FILE=""
SESSION_BRIDGE_FILE="${MST_TMP}/claude-session-${PPID}.id"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"

STDIN_RAW="$(cat || true)"
is_structured_mst_session_id() {
  local value="${1:-}"
  case "$value" in
    ''|*/*|*'..'*|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
  [[ "$value" =~ ^MST-[A-Z][A-Z0-9]*-[0-9]+-[0-9]{8}T[0-9]{9}Z-[a-z0-9]{8,}$ ]]
}

extract_stdin_mst_session_id_literal() {
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
      if is_structured_mst_session_id "$value"; then
        printf '%s\n' "$value"
      fi
      ;;
  esac
}

resolve_canonical_mst_session_id_or_exit() {
  local env_raw="${MST_SESSION_ID:-}" env_id="" stdin_id=""
  if [ -n "$env_raw" ] && is_structured_mst_session_id "$env_raw"; then
    env_id="$env_raw"
  fi
  stdin_id="$(extract_stdin_mst_session_id_literal "$STDIN_RAW" || true)"

  if [ -n "$env_id" ] && [ -n "$stdin_id" ] && [ "$env_id" != "$stdin_id" ]; then
    echo "[mst-session-init] error: mst_session_id mismatch: env:MST_SESSION_ID=$env_id stdin:mst_session_id=$stdin_id" >&2
    return 1
  fi
  if [ -n "$env_raw" ] && [ -z "$env_id" ]; then
    echo "[mst-session-init] diagnostic: ignoring invalid MST_SESSION_ID; no canonical parent mst_session_id." >&2
    return 2
  fi
  if [ -n "$env_id" ]; then
    MST_CANONICAL_SESSION_ID="$env_id"
    return 0
  fi
  if [ -n "$stdin_id" ]; then
    MST_CANONICAL_SESSION_ID="$stdin_id"
    return 0
  fi

  echo "[mst-session-init] diagnostic: missing canonical parent MST_SESSION_ID/mst_session_id; no hook identity mutation." >&2
  return 2
}

MST_CANONICAL_SESSION_ID=""
if resolve_canonical_mst_session_id_or_exit; then
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

resolve_history_lib() {
  local script_dir candidate
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
if [ -n "$HISTORY_LIB" ]; then
  source "$HISTORY_LIB"
else
  echo "[mst-session-init] warning: history library not found; skipped history sentinel initialization." >&2
fi


debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
}

stdin_session_id() {
  printf '%s\n' "${MST_SESSION_ID:-}"
}

utc_timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ
}

real_dir_path() {
  local path="$1"
  [ -d "$path" ] || return 1
  (
    cd "$path" 2>/dev/null || exit 1
    pwd -P
  )
}

path_within_boundary() {
  local base="$1" target="$2" allow_equal="${3:-0}"
  local base_real target_real target_parent target_name

  base_real="$(real_dir_path "$base")" || return 1
  if [ -d "$target" ]; then
    target_real="$(real_dir_path "$target")" || return 1
  else
    target_parent="$(dirname "$target")"
    target_name="$(basename "$target")"
    target_parent="$(real_dir_path "$target_parent")" || return 1
    target_real="${target_parent}/${target_name}"
  fi

  if [ "$allow_equal" = "1" ] && [ "$target_real" = "$base_real" ]; then
    return 0
  fi

  case "$target_real" in
    "$base_real"/*) return 0 ;;
  esac

  return 1
}

init_history_sentinel() {
  local session_id
  [ -n "${HISTORY_LIB:-}" ] || return 0
  session_id="$(stdin_session_id)"
  [ -n "$session_id" ] || return 0
  mst_history_init_session "$PROJECT_ROOT" "$session_id"
}

append_session_lifecycle_events() {
  local session_id timestamp_enter timestamp_state timestamp_exit event_enter event_state event_exit skill session_dir history_file
  [ -n "${HISTORY_LIB:-}" ] || return 0
  declare -F mst_history_append_events_batch >/dev/null 2>&1 || return 0
  session_id="$(stdin_session_id)"
  [ -n "$session_id" ] || return 0

  skill="mst:session-init"
  session_dir="$(mst_history_session_dir "$PROJECT_ROOT" "$session_id")"
  history_file="${session_dir}/history.ndjson"
  mkdir -p "$session_dir" || return 1
  [ -f "$history_file" ] || : > "$history_file" || return 1
  timestamp_enter="$(mst_history_timestamp)"
  timestamp_state="$(mst_history_timestamp)"
  timestamp_exit="$(mst_history_timestamp)"

  event_enter="$(printf '{"type":"skill_enter","skill":"%s","timestamp":"%s"}' "$(mst_history_json_escape "$skill")" "$timestamp_enter")"
  event_state="$(printf '{"type":"state_change","state":"session_initialized","timestamp":"%s"}' "$timestamp_state")"
  event_exit="$(printf '{"type":"skill_exit","skill":"%s","timestamp":"%s"}' "$(mst_history_json_escape "$skill")" "$timestamp_exit")"
  mst_history_append_events_batch "$PROJECT_ROOT" "$session_id" "$event_enter" "$event_state" "$event_exit"
}

clear_next_action_from_plan_json() {
  local clear_info clear_status clear_count clear_scanned clear_failed
  local plans_root="${PROJECT_ROOT}/.gran-maestro/plans"

  if [ ! -d "$PROJECT_ROOT" ]; then
    debug_log "session_init_plan_cleanup" "status=no_project_root cleared=0 scanned=0 failed=0 project_root=$PROJECT_ROOT"
    return 0
  fi

  if [ ! -d "$plans_root" ]; then
    debug_log "session_init_plan_cleanup" "status=no_plans_root cleared=0 scanned=0 failed=0 project_root=$PROJECT_ROOT"
    return 0
  fi

  clear_info="$(python3 -c 'import glob, json, os, sys

project_root = sys.argv[1]

if not project_root or not os.path.isdir(project_root):
    print("no_project_root\t0\t0\t0")
    sys.exit(0)

plans_root = os.path.join(project_root, ".gran-maestro", "plans")
if not os.path.isdir(plans_root):
    print("no_plans_root\t0\t0\t0")
    sys.exit(0)

targets = sorted(glob.glob(os.path.join(plans_root, "PLN-*", "plan.json")), reverse=True)
cleared = 0
scanned = 0
failed = 0

for path in targets:
    scanned += 1
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        failed += 1
        continue

    if not isinstance(data, dict) or "next_action" not in data:
        continue

    data.pop("next_action", None)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as wf:
            json.dump(data, wf, ensure_ascii=False, indent=2)
            wf.write("\n")
        os.replace(tmp_path, path)
        cleared += 1
    except Exception:
        failed += 1
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        continue

print(f"ok\t{cleared}\t{scanned}\t{failed}")
' "$PROJECT_ROOT" 2>/dev/null || echo "error\t0\t0\t1")"

  clear_status="$(printf '%s' "$clear_info" | cut -f1)"
  clear_count="$(printf '%s' "$clear_info" | cut -f2)"
  clear_scanned="$(printf '%s' "$clear_info" | cut -f3)"
  clear_failed="$(printf '%s' "$clear_info" | cut -f4)"

  if ! [[ "$clear_count" =~ ^[0-9]+$ ]]; then
    clear_count=0
  fi
  if ! [[ "$clear_scanned" =~ ^[0-9]+$ ]]; then
    clear_scanned=0
  fi
  if ! [[ "$clear_failed" =~ ^[0-9]+$ ]]; then
    clear_failed=0
  fi

  if [ "$clear_status" = "error" ] || [ "$clear_failed" -gt 0 ]; then
    echo "[mst-session-init] warning: failed to clear next_action from plan.json (status=$clear_status failed=$clear_failed scanned=$clear_scanned)." >&2
  fi

  debug_log "session_init_plan_cleanup" "status=$clear_status cleared=$clear_count scanned=$clear_scanned failed=$clear_failed project_root=$PROJECT_ROOT"
}

read_plugin_version() {
  local version

  if [ "${MST_PLUGIN_VERSION_READY:-0}" = "1" ]; then
    printf '%s\n' "${MST_PLUGIN_VERSION:-}"
    return 0
  fi

  version="$(python3 - "$PROJECT_ROOT" <<'PY' 2>/dev/null || true
import json
import os
import sys

project_root = sys.argv[1]
paths = [
    os.path.join(project_root, ".claude-plugin", "plugin.json"),
]

for path in paths:
    if not os.path.isfile(path):
        continue
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        continue

    version = data.get("version") if isinstance(data, dict) else ""
    if isinstance(version, str) and version.strip():
        print(version.strip())
        raise SystemExit(0)

print("")
PY
)"
  MST_PLUGIN_VERSION="$version"
  MST_PLUGIN_VERSION_READY=1
  printf '%s\n' "$version"
}

read_hook_version() {
  local version_file="${PROJECT_ROOT}/.claude/hooks/.mst-hook-version"
  if [ -f "$version_file" ]; then
    tr -d '[:space:]' < "$version_file" 2>/dev/null || true
    return 0
  fi
  printf ''
}

_auto_migrate_acquire_lock() {
  local lock_path="$1"
  local stale_secs="${2:-120}"
  mkdir -p "$(dirname "$lock_path")" 2>/dev/null || return 1
  if [ -e "$lock_path" ]; then
    local now mtime age
    now="$(date +%s 2>/dev/null || printf '0')"
    mtime="$(stat -f %m "$lock_path" 2>/dev/null || stat -c %Y "$lock_path" 2>/dev/null || printf '0')"
    age=$((now - mtime))
    if [ "$age" -gt "$stale_secs" ]; then
      rm -f "$lock_path" 2>/dev/null || return 1
    else
      return 1
    fi
  fi
  ( set -C; printf '%s\n' "$$" > "$lock_path" ) 2>/dev/null || return 1
  return 0
}

_auto_migrate_release_lock() {
  rm -f "$1" 2>/dev/null || true
}

_auto_migrate_failed_recently() {
  local marker="$1"
  local ttl_secs="${2:-600}"
  [ -f "$marker" ] || return 1
  local now mtime age
  now="$(date +%s 2>/dev/null || printf '0')"
  mtime="$(stat -f %m "$marker" 2>/dev/null || stat -c %Y "$marker" 2>/dev/null || printf '0')"
  age=$((now - mtime))
  if [ "$age" -gt "$ttl_secs" ]; then
    rm -f "$marker" 2>/dev/null || true
    return 1
  fi
  return 0
}

_auto_migrate_mark_failed() {
  local marker="$1"
  mkdir -p "$(dirname "$marker")" 2>/dev/null || return 1
  printf '%s\n' "$(date +%s 2>/dev/null || printf '0')" > "$marker" 2>/dev/null || true
}

_auto_migrate_clear_failed() {
  rm -f "$1" 2>/dev/null || true
}

# DOD-016: append migration.log with simple rotation cap (50KB)
_auto_migrate_log() {
  local log_path="$1"
  local message="$2"
  mkdir -p "$(dirname "$log_path")" 2>/dev/null || return 0
  if [ -f "$log_path" ]; then
    local size
    size="$(wc -c < "$log_path" 2>/dev/null | tr -d ' ')"
    case "$size" in
      ''|*[!0-9]*) size=0 ;;
    esac
    if [ "$size" -gt 51200 ]; then
      tail -c 25600 "$log_path" > "${log_path}.rot" 2>/dev/null && \
        mv "${log_path}.rot" "$log_path" 2>/dev/null || true
    fi
  fi
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf 'unknown-time')" "$message" \
    >> "$log_path" 2>/dev/null || true
}

# DOD-015: detect mst hook entries in user-level ~/.claude/settings.json
_auto_migrate_detect_user_settings_conflict() {
  local user_settings="${HOME}/.claude/settings.json"
  [ -f "$user_settings" ] || return 0
  if grep -qE 'mst-(stop-hook|session-init|pre-tool-use|auto-chain-context)\.sh' "$user_settings" 2>/dev/null; then
    echo "[mst-session-init] warning: user-level ~/.claude/settings.json contains mst hook entries. These may conflict with plugin hooks.json self-registration. Manual cleanup recommended (mst will not auto-modify user-level settings)." >&2
  fi
}

# DOD-014: detect duplicate hook invocation in same SessionStart (per-PPID marker)
_auto_migrate_detect_dup_hook() {
  local marker_dir="${PROJECT_ROOT:-$(pwd)}/.gran-maestro/tmp"
  local marker="${marker_dir}/session-init-${PPID:-0}.lock"
  mkdir -p "$marker_dir" 2>/dev/null || return 1
  if [ -f "$marker" ]; then
    local now mtime age
    now="$(date +%s 2>/dev/null || printf '0')"
    mtime="$(stat -f %m "$marker" 2>/dev/null || stat -c %Y "$marker" 2>/dev/null || printf '0')"
    age=$((now - mtime))
    if [ "$age" -lt 30 ]; then
      return 0
    fi
  fi
  printf '%s\n' "$(date +%s 2>/dev/null || printf '0')" > "$marker" 2>/dev/null || true
  return 1
}

check_hook_version_mismatch() {
  local plugin_version hook_version
  plugin_version="$(read_plugin_version)"
  hook_version="$(read_hook_version)"

  local migration_log="${PROJECT_ROOT:-$(pwd)}/.gran-maestro/migration.log"

  if [ -z "$plugin_version" ] || [ "$plugin_version" = "$hook_version" ]; then
    return 0
  fi

  local hook_display
  hook_display="${hook_version:-missing}"
  echo "[mst-session-init] warning: hook version mismatch (hook=$hook_display plugin=$plugin_version). Auto-migration will attempt cleanup." >&2
  debug_log "session_init_version_mismatch" "hook=$hook_display plugin=$plugin_version"
  _auto_migrate_log "$migration_log" "mismatch_detected hook=$hook_display plugin=$plugin_version"

  # DOD-015: 재귀 가드 — 자식 프로세스가 자동 트리거 진입 시도면 즉시 차단
  if [ "${MST_AUTO_MIGRATE_IN_PROGRESS:-0}" = "1" ]; then
    echo "[mst-session-init] auto-migration skipped (recursive call detected via MST_AUTO_MIGRATE_IN_PROGRESS=1)." >&2
    _auto_migrate_log "$migration_log" "recursive_call_blocked"
    return 0
  fi

  # DOD-015: 사용자 레벨 settings 충돌 detection (안내만, 자동 제거 X)
  _auto_migrate_detect_user_settings_conflict

  # G4: 환경 detection — claude CLI 부재 또는 명시적 disable 시 skip
  if [ "${MST_DISABLE_AUTO_MIGRATE:-0}" = "1" ]; then
    echo "[mst-session-init] auto-migration skipped (MST_DISABLE_AUTO_MIGRATE=1). Run /mst:on manually to sync." >&2
    _auto_migrate_log "$migration_log" "skipped reason=disabled_env"
    return 0
  fi

  if ! command -v timeout >/dev/null 2>&1; then
    echo "[mst-session-init] auto-migration skipped (timeout command not in PATH). Run /mst:on manually to sync." >&2
    _auto_migrate_log "$migration_log" "skipped reason=timeout_missing"
    return 0
  fi

  # G3: anti-loop — 직전 마이그레이션 실패 marker 존재 시 skip (TTL 600s)
  local migration_failed_marker="${PROJECT_ROOT:-$(pwd)}/.gran-maestro/tmp/migration-failed"
  if _auto_migrate_failed_recently "$migration_failed_marker" 600; then
    echo "[mst-session-init] auto-migration skipped (recent attempt failed within 10min window). Run /mst:on manually." >&2
    _auto_migrate_log "$migration_log" "skipped reason=recent_failure"
    return 0
  fi

  # G1: 동시성 lock — 단일 실행 보장
  local migration_lock="${PROJECT_ROOT:-$(pwd)}/.gran-maestro/tmp/migration.lock"
  if ! _auto_migrate_acquire_lock "$migration_lock" 120; then
    debug_log "session_init_auto_migrate_skipped" "another in progress"
    _auto_migrate_log "$migration_log" "skipped reason=lock_held"
    return 0
  fi

  # G2: fail-open — 30s timeout + cleanup 실행. 실패해도 SessionStart hook은 exit 0.
  local plugin_root="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
  if [ -z "$plugin_root" ]; then
    plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  local mst_script="${plugin_root}/scripts/mst.py"

  if [ ! -f "$mst_script" ]; then
    debug_log "session_init_auto_migrate_skipped" "mst.py missing path=$mst_script"
    _auto_migrate_log "$migration_log" "skipped reason=mst_script_missing"
    _auto_migrate_release_lock "$migration_lock"
    return 0
  fi

  # DOD-015: cleanup 호출 시 자식 프로세스에 재귀 가드 export
  if MST_AUTO_MIGRATE_IN_PROGRESS=1 timeout 30 python3 "$mst_script" on cleanup --silent >/dev/null 2>&1; then
    _auto_migrate_clear_failed "$migration_failed_marker"
    debug_log "session_init_auto_migrate_ok" "plugin=$plugin_version"
    _auto_migrate_log "$migration_log" "auto_migration_ok plugin=$plugin_version"
  else
    _auto_migrate_mark_failed "$migration_failed_marker"
    debug_log "session_init_auto_migrate_failed" "plugin=$plugin_version"
    echo "[mst-session-init] auto-migration failed; marker recorded (Run /mst:on manually)." >&2
    _auto_migrate_log "$migration_log" "auto_migration_failed plugin=$plugin_version"
  fi

  _auto_migrate_release_lock "$migration_lock"
  return 0
}

cleanup_stale_markers() {
  local tmp_dir my_ppid state_file pid_str
  tmp_dir="${MST_TMP}"

  rm -f \
    "${tmp_dir}/mst-call-stack-"*.json \
    "${tmp_dir}/mst-call-stack-"*.json.tmp \
    "${tmp_dir}/mst-pending-continuation-"* \
    "${tmp_dir}/mst-pending-continuation-"*.tmp \
    "${tmp_dir}/mst-next-action-"*.json \
    "${tmp_dir}/mst-next-action-"*.json.tmp \
    "${tmp_dir}/mst-next-action-count-"* \
    "${tmp_dir}/mst-next-action-count-"*.tmp \
    "${tmp_dir}/mst-next-action-state-"* \
    "${tmp_dir}/mst-next-action-state-"*.tmp \
    "${tmp_dir}/mst-stop-hook-count-"* \
    "${tmp_dir}/mst-stop-hook-count-"*.tmp \
    "${tmp_dir}/mst-hook-debug-"*.log \
    "${tmp_dir}/mst-hook-check-done-"* \
    "${tmp_dir}/mst-transcript-"*.path \
    2>/dev/null || true

  # PLN-479 T02: multi-terminal 시 타 세션 state 파괴 방지
  # DOD-003: structured MST_SESSION_ID state는 canonical 세션별 파일이므로 삭제하지 않는다.
  my_ppid="${PPID}"
  for state_file in "${tmp_dir}/mst-state-"*.json; do
    [ -e "$state_file" ] || continue

    # 파일명에서 PID 또는 structured session ID 추출
    pid_str="${state_file##*mst-state-}"
    pid_str="${pid_str%.json}"

    case "$pid_str" in
      MST-*)
        if [ -n "${MST_SESSION_ID:-}" ] && [ "$pid_str" = "$MST_SESSION_ID" ]; then
          rm -f "$state_file" 2>/dev/null || true
        fi
        continue
        ;;
    esac

    # 숫자 검증
    case "$pid_str" in
      ''|*[!0-9]*)
        # 비정상 legacy 파일명은 안전하게 삭제
        rm -f "$state_file" 2>/dev/null || true
        continue
        ;;
    esac

    # 자기 PPID면 삭제 (새 세션 시작이므로 이전 legacy 마커 정리)
    if [ "$pid_str" = "$my_ppid" ]; then
      rm -f "$state_file" 2>/dev/null || true
      continue
    fi

    # liveness 체크: kill -0 성공이면 살아있음
    if kill -0 "$pid_str" 2>/dev/null; then
      # 살아있는 타 PPID - 보존
      continue
    fi

    # 좀비 PPID - 삭제
    rm -f "$state_file" 2>/dev/null || true
  done

  debug_log "session_init_tmp_cleanup" "tmp_dir=$MST_TMP"
}

sync_plugin_cache() {
  local plugin_json active_version claude_home cache_base marketplace_base cache_target marketplace_target target
  local sync_output sync_kind sync_a sync_b sync_c sync_d failed_count
  plugin_json="${PROJECT_ROOT}/.claude-plugin/plugin.json"

  if [ ! -f "$plugin_json" ]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (missing plugin.json)." >&2
    debug_log "plugin_cache_sync_skip" "reason=missing_plugin_json path=$plugin_json"
    return 0
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "[mst-session-init] warning: skipped plugin cache sync (python3 not found)." >&2
    debug_log "plugin_cache_sync_skip" "reason=missing_python3"
    return 0
  fi

  active_version="$(read_plugin_version)"

  if [ -z "$active_version" ]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (invalid plugin.json version)." >&2
    debug_log "plugin_cache_sync_skip" "reason=invalid_plugin_version path=$plugin_json"
    return 0
  fi
  if ! [[ "$active_version" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$ ]]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (invalid plugin.json version)." >&2
    debug_log "plugin_cache_sync_skip" "reason=invalid_plugin_version value=$active_version path=$plugin_json"
    return 0
  fi

  claude_home="${MST_CLAUDE_HOME:-${HOME:-}}"
  if [ -z "$claude_home" ]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (HOME not set)." >&2
    debug_log "plugin_cache_sync_skip" "reason=missing_home version=$active_version"
    return 0
  fi

  cache_base="${claude_home}/.claude/plugins/cache/gran-maestro/mst"
  marketplace_base="${claude_home}/.claude/plugins/marketplaces/gran-maestro"
  cache_target="${cache_base}/${active_version}"
  marketplace_target="$marketplace_base"

  if ! path_within_boundary "$cache_base" "$cache_target" 0 || ! path_within_boundary "$marketplace_base" "$marketplace_target" 1; then
    echo "[mst-session-init] warning: skipped plugin cache sync (target outside allowed boundary)." >&2
    debug_log "plugin_cache_sync_skip" "reason=target_outside_boundary cache_target=$cache_target marketplace_target=$marketplace_target version=$active_version"
    return 0
  fi

  for target in "$cache_target" "$marketplace_target"; do
    if [ ! -d "$target" ]; then
      echo "[mst-session-init] warning: skipped plugin cache sync (target missing: $target)." >&2
      debug_log "plugin_cache_sync_skip" "reason=target_missing target=$target version=$active_version"
      return 0
    fi
    if [ ! -w "$target" ]; then
      echo "[mst-session-init] warning: skipped plugin cache sync (target not writable: $target)." >&2
      debug_log "plugin_cache_sync_skip" "reason=target_not_writable target=$target version=$active_version"
      return 0
    fi
  done

  failed_count=0

  sync_output="$(python3 - "$PROJECT_ROOT" "$active_version" "$cache_target" "$marketplace_target" <<'PY' 2>/dev/null || true
import hashlib
import os
import shutil
import stat
import sys
import tempfile

project_root = sys.argv[1]
active_version = sys.argv[2]
targets = sys.argv[3:]


def emit(*parts):
    print("\t".join(str(part) for part in parts))


def hash_files(paths):
    hashes = {}
    for path in paths:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        hashes[os.path.abspath(path)] = digest.hexdigest()
    return hashes


def is_regular_source(path):
    try:
        st = os.lstat(path)
    except OSError as exc:
        emit("WARN", "source_lstat_failed", path, str(exc))
        return False

    if stat.S_ISLNK(st.st_mode):
        emit("WARN", "source_symlink_skipped", path)
        return False
    if not stat.S_ISREG(st.st_mode):
        emit("WARN", "source_non_regular_skipped", path)
        return False
    return True


def copy_atomic(src, dst):
    dirname = os.path.dirname(dst)
    basename = os.path.basename(dst)
    tmp_path = ""

    if os.path.islink(dst):
        raise RuntimeError("destination is symlink")

    os.makedirs(dirname, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f"{basename}.tmp.", dir=dirname)
    os.close(fd)

    try:
        shutil.copy2(src, tmp_path)
        os.replace(tmp_path, dst)
        tmp_path = ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


sources = []
scripts_root = os.path.join(project_root, "scripts")
if os.path.isdir(scripts_root):
    for dirpath, _, filenames in os.walk(scripts_root):
        for filename in filenames:
            if filename.endswith((".sh", ".py")):
                path = os.path.join(dirpath, filename)
                if is_regular_source(path):
                    sources.append(path)

hooks_root = os.path.join(project_root, "hooks")
if os.path.isdir(hooks_root):
    for filename in sorted(os.listdir(hooks_root)):
        path = os.path.join(hooks_root, filename)
        if os.path.isfile(path) and is_regular_source(path):
            sources.append(path)
    lib_root = os.path.join(hooks_root, "lib")
    if os.path.isdir(lib_root):
        for filename in sorted(os.listdir(lib_root)):
            path = os.path.join(lib_root, filename)
            if os.path.isfile(path) and is_regular_source(path):
                sources.append(path)

sources = sorted(sources)
rel_paths = {path: os.path.relpath(path, project_root) for path in sources}
dest_maps = []
existing_dests = []

for target in targets:
    dest_by_src = {src: os.path.join(target, rel_paths[src]) for src in sources}
    dest_maps.append((target, dest_by_src))
    existing_dests.extend(dst for dst in dest_by_src.values() if os.path.isfile(dst) and not os.path.islink(dst))

try:
    file_hashes = hash_files(sources + existing_dests)
except Exception as exc:
    emit("FATAL", "hash_failed", str(exc))
    raise SystemExit(0)

copied = 0
skipped = 0
failed = 0
skip_records = []

for target, dest_by_src in dest_maps:
    for src in sources:
        rel_path = rel_paths[src]
        dst = dest_by_src[src]
        src_hash = file_hashes.get(os.path.abspath(src), "")
        dst_hash = file_hashes.get(os.path.abspath(dst), "")

        if src_hash and dst_hash == src_hash:
            skipped += 1
            skip_records.append((target, rel_path))
            continue

        if not is_regular_source(src):
            skipped += 1
            emit("SKIPPED_SOURCE_UNSAFE", target, rel_path)
            continue

        if os.path.islink(dst):
            skipped += 1
            emit("SKIPPED_DEST_SYMLINK", target, rel_path)
            continue

        try:
            copy_atomic(src, dst)
        except Exception as exc:
            failed += 1
            emit("FAILED", "copy_failed", target, rel_path, str(exc))
            continue

        copied += 1
        emit("COPIED", target, rel_path)

if copied == 0 and failed == 0:
    emit("ALL_SKIPPED", active_version, len(sources), skipped)
else:
    for target, rel_path in skip_records:
        emit("SKIPPED", target, rel_path)
    emit("SUMMARY", active_version, len(sources), copied, skipped, failed)
PY
)"

  if [ -z "$sync_output" ]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (sync helper failed)." >&2
    debug_log "plugin_cache_sync_skip" "reason=sync_helper_failed version=$active_version"
    return 0
  fi

  while IFS=$'\t' read -r sync_kind sync_a sync_b sync_c sync_d; do
    case "$sync_kind" in
      COPIED)
        debug_log "plugin_cache_sync_file_copied" "target=$sync_a file=$sync_b version=$active_version"
        ;;
      SKIPPED)
        debug_log "plugin_cache_sync_file_skipped" "sync skipped (no changes) target=$sync_a file=$sync_b version=$active_version"
        ;;
      SKIPPED_DEST_SYMLINK)
        debug_log "plugin_cache_sync_file_skipped" "sync skipped (destination symlink) target=$sync_a file=$sync_b version=$active_version"
        ;;
      SKIPPED_SOURCE_UNSAFE)
        debug_log "plugin_cache_sync_file_skipped" "sync skipped (unsafe source) target=$sync_a file=$sync_b version=$active_version"
        ;;
      WARN)
        echo "[mst-session-init] warning: plugin cache sync skipped file ($sync_a: $sync_b)." >&2
        debug_log "plugin_cache_sync_warning" "reason=$sync_a file=$sync_b detail=$sync_c version=$active_version"
        ;;
      FAILED)
        failed_count=$((failed_count + 1))
        debug_log "plugin_cache_sync_file_failed" "reason=$sync_a target=$sync_b file=$sync_c detail=$sync_d version=$active_version"
        ;;
      FATAL)
        failed_count=$((failed_count + 1))
        debug_log "plugin_cache_sync_failed" "reason=$sync_a detail=$sync_b version=$active_version"
        ;;
      ALL_SKIPPED)
        debug_log "plugin_cache_sync" "sync skipped (no changes) version=$sync_a sources=$sync_b skipped=$sync_c"
        ;;
      SUMMARY)
        debug_log "plugin_cache_sync" "version=$sync_a sources=$sync_b copied=$sync_c skipped=$sync_d failed=$failed_count"
        ;;
    esac
  done <<EOF_SYNC_PLUGIN_CACHE
$sync_output
EOF_SYNC_PLUGIN_CACHE

  if [ "$failed_count" -gt 0 ]; then
    echo "[mst-session-init] warning: plugin cache sync completed with $failed_count failed file operation(s)." >&2
  fi

  return 0
}

sync_run_markers() {
  local run_dir archive_base sync_output sync_kind sync_a sync_b sync_c sync_d
  local failed_count

  if ! command -v python3 >/dev/null 2>&1; then
    debug_log "run_marker_sync_skip" "reason=missing_python3"
    return 0
  fi

  run_dir="${PROJECT_ROOT}/.gran-maestro/run"
  archive_base="${PROJECT_ROOT}/.gran-maestro/archive/run"

  if [ ! -d "$run_dir" ]; then
    debug_log "run_marker_sync_skip" "reason=missing_run_dir path=$run_dir"
    return 0
  fi

  failed_count=0
  sync_output="$(python3 - "$PROJECT_ROOT" "$run_dir" "$archive_base" <<'PY' 2>/dev/null || true
import json
import os
import sys
from datetime import datetime, timezone

project_root = sys.argv[1]
run_dir = sys.argv[2]
archive_base = sys.argv[3]


def emit(*parts):
    print("\t".join(str(part) for part in parts))


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def coerce_positive_int(value, fallback):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_run_gc_config():
    paths = [
        os.path.join(project_root, ".gran-maestro", "config.resolved.json"),
        os.path.join(project_root, "templates", "defaults", "config.json"),
    ]
    for path in paths:
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        cfg = payload.get("run_gc")
        if isinstance(cfg, dict):
            return {
                "archive_after_days": coerce_positive_int(cfg.get("archive_after_days"), 7),
                "heartbeat_stale_minutes": coerce_positive_int(cfg.get("heartbeat_stale_minutes"), 10),
            }
    return {"archive_after_days": 7, "heartbeat_stale_minutes": 10}


def is_pid_alive(value):
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def atomic_write_json(path, payload):
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


cfg = load_run_gc_config()
archive_after_seconds = cfg["archive_after_days"] * 86400
stale_after_seconds = cfg["heartbeat_stale_minutes"] * 60
now = datetime.now(timezone.utc)
archived = 0
terminated = 0
skipped = 0
failed = 0

try:
    filenames = sorted(os.listdir(run_dir))
except Exception as exc:
    emit("WARN", "run_dir_list_failed", run_dir, str(exc))
    filenames = []
    failed += 1

for filename in filenames:
    if not filename.endswith(".json"):
        continue

    path = os.path.join(run_dir, filename)
    if not os.path.isfile(path):
        continue

    payload = load_json(path)
    if not isinstance(payload, dict):
        skipped += 1
        emit("WARN", "parse_failed", path)
        continue

    phase = str(payload.get("phase", "")).strip().lower()
    heartbeat = parse_utc(payload.get("last_heartbeat"))
    if heartbeat is None:
        skipped += 1
        emit("SKIPPED", "legacy_or_invalid_heartbeat", path)
        continue

    age_seconds = max(0, int((now - heartbeat).total_seconds()))

    if phase == "done":
        if age_seconds < archive_after_seconds:
            skipped += 1
            continue

        archive_dir = os.path.join(archive_base, f"{heartbeat.year:04d}-{heartbeat.month:02d}")
        target = os.path.join(archive_dir, filename)
        try:
            os.makedirs(archive_dir, exist_ok=True)
            os.replace(path, target)
            archived += 1
            emit("ARCHIVED", path, target)
        except Exception as exc:
            failed += 1
            emit("WARN", "archive_failed", path, str(exc))
        continue

    if phase != "running":
        skipped += 1
        continue

    reason = ""
    if "started_by_pid" in payload and not is_pid_alive(payload.get("started_by_pid")):
        reason = "pid_not_alive"
    elif age_seconds > stale_after_seconds:
        reason = "heartbeat_stale"

    if not reason:
        skipped += 1
        continue

    terminated_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload["phase"] = "terminated"
    payload["terminated_at"] = terminated_at
    try:
        atomic_write_json(path, payload)
        terminated += 1
        emit("TERMINATED", path, reason)
    except Exception as exc:
        failed += 1
        emit("WARN", "terminate_write_failed", path, str(exc))

emit("SUMMARY", archived, terminated, skipped, failed)
PY
)"

  if [ -z "$sync_output" ]; then
    debug_log "run_marker_sync_skip" "reason=sync_helper_failed"
    return 0
  fi

  while IFS=$'\t' read -r sync_kind sync_a sync_b sync_c sync_d; do
    case "$sync_kind" in
      ARCHIVED)
        debug_log "run_marker_archived" "source=$sync_a target=$sync_b"
        ;;
      TERMINATED)
        debug_log "run_marker_terminated" "path=$sync_a reason=$sync_b"
        ;;
      SKIPPED)
        debug_log "run_marker_skipped" "reason=$sync_a path=$sync_b"
        ;;
      WARN)
        failed_count=$((failed_count + 1))
        debug_log "run_marker_sync_warning" "reason=$sync_a path=$sync_b detail=$sync_c $sync_d"
        ;;
      SUMMARY)
        debug_log "run_marker_sync" "archived=$sync_a terminated=$sync_b skipped=$sync_c failed=$sync_d"
        ;;
    esac
  done <<EOF_SYNC_RUN_MARKERS
$sync_output
EOF_SYNC_RUN_MARKERS

  if [ "$failed_count" -gt 0 ]; then
    echo "[mst-session-init] warning: run marker sync completed with $failed_count skipped operation(s)." >&2
  fi

  return 0
}

write_initial_state() {
  local now tmp_path
  now="$(utc_timestamp)"
  tmp_path="${STATE_FILE}.tmp"

  cat > "$tmp_path" <<EOF_STATE
{
  "workflow_active": false,
  "next_action": {
    "skill": "",
    "source": "",
    "auto": false,
    "expected_skill": "",
    "source_skill": "",
    "source_id": "",
    "auto_mode": false
  },
  "current_skill": "",
  "active_req": "",
  "iteration": 0,
  "updated_at": "$now"
}
EOF_STATE

  mv "$tmp_path" "$STATE_FILE"

  debug_log "session_init_state_initialized" "state_file=$STATE_FILE"
}

write_session_bridge() {
  local session_id tmp_path
  session_id="$(stdin_session_id)"

  if [ -z "$session_id" ]; then
    return 0
  fi

  if ! [[ "$session_id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]; then
    return 0
  fi

  tmp_path="${SESSION_BRIDGE_FILE}.tmp"
  printf '%s\n' "$session_id" > "$tmp_path" || {
    rm -f "$tmp_path" 2>/dev/null || true
    return 1
  }
  mv "$tmp_path" "$SESSION_BRIDGE_FILE" || {
    rm -f "$tmp_path" 2>/dev/null || true
    return 1
  }
  chmod 644 "$SESSION_BRIDGE_FILE" 2>/dev/null || return 1

  debug_log "session_init_session_bridge_written" "bridge_file=$SESSION_BRIDGE_FILE"
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

# Auto-sync hooks to plugin version on session start (non-blocking)
if [ -n "${PROJECT_ROOT:-}" ] && [ -f "${PROJECT_ROOT}/scripts/mst.py" ]; then
  python3 "${PROJECT_ROOT}/scripts/mst.py" hooks sync --silent 2>/dev/null || true # mst.py hooks sync || true
fi

exit 0
