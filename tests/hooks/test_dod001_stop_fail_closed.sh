#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_SESSION_ID="MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID="MST-REQ-805-20260503T131853000Z-r4n8vd1c"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

run_stop_hook() {
  local project_root="$1" payload="$2" stdout_file="$3" stderr_file="$4"
  (
    cd "$project_root"
    HOME="$TEST_TMP_ROOT/home" \
    MST_CLAUDE_HOME="$TEST_TMP_ROOT/home" \
    MST_SESSION_ID="$ROOT_SESSION_ID" \
    MST_STOP_HOOK_CLEANUP_DISABLE=1 \
    bash "$REPO_ROOT/hooks/mst-stop-hook.sh" <<<"$payload" >"$stdout_file" 2>"$stderr_file"
  )
}

assert_blocked() {
  local name="$1" stdout_file="$2"
  python3 - "$name" "$stdout_file" <<'PY'
import json
import sys
from pathlib import Path

name = sys.argv[1]
text = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
payload = json.loads(text)
if payload.get("decision") != "block":
    raise SystemExit(f"{name}: expected block, got {payload}")
PY
}

assert_approved() {
  local name="$1" stdout_file="$2"
  python3 - "$name" "$stdout_file" <<'PY'
import json
import sys
from pathlib import Path

name = sys.argv[1]
text = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
payload = json.loads(text)
if payload.get("decision") != "approve":
    raise SystemExit(f"{name}: expected approve, got {payload}")
PY
}

assert_no_mutation_paths() {
  local name="$1" project_root="$2"
  [ ! -e "$project_root/.gran-maestro/state/$ROOT_SESSION_ID" ] || fail "$name mutated canonical state"
  [ ! -e "$project_root/.gran-maestro/sessions/$ROOT_SESSION_ID" ] || fail "$name mutated canonical session history"
}

mkdir -p "$TEST_TMP_ROOT/home"

mismatch_project="$TEST_TMP_ROOT/mismatch"
mkdir -p "$mismatch_project/.gran-maestro/state/$ROOT_SESSION_ID"
printf '{"mst_session_id":"%s","current_skill":"mst:agile","current_step":1,"total_steps":3}\n' "$STALE_SESSION_ID" > "$mismatch_project/.gran-maestro/state/$ROOT_SESSION_ID/snapshot.json"
mismatch_stdout="$TEST_TMP_ROOT/mismatch.out"
mismatch_stderr="$TEST_TMP_ROOT/mismatch.err"
run_stop_hook "$mismatch_project" "$(printf '{"hook_event_name":"Stop","mst_session_id":"%s","session_id":"claude-diagnostic"}' "$ROOT_SESSION_ID")" "$mismatch_stdout" "$mismatch_stderr"
assert_blocked "mismatch" "$mismatch_stdout"
python3 - "$mismatch_project/.gran-maestro/state/$ROOT_SESSION_ID/snapshot.json" "$STALE_SESSION_ID" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("mst_session_id") != sys.argv[2]:
    raise SystemExit("snapshot was mutated during mismatch fail-closed path")
if "block_count" in payload or "last_block_reason" in payload:
    raise SystemExit("block state was persisted during mismatch fail-closed path")
PY

owner_project="$TEST_TMP_ROOT/owner-ppid-only"
mkdir -p "$owner_project/.gran-maestro/requests/REQ-PPID" "$owner_project/.gran-maestro"
owner_stdout="$TEST_TMP_ROOT/owner.out"
owner_stderr="$TEST_TMP_ROOT/owner.err"
bash -c '
  set -euo pipefail
  cd "$1"
  wrapper_pid="$$"
  printf "{\"id\":\"REQ-PPID\",\"status\":\"active\",\"owner_ppid\":%s}\n" "$wrapper_pid" > ".gran-maestro/requests/REQ-PPID/request.json"
  HOME="$2" \
  MST_CLAUDE_HOME="$2" \
  MST_SESSION_ID="$3" \
  MST_STOP_HOOK_CLEANUP_DISABLE=1 \
  MST_HOOK_LEDGER_DISABLE=1 \
  bash "$4/hooks/mst-stop-hook.sh" >"$5" 2>"$6" <<JSON
{"hook_event_name":"Stop","mst_session_id":"$3","session_id":"claude-diagnostic"}
JSON
' _ "$owner_project" "$TEST_TMP_ROOT/home" "$ROOT_SESSION_ID" "$REPO_ROOT" "$owner_stdout" "$owner_stderr"
assert_approved "owner_ppid_only" "$owner_stdout"
assert_no_mutation_paths "owner_ppid_only" "$owner_project"
grep -F 'owner_ppid-only workflow state ignored' "$owner_stderr" >/dev/null || fail "owner_ppid diagnostic missing"
printf 'PASS: stop hook fail-closed mismatch and owner_ppid-only diagnostic-only cases without canonical mutation\n'
