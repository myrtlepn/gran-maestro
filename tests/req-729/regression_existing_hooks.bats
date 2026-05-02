#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export REPO_ROOT
  HOME_BASE="$BATS_TEST_TMPDIR/home"
  mkdir -p "$HOME_BASE"
}

new_workspace() {
  local name="$1"
  local workspace="$BATS_TEST_TMPDIR/$name"
  mkdir -p "$workspace/.gran-maestro/tmp" "$workspace/.gran-maestro/logs" "$workspace/home"
  printf 'gitdir: .\n' > "$workspace/.git"
  printf '%s\n' "$workspace"
}

capture_hook() {
  local workspace="$1"
  local hook="$2"
  local payload="$3"
  local out_file="$4"
  local err_file="$5"
  local status_file="$6"
  set +e
  (
    cd "$workspace" || exit 1
    HOME="$workspace/home" bash "$REPO_ROOT/hooks/$hook" <<<"$payload" >"$out_file" 2>"$err_file"
  )
  printf '%s\n' "$?" > "$status_file"
  set -e
}

capture_hook_file() {
  local workspace="$1"
  local hook_path="$2"
  local payload="$3"
  local out_file="$4"
  local err_file="$5"
  local status_file="$6"
  set +e
  (
    cd "$workspace" || exit 1
    HOME="$workspace/home" bash "$hook_path" <<<"$payload" >"$out_file" 2>"$err_file"
  )
  printf '%s\n' "$?" > "$status_file"
  set -e
}

assert_same_capture() {
  local left="$1"
  local right="$2"
  cmp -s "$left.status" "$right.status"
  cmp -s "$left.stdout" "$right.stdout"
  cmp -s "$left.stderr" "$right.stderr"
}

prepare_master_baseline_hook() {
  local baseline="$BATS_TEST_TMPDIR/master-baseline"
  local baseline_ref content
  mkdir -p "$baseline/hooks" "$baseline/hooks/lib"
  # T09: 회귀 baseline은 path guard 호환 가능한 master 조상 커밋에서 추출.
  # master 진행분이 strict path guard(plugin-cache/marketplaces 외 무조건 fail-open)를
  # 임시로 도입한 상태(REQ-732 등)에서는 그 커밋을 baseline으로 쓰면 자기 fail-open으로 회귀가 의미 없어진다.
  # 따라서 위 조건을 만족하는 가장 최근 master 조상 커밋을 walk-back으로 찾는다.
  baseline_ref=""
  for candidate in $(git -C "$REPO_ROOT" rev-list master -n 50); do
    content="$(git -C "$REPO_ROOT" show "$candidate":hooks/mst-pre-tool-use.sh 2>/dev/null || true)"
    if [ -z "$content" ]; then
      continue
    fi
    # strict-only guard 패턴 감지: relaxed 케이스 함수가 없고 strict whitelist만 존재
    if printf '%s' "$content" | grep -qE 'plugins/cache/\*/hooks\|.*plugins/marketplaces' \
       && ! printf '%s' "$content" | grep -q '_mst_hooks_dir_is_valid\|BATS_TEST_TMPDIR'; then
      continue
    fi
    baseline_ref="$candidate"
    break
  done
  if [ -z "$baseline_ref" ]; then
    baseline_ref="$(git -C "$REPO_ROOT" merge-base master HEAD 2>/dev/null || printf 'master')"
  fi
  git -C "$REPO_ROOT" show "$baseline_ref":hooks/mst-pre-tool-use.sh > "$baseline/hooks/mst-pre-tool-use.sh"
  chmod +x "$baseline/hooks/mst-pre-tool-use.sh"
  while IFS= read -r lib_file; do
    rel="${lib_file#hooks/lib/}"
    mkdir -p "$baseline/hooks/lib/$(dirname "$rel")"
    git -C "$REPO_ROOT" show "$baseline_ref:$lib_file" > "$baseline/hooks/lib/$rel" 2>/dev/null || true
  done < <(git -C "$REPO_ROOT" ls-tree -r --name-only "$baseline_ref" hooks/lib 2>/dev/null)
  [ -f "$baseline/hooks/lib/sha256.bash" ] || : > "$baseline/hooks/lib/sha256.bash"
  ln -s "$REPO_ROOT/scripts" "$baseline/scripts"
  printf '%s\n' "$baseline/hooks/mst-pre-tool-use.sh"
}

prepare_session_mismatch_workspace() {
  local workspace="$1"
  local stdin_sid="$2"
  local snapshot_sid="$3"
  local durable_sid="$4"
  mkdir -p \
    "$workspace/.gran-maestro/requests/REQ-729" \
    "$workspace/.gran-maestro/state/$stdin_sid"
  cat > "$workspace/.gran-maestro/requests/REQ-729/request.json" <<JSON
{"status":"active","owner_session_id":"$durable_sid"}
JSON
  cat > "$workspace/.gran-maestro/state/$stdin_sid/snapshot.json" <<JSON
{"session_id":"$snapshot_sid"}
JSON
}

prepare_auto_chain_workspace() {
  local workspace="$1"
  ln -s "$REPO_ROOT/scripts" "$workspace/scripts"
  ln -s "$REPO_ROOT/templates" "$workspace/templates"
  cat > "$workspace/.gran-maestro/config.resolved.json" <<'JSON'
{"workflow":{"auto_approve_on_unblock":true}}
JSON
  cat > "$workspace/.gran-maestro/tmp/mst-state-424242.json" <<'JSON'
{"workflow_active":true,"next_action":{"auto_mode":false}}
JSON
  cat > "$workspace/transcript.jsonl" <<'JSON'
{"message":{"model":"claude-sonnet-4-6","usage":{"input_tokens":100000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":10000}}}
JSON
}

@test "AC-010a mst-pre-tool-use baseline remains deterministic and pass-through for read payload" {
  left_ws="$(new_workspace pre-left)"
  right_ws="$(new_workspace pre-right)"

  capture_hook "$left_ws" "mst-pre-tool-use.sh" '{"tool_name":"Read","tool_input":{"file_path":"README.md"}}' "$BATS_TEST_TMPDIR/pre-left.stdout" "$BATS_TEST_TMPDIR/pre-left.stderr" "$BATS_TEST_TMPDIR/pre-left.status"
  capture_hook "$right_ws" "mst-pre-tool-use.sh" '{"tool_name":"Read","tool_input":{"file_path":"README.md"}}' "$BATS_TEST_TMPDIR/pre-right.stdout" "$BATS_TEST_TMPDIR/pre-right.stderr" "$BATS_TEST_TMPDIR/pre-right.status"

  assert_same_capture "$BATS_TEST_TMPDIR/pre-left" "$BATS_TEST_TMPDIR/pre-right"
  [ "$(cat "$BATS_TEST_TMPDIR/pre-left.status")" = "0" ]
}

@test "AC-T04-001/002 hooks sync installs lib and copied pre-tool hook handles read payload" {
  workspace="$(new_workspace t04-sync)"

  (
    cd "$workspace" || exit 1
    HOME="$workspace/home" python3 "$REPO_ROOT/scripts/mst.py" hooks sync --silent
  )

  [ -f "$workspace/.claude/hooks/lib/pre_tool_use_fast.py" ]
  python3 - "$REPO_ROOT/hooks/lib" "$workspace/.claude/hooks/lib" <<'PY'
import hashlib
import sys
from pathlib import Path

source = Path(sys.argv[1])
installed = Path(sys.argv[2])

def hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }

assert hashes(source) == hashes(installed)
PY

  set +e
  (
    cd "$workspace" || exit 1
    HOME="$workspace/home" bash "$workspace/.claude/hooks/mst-pre-tool-use.sh" < "$REPO_ROOT/tests/req-729/fixtures/req-729-t04/normal-read.json" >"$BATS_TEST_TMPDIR/t04-sync.stdout" 2>"$BATS_TEST_TMPDIR/t04-sync.stderr"
  )
  status="$?"
  set -e

  [ "$status" -eq 0 ]
  ! grep -F "can't open file" "$BATS_TEST_TMPDIR/t04-sync.stderr"
}

@test "AC-T06-002 mst-pre-tool-use baseline preserves session-id mismatch stderr for non-Skill fast path" {
  master_hook="$(prepare_master_baseline_hook)"
  master_ws="$(new_workspace mismatch-master)"
  head_ws="$(new_workspace mismatch-head)"
  stdin_sid="11111111-1111-4111-8111-111111111111"
  snapshot_sid="22222222-2222-4222-8222-222222222222"
  durable_sid="33333333-3333-4333-8333-333333333333"
  expected="[session-id mismatch] stdin=$stdin_sid snapshot=$snapshot_sid durable=$durable_sid hook=mst-pre-tool-use"
  payload='{"session_id":"'"$stdin_sid"'","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  prepare_session_mismatch_workspace "$master_ws" "$stdin_sid" "$snapshot_sid" "$durable_sid"
  prepare_session_mismatch_workspace "$head_ws" "$stdin_sid" "$snapshot_sid" "$durable_sid"

  capture_hook_file "$master_ws" "$master_hook" "$payload" "$BATS_TEST_TMPDIR/mismatch-master.stdout" "$BATS_TEST_TMPDIR/mismatch-master.stderr" "$BATS_TEST_TMPDIR/mismatch-master.status"
  capture_hook "$head_ws" "mst-pre-tool-use.sh" "$payload" "$BATS_TEST_TMPDIR/mismatch-head.stdout" "$BATS_TEST_TMPDIR/mismatch-head.stderr" "$BATS_TEST_TMPDIR/mismatch-head.status"

  assert_same_capture "$BATS_TEST_TMPDIR/mismatch-master" "$BATS_TEST_TMPDIR/mismatch-head"
  [ "$(cat "$BATS_TEST_TMPDIR/mismatch-head.status")" = "0" ]
  [ "$(cat "$BATS_TEST_TMPDIR/mismatch-head.stderr")" = "$expected" ]
}

@test "AC-T08-001 synced mst-pre-tool-use preserves session-id mismatch stderr for non-Skill fast path" {
  master_hook="$(prepare_master_baseline_hook)"
  master_ws="$(new_workspace synced-mismatch-master)"
  head_ws="$(new_workspace synced-mismatch-head)"
  stdin_sid="11111111-1111-4111-8111-111111111111"
  snapshot_sid="22222222-2222-4222-8222-222222222222"
  durable_sid="33333333-3333-4333-8333-333333333333"
  expected="[session-id mismatch] stdin=$stdin_sid snapshot=$snapshot_sid durable=$durable_sid hook=mst-pre-tool-use"
  payload='{"session_id":"'"$stdin_sid"'","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  prepare_session_mismatch_workspace "$master_ws" "$stdin_sid" "$snapshot_sid" "$durable_sid"
  prepare_session_mismatch_workspace "$head_ws" "$stdin_sid" "$snapshot_sid" "$durable_sid"
  ln -s "$REPO_ROOT/scripts" "$head_ws/scripts"

  (
    cd "$head_ws" || exit 1
    HOME="$head_ws/home" python3 "$REPO_ROOT/scripts/mst.py" hooks sync --silent
  )

  capture_hook_file "$master_ws" "$master_hook" "$payload" "$BATS_TEST_TMPDIR/synced-mismatch-master.stdout" "$BATS_TEST_TMPDIR/synced-mismatch-master.stderr" "$BATS_TEST_TMPDIR/synced-mismatch-master.status"
  capture_hook_file "$head_ws" "$head_ws/.claude/hooks/mst-pre-tool-use.sh" "$payload" "$BATS_TEST_TMPDIR/synced-mismatch-head.stdout" "$BATS_TEST_TMPDIR/synced-mismatch-head.stderr" "$BATS_TEST_TMPDIR/synced-mismatch-head.status"

  assert_same_capture "$BATS_TEST_TMPDIR/synced-mismatch-master" "$BATS_TEST_TMPDIR/synced-mismatch-head"
  [ "$(cat "$BATS_TEST_TMPDIR/synced-mismatch-head.status")" = "0" ]
  [ "$(cat "$BATS_TEST_TMPDIR/synced-mismatch-head.stderr")" = "$expected" ]
  ! grep -F "helper_failed" "$BATS_TEST_TMPDIR/synced-mismatch-head.stderr"
}

@test "AC-010a mst-session-init baseline creates bridge and history sentinels without output drift" {
  left_ws="$(new_workspace init-left)"
  right_ws="$(new_workspace init-right)"
  payload='{"session_id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}'

  capture_hook "$left_ws" "mst-session-init.sh" "$payload" "$BATS_TEST_TMPDIR/init-left.stdout" "$BATS_TEST_TMPDIR/init-left.stderr" "$BATS_TEST_TMPDIR/init-left.status"
  capture_hook "$right_ws" "mst-session-init.sh" "$payload" "$BATS_TEST_TMPDIR/init-right.stdout" "$BATS_TEST_TMPDIR/init-right.stderr" "$BATS_TEST_TMPDIR/init-right.status"

  assert_same_capture "$BATS_TEST_TMPDIR/init-left" "$BATS_TEST_TMPDIR/init-right"
  [ "$(cat "$BATS_TEST_TMPDIR/init-left.status")" = "0" ]
  [ -f "$left_ws/.gran-maestro/tmp/claude-session-"*".id" ]
  [ -f "$left_ws/.gran-maestro/sessions/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee/history.head" ]
  [ -f "$left_ws/home/.claude/gran-maestro-policy/ledger-heads/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee.head" ]
}

@test "AC-010a mst-stop-hook baseline pass-through for recursive stop hook remains stable" {
  left_ws="$(new_workspace stop-left)"
  right_ws="$(new_workspace stop-right)"
  payload='{"stop_hook_active":true}'

  capture_hook "$left_ws" "mst-stop-hook.sh" "$payload" "$BATS_TEST_TMPDIR/stop-left.stdout" "$BATS_TEST_TMPDIR/stop-left.stderr" "$BATS_TEST_TMPDIR/stop-left.status"
  capture_hook "$right_ws" "mst-stop-hook.sh" "$payload" "$BATS_TEST_TMPDIR/stop-right.stdout" "$BATS_TEST_TMPDIR/stop-right.stderr" "$BATS_TEST_TMPDIR/stop-right.status"

  cmp -s "$BATS_TEST_TMPDIR/stop-left.status" "$BATS_TEST_TMPDIR/stop-right.status"
  cmp -s "$BATS_TEST_TMPDIR/stop-left.stdout" "$BATS_TEST_TMPDIR/stop-right.stdout"
  sed -E 's#"lock_path": "[^"]+"#"lock_path": "<workspace>"#' "$BATS_TEST_TMPDIR/stop-left.stderr" > "$BATS_TEST_TMPDIR/stop-left.stderr.norm"
  sed -E 's#"lock_path": "[^"]+"#"lock_path": "<workspace>"#' "$BATS_TEST_TMPDIR/stop-right.stderr" > "$BATS_TEST_TMPDIR/stop-right.stderr.norm"
  cmp -s "$BATS_TEST_TMPDIR/stop-left.stderr.norm" "$BATS_TEST_TMPDIR/stop-right.stderr.norm"
  [ "$(cat "$BATS_TEST_TMPDIR/stop-left.status")" = "0" ]
  [ "$(jq -r '.decision' "$BATS_TEST_TMPDIR/stop-left.stdout")" = "approve" ]
  [ "$(jq -r '.reason' "$BATS_TEST_TMPDIR/stop-left.stdout")" = "stop_hook_active_true snapshot_present=false" ]
  grep -F '[stop-hook] anchor=docs/FLOW-CONSTRAINTS.md#layer-1-mode-gate' "$BATS_TEST_TMPDIR/stop-left.stderr" >/dev/null
}

@test "AC-010a mst-auto-chain-context baseline emits stable context reminder when chain is active" {
  left_ws="$(new_workspace chain-left)"
  right_ws="$(new_workspace chain-right)"
  prepare_auto_chain_workspace "$left_ws"
  prepare_auto_chain_workspace "$right_ws"
  payload_left='{"transcript_path":"'"$left_ws"'/transcript.jsonl"}'
  payload_right='{"transcript_path":"'"$right_ws"'/transcript.jsonl"}'

  MST_STATE_PPID=424242 capture_hook "$left_ws" "mst-auto-chain-context.sh" "$payload_left" "$BATS_TEST_TMPDIR/chain-left.stdout" "$BATS_TEST_TMPDIR/chain-left.stderr" "$BATS_TEST_TMPDIR/chain-left.status"
  MST_STATE_PPID=424242 capture_hook "$right_ws" "mst-auto-chain-context.sh" "$payload_right" "$BATS_TEST_TMPDIR/chain-right.stdout" "$BATS_TEST_TMPDIR/chain-right.stderr" "$BATS_TEST_TMPDIR/chain-right.status"

  assert_same_capture "$BATS_TEST_TMPDIR/chain-left" "$BATS_TEST_TMPDIR/chain-right"
  [ "$(cat "$BATS_TEST_TMPDIR/chain-left.status")" = "0" ]
  grep -F "[자동 연쇄 컨텍스트]" "$BATS_TEST_TMPDIR/chain-left.stdout"
  grep -F "65.0% (130000 / 200000 tokens)" "$BATS_TEST_TMPDIR/chain-left.stdout"
}
