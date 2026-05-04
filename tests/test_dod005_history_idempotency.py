from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
ROOT = "AGI-030"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_session(workspace: Path) -> None:
    session_dir = workspace / ".gran-maestro" / "sessions" / SID
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT}) + "\n",
        encoding="utf-8",
    )


def _env(policy_home: Path, attempt: str) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps({"mst_session_id": SID, "fixture": "idempotency"})
    env["MST_LOGICAL_ATTEMPT_ID"] = attempt
    return env


def _run(workspace: Path, policy_home: Path, attempt: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(policy_home, attempt),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _rows(workspace: Path, policy_home: Path) -> list[dict]:
    result = _run(workspace, policy_home, "read", "history", "log", "--session", SID, "--json")
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_same_logical_transition_is_deduped_and_new_transition_advances_head() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _init_session(workspace)

        first = _run(workspace, policy_home, "same-attempt", "state", "set", "--skill", "mst:request", "--step", "1", "--total", "3")
        retry = _run(workspace, policy_home, "same-attempt", "state", "set", "--skill", "mst:request", "--step", "1", "--total", "3")
        next_step = _run(workspace, policy_home, "same-attempt", "state", "set", "--skill", "mst:request", "--step", "2", "--total", "3")

        assert first.returncode == 0, first.stderr
        assert retry.returncode == 0, retry.stderr
        assert next_step.returncode == 0, next_step.stderr
        rows = [row for row in _rows(workspace, policy_home) if row["event_type"] == "skill.step"]
        step_keys = [row["idempotency_key"] for row in rows]
        assert len(step_keys) == 2
        assert len(set(step_keys)) == 2
        assert any(":step=1:" in key for key in step_keys)
        assert any(":step=2:" in key for key in step_keys)


def main() -> int:
    test_same_logical_transition_is_deduped_and_new_transition_advances_head()
    print("PASS test_same_logical_transition_is_deduped_and_new_transition_advances_head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
