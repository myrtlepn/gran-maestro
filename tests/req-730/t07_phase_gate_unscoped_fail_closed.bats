#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-002 unscoped spec.accepted does not satisfy an unscoped phase gate call" {
  sid="73000700-0000-4000-8000-000000000702"
  append_history_event "$sid" '{"type":"spec.accepted","timestamp":"2026-04-29T00:00:00Z"}'
  payload='{"session_id":"73000700-0000-4000-8000-000000000702","tool_name":"Write","tool_input":{"file_path":"out.txt","content":"hello"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ -f "$(pending_file "$sid")" ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}
