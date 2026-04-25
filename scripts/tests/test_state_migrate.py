"""Test state migrate CLI (PLN-557, REQ-728)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_PY = str(REPO_ROOT / "scripts" / "mst.py")


def _run(env_base: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> subprocess.CompletedProcess[str]:
    monkeypatch.setenv("MST_BASE_DIR", str(env_base))
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, MST_PY, *args],
        cwd=env_base,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _setup_legacy(tmp_path: Path, *, ppid: int = 12345, sid: str = "sid-001") -> None:
    _write_json(
        tmp_path / ".gran-maestro" / "state" / str(ppid) / "snapshot.json",
        {"owner_ppid": ppid, "owner_session_id": sid},
    )
    _write_json(
        tmp_path / ".gran-maestro" / "agile" / "AGI-001" / "objective" / "objective.json",
        {"id": "AGI-001", "owner_ppid": ppid},
    )
    _write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-001" / "request.json",
        {"id": "REQ-001", "owner_ppid": ppid},
    )
    _write_json(
        tmp_path / ".gran-maestro" / "plans" / "PLN-001" / "plan.json",
        {"id": "PLN-001", "owner_ppid": ppid},
    )


def _backup_dirs(tmp_path: Path) -> list[Path]:
    backups = tmp_path / ".gran-maestro" / "backups"
    if not backups.is_dir():
        return []
    return sorted(path for path in backups.iterdir() if path.is_dir() and path.name.startswith("state-migrate-"))


def test_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_legacy(tmp_path)

    dry = _run(tmp_path, monkeypatch, "state", "migrate", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    payload = json.loads(dry.stdout)
    assert len(payload["targets"]) == 4
    assert [target["type"] for target in payload["targets"]].count("rename_dir") == 1
    assert [target["type"] for target in payload["targets"]].count("json_field") == 3

    assert (tmp_path / ".gran-maestro" / "state" / "12345" / "snapshot.json").is_file()
    assert not (tmp_path / ".gran-maestro" / "state" / "sid-001").exists()

    actual = _run(tmp_path, monkeypatch, "state", "migrate")
    assert actual.returncode == 0, actual.stderr
    assert (tmp_path / ".gran-maestro" / "state" / "sid-001" / "snapshot.json").is_file()
    assert not (tmp_path / ".gran-maestro" / "state" / "12345").exists()

    for path in [
        tmp_path / ".gran-maestro" / "agile" / "AGI-001" / "objective" / "objective.json",
        tmp_path / ".gran-maestro" / "requests" / "REQ-001" / "request.json",
        tmp_path / ".gran-maestro" / "plans" / "PLN-001" / "plan.json",
    ]:
        data = _read_json(path)
        assert data.get("owner_session_id") == "sid-001"
        assert "owner_ppid" not in data

    assert _backup_dirs(tmp_path)
    assert list((tmp_path / ".gran-maestro" / "logs").glob("state-migrate-*.log"))

    verify = _run(tmp_path, monkeypatch, "state", "migrate", "--verify")
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["status"] == "PASS"


def test_rollback_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_legacy(tmp_path)
    original_snapshot = (tmp_path / ".gran-maestro" / "state" / "12345" / "snapshot.json").read_bytes()

    actual = _run(tmp_path, monkeypatch, "state", "migrate")
    assert actual.returncode == 0, actual.stderr

    rollback = _run(tmp_path, monkeypatch, "state", "migrate", "--rollback")
    assert rollback.returncode == 0, rollback.stderr

    restored_snapshot = tmp_path / ".gran-maestro" / "state" / "12345" / "snapshot.json"
    assert restored_snapshot.is_file()
    assert restored_snapshot.read_bytes() == original_snapshot

    for path in [
        tmp_path / ".gran-maestro" / "agile" / "AGI-001" / "objective" / "objective.json",
        tmp_path / ".gran-maestro" / "requests" / "REQ-001" / "request.json",
        tmp_path / ".gran-maestro" / "plans" / "PLN-001" / "plan.json",
    ]:
        data = _read_json(path)
        assert data.get("owner_ppid") == 12345


def test_idempotent_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_legacy(tmp_path)

    first = _run(tmp_path, monkeypatch, "state", "migrate")
    assert first.returncode == 0, first.stderr
    backups_after_first = _backup_dirs(tmp_path)

    second = _run(tmp_path, monkeypatch, "state", "migrate")
    assert second.returncode == 0, second.stderr
    assert "no_changes" in second.stdout or "0 item" in second.stdout
    assert len(_backup_dirs(tmp_path)) == len(backups_after_first)


def test_verify_fail_when_legacy_remains(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_json(tmp_path / ".gran-maestro" / "state" / "99999" / "snapshot.json", {"x": 1})

    verify = _run(tmp_path, monkeypatch, "state", "migrate", "--verify")
    assert verify.returncode != 0
    payload = json.loads(verify.stdout)
    assert payload["status"] == "FAIL"
    assert any("numeric_ppid_dir_remains" in issue for issue in payload["issues"])


def test_doctor_warns_on_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_json(tmp_path / ".gran-maestro" / "state" / "12345" / "snapshot.json", {})
    _write_json(
        tmp_path / ".gran-maestro" / "requests" / "REQ-001" / "request.json",
        {"id": "REQ-001", "owner_ppid": 12345},
    )

    result = _run(tmp_path, monkeypatch, "hooks", "doctor")
    combined = result.stdout + result.stderr
    assert "legacy PPID state 감지" in combined
    assert "migrate --dry-run" in combined


def test_doctor_silent_when_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".gran-maestro").mkdir(parents=True)

    result = _run(tmp_path, monkeypatch, "hooks", "doctor")
    combined = result.stdout + result.stderr
    assert "legacy PPID state 감지" not in combined


def test_mutually_exclusive_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run(tmp_path, monkeypatch, "state", "migrate", "--dry-run", "--verify")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not allowed" in combined.lower() or "argument" in combined.lower()
