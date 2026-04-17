#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION_INIT_SCRIPT="$SCRIPT_DIR/hooks/mst-session-init.sh"

PASS=0
FAIL=0
TOTAL=0

TMP_ROOTS=()

cleanup() {
  local dir
  for dir in "${TMP_ROOTS[@]:-}"; do
    rm -rf "$dir" 2>/dev/null || true
  done
}

trap cleanup EXIT

assert_eq() {
  local test_name="$1" expected="$2" actual="$3"
  TOTAL=$((TOTAL + 1))
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: $test_name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $test_name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local test_name="$1" needle="$2" haystack="$3"
  TOTAL=$((TOTAL + 1))
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $test_name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $test_name"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack"
    FAIL=$((FAIL + 1))
  fi
}

new_tmp_root() {
  local dir
  dir="$(mktemp -d)"
  TMP_ROOTS+=("$dir")
  printf '%s\n' "$dir"
}

write_config() {
  local project_root="$1" enabled="$2" guard_seconds="$3"
  mkdir -p "$project_root/.gran-maestro"
  cat > "$project_root/.gran-maestro/config.resolved.json" <<JSON
{
  "gardening": {
    "auto_archive": {
      "enabled": $enabled,
      "session_init_guard_seconds": $guard_seconds
    }
  }
}
JSON
}

write_fake_plugin() {
  local plugin_root="$1"
  mkdir -p "$plugin_root/scripts"
  cat > "$plugin_root/scripts/mst.py" <<'PY'
import os
import sys

log_path = os.environ.get("MST_TEST_LOG", "")
if log_path:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(" ".join(sys.argv[1:]) + "\n")
PY
}

run_session_init() {
  local project_root="$1" plugin_root="$2" log_file="$3"
  set +e
  (
    cd "$project_root" || exit 1
    MST_TEST_LOG="$log_file" PLUGIN_ROOT="$plugin_root" bash "$SESSION_INIT_SCRIPT" >/dev/null 2>&1
  )
  SESSION_EXIT=$?
  set -e
}

wait_for_non_empty_file() {
  local path="$1"
  local i
  for i in $(seq 1 30); do
    if [ -s "$path" ]; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

# ------------------------------------------------------------
echo "=== Test Suite: session-init gardening auto-archive trigger ==="

echo ""
echo "Case 1: enabled=true and no recent run -> spawn + stamp update"
tmp_root="$(new_tmp_root)"
project_root="$tmp_root/project"
plugin_root="$tmp_root/plugin"
log_file="$tmp_root/gardening-invocations.log"
stamp_file="$project_root/.gran-maestro/tmp/gardening-last-run"
mkdir -p "$project_root"
write_config "$project_root" true 86400
write_fake_plugin "$plugin_root"
run_session_init "$project_root" "$plugin_root" "$log_file"
assert_eq "case1 exits 0" "0" "$SESSION_EXIT"
spawned=0
if wait_for_non_empty_file "$log_file"; then
  spawned=1
fi
assert_eq "case1 background spawn happened" "1" "$spawned"
log_content="$(cat "$log_file" 2>/dev/null || true)"
assert_contains "case1 spawn args include auto-archive" "gardening auto-archive --silent" "$log_content"
stamp_exists=0
if [ -f "$stamp_file" ]; then
  stamp_exists=1
fi
assert_eq "case1 stamp file created" "1" "$stamp_exists"
stamp_value="$(cat "$stamp_file" 2>/dev/null || true)"
case "$stamp_value" in
  ''|*[!0-9]*) stamp_is_numeric=0 ;;
  *) stamp_is_numeric=1 ;;
esac
assert_eq "case1 stamp is epoch seconds" "1" "$stamp_is_numeric"

echo ""
echo "Case 2: last run 1 hour ago (within guard) -> skip + stamp unchanged"
tmp_root="$(new_tmp_root)"
project_root="$tmp_root/project"
plugin_root="$tmp_root/plugin"
log_file="$tmp_root/gardening-invocations.log"
stamp_file="$project_root/.gran-maestro/tmp/gardening-last-run"
mkdir -p "$project_root/.gran-maestro/tmp"
write_config "$project_root" true 86400
write_fake_plugin "$plugin_root"
before_stamp="$(( $(date +%s) - 3600 ))"
printf '%s\n' "$before_stamp" > "$stamp_file"
run_session_init "$project_root" "$plugin_root" "$log_file"
assert_eq "case2 exits 0" "0" "$SESSION_EXIT"
sleep 0.5
spawned=0
if [ -s "$log_file" ]; then
  spawned=1
fi
assert_eq "case2 no background spawn" "0" "$spawned"
after_stamp="$(cat "$stamp_file" 2>/dev/null || true)"
assert_eq "case2 stamp unchanged" "$before_stamp" "$after_stamp"

echo ""
echo "Case 3: enabled=false -> skip regardless of stamp"
tmp_root="$(new_tmp_root)"
project_root="$tmp_root/project"
plugin_root="$tmp_root/plugin"
log_file="$tmp_root/gardening-invocations.log"
stamp_file="$project_root/.gran-maestro/tmp/gardening-last-run"
mkdir -p "$project_root/.gran-maestro/tmp"
write_config "$project_root" false 86400
write_fake_plugin "$plugin_root"
before_stamp="$(( $(date +%s) - 12345 ))"
printf '%s\n' "$before_stamp" > "$stamp_file"
run_session_init "$project_root" "$plugin_root" "$log_file"
assert_eq "case3 exits 0" "0" "$SESSION_EXIT"
sleep 0.5
spawned=0
if [ -s "$log_file" ]; then
  spawned=1
fi
assert_eq "case3 no background spawn" "0" "$spawned"
after_stamp="$(cat "$stamp_file" 2>/dev/null || true)"
assert_eq "case3 stamp unchanged" "$before_stamp" "$after_stamp"

echo ""
echo "==============================="
echo "Results: $PASS/$TOTAL passed, $FAIL failed"
echo "==============================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi

exit 0
