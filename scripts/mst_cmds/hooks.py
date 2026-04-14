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
    TYPE_DIRS,
    _archive_run_type,
    _resolve_archive_max_active,
    _skill_state_base_dir,
    load_json,
)

def cmd_hooks_post_skill(args):
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            return 0

        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return 0

        skill = tool_input.get("skill", "")
        if not isinstance(skill, str):
            return 0

        # --- return_to continuation guard ---
        # Check snapshot for returnTo BEFORE archiving (archive may clear state)
        _hooks_post_skill_continuation(skill)

        if skill not in {"mst:accept", "mst:ideation", "mst:discussion", "mst:debug"}:
            return 0

        resolved = load_json(_common.BASE_DIR / "config.resolved.json") or {}
        archive_cfg = resolved.get("archive", {})
        if not isinstance(archive_cfg, dict):
            archive_cfg = {}

        if not archive_cfg.get("auto_archive_on_complete", True):
            return 0

        max_active_cfg = archive_cfg.get("max_active_sessions", 20)

        for type_key in TYPE_DIRS:
            try:
                max_active = _resolve_archive_max_active(max_active_cfg, type_key)
                _archive_run_type(type_key, max_active=max_active, emit_output=False)
            except Exception:
                pass
    except Exception:
        return 0
    return 0


def _atomic_copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.tmp.", dir=str(dest.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp_path)
        os.replace(tmp_path, dest)
        try:
            shutil.copymode(src, dest)
        except OSError:
            os.chmod(dest, src.stat().st_mode)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".mst-hook-version.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def cmd_hooks_sync(args):
    silent = bool(getattr(args, "silent", False))
    try:
        mst_script = _common._mst_script_path().resolve()
        plugin_root = mst_script.parent.parent
        plugin_json_path = plugin_root / ".claude-plugin" / "plugin.json"
        plugin_json = load_json(plugin_json_path)
        plugin_version = ""
        if isinstance(plugin_json, dict):
            version_value = plugin_json.get("version")
            if isinstance(version_value, str):
                plugin_version = version_value.strip()
        if not plugin_version:
            raise RuntimeError(f"invalid plugin version: {plugin_json_path}")

        project_root = Path(os.getcwd()).resolve()
        project_hooks_dir = project_root / ".claude" / "hooks"
        version_stamp_path = project_hooks_dir / ".mst-hook-version"
        current_version = ""
        try:
            current_version = version_stamp_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            current_version = ""

        if current_version == plugin_version:
            if not silent:
                print(f"[hooks] up-to-date (v{plugin_version})")
            return 0

        source_hooks_dir = plugin_root / "hooks"
        if not source_hooks_dir.is_dir():
            raise RuntimeError(f"hooks source not found: {source_hooks_dir}")
        source_files = sorted(path for path in source_hooks_dir.iterdir() if path.is_file())
        if not source_files:
            raise RuntimeError(f"hooks source empty: {source_hooks_dir}")

        synced_files = 0
        for src_file in source_files:
            dest_file = project_hooks_dir / src_file.name
            _atomic_copy_file(src_file, dest_file)
            synced_files += 1

        _atomic_write_text(version_stamp_path, f"{plugin_version}\n")
        if not silent:
            old_version = current_version or "none"
            print(f"[hooks] synced {synced_files} files (v{old_version}→v{plugin_version})")
    except Exception as exc:
        reason = str(exc).strip().replace("\n", " ") or exc.__class__.__name__
        print(f"[hooks] warning: sync skipped ({reason})", file=sys.stderr)
    return 0


def _hooks_post_skill_continuation(completed_skill: str) -> None:
    """If the snapshot has returnTo, emit a mandatory continuation message."""
    try:
        from scripts._skill_state import load_snapshot

        state_base_dir = _skill_state_base_dir()
        snapshot = load_snapshot(state_base_dir)
        if snapshot is None:
            return

        return_to = snapshot.get("returnTo")
        if not isinstance(return_to, dict):
            return

        parent_skill = return_to.get("skill", "")
        parent_step = return_to.get("step")
        if not parent_skill:
            return

        # Only emit when the completed skill is NOT the parent itself
        # (avoid loop when the parent skill completes normally)
        skill_short = completed_skill.replace("mst:", "")
        if skill_short == parent_skill:
            return

        step_info = f"/{parent_step}" if parent_step is not None else ""
        print(
            f"\n⚠️ MANDATORY CONTINUATION: "
            f"return_to={parent_skill}{step_info} detected. "
            f"The sub-skill '{completed_skill}' has completed and MUST return control to the parent skill. "
            f"You MUST immediately call Skill(skill: \"mst:{parent_skill}\") to resume. "
            f"Do NOT end the conversation or ask the user — continue NOW.\n"
        )
    except Exception:
        pass


def register(subparsers):
    sub = subparsers
    hooks = sub.add_parser("hooks")
    hooks_sub = hooks.add_subparsers(dest="subcommand")
    hooks_post_skill = hooks_sub.add_parser("post-skill")
    hooks_post_skill.set_defaults(func=cmd_hooks_post_skill)
    hooks_sync = hooks_sub.add_parser("sync")
    hooks_sync.add_argument("--silent", action="store_true")
    hooks_sync.set_defaults(func=cmd_hooks_sync)
