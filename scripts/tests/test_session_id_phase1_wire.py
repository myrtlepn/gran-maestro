from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from scripts._skill_state import _base_snapshot
from scripts.mst_cmds import _common
from scripts.mst_cmds.agile import cmd_agile_init
from scripts.mst_cmds.state import (
    _inject_owner_metadata_to_json,
    _resolve_owner_session_id,
)


UUID_V4 = "123e4567-e89b-42d3-a456-426614174000"
UUID_V1 = "aaaaaaaa-bbbb-1ccc-8ddd-eeeeeeeeeeee"
STRUCTURED_OWNER_SESSION_ID = "MST-REQ-864-20260515T000000000Z-a1b2c3d4"
REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _set_base_dir(monkeypatch, tmp_path: Path) -> Path:
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    return base_dir


def test_base_snapshot_has_owner_metadata(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    ppid = 4242
    bridge_path = base_dir / "tmp" / f"claude-session-{ppid}.id"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(UUID_V4, encoding="utf-8")
    monkeypatch.setenv("MST_STATE_PPID", str(ppid))

    snapshot = _base_snapshot("test-session-uuid")

    assert snapshot["sessionId"] == "test-session-uuid"
    assert "owner_ppid" in snapshot
    assert isinstance(snapshot["owner_ppid"], int)
    assert snapshot["owner_ppid"] == ppid
    assert "owner_session_id" in snapshot
    assert snapshot["owner_session_id"] == UUID_V4


def test_agile_init_writes_owner_metadata(tmp_path: Path, monkeypatch, capsys) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    ppid = 5252
    bridge_path = base_dir / "tmp" / f"claude-session-{ppid}.id"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(UUID_V4, encoding="utf-8")
    monkeypatch.setenv("MST_STATE_PPID", str(ppid))

    exit_code = cmd_agile_init(SimpleNamespace(steering_every=3, json=False))
    capsys.readouterr()

    assert exit_code == 0
    session_path = base_dir / "agile" / "AGI-001" / "session.json"
    session = _read_json(session_path)
    assert "owner_ppid" in session
    assert "owner_session_id" in session
    assert session["owner_ppid"] == ppid
    assert session["owner_session_id"] == UUID_V4


def test_inject_owner_metadata_idempotent(tmp_path: Path) -> None:
    json_path = tmp_path / "requests" / "REQ-722" / "request.json"
    _write_json(json_path, {"id": "REQ-722", "title": "wire check"})

    _inject_owner_metadata_to_json(json_path, 1111, UUID_V4)
    first = _read_json(json_path)
    _inject_owner_metadata_to_json(json_path, 2222, None)
    second = _read_json(json_path)

    assert first["owner_ppid"] == 1111
    assert first["owner_session_id"] == UUID_V4
    assert second == first


def test_resolve_owner_session_id_uuid_v4_only(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    ppid = 6363
    bridge_path = base_dir / "tmp" / f"claude-session-{ppid}.id"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)

    cases = [
        (UUID_V4, UUID_V4),
        ("", None),
        ("not-a-uuid", None),
        (UUID_V1, None),
    ]

    for raw_value, expected in cases:
        bridge_path.write_text(raw_value, encoding="utf-8")
        assert _resolve_owner_session_id(ppid) == expected


def test_existing_owner_ppid_preserved(tmp_path: Path) -> None:
    json_path = tmp_path / "requests" / "REQ-722" / "request.json"
    _write_json(
        json_path,
        {
            "id": "REQ-722",
            "owner_ppid": 7777,
        },
    )

    _inject_owner_metadata_to_json(json_path, 8888, UUID_V4)
    payload = _read_json(json_path)

    assert payload["owner_ppid"] == 7777
    assert payload["owner_session_id"] == UUID_V4


def test_mst_request_creates_request_json_with_owner_session_id(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: mst.py 신규 request 생성 경로가 owner_session_id 키를 채우는지 subprocess로 검증."""
    repo_root = tmp_path
    base_dir = repo_root / ".gran-maestro"
    request_path = base_dir / "requests" / "REQ-722" / "request.json"
    ppid = 7373

    monkeypatch.setenv("MST_STATE_PPID", str(ppid))
    monkeypatch.delenv("MST_SNAPSHOT_SESSION_ID", raising=False)

    bridge_path = base_dir / "tmp" / f"claude-session-{ppid}.id"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(UUID_V4, encoding="utf-8")
    _write_json(request_path, {"id": "REQ-722", "title": "wire check"})

    result = subprocess.run(
        [
            sys.executable,
            str(MST),
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:dispatch",
            "--req",
            "REQ-722",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    result_payload = json.loads(result.stdout)
    assert result_payload["status"] == "partial"
    assert result_payload["code"] == "owner_metadata_injected_without_workflow_state"
    assert result_payload["mutation_performed"] is True
    assert result_payload["workflow_state_written"] is False
    payload = _read_json(request_path)

    assert "owner_session_id" in payload
    assert payload["owner_session_id"] == UUID_V4
    assert "owner_ppid" in payload
    assert payload["owner_ppid"] == ppid


def test_mst_plan_branch_injects_owner_metadata(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: mst.py plan 분기가 기존 plan.json에 owner metadata를 주입하는지 검증."""
    repo_root = tmp_path
    base_dir = repo_root / ".gran-maestro"
    plan_path = base_dir / "plans" / "PLN-TEST" / "plan.json"
    ppid = 7373

    monkeypatch.setenv("MST_STATE_PPID", str(ppid))
    monkeypatch.delenv("MST_SNAPSHOT_SESSION_ID", raising=False)

    bridge_path = base_dir / "tmp" / f"claude-session-{ppid}.id"
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    bridge_path.write_text(UUID_V4, encoding="utf-8")
    _write_json(plan_path, {"id": "PLN-TEST", "title": "wire plan check"})

    result = subprocess.run(
        [
            sys.executable,
            str(MST),
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:plan",
            "--next-skill",
            "mst:request",
            "--next-source",
            "PLN-TEST",
            "--source-skill",
            "mst:plan",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    result_payload = json.loads(result.stdout)
    assert result_payload["status"] == "partial"
    assert result_payload["code"] == "owner_metadata_injected_without_workflow_state"
    assert result_payload["mutation_performed"] is True
    assert result_payload["workflow_state_written"] is False
    payload = _read_json(plan_path)

    assert "owner_session_id" in payload
    assert payload["owner_session_id"] == UUID_V4
    assert "owner_ppid" in payload
    assert payload["owner_ppid"] == ppid


def test_mst_request_repairs_stale_owner_metadata_with_canonical_env(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path
    base_dir = repo_root / ".gran-maestro"
    request_path = base_dir / "requests" / "REQ-864" / "request.json"
    ppid = 7474

    monkeypatch.setenv("MST_STATE_PPID", str(ppid))
    monkeypatch.setenv("MST_SESSION_ID", STRUCTURED_OWNER_SESSION_ID)
    monkeypatch.delenv("MST_SNAPSHOT_SESSION_ID", raising=False)

    _write_json(
        request_path,
        {
            "id": "REQ-864",
            "title": "repair check",
            "owner_ppid": ppid,
            "owner_session_id": None,
            "owner_resolution": {
                "reason": "bridge_missing",
                "action": "retry",
            },
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MST),
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:dispatch",
            "--req",
            "REQ-864",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = _read_json(request_path)
    assert payload["owner_session_id"] == STRUCTURED_OWNER_SESSION_ID
    assert payload["owner_resolution"]["reason"] == "repaired_from_canonical_identity"
    assert payload["owner_resolution"]["action"] == "converged_owner_session_id"
