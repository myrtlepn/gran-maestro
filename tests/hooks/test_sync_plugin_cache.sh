#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SESSION_INIT_SCRIPT="$REPO_ROOT/hooks/mst-session-init.sh"
SESSION_ID="123e4567-e89b-42d3-a456-426614174000"

PASS_COUNT=0
FAIL_COUNT=0
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" != "$actual" ]; then
    printf 'FAIL: %s\n  expected: %s\n  actual:   %s\n' "$name" "$expected" "$actual" >&2
    exit 1
  fi
}

assert_file_exists() {
  local name="$1"
  local path="$2"
  if [ ! -f "$path" ]; then
    printf 'FAIL: %s\n  missing file: %s\n' "$name" "$path" >&2
    exit 1
  fi
}

assert_file_missing() {
  local name="$1"
  local path="$2"
  if [ -e "$path" ]; then
    printf 'FAIL: %s\n  unexpected path exists: %s\n' "$name" "$path" >&2
    exit 1
  fi
}

assert_symlink() {
  local name="$1"
  local path="$2"
  if [ ! -L "$path" ]; then
    printf 'FAIL: %s\n  expected symlink: %s\n' "$name" "$path" >&2
    exit 1
  fi
}

assert_file_content() {
  local name="$1"
  local expected="$2"
  local path="$3"
  local actual

  if [ ! -f "$path" ]; then
    printf 'FAIL: %s\n  missing file: %s\n' "$name" "$path" >&2
    exit 1
  fi

  actual="$(cat "$path")"
  if [ "$expected" != "$actual" ]; then
    printf 'FAIL: %s\n  expected content: %s\n  actual content:   %s\n' "$name" "$expected" "$actual" >&2
    exit 1
  fi
}

assert_contains_file() {
  local name="$1"
  local needle="$2"
  local path="$3"
  if ! grep -Fq "$needle" "$path"; then
    printf 'FAIL: %s\n  expected %s to contain: %s\n' "$name" "$path" "$needle" >&2
    printf '  actual:\n' >&2
    sed 's/^/    /' "$path" >&2 || true
    exit 1
  fi
}

assert_contains_ci_file() {
  local name="$1"
  local needle="$2"
  local path="$3"
  if ! grep -Fiq "$needle" "$path"; then
    printf 'FAIL: %s\n  expected %s to contain case-insensitive: %s\n' "$name" "$path" "$needle" >&2
    printf '  actual:\n' >&2
    sed 's/^/    /' "$path" >&2 || true
    exit 1
  fi
}

assert_int_le() {
  local name="$1"
  local actual="$2"
  local limit="$3"

  case "$actual" in
    ''|*[!0-9]*)
      printf 'FAIL: %s\n  expected integer, got: %s\n' "$name" "$actual" >&2
      exit 1
      ;;
  esac

  if [ "$actual" -gt "$limit" ]; then
    printf 'FAIL: %s\n  expected <= %s\n  actual: %s\n' "$name" "$limit" "$actual" >&2
    exit 1
  fi
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

stat_mtime() {
  local path="$1"
  case "$(uname -s)" in
    Darwin) stat -f %m "$path" ;;
    *) stat -c %Y "$path" ;;
  esac
}

new_case_dir() {
  mktemp -d "$TEST_TMP_ROOT/case.XXXXXX"
}

write_project_fixture() {
  local project_root="$1"
  local content="$2"

  mkdir -p "$project_root/scripts" "$project_root/.claude-plugin"
  printf '%s\n' "$content" > "$project_root/scripts/mst-statusline.sh"
  chmod +x "$project_root/scripts/mst-statusline.sh"
  printf '{"version":"TEST"}\n' > "$project_root/.claude-plugin/plugin.json"
}

write_hooks_fixture() {
  local project_root="$1"

  mkdir -p "$project_root/hooks/lib"
  cp "$REPO_ROOT/hooks/mst-pre-tool-use.sh" "$project_root/hooks/mst-pre-tool-use.sh"
  cp "$REPO_ROOT/hooks/lib/pre_tool_use_fast.py" "$project_root/hooks/lib/pre_tool_use_fast.py"
  cp "$REPO_ROOT/hooks/lib/history.bash" "$project_root/hooks/lib/history.bash"
  cp "$REPO_ROOT/hooks/lib/rule_engine.bash" "$project_root/hooks/lib/rule_engine.bash"
  cp "$REPO_ROOT/hooks/lib/sha256.bash" "$project_root/hooks/lib/sha256.bash"
  chmod +x "$project_root/hooks/mst-pre-tool-use.sh"
}

create_fake_cache_targets() {
  local claude_home="$1"
  mkdir -p \
    "$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/scripts" \
    "$claude_home/.claude/plugins/marketplaces/gran-maestro/scripts"
}

run_session_init() {
  local project_root="$1"
  local claude_home="$2"
  local stdout_file="$3"
  local stderr_file="$4"

  (
    cd "$project_root"
    MST_CLAUDE_HOME="$claude_home" \
      HOME="$claude_home" \
      MST_DEBUG=1 \
      PLUGIN_ROOT="$REPO_ROOT" \
      bash "$SESSION_INIT_SCRIPT" >"$stdout_file" 2>"$stderr_file" <<JSON
{"session_id":"$SESSION_ID"}
JSON
  )
}

require_single_file_match() {
  local name="$1"
  local pattern="$2"
  local matches=()

  while IFS= read -r path; do
    matches+=("$path")
  done < <(compgen -G "$pattern" || true)

  if [ "${#matches[@]}" -ne 1 ]; then
    printf 'FAIL: %s\n  expected one match for: %s\n  actual count: %s\n' "$name" "$pattern" "${#matches[@]}" >&2
    printf '  matches:\n' >&2
    printf '    %s\n' "${matches[@]:-}" >&2
    exit 1
  fi

  printf '%s\n' "${matches[0]}"
}

assert_state_and_bridge_created() {
  local name="$1"
  local project_root="$2"
  local tmp_dir="$project_root/.gran-maestro/tmp"
  local state_file bridge_file anchor_file pid session_content

  state_file="$(require_single_file_match "$name state file" "$tmp_dir/mst-state-*.json")"
  pid="${state_file##*mst-state-}"
  pid="${pid%.json}"
  bridge_file="$tmp_dir/claude-session-${pid}.id"
  anchor_file="$tmp_dir/mst-session-anchor-${pid}.pid"

  assert_file_exists "$name bridge file" "$bridge_file"
  session_content="$(tr -d '\n' < "$bridge_file")"
  assert_eq "$name bridge session id" "$SESSION_ID" "$session_content"
  assert_file_exists "$name session anchor file" "$anchor_file"
  assert_file_content "$name session anchor content" "$pid" "$anchor_file"
}

json_field() {
  local path="$1"
  local field="$2"
  python3 - "$path" "$field" <<'PY'
import json
import sys

path, field = sys.argv[1:]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
value = payload.get(field, "")
print("" if value is None else value)
PY
}

test_ac101_sync_end_to_end() {
  local case_dir project_root claude_home stdout_file stderr_file
  local source_file cache_file marketplace_file hash_source hash_cache hash_marketplace

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# content A"
  create_fake_cache_targets "$claude_home"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  source_file="$project_root/scripts/mst-statusline.sh"
  cache_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/scripts/mst-statusline.sh"
  marketplace_file="$claude_home/.claude/plugins/marketplaces/gran-maestro/scripts/mst-statusline.sh"

  assert_file_exists "AC-101 cache copy content A" "$cache_file"
  assert_file_exists "AC-101 marketplace copy content A" "$marketplace_file"
  hash_source="$(sha256_file "$source_file")"
  hash_cache="$(sha256_file "$cache_file")"
  hash_marketplace="$(sha256_file "$marketplace_file")"
  assert_eq "AC-101 cache hash content A" "$hash_source" "$hash_cache"
  assert_eq "AC-101 marketplace hash content A" "$hash_source" "$hash_marketplace"

  printf '%s\n' "# content B" > "$source_file"
  chmod +x "$source_file"
  run_session_init "$project_root" "$claude_home" "$stdout_file.2" "$stderr_file.2"

  hash_source="$(sha256_file "$source_file")"
  hash_cache="$(sha256_file "$cache_file")"
  hash_marketplace="$(sha256_file "$marketplace_file")"
  assert_eq "AC-101 cache hash content B" "$hash_source" "$hash_cache"
  assert_eq "AC-101 marketplace hash content B" "$hash_source" "$hash_marketplace"
}

test_act08_002_sync_hooks_lib_to_plugin_cache() {
  local case_dir project_root claude_home stdout_file stderr_file
  local rel source_file cache_file marketplace_file status

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# hook lib content"
  write_hooks_fixture "$project_root"
  create_fake_cache_targets "$claude_home"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  for rel in \
    hooks/lib/pre_tool_use_fast.py \
    hooks/lib/history.bash \
    hooks/lib/rule_engine.bash \
    hooks/lib/sha256.bash; do
    source_file="$project_root/$rel"
    cache_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/$rel"
    marketplace_file="$claude_home/.claude/plugins/marketplaces/gran-maestro/$rel"
    assert_file_exists "AC-T08-002 cache $rel" "$cache_file"
    assert_file_exists "AC-T08-002 marketplace $rel" "$marketplace_file"
    assert_eq "AC-T08-002 cache hash $rel" "$(sha256_file "$source_file")" "$(sha256_file "$cache_file")"
    assert_eq "AC-T08-002 marketplace hash $rel" "$(sha256_file "$source_file")" "$(sha256_file "$marketplace_file")"
  done

  set +e
  (
    cd "$project_root" || exit 1
    HOME="$claude_home" bash "$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/hooks/mst-pre-tool-use.sh" >"$case_dir/copied-hook.stdout" 2>"$case_dir/copied-hook.stderr" <<'JSON'
{"tool_name":"Read","tool_input":{"file_path":"README.md"}}
JSON
  )
  status=$?
  set -e

  assert_eq "AC-T08-002 copied cache hook smoke exit code" "0" "$status"
  if [ -s "$case_dir/copied-hook.stderr" ]; then
    printf 'FAIL: AC-T08-002 copied cache hook stderr\n' >&2
    sed 's/^/    /' "$case_dir/copied-hook.stderr" >&2 || true
    exit 1
  fi
}

test_ac102_session_init_smoke_and_cleanup() {
  local case_dir project_root claude_home tmp_dir stdout_file stderr_file status

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  tmp_dir="$project_root/.gran-maestro/tmp"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# smoke content"
  create_fake_cache_targets "$claude_home"

  mkdir -p "$tmp_dir"
  printf '{}\n' > "$tmp_dir/mst-state-not-a-pid.json"
  printf '{}\n' > "$tmp_dir/mst-state-999999999.json"
  printf '{}\n' > "$tmp_dir/mst-call-stack-stale.json"
  printf '{}\n' > "$tmp_dir/mst-next-action-stale.json"
  printf 'stale\n' > "$tmp_dir/mst-pending-continuation-stale"
  printf 'stale\n' > "$tmp_dir/mst-stop-hook-count-stale"

  set +e
  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  status=$?
  set -e

  assert_eq "AC-102 session-init exit code" "0" "$status"
  assert_state_and_bridge_created "AC-102" "$project_root"
  assert_file_missing "AC-102 removes non-numeric stale state" "$tmp_dir/mst-state-not-a-pid.json"
  assert_file_missing "AC-102 removes zombie stale state" "$tmp_dir/mst-state-999999999.json"
  assert_file_missing "AC-102 removes call stack marker" "$tmp_dir/mst-call-stack-stale.json"
  assert_file_missing "AC-102 removes next action marker" "$tmp_dir/mst-next-action-stale.json"
  assert_file_missing "AC-102 removes pending continuation marker" "$tmp_dir/mst-pending-continuation-stale"
  assert_file_missing "AC-102 removes stop hook count marker" "$tmp_dir/mst-stop-hook-count-stale"
}

test_ac103_graceful_fallback_missing_cache() {
  local case_dir project_root claude_home stdout_file stderr_file status

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# fallback content"
  create_fake_cache_targets "$claude_home"
  rm -rf "$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST"

  set +e
  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  status=$?
  set -e

  assert_eq "AC-103 missing cache exit code" "0" "$status"
  assert_contains_file "AC-103 stderr skip reason" "skipped plugin cache sync (target missing:" "$stderr_file"
  assert_state_and_bridge_created "AC-103" "$project_root"
}

test_ac104_old_version_protection() {
  local case_dir project_root claude_home stdout_file stderr_file
  local old_file old_hash_before old_hash_after old_mtime_before old_mtime_after

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# active content"
  create_fake_cache_targets "$claude_home"

  old_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/0.57.6/scripts/mst-statusline.sh"
  mkdir -p "$(dirname "$old_file")"
  printf '%s\n' "# old protected content" > "$old_file"
  chmod +x "$old_file"
  touch -t 202001010000 "$old_file"

  old_hash_before="$(sha256_file "$old_file")"
  old_mtime_before="$(stat_mtime "$old_file")"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  old_hash_after="$(sha256_file "$old_file")"
  old_mtime_after="$(stat_mtime "$old_file")"
  assert_eq "AC-104 old version hash unchanged" "$old_hash_before" "$old_hash_after"
  assert_eq "AC-104 old version mtime unchanged" "$old_mtime_before" "$old_mtime_after"
}

test_ac201_destination_symlink_protection() {
  local case_dir project_root claude_home stdout_file stderr_file
  local cache_file protected_file protected_before protected_after

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# source content"
  create_fake_cache_targets "$claude_home"

  cache_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/scripts/mst-statusline.sh"
  protected_file="$case_dir/protected-target.sh"
  printf '%s' "protected content" > "$protected_file"
  rm -f "$cache_file"
  ln -s "$protected_file" "$cache_file"

  protected_before="$(sha256_file "$protected_file")"
  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  protected_after="$(sha256_file "$protected_file")"

  assert_symlink "AC-201 destination remains symlink" "$cache_file"
  assert_eq "AC-201 symlink target hash unchanged" "$protected_before" "$protected_after"
  assert_file_content "AC-201 symlink target content unchanged" "protected content" "$protected_file"
}

test_ac202_source_symlink_skipped() {
  local case_dir project_root claude_home stdout_file stderr_file status
  local source_target source_link cache_link marketplace_link

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"

  write_project_fixture "$project_root" "# source content"
  create_fake_cache_targets "$claude_home"

  source_target="$case_dir/linked-source.sh"
  source_link="$project_root/scripts/linked-source.sh"
  printf '%s\n' "# linked source should not copy" > "$source_target"
  ln -s "$source_target" "$source_link"

  set +e
  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  status=$?
  set -e

  cache_link="$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/scripts/linked-source.sh"
  marketplace_link="$claude_home/.claude/plugins/marketplaces/gran-maestro/scripts/linked-source.sh"

  assert_eq "AC-202 symlink source exit code" "0" "$status"
  assert_file_missing "AC-202 cache symlink source not copied" "$cache_link"
  assert_file_missing "AC-202 marketplace symlink source not copied" "$marketplace_link"
  assert_contains_file "AC-202 stderr warns source symlink" "source_symlink_skipped" "$stderr_file"
}

test_ac203_invalid_version_skipped() {
  local version case_dir project_root claude_home stdout_file stderr_file status
  local outside_file empty_version_file nested_version_file

  for version in "../evil" "" "a/b"; do
    case_dir="$(new_case_dir)"
    project_root="$case_dir/project"
    claude_home="$case_dir/home"
    stdout_file="$case_dir/stdout.log"
    stderr_file="$case_dir/stderr.log"

    write_project_fixture "$project_root" "# invalid version content"
    printf '{"version":"%s"}\n' "$version" > "$project_root/.claude-plugin/plugin.json"

    mkdir -p \
      "$claude_home/.claude/plugins/cache/gran-maestro/evil/scripts" \
      "$claude_home/.claude/plugins/cache/gran-maestro/mst/scripts" \
      "$claude_home/.claude/plugins/cache/gran-maestro/mst/a/b/scripts" \
      "$claude_home/.claude/plugins/marketplaces/gran-maestro/scripts"

    set +e
    run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
    status=$?
    set -e

    outside_file="$claude_home/.claude/plugins/cache/gran-maestro/evil/scripts/mst-statusline.sh"
    empty_version_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/scripts/mst-statusline.sh"
    nested_version_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/a/b/scripts/mst-statusline.sh"

    assert_eq "AC-203 invalid version exit code ($version)" "0" "$status"
    assert_contains_file "AC-203 invalid version warning ($version)" "skipped plugin cache sync (invalid plugin.json version)." "$stderr_file"
    assert_file_missing "AC-203 traversal target not written ($version)" "$outside_file"
    assert_file_missing "AC-203 empty version target not written ($version)" "$empty_version_file"
    assert_file_missing "AC-203 nested version target not written ($version)" "$nested_version_file"
  done
}

test_ac204a_static_sync_contract() {
  local todo_count function_count run_function_count cleanup_call_line sync_call_line run_sync_call_line order_probe

  todo_count="$(grep -c 'PLUGIN-CACHE-SYNC' "$SESSION_INIT_SCRIPT" || true)"
  function_count="$(grep -c '^sync_plugin_cache()' "$SESSION_INIT_SCRIPT" || true)"
  run_function_count="$(grep -c '^sync_run_markers()' "$SESSION_INIT_SCRIPT" || true)"
  order_probe="$(grep -n 'cleanup_stale_markers\|sync_plugin_cache\|sync_run_markers' "$SESSION_INIT_SCRIPT" || true)"
  cleanup_call_line="$(printf '%s\n' "$order_probe" | awk -F: '$2 == "cleanup_stale_markers" {print $1; exit}')"
  sync_call_line="$(printf '%s\n' "$order_probe" | awk -F: '$2 == "sync_plugin_cache" {print $1; exit}')"
  run_sync_call_line="$(printf '%s\n' "$order_probe" | awk -F: '$2 == "sync_run_markers" {print $1; exit}')"

  assert_eq "AC-204a no PLUGIN-CACHE-SYNC TODO marker" "0" "$todo_count"
  assert_eq "AC-204a single sync_plugin_cache definition" "1" "$function_count"
  assert_eq "AC-204a single sync_run_markers definition" "1" "$run_function_count"

  if [ -z "$cleanup_call_line" ] || [ -z "$sync_call_line" ] || [ -z "$run_sync_call_line" ]; then
    fail "AC-204a could not locate cleanup/sync call lines"
  fi
  case "$cleanup_call_line:$sync_call_line:$run_sync_call_line" in
    *[!0-9:]*)
      fail "AC-204a invalid cleanup/sync call line numbers"
      ;;
  esac

  if [ "$cleanup_call_line" -ge "$sync_call_line" ]; then
    printf 'FAIL: AC-204a call order\n  cleanup_stale_markers line: %s\n  sync_plugin_cache line: %s\n' "$cleanup_call_line" "$sync_call_line" >&2
    exit 1
  fi
  if [ "$sync_call_line" -ge "$run_sync_call_line" ]; then
    printf 'FAIL: AC-204a run sync call order\n  sync_plugin_cache line: %s\n  sync_run_markers line: %s\n' "$sync_call_line" "$run_sync_call_line" >&2
    exit 1
  fi
}

test_ac301_run_marker_gc_archive_terminate_and_preserve() {
  local case_dir project_root claude_home stdout_file stderr_file run_dir archive_file
  local alive_marker alive_mtime_before alive_mtime_after terminated_phase terminated_at
  local recent_done_phase legacy_phase

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  run_dir="$project_root/.gran-maestro/run"

  write_project_fixture "$project_root" "# run marker gc content"
  create_fake_cache_targets "$claude_home"
  mkdir -p "$run_dir"

  python3 - "$run_dir" "$$" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
alive_pid = int(sys.argv[2])
now = datetime.now(timezone.utc).replace(microsecond=0)

def write(name, payload):
    (run_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

write("old-done.json", {
    "task_id": "old-done",
    "phase": "done",
    "last_heartbeat": "2020-01-02T00:00:00Z",
})
write("recent-done.json", {
    "task_id": "recent-done",
    "phase": "done",
    "last_heartbeat": now.isoformat().replace("+00:00", "Z"),
})
write("dead-running.json", {
    "task_id": "dead-running",
    "phase": "running",
    "started_by_pid": 999999999,
    "last_heartbeat": now.isoformat().replace("+00:00", "Z"),
})
write("alive-running.json", {
    "task_id": "alive-running",
    "phase": "running",
    "started_by_pid": alive_pid,
    "last_heartbeat": now.isoformat().replace("+00:00", "Z"),
})
write("legacy-running.json", {
    "task_id": "legacy-running",
    "phase": "running",
    "started_by_pid": 999999999,
})
write("stale-running.json", {
    "task_id": "stale-running",
    "phase": "running",
    "started_by_pid": alive_pid,
    "last_heartbeat": (now - timedelta(minutes=11)).isoformat().replace("+00:00", "Z"),
})
PY

  alive_marker="$run_dir/alive-running.json"
  alive_mtime_before="$(stat_mtime "$alive_marker")"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  archive_file="$project_root/.gran-maestro/archive/run/2020-01/old-done.json"
  assert_file_missing "AC-301 old done removed from run dir" "$run_dir/old-done.json"
  assert_file_exists "AC-301 old done archived" "$archive_file"

  recent_done_phase="$(json_field "$run_dir/recent-done.json" "phase")"
  assert_eq "AC-301 recent done preserved" "done" "$recent_done_phase"

  terminated_phase="$(json_field "$run_dir/dead-running.json" "phase")"
  terminated_at="$(json_field "$run_dir/dead-running.json" "terminated_at")"
  assert_eq "AC-301 dead running terminated" "terminated" "$terminated_phase"
  if [ -z "$terminated_at" ]; then
    fail "AC-301 dead running terminated_at missing"
  fi

  terminated_phase="$(json_field "$run_dir/stale-running.json" "phase")"
  terminated_at="$(json_field "$run_dir/stale-running.json" "terminated_at")"
  assert_eq "AC-301 stale running terminated" "terminated" "$terminated_phase"
  if [ -z "$terminated_at" ]; then
    fail "AC-301 stale running terminated_at missing"
  fi

  legacy_phase="$(json_field "$run_dir/legacy-running.json" "phase")"
  assert_eq "AC-301 legacy marker preserved" "running" "$legacy_phase"

  alive_mtime_after="$(stat_mtime "$alive_marker")"
  assert_eq "AC-301 alive running mtime unchanged" "$alive_mtime_before" "$alive_mtime_after"
  assert_eq "AC-301 alive running phase unchanged" "running" "$(json_field "$alive_marker" "phase")"
}

test_ac204b_second_run_skip_log() {
  local case_dir project_root claude_home stdout_file stderr_file stdout_file2 stderr_file2
  local tmp_dir debug_file combined_log

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  stdout_file2="$case_dir/stdout.2.log"
  stderr_file2="$case_dir/stderr.2.log"

  write_project_fixture "$project_root" "# repeated content"
  create_fake_cache_targets "$claude_home"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  run_session_init "$project_root" "$claude_home" "$stdout_file2" "$stderr_file2"

  tmp_dir="$project_root/.gran-maestro/tmp"
  debug_file="$(require_single_file_match "AC-204b debug file" "$tmp_dir/mst-hook-debug-*.log")"
  combined_log="$case_dir/combined-second-run.log"
  cat "$stderr_file2" "$debug_file" > "$combined_log"

  assert_contains_ci_file "AC-204b second run skip log" "skip" "$combined_log"
}

test_ac204c_session_init_average_under_500ms() {
  local case_dir project_root claude_home avg_ms

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"

  write_project_fixture "$project_root" "# timing content"
  create_fake_cache_targets "$claude_home"

  avg_ms="$(python3 - "$project_root" "$claude_home" "$SESSION_INIT_SCRIPT" "$SESSION_ID" "$REPO_ROOT" <<'PY'
import os
import subprocess
import sys
import time

project_root, claude_home, script, session_id, repo_root = sys.argv[1:]
env = os.environ.copy()
env.update({
    "MST_CLAUDE_HOME": claude_home,
    "HOME": claude_home,
    "MST_DEBUG": "1",
    "PLUGIN_ROOT": repo_root,
})
payload = f'{{"session_id":"{session_id}"}}\n'
elapsed = []

for _ in range(3):
    start = time.perf_counter()
    result = subprocess.run(
        ["bash", script],
        cwd=project_root,
        input=payload,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    elapsed.append(time.perf_counter() - start)
    if result.returncode != 0:
        print("999999")
        raise SystemExit(0)

print(int(round((sum(elapsed) / len(elapsed)) * 1000)))
PY
)"

  assert_int_le "AC-204c average session-init wall time (ms)" "$avg_ms" "500"
}

run_case() {
  local name="$1"
  local fn="$2"

  printf 'RUN: %s\n' "$name"
  if ( set -euo pipefail; "$fn" ); then
    printf 'PASS: %s\n' "$name"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    printf 'FAIL: %s\n' "$name" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required"
fi
if ! command -v shasum >/dev/null 2>&1; then
  fail "shasum is required"
fi

run_case "AC-101 sync end-to-end" test_ac101_sync_end_to_end
run_case "AC-T08-002 sync hooks lib to plugin cache" test_act08_002_sync_hooks_lib_to_plugin_cache
run_case "AC-102 session-init smoke and cleanup" test_ac102_session_init_smoke_and_cleanup
run_case "AC-103 graceful fallback missing cache" test_ac103_graceful_fallback_missing_cache
run_case "AC-104 old version protection" test_ac104_old_version_protection
run_case "AC-201 destination symlink protection" test_ac201_destination_symlink_protection
run_case "AC-202 source symlink skipped" test_ac202_source_symlink_skipped
run_case "AC-203 invalid version skipped" test_ac203_invalid_version_skipped
run_case "AC-204a static sync contract" test_ac204a_static_sync_contract
run_case "AC-204b second run skip log" test_ac204b_second_run_skip_log
run_case "AC-204c session-init average under 500ms" test_ac204c_session_init_average_under_500ms
run_case "AC-301 run marker GC" test_ac301_run_marker_gc_archive_terminate_and_preserve

printf 'SUMMARY: passed=%s failed=%s total=%s\n' "$PASS_COUNT" "$FAIL_COUNT" "$((PASS_COUNT + FAIL_COUNT))"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi

exit 0
