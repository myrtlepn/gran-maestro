"""DOD-003: workflow state transition integrity regression tests for state set-workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import mst
from scripts.mst_cmds import request as request_cmds

REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
PPID = 99901
CANONICAL_SESSION_ID = "MST-AGI-039-20260519T130000000Z-req893t1"


def _state_path(workspace: Path, session_id: str = CANONICAL_SESSION_ID) -> Path:
    return workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json"


def _prepare_workspace(workspace: Path) -> None:
    (workspace / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _request_path(workspace: Path, req_id: str) -> Path:
    return workspace / ".gran-maestro" / "requests" / req_id / "request.json"


def _seed_request(
    workspace: Path,
    req_id: str,
    *,
    phase: int,
    status: str,
    tasks: list[dict[str, str]] | None = None,
    extra: dict | None = None,
) -> None:
    payload: dict = {
        "id": req_id,
        "current_phase": phase,
        "status": status,
        "dependencies": {"blockedBy": [], "blocks": []},
    }
    if tasks is not None:
        payload["tasks"] = tasks
    if extra:
        payload.update(extra)
    _write_json(_request_path(workspace, req_id), payload)


def _read_request(workspace: Path, req_id: str) -> dict:
    return json.loads(_request_path(workspace, req_id).read_text(encoding="utf-8"))


def _run_git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )


def _git(workspace: Path, *args: str) -> str:
    result = _run_git(workspace, *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _ensure_git_repo(workspace: Path) -> None:
    if (workspace / ".git").exists():
        return
    assert _run_git(workspace, "init").returncode == 0
    assert _run_git(workspace, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(workspace, "config", "user.name", "Test User").returncode == 0
    _git(workspace, "commit", "--allow-empty", "-m", "initial")
    _git(workspace, "branch", "-M", "main")


def _phase2_evidence_task(workspace: Path, req_id: str, task_id: str, status: str) -> dict[str, str]:
    _ensure_git_repo(workspace)
    branch = f"gran-maestro/main/{req_id}-{task_id}"
    _git(workspace, "checkout", "-B", branch, "main")
    (workspace / f"{req_id}-{task_id}.txt").write_text(f"{req_id} {task_id}\n", encoding="utf-8")
    _git(workspace, "add", f"{req_id}-{task_id}.txt")
    _git(workspace, "commit", "-m", f"[{req_id}/{task_id}] evidence")
    commit_hash = _git(workspace, "rev-parse", "HEAD")
    _git(workspace, "checkout", "main")
    return {"id": task_id, "status": status, "commit_hash": commit_hash, "branch": branch}


def _run(
    workspace: Path,
    *args: str,
    session_id: str | None = CANONICAL_SESSION_ID,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = {**os.environ, "MST_FLOW_DISABLE_ATEXIT": "1"}
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW", "MST_SNAPSHOT_SESSION_ID"):
        env.pop(key, None)
    if session_id is not None:
        env["MST_SESSION_ID"] = session_id
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(MST), "state", "set-workflow", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _read_state(workspace: Path, session_id: str = CANONICAL_SESSION_ID) -> dict:
    return json.loads(_state_path(workspace, session_id=session_id).read_text(encoding="utf-8"))


def _read_stdout_json(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert isinstance(payload, dict)
    return payload


def test_agile_loop_active_preserved_across_skill_transitions(tmp_path):
    _prepare_workspace(tmp_path)
    first = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:plan",
        "--req", "",
        "--auto", "true",
        "--agile-loop-active", "true",
    )
    assert first.returncode == 0, first.stderr

    second = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:request",
        "--req", "PLN-999",
        "--auto", "true",
    )
    assert second.returncode == 0, second.stderr

    state = _read_state(tmp_path)
    assert state["agile_loop_active"] is True
    assert state["current_skill"] == "mst:request"
    assert state["active_req"] == "PLN-999"


def test_disabling_agile_loop_resets_block_count(tmp_path):
    _prepare_workspace(tmp_path)
    # 초기 상태 구성
    init = _run(tmp_path, "--active", "true", "--skill", "mst:agile", "--req", "")
    assert init.returncode == 0, init.stderr

    # block_count 직접 주입
    state_path = _state_path(tmp_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["block_count"] = 5
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # agile-loop-active=false 전환
    result = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:agile",
        "--agile-loop-active", "false",
    )
    assert result.returncode == 0, result.stderr

    state = _read_state(tmp_path)
    assert state["agile_loop_active"] is False
    assert state["block_count"] == 0


def test_inactive_workflow_clears_current_skill_and_req(tmp_path):
    _prepare_workspace(tmp_path)
    setup = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:approve",
        "--req", "REQ-999",
    )
    assert setup.returncode == 0, setup.stderr
    assert _read_state(tmp_path)["current_skill"] == "mst:approve"

    teardown = _run(
        tmp_path,
        "--active", "false",
        "--auto", "false",
    )
    assert teardown.returncode == 0, teardown.stderr

    state = _read_state(tmp_path)
    assert state["workflow_active"] is False
    assert state["current_skill"] == ""
    assert state["active_req"] == ""


def test_active_workflow_sets_last_active_at(tmp_path):
    _prepare_workspace(tmp_path)

    result = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:agile",
        "--req", "REQ-757",
    )

    assert result.returncode == 0, result.stderr
    state = _read_state(tmp_path)
    assert isinstance(state.get("last_active_at"), str)
    parsed = datetime.fromisoformat(state["last_active_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    age = datetime.now(timezone.utc) - parsed
    assert age.total_seconds() < 5


def test_active_to_inactive_updates_last_active_at(tmp_path):
    _prepare_workspace(tmp_path)
    setup = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:agile",
        "--req", "REQ-757",
    )
    assert setup.returncode == 0, setup.stderr

    state_path = _state_path(tmp_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    stale_active_at = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload["last_active_at"] = stale_active_at
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    teardown = _run(
        tmp_path,
        "--active", "false",
        "--auto", "false",
    )
    assert teardown.returncode == 0, teardown.stderr

    state = _read_state(tmp_path)
    assert state["workflow_active"] is False
    assert state["last_active_at"] != stale_active_at
    parsed = datetime.fromisoformat(state["last_active_at"].replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - parsed
    assert age.total_seconds() < 5


def test_request_lifecycle_fixture_preserves_review_and_accept_scope(tmp_path, monkeypatch):
    req_id = "REQ-913"
    base_dir = tmp_path / ".gran-maestro"

    _seed_request(
        tmp_path,
        req_id,
        phase=1,
        status="phase1_analysis",
        extra={"title": "DOD-007 lifecycle compatibility"},
    )
    phase1 = _read_request(tmp_path, req_id)
    assert phase1["current_phase"] == 1
    assert phase1["status"] == "phase1_analysis"

    _seed_request(
        tmp_path,
        req_id,
        phase=2,
        status="phase2_execution",
        tasks=[
            _phase2_evidence_task(tmp_path, req_id, "T01", "committed"),
            _phase2_evidence_task(tmp_path, req_id, "T02", "completed"),
        ],
        extra={"review_summary": {"status": "pending_phase3_review"}},
    )
    phase2 = _read_request(tmp_path, req_id)
    assert phase2["current_phase"] == 2
    assert phase2["status"] == "phase2_execution"

    monkeypatch.setattr(mst, "BASE_DIR", base_dir)
    mst._sync_base_dir()
    result = request_cmds.advance_phase2_if_ready(req_id)
    assert result["ready"] is True
    assert result["advanced"] is True

    phase3 = _read_request(tmp_path, req_id)
    assert phase3["current_phase"] == 3
    assert phase3["status"] == "phase3_review"

    latest_review = {
        "iteration": 2,
        "status": "completed",
        "review_summary": {"status": "passed"},
    }
    accepted = dict(phase3)
    accepted["review_iterations"] = [latest_review]
    accepted["review_summary"] = {"status": "passed"}
    accepted["accept_summary"] = {
        "scope": "request_child_accept",
        "session_to_original": False,
        "target_branch": "gran-maestro/session/REQ-913-01",
    }
    accepted["current_phase"] = 5
    accepted["status"] = "accepted"
    _write_json(_request_path(tmp_path, req_id), accepted)

    phase5 = _read_request(tmp_path, req_id)
    assert [phase1["current_phase"], phase2["current_phase"], phase3["current_phase"], phase5["current_phase"]] == [1, 2, 3, 5]
    assert [phase2["status"], phase3["status"], phase5["status"]] == ["phase2_execution", "phase3_review", "accepted"]
    assert phase5["review_iterations"][-1]["status"] == "completed"
    assert phase5["review_iterations"][-1]["review_summary"]["status"] == "passed"
    assert phase5["review_summary"]["status"] == "passed"
    assert phase5["accept_summary"]["scope"] == "request_child_accept"
    assert phase5["accept_summary"]["session_to_original"] is False
    assert phase5["accept_summary"]["target_branch"].startswith("gran-maestro/session/")


def test_legacy_only_identity_inputs_are_diagnostic_only_for_workflow_mutation(tmp_path):
    _prepare_workspace(tmp_path)

    result = _run(
        tmp_path,
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--req",
        "REQ-893",
        "--auto",
        "true",
        session_id=None,
        extra_env={"MST_STATE_PPID": str(PPID)},
    )

    assert result.returncode != 0
    payload = _read_stdout_json(result)
    assert payload["status"] == "error"
    assert payload["code"] == "legacy_identity_not_canonical_source"
    assert payload["reason"] == "legacy_identity_not_canonical_source"
    assert payload["action"] == "emit_diagnostic_no_mutation"
    assert payload["canonical_mst_session_id"] is None
    assert payload["mutation_performed"] is False
    assert payload["created_new_session"] is False
    assert payload["legacy_diagnostics"] == {"MST_STATE_PPID": str(PPID)}
    assert payload["observed_sources"]["env:MST_SESSION_ID"]["present"] is False
    assert not _state_path(tmp_path).exists()
    assert not (tmp_path / ".gran-maestro" / "tmp" / f"mst-state-{PPID}.json").exists()


def test_structured_mst_session_id_writes_canonical_workflow_state(tmp_path):
    _prepare_workspace(tmp_path)
    structured_session_id = "MST-AGI-039-20260519T130000000Z-ctx00001"

    result = _run(
        tmp_path,
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--req",
        "REQ-893",
        "--auto",
        "true",
        session_id=None,
        extra_env={"MST_CONTEXT_JSON": json.dumps({"mst_session_id": structured_session_id})},
    )

    assert result.returncode == 0, result.stderr
    state = _read_state(tmp_path, session_id=structured_session_id)
    assert state["mst_session_id"] == structured_session_id
    assert state["root_mst_id"] == "AGI-039"
    assert state["workflow_active"] is True
    assert state["current_skill"] == "mst:plan"
    assert not (tmp_path / ".gran-maestro" / "tmp" / f"mst-state-{PPID}.json").exists()


def test_missing_canonical_identity_does_not_create_ppid_workflow_state(tmp_path):
    _prepare_workspace(tmp_path)

    result = _run(
        tmp_path,
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--req",
        "REQ-893",
        "--auto",
        "true",
        session_id=None,
    )

    assert result.returncode != 0
    payload = _read_stdout_json(result)
    assert payload["status"] == "error"
    assert payload["code"] == "missing_canonical_mst_session_id"
    assert payload["mutation_performed"] is False
    assert not _state_path(tmp_path).exists()
    assert not list((tmp_path / ".gran-maestro" / "tmp").glob("mst-state-*.json"))


def test_root_mst_id_generates_canonical_workflow_session_for_top_level_plan(tmp_path):
    _prepare_workspace(tmp_path)
    root_mst_id = "PLN-893"

    result = _run(
        tmp_path,
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--next-skill",
        "mst:request",
        "--next-source",
        root_mst_id,
        "--source-skill",
        "mst:plan",
        "--auto",
        "true",
        "--root-mst-id",
        root_mst_id,
        session_id=None,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    session_id = payload["mst_session_id"]
    assert session_id.startswith("MST-PLN-893-")
    assert payload["root_mst_id"] == root_mst_id
    assert payload["workflow_active"] is True
    assert payload["next_action"]["expected_skill"] == "mst:request"
    assert payload["session_creation"]["created_new_session"] is True
    assert payload["session_creation"]["root_artifact_created"] is True
    assert payload["session_creation"]["root_mst_id"] == root_mst_id
    assert _state_path(tmp_path, session_id=session_id).exists()
    assert (tmp_path / ".gran-maestro" / "plans" / root_mst_id / "plan.json").exists()
    assert (tmp_path / ".gran-maestro" / "sessions" / session_id / "session.json").exists()
    assert not (tmp_path / ".gran-maestro" / "tmp" / f"mst-state-{PPID}.json").exists()


def test_root_mst_id_merges_session_metadata_into_existing_plan_artifact(tmp_path):
    _prepare_workspace(tmp_path)
    root_mst_id = "PLN-894"
    plan_path = tmp_path / ".gran-maestro" / "plans" / root_mst_id / "plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        json.dumps(
            {
                "id": root_mst_id,
                "title": "기존 plan 본문",
                "status": "active",
                "linked_requests": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(
        tmp_path,
        "--active",
        "true",
        "--skill",
        "mst:plan",
        "--next-skill",
        "mst:request",
        "--next-source",
        root_mst_id,
        "--source-skill",
        "mst:plan",
        "--auto",
        "true",
        "--root-mst-id",
        root_mst_id,
        session_id=None,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    session_id = payload["mst_session_id"]
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan_payload["title"] == "기존 plan 본문"
    assert plan_payload["mst_session_id"] == session_id
    assert plan_payload["root_mst_id"] == root_mst_id
    assert payload["session_creation"]["created_new_session"] is True
    assert payload["session_creation"]["root_artifact_created"] is False
    assert _state_path(tmp_path, session_id=session_id).exists()
    assert (tmp_path / ".gran-maestro" / "sessions" / session_id / "session.json").exists()
