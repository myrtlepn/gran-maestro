#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-003 phase gate blocks mutating Write and Edit then confirm consume allows once" {
  cases=(
    '73000600-0000-4000-8000-000000000301|Write|{"file_path":"out.txt","content":"hello"}'
    '73000600-0000-4000-8000-000000000302|Edit|{"file_path":"out.txt","old_string":"hello","new_string":"bye"}'
  )

  for item in "${cases[@]}"; do
    IFS='|' read -r sid tool input_json <<<"$item"
    payload="$(python3 - "$sid" "$tool" "$input_json" <<'PY'
import json
import sys
print(json.dumps({
    "session_id": sys.argv[1],
    "req_id": "REQ-730",
    "task_id": "T06",
    "tool_name": sys.argv[2],
    "tool_input": json.loads(sys.argv[3]),
}))
PY
)"
    expected_sha="$(args_sha256_for_payload "$payload")"

    run run_pre_tool_hook "$payload"
    [ "$status" -eq 2 ]
    [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
    [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]
    pending_id="$(jq -r '.id' "$(pending_file "$sid")")"

    run run_mst_tty confirm "$pending_id"
    [ "$status" -eq 0 ]

    run run_pre_tool_hook "$payload"
    [ "$status" -eq 0 ]
    [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "true" ]
    [ "$(jq -r 'select(.event.type=="override_consumed") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
  done
}
