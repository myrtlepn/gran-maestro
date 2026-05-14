from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"

AGI_ID = "AGI-725"
DOD_ID = "DOD-XXX"
SID_A = "MST-AGI-725-20260503T130813382Z-k7f3q9x2"
SID_B = "MST-AGI-725-20260503T130813382Z-z9y8x7w6"
ZERO_HASH = "0" * 64


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_hash(prev_hash: str, event: dict) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + "\n" + canonical).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _seed_session_contract(root: Path, session_id: str = SID_B) -> None:
    session_dir = root / ".gran-maestro" / "sessions" / session_id
    write_json(
        session_dir / "session.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": AGI_ID,
        },
    )
    history_file = session_dir / "history.ndjson"
    event = {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": AGI_ID,
        "event_type": "skill.step",
        "type": "skill.step",
        "skill": "mst:agile",
        "created_at": "2026-05-03T13:08:13.382Z",
        "timestamp": "2026-05-03T13:08:13.382Z",
        "idempotency_key": f"{session_id}:skill.step:recover-cross-session-seed",
    }
    head = _event_hash(ZERO_HASH, event)
    row = {"seq": 1, "prev_hash": ZERO_HASH, "event_hash": head, "event": event, "mst_session_id": session_id}
    history_file.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    (session_dir / "history.head").write_text(head + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{head}\t{_fingerprint(history_file)}\t1\n", encoding="utf-8")
    mirror = root / ".policy" / "ledger-heads" / f"{session_id}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(head + "\n", encoding="utf-8")


def write_agile_fixture(
    root: Path,
    *,
    mst_session_id: str | None = SID_B,
    owner_session_id: str = SID_A,
) -> Path:
    agi_dir = root / ".gran-maestro" / "agile" / AGI_ID
    payload = {
        "id": AGI_ID,
        "schema_version": 1,
        "root_mst_id": AGI_ID,
        "status": "executing",
        "current_sprint": 2,
        "owner_ppid": 12345,
        "owner_session_id": owner_session_id,
    }
    if mst_session_id is not None:
        payload["mst_session_id"] = mst_session_id
    write_json(agi_dir / "session.json", payload)
    write_json(
        agi_dir / "sprints" / "S01" / "result.json",
        {
            "status": "success",
            "target_dod": DOD_ID,
        },
    )
    objective = agi_dir / "objective" / "objective.md"
    objective.parent.mkdir(parents=True, exist_ok=True)
    objective.write_text(
        f"# Test objective\n\n<!-- dod: {DOD_ID} status: pending priority: must -->\n",
        encoding="utf-8",
    )
    _seed_session_contract(root, SID_B)
    return agi_dir


def snapshot_path(root: Path, session_id: str = SID_B) -> Path:
    return root / ".gran-maestro" / "state" / session_id / "snapshot.json"


def flow_path(root: Path, session_id: str = SID_B) -> Path:
    return root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"


def run_mst(root: Path, *args: str, session_id: str | None = SID_B) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if session_id is None:
        env.pop("MST_SESSION_ID", None)
    else:
        env["MST_SESSION_ID"] = session_id
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(root / ".policy")
    return subprocess.run(
        ["python3", str(MST), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def recover(root: Path, *args: str, session_id: str | None = SID_B) -> subprocess.CompletedProcess[str]:
    return run_mst(root, "recover", AGI_ID, *args, session_id=session_id)


def test_durable_fallback_reconstructs_skillstack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "owner_session_id ignored" in result.stderr
    assert "read-only" not in result.stdout
    snapshot = read_json(snapshot_path(tmp_path))
    assert snapshot["skillStack"]
    assert snapshot["skillStack"][0]["skill"] == "agile"
    assert snapshot["skillStack"][0]["target_dod"] == DOD_ID


def test_new_session_snapshot_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    snapshot = read_json(snapshot_path(tmp_path))
    assert snapshot["sessionId"] == SID_B
    assert snapshot["status"] == "active"
    assert snapshot["durableFallback"] is True
    assert snapshot["skillStack"]


def test_owner_mismatch_is_diagnostic_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agi_dir = write_agile_fixture(tmp_path, owner_session_id=SID_A)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "owner_session_id ignored" in result.stderr
    assert read_json(agi_dir / "session.json")["owner_session_id"] == SID_A
    assert read_json(snapshot_path(tmp_path)).get("read_only") is not True

    mutation = run_mst(
        tmp_path,
        "agile",
        "objective-transition",
        AGI_ID,
        "--story",
        DOD_ID,
        "--status",
        "done",
    )

    assert mutation.returncode == 0, mutation.stderr
    assert read_json(agi_dir / "session.json")["owner_session_id"] == SID_A


def test_takeover_transfers_owner(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agi_dir = write_agile_fixture(tmp_path, owner_session_id=SID_A)

    result = recover(tmp_path, "--takeover")

    assert result.returncode == 0, result.stderr
    assert read_json(agi_dir / "session.json")["owner_session_id"] == SID_B
    snapshot = read_json(snapshot_path(tmp_path))
    assert snapshot.get("read_only") is not True

    mutation = run_mst(
        tmp_path,
        "agile",
        "objective-transition",
        AGI_ID,
        "--story",
        DOD_ID,
        "--status",
        "done",
    )

    assert mutation.returncode == 0, mutation.stderr
    objective = (agi_dir / "objective" / "objective.md").read_text(encoding="utf-8")
    assert f"<!-- dod: {DOD_ID} status: done priority: must -->" in objective


def test_flow_event_recorded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    events = [
        json.loads(line)
        for line in flow_path(tmp_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events[-1]["event"] == "cross_session_recover"
    assert events[-1]["agi_id"] == AGI_ID
    assert events[-1]["previous_owner_session_id"] == SID_A
    assert events[-1]["new_owner_session_id"] == SID_B
    assert events[-1]["takeover"] is False


def test_invalid_session_id_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path, session_id="invalid-format")

    assert result.returncode != 0
    assert "invalid structured mst_session_id" in result.stderr


def test_recover_requires_canonical_mst_session_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path, session_id=None)

    assert result.returncode != 0
    assert "missing_canonical_mst_session_id" in result.stderr
    assert not (tmp_path / ".gran-maestro" / "state").exists()


def test_durable_mst_session_id_mismatch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path, mst_session_id=SID_A)

    result = recover(tmp_path, session_id=SID_B)

    assert result.returncode != 0
    assert f"mst_session_id mismatch: env={SID_B} payload={SID_A}" in result.stderr
    assert not snapshot_path(tmp_path).exists()


def test_missing_durable_mst_session_id_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path, mst_session_id=None)

    result = recover(tmp_path, session_id=SID_B)

    assert result.returncode != 0
    assert "missing mst_session_id in durable session" in result.stderr
    assert not snapshot_path(tmp_path).exists()
