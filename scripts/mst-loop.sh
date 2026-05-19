#!/usr/bin/env bash
# mst-loop.sh — Gran Maestro external re-entry wrapper
#
# Historically used a Claude print-mode wrapper to drain `/mst:resume`.
# This script keeps the continuation path alive until a lifecycle-safe runner replaces it.
# Exits when the queue is empty, max iterations reached, or the configured runner fails.
#
# Usage: bash scripts/mst-loop.sh [--max-iterations N] [--sleep S] [--dry-run] [--help]

set -euo pipefail

MAX_ITERATIONS=100
SLEEP_SECONDS=3
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: mst-loop.sh [--max-iterations N] [--sleep S] [--dry-run] [--help]

Options:
  --max-iterations N   Maximum loop iterations (default: 100)
  --sleep S            Seconds to sleep between iterations (default: 3)
  --dry-run            Print actions without calling claude
  --help, -h           Show this help

Description:
  Gran Maestro external re-entry wrapper. Each iteration calls
  the configured legacy headless continuation runner, which pops one action
  from .gran-maestro/pending.ndjson and executes it.
  Loop exits when:
    - mst.py queue count returns 0
    - max iterations reached
    - claude CLI fails (non-zero exit)
    - user interrupts (SIGINT)

Environment:
  PLUGIN_ROOT  Path to the gran-maestro plugin root
               (default: $HOME/.claude/plugins/marketplaces/gran-maestro)

Examples:
  bash scripts/mst-loop.sh                             # default 100 iter, 3s sleep
  bash scripts/mst-loop.sh --max-iterations 20 --sleep 5
  bash scripts/mst-loop.sh --dry-run                   # simulate without calling claude
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-iterations)
            if [[ $# -lt 2 ]]; then echo "error: --max-iterations needs a value" >&2; exit 1; fi
            MAX_ITERATIONS="$2"; shift 2 ;;
        --sleep)
            if [[ $# -lt 2 ]]; then echo "error: --sleep needs a value" >&2; exit 1; fi
            SLEEP_SECONDS="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        --help|-h)
            usage; exit 0 ;;
        *)
            echo "error: unknown option: $1" >&2
            usage
            exit 1 ;;
    esac
done

PLUGIN_ROOT="${PLUGIN_ROOT:-$HOME/.claude/plugins/marketplaces/gran-maestro}"
MST_PY="$PLUGIN_ROOT/scripts/mst.py"
PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"

if [[ ! -f "$MST_PY" ]]; then
    echo "error: mst.py not found at $MST_PY" >&2
    echo "hint: set PLUGIN_ROOT env var or check plugin installation" >&2
    exit 1
fi

MST_LOOP_CLEANUP_DONE=0
run_mstloop_cleanup() {
    if [[ "$MST_LOOP_CLEANUP_DONE" == "1" ]]; then
        return 0
    fi
    MST_LOOP_CLEANUP_DONE=1
    python3 - "$PROJECT_ROOT" "${MST_SESSION_ID:-mstloop}" "$MST_PY" <<'PY' || true
import json
import sys
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
session_id = sys.argv[2] or "mstloop"
mst_py = Path(sys.argv[3]).resolve()
repo_root = mst_py.parents[1]
sys.path.insert(0, str(repo_root))

from scripts.mst_cmds import cleanup


def _cleanup(_context):
    return {"status": "ok", "reason": "mst-loop-exit", "real_cleanup": False}


report = cleanup.run_cleanup_with_lock_report(
    project_root=project_root,
    entrypoint="mstloop",
    session_id=session_id,
    timeout_seconds=5.0,
    cleanup_fn=_cleanup,
)
print("[mst-loop] cleanup " + json.dumps(report, ensure_ascii=False, sort_keys=True), file=sys.stderr)
PY
}

on_mstloop_exit() {
    local status="$?"
    trap - EXIT
    run_mstloop_cleanup
    exit "$status"
}

trap on_mstloop_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[mst-loop] starting (max=$MAX_ITERATIONS, sleep=${SLEEP_SECONDS}s, dry_run=$DRY_RUN)"

for ((i=1; i<=MAX_ITERATIONS; i++)); do
    # queue count check — exit early if nothing to do
    COUNT=$(python3 "$MST_PY" queue count 2>/dev/null || echo "0")
    if [[ "$COUNT" == "0" ]]; then
        echo "[mst-loop] queue empty (iteration $i/$MAX_ITERATIONS) — exiting"
        break
    fi

    echo "[mst-loop] iteration $i/$MAX_ITERATIONS — queued=$COUNT"

    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[mst-loop] would run: legacy headless continuation runner for /mst:resume"
    else
        if ! claude --dangerously-skip-permissions -p "/mst:resume"; then
            echo "[mst-loop] claude failed at iteration $i — exiting" >&2
            exit 1
        fi
    fi

    # Inter-iteration sleep (skip on last iteration)
    if [[ $i -lt $MAX_ITERATIONS ]]; then
        sleep "$SLEEP_SECONDS"
    fi
done

echo "[mst-loop] done"
