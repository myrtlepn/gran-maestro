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


def _find_nested_worktree_root(target_path, worktree_roots, master_root=None) -> Path | None:
    normalized_target = _normalize_target_path(target_path)
    normalized_master = _normalize_target_path(master_root) if master_root else None
    matches: list[Path] = []
    for worktree_root in worktree_roots:
        normalized_root = _normalize_target_path(worktree_root)
        if normalized_master is not None and normalized_root == normalized_master:
            continue
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
        nested_root = _find_nested_worktree_root(worktree_path, _list_worktree_roots(project_root), master_root=project_root)
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


def _meta_worktree_path(meta_data: dict, project_root: Path) -> Path | None:
    raw_path = _coerce_nonempty_str(meta_data.get("path"))
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve(strict=False)


def _git_branch_exists(project_root: Path, branch: str | None) -> bool:
    if not branch:
        return False
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"git branch --list {branch} failed"
        )
    return bool(result.stdout.strip())


def _iter_cleaned_meta_entries(project_root: Path) -> list[dict]:
    entries: list[dict] = []
    worktrees_dir = _common.BASE_DIR / "worktrees"
    if not worktrees_dir.is_dir():
        return entries

    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data = _common.load_json(meta_path)
        if not isinstance(meta_data, dict):
            print(f"Warning: failed to read worktree meta {meta_path}", file=sys.stderr)
            continue
        if meta_data.get("state") != "cleaned":
            continue

        task_id = _coerce_nonempty_str(meta_data.get("taskId")) or meta_path.name.removesuffix(".meta.json")
        worktree_path = _meta_worktree_path(meta_data, project_root)
        entries.append(
            {
                "taskId": task_id,
                "path": str(worktree_path) if worktree_path else None,
                "branch": _coerce_nonempty_str(meta_data.get("branch")),
                "meta_path": str(meta_path.resolve(strict=False)),
            }
        )
    return entries


def _detect_cleaned_orphans(project_root: Path) -> list[dict]:
    worktree_roots = set(_list_worktree_roots(project_root))
    orphans: list[dict] = []

    for entry in _iter_cleaned_meta_entries(project_root):
        worktree_path = Path(entry["path"]) if entry.get("path") else None
        worktree_listed = worktree_path in worktree_roots if worktree_path else False
        path_exists = worktree_path.exists() if worktree_path else False
        branch_exists = _git_branch_exists(project_root, entry.get("branch"))

        if not (worktree_listed or branch_exists or path_exists):
            continue

        orphans.append(
            {
                **entry,
                "worktree_listed": worktree_listed,
                "branch_exists": branch_exists,
                "path_exists": path_exists,
            }
        )
    return orphans


def _run_orphan_cleanup_command(project_root: Path, command: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode == 0:
        return True, (result.stdout.strip() or result.stderr.strip())
    return False, (result.stderr.strip() or result.stdout.strip() or f"{' '.join(command)} failed")


def _clean_detected_orphan(project_root: Path, orphan: dict) -> tuple[bool, list[dict]]:
    steps: list[dict] = []
    worktree_path = orphan.get("path")
    branch = orphan.get("branch")

    if worktree_path and (orphan.get("worktree_listed") or orphan.get("path_exists")):
        remove_cmd = [
            sys.executable,
            str(_common._mst_script_path()),
            "worktree",
            "remove",
            "--path",
            worktree_path,
            "--force",
        ]
        ok, message = _run_orphan_cleanup_command(project_root, remove_cmd)
        steps.append({"command": " ".join(remove_cmd), "ok": ok, "message": message})
        if not ok:
            return False, steps

    if branch and orphan.get("branch_exists"):
        branch_cmd = ["git", "branch", "-D", branch]
        ok, message = _run_orphan_cleanup_command(project_root, branch_cmd)
        steps.append({"command": " ".join(branch_cmd), "ok": ok, "message": message})
        if not ok:
            return False, steps

    meta_path = Path(str(orphan["meta_path"]))
    try:
        meta_path.unlink(missing_ok=True)
        steps.append({"command": f"remove meta {meta_path}", "ok": True, "message": str(meta_path)})
    except OSError as exc:
        steps.append({"command": f"remove meta {meta_path}", "ok": False, "message": str(exc)})
        return False, steps

    return True, steps


def _print_detect_orphans_payload(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    orphans = payload.get("orphans") or []
    if not orphans:
        print("[recover-orphan] cleaned meta orphan: none")
        return

    for orphan in orphans:
        reasons = [
            key
            for key in ("worktree_listed", "branch_exists", "path_exists")
            if orphan.get(key)
        ]
        print(
            "[recover-orphan] detected "
            f"taskId={orphan.get('taskId')} path={orphan.get('path')} "
            f"branch={orphan.get('branch')} reasons={','.join(reasons)}"
        )
        cleanup = orphan.get("cleanup")
        if cleanup:
            status = "cleaned" if cleanup.get("ok") else "failed"
            print(f"[recover-orphan] {status} taskId={orphan.get('taskId')}")


def cmd_worktree_detect_orphans(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)

    try:
        orphans = _detect_cleaned_orphans(project_root)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "clean", False):
        for orphan in orphans:
            ok, steps = _clean_detected_orphan(project_root, orphan)
            orphan["cleanup"] = {"ok": ok, "steps": steps}

    cleaned = [
        orphan["taskId"]
        for orphan in orphans
        if orphan.get("cleanup", {}).get("ok") is True
    ]
    failed = [
        orphan["taskId"]
        for orphan in orphans
        if orphan.get("cleanup", {}).get("ok") is False
    ]
    payload = {
        "orphans": orphans,
        "cleaned": cleaned,
        "failed": failed,
    }
    _print_detect_orphans_payload(payload, getattr(args, "json", False))
    return 1 if failed else 0



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


def _boundary_payload(
    ok: bool,
    violation: str | None,
    retry_possible: bool,
    detected_base: str | None,
    reason: str,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> dict:
    return {
        "ok": ok,
        "violation": violation,
        "retry_possible": retry_possible,
        "detected_base": detected_base,
        "reason": reason,
        "owner_ppid": owner_ppid,
        "current_ppid": current_ppid,
    }


def _print_boundary_payload(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _coerce_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_nonempty_str(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _load_boundary_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "JSON root is not an object"
    return data, None


def _boundary_request_path(req_id: str) -> Path:
    return _common.requests_dir() / req_id / "request.json"


def _boundary_meta_path(req_id: str, task_id: str) -> Path:
    return _common.BASE_DIR / "worktrees" / f"{req_id}-{task_id}.meta.json"


def _boundary_task_ids(request_data: dict, requested_task_id: str | None) -> list[str]:
    if requested_task_id:
        return [requested_task_id]

    task_ids: list[str] = []
    tasks = request_data.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict):
                task_id = _coerce_nonempty_str(task.get("id"))
                if task_id:
                    task_ids.append(task_id)
    return task_ids


def _boundary_retry_possible(violation: str | None, detected_base: str | None, state: str | None) -> bool:
    if violation == "worktree_missing":
        return detected_base is not None
    if violation == "not_cleaned":
        return state in {"cleaning", "pre_merge", "clean_failed"}
    return False


def _phase_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _boundary_ok_payload(
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
    reason: str = "boundary ok",
) -> dict:
    return _boundary_payload(True, None, False, detected_base, reason, owner_ppid, current_ppid)


def _check_entry_boundary(
    req_id: str,
    request_data: dict,
    task_ids: list[str],
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> tuple[dict, int]:
    current_phase = _phase_int(request_data.get("current_phase"))
    if current_phase is None or current_phase < 2:
        return _boundary_ok_payload(
            detected_base,
            owner_ppid,
            current_ppid,
            "entry boundary not active before phase 2",
        ), 0

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if not meta_path.exists():
            violation = "worktree_missing"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, None),
                detected_base,
                f"worktree meta missing: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

        meta_data, error = _load_boundary_json(meta_path)
        if error:
            print(f"Warning: failed to read worktree meta {meta_path}: {error}", file=sys.stderr)
            return _boundary_payload(
                False,
                None,
                False,
                detected_base,
                f"failed to read worktree meta: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 3
        if meta_data.get("state") == "conflict":
            violation = "merge_conflict"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, "conflict"),
                detected_base,
                f"worktree meta is in conflict state: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

    return _boundary_ok_payload(detected_base, owner_ppid, current_ppid), 0


def _check_exit_boundary(
    req_id: str,
    request_data: dict,
    task_ids: list[str],
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> tuple[dict, int]:
    status = str(request_data.get("status", "")).strip().lower()
    if status != "done":
        violation = "not_cleaned"
        return _boundary_payload(
            False,
            violation,
            _boundary_retry_possible(violation, detected_base, None),
            detected_base,
            f"request status is not done: {status or '<empty>'}",
            owner_ppid,
            current_ppid,
        ), 0

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if not meta_path.exists():
            violation = "worktree_missing"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, None),
                detected_base,
                f"worktree meta missing: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

        meta_data, error = _load_boundary_json(meta_path)
        if error:
            print(f"Warning: failed to read worktree meta {meta_path}: {error}", file=sys.stderr)
            return _boundary_payload(
                False,
                None,
                False,
                detected_base,
                f"failed to read worktree meta: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 3

        state = _coerce_nonempty_str(meta_data.get("state"))
        if state == "conflict":
            violation = "merge_conflict"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, state),
                detected_base,
                f"worktree meta is in conflict state: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0
        if state != "cleaned":
            violation = "not_cleaned"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, state),
                detected_base,
                f"worktree meta state is not cleaned: {meta_path} state={state or '<missing>'}",
                owner_ppid,
                current_ppid,
            ), 0

    return _boundary_ok_payload(detected_base, owner_ppid, current_ppid), 0


def cmd_worktree_check_boundary(args):
    req_id = _coerce_nonempty_str(args.req)
    current_ppid = getattr(args, "ppid", None)
    if not req_id:
        print("Warning: --req is required", file=sys.stderr)
        return 2

    request_path = _boundary_request_path(req_id)
    if not request_path.exists():
        payload = _boundary_payload(
            False,
            "unknown_req",
            False,
            None,
            f"request.json not found: {request_path}",
            None,
            current_ppid,
        )
        _print_boundary_payload(payload)
        return 0

    request_data, error = _load_boundary_json(request_path)
    if error:
        print(f"Warning: failed to read request.json {request_path}: {error}", file=sys.stderr)
        payload = _boundary_payload(
            False,
            None,
            False,
            None,
            f"failed to read request.json: {request_path}",
            None,
            current_ppid,
        )
        _print_boundary_payload(payload)
        return 3

    detected_base = _coerce_nonempty_str(request_data.get("detected_base"))
    owner_ppid = _coerce_int(request_data.get("owner_ppid"))
    if current_ppid is not None and owner_ppid is not None and current_ppid != owner_ppid:
        payload = _boundary_payload(
            False,
            "session_mismatch",
            False,
            detected_base,
            f"owner_ppid={owner_ppid} does not match current_ppid={current_ppid}",
            owner_ppid,
            current_ppid,
        )
        _print_boundary_payload(payload)
        return 0

    task_ids = _boundary_task_ids(request_data, getattr(args, "task_id", None))
    if not task_ids:
        payload = _boundary_ok_payload(
            detected_base,
            owner_ppid,
            current_ppid,
            "no task ids available for boundary check",
        )
        _print_boundary_payload(payload)
        return 0

    if args.phase == "entry":
        payload, exit_code = _check_entry_boundary(
            req_id,
            request_data,
            task_ids,
            detected_base,
            owner_ppid,
            current_ppid,
        )
    else:
        payload, exit_code = _check_exit_boundary(
            req_id,
            request_data,
            task_ids,
            detected_base,
            owner_ppid,
            current_ppid,
        )
    _print_boundary_payload(payload)
    return exit_code


def _register_worktree_dispatch(subcommand: str, fn) -> None:
    package = sys.modules.get("scripts.mst_cmds")
    dispatch = getattr(package, "DISPATCH", None)
    if isinstance(dispatch, dict):
        dispatch[("worktree", subcommand)] = fn


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

    worktree_check_boundary = worktree_sub.add_parser("check-boundary")
    worktree_check_boundary.add_argument("--req", required=True)
    worktree_check_boundary.add_argument("--phase", choices=["entry", "exit"], required=True)
    worktree_check_boundary.add_argument("--task-id")
    worktree_check_boundary.add_argument("--ppid", type=int)

    worktree_detect_orphans = worktree_sub.add_parser("detect-orphans")
    worktree_detect_orphans.add_argument("--clean", action="store_true")
    worktree_detect_orphans.add_argument("--json", action="store_true")

    _register_worktree_dispatch("check-boundary", cmd_worktree_check_boundary)
    _register_worktree_dispatch("detect-orphans", cmd_worktree_detect_orphans)
