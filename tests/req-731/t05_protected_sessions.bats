#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-001 sessions history.ndjson Write is blocked and recorded" {
  sid="73105001-0000-4000-8000-000000000001"
  payload='{"session_id":"73105001-0000-4000-8000-000000000001","tool_name":"Write","tool_input":{"file_path":".gran-maestro/sessions/73105001-0000-4000-8000-000000000001/history.ndjson","content":"tamper"}}'

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* || "$output" == *"[policy-block]"* ]]
  [ -f "$(history_file "$sid")" ]
  [ "$(jq -s '[.[].event | select(.type == "core_block" or .type == "policy_block")] | length' "$(history_file "$sid")")" -ge 1 ]
}
