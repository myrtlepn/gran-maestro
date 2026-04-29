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

@test "AC-002 shell-wrapper heredoc stdin scripts core block" {
  commands=(
    $'bash <<EOF\nmst confirm cf_X\nEOF'
    $'bash -s <<EOF\nmst hook allow\nEOF'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73012002-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(core_block_count "$sid")" -eq 1 ]
    index=$((index + 1))
  done
}

@test "AC-003 shell-wrapper here-string stdin scripts core block" {
  commands=(
    'sh <<< "mst confirm cf_X"'
    'bash <<< "mst hook allow"'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73012003-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(core_block_count "$sid")" -eq 1 ]
    index=$((index + 1))
  done
}

@test "AC-004 text sink heredoc body mentioning mst CLI does not core block" {
  sid="73012004-0000-4000-8000-000000000001"
  command=$'cat <<EOF\nmst confirm cf_X\nEOF'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 0 ]
  [ "$(core_block_count "$sid")" -eq 0 ]
}
