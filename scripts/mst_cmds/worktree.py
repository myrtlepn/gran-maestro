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
from scripts.mst_cmds import _common, on
from scripts.mst_cmds._common import (
    _project_root,
)


FALLBACK_PROTECTED_BRANCHES = ["main", "master", "release/*"]


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
    target_claude_dir = worktree_path / ".claude"

    settings_source = source_claude_dir / "settings.local.json"
    if not settings_source.is_file():
        return 0

    try:
        target_claude_dir.mkdir(parents=True, exist_ok=True)
        target_settings = target_claude_dir / "settings.local.json"
        try:
            settings = json.loads(settings_source.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            shutil.copy2(settings_source, target_settings)
            return 0

        if not isinstance(settings, dict):
            shutil.copy2(settings_source, target_settings)
            return 0

        filtered = dict(settings)
        hooks = filtered.get("hooks")
        if isinstance(hooks, dict):
            new_hooks, _removed = on._filter_hooks_block(hooks, project_root)
            if new_hooks:
                filtered["hooks"] = new_hooks
            else:
                filtered.pop("hooks", None)
        with open(target_settings, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception as exc:
        print(f"Error: failed to copy worktree support files ({exc})", file=sys.stderr)
        return 1

    return 0


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


def _persist_active_worktree_meta(project_root: Path, path_value, branch: str) -> None:
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

    try:
        _persist_active_worktree_meta(project_root, args.path, branch)
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


def _iter_cleaned_meta_entries(project_root: Path) -> list[dict]:
    entries: list[dict] = []
    worktrees_dir = _common.BASE_DIR / "worktrees"
    if not worktrees_dir.is_dir():
        return entries

    migrated_at_dt = datetime.now(timezone.utc).replace(microsecond=0)
    migrated_at = migrated_at_dt.isoformat().replace("+00:00", "Z")
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
                "legacy_cleaned_meta": True,
                "legacy_meta_data": meta_data,
                "legacy_migrated_at": migrated_at,
            }
        )
    return entries


def _normalize_meta_relative_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    relative_path = raw_path.replace("\\", "/")
    while relative_path.startswith("./"):
        relative_path = relative_path[2:]
    base_name = _common.BASE_DIR.name if _common.BASE_DIR else ".gran-maestro"
    for prefix in (f"{base_name}/", ".gran-maestro/"):
        if relative_path.startswith(prefix):
            return relative_path[len(prefix):]
    return relative_path


def _meta_relative_path(meta_data: dict, project_root: Path) -> str | None:
    worktree_path = _meta_worktree_path(meta_data, project_root)
    if worktree_path:
        for base_path in (_common.BASE_DIR, project_root):
            if base_path is None:
                continue
            try:
                return worktree_path.relative_to(base_path.resolve(strict=False)).as_posix()
            except ValueError:
                continue
    return _normalize_meta_relative_path(_coerce_nonempty_str(meta_data.get("path")))


def _normalize_scope_prefix(prefix: str | None) -> str | None:
    normalized = _normalize_meta_relative_path(_coerce_nonempty_str(prefix))
    if not normalized:
        return None
    return normalized


def _iter_scoped_meta_entries(
    project_root: Path,
    scope: str | None = None,
    prefix: str | None = None,
) -> list[dict]:
    entries: list[dict] = []
    scope_value = _coerce_nonempty_str(scope)
    prefix_value = _normalize_scope_prefix(prefix)
    if not scope_value and not prefix_value:
        return entries

    worktrees_dir = _common.BASE_DIR / "worktrees"
    if not worktrees_dir.is_dir():
        return entries

    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data = _common.load_json(meta_path)
        if not isinstance(meta_data, dict):
            print(f"Warning: failed to read worktree meta {meta_path}", file=sys.stderr)
            continue

        relative_path = _meta_relative_path(meta_data, project_root)
        scope_matches = bool(
            scope_value
            and (
                _coerce_nonempty_str(meta_data.get("agi_id")) == scope_value
                or (relative_path or "").startswith(f"worktrees/{scope_value}/sprint-")
            )
        )
        prefix_matches = bool(prefix_value and (relative_path or "").startswith(prefix_value))
        if not (scope_matches or prefix_matches):
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


def _iter_scope_fs_orphan_entries(project_root: Path, scope: str | None, known_paths: set[Path]) -> list[dict]:
    scope_value = _coerce_nonempty_str(scope)
    if not scope_value:
        return []

    scope_dir = _common.BASE_DIR / "worktrees" / scope_value
    if not scope_dir.is_dir():
        return []

    entries: list[dict] = []
    for sprint_dir in sorted(scope_dir.glob("sprint-*")):
        if not sprint_dir.is_dir():
            continue
        worktree_path = sprint_dir.resolve(strict=False)
        if worktree_path in known_paths:
            continue
        entries.append(
            {
                "taskId": f"<fs-orphan:{sprint_dir.name}>",
                "path": str(worktree_path),
                "branch": None,
                "meta_path": None,
            }
        )
    return entries


def _detect_orphans_from_entries(project_root: Path, entries: list[dict]) -> list[dict]:
    worktree_roots = set(_list_worktree_roots(project_root))
    orphans: list[dict] = []

    for entry in entries:
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


def _detect_cleaned_orphans(project_root: Path) -> list[dict]:
    return _detect_orphans_from_entries(project_root, _iter_cleaned_meta_entries(project_root))


def _detect_scoped_orphans(
    project_root: Path,
    scope: str | None = None,
    prefix: str | None = None,
) -> list[dict]:
    entries = _iter_scoped_meta_entries(project_root, scope=scope, prefix=prefix)
    known_paths = {
        Path(entry["path"]).resolve(strict=False)
        for entry in entries
        if entry.get("path")
    }
    entries.extend(_iter_scope_fs_orphan_entries(project_root, scope, known_paths))
    return _detect_orphans_from_entries(project_root, entries)


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

    raw_meta_path = orphan.get("meta_path")
    if raw_meta_path:
        meta_path = Path(str(raw_meta_path))
        if orphan.get("legacy_cleaned_meta"):
            migrated_item = _migrate_legacy_cleaned_meta_file(
                project_root,
                meta_path,
                orphan.get("legacy_meta_data") if isinstance(orphan.get("legacy_meta_data"), dict) else {},
                migrated_at_dt=_parse_archive_datetime(orphan.get("legacy_migrated_at"))
                or datetime.now(timezone.utc).replace(microsecond=0),
            )
            if migrated_item is not None:
                steps.append(
                    {
                        "command": f"migrate meta {meta_path}",
                        "ok": True,
                        "message": migrated_item["target"],
                    }
                )
            return True, steps
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


def cmd_worktree_archive_retention(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    default_days, default_count = _load_worktree_archive_retention_defaults()
    retention_days = _normalize_retention_value(getattr(args, "days", None))
    retention_count = _normalize_retention_value(getattr(args, "count", None))
    if retention_days is None and not getattr(args, "no_days", False):
        retention_days = default_days
    if retention_count is None and not getattr(args, "no_count", False):
        retention_count = default_count

    payload = prune_worktree_meta_archive(
        project_root,
        retention_days=retention_days,
        retention_count=retention_count,
        apply=bool(getattr(args, "apply", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        mode = "apply" if getattr(args, "apply", False) else "dry-run"
        print(
            f"[worktree-archive-retention] mode={mode} "
            f"days={retention_days} count={retention_count} "
            f"delete={len(payload['deleted'])} keep={len(payload['kept'])}"
        )
        for item in payload["deleted"]:
            print(f"delete session={item['session_token']} files={len(item['files'])}")
    return 0


def cmd_worktree_migrate_cleaned_meta(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    payload = migrate_legacy_cleaned_worktree_meta(project_root)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"[worktree-migrate-cleaned-meta] migrated={len(payload['migrated'])} skipped={len(payload['skipped'])}")
        for item in payload["migrated"]:
            print(f"migrated {item['source']} -> {item['target']}")
    return 0


def cmd_worktree_migrate_archive(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    apply = bool(getattr(args, "apply", False))
    delete = bool(getattr(args, "delete", False))
    payload = migrate_lineage_unknown_worktree_meta(project_root, apply=apply, delete=delete)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        mode = "apply" if apply else "dry-run"
        print(
            f"[worktree-migrate-archive] mode={mode} delete={delete} "
            f"candidates={payload['candidate_count']} migrated={payload['migrated_count']} "
            f"deleted={payload['deleted_count']} skipped={payload['skipped_count']}"
        )
        for item in payload["candidates"]:
            print(f"candidate lineage={item['lineage']} {item['source']} -> {item['target']}")
        for item in payload["migrated"]:
            print(f"migrated lineage={item['lineage']} {item['source']} -> {item['target']}")
        for item in payload["deleted"]:
            print(f"deleted lineage={item['lineage']} {item['target']}")
    return 0


def cmd_worktree_detect_orphans(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)

    scope = _coerce_nonempty_str(getattr(args, "scope", None))
    prefix = _coerce_nonempty_str(getattr(args, "prefix", None))

    try:
        if scope or prefix:
            orphans = _detect_scoped_orphans(project_root, scope=scope, prefix=prefix)
        else:
            orphans = _detect_cleaned_orphans(project_root)
            if not orphans:
                migrate_legacy_cleaned_worktree_meta(project_root)
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



def _read_git_worktree_branch(project_root: Path, worktree_path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        return None
    return _coerce_nonempty_str(result.stdout)


def _worktree_is_dirty(project_root: Path, worktree_path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _find_worktree_root(project_root: Path, worktree_path: Path) -> Path | None:
    try:
        for root in _list_worktree_roots(project_root):
            if _normalize_target_path(root) == _normalize_target_path(worktree_path):
                return root
    except RuntimeError:
        return None
    return None


def classify_worktree_collision(project_root: Path, worktree_path: Path, branch: str) -> str:
    normalized_path = _normalize_target_path(worktree_path)
    path_exists = normalized_path.exists()
    listed_root = _find_worktree_root(project_root, normalized_path)
    branch_exists = _git_branch_exists(project_root, branch)

    if listed_root is not None:
        current_branch = _read_git_worktree_branch(project_root, normalized_path)
        if _worktree_is_dirty(project_root, normalized_path):
            return "dirty_worktree_manual_conflict"
        if current_branch == branch and branch_exists:
            return "reusable_existing_worktree"
        return "stale_orphan_cleanup_required"

    if path_exists and not (normalized_path / ".git").exists():
        return "fatal_conflict"
    if path_exists or branch_exists:
        return "stale_orphan_cleanup_required"
    return "no_collision"


def cmd_worktree_classify_collision(args):
    branch = str(getattr(args, "branch", "") or "").strip()
    if not branch:
        print("Error: --branch is required", file=sys.stderr)
        return 1
    project_root = _resolve_master_project_root()
    classification = classify_worktree_collision(project_root, Path(args.path), branch)
    payload = {"classification": classification, "path": str(_normalize_target_path(args.path)), "branch": branch}
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(classification)
    return 0 if classification in {"no_collision", "reusable_existing_worktree"} else 2


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
    agi_id = getattr(args, "agi", None)
    role = getattr(args, "role", None)
    if role:
        print(role_branch_name(args.req, role, args.base, agi_id))
    elif getattr(args, "task", None):
        print(task_branch_name(args.req, args.task, args.base, agi_id))
    else:
        print(req_branch_name(args.req, args.base, agi_id))
    return 0


def cmd_worktree_path(args):
    print(role_worktree_path(_project_root(), args.req, args.role, getattr(args, "agi", None)))
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


def _all_tasks_committed_or_done(request_data: dict) -> bool:
    tasks = request_data.get("tasks") or []
    if not isinstance(tasks, list) or not tasks:
        return False

    for task in tasks:
        if not isinstance(task, dict):
            return False
        status = str(task.get("status") or "").strip().lower()
        if status not in {"committed", "done"}:
            return False
    return True


def _all_task_metas_missing(req_id: str, task_ids: list[str]) -> bool:
    if not task_ids:
        return False

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if meta_path.exists():
            return False
    return True


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

    if _all_tasks_committed_or_done(request_data) and _all_task_metas_missing(req_id, task_ids):
        return _boundary_payload(
            True,
            None,
            False,
            detected_base,
            "legacy_no_meta: all tasks committed and no meta files (legacy CLI path)",
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
        print(
            f"[boundary] diagnostic: owner_ppid ignored: owner_ppid={owner_ppid} current_ppid={current_ppid}",
            file=sys.stderr,
        )

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
    worktree_branch_name.add_argument("--role")
    worktree_branch_name.add_argument("--agi")

    worktree_path = worktree_sub.add_parser("path")
    worktree_path.add_argument("--req", required=True)
    worktree_path.add_argument("--role", required=True)
    worktree_path.add_argument("--agi")

    worktree_check_boundary = worktree_sub.add_parser("check-boundary")
    worktree_check_boundary.add_argument("--req", required=True)
    worktree_check_boundary.add_argument("--phase", choices=["entry", "exit"], required=True)
    worktree_check_boundary.add_argument("--task-id")
    worktree_check_boundary.add_argument("--ppid", type=int)

    worktree_detect_orphans = worktree_sub.add_parser("detect-orphans")
    worktree_detect_orphans.add_argument("--clean", action="store_true")
    worktree_detect_orphans.add_argument("--json", action="store_true")
    worktree_detect_orphans.add_argument("--scope", default=None)
    worktree_detect_orphans.add_argument("--prefix", default=None)

    worktree_classify_collision = worktree_sub.add_parser("classify-collision")
    worktree_classify_collision.add_argument("--path", required=True)
    worktree_classify_collision.add_argument("--branch", required=True)
    worktree_classify_collision.add_argument("--json", action="store_true")

    worktree_archive_retention = worktree_sub.add_parser("archive-retention")
    worktree_archive_retention.add_argument("--days", type=int)
    worktree_archive_retention.add_argument("--count", type=int)
    worktree_archive_retention.add_argument("--no-days", action="store_true")
    worktree_archive_retention.add_argument("--no-count", action="store_true")
    worktree_archive_retention.add_argument("--apply", action="store_true")
    worktree_archive_retention.add_argument("--json", action="store_true")

    worktree_migrate_cleaned_meta = worktree_sub.add_parser("migrate-cleaned-meta")
    worktree_migrate_cleaned_meta.add_argument("--json", action="store_true")

    worktree_migrate_archive = worktree_sub.add_parser("migrate-archive")
    worktree_migrate_archive.add_argument("--dry-run", action="store_true")
    worktree_migrate_archive.add_argument("--apply", action="store_true")
    worktree_migrate_archive.add_argument("--delete", action="store_true")
    worktree_migrate_archive.add_argument("--json", action="store_true")

    _register_worktree_dispatch("path", cmd_worktree_path)
    _register_worktree_dispatch("check-boundary", cmd_worktree_check_boundary)
    _register_worktree_dispatch("detect-orphans", cmd_worktree_detect_orphans)
    _register_worktree_dispatch("classify-collision", cmd_worktree_classify_collision)
    _register_worktree_dispatch("archive-retention", cmd_worktree_archive_retention)
    _register_worktree_dispatch("migrate-cleaned-meta", cmd_worktree_migrate_cleaned_meta)
    _register_worktree_dispatch("migrate-archive", cmd_worktree_migrate_archive)
