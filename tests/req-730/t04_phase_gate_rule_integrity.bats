#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  install_phase_gate_rule
}

@test "AC-006 phase-gate.json manifest mismatch fails closed" {
  policy_dir="$(policy_project_dir)"
  python3 - "$policy_dir/rules.d/phase-gate.json" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
PY

  run run_pre_tool_hook '{"session_id":"73000000-0000-4000-8000-000000000409","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"manifest_sha256_mismatch"* ]]
  [[ "$output" == *"phase-gate.json"* ]]
}
