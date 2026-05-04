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
SID_A = "MST-AGI-030-20260504T010000000Z-splitaa1"
SID_B = "MST-AGI-030-20260504T010000001Z-splitbb2"
ROOT = "AGI-030"
ZERO_HASH = "0" * 64
FLOW_CORRELATION_ID = "AGI-030:parent-session:pm-flow-1"
PARENT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
PARENT_INVOCATION_ID = "pm-flow-1"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
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


def _snapshot(*roots: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                result[f"{root.name}/{path.relative_to(root)}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _hash(prev_hash: str, event: dict) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _write_valid_ledger(workspace: Path, policy_home: Path, sid: str, *, step: int) -> None:
    session_dir = workspace / ".gran-maestro" / "sessions" / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"schema_version": 1, "mst_session_id": sid, "root_mst_id": ROOT}) + "\n",
        encoding="utf-8",
    )
    event = {
        "schema_version": 1,
        "mst_session_id": sid,
        "root_mst_id": ROOT,
        "event_type": "skill.step",
        "created_at": f"2026-05-04T01:00:0{step}.000Z",
        "idempotency_key": f"{sid}:skill.step:{step}",
        "flow_correlation_id": FLOW_CORRELATION_ID,
        "parent_mst_session_id": PARENT_SESSION_ID,
        "parent_invocation_id": PARENT_INVOCATION_ID,
        "skill": "mst:request",
        "step": step,
    }
    event_hash = _hash(ZERO_HASH, event)
    row = {
        "schema_version": 1,
        "mst_session_id": sid,
        "root_mst_id": ROOT,
        "event_type": "skill.step",
        "created_at": event["created_at"],
        "idempotency_key": event["idempotency_key"],
        "seq": 1,
        "prev_hash": ZERO_HASH,
        "event_hash": event_hash,
        "event": event,
    }
    history = session_dir / "history.ndjson"
    history.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    (session_dir / "history.head").write_text(event_hash + "\n", encoding="utf-8")
    mirror_head = policy_home / "ledger-heads" / f"{sid}.head"
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    mirror_head.write_text(event_hash + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{event_hash}\t{_fingerprint(history)}\t1\n", encoding="utf-8")


def test_split_ledger_is_structured_non_success_without_repair_or_partial_success() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        (workspace / ".gran-maestro").mkdir()
        _write_valid_ledger(workspace, policy_home, SID_A, step=1)
        _write_valid_ledger(workspace, policy_home, SID_B, step=2)
        before = _snapshot(workspace / ".gran-maestro", policy_home)

        for command in ("verify", "log"):
            result = _run(workspace, policy_home, "history", command, "--session", SID_A, "--json")
            assert result.returncode != 0, result.stdout + result.stderr
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == "history_split_ledger_violation"
            assert payload["mst_session_id"] == SID_A
            assert payload["root_mst_id"] == ROOT
            assert payload["flow_correlation_id"] == FLOW_CORRELATION_ID
            assert sorted(payload["split_sessions"]) == [SID_A, SID_B]
            assert _snapshot(workspace / ".gran-maestro", policy_home) == before


def main() -> int:
    test_split_ledger_is_structured_non_success_without_repair_or_partial_success()
    print("PASS test_split_ledger_is_structured_non_success_without_repair_or_partial_success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
