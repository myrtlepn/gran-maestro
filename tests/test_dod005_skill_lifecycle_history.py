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
RESOURCE_ID = "REQ-811"
PLAN_ID = "PLN-638"
LEGACY_PPID = "818181"


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
    env["MST_CONTEXT_JSON"] = json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "resource_id": RESOURCE_ID,
            "plan_id": PLAN_ID,
            "fixture": "skill-lifecycle",
        }
    )
    env["MST_STATE_PPID"] = LEGACY_PPID
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


def _history_rows(workspace: Path, policy_home: Path) -> list[dict]:
    result = _run(workspace, policy_home, "history", "log", "--session", SID, "--json")
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _raw_history_events(workspace: Path) -> list[dict]:
    history_path = workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
    return [json.loads(line)["event"] for line in history_path.read_text(encoding="utf-8").splitlines()]


def test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _init_session(workspace)

        workflow = _run(
            workspace,
            policy_home,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--req",
            RESOURCE_ID,
            "--next-source",
            PLAN_ID,
        )
        enter = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "0", "--total", "2")
        step = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "1", "--total", "2")
        exit_ = _run(workspace, policy_home, "state", "set", "--skill", "mst:request", "--step", "2", "--total", "2")
        recover = _run(workspace, policy_home, "state", "recover", ROOT)

        assert workflow.returncode == 0, workflow.stderr
        assert enter.returncode == 0, enter.stderr
        assert step.returncode == 0, step.stderr
        assert exit_.returncode == 0, exit_.stderr
        assert recover.returncode == 0, recover.stderr
        event_types = _event_types(workspace, policy_home)
        for expected in ("skill.enter", "skill.step", "skill.exit", "skill.recover"):
            assert expected in event_types
        rows = _history_rows(workspace, policy_home)
        assert {row["mst_session_id"] for row in rows} == {SID}
        raw_events = _raw_history_events(workspace)
        assert {event["mst_session_id"] for event in raw_events} == {SID}
        assert {event["root_mst_id"] for event in raw_events} == {ROOT}
        skill_events = [event for event in raw_events if str(event["event_type"]).startswith("skill.")]
        assert any(event.get("resource_id") == RESOURCE_ID for event in skill_events)
        assert all(event["mst_session_id"] != event.get("resource_id") for event in skill_events)
        assert all(event["mst_session_id"] != LEGACY_PPID for event in skill_events)
        for resource_id in (ROOT, RESOURCE_ID, PLAN_ID, LEGACY_PPID):
            assert not (workspace / ".gran-maestro" / "sessions" / resource_id).exists()


def main() -> int:
    test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger()
    print("PASS test_state_set_and_recover_emit_skill_lifecycle_events_to_parent_ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
