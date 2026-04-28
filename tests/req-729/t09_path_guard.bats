#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export REPO_ROOT
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$WORKSPACE/.gran-maestro/logs" "$HOME_DIR"
  printf 'gitdir: .\n' > "$WORKSPACE/.git"
  export HOME="$HOME_DIR"
}

copy_hook_fixture() {
  local hook="$1"
  local hook_dir="$2"
  local with_lib="${3:-}"
  mkdir -p "$hook_dir"
  cp "$REPO_ROOT/hooks/$hook" "$hook_dir/$hook"
  chmod +x "$hook_dir/$hook"
  if [ "$with_lib" = "with-lib" ]; then
    cp -R "$REPO_ROOT/hooks/lib" "$hook_dir/lib"
  fi
  printf '%s/%s\n' "$hook_dir" "$hook"
}

payload_for_hook() {
  local hook="$1"
  case "$hook" in
    mst-pre-tool-use.sh)
      printf '%s\n' '{"tool_name":"Read","tool_input":{"file_path":"README.md"}}'
      ;;
    mst-session-init.sh)
      printf '%s\n' '{"session_id":"99999999-9999-4999-8999-999999999999"}'
      ;;
    mst-stop-hook.sh)
      printf '%s\n' '{"stop_hook_active":true}'
      ;;
    *)
      printf '%s\n' '{}'
      ;;
  esac
}

run_hook() {
  local hook_path="$1"
  local payload="$2"
  (
    cd "$WORKSPACE" || exit 1
    HOME="$HOME_DIR" bash "$hook_path" <<<"$payload"
  )
}

assert_no_guard_warning() {
  [[ "$output" != *"[mst-hook] warning: unexpected execution path"* ]]
}

assert_guard_warning() {
  [ "$status" -eq 0 ]
  [[ "$output" == *"[mst-hook] warning: unexpected execution path"* ]]
  [[ "$output" == *'Possible ${CLAUDE_PLUGIN_ROOT} mis-substitution'* ]]
}

@test "mst-pre-tool-use allows plugin cache hooks path" {
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$BATS_TEST_TMPDIR/.claude/plugins/cache/foo/mst/0.59.6/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-pre-tool-use allows plugin marketplaces hooks path" {
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$BATS_TEST_TMPDIR/.claude/plugins/marketplaces/foo/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-pre-tool-use allows repo dev hooks path with git marker" {
  repo_dir="$BATS_TEST_TMPDIR/myrepo"
  mkdir -p "$repo_dir"
  printf 'gitdir: .\n' > "$repo_dir/.git"
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$repo_dir/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-pre-tool-use allows project install .claude hooks path with gran-maestro marker" {
  project_dir="$BATS_TEST_TMPDIR/myproj"
  mkdir -p "$project_dir/.gran-maestro"
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$project_dir/.claude/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-pre-tool-use fail-opens literal CLAUDE_PLUGIN_ROOT path" {
  literal_dir="$BATS_TEST_TMPDIR/\${CLAUDE_PLUGIN_ROOT}/hooks"
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$literal_dir")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  assert_guard_warning
}

@test "mst-pre-tool-use fail-opens arbitrary hooks path without markers or lib" {
  hook_path="$(copy_hook_fixture "mst-pre-tool-use.sh" "$BATS_TEST_TMPDIR/random/hooks")"

  run run_hook "$hook_path" "$(payload_for_hook "mst-pre-tool-use.sh")"

  assert_guard_warning
}

@test "mst-session-init allows plugin cache hooks path" {
  hook="mst-session-init.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/session/.claude/plugins/cache/foo/mst/0.59.6/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-session-init fail-opens arbitrary hooks path without markers or lib" {
  hook="mst-session-init.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/session-random/hooks")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  assert_guard_warning
}

@test "mst-auto-chain-context allows plugin cache hooks path" {
  hook="mst-auto-chain-context.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/auto/.claude/plugins/cache/foo/mst/0.59.6/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-auto-chain-context fail-opens arbitrary hooks path without markers or lib" {
  hook="mst-auto-chain-context.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/auto-random/hooks")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  assert_guard_warning
}

@test "mst-stop-hook allows plugin cache hooks path" {
  hook="mst-stop-hook.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/stop/.claude/plugins/cache/foo/mst/0.59.6/hooks" "with-lib")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  [ "$status" -eq 0 ]
  assert_no_guard_warning
}

@test "mst-stop-hook fail-opens arbitrary hooks path without markers or lib" {
  hook="mst-stop-hook.sh"
  hook_path="$(copy_hook_fixture "$hook" "$BATS_TEST_TMPDIR/stop-random/hooks")"

  run run_hook "$hook_path" "$(payload_for_hook "$hook")"

  assert_guard_warning
}
