#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-005 read-only Bash allowlist bypasses phase gate" {
  cases=(
    '73000700-0000-4000-8000-000000000751|ls -la'
    '73000700-0000-4000-8000-000000000752|cat README.md'
    '73000700-0000-4000-8000-000000000753|git status --short'
    '73000700-0000-4000-8000-000000000754|pwd'
    '73000700-0000-4000-8000-000000000755|echo hi'
  )

  for item in "${cases[@]}"; do
    IFS='|' read -r sid command <<<"$item"
    payload="$(python3 - "$sid" "$command" <<'PY'
import json
import sys
print(json.dumps({
    "session_id": sys.argv[1],
    "tool_name": "Bash",
    "tool_input": {"command": sys.argv[2]},
}))
PY
)"

    run run_pre_tool_hook "$payload"

    [ "$status" -eq 0 ]
    [ ! -f "$(pending_file "$sid")" ]
    [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
  done
}
