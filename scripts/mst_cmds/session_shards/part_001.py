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
                diagnostic={"worktree_creation": "skipped_detached_head"},
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
SESSION_MERGE_SCOPE_CHILD_CALLERS = frozenset(
    {
        "request_child_accept",
        "auto_accept_result_child",
        "auto_accept_result_for_child",
    }
)
SESSION_MERGE_SCOPE_CHILD_OPTIONAL_CALLERS = frozenset({"review_completed"})
SESSION_MERGE_SCOPE_FINAL_CALLERS = frozenset({"session_level_accept", "terminal_success"})
SESSION_MERGE_SCOPE_FORBIDDEN_CALLERS = frozenset(
    {
        "assistant_turn_end",
        "stop_hook_continuation",
        "tool_exit",
        "subskill_return",
        "review_pass_only",
        "cancel",
        "recover_dry_run",
    }
)
SESSION_MERGE_SCOPE_ALLOWED_TARGETS = frozenset({"auto", "child_to_session", "session_to_original"})
SESSION_FINAL_MERGE_REQUIRED_EVIDENCE = (
    "all_must_dod_eligible",
    "children_clean",
    "base_branch_lock_acquired",
    "destructive_command_policy_passed",
)
def _merge_scope_payload(
    *,
    ok: bool,
    caller: str,
    requested_target: str,
    merge_state: str,
    child_to_session: bool,
    session_to_original: bool,
    target_branch: str | None,
    session_branch: str | None,
    original_base_branch: str | None,
    original_base_sha: str | None,
    reason: str | None = None,
    action: str | None = None,
    evidence: dict | None = None,
    forbidden_caller: bool = False,
    required_evidence: tuple[str, ...] = (),
    legacy_diagnostics: dict | None = None,
) -> dict:
    payload = {
        "ok": ok,
        "caller": caller,
        "requested_target": requested_target,
        "merge_state": merge_state,
        "child_to_session": child_to_session,
        "session_to_original": session_to_original,
        "target_branch": target_branch,
        "session_branch": session_branch,
        "original_base_branch": original_base_branch,
        "original_base_sha": original_base_sha,
        "forbidden_caller": forbidden_caller,
        "required_evidence": list(required_evidence),
        "reference_only_fields": ["original_base_branch", "original_base_sha"],
        "evidence": dict(evidence or {}),
    }
    if reason:
        payload["reason"] = reason
    if action:
        payload["action"] = action
    if legacy_diagnostics:
        payload["legacy_diagnostics"] = legacy_diagnostics
    return payload
def _normalize_merge_requested_target(value: str | None) -> str:
    normalized = _string_or_none(value) or "auto"
    if normalized not in SESSION_MERGE_SCOPE_ALLOWED_TARGETS:
        raise ValueError(
            "requested_target must be one of "
            f"{', '.join(sorted(SESSION_MERGE_SCOPE_ALLOWED_TARGETS))}"
        )
    return normalized
def _merge_scope_identity_non_success(
    caller: str,
    requested_target: str,
    *,
    error: object | None = None,
) -> dict:
    diagnostics = _common.legacy_session_diagnostics()
    code = _common.session_identity_non_success_code(error, diagnostics) or "missing_canonical_mst_session_id"
    reason_map = {
        "mst_session_id_mismatch": "canonical_identity_conflict",
        "invalid_canonical_mst_session_id": "invalid_canonical_identity",
        "legacy_identity_not_canonical_source": "legacy_identity_not_canonical_source",
        "missing_canonical_mst_session_id": "missing_canonical_identity",
    }
    action_map = {
        "mst_session_id_mismatch": "repair_canonical_identity_conflict",
        "invalid_canonical_mst_session_id": "emit_diagnostic_no_mutation",
        "legacy_identity_not_canonical_source": "emit_diagnostic_no_mutation",
        "missing_canonical_mst_session_id": "emit_diagnostic_no_mutation",
    }
    return _merge_scope_payload(
        ok=False,
        caller=caller,
        requested_target=requested_target,
        merge_state="non_success_diagnostic",
        child_to_session=False,
        session_to_original=False,
        target_branch=None,
        session_branch=None,
        original_base_branch=None,
        original_base_sha=None,
        reason=reason_map.get(code, code),
        action=action_map.get(code, "emit_diagnostic_no_mutation"),
        evidence={"mutation_performed": False},
        legacy_diagnostics=diagnostics,
    )
def _resolve_merge_scope_session_context(
    project_root: Path,
    *,
    caller: str,
    requested_target: str,
    mst_session_id: str | None = None,
) -> tuple[dict | None, dict | None]:
    raw_session_id = _string_or_none(mst_session_id) or os.environ.get("MST_SESSION_ID", "").strip()
    if not raw_session_id:
        return None, _merge_scope_identity_non_success(caller, requested_target)
    try:
        parsed = validate_mst_session_id(raw_session_id)
    except ValueError as exc:
        return None, _merge_scope_identity_non_success(caller, requested_target, error=exc)

    base_dir = _common.base_dir_from_project(project_root)
    session_path = session_metadata_path(base_dir, parsed.mst_session_id)
    payload = _load_session_metadata_payload(session_path)
    if not isinstance(payload, dict):
        return None, _merge_scope_payload(
            ok=False,
            caller=caller,
            requested_target=requested_target,
            merge_state="non_success_diagnostic",
            child_to_session=False,
            session_to_original=False,
            target_branch=None,
            session_branch=None,
            original_base_branch=None,
            original_base_sha=None,
            reason="session_metadata_missing",
            action="ensure_session_worktree_contract_before_merge",
            evidence={"session_metadata_path": str(session_path)},
        )

    state = _string_or_none(payload.get("state")) or ""
    session_branch = _string_or_none(payload.get("session_branch"))
    worktree_path = _string_or_none(payload.get("session_worktree_path"))
    original_base_branch = _string_or_none(payload.get("base_branch"))
    original_base_sha = _string_or_none(payload.get("base_sha"))
    expected_branch = session_worktree_branch_name(parsed.mst_session_id)
    expected_path = str(session_worktree_path(project_root, parsed.mst_session_id).resolve(strict=False))
    if state not in SESSION_WORKTREE_ACTIVE_STATES:
        return None, _merge_scope_payload(
            ok=False,
            caller=caller,
            requested_target=requested_target,
            merge_state="non_success_diagnostic",
            child_to_session=False,
            session_to_original=False,
            target_branch=None,
            session_branch=session_branch,
            original_base_branch=original_base_branch,
            original_base_sha=original_base_sha,
            reason=_string_or_none(payload.get("reason")) or "session_worktree_not_active",
            action=_string_or_none(payload.get("action")) or "repair_or_remove_conflicting_session_metadata",
            evidence={"state": state, "outcome": payload.get("outcome")},
        )
    if not session_branch or not worktree_path or not original_base_branch or not original_base_sha:
        return None, _merge_scope_payload(
            ok=False,
            caller=caller,
            requested_target=requested_target,
            merge_state="non_success_diagnostic",
            child_to_session=False,
            session_to_original=False,
            target_branch=None,
            session_branch=session_branch,
            original_base_branch=original_base_branch,
            original_base_sha=original_base_sha,
            reason="session_metadata_incomplete",
            action="repair_or_remove_conflicting_session_metadata",
            evidence={"session_metadata_path": str(session_path)},
        )
    if session_branch != expected_branch or worktree_path != expected_path:
        return None, _merge_scope_payload(
            ok=False,
            caller=caller,
            requested_target=requested_target,
            merge_state="non_success_diagnostic",
            child_to_session=False,
            session_to_original=False,
            target_branch=None,
            session_branch=session_branch,
            original_base_branch=original_base_branch,
            original_base_sha=original_base_sha,
            reason="session_metadata_mismatch",
            action="repair_or_remove_conflicting_session_metadata",
            evidence={
                "expected_session_branch": expected_branch,
                "expected_session_worktree_path": expected_path,
                "session_metadata_path": str(session_path),
            },
        )

    return {
        "mst_session_id": parsed.mst_session_id,
        "session_branch": session_branch,
        "session_worktree_path": worktree_path,
        "original_base_branch": original_base_branch,
        "original_base_sha": original_base_sha,
        "session_metadata_path": str(session_path),
    }, None
def _merge_scope_git_stdout(path: Path, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
    return True, result.stdout.strip()
def _merge_scope_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "ok", "pass", "passed"}
    return False
def _final_merge_blocked_payload(
    caller: str,
    requested_target: str,
    session_context: dict,
    *,
    reason: str,
    action: str,
    evidence: dict | None = None,
) -> dict:
    return _merge_scope_payload(
        ok=False,
        caller=caller,
        requested_target=requested_target,
        merge_state="blocked_final_merge",
        child_to_session=False,
        session_to_original=False,
        target_branch=None,
        session_branch=session_context["session_branch"],
        original_base_branch=session_context["original_base_branch"],
        original_base_sha=session_context["original_base_sha"],
        reason=reason,
        action=action,
        evidence=evidence,
        required_evidence=SESSION_FINAL_MERGE_REQUIRED_EVIDENCE,
    )
def _resolve_final_merge_scope(
    project_root: Path,
    *,
    caller: str,
    requested_target: str,
    session_context: dict,
    evidence: dict | None = None,
) -> dict:
    evidence_payload = dict(evidence or {})
    session_worktree = Path(session_context["session_worktree_path"]).resolve(strict=False)
    if not session_worktree.is_dir():
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="session_worktree_missing",
            action="repair_or_remove_conflicting_session_metadata",
            evidence={"session_worktree_path": str(session_worktree)},
        )

    ok_status, status_output = _merge_scope_git_stdout(session_worktree, "status", "--porcelain")
    if not ok_status:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="session_worktree_status_failed",
            action="inspect_session_worktree_before_final_merge",
            evidence={"git_error": status_output},
        )
    if status_output:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="dirty_session_branch",
            action="clean_session_branch_before_final_merge",
            evidence={"git_status": status_output.splitlines()},
        )

    ok_unmerged, unmerged_output = _merge_scope_git_stdout(session_worktree, "diff", "--name-only", "--diff-filter=U")
    if not ok_unmerged:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="session_conflict_check_failed",
            action="inspect_session_conflicts_before_final_merge",
            evidence={"git_error": unmerged_output},
        )
    if unmerged_output:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="child_conflict",
            action="resolve_child_conflicts_before_final_merge",
            evidence={"conflicted_paths": unmerged_output.splitlines()},
        )

    for key in SESSION_FINAL_MERGE_REQUIRED_EVIDENCE:
        if not _merge_scope_bool(evidence_payload.get(key)):
            return _final_merge_blocked_payload(
                caller,
                requested_target,
                session_context,
                reason=f"missing_{key}",
                action="collect_required_final_merge_evidence",
                evidence={**evidence_payload, "missing_evidence": key},
            )

    if _merge_scope_bool(evidence_payload.get("conflict_detected")):
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="final_merge_conflict",
            action="resolve_conflict_before_final_merge",
            evidence=evidence_payload,
        )

    ok_base_sha, current_base_sha = _merge_scope_git_stdout(project_root, "rev-parse", session_context["original_base_branch"])
    if not ok_base_sha:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="original_base_missing",
            action="inspect_original_base_reference",
            evidence={"git_error": current_base_sha},
        )
    if current_base_sha != session_context["original_base_sha"]:
        return _final_merge_blocked_payload(
            caller,
            requested_target,
            session_context,
            reason="original_base_drift_detected",
            action="refresh_session_against_original_base",
            evidence={
                **evidence_payload,
                "expected_original_base_sha": session_context["original_base_sha"],
                "current_original_base_sha": current_base_sha,
            },
        )

    return _merge_scope_payload(
        ok=True,
        caller=caller,
        requested_target=requested_target,
        merge_state="authorized_final_merge",
        child_to_session=False,
        session_to_original=True,
        target_branch=session_context["original_base_branch"],
        session_branch=session_context["session_branch"],
        original_base_branch=session_context["original_base_branch"],
        original_base_sha=session_context["original_base_sha"],
        evidence={**evidence_payload, "current_original_base_sha": current_base_sha},
        required_evidence=SESSION_FINAL_MERGE_REQUIRED_EVIDENCE,
    )
SESSION_START_LEGACY_DIAGNOSTIC_FIELDS = (
    "owner_session_id",
    "owner_pid",
    "owner_ppid",
    "session_id",
    "sessionId",
    "MST_STATE_PPID",
    "MST_SNAPSHOT_SESSION_ID",
    "hook_session_id",
    "transcript_uuid",
)
def _session_start_legacy_diagnostics(payload: dict | None) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    diagnostics: dict[str, object] = {}
    for key in SESSION_START_LEGACY_DIAGNOSTIC_FIELDS:
        value = payload.get(key)
        if _string_or_none(value) is not None or isinstance(value, (int, float)) and not isinstance(value, bool):
            diagnostics[key] = value
    return diagnostics

def _session_start_path(value: object) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    return os.path.abspath(os.path.expanduser(text))

def _session_start_bool(payload: dict, key: str) -> bool:
    return bool(payload.get(key)) if isinstance(payload, dict) else False

def _dirty_base_policy(git_status: dict | None) -> tuple[str, list[str]]:
    status = git_status if isinstance(git_status, dict) else {}
    if _session_start_bool(status, "conflicted"):
        return "conflicted_index", ["conflicted"]
    if _session_start_bool(status, "staged"):
        return "staged_changes", ["staged"]
    if _session_start_bool(status, "dirty") or _session_start_bool(status, "modified"):
        return "dirty_worktree", ["dirty"]
    if _session_start_bool(status, "untracked"):
        return "untracked_files", ["untracked"]
    return "clean", []

def _canonical_session_payload(session_metadata: dict | None) -> dict[str, object]:
    if not isinstance(session_metadata, dict):
        return {}
    mst_session_id = _string_or_none(session_metadata.get("mst_session_id"))
    if not mst_session_id:
        return {}
    payload: dict[str, object] = {"mst_session_id": mst_session_id}
    for key in ("state", "session_worktree_path", "session_branch", "base_branch", "base_sha"):
        value = _string_or_none(session_metadata.get(key))
        if value:
            payload[key] = value
    return payload

def _session_start_result(
    *,
    ok: bool,
    classification: str,
    dirty_base_policy: str,
    resume_action: str,
    nested_session_action: str,
    action: str,
    reason: str | None = None,
    canonical_session: dict | None = None,
    legacy_diagnostics: dict | None = None,
    target_project_root: str | None = None,
    unsafe_merge_blocked: bool = False,
    parent_session: dict | None = None,
    diagnostics: list[dict] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": ok,
        "classification": classification,
        "dirty_base_policy": dirty_base_policy,
        "resume_action": resume_action,
        "nested_session_action": nested_session_action,
        "action": action,
        "target_project_root": target_project_root,
        "unsafe_merge_blocked": unsafe_merge_blocked,
        "destructive_action_allowed": False,
        "canonical_session": canonical_session or {},
        "legacy_diagnostics": legacy_diagnostics or {},
        "diagnostics": diagnostics or [],
    }
    if reason:
        payload["reason"] = reason
    if parent_session is not None:
        payload["parent_session"] = parent_session
    return payload

def resolve_session_start_policy_state(
    *,
    git_status: dict | None = None,
    entry_context: dict | None = None,
    session_metadata: dict | None = None,
) -> dict[str, object]:
    status = git_status if isinstance(git_status, dict) else {}
    context = entry_context if isinstance(entry_context, dict) else {}
    metadata = session_metadata if isinstance(session_metadata, dict) else None
    dirty_policy, dirty_signals = _dirty_base_policy(status)
    canonical_session = _canonical_session_payload(metadata)
    legacy_diagnostics = _session_start_legacy_diagnostics(metadata)
    entry_type = _string_or_none(context.get("entry_type")) or "start"
    cwd = _session_start_path(context.get("cwd"))
    session_root = _session_start_path(canonical_session.get("session_worktree_path"))

    if dirty_policy != "clean":
        return _session_start_result(
            ok=False,
            classification="blocked_dirty_base",
            dirty_base_policy=dirty_policy,
            resume_action="clean_or_stash_before_session_start",
            nested_session_action="none",
            action="clean_or_stash_before_session_start",
            reason=dirty_policy,
            canonical_session=canonical_session,
            legacy_diagnostics=legacy_diagnostics,
            unsafe_merge_blocked=True,
            diagnostics=[{"code": "dirty_base_policy", "signals": dirty_signals}],
        )

    if entry_type in {"resume", "recover"} and not canonical_session:
        return _session_start_result(
            ok=False,
            classification="session_identity_required",
            dirty_base_policy="clean",
            resume_action="provide_canonical_mst_session_id",
            nested_session_action="none",
            action="provide_canonical_mst_session_id",
            reason="missing_canonical_mst_session_id",
            legacy_diagnostics=legacy_diagnostics,
            unsafe_merge_blocked=True,
        )

    if entry_type == "recover" and bool(context.get("recover_dry_run")):
        return _session_start_result(
            ok=False,
            classification="recover_dry_run",
            dirty_base_policy="clean",
            resume_action="recover_dry_run",
            nested_session_action="none",
            action="report_recovery_plan_without_mutation",
            reason="recover_dry_run",
            canonical_session=canonical_session,
            legacy_diagnostics=legacy_diagnostics,
            target_project_root=session_root,
            unsafe_merge_blocked=True,
        )

    if entry_type == "resume":
        if not session_root:
            return _session_start_result(
                ok=False,
                classification="repair_session_metadata",
                dirty_base_policy="clean",
                resume_action="repair_session_metadata",
                nested_session_action="none",
                action="repair_or_remove_conflicting_session_metadata",
                reason="missing_session_worktree_path",
                canonical_session=canonical_session,
                legacy_diagnostics=legacy_diagnostics,
                unsafe_merge_blocked=True,
            )
        if not _string_or_none(canonical_session.get("session_branch")):
            return _session_start_result(
                ok=False,
                classification="repair_session_metadata",
                dirty_base_policy="clean",
                resume_action="repair_session_metadata",
                nested_session_action="none",
                action="repair_or_remove_conflicting_session_metadata",
                reason="missing_session_branch",
                canonical_session=canonical_session,
                legacy_diagnostics=legacy_diagnostics,
                target_project_root=session_root,
                unsafe_merge_blocked=True,
            )
        if context.get("worktree_exists") is False:
            return _session_start_result(
                ok=False,
                classification="repair_session_worktree",
                dirty_base_policy="clean",
                resume_action="repair_missing_session_worktree",
                nested_session_action="none",
                action="repair_or_remove_stale_session_metadata",
                reason="session_worktree_missing",
                canonical_session=canonical_session,
                legacy_diagnostics=legacy_diagnostics,
                target_project_root=session_root,
                unsafe_merge_blocked=True,
            )
        return _session_start_result(
            ok=True,
            classification="resume_existing_session",
            dirty_base_policy="clean",
            resume_action="resume_existing_session",
            nested_session_action="none",
            action="use_session_worktree",
            canonical_session=canonical_session,
            legacy_diagnostics=legacy_diagnostics,
            target_project_root=session_root,
        )

    if entry_type == "nested":
        nested_intent = _string_or_none(context.get("nested_intent")) or "inherit"
        if nested_intent == "top_level":
            return _session_start_result(
                ok=False,
                classification="blocked_nested_top_level",
                dirty_base_policy="clean",
                resume_action="inherit_parent_session",
                nested_session_action="block_top_level_session",
                action="inherit_parent_session_or_create_child_worktree",
                reason="nested_top_level_session_blocked",
                canonical_session=canonical_session,
                legacy_diagnostics=legacy_diagnostics,
                target_project_root=session_root,
                unsafe_merge_blocked=True,
                parent_session=canonical_session,
            )
        if nested_intent == "child_worktree":
            return _session_start_result(
                ok=True,
                classification="nested_session_entry",
                dirty_base_policy="clean",
                resume_action="inherit_parent_session",
                nested_session_action="create_child_worktree",
                action="create_child_worktree_under_parent_session",
                canonical_session=canonical_session,
                legacy_diagnostics=legacy_diagnostics,
                target_project_root=cwd or session_root,
                parent_session=canonical_session,
            )
        return _session_start_result(
            ok=True,
            classification="nested_session_entry",
            dirty_base_policy="clean",
            resume_action="inherit_parent_session",
            nested_session_action="inherit_parent_session",
            action="use_parent_session_context",
            canonical_session=canonical_session,
            legacy_diagnostics=legacy_diagnostics,
            target_project_root=session_root or cwd,
            parent_session=canonical_session,
        )

    return _session_start_result(
        ok=True,
        classification="top_level_session_start",
        dirty_base_policy="clean",
        resume_action="create_new_session",
        nested_session_action="none",
        action="create_session_worktree",
        canonical_session=canonical_session,
        legacy_diagnostics=legacy_diagnostics,
        target_project_root=cwd,
    )

SESSION_RESERVATION_FIELDS = (
    "mst_session_id",
    "session_branch",
    "session_worktree_path",
    "metadata_path",
    "base_branch",
    "base_sha",
)
SESSION_RESERVATION_COLLISION_FIELDS = (
    "metadata_path",
    "mst_session_id",
    "session_branch",
    "session_worktree_path",
)

def _session_reservation_candidate_payload(candidate: dict | None) -> dict[str, object]:
    if not isinstance(candidate, dict):
        return {}
    payload: dict[str, object] = {}
    for key in SESSION_RESERVATION_FIELDS:
        value = _string_or_none(candidate.get(key))
        if value:
            payload[key] = value
    return payload

def session_reservation_idempotency_key(*, candidate: dict | None = None) -> str:
    payload = _session_reservation_candidate_payload(candidate)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "session-reservation:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

def _session_reservation_legacy_diagnostics(payload: dict | None) -> dict[str, object]:
    return _session_start_legacy_diagnostics(payload)

def _session_reservation_collisions(
    candidate_payload: dict[str, object],
    existing_reservations: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    collisions: list[dict[str, object]] = []
    existing = existing_reservations if isinstance(existing_reservations, list) else []
    for index, reservation in enumerate(existing):
        if not isinstance(reservation, dict):
            continue
        fields = [
            key
            for key in SESSION_RESERVATION_COLLISION_FIELDS
            if _string_or_none(candidate_payload.get(key))
            and _string_or_none(candidate_payload.get(key)) == _string_or_none(reservation.get(key))
        ]
        if fields:
            collisions.append(
                {
                    "index": index,
                    "fields": fields,
                    "policy": "retry_with_new_session_identity",
                }
            )
    return collisions

def _reservation_result(
    *,
    ok: bool,
    classification: str,
    reservation_policy: str,
    collision_policy: str,
    lock_policy: str,
    base_drift_policy: str,
    final_merge_action: str,
    action: str,
    reservation: dict | None = None,
    collisions: list[dict] | None = None,
    legacy_diagnostics: dict | None = None,
    diagnostics: list[dict] | None = None,
    unsafe_merge_blocked: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": ok,
        "classification": classification,
        "reservation_policy": reservation_policy,
        "collision_policy": collision_policy,
        "lock_policy": lock_policy,
        "base_drift_policy": base_drift_policy,
        "final_merge_action": final_merge_action,
        "action": action,
        "reservation": reservation or {},
        "collisions": collisions or [],
        "legacy_diagnostics": legacy_diagnostics or {},
        "diagnostics": diagnostics or [],
        "unsafe_merge_blocked": unsafe_merge_blocked,
        "destructive_action_allowed": False,
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    return payload

def _resolve_final_merge_lock_policy(
    *,
    candidate_payload: dict[str, object],
    final_merge_context: dict,
) -> tuple[str, str, bool]:
    lock = final_merge_context.get("lock") if isinstance(final_merge_context.get("lock"), dict) else {}
    lock_state = _string_or_none(lock.get("state")) or "missing"
    owner = _string_or_none(lock.get("owner_mst_session_id"))
    session_id = _string_or_none(candidate_payload.get("mst_session_id"))
    if lock_state == "busy":
        return "lock_busy", "wait_for_base_merge_lock", True
    if lock_state == "stale":
        return "stale_lock", "recover_or_repair_base_merge_lock", True
    if lock_state != "held":
        return "lock_missing", "acquire_base_merge_lock", True
    if owner != session_id:
        return "lock_owner_mismatch", "wait_for_or_recover_base_merge_lock", True
    return "owned_lock", "authorize_final_merge", False

def resolve_parallel_session_reservation_state(
    *,
    candidate: dict | None = None,
    existing_reservations: list[dict[str, object]] | None = None,
    final_merge_context: dict | None = None,
) -> dict[str, object]:
    candidate_payload = _session_reservation_candidate_payload(candidate)
    legacy_diagnostics = _session_reservation_legacy_diagnostics(candidate)
    session_id = _string_or_none(candidate_payload.get("mst_session_id"))
    context = final_merge_context if isinstance(final_merge_context, dict) else {}
    final_merge_requested = bool(context.get("requested"))

    if not session_id:
        return _reservation_result(
            ok=False,
            classification="session_identity_required",
            reservation_policy="canonical_identity_required",
            collision_policy="none",
            lock_policy="canonical_identity_required" if final_merge_requested else "not_requested",
            base_drift_policy="not_checked",
            final_merge_action="provide_canonical_mst_session_id",
            action="provide_canonical_mst_session_id",
            legacy_diagnostics=legacy_diagnostics,
            unsafe_merge_blocked=True,
        )

    collisions = _session_reservation_collisions(candidate_payload, existing_reservations)
    idempotency_key = session_reservation_idempotency_key(candidate=candidate_payload)
    reservation = {**candidate_payload, "idempotency_key": idempotency_key}
    if collisions:
        return _reservation_result(
            ok=False,
            classification="reservation_collision",
            reservation_policy="collision_detected",
            collision_policy="retry_with_new_session_identity",
            lock_policy="not_requested",
            base_drift_policy="not_checked",
            final_merge_action="reserve_session_before_final_merge",
            action="allocate_new_session_identity_or_resume_existing",
            reservation=reservation,
            collisions=collisions,
            legacy_diagnostics=legacy_diagnostics,
            unsafe_merge_blocked=True,
            idempotency_key=idempotency_key,
        )

    if final_merge_requested:
        lock_policy, lock_action, lock_blocked = _resolve_final_merge_lock_policy(
            candidate_payload=candidate_payload,
            final_merge_context=context,
        )
        current_base_sha = _string_or_none(context.get("current_base_sha"))
        reserved_base_sha = _string_or_none(candidate_payload.get("base_sha"))
        if not lock_blocked and current_base_sha and reserved_base_sha and current_base_sha != reserved_base_sha:
            return _reservation_result(
                ok=False,
                classification="final_merge_blocked",
                reservation_policy="atomic_reservation_available",
                collision_policy="none",
                lock_policy=lock_policy,
                base_drift_policy="base_sha_drift",
                final_merge_action="refresh_session_or_rebase_before_final_merge",
                action="refresh_session_or_rebase_before_final_merge",
                reservation=reservation,
                legacy_diagnostics=legacy_diagnostics,
                diagnostics=[
                    {
                        "code": "base_sha_drift",
                        "reserved_base_sha": reserved_base_sha,
                        "current_base_sha": current_base_sha,
                        "safer_action": "refresh_session_or_rebase_before_final_merge",
                    }
                ],
                unsafe_merge_blocked=True,
                idempotency_key=idempotency_key,
            )
        if lock_blocked:
            return _reservation_result(
                ok=False,
                classification="final_merge_blocked",
                reservation_policy="atomic_reservation_available",
                collision_policy="none",
                lock_policy=lock_policy,
                base_drift_policy="not_checked",
                final_merge_action=lock_action,
                action=lock_action,
                reservation=reservation,
                legacy_diagnostics=legacy_diagnostics,
                unsafe_merge_blocked=True,
                idempotency_key=idempotency_key,
            )
        return _reservation_result(
            ok=True,
            classification="final_merge_authorized",
            reservation_policy="atomic_reservation_available",
            collision_policy="none",
            lock_policy=lock_policy,
            base_drift_policy="clean",
            final_merge_action="authorize_final_merge",
            action="authorize_final_merge",
            reservation=reservation,
            legacy_diagnostics=legacy_diagnostics,
            idempotency_key=idempotency_key,
        )

    return _reservation_result(
        ok=True,
        classification="reservation_available",
        reservation_policy="atomic_reservation_available",
        collision_policy="none",
        lock_policy="not_requested",
        base_drift_policy="not_checked",
        final_merge_action="reserve_session_before_final_merge",
        action="create_session_reservation",
        reservation=reservation,
        legacy_diagnostics=legacy_diagnostics,
        idempotency_key=idempotency_key,
    )

SECURITY_CONTRACT_MAX_VALUE_LENGTH = 160
SECURITY_CONTRACT_SHELL_META = set(";&|`$<>(){}[]!\\\n\r")
SECURITY_CONTRACT_HTML_MARKERS = ("<", ">", "javascript:", "onerror=", "onload=", "script")
SECURITY_CONTRACT_DESTRUCTIVE_GIT = (
    ("git", "branch", "-d"),
    ("git", "worktree", "remove", "--force"),
    ("git", "reset"),
    ("git", "clean"),
    ("git", "checkout", "--"),
)

def _security_legacy_diagnostics(payload: dict | None) -> dict[str, object]:
    return _session_start_legacy_diagnostics(payload)

def _security_text(value: object) -> str | None:
    return _string_or_none(value)

def _security_reason(value: object, *, allow_slash: bool = False, allow_query: bool = False) -> str | None:
    text = _security_text(value)
    if text is None:
        return "missing"
    if len(text) > SECURITY_CONTRACT_MAX_VALUE_LENGTH:
        return "too_long"
    lowered = text.lower()
    if "%2e" in lowered or "%2f" in lowered or ".." in text:
        return "path_traversal"
    if not allow_slash and "/" in text:
        return "slash_not_allowed"
    if any(char in text for char in SECURITY_CONTRACT_SHELL_META):
        return "shell_metacharacter"
    if any(marker in lowered for marker in SECURITY_CONTRACT_HTML_MARKERS):
        return "ui_injection"
    if text != unicodedata.normalize("NFKC", text):
        return "unicode_normalization"
    if not text.isascii():
        return "non_ascii"
    if allow_query:
        return None
    return None

def _security_session_reason(value: object) -> str | None:
    reason = _security_reason(value)
    if reason is not None:
        return reason
    text = _security_text(value)
    if text is None:
        return "missing"
    try:
        validate_mst_session_id(text)
    except ValueError:
        return "invalid_structured_mst_session_id"
    return None

def _security_branch_reason(value: object, mst_session_id: str) -> str | None:
    reason = _security_reason(value, allow_slash=True)
    if reason is not None:
        return reason
    text = _security_text(value)
    if text != session_worktree_branch_name(mst_session_id):
        return "unexpected_session_branch"
    return None

def _security_path_reason(value: object) -> str | None:
    text = _security_text(value)
    if text is None:
        return "missing"
    if len(text) > SECURITY_CONTRACT_MAX_VALUE_LENGTH:
        return "too_long"
    lowered = text.lower()
    if "%2e" in lowered or "%2f" in lowered:
        return "path_traversal"
    parts = Path(text).parts
    if ".." in parts:
        return "path_traversal"
    if any(char in text for char in SECURITY_CONTRACT_SHELL_META - {"/"}):
        return "shell_metacharacter"
    if any(marker in lowered for marker in SECURITY_CONTRACT_HTML_MARKERS):
        return "ui_injection"
    if text != unicodedata.normalize("NFKC", text):
        return "unicode_normalization"
    if not text.isascii():
        return "non_ascii"
    return None

def _security_shell_arg_reason(value: object) -> str | None:
    reason = _security_reason(value, allow_slash=True)
    if reason is not None:
        return reason
    return None

def _security_api_reason(value: object) -> str | None:
    reason = _security_reason(value, allow_slash=True, allow_query=True)
    if reason is not None:
        return reason
    return None

def _security_ui_reason(value: object) -> str | None:
    reason = _security_reason(value, allow_slash=True, allow_query=True)
    if reason is not None:
        return reason
    return None

def _security_add_boundary_diagnostic(diagnostics: list[dict], *, boundary: str, code: str, value: object, reason: str) -> None:
    diagnostics.append({"code": code, "boundary": boundary, "reason": reason, "value": value})

def _security_command_parts(command: object) -> list[str]:
    if isinstance(command, list):
        return [str(part) for part in command]
    text = _security_text(command)
    return text.split() if text else []

def _security_is_destructive_git_command(parts: list[str]) -> bool:
    lowered = tuple(part.lower() for part in parts)
    return any(lowered[: len(pattern)] == pattern for pattern in SECURITY_CONTRACT_DESTRUCTIVE_GIT)

def _security_destructive_diagnostics(commands: object) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    items = commands if isinstance(commands, list) else []
    for item in items:
        command = item.get("command") if isinstance(item, dict) else item
        parts = _security_command_parts(command)
        if not _security_is_destructive_git_command(parts):
            continue
        dry_run_evidence = item.get("dry_run_evidence") if isinstance(item, dict) else None
        explicit_authorization = bool(item.get("explicit_authorization")) if isinstance(item, dict) else False
        if dry_run_evidence and explicit_authorization:
            continue
        diagnostics.append(
            {
                "code": "blocked_destructive",
                "command": parts,
                "target": item.get("target") if isinstance(item, dict) else None,
                "reason": "dry_run_evidence_required",
                "safer_action": "run_dry_run_and_revalidate_contract",
                "dry_run_required": True,
            }
        )
    return diagnostics

def resolve_security_diagnostic_contract_state(context: dict | None = None) -> dict[str, object]:
    payload = context if isinstance(context, dict) else {}
    diagnostics: list[dict[str, object]] = []
    legacy_diagnostics = _security_legacy_diagnostics(payload)
    mst_session_id = _security_text(payload.get("mst_session_id"))
    session_reason = _security_session_reason(mst_session_id)
    if session_reason is not None:
        _security_add_boundary_diagnostic(
            diagnostics,
            boundary="session_id",
            code="invalid_session_id",
            value=mst_session_id,
            reason=session_reason,
        )
    if session_reason is None and mst_session_id is not None:
        branch = _security_text(payload.get("session_branch"))
        branch_reason = _security_branch_reason(branch, mst_session_id)
        if branch_reason is not None:
            _security_add_boundary_diagnostic(
                diagnostics,
                boundary="branch",
                code="unsafe_branch",
                value=branch,
                reason=branch_reason,
            )
        worktree_path = _security_text(payload.get("session_worktree_path"))
        path_reason = _security_path_reason(worktree_path)
        if path_reason is not None:
            _security_add_boundary_diagnostic(
                diagnostics,
                boundary="path",
                code="unsafe_path",
                value=worktree_path,
                reason=path_reason,
            )
        shell_args = payload.get("shell_args") if isinstance(payload.get("shell_args"), list) else []
        for index, arg in enumerate(shell_args):
            reason = _security_shell_arg_reason(arg)
            if reason is not None:
                diagnostics.append({"code": "unsafe_shell_arg", "boundary": "shell", "index": index, "reason": reason, "value": arg})
        api_params = payload.get("api_params") if isinstance(payload.get("api_params"), dict) else {}
        for key, value in api_params.items():
            if key == "mst_session_id" and value != mst_session_id:
                reason = "canonical_identity_mismatch"
            else:
                reason = _security_api_reason(value)
            if reason is not None:
                diagnostics.append({"code": "unsafe_api_param", "boundary": "api", "field": key, "reason": reason, "value": value})
        ui_payload = payload.get("ui_payload") if isinstance(payload.get("ui_payload"), dict) else {}
        for key, value in ui_payload.items():
            reason = _security_ui_reason(value)
            if reason is not None:
                diagnostics.append({"code": "unsafe_ui_value", "boundary": "ui", "field": key, "reason": reason, "value": value})
    destructive_diagnostics = _security_destructive_diagnostics(payload.get("destructive_commands"))
    ok = not diagnostics and not destructive_diagnostics
    boundary_payload: dict[str, object] = {}
    if ok and mst_session_id is not None:
        boundary_payload = {
            "mst_session_id": mst_session_id,
            "session_branch": _security_text(payload.get("session_branch")),
            "session_worktree_path": _security_text(payload.get("session_worktree_path")),
            "shell_args": list(payload.get("shell_args") if isinstance(payload.get("shell_args"), list) else []),
            "api_params": dict(payload.get("api_params") if isinstance(payload.get("api_params"), dict) else {}),
            "ui_payload": dict(payload.get("ui_payload") if isinstance(payload.get("ui_payload"), dict) else {}),
        }
    classification = "security_contract_clear" if ok else "security_boundary_blocked"
    if destructive_diagnostics:
        classification = "blocked_destructive"
    return {
        "ok": ok,
        "classification": classification,
        "canonical_identity_source": "mst_session_id" if ok and mst_session_id else "blocked",
        "boundary_payload": boundary_payload,
        "diagnostics": diagnostics,
        "destructive_diagnostics": destructive_diagnostics,
        "legacy_diagnostics": legacy_diagnostics,
        "destructive_action_allowed": False,
    }

def resolve_session_merge_scope(
    project_root: Path,
    *,
    caller: str,
    requested_target: str | None = None,
    mst_session_id: str | None = None,
    evidence: dict | None = None,
) -> dict:
    caller_value = _string_or_none(caller)
    if not caller_value:
        raise ValueError("caller is required")
    requested_target_value = _normalize_merge_requested_target(requested_target)
    session_context, session_error = _resolve_merge_scope_session_context(
        Path(project_root).resolve(strict=False),
        caller=caller_value,
        requested_target=requested_target_value,
        mst_session_id=mst_session_id,
    )
    if session_error is not None:
        return session_error
    assert session_context is not None

    if caller_value in SESSION_MERGE_SCOPE_FORBIDDEN_CALLERS:
        return _merge_scope_payload(
            ok=False,
            caller=caller_value,
            requested_target=requested_target_value,
            merge_state="forbidden_caller",
            child_to_session=False,
            session_to_original=False,
            target_branch=None,
            session_branch=session_context["session_branch"],
            original_base_branch=session_context["original_base_branch"],
            original_base_sha=session_context["original_base_sha"],
            reason="forbidden_caller",
            action="resume_parent_session_workflow",
            evidence={"safer_action": "use_request_child_accept_or_session_level_accept"},
            forbidden_caller=True,
        )
    if caller_value in SESSION_MERGE_SCOPE_CHILD_CALLERS or (
        caller_value in SESSION_MERGE_SCOPE_CHILD_OPTIONAL_CALLERS
        and requested_target_value == "child_to_session"
    ):
        return _merge_scope_payload(
            ok=True,
            caller=caller_value,
            requested_target=requested_target_value,
            merge_state="authorized_child_merge",
            child_to_session=True,
            session_to_original=False,
            target_branch=session_context["session_branch"],
            session_branch=session_context["session_branch"],
            original_base_branch=session_context["original_base_branch"],
            original_base_sha=session_context["original_base_sha"],
            evidence={"merge_target": "parent_session_branch"},
        )
    if caller_value in SESSION_MERGE_SCOPE_FINAL_CALLERS:
        return _resolve_final_merge_scope(
            Path(project_root).resolve(strict=False),
            caller=caller_value,
            requested_target=requested_target_value,
            session_context=session_context,
            evidence=evidence,
        )
    return _merge_scope_payload(
        ok=False,
        caller=caller_value,
        requested_target=requested_target_value,
        merge_state="non_success_diagnostic",
        child_to_session=False,
        session_to_original=False,
        target_branch=None,
        session_branch=session_context["session_branch"],
        original_base_branch=session_context["original_base_branch"],
        original_base_sha=session_context["original_base_sha"],
        reason="unsupported_caller",
        action="inspect_merge_scope_truth_table",
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
