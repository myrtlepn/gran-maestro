#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WORKSPACE="$BATS_TEST_TMPDIR/workspace"
  HOME_DIR="$BATS_TEST_TMPDIR/home"
  mkdir -p "$WORKSPACE/.gran-maestro/tmp" "$WORKSPACE/.gran-maestro/logs" "$HOME_DIR"
  printf 'gitdir: .\n' > "$WORKSPACE/.git"
  export HOME="$HOME_DIR"
}

payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

print(json.dumps({"session_id": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))
PY
}

run_pre_tool_hook() {
  (cd "$WORKSPACE" && HOME="$HOME_DIR" bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$(payload "$1" "$2")")
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

@test "AC-004 blocks eight Bash command variants with 100 percent pass rate" {
  cat > "$WORKSPACE/wrap.sh" <<'SH'
#!/usr/bin/env sh
mst confirm cf_wrapper
SH
  chmod +x "$WORKSPACE/wrap.sh"

  commands=(
    'bash -c "mst confirm cf_bash_c"'
    'eval "mst confirm cf_eval"'
    'MST_FOO=1 mst confirm cf_env'
    './scripts/mst.py confirm cf_script'
    'python3 -m mst confirm cf_module'
    "alias mc='mst confirm'; mc cf_alias"
    './wrap.sh'
    'sh ./wrap.sh mst confirm cf_wrapper_args'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73003004-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$sid" "$command"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
    index=$((index + 1))
  done
}
