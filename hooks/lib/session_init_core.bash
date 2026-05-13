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
