from __future__ import annotations

import argparse
import copy
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    _project_root,
)


FALLBACK_PROTECTED_BRANCHES = ["main", "master", "release/*"]


def base_slug(base: str) -> str:
    return str(base).replace("/", "-")


def req_branch_name(req_id: str, base: str) -> str:
    return f"gran-maestro/{base_slug(base)}/{req_id}"


def task_branch_name(req_id: str, task_id: str, base: str) -> str:
    return f"{req_branch_name(req_id, base)}-{task_id}"


def matching_protected_pattern(branch: str, protected_patterns: list[str]) -> str | None:
    for pattern in protected_patterns:
        if fnmatch.fnmatchcase(branch, pattern):
            return pattern
    return None


def is_protected_branch(branch: str, protected_patterns: list[str]) -> bool:
    return matching_protected_pattern(branch, protected_patterns) is not None


def _load_protected_branches() -> list[str]:
    for config_name in ("config.resolved.json", "config.json"):
        data = _common.load_json(_common.BASE_DIR / config_name) or {}
        worktree_config = data.get("worktree") if isinstance(data, dict) else None
        patterns = worktree_config.get("protected_branches") if isinstance(worktree_config, dict) else None
        if isinstance(patterns, list) and all(isinstance(item, str) for item in patterns):
            return list(patterns)
    return list(FALLBACK_PROTECTED_BRANCHES)


def current_head_branch(project_root: Path | None = None) -> str:
    if project_root is None:
        project_root = _project_root()
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "detached HEAD 상태이거나 현재 브랜치를 확인할 수 없습니다"
        )
    branch = result.stdout.strip()
    if not branch:
        raise RuntimeError("현재 브랜치를 확인할 수 없습니다")
    return branch


def _persist_detected_base(req_id: str, detected_base: str) -> None:
    request_path = _common.requests_dir() / req_id / "request.json"
    request_data = _common.load_json(request_path)
    if not isinstance(request_data, dict):
        raise RuntimeError(f"request.json 읽기 실패: {request_path}")
    request_data["detected_base"] = detected_base
    _common.save_json(request_path, request_data)


def _print_resolve_base_payload(detected_base: str, req_id: str | None, as_json: bool) -> None:
    if not as_json:
        print(detected_base)
        return
    payload = {
        "base": detected_base,
        "base_slug": base_slug(detected_base),
    }
    if req_id:
        payload["req_branch"] = req_branch_name(req_id, detected_base)
    print(json.dumps(payload, ensure_ascii=False))


def _copy_worktree_support_files(project_root: Path, worktree_path: Path) -> int:
    source_claude_dir = project_root / ".claude"
    source_hooks_dir = source_claude_dir / "hooks"
    target_claude_dir = worktree_path / ".claude"
    target_hooks_dir = target_claude_dir / "hooks"

    if not source_hooks_dir.is_dir():
        print(f"Error: source hooks directory not found: {source_hooks_dir}", file=sys.stderr)
        return 1

    hook_sources = sorted(source_hooks_dir.glob("mst-*.sh"))
    if not hook_sources:
        print(f"Error: no mst hook scripts found in {source_hooks_dir}", file=sys.stderr)
        return 1

    settings_source = source_claude_dir / "settings.local.json"
    if not settings_source.is_file():
        print(f"Error: source settings file not found: {settings_source}", file=sys.stderr)
        return 1

    target_hooks_dir.mkdir(parents=True, exist_ok=True)

    try:
        for hook_source in hook_sources:
            target_path = target_hooks_dir / hook_source.name
            shutil.copy2(hook_source, target_path)
            target_path.chmod(0o755)

        hook_version_source = source_hooks_dir / ".mst-hook-version"
        if hook_version_source.is_file():
            shutil.copy2(hook_version_source, target_hooks_dir / ".mst-hook-version")

        target_claude_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings_source, target_claude_dir / "settings.local.json")
    except Exception as exc:
        print(f"Error: failed to copy worktree support files ({exc})", file=sys.stderr)
        return 1

    return 0


def _normalize_target_path(path_value) -> Path:
    return Path(path_value).expanduser().resolve(strict=False)


def _resolve_master_project_root() -> Path:
    project_root = _project_root()
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "git rev-parse --git-common-dir failed"
        )

    git_common_dir = Path(result.stdout.strip())
    if not git_common_dir.is_absolute():
        git_common_dir = (project_root / git_common_dir).resolve(strict=False)
    return git_common_dir.parent


def _list_worktree_roots(project_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or "git worktree list --porcelain failed"
        )

    worktree_roots: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            worktree_roots.append(_normalize_target_path(line[len("worktree "):]))
    return worktree_roots


def _find_nested_worktree_root(target_path, worktree_roots) -> Path | None:
    normalized_target = _normalize_target_path(target_path)
    matches: list[Path] = []
    for worktree_root in worktree_roots:
        normalized_root = _normalize_target_path(worktree_root)
        if normalized_target == normalized_root or normalized_root in normalized_target.parents:
            matches.append(normalized_root)
    if not matches:
        return None
    return max(matches, key=lambda candidate: len(candidate.parts))


def _find_child_worktree_root(target_path, worktree_roots) -> Path | None:
    normalized_target = _normalize_target_path(target_path)
    matches: list[Path] = []
    for worktree_root in worktree_roots:
        normalized_root = _normalize_target_path(worktree_root)
        if normalized_root != normalized_target and normalized_target in normalized_root.parents:
            matches.append(normalized_root)
    if not matches:
        return None
    return min(matches, key=lambda candidate: len(candidate.parts))


def _resolve_worktree_source_root() -> Path:
    project_root = _project_root()
    source_claude_dir = project_root / ".claude"
    if (source_claude_dir / "hooks").is_dir() and (source_claude_dir / "settings.local.json").is_file():
        return project_root
    return _resolve_master_project_root()


def cmd_worktree_create(args):
    # Worktree creation commands must resolve master cwd and reject nested targets.
    # Currently this policy applies only to cmd_worktree_create.
    worktree_path = _normalize_target_path(args.path)
    branch = str(args.branch or "").strip()
    base = str(args.base or "").strip()

    if not branch:
        print("Error: --branch is required", file=sys.stderr)
        return 1
    if not base:
        print("Error: --base is required", file=sys.stderr)
        return 1

    try:
        project_root = _resolve_master_project_root()
        source_root = _resolve_worktree_source_root()
        nested_root = _find_nested_worktree_root(worktree_path, _list_worktree_roots(project_root))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if nested_root is not None:
        print(
            "Error: nested worktree path detected. "
            f"현재 target 경로 {worktree_path}는 기존 worktree {nested_root}의 내부입니다. "
            f"master({project_root})에서 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), base],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip() or "git worktree add failed", file=sys.stderr)
        return result.returncode or 1

    copy_result = _copy_worktree_support_files(source_root, worktree_path)
    if copy_result != 0:
        return copy_result

    print(str(worktree_path))
    return 0


def cmd_worktree_remove(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    worktree_path = _normalize_target_path(args.path)
    force = getattr(args, "force", False)

    try:
        child_worktree = _find_child_worktree_root(worktree_path, _list_worktree_roots(project_root))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if child_worktree is not None:
        print(
            "Error: child worktree detected. "
            f"worktree {worktree_path}에 자식 worktree {child_worktree}가 존재합니다. "
            "자식부터 정리하세요.",
            file=sys.stderr,
        )
        return 1

    status_result = subprocess.run(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if status_result.returncode != 0:
        print(
            status_result.stderr.strip()
            or status_result.stdout.strip()
            or "git status --porcelain failed",
            file=sys.stderr,
        )
        return status_result.returncode or 1

    if status_result.stdout:
        if not force:
            print(
                "Error: uncommitted changes detected. "
                f"worktree {worktree_path}에 미커밋 변경이 있습니다. "
                "커밋 후 재시도하거나 --force 사용.",
                file=sys.stderr,
            )
            return 1
        print(
            "Warning: uncommitted changes detected; removing this dirty worktree may cause data loss. "
            f"worktree {worktree_path}에 미커밋 변경이 있습니다.",
            file=sys.stderr,
        )

    remove_cmd = ["git", "worktree", "remove"]
    if force:
        remove_cmd.append("--force")
    remove_cmd.append(str(worktree_path))

    remove_result = subprocess.run(
        remove_cmd,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if remove_result.returncode != 0:
        print(remove_result.stderr.strip() or remove_result.stdout.strip() or "git worktree remove failed", file=sys.stderr)
        return remove_result.returncode or 1

    prune_result = subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if prune_result.returncode != 0:
        print(prune_result.stderr.strip() or prune_result.stdout.strip() or "git worktree prune failed", file=sys.stderr)
        return prune_result.returncode or 1

    print(str(worktree_path))
    return 0



def cmd_worktree_resolve_base(args):
    try:
        detected_base = current_head_branch()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    protected_patterns = _load_protected_branches()
    matched_pattern = matching_protected_pattern(detected_base, protected_patterns)
    if matched_pattern is not None:
        print(
            "Error: 현재 브랜치가 보호 브랜치입니다. "
            f"base={detected_base!r}, matched={matched_pattern!r}. "
            "다른 브랜치로 이동한 뒤 /mst:approve를 다시 실행하세요.",
            file=sys.stderr,
        )
        return 2

    req_id = getattr(args, "req", None)
    if req_id:
        try:
            _persist_detected_base(req_id, detected_base)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    _print_resolve_base_payload(detected_base, req_id, getattr(args, "json", False))
    return 0


def cmd_worktree_is_protected(args):
    branch = getattr(args, "branch", None)
    if not branch:
        try:
            branch = current_head_branch()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    protected_patterns = _load_protected_branches()
    matched_pattern = matching_protected_pattern(branch, protected_patterns)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "branch": branch,
                    "protected": matched_pattern is not None,
                    "matched_pattern": matched_pattern,
                },
                ensure_ascii=False,
            )
        )
    elif matched_pattern is not None:
        print(matched_pattern)

    return 0 if matched_pattern is not None else 1


def cmd_worktree_slug(args):
    print(base_slug(args.base))
    return 0


def cmd_worktree_branch_name(args):
    if getattr(args, "task", None):
        print(task_branch_name(args.req, args.task, args.base))
    else:
        print(req_branch_name(args.req, args.base))
    return 0


def register(subparsers):
    sub = subparsers
    worktree = sub.add_parser("worktree")
    worktree_sub = worktree.add_subparsers(dest="subcommand")

    worktree_create = worktree_sub.add_parser("create")
    worktree_create.add_argument("--path", required=True)
    worktree_create.add_argument("--branch", required=True)
    worktree_create.add_argument("--base", default="master")

    worktree_remove = worktree_sub.add_parser("remove")
    worktree_remove.add_argument("--path", required=True)
    worktree_remove.add_argument("--force", action="store_true")

    worktree_resolve_base = worktree_sub.add_parser("resolve-base")
    worktree_resolve_base.add_argument("--req")
    worktree_resolve_base.add_argument("--json", action="store_true")

    worktree_is_protected = worktree_sub.add_parser("is-protected")
    worktree_is_protected.add_argument("--branch")
    worktree_is_protected.add_argument("--json", action="store_true")

    worktree_slug = worktree_sub.add_parser("slug")
    worktree_slug.add_argument("base")

    worktree_branch_name = worktree_sub.add_parser("branch-name")
    worktree_branch_name.add_argument("--req", required=True)
    worktree_branch_name.add_argument("--base", required=True)
    worktree_branch_name.add_argument("--task")
