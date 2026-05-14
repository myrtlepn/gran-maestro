#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_SESSION_ID="MST-AGI-038-20260514T120000000Z-a1b2c3d4"
STDIN_SESSION_ID="MST-AGI-038-20260514T120001000Z-b2c3d4e5"
LEGACY_SESSION_ID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

# shellcheck source=/dev/null
source "$REPO_ROOT/hooks/lib/session_identity.bash"

json_payload() {
  local session_id="$1" mst_session_id="${2:-}"
  python3 - "$session_id" "$mst_session_id" <<'PY'
import json
import sys

session_id, mst_session_id = sys.argv[1:]
payload = {"session_id": session_id}
if mst_session_id:
    payload["mst_session_id"] = mst_session_id
print(json.dumps(payload, sort_keys=True))
PY
}

assert_diagnostic() {
  local expected_valid="$1" expected_reason="$2" expected_action="$3" expected_canonical="$4" expected_invocation="$5"
  python3 - \
    "$MST_SESSION_IDENTITY_DIAGNOSTIC_JSON" \
    "$expected_valid" \
    "$expected_reason" \
    "$expected_action" \
    "$expected_canonical" \
    "$expected_invocation" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_valid = sys.argv[2] == "true"
expected_reason = sys.argv[3]
expected_action = sys.argv[4]
expected_canonical = sys.argv[5] or None
expected_invocation = sys.argv[6]

required = {"valid", "reason", "action", "observed_sources", "source_precedence", "invocation_class"}
missing = required - payload.keys()
if missing:
    raise SystemExit(f"missing diagnostic keys: {sorted(missing)}")
if payload["valid"] is not expected_valid:
    raise SystemExit(f"valid mismatch: {payload}")
if payload["reason"] != expected_reason:
    raise SystemExit(f"reason mismatch: {payload}")
if payload["action"] != expected_action:
    raise SystemExit(f"action mismatch: {payload}")
if payload.get("canonical_mst_session_id") != expected_canonical:
    raise SystemExit(f"canonical mismatch: {payload}")
if payload["invocation_class"] != expected_invocation:
    raise SystemExit(f"invocation_class mismatch: {payload}")
if payload["source_precedence"] != ["env:MST_SESSION_ID", "structured:mst_session_id"]:
    raise SystemExit(f"source precedence mismatch: {payload}")
if "env:MST_SESSION_ID" not in payload["observed_sources"]:
    raise SystemExit(f"missing env observed source: {payload}")
if "structured:mst_session_id" not in payload["observed_sources"]:
    raise SystemExit(f"missing structured observed source: {payload}")
PY
}

run_resolver() {
  local name="$1" policy="$2" env_value="$3" payload="$4" expected_status="$5"
  MST_SESSION_IDENTITY_DIAGNOSTIC_JSON=""
  if [ -n "$env_value" ]; then
    MST_SESSION_ID="$env_value"
    export MST_SESSION_ID
  else
    unset MST_SESSION_ID
  fi

  set +e
  mst_resolve_canonical_mst_session_id "$name" "$policy" "$payload" 2>"$TEST_TMP_ROOT/$name.stderr"
  status=$?
  set -e
  [ "$status" -eq "$expected_status" ] || fail "$name status=$status expected=$expected_status stderr=$(cat "$TEST_TMP_ROOT/$name.stderr")"
}

run_resolver "env_only" "require-env-for-stdin" "$ENV_SESSION_ID" "{}" 0
[ "$MST_RESOLVED_CANONICAL_SESSION_ID" = "$ENV_SESSION_ID" ] || fail "env-only did not resolve env session"
assert_diagnostic true "canonical_identity_resolved" "use_canonical_mst_session_id" "$ENV_SESSION_ID" "hook_boundary_env_only"

run_resolver "stdin_only_allowed" "allow-stdin-without-env" "" "$(json_payload "$LEGACY_SESSION_ID" "$STDIN_SESSION_ID")" 0
[ "$MST_RESOLVED_CANONICAL_SESSION_ID" = "$STDIN_SESSION_ID" ] || fail "stdin-only did not resolve structured stdin session"
assert_diagnostic true "canonical_identity_resolved" "use_canonical_mst_session_id" "$STDIN_SESSION_ID" "hook_boundary_stdin_only"

run_resolver "env_stdin_same" "require-env-for-stdin" "$ENV_SESSION_ID" "$(json_payload "$LEGACY_SESSION_ID" "$ENV_SESSION_ID")" 0
[ "$MST_RESOLVED_CANONICAL_SESSION_ID" = "$ENV_SESSION_ID" ] || fail "env/stdin same did not resolve env session"
assert_diagnostic true "canonical_identity_resolved" "use_canonical_mst_session_id" "$ENV_SESSION_ID" "hook_boundary_env_stdin_same"

run_resolver "env_stdin_conflict" "require-env-for-stdin" "$ENV_SESSION_ID" "$(json_payload "$LEGACY_SESSION_ID" "$STDIN_SESSION_ID")" 1
[ -z "$MST_RESOLVED_CANONICAL_SESSION_ID" ] || fail "conflict resolved a canonical session"
assert_diagnostic false "canonical_identity_conflict" "block_canonical_identity_conflict" "" "hook_boundary_env_stdin_conflict"

run_resolver "invalid_env" "require-env-for-stdin" "not/a/session" "{}" 2
[ -z "$MST_RESOLVED_CANONICAL_SESSION_ID" ] || fail "invalid env resolved a canonical session"
assert_diagnostic false "invalid_canonical_identity" "emit_diagnostic_no_mutation" "" "hook_boundary_invalid_env"

run_resolver "missing" "require-env-for-stdin" "" "{}" 2
[ -z "$MST_RESOLVED_CANONICAL_SESSION_ID" ] || fail "missing identity resolved a canonical session"
assert_diagnostic false "missing_canonical_identity" "emit_diagnostic_no_mutation" "" "hook_boundary_missing"

run_resolver "legacy_only" "allow-stdin-without-env" "" "$(json_payload "$LEGACY_SESSION_ID")" 2
[ -z "$MST_RESOLVED_CANONICAL_SESSION_ID" ] || fail "legacy-only identity resolved a canonical session"
assert_diagnostic false "legacy_identity_not_canonical_source" "emit_diagnostic_no_mutation" "" "hook_boundary_legacy_only"

PROJECT_ROOT="$TEST_TMP_ROOT/project"
HOME_DIR="$TEST_TMP_ROOT/home"
mkdir -p "$PROJECT_ROOT/.gran-maestro" "$HOME_DIR"
(
  cd "$PROJECT_ROOT"
  HOME="$HOME_DIR" \
  MST_CLAUDE_HOME="$HOME_DIR" \
  bash "$REPO_ROOT/hooks/mst-session-init.sh" <<<"$(json_payload "$LEGACY_SESSION_ID")" >/dev/null
)
[ ! -d "$PROJECT_ROOT/.gran-maestro/sessions/$LEGACY_SESSION_ID" ] || fail "legacy-only session created session directory"
[ ! -d "$PROJECT_ROOT/.gran-maestro/state/$LEGACY_SESSION_ID" ] || fail "legacy-only session created state directory"
[ ! -e "$PROJECT_ROOT/.gran-maestro/tmp/mst-state-$LEGACY_SESSION_ID.json" ] || fail "legacy-only session created state file"

printf 'PASS: session identity boundary fixtures converge canonical ids and block legacy/invalid mutation\n'
