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

run_stop_hook_without_mst_session() {
  local project_root="$1" payload="$2" stdout_file="$3" stderr_file="$4"
  (
    cd "$project_root"
    HOME="$TEST_TMP_ROOT/home" \
    MST_CLAUDE_HOME="$TEST_TMP_ROOT/home" \
    MST_STOP_HOOK_CLEANUP_DISABLE=1 \
    bash "$REPO_ROOT/hooks/mst-stop-hook.sh" <<<"$payload" >"$stdout_file" 2>"$stderr_file"
  )
}

run_stop_hook_timeout() {
  local project_root="$1" payload="$2" stdout_file="$3" stderr_file="$4"
  (
    cd "$project_root"
    HOME="$TEST_TMP_ROOT/home" \
    MST_CLAUDE_HOME="$TEST_TMP_ROOT/home" \
    MST_SESSION_ID="$ROOT_SESSION_ID" \
    MST_STOP_HOOK_CLEANUP_DISABLE=1 \
    MST_HOOK_JUDGE_TIMEOUT_MS=5 \
    MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS=50 \
    bash "$REPO_ROOT/hooks/mst-stop-hook.sh" <<<"$payload" >"$stdout_file" 2>"$stderr_file"
  )
}

assert_strict_stdout_contract() {
  local name="$1" stdout_file="$2" expected_decision="$3" expected_reason_substring="$4"
  python3 - "$name" "$stdout_file" "$expected_decision" "$expected_reason_substring" <<'PY'
import json
import sys
from pathlib import Path

name, stdout_path, expected_decision, expected_reason_substring = sys.argv[1:5]
lines = [line for line in Path(stdout_path).read_text(encoding="utf-8").splitlines() if line.strip()]
if len(lines) != 1:
    raise SystemExit(f"{name}: expected exactly one non-empty stdout line, got {lines!r}")

payload = json.loads(lines[0])
if set(payload) != {"decision", "reason"}:
    raise SystemExit(f"{name}: unexpected stdout keys {sorted(payload)}")
if payload.get("decision") != expected_decision:
    raise SystemExit(f"{name}: expected decision={expected_decision}, got {payload!r}")
reason = payload.get("reason")
if not isinstance(reason, str) or not reason.strip():
    raise SystemExit(f"{name}: missing reason in {payload!r}")
if expected_reason_substring and expected_reason_substring not in reason:
    raise SystemExit(
        f"{name}: expected reason to contain {expected_reason_substring!r}, got {reason!r}"
    )
PY
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
assert_strict_stdout_contract "mismatch" "$mismatch_stdout" "block" "mst_session_id mismatch"
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
assert_strict_stdout_contract "owner_ppid_only" "$owner_stdout" "approve" "owner_ppid-only workflow state ignored"
assert_no_mutation_paths "owner_ppid_only" "$owner_project"
grep -F 'owner_ppid-only workflow state ignored' "$owner_stderr" >/dev/null || fail "owner_ppid diagnostic missing"

no_canonical_project="$TEST_TMP_ROOT/no-canonical"
mkdir -p "$no_canonical_project/.gran-maestro/tmp"
no_canonical_stdout="$TEST_TMP_ROOT/no-canonical.out"
no_canonical_stderr="$TEST_TMP_ROOT/no-canonical.err"
run_stop_hook_without_mst_session "$no_canonical_project" '{"hook_event_name":"Stop","session_id":"claude-diagnostic"}' "$no_canonical_stdout" "$no_canonical_stderr"
assert_approved "no_canonical" "$no_canonical_stdout"
assert_strict_stdout_contract "no_canonical" "$no_canonical_stdout" "approve" "no-mst-session"
grep -F 'missing canonical parent MST_SESSION_ID/mst_session_id' "$no_canonical_stderr" >/dev/null || fail "no canonical diagnostic missing"

timeout_project="$TEST_TMP_ROOT/timeout"
mkdir -p "$timeout_project/.gran-maestro/tmp"
timeout_stdout="$TEST_TMP_ROOT/timeout.out"
timeout_stderr="$TEST_TMP_ROOT/timeout.err"
run_stop_hook_timeout "$timeout_project" "$(printf '{"hook_event_name":"Stop","session_id":"claude-diagnostic","mst_session_id":"%s"}' "$ROOT_SESSION_ID")" "$timeout_stdout" "$timeout_stderr"
assert_approved "timeout" "$timeout_stdout"
assert_strict_stdout_contract "timeout" "$timeout_stdout" "approve" "hook judge timeout (>5ms) fail-open"
grep -F 'judge_timeout budget_ms=5' "$timeout_stderr" >/dev/null || fail "timeout diagnostic missing"
printf 'PASS: stop hook fail-closed mismatch and owner_ppid-only diagnostic-only cases without canonical mutation\n'
