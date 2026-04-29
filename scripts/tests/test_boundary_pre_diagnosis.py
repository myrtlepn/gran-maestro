from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_TOOL_HOOK = REPO_ROOT / "hooks" / "mst-pre-tool-use.sh"


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


def run_shell(cwd: Path, command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_PRE_TOOL_USE_SOURCE_ONLY"] = "1"
    env["MST_PRE_TOOL_USE_TEST_BOOTSTRAP"] = "1"
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def test_pre_diagnosis_classifies_base_not_verified(tmp_path: Path) -> None:
    init_git_project(tmp_path)
    command = f'''
      source "{PRE_TOOL_HOOK}"
      PROJECT_ROOT="{tmp_path}"
      diagnose_repair_blocker "REQ-7453" "T01" "gran-maestro/main/REQ-7453-T01" "missing-base" "{tmp_path}/.gran-maestro/worktrees/REQ-7453-T01"
    '''
    result = run_shell(tmp_path, command)

    assert result.returncode == 0
    assert result.stdout.strip() == "base_not_verified"


def test_pre_diagnosis_classifies_branch_conflict(tmp_path: Path) -> None:
    init_git_project(tmp_path)
    branch = "gran-maestro/main/REQ-7454-T01"
    subprocess.run(["git", "branch", branch, "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    command = f'''
      source "{PRE_TOOL_HOOK}"
      PROJECT_ROOT="{tmp_path}"
      diagnose_repair_blocker "REQ-7454" "T01" "{branch}" "main" "{tmp_path}/.gran-maestro/worktrees/REQ-7454-T01"
    '''
    result = run_shell(tmp_path, command)

    assert result.returncode == 0
    assert result.stdout.strip() == "branch_conflict"


def test_pre_diagnosis_maps_none_to_repair_failed_for_general_failure(tmp_path: Path) -> None:
    init_git_project(tmp_path)
    command = f'''
      source "{PRE_TOOL_HOOK}"
      PROJECT_ROOT="{tmp_path}"
      diagnosis="$(diagnose_repair_blocker "REQ-7455" "T01" "gran-maestro/main/REQ-7455-T01" "main" "{tmp_path}/.gran-maestro/worktrees/REQ-7455-T01")"
      REPAIR_PRE_DIAGNOSIS="$diagnosis"
      REPAIR_LAST_REASON_TOKEN=""
      resolve_repair_block_reason
    '''
    result = run_shell(tmp_path, command)

    assert result.returncode == 0
    assert result.stdout.strip() == "repair_failed"
