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
mkdir -p "$MST_TMP"


debug_log() {
  [ "${MST_DEBUG:-0}" = "1" ] || return 0
  local event="${1:-event}"
  shift || true
  local detail="${*:-}"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%FT%TZ)"
  printf '%s event=%s %s\n' "$ts" "$event" "$detail" >> "$DEBUG_LOG_FILE" 2>/dev/null || true
}

clear_next_action_from_plan_json() {
  local clear_info clear_status clear_count clear_scanned clear_failed
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
  python3 - "$PROJECT_ROOT" <<'PY' 2>/dev/null || true
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
}

read_hook_version() {
  local version_file="${PROJECT_ROOT}/.claude/hooks/.mst-hook-version"
  if [ -f "$version_file" ]; then
    tr -d '[:space:]' < "$version_file" 2>/dev/null || true
    return 0
  fi
  printf ''
}

check_hook_version_mismatch() {
  local plugin_version hook_version
  plugin_version="$(read_plugin_version)"
  hook_version="$(read_hook_version)"

  if [ -n "$plugin_version" ] && [ "$plugin_version" != "$hook_version" ]; then
    local hook_display
    hook_display="${hook_version:-missing}"
    echo "[mst-session-init] warning: hook version mismatch (hook=$hook_display plugin=$plugin_version). Run /mst:on to sync hooks." >&2
    debug_log "session_init_version_mismatch" "hook=$hook_display plugin=$plugin_version"
  fi
}

cleanup_stale_markers() {
  rm -f \
    "${MST_TMP}/mst-call-stack-"*.json \
    "${MST_TMP}/mst-call-stack-"*.json.tmp \
    "${MST_TMP}/mst-pending-continuation-"* \
    "${MST_TMP}/mst-pending-continuation-"*.tmp \
    "${MST_TMP}/mst-next-action-"*.json \
    "${MST_TMP}/mst-next-action-"*.json.tmp \
    "${MST_TMP}/mst-next-action-count-"* \
    "${MST_TMP}/mst-next-action-count-"*.tmp \
    "${MST_TMP}/mst-next-action-state-"* \
    "${MST_TMP}/mst-next-action-state-"*.tmp \
    "${MST_TMP}/mst-stop-hook-count-"* \
    "${MST_TMP}/mst-stop-hook-count-"*.tmp \
    "${MST_TMP}/mst-hook-debug-"*.log \
    "${MST_TMP}/mst-hook-check-done-"* \
    "${MST_TMP}/mst-transcript-"*.path \
    "${MST_TMP}/mst-state-"*.json \
    "${MST_TMP}/mst-state-"*.json.tmp \
    2>/dev/null || true

  debug_log "session_init_tmp_cleanup" "tmp_dir=$MST_TMP"
}

write_initial_state() {
  python3 - "$STATE_FILE" <<'PY'
import json
import sys
from datetime import datetime, timezone

path = sys.argv[1]
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
payload = {
    "workflow_active": False,
    "next_action": {
        "skill": "",
        "source": "",
        "auto": False,
        "expected_skill": "",
        "source_skill": "",
        "source_id": "",
        "auto_mode": False,
    },
    "current_skill": "",
    "active_req": "",
    "iteration": 0,
    "updated_at": now,
}

with open(path + ".tmp", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")

import os
os.replace(path + ".tmp", path)
PY

  debug_log "session_init_state_initialized" "state_file=$STATE_FILE"
}

cleanup_stale_markers
clear_next_action_from_plan_json
check_hook_version_mismatch
write_initial_state

exit 0
