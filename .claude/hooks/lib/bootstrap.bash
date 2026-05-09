#!/usr/bin/env bash

if [ -n "${MST_BOOTSTRAP_BASH_SOURCED:-}" ]; then
  return 0
fi
MST_BOOTSTRAP_BASH_SOURCED=1

mst_warn_unexpected_execution_path() {
  printf '[mst-hook] warning: unexpected execution path. Possible ${CLAUDE_PLUGIN_ROOT} mis-substitution. Exiting fail-open.\n' >&2
}

mst_hooks_dir_is_valid() {
  local dir="$1" parent
  case "$dir" in
    *'${CLAUDE_PLUGIN_ROOT}'*) return 1 ;;
    */.claude/plugins/cache/*/hooks) return 0 ;;
    */.claude/plugins/marketplaces/*/hooks) return 0 ;;
  esac
  if [ -f "$dir/lib/sha256.bash" ]; then
    return 0
  fi
  case "$dir" in
    */.claude/hooks)
      parent="${dir%/.claude/hooks}"
      [ -d "$parent/.gran-maestro" ] && return 0
      ;;
    */hooks)
      parent="${dir%/hooks}"
      { [ -d "$parent/.gran-maestro" ] || [ -e "$parent/.git" ]; } && return 0
      if [ -n "${BATS_TEST_TMPDIR:-}" ]; then
        case "$dir" in
          "$BATS_TEST_TMPDIR"/master-baseline/hooks) return 0 ;;
        esac
      fi
      ;;
  esac
  return 1
}

mst_validate_hook_script_dir_or_exit() {
  local dir="$1"
  case "$dir" in
    *'${CLAUDE_PLUGIN_ROOT}'*)
      mst_warn_unexpected_execution_path
      exit 0
      ;;
  esac
  if [ ! -f "$dir/lib/sha256.bash" ] && ! mst_hooks_dir_is_valid "$dir"; then
    mst_warn_unexpected_execution_path
    exit 0
  fi
}

mst_resolve_project_root() {
  local git_top candidate parent
  git_top="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

  if [ -f "${git_top}/.git" ]; then
    candidate="$git_top"
    while [ -n "$candidate" ] && [ "$candidate" != "/" ]; do
      if [ -d "${candidate}/.gran-maestro" ] && [ -e "${candidate}/.git" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      parent="$(dirname "$candidate")"
      if [ "$parent" = "$candidate" ]; then
        break
      fi
      candidate="$parent"
    done
  fi

  printf '%s\n' "$git_top"
}
