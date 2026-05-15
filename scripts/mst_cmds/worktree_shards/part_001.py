from __future__ import annotations
import argparse
import copy
import errno
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
from scripts.mst_cmds.session import (
    SESSION_WORKTREE_ACTIVE_STATES,
    session_metadata_path,
    validate_mst_session_id,
)
FALLBACK_PROTECTED_BRANCHES = ["main", "master", "release/*"]
MST_WORKTREE_HOOK_COMMAND_RE = re.compile(
    r"(\$CLAUDE_PROJECT_DIR|\$\(git rev-parse[^)]+\))/\.claude/hooks/"
    r"mst-(stop-hook|session-init|pre-tool-use|auto-chain-context)\.sh"
)
MST_WORKTREE_HOOK_MARKER_FILES = {
    ".mst-hook-version",
    "stop-agile-gate-reasons.json",
}
def base_slug(base: str) -> str:
    return str(base).replace("/", "-")
def _agi_segment(agi_id: str | None) -> str | None:
    agi_value = str(agi_id).strip() if agi_id is not None else ""
    return agi_value or None
def req_branch_name(req_id: str, base: str, agi_id: str | None = None) -> str:
    agi_value = _agi_segment(agi_id)
    if agi_value:
        return f"gran-maestro/{base_slug(base)}/{agi_value}/{req_id}"
    return f"gran-maestro/{base_slug(base)}/{req_id}"
def task_branch_name(req_id: str, task_id: str, base: str, agi_id: str | None = None) -> str:
    return f"{req_branch_name(req_id, base, agi_id)}-{task_id}"
def role_branch_name(req_id: str, role: str, base: str, agi_id: str | None = None) -> str:
    role_value = str(role).strip()
    normalized_role = role_value.lower()
    if normalized_role == "integration":
        return req_branch_name(req_id, base, agi_id)
    if normalized_role.startswith("review-"):
        return f"{req_branch_name(req_id, base, agi_id)}-review-{role_value[7:]}"
    return f"{req_branch_name(req_id, base, agi_id)}-{normalized_role}"
def role_worktree_path(project_root: Path, req_id: str, role: str, agi_id: str | None = None) -> Path:
    role_value = str(role).strip()
    normalized_role = role_value.lower()
    agi_value = _agi_segment(agi_id)
    if agi_value:
        if normalized_role.startswith("review-"):
            return _common.worktrees_dir(project_root) / agi_value / req_id / "review" / role_value[7:]
        return _common.worktrees_dir(project_root) / agi_value / req_id / normalized_role
    return _common.worktrees_dir(project_root) / req_id / normalized_role
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
def _persist_detected_base(
    req_id: str,
    detected_base: str,
    *,
    parent_session: dict | None = None,
) -> None:
    request_path = _common.requests_dir() / req_id / "request.json"
    request_data = _common.load_json(request_path)
    if not isinstance(request_data, dict):
        raise RuntimeError(f"request.json 읽기 실패: {request_path}")
    request_data["detected_base"] = detected_base
    if parent_session is not None:
        request_data["parent_mst_session_id"] = parent_session["mst_session_id"]
        request_data["parent_session_branch"] = parent_session["session_branch"]
        request_data["parent_session_worktree_path"] = parent_session["session_worktree_path"]
        request_data["original_base_branch"] = parent_session.get("base_branch")
        request_data["original_base_sha"] = parent_session.get("base_sha")
    _common.save_json(request_path, request_data)
def _print_resolve_base_payload(
    detected_base: str,
    req_id: str | None,
    as_json: bool,
    *,
    parent_session: dict | None = None,
) -> None:
    if not as_json:
        print(detected_base)
        return
    payload = {
        "base": detected_base,
        "base_slug": base_slug(detected_base),
    }
    if req_id:
        payload["req_branch"] = req_branch_name(req_id, detected_base)
    if parent_session is not None:
        payload["parent_mst_session_id"] = parent_session["mst_session_id"]
        payload["parent_session_branch"] = parent_session["session_branch"]
        payload["parent_session_worktree_path"] = parent_session["session_worktree_path"]
        payload["original_base_branch"] = parent_session.get("base_branch")
        payload["original_base_sha"] = parent_session.get("base_sha")
        payload["merge_scope"] = {
            "ok": True,
            "caller": "request_child_accept",
            "requested_target": "child_to_session",
            "merge_state": "authorized_child_merge",
            "child_to_session": True,
            "session_to_original": False,
            "target_branch": parent_session["session_branch"],
            "session_branch": parent_session["session_branch"],
            "original_base_branch": parent_session.get("base_branch"),
            "original_base_sha": parent_session.get("base_sha"),
            "forbidden_caller": False,
            "required_evidence": [],
            "reference_only_fields": ["original_base_branch", "original_base_sha"],
            "evidence": {"merge_target": "parent_session_branch"},
        }
    print(json.dumps(payload, ensure_ascii=False))
def _session_child_non_success(reason: str, action: str, *, details: dict | None = None) -> dict:
    payload = {
        "ok": False,
        "base": None,
        "reason": reason,
        "action": action,
    }
    if details:
        payload["details"] = details
    return payload
def _print_session_child_non_success(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    print(f"Error: {payload['reason']}. action={payload['action']}", file=sys.stderr)
def _resolve_parent_session_context() -> tuple[dict | None, dict | None]:
    raw_session_id = os.environ.get("MST_SESSION_ID", "").strip()
    if not raw_session_id:
        return None, _session_child_non_success(
            "missing_mst_session_id",
            "start_or_resume_mst_session_before_child_worktree",
        )
    try:
        parsed = validate_mst_session_id(raw_session_id)
    except ValueError as exc:
        return None, _session_child_non_success(
            "invalid_mst_session_id",
            "provide_structured_mst_session_id",
            details={"error": str(exc)},
        )

    payload = _common.load_json(session_metadata_path(_common.BASE_DIR, parsed.mst_session_id))
    if not isinstance(payload, dict):
        return None, _session_child_non_success(
            "session_metadata_missing",
            "ensure_session_worktree_contract_before_child_worktree",
        )

    state = str(payload.get("state") or "").strip()
    if state not in SESSION_WORKTREE_ACTIVE_STATES:
        return None, _session_child_non_success(
            str(payload.get("reason") or "session_worktree_not_active"),
            str(payload.get("action") or "repair_or_resume_session_worktree"),
            details={"state": state, "outcome": payload.get("outcome")},
        )

    session_branch = _coerce_nonempty_str(payload.get("session_branch"))
    session_worktree_path = _coerce_nonempty_str(payload.get("session_worktree_path"))
    if not session_branch or not session_worktree_path:
        return None, _session_child_non_success(
            "session_metadata_incomplete",
            "repair_or_remove_conflicting_session_metadata",
        )

    parent_session = {
        "mst_session_id": parsed.mst_session_id,
        "session_branch": session_branch,
        "session_worktree_path": session_worktree_path,
        "base_branch": _coerce_nonempty_str(payload.get("base_branch")),
        "base_sha": _coerce_nonempty_str(payload.get("base_sha")),
    }
    return parent_session, None
def _is_mst_owned_worktree_hook_file(path: Path) -> bool:
    name = path.name
    return (name.startswith("mst-") and name.endswith(".sh")) or name in MST_WORKTREE_HOOK_MARKER_FILES
def _filter_worktree_hooks_block(hooks: dict) -> tuple[dict, list[str]]:
    removed: list[str] = []
    if not isinstance(hooks, dict):
        return {}, removed
    new_hooks: dict[str, object] = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            new_hooks[event] = entries
            continue
        kept_entries: list[object] = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            inner = entry.get("hooks") or []
            if not isinstance(inner, list):
                kept_entries.append(entry)
                continue
            kept_inner: list[object] = []
            for hook in inner:
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                if isinstance(command, str) and MST_WORKTREE_HOOK_COMMAND_RE.search(command):
                    removed.append(command)
                    continue
                kept_inner.append(hook)
            if kept_inner:
                new_entry = dict(entry)
                new_entry["hooks"] = kept_inner
                kept_entries.append(new_entry)
        if kept_entries:
            new_hooks[event] = kept_entries
    return new_hooks, removed
def _filter_worktree_settings(settings: dict) -> dict:
    filtered = copy.deepcopy(settings)
    hooks = filtered.get("hooks")
    if isinstance(hooks, dict):
        filtered_hooks, _ = _filter_worktree_hooks_block(hooks)
        if filtered_hooks:
            filtered["hooks"] = filtered_hooks
        else:
            filtered.pop("hooks", None)
    return filtered
def _copy_custom_worktree_hook_files(source_hooks_dir: Path, target_hooks_dir: Path) -> int:
    if not source_hooks_dir.is_dir():
        return 0

    hook_sources = sorted(
        path for path in source_hooks_dir.iterdir()
        if path.is_file() and not _is_mst_owned_worktree_hook_file(path)
    )
    if not hook_sources:
        return 0

    try:
        target_hooks_dir.mkdir(parents=True, exist_ok=True)
        for hook_source in hook_sources:
            shutil.copy2(hook_source, target_hooks_dir / hook_source.name)
    except Exception as exc:
        print(f"Error: failed to copy worktree custom hook files ({exc})", file=sys.stderr)
        return 1

    return 0
def _copy_filtered_worktree_settings(source_claude_dir: Path, target_claude_dir: Path) -> int:
    settings_source = source_claude_dir / "settings.local.json"
    if not settings_source.is_file():
        return 0

    try:
        original = json.loads(settings_source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: failed to parse source settings file ({exc})", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: failed to read source settings file ({exc})", file=sys.stderr)
        return 1

    try:
        target_claude_dir.mkdir(parents=True, exist_ok=True)
        target_settings = target_claude_dir / "settings.local.json"
        if isinstance(original, dict):
            filtered = _filter_worktree_settings(original)
            target_settings.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            shutil.copy2(settings_source, target_settings)
    except Exception as exc:
        print(f"Error: failed to copy worktree settings file ({exc})", file=sys.stderr)
        return 1

    return 0
def _copy_worktree_support_files(project_root: Path, worktree_path: Path) -> int:
    source_claude_dir = project_root / ".claude"
    source_hooks_dir = source_claude_dir / "hooks"
    target_claude_dir = worktree_path / ".claude"
    target_hooks_dir = target_claude_dir / "hooks"

    hook_result = _copy_custom_worktree_hook_files(source_hooks_dir, target_hooks_dir)
    if hook_result != 0:
        return hook_result

    return _copy_filtered_worktree_settings(source_claude_dir, target_claude_dir)
def _normalize_target_path(path_value) -> Path:
    return Path(path_value).expanduser().resolve(strict=False)
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _worktree_task_id_from_path(path_value) -> str | None:
    raw_path = _coerce_nonempty_str(path_value)
    if not raw_path:
        return None
    return _coerce_nonempty_str(Path(raw_path).expanduser().name)
def _worktree_meta_path(project_root: Path, task_id: str) -> Path:
    return _common.worktrees_dir(project_root) / f"{task_id}.meta.json"
def _write_worktree_meta_atomic(meta_path: Path, meta_data: dict) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = meta_path.with_name(f"{meta_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, meta_path)
def _git_ref_sha(project_root: Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        return None
    return _coerce_nonempty_str(result.stdout)
def _persist_active_worktree_meta(
    project_root: Path,
    path_value,
    branch: str,
    *,
    base: str | None = None,
    parent_session: dict | None = None,
) -> None:
    task_id = _worktree_task_id_from_path(path_value)
    if not task_id:
        return

    meta_path = _worktree_meta_path(project_root, task_id)
    existing = _common.load_json(meta_path)
    now = _utc_now_iso()
    created_at = None
    if isinstance(existing, dict):
        created_at = _coerce_nonempty_str(existing.get("created_at"))

    meta_data = {
        "taskId": task_id,
        "path": str(_normalize_target_path(path_value)),
        "branch": branch,
        "state": "active",
        "created_at": created_at or now,
        "last_activity_at": now,
    }
    if base:
        meta_data["base_branch"] = base
        base_sha = _git_ref_sha(project_root, base)
        if base_sha:
            meta_data["base_sha"] = base_sha
    if parent_session is not None:
        meta_data["parent_mst_session_id"] = parent_session["mst_session_id"]
        meta_data["parent_session_branch"] = parent_session["session_branch"]
        meta_data["parent_session_worktree_path"] = parent_session["session_worktree_path"]
    _write_worktree_meta_atomic(meta_path, meta_data)
def _safe_worktree_archive_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    token = token.strip(".-")
    return token or "lineage-unknown"
def _worktree_archive_session_token(meta_data: dict) -> str:
    for key in ("session_id", "owner_session_id"):
        value = _coerce_nonempty_str(meta_data.get(key))
        if value:
            return _safe_worktree_archive_token(value)
    return "lineage-unknown"
def _worktree_meta_archive_target(
    project_root: Path,
    meta_path: Path,
    meta_data: dict,
    now: datetime | None = None,
) -> Path:
    timestamp = now or datetime.now(timezone.utc)
    month = timestamp.strftime("%Y-%m")
    token = _worktree_archive_session_token(meta_data)
    archive_dir = _common.worktrees_dir(project_root) / ".archive" / token / month
    target = archive_dir / meta_path.name
    if not target.exists():
        return target

    stem = meta_path.stem
    suffix = meta_path.suffix
    index = 1
    while True:
        candidate = archive_dir / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
def _move_meta_to_archive(meta_path: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        meta_path.rename(target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(meta_path), str(target))
def _parse_archive_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    raw = _coerce_nonempty_str(value)
    if not raw:
        return None
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        try:
            return datetime.fromtimestamp(float(raw), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
def _archive_meta_reference_time(meta_path: Path, meta_data: dict | None = None) -> datetime:
    data = meta_data if isinstance(meta_data, dict) else _common.load_json(meta_path)
    if isinstance(data, dict):
        for key in ("migrated_at", "original_mtime"):
            parsed = _parse_archive_datetime(data.get(key))
            if parsed is not None:
                return parsed
    return datetime.fromtimestamp(meta_path.stat().st_mtime, timezone.utc)
def _iter_worktree_archive_session_groups(project_root: Path) -> list[dict]:
    archive_root = _common.worktrees_dir(project_root) / ".archive"
    if not archive_root.is_dir():
        return []

    groups: list[dict] = []
    for session_dir in sorted(path for path in archive_root.iterdir() if path.is_dir()):
        file_entries: list[dict] = []
        for meta_path in sorted(session_dir.glob("*/*.meta.json")):
            meta_data = _common.load_json(meta_path)
            if not isinstance(meta_data, dict):
                meta_data = {}
            ref_time = _archive_meta_reference_time(meta_path, meta_data)
            file_entries.append({"path": str(meta_path), "reference_time": ref_time})
        if not file_entries:
            continue
        file_entries.sort(key=lambda item: item["reference_time"], reverse=True)
        groups.append({"session_token": session_dir.name, "files": file_entries})
    return groups
def _normalize_retention_value(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(parsed, 0)
def _load_worktree_archive_retention_defaults() -> tuple[int | None, int | None]:
    for config_name in ("config.resolved.json", "config.json"):
        data = _common.load_json(_common.BASE_DIR / config_name) or {}
        worktree_config = data.get("worktree") if isinstance(data, dict) else None
        if isinstance(worktree_config, dict):
            days = _normalize_retention_value(worktree_config.get("archive_retention_days"))
            count = _normalize_retention_value(worktree_config.get("archive_retention_count"))
            if days is not None or count is not None:
                return days, count
    defaults = _common.load_json(_common._plugin_root() / "templates" / "defaults" / "config.json") or {}
    worktree_defaults = defaults.get("worktree") if isinstance(defaults, dict) else None
    if isinstance(worktree_defaults, dict):
        return (
            _normalize_retention_value(worktree_defaults.get("archive_retention_days")),
            _normalize_retention_value(worktree_defaults.get("archive_retention_count")),
        )
    return 30, 100
def prune_worktree_meta_archive(
    project_root: Path,
    *,
    retention_days: int | None = None,
    retention_count: int | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> dict:
    if retention_days is None and retention_count is None:
        return {"dry_run": not apply, "retention_days": None, "retention_count": None, "kept": [], "deleted": []}

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days) if retention_days is not None else None
    kept: list[dict] = []
    deleted: list[dict] = []

    for group in _iter_worktree_archive_session_groups(project_root):
        for idx, entry in enumerate(group["files"]):
            reference_time = entry["reference_time"]
            keep_by_days = cutoff is not None and reference_time >= cutoff
            keep_by_count = retention_count is not None and idx < retention_count
            serialized = {
                "session_token": group["session_token"],
                "reference_time": reference_time.isoformat().replace("+00:00", "Z"),
                "path": entry["path"],
                "files": [entry["path"]],
                "keep_by_days": keep_by_days,
                "keep_by_count": keep_by_count,
            }
            if keep_by_days or keep_by_count:
                kept.append(serialized)
                continue
            deleted.append(serialized)
            if apply:
                try:
                    Path(entry["path"]).unlink(missing_ok=True)
                except OSError as exc:
                    serialized.setdefault("errors", []).append(f"{entry['path']}: {exc}")

    if apply:
        archive_root = _common.worktrees_dir(project_root) / ".archive"
        if archive_root.is_dir():
            for directory in sorted((p for p in archive_root.glob("*/*") if p.is_dir()), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            for directory in sorted((p for p in archive_root.glob("*") if p.is_dir()), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    return {
        "dry_run": not apply,
        "retention_days": retention_days,
        "retention_count": retention_count,
        "kept": kept,
        "deleted": deleted,
    }
def _migrate_legacy_cleaned_meta_file(
    project_root: Path,
    meta_path: Path,
    meta_data: dict,
    *,
    migrated_at_dt: datetime,
) -> dict | None:
    try:
        original_mtime = meta_path.stat().st_mtime
    except FileNotFoundError:
        return None

    migrated_at = migrated_at_dt.isoformat().replace("+00:00", "Z")
    next_data = dict(meta_data)
    next_data.setdefault("original_mtime", original_mtime)
    next_data["migrated_at"] = migrated_at
    target_time = _parse_archive_datetime(next_data.get("original_mtime")) or migrated_at_dt
    target = _worktree_meta_archive_target(project_root, meta_path, next_data, target_time)
    _write_worktree_meta_atomic(meta_path, next_data)
    _move_meta_to_archive(meta_path, target)
    return {"source": str(meta_path), "target": str(target)}
def migrate_legacy_cleaned_worktree_meta(project_root: Path, *, now: datetime | None = None) -> dict:
    worktrees_dir = _common.worktrees_dir(project_root)
    if not worktrees_dir.is_dir():
        return {"migrated": [], "skipped": []}

    migrated: list[dict] = []
    skipped: list[dict] = []
    migrated_at_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)

    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data = _common.load_json(meta_path)
        if not isinstance(meta_data, dict):
            skipped.append({"path": str(meta_path), "reason": "invalid-json"})
            continue
        if meta_data.get("state") != "cleaned":
            skipped.append({"path": str(meta_path), "reason": "not-cleaned"})
            continue

        migrated_item = _migrate_legacy_cleaned_meta_file(
            project_root,
            meta_path,
            meta_data,
            migrated_at_dt=migrated_at_dt,
        )
        if migrated_item is not None:
            migrated.append(migrated_item)

    return {"migrated": migrated, "skipped": skipped}
def _load_worktree_meta_json_for_migration(meta_path: Path) -> tuple[dict | None, str | None]:
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return None, "invalid-json"
    except OSError as exc:
        return None, f"read-error: {exc}"
    if not isinstance(data, dict):
        return None, "invalid-json"
    return data, None
def _has_worktree_lineage(meta_data: dict) -> bool:
    return bool(_coerce_nonempty_str(meta_data.get("session_id")) or _coerce_nonempty_str(meta_data.get("owner_session_id")))
def _lineage_unknown_archive_target_for_mtime(project_root: Path, meta_path: Path, original_mtime: float) -> Path:
    target_time = datetime.fromtimestamp(original_mtime, timezone.utc)
    return _worktree_meta_archive_target(project_root, meta_path, {"lineage": "unknown"}, target_time)
def _archived_unknown_meta_is_valid(target: Path) -> bool:
    data, error = _load_worktree_meta_json_for_migration(target)
    if error or not isinstance(data, dict):
        return False
    return data.get("lineage") == "unknown"
def _migrate_archive_empty_payload(*, apply: bool, delete: bool) -> dict:
    dry_run = not apply
    return {
        "dry_run": dry_run,
        "apply": apply,
        "delete": delete,
        "candidates": [],
        "migrated": [],
        "deleted": [],
        "skipped": [],
        "candidate_count": 0,
        "migrated_count": 0,
        "deleted_count": 0,
        "skipped_count": 0,
    }
def inspect_lineage_unknown_worktree_meta(project_root: Path, *, now: datetime | None = None) -> dict:
    """Return read-only migrate-archive diagnostic counts for lineage=unknown meta files."""
    return migrate_lineage_unknown_worktree_meta(project_root, apply=False, delete=False, now=now)
def migrate_lineage_unknown_worktree_meta(
    project_root: Path,
    *,
    apply: bool = False,
    delete: bool = False,
    now: datetime | None = None,
) -> dict:
    worktrees_dir = _common.worktrees_dir(project_root)
    payload = _migrate_archive_empty_payload(apply=apply, delete=delete)
    if not worktrees_dir.is_dir():
        return payload

    migrated_at_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    migrated_at = migrated_at_dt.isoformat().replace("+00:00", "Z")

    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data, error = _load_worktree_meta_json_for_migration(meta_path)
        if error:
            payload["skipped"].append({"source": str(meta_path), "path": str(meta_path), "reason": error})
            continue
        if not isinstance(meta_data, dict):
            payload["skipped"].append({"source": str(meta_path), "path": str(meta_path), "reason": "invalid-json"})
            continue
        if _has_worktree_lineage(meta_data):
            payload["skipped"].append({"source": str(meta_path), "path": str(meta_path), "reason": "has-lineage"})
            continue

        try:
            original_mtime = meta_path.stat().st_mtime
        except FileNotFoundError:
            continue
        target = _lineage_unknown_archive_target_for_mtime(project_root, meta_path, original_mtime)
        row = {"source": str(meta_path), "target": str(target), "lineage": "unknown"}
        payload["candidates"].append(row)
        if not apply:
            continue

        canonical_target = worktrees_dir / ".archive" / "lineage-unknown" / datetime.fromtimestamp(original_mtime, timezone.utc).strftime("%Y-%m") / meta_path.name
        if canonical_target.exists() and _archived_unknown_meta_is_valid(canonical_target):
            meta_path.unlink(missing_ok=True)
            row = {"source": str(meta_path), "target": str(canonical_target), "lineage": "unknown"}
            payload["migrated"].append(row)
            if delete:
                canonical_target.unlink(missing_ok=True)
                payload["deleted"].append(row)
            continue

        next_data = dict(meta_data)
        next_data["lineage"] = "unknown"
        next_data.setdefault("original_mtime", original_mtime)
        next_data["migrated_at"] = migrated_at
        _write_worktree_meta_atomic(meta_path, next_data)
        _move_meta_to_archive(meta_path, target)
        payload["migrated"].append(row)
        if delete:
            target.unlink(missing_ok=True)
            payload["deleted"].append(row)

    payload["candidate_count"] = len(payload["candidates"])
    payload["migrated_count"] = len(payload["migrated"])
    payload["deleted_count"] = len(payload["deleted"])
    payload["skipped_count"] = len(payload["skipped"])
    return payload
def _mark_worktree_meta_cleaned(project_root: Path, path_value) -> None:
    task_id = _worktree_task_id_from_path(path_value)
    if not task_id:
        return

    meta_path = _worktree_meta_path(project_root, task_id)
    if not meta_path.exists():
        return

    existing = _common.load_json(meta_path)
    now = _utc_now_iso()
    if isinstance(existing, dict):
        meta_data = dict(existing)
    else:
        meta_data = {}

    meta_data.setdefault("taskId", task_id)
    meta_data.setdefault("path", str(_normalize_target_path(path_value)))
    meta_data.setdefault("branch", "")
    meta_data.setdefault("created_at", now)
    meta_data["state"] = "cleaned"
    meta_data["last_activity_at"] = now
    meta_data["archived_at"] = now
    archive_target = _worktree_meta_archive_target(
        project_root,
        meta_path,
        meta_data,
        datetime.fromisoformat(now.replace("Z", "+00:00")),
    )
    _write_worktree_meta_atomic(meta_path, meta_data)
    _move_meta_to_archive(meta_path, archive_target)
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
def _is_session_owned_child_target(worktree_path: Path, branch: str, base: str, parent_session: dict | None) -> bool:
    if parent_session is None:
        return False
    session_path = _normalize_target_path(parent_session["session_worktree_path"])
    normalized_target = _normalize_target_path(worktree_path)
    if session_path != normalized_target and session_path not in normalized_target.parents:
        return False
    session_branch = str(parent_session["session_branch"])
    if base != session_branch and not branch.startswith(f"gran-maestro/{base_slug(session_branch)}/"):
        return False
    return True
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
        worktree_roots = _list_worktree_roots(project_root)
        nested_root = _find_nested_worktree_root(worktree_path, worktree_roots, master_root=project_root)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parent_session, session_error = _resolve_parent_session_context()
    if nested_root is not None and not _is_session_owned_child_target(worktree_path, branch, base, parent_session):
        print(
            "Error: nested worktree path detected. "
            f"현재 target 경로 {worktree_path}는 기존 worktree {nested_root}의 내부입니다. "
            f"master({project_root})에서 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1
    if session_error is not None and (base.startswith("gran-maestro/session/") or branch.startswith("gran-maestro/gran-maestro-session-")):
        _print_session_child_non_success(session_error, True)
        return 2

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), base],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip() or "git worktree add failed", file=sys.stderr)
        return result.returncode or 1

    try:
        _persist_active_worktree_meta(project_root, args.path, branch, base=base, parent_session=parent_session)
    except OSError as exc:
        print(f"Error: failed to write worktree meta ({exc})", file=sys.stderr)
        return 1

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

    try:
        _mark_worktree_meta_cleaned(project_root, args.path)
    except OSError as exc:
        print(f"Error: failed to update worktree meta ({exc})", file=sys.stderr)
        return 1

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
