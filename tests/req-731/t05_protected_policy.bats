#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-002 project policy Edit is blocked by protected paths rule" {
  sid="73105002-0000-4000-8000-000000000001"
  payload='{"session_id":"73105002-0000-4000-8000-000000000001","tool_name":"Edit","tool_input":{"file_path":".gran-maestro/policy/rules.d/foo.json","old_string":"{}","new_string":"{\"x\":1}"}}'

  [ -f "$(policy_project_dir)/rules.d/protected-paths.json" ]

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[policy-block]"* ]]
  [[ "$output" == *"PROTECTED-PATHS"* ]]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "PROTECTED-PATHS" ]
  [ -f "$(pending_file "$sid")" ]
}
