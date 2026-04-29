#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-003 mutating MultiEdit allows once via matching override_granted and consumes it" {
  sid="73000000-0000-4000-8000-000000000403"
  payload='{"session_id":"73000000-0000-4000-8000-000000000403","req_id":"REQ-730","task_id":"T04","tool_name":"MultiEdit","tool_input":{"file_path":"out.txt","edits":[{"old_string":"a","new_string":"b"}]}}'
  expected_sha="$(args_sha256_for_payload "$payload")"
  session_dir="$WORKSPACE/.gran-maestro/sessions/$sid"
  mkdir -p "$session_dir"
  chmod 700 "$session_dir"
  python3 - "$(pending_file "$sid")" "$expected_sha" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "approved": True,
    "args_sha256": sys.argv[2],
    "consumed": False,
    "created_at": "2026-04-29T00:00:00Z",
    "expires_at": "2099-01-01T00:00:00Z",
    "id": "cf_override_t04",
    "tool": "MultiEdit",
}
path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
PY
  append_history_event "$sid" "{\"type\":\"override_granted\",\"id\":\"cf_override_t04\",\"tool\":\"MultiEdit\",\"args_sha256\":\"$expected_sha\",\"timestamp\":\"2026-04-29T00:00:00Z\",\"expires_at\":\"2099-01-01T00:00:00Z\"}"

  run run_pre_tool_hook "$payload"

  [ "$status" -eq 0 ]
  [ "$(jq -r '.consumed' "$(pending_file "$sid")")" = "true" ]
  [ "$(jq -r 'select(.event.type=="override_consumed") | .event.override_id' "$(history_file "$sid")")" = "cf_override_t04" ]
  [ "$(jq -r 'select(.event.type=="override_consumed") | .event.args_sha256' "$(history_file "$sid")")" = "$expected_sha" ]
}
