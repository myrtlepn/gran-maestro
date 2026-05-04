#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MST_SCRIPT="$REPO_ROOT/scripts/mst.py"
PLUGIN_JSON="$REPO_ROOT/.claude-plugin/plugin.json"

TMP_ROOT="$(mktemp -d)"
TMP_PROJECT="$TMP_ROOT/project"

cleanup() {
  rm -rf "$TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

PLUGIN_VERSION="$(python3 - "$PLUGIN_JSON" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = payload.get("version")
if not isinstance(version, str) or not version.strip():
    raise SystemExit(1)
print(version.strip())
PY
)"

[ -n "$PLUGIN_VERSION" ] || fail "plugin version read failed"

mkdir -p "$TMP_PROJECT"
cp -R "$REPO_ROOT/hooks" "$TMP_PROJECT/hooks"
mkdir -p "$TMP_PROJECT/.claude/hooks"
if [ -d "$REPO_ROOT/.claude/hooks" ]; then
  cp -R "$REPO_ROOT/.claude/hooks/." "$TMP_PROJECT/.claude/hooks/"
fi

# self-reference recursion guard for temporary project scans
rm -rf "$TMP_PROJECT/.gran-maestro/worktrees" 2>/dev/null || true

printf '%s\n' "$PLUGIN_VERSION" > "$TMP_PROJECT/.claude/hooks/.mst-hook-version"
cp "$TMP_PROJECT/hooks/mst-stop-hook.sh" "$TMP_PROJECT/.claude/hooks/mst-stop-hook.sh"
printf '\n# dbg042-integration hash mismatch marker\n' >> "$TMP_PROJECT/.claude/hooks/mst-stop-hook.sh"

SYNC_OUTPUT="$(
  cd "$TMP_PROJECT"
  python3 "$MST_SCRIPT" hooks sync
)"

SOURCE_HASH="$(sha256_file "$TMP_PROJECT/hooks/mst-stop-hook.sh")"
SYNCED_HASH="$(sha256_file "$TMP_PROJECT/.claude/hooks/mst-stop-hook.sh")"
[ "$SOURCE_HASH" = "$SYNCED_HASH" ] || fail "CAUSE-1 hash mismatch was not repaired"
printf '%s\n' "$SYNC_OUTPUT" | grep -Eiq 'resynced|hash' || fail "CAUSE-1 sync output missing hash/resynced signal"

mkdir -p "$TMP_PROJECT/.gran-maestro/requests/REQ-TEST-INT"
printf '%s\n' '{"status":"phase1_analysis","mst_session_id":"MST-AGI-030-20260503T130813382Z-k7f3q9x2"}' > "$TMP_PROJECT/.gran-maestro/requests/REQ-TEST-INT/request.json"
rm -f "$TMP_PROJECT/.gran-maestro/tmp"/mst-state-*.json 2>/dev/null || true

(
  cd "$TMP_PROJECT"
  printf '%s' '{"stop_hook_active":false,"mst_session_id":"MST-AGI-030-20260503T130813382Z-k7f3q9x2","last_assistant_message":"integration"}' \
    | bash hooks/mst-stop-hook.sh > out.txt
)

grep -F '"decision": "block"' "$TMP_PROJECT/out.txt" >/dev/null || fail "CAUSE-2 did not block"
grep -F 'active workflow session detected' "$TMP_PROJECT/out.txt" >/dev/null \
  || fail "CAUSE-2 block reason missing active workflow session message"

(
  cd "$REPO_ROOT"
  bash tests/test-continuation-guard.sh
)

(
  cd "$REPO_ROOT"
  bash tests/test-hooks-sync.sh
)

if python3 -m pytest --version >/dev/null 2>&1; then
  (
    cd "$REPO_ROOT"
    python3 -m pytest -q tests/test_agile_pause_guard.py tests/test_stop_hook_patterns.py
  )
else
  printf 'WARN: pytest not installed; skipping pytest regression step.\n' >&2
fi

echo "integration PASS"
exit 0
