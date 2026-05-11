from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import request as request_cmds


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


REQUIRED_ATTEMPT_FIELDS = (
    "attempt_id",
    "dispatched_at",
    "agent",
    "worktree_path",
    "log_path",
    "expected_task_status_before",
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_base_dir(tmp_path: Path) -> Path:
    base_dir = tmp_path / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _set_base_dir(monkeypatch, tmp_path: Path) -> Path:
    base_dir = _make_base_dir(tmp_path)
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    return base_dir


def _seed_request(
    base_dir: Path,
    req_id: str,
    *,
    phase: int,
    status: str,
    tasks: list[dict],
    extra: dict | None = None,
) -> Path:
    payload = {
        "id": req_id,
        "current_phase": phase,
        "status": status,
        "tasks": tasks,
        "dependencies": {
            "blockedBy": [],
            "blocks": [],
        },
    }
    if extra:
        payload.update(extra)
    request_path = base_dir / "requests" / req_id / "request.json"
    _write_json(request_path, payload)
    return request_path


def _record_phase2_dispatch_attempt(req_id: str, **kwargs):
    recorder = getattr(request_cmds, "record_phase2_dispatch_attempt", None)
    if recorder is None:
        recorder = getattr(_common, "record_phase2_dispatch_attempt", None)
    assert callable(
        recorder
    ), "missing record_phase2_dispatch_attempt(req_id, **kwargs) dispatch metadata writer"
    return recorder(req_id, **kwargs)


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def _background_attempts(request_data: dict) -> list[dict]:
    attempts = request_data.get("background_task_ids")
    assert isinstance(attempts, list), "request.json must preserve background_task_ids as a list"
    return attempts


def _attempts_for_task_num(request_data: dict, task_num: str) -> list[dict]:
    return [
        attempt
        for attempt in _background_attempts(request_data)
        if isinstance(attempt, dict) and str(attempt.get("task_num") or "") == str(task_num)
    ]


def test_phase2_metadata_records_required_dispatch_attempt_fields(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-854"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending"}],
        extra={"background_task_ids": []},
    )

    _record_phase2_dispatch_attempt(
        req_id,
        task_num="01",
        task_id="bg-task-001",
        attempt_id="attempt-001",
        dispatched_at="2026-05-11T00:00:00Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-854-T01",
        log_path="/tmp/REQ-854-T01/running.log",
        expected_task_status_before="pending",
    )

    request_data = _read_json(request_path)
    attempts = _attempts_for_task_num(request_data, "01")

    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["task_id"] == "bg-task-001"
    for field in REQUIRED_ATTEMPT_FIELDS:
        assert attempt.get(field), f"missing attempt metadata field: {field}"
    assert attempt["attempt_id"] == "attempt-001"
    assert attempt["dispatched_at"] == "2026-05-11T00:00:00Z"
    assert attempt["agent"] == "codex-dev"
    assert attempt["worktree_path"] == "/tmp/REQ-854-T01"
    assert attempt["log_path"] == "/tmp/REQ-854-T01/running.log"
    assert attempt["expected_task_status_before"] == "pending"

    task_attempts = request_data["tasks"][0]["attempts"]
    assert len(task_attempts) == 1
    assert task_attempts[0]["attempt_id"] == "attempt-001"
    assert task_attempts[0]["task_id"] == "bg-task-001"
    assert task_attempts[0]["task_num"] == "01"
    assert task_attempts[0]["expected_task_status_before"] == "pending"


def test_phase2_metadata_cli_records_dispatch_attempt_fields(tmp_path: Path) -> None:
    base_dir = _make_base_dir(tmp_path)
    req_id = "REQ-860"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending"}],
        extra={"background_task_ids": []},
    )

    result = _run_mst(
        tmp_path,
        "request",
        "record-phase2-dispatch-attempt",
        req_id,
        "--task-num",
        "01",
        "--task-id",
        "bg-task-cli-001",
        "--attempt-id",
        "attempt-cli-001",
        "--dispatched-at",
        "2026-05-11T00:00:00Z",
        "--agent",
        "codex-dev",
        "--worktree-path",
        "/tmp/REQ-860-T01",
        "--log-path",
        "/tmp/REQ-860-T01/running.log",
        "--expected-task-status-before",
        "pending",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    assert stdout_payload["attempt_id"] == "attempt-cli-001"
    assert stdout_payload["task_id"] == "bg-task-cli-001"
    assert stdout_payload["task_num"] == "01"
    assert stdout_payload["status"] == "running"

    request_data = _read_json(request_path)
    attempts = _attempts_for_task_num(request_data, "01")

    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["task_id"] == "bg-task-cli-001"
    for field in REQUIRED_ATTEMPT_FIELDS:
        assert attempt.get(field), f"missing attempt metadata field: {field}"

    task_attempts = request_data["tasks"][0]["attempts"]
    assert len(task_attempts) == 1
    assert task_attempts[0]["attempt_id"] == "attempt-cli-001"
    assert task_attempts[0]["task_id"] == "bg-task-cli-001"
    assert task_attempts[0]["task_num"] == "01"


def test_phase2_metadata_distinguishes_multitask_and_retry_attempts(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-855"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "pending"},
            {"id": "T02", "status": "pending"},
        ],
        extra={"background_task_ids": []},
    )

    _record_phase2_dispatch_attempt(
        req_id,
        task_num="01",
        task_id="bg-task-001",
        attempt_id="attempt-001",
        dispatched_at="2026-05-11T00:00:00Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-855-T01-A1",
        log_path="/tmp/REQ-855-T01-A1/running.log",
        expected_task_status_before="pending",
    )
    _record_phase2_dispatch_attempt(
        req_id,
        task_num="02",
        task_id="bg-task-002",
        attempt_id="attempt-002",
        dispatched_at="2026-05-11T00:00:10Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-855-T02-A1",
        log_path="/tmp/REQ-855-T02-A1/running.log",
        expected_task_status_before="pending",
    )
    _record_phase2_dispatch_attempt(
        req_id,
        task_num="01",
        task_id="bg-task-003",
        attempt_id="attempt-003",
        dispatched_at="2026-05-11T00:01:00Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-855-T01-A2",
        log_path="/tmp/REQ-855-T01-A2/running.log",
        expected_task_status_before="pending",
    )

    request_data = _read_json(request_path)
    attempts_task_01 = _attempts_for_task_num(request_data, "01")
    attempts_task_02 = _attempts_for_task_num(request_data, "02")

    assert len(_background_attempts(request_data)) == 3
    assert len(attempts_task_01) == 2
    assert len(attempts_task_02) == 1
    assert {attempt["attempt_id"] for attempt in attempts_task_01} == {
        "attempt-001",
        "attempt-003",
    }
    assert {attempt["task_id"] for attempt in attempts_task_01} == {
        "bg-task-001",
        "bg-task-003",
    }
    assert attempts_task_02[0]["attempt_id"] == "attempt-002"

    tasks_by_id = {task["id"]: task for task in request_data["tasks"]}
    assert [attempt["attempt_id"] for attempt in tasks_by_id["T01"]["attempts"]] == [
        "attempt-001",
        "attempt-003",
    ]
    assert [attempt["attempt_id"] for attempt in tasks_by_id["T02"]["attempts"]] == [
        "attempt-002"
    ]


def test_phase2_metadata_rejects_duplicate_attempt_ids_within_request(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-857"
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "pending"},
            {"id": "T02", "status": "pending"},
        ],
        extra={"background_task_ids": []},
    )

    _record_phase2_dispatch_attempt(
        req_id,
        task_num="01",
        task_id="bg-task-001",
        attempt_id="attempt-dup-001",
        dispatched_at="2026-05-11T00:00:00Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-857-T01-A1",
        log_path="/tmp/REQ-857-T01-A1/running.log",
        expected_task_status_before="pending",
    )

    try:
        _record_phase2_dispatch_attempt(
            req_id,
            task_num="02",
            task_id="bg-task-002",
            attempt_id="attempt-dup-001",
            dispatched_at="2026-05-11T00:01:00Z",
            agent="codex-dev",
            worktree_path="/tmp/REQ-857-T02-A1",
            log_path="/tmp/REQ-857-T02-A1/running.log",
            expected_task_status_before="pending",
        )
    except ValueError as exc:
        assert "duplicate phase2 dispatch attempt_id" in str(exc)
    else:
        raise AssertionError("duplicate attempt_id within the same request must fail")


def test_phase2_metadata_rejects_duplicate_attempt_ids_from_other_task_attempts_even_when_background_stale(
    tmp_path: Path,
) -> None:
    base_dir = _make_base_dir(tmp_path)
    req_id = "REQ-861"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {
                "id": "T01",
                "status": "completed",
                "attempts": [
                    {
                        "attempt_id": "attempt-stale-001",
                        "task_id": "bg-task-existing-001",
                        "task_num": "01",
                        "dispatched_at": "2026-05-11T00:00:00Z",
                        "agent": "codex-dev",
                        "worktree_path": "/tmp/REQ-861-T01-A1",
                        "log_path": "/tmp/REQ-861-T01-A1/running.log",
                        "expected_task_status_before": "pending",
                        "status": "completed",
                    }
                ],
            },
            {"id": "T02", "status": "pending"},
        ],
        extra={"background_task_ids": []},
    )

    result = _run_mst(
        tmp_path,
        "request",
        "record-phase2-dispatch-attempt",
        req_id,
        "--task-num",
        "02",
        "--task-id",
        "bg-task-new-002",
        "--attempt-id",
        "attempt-stale-001",
        "--dispatched-at",
        "2026-05-11T00:01:00Z",
        "--agent",
        "codex-dev",
        "--worktree-path",
        "/tmp/REQ-861-T02-A1",
        "--log-path",
        "/tmp/REQ-861-T02-A1/running.log",
        "--expected-task-status-before",
        "pending",
        "--json",
    )

    assert result.returncode != 0
    assert "duplicate phase2 dispatch attempt_id" in result.stderr

    request_data = _read_json(request_path)
    assert request_data["background_task_ids"] == []
    tasks_by_id = {task["id"]: task for task in request_data["tasks"]}
    assert [attempt["attempt_id"] for attempt in tasks_by_id["T01"]["attempts"]] == [
        "attempt-stale-001"
    ]
    assert "attempts" not in tasks_by_id["T02"]


def test_phase2_metadata_appends_without_overwriting_existing_background_contract(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-858"
    existing_attempt = {
        "attempt_id": "attempt-existing-001",
        "task_id": "bg-task-existing-001",
        "task_num": "01",
        "dispatched_at": "2026-05-11T00:00:00Z",
        "agent": "codex-dev",
        "worktree_path": "/tmp/REQ-858-T01-A1",
        "log_path": "/tmp/REQ-858-T01-A1/running.log",
        "expected_task_status_before": "pending",
        "status": "completed",
    }
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "completed", "attempts": [dict(existing_attempt)]},
            {"id": "T02", "status": "pending"},
        ],
        extra={"background_task_ids": [dict(existing_attempt)]},
    )

    _record_phase2_dispatch_attempt(
        req_id,
        task_num="02",
        task_id="bg-task-002",
        attempt_id="attempt-002",
        dispatched_at="2026-05-11T00:01:00Z",
        agent="codex-dev",
        worktree_path="/tmp/REQ-858-T02-A1",
        log_path="/tmp/REQ-858-T02-A1/running.log",
        expected_task_status_before="pending",
    )

    request_data = _read_json(request_path)
    background_attempts = _background_attempts(request_data)

    assert [attempt["attempt_id"] for attempt in background_attempts] == [
        "attempt-existing-001",
        "attempt-002",
    ]

    tasks_by_id = {task["id"]: task for task in request_data["tasks"]}
    assert [attempt["attempt_id"] for attempt in tasks_by_id["T01"]["attempts"]] == [
        "attempt-existing-001"
    ]
    assert [attempt["attempt_id"] for attempt in tasks_by_id["T02"]["attempts"]] == [
        "attempt-002"
    ]
    assert tasks_by_id["T02"]["attempts"][0]["task_num"] == "02"


def test_phase2_metadata_does_not_regress_advance_ready_gate(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-856"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "committed"},
            {"id": "T02", "status": "completed"},
        ],
        extra={
            "background_task_ids": [
                {
                    "task_id": "bg-task-101",
                    "task_num": "01",
                    "attempt_id": "attempt-101",
                    "dispatched_at": "2026-05-11T00:00:00Z",
                    "agent": "codex-dev",
                    "worktree_path": "/tmp/REQ-856-T01-A1",
                    "log_path": "/tmp/REQ-856-T01-A1/running.log",
                    "expected_task_status_before": "pending",
                    "status": "running",
                },
                {
                    "task_id": "bg-task-102",
                    "task_num": "02",
                    "attempt_id": "attempt-102",
                    "dispatched_at": "2026-05-11T00:00:10Z",
                    "agent": "codex-dev",
                    "worktree_path": "/tmp/REQ-856-T02-A1",
                    "log_path": "/tmp/REQ-856-T02-A1/running.log",
                    "expected_task_status_before": "pending",
                    "status": "completed",
                },
            ],
            "review_summary": {"status": "pending_phase3_review"},
        },
    )

    before = _read_json(request_path)
    check_result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    after_check = _read_json(request_path)
    apply_result = request_cmds.advance_phase2_if_ready(req_id)
    after_apply = _read_json(request_path)

    assert check_result["ready"] is True
    assert check_result["advanced"] is False
    assert after_check["background_task_ids"] == before["background_task_ids"]

    assert apply_result["ready"] is True
    assert apply_result["advanced"] is True
    assert after_apply["current_phase"] == 3
    assert after_apply["status"] == "phase3_review"
    assert after_apply["background_task_ids"] == before["background_task_ids"]
