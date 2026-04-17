#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN_ROOT="$REPO_ROOT"
MST_SCRIPT="$PLUGIN_ROOT/scripts/mst.py"
SESSION_INIT_SCRIPT="$REPO_ROOT/hooks/mst-session-init.sh"

TMP_ROOT="$(mktemp -d)"
MAIN_PROJECT="$TMP_ROOT/project-main"
HOOK_PROJECT="$TMP_ROOT/project-hook"

cleanup() {
  rm -rf "$TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

wait_for_file() {
  local file="$1"
  local attempts="${2:-30}"
  local delay="${3:-0.1}"
  local i
  for i in $(seq 1 "$attempts"); do
    if [ -s "$file" ]; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

setup_main_fixture() {
  mkdir -p "$MAIN_PROJECT/.gran-maestro"
  python3 - "$MAIN_PROJECT" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

project = Path(sys.argv[1])
gm = project / ".gran-maestro"
(gm / "requests").mkdir(parents=True, exist_ok=True)
(gm / "plans").mkdir(parents=True, exist_ok=True)

now = datetime.now(timezone.utc).replace(microsecond=0)

def iso_days_ago(days: int) -> str:
    return (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")

def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

write_json(
    gm / "config.json",
    {
        "gardening": {
            "auto_archive": {
                "enabled": True,
                "dry_run": False,
                "thresholds": {
                    "req_stale_days": 14,
                    "plan_stale_days": 30,
                    "plan_active_stale_days": 14,
                },
            }
        }
    },
)

write_json(
    gm / "requests" / "REQ-STALE-1" / "request.json",
    {
        "id": "REQ-STALE-1",
        "title": "stale request 1",
        "status": "phase1_analysis",
        "updated_at": iso_days_ago(20),
    },
)
write_json(
    gm / "requests" / "REQ-STALE-2" / "request.json",
    {
        "id": "REQ-STALE-2",
        "title": "stale request exempt",
        "status": "spec_ready",
        "gardening_exempt": True,
        "updated_at": iso_days_ago(20),
    },
)
write_json(
    gm / "requests" / "REQ-ACTIVE-1" / "request.json",
    {
        "id": "REQ-ACTIVE-1",
        "title": "active request",
        "status": "phase1_analysis",
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    },
)
write_json(
    gm / "requests" / "REQ-STALE-2-OLD" / "request.json",
    {
        "id": "REQ-STALE-2-OLD",
        "title": "already cancelled request",
        "status": "cancelled",
        "updated_at": iso_days_ago(45),
    },
)
write_json(
    gm / "plans" / "PLN-DEAD-1" / "plan.json",
    {
        "id": "PLN-DEAD-1",
        "title": "dead linked plan",
        "status": "active",
        "linked_requests": ["REQ-STALE-1", "REQ-STALE-2-OLD"],
        "updated_at": now.isoformat().replace("+00:00", "Z"),
    },
)
PY
}

verify_after_apply() {
  python3 - "$MAIN_PROJECT" <<'PY'
import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
gm = project / ".gran-maestro"

def read_request(req_id: str) -> dict:
    return json.loads((gm / "requests" / req_id / "request.json").read_text(encoding="utf-8"))

def read_plan(plan_id: str) -> dict:
    return json.loads((gm / "plans" / plan_id / "plan.json").read_text(encoding="utf-8"))

stale1 = read_request("REQ-STALE-1")
assert stale1["status"] == "cancelled", stale1

stale2 = read_request("REQ-STALE-2")
assert stale2["status"] == "spec_ready", stale2

active1 = read_request("REQ-ACTIVE-1")
assert active1["status"] == "phase1_analysis", active1

plan = read_plan("PLN-DEAD-1")
assert plan["status"] == "cancelled", plan

log_path = gm / "gardening" / "auto-archive.ndjson"
assert log_path.exists(), "missing auto-archive.ndjson"
rows = [
    json.loads(line)
    for line in log_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert any(row.get("action") == "cancel" and row.get("id") == "REQ-STALE-1" for row in rows), rows
assert any(row.get("action") == "skipped" and row.get("id") == "REQ-STALE-2" for row in rows), rows
PY
}

verify_after_restore() {
  python3 - "$MAIN_PROJECT" <<'PY'
import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
gm = project / ".gran-maestro"
req = json.loads((gm / "requests" / "REQ-STALE-1" / "request.json").read_text(encoding="utf-8"))
assert req["status"] == "phase1_analysis", req

rows = [
    json.loads(line)
    for line in (gm / "gardening" / "auto-archive.ndjson").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert any(row.get("action") == "restore" and row.get("id") == "REQ-STALE-1" for row in rows), rows
PY
}

setup_hook_fixture() {
  mkdir -p "$HOOK_PROJECT/.gran-maestro"
  python3 - "$HOOK_PROJECT" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

project = Path(sys.argv[1])
gm = project / ".gran-maestro"
(gm / "requests" / "REQ-HOOK-STALE").mkdir(parents=True, exist_ok=True)
(gm / "tmp").mkdir(parents=True, exist_ok=True)

now = datetime.now(timezone.utc).replace(microsecond=0)
stale = (now - timedelta(days=20)).isoformat().replace("+00:00", "Z")

def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

resolved = {
    "gardening": {
        "auto_archive": {
            "enabled": True,
            "dry_run": False,
            "session_init_guard_seconds": 0,
            "thresholds": {
                "req_stale_days": 14,
                "plan_stale_days": 30,
                "plan_active_stale_days": 14,
            },
        }
    }
}
write_json(gm / "config.resolved.json", resolved)
write_json(gm / "config.json", resolved)
write_json(
    gm / "requests" / "REQ-HOOK-STALE" / "request.json",
    {
        "id": "REQ-HOOK-STALE",
        "title": "hook stale request",
        "status": "phase1_analysis",
        "updated_at": stale,
    },
)
PY

  printf '%s\n' "1" > "$HOOK_PROJECT/.gran-maestro/tmp/gardening-last-run"
}

verify_hook_results() {
  local stamp_file="$HOOK_PROJECT/.gran-maestro/tmp/gardening-last-run"
  local log_file="$HOOK_PROJECT/.gran-maestro/gardening/auto-archive.ndjson"

  [ -f "$stamp_file" ] || fail "session-init did not write gardening stamp"
  local stamp_value
  stamp_value="$(cat "$stamp_file" 2>/dev/null || true)"
  case "$stamp_value" in
    ''|*[!0-9]*) fail "gardening stamp is not numeric: $stamp_value" ;;
  esac
  [ "$stamp_value" -gt 1 ] || fail "gardening stamp was not refreshed"

  sleep 1
  wait_for_file "$log_file" 50 0.1 || fail "session-init did not trigger background auto-archive"

  python3 - "$HOOK_PROJECT" <<'PY'
import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
gm = project / ".gran-maestro"
req = json.loads((gm / "requests" / "REQ-HOOK-STALE" / "request.json").read_text(encoding="utf-8"))
assert req["status"] == "cancelled", req

rows = [
    json.loads(line)
    for line in (gm / "gardening" / "auto-archive.ndjson").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert any(row.get("action") == "cancel" and row.get("id") == "REQ-HOOK-STALE" for row in rows), rows
PY
}

run_regression_suite() {
  (
    cd "$REPO_ROOT"
    bash tests/test-continuation-guard.sh
    bash tests/test-hooks-sync.sh
  )

  if python3 -m pytest --version >/dev/null 2>&1; then
    (
      cd "$REPO_ROOT"
      python3 -m pytest -q tests/test_agile_pause_guard.py tests/test_stop_hook_patterns.py
      python3 -m pytest -q tests/test_gardening_auto_archive.py tests/test_gardening_config_schema.py
    )
  else
    printf 'WARN: pytest not installed; skipping pytest regression steps.\n' >&2
  fi

  (
    cd "$REPO_ROOT"
    bash tests/test-session-init-gardening.sh
  )
}

echo "=== PLN-475 integration: setup fixture ==="
setup_main_fixture

echo "=== Step 2: auto-archive apply ==="
(
  cd "$MAIN_PROJECT"
  python3 "$MST_SCRIPT" gardening auto-archive --apply
)
verify_after_apply

echo "=== Step 3: restore roundtrip ==="
(
  cd "$MAIN_PROJECT"
  python3 "$MST_SCRIPT" gardening restore --id REQ-STALE-1
)
verify_after_restore

echo "=== Step 4: session-init hook integration ==="
setup_hook_fixture
(
  cd "$HOOK_PROJECT"
  PLUGIN_ROOT="$PLUGIN_ROOT" bash "$SESSION_INIT_SCRIPT"
)
verify_hook_results

echo "=== Step 5: regression suite ==="
run_regression_suite

echo "PLN-475 integration PASS"
exit 0
