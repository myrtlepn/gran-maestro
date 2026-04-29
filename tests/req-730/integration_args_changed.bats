#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-007 args change after override creates a new pending confirm" {
  install_decision_rule "GM-REQ730-ARGS-CHANGED" "block" "req730-integration-args"
  sid="73000600-0000-4000-8000-000000000701"
  payload='{"session_id":"73000600-0000-4000-8000-000000000701","tool_name":"Bash","tool_input":{"command":"echo req730-integration-args","value":1}}'
  changed_payload='{"session_id":"73000600-0000-4000-8000-000000000701","tool_name":"Bash","tool_input":{"command":"echo req730-integration-args","value":2}}'
  changed_sha="$(args_sha256_for_payload "$changed_payload")"

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 2 ]
  first_pending_id="$(jq -r '.id' "$(pending_file "$sid")")"

  run run_mst_tty confirm "$first_pending_id"
  [ "$status" -eq 0 ]

  run run_pre_tool_hook "$changed_payload"
  [ "$status" -eq 2 ]
  [[ "$output" == *"args_sha256 mismatch on subsequent call"* ]]
  [ "$(jq -r '.id' "$(pending_file "$sid")")" != "$first_pending_id" ]
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$changed_sha" ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "false" ]
  [ "$(jq -s '[.[].event | select(.type=="override_consumed")] | length' "$(history_file "$sid")")" -eq 0 ]
}
