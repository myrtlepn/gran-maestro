import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from scripts.mst_cmds import _common


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _prepare_state_file(tmp_path: Path, monkeypatch, pid: str = "424242") -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", pid)
    state_path = tmp_path / ".gran-maestro" / "tmp" / f"mst-state-{pid}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return state_path


def _write_state(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _authoritative_payload(
    *,
    expected_skill: str = "mst:accept",
    source_id: str = "REQ-638",
    auto_mode: bool = True,
    updated_at: Optional[str] = None,
    workflow_active: bool = True,
) -> dict:
    if updated_at is None:
        updated_at = _iso_utc(datetime.now(timezone.utc) - timedelta(minutes=5))
    return {
        "workflow_active": workflow_active,
        "next_action": {
            "expected_skill": expected_skill,
            "source_id": source_id,
            "auto_mode": auto_mode,
        },
        "updated_at": updated_at,
    }


def test_state_authoritative_accepted(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload())

    calls = []

    def _alive(pid, sig):
        calls.append((pid, sig))

    monkeypatch.setattr(_common.os, "kill", _alive)

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is True
    assert calls == [(424242, 0)]


def test_state_mismatch_skill(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload(expected_skill="mst:request"))

    def _unexpected_kill(pid, sig):  # pragma: no cover
        raise AssertionError("os.kill must not be called when expected_skill mismatches")

    monkeypatch.setattr(_common.os, "kill", _unexpected_kill)

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_state_expired_ttl(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    expired_at = _iso_utc(datetime.now(timezone.utc) - timedelta(minutes=40))
    _write_state(state_path, _authoritative_payload(updated_at=expired_at))

    def _unexpected_kill(pid, sig):  # pragma: no cover
        raise AssertionError("os.kill must not be called when ttl check fails")

    monkeypatch.setattr(_common.os, "kill", _unexpected_kill)

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_state_workflow_inactive(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload(workflow_active=False))

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_missing_state_file(tmp_path, monkeypatch):
    _prepare_state_file(tmp_path, monkeypatch)

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_corrupted_json(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    state_path.write_text("{corrupted", encoding="utf-8")

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_ppid_liveness_dead(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload())

    def _dead_process(pid, sig):
        raise ProcessLookupError("process not found")

    monkeypatch.setattr(_common.os, "kill", _dead_process)

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_source_id_mismatch(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload(source_id="REQ-999"))

    result = _common.read_workflow_state_auto_mode("mst:accept", expected_source_id="REQ-638")

    assert result is None


def test_source_id_none_allowed(tmp_path, monkeypatch):
    state_path = _prepare_state_file(tmp_path, monkeypatch)
    _write_state(state_path, _authoritative_payload(source_id="REQ-999", auto_mode=True))

    def _alive(pid, sig):
        return None

    monkeypatch.setattr(_common.os, "kill", _alive)

    result = _common.read_workflow_state_auto_mode("mst:accept")

    assert result is True


def test_is_pid_alive_helper():
    from scripts.mst_cmds._common import is_pid_alive
    import os

    assert is_pid_alive(os.getpid()) is True, "자기 PID는 alive"
    assert is_pid_alive(999999999) is False, "매우 큰 PID는 not alive"
    assert is_pid_alive(0) is False, "PID 0 거부"
    assert is_pid_alive(-1) is False, "음수 PID 거부"
    assert is_pid_alive("not-a-number") is False, "non-int input graceful False"
    assert is_pid_alive(None) is False, "None graceful False"
