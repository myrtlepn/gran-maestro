#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-001 broad Edit allowlist does not bypass protected policy path block" {
  sid="73107001-0000-4000-8000-000000000001"
  payload='{"session_id":"73107001-0000-4000-8000-000000000001","tool_name":"Edit","tool_input":{"file_path":".gran-maestro/policy/rules.d/foo.json","old_string":"{}","new_string":"{\"x\":1}"}}'

  run run_mst_tty hook allow Edit --args-pattern "*"
  [ "$status" -eq 0 ]

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[policy-block]"* ]]
  [[ "$output" == *"PROTECTED-PATHS"* ]]
  [ "$(jq -s '[.[].event | select(.type == "normal_allow" and .rule_id == "MST-HOOK-ALLOWLIST")] | length' "$(history_file "$sid")")" -eq 0 ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "PROTECTED-PATHS" ]
}

@test "AC-002 Bash allowlist still permits matching ordinary command" {
  sid="73107002-0000-4000-8000-000000000001"

  run run_mst_tty hook allow Bash --args-pattern "*npm*"
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73107002-0000-4000-8000-000000000001","req_id":"REQ-731","task_id":"T07","tool_name":"Bash","tool_input":{"command":"npm test"}}'

  [ "$status" -eq 0 ]
  [ "$(jq -s '[.[].event | select(.type == "policy_block")] | length' "$(history_file "$sid")")" -eq 0 ]
  [ "$(jq -s '[.[].event | select(.type == "normal_allow" and .rule_id == "MST-HOOK-ALLOWLIST")] | length' "$(history_file "$sid")")" -eq 1 ]
}
