import json
import hashlib
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import mst
from scripts.mst_cmds import request as request_cmds
from scripts.mst_cmds import workflow as workflow_cmds


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_request(
    base_dir: Path,
    req_id: str,
    *,
    phase: int,
    status: str,
    blocked_by=None,
    tasks=None,
    extra=None,
) -> None:
    payload = {
        "id": req_id,
        "current_phase": phase,
        "status": status,
        "dependencies": {
            "blockedBy": blocked_by or [],
            "blocks": [],
        },
    }
    if tasks is not None:
        payload["tasks"] = tasks
    if extra:
        payload.update(extra)
    _write_json(base_dir / "requests" / req_id / "request.json", payload)


def _request_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_mst(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(mst.__file__).resolve()), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def _seed_mst_session_env(monkeypatch, root: str = "REQ-001") -> None:
    monkeypatch.setenv("MST_SESSION_ID", f"MST-{root}-20260101T000000000Z-abcdefgh")


def _seed_plan(base_dir: Path, pln_id: str, linked_requests) -> None:
    _write_json(
        base_dir / "plans" / pln_id / "plan.json",
        {
            "id": pln_id,
            "linked_requests": linked_requests,
        },
    )


def test_next_action():
    # Arrange
    mapping = [
        ((1, "phase1_analysis"), "mst:approve"),
        ((1, "spec_ready"), "mst:approve"),
        ((2, "phase2_execution"), "mst:approve"),
        ((3, "phase3_review"), "mst:approve"),
        ((5, "phase5_pending"), "mst:accept"),
        ((2, "done"), None),
        ((2, "completed"), None),
        ((2, "accepted"), None),
        ((2, "cancelled"), None),
    ]

    # Act / Assert
    for (phase, status), expected in mapping:
        assert mst.next_action(phase, status) == expected


def test_stall_detection(tmp_path, monkeypatch, capsys):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    _seed_request(base_dir, "REQ-001", phase=2, status="phase2_execution")
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    calls = []

    def fake_run(cmd, capture_output, text, cwd, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mst.subprocess, "run", fake_run)

    # Act
    return_code = mst.cmd_workflow_run(Namespace(target="REQ-001"))
    captured = capsys.readouterr()

    # Assert
    assert return_code == 1
    assert len(calls) == 3
    assert "[workflow] Stalled: (phase=2, status=phase2_execution) unchanged for 3 iterations" in captured.err


def test_phase2_ready_accepts_completed_evidence_task(tmp_path, monkeypatch):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-828"
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "committed"},
            {"id": "T02", "status": "committed"},
            {"id": "T03", "status": "committed"},
            {"id": "T04", "status": "completed"},
        ],
        extra={
            "phase2_result": {"status": "pass"},
            "review_summary": {"status": "pending_phase3_review"},
        },
    )
    req_path = base_dir / "requests" / req_id / "request.json"
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    mst._sync_base_dir()

    # Act
    check_result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    checked_data = json.loads(req_path.read_text(encoding="utf-8"))
    result = request_cmds.advance_phase2_if_ready(req_id)

    # Assert
    assert check_result["advanced"] is False
    assert check_result["ready"] is True
    assert checked_data["current_phase"] == 2
    assert checked_data["status"] == "phase2_execution"
    assert result["advanced"] is True
    assert result["ready"] is True
    data = json.loads(req_path.read_text(encoding="utf-8"))
    assert data["current_phase"] == 3
    assert data["status"] == "phase3_review"
    assert data["review_summary"]["status"] == "pending_phase3_review"


def test_phase2_ready_json_guard_returns_structured_guard_block_without_mutation(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-842"
    _seed_mst_session_env(monkeypatch, req_id)
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "committed"},
            {"id": "T02", "status": "completed"},
        ],
        extra={"mst_session_id": "MST-REQ-842-20260101T000000000Z-mismatch"},
    )
    request_path = base_dir / "requests" / req_id / "request.json"
    before_hash = _request_hash(request_path)

    result = _run_mst(
        tmp_path,
        "request",
        "advance-phase2-if-ready",
        req_id,
        "--json",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "req_id": req_id,
        "ready": False,
        "advanced": False,
        "reason": "guard_blocked",
        "guard_blocked": True,
        "guard_message": "canonical read-only guard blocked phase transition",
        "incomplete_tasks": [],
    }
    assert _request_hash(request_path) == before_hash
    assert "mst_session_id mismatch" in result.stderr


@pytest.mark.parametrize("terminal_status", ["passed", "failed"])
def test_phase2_ready_preserves_terminal_review_summary(tmp_path, monkeypatch, terminal_status):
    base_dir = tmp_path / ".gran-maestro"
    req_id = f"REQ-84{3 if terminal_status == 'passed' else 4}"
    review_summary = {"iteration": 2, "status": terminal_status, "review_id": "RV-001"}
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "committed"},
            {"id": "T02", "status": "completed"},
        ],
        extra={"review_summary": review_summary},
    )
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    mst._sync_base_dir()

    result = request_cmds.advance_phase2_if_ready(req_id)

    assert result["ready"] is True
    assert result["advanced"] is True
    updated = json.loads((base_dir / "requests" / req_id / "request.json").read_text(encoding="utf-8"))
    assert updated["current_phase"] == 3
    assert updated["status"] == "phase3_review"
    assert updated["review_summary"] == review_summary


def test_phase2_ready_rejects_incomplete_task(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-900"
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "pre_check_failed"},
            {"id": "T02"},
            {"id": "T03", "status": "mystery"},
            "T04",
        ],
    )
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    mst._sync_base_dir()

    result = request_cmds.advance_phase2_if_ready(req_id)

    assert result["advanced"] is False
    assert result["ready"] is False
    assert result["reason"] == "incomplete_tasks"
    assert result["incomplete_tasks"] == [
        {"id": "T01", "status": "pre_check_failed"},
        {"id": "T02", "status": None},
        {"id": "T03", "status": "mystery"},
        {"id": None, "status": None},
    ]


@pytest.mark.parametrize(
    ("phase", "status"),
    [(5, "done"), (5, "completed"), (5, "accepted"), (2, "cancelled")],
)
def test_exit_conditions(tmp_path, monkeypatch, phase, status):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    _seed_request(base_dir, "REQ-010", phase=phase, status=status)
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})

    def fail_run(*_args, **_kwargs):
        raise AssertionError("subprocess.run should not be called for terminal states")

    monkeypatch.setattr(mst.subprocess, "run", fail_run)

    # Act
    return_code = mst.cmd_workflow_run(Namespace(target="REQ-010"))

    # Assert
    assert return_code == 0


def test_pln_mode(tmp_path, monkeypatch):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    _seed_plan(base_dir, "PLN-001", [])
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    calls = []

    def fake_run(cmd, capture_output, text, cwd, env=None):
        calls.append(cmd)
        if cmd[1] == "/mst:request":
            _seed_request(base_dir, "REQ-200", phase=2, status="phase2_execution")
            _seed_plan(base_dir, "PLN-001", ["REQ-200"])
        elif cmd[1] == "/mst:approve":
            _seed_request(base_dir, cmd[2], phase=5, status="phase5_pending")
        elif cmd[1] == "/mst:accept":
            _seed_request(base_dir, cmd[2], phase=5, status="done")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mst.subprocess, "run", fake_run)

    # Act
    return_code = mst.cmd_workflow_run(Namespace(target="PLN-001"))

    # Assert
    assert return_code == 0
    assert calls[0] == ["claude", "/mst:request", "--plan", "PLN-001", "-a"]
    assert [cmd[1] for cmd in calls if cmd[1] in {"/mst:approve", "/mst:accept"}] == [
        "/mst:approve",
        "/mst:accept",
    ]


def test_dag_chain(tmp_path, monkeypatch):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    _seed_plan(base_dir, "PLN-010", ["REQ-302", "REQ-301"])
    _seed_request(base_dir, "REQ-301", phase=2, status="phase2_execution", blocked_by=[])
    _seed_request(base_dir, "REQ-302", phase=2, status="phase2_execution", blocked_by=["REQ-301"])
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    calls = []

    def fake_run(cmd, capture_output, text, cwd, env=None):
        calls.append(cmd)
        if cmd[1] == "/mst:approve":
            _seed_request(base_dir, cmd[2], phase=5, status="phase5_pending")
        elif cmd[1] == "/mst:accept":
            _seed_request(base_dir, cmd[2], phase=5, status="done")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mst.subprocess, "run", fake_run)

    # Act
    return_code = mst.cmd_workflow_run(Namespace(target="PLN-010"))

    # Assert
    assert return_code == 0
    approve_order = [cmd[2] for cmd in calls if cmd[1] == "/mst:approve"]
    assert approve_order == ["REQ-301", "REQ-302"]


def test_max_iterations(tmp_path, monkeypatch, capsys):
    # Arrange
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-777"
    req_path = base_dir / "requests" / req_id / "request.json"
    _seed_request(base_dir, req_id, phase=2, status="phase2_execution")
    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    monkeypatch.setattr(workflow_cmds, "_validated_claude_child_env", lambda: {})
    calls = []
    toggle = {"value": False}

    def fake_run(cmd, capture_output, text, cwd, env=None):
        calls.append(cmd)
        data = json.loads(req_path.read_text(encoding="utf-8"))
        if toggle["value"]:
            data["current_phase"] = 2
            data["status"] = "phase2_execution"
        else:
            data["current_phase"] = 3
            data["status"] = "phase3_review"
        toggle["value"] = not toggle["value"]
        req_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mst.subprocess, "run", fake_run)

    # Act
    return_code = mst.cmd_workflow_run(Namespace(target=req_id))
    captured = capsys.readouterr()

    # Assert
    assert return_code == 1
    assert len(calls) == mst.WORKFLOW_MAX_ITERATIONS
    assert f"[workflow] Max iterations ({mst.WORKFLOW_MAX_ITERATIONS}) reached" in captured.err
