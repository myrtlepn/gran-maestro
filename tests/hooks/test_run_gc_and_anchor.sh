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

assert_dir_exists() {
  local name="$1"
  local path="$2"
  if [ ! -d "$path" ]; then
    printf 'FAIL: %s\n  missing directory: %s\n' "$name" "$path" >&2
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

assert_file_content() {
  local name="$1"
  local expected="$2"
  local path="$3"
  local actual

  assert_file_exists "$name" "$path"
  actual="$(tr -d '\n' < "$path")"
  if [ "$expected" != "$actual" ]; then
    printf 'FAIL: %s\n  expected content: %s\n  actual content:   %s\n' "$name" "$expected" "$actual" >&2
    exit 1
  fi
}

assert_nonempty() {
  local name="$1"
  local actual="$2"
  if [ -z "$actual" ]; then
    printf 'FAIL: %s\n  expected non-empty value\n' "$name" >&2
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

  mkdir -p "$project_root/.gran-maestro" "$project_root/scripts" "$project_root/.claude-plugin"
  printf '%s\n' "$content" > "$project_root/scripts/mst-statusline.sh"
  chmod +x "$project_root/scripts/mst-statusline.sh"
  printf '{"version":"TEST"}\n' > "$project_root/.claude-plugin/plugin.json"
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
  local ppid_file="${5:-}"

  (
    cd "$project_root"
    if [ -n "$ppid_file" ]; then
      sh -c 'printf "%s\n" "$PPID"' > "$ppid_file"
    fi
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

assert_state_bridge_anchor_created() {
  local name="$1"
  local project_root="$2"
  local tmp_dir="$project_root/.gran-maestro/tmp"
  local state_file pid bridge_file anchor_file

  state_file="$(require_single_file_match "$name state file" "$tmp_dir/mst-state-*.json")"
  pid="${state_file##*mst-state-}"
  pid="${pid%.json}"
  bridge_file="$tmp_dir/claude-session-${pid}.id"
  anchor_file="$tmp_dir/mst-session-anchor-${pid}.pid"

  assert_file_exists "$name bridge file" "$bridge_file"
  assert_file_content "$name bridge content" "$SESSION_ID" "$bridge_file"
  assert_file_exists "$name anchor file" "$anchor_file"
  assert_file_content "$name anchor content" "$pid" "$anchor_file"
}

run_resolver() {
  local project_root="$1"
  (
    cd "$project_root"
    PYTHONPATH="$REPO_ROOT" python3 -c "from scripts.mst_cmds._common import resolve_started_by_pid; print(resolve_started_by_pid())"
  )
}

test_ac101_archive_end_to_end() {
  local case_dir project_root claude_home stdout_file stderr_file run_dir archive_file

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  run_dir="$project_root/.gran-maestro/run"

  write_project_fixture "$project_root" "# run gc archive fixture"
  create_fake_cache_targets "$claude_home"
  mkdir -p "$run_dir"

  python3 - "$run_dir" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
now = datetime.now(timezone.utc).replace(microsecond=0)

fixtures = {
    "done-old.json": {
        "task_id": "done-old",
        "phase": "done",
        "last_heartbeat": (now - timedelta(days=8)).isoformat().replace("+00:00", "Z"),
    },
    "done-recent.json": {
        "task_id": "done-recent",
        "phase": "done",
        "last_heartbeat": now.isoformat().replace("+00:00", "Z"),
    },
}

for filename, payload in fixtures.items():
    (run_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  assert_file_missing "AC-101 archived marker removed from run dir" "$run_dir/done-old.json"
  archive_file="$(require_single_file_match "AC-101 archived marker" "$project_root/.gran-maestro/archive/run/*/done-old.json")"
  assert_file_exists "AC-101 archived marker exists" "$archive_file"
  assert_file_exists "AC-101 recent marker remains in run dir" "$run_dir/done-recent.json"
  assert_eq "AC-101 recent marker phase unchanged" "done" "$(json_field "$run_dir/done-recent.json" "phase")"
}

test_ac102_dead_pid_running_terminated() {
  local case_dir project_root claude_home stdout_file stderr_file run_dir marker phase terminated_at

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  run_dir="$project_root/.gran-maestro/run"
  marker="$run_dir/dead-running.json"

  write_project_fixture "$project_root" "# run gc terminate fixture"
  create_fake_cache_targets "$claude_home"
  mkdir -p "$run_dir"

  python3 - "$marker" <<'PY'
import json
import sys
from datetime import datetime, timezone

payload = {
    "task_id": "dead-running",
    "phase": "running",
    "started_by_pid": 999999,
    "last_heartbeat": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"

  phase="$(json_field "$marker" "phase")"
  terminated_at="$(json_field "$marker" "terminated_at")"
  assert_eq "AC-102 dead running phase" "terminated" "$phase"
  assert_nonempty "AC-102 terminated_at" "$terminated_at"
}

test_ac103_live_ppid_running_preserved() {
  local case_dir project_root claude_home stdout_file stderr_file run_dir marker mtime_file
  local mtime_before mtime_after phase

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  run_dir="$project_root/.gran-maestro/run"
  marker="$run_dir/live-running.json"
  mtime_file="$case_dir/live-running.mtime"

  write_project_fixture "$project_root" "# run gc live fixture"
  create_fake_cache_targets "$claude_home"
  mkdir -p "$run_dir"

  (
    cd "$project_root"
    current_ppid="$(sh -c 'printf "%s\n" "$PPID"')"
    python3 - "$marker" "$current_ppid" <<'PY'
import json
import sys
from datetime import datetime, timezone

payload = {
    "task_id": "live-running",
    "phase": "running",
    "started_by_pid": int(sys.argv[2]),
    "last_heartbeat": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
    touch -t 202001010000 "$marker"
    stat_mtime "$marker" > "$mtime_file"
    MST_CLAUDE_HOME="$claude_home" \
      HOME="$claude_home" \
      MST_DEBUG=1 \
      PLUGIN_ROOT="$REPO_ROOT" \
      bash "$SESSION_INIT_SCRIPT" >"$stdout_file" 2>"$stderr_file" <<JSON
{"session_id":"$SESSION_ID"}
JSON
  )

  mtime_before="$(tr -d '\n' < "$mtime_file")"
  phase="$(json_field "$marker" "phase")"
  mtime_after="$(stat_mtime "$marker")"
  assert_eq "AC-103 live running phase unchanged" "running" "$phase"
  assert_eq "AC-103 live running mtime unchanged" "$mtime_before" "$mtime_after"
}

test_ac104_session_anchor_written() {
  local case_dir project_root claude_home stdout_file stderr_file ppid_file expected_ppid anchor_file

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  ppid_file="$case_dir/session-init-parent.pid"

  write_project_fixture "$project_root" "# anchor fixture"
  create_fake_cache_targets "$claude_home"

  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file" "$ppid_file"

  expected_ppid="$(tr -d '\n' < "$ppid_file")"
  anchor_file="$project_root/.gran-maestro/tmp/mst-session-anchor-${expected_ppid}.pid"
  assert_file_exists "AC-104 session anchor file" "$anchor_file"
  assert_file_content "AC-104 session anchor content" "$expected_ppid" "$anchor_file"
}

test_ac105_resolve_started_by_pid() {
  local case_dir project_root actual anchor_pid expected_file actual_file expected

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project-env"
  write_project_fixture "$project_root" "# resolver env fixture"
  actual="$(
    cd "$project_root"
    MST_STATE_PPID=12345 PYTHONPATH="$REPO_ROOT" \
      python3 -c "from scripts.mst_cmds._common import resolve_started_by_pid; print(resolve_started_by_pid())"
  )"
  assert_eq "AC-105a env MST_STATE_PPID wins" "12345" "$actual"

  project_root="$case_dir/project-anchor"
  write_project_fixture "$project_root" "# resolver anchor fixture"
  mkdir -p "$project_root/.gran-maestro/tmp"
  anchor_pid="$$"
  printf '%s\n' "$anchor_pid" > "$project_root/.gran-maestro/tmp/mst-session-anchor-${anchor_pid}.pid"
  actual="$(unset MST_STATE_PPID; run_resolver "$project_root")"
  assert_eq "AC-105b anchor file resolves" "$anchor_pid" "$actual"

  project_root="$case_dir/project-ppid"
  write_project_fixture "$project_root" "# resolver ppid fallback fixture"
  rm -f "$project_root/.gran-maestro/tmp"/mst-session-anchor-*.pid 2>/dev/null || true
  expected_file="$case_dir/expected-ppid.txt"
  actual_file="$case_dir/actual-ppid.txt"
  (
    cd "$project_root"
    unset MST_STATE_PPID
    sh -c 'printf "%s\n" "$$" > "$1"; PYTHONPATH="$2" python3 -c "from scripts.mst_cmds._common import resolve_started_by_pid; print(resolve_started_by_pid())" > "$3"' sh "$expected_file" "$REPO_ROOT" "$actual_file"
  )
  expected="$(tr -d '\n' < "$expected_file")"
  actual="$(tr -d '\n' < "$actual_file")"
  assert_eq "AC-105c os.getppid fallback" "$expected" "$actual"
}

test_ac106_session_init_regression_surface() {
  local case_dir project_root claude_home stdout_file stderr_file tmp_dir status
  local source_file cache_file marketplace_file hash_source

  case_dir="$(new_case_dir)"
  project_root="$case_dir/project"
  claude_home="$case_dir/home"
  stdout_file="$case_dir/stdout.log"
  stderr_file="$case_dir/stderr.log"
  tmp_dir="$project_root/.gran-maestro/tmp"

  write_project_fixture "$project_root" "# regression fixture"
  create_fake_cache_targets "$claude_home"
  mkdir -p "$tmp_dir"
  printf '{}\n' > "$tmp_dir/mst-call-stack-stale.json"
  printf '{}\n' > "$tmp_dir/mst-next-action-stale.json"
  printf 'stale\n' > "$tmp_dir/mst-pending-continuation-stale"
  printf 'stale\n' > "$tmp_dir/mst-stop-hook-count-stale"

  set +e
  run_session_init "$project_root" "$claude_home" "$stdout_file" "$stderr_file"
  status=$?
  set -e

  assert_eq "AC-106 session-init exit code" "0" "$status"
  assert_dir_exists "AC-106 MST_TMP created" "$tmp_dir"
  assert_file_missing "AC-106 cleanup stale call stack" "$tmp_dir/mst-call-stack-stale.json"
  assert_file_missing "AC-106 cleanup stale next action" "$tmp_dir/mst-next-action-stale.json"
  assert_file_missing "AC-106 cleanup stale pending continuation" "$tmp_dir/mst-pending-continuation-stale"
  assert_file_missing "AC-106 cleanup stale stop hook count" "$tmp_dir/mst-stop-hook-count-stale"

  source_file="$project_root/scripts/mst-statusline.sh"
  cache_file="$claude_home/.claude/plugins/cache/gran-maestro/mst/TEST/scripts/mst-statusline.sh"
  marketplace_file="$claude_home/.claude/plugins/marketplaces/gran-maestro/scripts/mst-statusline.sh"
  assert_file_exists "AC-106 cache sync target" "$cache_file"
  assert_file_exists "AC-106 marketplace sync target" "$marketplace_file"
  hash_source="$(sha256_file "$source_file")"
  assert_eq "AC-106 cache sync hash" "$hash_source" "$(sha256_file "$cache_file")"
  assert_eq "AC-106 marketplace sync hash" "$hash_source" "$(sha256_file "$marketplace_file")"
  assert_state_bridge_anchor_created "AC-106" "$project_root"
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

run_case "AC-101 archive end-to-end" test_ac101_archive_end_to_end
run_case "AC-102 dead pid running terminated" test_ac102_dead_pid_running_terminated
run_case "AC-103 live PPID running preserved" test_ac103_live_ppid_running_preserved
run_case "AC-104 session anchor written" test_ac104_session_anchor_written
run_case "AC-105 resolve_started_by_pid" test_ac105_resolve_started_by_pid
run_case "AC-106 session-init regression surface" test_ac106_session_init_regression_surface

printf 'SUMMARY: passed=%s failed=%s total=%s\n' "$PASS_COUNT" "$FAIL_COUNT" "$((PASS_COUNT + FAIL_COUNT))"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi

exit 0
