#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_SESSION_ID="mst-root-REQ-804-T02"
LEGACY_SESSION_ID="claude-legacy-REQ-804-T02"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_file_exists() {
  local name="$1" path="$2"
  [ -f "$path" ] || fail "$name missing file: $path"
}

PROJECT_ROOT="$TEST_TMP_ROOT/project"
HOME_DIR="$TEST_TMP_ROOT/home"
mkdir -p "$PROJECT_ROOT/.gran-maestro" "$HOME_DIR"

# shellcheck source=/dev/null
source "$REPO_ROOT/hooks/lib/history.bash"

event_json="$(printf '{"type":"fixture","session_id":"%s","legacy_note":"diagnostic-only"}' "$LEGACY_SESSION_ID")"
HOME="$HOME_DIR" MST_CLAUDE_HOME="$HOME_DIR" mst_history_append_event "$PROJECT_ROOT" "$ROOT_SESSION_ID" "$event_json"

history_file="$PROJECT_ROOT/.gran-maestro/sessions/$ROOT_SESSION_ID/history.ndjson"
legacy_history_file="$PROJECT_ROOT/.gran-maestro/sessions/$LEGACY_SESSION_ID/history.ndjson"
assert_file_exists "canonical history" "$history_file"
[ ! -e "$legacy_history_file" ] || fail "legacy session_id created history path: $legacy_history_file"

python3 - "$history_file" "$ROOT_SESSION_ID" "$LEGACY_SESSION_ID" <<'PY'
import json
import sys
from pathlib import Path

history_file = Path(sys.argv[1])
root = sys.argv[2]
legacy = sys.argv[3]
rows = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) != 1:
    raise SystemExit(f"expected one history row, got {len(rows)}")
row = rows[0]
event = row.get("event")
if not isinstance(event, dict):
    raise SystemExit("history row event is not object")
if row.get("mst_session_id") != root:
    raise SystemExit(f"row mst_session_id mismatch: {row.get('mst_session_id')!r}")
if event.get("mst_session_id") != root:
    raise SystemExit(f"event mst_session_id mismatch: {event.get('mst_session_id')!r}")
if row.get("session_id") == root or event.get("session_id") == root:
    raise SystemExit("legacy session_id field used as canonical root")
if row.get("session_id") == legacy or event.get("session_id") == legacy:
    raise SystemExit("legacy session_id field preserved as canonical comparison input")
print("PASS: history ledger uses canonical mst_session_id")
PY
