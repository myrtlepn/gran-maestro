#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STOP_SCRIPT="$SCRIPT_DIR/hooks/mst-stop-hook.sh"
SESSION_INIT_SCRIPT="$SCRIPT_DIR/hooks/mst-session-init.sh"
STATUSLINE_SCRIPT="$SCRIPT_DIR/scripts/mst-statusline.sh"
MST_SCRIPT="$SCRIPT_DIR/scripts/mst.py"

PASS=0
FAIL=0
TOTAL=0

OUTFILE="/tmp/mst-stop-hook-out-$$.txt"
ERRFILE="/tmp/mst-stop-hook-err-$$.txt"
INFILE="/tmp/mst-stop-hook-in-$$.txt"

MY_PID="$$"
MST_TMP="${SCRIPT_DIR}/.gran-maestro/tmp"
STATE_FILE="${MST_TMP}/mst-state-${MY_PID}.json"
mkdir -p "$MST_TMP"

cleanup() {
  rm -f "$OUTFILE" "$ERRFILE" "$INFILE" "$STATE_FILE" "${STATE_FILE}.tmp" 2>/dev/null || true
  rm -f \
    "${MST_TMP}/mst-call-stack-${MY_PID}.json" \
    "${MST_TMP}/mst-pending-continuation-${MY_PID}" \
    "${MST_TMP}/mst-next-action-${MY_PID}.json" \
    "${MST_TMP}/mst-next-action-count-${MY_PID}" \
    "${MST_TMP}/mst-next-action-state-${MY_PID}" \
    "${MST_TMP}/mst-stop-hook-count-${MY_PID}" \
    "${MST_TMP}/mst-hook-debug-${MY_PID}.log" \
    "${MST_TMP}/mst-hook-check-done-${MY_PID}" \
    "${MST_TMP}/mst-transcript-${MY_PID}.path" \
    2>/dev/null || true
  rm -f "$SCRIPT_DIR/.claude/hooks/.mst-hook-version" 2>/dev/null || true
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

assert_empty() {
  local test_name="$1" actual="$2"
  TOTAL=$((TOTAL + 1))
  if [ -z "$actual" ]; then
    echo "  PASS: $test_name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $test_name"
    echo "    expected empty, got: $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local test_name="$1" needle="$2" haystack="$3"
  TOTAL=$((TOTAL + 1))
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $test_name"
    echo "    expected to not contain: $needle"
    echo "    actual: $haystack"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $test_name"
    PASS=$((PASS + 1))
  fi
}

run_stop() {
  local input="$1"
  printf '%s' "$input" > "$INFILE"
  set +e
  bash "$STOP_SCRIPT" < "$INFILE" > "$OUTFILE" 2> "$ERRFILE"
  STOP_EXIT=$?
  set -e
}

run_session_init() {
  set +e
  bash "$SESSION_INIT_SCRIPT" > "$OUTFILE" 2> "$ERRFILE"
  SESSION_EXIT=$?
  set -e
}

run_set_workflow() {
  set +e
  (
    cd "$SCRIPT_DIR" || exit 1
    MST_STATE_PPID="$MY_PID" python3 "$MST_SCRIPT" state set-workflow "$@"
  ) > "$OUTFILE" 2> "$ERRFILE"
  SET_WORKFLOW_EXIT=$?
  set -e
}

write_state() {
  local payload="$1"
  printf '%s\n' "$payload" > "$STATE_FILE"
}

# ------------------------------------------------------------
echo "=== Test Suite: stop-hook core ==="

cleanup
run_stop '{"stop_hook_active":true}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "stop_hook_active=true exits 0" "0" "$STOP_EXIT"
assert_empty "stop_hook_active=true -> empty stdout" "$output"

cleanup
run_stop '{"stop_hook_active":false,"last_assistant_message":"AskUserQuestion"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "explicit allow pattern exits 0" "0" "$STOP_EXIT"
assert_empty "AskUserQuestion -> empty stdout" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":1,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"{\"tool_name\":\"AskUserQuestion\"} 계속 진행하시겠습니까?"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion(no marker) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion(no marker) -> block" '"decision": "block"' "$output"
assert_contains "agile + AskUserQuestion(no marker) reason includes continuation guard" 'Sprint loop active; continue to next sprint without stopping.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":2,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[스티어링 체크포인트] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([스티어링 체크포인트]) exits 0" "0" "$STOP_EXIT"
assert_empty "agile + AskUserQuestion([스티어링 체크포인트]) -> allow" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":3,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[비상 스티어링] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([비상 스티어링]) exits 0" "0" "$STOP_EXIT"
assert_empty "agile + AskUserQuestion([비상 스티어링]) -> allow" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":4,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[Sprint 0] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([Sprint 0]) exits 0" "0" "$STOP_EXIT"
assert_empty "agile + AskUserQuestion([Sprint 0]) -> allow" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":5,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[자동 중단] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([자동 중단]) exits 0" "0" "$STOP_EXIT"
assert_empty "agile + AskUserQuestion([자동 중단]) -> allow" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:request","active_req":"REQ-541","iteration":1,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"{\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "non-agile + AskUserQuestion exits 0" "0" "$STOP_EXIT"
assert_empty "non-agile + AskUserQuestion keeps existing allow" "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:plan","active_req":"REQ-496","iteration":3,"updated_at":"2026-03-28T00:00:00Z","next_action":{"skill":"mst:request","source":"PLN-364","auto":true}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_active=true exits 0" "0" "$STOP_EXIT"
assert_contains "workflow_active=true -> block" '"decision": "block"' "$output"
assert_contains "block reason includes next skill" 'mst:request' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:plan","active_req":"REQ-500","iteration":1,"updated_at":"2026-03-28T10:30:45Z","next_action":{"skill":"mst:request","source":"PLN-400","auto":false}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_contains "block reason includes updated_at timestamp" '2026-03-28T10:30:45Z' "$output"
assert_contains "workflow_active=true + next_auto=false includes continue guidance" 'Workflow active, continue current skill' "$output"
assert_not_contains "workflow_active=true + next_auto=false does not suggest next skill" 'Suggested next skill' "$output"

cleanup
write_state '{"workflow_active":false,"current_skill":"","active_req":"","iteration":0,"updated_at":"2026-03-28T00:00:00Z","next_action":{"skill":"","source":"","auto":false}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_active=false exits 0" "0" "$STOP_EXIT"
assert_empty "workflow_active=false -> allow" "$output"

# ------------------------------------------------------------
echo ""
echo "=== Test Suite: session-init + statusline ==="

cleanup
run_session_init
assert_eq "session-init exits 0" "0" "$SESSION_EXIT"
state_files="$(ls -1 "${MST_TMP}"/mst-state-*.json 2>/dev/null || true)"
assert_contains "session-init creates mst-state file" "mst-state-" "$state_files"

legacy_markers="$(ls -1 "${MST_TMP}"/mst-* 2>/dev/null | grep -E 'mst-(call-stack|pending-continuation|next-action|next-action-count|next-action-state|stop-hook-count|hook-debug|hook-check-done|transcript)-' || true)"
assert_empty "legacy marker files are absent after session-init" "$legacy_markers"

cleanup
write_state '{"workflow_active":true,"current_skill":"plan","active_req":"REQ-001","iteration":1,"updated_at":"2026-03-28T00:00:00Z","next_action":{"skill":"mst:request","source":"PLN-001","auto":true}}'
statusline_output="$(printf '{}' | bash "$STATUSLINE_SCRIPT" 2>/dev/null || true)"
assert_contains "statusline includes skill" "plan" "$statusline_output"
assert_contains "statusline includes REQ" "REQ-001" "$statusline_output"

# ------------------------------------------------------------
echo ""
echo "=== Test Suite: state set-workflow ==="

cleanup
run_set_workflow --active true --skill mst:plan --req "" --next-skill mst:request --next-source PLN-377 --source-skill mst:plan --auto true
assert_eq "state set-workflow(active=true) exits 0" "0" "$SET_WORKFLOW_EXIT"
state_payload="$(cat "$STATE_FILE" 2>/dev/null || true)"
assert_contains "state set-workflow(active=true) sets workflow_active" '"workflow_active": true' "$state_payload"
assert_contains "state set-workflow(active=true) sets current_skill" '"current_skill": "mst:plan"' "$state_payload"
assert_contains "state set-workflow(active=true) sets expected_skill" '"expected_skill": "mst:request"' "$state_payload"
assert_contains "state set-workflow(active=true) sets source_id" '"source_id": "PLN-377"' "$state_payload"
assert_contains "state set-workflow(active=true) sets auto_mode" '"auto_mode": true' "$state_payload"

run_set_workflow --active false
assert_eq "state set-workflow(active=false) exits 0" "0" "$SET_WORKFLOW_EXIT"
state_payload="$(cat "$STATE_FILE" 2>/dev/null || true)"
assert_contains "state set-workflow(active=false) clears workflow_active" '"workflow_active": false' "$state_payload"
assert_contains "state set-workflow(active=false) clears expected_skill" '"expected_skill": ""' "$state_payload"
assert_contains "state set-workflow(active=false) clears source_id" '"source_id": ""' "$state_payload"
assert_contains "state set-workflow(active=false) clears auto_mode" '"auto_mode": false' "$state_payload"

# ------------------------------------------------------------
echo ""
echo "=== Test Suite: session-init version gate warning ==="

cleanup
mkdir -p "$SCRIPT_DIR/.claude/hooks"
printf '0.0.0\n' > "$SCRIPT_DIR/.claude/hooks/.mst-hook-version"
run_session_init
stderr_output="$(cat "$ERRFILE" 2>/dev/null || true)"
assert_eq "version mismatch still exits 0" "0" "$SESSION_EXIT"
assert_contains "version mismatch warning emitted" "hook version mismatch" "$stderr_output"

cleanup

echo ""
echo "==============================="
echo "Results: $PASS/$TOTAL passed, $FAIL failed"
echo "==============================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
