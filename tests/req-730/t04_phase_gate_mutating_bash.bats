#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-004 Bash git commit is mutating and blocks without phase evidence" {
  sid="73000000-0000-4000-8000-000000000404"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000404","req_id":"REQ-730","task_id":"T04","tool_name":"Bash","tool_input":{"command":"git commit -m x"}}'

  [ "$status" -eq 2 ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}

@test "AC-004 Bash redirection is mutating and blocks without phase evidence" {
  sid="73000000-0000-4000-8000-000000000405"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000405","req_id":"REQ-730","task_id":"T04","tool_name":"Bash","tool_input":{"command":"echo hello > out.txt"}}'

  [ "$status" -eq 2 ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}

@test "AC-004 Bash sed -i is mutating and blocks without phase evidence" {
  sid="73000000-0000-4000-8000-000000000406"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000406","req_id":"REQ-730","task_id":"T04","tool_name":"Bash","tool_input":{"command":"sed -i s/a/b/ file.txt"}}'

  [ "$status" -eq 2 ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}
