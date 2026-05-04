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


def _event(seq: int) -> dict:
    return {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "event_type": "skill.step",
        "created_at": f"2026-05-04T00:00:0{seq}.000Z",
        "idempotency_key": f"{SID}:skill.step:{seq}",
        "step": seq,
    }


def _hash(prev_hash: str, event: dict) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _write_base_session(workspace: Path, policy_home: Path) -> tuple[Path, Path, Path, Path]:
    base = workspace / ".gran-maestro"
    session_dir = base / "sessions" / SID
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps({"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT}) + "\n",
        encoding="utf-8",
    )
    history = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    mirror_head = policy_home / "ledger-heads" / f"{SID}.head"
    mirror_head.parent.mkdir(parents=True, exist_ok=True)
    verify = session_dir / "history.verify"
    return history, local_head, mirror_head, verify


def _write_valid_history(workspace: Path, policy_home: Path, *, count: int = 2) -> tuple[Path, str]:
    history, local_head, mirror_head, verify = _write_base_session(workspace, policy_home)
    prev_hash = ZERO_HASH
    rows = []
    for seq in range(1, count + 1):
        event = _event(seq)
        event_hash = _hash(prev_hash, event)
        rows.append(
            {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT,
                "event_type": event["event_type"],
                "created_at": event["created_at"],
                "idempotency_key": event["idempotency_key"],
                "seq": seq,
                "prev_hash": prev_hash,
                "event_hash": event_hash,
                "event": event,
            }
        )
        prev_hash = event_hash
    history.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    local_head.write_text(prev_hash + "\n", encoding="utf-8")
    mirror_head.write_text(prev_hash + "\n", encoding="utf-8")
    verify.write_text(f"{prev_hash}\t{_fingerprint(history)}\t{count}\n", encoding="utf-8")
    return history, prev_hash


def _expect_non_success_without_mutation(workspace: Path, policy_home: Path, expected_codes: set[str]) -> None:
    before = _snapshot(workspace / ".gran-maestro", policy_home)
    for command in ("log", "verify", "head"):
        result = _run(workspace, policy_home, "history", command, "--session", SID, "--json")
        assert result.returncode != 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] in expected_codes
        assert _snapshot(workspace / ".gran-maestro", policy_home) == before


def test_empty_missing_truncated_invalid_and_mismatched_history_fail_closed() -> None:
    cases = []

    def missing_history(workspace: Path, policy_home: Path) -> set[str]:
        _write_base_session(workspace, policy_home)
        return {"history_file_missing"}

    def empty_history(workspace: Path, policy_home: Path) -> set[str]:
        history, local_head, mirror_head, verify = _write_base_session(workspace, policy_home)
        history.write_text("", encoding="utf-8")
        local_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        mirror_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        verify.write_text(f"{ZERO_HASH}\tmissing\t0\n", encoding="utf-8")
        return {"history_empty"}

    def truncated_json(workspace: Path, policy_home: Path) -> set[str]:
        history, local_head, mirror_head, verify = _write_base_session(workspace, policy_home)
        history.write_text('{"seq":1,"event":', encoding="utf-8")
        local_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        mirror_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        verify.write_text(f"{ZERO_HASH}\tmissing\t0\n", encoding="utf-8")
        return {"history_json_invalid"}

    def invalid_json(workspace: Path, policy_home: Path) -> set[str]:
        history, local_head, mirror_head, verify = _write_base_session(workspace, policy_home)
        history.write_text("{not-json}\n", encoding="utf-8")
        local_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        mirror_head.write_text(ZERO_HASH + "\n", encoding="utf-8")
        verify.write_text(f"{ZERO_HASH}\tmissing\t0\n", encoding="utf-8")
        return {"history_json_invalid"}

    def seq_gap(workspace: Path, policy_home: Path) -> set[str]:
        history, _tail = _write_valid_history(workspace, policy_home, count=1)
        row = json.loads(history.read_text(encoding="utf-8").splitlines()[0])
        row["seq"] = 2
        history.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        return {"history_seq_mismatch"}

    def prev_hash_mismatch(workspace: Path, policy_home: Path) -> set[str]:
        history, _tail = _write_valid_history(workspace, policy_home, count=1)
        row = json.loads(history.read_text(encoding="utf-8").splitlines()[0])
        row["prev_hash"] = "f" * 64
        history.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        return {"history_prev_hash_mismatch"}

    def event_hash_mismatch(workspace: Path, policy_home: Path) -> set[str]:
        history, _tail = _write_valid_history(workspace, policy_home, count=1)
        row = json.loads(history.read_text(encoding="utf-8").splitlines()[0])
        row["event_hash"] = "f" * 64
        history.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        return {"history_event_hash_mismatch"}

    def tail_vs_head_mismatch(workspace: Path, policy_home: Path) -> set[str]:
        history, _tail = _write_valid_history(workspace, policy_home, count=2)
        first_hash = json.loads(history.read_text(encoding="utf-8").splitlines()[0])["event_hash"]
        (history.parent / "history.head").write_text(first_hash + "\n", encoding="utf-8")
        return {"history_head_mismatch"}

    cases.extend(
        [
            missing_history,
            empty_history,
            truncated_json,
            invalid_json,
            seq_gap,
            prev_hash_mismatch,
            event_hash_mismatch,
            tail_vs_head_mismatch,
        ]
    )

    for arrange in cases:
        with _workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            expected_codes = arrange(workspace, policy_home)
            _expect_non_success_without_mutation(workspace, policy_home, expected_codes)


def main() -> int:
    test_empty_missing_truncated_invalid_and_mismatched_history_fail_closed()
    print("PASS test_empty_missing_truncated_invalid_and_mismatched_history_fail_closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
