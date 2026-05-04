from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
HOOK_HISTORY_BASH = REPO_ROOT / "hooks" / "lib" / "history.bash"
SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
ROOT = "AGI-030"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _env(workspace: Path, policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_CLAUDE_HOME"] = str(workspace / "home")
    env["HOME"] = str(workspace / "home")
    return env


def _run_history(workspace: Path, policy_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "history", *args],
        cwd=workspace,
        env=_env(workspace, policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _bash_append(workspace: Path, policy_home: Path, event: dict) -> subprocess.CompletedProcess[str]:
    event_json = json.dumps(event, sort_keys=True, separators=(",", ":"))
    script = (
        f"source {HOOK_HISTORY_BASH}; "
        f"mst_history_append_event {workspace} {SID} '{event_json}'"
    )
    return subprocess.run(
        ["bash", "-c", script],
        cwd=workspace,
        env=_env(workspace, policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _python_append(workspace: Path, policy_home: Path, event: dict) -> subprocess.CompletedProcess[str]:
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from scripts.mst_cmds import hook\n"
        "hook.append_history_event(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], json.loads(sys.argv[4]))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(workspace), str(policy_home), SID, json.dumps(event)],
        cwd=REPO_ROOT,
        env=_env(workspace, policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _json_lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_bash_rows_are_canonical_for_python_history_verify_and_head() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()

        first = {
            "type": "hook_event",
            "hook_event": "PreToolUse",
            "phase": "start",
            "payload_digest": "abc123",
            "timestamp": "2026-05-04T00:00:00.000Z",
        }
        result = _bash_append(workspace, policy_home, first)
        assert result.returncode == 0, result.stderr

        duplicate = _bash_append(workspace, policy_home, first)
        assert duplicate.returncode == 0, duplicate.stderr

        verify = _run_history(workspace, policy_home, "verify", "--session", SID, "--json")
        head = _run_history(workspace, policy_home, "head", "--session", SID, "--json")
        log = _run_history(workspace, policy_home, "log", "--session", SID, "--json")

        assert verify.returncode == 0, verify.stderr + verify.stdout
        assert head.returncode == 0, head.stderr + head.stdout
        rows = _json_lines(log.stdout)
        assert [row["seq"] for row in rows] == [1]
        assert rows[0]["schema_version"] == 1
        assert rows[0]["mst_session_id"] == SID
        assert rows[0]["root_mst_id"] == ROOT
        assert rows[0]["event_type"] == "hook_event"
        assert rows[0]["created_at"] == "2026-05-04T00:00:00.000Z"
        assert rows[0]["idempotency_key"]


def test_python_append_continues_bash_chain_with_shared_heads_and_verify_state() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()

        bash_result = _bash_append(
            workspace,
            policy_home,
            {
                "type": "hook_event",
                "hook_event": "SessionStart",
                "phase": "start",
                "payload_digest": "session-start",
                "timestamp": "2026-05-04T00:00:01.000Z",
            },
        )
        assert bash_result.returncode == 0, bash_result.stderr

        python_result = _python_append(
            workspace,
            policy_home,
            {
                "event_type": "mst.invocation_start",
                "created_at": "2026-05-04T00:00:02.000Z",
                "idempotency_key": f"{SID}:mst.invocation_start:fixture",
            },
        )
        assert python_result.returncode == 0, python_result.stderr

        verify = _run_history(workspace, policy_home, "verify", "--session", SID, "--json")
        head = _run_history(workspace, policy_home, "head", "--session", SID, "--json")
        log = _run_history(workspace, policy_home, "log", "--session", SID, "--json")

        assert verify.returncode == 0, verify.stderr + verify.stdout
        assert head.returncode == 0, head.stderr + head.stdout
        verify_payload = json.loads(verify.stdout)
        head_payload = json.loads(head.stdout)
        rows = _json_lines(log.stdout)
        assert [row["seq"] for row in rows] == [1, 2]
        assert rows[1]["prev_hash"] == rows[0]["event_hash"]
        assert verify_payload["tail"]["event_hash"] == rows[-1]["event_hash"]
        assert head_payload["head"]["event_hash"] == rows[-1]["event_hash"]
        assert verify_payload["verify"]["seq"] == 2


def main() -> int:
    for test in (
        test_bash_rows_are_canonical_for_python_history_verify_and_head,
        test_python_append_continues_bash_chain_with_shared_heads_and_verify_state,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
