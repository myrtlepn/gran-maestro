#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-002 repeated policy block with same tool and args reuses active pending id" {
  install_decision_rule "GM-REQ730-BLOCK" "block" "req730-idempotent"
  sid="73000000-0000-4000-8000-000000000002"
  payload='{"session_id":"73000000-0000-4000-8000-000000000002","tool_name":"Bash","tool_input":{"command":"echo req730-idempotent","value":7}}'

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 2 ]
  first_id="$(jq -r '.id' "$(pending_file "$sid")")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ "$(jq -r '.id' "$(pending_file "$sid")")" = "$first_id" ]
  [ "$(jq -r '[.event.type] | @tsv' "$(history_file "$sid")" | grep -c confirm_requested)" -eq 1 ]
}
