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


def _seed_session(workspace: Path, policy_home: Path) -> str:
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
    return head


def _env(policy_home: Path, head: str) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_LOGICAL_ATTEMPT_ID"] = "dod006-skill-history"
    env["MST_CONTEXT_JSON"] = json.dumps(
        {
            "prompt_summary": "diagnostic-only",
            "core_rehydration": {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT,
                "history": {"head_hash": head, "seq": 1},
                "next_execution": {
                    "env": {"MST_SESSION_ID": SID},
                    "context": {"mst_session_id": SID, "recovery_fingerprint": "recover:skill-history"},
                },
            },
        },
        separators=(",", ":"),
    )
    return env


def _run(workspace: Path, policy_home: Path, head: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(policy_home, head),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _history_event_types(workspace: Path) -> list[str]:
    path = workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
    return [json.loads(line)["event"]["event_type"] for line in path.read_text(encoding="utf-8").splitlines()]


def _history_session_ids(workspace: Path) -> set[str]:
    path = workspace / ".gran-maestro" / "sessions" / SID / "history.ndjson"
    return {json.loads(line)["event"]["mst_session_id"] for line in path.read_text(encoding="utf-8").splitlines()}


def test_recovered_context_skill_lifecycle_appends_to_existing_session_ledger() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_session(workspace, policy_home)

        step = _run(workspace, policy_home, head, "state", "set", "--skill", "mst:request", "--step", "2", "--total", "3")

        assert step.returncode == 0, step.stderr
        event_types = _history_event_types(workspace)
        assert event_types.count("skill.step") == 2
        assert "mst.invocation_start" in event_types
        assert "mst.invocation_end" in event_types
        assert _history_session_ids(workspace) == {SID}
        sessions = sorted(path.name for path in (workspace / ".gran-maestro" / "sessions").iterdir() if path.is_dir())
        assert sessions == [SID]


def main() -> int:
    test_recovered_context_skill_lifecycle_appends_to_existing_session_ledger()
    print("PASS test_recovered_context_skill_lifecycle_appends_to_existing_session_ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
