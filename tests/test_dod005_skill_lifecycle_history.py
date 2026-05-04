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
    agi_dir = workspace / ".gran-maestro" / "agile" / ROOT
    agi_dir.mkdir(parents=True, exist_ok=True)
    (agi_dir / "session.json").write_text(
        json.dumps({"id": ROOT, "schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT}) + "\n",
        encoding="utf-8",
    )


def _env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps({"mst_session_id": SID, "fixture": "skill-lifecycle"})
    return env


def _run(workspace: Path, policy_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _event_types(workspace: Path, policy_home: Path) -> list[str]:
    result = _run(workspace, policy_home, "history", "log", "--session", SID, "--json")
    assert result.returncode == 0, result.stderr
    return [json.loads(line)["event_type"] for line in result.stdout.splitlines() if line.strip()]


def test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _init_session(workspace)

        enter = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "0", "--total", "2")
        step = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "1", "--total", "2")
        exit_ = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "2", "--total", "2")
        recover = _run(workspace, policy_home, "state", "recover", ROOT)

        assert enter.returncode == 0, enter.stderr
        assert step.returncode == 0, step.stderr
        assert exit_.returncode == 0, exit_.stderr
        assert recover.returncode == 0, recover.stderr
        event_types = _event_types(workspace, policy_home)
        for expected in ("skill.enter", "skill.step", "skill.exit", "skill.recover"):
            assert expected in event_types


def main() -> int:
    test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger()
    print("PASS test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
