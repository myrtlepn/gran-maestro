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

run_mst() {
  (cd "$WORKSPACE" && HOME="$HOME_DIR" python3 "$REPO_ROOT/scripts/mst.py" "$@")
}

run_pre_tool_hook() {
  local payload="$1"
  (cd "$WORKSPACE" && HOME="$HOME_DIR" bash "$REPO_ROOT/hooks/mst-pre-tool-use.sh" <<<"$payload")
}

run_session_init_hook() {
  local payload="$1"
  (cd "$WORKSPACE" && HOME="$HOME_DIR" bash "$REPO_ROOT/hooks/mst-session-init.sh" <<<"$payload")
}

history_file() {
  printf '%s/.gran-maestro/sessions/%s/history.ndjson\n' "$WORKSPACE" "$1"
}

head_file() {
  printf '%s/.gran-maestro/sessions/%s/history.head\n' "$WORKSPACE" "$1"
}

mirror_head_file() {
  printf '%s/.claude/gran-maestro-policy/ledger-heads/%s.head\n' "$HOME_DIR" "$1"
}

policy_project_dir() {
  python3 - "$WORKSPACE" "$HOME_DIR" <<'PY'
import hashlib
import os
import sys

project = os.path.realpath(sys.argv[1])
home = sys.argv[2]
key = hashlib.sha256(project.encode()).hexdigest()[:16]
print(os.path.join(home, ".claude", "gran-maestro-policy", "projects", key))
PY
}

rewrite_manifest() {
  local policy_dir="$1"
  python3 - "$policy_dir" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

policy_dir = Path(sys.argv[1])
rules = []
for rule_file in sorted((policy_dir / "rules.d").glob("*.json")):
    rules.append(
        {
            "path": rule_file.relative_to(policy_dir).as_posix(),
            "sha256": hashlib.sha256(rule_file.read_bytes()).hexdigest(),
            "last_modified": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )
manifest = policy_dir / "manifest.json"
manifest.write_text(json.dumps({"version": 1, "rules": rules}, indent=2) + "\n", encoding="utf-8")
os.chmod(manifest, 0o600)
PY
}

write_rule_file() {
  local policy_dir="$1"
  local file_name="$2"
  local json_payload="$3"
  printf '%s\n' "$json_payload" > "$policy_dir/rules.d/$file_name"
  chmod 600 "$policy_dir/rules.d/$file_name"
  rewrite_manifest "$policy_dir"
}

seed_history() {
  local sid="$1"
  local rows="$2"
  python3 - "$WORKSPACE" "$HOME_DIR" "$sid" "$rows" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
home = Path(sys.argv[2])
sid = sys.argv[3]
rows = int(sys.argv[4])
zero = "0" * 64
session_dir = project / ".gran-maestro" / "sessions" / sid
heads_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
session_dir.mkdir(parents=True, exist_ok=True)
heads_dir.mkdir(parents=True, exist_ok=True)
history = session_dir / "history.ndjson"
prev = zero
with history.open("w", encoding="utf-8") as handle:
    for seq in range(1, rows + 1):
        event = {
            "args_sha256": hashlib.sha256(f"seed-{seq}".encode()).hexdigest(),
            "timestamp": f"2026-04-28T00:{seq // 60:02d}:{seq % 60:02d}Z",
            "tool": "Bash",
            "type": "tool_call",
        }
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
        event_hash = hashlib.sha256((prev + "\n" + canonical).encode()).hexdigest()
        row = {
            "args_sha256": event["args_sha256"],
            "event": event,
            "event_hash": event_hash,
            "prev_hash": prev,
            "seq": seq,
            "timestamp": event["timestamp"],
            "tool": event["tool"],
        }
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        prev = event_hash
(session_dir / "history.head").write_text(prev + "\n", encoding="utf-8")
(heads_dir / f"{sid}.head").write_text(prev + "\n", encoding="utf-8")
PY
}

verify_chain() {
  local sid="$1"
  python3 - "$(history_file "$sid")" "$(head_file "$sid")" "$(mirror_head_file "$sid")" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

history = Path(sys.argv[1])
local_head = Path(sys.argv[2])
mirror_head = Path(sys.argv[3])
prev = "0" * 64
seq = 1
last_hash = prev
for line_no, line in enumerate(history.read_text(encoding="utf-8").splitlines(), 1):
    row = json.loads(line)
    assert row["seq"] == seq, f"seq line={line_no}"
    assert row["prev_hash"] == prev, f"prev_hash line={line_no}"
    canonical = json.dumps(row["event"], sort_keys=True, separators=(",", ":"))
    computed = hashlib.sha256((prev + "\n" + canonical).encode()).hexdigest()
    assert row["event_hash"] == computed, f"event_hash line={line_no}"
    prev = computed
    last_hash = computed
    seq += 1
assert local_head.read_text(encoding="utf-8").strip() == last_hash
assert mirror_head.read_text(encoding="utf-8").strip() == last_hash
PY
}

setup_policy_dir() {
  run_mst policy init >/dev/null
}

@test "AC-T03-001 normal tool flow: policy rule match, history append, and 1000-row chain verification" {
  cd "$WORKSPACE"
  setup_policy_dir
  policy_dir="$(policy_project_dir)"
  write_rule_file "$policy_dir" "t03-warn.json" '{
    "version": 1,
    "rules": [
      {
        "id": "GM-T03-WARN",
        "severity": "warn",
        "trigger": {"tool": "Bash", "args": {"command": {"contains": "t03-normal"}}},
        "action": {"decision": "warn", "message": "t03 normal rule matched"}
      }
    ]
  }'
  sid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  seed_history "$sid" 1000

  run run_pre_tool_hook '{"session_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","tool_name":"Bash","tool_input":{"command":"echo t03-normal"}}'

  [ "$status" -eq 0 ]
  [[ "$output" == *"GM-T03-WARN"* ]]
  # PLN-560 PAC-7 intentionally records WARN as warn_auto_allow and still appends
  # the normal tool_call event, so the 1000-row fixture grows by two rows.
  [ "$(wc -l < "$(history_file "$sid")" | tr -d ' ')" = "1002" ]
  [ "$(jq -r '.seq' "$(history_file "$sid")" | tail -1)" = "1002" ]
  [ "$(jq -r 'select(.event.type=="tool_call") | .event.tool' "$(history_file "$sid")" | tail -1)" = "Bash" ]
  verify_chain "$sid"
}

@test "AC-T03-002 hardcoded core adversarial corpus blocks five metadata bypass attempts" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

  attempts=(
    '{"session_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","tool_name":"Write","tool_input":{"file_path":"~/.claude/gran-maestro-policy/projects/demo/rules.d/x.json","content":"{}"}}'
    '{"session_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","tool_name":"Write","tool_input":{"file_path":"'"$WORKSPACE"'/.gran-maestro/sessions/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/history.ndjson","content":"tamper"}}'
    '{"session_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","tool_name":"Bash","tool_input":{"command":"mkdir -p .gran-maestro/sessions/forged-session"}}'
    '{"session_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","tool_name":"Write","tool_input":{"file_path":"~/.claude/gran-maestro-policy/projects/demo/notes.txt","content":"tamper"}}'
    '{"session_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","tool_name":"Write","tool_input":{"file_path":"~/.claude/gran-maestro-policy/ledger-heads/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb.head","content":"0"}}'
  )

  for payload in "${attempts[@]}"; do
    run run_pre_tool_hook "$payload"
    [ "$status" -eq 2 ]
    [[ "$output" == *"[core-block]"* ]]
  done

  # RV-001 F-08: T10이 hardcoded_core_check return path를 통일해 모든 core BLOCK이 ledger core_block event를 append. PLN-560 D5 ledger 무결성 + REQ-731 statusline 카운터 호환을 위한 의도된 변경.
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 5 ]
}

@test "AC-T03-002 manifest mismatch and history tampering both fail closed" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
  run_pre_tool_hook '{"session_id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","tool_name":"Bash","tool_input":{"command":"echo seed"}}'
  policy_dir="$(policy_project_dir)"
  printf 'tampered\n' >> "$policy_dir/rules.d/core-bypass.json"
  tmp_history="$BATS_TEST_TMPDIR/tampered-history.ndjson"
  jq -c '.event.tool = "Tampered"' "$(history_file "$sid")" > "$tmp_history"
  mv "$tmp_history" "$(history_file "$sid")"

  run run_pre_tool_hook '{"session_id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"manifest_sha256_mismatch"* ]]

  rewrite_manifest "$policy_dir"
  run run_pre_tool_hook '{"session_id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"history ledger mismatch"* ]]
}

@test "AC-T04-003/004 bash redirects into ledger sentinel files trigger core BLOCK" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

  commands=(
    "echo bad > .gran-maestro/sessions/$sid/history.head"
    "echo bad > .gran-maestro/sessions/$sid/history.verify"
    "echo bad > $HOME_DIR/.claude/gran-maestro-policy/ledger-heads/$sid.head"
    "echo bad > $HOME_DIR/.claude/gran-maestro-policy/ledger-heads/$sid.lock"
  )

  for command in "${commands[@]}"; do
    run run_pre_tool_hook '{"session_id":"'"$sid"'","tool_name":"Bash","tool_input":{"command":"'"$command"'"}}'
    [ "$status" -eq 2 ]
    [[ "$output" == *"META-BYPASS-LEDGER-SENTINEL"* ]]
  done

  # RV-001 F-08: T10이 hardcoded_core_check return path를 통일해 모든 core BLOCK이 ledger core_block event를 append. PLN-560 D5 ledger 무결성 + REQ-731 statusline 카운터 호환을 위한 의도된 변경.
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 4 ]
}

@test "AC-T05-001 cache bypass attempt fails closed on manifest sha256 mismatch" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  policy_dir="$(policy_project_dir)"
  rule_file="$policy_dir/rules.d/core-bypass.json"

  run run_pre_tool_hook '{"session_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","tool_name":"Read","tool_input":{"file_path":"README.md"}}'
  [ "$status" -eq 0 ]
  [ -f "$policy_dir/.rule-engine-cache.json" ]

  python3 - "$rule_file" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
stat = path.stat()
data = path.read_bytes()
modified = data.replace(b"core", b"CORE", 1)
assert modified != data
assert len(modified) == stat.st_size
with path.open("r+b") as handle:
    handle.seek(0)
    handle.write(modified)
    handle.truncate()
os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
assert path.stat().st_size == stat.st_size
assert path.stat().st_mtime_ns == stat.st_mtime_ns
assert path.stat().st_ino == stat.st_ino
PY

  run run_pre_tool_hook '{"session_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"manifest_sha256_mismatch"* ]]
}

@test "AC-T05-002 unknown predicate-only rule fails closed" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="ffffffff-ffff-4fff-8fff-ffffffffffff"
  policy_dir="$(policy_project_dir)"
  write_rule_file "$policy_dir" "t05-unknown-predicate.json" '{
    "version": 1,
    "rules": [
      {
        "id": "GM-T05-UNKNOWN",
        "severity": "block",
        "trigger": {"tool": "Read"},
        "condition": {"predicate": "unknown_xyz"},
        "action": {"decision": "block", "message": "unknown predicate must fail closed"}
      }
    ]
  }'

  run run_pre_tool_hook '{"session_id":"ffffffff-ffff-4fff-8fff-ffffffffffff","tool_name":"Read","tool_input":{"file_path":"README.md"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown_predicate"* ]]
  [[ "$output" == *"unknown_xyz"* ]]
}

@test "AC-T03-002 predicate registry corpus covers five allowed predicates" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="dddddddd-dddd-4ddd-8ddd-dddddddddddd"
  source "$REPO_ROOT/hooks/lib/history.bash"
  mst_history_append_event "$WORKSPACE" "$sid" '{"type":"skill_enter","skill":"mst:plan","timestamp":"2026-04-28T00:00:00Z"}'
  policy_dir="$(policy_project_dir)"
  write_rule_file "$policy_dir" "t03-predicates.json" '{
    "version": 1,
    "rules": [
      {
        "id": "GM-T03-TOOL-MATCH",
        "severity": "block",
        "trigger": {"tool": "Bash"},
        "condition": {"all": [{"predicate": "tool_match", "name": "Bash"}, {"predicate": "arg_pattern", "key": "command", "op": "contains", "value": "predicate-tool"}]},
        "action": {"decision": "block", "message": "tool_match applied"}
      },
      {
        "id": "GM-T03-HISTORY-EXISTS",
        "severity": "block",
        "trigger": {"tool": "Bash", "args": {"command": {"contains": "predicate-history"}}},
        "condition": {"all": [{"predicate": "history_exists", "type_filter": {"type": "skill_enter", "skill": "mst:plan"}}]},
        "action": {"decision": "block", "message": "history_exists applied"}
      },
      {
        "id": "GM-T03-HISTORY-NOT-AFTER",
        "severity": "block",
        "trigger": {"tool": "Bash", "args": {"command": {"contains": "predicate-not-after"}}},
        "condition": {"all": [{"predicate": "history_not_exists_after", "anchor": {"type": "skill_enter", "skill": "mst:plan"}, "target": {"type": "skill_exit", "skill": "mst:plan"}}]},
        "action": {"decision": "block", "message": "history_not_exists_after applied"}
      },
      {
        "id": "GM-T03-PATH-PROTECTED",
        "severity": "block",
        "trigger": {"tool": "Read"},
        "condition": {"all": [{"predicate": "path_protected", "path_glob": "*/protected.txt"}]},
        "action": {"decision": "block", "message": "path_protected applied"}
      }
    ]
  }'

  run run_pre_tool_hook '{"session_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd","tool_name":"Bash","tool_input":{"command":"echo predicate-tool"}}'
  [ "$status" -eq 2 ]
  [[ "$output" == *"tool_match applied"* ]]

  run run_pre_tool_hook '{"session_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd","tool_name":"Bash","tool_input":{"command":"echo predicate-history"}}'
  [ "$status" -eq 2 ]
  [[ "$output" == *"history_exists applied"* ]]

  run run_pre_tool_hook '{"session_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd","tool_name":"Bash","tool_input":{"command":"echo predicate-not-after"}}'
  [ "$status" -eq 2 ]
  [[ "$output" == *"history_not_exists_after applied"* ]]

  run run_pre_tool_hook '{"session_id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd","tool_name":"Read","tool_input":{"file_path":"tmp/protected.txt"}}'
  [ "$status" -eq 2 ]
  [[ "$output" == *"path_protected applied"* ]]
}

@test "AC-T07-001 hardcoded core blocks policy writes before weakening rules can allow them" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
  policy_dir="$(policy_project_dir)"
  write_rule_file "$policy_dir" "t07-weaken-core.json" '{
    "version": 1,
    "rules": [
      {
        "id": "GM-T07-WEAKEN-CORE",
        "severity": "warn",
        "trigger": {"tool": "Write"},
        "action": {"decision": "allow", "message": "weakening rule must not override core"}
      }
    ]
  }'

  run run_pre_tool_hook '{"session_id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee","tool_name":"Write","tool_input":{"file_path":"~/.claude/gran-maestro-policy/projects/demo/rules.d/x.json","content":"{}"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"[core-block]"* ]]
  [[ "$output" == *"META-BYPASS-RULE-FILE"* ]]
  [[ "$output" != *"weakening rule must not override core"* ]]
  # RV-001 F-08: T10이 hardcoded_core_check return path를 통일해 모든 core BLOCK이 ledger core_block event를 append. PLN-560 D5 ledger 무결성 + REQ-731 statusline 카운터 호환을 위한 의도된 변경.
  [ "$(jq -s '[.[].event | select(.type == "core_block")] | length' "$(history_file "$sid")")" -eq 1 ]
}

@test "AC-T07-002 unknown predicate-only rule fails closed" {
  cd "$WORKSPACE"
  setup_policy_dir
  sid="ffffffff-ffff-4fff-8fff-ffffffffffff"
  policy_dir="$(policy_project_dir)"
  write_rule_file "$policy_dir" "t07-unknown-predicate.json" '{
    "version": 1,
    "rules": [
      {
        "id": "GM-T07-UNKNOWN-PREDICATE",
        "severity": "block",
        "trigger": {"tool": "Bash", "args": {"command": {"contains": "predicate-only"}}},
        "condition": {"all": [{"predicate": "unknown_t07"}]},
        "action": {"decision": "block", "message": "unknown predicate must fail closed"}
      }
    ]
  }'

  run run_pre_tool_hook '{"session_id":"ffffffff-ffff-4fff-8fff-ffffffffffff","tool_name":"Bash","tool_input":{"command":"echo predicate-only"}}'

  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown_predicate"* ]]
  [[ "$output" == *"unknown_t07"* ]]
}

@test "AC-T07-003 mst-session-init appends skill lifecycle events" {
  cd "$WORKSPACE"
  sid="77777777-7777-4777-8777-777777777777"

  run run_session_init_hook '{"session_id":"77777777-7777-4777-8777-777777777777"}'

  [ "$status" -eq 0 ]
  [ "$(jq -s '[.[].event | select(.type == "skill_enter" and .skill == "mst:session-init")] | length' "$(history_file "$sid")")" -ge 1 ]
  [ "$(jq -s '[.[].event | select(.type == "state_change" and .state == "session_initialized")] | length' "$(history_file "$sid")")" -ge 1 ]
  [ "$(jq -s '[.[].event | select(.type == "skill_exit" and .skill == "mst:session-init")] | length' "$(history_file "$sid")")" -ge 1 ]
  verify_chain "$sid"
}
