#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-001 state_change implementation event is not phase evidence" {
  sid="73000700-0000-4000-8000-000000000701"
  append_history_event "$sid" '{"type":"state_change","req_id":"REQ-730","task_id":"T07","phase":"implementation","timestamp":"2026-04-29T00:00:00Z"}'
  payload='{"session_id":"73000700-0000-4000-8000-000000000701","req_id":"REQ-730","task_id":"T07","tool_name":"Write","tool_input":{"file_path":"out.txt","content":"hello"}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ -f "$(pending_file "$sid")" ]
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}
