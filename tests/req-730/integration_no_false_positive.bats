#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-005 normal hook corpus passes with zero policy or core blocks" {
  sid="73000600-0000-4000-8000-000000000501"
  mkdir -p "$WORKSPACE/docs"
  printf 'Documentation may mention mst confirm cf_X without executing it.\n' > "$WORKSPACE/docs/note.md"
  payloads=(
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"git status --short"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"cat README.md"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"mst:request REQ-730"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"bash -c \"echo hi\""}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"echo \"mst confirm cf_X\""}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"grep \"mst confirm\" docs/note.md"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"cat docs/note.md"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Bash","tool_input":{"command":"printf \"mst hook allow\\n\""}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Read","tool_input":{"file_path":"README.md"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Glob","tool_input":{"pattern":"*.md"}}'
    '{"session_id":"73000600-0000-4000-8000-000000000501","tool_name":"Grep","tool_input":{"pattern":"Gran Maestro","path":"README.md"}}'
  )

  for payload in "${payloads[@]}"; do
    run run_pre_tool_hook "$payload"
    [ "$status" -eq 0 ]
  done

  [ "$(jq -s '[.[].event | select(.type == "policy_block" or .type == "core_block")] | length' "$(history_file "$sid")")" -eq 0 ]
}

@test "AC-005/PAC-23 representative existing mst.py commands still return successfully" {
  mkdir -p "$WORKSPACE/.gran-maestro/requests/REQ-001" "$WORKSPACE/.gran-maestro/intents"
  cat > "$WORKSPACE/.gran-maestro/requests/REQ-001/request.json" <<'JSON'
{"id":"REQ-001","status":"active","current_phase":1,"title":"Fixture request"}
JSON

  run run_mst config get test.missing --default ok
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]

  run run_mst state set-workflow --active true --skill mst:test
  [ "$status" -eq 0 ]

  run run_mst intent add --feature "Fixture intent" --situation "testing" --goal "verify get"
  [ "$status" -eq 0 ]
  intent_id="$output"

  run run_mst intent get "$intent_id"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Fixture intent"* ]]

  run run_mst request count --all
  [ "$status" -eq 0 ]
  [[ "$output" == *"1"* ]]

  run run_mst counter next --type req
  [ "$status" -eq 0 ]
  [[ "$output" == REQ-* ]]
}
