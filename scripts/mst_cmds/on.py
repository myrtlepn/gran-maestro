"""`mst.py on` subcommand — /mst:on 보조 명령.

DOD-008 + DOD-009 (PLN-567) — 등록된 기존 프로젝트의 stale mst hook 사본·
settings.local.json hook 항목을 정규식 식별로 자동 정리한다. 사용자 정의
hook은 100% 보존, 변경은 단일 트랜잭션, lock 파일로 동시 실행 차단,
부분 실패 시 settings 백업으로 rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from scripts.mst_cmds import _common

# AD-007: 등록 프로젝트의 mst hook command 두 변종을 모두 매칭
MST_HOOK_COMMAND_RE = re.compile(
    r"(\$CLAUDE_PROJECT_DIR|\$\(git rev-parse[^)]+\))/\.claude/hooks/"
    r"mst-(stop-hook|session-init|pre-tool-use|auto-chain-context)\.sh"
)
PROJECT_LOCAL_HOOK_COMMAND_RE = re.compile(
    r"(\$CLAUDE_PROJECT_DIR|\$\(git rev-parse[^)]+\))/\.claude/hooks/"
    r"(?P<name>[^/\s\"']+)"
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
DIAGNOSTIC_MISSING_PLUGIN_MANIFEST = "missing_plugin_manifest"
DIAGNOSTIC_BROKEN_CANONICAL_REGISTRATION = "broken_canonical_registration"
DIAGNOSTIC_PARSE_ERROR = "parse_error"
DIAGNOSTIC_PERMISSION_DENIED = "permission_denied"
DIAGNOSTIC_STALE_PLUGIN_CACHE = "stale_plugin_cache"
DIAGNOSTIC_CACHE_SYNC_FAILURE = "cache_sync_failure"
DIAGNOSTIC_UNKNOWN_ENVIRONMENT = "unknown_environment"
DIAGNOSTIC_DUPLICATE_REGISTRATION = "duplicate_registration"
DIAGNOSTIC_DUPLICATE_CANONICAL_REGISTRATION = "duplicate_canonical_registration"
DIAGNOSTIC_DUPLICATE_LEGACY_REGISTRATION = "duplicate_legacy_registration"
DIAGNOSTIC_UNKNOWN_HOOK_COMMAND = "unknown_hook_command"
DIAGNOSTIC_REASON_CODES = (
    DIAGNOSTIC_BROKEN_CANONICAL_REGISTRATION,
    DIAGNOSTIC_CACHE_SYNC_FAILURE,
    DIAGNOSTIC_MALFORMED_SETTINGS,
    DIAGNOSTIC_MISSING_HOOKS_REGISTRY,
    DIAGNOSTIC_MISSING_PLUGIN_MANIFEST,
    DIAGNOSTIC_PARSE_ERROR,
    DIAGNOSTIC_PERMISSION_DENIED,
    DIAGNOSTIC_STALE_PLUGIN_CACHE,
    DIAGNOSTIC_UNKNOWN_ENVIRONMENT,
    DIAGNOSTIC_DUPLICATE_REGISTRATION,
    DIAGNOSTIC_DUPLICATE_CANONICAL_REGISTRATION,
    DIAGNOSTIC_DUPLICATE_LEGACY_REGISTRATION,
    DIAGNOSTIC_UNKNOWN_HOOK_COMMAND,
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
CLEANUP_SCHEMA_VERSION = "mst.on.cleanup.v1"
CLEANUP_DRY_RUN_ARTIFACT = "mst-on-cleanup-dry-run.json"


def _project_root() -> Path:
    env_root = os.environ.get("MST_PROJECT_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().absolute()
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
    return Path.cwd().absolute()


def _diagnostic(
    code: str,
    message: str,
    path: Optional[Path] = None,
    *,
    reason_code: Optional[str] = None,
    reason: Optional[str] = None,
    result: Optional[str] = None,
    status: Optional[str] = None,
    **extra,
) -> dict:
    item = {
        "code": code,
        "reason_code": reason_code or code,
        "reason": reason or reason_code or code,
        "message": message,
    }
    if path is not None:
        item["path"] = str(path)
    if result is not None:
        item["result"] = result
        item["outcome"] = result
    if status is not None:
        item["status"] = status
    for key, value in extra.items():
        if value is not None:
            item[key] = value
    return item


def _annotate_diagnostics(diagnostics: List[dict], *, result: str, status: str) -> None:
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        diagnostic.setdefault("result", result)
        diagnostic.setdefault("outcome", result)
        diagnostic.setdefault("status", status)


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


def _is_canonical_plugin_command(command: str) -> bool:
    return command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/")


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return [command]


def _is_project_legacy_mst_hook_command(command: str, project_root: Path) -> bool:
    if MST_HOOK_COMMAND_RE.search(command):
        return True

    legacy_paths = {
        str((project_root / ".claude" / "hooks" / name).resolve(strict=False))
        for name in MST_HOOK_FILE_EVENTS
    }
    for token in _shell_tokens(command):
        if token.strip("\"'") in legacy_paths:
            return True
    return False


def _project_local_hook_name(command: str, project_root: Path) -> Optional[str]:
    match = PROJECT_LOCAL_HOOK_COMMAND_RE.search(command)
    if match:
        return match.group("name")

    hooks_dir = str((project_root / ".claude" / "hooks").resolve(strict=False))
    prefix = hooks_dir + os.sep
    for token in _shell_tokens(command):
        stripped = token.strip("\"'")
        if stripped.startswith(prefix):
            return Path(stripped).name
    return None


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


def _filter_hooks_block(hooks: dict, project_root: Optional[Path] = None) -> Tuple[dict, List[str]]:
    """settings.local.json hooks 블록에서 mst 4종 항목만 정규식 매칭으로 제거.

    Returns:
        (filtered_hooks, removed_commands_list)
    """
    if project_root is None:
        project_root = _project_root()
    removed: List[str] = []
    removed_seen: set[str] = set()
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
                if isinstance(cmd, str) and _is_project_legacy_mst_hook_command(cmd, project_root):
                    if cmd not in removed_seen:
                        removed.append(cmd)
                        removed_seen.add(cmd)
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
    _, removed = _filter_hooks_block(hooks, project_root)
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


def _has_user_global_settings() -> bool:
    return (Path.home() / ".claude" / "settings.json").exists()


def _source_repo_unknown_reasons(project_root: Path) -> List[str]:
    reasons: List[str] = []
    plugin_dir = project_root / ".claude-plugin"
    hooks_dir = project_root / "hooks"
    plugin_json = plugin_dir / "plugin.json"
    hooks_json = hooks_dir / "hooks.json"

    if plugin_dir.exists() and not plugin_json.exists():
        reasons.append("partial_checkout")
    if plugin_json.exists() and not hooks_json.exists():
        reasons.append(DIAGNOSTIC_MISSING_HOOKS_REGISTRY)
    if hooks_dir.exists() and plugin_dir.exists() and not hooks_json.exists():
        reasons.append("missing_plugin_files")
    return sorted(set(reasons))


def _classify_environment(project_root: Path, diagnostics: List[dict], *, source_repo_opt_in: bool = False) -> dict:
    is_source = _is_plugin_source_repo(project_root)
    resolved_root = project_root.resolve()
    parts = set(project_root.parts) | set(resolved_root.parts)
    is_worktree = ".gran-maestro" in parts and "worktrees" in parts
    has_base = (project_root / ".gran-maestro").is_dir()
    has_project_surface = any(
        (project_root / rel).exists()
        for rel in (".claude", ".claude-plugin", "hooks")
    )
    unknown_reasons: List[str] = []

    try:
        if project_root.is_symlink():
            unknown_reasons.append("symlink_project_root")
    except OSError as exc:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), project_root))
        unknown_reasons.append("project_root_unreadable")

    claude_project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if claude_project_dir:
        try:
            if Path(claude_project_dir).expanduser().resolve() != resolved_root:
                unknown_reasons.append("claude_project_dir_mismatch")
        except OSError:
            unknown_reasons.append("claude_project_dir_mismatch")

    unknown_reasons.extend(_source_repo_unknown_reasons(project_root))
    unknown_reasons = sorted(set(unknown_reasons))

    if unknown_reasons:
        project_kind = "unknown"
        kind = "unknown"
        status = "diagnostic"
        reason = DIAGNOSTIC_UNKNOWN_ENVIRONMENT
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_UNKNOWN_ENVIRONMENT,
                "cleanup environment is ambiguous: " + ", ".join(unknown_reasons),
                project_root,
            )
        )
    elif is_source:
        project_kind = "source_repo"
        kind = "source-dev"
        if source_repo_opt_in:
            status = "ok"
            reason = "plugin source repo cleanup opt-in"
        else:
            status = "skipped"
            reason = "plugin source repo (out of cleanup scope)"
    elif is_worktree:
        project_kind = "worktree"
        kind = "worktree"
        status = "diagnostic"
        reason = "worktree-like environment"
    elif has_base:
        project_kind = "normal_project"
        kind = "project"
        status = "ok"
        reason = "project cleanup inventory"
    elif has_project_surface:
        project_kind = "non_mst"
        kind = "non_mst"
        status = "skipped"
        reason = "non-MST project fail-open"
    else:
        project_kind = "non_mst"
        kind = "non_mst"
        status = "skipped"
        reason = "non-MST project fail-open"

    if project_kind == "unknown":
        mst_mode = "unknown"
    elif project_kind == "source_repo":
        mst_mode = "source_repo"
    elif project_kind == "worktree":
        mst_mode = "worktree"
    elif project_kind == "normal_project":
        mst_mode = "active"
    else:
        mst_mode = "inactive"

    return {
        "project_root": str(project_root),
        "project_kind": project_kind,
        "is_source_repo": is_source,
        "is_worktree": is_worktree,
        "mst_mode": mst_mode,
        "user_global_present": _has_user_global_settings(),
        "unknown_environment_reasons": unknown_reasons,
        "kind": kind,
        "status": status,
        "reason": reason,
        "source_repo": is_source,
        "worktree_like": is_worktree,
        "cleanup_scope": "source-repo-opt-in" if is_source and source_repo_opt_in else "skipped" if is_source else "project",
    }


def _plugin_inventory_root(project_root: Path) -> Path:
    if (project_root / ".claude-plugin").exists():
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

    if not manifest_path.exists():
        result["status"] = "missing_manifest"
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_MISSING_PLUGIN_MANIFEST,
                "plugin manifest not found",
                manifest_path,
            )
        )
        return result

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

    duplicate_sources: Dict[Tuple[str, str, str], List[str]] = {}
    for event, entries in registry_hooks.items():
        if not isinstance(entries, list):
            continue
        for entry_index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher", "")
            inner = entry.get("hooks", [])
            if not isinstance(inner, list):
                continue
            for hook_index, hook in enumerate(inner):
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    continue
                dedupe_key = (str(event), matcher if isinstance(matcher, str) else "", command)
                source_ref = (
                    f"{registry_path}::event={event}::matcher={matcher if isinstance(matcher, str) else ''}"
                    f"::entry={entry_index}::hook={hook_index}"
                )
                duplicate_sources.setdefault(dedupe_key, []).append(source_ref)
                if len(duplicate_sources[dedupe_key]) > 1:
                    continue
                hook_name = _command_hook_name(command)
                expected_path = plugin_root / "hooks" / hook_name if hook_name else None
                hooks.append(
                    {
                        "classification": CLASS_PLUGIN_CORE,
                        "status": "canonical" if _is_canonical_plugin_command(command) else "observed",
                        "event": str(event),
                        "matcher": matcher if isinstance(matcher, str) else "",
                        "command": command,
                        "path": str(expected_path) if expected_path is not None else None,
                    }
                )

    if hooks and any(not _is_canonical_plugin_command(item.get("command", "")) for item in hooks):
        result["status"] = "broken_canonical"
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_BROKEN_CANONICAL_REGISTRATION,
                "plugin hook registry contains non-canonical commands",
                registry_path,
            )
        )
        return result

    result["status"] = "canonical" if hooks else "empty"
    for (event, matcher, command), sources in duplicate_sources.items():
        if len(sources) < 2:
            continue
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_DUPLICATE_CANONICAL_REGISTRATION,
                "duplicate canonical plugin registration observed; inventory output was deduplicated",
                registry_path,
                reason_code=DIAGNOSTIC_DUPLICATE_REGISTRATION,
                reason=DIAGNOSTIC_DUPLICATE_REGISTRATION,
                result="diagnostic",
                status="diagnostic",
                event=event,
                matcher=matcher,
                command=command,
                duplicate_sources=sources,
            )
        )
    return result


def _plugin_cache_root() -> Path:
    return Path.home() / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst"


def _plugin_cache_inventory_diagnostics(diagnostics: List[dict]) -> None:
    cache_root = _plugin_cache_root()
    if not cache_root.exists():
        return

    try:
        installs = sorted(path for path in cache_root.iterdir() if path.is_dir())
    except OSError as exc:
        diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), cache_root))
        return

    if not installs:
        return

    manifest_path = _common._plugin_root() / ".claude-plugin" / "plugin.json"
    manifest = _read_json_diagnostic(manifest_path, diagnostics)
    if not isinstance(manifest, dict):
        return

    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache sync cannot resolve active plugin version",
                manifest_path,
            )
        )
        return
    version = version.strip()

    current_install = cache_root / version
    if not current_install.exists():
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_STALE_PLUGIN_CACHE,
                f"plugin cache does not contain active version {version}",
                cache_root,
            )
        )
        return

    current_manifest_path = current_install / ".claude-plugin" / "plugin.json"
    if not current_manifest_path.exists():
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache manifest is missing",
                current_manifest_path,
            )
        )
        return

    current_manifest = _read_json_diagnostic(current_manifest_path, diagnostics)
    if not isinstance(current_manifest, dict):
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache manifest is invalid",
                current_manifest_path,
            )
        )
        return

    registry_ref = current_manifest.get("hooks")
    registry_path = (
        current_install / registry_ref
        if isinstance(registry_ref, str)
        else current_install / "hooks" / "hooks.json"
    )
    if not registry_path.exists():
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache hooks registry is missing",
                registry_path,
            )
        )
        return

    registry = _read_json_diagnostic(registry_path, diagnostics)
    if not isinstance(registry, dict):
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache hooks registry is invalid",
                registry_path,
            )
        )
        return

    registry_hooks = registry.get("hooks")
    if not isinstance(registry_hooks, dict):
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache hooks registry has no hooks object",
                registry_path,
            )
        )
        return

    commands = [
        hook.get("command")
        for entries in registry_hooks.values()
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict) and isinstance(hook.get("command"), str)
    ]
    if commands and any(not _is_canonical_plugin_command(command) for command in commands):
        diagnostics.append(
            _diagnostic(
                DIAGNOSTIC_CACHE_SYNC_FAILURE,
                "plugin cache hooks registry contains non-canonical commands",
                registry_path,
            )
        )


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
    if settings_path.exists():
        try:
            mode = settings_path.stat().st_mode
            if mode & 0o222 == 0:
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_PERMISSION_DENIED,
                        "settings.local.json is not writable",
                        settings_path,
                    )
                )
        except OSError as exc:
            diagnostics.append(_diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), settings_path))
    if isinstance(settings, dict):
        legacy_settings_duplicates: Dict[Tuple[str, str, str], List[str]] = {}
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
            for index, item in enumerate(_iter_settings_hook_commands(settings) or []):
                command = item["command"]
                if _is_project_legacy_mst_hook_command(command, project_root):
                    dedupe_key = (item["event"], item["matcher"], command)
                    source_ref = (
                        f"{settings_path}::event={item['event']}::matcher={item['matcher']}::hook={index}"
                    )
                    legacy_settings_duplicates.setdefault(dedupe_key, []).append(source_ref)
                    if len(legacy_settings_duplicates[dedupe_key]) > 1:
                        continue
                    project_legacy["settings"]["candidates"].append(
                        {
                            "classification": CLASS_PROJECT_LEGACY,
                            "status": "candidate",
                            "reason": "legacy_mst_settings_hook",
                            **item,
                        }
                    )
                else:
                    hook_name = _project_local_hook_name(command, project_root)
                    user_custom["settings"].append(
                        {
                            "classification": CLASS_USER_CUSTOM,
                            "status": "preserved",
                            "reason": (
                                "unknown_project_local_hook_command"
                                if hook_name
                                else "user_custom_settings_hook"
                            ),
                            "project_local": bool(hook_name),
                            "hook_name": hook_name,
                            **item,
                        }
                    )
                    if hook_name:
                        diagnostics.append(
                            _diagnostic(
                                DIAGNOSTIC_UNKNOWN_HOOK_COMMAND,
                                "unknown project-local hook command preserved for manual review",
                                settings_path,
                                reason="manual-review",
                                result="safe-skip",
                                status="diagnostic",
                                event=item["event"],
                                matcher=item["matcher"],
                                command=command,
                                hook_name=hook_name,
                            )
                        )
            for (event, matcher, command), sources in legacy_settings_duplicates.items():
                if len(sources) < 2:
                    continue
                diagnostics.append(
                    _diagnostic(
                        DIAGNOSTIC_DUPLICATE_LEGACY_REGISTRATION,
                        "duplicate legacy settings registration observed; cleanup candidates were deduplicated",
                        settings_path,
                        reason_code=DIAGNOSTIC_DUPLICATE_REGISTRATION,
                        reason=DIAGNOSTIC_DUPLICATE_REGISTRATION,
                        result="safe-skip",
                        status="diagnostic",
                        event=event,
                        matcher=matcher,
                        command=command,
                        duplicate_sources=sources,
                    )
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
                    "preservation": "preserved-state",
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


def _build_cleanup_inventory(
    project_root: Path,
    *,
    dry_run: bool,
    mutated: bool,
    source_repo_opt_in: bool = False,
) -> dict:
    diagnostics: List[dict] = []
    environment = _classify_environment(project_root, diagnostics, source_repo_opt_in=source_repo_opt_in)
    plugin_core = _plugin_core_inventory(project_root, diagnostics)
    project_legacy, user_custom = _project_legacy_and_custom_inventory(project_root, diagnostics)
    user_global = _user_global_inventory(diagnostics)
    _plugin_cache_inventory_diagnostics(diagnostics)
    if environment.get("source_repo") and not source_repo_opt_in:
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


def _diagnostics_block_mutation(project_root: Path, inventory: dict) -> bool:
    environment = inventory.get("environment", {})
    if environment.get("project_kind") == "unknown" or environment.get("unknown_environment_reasons"):
        return True
    diagnostics = inventory.get("diagnostics", [])
    blocking_codes = {
        DIAGNOSTIC_BROKEN_CANONICAL_REGISTRATION,
        DIAGNOSTIC_CACHE_SYNC_FAILURE,
        DIAGNOSTIC_MISSING_PLUGIN_MANIFEST,
        DIAGNOSTIC_STALE_PLUGIN_CACHE,
    }
    if any(isinstance(item, dict) and item.get("code") in blocking_codes for item in diagnostics):
        return True
    return _settings_diagnostics_block_mutation(project_root, diagnostics)


def _candidate_set(settings_removed: List[str], file_targets: List[str], project_root: Path) -> List[dict]:
    settings_path = project_root / ".claude" / "settings.local.json"
    candidates: List[dict] = []
    for command in sorted(settings_removed):
        candidates.append(
            {
                "type": "settings_hook",
                "path": str(settings_path),
                "command": command,
            }
        )
    for target in sorted(file_targets):
        target_path = Path(target)
        candidates.append(
            {
                "type": "hook_file",
                "path": str(target_path),
                "name": target_path.name,
            }
        )
    return candidates


def _candidate_hash(candidate_set: List[dict]) -> str:
    encoded = json.dumps(candidate_set, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _created_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cleanup_artifact_path(project_root: Path) -> Optional[Path]:
    base_dir = project_root / ".gran-maestro"
    if not base_dir.exists():
        return None
    return _common.tmp_dir(project_root) / CLEANUP_DRY_RUN_ARTIFACT


def _rollback_plan(project_root: Path, candidate_set: List[dict]) -> dict:
    backup_path = _common.tmp_dir(project_root) / "mst-on-cleanup-rollback.json"
    inverse_operations: List[dict] = []
    restore_targets: List[str] = []
    for candidate in candidate_set:
        candidate_path = candidate.get("path")
        if isinstance(candidate_path, str) and candidate_path not in restore_targets:
            restore_targets.append(candidate_path)
        if candidate.get("type") == "settings_hook":
            inverse_operations.append(
                {
                    "type": "restore_settings_hook",
                    "path": candidate_path,
                    "command": candidate.get("command"),
                }
            )
        elif candidate.get("type") == "hook_file":
            inverse_operations.append(
                {
                    "type": "restore_hook_file",
                    "path": candidate_path,
                }
            )
    return {
        "available": bool(candidate_set),
        "backup_path": str(backup_path),
        "restore_targets": restore_targets,
        "inverse_operations": inverse_operations,
    }


def _post_check_required(environment: dict) -> List[str]:
    checks = [
        "stale_cleanup_candidates_absent",
        "plugin_core_canonical_command",
        "user_custom_preserved",
    ]
    project_kind = environment.get("project_kind")
    if project_kind == "source_repo":
        checks.append("source_repo_default_skip_or_opt_in")
    if project_kind == "worktree":
        checks.append("worktree_no_legacy_propagation")
    if project_kind == "non_mst" or environment.get("user_global_present"):
        checks.append("non_mst_user_global_fail_open")
    return checks


def _preserved_user_hooks(user_custom: dict) -> List[dict]:
    preserved: List[dict] = []
    for item in user_custom.get("settings", []):
        if isinstance(item, dict):
            preserved.append(
                {
                    "type": "settings_hook",
                    "event": item.get("event"),
                    "matcher": item.get("matcher", ""),
                    "command": item.get("command"),
                    "reason": item.get("reason", "user_custom_settings_hook"),
                }
            )
    for item in user_custom.get("files", []):
        if isinstance(item, dict):
            preserved.append(
                {
                    "type": "hook_file",
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "reason": item.get("reason", "user_custom_hook_file"),
                }
            )
    return preserved


def _status_items(diagnostics: List[dict], status: str) -> List[dict]:
    return [
        {
            "status": status,
            "reason": item.get("reason") or item.get("reason_code") or item.get("code"),
            "reason_code": item.get("reason_code") or item.get("code"),
            "result": item.get("result") or item.get("outcome"),
            "outcome": item.get("outcome") or item.get("result"),
            "message": item.get("message", ""),
            "path": item.get("path"),
        }
        for item in diagnostics
    ]


def _migration_boundary_items(inventory: dict) -> List[dict]:
    environment = inventory.get("environment", {})
    plugin_core = inventory.get("plugin_core", {})
    project_legacy = inventory.get("project_legacy", {})
    user_global = inventory.get("user_global", {})
    diagnostics = inventory.get("diagnostics", [])

    settings_candidates = project_legacy.get("settings", {}).get("candidates", [])
    file_candidates = project_legacy.get("files", {}).get("candidates", [])
    legacy_candidate_count = len(settings_candidates) + len(file_candidates)
    source_default_skip = bool(environment.get("source_repo")) and environment.get("cleanup_scope") == "skipped"
    blocked = _diagnostics_block_mutation(Path(environment.get("project_root", "")), inventory)

    if source_default_skip:
        legacy_status = "SKIP"
        legacy_result = "diagnostic-only"
        legacy_message = "source-dev project-local hooks remain diagnostic-only unless --source-repo is used"
    elif blocked:
        legacy_status = "DIAGNOSTIC"
        legacy_result = "safe-skip"
        legacy_message = "legacy project-local hook cleanup is blocked and pre-mutation state is preserved"
    else:
        legacy_status = "PASS"
        legacy_result = "reinjection-absent"
        legacy_message = "legacy project-local hooks are candidates only; canonical runtime is not reinserted"

    plugin_commands = [
        item.get("command")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]
    canonical = plugin_core.get("status") in {"canonical", "empty"} and all(
        _is_canonical_plugin_command(command)
        for command in plugin_commands
    )
    if canonical:
        plugin_status = "PASS"
        plugin_message = "canonical plugin registration is preserved"
    else:
        plugin_status = "DIAGNOSTIC"
        plugin_message = "canonical plugin registration needs inspection"

    user_settings = user_global.get("settings", {})
    user_settings_path = user_settings.get("path")
    user_global_diag = any(
        isinstance(item, dict) and item.get("path") == user_settings_path
        for item in diagnostics
    )
    if user_global_diag:
        user_status = "DIAGNOSTIC"
        user_result = "safe-skip"
        user_message = "user-global hook settings could not be fully inspected and were not mutated"
    elif user_settings.get("exists"):
        user_status = "PASS"
        user_result = "preserved-state"
        user_message = "user-global hook settings are observed and preserved"
    else:
        user_status = "SKIP"
        user_result = "absent"
        user_message = "user-global hook settings are absent"

    return [
        {
            "id": "legacy_project_local_hook_reinjection",
            "status": legacy_status,
            "result": legacy_result,
            "message": legacy_message,
            "classification": CLASS_PROJECT_LEGACY,
            "candidate_count": legacy_candidate_count,
            "settings_candidate_count": len(settings_candidates),
            "file_candidate_count": len(file_candidates),
            "prohibited_actions": [
                "create_.claude_hooks_copy",
                "reinsert_settings_local_hooks_as_canonical_runtime",
            ],
            "evidence": {
                "cleanup_scope": environment.get("cleanup_scope"),
                "project_kind": environment.get("project_kind"),
            },
        },
        {
            "id": "canonical_plugin_registration",
            "status": plugin_status,
            "result": "preserved-state" if canonical else "diagnostic",
            "message": plugin_message,
            "classification": CLASS_PLUGIN_CORE,
            "manifest": plugin_core.get("manifest"),
            "registry": plugin_core.get("registry"),
            "canonical_command_count": len(
                [command for command in plugin_commands if _is_canonical_plugin_command(command)]
            ),
            "command_prefix": "${CLAUDE_PLUGIN_ROOT}/hooks/",
        },
        {
            "id": "user_global_hook_preservation",
            "status": user_status,
            "result": user_result,
            "message": user_message,
            "classification": CLASS_USER_GLOBAL,
            "settings_path": user_settings_path,
            "hook_count": len(user_global.get("hooks", [])),
        },
    ]


def _migration_boundary(inventory: dict) -> dict:
    items = _migration_boundary_items(inventory)
    summary = {"PASS": 0, "SKIP": 0, "DIAGNOSTIC": 0}
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
    return {
        "schema_version": "mst.on.cleanup.boundary.v1",
        "items": items,
        "summary": summary,
    }


def _enrich_cleanup_payload(
    payload: dict,
    *,
    project_root: Path,
    inventory: dict,
    settings_removed: List[str],
    file_targets: List[str],
    dry_run: bool,
) -> None:
    candidates = _candidate_set(settings_removed, file_targets, project_root)
    candidate_hash = _candidate_hash(candidates)
    created_at = _created_at()
    dry_run_id = hashlib.sha256(
        json.dumps(
            {
                "schema_version": CLEANUP_SCHEMA_VERSION,
                "project_root": str(project_root),
                "created_at": created_at,
                "candidate_hash": candidate_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    environment = inventory.get("environment", {})
    rollback = _rollback_plan(project_root, candidates)
    diagnostics = inventory.get("diagnostics", [])
    blocked = _status_items(diagnostics, "blocked") if diagnostics else []
    skipped = []
    if environment.get("project_kind") in {"source_repo", "non_mst", "worktree"} and not candidates:
        skipped.append(
            {
                "status": "skipped",
                "reason": environment.get("reason"),
                "reason_code": environment.get("project_kind"),
            }
        )

    payload.update(
        {
            "schema_version": CLEANUP_SCHEMA_VERSION,
            "dry_run_id": dry_run_id,
            "dry_run": dry_run,
            "created_at": created_at,
            "candidate_set": candidates,
            "candidate_hash": candidate_hash,
            "preserved_user_hooks": _preserved_user_hooks(inventory.get("user_custom", {})),
            "skipped": skipped,
            "blocked": blocked,
            "rollback": rollback,
            "rollback_available": rollback["available"],
            "post_check_required": _post_check_required(environment),
            "migration_boundary": _migration_boundary(inventory),
        }
    )


def _write_dry_run_artifact(project_root: Path, payload: dict) -> None:
    artifact_path = _cleanup_artifact_path(project_root)
    if artifact_path is None:
        return
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_dry_run_artifact(project_root: Path, args: argparse.Namespace, diagnostics: List[dict]) -> Optional[dict]:
    explicit_path = getattr(args, "dry_run_artifact", None)
    artifact_path = Path(explicit_path).expanduser() if explicit_path else _cleanup_artifact_path(project_root)
    if artifact_path is None or not artifact_path.exists():
        if explicit_path or getattr(args, "dry_run_id", None):
            diagnostics.append(_diagnostic("dry_run_artifact_missing", "dry-run artifact not found", artifact_path))
        return None
    artifact = _read_json_diagnostic(artifact_path, diagnostics)
    return artifact if isinstance(artifact, dict) else None


def _validate_dry_run_artifact(
    project_root: Path,
    args: argparse.Namespace,
    artifact: Optional[dict],
    current_candidate_set: List[dict],
    current_candidate_hash: str,
) -> List[str]:
    if artifact is None:
        return []

    mismatches: List[str] = []
    if artifact.get("schema_version") != CLEANUP_SCHEMA_VERSION:
        mismatches.append("schema_version_mismatch")
    if artifact.get("project_root") != str(project_root):
        mismatches.append("project_root_mismatch")
    expected_dry_run_id = getattr(args, "dry_run_id", None)
    if expected_dry_run_id and artifact.get("dry_run_id") != expected_dry_run_id:
        mismatches.append("dry_run_id_mismatch")
    if artifact.get("candidate_set") != current_candidate_set:
        mismatches.append("candidate_set_mismatch")
    if artifact.get("candidate_hash") != current_candidate_hash:
        mismatches.append("candidate_hash_mismatch")
    for required in ("dry_run_id", "candidate_set", "candidate_hash"):
        if required not in artifact:
            mismatches.append(f"{required}_missing")
    return sorted(set(mismatches))


def _post_check(project_root: Path, environment: dict) -> dict:
    return _post_check_with_context(
        project_root,
        environment=environment,
        expected_preserved_user_hooks=None,
        expected_candidate_set=None,
    )


def _post_check_with_context(
    project_root: Path,
    *,
    environment: dict,
    expected_preserved_user_hooks: Optional[List[dict]],
    expected_candidate_set: Optional[List[dict]],
    allow_expected_candidates: bool = False,
) -> dict:
    inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
    settings_removed = _plan_settings_changes(project_root).get("removed", [])
    file_targets = _plan_file_deletions(project_root)
    current_candidate_set = _candidate_set(settings_removed, file_targets, project_root)
    current_preserved = _preserved_user_hooks(inventory.get("user_custom", {}))
    plugin_core = inventory.get("plugin_core", {})
    plugin_core_commands = [
        item.get("command")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]
    plugin_core_canonical = all(
        _is_canonical_plugin_command(command)
        for command in plugin_core_commands
    )
    user_custom_preserved = (
        current_preserved == expected_preserved_user_hooks
        if expected_preserved_user_hooks is not None
        else True
    )

    if not current_candidate_set:
        candidate_state = "absent"
    elif expected_candidate_set is not None and current_candidate_set == expected_candidate_set:
        candidate_state = "restored"
    else:
        candidate_state = "present"

    expected_candidates_restored = allow_expected_candidates and candidate_state == "restored"
    checks = {
        "stale_cleanup_candidates_absent": not current_candidate_set,
        "unexpected_cleanup_candidates_absent": not current_candidate_set or expected_candidates_restored,
        "plugin_core_canonical_command": plugin_core_canonical,
        "user_custom_preserved": user_custom_preserved,
    }
    if allow_expected_candidates:
        checks["rollback_restored_pre_mutation_state"] = expected_candidates_restored
        checks["stale_cleanup_reinjection_absent"] = expected_candidates_restored

    project_kind = environment.get("project_kind")
    if project_kind == "source_repo":
        checks["source_repo_default_skip_or_opt_in"] = all(
            not str(item.get("path", "")).startswith(str(project_root / "hooks"))
            and "hooks/hooks.json" not in str(item.get("path", ""))
            for item in current_candidate_set
        )
    if project_kind == "worktree":
        checks["worktree_no_legacy_propagation"] = not current_candidate_set
    if project_kind == "non_mst" or environment.get("user_global_present"):
        checks["non_mst_user_global_fail_open"] = True

    required_checks = dict(checks)
    if expected_candidates_restored:
        required_checks["stale_cleanup_candidates_absent"] = True

    return {
        "passed": all(required_checks.values()),
        "checks": checks,
        "candidate_state": candidate_state,
        "evidence": {
            "remaining_settings_removed": settings_removed,
            "remaining_file_targets": file_targets,
            "current_candidate_set": current_candidate_set,
            "plugin_core_commands": plugin_core_commands,
            "preserved_user_hooks": current_preserved,
        },
    }


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
    project_root = settings_path.parent.parent
    new_hooks, removed = _filter_hooks_block(hooks, project_root)
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
    existing = [Path(target) for target in targets if Path(target).exists()]
    if not existing:
        return [], []

    backups: Dict[Path, Tuple[bytes, int]] = {}
    for target in existing:
        try:
            stat_result = target.stat()
            backups[target] = (target.read_bytes(), stat_result.st_mode)
        except OSError as exc:
            return [], [(str(target), str(exc))]

    try:
        quarantine_dir = Path(tempfile.mkdtemp(prefix=".mst-cleanup.", dir=str(existing[0].parent)))
    except OSError as exc:
        return [], [(str(target), str(exc)) for target in existing]

    moved: List[Tuple[Path, Path]] = []
    failed: List[Tuple[str, str]] = []
    for index, target in enumerate(existing):
        quarantine_path = quarantine_dir / f"{index}-{target.name}"
        try:
            os.replace(target, quarantine_path)
            moved.append((target, quarantine_path))
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed.append((str(target), str(exc)))
            break

    def restore_targets() -> None:
        for target, quarantine_path in reversed(moved):
            try:
                if quarantine_path.exists():
                    os.replace(quarantine_path, target)
            except OSError as exc:
                failed.append((str(target), f"restore failed: {exc}"))
        for target, (content, mode) in backups.items():
            if target.exists():
                continue
            try:
                target.write_bytes(content)
                target.chmod(mode & 0o777)
            except OSError as exc:
                failed.append((str(target), f"restore failed: {exc}"))

    if failed:
        restore_targets()
        try:
            quarantine_dir.rmdir()
        except OSError:
            pass
        return [], failed

    deleted: List[str] = []
    for target, quarantine_path in moved:
        try:
            quarantine_path.unlink()
            deleted.append(str(target))
        except OSError as exc:
            failed.append((str(target), str(exc)))
            break

    if failed:
        restore_targets()
        try:
            quarantine_dir.rmdir()
        except OSError:
            pass
        return [], failed

    try:
        quarantine_dir.rmdir()
    except OSError:
        pass
    return deleted, []


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
        for item in payload.get("preserved_user_hooks", []):
            value = item.get("command") or item.get("path")
            if value:
                print(f"  preserve user hook: {value}")
        for item in payload.get("skipped", []):
            print(f"  skipped: {item.get('reason', '')}")
        for item in payload.get("blocked", []):
            print(f"  blocked: {item.get('reason_code') or item.get('reason', '')}")
        boundary = payload.get("migration_boundary", {})
        for item in boundary.get("items", []):
            print(f"  {item.get('status')} {item.get('id')}: {item.get('message', '')}")
        rollback = payload.get("rollback", {})
        if rollback:
            print(f"  rollback available: {str(rollback.get('available')).lower()}")
            if rollback.get("backup_path"):
                print(f"  rollback backup: {rollback.get('backup_path')}")
        for check in payload.get("post_check_required", []):
            print(f"  post-check required: {check}")
        return
    if payload.get("status") in {"blocked", "diagnostic"}:
        print(f"[mst:on cleanup] {payload.get('status')}: {payload.get('reason', '')}")
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
    source_repo_opt_in = bool(getattr(args, "source_repo", False))

    if args.dry_run:
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=True,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        environment = inventory.get("environment", {})
        if environment.get("source_repo") and not source_repo_opt_in:
            payload["status"] = "skipped"
            payload["reason"] = "plugin source repo (out of cleanup scope)"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        elif _diagnostics_block_mutation(project_root, inventory):
            _annotate_diagnostics(inventory.get("diagnostics", []), result="safe-skip", status="diagnostic")
            payload["status"] = "diagnostic"
            payload["reason"] = "cleanup environment cannot be safely mutated"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        elif environment.get("project_kind") == "non_mst":
            payload["status"] = "skipped"
            payload["reason"] = "non-MST project fail-open"
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
        payload["status"] = payload.get("status")
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=payload.get("settings", {}).get("removed", []),
            file_targets=payload.get("files", {}).get("targets", []),
            dry_run=True,
        )
        if payload.get("status") == "dry_run":
            try:
                _write_dry_run_artifact(project_root, payload)
            except OSError as exc:
                payload.setdefault("diagnostics", []).append(
                    _diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), _cleanup_artifact_path(project_root))
                )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    if _is_plugin_source_repo(project_root) and not source_repo_opt_in:
        inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        payload["settings"] = {
            "path": str(project_root / ".claude" / "settings.local.json"),
            "exists": (project_root / ".claude" / "settings.local.json").exists(),
            "removed": [],
        }
        payload["files"] = {"targets": [], "deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=[],
            file_targets=[],
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    if not _acquire_lock(lock_path):
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=False,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        payload["settings"] = {"removed": []}
        payload["files"] = {"deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=[],
            file_targets=[],
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    try:
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=False,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        if _diagnostics_block_mutation(project_root, inventory):
            _annotate_diagnostics(inventory.get("diagnostics", []), result="safe-skip", status="diagnostic")
            payload.update(inventory)
            payload["status"] = "diagnostic"
            payload["reason"] = "cleanup environment cannot be safely mutated"
            payload["settings"] = {"removed": []}
            payload["files"] = {"targets": [], "deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=[],
                file_targets=[],
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
            _emit(args, payload)
            return 0

        planned_settings = _plan_settings_changes(project_root).get("removed", [])
        planned_files = _plan_file_deletions(project_root)
        current_candidates = _candidate_set(planned_settings, planned_files, project_root)
        current_candidate_hash = _candidate_hash(current_candidates)
        artifact_diagnostics: List[dict] = []
        artifact = _read_dry_run_artifact(project_root, args, artifact_diagnostics)
        if artifact is None and current_candidates:
            artifact_diagnostics.append(
                _diagnostic("dry_run_artifact_missing", "dry-run artifact not found", project_root)
            )
        mismatches = _validate_dry_run_artifact(
            project_root,
            args,
            artifact,
            current_candidates,
            current_candidate_hash,
        )
        if artifact_diagnostics or mismatches:
            for mismatch in mismatches:
                artifact_diagnostics.append(
                    _diagnostic(
                        mismatch,
                        f"dry-run artifact validation failed: {mismatch}",
                        project_root,
                        result="preserved-state",
                        status="blocked",
                    )
                )
            _annotate_diagnostics(artifact_diagnostics, result="preserved-state", status="blocked")
            inventory["diagnostics"].extend(artifact_diagnostics)
            payload.update(inventory)
            payload["status"] = "blocked"
            payload["reason"] = "dry_run_candidate_mismatch" if mismatches else "dry_run_artifact_unavailable"
            payload["settings"] = {"removed": []}
            payload["files"] = {"targets": planned_files, "deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=planned_settings,
                file_targets=planned_files,
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
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
                payload["files"] = {"targets": planned_files, "deleted": []}
                _enrich_cleanup_payload(
                    payload,
                    project_root=project_root,
                    inventory=inventory,
                    settings_removed=[],
                    file_targets=[],
                    dry_run=False,
                )
                payload["post_check"] = _post_check_with_context(
                    project_root,
                    environment=inventory.get("environment", {}),
                    expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                    expected_candidate_set=payload.get("candidate_set"),
                )
                _emit(args, payload)
                return 0

        ok_settings, removed = _apply_settings(settings_path, backup_text)
        if not ok_settings:
            payload.update(inventory)
            payload["status"] = "error"
            payload["reason"] = "settings.local.json write failed"
            payload["settings"] = {"removed": [], "failed": removed}
            payload["files"] = {"deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=[],
                file_targets=[],
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
            _emit(args, payload)
            return 1

        targets = planned_files
        deleted, failed = _apply_file_deletions(targets)

        if failed:
            mutated = bool(removed or deleted)
            # rollback settings
            settings_rolled_back = backup_text is None
            settings_rollback_error = None
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
                    settings_rolled_back = True
                except OSError as exc:
                    settings_rollback_error = str(exc)
            inventory["mutation"]["mutated"] = mutated and settings_rolled_back
            payload.update(inventory)
            payload["status"] = "rollback" if settings_rolled_back else "error"
            payload["reason"] = (
                "file deletion failed; settings rollback attempted"
                if settings_rolled_back
                else "file deletion failed; settings rollback failed"
            )
            payload["settings"] = {"removed": removed, "rolled_back": settings_rolled_back}
            if settings_rollback_error is not None:
                payload["settings"]["rollback_error"] = settings_rollback_error
            payload["files"] = {"deleted": deleted, "failed": failed}
            payload.setdefault("diagnostics", []).append(
                _diagnostic(
                    "file_deletion_failed",
                    "file deletion failed; restored pre-mutation state where possible",
                    Path(failed[0][0]),
                    result="preserved-state",
                    status="rollback" if settings_rolled_back else "error",
                )
            )
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=removed,
                file_targets=targets,
                dry_run=False,
            )
            rollback = payload.get("rollback")
            if isinstance(rollback, dict):
                failed_path, failed_reason = failed[0]
                rollback["failed_operation"] = {
                    "type": "file_delete",
                    "path": failed_path,
                    "reason": failed_reason,
                }
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
                allow_expected_candidates=True,
            )
            _emit(args, payload)
            return 1

        # cleanup empty .claude/hooks dir (선택)
        hooks_dir = project_root / ".claude" / "hooks"
        try:
            if deleted and hooks_dir.exists() and not any(hooks_dir.iterdir()):
                hooks_dir.rmdir()
        except OSError:
            pass

        mutated = bool(removed or deleted)
        inventory["mutation"]["mutated"] = mutated
        payload.update(inventory)
        payload["status"] = "ok"
        payload["settings"] = {"removed": removed}
        payload["files"] = {"deleted": deleted}
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=removed,
            file_targets=targets,
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0
    finally:
        _release_lock(lock_path)


def register(subparsers) -> None:
    on_parser = subparsers.add_parser("on", help="/mst:on 보조 명령")
    on_sub = on_parser.add_subparsers(dest="subcommand")

    cleanup = on_sub.add_parser("cleanup", help="기존 mst hook 사본·settings 항목 정리")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--source-repo", action="store_true", help="플러그인 소스 저장소 legacy hook cleanup을 명시적으로 허용")
    cleanup.add_argument("--dry-run-id", help="직전 dry-run artifact id와 일치할 때만 apply 허용")
    cleanup.add_argument("--dry-run-artifact", help="검증할 cleanup dry-run JSON artifact 경로")
    cleanup.add_argument("--silent", action="store_true")
    cleanup.add_argument("--json", action="store_true")
