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
SID = "MST-AGI-030-20260504T160133000Z-dod006a1"
ROOT = "AGI-030"
ZERO_HASH = "0" * 64


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_LOGICAL_ATTEMPT_ID"] = "dod006-stable-recovery"
    env["MST_CONTEXT_JSON"] = json.dumps(
        {
            "mst_session_id": SID,
            "recovery_fingerprint": "recover:AGI-030:history-head",
        },
        separators=(",", ":"),
    )
    return env


def _run_recover(workspace: Path, policy_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "recover", ROOT],
        cwd=workspace,
        env=_env(policy_home),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_event(event)).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _read_json_from_stdout(stdout: str) -> dict:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(lines[index:]))
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _seed_fixture(workspace: Path, policy_home: Path) -> None:
    base = workspace / ".gran-maestro"
    session_dir = base / "sessions" / SID
    session_dir.mkdir(parents=True, exist_ok=True)
    _write_json(session_dir / "session.json", {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT})
    _write_json(
        base / "agile" / ROOT / "session.json",
        {"id": ROOT, "schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT, "status": "executing"},
    )
    history_file = session_dir / "history.ndjson"
    event = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "event_type": "skill.step",
        "type": "skill.step",
        "created_at": "2026-05-04T16:01:33.000Z",
        "timestamp": "2026-05-04T16:01:33.000Z",
        "idempotency_key": f"{SID}:skill.step:dod006-seed",
    }
    head = _event_hash(ZERO_HASH, event)
    row = {"seq": 1, "prev_hash": ZERO_HASH, "event_hash": head, "event": event, "mst_session_id": SID}
    history_file.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    (session_dir / "history.head").write_text(head + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{head}\t{_fingerprint(history_file)}\t1\n", encoding="utf-8")
    mirror = policy_home / "ledger-heads" / f"{SID}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(head + "\n", encoding="utf-8")


def _history_rows(workspace: Path) -> list[dict]:
    path = workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _head(workspace: Path) -> str:
    return (workspace / ".gran-maestro" / "sessions" / SID / "history.head").read_text(encoding="utf-8").strip()


def _session_dirs(workspace: Path) -> list[str]:
    sessions = workspace / ".gran-maestro" / "sessions"
    return sorted(path.name for path in sessions.iterdir() if path.is_dir())


def test_repeated_recover_is_idempotent_by_stable_recovery_fingerprint() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_fixture(workspace, policy_home)

        first = _run_recover(workspace, policy_home)
        first_head = _head(workspace)
        first_rows = _history_rows(workspace)
        first_sessions = _session_dirs(workspace)
        second = _run_recover(workspace, policy_home)
        second_head = _head(workspace)
        second_rows = _history_rows(workspace)
        second_sessions = _session_dirs(workspace)

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        first_payload = _read_json_from_stdout(first.stdout)
        second_payload = _read_json_from_stdout(second.stdout)
        assert first_payload["core_rehydration"]["recovery_fingerprint"] == "recover:AGI-030:history-head"
        assert second_payload["core_rehydration"]["recovery_fingerprint"] == "recover:AGI-030:history-head"
        assert second_head == first_head
        assert second_rows == first_rows
        assert second_sessions == first_sessions == [SID]


def main() -> int:
    test_repeated_recover_is_idempotent_by_stable_recovery_fingerprint()
    print("PASS test_repeated_recover_is_idempotent_by_stable_recovery_fingerprint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
