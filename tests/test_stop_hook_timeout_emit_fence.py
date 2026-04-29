from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


SCRIPT = r"""
set -Eeuo pipefail
mode="$1"
hook="$2"

eval "$(awk '
/^(emit_approve_json|emit_block_json|emit_allow_json|details_anchor_for_reason|claim_judge_timeout_emit)\(\)/ { printing = 1 }
printing { print }
printing && /^}/ { printing = 0 }
' "$hook")"

tmpdir="$(mktemp -d)"
HOOK_JUDGE_TIMEOUT_MARKER="$tmpdir/marker"
HOOK_JUDGE_TIMEOUT_DONE="$tmpdir/done"

case "$mode" in
  normal-approve)
    emit_approve_json "approved" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  normal-block)
    emit_block_json "blocked" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  preclaimed-approve)
    mkdir "$HOOK_JUDGE_TIMEOUT_MARKER"
    emit_approve_json "approved" ""
    test ! -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  claimed-timeout-allow)
    claim_judge_timeout_emit
    emit_allow_json "hook judge timeout (>1ms) fail-open"
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  double-main-approve)
    emit_approve_json "approved" ""
    emit_block_json "blocked" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  *)
    exit 2
    ;;
esac
"""


def _run_mode(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", SCRIPT, "stop-hook-timeout-emit-fence", mode, str(HOOK_PATH)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_main_emit_claims_marker_and_touches_done():
    result = _run_mode("normal-approve")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"decision": "approve", "reason": "approved"}


def test_main_emit_stays_quiet_when_watchdog_already_claimed():
    result = _run_mode("preclaimed-approve")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_timeout_emit_preserves_already_claimed_fail_open_output():
    result = _run_mode("claimed-timeout-allow")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "hook judge timeout (>1ms) fail-open"


def test_block_emit_claims_marker_and_touches_done():
    result = _run_mode("normal-block")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"decision": "block", "reason": "blocked"}


def test_claim_is_consumed_after_first_main_emit():
    result = _run_mode("double-main-approve")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout) == {"decision": "approve", "reason": "approved"}
