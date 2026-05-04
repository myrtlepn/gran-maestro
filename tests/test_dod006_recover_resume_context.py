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
OTHER_SID = "MST-AGI-030-20260504T160133000Z-dod006b2"
ROOT = "AGI-030"
REQ = "REQ-809"
ZERO_HASH = "0" * 64


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _env(policy_home: Path, *, context: dict | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps(
        context or {"mst_session_id": SID, "prompt_summary": "diagnostic-only"},
        ensure_ascii=False,
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


def _read_json_from_stdout(stdout: str) -> dict:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            return json.loads("\n".join(lines[index:]))
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_event(event)).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _seed_history(workspace: Path, policy_home: Path, *, head_override: str | None = None) -> str:
    session_dir = workspace / ".gran-maestro" / "sessions" / SID
    session_dir.mkdir(parents=True, exist_ok=True)
    history_file = session_dir / "history.ndjson"
    prev_hash = ZERO_HASH
    rows = []
    for seq, event_type in enumerate(("mst.invocation_start", "skill.step"), 1):
        event = {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "event_type": event_type,
            "type": event_type,
            "created_at": f"2026-05-04T16:01:3{seq}.000Z",
            "timestamp": f"2026-05-04T16:01:3{seq}.000Z",
            "idempotency_key": f"{SID}:{event_type}:dod006-fixture",
        }
        current_hash = _event_hash(prev_hash, event)
        rows.append({"seq": seq, "prev_hash": prev_hash, "event_hash": current_hash, "event": event, "mst_session_id": SID})
        prev_hash = current_hash
    history_file.write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    head = head_override or prev_hash
    (session_dir / "history.head").write_text(head + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{head}\t{_fingerprint(history_file)}\t{len(rows)}\n", encoding="utf-8")
    mirror = policy_home / "ledger-heads" / f"{SID}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(head + "\n", encoding="utf-8")
    return head


def _seed_session_and_snapshot(
    workspace: Path,
    policy_home: Path,
    *,
    snapshot_root: str = ROOT,
    snapshot_session: str = SID,
    include_history: bool = True,
    head_override: str | None = None,
) -> str:
    base = workspace / ".gran-maestro"
    head = _seed_history(workspace, policy_home, head_override=head_override)
    session_payload = {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT}
    _write_json(base / "sessions" / SID / "session.json", session_payload)
    _write_json(base / "agile" / ROOT / "session.json", {"id": ROOT, **session_payload, "status": "executing"})
    snapshot = {
        "schema_version": 1,
        "mst_session_id": snapshot_session,
        "root_mst_id": snapshot_root,
        "sessionId": snapshot_session,
        "currentSkill": "mst:request",
        "currentStep": 3,
        "totalSteps": 5,
        "status": "active",
        "workflow": {
            "current_skill": "mst:request",
            "current_step": 3,
            "total_steps": 5,
            "status": "active",
        },
        "next_action": {
            "expected_skill": "mst:approve",
            "skill": "mst:approve",
            "source_id": REQ,
            "source": REQ,
            "auto": True,
            "auto_mode": True,
        },
    }
    if include_history:
        snapshot["history"] = {"last_event_id": head, "head_hash": head}
    _write_json(base / "state" / SID / "snapshot.json", snapshot)
    return head


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _envelope(payload: dict) -> dict:
    core = payload.get("core_rehydration")
    return core if isinstance(core, dict) else payload


def _assert_structured_non_success(result: subprocess.CompletedProcess[str], before: dict[str, str], workspace: Path) -> dict:
    assert result.returncode != 0
    assert _hashes(workspace) == before
    payload = _read_json_from_stdout(result.stdout)
    assert payload["status"] in {"error", "blocked", "non_success"}
    assert payload.get("created_new_session") is not True
    assert payload.get("prompt_summary_used_as_source") is not True
    return payload


def test_valid_recover_restores_rehydration_envelope_and_next_execution_context() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_session_and_snapshot(workspace, policy_home)

        result = _run_recover(workspace, policy_home)

        assert result.returncode == 0, result.stderr
        payload = _read_json_from_stdout(result.stdout)
        envelope = _envelope(payload)
        assert envelope["schema_version"] == 1
        assert envelope["mst_session_id"] == SID
        assert envelope["root_mst_id"] == ROOT
        assert envelope["workflow"]["status"] == "active"
        assert envelope["current_skill"]["name"] == "mst:request"
        assert envelope["current_skill"]["step"] == 3
        assert envelope["next_skill"]["name"] == "mst:approve"
        assert envelope["next_skill"]["source_id"] == REQ
        assert envelope["next_skill"]["auto"] is True
        history = envelope["history"]
        assert history.get("head_hash") or history.get("last_event_id")
        assert head in {history.get("head_hash"), history.get("last_event_id")}
        assert envelope["next_execution"]["env"]["MST_SESSION_ID"] == SID
        assert envelope["next_execution"]["context"]["mst_session_id"] == SID
        assert envelope["source_precedence"][0] == "validated_history_ledger"
        assert envelope["prompt_summary_used_as_source"] is False


def test_mismatch_snapshot_payload_fails_closed_without_prompt_summary_or_new_session() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_session_and_snapshot(workspace, policy_home, snapshot_root="REQ-809")
        before = _hashes(workspace)

        result = _run_recover(workspace, policy_home)

        payload = _assert_structured_non_success(result, before, workspace)
        assert payload["code"] in {"state_history_linkage_mismatch", "snapshot_root_mismatch"}
        assert not (workspace / ".gran-maestro" / "sessions" / OTHER_SID).exists()


def test_stale_history_head_fails_closed_without_snapshot_repair() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        stale_head = "f" * 64
        _seed_session_and_snapshot(workspace, policy_home)
        snapshot_path = workspace / ".gran-maestro" / "state" / SID / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["history"] = {"last_event_id": stale_head, "head_hash": stale_head}
        _write_json(snapshot_path, snapshot)
        before = _hashes(workspace)

        result = _run_recover(workspace, policy_home)

        payload = _assert_structured_non_success(result, before, workspace)
        assert payload["code"] in {"state_history_linkage_mismatch", "stale_history_head"}


def test_missing_history_linkage_fails_closed_without_rehydration_fallback() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_session_and_snapshot(workspace, policy_home, include_history=False)
        before = _hashes(workspace)

        result = _run_recover(workspace, policy_home)

        payload = _assert_structured_non_success(result, before, workspace)
        assert payload["code"] in {"missing_required_rehydration_field", "missing_history_linkage"}


def _selected_tests(argv: list[str]) -> list[tuple[str, object]]:
    tests = [
        (name, value)
        for name, value in globals().items()
        if name.startswith("test_") and callable(value)
    ]
    if "-k" not in argv:
        return tests
    index = argv.index("-k")
    expression = argv[index + 1] if index + 1 < len(argv) else ""
    terms = [term.strip() for term in expression.split("or") if term.strip()]
    return [(name, test) for name, test in tests if any(term in name for term in terms)]


def main() -> int:
    for name, test in _selected_tests(sys.argv[1:]):
        test()
        print(f"PASS {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
