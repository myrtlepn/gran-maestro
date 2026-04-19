from __future__ import annotations

import json
import os
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


def test_pre_tool_hook_blocks_missing_worktree_when_retry_not_possible(tmp_path: Path) -> None:
    req_id = "REQ-679"
    write_request(tmp_path, req_id)

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))
    payload = parse_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"] == "boundary_violation:worktree_missing"
    assert not (tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01.meta.json").exists()


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


def test_pre_tool_hook_skips_foreign_session_mismatch(tmp_path: Path) -> None:
    req_id = "REQ-683"
    write_request(tmp_path, req_id, detected_base="main", owner_ppid=1)

    result = run_hook(PRE_TOOL_HOOK, tmp_path, approve_payload(req_id))

    assert result.returncode == 0
    assert result.stdout == ""
    assert "session_mismatch" in result.stderr


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
