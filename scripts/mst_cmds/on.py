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

LOCK_STALE_SECONDS = 60


def _project_root() -> Path:
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
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".settings.local.json.", suffix=".tmp", dir=str(settings_path.parent)
    )
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

    if _is_plugin_source_repo(project_root):
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        _emit(args, payload)
        return 0

    if args.dry_run:
        payload["status"] = "dry_run"
        payload["settings"] = _plan_settings_changes(project_root)
        payload["files"] = {"targets": _plan_file_deletions(project_root)}
        _emit(args, payload)
        return 0

    if not _acquire_lock(lock_path):
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        _emit(args, payload)
        return 0

    try:
        settings_path = project_root / ".claude" / "settings.local.json"
        backup_text: Optional[str] = None
        if settings_path.exists():
            try:
                backup_text = settings_path.read_text(encoding="utf-8")
            except OSError:
                backup_text = None

        ok_settings, removed = _apply_settings(settings_path, backup_text)
        if not ok_settings:
            payload["status"] = "error"
            payload["reason"] = "settings.local.json write failed"
            _emit(args, payload)
            return 1

        targets = _plan_file_deletions(project_root)
        deleted, failed = _apply_file_deletions(targets)

        if failed:
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
            payload["status"] = "rollback"
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
