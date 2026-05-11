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
/^(emit_approve_json|emit_block_json|emit_final_file_once|details_anchor_for_reason|claim_judge_timeout_emit)\(\)/ { printing = 1 }
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
  preclaimed-block)
    mkdir "$HOOK_JUDGE_TIMEOUT_MARKER"
    emit_block_json "blocked" ""
    test ! -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  claimed-timeout-allow)
    final_file="$tmpdir/final.json"
    python3 - "$final_file" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"decision": "approve", "reason": "hook judge timeout (>1ms) fail-open"}, ensure_ascii=False) + "\n")
PY
    emit_final_file_once "$final_file"
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  claimed-timeout-then-main-approve)
    final_file="$tmpdir/final.json"
    python3 - "$final_file" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"decision": "approve", "reason": "hook judge timeout (>1ms) fail-open"}, ensure_ascii=False) + "\n")
PY
    emit_final_file_once "$final_file"
    emit_approve_json "approved" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  claimed-timeout-then-main-block)
    final_file="$tmpdir/final.json"
    python3 - "$final_file" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps({"decision": "approve", "reason": "hook judge timeout (>1ms) fail-open"}, ensure_ascii=False) + "\n")
PY
    emit_final_file_once "$final_file"
    emit_block_json "blocked" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  double-main-approve)
    emit_approve_json "approved" ""
    emit_block_json "blocked" ""
    test -f "$HOOK_JUDGE_TIMEOUT_DONE"
    ;;
  double-main-block)
    emit_block_json "blocked" ""
    emit_approve_json "approved" ""
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


def _stdout_json(result: subprocess.CompletedProcess[str]) -> dict:
    non_empty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(non_empty_lines) == 1, (
        "stop hook source-time harness must emit exactly one JSON decision line\n"
        f"stdout:\n{result.stdout!r}\n"
        f"stderr:\n{result.stderr!r}"
    )
    return json.loads(non_empty_lines[0])


def _assert_stdout_empty(result: subprocess.CompletedProcess[str]) -> None:
    assert result.stdout == "", (
        "preclaimed decision marker must suppress later stdout emission\n"
        f"stdout:\n{result.stdout!r}\n"
        f"stderr:\n{result.stderr!r}"
    )


def test_main_emit_claims_marker_and_touches_done():
    result = _run_mode("normal-approve")

    assert result.returncode == 0, result.stderr
    assert _stdout_json(result) == {"decision": "approve", "reason": "approved"}


def test_main_emit_stays_quiet_when_watchdog_already_claimed():
    result = _run_mode("preclaimed-approve")

    assert result.returncode == 0, result.stderr
    _assert_stdout_empty(result)


def test_block_emit_stays_quiet_when_watchdog_already_claimed():
    result = _run_mode("preclaimed-block")

    assert result.returncode == 0, result.stderr
    _assert_stdout_empty(result)


def test_timeout_emit_preserves_already_claimed_fail_open_output():
    result = _run_mode("claimed-timeout-allow")

    assert result.returncode == 0, result.stderr
    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "hook judge timeout (>1ms) fail-open"


def test_timeout_claim_suppresses_later_approve_emit():
    result = _run_mode("claimed-timeout-then-main-approve")

    assert result.returncode == 0, result.stderr
    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "hook judge timeout (>1ms) fail-open"


def test_timeout_claim_suppresses_later_block_emit():
    result = _run_mode("claimed-timeout-then-main-block")

    assert result.returncode == 0, result.stderr
    payload = _stdout_json(result)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "hook judge timeout (>1ms) fail-open"


def test_block_emit_claims_marker_and_touches_done():
    result = _run_mode("normal-block")

    assert result.returncode == 0, result.stderr
    assert _stdout_json(result) == {"decision": "block", "reason": "blocked"}


def test_approve_claim_suppresses_later_block_emit():
    result = _run_mode("double-main-approve")

    assert result.returncode == 0, result.stderr
    assert _stdout_json(result) == {"decision": "approve", "reason": "approved"}


def test_block_claim_suppresses_later_approve_emit():
    result = _run_mode("double-main-block")

    assert result.returncode == 0, result.stderr
    assert _stdout_json(result) == {"decision": "block", "reason": "blocked"}
