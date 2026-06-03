from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def _git(repo_root: Path, *args: str) -> str:
    result = _run_git(repo_root, *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _ensure_git_repo(repo_root: Path) -> None:
    if (repo_root / ".git").exists():
        return
    assert _run_git(repo_root, "init").returncode == 0
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    _git(repo_root, "commit", "--allow-empty", "-m", "initial")
    _git(repo_root, "branch", "-M", "main")


def _phase2_evidence_task(repo_root: Path, req_id: str, task_id: str, status: str) -> dict:
    _ensure_git_repo(repo_root)
    branch = f"gran-maestro/main/{req_id}-{task_id}"
    _git(repo_root, "checkout", "-B", branch, "main")
    (repo_root / f"{req_id}-{task_id}.txt").write_text(f"{req_id} {task_id}\n", encoding="utf-8")
    _git(repo_root, "add", f"{req_id}-{task_id}.txt")
    _git(repo_root, "commit", "-m", f"[{req_id}/{task_id}] evidence")
    commit_hash = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "checkout", "main")
    return {"id": task_id, "status": status, "commit_hash": commit_hash, "branch": branch}


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


def _pending_queue_path(base_dir: Path) -> Path:
    return base_dir / "pending.ndjson"


def _read_pending_queue(base_dir: Path) -> list[dict]:
    queue_path = _pending_queue_path(base_dir)
    if not queue_path.exists():
        return []
    entries = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        entries.append(json.loads(text))
    return entries


def _write_pending_queue(base_dir: Path, entries: list[dict]) -> None:
    queue_path = _pending_queue_path(base_dir)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


def _make_phase2_attempt(
    *,
    task_num: str = "01",
    task_id: str = "bg-task-queue-001",
    attempt_id: str = "attempt-queue-001",
    dispatched_at: str = "2026-05-11T00:00:00Z",
    agent: str = "codex-dev",
    worktree_path: str = "/tmp/REQ-855-T01",
    log_path: str = "/tmp/REQ-855-T01/running.log",
    expected_task_status_before: str = "pending",
    status: str = "running",
) -> dict:
    return {
        "task_num": task_num,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "dispatched_at": dispatched_at,
        "agent": agent,
        "worktree_path": worktree_path,
        "log_path": log_path,
        "expected_task_status_before": expected_task_status_before,
        "status": status,
    }


def _task_attempt_from_background_attempt(attempt: dict) -> dict:
    task_attempt = {
        "attempt_id": attempt["attempt_id"],
        "task_id": attempt["task_id"],
        "task_num": attempt["task_num"],
        "dispatched_at": attempt["dispatched_at"],
        "agent": attempt["agent"],
        "worktree_path": attempt["worktree_path"],
        "log_path": attempt["log_path"],
        "expected_task_status_before": attempt["expected_task_status_before"],
        "status": attempt["status"],
    }
    if attempt.get("run_state_path") is not None:
        task_attempt["run_state_path"] = attempt["run_state_path"]
    return task_attempt


def _make_reconcile_action(
    req_id: str,
    attempt: dict,
    *,
    created_at: str = "2026-05-11T00:00:30Z",
    status: str = "queued",
    source: str = "phase2_dispatch",
) -> dict:
    return {
        "kind": "reconcile_phase2",
        "req_id": req_id,
        "attempt_id": attempt["attempt_id"],
        "created_at": created_at,
        "source": source,
        "status": status,
        "task_num": attempt["task_num"],
        "task_id": attempt["task_id"],
        "log_path": attempt["log_path"],
        "worktree_path": attempt["worktree_path"],
    }


def _invoke_reconcile_queue_upsert(req_id: str, attempt: dict):
    candidates = (
        getattr(request_cmds, "upsert_reconcile_phase2_action", None),
        getattr(_common, "upsert_reconcile_phase2_action", None),
        getattr(request_cmds, "queue_reconcile_phase2_action", None),
        getattr(_common, "queue_reconcile_phase2_action", None),
        getattr(request_cmds, "ensure_reconcile_phase2_action", None),
        getattr(_common, "ensure_reconcile_phase2_action", None),
    )
    helper = next((candidate for candidate in candidates if callable(candidate)), None)
    assert callable(helper), "missing reconcile queue upsert helper for Phase 2 continuation"
    try:
        return helper(req_id, attempt=attempt)
    except TypeError:
        return helper(req_id, **attempt)


def _assert_reconcile_queue_action_matches(action: dict, req_id: str, attempt: dict) -> None:
    assert action["kind"] == "reconcile_phase2"
    assert action["req_id"] == req_id
    assert action["attempt_id"] == attempt["attempt_id"]
    assert isinstance(action.get("created_at"), str) and action["created_at"]
    assert isinstance(action.get("source"), str) and action["source"]
    assert action["status"] == "queued"
    assert action["task_num"] == attempt["task_num"]
    assert action["task_id"] == attempt["task_id"]
    assert action["log_path"] == attempt["log_path"]
    assert action["worktree_path"] == attempt["worktree_path"]


def _assert_observable_noop_reason(result: object, request_data: dict) -> None:
    serialized_result = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    serialized_request = json.dumps(request_data, ensure_ascii=False, sort_keys=True)
    observable = serialized_result + "\n" + serialized_request
    assert "reason" in observable or "manual_reconcile_required" in observable, (
        "terminal/blocked duplicate or partial-state fallback must leave an observable reason"
    )


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


def test_phase2_queue_dispatch_attempt_writes_reconcile_action(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending"}],
        extra={"background_task_ids": []},
    )

    attempt = _make_phase2_attempt()
    _record_phase2_dispatch_attempt(req_id, **attempt)

    entries = _read_pending_queue(base_dir)

    assert len(entries) == 1
    _assert_reconcile_queue_action_matches(entries[0], req_id, attempt)


@pytest.mark.parametrize("existing_status", ["queued", "running", " Queued ", "RUNNING"])
def test_phase2_queue_duplicate_queued_or_running_attempt_is_noop(
    tmp_path: Path, monkeypatch, existing_status: str
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _make_phase2_attempt(status="running")
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {
                "id": "T01",
                "status": "pending",
                "attempts": [_task_attempt_from_background_attempt(attempt)],
            }
        ],
        extra={"background_task_ids": [dict(attempt)]},
    )
    existing_action = _make_reconcile_action(req_id, attempt, status=existing_status)
    _write_pending_queue(base_dir, [existing_action])

    result = _invoke_reconcile_queue_upsert(req_id, attempt)
    after_entries = _read_pending_queue(base_dir)

    assert result is not None
    assert after_entries == [existing_action]


@pytest.mark.parametrize(
    "existing_status",
    [
        "done",
        "cancelled",
        "blocked",
        "version_skew_blocked",
        " Done ",
        "CANCELLED",
        " Blocked ",
        "VERSION_SKEW_BLOCKED",
    ],
)
def test_phase2_queue_duplicate_terminal_or_blocked_attempt_is_noop_with_reason(
    tmp_path: Path, monkeypatch, existing_status: str
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _make_phase2_attempt()
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {
                "id": "T01",
                "status": "pending",
                "attempts": [_task_attempt_from_background_attempt(attempt)],
            }
        ],
        extra={"background_task_ids": [dict(attempt)]},
    )
    existing_action = _make_reconcile_action(req_id, attempt, status=existing_status)
    _write_pending_queue(base_dir, [existing_action])

    result = _invoke_reconcile_queue_upsert(req_id, attempt)
    after_entries = _read_pending_queue(base_dir)
    request_data = _read_json(request_path)

    assert after_entries == [existing_action]
    _assert_observable_noop_reason(result, request_data)


def test_phase2_queue_partial_state_metadata_only_is_backfilled_or_marked_manual_reason(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _make_phase2_attempt()
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {
                "id": "T01",
                "status": "pending",
                "attempts": [_task_attempt_from_background_attempt(attempt)],
            }
        ],
        extra={"background_task_ids": [dict(attempt)]},
    )

    result = _invoke_reconcile_queue_upsert(req_id, attempt)
    entries = _read_pending_queue(base_dir)
    request_data = _read_json(request_path)

    if entries:
        assert len(entries) == 1
        _assert_reconcile_queue_action_matches(entries[0], req_id, attempt)
    else:
        _assert_observable_noop_reason(result, request_data)

def test_phase2_queue_continuation_check_backfills_metadata_only_request_state(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _make_phase2_attempt()
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending"}],
        extra={"background_task_ids": [dict(attempt)]},
    )

    before = _read_json(request_path)
    result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    after = _read_json(request_path)
    entries = _read_pending_queue(base_dir)

    assert result["ready"] is False
    assert result["reason"] == "incomplete_tasks"
    assert len(entries) == 1
    _assert_reconcile_queue_action_matches(entries[0], req_id, attempt)
    assert result["reconcile_queue"]["created_count"] == 1
    assert result["reconcile_queue"]["manual_reconcile_required"] is False
    assert after == before

def test_phase2_queue_continuation_check_backfills_task_level_only_attempt(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _task_attempt_from_background_attempt(_make_phase2_attempt())
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending", "attempts": [attempt]}],
        extra={},
    )

    before = _read_json(request_path)
    result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    after = _read_json(request_path)
    entries = _read_pending_queue(base_dir)

    assert result["ready"] is False
    assert result["reason"] == "incomplete_tasks"
    assert len(entries) == 1
    _assert_reconcile_queue_action_matches(entries[0], req_id, attempt)
    assert result["reconcile_queue"]["attempt_count"] == 1
    assert result["reconcile_queue"]["created_count"] == 1
    assert result["reconcile_queue"]["manual_reconcile_required"] is False
    assert after == before


def test_phase2_queue_continuation_reports_manual_reason_for_incomplete_task_level_attempt(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    attempt = _task_attempt_from_background_attempt(_make_phase2_attempt())
    del attempt["log_path"]
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[{"id": "T01", "status": "pending", "attempts": [attempt]}],
        extra={},
    )

    result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    entries = _read_pending_queue(base_dir)

    assert result["ready"] is False
    assert result["reason"] == "incomplete_tasks"
    assert entries == []
    assert result["reconcile_queue"]["attempt_count"] == 1
    assert result["reconcile_queue"]["manual_reconcile_required"] is True
    assert result["reconcile_queue"]["results"][0]["reason"] == "missing_reconcile_action_fields:log_path"


def test_phase2_queue_continuation_merges_background_and_task_level_attempts(
    tmp_path: Path, monkeypatch
) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(_common, "_skill_state_base_dir", lambda: base_dir)
    req_id = "REQ-855"
    background_attempt = _make_phase2_attempt(
        task_num="01",
        task_id="bg-task-background-001",
        attempt_id="attempt-background-001",
        worktree_path="/tmp/background-priority",
        log_path="/tmp/background-priority/running.log",
    )
    duplicate_task_attempt = _task_attempt_from_background_attempt(
        {
            **background_attempt,
            "task_id": "task-level-stale-001",
            "worktree_path": "/tmp/task-level-stale",
            "log_path": "/tmp/task-level-stale/running.log",
        }
    )
    task_only_attempt = _task_attempt_from_background_attempt(
        _make_phase2_attempt(
            task_num="02",
            task_id="task-level-only-002",
            attempt_id="attempt-task-only-002",
            worktree_path="/tmp/task-level-only-002",
            log_path="/tmp/task-level-only-002/running.log",
        )
    )
    incomplete_task_attempt = _task_attempt_from_background_attempt(
        _make_phase2_attempt(
            task_num="03",
            task_id="task-level-incomplete-003",
            attempt_id="attempt-task-incomplete-003",
            worktree_path="/tmp/task-level-incomplete-003",
            log_path="/tmp/task-level-incomplete-003/running.log",
        )
    )
    del incomplete_task_attempt["worktree_path"]
    _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            {"id": "T01", "status": "pending", "attempts": [duplicate_task_attempt]},
            {"id": "T02", "status": "pending", "attempts": [task_only_attempt]},
            {"id": "T03", "status": "pending", "attempts": [incomplete_task_attempt]},
        ],
        extra={"background_task_ids": [dict(background_attempt)]},
    )

    result = request_cmds.advance_phase2_if_ready(req_id, check=True)
    entries = _read_pending_queue(base_dir)

    assert result["ready"] is False
    assert result["reason"] == "incomplete_tasks"
    assert result["reconcile_queue"]["attempt_count"] == 3
    assert result["reconcile_queue"]["created_count"] == 2
    assert result["reconcile_queue"]["noop_count"] == 1
    assert result["reconcile_queue"]["manual_reconcile_required"] is True
    assert [entry["attempt_id"] for entry in entries] == [
        "attempt-background-001",
        "attempt-task-only-002",
    ]
    _assert_reconcile_queue_action_matches(entries[0], req_id, background_attempt)
    _assert_reconcile_queue_action_matches(entries[1], req_id, task_only_attempt)
    assert entries[0]["task_id"] == "bg-task-background-001"
    reasons = {item.get("attempt_id"): item.get("reason") for item in result["reconcile_queue"]["results"]}
    assert reasons["attempt-task-incomplete-003"] == "missing_reconcile_action_fields:worktree_path"


def test_phase2_metadata_does_not_regress_advance_ready_gate(tmp_path: Path, monkeypatch) -> None:
    base_dir = _set_base_dir(monkeypatch, tmp_path)
    req_id = "REQ-856"
    request_path = _seed_request(
        base_dir,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            _phase2_evidence_task(tmp_path, req_id, "T01", "committed"),
            _phase2_evidence_task(tmp_path, req_id, "T02", "completed"),
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
