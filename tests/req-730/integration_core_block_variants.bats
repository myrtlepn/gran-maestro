#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-002 integrated core block corpus rejects LLM Bash approval and policy bypass commands" {
  cat > "$WORKSPACE/wrap-confirm.sh" <<'SH'
#!/usr/bin/env sh
mst confirm cf_wrapper
SH
  chmod +x "$WORKSPACE/wrap-confirm.sh"

  commands=(
    'mst confirm cf_direct'
    'bash -c "mst confirm cf_bash_c"'
    'eval "mst confirm cf_eval"'
    'MST_FOO=1 mst confirm cf_env'
    './scripts/mst.py confirm cf_script'
    'python3 -m mst confirm cf_module'
    './wrap-confirm.sh'
    'mst hook allow Bash --args-pattern "*"'
    'mst policy edit core-bypass'
    'mst policy install ./policy.json'
  )

  index=1
  for command in "${commands[@]}"; do
    sid="$(printf '73000600-0000-4000-8000-%012d' "$index")"
    payload="$(python3 - "$sid" "$command" <<'PY'
import json
import sys
print(json.dumps({"session_id": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": sys.argv[2]}}))
PY
)"

    run run_pre_tool_hook "$payload"

    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
    [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
    index=$((index + 1))
  done
}
