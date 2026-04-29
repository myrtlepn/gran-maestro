#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  mkdir -p "$WORKSPACE/docs"
  printf 'Run mst confirm cf_X only from a user terminal.\n' > "$WORKSPACE/docs/note.md"
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

@test "AC-001 text references to blocked mst CLI forms do not core block" {
  commands=(
    'echo "mst confirm cf_X"'
    'grep "mst confirm" docs/note.md'
    'cat docs/note.md'
    'printf "mst hook allow\n"'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73008001-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 0 ]
    [ "$(core_block_count "$sid")" -eq 0 ]
    index=$((index + 1))
  done
}
