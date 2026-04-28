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
from scripts.mst_cmds import skill as skill_cmd
from scripts.mst_cmds._common import (
    TYPE_DIRS,
    _archive_run_type,
    _resolve_archive_max_active,
    _skill_state_base_dir,
    load_json,
)


def _snapshot_session_id() -> str:
    ppid_env = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid_env:
        return ppid_env
    return str(os.getppid())


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

        max_active_cfg = archive_cfg.get("max_active_sessions", 200)

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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_plugin_root() -> Path:
    mst_script = _common._mst_script_path().resolve()
    return mst_script.parent.parent


def _resolve_hooks_paths() -> tuple[Path, Path, Path]:
    plugin_root = _resolve_plugin_root()
    project_root = Path(os.getcwd()).resolve()
    return project_root / ".claude" / "hooks", plugin_root / "hooks", plugin_root


def _read_text_file(path: Path, default: str = "unknown") -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return default
    return value or default


def _read_plugin_version(plugin_root: Path) -> str:
    plugin_json_path = plugin_root / ".claude-plugin" / "plugin.json"
    plugin_json = load_json(plugin_json_path)
    if isinstance(plugin_json, dict):
        version_value = plugin_json.get("version")
        if isinstance(version_value, str):
            return version_value.strip()
    return ""


def _read_source_version(source_hooks_dir: Path, plugin_root: Path) -> str:
    version = _read_text_file(source_hooks_dir / "VERSION", default="")
    if version:
        return version
    return _read_plugin_version(plugin_root) or "unknown"


def _is_hook_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith(".") or path.name == "VERSION":
        return False
    return path.suffix == ".sh" or path.name.startswith("mst-") or path.name.startswith("stop-")


def _hook_files_by_name(path: Path) -> dict[str, Path]:
    if not path.is_dir():
        return {}
    return {hook_path.name: hook_path for hook_path in sorted(path.iterdir()) if _is_hook_file(hook_path)}


def _hook_sync_files(source_hooks_dir: Path) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    files.extend((path, Path(path.name)) for path in sorted(source_hooks_dir.iterdir()) if path.is_file())

    lib_dir = source_hooks_dir / "lib"
    if lib_dir.is_dir():
        files.extend(
            (path, Path("lib") / path.name)
            for path in sorted(lib_dir.iterdir())
            if path.is_file()
        )

    return files


def cmd_hooks_sync(args):
    silent = bool(getattr(args, "silent", False))
    plugin_root = None
    try:
        project_hooks_dir, source_hooks_dir, plugin_root = _resolve_hooks_paths()
        plugin_json_path = plugin_root / ".claude-plugin" / "plugin.json"
        plugin_version = _read_plugin_version(plugin_root)
        if not plugin_version:
            raise RuntimeError(f"invalid plugin version: {plugin_json_path}")

        version_stamp_path = project_hooks_dir / ".mst-hook-version"
        if not source_hooks_dir.is_dir():
            raise RuntimeError(f"hooks source not found: {source_hooks_dir}")
        source_files = _hook_sync_files(source_hooks_dir)
        if not source_files:
            raise RuntimeError(f"hooks source empty: {source_hooks_dir}")

        current_version = ""
        try:
            current_version = version_stamp_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            current_version = ""

        if current_version == plugin_version:
            resynced_files = 0
            for src_file, rel_path in source_files:
                dest_file = project_hooks_dir / rel_path
                hashes_match = dest_file.is_file() and _sha256_file(src_file) == _sha256_file(dest_file)
                if hashes_match:
                    continue
                _atomic_copy_file(src_file, dest_file)
                resynced_files += 1

            if not silent:
                if resynced_files > 0:
                    print(f"[hooks] resynced {resynced_files} files by hash (v{plugin_version})")
                else:
                    print(f"[hooks] up-to-date (v{plugin_version})")
        else:
            synced_files = 0
            for src_file, rel_path in source_files:
                dest_file = project_hooks_dir / rel_path
                _atomic_copy_file(src_file, dest_file)
                synced_files += 1

            _atomic_write_text(version_stamp_path, f"{plugin_version}\n")
            if not silent:
                old_version = current_version or "none"
                print(f"[hooks] synced {synced_files} files (v{old_version}→v{plugin_version})")
    except Exception as exc:
        reason = str(exc).strip().replace("\n", " ") or exc.__class__.__name__
        print(f"[hooks] warning: sync skipped ({reason})", file=sys.stderr)
    if plugin_root is not None:
        try:
            skill_cmd.build_all(plugin_root / "skills", silent=True)
        except Exception:
            pass
    return 0


def _detect_legacy_ppid_state(base_dir: Path) -> int:
    """legacy 항목 수 (numeric PPID 디렉토리 + owner_ppid 필드만 가진 JSON)."""
    count = 0
    state_dir = base_dir / ".gran-maestro" / "state"
    if state_dir.is_dir():
        for child in state_dir.iterdir():
            if child.is_dir() and child.name.isdigit():
                count += 1

    for pattern in [
        ".gran-maestro/agile/AGI-*/objective/objective.json",
        ".gran-maestro/requests/REQ-*/request.json",
        ".gran-maestro/plans/PLN-*/plan.json",
    ]:
        for jp in base_dir.glob(pattern):
            try:
                text = jp.read_text("utf-8")
            except Exception:
                continue
            if '"owner_ppid"' in text and '"owner_session_id"' not in text:
                count += 1

    return count


def doctor(args: argparse.Namespace) -> int:
    installed_path, source_path, plugin_root = _resolve_hooks_paths()
    installed_version = _read_text_file(installed_path / ".mst-hook-version")
    source_version = _read_source_version(source_path, plugin_root)
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    status_message = ""
    mismatched: list[str] = []
    total_hooks = 0
    return_code = 0

    if not source_path.is_dir():
        status_message = "SOURCE_NOT_FOUND"
        print(f"[hooks] warning: source hooks not found: {source_path}", file=sys.stderr)
    else:
        installed_hooks = _hook_files_by_name(installed_path)
        source_hooks = _hook_files_by_name(source_path)
        total_hooks = len(source_hooks)

        for name, source_file in source_hooks.items():
            installed_file = installed_hooks.get(name)
            if not installed_file or _sha256_file(source_file) != _sha256_file(installed_file):
                mismatched.append(name)

        if mismatched:
            status_message = f"MISMATCH ({len(mismatched)} out of {total_hooks} hooks differ)"
            return_code = 1
        else:
            status_message = f"OK (all {total_hooks} hooks in sync)"

    print("Gran Maestro Hooks Doctor")
    print("---")
    print(f"Installed hooks: {installed_path}")
    print(f"Source hooks:    {source_path}")
    print()
    print(f"Status: {status_message}")
    if mismatched:
        print()
        print("Mismatched hooks:")
        for name in mismatched:
            print(f"- {name}")
    print()
    print(f"Installed version: {installed_version}")
    print(f"Expected version:  {source_version}")
    print()
    print(f"Checked at: {checked_at}")

    base_dir = Path(os.environ.get("MST_BASE_DIR", os.getcwd()))
    legacy_count = _detect_legacy_ppid_state(base_dir)
    if legacy_count > 0:
        print(f"[warn] legacy PPID state 감지 — {legacy_count}개 항목")
        print("실행: python3 mst.py state migrate --dry-run")
    return return_code


def _hooks_post_skill_continuation(completed_skill: str) -> None:
    """If the snapshot has returnTo, emit a mandatory continuation message."""
    try:
        from scripts._skill_state import load_snapshot

        state_base_dir = _skill_state_base_dir()
        snapshot = load_snapshot(state_base_dir, session_id=_snapshot_session_id())
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
    hooks_doctor = hooks_sub.add_parser("doctor")
    hooks_doctor.set_defaults(func=doctor)
