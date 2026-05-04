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
RESOURCE_IDS = {"AGI-030", "PLN-638", "REQ-811"}
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


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
    env["MST_CONTEXT_JSON"] = json.dumps(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "resource_id": "REQ-811",
            "plan_id": "PLN-638",
            "fixture": "dod005",
        }
    )
    env["MST_STATE_PPID"] = "818181"
    env["MST_HOOK_STDIN_RAW"] = json.dumps(
        {
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": 818181,
            "owner_session_id": "owner-diagnostic-only",
        }
    )
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


def _assert_rows_use_only_canonical_mst_session_id(rows: list[dict]) -> None:
    assert {row["mst_session_id"] for row in rows} == {SID}
    events = [row.get("event", row) for row in rows]
    assert {event["mst_session_id"] for event in events} == {SID}
    assert {event["root_mst_id"] for event in events} == {ROOT}
    assert not ({row["mst_session_id"] for row in rows} & RESOURCE_IDS)


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
        _assert_rows_use_only_canonical_mst_session_id(rows)
        raw_events = [json.loads(line)["event"] for line in (
            workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
        ).read_text(encoding="utf-8").splitlines()]
        assert {event["command"] for event in raw_events if event["event_type"].startswith("mst.invocation_")} >= {
            "history head",
            "history log",
        }
        for event in raw_events:
            assert event["mst_session_id"] != event.get("pid")
            assert event["mst_session_id"] != event.get("ppid")
        for resource_id in RESOURCE_IDS:
            assert not (workspace / ".gran-maestro" / "sessions" / resource_id).exists()


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
        _assert_rows_use_only_canonical_mst_session_id(rows)
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
