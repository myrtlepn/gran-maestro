#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_SESSION_ID="MST-AGI-030-20260503T130813382Z-k7f3q9x2"
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

PROJECT_ROOT="$TEST_TMP_ROOT/project"
HOME_DIR="$TEST_TMP_ROOT/home"
mkdir -p "$PROJECT_ROOT/.gran-maestro" "$HOME_DIR"

payload="$(printf '{"session_id":"%s","mst_session_id":"%s","tool_name":"Bash","tool_input":{"command":"true"}}' "$LEGACY_SESSION_ID" "$ROOT_SESSION_ID")"
(
  cd "$PROJECT_ROOT"
  HOME="$HOME_DIR" \
  MST_CLAUDE_HOME="$HOME_DIR" \
  MST_SESSION_ID="$ROOT_SESSION_ID" \
  MST_PRE_TOOL_USE_TEST_BOOTSTRAP=1 \
  bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload" >/dev/null
)

ledger_file="$PROJECT_ROOT/.gran-maestro/hooks-ledger.ndjson"
history_file="$PROJECT_ROOT/.gran-maestro/sessions/$ROOT_SESSION_ID/history.ndjson"
[ -f "$ledger_file" ] || fail "missing hook ledger: $ledger_file"
[ -f "$history_file" ] || fail "missing canonical history: $history_file"
[ ! -e "$PROJECT_ROOT/.gran-maestro/sessions/$LEGACY_SESSION_ID" ] || fail "legacy session_id created session directory"

python3 - "$ledger_file" "$history_file" "$ROOT_SESSION_ID" "$LEGACY_SESSION_ID" <<'PY'
import json
import sys
from pathlib import Path

ledger_file = Path(sys.argv[1])
history_file = Path(sys.argv[2])
root = sys.argv[3]
legacy = sys.argv[4]

ledger_rows = [json.loads(line) for line in ledger_file.read_text(encoding="utf-8").splitlines() if line.strip()]
if not ledger_rows:
    raise SystemExit("empty hook ledger")
for row in ledger_rows:
    if row.get("mst_session_id") != root:
        raise SystemExit(f"ledger canonical mismatch: {row}")
    if row.get("claude_session_id") != legacy:
        raise SystemExit(f"ledger diagnostic claude_session_id missing: {row}")
    if row.get("session_id") in {root, legacy}:
        raise SystemExit(f"ledger session_id used as canonical/legacy key: {row}")

history_rows = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
if not history_rows:
    raise SystemExit("empty history ledger")
for row in history_rows:
    event = row.get("event") if isinstance(row.get("event"), dict) else {}
    if row.get("mst_session_id") != root or event.get("mst_session_id") != root:
        raise SystemExit(f"history canonical mismatch: {row}")
    if row.get("session_id") in {root, legacy} or event.get("session_id") in {root, legacy}:
        raise SystemExit(f"history session_id used as canonical/legacy key: {row}")

print("PASS: hook identity uses canonical mst_session_id and rejects legacy session_id mutation")
PY
