#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$HOME_DIR/.claude"
  export HOME="$HOME_DIR"
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

append_history_event() {
  local sid="$1"
  local event_type="$2"
  local path
  path="$(history_file "$sid")"
  mkdir -p "$(dirname "$path")"
  printf '{"event":{"type":"%s"}}\n' "$event_type" >> "$path"
}

run_statusline() {
  local payload="$1"
  (cd "$WORKSPACE" && bash "$REPO_ROOT/scripts/mst-statusline.sh" <<<"$payload")
}

@test "AC-003 statusline appends five counter line from input session_id" {
  sid="73100000-0000-4000-8000-000000000003"
  append_history_event "$sid" "core_block"
  append_history_event "$sid" "policy_block"
  append_history_event "$sid" "warn_auto_allow"

  run run_statusline "{\"session_id\":\"$sid\"}"

  [ "$status" -eq 0 ]
  [[ "$output" == *"[CORE-BLOCK:1] [POLICY-BLOCK:1] [PENDING:0] [OVERRIDE:0] [WARN:1]"* ]]
}

@test "AC-004 statusline keeps HUD output and MST line before counters" {
  sid="73100000-0000-4000-8000-000000000004"
  append_history_event "$sid" "pending_confirm_created"
  cat > "$HOME_DIR/.claude/mst-statusline-backup.json" <<'JSON'
{"statusLine":{"command":"cat >/dev/null; printf 'HUD command invoked\\n'"}}
JSON

  run run_statusline "{\"session_id\":\"$sid\"}"

  [ "$status" -eq 0 ]
  [[ "$(printf '%s\n' "$output" | sed -n '1p')" == "HUD command invoked" ]]
  [[ "$(printf '%s\n' "$output" | sed -n '2p')" == "MST idle" ]]
  [[ "$(printf '%s\n' "$output" | sed -n '3p')" == "[CORE-BLOCK:0] [POLICY-BLOCK:0] [PENDING:1] [OVERRIDE:0] [WARN:0]" ]]
}
