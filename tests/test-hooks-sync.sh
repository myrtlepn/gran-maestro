#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MST_SCRIPT="$REPO_ROOT/scripts/mst.py"
HOOKS_SOURCE_DIR="$REPO_ROOT/hooks"
PLUGIN_JSON="$REPO_ROOT/.claude-plugin/plugin.json"

PLUGIN_VERSION="$(python3 - <<'PY' "$PLUGIN_JSON"
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
version = data.get("version")
if not isinstance(version, str) or not version.strip():
    raise SystemExit("")
print(version.strip())
PY
)"

if [ -z "$PLUGIN_VERSION" ]; then
  echo "FAIL: unable to read plugin version"
  exit 1
fi

PASS_COUNT=0
TMP_DIRS=()

cleanup() {
  local dir=""
  for dir in "${TMP_DIRS[@]:-}"; do
    rm -rf "$dir" 2>/dev/null || true
  done
}
trap cleanup EXIT

new_tmpdir() {
  local dir=""
  dir="$(mktemp -d)"
  TMP_DIRS+=("$dir")
  printf '%s\n' "$dir"
}

fail() {
  local name="$1"
  echo "FAIL: $name"
  exit 1
}

pass() {
  local name="$1"
  echo "PASS: $name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

assert_eq() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" != "$actual" ]; then
    echo "FAIL: $name"
    echo "  expected: $expected"
    echo "  actual:   $actual"
    exit 1
  fi
}

assert_file_exists() {
  local name="$1"
  local file_path="$2"
  if [ ! -f "$file_path" ]; then
    fail "$name"
  fi
}

assert_dir_exists() {
  local name="$1"
  local dir_path="$2"
  if [ ! -d "$dir_path" ]; then
    fail "$name"
  fi
}

sync_hooks() {
  local project_dir="$1"
  mkdir -p "$project_dir/.gran-maestro"
  if ! (cd "$project_dir" && python3 "$MST_SCRIPT" hooks sync >/dev/null 2>&1); then
    fail "hooks sync command failed in $project_dir"
  fi
}

file_mtime_ns() {
  local file_path="$1"
  python3 - <<'PY' "$file_path"
import sys
from pathlib import Path
print(Path(sys.argv[1]).stat().st_mtime_ns)
PY
}

hooks_sync_copies_when_version_differs() {
  local case_name="hooks_sync_copies_when_version_differs"
  local project_dir=""
  project_dir="$(new_tmpdir)"

  mkdir -p "$project_dir/.claude/hooks"
  printf '0.0.0\n' > "$project_dir/.claude/hooks/.mst-hook-version"

  sync_hooks "$project_dir"

  assert_file_exists "$case_name" "$project_dir/.claude/hooks/.mst-hook-version"

  local stamped_version=""
  stamped_version="$(tr -d '\n' < "$project_dir/.claude/hooks/.mst-hook-version")"
  assert_eq "$case_name" "$PLUGIN_VERSION" "$stamped_version"

  assert_file_exists "$case_name" "$project_dir/.claude/hooks/mst-stop-hook.sh"
  if ! cmp -s "$HOOKS_SOURCE_DIR/mst-stop-hook.sh" "$project_dir/.claude/hooks/mst-stop-hook.sh"; then
    fail "$case_name"
  fi

  pass "$case_name"
}

hooks_sync_is_noop_on_match() {
  local case_name="hooks_sync_is_noop_on_match"
  local project_dir=""
  project_dir="$(new_tmpdir)"

  sync_hooks "$project_dir"

  local synced_file="$project_dir/.claude/hooks/mst-stop-hook.sh"
  assert_file_exists "$case_name" "$synced_file"

  local before_mtime=""
  local after_mtime=""
  before_mtime="$(file_mtime_ns "$synced_file")"
  sync_hooks "$project_dir"
  after_mtime="$(file_mtime_ns "$synced_file")"

  assert_eq "$case_name" "$before_mtime" "$after_mtime"
  pass "$case_name"
}

hooks_sync_creates_missing_dirs() {
  local case_name="hooks_sync_creates_missing_dirs"
  local project_dir=""
  project_dir="$(new_tmpdir)"

  if [ -d "$project_dir/.claude" ]; then
    rm -rf "$project_dir/.claude"
  fi

  sync_hooks "$project_dir"

  assert_dir_exists "$case_name" "$project_dir/.claude"
  assert_dir_exists "$case_name" "$project_dir/.claude/hooks"
  assert_file_exists "$case_name" "$project_dir/.claude/hooks/.mst-hook-version"
  pass "$case_name"
}

hooks_sync_rewrites_when_hash_differs_on_same_version() {
  local case_name="hooks_sync_rewrites_when_hash_differs_on_same_version"
  local project_dir=""
  local synced_file=""
  local command_output=""
  project_dir="$(new_tmpdir)"

  sync_hooks "$project_dir"

  synced_file="$project_dir/.claude/hooks/mst-stop-hook.sh"
  assert_file_exists "$case_name" "$synced_file"

  printf '#!/usr/bin/env bash\necho "stale-copy"\n' > "$synced_file"
  chmod +x "$synced_file"

  if cmp -s "$HOOKS_SOURCE_DIR/mst-stop-hook.sh" "$synced_file"; then
    fail "$case_name"
  fi

  command_output="$(
    cd "$project_dir" &&
      python3 "$MST_SCRIPT" hooks sync
  )"

  if ! cmp -s "$HOOKS_SOURCE_DIR/mst-stop-hook.sh" "$synced_file"; then
    fail "$case_name"
  fi

  if ! printf '%s\n' "$command_output" | grep -Fq "[hooks] resynced 1 files by hash (v$PLUGIN_VERSION)"; then
    fail "$case_name"
  fi

  pass "$case_name"
}

hooks_sync_copies_when_version_differs
hooks_sync_is_noop_on_match
hooks_sync_creates_missing_dirs
hooks_sync_rewrites_when_hash_differs_on_same_version

echo "PASS: total=$PASS_COUNT"
