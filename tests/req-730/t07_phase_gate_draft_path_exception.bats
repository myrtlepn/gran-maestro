#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-004 draft file paths bypass phase gate for D5 draft workflow" {
  cases=(
    '73000700-0000-4000-8000-000000000741|Write|{"file_path":".gran-maestro/drafts/spec-draft.md","content":"draft"}'
    '73000700-0000-4000-8000-000000000742|Edit|{"file_path":".gran-maestro/drafts/anything/sub/path.md","old_string":"a","new_string":"b"}'
  )

  for item in "${cases[@]}"; do
    IFS='|' read -r sid tool input_json <<<"$item"
    payload="$(python3 - "$sid" "$tool" "$input_json" <<'PY'
import json
import sys
print(json.dumps({
    "session_id": sys.argv[1],
    "req_id": "REQ-730",
    "task_id": "T07",
    "tool_name": sys.argv[2],
    "tool_input": json.loads(sys.argv[3]),
}))
PY
)"

    run run_pre_tool_hook "$payload"

    [ "$status" -eq 0 ]
    [ ! -f "$(pending_file "$sid")" ]
    [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
  done
}

@test "AC-004 absolute draft file path also bypasses phase gate" {
  sid="73000700-0000-4000-8000-000000000743"
  draft_path="$WORKSPACE/.gran-maestro/drafts/absolute/spec-draft.md"
  payload="$(python3 - "$sid" "$draft_path" <<'PY'
import json
import sys
print(json.dumps({
    "session_id": sys.argv[1],
    "req_id": "REQ-730",
    "task_id": "T07",
    "tool_name": "Write",
    "tool_input": {"file_path": sys.argv[2], "content": "draft"},
}))
PY
)"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ ! -f "$(pending_file "$sid")" ]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.type' "$(history_file "$sid")")" = "" ]
}
