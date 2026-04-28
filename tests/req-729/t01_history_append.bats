#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export REPO_ROOT
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$HOME_DIR"
  printf 'gitdir: .\n' > "$WORKSPACE/.git"
  export HOME="$HOME_DIR"
}

run_pre_tool_hook() {
  local payload="$1"
  bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload"
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

head_file() {
  printf '%s/.gran-maestro/sessions/%s/history.head\n' "$WORKSPACE" "$1"
}

mirror_head_file() {
  printf '%s/.claude/gran-maestro-policy/ledger-heads/%s.head\n' "$HOME_DIR" "$1"
}

canonical_event_hash() {
  local prev_hash="$1"
  local event_json="$2"
  python3 - "$prev_hash" "$event_json" <<'PY'
import hashlib
import json
import sys

prev_hash = sys.argv[1]
event = json.loads(sys.argv[2])
canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest())
PY
}

@test "AC-001a appends a tool_call event for every PreToolUse hook call" {
  cd "$WORKSPACE"
  sid="11111111-1111-4111-8111-111111111111"

  run run_pre_tool_hook '{"session_id":"11111111-1111-4111-8111-111111111111","tool_name":"Bash","tool_input":{"command":"echo ok"}}'

  [ "$status" -eq 0 ]
  [ -f "$(history_file "$sid")" ]
  [ "$(wc -l < "$(history_file "$sid")" | tr -d ' ')" = "1" ]
  [ "$(jq -r '.seq' "$(history_file "$sid")")" = "1" ]
  [ "$(jq -r '.event.type' "$(history_file "$sid")")" = "tool_call" ]
  [ "$(jq -r '.event.tool' "$(history_file "$sid")")" = "Bash" ]
  [ "$(jq -r '.event.args_sha256 | test("^[0-9a-f]{64}$")' "$(history_file "$sid")")" = "true" ]
}

@test "AC-001b serializes concurrent hook appends with mkdir lock" {
  cd "$WORKSPACE"
  sid="22222222-2222-4222-8222-222222222222"
  payload='{"session_id":"22222222-2222-4222-8222-222222222222","tool_name":"Bash","tool_input":{"command":"echo concurrent"}}'

  for _ in 1 2 3 4 5; do
    bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload" &
  done
  wait

  [ -f "$(history_file "$sid")" ]
  [ "$(wc -l < "$(history_file "$sid")" | tr -d ' ')" = "5" ]
  [ ! -d "$WORKSPACE/.gran-maestro/sessions/$sid/history.lock" ]
  jq -s -e '[.[].seq] == [1,2,3,4,5]' "$(history_file "$sid")" >/dev/null
}

@test "AC-002a computes event_hash from prev_hash and canonical event json" {
  cd "$WORKSPACE"
  sid="33333333-3333-4333-8333-333333333333"

  run_pre_tool_hook '{"session_id":"33333333-3333-4333-8333-333333333333","tool_name":"Bash","tool_input":{"command":"echo one"}}'
  run_pre_tool_hook '{"session_id":"33333333-3333-4333-8333-333333333333","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  first_event="$(jq -c '.event' "$(history_file "$sid")" | sed -n '1p')"
  first_hash="$(jq -r '.event_hash' "$(history_file "$sid")" | sed -n '1p')"
  second_prev="$(jq -r '.prev_hash' "$(history_file "$sid")" | sed -n '2p')"
  expected="$(canonical_event_hash "0000000000000000000000000000000000000000000000000000000000000000" "$first_event")"

  [ "$first_hash" = "$expected" ]
  [ "$second_prev" = "$first_hash" ]
  [ "$(cat "$(head_file "$sid")")" = "$(jq -r '.event_hash' "$(history_file "$sid")" | tail -1)" ]
  [ "$(cat "$(mirror_head_file "$sid")")" = "$(cat "$(head_file "$sid")")" ]
}

@test "AC-002b exits 2 when existing history chain is tampered" {
  cd "$WORKSPACE"
  sid="44444444-4444-4444-8444-444444444444"
  payload='{"session_id":"44444444-4444-4444-8444-444444444444","tool_name":"Bash","tool_input":{"command":"echo ok"}}'

  run_pre_tool_hook "$payload"
  tmp="$BATS_TEST_TMPDIR/tampered.ndjson"
  jq -c '.event.tool = "Tampered"' "$(history_file "$sid")" > "$tmp"
  mv "$tmp" "$(history_file "$sid")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"history ledger mismatch"* ]]
}

@test "AC-003a records skill_enter skill_exit state_change and tool_call event types" {
  cd "$WORKSPACE"
  sid="55555555-5555-4555-8555-555555555555"
  source "$REPO_ROOT/hooks/lib/history.bash"

  mst_history_append_event "$WORKSPACE" "$sid" '{"type":"skill_enter","skill":"agile-plan","timestamp":"2026-04-28T00:00:00Z"}'
  run_pre_tool_hook '{"session_id":"55555555-5555-4555-8555-555555555555","tool_name":"Bash","tool_input":{"command":"echo tool"}}'
  mst_history_append_event "$WORKSPACE" "$sid" '{"type":"state_change","state":"step-1","timestamp":"2026-04-28T00:00:01Z"}'
  mst_history_append_event "$WORKSPACE" "$sid" '{"type":"skill_exit","skill":"agile-plan","timestamp":"2026-04-28T00:00:02Z"}'

  types="$(jq -r '.event.type' "$(history_file "$sid")" | sort -u | tr '\n' ' ')"
  [[ "$types" == *"skill_enter"* ]]
  [[ "$types" == *"skill_exit"* ]]
  [[ "$types" == *"state_change"* ]]
  [[ "$types" == *"tool_call"* ]]
}
