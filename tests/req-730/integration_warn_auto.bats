#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-004 warn policy auto-allows and records warn_auto_allow before tool_call" {
  install_decision_rule "GM-REQ730-INTEGRATION-WARN" "warn" "req730-integration-warn"
  sid="73000600-0000-4000-8000-000000000401"
  payload='{"session_id":"73000600-0000-4000-8000-000000000401","tool_name":"Bash","tool_input":{"command":"echo req730-integration-warn"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ ! -f "$(pending_file "$sid")" ]
  [ "$(jq -r 'select(.event.type=="warn_auto_allow") | .event.rule_id' "$(history_file "$sid")")" = "GM-REQ730-INTEGRATION-WARN" ]
  [ "$(jq -r '[.event.type] | @tsv' "$(history_file "$sid")")" = $'warn_auto_allow\ntool_call' ]
  [ "$(jq -r 'select(.event.type=="tool_call") | .event.tool' "$(history_file "$sid")")" = "Bash" ]
}
