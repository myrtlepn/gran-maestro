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

@test "AC-004 command substitution executing mst CLI core blocks" {
  commands=(
    'echo $(mst confirm cf_substitution)'
    'echo `mst confirm cf_backtick`'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73008004-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
    index=$((index + 1))
  done
}
