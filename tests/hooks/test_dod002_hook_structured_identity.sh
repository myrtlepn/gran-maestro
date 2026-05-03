#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STRUCTURED_ID="MST-AGI-030-20260503T130813382Z-k7f3q9x2"
LEGACY_CLAUDE_SESSION="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_TRANSCRIPT_SESSION="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

new_project() {
  local name="$1" project
  project="$TEST_TMP_ROOT/$name"
  mkdir -p "$project/.gran-maestro" "$project/home"
  printf '%s\n' "$project"
}

run_session_init() {
  local project="$1" payload="$2"
  (
    cd "$project"
    HOME="$project/home" \
    MST_CLAUDE_HOME="$project/home" \
    bash "$REPO_ROOT/hooks/mst-session-init.sh" <<<"$payload" >/dev/null
  )
}

run_pre_tool() {
  local project="$1" payload="$2"
  (
    cd "$project"
    HOME="$project/home" \
    MST_CLAUDE_HOME="$project/home" \
    MST_PRE_TOOL_USE_TEST_BOOTSTRAP=1 \
    bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload" >/dev/null
  )
}

run_stop_hook() {
  local project="$1" payload="$2"
  (
    cd "$project"
    HOME="$project/home" \
    MST_CLAUDE_HOME="$project/home" \
    MST_STOP_HOOK_CLEANUP_DISABLE=1 \
    bash "$REPO_ROOT/hooks/mst-stop-hook.sh" <<<"$payload" >/dev/null
  )
}

run_stop_timeout_legacy_only() {
  local project="$1" payload="$2"
  (
    cd "$project"
    HOME="$project/home" \
    MST_CLAUDE_HOME="$project/home" \
    MST_STOP_HOOK_CLEANUP_DISABLE=1 \
    MST_HOOK_JUDGE_TIMEOUT_TEST_SLEEP_MS=999 \
    bash "$REPO_ROOT/hooks/mst-stop-hook.sh" <<<"$payload" >/dev/null
  )
}

payload_with_structured="$(python3 - "$STRUCTURED_ID" "$LEGACY_CLAUDE_SESSION" "$LEGACY_TRANSCRIPT_SESSION" <<'PY'
import json
import sys

structured, legacy, transcript = sys.argv[1:]
print(json.dumps({
    "session_id": legacy,
    "mst_session_id": structured,
    "transcript_path": f"/tmp/{transcript}.jsonl",
    "tool_name": "Skill",
    "tool_input": {"skill_name": "mst:request", "args": "REQ-805"},
}))
PY
)"

legacy_only_payload="$(python3 - "$LEGACY_CLAUDE_SESSION" "$LEGACY_TRANSCRIPT_SESSION" <<'PY'
import json
import sys

legacy, transcript = sys.argv[1:]
print(json.dumps({
    "session_id": legacy,
    "transcript_path": f"/tmp/{transcript}.jsonl",
    "tool_name": "Stop",
    "tool_input": {},
}))
PY
)"

session_project="$(new_project session-init)"
pretool_project="$(new_project pre-tool)"
stop_project="$(new_project stop-hook)"
legacy_project="$(new_project legacy-only)"

run_session_init "$session_project" "$payload_with_structured"
run_pre_tool "$pretool_project" "$payload_with_structured"
run_stop_hook "$stop_project" "$payload_with_structured"
run_stop_timeout_legacy_only "$legacy_project" "$legacy_only_payload"

python3 - \
  "$STRUCTURED_ID" \
  "$LEGACY_CLAUDE_SESSION" \
  "$LEGACY_TRANSCRIPT_SESSION" \
  "$session_project" \
  "$pretool_project" \
  "$stop_project" \
  "$legacy_project" <<'PY'
import json
import sys
from pathlib import Path

structured, legacy, transcript, *projects = sys.argv[1:]

for raw_project in projects[:3]:
    project = Path(raw_project)
    ledger = project / ".gran-maestro" / "hooks-ledger.ndjson"
    if not ledger.is_file():
        raise SystemExit(f"missing ledger for {project}")
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"empty ledger for {project}")
    for row in rows:
        if row.get("mst_session_id") != structured:
            raise SystemExit(f"structured mst_session_id not canonical for {project}: {row}")
        if row.get("claude_session_id") != legacy:
            raise SystemExit(f"Claude session_id not retained as diagnostic for {project}: {row}")
    for forbidden in (legacy, transcript):
        if (project / ".gran-maestro" / "sessions" / forbidden).exists():
            raise SystemExit(f"legacy session directory created: {project} {forbidden}")
        if (project / ".gran-maestro" / "state" / forbidden).exists():
            raise SystemExit(f"legacy state directory created: {project} {forbidden}")

legacy_project = Path(projects[3])
legacy_ledger = legacy_project / ".gran-maestro" / "hooks-ledger.ndjson"
if legacy_ledger.is_file():
    rows = [json.loads(line) for line in legacy_ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row.get("mst_session_id") in {legacy, transcript}:
            raise SystemExit(f"legacy value became canonical in legacy-only hook: {row}")
for forbidden in (legacy, transcript):
    if (legacy_project / ".gran-maestro" / "state" / forbidden).exists():
        raise SystemExit(f"legacy-only stop hook created state from legacy id: {forbidden}")
    if (legacy_project / ".gran-maestro" / "sessions" / forbidden).exists():
        raise SystemExit(f"legacy-only stop hook created session from legacy id: {forbidden}")

print("PASS: hooks use structured mst_session_id and do not generate from Claude session_id/transcript")
PY
