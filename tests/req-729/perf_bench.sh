#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ITERATIONS="${REQ729_PERF_ITERATIONS:-100}"
RULES="${REQ729_PERF_RULES:-50}"
HISTORY_ROWS="${REQ729_PERF_HISTORY_ROWS:-1000}"
AVG_THRESHOLD_MS="${REQ729_PERF_AVG_THRESHOLD_MS:-50}"
P95_THRESHOLD_MS="${REQ729_PERF_P95_THRESHOLD_MS:-100}"

TMP_ROOT="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

PROJECT="$TMP_ROOT/project"
HOME_DIR="$TMP_ROOT/home"
SID="ffffffff-ffff-4fff-8fff-ffffffffffff"
mkdir -p "$PROJECT/.gran-maestro/tmp" "$PROJECT/.gran-maestro/logs" "$HOME_DIR"
printf 'gitdir: .\n' > "$PROJECT/.git"

(
  cd "$PROJECT"
  HOME="$HOME_DIR" python3 "$REPO_ROOT/scripts/mst.py" policy init >/dev/null
)

python3 - "$PROJECT" "$HOME_DIR" "$RULES" "$HISTORY_ROWS" "$SID" <<'PY'
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project = Path(sys.argv[1])
home = Path(sys.argv[2])
rule_count = int(sys.argv[3])
history_rows = int(sys.argv[4])
sid = sys.argv[5]
project_key = hashlib.sha256(os.path.realpath(project).encode()).hexdigest()[:16]
policy_dir = home / ".claude" / "gran-maestro-policy" / "projects" / project_key
rules_dir = policy_dir / "rules.d"
rules_dir.mkdir(parents=True, exist_ok=True)

for index in range(rule_count):
    payload = {
        "version": 1,
        "rules": [
            {
                "id": f"GM-PERF-{index:02d}",
                "severity": "warn",
                "trigger": {
                    "tool": "Bash",
                    "args": {"command": {"contains": f"__never_match_perf_{index}__"}},
                },
                "action": {"decision": "warn", "message": "perf no-op"},
            }
        ],
    }
    path = rules_dir / f"perf-{index:02d}.json"
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)

rules = []
for rule_file in sorted(rules_dir.glob("*.json")):
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

zero = "0" * 64
session_dir = project / ".gran-maestro" / "sessions" / sid
heads_dir = home / ".claude" / "gran-maestro-policy" / "ledger-heads"
session_dir.mkdir(parents=True, exist_ok=True)
heads_dir.mkdir(parents=True, exist_ok=True)
history = session_dir / "history.ndjson"
prev = zero
with history.open("w", encoding="utf-8") as handle:
    for seq in range(1, history_rows + 1):
        event = {
            "args_sha256": hashlib.sha256(f"perf-seed-{seq}".encode()).hexdigest(),
            "timestamp": f"2026-04-28T01:{(seq // 60) % 60:02d}:{seq % 60:02d}Z",
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

RESULT_JSON="$(
  python3 - "$REPO_ROOT" "$PROJECT" "$HOME_DIR" "$SID" "$ITERATIONS" <<'PY'
import json
import os
import statistics
import subprocess
import sys
import time

repo = sys.argv[1]
project = sys.argv[2]
home = sys.argv[3]
sid = sys.argv[4]
iterations = int(sys.argv[5])
hook = os.path.join(repo, "hooks", "mst-pre-tool-use.sh")
env = {**os.environ, "HOME": home}
durations = []

for index in range(iterations):
    payload = {
        "session_id": sid,
        "tool_name": "Bash",
        "tool_input": {"command": f"echo perf-{index}"},
    }
    start = time.perf_counter_ns()
    result = subprocess.run(
        ["bash", hook],
        cwd=project,
        env=env,
        input=json.dumps(payload, separators=(",", ":")),
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    durations.append(elapsed_ms)

durations_sorted = sorted(durations)
p95_index = max(0, int((len(durations_sorted) * 0.95) + 0.999999) - 1)
print(
    json.dumps(
        {
            "avg": statistics.fmean(durations),
            "p95": durations_sorted[p95_index],
            "min": durations_sorted[0],
            "max": durations_sorted[-1],
        },
        separators=(",", ":"),
    )
)
PY
)"

AVG_MS="$(python3 - "$RESULT_JSON" <<'PY'
import json
import sys
print(f"{json.loads(sys.argv[1])['avg']:.2f}")
PY
)"
P95_MS="$(python3 - "$RESULT_JSON" <<'PY'
import json
import sys
print(f"{json.loads(sys.argv[1])['p95']:.2f}")
PY
)"

echo "=== REQ-729 PreToolUse hook performance ==="
printf 'Iterations: %s\n' "$ITERATIONS"
printf 'Rules:      %s\n' "$RULES"
printf 'History:    %s rows\n' "$HISTORY_ROWS"
printf 'Avg:        %sms\n' "$AVG_MS"
printf 'p95:        %sms\n' "$P95_MS"
printf 'Threshold:  avg<%sms, p95<%sms\n' "$AVG_THRESHOLD_MS" "$P95_THRESHOLD_MS"

if python3 - "$AVG_MS" "$P95_MS" "$AVG_THRESHOLD_MS" "$P95_THRESHOLD_MS" <<'PY'
import sys
avg, p95, avg_threshold, p95_threshold = map(float, sys.argv[1:])
raise SystemExit(0 if avg < avg_threshold and p95 < p95_threshold else 1)
PY
then
  echo "Result:     PASS"
  exit 0
fi

echo "Result:     FAIL"
exit 1
