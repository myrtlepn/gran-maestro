#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

bash_payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

print(json.dumps({"session_id": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))
PY
}

core_block_count() {
  local sid="$1"
  if [ ! -f "$(history_file "$sid")" ]; then
    printf '0\n'
    return
  fi
  jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")"
}

@test "AC-001 dot printf process substitution blocks" {
  sid="73016001-0000-4000-8000-000000000001"
  command=$'. <(printf \'%s\\n\' \'mst confirm cf_X\')'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-002 dot cat here-string process substitution blocks" {
  sid="73016002-0000-4000-8000-000000000001"
  command=$'. <(cat <<<\'mst confirm cf_X\')'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-003 dot escaped printf process substitution blocks" {
  sid="73016003-0000-4000-8000-000000000001"
  command='. <(printf mst\ confirm\ cf_X)'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}
