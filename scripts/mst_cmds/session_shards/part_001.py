from __future__ import annotations
import argparse
import copy
import glob
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds.env_alias_compat import canonical_session_id_from_env
from scripts.mst_cmds._common import (
    load_json,
)
MST_SESSION_ID_PREFIX = "MST-"
MST_SESSION_ID_RANDOM_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
MST_SESSION_ID_RANDOM_MIN_LENGTH = 8
MST_SESSION_ID_RANDOM_DEFAULT_LENGTH = 8
ALLOWED_ROOT_MST_NAMESPACES = frozenset(
    {
        "AGI",
        "PLN",
        "REQ",
        "DBG",
        "EXP",
        "DSC",
        "IDN",
        "DES",
        "INTENT",
        "CAP",
        "FC",
        "REF",
    }
)
_ROOT_MST_ID_RE = re.compile(r"^([A-Z][A-Z0-9]*)-\d+$")
_STARTED_AT_COMPACT_RE = re.compile(r"^\d{8}T\d{9}Z$")
_RANDOM_SEGMENT_RE = re.compile(r"^[a-z0-9]+$")
class MstSessionIdValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(f"invalid structured mst_session_id: {reason}")
        self.reason = reason
class RootSessionCreateError(RuntimeError):
    pass
@dataclass(frozen=True)
class StructuredMstSessionId:
    mst_session_id: str
    root_mst_id: str
    started_at: datetime
    started_at_compact: str
    random: str
def _structured_failure(reason: str) -> MstSessionIdValidationError:
    return MstSessionIdValidationError(reason)
def format_mst_session_started_at(started_at: datetime) -> str:
    if started_at.tzinfo is None:
        raise _structured_failure("started_at must be timezone-aware UTC")
    started_at_utc = started_at.astimezone(timezone.utc)
    if started_at_utc.microsecond % 1000 != 0:
        raise _structured_failure("started_at precision must be milliseconds")
    return (
        started_at_utc.strftime("%Y%m%dT%H%M%S")
        + f"{started_at_utc.microsecond // 1000:03d}Z"
    )
def parse_mst_session_started_at_compact(value: str) -> datetime:
    text = str(value)
    if not _STARTED_AT_COMPACT_RE.fullmatch(text):
        raise _structured_failure("started_at_compact must be UTC milliseconds in YYYYMMDDTHHMMSSmmmZ form")
    main = text[:-1]
    try:
        base = datetime.strptime(main[:15], "%Y%m%dT%H%M%S")
        started_at = base.replace(microsecond=int(main[15:18]) * 1000, tzinfo=timezone.utc)
    except ValueError as exc:
        raise _structured_failure("started_at_compact is not a valid UTC timestamp") from exc
    if format_mst_session_started_at(started_at) != text:
        raise _structured_failure("started_at_compact does not round-trip")
    return started_at
def format_mst_session_started_at_iso(started_at: datetime) -> str:
    if started_at.tzinfo is None:
        raise _structured_failure("started_at must be timezone-aware UTC")
    return started_at.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
def parse_mst_session_started_at_metadata(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise _structured_failure("started_at metadata must not be empty")
    if _STARTED_AT_COMPACT_RE.fullmatch(text):
        return parse_mst_session_started_at_compact(text)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _structured_failure("started_at metadata is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None:
        raise _structured_failure("started_at metadata must be timezone-aware UTC")
    parsed_utc = parsed.astimezone(timezone.utc)
    if parsed_utc.microsecond % 1000 != 0:
        raise _structured_failure("started_at metadata precision must be milliseconds")
    return parsed_utc
def validate_root_mst_id(root_mst_id: str) -> str:
    root = str(root_mst_id).strip()
    if root != str(root_mst_id):
        raise _structured_failure("root_mst_id must not require normalization")
    match = _ROOT_MST_ID_RE.fullmatch(root)
    if not match:
        raise _structured_failure("root_mst_id must be an allowed MST resource id")
    namespace = match.group(1)
    if namespace not in ALLOWED_ROOT_MST_NAMESPACES:
        raise _structured_failure(f"root namespace is not allowed: {namespace}")
    if not _common.is_path_safe_mst_session_id(root):
        raise _structured_failure("root_mst_id must be path-safe")
    return root
def _validate_random_segment(value: str) -> str:
    random_segment = str(value)
    if len(random_segment) < MST_SESSION_ID_RANDOM_MIN_LENGTH:
        raise _structured_failure("random segment is too short")
    if not _RANDOM_SEGMENT_RE.fullmatch(random_segment):
        raise _structured_failure("random segment contains characters outside [a-z0-9]")
    return random_segment
def _new_random_segment(length: int = MST_SESSION_ID_RANDOM_DEFAULT_LENGTH) -> str:
    if length < MST_SESSION_ID_RANDOM_MIN_LENGTH:
        raise ValueError(f"random length must be >= {MST_SESSION_ID_RANDOM_MIN_LENGTH}")
    return "".join(secrets.choice(MST_SESSION_ID_RANDOM_ALPHABET) for _ in range(length))
def parse_mst_session_id(value: str) -> StructuredMstSessionId:
    if not isinstance(value, str):
        raise _structured_failure("value must be a string")
    session_id = value.strip()
    if session_id != value:
        raise _structured_failure("value must not require normalization")
    if not _common.is_path_safe_mst_session_id(session_id):
        raise _structured_failure("value must be path-safe and must not contain traversal")
    if not session_id.startswith(MST_SESSION_ID_PREFIX):
        raise _structured_failure("missing MST- prefix")

    body = session_id[len(MST_SESSION_ID_PREFIX):]
    try:
        root_mst_id, started_at_compact, random_segment = body.rsplit("-", 2)
    except ValueError as exc:
        raise _structured_failure("expected root, started_at, and random segments") from exc

    root_mst_id = validate_root_mst_id(root_mst_id)
    started_at = parse_mst_session_started_at_compact(started_at_compact)
    random_segment = _validate_random_segment(random_segment)
    return StructuredMstSessionId(
        mst_session_id=session_id,
        root_mst_id=root_mst_id,
        started_at=started_at,
        started_at_compact=started_at_compact,
        random=random_segment,
    )
def validate_mst_session_id(
    value: str,
    *,
    expected_root_mst_id: str | None = None,
    expected_started_at: datetime | str | None = None,
    expected_random: str | None = None,
) -> StructuredMstSessionId:
    parsed = parse_mst_session_id(value)
    if expected_root_mst_id is not None and parsed.root_mst_id != validate_root_mst_id(expected_root_mst_id):
        raise _structured_failure("root_mst_id metadata mismatch")
    if expected_started_at is not None:
        expected_compact = (
            format_mst_session_started_at(parse_mst_session_started_at_metadata(expected_started_at))
            if isinstance(expected_started_at, str)
            else format_mst_session_started_at(expected_started_at)
        )
        if parsed.started_at_compact != expected_compact:
            raise _structured_failure("started_at metadata mismatch")
    if expected_random is not None and parsed.random != _validate_random_segment(expected_random):
        raise _structured_failure("random metadata mismatch")
    return parsed
def generate_mst_session_id(
    root_mst_id: str,
    *,
    started_at: datetime | None = None,
    random_segment: str | None = None,
) -> str:
    root = validate_root_mst_id(root_mst_id)
    if started_at is None:
        now = datetime.now(timezone.utc)
        started_at = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    started_at_compact = format_mst_session_started_at(started_at)
    random_value = _validate_random_segment(random_segment) if random_segment is not None else _new_random_segment()
    session_id = f"{MST_SESSION_ID_PREFIX}{root}-{started_at_compact}-{random_value}"
    validate_mst_session_id(session_id, expected_root_mst_id=root, expected_started_at=started_at)
    return session_id
def mst_session_metadata(parsed: StructuredMstSessionId) -> dict:
    return {
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "started_at": format_mst_session_started_at_iso(parsed.started_at),
        "started_at_compact": parsed.started_at_compact,
        "random": parsed.random,
    }
def load_json_object(path: Path) -> dict | None:
    data = load_json(path)
    return data if isinstance(data, dict) else None
def _root_type_key(root_mst_id: str) -> str:
    root = validate_root_mst_id(root_mst_id)
    namespace = root.split("-", 1)[0]
    for type_key, (_subdir, prefix) in _common.TYPE_DIRS.items():
        if prefix == namespace:
            return type_key
    raise _structured_failure(f"root namespace is not mapped: {namespace}")
def root_artifact_metadata_path(base_dir: Path, root_mst_id: str) -> Path:
    type_key = _root_type_key(root_mst_id)
    subdir, prefix = _common.TYPE_DIRS[type_key]
    filename = _common.JSON_FILE_MAP.get(type_key, "session.json")
    if prefix == "AGI":
        filename = "session.json"
    return Path(base_dir) / subdir / validate_root_mst_id(root_mst_id) / filename
def session_metadata_path(base_dir: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return Path(base_dir) / "sessions" / parsed.mst_session_id / "session.json"
def session_history_path(base_dir: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return Path(base_dir) / "sessions" / parsed.mst_session_id / "history.ndjson"
def session_history_head_path(base_dir: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return Path(base_dir) / "sessions" / parsed.mst_session_id / "history.head"
def session_history_verify_path(base_dir: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return Path(base_dir) / "sessions" / parsed.mst_session_id / "history.verify"
def _fsync_parent_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent_dir(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent_dir(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
def _cleanup_empty_dirs(path: Path, stop: Path) -> None:
    stop = stop.resolve(strict=False)
    current = path.resolve(strict=False)
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
def _metadata_mismatch(source: str, field: str) -> MstSessionIdValidationError:
    return _structured_failure(f"{source} {field} metadata mismatch")
def _validate_metadata_payload(
    parsed: StructuredMstSessionId,
    payload: dict,
    *,
    source: str,
) -> None:
    raw_session_id = payload.get("mst_session_id")
    if isinstance(raw_session_id, str) and raw_session_id.strip() and raw_session_id.strip() != parsed.mst_session_id:
        raise _metadata_mismatch(source, "mst_session_id")
    raw_root = payload.get("root_mst_id")
    if isinstance(raw_root, str) and raw_root.strip() and validate_root_mst_id(raw_root.strip()) != parsed.root_mst_id:
        raise _metadata_mismatch(source, "root_mst_id")
    raw_started_at = payload.get("started_at")
    if isinstance(raw_started_at, str) and raw_started_at.strip():
        compact = format_mst_session_started_at(parse_mst_session_started_at_metadata(raw_started_at))
        if compact != parsed.started_at_compact:
            raise _metadata_mismatch(source, "started_at")
    raw_random = payload.get("random")
    if isinstance(raw_random, str) and raw_random.strip() and _validate_random_segment(raw_random.strip()) != parsed.random:
        raise _metadata_mismatch(source, "random")
def validate_mst_session_metadata_consistency(
    base_dir: Path,
    mst_session_id: str,
    *,
    require_root_metadata: bool = False,
    require_session_metadata: bool = False,
) -> StructuredMstSessionId:
    parsed = validate_mst_session_id(mst_session_id)
    root_path = root_artifact_metadata_path(base_dir, parsed.root_mst_id)
    session_path = session_metadata_path(base_dir, parsed.mst_session_id)

    root_payload = load_json_object(root_path)
    session_payload = load_json_object(session_path)
    if require_root_metadata and root_payload is None:
        raise _structured_failure(f"missing root metadata: {root_path}")
    if require_session_metadata and session_payload is None:
        raise _structured_failure(f"missing session metadata: {session_path}")
    if isinstance(root_payload, dict):
        _validate_metadata_payload(parsed, root_payload, source="root")
    if isinstance(session_payload, dict):
        _validate_metadata_payload(parsed, session_payload, source="session")
    return parsed
def create_root_session_artifacts(
    base_dir: Path,
    root_mst_id: str,
    *,
    root_payload: dict | None = None,
    started_at: datetime | None = None,
    random_segment: str | None = None,
    commit_order: str = "root-first",
    failure_stage: str | None = None,
) -> dict:
    root = validate_root_mst_id(root_mst_id)
    mst_session_id = generate_mst_session_id(root, started_at=started_at, random_segment=random_segment)
    parsed = validate_mst_session_id(mst_session_id, expected_root_mst_id=root, expected_started_at=started_at)
    metadata = mst_session_metadata(parsed)
    base = Path(base_dir)
    root_path = root_artifact_metadata_path(base, root)
    session_path = session_metadata_path(base, parsed.mst_session_id)

    if commit_order not in {"root-first", "session-first"}:
        raise ValueError("commit_order must be root-first or session-first")
    if root_path.exists():
        raise RootSessionCreateError(f"root artifact already exists: {root_path}")
    if session_path.exists():
        raise RootSessionCreateError(f"session metadata already exists: {session_path}")

    root_data = dict(root_payload or {})
    root_data.setdefault("id", root)
    root_data.update(metadata)
    session_data = {
        **metadata,
        "root_artifact_path": str(root_path.relative_to(base)),
        "schema_version": 1,
    }

    created_paths: list[Path] = []

    def _commit(path: Path, payload: dict, stage_name: str) -> None:
        _atomic_write_json(path, payload)
        created_paths.append(path)
        if failure_stage == stage_name:
            raise RootSessionCreateError(f"injected failure: {stage_name}")

    try:
        if commit_order == "root-first":
            _commit(root_path, root_data, "after_root_artifact_commit")
            _commit(session_path, session_data, "after_session_metadata_commit")
        else:
            _commit(session_path, session_data, "after_session_metadata_commit")
            _commit(root_path, root_data, "after_root_artifact_commit")
        validate_mst_session_metadata_consistency(
            base,
            parsed.mst_session_id,
            require_root_metadata=True,
            require_session_metadata=True,
        )
    except Exception as exc:
        for path in reversed(created_paths):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        _cleanup_empty_dirs(root_path.parent, base)
        _cleanup_empty_dirs(session_path.parent, base)
        if isinstance(exc, RootSessionCreateError):
            raise
        raise RootSessionCreateError(str(exc)) from exc

    return {
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "root_artifact_path": root_path,
        "session_metadata_path": session_path,
        **metadata,
    }
SESSION_WORKTREE_OUTCOME_KEY = "session_worktree_outcome"
SESSION_WORKTREE_ACTIVE_STATES = {"active", "reused"}
def _session_worktree_created_at_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
def session_worktree_branch_name(mst_session_id: str) -> str:
    parsed = validate_mst_session_id(mst_session_id)
    return f"gran-maestro/session/{parsed.mst_session_id}"
def session_worktree_path(project_root: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return _common.worktrees_dir(Path(project_root)) / "sessions" / parsed.mst_session_id
def _git_stdout(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()
def _try_git_stdout(project_root: Path, *args: str) -> str | None:
    try:
        return _git_stdout(project_root, *args)
    except RuntimeError:
        return None
def _git_worktree_entries(project_root: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git worktree list failed")
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = raw_line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries
def _git_branch_exists(project_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
def _git_branch_candidates_for_head(project_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "--points-at", "HEAD", "refs/heads"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
def _restore_detached_head_symbolic_ref(project_root: Path) -> str | None:
    candidates = _git_branch_candidates_for_head(project_root)
    if len(candidates) != 1:
        return None
    branch = candidates[0]
    result = subprocess.run(
        ["git", "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return branch
def _load_session_metadata_payload(path: Path) -> dict | None:
    payload = load_json_object(path)
    return dict(payload) if isinstance(payload, dict) else None
def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
def _session_worktree_base_snapshot(project_root: Path) -> dict[str, str | None]:
    base_sha = _git_stdout(project_root, "rev-parse", "HEAD")
    base_branch = _try_git_stdout(project_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if base_branch:
        return {
            "base_branch": base_branch,
            "base_sha": base_sha,
            "base_ref_type": "branch",
        }
    return {
        "base_branch": None,
        "base_sha": base_sha,
        "base_ref_type": "detached_head",
    }
def _session_worktree_reason_action(outcome: str) -> tuple[str, str]:
    mapping = {
        "created": ("session_worktree_created", "use_session_worktree"),
        "reused_existing": ("session_worktree_reused", "use_session_worktree"),
        "resume_preserved": ("session_worktree_resumed", "use_session_worktree"),
        "blocked_detached_head": ("detached_head", "attach_original_checkout_to_branch_before_session_worktree"),
        "blocked_branch_collision": ("session_worktree_branch_collision", "resolve_session_worktree_branch_collision"),
        "blocked_path_collision": ("session_worktree_path_collision", "resolve_session_worktree_path_collision"),
        "blocked_missing_worktree": ("session_worktree_missing", "repair_or_remove_stale_session_metadata"),
        "blocked_metadata_mismatch": ("session_metadata_mismatch", "repair_or_remove_conflicting_session_metadata"),
        "blocked_worktree_conflict": ("session_worktree_conflict", "repair_or_remove_conflicting_session_worktree"),
        "blocked_git_worktree_add_failed": ("git_worktree_add_failed", "inspect_git_worktree_error"),
    }
    return mapping.get(outcome, (outcome, "inspect_session_worktree_contract"))
def _session_worktree_payload(
    parsed: StructuredMstSessionId,
    *,
    project_root: Path,
    session_branch: str,
    worktree_path: Path,
    base_branch: str | None,
    base_sha: str,
    base_ref_type: str,
    created_at: str,
    state: str,
    outcome: str,
    existing_payload: dict | None = None,
    diagnostic: dict | None = None,
) -> dict:
    payload = dict(existing_payload or {})
    payload.update(mst_session_metadata(parsed))
    payload["schema_version"] = 1
    payload["mst_session_id"] = parsed.mst_session_id
    payload["root_mst_id"] = parsed.root_mst_id
    payload["session_worktree_path"] = str(worktree_path)
    payload["session_branch"] = session_branch
    payload["base_branch"] = base_branch
    payload["base_sha"] = base_sha
    payload["base_ref_type"] = base_ref_type
    payload["created_at"] = created_at
    payload["state"] = state
    payload["outcome"] = outcome
    payload[SESSION_WORKTREE_OUTCOME_KEY] = outcome
    reason, action = _session_worktree_reason_action(outcome)
    payload["reason"] = reason
    payload["action"] = action
    if diagnostic:
        payload["diagnostic"] = diagnostic
    else:
        payload.pop("diagnostic", None)
    return payload
def _session_metadata_matches_contract(
    payload: dict,
    *,
    mst_session_id: str,
    session_branch: str,
    worktree_path: Path,
) -> bool:
    return (
        _string_or_none(payload.get("mst_session_id")) == mst_session_id
        and _string_or_none(payload.get("session_branch")) == session_branch
        and _string_or_none(payload.get("session_worktree_path")) == str(worktree_path)
    )
def _write_session_worktree_payload(session_path: Path, payload: dict) -> dict:
    _atomic_write_json(session_path, payload)
    return payload
def ensure_session_worktree_contract(project_root: Path, mst_session_id: str) -> dict:
    project_root = Path(project_root).resolve(strict=False)
    parsed = validate_mst_session_id(mst_session_id)
    base_dir = _common.base_dir_from_project(project_root)
    session_path = session_metadata_path(base_dir, parsed.mst_session_id)
    existing_payload = _load_session_metadata_payload(session_path)
    session_branch = session_worktree_branch_name(parsed.mst_session_id)
    session_branch_ref = f"refs/heads/{session_branch}"
    worktree_path = session_worktree_path(project_root, parsed.mst_session_id).resolve(strict=False)
    created_at_now = _session_worktree_created_at_now()
    created_at = _string_or_none((existing_payload or {}).get("created_at")) or created_at_now
    snapshot = _session_worktree_base_snapshot(project_root)
    base_branch = _string_or_none(snapshot["base_branch"])
    base_sha = str(snapshot["base_sha"] or "")
    base_ref_type = str(snapshot["base_ref_type"] or "detached_head")
    entries = _git_worktree_entries(project_root)
    path_entry = next((entry for entry in entries if entry.get("worktree") == str(worktree_path)), None)
    branch_entry = next((entry for entry in entries if entry.get("branch") == session_branch_ref), None)

    if existing_payload and _session_metadata_matches_contract(
        existing_payload,
        mst_session_id=parsed.mst_session_id,
        session_branch=session_branch,
        worktree_path=worktree_path,
    ):
        existing_base_branch = _string_or_none(existing_payload.get("base_branch"))
        existing_base_sha = _string_or_none(existing_payload.get("base_sha"))
        existing_base_ref_type = _string_or_none(existing_payload.get("base_ref_type")) or ("branch" if existing_base_branch else "detached_head")
        if path_entry and branch_entry and path_entry.get("branch") == session_branch_ref and branch_entry.get("worktree") == str(worktree_path):
            return _write_session_worktree_payload(
                session_path,
                _session_worktree_payload(
                    parsed,
                    project_root=project_root,
                    session_branch=session_branch,
                    worktree_path=worktree_path,
                    base_branch=existing_base_branch,
                    base_sha=existing_base_sha or base_sha,
                    base_ref_type=existing_base_ref_type,
                    created_at=created_at,
                    state="active",
                    outcome="resume_preserved",
                    existing_payload=existing_payload,
                ),
            )
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=existing_base_branch,
                base_sha=existing_base_sha or base_sha,
                base_ref_type=existing_base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_missing_worktree",
                existing_payload=existing_payload,
                diagnostic={
                    "expected_branch": session_branch,
                    "expected_path": str(worktree_path),
                },
            ),
        )

    if existing_payload:
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=_string_or_none(existing_payload.get("base_branch")) or base_branch,
                base_sha=_string_or_none(existing_payload.get("base_sha")) or base_sha,
                base_ref_type=_string_or_none(existing_payload.get("base_ref_type")) or base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_metadata_mismatch",
                existing_payload=existing_payload,
                diagnostic={
                    "expected_branch": session_branch,
                    "expected_path": str(worktree_path),
                    "existing_branch": existing_payload.get("session_branch"),
                    "existing_path": existing_payload.get("session_worktree_path"),
                },
            ),
        )

    if path_entry and branch_entry and path_entry.get("branch") == session_branch_ref and branch_entry.get("worktree") == str(worktree_path):
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=base_branch,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="active",
                outcome="reused_existing",
            ),
        )

    if base_ref_type != "branch":
        restored_branch = _restore_detached_head_symbolic_ref(project_root)
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=None,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_detached_head",
                diagnostic={"restored_head_branch": restored_branch},
            ),
        )

    if path_entry or branch_entry:
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=base_branch,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_worktree_conflict",
                diagnostic={
                    "existing_path_entry": path_entry,
                    "existing_branch_entry": branch_entry,
                },
            ),
        )

    if worktree_path.exists():
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=base_branch,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_path_collision",
                diagnostic={"existing_path": str(worktree_path)},
            ),
        )

    if _git_branch_exists(project_root, session_branch):
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=base_branch,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_branch_collision",
                diagnostic={"existing_branch": session_branch},
            ),
        )

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "-b", session_branch, str(worktree_path), base_sha],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return _write_session_worktree_payload(
            session_path,
            _session_worktree_payload(
                parsed,
                project_root=project_root,
                session_branch=session_branch,
                worktree_path=worktree_path,
                base_branch=base_branch,
                base_sha=base_sha,
                base_ref_type=base_ref_type,
                created_at=created_at,
                state="blocked",
                outcome="blocked_git_worktree_add_failed",
                diagnostic={
                    "stderr": result.stderr.strip(),
                    "stdout": result.stdout.strip(),
                },
            ),
        )

    return _write_session_worktree_payload(
        session_path,
        _session_worktree_payload(
            parsed,
            project_root=project_root,
            session_branch=session_branch,
            worktree_path=worktree_path,
            base_branch=base_branch,
            base_sha=base_sha,
            base_ref_type=base_ref_type,
            created_at=created_at,
            state="active",
            outcome="created",
        ),
    )
ZERO_HISTORY_HASH = "0" * 64
def _utc_now_history() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
def _history_policy_home(base_dir: Path) -> Path:
    explicit = os.environ.get("MST_POLICY_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    claude_home = Path(os.environ.get("MST_CLAUDE_HOME", str(Path.home()))).expanduser()
    default = claude_home / ".claude" / "gran-maestro-policy"
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:
        return Path(base_dir) / "policy" / "gran-maestro-policy"
def _session_history_mirror_head_path(base_dir: Path, mst_session_id: str) -> Path:
    parsed = validate_mst_session_id(mst_session_id)
    return _history_policy_home(base_dir) / "ledger-heads" / f"{parsed.mst_session_id}.head"
def _canonical_history_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def _history_event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_history_event(event)).encode("utf-8")).hexdigest()
def _file_fingerprint(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"
def _history_idempotency_key(mst_session_id: str, event: dict) -> str:
    event_type = str(event.get("event_type") or event.get("type") or "event").strip()
    explicit = event.get("idempotency_key")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    stable_parts = [
        ("event_type", event_type),
        ("skill", event.get("skill")),
        ("step", event.get("step")),
        ("total_steps", event.get("total_steps")),
        ("command", event.get("command")),
        ("logical_attempt_id", event.get("logical_attempt_id")),
        ("phase", event.get("phase")),
        ("status", event.get("status")),
        ("exit_code", event.get("exit_code")),
    ]
    material = "|".join(f"{key}={value}" for key, value in stable_parts if value not in (None, ""))
    if not material:
        material = event_type
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{mst_session_id}:{event_type}:{digest}"
def _history_event_id(mst_session_id: str, event: dict) -> str:
    explicit = event.get("event_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    key = _history_idempotency_key(mst_session_id, event)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"evt-{digest}"
def _validate_history_event_contract(parsed: StructuredMstSessionId, event: dict) -> None:
    if not isinstance(event, dict):
        _common.raise_validation_failure(
            target="history_event",
            field="payload",
            reason="history event must be a JSON object",
        )
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    if event_type.startswith("mst.invocation_"):
        return

    if event.get("schema_version") != 1:
        _common.raise_validation_failure(
            target="history_event",
            field="schema_version",
            reason="schema_version is required and must be 1",
        )
    if not isinstance(event.get("event_id"), str) or not event.get("event_id", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="event_id",
            reason="event_id is required",
        )
    if not isinstance(event.get("idempotency_key"), str) or not event.get("idempotency_key", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="idempotency_key",
            reason="idempotency_key is required",
        )
    has_legacy_identity = any(
        isinstance(event.get(key), str) and event.get(key, "").strip()
        for key in ("session_id", "sessionId", "owner_session_id")
    )
    if has_legacy_identity:
        _common.raise_validation_failure(
            target="history_event",
            field="legacy_identity",
            reason="legacy session identity is not a canonical source",
            code="legacy_identity_not_canonical_source",
        )
    if not isinstance(event.get("mst_session_id"), str) or not event.get("mst_session_id", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="mst_session_id",
            reason="mst_session_id is required",
        )
    if event["mst_session_id"].strip() != parsed.mst_session_id:
        _common.raise_validation_failure(
            target="history_event",
            field="mst_session_id",
            reason="history event mst_session_id mismatch",
        )
    if not isinstance(event.get("root_mst_id"), str) or not event.get("root_mst_id", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="root_mst_id",
            reason="root_mst_id is required",
        )
    if validate_root_mst_id(event["root_mst_id"].strip()) != parsed.root_mst_id:
        _common.raise_validation_failure(
            target="history_event",
            field="root_mst_id",
            reason="root_mst_id must match root parsed from mst_session_id",
        )
    if not event_type:
        _common.raise_validation_failure(
            target="history_event",
            field="event_type",
            reason="event_type is required",
        )
    if not isinstance(event.get("artifact_id"), str) or not event.get("artifact_id", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="artifact_id",
            reason="artifact_id is required",
        )
    if not isinstance(event.get("created_at"), str) or not event.get("created_at", "").strip():
        _common.raise_validation_failure(
            target="history_event",
            field="created_at",
            reason="created_at is required",
        )
def _history_refs_from_mapping(payload: dict) -> set[str]:
    refs: set[str] = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = payload.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    return refs
def _core_rehydration_history_refs_from_env() -> set[str]:
    raw_context = os.environ.get("MST_CONTEXT_JSON", "").strip()
    if not raw_context:
        return set()
    try:
        payload = json.loads(raw_context)
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, dict):
        return set()
    core = payload.get("core_rehydration")
    if not isinstance(core, dict):
        return set()
    history = core.get("history")
    return _history_refs_from_mapping(history) if isinstance(history, dict) else set()
def _snapshot_history_refs(base_dir: Path, mst_session_id: str) -> set[str]:
    snapshot_path = Path(base_dir) / "state" / mst_session_id / "snapshot.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    history = payload.get("history")
    return _history_refs_from_mapping(history) if isinstance(history, dict) else set()
def _local_history_head(base_dir: Path, mst_session_id: str) -> str:
    try:
        return session_history_head_path(base_dir, mst_session_id).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
def _history_has_current_invocation_start(base_dir: Path, mst_session_id: str) -> bool:
    try:
        rows = _read_history_rows_unlocked(session_history_path(base_dir, mst_session_id))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    current_pid = str(os.getpid())
    for row in reversed(rows):
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("type") or "").strip()
        if event_type != "mst.invocation_start":
            continue
        if str(event.get("pid") or "") == current_pid:
            return True
    return False
def _history_transition_depth_limit() -> int:
    raw = os.environ.get("MST_TRANSITION_DEPTH_LIMIT", "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 8
    return parsed if parsed > 0 else 8
def _transition_depth_from_mapping(payload: dict) -> int:
    continuation = payload.get("continuation")
    if not isinstance(continuation, dict):
        return 0
    try:
        depth = int(continuation.get("transition_depth"))
    except (TypeError, ValueError):
        return 0
    return depth if depth > 0 else 0
def _context_transition_depth() -> int:
    raw_context = os.environ.get("MST_CONTEXT_JSON", "").strip()
    if not raw_context:
        return 0
    try:
        payload = json.loads(raw_context)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    depths = [_transition_depth_from_mapping(payload)]
    core = payload.get("core_rehydration")
    if isinstance(core, dict):
        depths.append(_transition_depth_from_mapping(core))
    return max(depths)
def _snapshot_transition_depth(base_dir: Path, mst_session_id: str) -> int:
    snapshot_path = Path(base_dir) / "state" / mst_session_id / "snapshot.json"
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return _transition_depth_from_mapping(payload) if isinstance(payload, dict) else 0
def _recursive_transition_guard_exceeded(base_dir: Path, mst_session_id: str) -> bool:
    depth = max(_context_transition_depth(), _snapshot_transition_depth(base_dir, mst_session_id))
    return depth > _history_transition_depth_limit()
def _should_skip_stale_invocation_history_append(base_dir: Path, mst_session_id: str, event: dict) -> bool:
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    if not event_type.startswith("mst.invocation_"):
        return False
    if _recursive_transition_guard_exceeded(base_dir, mst_session_id):
        return True
    refs = _core_rehydration_history_refs_from_env()
    if not refs:
        return False
    if refs & _snapshot_history_refs(base_dir, mst_session_id):
        return False
    local_head = _local_history_head(base_dir, mst_session_id)
    if local_head in refs:
        return False
    if event_type in {"mst.invocation_end", "mst.invocation_error"} and _history_has_current_invocation_start(base_dir, mst_session_id):
        return False
    return True
def _read_history_rows_unlocked(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"history row must be object line={line_no}")
        rows.append(row)
    return rows
def _history_tail_unlocked(path: Path) -> tuple[int, str, set[str]]:
    expected_seq = 1
    expected_prev = ZERO_HISTORY_HASH
    idempotency_keys: set[str] = set()
    rows = _read_history_rows_unlocked(path)
    for row in rows:
        if row.get("seq") != expected_seq:
            raise ValueError(f"history seq mismatch at seq={expected_seq}")
        if row.get("prev_hash") != expected_prev:
            raise ValueError(f"history prev_hash mismatch at seq={expected_seq}")
        event = row.get("event")
        if not isinstance(event, dict):
            raise ValueError(f"history event missing at seq={expected_seq}")
        computed = _history_event_hash(expected_prev, event)
        if row.get("event_hash") != computed:
            raise ValueError(f"history event_hash mismatch at seq={expected_seq}")
        key = event.get("idempotency_key")
        if isinstance(key, str) and key.strip():
            idempotency_keys.add(key.strip())
        expected_prev = computed
        expected_seq += 1
    return expected_seq - 1, expected_prev, idempotency_keys
def _write_history_heads(base_dir: Path, mst_session_id: str, head_hash: str, history_file: Path, seq: int) -> None:
    local_head = session_history_head_path(base_dir, mst_session_id)
    mirror_head = _session_history_mirror_head_path(base_dir, mst_session_id)
    verify_state = session_history_verify_path(base_dir, mst_session_id)
    _atomic_write_text(local_head, head_hash + "\n")
    try:
        _atomic_write_text(mirror_head, head_hash + "\n")
    except OSError:
        if os.environ.get("MST_POLICY_HOME", "").strip():
            raise
        fallback_mirror = Path(base_dir) / "policy" / "gran-maestro-policy" / "ledger-heads" / f"{mst_session_id}.head"
        _atomic_write_text(fallback_mirror, head_hash + "\n")
    _atomic_write_text(verify_state, f"{head_hash}\t{_file_fingerprint(history_file)}\t{seq}\n")
def _read_history_sidecar_head(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
def _read_verify_head(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return raw.split("\t", 1)[0].strip()
def _history_sidecars_match_tail(base_dir: Path, mst_session_id: str, tail_hash: str) -> bool:
    local_head = _read_history_sidecar_head(session_history_head_path(base_dir, mst_session_id))
    mirror_head = _read_history_sidecar_head(_session_history_mirror_head_path(base_dir, mst_session_id))
    verify_head = _read_verify_head(session_history_verify_path(base_dir, mst_session_id))
    return local_head == tail_hash and mirror_head == tail_hash and verify_head == tail_hash
def write_session_history_event(base_dir: Path, mst_session_id: str, payload: dict) -> Path:
    parsed = validate_mst_session_metadata_consistency(base_dir, mst_session_id)
    path = session_history_path(base_dir, parsed.mst_session_id)
    if _should_skip_stale_invocation_history_append(base_dir, parsed.mst_session_id, payload):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / "history.lock"

    event = dict(payload)
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    if not event_type:
        event_type = "event"
    event["event_type"] = event_type
    event.setdefault("type", event_type)
    event.setdefault("schema_version", 1)
    event.setdefault("mst_session_id", parsed.mst_session_id)
    event.setdefault("root_mst_id", parsed.root_mst_id)
    event.setdefault("artifact_id", parsed.mst_session_id)
    event.setdefault("created_at", event.get("timestamp") or _utc_now_history())
    event.setdefault("idempotency_key", _history_idempotency_key(parsed.mst_session_id, event))
    event.setdefault("event_id", _history_event_id(parsed.mst_session_id, event))
    _validate_history_event_contract(parsed, event)
    event.setdefault("timestamp", event["created_at"])

    with open(lock_path, "a+", encoding="utf-8") as lock_handle:
        _common._lock_exclusive_with_timeout(lock_handle, timeout_sec=5)
        try:
            last_seq, last_hash, idempotency_keys = _history_tail_unlocked(path)
            if event_type.startswith("mst.invocation_") and last_seq > 0:
                if not _history_sidecars_match_tail(base_dir, parsed.mst_session_id, last_hash):
                    return path
            if event["idempotency_key"] in idempotency_keys:
                return path
            event_hash = _history_event_hash(last_hash, event)
            row = {
                "seq": last_seq + 1,
                "prev_hash": last_hash,
                "event_hash": event_hash,
                "event": event,
                "mst_session_id": parsed.mst_session_id,
                "timestamp": event["created_at"],
            }
            with open(path, "a", encoding="utf-8", buffering=1) as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_parent_dir(path)
            _write_history_heads(base_dir, parsed.mst_session_id, event_hash, path, last_seq + 1)
            return path
        finally:
            _common._unlock(lock_handle)
def _session_id_from_payload(raw: str) -> str | None:
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    direct = payload.get("mst_session_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    core = payload.get("core_rehydration")
    if isinstance(core, dict):
        direct = core.get("mst_session_id")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    return None
def _context_payload_session_candidates(payload: dict) -> list[str]:
    candidates: list[str] = []
    direct = payload.get("mst_session_id")
    if isinstance(direct, str) and direct.strip():
        candidates.append(direct.strip())
    core = payload.get("core_rehydration")
    if isinstance(core, dict):
        nested = core.get("mst_session_id")
        if isinstance(nested, str) and nested.strip():
            candidates.append(nested.strip())
        next_execution = core.get("next_execution")
        if isinstance(next_execution, dict):
            env = next_execution.get("env")
            if isinstance(env, dict):
                next_env_sid = env.get("MST_SESSION_ID")
                if isinstance(next_env_sid, str) and next_env_sid.strip():
                    candidates.append(next_env_sid.strip())
            context = next_execution.get("context")
            if isinstance(context, dict):
                next_context_sid = context.get("mst_session_id")
                if isinstance(next_context_sid, str) and next_context_sid.strip():
                    candidates.append(next_context_sid.strip())
        handoff = core.get("execution_handoff")
        if isinstance(handoff, dict):
            handoff_sid = handoff.get("mst_session_id")
            if isinstance(handoff_sid, str) and handoff_sid.strip():
                candidates.append(handoff_sid.strip())
    return candidates
def _context_payload_root_candidates(payload: dict) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    direct = payload.get("root_mst_id")
    if isinstance(direct, str) and direct.strip():
        candidates.append(("root_mst_id", direct.strip()))
    core = payload.get("core_rehydration")
    if isinstance(core, dict):
        nested = core.get("root_mst_id")
        if isinstance(nested, str) and nested.strip():
            candidates.append(("core_rehydration.root_mst_id", nested.strip()))
        next_execution = core.get("next_execution")
        if isinstance(next_execution, dict):
            context = next_execution.get("context")
            if isinstance(context, dict):
                next_context_root = context.get("root_mst_id")
                if isinstance(next_context_root, str) and next_context_root.strip():
                    candidates.append(("core_rehydration.next_execution.context.root_mst_id", next_context_root.strip()))
        handoff = core.get("execution_handoff")
        if isinstance(handoff, dict):
            handoff_root = handoff.get("root_mst_id")
            if isinstance(handoff_root, str) and handoff_root.strip():
                candidates.append(("core_rehydration.execution_handoff.root_mst_id", handoff_root.strip()))
    return candidates
