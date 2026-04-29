#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
}

@test "AC-001 policy block creates pending-confirm with canonical args sha and unconsumed state" {
  install_decision_rule "GM-REQ730-BLOCK" "block" "req730-block"
  sid="73000000-0000-4000-8000-000000000001"
  payload='{"session_id":"73000000-0000-4000-8000-000000000001","tool_name":"Bash","tool_input":{"extra":{"b":2,"a":1},"command":"echo req730-block"}}'
  expected_sha="$(args_sha256_for_payload "$payload")"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 2 ]
  [ -f "$(pending_file "$sid")" ]
  [ "$(jq -r '.tool' "$(pending_file "$sid")")" = "Bash" ]
  [ "$(jq -r '.args_sha256' "$(pending_file "$sid")")" = "$expected_sha" ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "false" ]
  [ "$(jq -r '.id | startswith("cf_")' "$(pending_file "$sid")")" = "true" ]
  [ "$(jq -S -c '.args_canonical' "$(pending_file "$sid")")" = "$(jq -S -c '.tool_input' <<<"$payload")" ]
  python3 - "$WORKSPACE/.gran-maestro/sessions/$sid" "$(pending_file "$sid")" <<'PY'
import stat
import sys
from pathlib import Path

session_dir = Path(sys.argv[1])
pending = Path(sys.argv[2])
assert stat.S_IMODE(session_dir.stat().st_mode) == 0o700
assert stat.S_IMODE(pending.stat().st_mode) == 0o600
PY
}
