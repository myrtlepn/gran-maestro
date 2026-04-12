from __future__ import annotations

import argparse
import copy
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

def _resolve_worktree_source_root() -> Path:
    project_root = _project_root()
    source_claude_dir = project_root / ".claude"
    if (source_claude_dir / "hooks").is_dir() and (source_claude_dir / "settings.local.json").is_file():
        return project_root
    return _common.BASE_DIR.parent

def cmd_worktree_create(args):
    project_root = _common.BASE_DIR.parent
    source_root = _resolve_worktree_source_root()
    worktree_path = Path(args.path).expanduser().resolve()
    branch = str(args.branch or "").strip()
    base = str(args.base or "").strip()

    if not branch:
        print("Error: --branch is required", file=sys.stderr)
        return 1
    if not base:
        print("Error: --base is required", file=sys.stderr)
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
    project_root = _common.BASE_DIR.parent
    worktree_path = Path(args.path).expanduser().resolve()

    remove_cmd = ["git", "worktree", "remove"]
    if getattr(args, "force", False):
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
