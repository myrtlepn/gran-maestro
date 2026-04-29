#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-005 read-only tools bypass phase gate" {
  sid="73000000-0000-4000-8000-000000000407"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000407","tool_name":"Read","tool_input":{"file_path":"README.md"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000407","tool_name":"Glob","tool_input":{"pattern":"*.md"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000407","tool_name":"Grep","tool_input":{"pattern":"hello","path":"."}}'
  [ "$status" -eq 0 ]

  [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
}

@test "AC-005 read-only Bash commands bypass phase gate" {
  sid="73000000-0000-4000-8000-000000000408"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000408","tool_name":"Bash","tool_input":{"command":"ls -la"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000408","tool_name":"Bash","tool_input":{"command":"cat README.md"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000408","tool_name":"Bash","tool_input":{"command":"git status --short"}}'
  [ "$status" -eq 0 ]

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000408","tool_name":"Bash","tool_input":{"command":"echo hello"}}'
  [ "$status" -eq 0 ]

  [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
}
