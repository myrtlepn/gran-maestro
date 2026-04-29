#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-001 mutating Write blocks without spec.accepted or override and creates pending confirm" {
  sid="73000000-0000-4000-8000-000000000401"
  payload='{"session_id":"73000000-0000-4000-8000-000000000401","req_id":"REQ-730","task_id":"T04","tool_name":"Write","tool_input":{"file_path":"out.txt","content":"hello"}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ -f "$(pending_file "$sid")" ]
  [ "$(jq -r '.tool' "$(pending_file "$sid")")" = "Write" ]
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "false" ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
  [ "$(jq -r 'select(.event.type=="confirm_requested") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
}
