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
ROOT_MST_SESSION_ID="MST-AGI-030-20260503T130813382Z-k7f3q9x2"
OTHER_MST_SESSION_ID="MST-AGI-030-20260503T130813382Z-z9y8x7w6"
TEST_PROJECT_ROOT="$(mktemp -d)"
MST_TMP="${TEST_PROJECT_ROOT}/.gran-maestro/tmp"
STATE_FILE="${MST_TMP}/mst-state-${ROOT_MST_SESSION_ID}.json"
REQUEST_FIXTURE_DIR="${TEST_PROJECT_ROOT}/.gran-maestro/requests/REQ-TEST-CONTINUATION-GUARD"
REQUEST_FIXTURE_FILE="${REQUEST_FIXTURE_DIR}/request.json"
PLAN_FIXTURE_DIR="${TEST_PROJECT_ROOT}/.gran-maestro/plans/PLN-TEST-CONTINUATION-GUARD"
PLAN_FIXTURE_FILE="${PLAN_FIXTURE_DIR}/plan.json"
mkdir -p "$MST_TMP" "$TEST_PROJECT_ROOT/.claude/hooks" "$TEST_PROJECT_ROOT/.claude-plugin"
printf '%s\n' '{"version":"0.0.1"}' > "$TEST_PROJECT_ROOT/.claude-plugin/plugin.json"

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
  rm -rf "$REQUEST_FIXTURE_DIR" "$PLAN_FIXTURE_DIR" 2>/dev/null || true
  rm -rf \
    "$TEST_PROJECT_ROOT/.gran-maestro/state" \
    "$TEST_PROJECT_ROOT/.gran-maestro/run" \
    "$TEST_PROJECT_ROOT/.gran-maestro/logs" \
    2>/dev/null || true
  rm -f "$TEST_PROJECT_ROOT/.claude/hooks/.mst-hook-version" 2>/dev/null || true
}

cleanup_all() {
  cleanup
  rm -rf "$TEST_PROJECT_ROOT" 2>/dev/null || true
}

trap cleanup_all EXIT

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

assert_stop_stdout_contract() {
  local test_name="$1" output_file="$2" expected_decision="$3" expected_reason_substring="$4"
  TOTAL=$((TOTAL + 1))
  if python3 - "$output_file" "$expected_decision" "$expected_reason_substring" <<'PY'
import json
import sys
from pathlib import Path

output_path, expected_decision, expected_reason_substring = sys.argv[1:4]
lines = [line for line in Path(output_path).read_text(encoding="utf-8").splitlines() if line.strip()]
if len(lines) != 1:
    raise SystemExit(f"expected exactly one non-empty stdout line, got {lines!r}")

payload = json.loads(lines[0])
if set(payload) != {"decision", "reason"}:
    raise SystemExit(f"unexpected stdout keys: {sorted(payload)}")
if payload.get("decision") != expected_decision:
    raise SystemExit(f"expected decision={expected_decision}, got {payload!r}")
reason = payload.get("reason")
if not isinstance(reason, str) or not reason.strip():
    raise SystemExit(f"missing reason: {payload!r}")
if expected_reason_substring and expected_reason_substring not in reason:
    raise SystemExit(
        f"expected reason to contain {expected_reason_substring!r}, got {reason!r}"
    )
PY
  then
    echo "  PASS: $test_name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $test_name"
    echo "    stdout: $(cat "$output_file" 2>/dev/null || true)"
    FAIL=$((FAIL + 1))
  fi
}

run_stop() {
  local input="$1"
  printf '%s' "$input" > "$INFILE"
  set +e
  (
    cd "$TEST_PROJECT_ROOT" || exit 1
    MST_SESSION_ID="$ROOT_MST_SESSION_ID" bash "$STOP_SCRIPT" < "$INFILE"
  ) > "$OUTFILE" 2> "$ERRFILE"
  STOP_EXIT=$?
  set -e
}

run_session_init() {
  set +e
  (
    cd "$TEST_PROJECT_ROOT" || exit 1
    MST_SESSION_ID="$ROOT_MST_SESSION_ID" bash "$SESSION_INIT_SCRIPT"
  ) > "$OUTFILE" 2> "$ERRFILE"
  SESSION_EXIT=$?
  set -e
}

run_set_workflow() {
  set +e
  (
    cd "$TEST_PROJECT_ROOT" || exit 1
    MST_SESSION_ID="$ROOT_MST_SESSION_ID" python3 "$MST_SCRIPT" state set-workflow "$@"
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
assert_contains "stop_hook_active=true -> approve" '"decision": "approve"' "$output"
assert_stop_stdout_contract "stop_hook_active=true stdout contract" "$OUTFILE" "approve" ""

cleanup
run_stop '{"stop_hook_active":false,"last_assistant_message":"AskUserQuestion"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "explicit allow pattern exits 0" "0" "$STOP_EXIT"
assert_contains "AskUserQuestion -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":1,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"{\"tool_name\":\"AskUserQuestion\"} 계속 진행하시겠습니까?"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion(no marker) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion(no marker) -> block" '"decision": "block"' "$output"
assert_contains "agile + AskUserQuestion(no marker) reason includes continuation guard" 'AskUserQuestion is allowed only with agile whitelist markers.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":2,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[스티어링 체크포인트] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([스티어링 체크포인트]) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion([스티어링 체크포인트]) -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":3,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[비상 스티어링] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([비상 스티어링]) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion([비상 스티어링]) -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":4,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[Sprint 0] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([Sprint 0]) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion([Sprint 0]) -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-541","iteration":5,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"[자동 중단] {\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile + AskUserQuestion([자동 중단]) exits 0" "0" "$STOP_EXIT"
assert_contains "agile + AskUserQuestion([자동 중단]) -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-577","iteration":6,"updated_at":"2026-04-05T00:00:00Z","agile_loop_active":true,"next_action":{"auto":true}}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"요약하고 계속합니다. 계속 진행할까요?"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile AUTO_MODE + 요약하고 계속 + 확인 질문 exits 0" "0" "$STOP_EXIT"
assert_contains "agile AUTO_MODE + 요약하고 계속 + 확인 질문 -> block" '"decision": "block"' "$output"
assert_contains "agile AUTO_MODE + 요약하고 계속 + 확인 질문 -> text-question branch" 'text-based question patterns are blocked.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-577","iteration":7,"updated_at":"2026-04-05T00:00:00Z","agile_loop_active":true,"next_action":{"auto":true}}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"컨텍스트가 길어지고 있으므로 정리하고 계속합니다"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile AUTO_MODE + 컨텍스트 길이 사유 정리하고 계속 exits 0" "0" "$STOP_EXIT"
assert_contains "agile AUTO_MODE + 컨텍스트 길이 사유 정리하고 계속 -> block" '"decision": "block"' "$output"
assert_contains "agile AUTO_MODE + 컨텍스트 길이 사유 정리하고 계속 -> text-question branch" 'text-based question patterns are blocked.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-578","iteration":8,"updated_at":"2026-04-05T00:00:00Z","agile_loop_active":true,"steering_disabled":true,"next_action":{"auto":false}}'
run_stop '{"stop_hook_active":false,"agile_auto_mode":false,"last_assistant_message":"계속 진행할까요?"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile STEERING_DISABLED + AUTO_MODE=false + 확인 질문 exits 0" "0" "$STOP_EXIT"
assert_contains "agile STEERING_DISABLED + AUTO_MODE=false + 확인 질문 -> block" '"decision": "block"' "$output"
assert_contains "agile STEERING_DISABLED + AUTO_MODE=false + 확인 질문 -> steering branch reason" 'AUTO_MODE=true or STEERING_DISABLED=true' "$output"
assert_contains "agile STEERING_DISABLED + AUTO_MODE=false + 확인 질문 -> text-question branch" 'text-based question patterns are blocked.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:agile","active_req":"REQ-578","iteration":9,"updated_at":"2026-04-05T00:00:00Z","agile_loop_active":true,"steering_disabled":false,"next_action":{"auto":false}}'
run_stop '{"stop_hook_active":false,"agile_auto_mode":false,"last_assistant_message":"계속 진행할까요?"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile STEERING_DISABLED=false + AUTO_MODE=false + 확인 질문 exits 0" "0" "$STOP_EXIT"
assert_contains "agile STEERING_DISABLED=false + AUTO_MODE=false + 확인 질문 -> 기존 workflow block 유지" '"decision": "block"' "$output"
assert_contains "agile STEERING_DISABLED=false + AUTO_MODE=false + 확인 질문 -> 기존 이유 유지" 'Workflow active, continue current skill' "$output"
assert_not_contains "agile STEERING_DISABLED=false + AUTO_MODE=false + 확인 질문 -> text-question branch 미진입" 'text-based question patterns are blocked.' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:request","active_req":"REQ-541","iteration":1,"updated_at":"2026-03-31T00:00:00Z"}'
run_stop '{"stop_hook_active":false,"last_assistant_message":"{\"tool_name\":\"AskUserQuestion\"}"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "non-agile + AskUserQuestion exits 0" "0" "$STOP_EXIT"
assert_contains "non-agile + AskUserQuestion keeps existing allow" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:plan","active_req":"REQ-496","iteration":3,"updated_at":"2026-03-28T00:00:00Z","next_action":{"skill":"mst:request","source":"PLN-364","auto":true}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_active=true exits 0" "0" "$STOP_EXIT"
assert_contains "workflow_active=true -> block" '"decision": "block"' "$output"
assert_contains "block reason includes next skill" 'mst:request' "$output"
assert_stop_stdout_contract "workflow_active=true stdout contract" "$OUTFILE" "block" "Workflow active, continue current skill"

cleanup
write_state '{"workflow_active":true,"current_skill":"mst:plan","active_req":"REQ-500","iteration":1,"updated_at":"2026-03-28T10:30:45Z","next_action":{"skill":"mst:request","source":"PLN-400","auto":false}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_contains "block reason includes updated_at timestamp" '2026-03-28T10:30:45Z' "$output"
assert_contains "workflow_active=true + next_auto=false includes continue guidance" 'Workflow active, continue current skill' "$output"
assert_not_contains "workflow_active=true + next_auto=false does not suggest next skill" 'Suggested next skill' "$output"

cleanup
write_state '{"workflow_active":false,"agile_loop_active":false,"current_skill":"","active_req":"REQ-627","iteration":1,"updated_at":"2026-04-14T00:00:00Z"}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_inactive_agile_loop_false exits 0" "0" "$STOP_EXIT"
assert_contains "workflow_inactive_agile_loop_false -> approve pass_through" '"decision": "approve"' "$output"

cleanup
mkdir -p "$REQUEST_FIXTURE_DIR"
printf '%s\n' "{\"id\":\"REQ-TEST-CONTINUATION-GUARD\",\"status\":\"phase1_analysis\",\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\"}" > "$REQUEST_FIXTURE_FILE"
run_stop "{\"stop_hook_active\":false,\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\",\"last_assistant_message\":\"status update\"}"
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "stop_hook_blocks_when_state_missing_and_active_request_exists exits 0" "0" "$STOP_EXIT"
assert_contains "stop_hook_blocks_when_state_missing_and_active_request_exists -> block" '"decision": "block"' "$output"
assert_contains "stop_hook_blocks_when_state_missing_and_active_request_exists reason" 'active workflow session detected' "$output"

cleanup
mkdir -p "$REQUEST_FIXTURE_DIR" "$PLAN_FIXTURE_DIR"
printf '%s\n' '{"id":"REQ-TEST-CONTINUATION-GUARD","status":"done"}' > "$REQUEST_FIXTURE_FILE"
printf '%s\n' '{"id":"PLN-TEST-CONTINUATION-GUARD","status":"completed"}' > "$PLAN_FIXTURE_FILE"
run_stop '{"stop_hook_active":false,"last_assistant_message":"status update"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "stop_hook_allows_when_only_terminal_requests_exist exits 0" "0" "$STOP_EXIT"
assert_contains "stop_hook_allows_when_only_terminal_requests_exist -> approve pass_through" '"decision": "approve"' "$output"

cleanup
mkdir -p "$REQUEST_FIXTURE_DIR/tasks/06"
printf '%s\n' '{"id":"REQ-TEST-CONTINUATION-GUARD","status":"done"}' > "$REQUEST_FIXTURE_FILE"
printf '%s\n' '{"id":"REQ-TEST-CONTINUATION-GUARD-T06","status":"pending"}' > "$REQUEST_FIXTURE_DIR/tasks/06/task.json"
run_stop '{"stop_hook_active":false,"last_assistant_message":"status update"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "terminal_request_with_stale_pending_task_does_not_block exits 0" "0" "$STOP_EXIT"
assert_contains "terminal_request_with_stale_pending_task_does_not_block -> approve pass_through" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":false,"current_skill":"mst:agile","agile_loop_active":true,"active_req":"REQ-xxx","iteration":5,"updated_at":"2026-04-14T00:00:00Z"}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "agile_resume_after_accept exits 0" "0" "$STOP_EXIT"
assert_contains "agile_resume_after_accept -> AGILE-CONTINUE" "AGILE-CONTINUE" "$output"
assert_contains "agile_resume_after_accept -> objective-check" "objective-check" "$output"
assert_stop_stdout_contract "agile_resume_after_accept stdout contract" "$OUTFILE" "block" "[AGILE-CONTINUE]"

cleanup
run_stop '{"stop_hook_active":false,"last_assistant_message":"return_to=mst:plan/step-2"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_inactive return_to exits 0" "0" "$STOP_EXIT"
assert_contains "workflow_inactive return_to -> block" '"decision": "block"' "$output"
assert_contains "workflow_inactive return_to -> reason includes resume hint" '/mst:resume --wakeup-hint stop-recover' "$output"
assert_stop_stdout_contract "workflow_inactive return_to stdout contract" "$OUTFILE" "block" "[RETURN-TO] Sub-skill returned with return_to=mst:plan/step-2"

cleanup
mkdir -p "$TEST_PROJECT_ROOT/.gran-maestro/state/$ROOT_MST_SESSION_ID"
printf '%s\n' "{\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\",\"currentSkill\":\"mst:request\",\"currentStep\":0,\"totalSteps\":3}" > "$TEST_PROJECT_ROOT/.gran-maestro/state/$ROOT_MST_SESSION_ID/snapshot.json"
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "snapshot step progress exits 0" "0" "$STOP_EXIT"
assert_contains "snapshot step progress -> block" '"decision": "block"' "$output"
assert_contains "snapshot step progress -> reason includes skill" '[SNAPSHOT][step_progress] skill mst:request step 1/3' "$output"
assert_stop_stdout_contract "snapshot step progress stdout contract" "$OUTFILE" "block" "[SNAPSHOT][step_progress]"

cleanup
mkdir -p "$TEST_PROJECT_ROOT/.gran-maestro/run"
printf '%s\n' '{"delegate_io_attention_events":[{"kind":"delegate_io_attention","event_id":"evt-1","task_id":"REQ-850-T01","provider":"claude","pid":123,"signal":"stdin_timeout","confidence":"high","allowed_actions":["resume"],"forbidden_reasons":["write_child_stdin"],"observed_at":"2099-01-01T00:00:00Z","expires_at":"2099-01-02T00:00:00Z"}]}' > "$TEST_PROJECT_ROOT/.gran-maestro/run/attention.json"
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "delegate io attention exits 0" "0" "$STOP_EXIT"
assert_contains "delegate io attention -> block" '"decision": "block"' "$output"
assert_contains "delegate io attention -> reason includes context" 'event_id=evt-1 task_id=REQ-850-T01' "$output"
assert_stop_stdout_contract "delegate io attention stdout contract" "$OUTFILE" "block" "[DELEGATE-IO] pending delegate_io_attention event:"

cleanup
write_state '{"workflow_active":false,"agile_loop_active":false,"current_skill":"","active_req":"REQ-627","iteration":2,"updated_at":"2026-04-14T00:00:00Z","next_action":{"skill":"","source":"","auto":false}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "standalone_accept_simulation exits 0" "0" "$STOP_EXIT"
assert_contains "standalone_accept_simulation -> approve" '"decision": "approve"' "$output"

cleanup
write_state '{"workflow_active":false,"current_skill":"","active_req":"","iteration":0,"updated_at":"2026-03-28T00:00:00Z","next_action":{"skill":"","source":"","auto":false}}'
run_stop '{"stop_hook_active":false}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "workflow_active=false exits 0" "0" "$STOP_EXIT"
assert_contains "workflow_active=false -> approve" '"decision": "approve"' "$output"

# ------------------------------------------------------------
echo ""
echo "=== Test Suite: session-init + statusline ==="

cleanup
legacy_markers_before="$(ls -1 "${MST_TMP}"/mst-* 2>/dev/null | grep -E 'mst-(call-stack|pending-continuation|next-action|next-action-count|next-action-state|stop-hook-count|hook-debug|hook-check-done|transcript)-' || true)"
run_session_init
assert_eq "session-init exits 0" "0" "$SESSION_EXIT"
state_files="$(ls -1 "${MST_TMP}"/mst-state-*.json 2>/dev/null || true)"
assert_contains "session-init creates mst-state file" "mst-state-" "$state_files"

legacy_markers_after="$(ls -1 "${MST_TMP}"/mst-* 2>/dev/null | grep -E 'mst-(call-stack|pending-continuation|next-action|next-action-count|next-action-state|stop-hook-count|hook-debug|hook-check-done|transcript)-' || true)"
legacy_markers="$(comm -13 <(printf '%s\n' "$legacy_markers_before" | sort) <(printf '%s\n' "$legacy_markers_after" | sort) | grep . || true)"
assert_empty "legacy marker files are absent after session-init" "$legacy_markers"

cleanup
transcript_fixture="/tmp/mst-statusline-transcript-$$.jsonl"
cat > "$transcript_fixture" <<'EOF'
{"timestamp":"2026-04-18T00:00:01Z","message":{"content":[{"type":"tool_use","id":"toolu_1","name":"Skill","input":{"skill":"mst:plan","args":"REQ-001"}}]}}
EOF
statusline_output="$(printf '%s' "{\"transcript_path\":\"$transcript_fixture\"}" | bash "$STATUSLINE_SCRIPT" 2>/dev/null || true)"
rm -f "$transcript_fixture"
last_statusline_line="$(printf '%s\n' "$statusline_output" | grep -v '^$' | tail -n 1)"
assert_contains "statusline includes skill" "plan" "$last_statusline_line"
assert_contains "statusline includes REQ" "REQ-001" "$last_statusline_line"

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
mkdir -p "$TEST_PROJECT_ROOT/.claude/hooks"
printf '0.0.0\n' > "$TEST_PROJECT_ROOT/.claude/hooks/.mst-hook-version"
run_session_init
stderr_output="$(cat "$ERRFILE" 2>/dev/null || true)"
assert_eq "version mismatch still exits 0" "0" "$SESSION_EXIT"
assert_contains "version mismatch warning emitted" "hook version mismatch" "$stderr_output"

cleanup

# ------------------------------------------------------------
echo ""
echo "=== Test Suite: session isolation (AC-001, AC-002, AC-003) ==="

# AC-001: other_session_req_does_not_block
# 다른 canonical mst_session_id의 non-terminal REQ가 있어도 현재 세션 stop은 pass-through
cleanup
mkdir -p "$REQUEST_FIXTURE_DIR"
printf '%s\n' "{\"id\":\"REQ-TEST-CONTINUATION-GUARD\",\"status\":\"phase1_analysis\",\"mst_session_id\":\"${OTHER_MST_SESSION_ID}\"}" > "$REQUEST_FIXTURE_FILE"
run_stop "{\"stop_hook_active\":false,\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\",\"last_assistant_message\":\"status update\"}"
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "other_session_req_does_not_block exits 0" "0" "$STOP_EXIT"
assert_contains "other_session_req_does_not_block -> approve JSON" '"decision": "approve"' "$output"

# AC-002: same_session_req_still_blocks
# 현재 canonical mst_session_id의 non-terminal REQ가 있으면 canonical state 파일 유실 시에도 block
cleanup
mkdir -p "$REQUEST_FIXTURE_DIR"
printf '%s\n' "{\"id\":\"REQ-TEST-CONTINUATION-GUARD\",\"status\":\"phase1_analysis\",\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\"}" > "$REQUEST_FIXTURE_FILE"
run_stop "{\"stop_hook_active\":false,\"mst_session_id\":\"${ROOT_MST_SESSION_ID}\",\"last_assistant_message\":\"status update\"}"
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "same_session_req_still_blocks exits 0" "0" "$STOP_EXIT"
assert_contains "same_session_req_still_blocks -> block" '"decision": "block"' "$output"
assert_contains "same_session_req_still_blocks reason" 'active workflow session detected' "$output"
assert_stop_stdout_contract "same_session_req_still_blocks stdout contract" "$OUTFILE" "block" "active workflow session detected"

# AC-003: legacy_request_without_canonical_session_does_not_block
# canonical mst_session_id 없는 레거시 파일은 최근 mtime이어도 diagnostic-only로 처리 → pass-through
cleanup
mkdir -p "$REQUEST_FIXTURE_DIR"
printf '%s\n' '{"id":"REQ-TEST-CONTINUATION-GUARD","status":"phase1_analysis","owner_session_id":null}' > "$REQUEST_FIXTURE_FILE"
run_stop '{"stop_hook_active":false,"last_assistant_message":"status update"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "legacy_request_without_owner_ppid_does_not_block exits 0" "0" "$STOP_EXIT"
assert_contains "legacy_request_without_owner_ppid_does_not_block -> approve JSON" '"decision": "approve"' "$output"

# AC-001 (T03): malformed_owner_ppid_true_graceful_skip
# owner_ppid가 JSON bool true이면 parse failure → graceful skip → pass-through
cleanup
mkdir -p "$REQUEST_FIXTURE_DIR"
printf '%s\n' '{"id":"REQ-TEST-CONTINUATION-GUARD","status":"phase1_analysis","owner_ppid":true,"owner_session_id":"123e4567-e89b-42d3-a456-426614174000"}' > "$REQUEST_FIXTURE_FILE"
run_stop '{"stop_hook_active":false,"last_assistant_message":"status update"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "malformed_owner_ppid_true_graceful_skip exits 0" "0" "$STOP_EXIT"
assert_contains "malformed_owner_ppid_true_graceful_skip -> approve JSON" '"decision": "approve"' "$output"

# AC-002 (T03): plan_isolation_other_session_does_not_block
# 다른 PPID(99999) owner의 non-terminal plan이 있어도 현재 세션 stop은 pass-through
cleanup
mkdir -p "$PLAN_FIXTURE_DIR"
printf '%s\n' '{"id":"PLN-TEST","status":"active","owner_ppid":99999,"owner_session_id":"123e4567-e89b-42d3-a456-426614174000"}' > "$PLAN_FIXTURE_FILE"
run_stop '{"stop_hook_active":false,"last_assistant_message":"status update"}'
output="$(cat "$OUTFILE" 2>/dev/null || true)"
assert_eq "plan_isolation_other_session_does_not_block exits 0" "0" "$STOP_EXIT"
assert_contains "plan_isolation_other_session_does_not_block -> approve JSON" '"decision": "approve"' "$output"

cleanup

echo ""
echo "==============================="
echo "Results: $PASS/$TOTAL passed, $FAIL failed"
echo "==============================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
