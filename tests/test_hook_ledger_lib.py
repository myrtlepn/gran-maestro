from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_LIB = REPO_ROOT / "hooks" / "lib" / "ledger.bash"
MST_SESSION_ID = "MST-AGI-036-20260513T120000000Z-ledgerlib"


def _run_ledger(workspace: Path, payload: str, event: str = "SessionStart") -> subprocess.CompletedProcess:
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    script = f"""
set -euo pipefail
PROJECT_ROOT={json.dumps(str(workspace))}
STDIN_RAW={json.dumps(payload)}
source {json.dumps(str(LEDGER_LIB))}
emit_ledger_start {json.dumps(event)}
emit_ledger_complete {json.dumps(event)} 0
"""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(workspace / "home")},
    )


def _read_ledger(workspace: Path) -> list[dict]:
    ledger = workspace / ".gran-maestro" / "hooks-ledger.ndjson"
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]


def test_emit_ledger_start_and_complete_write_schema(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    payload = json.dumps({"mst_session_id": MST_SESSION_ID, "session_id": "sess-lib", "value": 1})

    result = _run_ledger(workspace, payload)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    records = _read_ledger(workspace)
    assert [record["phase"] for record in records] == ["start", "complete"]
    assert records[0]["exit_code"] is None
    assert records[1]["exit_code"] == 0
    for record in records:
        assert set(record) == {
            "ts",
            "hook_event",
            "phase",
            "exit_code",
            "payload_digest",
            "mst_session_id",
            "claude_session_id",
            "invocation_source",
            "pid",
        }
        assert record["hook_event"] == "SessionStart"
        assert record["mst_session_id"] == MST_SESSION_ID
        assert record["claude_session_id"] == "sess-lib"
        assert record["invocation_source"] == "settings_local"
        assert isinstance(record["pid"], int)
        assert len(record["payload_digest"]) == 12


def test_payload_digest_is_stable_for_same_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    payload = json.dumps({"mst_session_id": MST_SESSION_ID, "session_id": "sess-digest", "value": "same"})

    result = _run_ledger(workspace, payload)

    assert result.returncode == 0, result.stderr
    start, complete = _read_ledger(workspace)
    assert start["payload_digest"] == complete["payload_digest"]


def test_payload_digest_changes_for_different_payloads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"

    first = _run_ledger(workspace, json.dumps({"mst_session_id": MST_SESSION_ID, "session_id": "sess-a", "value": "a"}), "PreToolUse")
    second = _run_ledger(workspace, json.dumps({"mst_session_id": MST_SESSION_ID, "session_id": "sess-b", "value": "b"}), "PreToolUse")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    records = _read_ledger(workspace)
    assert records[0]["payload_digest"] != records[2]["payload_digest"]
