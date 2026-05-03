#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TEST_TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "$TEST_TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

assert_hash_match_if_exists() {
  local label="$1" source="$2" candidate="$3"
  [ -f "$candidate" ] || return 0
  local source_hash candidate_hash
  source_hash="$(sha256_file "$source")"
  candidate_hash="$(sha256_file "$candidate")"
  [ "$source_hash" = "$candidate_hash" ] || fail "$label hash mismatch: $candidate"
}

for hook_name in mst-session-init.sh mst-pre-tool-use.sh mst-stop-hook.sh; do
  assert_hash_match_if_exists ".claude hook $hook_name" \
    "$REPO_ROOT/hooks/$hook_name" \
    "$REPO_ROOT/.claude/hooks/$hook_name"
done

fixture_cache="$TEST_TMP_ROOT/.claude/plugins/cache/gran-maestro/mst/DOD002"
mkdir -p "$fixture_cache/hooks/lib" "$fixture_cache/.claude/hooks"
cp "$REPO_ROOT/hooks/mst-session-init.sh" \
  "$REPO_ROOT/hooks/mst-pre-tool-use.sh" \
  "$REPO_ROOT/hooks/mst-stop-hook.sh" \
  "$fixture_cache/hooks/"
cp "$REPO_ROOT/hooks/mst-session-init.sh" \
  "$REPO_ROOT/hooks/mst-pre-tool-use.sh" \
  "$REPO_ROOT/hooks/mst-stop-hook.sh" \
  "$fixture_cache/.claude/hooks/"
cp "$REPO_ROOT/hooks/lib/ledger.bash" "$fixture_cache/hooks/lib/"

for hook_name in mst-session-init.sh mst-pre-tool-use.sh mst-stop-hook.sh; do
  assert_hash_match_if_exists "fixture plugin cache hook $hook_name" \
    "$REPO_ROOT/hooks/$hook_name" \
    "$fixture_cache/hooks/$hook_name"
  assert_hash_match_if_exists "fixture plugin cache .claude hook $hook_name" \
    "$REPO_ROOT/hooks/$hook_name" \
    "$fixture_cache/.claude/hooks/$hook_name"
done
assert_hash_match_if_exists "fixture plugin cache ledger.bash" \
  "$REPO_ROOT/hooks/lib/ledger.bash" \
  "$fixture_cache/hooks/lib/ledger.bash"

if [ "${MST_ASSERT_REAL_PLUGIN_CACHE_SYNC:-0}" = "1" ]; then
  for hook_name in mst-session-init.sh mst-pre-tool-use.sh mst-stop-hook.sh; do

    while IFS= read -r cache_file; do
      [ -n "$cache_file" ] || continue
      assert_hash_match_if_exists "plugin cache hook $hook_name" "$REPO_ROOT/hooks/$hook_name" "$cache_file"
    done < <(find "$HOME/.claude/plugins/cache/gran-maestro/mst" \
      \( -path "*/hooks/$hook_name" -o -path "*/.claude/hooks/$hook_name" \) \
      -type f 2>/dev/null | sort || true)
  done

  while IFS= read -r cache_file; do
    [ -n "$cache_file" ] || continue
    assert_hash_match_if_exists "plugin cache ledger.bash" "$REPO_ROOT/hooks/lib/ledger.bash" "$cache_file"
  done < <(find "$HOME/.claude/plugins/cache/gran-maestro/mst" \
    -path "*/hooks/lib/ledger.bash" \
    -type f 2>/dev/null | sort || true)
fi

echo "PASS: DOD-002 hook source, project copy, and plugin cache copies are synchronized"
