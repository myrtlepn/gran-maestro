from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def run_hook(
    hook: Path,
    cwd: Path,
    payload: dict,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(hook)],
        cwd=cwd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def parse_stdout_json(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.strip(), result.stderr
    return json.loads(result.stdout)


def boundary_log_lines(root: Path) -> list[str]:
    log_path = root / ".gran-maestro" / "logs" / "boundary-guard.log"
    assert log_path.is_file()
    return log_path.read_text(encoding="utf-8").splitlines()


def assert_boundary_log(
    root: Path,
    *,
    hook_name: str,
    event_type: str,
    task_id: str,
    result: str,
    message: str,
) -> None:
    expected = f" | {hook_name} | {event_type} | {task_id} | {result} | {message}"
    assert any(line.endswith(expected) for line in boundary_log_lines(root))


def assert_boundary_log_format(root: Path) -> None:
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
        r" \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \| .*$"
    )
    lines = boundary_log_lines(root)
    assert lines
    assert all(pattern.match(line) for line in lines)


def approve_payload(req_id: str) -> dict:
    return {
        "tool_name": "Skill",
        "tool_input": {
            "skill_name": "mst:approve",
            "args": req_id,
        },
    }


def write_request(
    root: Path,
    req_id: str,
    *,
    status: str = "phase2_execution",
    current_phase: int = 2,
    detected_base: str | None = None,
    owner_ppid: int | None = None,
) -> None:
    payload: dict = {
        "id": req_id,
        "status": status,
        "current_phase": current_phase,
        "tasks": [{"id": "T01"}],
    }
    if detected_base is not None:
        payload["detected_base"] = detected_base
    if owner_ppid is not None:
        payload["owner_ppid"] = owner_ppid
    write_json(root / ".gran-maestro" / "requests" / req_id / "request.json", payload)


def init_git_project(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Boundary Test",
            "-c",
            "user.email=boundary@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    hook_dir = root / ".claude" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "mst-placeholder.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")


def run_detect_orphans(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), "worktree", "detect-orphans", "--clean", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_pre_tool_hook_blocks_missing_worktree_when_retry_not_possible(tmp_path: Path) -> None:
    req_id = "REQ-679"
    write_request(tmp_path, req_id)

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))
    payload = parse_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == "boundary_violation:worktree_missing"
    assert not (tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json").exists()
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="detected",
        task_id=req_id,
        result="worktree_missing",
        message="entry boundary violation detected",
    )
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="blocked",
        task_id=req_id,
        result="worktree_missing",
        message="boundary_violation:worktree_missing",
    )


def test_pre_tool_hook_retries_missing_worktree_then_blocks_after_failed_recheck(tmp_path: Path) -> None:
    req_id = "REQ-680"
    write_request(tmp_path, req_id, detected_base="main")

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id), env={"MST_DEBUG": "1"})
    payload = parse_stdout_json(result)
    debug_logs = list((tmp_path / ".gran-maestro" / "tmp").glob("mst-hook-debug-*.log"))
    debug_text = "\n".join(path.read_text(encoding="utf-8") for path in debug_logs)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == "boundary_violation:worktree_missing"
    assert "boundary_entry_repair_failed" in debug_text
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="retry_failed",
        task_id=req_id,
        result="worktree_missing",
        message="entry repair failed",
    )
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="blocked",
        task_id=req_id,
        result="worktree_missing",
        message="boundary_violation:worktree_missing",
    )


def test_pre_tool_hook_repairs_missing_worktree_when_retry_possible(tmp_path: Path) -> None:
    req_id = "REQ-681"
    init_git_project(tmp_path)
    write_request(tmp_path, req_id, detected_base="main")

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))
    meta_path = tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json"
    worktree_path = tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert result.stdout == ""
    assert meta["state"] == "active"
    assert meta["taskId"] == f"{req_id}-T01"
    assert (worktree_path / ".git").exists()
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="retry_success",
        task_id=req_id,
        result="ok",
        message="entry repair succeeded",
    )


@pytest.mark.parametrize("violation", ["merge_conflict", "unknown_req"])
def test_pre_tool_hook_maps_non_retryable_boundary_violations_to_block_json(
    tmp_path: Path,
    violation: str,
) -> None:
    req_id = "REQ-682"
    if violation == "merge_conflict":
        write_request(tmp_path, req_id, detected_base="main")
        write_json(
            tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json",
            {
                "taskId": f"{req_id}-T01",
                "path": ".gran-maestro/worktrees/REQ-682-T01",
                "branch": "gran-maestro/main/REQ-682-T01",
                "state": "conflict",
            },
        )
    else:
        (tmp_path / ".gran-maestro").mkdir()

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))
    payload = parse_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == f"boundary_violation:{violation}"
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="blocked",
        task_id=req_id,
        result=violation,
        message=f"boundary_violation:{violation}",
    )


def test_pre_tool_hook_skips_foreign_session_mismatch(tmp_path: Path) -> None:
    req_id = "REQ-683"
    write_request(tmp_path, req_id, detected_base="main", owner_ppid=1)

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))

    assert result.returncode == 0
    assert result.stdout == ""
    assert "session_mismatch" in result.stderr
    assert_boundary_log(
        tmp_path,
        hook_name="mst-pre-tool-use.sh",
        event_type="detected",
        task_id=req_id,
        result="session_mismatch",
        message="entry boundary violation detected",
    )


@pytest.mark.parametrize("status", ["executing", "pending", "review", "feedback"])
def test_stop_hook_keeps_active_workflow_session_block(status: str, tmp_path: Path) -> None:
    req_id = "REQ-684"
    write_request(tmp_path, req_id, status=status, owner_ppid=os.getpid())

    result = run_hook(STOP_HOOK, tmp_path, {})
    payload = parse_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert "active workflow session detected" in payload["reason"]
    assert "boundary_violation" not in payload["reason"]


def test_stop_hook_logs_exit_retry_success(tmp_path: Path) -> None:
    req_id = "REQ-685"
    write_request(tmp_path, req_id, status="done", current_phase=5, owner_ppid=os.getpid())
    write_json(
        tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json",
        {
            "taskId": f"{req_id}-T01",
            "path": f".gran-maestro/worktrees/{req_id}-T01",
            "branch": f"gran-maestro/main/{req_id}-T01",
            "state": "clean_failed",
        },
    )

    result = run_hook(STOP_HOOK, tmp_path, {})
    meta = json.loads(
        (tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.returncode == 0
    if result.stdout.strip():
        payload = parse_stdout_json(result)
        assert payload["decision"] == "approve"
        assert payload["reason"] == "workflow_inactive snapshot_present=false"
    assert meta["state"] == "cleaned"
    assert_boundary_log(
        tmp_path,
        hook_name="mst-stop-hook.sh",
        event_type="detected",
        task_id=req_id,
        result="not_cleaned",
        message="exit boundary violation detected",
    )
    assert_boundary_log(
        tmp_path,
        hook_name="mst-stop-hook.sh",
        event_type="retry_success",
        task_id=req_id,
        result="ok",
        message="exit repair succeeded",
    )


def test_stop_hook_logs_exit_merge_conflict_block(tmp_path: Path) -> None:
    req_id = "REQ-686"
    write_request(tmp_path, req_id, status="done", current_phase=5, owner_ppid=os.getpid())
    write_json(
        tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json",
        {
            "taskId": f"{req_id}-T01",
            "path": f".gran-maestro/worktrees/{req_id}-T01",
            "branch": f"gran-maestro/main/{req_id}-T01",
            "state": "conflict",
        },
    )

    result = run_hook(STOP_HOOK, tmp_path, {})
    payload = parse_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == "boundary_violation:merge_conflict snapshot_present=false"
    assert_boundary_log(
        tmp_path,
        hook_name="mst-stop-hook.sh",
        event_type="blocked",
        task_id=req_id,
        result="merge_conflict",
        message="boundary_violation:merge_conflict",
    )


def test_stop_boundary_log_then_detect_orphans_cleans_lingering_branch(tmp_path: Path) -> None:
    req_id = "REQ-687"
    task_id = "T01"
    full_task_id = f"{req_id}-{task_id}"
    branch = f"gran-maestro/main/{full_task_id}"
    worktree_path = tmp_path / ".gran-maestro" / "worktrees" / full_task_id
    meta_path = tmp_path / ".gran-maestro" / "worktrees" / f"{full_task_id}.meta.json"

    init_git_project(tmp_path)
    add_worktree = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), "main"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    write_request(tmp_path, req_id, status="done", current_phase=5, owner_ppid=os.getpid())
    write_json(
        meta_path,
        {
            "taskId": full_task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "clean_failed",
        },
    )

    stop_result = run_hook(STOP_HOOK, tmp_path, {})
    assert stop_result.returncode == 0
    if stop_result.stdout.strip():
        payload = parse_stdout_json(stop_result)
        assert payload["decision"] == "approve"
        assert payload["reason"] == "workflow_inactive snapshot_present=false"
    assert json.loads(meta_path.read_text(encoding="utf-8"))["state"] == "cleaned"
    assert not worktree_path.exists()
    assert_boundary_log(
        tmp_path,
        hook_name="mst-stop-hook.sh",
        event_type="detected",
        task_id=req_id,
        result="not_cleaned",
        message="exit boundary violation detected",
    )
    assert_boundary_log(
        tmp_path,
        hook_name="mst-stop-hook.sh",
        event_type="retry_success",
        task_id=req_id,
        result="ok",
        message="exit repair succeeded",
    )
    assert_boundary_log_format(tmp_path)

    orphan_result = run_detect_orphans(tmp_path)
    payload = parse_stdout_json(orphan_result)

    assert orphan_result.returncode == 0, orphan_result.stderr
    assert payload["cleaned"] == [full_task_id]
    assert payload["orphans"][0]["branch_exists"] is True
    assert payload["orphans"][0]["worktree_listed"] is False
    assert payload["orphans"][0]["path_exists"] is False
    assert not meta_path.exists()


def test_worktree_create_and_remove_help_smoke() -> None:
    for subcommand in ("create", "remove"):
        result = subprocess.run(
            [sys.executable, str(MST), "worktree", subcommand, "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "usage:" in result.stdout
        assert subcommand in result.stdout


def test_pre_tool_hook_source_exists() -> None:
    assert PRE_TOOL_HOOK.is_file()
