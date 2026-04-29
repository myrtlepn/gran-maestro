#!/usr/bin/env bats

load './t01_helpers.bash'

setup() {
  setup_req730_workspace
  run_mst policy init >/dev/null
}

@test "AC-008 hook repair recovers fail-closed ledger and records repair_executed for manifest repair" {
  sid="73000600-0000-4000-8000-000000000801"
  seed_payload='{"session_id":"73000600-0000-4000-8000-000000000801","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  run run_pre_tool_hook "$seed_payload"
  [ "$status" -eq 0 ]

  jq -c '.event.tool = "Tampered"' "$(history_file "$sid")" > "$BATS_TEST_TMPDIR/tampered.ndjson"
  mv "$BATS_TEST_TMPDIR/tampered.ndjson" "$(history_file "$sid")"

  run run_pre_tool_hook "$seed_payload"
  [ "$status" -eq 2 ]
  [[ "$output" == *"history ledger mismatch"* ]]

  run run_mst_tty hook repair --session "$sid" --truncate-to 0 --yes
  [ "$status" -eq 0 ]
  [[ "$output" == *"truncated session=$sid to seq=0"* ]]
  [ "$(wc -l < "$(history_file "$sid")" | tr -d ' ')" = "0" ]
  ls "$WORKSPACE/.gran-maestro/sessions/$sid"/history.ndjson.bak.* >/dev/null

  run run_pre_tool_hook "$seed_payload"
  [ "$status" -eq 0 ]

  policy_dir="$(policy_project_dir)"
  printf '\n' >> "$policy_dir/rules.d/core-bypass.json"
  run run_pre_tool_hook "$seed_payload"
  [ "$status" -eq 2 ]
  [[ "$output" == *"manifest_sha256_mismatch"* ]]

  run run_mst_tty hook repair --manifest --yes
  [ "$status" -eq 0 ]
  [[ "$output" == *"manifest repaired:"* ]]
  [ "$(jq -r 'select(.event.type=="repair_executed") | .event.repair_target' "$(history_file "$sid")")" = "manifest" ]

  run run_pre_tool_hook "$seed_payload"
  [ "$status" -eq 0 ]
}
