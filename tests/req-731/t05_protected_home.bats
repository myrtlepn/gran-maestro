#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-003 sandbox HOME policy Write is blocked" {
  sid="73105003-0000-4000-8000-000000000001"
  payload='{"session_id":"73105003-0000-4000-8000-000000000001","tool_name":"Write","tool_input":{"file_path":"~/.claude/gran-maestro-policy/allowlist.json","content":"{}"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* || "$output" == *"[policy-block]"* ]]
  [ "$(jq -s '[.[].event | select(.type == "core_block" or .type == "policy_block")] | length' "$(history_file "$sid")")" -ge 1 ]
}

@test "AC-004 protected path block can be bypassed once by user confirm" {
  sid="73105004-0000-4000-8000-000000000001"
  payload='{"session_id":"73105004-0000-4000-8000-000000000001","tool_name":"MultiEdit","tool_input":{"file_path":".gran-maestro/policy/rules.d/foo.json","edits":[{"old_string":"a","new_string":"b"}]}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 2 ]
  pending_id="$(jq -r '.id' "$(pending_file "$sid")")"
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]

  run run_mst_tty confirm "$pending_id"
  [ "$status" -eq 0 ]

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 0 ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "true" ]
  [ "$(jq -r 'select(.event.type=="override_consumed") | .event.pending_id' "$(history_file "$sid")")" = "$pending_id" ]
}

@test "AC-005 ordinary source Write is not blocked by protected paths rule" {
  sid="73105005-0000-4000-8000-000000000001"
  append_history_event "$sid" '{"type":"spec.accepted","req_id":"REQ-731","task_id":"T05","timestamp":"2026-04-29T00:00:00Z"}'
  payload='{"session_id":"73105005-0000-4000-8000-000000000001","req_id":"REQ-731","task_id":"T05","tool_name":"Write","tool_input":{"file_path":"src/foo.ts","content":"export const foo = 1;\n"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ ! -f "$(pending_file "$sid")" ]
  [ "$(jq -s '[.[].event | select(.type == "policy_block" and .rule_id == "PROTECTED-PATHS")] | length' "$(history_file "$sid")")" -eq 0 ]
  [ "$(jq -r 'select(.event.type=="tool_call") | .event.tool' "$(history_file "$sid")" | tail -1)" = "Write" ]
}
