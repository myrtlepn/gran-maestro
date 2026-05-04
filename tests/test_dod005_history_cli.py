from __future__ import annotations

import hashlib
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
ZERO_HASH = "0" * 64


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _clean_env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        env.pop(key, None)
    return env


def _run(workspace: Path, policy_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_clean_env(policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def _event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_event(event)).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _seed_history(workspace: Path, policy_home: Path, sid: str = SID, root: str = ROOT) -> list[dict]:
    base = workspace / ".gran-maestro"
    session_dir = base / "sessions" / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"schema_version": 1, "mst_session_id": sid, "root_mst_id": root}) + "\n",
        encoding="utf-8",
    )
    history_file = session_dir / "history.ndjson"
    prev_hash = ZERO_HASH
    rows = []
    for seq, event_type in enumerate(("mst.invocation_start", "skill.enter", "skill.exit"), 1):
        event = {
            "schema_version": 1,
            "mst_session_id": sid,
            "root_mst_id": root,
            "event_type": event_type,
            "type": event_type,
            "created_at": f"2026-05-04T00:00:0{seq}.000Z",
            "timestamp": f"2026-05-04T00:00:0{seq}.000Z",
            "idempotency_key": f"{sid}:{event_type}:fixture",
        }
        current_hash = _event_hash(prev_hash, event)
        row = {
            "seq": seq,
            "prev_hash": prev_hash,
            "event_hash": current_hash,
            "event": event,
            "mst_session_id": sid,
        }
        rows.append(row)
        prev_hash = current_hash
    history_file.write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    (session_dir / "history.head").write_text(prev_hash + "\n", encoding="utf-8")
    mirror = policy_home / "ledger-heads" / f"{sid}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(prev_hash + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{prev_hash}\t{_fingerprint(history_file)}\t3\n", encoding="utf-8")
    return rows


def _json_lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_history_log_json_projects_validated_rows_in_seq_order() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()
        _seed_history(workspace, policy_home)

        result = _run(workspace, policy_home, "history", "log", "--session", SID, "--json")

        assert result.returncode == 0, result.stderr
        rows = _json_lines(result.stdout)
        assert [row["seq"] for row in rows] == [1, 2, 3]
        required = {
            "schema_version",
            "mst_session_id",
            "root_mst_id",
            "event_type",
            "created_at",
            "seq",
            "prev_hash",
            "event_hash",
            "idempotency_key",
        }
        for row in rows:
            assert required <= row.keys()
            assert row["mst_session_id"] == SID
            assert row["root_mst_id"] == ROOT


def test_history_log_table_exposes_canonical_columns() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()
        _seed_history(workspace, policy_home)

        result = _run(workspace, policy_home, "history", "log", "--session", SID)

        assert result.returncode == 0, result.stderr
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert lines[0] == "seq | mst_session_id | root_mst_id | event_type | created_at | event_hash | idempotency_key"
        assert "1 | MST-AGI-030-" in lines[1]
        assert "mst.invocation_start" in lines[1]


def test_history_log_rejects_root_mismatch_without_partial_success() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()
        _seed_history(workspace, policy_home)
        history_file = workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
        rows = _json_lines(history_file.read_text(encoding="utf-8"))
        rows[1]["event"]["root_mst_id"] = "REQ-808"
        rows[1]["event_hash"] = _event_hash(rows[1]["prev_hash"], rows[1]["event"])
        rows[2]["prev_hash"] = rows[1]["event_hash"]
        rows[2]["event_hash"] = _event_hash(rows[2]["prev_hash"], rows[2]["event"])
        history_file.write_text(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
            encoding="utf-8",
        )
        tail = rows[-1]["event_hash"]
        (history_file.parent / "history.head").write_text(tail + "\n", encoding="utf-8")
        (policy_home / "ledger-heads" / f"{SID}.head").write_text(tail + "\n", encoding="utf-8")
        (history_file.parent / "history.verify").write_text(f"{tail}\t{_fingerprint(history_file)}\t3\n", encoding="utf-8")

        result = _run(workspace, policy_home, "history", "log", "--session", SID, "--json")

        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "history_row_root_mismatch"


def main() -> int:
    for test in (
        test_history_log_json_projects_validated_rows_in_seq_order,
        test_history_log_table_exposes_canonical_columns,
        test_history_log_rejects_root_mismatch_without_partial_success,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
