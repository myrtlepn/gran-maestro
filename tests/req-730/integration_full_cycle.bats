#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-001 policy block confirm CLI and next hook consume form the full override cycle" {
  install_decision_rule "GM-REQ730-FULL-CYCLE" "block" "req730-full-cycle"
  sid="73000600-0000-4000-8000-000000000001"
  payload='{"session_id":"73000600-0000-4000-8000-000000000001","tool_name":"Bash","tool_input":{"command":"echo req730-full-cycle","nested":{"b":2,"a":1}}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 2 ]
  pending_id="$(jq -r '.id' "$(pending_file "$sid")")"
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]

  run run_mst_tty confirm "$pending_id"
  [ "$status" -eq 0 ]
  [[ "$output" == *"override granted: pending_id=$pending_id"* ]]

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 0 ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "true" ]

  jq -r '[.event.type] | @tsv' "$(history_file "$sid")" > "$BATS_TEST_TMPDIR/events.txt"
  [ "$(cat "$BATS_TEST_TMPDIR/events.txt")" = $'policy_block\nconfirm_requested\noverride_granted\noverride_consumed' ]
  [ "$(jq -r 'select(.event.type=="override_consumed") | .event.pending_id' "$(history_file "$sid")")" = "$pending_id" ]
  [ "$(jq -r 'select(.event.type=="override_consumed") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
}
