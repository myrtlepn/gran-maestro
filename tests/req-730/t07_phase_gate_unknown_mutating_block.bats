#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-003 unknown or non-allowlisted mutating Bash commands block" {
  cases=(
    '73000700-0000-4000-8000-000000000731|git add file.txt'
    '73000700-0000-4000-8000-000000000732|dd of=out bs=1'
    '73000700-0000-4000-8000-000000000733|find . -delete'
    '73000700-0000-4000-8000-000000000734|rsync -av src dst'
    '73000700-0000-4000-8000-000000000735|install -m 644 a b'
  )

  for item in "${cases[@]}"; do
    IFS='|' read -r sid command <<<"$item"
    payload="$(python3 - "$sid" "$command" <<'PY'
import json
import sys
print(json.dumps({
    "session_id": sys.argv[1],
    "req_id": "REQ-730",
    "task_id": "T07",
    "tool_name": "Bash",
    "tool_input": {"command": sys.argv[2]},
}))
PY
)"

    run run_pre_tool_hook "$payload"

    [ "$status" -eq 2 ]
    [ -f "$(pending_file "$sid")" ]
    [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
  done
}
