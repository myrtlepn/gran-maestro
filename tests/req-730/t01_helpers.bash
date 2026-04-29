setup_req730_workspace() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export REPO_ROOT
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$WORKSPACE/.gran-maestro/logs" "$HOME_DIR"
  printf 'gitdir: .\n' > "$WORKSPACE/.git"
  export HOME="$HOME_DIR"
}

run_mst() {
  (cd "$WORKSPACE" && HOME="$HOME_DIR" python3 "$REPO_ROOT/scripts/mst.py" "$@")
}

run_mst_tty() {
  python3 - "$REPO_ROOT" "$WORKSPACE" "$HOME_DIR" "$@" <<'PY'
import os
import pty
import subprocess
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
workspace = Path(sys.argv[2])
home = Path(sys.argv[3])
args = sys.argv[4:]
env = {
    key: value
    for key, value in os.environ.items()
    if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_"))
}
env["HOME"] = str(home)
master_fd, slave_fd = pty.openpty()
try:
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "mst.py"), *args],
        cwd=workspace,
        env=env,
        stdin=slave_fd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
finally:
    os.close(slave_fd)
    os.close(master_fd)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
PY
}

run_pre_tool_hook() {
  local payload="$1"
  (cd "$WORKSPACE" && HOME="$HOME_DIR" bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload")
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
from datetime import datetime, timezone
from pathlib import Path

policy_dir = Path(sys.argv[1])
rules = []
for rule_file in sorted((policy_dir / "rules.d").glob("*.json")):
    rules.append(
        {
            "path": rule_file.relative_to(policy_dir).as_posix(),
            "sha256": hashlib.sha256(rule_file.read_bytes()).hexdigest(),
            "last_modified": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
manifest = policy_dir / "manifest.json"
manifest.write_text(json.dumps({"version": 1, "rules": rules}, indent=2) + "\n", encoding="utf-8")
os.chmod(manifest, 0o600)
PY
}

install_decision_rule() {
  local rule_id="$1"
  local decision="$2"
  local command_fragment="$3"
  run_mst policy init >/dev/null
  local policy_dir
  policy_dir="$(policy_project_dir)"
  python3 - "$policy_dir/rules.d/req730.json" "$rule_id" "$decision" "$command_fragment" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
rule_id = sys.argv[2]
decision = sys.argv[3]
command_fragment = sys.argv[4]
payload = {
    "version": 1,
    "rules": [
        {
            "id": rule_id,
            "severity": "block" if decision == "block" else "warn",
            "trigger": {
                "tool": "Bash",
                "args": {"command": {"contains": command_fragment}},
            },
            "action": {
                "decision": decision,
                "message": f"{rule_id} matched",
            },
        }
    ],
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
PY
  rewrite_manifest "$policy_dir"
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

pending_file() {
  printf '%s/.gran-maestro/sessions/%s/pending-confirm.json\n' "$WORKSPACE" "$1"
}

args_sha256_for_payload() {
  local payload="$1"
  python3 - "$payload" <<'PY'
import hashlib
import json
import sys

payload = json.loads(sys.argv[1])
args = payload.get("tool_input") if isinstance(payload, dict) else {}
if not isinstance(args, dict):
    args = {}
canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
PY
}

append_history_event() {
  local sid="$1"
  local event_json="$2"
  python3 - "$REPO_ROOT" "$WORKSPACE" "$HOME_DIR" "$sid" "$event_json" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
workspace = Path(sys.argv[2])
home = Path(sys.argv[3])
sid = sys.argv[4]
event = json.loads(sys.argv[5])

module_path = repo_root / "hooks" / "lib" / "pre_tool_use_fast.py"
spec = importlib.util.spec_from_file_location("pre_tool_use_fast", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
status = module.append_event_after_verified(workspace, home, sid, event)
raise SystemExit(status)
PY
}

install_phase_gate_rule() {
  run_mst policy init >/dev/null
  local policy_dir
  policy_dir="$(policy_project_dir)"
  python3 - "$policy_dir/rules.d/phase-gate.json" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "version": 1,
    "rules": [
        {
            "id": "GM-PHASE-GATE",
            "description": "Phase gate is enforced by hooks/lib/pre_tool_use_fast.py for mutating tool and Bash calls.",
            "severity": "warn",
            "trigger": {"tool": "__never__"},
            "action": {
                "decision": "warn",
                "message": "phase gate enforcement is hardcoded",
            },
        }
    ],
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
PY
  rewrite_manifest "$policy_dir"
}
