"""`mst.py on` subcommand — /mst:on 보조 명령.

DOD-008 + DOD-009 (PLN-567) — 등록된 기존 프로젝트의 stale mst hook 사본·
settings.local.json hook 항목을 정규식 식별로 자동 정리한다. 사용자 정의
hook은 100% 보존, 변경은 단일 트랜잭션, lock 파일로 동시 실행 차단,
부분 실패 시 settings 백업으로 rollback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.mst_cmds import _common

# AD-007: 등록 프로젝트의 mst hook command 두 변종을 모두 매칭
MST_HOOK_COMMAND_RE = re.compile(
    r"(\$CLAUDE_PROJECT_DIR|\$\(git rev-parse[^)]+\))/\.claude/hooks/"
    r"mst-(stop-hook|session-init|pre-tool-use|auto-chain-context)\.sh"
)

MST_HOOK_FILES = [
    "mst-stop-hook.sh",
    "mst-session-init.sh",
    "mst-pre-tool-use.sh",
    "mst-auto-chain-context.sh",
    ".mst-hook-version",
    "stop-agile-gate-reasons.json",
]

CLASS_PLUGIN_CORE = "plugin_core"
CLASS_PROJECT_LEGACY = "project_legacy"
CLASS_USER_GLOBAL = "user_global"
CLASS_USER_CUSTOM = "user_custom"
HOOK_CLASSIFICATIONS = (
    CLASS_PLUGIN_CORE,
    CLASS_PROJECT_LEGACY,
    CLASS_USER_GLOBAL,
    CLASS_USER_CUSTOM,
)

DIAGNOSTIC_MALFORMED_SETTINGS = "malformed_settings"
DIAGNOSTIC_MISSING_HOOKS_REGISTRY = "missing_hooks_registry"
DIAGNOSTIC_PARSE_ERROR = "parse_error"
DIAGNOSTIC_PERMISSION_DENIED = "permission_denied"
DIAGNOSTIC_UNKNOWN_ENVIRONMENT = "unknown_environment"
DIAGNOSTIC_REASON_CODES = (
    DIAGNOSTIC_MALFORMED_SETTINGS,
    DIAGNOSTIC_MISSING_HOOKS_REGISTRY,
    DIAGNOSTIC_PARSE_ERROR,
    DIAGNOSTIC_PERMISSION_DENIED,
    DIAGNOSTIC_UNKNOWN_ENVIRONMENT,
)

MST_HOOK_FILE_EVENTS = {
    "mst-session-init.sh": "SessionStart",
    "mst-pre-tool-use.sh": "PreToolUse",
    "mst-stop-hook.sh": "Stop",
    "mst-auto-chain-context.sh": "UserPromptSubmit",
}
USER_GLOBAL_HOOK_NAMES = {
    "maestro-guard.sh",
    "log-prompt.sh",
    "check-version.sh",
}

LOCK_STALE_SECONDS = 60


def _project_root() -> Path:
    env_root = os.environ.get("MST_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return Path.cwd()


def _diagnostic(code: str, message: str, path: Optional[Path] = None) -> dict:
    item = {
        "code": code,
        "reason_code": code,
        "reason": code,
        "message": message,
    }
    if path is not None:
        item["path"] = str(path)
    return item


def _read_json_diagnostic(path: Path, diagnostics: List[dict], *, malformed_settings: bool = False):
    if not path.exists():
        return None
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), path))
        return None
    if mode & 0o444 == 0:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, "file is not readable", path))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except PermissionError as exc:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), path))
    except json.JSONDecodeError as exc:
        if malformed_settings:
            diagnostics.append(_diagnostic(DIAGNOSTIC_MALFORMED_SETTINGS, str(exc), path))
        diagnostics.append(_diagnostic(DIAGNOSTIC_PARSE_ERROR, str(exc), path))
    except OSError as exc:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), path))
    return None


def _iter_settings_hook_commands(settings: object):
    if not isinstance(settings, dict):
        return
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("hooks")
            if not isinstance(inner, list):
                continue
            matcher = entry.get("matcher", "")
            for hook in inner:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if isinstance(command, str) and command.strip():
                    yield {
                        "event": str(event),
                        "matcher": matcher if isinstance(matcher, str) else "",
                        "command": command,
                    }


def _command_hook_name(command: str) -> str:
    for name in set(MST_HOOK_FILE_EVENTS) | USER_GLOBAL_HOOK_NAMES:
        if name in command:
            return name
    return Path(command.strip().split()[0]).name if command.strip() else ""


def _acquire_lock(lock_path: Path) -> bool:
    """Lock 획득. stale lock(>60s)는 자동 무효화."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            mtime = lock_path.stat().st_mtime
            if time.time() - mtime > LOCK_STALE_SECONDS:
                lock_path.unlink(missing_ok=True)
        except OSError:
            return False
    if lock_path.exists():
        return False
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _filter_hooks_block(hooks: dict) -> Tuple[dict, List[str]]:
    """settings.local.json hooks 블록에서 mst 4종 항목만 정규식 매칭으로 제거.

    Returns:
        (filtered_hooks, removed_commands_list)
    """
    removed: List[str] = []
    if not isinstance(hooks, dict):
        return {}, removed
    new_hooks: Dict[str, list] = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            new_hooks[event] = entries
            continue
        kept_entries: list = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            inner = entry.get("hooks") or []
            if not isinstance(inner, list):
                kept_entries.append(entry)
                continue
            kept_inner: list = []
            for h in inner:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                if isinstance(cmd, str) and MST_HOOK_COMMAND_RE.search(cmd):
                    removed.append(cmd)
                    continue
                kept_inner.append(h)
            if kept_inner:
                new_entry = dict(entry)
                new_entry["hooks"] = kept_inner
                kept_entries.append(new_entry)
        if kept_entries:
            new_hooks[event] = kept_entries
    return new_hooks, removed


def _plan_settings_changes(project_root: Path) -> dict:
    """settings.local.json에서 mst hook 항목 식별. 변경 미리보기."""
    settings_path = project_root / ".claude" / "settings.local.json"
    if not settings_path.exists():
        return {"path": str(settings_path), "exists": False, "removed": []}
    try:
        original = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"path": str(settings_path), "exists": True, "removed": [], "parse_error": True}
    if not isinstance(original, dict):
        return {"path": str(settings_path), "exists": True, "removed": []}
    hooks = original.get("hooks", {})
    _, removed = _filter_hooks_block(hooks)
    return {"path": str(settings_path), "exists": True, "removed": removed}


def _plan_file_deletions(project_root: Path) -> List[str]:
    hooks_dir = project_root / ".claude" / "hooks"
    if not hooks_dir.exists():
        return []
    targets: List[str] = []
    for name in MST_HOOK_FILES:
        candidate = hooks_dir / name
        if candidate.exists():
            targets.append(str(candidate))
    return targets


def _classify_environment(project_root: Path, diagnostics: List[dict]) -> dict:
    is_source = _is_plugin_source_repo(project_root)
    parts = project_root.resolve().parts
    is_worktree = ".gran-maestro" in parts and "worktrees" in parts
    has_base = (project_root / ".gran-maestro").is_dir()
    has_project_surface = any(
        (project_root / rel).exists()
        for rel in (".claude", ".claude-plugin", "hooks")
    )

    if is_source:
        kind = "source-dev"
        status = "skipped"
        reason = "plugin source repo (out of cleanup scope)"
    elif is_worktree:
        kind = "worktree"
        status = "diagnostic"
        reason = "worktree-like environment"
    elif has_base or has_project_surface:
        kind = "project"
        status = "ok"
        reason = "project cleanup inventory"
    else:
        kind = "unknown"
        status = "diagnostic"
        reason = DIAGNOSTIC_UNKNOWN_ENVIRONMENT
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_UNKNOWN_ENVIRONMENT,
                "no .gran-maestro, .claude, or plugin metadata found",
                project_root,
            )
        )

    return {
        "project_root": str(project_root),
        "kind": kind,
        "status": status,
        "reason": reason,
        "source_repo": is_source,
        "worktree_like": is_worktree,
        "cleanup_scope": "skipped" if is_source else "project",
    }


def _plugin_inventory_root(project_root: Path) -> Path:
    if (project_root / ".claude-plugin" / "plugin.json").exists():
        return project_root
    return _common._plugin_root()


def _plugin_core_inventory(project_root: Path, diagnostics: List[dict]) -> dict:
    plugin_root = _plugin_inventory_root(project_root)
    manifest_path = plugin_root / ".claude-plugin" / "plugin.json"
    hooks: List[dict] = []
    result = {
        "classification": CLASS_PLUGIN_CORE,
        "status": "unknown",
        "plugin_root": str(plugin_root),
        "manifest": str(manifest_path),
        "registry": None,
        "hooks": hooks,
    }

    manifest = _read_json_diagnostic(manifest_path, diagnostics)
    if not isinstance(manifest, dict):
        diagnostics.append(_diagnostic(DIAGNOSTIC_PARSE_ERROR, "plugin manifest is missing or invalid", manifest_path))
        return result

    registry_ref = manifest.get("hooks")
    registry_path = plugin_root / registry_ref if isinstance(registry_ref, str) else plugin_root / "hooks" / "hooks.json"
    result["registry"] = str(registry_path)
    if not registry_path.exists():
        result["status"] = "missing_registry"
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_MISSING_HOOKS_REGISTRY,
                "plugin hook registry not found",
                registry_path,
            )
        )
        return result

    registry = _read_json_diagnostic(registry_path, diagnostics)
    if not isinstance(registry, dict):
        result["status"] = "parse_error"
        return result

    registry_hooks = registry.get("hooks")
    if not isinstance(registry_hooks, dict):
        result["status"] = "parse_error"
        diagnostics.append(_diagnostic(DIAGNOSTIC_PARSE_ERROR, "plugin hook registry has no hooks object", registry_path))
        return result

    for event, entries in registry_hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher", "")
            inner = entry.get("hooks", [])
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    continue
                hook_name = _command_hook_name(command)
                expected_path = plugin_root / "hooks" / hook_name if hook_name else None
                hooks.append(
                    {
                        "classification": CLASS_PLUGIN_CORE,
                        "status": "canonical" if command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/") else "observed",
                        "event": str(event),
                        "matcher": matcher if isinstance(matcher, str) else "",
                        "command": command,
                        "path": str(expected_path) if expected_path is not None else None,
                    }
                )

    result["status"] = "canonical" if hooks else "empty"
    return result


def _project_legacy_and_custom_inventory(project_root: Path, diagnostics: List[dict]) -> tuple[dict, dict]:
    settings_path = project_root / ".claude" / "settings.local.json"
    project_legacy = {
        "classification": CLASS_PROJECT_LEGACY,
        "settings": {"path": str(settings_path), "candidates": []},
        "files": {"path": str(project_root / ".claude" / "hooks"), "candidates": []},
    }
    user_custom = {
        "classification": CLASS_USER_CUSTOM,
        "settings": [],
        "files": [],
    }

    settings = _read_json_diagnostic(settings_path, diagnostics, malformed_settings=True)
    if isinstance(settings, dict):
        hooks_value = settings.get("hooks")
        if "hooks" in settings and not isinstance(hooks_value, dict):
            diagnostics.append(
                _diagnostic(
                    DIAGNOSTIC_MALFORMED_SETTINGS,
                    "settings.local.json hooks must be a JSON object",
                    settings_path,
                )
            )
        else:
            for item in _iter_settings_hook_commands(settings) or []:
                command = item["command"]
                if MST_HOOK_COMMAND_RE.search(command):
                    project_legacy["settings"]["candidates"].append(
                        {
                            "classification": CLASS_PROJECT_LEGACY,
                            "status": "candidate",
                            "reason": "legacy_mst_settings_hook",
                            **item,
                        }
                    )
                else:
                    user_custom["settings"].append(
                        {
                            "classification": CLASS_USER_CUSTOM,
                            "status": "preserved",
                            "reason": "user_custom_settings_hook",
                            **item,
                        }
                    )
    elif settings_path.exists() and not any(d.get("path") == str(settings_path) for d in diagnostics):
        diagnostics.append(_diagnostic(DIAGNOSTIC_MALFORMED_SETTINGS, "settings.local.json is not a JSON object", settings_path))

    hooks_dir = project_root / ".claude" / "hooks"
    if hooks_dir.exists():
        try:
            mode = hooks_dir.stat().st_mode
            if mode & 0o555 == 0:
                diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, "hooks directory is not readable", hooks_dir))
            else:
                for hook_path in sorted(hooks_dir.iterdir()):
                    if hook_path.name in MST_HOOK_FILES:
                        project_legacy["files"]["candidates"].append(
                            {
                                "classification": CLASS_PROJECT_LEGACY,
                                "status": "candidate",
                                "reason": "legacy_mst_hook_file",
                                "path": str(hook_path),
                                "name": hook_path.name,
                                "event": MST_HOOK_FILE_EVENTS.get(hook_path.name),
                            }
                        )
                    elif hook_path.is_file():
                        user_custom["files"].append(
                            {
                                "classification": CLASS_USER_CUSTOM,
                                "status": "preserved",
                                "reason": "user_custom_hook_file",
                                "path": str(hook_path),
                                "name": hook_path.name,
                            }
                        )
        except PermissionError as exc:
            diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), hooks_dir))
        except OSError as exc:
            diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), hooks_dir))

    return project_legacy, user_custom


def _user_global_inventory(diagnostics: List[dict]) -> dict:
    settings_path = Path.home() / ".claude" / "settings.json"
    result = {
        "classification": CLASS_USER_GLOBAL,
        "settings": {"path": str(settings_path), "exists": settings_path.exists()},
        "hooks": [],
    }
    settings = _read_json_diagnostic(settings_path, diagnostics)
    if isinstance(settings, dict):
        for item in _iter_settings_hook_commands(settings) or []:
            hook_name = _command_hook_name(item["command"])
            result["hooks"].append(
                {
                    "classification": CLASS_USER_GLOBAL,
                    "status": "observed",
                    "reason": "user_global_settings_hook",
                    "known_global": hook_name in USER_GLOBAL_HOOK_NAMES,
                    "name": hook_name,
                    **item,
                }
            )
    return result


def _duplicate_risks(plugin_core: dict, project_legacy: dict) -> List[dict]:
    plugin_events = {
        item.get("event")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and item.get("event")
    }
    legacy_events = {
        item.get("event")
        for group in (
            project_legacy.get("settings", {}).get("candidates", []),
            project_legacy.get("files", {}).get("candidates", []),
        )
        for item in group
        if isinstance(item, dict) and item.get("event")
    }
    risks: List[dict] = []
    for event in sorted(plugin_events & legacy_events):
        risks.append(
            {
                "event": event,
                "sources": [CLASS_PLUGIN_CORE, CLASS_PROJECT_LEGACY],
                "classifications": [CLASS_PLUGIN_CORE, CLASS_PROJECT_LEGACY],
                "reason": "plugin_core_and_project_legacy_hooks_coexist",
            }
        )
    return risks


def _mark_source_dev_project_legacy(project_legacy: dict) -> None:
    for group in (
        project_legacy.get("settings", {}).get("candidates", []),
        project_legacy.get("files", {}).get("candidates", []),
    ):
        for item in group:
            if isinstance(item, dict):
                item["status"] = "skipped"
                item["reason"] = "source_dev_diagnostic_only"


def _build_cleanup_inventory(project_root: Path, *, dry_run: bool, mutated: bool) -> dict:
    diagnostics: List[dict] = []
    environment = _classify_environment(project_root, diagnostics)
    plugin_core = _plugin_core_inventory(project_root, diagnostics)
    project_legacy, user_custom = _project_legacy_and_custom_inventory(project_root, diagnostics)
    user_global = _user_global_inventory(diagnostics)
    if environment.get("source_repo"):
        _mark_source_dev_project_legacy(project_legacy)

    return {
        "mutation": {"dry_run": dry_run, "mutated": mutated},
        "environment": environment,
        "plugin_core": plugin_core,
        "project_legacy": project_legacy,
        "user_global": user_global,
        "user_custom": user_custom,
        "duplicate_risks": _duplicate_risks(plugin_core, project_legacy),
        "diagnostics": diagnostics,
    }


def _settings_diagnostics_block_mutation(project_root: Path, diagnostics: List[dict]) -> bool:
    settings_path = str(project_root / ".claude" / "settings.local.json")
    blocking_codes = {
        DIAGNOSTIC_MALFORMED_SETTINGS,
        DIAGNOSTIC_PARSE_ERROR,
        DIAGNOSTIC_PERMISSION_DENIED,
    }
    for diagnostic in diagnostics:
        if diagnostic.get("path") != settings_path:
            continue
        if diagnostic.get("code") in blocking_codes:
            return True
    return False


def _apply_settings(settings_path: Path, original_text: Optional[str]) -> Tuple[bool, List[str]]:
    """settings.local.json hooks 정리 적용. atomic via tempfile + os.replace."""
    if original_text is None:
        return True, []
    try:
        original = json.loads(original_text)
    except json.JSONDecodeError:
        return True, []
    if not isinstance(original, dict):
        return True, []
    hooks = original.get("hooks", {})
    new_hooks, removed = _filter_hooks_block(hooks)
    if not removed:
        return True, []
    new_settings = dict(original)
    if new_hooks:
        new_settings["hooks"] = new_hooks
    else:
        new_settings.pop("hooks", None)
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".settings.local.json.", suffix=".tmp", dir=str(settings_path.parent)
        )
    except OSError:
        return False, removed
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, settings_path)
        return True, removed
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False, removed


def _apply_file_deletions(targets: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    deleted: List[str] = []
    failed: List[Tuple[str, str]] = []
    for target in targets:
        try:
            Path(target).unlink()
            deleted.append(target)
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed.append((target, str(exc)))
    return deleted, failed


def _emit(args: argparse.Namespace, payload: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if getattr(args, "silent", False):
        return
    if payload.get("status") == "skipped":
        print(f"[mst:on cleanup] skipped: {payload.get('reason', '')}")
        return
    if payload.get("status") == "dry_run":
        print("[mst:on cleanup] dry-run preview:")
        for cmd in payload.get("settings", {}).get("removed", []):
            print(f"  remove settings hook: {cmd}")
        for f in payload.get("files", {}).get("targets", []):
            print(f"  remove file: {f}")
        return
    if payload.get("status") == "ok":
        print(
            f"[mst:on cleanup] removed {len(payload.get('settings', {}).get('removed', []))} settings hooks, "
            f"{len(payload.get('files', {}).get('deleted', []))} files."
        )
    if payload.get("status") == "rollback":
        print("[mst:on cleanup] rollback applied due to partial failure", file=sys.stderr)
    if payload.get("status") == "error":
        print(f"[mst:on cleanup] error: {payload.get('reason', '')}", file=sys.stderr)


def _is_plugin_source_repo(project_root: Path) -> bool:
    """gran-maestro 플러그인 소스 저장소 식별 가드.

    .claude-plugin/plugin.json + hooks/hooks.json이 모두 존재하면 플러그인
    소스 저장소로 판정하여 cleanup 대상에서 제외한다 (No-go scope).
    """
    return (
        (project_root / ".claude-plugin" / "plugin.json").exists()
        and (project_root / "hooks" / "hooks.json").exists()
    )


def cmd_on_cleanup(args) -> int:
    project_root = _project_root()
    lock_path = _common.tmp_dir(project_root) / "cleanup.lock"
    payload: dict = {"project_root": str(project_root)}

    if args.dry_run:
        inventory = _build_cleanup_inventory(project_root, dry_run=True, mutated=False)
        if inventory.get("environment", {}).get("source_repo"):
            payload["status"] = "skipped"
            payload["reason"] = "plugin source repo (out of cleanup scope)"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        else:
            payload["status"] = "dry_run"
            payload["settings"] = _plan_settings_changes(project_root)
            payload["files"] = {"targets": _plan_file_deletions(project_root)}
        payload.update(inventory)
        _emit(args, payload)
        return 0

    if _is_plugin_source_repo(project_root):
        inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        payload["settings"] = {
            "path": str(project_root / ".claude" / "settings.local.json"),
            "exists": (project_root / ".claude" / "settings.local.json").exists(),
            "removed": [],
        }
        payload["files"] = {"targets": _plan_file_deletions(project_root), "deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        _emit(args, payload)
        return 0

    if not _acquire_lock(lock_path):
        inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        payload["settings"] = {"removed": []}
        payload["files"] = {"deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        _emit(args, payload)
        return 0

    try:
        inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
        if _settings_diagnostics_block_mutation(project_root, inventory.get("diagnostics", [])):
            payload.update(inventory)
            payload["status"] = "diagnostic"
            payload["reason"] = "settings.local.json cannot be safely mutated"
            payload["settings"] = {"removed": []}
            payload["files"] = {"targets": _plan_file_deletions(project_root), "deleted": []}
            _emit(args, payload)
            return 0

        settings_path = project_root / ".claude" / "settings.local.json"
        backup_text: Optional[str] = None
        if settings_path.exists():
            try:
                backup_text = settings_path.read_text(encoding="utf-8")
            except OSError:
                payload.update(inventory)
                payload["status"] = "diagnostic"
                payload["reason"] = "settings.local.json cannot be read"
                payload["settings"] = {"removed": []}
                payload["files"] = {"targets": _plan_file_deletions(project_root), "deleted": []}
                _emit(args, payload)
                return 0

        ok_settings, removed = _apply_settings(settings_path, backup_text)
        if not ok_settings:
            payload.update(inventory)
            payload["status"] = "error"
            payload["reason"] = "settings.local.json write failed"
            payload["settings"] = {"removed": [], "failed": removed}
            payload["files"] = {"deleted": []}
            _emit(args, payload)
            return 1

        targets = _plan_file_deletions(project_root)
        deleted, failed = _apply_file_deletions(targets)

        if failed:
            mutated = bool(removed or deleted)
            # rollback settings
            if backup_text is not None:
                try:
                    tmp_fd, tmp_path = tempfile.mkstemp(
                        prefix=".settings.local.json.",
                        suffix=".restore",
                        dir=str(settings_path.parent),
                    )
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        f.write(backup_text)
                    os.replace(tmp_path, settings_path)
                except OSError:
                    pass
            inventory["mutation"]["mutated"] = mutated
            payload.update(inventory)
            payload["status"] = "rollback"
            payload["reason"] = "file deletion failed; settings rollback attempted"
            payload["settings"] = {"removed": removed, "rolled_back": True}
            payload["files"] = {"deleted": deleted, "failed": failed}
            _emit(args, payload)
            return 1

        # cleanup empty .claude/hooks dir (선택)
        hooks_dir = project_root / ".claude" / "hooks"
        try:
            if hooks_dir.exists() and not any(hooks_dir.iterdir()):
                hooks_dir.rmdir()
        except OSError:
            pass

        mutated = bool(removed or deleted)
        inventory["mutation"]["mutated"] = mutated
        payload.update(inventory)
        payload["status"] = "ok"
        payload["settings"] = {"removed": removed}
        payload["files"] = {"deleted": deleted}
        _emit(args, payload)
        return 0
    finally:
        _release_lock(lock_path)


def register(subparsers) -> None:
    on_parser = subparsers.add_parser("on", help="/mst:on 보조 명령")
    on_sub = on_parser.add_subparsers(dest="subcommand")

    cleanup = on_sub.add_parser("cleanup", help="기존 mst hook 사본·settings 항목 정리")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--silent", action="store_true")
    cleanup.add_argument("--json", action="store_true")
