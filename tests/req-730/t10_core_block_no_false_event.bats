#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-003 read-only Bash appends no core_block event" {
  sid="73001000-0000-4000-8000-000000000101"
  payload='{"session_id":"73001000-0000-4000-8000-000000000101","tool_name":"Bash","tool_input":{"command":"pwd && ls ."}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ -f "$(history_file "$sid")" ]
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 0 ]
}
