#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-005 housekeeping marks expired pending record and later block creates a new id" {
  install_decision_rule "GM-REQ730-BLOCK" "block" "req730-expiry"
  sid="73000000-0000-4000-8000-000000000005"
  session_dir="$WORKSPACE/.gran-maestro/sessions/$sid"
  mkdir -p "$session_dir"
  chmod 700 "$session_dir"
  cat > "$session_dir/pending-confirm.json" <<'JSON'
{"args_canonical":{"command":"echo req730-expiry"},"args_sha256":"stale","consumed":false,"created_at":"2026-04-27T00:00:00Z","expires_at":"2026-04-27T00:00:01Z","id":"cf_stale","tool":"Bash"}
JSON
  chmod 600 "$session_dir/pending-confirm.json"

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000005","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 0 ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "expired" ]

  payload='{"session_id":"73000000-0000-4000-8000-000000000005","tool_name":"Bash","tool_input":{"command":"echo req730-expiry"}}'
  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ "$(jq -r '.id' "$(pending_file "$sid")")" != "cf_stale" ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "false" ]
}
