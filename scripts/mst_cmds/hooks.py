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
from scripts.mst_cmds import env_alias_compat
from scripts.mst_cmds import on as on_cmd
from scripts.mst_cmds import skill as skill_cmd
from scripts.mst_cmds.worktree import inspect_lineage_unknown_worktree_meta
from scripts.mst_cmds._common import (
    TYPE_DIRS,
    _archive_run_type,
    _resolve_archive_max_active,
    _skill_state_base_dir,
    load_json,
)


def _snapshot_session_id() -> str:
    session_id, _source = env_alias_compat.resolve_session_id_from_env(warn_legacy=False)
    if session_id:
        return session_id
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


def _detect_legacy_env_aliases() -> list[tuple[str, str]]:
    detected: list[tuple[str, str]] = []
    for alias in env_alias_compat.LEGACY_SESSION_ALIASES:
        value = os.environ.get(alias, "").strip()
        if value:
            detected.append((alias, value))
    return detected


def _print_legacy_env_alias_report(detected: list[tuple[str, str]]) -> None:
    if not detected:
        return
    canonical = os.environ.get(env_alias_compat.CANONICAL_SESSION_ENV, "").strip() or "<unset>"
    print()
    print("[legacy-env-alias] deprecated session env alias detected; migration: set MST_SESSION_ID as canonical.")
    print(f"  MST_SESSION_ID={canonical}")
    print("  detected legacy aliases:")
    for alias, value in detected:
        print(f"  - {alias}={value} (deprecated alias; compatibility only)")
    print("  0.61.0 removal readiness:")
    print("  - legacy alias list: MST_STATE_PPID, MST_SNAPSHOT_SESSION_ID")
    print("  - allowed residual surfaces: scripts/mst_cmds/env_alias_compat.py, doctor reporting, runtime compatibility fallbacks, compatibility tests/docs")
    print("  - remove compatibility helper/test/allowlist/docs items: env_alias_compat fallback warnings, tests/test_env_alias_compatibility.py alias allowlist, SESSION-ID-MIGRATION deprecated alias notes")


def _detect_legacy_ppid_state(base_dir: Path) -> int:
    """legacy 항목 수 (numeric PPID 디렉토리 + owner_ppid 필드만 가진 JSON)."""
    count = 0
    state_dir = _common.state_dir(_common.base_dir_from_project(base_dir))
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


def _load_json_quiet(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _manifest_hooks_path(plugin_root: Path, manifest: dict) -> Path | None:
    hooks_field = manifest.get("hooks")
    if not isinstance(hooks_field, str) or not hooks_field.strip():
        return None
    return (plugin_root / hooks_field).resolve()


def _iter_registry_commands(registry: object):
    if not isinstance(registry, dict):
        return
    hooks_obj = registry.get("hooks")
    if not isinstance(hooks_obj, dict):
        return
    for event, entries in hooks_obj.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("hooks")
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if isinstance(command, str) and command.strip():
                    yield str(event), command


def _first_stop_command(registry: object) -> str:
    for event, command in _iter_registry_commands(registry) or []:
        if event == "Stop":
            return command
    return ""


def _enabled_plugin_state(plugin_id: str = "mst@gran-maestro") -> str:
    settings = _load_json_quiet(Path.home() / ".claude" / "settings.json")
    if not isinstance(settings, dict):
        return "unknown"
    enabled_plugins = settings.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict) or plugin_id not in enabled_plugins:
        return "unknown"
    value = enabled_plugins.get(plugin_id)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "unknown"


def _active_plugin_diagnostic(plugin_root: Path) -> dict:
    manifest_path = plugin_root / ".claude-plugin" / "plugin.json"
    manifest = _load_json_quiet(manifest_path)
    if not isinstance(manifest, dict):
        manifest = {}
    registry_path = _manifest_hooks_path(plugin_root, manifest)
    registry = _load_json_quiet(registry_path) if registry_path is not None else None
    stop_command = _first_stop_command(registry)
    hooks_field = manifest.get("hooks", "")
    hooks_json_exists = bool(registry_path and registry_path.exists())
    has_canonical_stop = stop_command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/")
    status = "OK" if has_canonical_stop else "WARNING"
    message = "" if status == "OK" else "active plugin cache manifest/registry lacks canonical Stop registration"
    return {
        "skill_base_dir": str(plugin_root / "skills"),
        "enabled_plugin": _enabled_plugin_state(),
        "active_plugin_root": str(plugin_root),
        "active_plugin_version": str(manifest.get("version") or "unknown"),
        "active_manifest_hooks_field": str(hooks_field) if hooks_field else "<missing>",
        "active_hooks_json_exists": hooks_json_exists,
        "active_stop_registration": has_canonical_stop,
        "active_stop_command": stop_command or "<missing>",
        "canonical_stop_registration_status": status,
        "canonical_stop_registration_message": message,
        "registry_path": str(registry_path) if registry_path is not None else "<missing>",
    }


def _settings_has_stop_registration(settings: object) -> bool:
    if not isinstance(settings, dict):
        return False
    for item in on_cmd._iter_settings_hook_commands(settings) or []:
        if item.get("event") == "Stop" or "mst-stop-hook.sh" in item.get("command", ""):
            return True
    return False


def _layer_diagnostics(project_root: Path, plugin_root: Path, installed_path: Path, active: dict) -> list[dict]:
    canonical_path = Path(str(active.get("registry_path") or "")) if active.get("registry_path") != "<missing>" else plugin_root / "hooks" / "hooks.json"
    legacy_settings_path = project_root / ".claude" / "settings.local.json"
    legacy_settings = _load_json_quiet(legacy_settings_path)
    legacy_file_stop = (installed_path / "mst-stop-hook.sh").exists()
    legacy_settings_stop = _settings_has_stop_registration(legacy_settings)
    user_global_path = Path.home() / ".claude" / "settings.json"
    user_global_settings = _load_json_quiet(user_global_path)
    user_global_stop = _settings_has_stop_registration(user_global_settings)
    return [
        {
            "name": "canonical_plugin_hook",
            "source_path": str(canonical_path),
            "found": canonical_path.exists(),
            "stop_registration": bool(active.get("active_stop_registration")),
            "mst_core_stop_guarantee": "true" if active.get("active_stop_registration") else "false",
        },
        {
            "name": "project_local_legacy_source_dev_hook",
            "source_path": f"{installed_path} ; {legacy_settings_path}",
            "found": installed_path.exists() or legacy_settings_path.exists(),
            "stop_registration": legacy_file_stop or legacy_settings_stop,
            "mst_core_stop_guarantee": "false (legacy/source-dev is not canonical)",
        },
        {
            "name": "user_global_environment_hook",
            "source_path": str(user_global_path),
            "found": user_global_path.exists(),
            "stop_registration": user_global_stop,
            "mst_core_stop_guarantee": "false (user-global is not MST core canonical)",
        },
    ]


def evaluate_stop_dispatcher_smoke(script_direct_execution: bool, event_dispatch_evidence: dict | None = None) -> dict:
    evidence = event_dispatch_evidence if isinstance(event_dispatch_evidence, dict) else {}
    required = ("event_type", "hook_command_path", "timestamp")
    identity_present = bool(evidence.get("process_invocation_id") or evidence.get("test_sentinel"))
    dispatch_pass = all(bool(evidence.get(key)) for key in required) and identity_present and evidence.get("event_type") == "Stop"
    overall = "PASS" if script_direct_execution and dispatch_pass else "INCONCLUSIVE" if script_direct_execution else "FAIL"
    return {
        "script_direct_execution": "PASS" if script_direct_execution else "FAIL",
        "claude_code_stop_event_dispatch": "PASS" if dispatch_pass else "INCONCLUSIVE",
        "overall": overall,
        "required_evidence": [*required, "process_invocation_id_or_test_sentinel"],
    }


def _print_active_plugin_report(active: dict, layers: list[dict], smoke: dict) -> None:
    print()
    print("Active plugin diagnostic:")
    for key in (
        "skill_base_dir",
        "enabled_plugin",
        "active_plugin_root",
        "active_plugin_version",
        "active_manifest_hooks_field",
        "active_hooks_json_exists",
        "active_stop_registration",
        "active_stop_command",
        "canonical_stop_registration_status",
    ):
        print(f"  {key}: {active.get(key)}")
    if active.get("canonical_stop_registration_message"):
        print(f"  message: {active['canonical_stop_registration_message']}")
    print()
    print("Hook responsibility layers:")
    for layer in layers:
        print(f"  {layer['name']}:")
        print(f"    source_path: {layer['source_path']}")
        print(f"    found: {layer['found']}")
        print(f"    stop_registration: {layer['stop_registration']}")
        print(f"    mst_core_stop_guarantee: {layer['mst_core_stop_guarantee']}")
    print()
    print("Stop dispatcher smoke:")
    for key, value in smoke.items():
        print(f"  {key}: {value}")


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

    project_root = Path(os.getcwd()).resolve()
    active = _active_plugin_diagnostic(plugin_root)
    layers = _layer_diagnostics(project_root, plugin_root, installed_path, active)
    smoke = evaluate_stop_dispatcher_smoke(script_direct_execution=False, event_dispatch_evidence=None)
    _print_active_plugin_report(active, layers, smoke)

    _print_legacy_env_alias_report(_detect_legacy_env_aliases())

    base_dir = Path(os.environ.get("MST_BASE_DIR", os.getcwd()))
    legacy_count = _detect_legacy_ppid_state(base_dir)
    if legacy_count > 0:
        print(f"[warn] legacy PPID state 감지 — {legacy_count}개 항목")
        print("실행: python3 mst.py state migrate --dry-run")

    try:
        worktree_meta_report = inspect_lineage_unknown_worktree_meta(base_dir)
    except Exception as exc:
        reason = str(exc).strip().replace("\n", " ") or exc.__class__.__name__
        print(f"[warn] worktree stale meta 진단 실패 — {reason}")
    else:
        candidate_count = int(worktree_meta_report.get("candidate_count") or 0)
        skipped_count = int(worktree_meta_report.get("skipped_count") or 0)
        print(
            "[worktree-migrate-archive] "
            f"stale meta lineage=unknown candidates={candidate_count} skipped={skipped_count}"
        )
        if candidate_count > 0:
            print("권장 명령:")
            print("  mst.py worktree migrate-archive --dry-run")
            print("  mst.py worktree migrate-archive --apply")
            print("  mst.py worktree migrate-archive --delete --apply")
        else:
            print("[worktree-migrate-archive] clean: lineage=unknown candidate 없음")
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
