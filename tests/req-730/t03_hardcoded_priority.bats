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

run_mst() {
  (cd "$WORKSPACE" && HOME="$HOME_DIR" python3 "$REPO_ROOT/scripts/mst.py" "$@")
}

policy_project_dir() {
  python3 - "$WORKSPACE" "$HOME_DIR" <<'PY'
import hashlib
import os
import sys

project = os.path.realpath(sys.argv[1])
home = sys.argv[2]
key = hashlib.sha256(project.encode()).hexdigest()[:16]
print(os.path.join(home, ".claude", "gran-maestro-policy", "projects", key))
PY
}

rewrite_manifest() {
  local policy_dir="$1"
  python3 - "$policy_dir" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

policy_dir = Path(sys.argv[1])
rules = []
for rule_file in sorted((policy_dir / "rules.d").glob("*.json")):
    rules.append({"path": rule_file.relative_to(policy_dir).as_posix(), "sha256": hashlib.sha256(rule_file.read_bytes()).hexdigest()})
manifest = policy_dir / "manifest.json"
manifest.write_text(json.dumps({"version": 1, "rules": rules}, indent=2) + "\n", encoding="utf-8")
os.chmod(manifest, 0o600)
PY
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

@test "AC-006 hardcoded core BLOCK precedes weakening JSON allow rule" {
  sid="73003006-0000-4000-8000-000000000001"
  run_mst policy init >/dev/null
  policy_dir="$(policy_project_dir)"
  cat > "$policy_dir/rules.d/t03-allow-mst-confirm.json" <<'JSON'
{
  "version": 1,
  "rules": [
    {
      "id": "T03-ALLOW-MST-CONFIRM",
      "severity": "warn",
      "trigger": {"tool": "Bash", "args": {"command": {"contains": "mst confirm"}}},
      "action": {"decision": "allow", "message": "weakening rule must not override core"}
    }
  ]
}
JSON
  chmod 600 "$policy_dir/rules.d/t03-allow-mst-confirm.json"
  rewrite_manifest "$policy_dir"

  run run_pre_tool_hook "$sid" "mst confirm cf_weakened"

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [[ "$output" == *"mst confirm"* ]]
  [[ "$output" != *"weakening rule must not override core"* ]]
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
}
