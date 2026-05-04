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
HOOK_HISTORY_BASH = REPO_ROOT / "hooks" / "lib" / "history.bash"
SID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
ROOT = "AGI-030"
ZERO_HASH = "0" * 64


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _clean_env(policy_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
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


def _hash(prev_hash: str, event: dict) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _seed(workspace: Path, policy_home: Path) -> tuple[Path, str]:
    (workspace / ".gran-maestro").mkdir(exist_ok=True)
    session_dir = workspace / ".gran-maestro" / "sessions" / SID
    session_dir.mkdir(parents=True)
    history_file = session_dir / "history.ndjson"
    prev_hash = ZERO_HASH
    for seq in (1, 2):
        event = {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "event_type": f"skill.step.{seq}",
            "created_at": f"2026-05-04T00:01:0{seq}.000Z",
            "idempotency_key": f"{SID}:skill.step:{seq}",
        }
        event_hash = _hash(prev_hash, event)
        row = {"seq": seq, "prev_hash": prev_hash, "event_hash": event_hash, "event": event, "mst_session_id": SID}
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        prev_hash = event_hash
    (session_dir / "session.json").write_text(json.dumps({"mst_session_id": SID, "root_mst_id": ROOT}) + "\n", encoding="utf-8")
    (session_dir / "history.head").write_text(prev_hash + "\n", encoding="utf-8")
    mirror = policy_home / "ledger-heads" / f"{SID}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(prev_hash + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{prev_hash}\t{_fingerprint(history_file)}\t2\n", encoding="utf-8")
    return history_file, prev_hash


def test_history_verify_and_head_return_matching_tail() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _history_file, tail = _seed(workspace, policy_home)

        verify = _run(workspace, policy_home, "history", "verify", "--session", SID, "--json")
        head = _run(workspace, policy_home, "history", "head", "--session", SID, "--json")

        assert verify.returncode == 0, verify.stderr
        assert head.returncode == 0, head.stderr
        verify_payload = json.loads(verify.stdout)
        head_payload = json.loads(head.stdout)
        assert verify_payload["status"] == "ok"
        assert verify_payload["tail"]["event_hash"] == tail
        assert head_payload["status"] == "ok"
        assert head_payload["head"]["event_hash"] == tail
        assert head_payload["head"]["seq"] == 2


def test_history_verify_reports_mirror_head_mismatch_without_repair() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _history_file, tail = _seed(workspace, policy_home)
        mirror = policy_home / "ledger-heads" / f"{SID}.head"
        mirror.write_text("f" * 64 + "\n", encoding="utf-8")

        result = _run(workspace, policy_home, "history", "verify", "--session", SID, "--json")

        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "history_mirror_head_mismatch"
        assert mirror.read_text(encoding="utf-8").strip() == "f" * 64
        assert (workspace / ".gran-maestro" / "sessions" / SID / "history.head").read_text(encoding="utf-8").strip() == tail


def test_history_head_reports_missing_verify_state() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _history_file, _tail = _seed(workspace, policy_home)
        (workspace / ".gran-maestro" / "sessions" / SID / "history.verify").unlink()

        result = _run(workspace, policy_home, "history", "head", "--session", SID, "--json")

        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "history_verify_missing"


def test_bash_verify_reports_head_mismatch_without_self_heal() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        history_file, tail = _seed(workspace, policy_home)
        rows = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        stale = rows[0]["event_hash"]
        local_head = history_file.parent / "history.head"
        local_head.write_text(stale + "\n", encoding="utf-8")
        bash_home = workspace / "bash-home"
        bash_mirror = bash_home / ".claude" / "gran-maestro-policy" / "ledger-heads" / f"{SID}.head"
        bash_mirror.parent.mkdir(parents=True)
        bash_mirror.write_text(tail + "\n", encoding="utf-8")

        script = f"source {HOOK_HISTORY_BASH}; mst_history_verify_chain_unlocked {workspace} {SID}"
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=workspace,
            env={"HOME": str(bash_home), "MST_CLAUDE_HOME": str(bash_home)},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        assert result.returncode != 0
        assert "history ledger mismatch: history.head" in result.stderr
        assert local_head.read_text(encoding="utf-8").strip() == stale
        assert bash_mirror.read_text(encoding="utf-8").strip() == tail


def main() -> int:
    for test in (
        test_history_verify_and_head_return_matching_tail,
        test_history_verify_reports_mirror_head_mismatch_without_repair,
        test_history_head_reports_missing_verify_state,
        test_bash_verify_reports_head_mismatch_without_self_heal,
    ):
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
