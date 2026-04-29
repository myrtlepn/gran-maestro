#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  mkdir -p "$HOME_DIR/.claude/gran-maestro-policy"
  cat > "$HOME_DIR/.claude/gran-maestro-policy/allowlist.json" <<'JSON'
{
  "version": 1,
  "entries": [
    {
      "id": "alw_wildcard",
      "tool": "Bash",
      "args_pattern": "*",
      "expires_at": null,
      "created_at": "2026-04-29T00:00:00Z",
      "added_by_tty": true
    }
  ]
}
JSON
}

@test "AC-007 LLM Bash mst hook allow remains core blocked before allowlist" {
  sid="73103007-0000-4000-8000-000000000001"

  run run_pre_tool_hook '{"session_id":"73103007-0000-4000-8000-000000000001","tool_name":"Bash","tool_input":{"command":"mst hook allow Bash --args-pattern '\''*'\'' --expires 5"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [[ "$output" == *"mst hook allow"* ]]
  [ "$(jq -s '[.[].event | select(.type == "core_block" and .rule_id == "MST-LLM-MST-CLI-BLOCK")] | length' "$(history_file "$sid")")" -eq 1 ]
}
