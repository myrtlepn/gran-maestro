from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"
TEST_MST_SESSION_ID = "MST-AGI-034-20260510T000000000Z-boundary00"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_request(root: Path, req_id: str, *, detected_base: str) -> None:
    write_json(
        root / ".gran-maestro" / "requests" / req_id / "request.json",
        {
            "id": req_id,
            "status": "phase2_execution",
            "current_phase": 2,
            "detected_base": detected_base,
            "tasks": [{"id": "T01"}],
        },
    )


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


def run_hook(cwd: Path, payload: dict, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.setdefault("MST_SESSION_ID", TEST_MST_SESSION_ID)
    merged_env.setdefault("MST_POLICY_HOME", str(cwd / ".gran-maestro" / "policy"))
    if env:
        merged_env.update(env)
    hook_payload = {**payload, "mst_session_id": merged_env["MST_SESSION_ID"]}
    return subprocess.run(
        ["bash", str(PRE_TOOL_HOOK)],
        cwd=cwd,
        input=json.dumps(hook_payload),
        capture_output=True,
        text=True,
        env=merged_env,
    )


def test_repair_entry_once_captures_create_failure_status_and_stderr(tmp_path: Path) -> None:
    req_id = "REQ-7451"
    init_git_project(tmp_path)
    write_request(tmp_path, req_id, detected_base="main")

    # Force create failure with a non-empty target path.
    blocked_path = tmp_path / ".gran-maestro" / "worktrees" / f"{req_id}-T01"
    blocked_path.mkdir(parents=True, exist_ok=True)
    (blocked_path / "occupied.txt").write_text("occupied\n", encoding="utf-8")

    result = run_hook(
        tmp_path,
        {
            "tool_name": "Skill",
            "tool_input": {"skill_name": "mst:approve", "args": req_id},
        },
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "block"
    assert payload["reason"].startswith("create_failed:")
    assert "details" in payload
    assert "summary" in payload["details"]
    assert "stderr:" in payload["details"]["summary"]
