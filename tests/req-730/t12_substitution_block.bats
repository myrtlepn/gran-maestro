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

@test "AC-001 double-quoted command substitution executing mst CLI core blocks" {
  sid="73012001-0000-4000-8000-000000000001"

  run run_pre_tool_hook "$(bash_payload "$sid" 'echo "$(mst confirm cf_X)"')"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-005 single-quoted command substitution text does not core block" {
  sid="73012005-0000-4000-8000-000000000001"

  run run_pre_tool_hook "$(bash_payload "$sid" 'echo '"'"'$(mst confirm cf_X)'"'"'')"

  [ "$status" -eq 0 ]
  [ "$(core_block_count "$sid")" -eq 0 ]
}
