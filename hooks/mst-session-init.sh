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
SESSION_BRIDGE_FILE="${MST_TMP}/claude-session-${PPID}.id"
DEBUG_LOG_FILE="${MST_TMP}/mst-hook-debug-${PPID}.log"
mkdir -p "$MST_TMP"
echo "$PPID" > "${MST_TMP}/mst-session-anchor-${PPID}.pid" 2>/dev/null || true

STDIN_RAW="$(cat || true)"


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
  # 자기 PPID 및 liveness 없는 PPID의 state만 삭제, 살아있는 타 PPID는 보존
  my_ppid="${PPID}"
  for state_file in "${tmp_dir}/mst-state-"*.json; do
    [ -e "$state_file" ] || continue

    # 파일명에서 PID 추출: mst-state-12345.json -> 12345
    pid_str="${state_file##*mst-state-}"
    pid_str="${pid_str%.json}"

    # 숫자 검증
    case "$pid_str" in
      ''|*[!0-9]*)
        # 비정상 파일명은 안전하게 삭제
        rm -f "$state_file" 2>/dev/null || true
        continue
        ;;
    esac

    # 자기 PPID면 삭제 (새 세션 시작이므로 이전 마커 정리)
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
  local boundary_status boundary_detail
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

  active_version="$(python3 -c 'import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
version = data.get("version") if isinstance(data, dict) else ""
if not isinstance(version, str) or not version.strip():
    raise SystemExit(1)
print(version.strip())
' "$plugin_json" 2>/dev/null || true)"

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

  if ! command -v shasum >/dev/null 2>&1; then
    echo "[mst-session-init] warning: skipped plugin cache sync (shasum not found)." >&2
    debug_log "plugin_cache_sync_skip" "reason=missing_shasum version=$active_version"
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

  boundary_detail="$(python3 - "$cache_base" "$cache_target" "$marketplace_base" "$marketplace_target" <<'PY' 2>/dev/null || printf 'error\tboundary_check_failed\n'
import os
import sys

pairs = [
    (sys.argv[1], sys.argv[2], "cache"),
    (sys.argv[3], sys.argv[4], "marketplace"),
]

for base, target, label in pairs:
    base_real = os.path.join(
        os.path.realpath(os.path.dirname(base)),
        os.path.basename(base),
    )
    target_real = os.path.realpath(target)
    try:
        common = os.path.commonpath([base_real, target_real])
    except ValueError:
        print(f"outside\t{label}:{target_real}")
        raise SystemExit(0)

    if common != base_real or target_real == base_real and label == "cache":
        print(f"outside\t{label}:{target_real}")
        raise SystemExit(0)

print("ok\t")
PY
)"
  boundary_status="$(printf '%s' "$boundary_detail" | cut -f1)"
  boundary_detail="$(printf '%s' "$boundary_detail" | cut -f2-)"
  if [ "$boundary_status" != "ok" ]; then
    echo "[mst-session-init] warning: skipped plugin cache sync (target outside allowed boundary)." >&2
    debug_log "plugin_cache_sync_skip" "reason=target_outside_boundary detail=$boundary_detail version=$active_version"
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
import os
import stat
import subprocess
import sys
import tempfile

project_root = sys.argv[1]
active_version = sys.argv[2]
targets = sys.argv[3:]


def emit(*parts):
    print("\t".join(str(part) for part in parts))


def hash_files(paths):
    hashes = {}
    if not paths:
        return hashes
    for index in range(0, len(paths), 500):
        chunk = paths[index:index + 500]
        result = subprocess.run(
            ["shasum", "-a", "256"] + chunk,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "shasum failed")
        for line in result.stdout.splitlines():
            fields = line.split(None, 1)
            if len(fields) == 2:
                hashes[os.path.abspath(fields[1])] = fields[0]
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
        result = subprocess.run(
            ["cp", "-p", src, tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "cp failed")
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
        if filename.endswith(".sh") and is_regular_source(path):
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

write_session_bridge() {
  STDIN_RAW="$STDIN_RAW" python3 - "$SESSION_BRIDGE_FILE" <<'PY'
import json
import os
import sys
import uuid

path = sys.argv[1]
raw_stdin = os.environ.get("STDIN_RAW", "")

try:
    payload = json.loads(raw_stdin)
except Exception:
    print("[mst-session-init] warning: skipped session bridge write (invalid stdin json).", file=sys.stderr)
    raise SystemExit(0)

if not isinstance(payload, dict):
    print("[mst-session-init] warning: skipped session bridge write (stdin payload is not a JSON object).", file=sys.stderr)
    raise SystemExit(0)

raw_value = payload.get("session_id")
if not isinstance(raw_value, str) or not raw_value:
    print("[mst-session-init] warning: skipped session bridge write (missing or empty session_id).", file=sys.stderr)
    raise SystemExit(0)

try:
    session_id = uuid.UUID(raw_value)
except ValueError:
    print("[mst-session-init] warning: skipped session bridge write (invalid session_id uuid).", file=sys.stderr)
    raise SystemExit(0)

canonical = str(session_id)
if session_id.variant != uuid.RFC_4122 or canonical != raw_value:
    print("[mst-session-init] warning: skipped session bridge write (non-canonical or non-RFC4122 session_id).", file=sys.stderr)
    raise SystemExit(0)

tmp_path = path + ".tmp"
try:
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(canonical)
        f.write("\n")
    os.replace(tmp_path, path)
    os.chmod(path, 0o644)
except Exception as exc:
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        pass
    print(f"[mst-session-init] warning: failed to write session bridge: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY

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
