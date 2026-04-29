#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

grant_override() {
  local sid="$1"
  local pending_id="$2"
  local tool="$3"
  local args_sha="$4"
  PYTHONPATH="$REPO_ROOT" python3 - "$WORKSPACE" "$HOME_DIR" "$sid" "$pending_id" "$tool" "$args_sha" <<'PY'
import sys
from pathlib import Path
from hooks.lib.pre_tool_use_fast import append_event_after_verified, format_utc, utc_now

project_root = Path(sys.argv[1])
home = Path(sys.argv[2])
sid = sys.argv[3]
pending_id = sys.argv[4]
tool = sys.argv[5]
args_sha = sys.argv[6]
raise SystemExit(
    append_event_after_verified(
        project_root,
        home,
        sid,
        {
            "args_sha256": args_sha,
            "pending_id": pending_id,
            "timestamp": format_utc(utc_now()),
            "tool": tool,
            "type": "override_granted",
        },
    )
)
PY
}

@test "AC-004 changed args after override_granted block and require a new confirm" {
  install_decision_rule "GM-REQ730-BLOCK" "block" "req730-args-changed"
  sid="73000000-0000-4000-8000-000000000203"
  payload='{"session_id":"73000000-0000-4000-8000-000000000203","tool_name":"Bash","tool_input":{"command":"echo req730-args-changed","value":1}}'
  changed_payload='{"session_id":"73000000-0000-4000-8000-000000000203","tool_name":"Bash","tool_input":{"command":"echo req730-args-changed","value":2}}'
  expected_sha="$(args_sha256_for_payload "$payload")"
  changed_sha="$(args_sha256_for_payload "$changed_payload")"

  run run_pre_tool_hook "$payload"
  [ "$status" -eq 2 ]
  pending_id="$(jq -r '.id' "$(pending_file "$sid")")"
  grant_override "$sid" "$pending_id" "Bash" "$expected_sha"

  run run_pre_tool_hook "$changed_payload"

  [ "$status" -eq 2 ]
  [[ "$output" == *"args_sha256 mismatch on subsequent call"* ]]
  [ "$(jq -r '.id' "$(pending_file "$sid")")" != "$pending_id" ]
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$changed_sha" ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "false" ]
}
