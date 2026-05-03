#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_SESSION_ID="MST-AGI-030-20260503T130813382Z-k7f3q9x2"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

write_mst_stub() {
  local project_root="$1"
  mkdir -p "$project_root/scripts"
  cat > "$project_root/scripts/mst.py" <<'PY'
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
capture = Path.cwd() / ".gran-maestro" / "tmp" / "context-usage-args.json"
capture.parent.mkdir(parents=True, exist_ok=True)
capture.write_text(json.dumps({"args": args}, sort_keys=True) + "\n", encoding="utf-8")
if args[:2] == ["status", "context-usage"]:
    print(json.dumps({
        "context_pct": 0.2,
        "context_tokens": 200,
        "model_window": 1000,
        "cache_available": True,
        "auto_approve_on_unblock": True,
    }))
    raise SystemExit(0)
raise SystemExit(2)
PY
  chmod +x "$project_root/scripts/mst.py"
}

PROJECT_ROOT="$TEST_TMP_ROOT/project"
mkdir -p "$PROJECT_ROOT/.gran-maestro/tmp" "$PROJECT_ROOT/.gran-maestro"
write_mst_stub "$PROJECT_ROOT"

printf '{"workflow_active":true,"next_action":{"auto_mode":true}}\n' > "$PROJECT_ROOT/.gran-maestro/tmp/mst-state-999999.json"
output="$(
  cd "$PROJECT_ROOT"
  MST_STATE_PPID=999999 bash "$REPO_ROOT/hooks/mst-auto-chain-context.sh" <<'JSON'
{"transcript_path":"/tmp/transcript.jsonl"}
JSON
)"
[ -z "$output" ] || fail "PPID-only state was adopted as canonical workflow state"
[ ! -f "$PROJECT_ROOT/.gran-maestro/tmp/context-usage-args.json" ] || fail "PPID-only state invoked context usage"

printf '{"workflow_active":true,"next_action":{"auto_mode":true}}\n' > "$PROJECT_ROOT/.gran-maestro/tmp/mst-state-$ROOT_SESSION_ID.json"
output="$(
  cd "$PROJECT_ROOT"
  MST_SESSION_ID="$ROOT_SESSION_ID" bash "$REPO_ROOT/hooks/mst-auto-chain-context.sh" <<'JSON'
{"transcript_path":"/tmp/transcript.jsonl"}
JSON
)"
printf '%s' "$output" | grep -Fq "hookSpecificOutput" || fail "canonical state did not emit auto-chain context"
python3 - "$PROJECT_ROOT/.gran-maestro/tmp/context-usage-args.json" "$ROOT_SESSION_ID" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = sys.argv[2]
args = payload.get("args", [])
if "--state-file" not in args:
    raise SystemExit("missing --state-file")
state_file = args[args.index("--state-file") + 1]
if not state_file.endswith(f"mst-state-{root}.json"):
    raise SystemExit(f"state file is not canonical: {state_file}")
print("PASS: auto-chain context rejects PPID-only state and accepts canonical state")
PY
