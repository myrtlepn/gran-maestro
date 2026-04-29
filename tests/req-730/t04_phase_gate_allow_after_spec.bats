#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-002 mutating Edit allows after matching spec.accepted marker" {
  sid="73000000-0000-4000-8000-000000000402"
  append_history_event "$sid" '{"type":"spec.accepted","req_id":"REQ-730","task_id":"T04","timestamp":"2026-04-29T00:00:00Z"}'

  payload='{"session_id":"73000000-0000-4000-8000-000000000402","req_id":"REQ-730","task_id":"T04","tool_name":"Edit","tool_input":{"file_path":"out.txt","old_string":"a","new_string":"b"}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ ! -f "$(pending_file "$sid")" ]
  [ "$(jq -r 'select(.event.type=="normal_allow") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
  [ "$(jq -r 'select(.event.type=="normal_allow") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
  [ "$(jq -r 'select(.event.type=="tool_call") | .event.tool' "$(history_file "$sid")" | tail -1)" = "Edit" ]
}
