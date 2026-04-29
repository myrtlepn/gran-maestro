#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$WORKSPACE/.gran-maestro/logs" "$HOME_DIR"
  printf 'gitdir: .\n' > "$WORKSPACE/.git"
  export HOME="$HOME_DIR"
}

payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

print(json.dumps({"session_id": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))
PY
}

run_pre_tool_hook() {
  (cd "$WORKSPACE" && HOME="$HOME_DIR" bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$(payload "$1" "$2")")
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

assert_core_block_event() {
  local sid="$1"
  [ -f "$(history_file "$sid")" ]
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
}

@test "AC-001 blocks direct mst confirm from LLM Bash and records core_block" {
  sid="73003001-0000-4000-8000-000000000001"

  run run_pre_tool_hook "$sid" "mst confirm cf_X"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [[ "$output" == *"mst confirm"* ]]
  assert_core_block_event "$sid"
}

@test "AC-001 blocks python mst.py confirm from LLM Bash and records core_block" {
  sid="73003001-0000-4000-8000-000000000002"

  run run_pre_tool_hook "$sid" "python3 scripts/mst.py confirm cf_X"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [[ "$output" == *"mst confirm"* ]]
  assert_core_block_event "$sid"
}
