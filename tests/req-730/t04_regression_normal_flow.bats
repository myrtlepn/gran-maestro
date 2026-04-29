#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-008 normal read-only Bash workflow remains allowed" {
  sid="73000000-0000-4000-8000-000000000410"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000410","tool_name":"Bash","tool_input":{"command":"git status --short"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000410","tool_name":"Bash","tool_input":{"command":"cat README.md"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000410","tool_name":"Bash","tool_input":{"command":"mst:request REQ-730"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000410","tool_name":"Bash","tool_input":{"command":"mst:approve REQ-730"}}'
  [ "$status" -eq 0 ]

  [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
}

@test "AC-008 existing policy warn and block decisions still route through T01 flow" {
  install_decision_rule "GM-REQ730-REGRESSION-WARN" "warn" "req730-regression-warn"
  sid_warn="73000000-0000-4000-8000-000000000411"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000411","tool_name":"Bash","tool_input":{"command":"echo req730-regression-warn"}}'

  [ "$status" -eq 0 ]
  [ "$(jq -r 'select(.event.type=="warn_auto_allow") | .event.rule_id' "$(history_file "$sid_warn")")" = "GM-REQ730-REGRESSION-WARN" ]

  install_decision_rule "GM-REQ730-REGRESSION-BLOCK" "block" "req730-regression-block"
  sid_block="73000000-0000-4000-8000-000000000412"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000412","tool_name":"Bash","tool_input":{"command":"echo req730-regression-block"}}'

  [ "$status" -eq 2 ]
  [ -f "$(pending_file "$sid_block")" ]
  [ "$(jq -r 'select(.event.type=="confirm_requested") | .event.rule_id' "$(history_file "$sid_block")")" = "GM-REQ730-REGRESSION-BLOCK" ]
}
