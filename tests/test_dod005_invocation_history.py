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


def _env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps({"mst_session_id": SID, "fixture": "dod005"})
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


def _history_json(workspace: Path, policy_home: Path) -> list[dict]:
    result = _run(workspace, policy_home, "history", "log", "--session", SID, "--json")
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_successful_mst_invocation_appends_start_and_end_to_parent_ledger() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _init_session(workspace)

        result = _run(workspace, policy_home, "history", "head", "--session", SID, "--json")

        assert result.returncode == 0, result.stderr
        rows = _history_json(workspace, policy_home)
        event_types = [row["event_type"] for row in rows]
        assert "mst.invocation_start" in event_types
        assert "mst.invocation_end" in event_types
        assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))
        assert {row["mst_session_id"] for row in rows} == {SID}
        assert {row["root_mst_id"] for row in rows} == {ROOT}


def test_failed_mst_invocation_appends_error_without_child_fallback_session() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _init_session(workspace)

        result = _run(workspace, policy_home, "history", "log", "--session", "not-a-session", "--json")

        assert result.returncode != 0
        rows = _history_json(workspace, policy_home)
        event_types = [row["event_type"] for row in rows]
        assert "mst.invocation_start" in event_types
        assert "mst.invocation_error" in event_types
        assert not (workspace / ".gran-maestro" / "sessions" / "not-a-session").exists()
        assert not (workspace / ".gran-maestro" / "sessions" / "default").exists()


def main() -> int:
    for test in (
        test_successful_mst_invocation_appends_start_and_end_to_parent_ledger,
        test_failed_mst_invocation_appends_error_without_child_fallback_session,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
