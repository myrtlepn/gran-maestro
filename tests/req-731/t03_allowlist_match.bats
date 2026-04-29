#!/usr/bin/env bats

load '../req-730/t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

write_allowlist() {
  local expires_at="$1"
  mkdir -p "$HOME_DIR/.claude/gran-maestro-policy"
  python3 - "$HOME_DIR/.claude/gran-maestro-policy/allowlist.json" "$expires_at" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expires_at = sys.argv[2]
payload = {
    "version": 1,
    "entries": [
        {
            "id": "alw_test",
            "tool": "Bash",
            "args_pattern": "*npm test*",
            "expires_at": None if expires_at == "null" else expires_at,
            "created_at": "2026-04-29T00:00:00Z",
            "added_by_tty": True,
        }
    ],
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

@test "AC-005 allowlist match passes a command phase gate would block" {
  sid="73103005-0000-4000-8000-000000000001"
  write_allowlist "2099-01-01T00:00:00Z"

  run run_pre_tool_hook '{"session_id":"73103005-0000-4000-8000-000000000001","req_id":"REQ-731","task_id":"T03","tool_name":"Bash","tool_input":{"command":"npm test"}}'

  [ "$status" -eq 0 ]
  [ "$(jq -s '[.[].event | select(.type == "policy_block")] | length' "$(history_file "$sid")")" -eq 0 ]
  [ "$(jq -s '[.[].event | select(.type == "normal_allow" and .rule_id == "MST-HOOK-ALLOWLIST")] | length' "$(history_file "$sid")")" -eq 1 ]
}

@test "AC-006 expired allowlist entry is ignored" {
  sid="73103006-0000-4000-8000-000000000001"
  write_allowlist "2000-01-01T00:00:00Z"

  run run_pre_tool_hook '{"session_id":"73103006-0000-4000-8000-000000000001","req_id":"REQ-731","task_id":"T03","tool_name":"Bash","tool_input":{"command":"npm test"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"GM-PHASE-GATE"* ]]
  [ "$(jq -r 'select(.event.type=="policy_block") | .event.rule_id' "$(history_file "$sid")")" = "GM-PHASE-GATE" ]
}
