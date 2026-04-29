#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

core_block_count() {
  local sid="$1"
  jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")"
}

assert_single_core_block() {
  local sid="$1"
  [ -f "$(history_file "$sid")" ]
  [ "$(core_block_count "$sid")" -eq 1 ]
  [ "$(jq -r '.[0].event.tool' "$(history_file "$sid")")" != "null" ]
  [ "$(jq -r '.[0].event.args_sha256' "$(history_file "$sid")")" != "null" ]
  [ "$(jq -r '.[0].event.rule_id' "$(history_file "$sid")")" != "null" ]
  [ "$(jq -r '.[0].event.reason' "$(history_file "$sid")")" != "null" ]
  [ "$(jq -r '.[0].event.timestamp' "$(history_file "$sid")")" != "null" ]
}

json_payload() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys

sid, tool_name, tool_input = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
print(json.dumps({"session_id": sid, "tool_name": tool_name, "tool_input": tool_input}))
PY
}

@test "AC-002 hardcoded core block branches append one core_block ledger event" {
  cases=(
    '73001000-0000-4000-8000-000000000001|Bash|{"command":"mst confirm cf_t10"}'
    '73001000-0000-4000-8000-000000000002|Write|{"file_path":"'"$HOME_DIR"'/.claude/gran-maestro-policy/projects/demo/notes.txt","content":"tamper"}'
    '73001000-0000-4000-8000-000000000003|Write|{"file_path":"'"$WORKSPACE"'/.gran-maestro/sessions/73001000-0000-4000-8000-000000000003/history.ndjson","content":"tamper"}'
    '73001000-0000-4000-8000-000000000004|Write|{"file_path":"'"$HOME_DIR"'/.claude/gran-maestro-policy/ledger-heads/73001000-0000-4000-8000-000000000004.head","content":"0"}'
    '73001000-0000-4000-8000-000000000005|Bash|{"command":"echo bad > .gran-maestro/sessions/73001000-0000-4000-8000-000000000005/history.verify"}'
  )

  for item in "${cases[@]}"; do
    IFS='|' read -r sid tool_name tool_input <<<"$item"
    payload="$(json_payload "$sid" "$tool_name" "$tool_input")"

    run run_pre_tool_hook "$payload"

    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    assert_single_core_block "$sid"
  done
}
