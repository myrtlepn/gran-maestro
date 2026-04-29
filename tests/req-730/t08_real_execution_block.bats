#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  cat > "$WORKSPACE/wrap.sh" <<'SH'
#!/usr/bin/env sh
mst confirm cf_wrapper
SH
  chmod +x "$WORKSPACE/wrap.sh"
}

bash_payload() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

print(json.dumps({"session_id": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))
PY
}

@test "AC-002 real mst execution variants still core block" {
  commands=(
    'mst confirm cf_direct'
    'bash -c "mst confirm cf_bash_c"'
    'eval "mst confirm cf_eval"'
    'MST_FOO=1 mst confirm cf_env'
    'python3 scripts/mst.py confirm cf_script'
    './scripts/mst.py confirm cf_script_direct'
    'python3 -m mst confirm cf_module'
    './wrap.sh'
    "alias mc='mst confirm'; mc cf_alias"
    'sh ./wrap.sh mst confirm cf_wrapper_args'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73008002-0000-4000-8000-%012d' "$index")"
    run run_pre_tool_hook "$(bash_payload "$sid" "$command")"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
    index=$((index + 1))
  done
}
