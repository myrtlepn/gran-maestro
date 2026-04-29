#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-004 policy block appends confirm_requested event with pending id tool and args sha" {
  install_decision_rule "GM-REQ730-BLOCK" "block" "req730-confirm-event"
  sid="73000000-0000-4000-8000-000000000004"
  payload='{"session_id":"73000000-0000-4000-8000-000000000004","tool_name":"Bash","tool_input":{"command":"echo req730-confirm-event","nested":{"z":0}}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  pending_id="$(jq -r '.id' "$(pending_file "$sid")")"
  [ "$(jq -r 'select(.event.type=="confirm_requested") | .event.pending_id' "$(history_file "$sid")")" = "$pending_id" ]
  [ "$(jq -r 'select(.event.type=="confirm_requested") | .event.tool' "$(history_file "$sid")")" = "Bash" ]
  [ "$(jq -r 'select(.event.type=="confirm_requested") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
}
