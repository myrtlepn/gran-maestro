from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Sequence, Union


PathLike = Union[str, Path]


def slugify_base_branch(base_branch: str) -> str:
    branch = str(base_branch or "").strip()
    if not branch:
        raise ValueError("base_branch is required")
    return branch.replace("/", "-")


def make_req_branch_name(req_id: str, base_branch: str) -> str:
    normalized_req_id = str(req_id or "").strip()
    if not normalized_req_id:
        raise ValueError("req_id is required")
    return f"gran-maestro/{slugify_base_branch(base_branch)}/{normalized_req_id}"


def is_protected_branch(branch: str, protected_branches: Sequence[str]) -> bool:
    branch_name = str(branch or "").strip()
    if not branch_name:
        return False

    for pattern in protected_branches:
        pattern_text = str(pattern or "").strip()
        if pattern_text and fnmatch.fnmatchcase(branch_name, pattern_text):
            return True
    return False


def current_branch(repo_root: PathLike) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(Path(repo_root)),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git branch --show-current failed"
        raise RuntimeError(message)

    branch = result.stdout.strip()
    if not branch:
        raise RuntimeError("detached HEAD is not supported for approve branch detection")
    return branch
