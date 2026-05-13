session_init_sync_plugin_cache() {
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

session_init_sync_run_markers() {
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

