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

@test "AC-001 here-string substitution sink blocks" {
  sid="73015001-0000-4000-8000-000000000001"
  command=$'bash <<< "$(printf \'%s\\n\' \'mst confirm cf_X\')"'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-002 eval substitution sink blocks" {
  sid="73015002-0000-4000-8000-000000000001"
  command=$'eval "$(printf \'%s\\n\' \'mst confirm cf_X\')"'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-003 source process substitution sink blocks" {
  sid="73015003-0000-4000-8000-000000000001"
  command=$'source <(printf \'%s\\n\' \'mst confirm cf_X\')'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-004 dot process substitution sink blocks" {
  sid="73015004-0000-4000-8000-000000000001"
  command='. <(echo mst confirm cf_X)'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-005 dot printf process substitution sink blocks" {
  sid="73015005-0000-4000-8000-000000000001"
  command=$'. <(printf \'%s\\n\' \'mst confirm cf_X\')'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-006 nested bash -c source process substitution blocks" {
  sid="73015006-0000-4000-8000-000000000001"
  command=$'bash -c \'source <(printf %s\\n "mst confirm cf_X")\''

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [ "$(core_block_count "$sid")" -eq 1 ]
}

@test "AC-007 non-sink command substitution does not core block" {
  sid="73015007-0000-4000-8000-000000000001"
  command='echo "$(date)"'

  run run_pre_tool_hook "$(bash_payload "$sid" "$command")"

  [ "$status" -eq 0 ]
  [ "$(core_block_count "$sid")" -eq 0 ]
}
