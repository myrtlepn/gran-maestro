from __future__ import annotations

import argparse
import contextlib
import copy
import ctypes
import errno
import glob
import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    DEFAULT_REFERENCE_CONFIG,
    DEFAULT_REFERENCE_KEYWORDS,
    TYPE_DIRS,
    _parse_utc_datetime,
    _plugin_root,
    deep_merge,
    get_counter_path,
    load_json,
    save_json,
)


# ==============================================================================
# Constants
# ==============================================================================

REQUIRED_REFERENCE_FIELDS = {
    "id", "topic", "url", "summary",
    "searched_at", "expires_at", "freshness", "content_path",
}

VALID_FRESHNESS_VALUES = {"fresh", "stale", "expired"}

_REF_DIR_PATTERN = re.compile(r"^REF-(\d+)$")
_STAGING_PATTERN = re.compile(r"^REF-(\d+)\.([0-9a-f]{32})$")
_BACKUP_PATTERN = re.compile(r"^REF-(\d+)\.([0-9a-f]{32})$")


# ==============================================================================
# Directory Helpers
# ==============================================================================

def references_dir() -> Path:
    return _common.BASE_DIR / "references"


def _normalize_reference_id(value: str) -> str:
    ref_id = (value or "").strip().upper()
    if not re.fullmatch(r"REF-\d+", ref_id):
        raise ValueError(f"Invalid reference id: {value}")
    return ref_id


def _reference_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "reference.json"


def _reference_content_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "content.md"


def _coerce_positive_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


# ==============================================================================
# Config Helpers (unchanged)
# ==============================================================================

def _load_reference_config():
    config = dict(DEFAULT_REFERENCE_CONFIG)
    config["keywords_whitelist"] = list(DEFAULT_REFERENCE_KEYWORDS)

    resolved = load_json(_common.BASE_DIR / "config.resolved.json")
    if not isinstance(resolved, dict):
        defaults = load_json(_plugin_root() / "templates" / "defaults" / "config.json") or {}
        overrides = load_json(_common.BASE_DIR / "config.json") or {}
        resolved = deep_merge(defaults, overrides)

    raw_reference = resolved.get("reference")
    if not isinstance(raw_reference, dict):
        return config

    config["cache_ttl_days"] = _coerce_positive_int(
        raw_reference.get("cache_ttl_days"),
        DEFAULT_REFERENCE_CONFIG["cache_ttl_days"],
    )
    config["cutoff_threshold_months"] = _coerce_positive_int(
        raw_reference.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )
    config["auto_search"] = bool(raw_reference.get("auto_search", DEFAULT_REFERENCE_CONFIG["auto_search"]))
    config["max_searches_per_step"] = _coerce_positive_int(
        raw_reference.get("max_searches_per_step"),
        DEFAULT_REFERENCE_CONFIG["max_searches_per_step"],
    )

    keywords = raw_reference.get("keywords_whitelist")
    if isinstance(keywords, list):
        normalized = []
        for keyword in keywords:
            text = str(keyword).strip()
            if text:
                normalized.append(text)
        if normalized:
            config["keywords_whitelist"] = normalized

    return config


def _compute_reference_expires_at(searched_at, cache_ttl_days: int):
    searched_dt = _parse_utc_datetime(searched_at)
    if searched_dt is None:
        return None
    return (searched_dt + timedelta(days=cache_ttl_days)).isoformat()


def _check_reference_freshness(reference_data, config=None, now=None):
    if not isinstance(reference_data, dict):
        return "expired"

    searched_dt = _parse_utc_datetime(reference_data.get("searched_at"))
    if searched_dt is None:
        return "expired"

    if config is None:
        config = _load_reference_config()
    ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])
    cutoff_months = _coerce_positive_int(
        config.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )

    now_dt = now or datetime.now(timezone.utc)
    freshness = "fresh"
    if searched_dt + timedelta(days=ttl_days) < now_dt:
        freshness = "stale"

    cutoff_delta = timedelta(days=cutoff_months * 30)
    if (now_dt - searched_dt) > cutoff_delta:
        freshness = "expired"
    return freshness


def _detect_reference_keywords(text: str, keywords_whitelist=None):
    if not isinstance(text, str) or not text.strip():
        return []

    keywords = keywords_whitelist
    if keywords is None:
        keywords = _load_reference_config().get("keywords_whitelist", [])
    if not isinstance(keywords, list):
        return []

    lowered = text.lower()
    matches = []
    for keyword in keywords:
        candidate = str(keyword).strip()
        if not candidate:
            continue
        if candidate.lower() in lowered:
            matches.append(candidate)
    return sorted(set(matches))


def _build_reference_prompt_block(reference_entries, model_cutoff_date: str, now=None):
    now_dt = now or datetime.now(timezone.utc)
    lines = [
        "[REFERENCE_CONTEXT]",
        f"current_date: {now_dt.date().isoformat()}",
        f"model_cutoff: {model_cutoff_date}",
    ]
    if not isinstance(reference_entries, list) or not reference_entries:
        lines.append("references: none")
    else:
        lines.append("references:")
        for entry in reference_entries:
            if not isinstance(entry, dict):
                continue
            lines.append(
                "- {id} ({freshness}) {topic} | {url}".format(
                    id=entry.get("id", "-"),
                    freshness=entry.get("freshness", "unknown"),
                    topic=entry.get("topic", "-"),
                    url=entry.get("url", "-"),
                )
            )
    lines.append("[/REFERENCE_CONTEXT]")
    return "\n".join(lines)


# ==============================================================================
# Diagnostic Error Helpers
# ==============================================================================

class ReferenceError(Exception):
    """Structured reference error with diagnostic code."""
    def __init__(self, code: str, message: str, outcome: str = "confirmed_failure"):
        self.code = code
        self.message = message
        self.outcome = outcome
        super().__init__(f"[{code}] outcome={outcome}: {message}")


def _emit_error(code: str, message: str, outcome: str = "confirmed_failure") -> int:
    print(f"Error [{code}] outcome={outcome}: {message}", file=sys.stderr)
    return 1


def _emit_warning(code: str, ref_id: str, message: str) -> None:
    print(f"Warning [{code}]: {ref_id} {message}", file=sys.stderr)


# ==============================================================================
# Failpoint Infrastructure
# ==============================================================================

def _check_failpoint(name: str, *, is_update: bool = False) -> None:
    """Check and fire a one-shot failpoint if active.

    Only active when MST_TEST_MODE=1.
    Reads MST_REFERENCE_FAILPOINT, MST_REFERENCE_FAIL_ACTION.
    Actions: sigkill, barrier.
    One-shot: clears env after firing.
    """
    if os.environ.get("MST_TEST_MODE") != "1":
        return

    active_failpoint = os.environ.get("MST_REFERENCE_FAILPOINT", "")
    if active_failpoint != name:
        return

    action = os.environ.get("MST_REFERENCE_FAIL_ACTION", "sigkill")

    # One-shot: clear so it doesn't fire again
    os.environ.pop("MST_REFERENCE_FAILPOINT", None)
    os.environ.pop("MST_REFERENCE_FAIL_ACTION", None)

    if action == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    elif action == "barrier":
        barrier_dir = os.environ.get("MST_TEST_BARRIER_DIR", "")
        if barrier_dir:
            barrier_path = Path(barrier_dir)
            # Signal ready
            (barrier_path / "ready").touch()
            # Wait for release
            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                if (barrier_path / "release").exists():
                    return
                time.sleep(0.02)
            raise TimeoutError(f"Barrier release not received at {barrier_dir}")


# ==============================================================================
# Secure Filesystem Helpers
# ==============================================================================

def _fsync_file(fd: int) -> None:
    """Flush file data to disk."""
    os.fsync(fd)


def _fsync_directory(dir_path: Path) -> None:
    """POSIX directory fsync for metadata durability."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(dir_path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _is_safe_path(path: Path) -> bool:
    """Check that path is not a symlink."""
    try:
        return not path.is_symlink()
    except OSError:
        return False


def _assert_no_symlink(path: Path, label: str = "path") -> None:
    """Raise REFERENCE_PATH_UNSAFE if path is a symlink."""
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise ReferenceError(
                "REFERENCE_PATH_UNSAFE",
                f"{label} is a symlink: {path}",
            )


def _secure_mkdir_no_overwrite(path: Path, label: str = "directory") -> None:
    """Create directory atomically with no-overwrite guarantee.

    Raises REFERENCE_COLLISION if already exists.
    Raises REFERENCE_PATH_UNSAFE if symlink.
    """
    if os.name == "nt":
        raise ReferenceError(
            "REFERENCE_PLATFORM_UNSUPPORTED",
            "safe no-reparse directory publication is unavailable on this Windows runtime",
        )
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(str(path.parent), parent_flags)
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PATH_UNSAFE",
            f"cannot open secure parent for {label}: {exc}",
        )
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        try:
            existing = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ReferenceError(
                "REFERENCE_PATH_UNSAFE",
                f"cannot inspect colliding {label}: {exc}",
            )
        if stat.S_ISLNK(existing.st_mode):
            raise ReferenceError(
                "REFERENCE_PATH_UNSAFE",
                f"{label} target is a symlink: {path}",
            )
        raise ReferenceError(
            "REFERENCE_COLLISION",
            f"{label} already exists: {path}",
        )
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"failed to create {label}: {exc}",
        )
    finally:
        os.close(parent_fd)


def _open_directory_no_follow(path: Path, label: str) -> int:
    if os.name == "nt":
        raise ReferenceError(
            "REFERENCE_PLATFORM_UNSUPPORTED",
            "safe no-reparse directory handles are unavailable on this Windows runtime",
        )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise ReferenceError("REFERENCE_PATH_UNSAFE", f"{label} is not a directory")
        return fd
    except ReferenceError:
        raise
    except OSError as exc:
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"cannot open {label} safely: {exc}")


def _copy_file_to_dir_secure(source: Path, directory_fd: int, name: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        output_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError:
        raise ReferenceError("REFERENCE_COLLISION", f"publish target already exists: {name}")
    except OSError as exc:
        raise ReferenceError("REFERENCE_PUBLISH_FAILED", f"cannot create publish target {name}: {exc}")
    try:
        with source.open("rb") as input_file:
            while True:
                chunk = input_file.read(1024 * 1024)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    written = os.write(output_fd, view)
                    view = view[written:]
        _fsync_file(output_fd)
    finally:
        os.close(output_fd)


def _ensure_hidden_transaction_root(refs_root: Path, name: str) -> Path:
    root = refs_root / name
    if root.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"{name} root is a symlink: {root}")
    if root.exists():
        if not root.is_dir():
            raise ReferenceError("REFERENCE_PATH_UNSAFE", f"{name} root is not a directory: {root}")
        return root
    _secure_mkdir_no_overwrite(root, f"{name} root")
    _fsync_directory(refs_root)
    return root


def _write_file_atomic(path: Path, content: str | bytes) -> None:
    """Write file content with flush+fsync."""
    is_bytes = isinstance(content, bytes)
    mode = "wb" if is_bytes else "w"
    kwargs = {} if is_bytes else {"encoding": "utf-8"}

    with open(path, mode, **kwargs) as f:
        f.write(content)
        f.flush()
        _fsync_file(f.fileno())


# ==============================================================================
# Lock Management
# ==============================================================================

def _open_ref_lock(lock_base: Optional[Path] = None):
    """Open the shared ref namespace lock (same identity as counter next --type ref)."""
    from scripts.mst_cmds import session as session_mod
    return session_mod.open_root_type_bootstrap_lock(lock_base or _common.BASE_DIR, "ref")


def _acquire_ref_lock(lock_handle, timeout_sec: float = 30.0):
    """Acquire exclusive lock on the ref namespace."""
    try:
        _common._lock_exclusive_with_timeout(lock_handle, timeout_sec=timeout_sec, poll_interval=0.01)
    except TimeoutError:
        raise ReferenceError(
            "REFERENCE_LOCK_TIMEOUT",
            f"could not acquire reference namespace lock within {timeout_sec}s",
        )


def _release_ref_lock(lock_handle):
    """Release the ref namespace lock."""
    try:
        _common._unlock(lock_handle)
    except Exception:
        pass


@contextlib.contextmanager
def _locked_ref_namespace(lock_base: Optional[Path] = None) -> Iterator[None]:
    """Serialize every reference reader and writer on the ref root-type lock."""
    with _open_ref_lock(lock_base) as lock_handle:
        _acquire_ref_lock(lock_handle)
        try:
            yield
        finally:
            _release_ref_lock(lock_handle)


# ==============================================================================
# Counter: Durable Forward-Only Reservation
# ==============================================================================

def _scan_high_water_evidence(refs_root: Path) -> int:
    """Scan direct non-symlink children for highest REF number.

    Scans: REF-NNN dirs, .staging/REF-NNN.*, .backup/REF-NNN.*
    No recursion. Symlinks are skipped (high-water only).
    """
    high_water = 0

    if refs_root.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"references root is a symlink: {refs_root}")
    if not refs_root.exists():
        return high_water
    if not refs_root.is_dir():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"references root is not a directory: {refs_root}")

    # Scan direct REF-NNN directories
    try:
        for entry in os.scandir(str(refs_root)):
            m = _REF_DIR_PATTERN.match(entry.name)
            if not m:
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                raise ReferenceError("REFERENCE_PATH_UNSAFE", f"unsafe REF high-water entry: {entry.name}")
            high_water = max(high_water, int(m.group(1)))
    except ReferenceError:
        raise
    except OSError as exc:
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"cannot scan reference high-water evidence: {exc}")

    # Scan .staging/ subdirectories
    staging_dir = refs_root / ".staging"
    if staging_dir.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"staging root is a symlink: {staging_dir}")
    if staging_dir.exists() and not staging_dir.is_dir():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"staging root is not a directory: {staging_dir}")
    if staging_dir.is_dir():
        try:
            for entry in os.scandir(str(staging_dir)):
                m = _STAGING_PATTERN.match(entry.name)
                if not m:
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise ReferenceError("REFERENCE_PATH_UNSAFE", f"unsafe staging high-water entry: {entry.name}")
                high_water = max(high_water, int(m.group(1)))
        except ReferenceError:
            raise
        except OSError as exc:
            raise ReferenceError("REFERENCE_PATH_UNSAFE", f"cannot scan staging high-water evidence: {exc}")

    # Scan .backup/ subdirectories
    backup_dir = refs_root / ".backup"
    if backup_dir.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"backup root is a symlink: {backup_dir}")
    if backup_dir.exists() and not backup_dir.is_dir():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"backup root is not a directory: {backup_dir}")
    if backup_dir.is_dir():
        try:
            for entry in os.scandir(str(backup_dir)):
                m = _BACKUP_PATTERN.match(entry.name)
                if not m:
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise ReferenceError("REFERENCE_PATH_UNSAFE", f"unsafe backup high-water entry: {entry.name}")
                high_water = max(high_water, int(m.group(1)))
        except ReferenceError:
            raise
        except OSError as exc:
            raise ReferenceError("REFERENCE_PATH_UNSAFE", f"cannot scan backup high-water evidence: {exc}")

    return high_water


def _reserve_counter_durable(refs_root: Path) -> int:
    """Reserve next counter ID with durable persistence.

    Uses temp file → fsync → os.replace → parent fsync.
    Returns the reserved numeric ID.
    Fail-closed on malformed/non-integer/unreadable counter.
    """
    counter_path = refs_root / "counter.json"
    if os.name == "nt":
        raise ReferenceError(
            "REFERENCE_PLATFORM_UNSUPPORTED",
            "safe no-reparse counter persistence is unavailable on this Windows runtime",
        )
    if refs_root.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"references root is a symlink: {refs_root}")
    refs_root.mkdir(parents=True, exist_ok=True)
    if refs_root.is_symlink() or not refs_root.is_dir():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"unsafe references root: {refs_root}")

    # Read current counter
    last_id = 0
    if counter_path.is_symlink():
        raise ReferenceError(
            "REFERENCE_PATH_UNSAFE",
            f"counter.json is a symlink: {counter_path}",
        )
    if counter_path.exists():
        try:
            if not stat.S_ISREG(os.lstat(str(counter_path)).st_mode):
                raise ReferenceError(
                    "REFERENCE_COUNTER_CORRUPT",
                    f"counter.json is not a regular file: {counter_path}",
                )
        except ReferenceError:
            raise
        except OSError as exc:
            raise ReferenceError("REFERENCE_COUNTER_CORRUPT", f"cannot inspect counter.json: {exc}")
        try:
            raw = counter_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReferenceError(
                "REFERENCE_COUNTER_CORRUPT",
                f"counter.json unreadable: {exc}",
            )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReferenceError(
                "REFERENCE_COUNTER_CORRUPT",
                f"counter.json malformed JSON: {exc}",
            )
        if not isinstance(data, dict):
            raise ReferenceError(
                "REFERENCE_COUNTER_CORRUPT",
                f"counter.json is not a JSON object",
            )
        raw_last_id = data.get("last_id", 0)
        if type(raw_last_id) is not int or raw_last_id < 0:
            raise ReferenceError(
                "REFERENCE_COUNTER_CORRUPT",
                f"counter.json last_id is not a non-negative integer: {raw_last_id!r}",
            )
        last_id = raw_last_id

    # Scan filesystem for high-water evidence
    disk_max = _scan_high_water_evidence(refs_root)

    # Forward-only: take max of counter and disk evidence
    next_id = max(last_id, disk_max) + 1

    # Durable write: temp → fsync → replace → parent fsync
    new_data = json.dumps({"last_id": next_id}, ensure_ascii=False, indent=2)
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=".counter.", suffix=".tmp", dir=str(refs_root)
        )
        tmp_path = Path(tmp_path_str)
        pending = memoryview(new_data.encode("utf-8"))
        while pending:
            written = os.write(tmp_fd, pending)
            if written <= 0:
                raise OSError("counter temp write made no progress")
            pending = pending[written:]
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None

        _check_failpoint("counter_after_temp_fsync")

        os.replace(str(tmp_path), str(counter_path))
        tmp_path = None

        _check_failpoint("counter_after_replace")

        _fsync_directory(refs_root)

        _check_failpoint("counter_after_parent_sync")
    except ReferenceError:
        raise
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"counter durable write failed: {exc}",
        )
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return next_id


def reserve_reference_id_for_counter(directory: Optional[str] = None) -> str:
    """Canonical raw `counter next --type ref` reservation path."""
    refs_root = Path(directory) if directory else references_dir()
    lock_base = Path(directory) if directory else _common.BASE_DIR
    with _locked_ref_namespace(lock_base):
        number = _reserve_counter_durable(refs_root)
    return f"REF-{number:03d}"


# ==============================================================================
# Transaction Manifest
# ==============================================================================

def _create_transaction_manifest(
    txid: str,
    ref_id: str,
    operation: str,
    state: str,
    ref_json_bytes: bytes,
    content_bytes: bytes,
) -> dict:
    hasher = hashlib.sha256()
    hasher.update(ref_json_bytes)
    hasher.update(content_bytes)

    return {
        "schema_version": 1,
        "transaction_id": txid,
        "reference_id": ref_id,
        "operation": operation,
        "state": state,
        "payload_sha256": hasher.hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ==============================================================================
# Reference Schema Validation
# ==============================================================================

def _validate_reference_schema(data: dict, expected_ref_id: str) -> Optional[str]:
    """Validate reference.json schema. Returns error message or None."""
    if not isinstance(data, dict):
        return "reference.json is not a JSON object"

    missing = REQUIRED_REFERENCE_FIELDS - set(data.keys())
    if missing:
        return f"missing required fields: {sorted(missing)}"

    for field_name in sorted(REQUIRED_REFERENCE_FIELDS):
        if not isinstance(data.get(field_name), str):
            return f"required field {field_name!r} must be a string"

    actual_id = data.get("id", "")
    if actual_id != expected_ref_id:
        return f"ID mismatch: data has {actual_id!r}, directory is {expected_ref_id}"

    freshness = data.get("freshness", "")
    if freshness not in VALID_FRESHNESS_VALUES:
        return f"invalid freshness value: {freshness!r}"

    expected_content_path = str(
        Path(".gran-maestro") / "references" / expected_ref_id / "content.md"
    )
    if data.get("content_path") != expected_content_path:
        return (
            f"content_path mismatch: expected {expected_content_path!r}, "
            f"got {data.get('content_path')!r}"
        )

    return None


def _diagnose_reference(refs_root: Path, ref_id: str) -> Tuple[str, Optional[dict], Optional[str]]:
    """Diagnose a single reference directory.

    Returns: (status_code, data_or_none, error_message_or_none)
    status_code: "valid" | diagnostic code string
    """
    ref_dir = refs_root / ref_id

    # Check symlink on directory itself
    if ref_dir.is_symlink():
        return "REFERENCE_PATH_UNSAFE", None, f"{ref_id} directory is a symlink"

    if not ref_dir.exists():
        return "REFERENCE_NOT_FOUND", None, f"{ref_id} not found"

    if not ref_dir.is_dir():
        return "REFERENCE_NOT_FOUND", None, f"{ref_id} is not a directory"

    json_path = ref_dir / "reference.json"
    content_path = ref_dir / "content.md"

    if json_path.is_symlink() or content_path.is_symlink():
        return "REFERENCE_PATH_UNSAFE", None, f"{ref_id} contains a symlinked required file"

    # Check for incomplete pair
    if not json_path.exists() and not content_path.exists():
        return "REFERENCE_INCOMPLETE", None, f"{ref_id} directory exists but has no files"

    if not json_path.exists():
        return "REFERENCE_INCOMPLETE", None, f"{ref_id} missing reference.json"

    if not json_path.is_file():
        return "REFERENCE_INCOMPLETE", None, f"{ref_id} reference.json is not a regular file"

    # Try to read
    try:
        raw = json_path.read_text(encoding="utf-8")
    except (OSError, PermissionError) as exc:
        return "REFERENCE_UNREADABLE", None, f"{ref_id} reference.json unreadable: {exc}"

    # Try to parse
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return "REFERENCE_CORRUPT", None, f"{ref_id} reference.json malformed JSON: {exc}"

    if not isinstance(data, dict):
        return "REFERENCE_CORRUPT", None, f"{ref_id} reference.json is not a JSON object"

    # Schema validation
    schema_err = _validate_reference_schema(data, ref_id)
    if schema_err:
        return "REFERENCE_SCHEMA_INVALID", data, f"{ref_id} {schema_err}"

    # Content.md check
    if not content_path.exists():
        return "REFERENCE_INCOMPLETE", data, f"{ref_id} missing content.md"

    if not content_path.is_file():
        return "REFERENCE_INCOMPLETE", data, f"{ref_id} content.md is not a regular file"

    return "valid", data, None


# ==============================================================================
# Enrichment (apply config-based computed fields)
# ==============================================================================

def _enrich_reference_data(data: dict, ref_id: str, config: Optional[dict] = None) -> dict:
    """Apply computed fields (freshness, expires_at, content_path) to reference data."""
    if config is None:
        config = _load_reference_config()

    cache_ttl_days = _coerce_positive_int(
        config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"]
    )

    enriched = dict(data)
    enriched["id"] = ref_id
    enriched["topic"] = str(enriched.get("topic", ""))
    enriched["url"] = str(enriched.get("url", ""))
    enriched["summary"] = str(enriched.get("summary", ""))
    enriched["searched_at"] = str(enriched.get("searched_at", ""))
    expires_at = _compute_reference_expires_at(enriched.get("searched_at"), cache_ttl_days)
    enriched["expires_at"] = expires_at or str(enriched.get("expires_at", ""))
    enriched["freshness"] = _check_reference_freshness(enriched, config=config)
    enriched["content_path"] = str(
        Path(".gran-maestro") / "references" / ref_id / "content.md"
    )
    return enriched


# ==============================================================================
# Strict Reference Reader (used by get, update, agile linker)
# ==============================================================================

def _strict_read_reference(ref_id: str) -> Tuple[dict, Optional[str]]:
    """Read and validate a reference with full diagnostic.

    Returns (enriched_data, content_text).
    Raises ReferenceError with proper diagnostic code on any issue.
    """
    normalized_id = _normalize_reference_id(ref_id)
    refs_root = references_dir()

    status, data, err_msg = _diagnose_reference(refs_root, normalized_id)

    if status != "valid":
        raise ReferenceError(status, err_msg or f"{normalized_id} {status}")

    config = _load_reference_config()
    enriched = _enrich_reference_data(data, normalized_id, config)

    content_path = _reference_content_path(normalized_id)
    try:
        content_text = content_path.read_text(encoding="utf-8")
        enriched["content"] = content_text if content_text else None
    except (OSError, UnicodeDecodeError) as exc:
        raise ReferenceError("REFERENCE_UNREADABLE", f"{normalized_id} content.md unreadable: {exc}")

    return enriched, content_text


def read_reference_strict(ref_id: str) -> Tuple[dict, Optional[str]]:
    """Public strict snapshot reader used by non-reference command modules."""
    with _locked_ref_namespace():
        return _strict_read_reference(ref_id)


# ==============================================================================
# Legacy-Compatible Load/Save (for backward compat)
# ==============================================================================

def _load_reference(ref_id: str):
    """Legacy-compatible load. Returns (data, ref_path).

    Now uses strict reader internally.
    """
    normalized_id = _normalize_reference_id(ref_id)
    data, _ = _strict_read_reference(normalized_id)
    return data, _reference_path(normalized_id)


# ==============================================================================
# Staging Helpers
# ==============================================================================

def _create_staging_pair(
    refs_root: Path,
    ref_id: str,
    txid: str,
    operation: str,
    payload: dict,
    content_text: str,
) -> Path:
    """Create staging directory with transaction.json, reference.json, content.md.

    Returns the staging directory path.
    """
    staging_root = _ensure_hidden_transaction_root(refs_root, ".staging")
    staging_dir = staging_root / f"{ref_id}.{txid}"

    try:
        staging_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise ReferenceError(
            "REFERENCE_COLLISION",
            f"staging directory already exists: {staging_dir.name}",
        )

    _check_failpoint("after_staging_create")

    ref_json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    content_bytes = content_text.encode("utf-8")

    # Write reference.json
    ref_json_path = staging_dir / "reference.json"
    _write_file_atomic(ref_json_path, ref_json_bytes)

    _check_failpoint("after_metadata_fsync")

    # Write content.md
    content_md_path = staging_dir / "content.md"
    _write_file_atomic(content_md_path, content_bytes)

    _check_failpoint("after_content_fsync")

    # Write transaction.json
    manifest = _create_transaction_manifest(
        txid, ref_id, operation, "staged", ref_json_bytes, content_bytes
    )
    tx_json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    _write_file_atomic(staging_dir / "transaction.json", tx_json_bytes)

    # fsync staging directory
    _fsync_directory(staging_dir)

    _check_failpoint("after_staging_fsync")

    if not _transaction_directory_is_valid(staging_dir, ref_id, operation, "staged"):
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"staging pair failed read-back validation: {staging_dir.name}",
        )

    return staging_dir


def _publish_from_staging(
    refs_root: Path,
    ref_id: str,
    staging_dir: Path,
) -> None:
    """Publish staging pair to final directory.

    Atomic no-overwrite mkdir, content-first, metadata-last commit.
    """
    final_dir = refs_root / ref_id

    _check_failpoint("before_publish")

    # Atomic no-overwrite reservation
    _assert_no_symlink(refs_root, "references root")

    # Ensure parent (refs_root) exists and is safe
    if refs_root.is_symlink():
        raise ReferenceError(
            "REFERENCE_PATH_UNSAFE",
            f"references root is a symlink: {refs_root}",
        )

    _secure_mkdir_no_overwrite(final_dir, f"final directory {ref_id}")

    _check_failpoint("after_final_reserve")

    final_fd = _open_directory_no_follow(final_dir, f"final directory {ref_id}")
    try:
        # Content first
        src_content = staging_dir / "content.md"
        _copy_file_to_dir_secure(src_content, final_fd, "content.md")

        _check_failpoint("after_final_content")

        # Metadata last (commit marker)
        src_json = staging_dir / "reference.json"
        _copy_file_to_dir_secure(src_json, final_fd, "reference.json")
        _fsync_file(final_fd)

    except ReferenceError:
        raise
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"failed to publish {ref_id}: {exc}",
        )
    finally:
        os.close(final_fd)

    # Clean staging on success (before after_publish failpoint)
    try:
        shutil.rmtree(str(staging_dir), ignore_errors=True)
    except Exception:
        pass

    _check_failpoint("after_publish")


# ==============================================================================
# Backup Helpers (for update)
# ==============================================================================

def _backup_final_dir(refs_root: Path, ref_id: str, txid: str) -> Path:
    """Move existing final directory to .backup/REF-NNN.<txid>/"""
    backup_root = _ensure_hidden_transaction_root(refs_root, ".backup")
    backup_dir = backup_root / f"{ref_id}.{txid}"

    final_dir = refs_root / ref_id
    if not final_dir.exists():
        raise ReferenceError(
            "REFERENCE_NOT_FOUND",
            f"cannot backup {ref_id}: final directory does not exist",
        )

    if backup_dir.exists() or backup_dir.is_symlink():
        raise ReferenceError("REFERENCE_COLLISION", f"backup target already exists: {backup_dir}")

    # The authority transition is one same-filesystem directory rename.
    try:
        os.rename(str(final_dir), str(backup_dir))
        _fsync_directory(backup_root)
        _fsync_directory(refs_root)
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"failed to move {ref_id} to backup atomically: {exc}",
        )

    # Write backup transaction.json
    ref_json_path = backup_dir / "reference.json"
    content_path = backup_dir / "content.md"

    ref_json_bytes = ref_json_path.read_bytes() if ref_json_path.exists() else b"{}"
    content_bytes = content_path.read_bytes() if content_path.exists() else b""

    manifest = _create_transaction_manifest(
        txid, ref_id, "update", "backup", ref_json_bytes, content_bytes
    )
    _write_file_atomic(
        backup_dir / "transaction.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    _fsync_directory(backup_dir)

    return backup_dir


def _find_valid_backups(refs_root: Path, ref_id: str) -> List[Path]:
    """Find all valid backup directories for a reference ID."""
    backup_root = refs_root / ".backup"
    if not backup_root.is_dir():
        return []

    valid_backups = []
    try:
        for entry in os.scandir(str(backup_root)):
            if entry.is_symlink():
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            m = _BACKUP_PATTERN.match(entry.name)
            if not m:
                continue
            if f"REF-{int(m.group(1)):03d}" != ref_id and entry.name.split(".")[0] != ref_id:
                prefix_id = entry.name.split(".")[0]
                if prefix_id != ref_id:
                    continue

            backup_path = Path(entry.path)
            if _transaction_directory_is_valid(backup_path, ref_id, "update", "backup"):
                valid_backups.append(backup_path)
    except OSError:
        pass

    return sorted(valid_backups, key=lambda p: p.name)


def _transaction_directory_is_valid(
    transaction_dir: Path,
    ref_id: str,
    operation: str,
    state_value: str,
) -> bool:
    if transaction_dir.is_symlink() or not transaction_dir.is_dir():
        return False
    manifest_path = transaction_dir / "transaction.json"
    reference_path = transaction_dir / "reference.json"
    content_path = transaction_dir / "content.md"
    for path in (manifest_path, reference_path, content_path):
        if path.is_symlink() or not path.is_file():
            return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reference_bytes = reference_path.read_bytes()
        content_bytes = content_path.read_bytes()
        reference_payload = json.loads(reference_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    tx_match = _BACKUP_PATTERN.match(transaction_dir.name) or _STAGING_PATTERN.match(transaction_dir.name)
    if not tx_match:
        return False
    expected_hash = hashlib.sha256(reference_bytes + content_bytes).hexdigest()
    required_manifest = {
        "schema_version": 1,
        "transaction_id": tx_match.group(2),
        "reference_id": ref_id,
        "operation": operation,
        "state": state_value,
        "payload_sha256": expected_hash,
    }
    if any(manifest.get(key) != value for key, value in required_manifest.items()):
        return False
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"]:
        return False
    return _validate_reference_schema(reference_payload, ref_id) is None


def _try_restore_from_backup(refs_root: Path, ref_id: str) -> Optional[dict]:
    """Update writer: try to restore from exactly-one valid backup.

    Recovery precedence (from spec AC-010):
    1. final valid -> no restoration needed
    2. final missing + exactly one valid backup -> restore
    3. final missing + exactly one valid backup + staging -> restore backup, staging stays stale
    4. invalid final + valid backup -> no auto overwrite, fail closed
    5. multiple valid backups -> REFERENCE_OUTCOME_UNKNOWN
    """
    final_dir = refs_root / ref_id
    final_status, final_data, final_err = _diagnose_reference(refs_root, ref_id)

    if final_dir.is_symlink():
        raise ReferenceError("REFERENCE_PATH_UNSAFE", f"{ref_id} final target is a symlink")

    if final_status == "valid":
        return final_data  # Case 1

    valid_backups = _find_valid_backups(refs_root, ref_id)

    if final_dir.exists() and final_status != "REFERENCE_NOT_FOUND":
        # Case 4: invalid final + valid backup
        if valid_backups:
            raise ReferenceError(
                final_status,
                f"{ref_id} final is invalid ({final_err}) and backup exists; "
                f"auto overwrite forbidden",
            )
        # Invalid final, no backup
        raise ReferenceError(
            final_status,
            final_err or f"{ref_id} is invalid",
        )

    # Final missing
    if not valid_backups:
        raise ReferenceError(
            "REFERENCE_NOT_FOUND",
            f"{ref_id} not found and no valid backup available",
        )

    if len(valid_backups) > 1:
        # Case 5
        raise ReferenceError(
            "REFERENCE_OUTCOME_UNKNOWN",
            f"{ref_id} has {len(valid_backups)} valid backups; "
            f"cannot determine authoritative version",
            outcome="unknown_outcome",
        )

    # Case 2/3: exactly one valid backup -> restore
    backup_dir = valid_backups[0]
    try:
        if final_dir.exists() or final_dir.is_symlink():
            raise ReferenceError(
                "REFERENCE_COLLISION",
                f"cannot restore {ref_id}; final target appeared concurrently",
            )
        os.rename(str(backup_dir), str(final_dir))
        # Remove transaction.json from restored final
        tx_json = final_dir / "transaction.json"
        if tx_json.exists():
            tx_json.unlink()
        _fsync_directory(final_dir)
        _fsync_directory(refs_root)
        _fsync_directory(refs_root / ".backup")
    except ReferenceError:
        raise
    except OSError as exc:
        raise ReferenceError(
            "REFERENCE_PUBLISH_FAILED",
            f"failed to restore {ref_id} from backup: {exc}",
        )

    # Read restored data
    try:
        raw = (final_dir / "reference.json").read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReferenceError(
            "REFERENCE_CORRUPT",
            f"restored {ref_id} but failed to read: {exc}",
        )


# ==============================================================================
# Inventory Helpers
# ==============================================================================

def _iter_reference_dirs(refs_root: Path) -> List[Tuple[str, int]]:
    """List all REF-NNN directories (one level, non-symlink, sorted by numeric ID)."""
    results = []
    if not refs_root.is_dir():
        return results

    try:
        for entry in os.scandir(str(refs_root)):
            m = _REF_DIR_PATTERN.match(entry.name)
            if m and (entry.is_symlink() or entry.is_dir(follow_symlinks=False)):
                results.append((entry.name, int(m.group(1))))
    except OSError:
        pass

    results.sort(key=lambda x: x[1])
    return results


def _iter_staging_dirs(refs_root: Path) -> List[Tuple[str, Path]]:
    """List all staging directories."""
    staging_root = refs_root / ".staging"
    results = []
    if not staging_root.is_dir():
        return results

    try:
        for entry in os.scandir(str(staging_root)):
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                results.append((entry.name, Path(entry.path)))
    except OSError:
        pass

    results.sort(key=lambda x: x[0])
    return results


def _iter_backup_dirs(refs_root: Path) -> List[Tuple[str, Path]]:
    """List all backup directories."""
    backup_root = refs_root / ".backup"
    results = []
    if not backup_root.is_dir():
        return results

    try:
        for entry in os.scandir(str(backup_root)):
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                results.append((entry.name, Path(entry.path)))
    except OSError:
        pass

    results.sort(key=lambda x: x[0])
    return results


# ==============================================================================
# Command: reference add
# ==============================================================================

def cmd_reference_add(args):
    refs_root = references_dir()
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(
        config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"]
    )
    txid = uuid.uuid4().hex

    try:
        with _open_ref_lock() as lock_handle:
            _acquire_ref_lock(lock_handle)
            try:
                # 1. Counter-first durable reservation
                next_id = _reserve_counter_durable(refs_root)
                ref_id = f"REF-{next_id:03d}"

                _check_failpoint("after_counter_reserve")

                # 2. Build reference payload
                searched_at = datetime.now(timezone.utc).isoformat()
                expires_at = _compute_reference_expires_at(searched_at, cache_ttl_days)

                payload = {
                    "id": ref_id,
                    "topic": str(args.topic),
                    "url": str(args.url),
                    "summary": str(args.summary),
                    "searched_at": searched_at,
                    "expires_at": expires_at or "",
                    "freshness": _check_reference_freshness(
                        {"searched_at": searched_at}, config=config
                    ),
                    "content_path": str(
                        Path(".gran-maestro") / "references" / ref_id / "content.md"
                    ),
                }

                content_text = str(args.content) if args.content is not None else ""

                # 3. Create staging pair
                staging_dir = _create_staging_pair(
                    refs_root, ref_id, txid, "add", payload, content_text
                )

                # 4. Publish from staging
                _publish_from_staging(refs_root, ref_id, staging_dir)

                _check_failpoint("before_success")

                # 5. Read back for output
                data, _ = _strict_read_reference(ref_id)

            finally:
                _release_ref_lock(lock_handle)

    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)
    except Exception as exc:
        return _emit_error("REFERENCE_PUBLISH_FAILED", str(exc))

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(ref_id)
    return 0


# ==============================================================================
# Command: reference get
# ==============================================================================

def cmd_reference_get(args):
    try:
        data, _ = read_reference_strict(args.reference_id)
    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)
    except ValueError as exc:
        return _emit_error("REFERENCE_NOT_FOUND", str(exc))

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(
            f"{data.get('id', '')} "
            f"[{data.get('freshness', 'unknown')}] "
            f"{data.get('topic', '')} - {data.get('url', '')}"
        )
    return 0


# ==============================================================================
# Command: reference list
# ==============================================================================

def _cmd_reference_list_unlocked(args):
    refs_root = references_dir()
    entries = []
    config = _load_reference_config()

    ref_dirs = _iter_reference_dirs(refs_root)

    for ref_name, _numeric_id in ref_dirs:
        status, data, err_msg = _diagnose_reference(refs_root, ref_name)

        if status != "valid":
            _emit_warning(status, ref_name, err_msg or "")
            continue

        enriched = _enrich_reference_data(data, ref_name, config)

        # Load content for JSON output
        content_path = refs_root / ref_name / "content.md"
        try:
            if content_path.exists():
                content = content_path.read_text(encoding="utf-8")
                enriched["content"] = content if content else None
            else:
                enriched["content"] = None
        except (OSError, UnicodeDecodeError):
            enriched["content"] = None

        entries.append(enriched)

    entries.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No references found.")
        return 0

    print(f"{'ID':<8} {'Freshness':<10} {'Topic':<32} {'URL'}")
    print("-" * 100)
    for entry in entries:
        topic = entry.get("topic", "")
        if len(topic) > 31:
            topic = topic[:28] + "..."
        print(
            f"{entry.get('id', ''):<8} "
            f"{entry.get('freshness', 'unknown'):<10} "
            f"{topic:<32} "
            f"{entry.get('url', '')}"
        )
    return 0


def cmd_reference_list(args):
    try:
        with _locked_ref_namespace():
            return _cmd_reference_list_unlocked(args)
    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)


# ==============================================================================
# Command: reference search
# ==============================================================================

def _cmd_reference_search_unlocked(args):
    keyword = (args.keyword or "").strip().lower()
    if not keyword:
        if args.json:
            print("[]")
        else:
            print("No matching references found.")
        return 0

    refs_root = references_dir()
    matches = []
    config = _load_reference_config()

    ref_dirs = _iter_reference_dirs(refs_root)

    for ref_name, _numeric_id in ref_dirs:
        status, data, err_msg = _diagnose_reference(refs_root, ref_name)

        if status != "valid":
            _emit_warning(status, ref_name, err_msg or "")
            continue

        topic = str(data.get("topic", ""))
        summary = str(data.get("summary", ""))
        if keyword not in topic.lower() and keyword not in summary.lower():
            continue

        enriched = _enrich_reference_data(data, ref_name, config)

        content_path = refs_root / ref_name / "content.md"
        try:
            if content_path.exists():
                content = content_path.read_text(encoding="utf-8")
                enriched["content"] = content if content else None
            else:
                enriched["content"] = None
        except (OSError, UnicodeDecodeError):
            enriched["content"] = None

        matches.append(enriched)

    matches.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if not matches:
        print("No matching references found.")
        return 0

    for item in matches:
        print(
            f"{item.get('id', '')} [{item.get('freshness', 'unknown')}] "
            f"{item.get('topic', '')} - {item.get('url', '')}"
        )
    return 0


def cmd_reference_search(args):
    try:
        with _locked_ref_namespace():
            return _cmd_reference_search_unlocked(args)
    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)


# ==============================================================================
# Command: reference update
# ==============================================================================

def cmd_reference_update(args):
    refs_root = references_dir()
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(
        config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"]
    )
    txid = uuid.uuid4().hex

    try:
        normalized_id = _normalize_reference_id(args.reference_id)
    except ValueError as exc:
        return _emit_error("REFERENCE_NOT_FOUND", str(exc))

    try:
        # Test-only snapshot barrier: pause before taking the writer lock so a
        # normal locked reader can deterministically observe the old commit.
        if (
            os.environ.get("MST_TEST_MODE") == "1"
            and os.environ.get("MST_REFERENCE_FAILPOINT") == "before_publish"
            and os.environ.get("MST_REFERENCE_FAIL_ACTION") == "barrier"
        ):
            _check_failpoint("before_publish", is_update=True)

        with _open_ref_lock() as lock_handle:
            _acquire_ref_lock(lock_handle)
            try:
                # Try restore from backup if needed (update writer authority)
                existing_data = _try_restore_from_backup(refs_root, normalized_id)

                # Read current committed content
                content_path = refs_root / normalized_id / "content.md"
                try:
                    existing_content = content_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    existing_content = ""

                # Apply requested changes
                changed = False
                data = dict(existing_data)

                if args.topic is not None:
                    data["topic"] = str(args.topic)
                    changed = True
                if args.url is not None:
                    data["url"] = str(args.url)
                    changed = True
                if args.summary is not None:
                    data["summary"] = str(args.summary)
                    changed = True
                if args.searched_at is not None:
                    data["searched_at"] = str(args.searched_at)
                    changed = True
                if args.content is not None:
                    changed = True

                if not changed:
                    return _emit_error(
                        "REFERENCE_PUBLISH_FAILED",
                        "no fields to update",
                    )

                data["updated_at"] = datetime.now(timezone.utc).isoformat()

                # Determine content
                if args.content is not None:
                    new_content = str(args.content)
                else:
                    new_content = existing_content

                # Enrich computed fields
                enriched = _enrich_reference_data(data, normalized_id, config)

                # 1. Backup existing final
                _backup_final_dir(refs_root, normalized_id, txid)

                _check_failpoint("update_after_backup")

                # 2. Create staging pair
                staging_dir = _create_staging_pair(
                    refs_root, normalized_id, txid, "update", enriched, new_content
                )

                # 3. Publish: atomic mkdir + content-first + metadata-last
                final_dir = refs_root / normalized_id
                _secure_mkdir_no_overwrite(final_dir, f"update final {normalized_id}")

                _check_failpoint("update_after_final_reserve")

                final_fd = _open_directory_no_follow(final_dir, f"update final {normalized_id}")
                try:
                    # Content first
                    src_content = staging_dir / "content.md"
                    _copy_file_to_dir_secure(src_content, final_fd, "content.md")

                    _check_failpoint("update_after_final_content")

                    # Metadata last (commit marker)
                    src_json = staging_dir / "reference.json"
                    _copy_file_to_dir_secure(src_json, final_fd, "reference.json")
                    _fsync_file(final_fd)
                except ReferenceError:
                    raise
                except OSError as exc:
                    raise ReferenceError(
                        "REFERENCE_PUBLISH_FAILED",
                        f"failed to publish update for {normalized_id}: {exc}",
                    )
                finally:
                    os.close(final_fd)

                # Clean staging on success
                try:
                    shutil.rmtree(str(staging_dir), ignore_errors=True)
                except Exception:
                    pass

                _check_failpoint("update_after_publish")

                # Read back
                result_data, _ = _strict_read_reference(normalized_id)

            finally:
                _release_ref_lock(lock_handle)

    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)
    except Exception as exc:
        return _emit_error("REFERENCE_PUBLISH_FAILED", str(exc))

    if args.json:
        print(json.dumps(result_data, ensure_ascii=False, indent=2))
    else:
        print(result_data.get("id"))
    return 0


# ==============================================================================
# Command: reference doctor
# ==============================================================================

def _cmd_reference_doctor_unlocked(args):
    refs_root = references_dir()

    try:
        if refs_root.is_symlink():
            return _emit_error(
                "REFERENCE_PATH_UNSAFE",
                "references root is a symlink",
            )
    except OSError as exc:
        return _emit_error("REFERENCE_PUBLISH_FAILED", f"cannot access references root: {exc}")

    # Build references inventory
    ref_entries = []
    valid_count = 0
    invalid_count = 0

    ref_dirs = _iter_reference_dirs(refs_root)
    for ref_name, _numeric_id in ref_dirs:
        status, data, err_msg = _diagnose_reference(refs_root, ref_name)

        entry = {
            "id": ref_name,
            "path": str(refs_root / ref_name),
            "status": "valid" if status == "valid" else "invalid",
            "diagnostics": [],
        }

        if status == "valid":
            valid_count += 1
        else:
            invalid_count += 1
            entry["diagnostics"].append({
                "code": status,
                "message": err_msg or "",
            })

        ref_entries.append(entry)

    # Build staging inventory
    staging_entries = []
    staging_dirs = _iter_staging_dirs(refs_root)
    for name, path in staging_dirs:
        staging_entry = {
            "name": name,
            "path": str(path),
            "status": "stale",
            "diagnostics": [{
                "code": "REFERENCE_STAGING_STALE",
                "message": f"staging directory {name}",
            }],
        }
        staging_entries.append(staging_entry)

    # Build backup inventory
    backup_entries = []
    backup_dirs = _iter_backup_dirs(refs_root)
    for name, path in backup_dirs:
        backup_entry = {
            "name": name,
            "path": str(path),
            "status": "stale",
            "diagnostics": [{
                "code": "REFERENCE_BACKUP_STALE",
                "message": f"backup directory {name}",
            }],
        }
        backup_entries.append(backup_entry)

    has_issues = (invalid_count > 0) or staging_entries or backup_entries

    # Check for temp file residues
    try:
        tmp_files = sorted(
            set(refs_root.glob(".*.tmp")) | set(refs_root.glob("*.tmp")),
            key=lambda path: str(path),
        )
        if tmp_files:
            has_issues = True
            for tmp_file in tmp_files:
                staging_entries.append(
                    {
                        "path": str(tmp_file),
                        "status": "stale",
                        "diagnostics": [{
                            "code": "REFERENCE_STAGING_STALE",
                            "message": "orphaned reference transaction temp file",
                        }],
                    }
                )
            staging_entries.sort(key=lambda item: item["path"])
    except OSError:
        pass

    result = {
        "schema_version": 1,
        "status": "issues" if has_issues else "ok",
        "references": ref_entries,
        "staging": staging_entries,
        "backups": backup_entries,
        "summary": {
            "valid": valid_count,
            "invalid": invalid_count,
            "staging": len(staging_entries),
            "backups": len(backup_entries),
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_reference_doctor(args):
    try:
        with _locked_ref_namespace():
            return _cmd_reference_doctor_unlocked(args)
    except ReferenceError as exc:
        return _emit_error(exc.code, exc.message, exc.outcome)


# ==============================================================================
# Register CLI
# ==============================================================================

def register(subparsers):
    sub = subparsers
    reference = sub.add_parser("reference")
    reference_sub = reference.add_subparsers(dest="subcommand")

    reference_add = reference_sub.add_parser("add")
    reference_add.add_argument("--topic", required=True)
    reference_add.add_argument("--url", required=True)
    reference_add.add_argument("--summary", required=True)
    reference_add.add_argument(
        "--content",
        help=(
            "content.md용 raw 발췌를 저장한다. 결론 요약만 입력하지 말고 원문 근거를 남긴다 "
            "(예: 인용, 표, 코드 스니펫 + 출처 URL/날짜)."
        ),
    )
    reference_add.add_argument("--json", action="store_true")

    reference_get = reference_sub.add_parser("get")
    reference_get.add_argument("reference_id")
    reference_get.add_argument("--json", action="store_true")

    reference_list = reference_sub.add_parser("list")
    reference_list.add_argument("--json", action="store_true")

    reference_search = reference_sub.add_parser("search")
    reference_search.add_argument("--keyword", required=True)
    reference_search.add_argument("--json", action="store_true")

    reference_update = reference_sub.add_parser("update")
    reference_update.add_argument("reference_id")
    reference_update.add_argument("--topic")
    reference_update.add_argument("--url")
    reference_update.add_argument("--summary")
    reference_update.add_argument("--searched-at")
    reference_update.add_argument(
        "--content",
        help=(
            "content.md를 raw 발췌 중심으로 갱신한다. 결론 요약만 입력하지 말고 원문 근거를 보강한다 "
            "(예: 인용, 표, 코드 스니펫 + 출처 URL/날짜)."
        ),
    )
    reference_update.add_argument("--json", action="store_true")

    reference_doctor = reference_sub.add_parser("doctor")
    reference_doctor.add_argument("--json", action="store_true")
