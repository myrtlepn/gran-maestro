from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"

AGI_ID = "AGI-725"
DOD_ID = "DOD-XXX"
SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-9222-222222222222"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_agile_fixture(root: Path, *, owner_session_id: str = SID_A) -> Path:
    agi_dir = root / ".gran-maestro" / "agile" / AGI_ID
    write_json(
        agi_dir / "session.json",
        {
            "id": AGI_ID,
            "status": "executing",
            "current_sprint": 2,
            "owner_ppid": 12345,
            "owner_session_id": owner_session_id,
        },
    )
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
    return agi_dir


def snapshot_path(root: Path, session_id: str = SID_B) -> Path:
    return root / ".gran-maestro" / "state" / session_id / "snapshot.json"


def flow_path(root: Path, session_id: str = SID_B) -> Path:
    return root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"


def run_mst(root: Path, *args: str, session_id: str = SID_B) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_SESSION_ID"] = session_id
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    return subprocess.run(
        ["python3", str(MST), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def recover(root: Path, *args: str, session_id: str = SID_B) -> subprocess.CompletedProcess[str]:
    return run_mst(root, "recover", AGI_ID, *args, session_id=session_id)


def test_durable_fallback_reconstructs_skillstack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_agile_fixture(tmp_path)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "cross-session recover" in result.stdout
    assert "read-only" in result.stdout
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


def test_readonly_on_owner_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agi_dir = write_agile_fixture(tmp_path, owner_session_id=SID_A)

    result = recover(tmp_path)

    assert result.returncode == 0, result.stderr
    assert read_json(agi_dir / "session.json")["owner_session_id"] == SID_A
    assert read_json(snapshot_path(tmp_path))["read_only"] is True

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

    assert mutation.returncode != 0
    assert "read-only" in mutation.stderr
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
    assert "current session_id is required" in result.stderr
