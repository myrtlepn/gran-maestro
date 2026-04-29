#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-003 warn decision exits zero and appends warn_auto_allow ledger event" {
  install_decision_rule "GM-REQ730-WARN" "warn" "req730-warn"
  sid="73000000-0000-4000-8000-000000000003"
  payload='{"session_id":"73000000-0000-4000-8000-000000000003","tool_name":"Bash","tool_input":{"command":"echo req730-warn"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ -f "$(history_file "$sid")" ]
  [ "$(jq -r 'select(.event.type=="warn_auto_allow") | .event.rule_id' "$(history_file "$sid")")" = "GM-REQ730-WARN" ]
  [ "$(jq -r 'select(.event.type=="warn_auto_allow") | .event.tool' "$(history_file "$sid")")" = "Bash" ]
  [ "$(jq -r 'select(.event.type=="tool_call") | .event.tool' "$(history_file "$sid")" | tail -1)" = "Bash" ]
}
