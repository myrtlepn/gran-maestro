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

@test "AC-003 heredoc bodies containing mst CLI text do not core block" {
  commands=(
    $'bash -c \'cat <<EOF\nmst confirm cf_X\nEOF\''
    $'bash -c \'cat <<\'"\'"\'EOF\'"\'"\'\nmst hook allow\nEOF\''
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73008003-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 0 ]
    [ "$(core_block_count "$sid")" -eq 0 ]
    index=$((index + 1))
  done
}

@test "AC-003 heredoc followed by real mst execution still core blocks" {
  sid="73008003-0000-4000-8000-000000000099"
  command=$'bash -c \'cat <<EOF\nplain text\nEOF\nmst confirm cf_after\''

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
}
