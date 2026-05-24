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
