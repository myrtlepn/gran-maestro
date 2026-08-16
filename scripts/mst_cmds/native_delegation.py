from __future__ import annotations

"""Provider-neutral native-first delegation routing and lifecycle commands.

Python owns the route and evidence contract.  The host remains responsible for
calling its native agent tool after a ``native_candidate`` result.
"""

import argparse
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.mst_cmds import _common
from scripts.mst_cmds import orca_delegation as orca_delegation_mod
from scripts.mst_cmds import reasoning_effort as reasoning_effort_mod


NATIVE_PROVIDERS = {"codex", "claude"}
CAPABILITY_STATUSES = {"available", "unavailable", "unknown"}
NATIVE_FIRST_POLICY = "same-host-native-first"
REQUIRED_CAPABILITY = "native_agent_delegation"
ACTIVE_PHASES = {"planned", "spawn_requested", "spawned", "attached", "running", "reconciling", "cancel_requested"}
TERMINAL_PHASES = {"done", "failed", "terminated"}
TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "fallback_completed",
        "failed",
        "empty_result",
        "missing_result",
        "unchanged_result",
        "preexisting_result",
        "missing_output_baseline",
        "cancelled",
        "canceled",
        "blocked",
    }
)
READ_ONLY_SCOPES = {"analysis", "review", "exploration", "ideation", "discussion", "debug"}
EXTERNAL_CLAIM_TTL = timedelta(minutes=15)
NATIVE_SPAWN_CLAIM_TTL = timedelta(minutes=2)
EXTERNAL_CANCEL_GRACE_SECONDS = 2.0
EXTERNAL_CANCEL_POLL_SECONDS = 0.05
_EXTERNAL_EXEC_GATE_CODE = r"""
import json
import os

control_fd = int(os.environ.pop("MST_EXTERNAL_EXEC_GATE_FD"))
config_fd = int(os.environ.pop("MST_EXTERNAL_EXEC_CONFIG_FD"))
try:
    token = os.read(control_fd, 1)
finally:
    os.close(control_fd)
if token != b"1":
    os._exit(125)
os.lseek(config_fd, 0, os.SEEK_SET)
chunks = []
while True:
    chunk = os.read(config_fd, 65536)
    if not chunk:
        break
    chunks.append(chunk)
os.close(config_fd)
payload = json.loads(b"".join(chunks).decode("utf-8"))
argv = payload.get("argv")
provider_env = payload.get("env")
if not isinstance(argv, list) or not argv or not isinstance(provider_env, dict):
    os._exit(126)
argv = [str(item) for item in argv]
provider_env = {str(key): str(value) for key, value in provider_env.items()}
os.execvpe(argv[0], argv, provider_env)
"""


class LifecycleConflict(RuntimeError):
    """A lifecycle mutation would risk duplicate provider execution."""


class ExternalAdapterUnavailable(LifecycleConflict):
    """The selected fallback provider has no executable CLI adapter."""


def lifecycle_is_terminal(payload: dict[str, Any]) -> bool:
    phase = str(payload.get("phase") or "").strip().lower()
    status = str(payload.get("status") or "").strip().lower()
    return phase in TERMINAL_PHASES or status in TERMINAL_STATUSES


def _assert_nonterminal_lifecycle(payload: dict[str, Any], operation: str) -> None:
    if lifecycle_is_terminal(payload):
        raise LifecycleConflict(f"terminal lifecycle attempt cannot {operation}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _external_claim_expires_at(now: datetime | None = None) -> str:
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return (observed.astimezone(timezone.utc) + EXTERNAL_CLAIM_TTL).isoformat()


def _native_spawn_claim_expires_at(now: datetime | None = None) -> str:
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return (observed.astimezone(timezone.utc) + NATIVE_SPAWN_CLAIM_TTL).isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _native_spawn_claim_is_active(state: dict[str, Any]) -> bool:
    if str(state.get("spawn_claim_status") or "") != "claimed":
        return False
    expires_at = _parse_iso_datetime(state.get("spawn_claim_expires_at"))
    # Legacy/malformed claimed states are treated as active rather than
    # silently stealing ownership from a caller that may already have spawned.
    return expires_at is None or datetime.now(timezone.utc) < expires_at


def _remove_private_claim_token_handle(
    base_dir: Path | str,
    state: dict[str, Any],
) -> None:
    token_hash = str(state.get("spawn_claim_token_hash") or "")
    if not token_hash.startswith("sha256:"):
        return
    digest = token_hash.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return
    try:
        (_base_path(base_dir) / "run" / ".claim-secrets" / f"{digest}.token").unlink()
    except FileNotFoundError:
        pass


def _validate_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if not value or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None:
        raise LifecycleConflict("task_id must be a filesystem-safe identifier")
    return value


def _base_path(base_dir: Path | str) -> Path:
    return Path(base_dir).resolve(strict=False)


def native_state_path(base_dir: Path | str, task_id: str) -> Path:
    return _base_path(base_dir) / "run" / f"{_validate_task_id(task_id)}.json"


@contextmanager
def _task_lock(base_dir: Path | str, task_id: str):
    base = _base_path(base_dir)
    lock_dir = base / "run" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(_validate_task_id(task_id).encode("utf-8")).hexdigest()[:32]
    with (lock_dir / f"{lock_name}.lock").open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _bridge_lock(base_dir: Path | str, task_id: str):
    base = _base_path(base_dir)
    lock_dir = base / "run" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_name = hashlib.sha256(_validate_task_id(task_id).encode("utf-8")).hexdigest()[:32]
    with (lock_dir / f"{lock_name}.bridge.lock").open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _worktree_lease_lock(base_dir: Path | str):
    lock_dir = _base_path(base_dir) / "run" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / "worktree-leases.lock").open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_state(base_dir: Path | str, task_id: str) -> dict[str, Any] | None:
    path = native_state_path(base_dir, task_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleConflict(f"invalid native lifecycle state: {exc}") from exc
    if not isinstance(payload, dict):
        raise LifecycleConflict("invalid native lifecycle state payload")
    return payload


def _atomic_save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_private_bytes(path: Path, content: bytes) -> dict[str, Any]:
    """Write an immutable private artifact without following symlinks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp, flags, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o400)
        os.replace(temp, path)
    except OSError as exc:
        raise LifecycleConflict(f"cannot persist private lifecycle artifact: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    evidence = _file_evidence(path)
    if not evidence or not evidence.get("exists"):
        raise LifecycleConflict("private lifecycle artifact evidence is missing")
    return evidence


def _truncate_external_output_for_claim(path: Path) -> dict[str, Any]:
    """Bind a fresh empty inode without truncating any pre-existing target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    dir_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        dir_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        dir_flags |= os.O_NOFOLLOW
    dir_fd: int | None = None
    output_fd: int | None = None
    temp_name = f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.claim"
    replaced = False
    try:
        dir_fd = os.open(path.parent, dir_flags)
        parent_stat = os.fstat(dir_fd)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise LifecycleConflict("external output parent is not a directory")
        existing_stat: os.stat_result | None
        try:
            existing_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing_stat = None
        if existing_stat is not None:
            if not stat.S_ISREG(existing_stat.st_mode):
                raise LifecycleConflict("external output target must be a regular file")
            if int(existing_stat.st_nlink) != 1:
                raise LifecycleConflict("external output target must not be hard-linked")
            validation_flags = os.O_RDWR
            if hasattr(os, "O_NONBLOCK"):
                validation_flags |= os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                validation_flags |= os.O_NOFOLLOW
            output_fd = os.open(path.name, validation_flags, dir_fd=dir_fd)
            validated_stat = os.fstat(output_fd)
            if not stat.S_ISREG(validated_stat.st_mode):
                raise LifecycleConflict("external output must be a regular file")
            if int(validated_stat.st_nlink) != 1:
                raise LifecycleConflict("external output must have exactly one hard link")
            if (
                int(existing_stat.st_dev) != int(validated_stat.st_dev)
                or int(existing_stat.st_ino) != int(validated_stat.st_ino)
            ):
                raise LifecycleConflict("external output identity changed during claim")
            os.close(output_fd)
            output_fd = None

        stage_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NONBLOCK"):
            stage_flags |= os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            stage_flags |= os.O_NOFOLLOW
        output_fd = os.open(temp_name, stage_flags, 0o600, dir_fd=dir_fd)
        output_stat = os.fstat(output_fd)
        if not stat.S_ISREG(output_stat.st_mode) or int(output_stat.st_nlink) != 1:
            raise LifecycleConflict("external output claim stage is not a private regular file")
        os.fsync(output_fd)
        os.replace(temp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        replaced = True
        os.fsync(dir_fd)
        path_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or int(path_stat.st_nlink) != 1
            or int(path_stat.st_dev) != int(output_stat.st_dev)
            or int(path_stat.st_ino) != int(output_stat.st_ino)
        ):
            raise LifecycleConflict("external output identity changed while binding fresh claim inode")
        return {
            "path": str(path),
            "exists": True,
            "hash": "sha256:" + hashlib.sha256(b"").hexdigest(),
            "version": f"{output_stat.st_size}:{output_stat.st_mtime_ns}",
            "size": 0,
            "device": int(output_stat.st_dev),
            "inode": int(output_stat.st_ino),
            "parent_device": int(parent_stat.st_dev),
            "parent_inode": int(parent_stat.st_ino),
            "link_count": int(output_stat.st_nlink),
            "fresh_inode": True,
            "kind": "regular_file",
        }
    except LifecycleConflict:
        raise
    except OSError as exc:
        raise LifecycleConflict(f"external output is not safely writable: {exc}") from exc
    finally:
        if output_fd is not None:
            os.close(output_fd)
        if dir_fd is not None:
            if not replaced:
                try:
                    os.unlink(temp_name, dir_fd=dir_fd)
                except FileNotFoundError:
                    pass
            os.close(dir_fd)


def _read_fd_bytes(fd: int) -> bytes:
    chunks: list[bytes] = []
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _external_output_evidence(
    path: Path,
    claim_baseline: dict[str, Any],
    *,
    require_baseline_inode: bool,
) -> dict[str, Any]:
    """Read output through a bound parent dirfd and reject identity changes."""

    dir_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        dir_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        dir_flags |= os.O_NOFOLLOW
    dir_fd: int | None = None
    output_fd: int | None = None
    try:
        dir_fd = os.open(path.parent, dir_flags)
        parent_stat = os.fstat(dir_fd)
        if (
            int(claim_baseline.get("parent_device") or -1) != int(parent_stat.st_dev)
            or int(claim_baseline.get("parent_inode") or -1) != int(parent_stat.st_ino)
        ):
            raise LifecycleConflict("external output parent identity changed after claim")
        try:
            path_stat = os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise LifecycleConflict("external output disappeared after claim") from exc
        if not stat.S_ISREG(path_stat.st_mode):
            raise LifecycleConflict("external output is no longer a regular file")
        if int(path_stat.st_nlink) != 1:
            raise LifecycleConflict("external output gained an unsafe hard link after claim")
        flags = os.O_RDONLY
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        output_fd = os.open(path.name, flags, dir_fd=dir_fd)
        output_stat = os.fstat(output_fd)
        if not stat.S_ISREG(output_stat.st_mode):
            raise LifecycleConflict("external output is no longer a regular file")
        if int(output_stat.st_nlink) != 1:
            raise LifecycleConflict("external output gained an unsafe hard link after claim")
        if require_baseline_inode and (
            int(claim_baseline.get("device") or -1) != int(output_stat.st_dev)
            or int(claim_baseline.get("inode") or -1) != int(output_stat.st_ino)
        ):
            raise LifecycleConflict("external output identity changed after claim")
        content = _read_fd_bytes(output_fd)
        return {
            "path": str(path),
            "exists": True,
            "hash": "sha256:" + hashlib.sha256(content).hexdigest(),
            "version": f"{output_stat.st_size}:{output_stat.st_mtime_ns}",
            "size": int(output_stat.st_size),
            "device": int(output_stat.st_dev),
            "inode": int(output_stat.st_ino),
            "parent_device": int(parent_stat.st_dev),
            "parent_inode": int(parent_stat.st_ino),
            "link_count": int(output_stat.st_nlink),
            "kind": "regular_file",
        }
    except LifecycleConflict:
        raise
    except OSError as exc:
        raise LifecycleConflict(f"external output identity cannot be verified: {exc}") from exc
    finally:
        if output_fd is not None:
            os.close(output_fd)
        if dir_fd is not None:
            os.close(dir_fd)


def _open_claimed_external_output_fd(
    path: Path,
    claim_baseline: dict[str, Any],
) -> int:
    fd = -1
    flags = os.O_RDWR
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode):
            raise LifecycleConflict("claimed external output descriptor is not regular")
        if int(observed.st_nlink) != 1:
            raise LifecycleConflict("claimed external output descriptor is hard-linked")
        if (
            int(claim_baseline.get("device") or -1) != int(observed.st_dev)
            or int(claim_baseline.get("inode") or -1) != int(observed.st_ino)
        ):
            raise LifecycleConflict("external output identity changed while acquiring descriptor")
        return fd
    except LifecycleConflict:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    except OSError as exc:
        raise LifecycleConflict(f"external output descriptor cannot be acquired: {exc}") from exc


def _publish_external_output_to_claimed_fd(
    *,
    output_fd: int,
    path: Path,
    content: bytes,
    claim_baseline: dict[str, Any],
) -> dict[str, Any]:
    before = _external_output_evidence(path, claim_baseline, require_baseline_inode=True)
    descriptor_stat = os.fstat(output_fd)
    if int(descriptor_stat.st_nlink) != 1:
        raise LifecycleConflict("claimed external output descriptor gained an unsafe hard link")
    if (
        int(before.get("device") or -1) != int(descriptor_stat.st_dev)
        or int(before.get("inode") or -1) != int(descriptor_stat.st_ino)
    ):
        raise LifecycleConflict("external output pathname no longer names the claimed descriptor")
    try:
        os.ftruncate(output_fd, 0)
        os.lseek(output_fd, 0, os.SEEK_SET)
        view = memoryview(content)
        while view:
            written = os.write(output_fd, view)
            if written <= 0:
                raise OSError("short write while publishing external output")
            view = view[written:]
        os.fsync(output_fd)
    except OSError as exc:
        raise LifecycleConflict(f"external output descriptor publish failed: {exc}") from exc
    after = _external_output_evidence(path, claim_baseline, require_baseline_inode=True)
    descriptor_stat = os.fstat(output_fd)
    if int(descriptor_stat.st_nlink) != 1:
        raise LifecycleConflict("claimed external output descriptor gained an unsafe hard link")
    expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    if (
        int(after.get("device") or -1) != int(descriptor_stat.st_dev)
        or int(after.get("inode") or -1) != int(descriptor_stat.st_ino)
        or after.get("hash") != expected_hash
    ):
        raise LifecycleConflict("external output descriptor evidence changed during publish")
    after["descriptor_bound"] = True
    after["atomic_replace"] = False
    after["published_at"] = _now_iso()
    return after


def _atomic_publish_external_output(
    path: Path,
    content: bytes,
    claim_baseline: dict[str, Any],
) -> dict[str, Any]:
    """Publish provider output by dirfd-relative atomic replace.

    The claimed empty inode must still be present before publication.  The
    provider never receives this pathname, and the temporary filename is not
    persisted or exposed to the child process.
    """

    _external_output_evidence(path, claim_baseline, require_baseline_inode=True)
    dir_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        dir_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        dir_flags |= os.O_NOFOLLOW
    dir_fd: int | None = None
    temp_fd: int | None = None
    temp_name = f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.publish"
    replaced = False
    try:
        dir_fd = os.open(path.parent, dir_flags)
        parent_stat = os.fstat(dir_fd)
        if (
            int(claim_baseline.get("parent_device") or -1) != int(parent_stat.st_dev)
            or int(claim_baseline.get("parent_inode") or -1) != int(parent_stat.st_ino)
        ):
            raise LifecycleConflict("external output parent identity changed before publish")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        temp_fd = os.open(temp_name, flags, 0o600, dir_fd=dir_fd)
        view = memoryview(content)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short write while publishing external output")
            view = view[written:]
        os.fsync(temp_fd)
        temp_stat = os.fstat(temp_fd)
        if not stat.S_ISREG(temp_stat.st_mode):
            raise LifecycleConflict("external output publish stage is not a regular file")
        os.close(temp_fd)
        temp_fd = None
        # Recheck the baseline immediately before the atomic replacement.
        _external_output_evidence(path, claim_baseline, require_baseline_inode=True)
        os.replace(temp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        replaced = True
        os.fsync(dir_fd)
        evidence = _external_output_evidence(
            path,
            claim_baseline,
            require_baseline_inode=False,
        )
        if (
            int(evidence.get("device") or -1) != int(temp_stat.st_dev)
            or int(evidence.get("inode") or -1) != int(temp_stat.st_ino)
            or evidence.get("hash") != "sha256:" + hashlib.sha256(content).hexdigest()
        ):
            raise LifecycleConflict("external output publish evidence does not match staged bytes")
        evidence["atomic_replace"] = True
        evidence["published_at"] = _now_iso()
        return evidence
    except LifecycleConflict:
        raise
    except OSError as exc:
        raise LifecycleConflict(f"external output could not be atomically published: {exc}") from exc
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if dir_fd is not None:
            if not replaced:
                try:
                    os.unlink(temp_name, dir_fd=dir_fd)
                except FileNotFoundError:
                    pass
            os.close(dir_fd)


def _append_history(base_dir: Path | str, payload: dict[str, Any], event: str) -> None:
    path = _base_path(base_dir) / "history" / "native-delegation.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "event_type": f"delegation.{event}",
        "observed_at": _now_iso(),
        "task_id": payload.get("task_id"),
        "attempt_id": payload.get("attempt_id"),
        "mst_session_id": payload.get("mst_session_id"),
        "root_mst_id": payload.get("root_mst_id"),
        "parent_session_id": payload.get("parent_session_id"),
        "execution_transport": payload.get("execution_transport"),
        "launch_surface": payload.get("launch_surface"),
        "requested_launch_surface": payload.get("requested_launch_surface"),
        "launch_surface_status": payload.get("launch_surface_status"),
        "orca_launch_status": payload.get("orca_launch_status"),
        "orca_worktree_selector": payload.get("orca_worktree_selector"),
        "orca_terminal_title": payload.get("orca_terminal_title"),
        "orca_terminal_handle": payload.get("orca_terminal_handle"),
        "orca_create_invoked_at": payload.get("orca_create_invoked_at"),
        "orca_reconciliation_required": payload.get("orca_reconciliation_required"),
        "orca_reconciliation": payload.get("orca_reconciliation"),
        "orca_cleanup_status": payload.get("orca_cleanup_status"),
        "host": payload.get("host"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "reasoning_effort_source": payload.get("reasoning_effort_source"),
        "provider_task_id": payload.get("provider_task_id"),
        "spawn_claim_status": payload.get("spawn_claim_status"),
        "spawn_claim_owner": payload.get("spawn_claim_owner"),
        "spawn_claimed_at": payload.get("spawn_claimed_at"),
        "spawn_claim_expires_at": payload.get("spawn_claim_expires_at"),
        "spawn_claim_consumed_at": payload.get("spawn_claim_consumed_at"),
        "route_reason": payload.get("route_reason"),
        "phase": payload.get("phase"),
        "status": payload.get("status"),
        "started_at": payload.get("started_at"),
        "last_heartbeat": payload.get("last_heartbeat"),
        "terminated_at": payload.get("terminated_at"),
        "completion_signal": payload.get("completion_signal"),
        "exit_code": payload.get("exit_code"),
        "failure_domain": payload.get("failure_domain"),
        "worktree_dir": payload.get("worktree_dir"),
        "running_log_path": payload.get("running_log_path"),
        "trace_path": payload.get("trace_path"),
        "prompt_file": payload.get("prompt_file"),
        "prompt_hash": payload.get("prompt_hash"),
        "prompt_snapshot_path": payload.get("prompt_snapshot_path"),
        "prompt_snapshot_hash": payload.get("prompt_snapshot_hash"),
        "prompt_snapshot_role": payload.get("prompt_snapshot_role"),
        "prompt_snapshot_audit": payload.get("prompt_snapshot_audit"),
        "prompt_execution": payload.get("prompt_execution"),
        "context_files_read": payload.get("context_files_read", []),
        "output_path": payload.get("output_path"),
        "output_hash": payload.get("output_hash"),
        "output_baseline_exists": payload.get("output_baseline_exists"),
        "output_baseline_hash": payload.get("output_baseline_hash"),
        "output_baseline_version": payload.get("output_baseline_version"),
        "output_claim_baseline": payload.get("output_claim_baseline"),
        "output_claim": payload.get("output_claim"),
        "output_publish": payload.get("output_publish"),
        "stderr_evidence": payload.get("stderr_evidence"),
        "artifact_binding_version": payload.get("artifact_binding_version"),
        "io_exit_code": payload.get("io_exit_code"),
        "provider_reconciliation_required": payload.get("provider_reconciliation_required"),
        "reconciliation_action": payload.get("reconciliation_action"),
        "fallback_from": payload.get("fallback_from"),
        "fallback_to": payload.get("fallback_to"),
        "attempts": payload.get("attempts", []),
        "output_freshness": payload.get("output_freshness"),
        "external_claim_id": payload.get("external_claim_id"),
        "external_claimed_at": payload.get("external_claimed_at"),
        "external_claim_consumed_at": payload.get("external_claim_consumed_at"),
        "external_claim_expires_at": payload.get("external_claim_expires_at"),
        "provider_pid": payload.get("provider_pid"),
        "provider_pgid": payload.get("provider_pgid"),
        "provider_pid_start_time": payload.get("provider_pid_start_time"),
        "provider_exec_release_status": payload.get("provider_exec_release_status"),
        "provider_exec_authorized_at": payload.get("provider_exec_authorized_at"),
        "provider_exec_released_at": payload.get("provider_exec_released_at"),
        "provider_reap_evidence": payload.get("provider_reap_evidence"),
    }
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _file_evidence(path_value: Path | str | None) -> dict[str, Any] | None:
    if path_value is None or not str(path_value).strip():
        return None
    path = Path(path_value).resolve(strict=False)
    evidence: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "hash": None,
        "version": None,
        "size": None,
    }
    if not path.is_file():
        return evidence
    try:
        content = path.read_bytes()
        stat_result = path.stat()
    except OSError:
        return evidence
    evidence["hash"] = "sha256:" + hashlib.sha256(content).hexdigest()
    evidence["version"] = f"{stat_result.st_size}:{stat_result.st_mtime_ns}"
    evidence["size"] = stat_result.st_size
    return evidence


def _canonical_delegation_identity(
    *,
    mst_session_id: str | None = None,
    root_mst_id: str | None = None,
    parent_session_id: str | None = None,
) -> dict[str, str | None]:
    """Resolve lifecycle identity from the canonical inherited session.

    Library callers outside an MST session may omit all identity fields. Once
    any identity is supplied, the full structured identity is validated and a
    conflicting inherited MST_SESSION_ID is rejected.
    """

    from scripts.mst_cmds.session import validate_mst_session_id

    try:
        inherited = _common.canonical_mst_session_id_from_env_or_context()
    except ValueError as exc:
        raise LifecycleConflict(str(exc)) from exc
    explicit = str(mst_session_id or "").strip() or None
    if explicit:
        try:
            explicit = validate_mst_session_id(explicit).mst_session_id
        except ValueError as exc:
            raise LifecycleConflict(str(exc)) from exc
    if inherited and explicit and inherited != explicit:
        raise LifecycleConflict("MST_SESSION_ID and explicit mst_session_id mismatch")
    canonical = inherited or explicit
    if canonical is None:
        if root_mst_id or parent_session_id:
            raise LifecycleConflict("root/parent session identity requires mst_session_id")
        return {"mst_session_id": None, "root_mst_id": None, "parent_session_id": None}

    try:
        parsed = validate_mst_session_id(canonical)
    except ValueError as exc:
        raise LifecycleConflict(str(exc)) from exc
    explicit_root = str(root_mst_id or "").strip() or None
    if explicit_root and explicit_root != parsed.root_mst_id:
        raise LifecycleConflict("MST_SESSION_ID and root_mst_id mismatch")
    parent = str(parent_session_id or "").strip() or parsed.mst_session_id
    try:
        validate_mst_session_id(parent, expected_root_mst_id=parsed.root_mst_id)
    except ValueError as exc:
        raise LifecycleConflict(f"parent_session_id mismatch: {exc}") from exc
    return {
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "parent_session_id": parent,
    }


def _validate_persisted_session_identity(state: dict[str, Any]) -> None:
    persisted = str(state.get("mst_session_id") or "").strip() or None
    root = str(state.get("root_mst_id") or "").strip() or None
    parent = str(state.get("parent_session_id") or "").strip() or None
    try:
        inherited = _common.canonical_mst_session_id_from_env_or_context()
    except ValueError as exc:
        raise LifecycleConflict(str(exc)) from exc
    if persisted is None:
        if root or parent:
            raise LifecycleConflict("persisted delegation session identity is incomplete")
        if inherited:
            raise LifecycleConflict("persisted delegation attempt is missing inherited MST_SESSION_ID")
        return
    identity = _canonical_delegation_identity(
        mst_session_id=persisted,
        root_mst_id=root,
        parent_session_id=parent,
    )
    if inherited and identity["mst_session_id"] != inherited:
        raise LifecycleConflict("persisted delegation MST_SESSION_ID mismatch")


def _normalize_mst_context_json(
    raw_context: str | None,
    *,
    mst_session_id: str,
    root_mst_id: str,
) -> str:
    raw = str(raw_context or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LifecycleConflict(f"MST_CONTEXT_JSON must be valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise LifecycleConflict("MST_CONTEXT_JSON must be a JSON object")
    else:
        payload = {}
    if payload.get("schema_version") not in {None, 1}:
        raise LifecycleConflict("MST_CONTEXT_JSON schema_version mismatch")
    persisted_session = str(payload.get("mst_session_id") or "").strip()
    if persisted_session and persisted_session != mst_session_id:
        raise LifecycleConflict("MST_CONTEXT_JSON mst_session_id mismatch")
    persisted_root = str(payload.get("root_mst_id") or "").strip()
    if persisted_root and root_mst_id and persisted_root != root_mst_id:
        raise LifecycleConflict("MST_CONTEXT_JSON root_mst_id mismatch")
    normalized = dict(payload)
    normalized["schema_version"] = 1
    normalized["mst_session_id"] = mst_session_id
    if root_mst_id:
        normalized["root_mst_id"] = root_mst_id
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mst_context_binding(
    *,
    base_dir: Path | str,
    task_id: str,
    attempt_id: str,
    mst_session_id: str,
    root_mst_id: str,
    raw_context: str | None,
) -> tuple[Path, bytes, str]:
    normalized = _normalize_mst_context_json(
        raw_context,
        mst_session_id=mst_session_id,
        root_mst_id=root_mst_id,
    )
    content = normalized.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = _artifact_path(
        base_dir,
        task_id,
        None,
        f"mst-context-{hashlib.sha256(attempt_id.encode('utf-8')).hexdigest()[:16]}.json",
    )
    return path, content, f"sha256:{digest}"


def load_persisted_mst_context(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    inherited_context: str | None = None,
) -> str:
    """Load the bound context, with a direct-only legacy inherited fallback."""

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "load_mst_context")
        _validate_persisted_session_identity(state)
        path_text = str(state.get("mst_context_snapshot_path") or "").strip()
        expected_hash = str(state.get("mst_context_snapshot_hash") or "").strip()
        session_id = str(state.get("mst_session_id") or "").strip()
        root_id = str(state.get("root_mst_id") or "").strip()
        launch_surface = str(state.get("launch_surface") or "direct").strip()
        requested_launch_surface = str(
            state.get("requested_launch_surface") or "direct"
        ).strip()
    if not path_text or not expected_hash.startswith("sha256:"):
        legacy_binding_absent = not path_text and not expected_hash
        if (
            legacy_binding_absent
            and launch_surface != "orca"
            and requested_launch_surface != "orca"
            and str(inherited_context or "").strip()
        ):
            return _normalize_mst_context_json(
                str(inherited_context),
                mst_session_id=session_id,
                root_mst_id=root_id,
            )
        raise LifecycleConflict("external attempt is missing its MST context binding")
    path = Path(path_text)
    artifact_root = (_base_path(base_dir) / "run" / "artifacts" / task_id).resolve(
        strict=False
    )
    resolved = path.resolve(strict=False)
    if not _path_is_within(resolved, artifact_root):
        raise LifecycleConflict("MST context snapshot escapes the task artifact root")
    try:
        observed = path.lstat()
        content = path.read_bytes()
    except OSError as exc:
        raise LifecycleConflict(f"MST context snapshot is unreadable: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode) or int(observed.st_nlink) != 1:
        raise LifecycleConflict("MST context snapshot must be a single-link regular file")
    actual_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash:
        raise LifecycleConflict("MST context snapshot hash mismatch")
    return _normalize_mst_context_json(
        content.decode("utf-8"),
        mst_session_id=session_id,
        root_mst_id=root_id,
    )


def _artifact_path(
    base_dir: Path | str,
    task_id: str,
    value: Path | str | None,
    default_name: str,
) -> Path:
    if value is None or not str(value).strip():
        return _base_path(base_dir) / "run" / "artifacts" / task_id / default_name
    path = Path(value)
    if not path.is_absolute():
        path = _base_path(base_dir) / "run" / "artifacts" / task_id / path.name
    return path.resolve(strict=False)


def _lifecycle_artifact_paths(
    *,
    base_dir: Path | str,
    task_id: str,
    running_log_path: Path | str | None,
    trace_path: Path | str | None,
    output_path: Path | str | None,
) -> tuple[Path, Path, Path]:
    running = _artifact_path(base_dir, task_id, running_log_path, "running.log")
    trace = _artifact_path(base_dir, task_id, trace_path, "trace.ndjson")
    output = _artifact_path(base_dir, task_id, output_path, "result.md")
    return running, trace, output


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_external_control_plane_artifacts(
    *,
    base_dir: Path | str,
    task_id: str,
    worktree_dir: Path | str,
    artifacts: dict[str, Path | str],
) -> None:
    """Keep writable provider artifacts away from MST state, locks, and history."""

    base = _base_path(base_dir)
    _validate_task_id(task_id)
    artifact_root_lexical = base / "run" / "artifacts"
    artifact_root = artifact_root_lexical.resolve(strict=False)
    if artifact_root != artifact_root_lexical:
        raise LifecycleConflict("external artifact root must not traverse a symlink")
    run_root = (base / "run").resolve(strict=False)
    worktree = Path(worktree_dir).resolve(strict=False)
    git_control = (worktree / ".git").resolve(strict=False)
    reserved_roots = [
        (base / name).resolve(strict=False)
        for name in ("history", "sessions", "state", "logs", "tmp", "intent")
    ]
    reserved_names = {
        "agents.json",
        "config.json",
        "config.resolved.json",
        "counter.json",
        "events.ndjson",
        "history.head",
        "history.ndjson",
        "intent.db",
        "pending.ndjson",
        "request.json",
        "session.json",
        "snapshot.json",
        "state.json",
    }
    for label, raw_path in artifacts.items():
        resolved = Path(raw_path).resolve(strict=False)
        aliases_run_control = _path_is_within(resolved, run_root) and not _path_is_within(
            resolved, artifact_root
        )
        aliases_reserved_root = any(
            _path_is_within(resolved, reserved_root) for reserved_root in reserved_roots
        )
        aliases_top_level_control = resolved.parent == base
        aliases_git_control = _path_is_within(resolved, git_control)
        aliases_named_control = _path_is_within(resolved, base) and (
            resolved.name in reserved_names or resolved.name.endswith(".lock")
        )
        if (
            aliases_run_control
            or aliases_reserved_root
            or aliases_top_level_control
            or aliases_named_control
            or aliases_git_control
        ):
            raise LifecycleConflict(
                f"external {label} path aliases reserved MST control-plane storage"
            )


def _prepare_lifecycle_artifact_paths(
    running: Path,
    trace: Path,
    output: Path,
) -> None:
    for artifact in (running, trace):
        artifact.parent.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_APPEND
            if hasattr(os, "O_NONBLOCK"):
                flags |= os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(artifact, flags)
            except FileNotFoundError:
                fd = os.open(artifact, flags | os.O_CREAT | os.O_EXCL, 0o600)
            observed = os.fstat(fd)
            if not stat.S_ISREG(observed.st_mode) or int(observed.st_nlink) != 1:
                raise LifecycleConflict(
                    f"lifecycle artifact must be a single-link regular file: {artifact}"
                )
        except LifecycleConflict:
            raise
        except OSError as exc:
            raise LifecycleConflict(f"lifecycle artifact is not safely writable: {artifact}: {exc}") from exc
        finally:
            if fd is not None:
                os.close(fd)
    output.parent.mkdir(parents=True, exist_ok=True)


def _attempt_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    excluded = {"attempts", "lifecycle_events", "idempotency_keys"}
    return json.loads(json.dumps({key: value for key, value in payload.items() if key not in excluded}, ensure_ascii=False))


def _sync_attempt(payload: dict[str, Any]) -> None:
    attempt_id = str(payload.get("attempt_id") or "")
    attempts = [dict(item) for item in payload.get("attempts", []) if isinstance(item, dict)]
    snapshot = _attempt_snapshot(payload)
    snapshot["current_attempt"] = True
    replaced = False
    for index, attempt in enumerate(attempts):
        if str(attempt.get("attempt_id") or "") == attempt_id:
            attempts[index] = snapshot
            replaced = True
        else:
            attempt["current_attempt"] = False
    if not replaced:
        attempts.append(snapshot)
    payload["attempts"] = attempts
    payload["current_attempt"] = True


def _settle_terminal_reconciliation(payload: dict[str, Any]) -> None:
    """Resolve provider reconciliation in the same write as terminal state.

    A pending reconciliation action is current control-plane authority.  Once
    the lifecycle has conclusive terminal evidence, retaining that authority
    would let a consumer execute recovery work against an already-settled
    attempt.  Keep the action as append-only evidence, but make it explicitly
    non-actionable before the terminal state is persisted.
    """

    phase = str(payload.get("phase") or "").strip().lower()
    if not lifecycle_is_terminal(payload):
        return

    payload["provider_reconciliation_required"] = False
    action = payload.get("reconciliation_action")
    if not isinstance(action, dict):
        return

    resolved_at = str(payload.get("terminated_at") or "").strip() or _now_iso()
    reap_evidence = (
        payload.get("provider_reap_evidence")
        if isinstance(payload.get("provider_reap_evidence"), dict)
        else {}
    )
    prior_provider_state = str(payload.get("provider_state") or "").strip() or None
    completion_signal = str(payload.get("completion_signal") or "").strip().lower()
    if phase == "terminated" or completion_signal in {
        "cancelled",
        "canceled",
        "process_cancelled",
    }:
        provider_state = "cancelled"
    elif phase == "done" or completion_signal in {"completed", "succeeded", "success"}:
        provider_state = "completed"
    elif completion_signal == "process_exit" and int(payload.get("exit_code") or 0) == 0:
        provider_state = "completed"
    else:
        provider_state = "failed"
    payload["provider_state"] = provider_state

    prior_result = action.get("result") if isinstance(action.get("result"), dict) else {}
    result = {
        **prior_result,
        "provider_state": provider_state,
        "prior_provider_state": prior_provider_state,
        "completion_signal": payload.get("completion_signal"),
        "phase": phase,
        "status": payload.get("status"),
        "exit_code": payload.get("exit_code"),
        "group_observed_gone": reap_evidence.get("group_observed_gone"),
        "observed_at": resolved_at,
        "evidence_source": "terminal_lifecycle_state",
    }
    payload["reconciliation_action"] = {
        **action,
        "status": "resolved",
        "completion_accepted": True,
        "resolved_at": str(action.get("resolved_at") or "").strip() or resolved_at,
        "result": result,
    }
    payload["reconciliation_resolved_at"] = resolved_at


def _operation_fingerprint(event: str, source_attempt_id: str, operation_payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "operation": event,
            "source_attempt_id": str(source_attempt_id or ""),
            "payload": operation_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_event(
    payload: dict[str, Any],
    event: str,
    idempotency_key: str,
    *,
    source_attempt_id: str,
    fingerprint: str,
    **details: Any,
) -> None:
    now = _now_iso()
    events = payload.setdefault("lifecycle_events", [])
    events.append({"event": event, "at": now, **details})
    keys = payload.setdefault("idempotency_keys", {})
    keys[idempotency_key] = {
        "operation": event,
        "at": now,
        "source_attempt_id": str(source_attempt_id or ""),
        "result_attempt_id": payload.get("attempt_id"),
        "fingerprint": fingerprint,
    }
    payload["updated_at"] = now
    _sync_attempt(payload)


def _idempotent_replay(payload: dict[str, Any], idempotency_key: str) -> bool:
    keys = payload.get("idempotency_keys")
    return isinstance(keys, dict) and idempotency_key in keys


def _exact_replay(
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    operation: str,
    source_attempt_id: str,
    fingerprint: str,
) -> bool:
    keys = payload.get("idempotency_keys")
    record = keys.get(idempotency_key) if isinstance(keys, dict) else None
    if not isinstance(record, dict):
        return False
    if (
        record.get("operation") == operation
        and str(record.get("source_attempt_id") or "") == str(source_attempt_id or "")
        and record.get("fingerprint") == fingerprint
    ):
        return True
    raise LifecycleConflict(f"idempotency key '{idempotency_key}' has a conflicting replay")


def _assert_attempt_cas(state: dict[str, Any], expected_attempt_id: str, operation: str) -> None:
    expected = str(expected_attempt_id or "").strip()
    current = str(state.get("attempt_id") or "").strip()
    if not expected:
        raise LifecycleConflict(f"{operation} requires expected_attempt_id")
    if expected != current:
        raise LifecycleConflict(
            f"{operation} attempt CAS mismatch: expected {expected}, current {current or 'missing'}"
        )


def _git_lines(cwd: Path, *args: str) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise LifecycleConflict(proc.stderr.strip() or "git worktree inspection failed")
    return proc.stdout.splitlines()


def validate_native_worktree(
    *,
    base_dir: Path | str,
    task_id: str,
    worktree_dir: Path | str,
    read_only: bool,
    scope: str,
) -> dict[str, Any]:
    target = Path(worktree_dir).resolve(strict=False)
    if read_only:
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope not in READ_ONLY_SCOPES:
            raise LifecycleConflict(f"read-only exception is not allowed for scope '{normalized_scope}'")
        return {"ok": True, "reason": "read_only_exception", "worktree_dir": str(target)}
    if not target.is_dir():
        raise LifecycleConflict(f"unregistered worktree: {target}")

    project_root = _base_path(base_dir).parent
    lines = _git_lines(project_root, "worktree", "list", "--porcelain")
    worktrees = [Path(line.split(" ", 1)[1]).resolve(strict=False) for line in lines if line.startswith("worktree ")]
    if not worktrees or target not in worktrees:
        raise LifecycleConflict(f"unregistered worktree: {target}")
    if target == worktrees[0]:
        raise LifecycleConflict(f"primary checkout is not allowed for write-capable native delegation: {target}")

    run_dir = _base_path(base_dir) / "run"
    for path in run_dir.glob("*.json") if run_dir.is_dir() else []:
        if path == native_state_path(base_dir, task_id):
            continue
        try:
            other = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleConflict(f"cannot verify worktree ownership because state is unreadable: {path}") from exc
        if not isinstance(other, dict) or other.get("phase") in TERMINAL_PHASES:
            continue
        other_worktree = str(other.get("worktree_dir") or "")
        if other_worktree and Path(other_worktree).resolve(strict=False) == target and not other.get("read_only"):
            raise LifecycleConflict(f"worktree already owned by active task {other.get('task_id')}")
    return {"ok": True, "reason": "linked_worktree", "worktree_dir": str(target)}


def start_native_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    idempotency_key: str,
    host: str,
    provider: str,
    worktree_dir: Path | str,
    scope: str,
    read_only: bool,
    attempt_id: str | None = None,
    capability_status: str = "available",
    route_reason: str = "same_host_native_capable",
    route_decision: dict[str, Any] | None = None,
    prompt_file: Path | str | None = None,
    context_files: list[Path | str] | None = None,
    running_log_path: Path | str | None = None,
    trace_path: Path | str | None = None,
    output_path: Path | str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    reasoning_effort_source: str | None = None,
    mst_session_id: str | None = None,
    root_mst_id: str | None = None,
    parent_session_id: str | None = None,
    parent_heartbeat: str | None = None,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    normalized_host = str(host or "").strip().lower()
    normalized_provider = _normalized_provider(provider)
    if normalized_host != normalized_provider or normalized_provider not in NATIVE_PROVIDERS:
        raise LifecycleConflict("native attempt requires the same supported host and provider")
    identity = _canonical_delegation_identity(
        mst_session_id=mst_session_id,
        root_mst_id=root_mst_id,
        parent_session_id=parent_session_id,
    )
    running_artifact, trace_artifact, output_artifact = _lifecycle_artifact_paths(
        base_dir=base_dir,
        task_id=task_id,
        running_log_path=running_log_path,
        trace_path=trace_path,
        output_path=output_path,
    )
    decision = dict(route_decision) if isinstance(route_decision, dict) else resolve_delegation_route(
        base_dir=base_dir,
        host=normalized_host,
        provider=normalized_provider,
        scope=scope,
        capability_status=capability_status,
        external_adapter_available=None,
        worktree_dir=worktree_dir,
    )
    if decision.get("route") != "native_candidate":
        raise LifecycleConflict(f"persisted route does not authorize native start: {decision.get('reason_code')}")
    capability = str(decision.get("capability_status") or capability_status or "unknown").lower()
    prompt_evidence = _file_evidence(prompt_file)
    context_evidence = [evidence for evidence in (_file_evidence(path) for path in (context_files or [])) if evidence]
    start_payload = {
        "attempt_id": attempt_id,
        "host": normalized_host,
        "provider": normalized_provider,
        "worktree_dir": str(Path(worktree_dir).resolve(strict=False)),
        "scope": scope,
        "read_only": bool(read_only),
        "capability_status": capability,
        "route_fingerprint": decision.get("route_fingerprint"),
        "launch_surface": decision.get("launch_surface", "direct"),
        "prompt_hash": prompt_evidence.get("hash") if prompt_evidence else None,
        "context_hashes": [item.get("hash") for item in context_evidence],
        "mst_session_id": identity["mst_session_id"],
        "root_mst_id": identity["root_mst_id"],
        "parent_session_id": identity["parent_session_id"],
        "running_log_path": str(running_artifact),
        "trace_path": str(trace_artifact),
        "output_path": str(output_artifact),
        "model": str(model) if model is not None else None,
        "reasoning_effort": str(reasoning_effort) if reasoning_effort is not None else None,
        "reasoning_effort_source": str(reasoning_effort_source) if reasoning_effort_source is not None else None,
        "parent_heartbeat": parent_heartbeat,
    }
    start_fingerprint = _operation_fingerprint("start", "", start_payload)

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        existing = _load_state(base_dir, task_id)
        if isinstance(existing, dict):
            _validate_persisted_session_identity(existing)
            if _exact_replay(
                existing,
                idempotency_key=key,
                operation="start",
                source_attempt_id="",
                fingerprint=start_fingerprint,
            ):
                return existing
        if isinstance(existing, dict) and str(existing.get("phase") or "") not in TERMINAL_PHASES:
            raise LifecycleConflict("task already has an active attempt")

        guard = validate_native_worktree(
            base_dir=base_dir,
            task_id=task_id,
            worktree_dir=worktree_dir,
            read_only=bool(read_only),
            scope=scope,
        )
        _prepare_lifecycle_artifact_paths(
            running_artifact,
            trace_artifact,
            output_artifact,
        )
        now = _now_iso()
        initial_phase = "reconciling" if capability == "unknown" else "spawn_requested"
        initial_status = "capability_reconciliation_required" if capability == "unknown" else "spawn_requested"
        state: dict[str, Any] = {
            "schema_version": 1,
            "mst_session_id": identity["mst_session_id"],
            "root_mst_id": identity["root_mst_id"],
            "parent_session_id": identity["parent_session_id"],
            "task_id": task_id,
            "attempt_id": str(attempt_id or f"{task_id}-native-{uuid.uuid4().hex[:12]}").strip(),
            "current_attempt": True,
            "execution_transport": "native",
            "launch_surface": str(decision.get("launch_surface") or "direct"),
            "requested_launch_surface": str(
                decision.get("requested_launch_surface") or "direct"
            ),
            "launch_surface_status": str(
                decision.get("launch_surface_status") or "disabled"
            ),
            "external_control_surface": "host_bridge",
            "host": normalized_host,
            "provider": normalized_provider,
            "provider_task_id": None,
            "capability_status": capability,
            "spawn_status": "requested",
            "start_acknowledged": False,
            "spawn_claim_status": "unclaimed",
            "spawn_claim_owner": None,
            "spawn_claim_token_hash": None,
            "spawn_claimed_at": None,
            "spawn_claim_expires_at": None,
            "spawn_claim_consumed_at": None,
            "route_reason": str(decision.get("reason_code") or route_reason or "same_host_native_capable"),
            "route_decision": decision,
            "route_fingerprint": str(decision.get("route_fingerprint") or _route_fingerprint(decision)),
            "phase": initial_phase,
            "status": initial_status,
            "spawn_allowed": False,
            "fallback_allowed": False,
            "pid": None,
            "exit_code": None,
            "completion_signal": None,
            "failure_domain": None,
            "started_at": now,
            "last_heartbeat": now,
            "parent_heartbeat": parent_heartbeat or now,
            "worktree_dir": str(Path(worktree_dir).resolve(strict=False)),
            "worktree_guard": guard,
            "scope": str(scope or "implementation"),
            "read_only": bool(read_only),
            "model": str(model) if model is not None else None,
            "reasoning_effort": str(reasoning_effort) if reasoning_effort is not None else None,
            "reasoning_effort_source": str(reasoning_effort_source) if reasoning_effort_source is not None else None,
            "prompt_file": prompt_evidence["path"] if prompt_evidence else None,
            "prompt_hash": prompt_evidence["hash"] if prompt_evidence else None,
            "context_files_read": context_evidence,
            "running_log_path": str(running_artifact),
            "log_path": str(running_artifact),
            "trace_path": str(trace_artifact),
            "output_path": str(output_artifact),
            "output_hash": None,
            "output_baseline": None,
            "output_baseline_exists": False,
            "output_baseline_hash": None,
            "output_baseline_version": None,
            "attempts": [],
            "lifecycle_events": [],
            "idempotency_keys": {},
        }
        if isinstance(existing, dict):
            state["attempts"] = [dict(item) for item in existing.get("attempts", []) if isinstance(item, dict)]
        _record_event(
            state,
            "start",
            key,
            source_attempt_id="",
            fingerprint=start_fingerprint,
        )
        # Capture the baseline only after the ownership guard and artifact
        # preparation, while both global/task leases are held.  Keeping this
        # immediately adjacent to the atomic state save records files that
        # appear during the guard instead of misclassifying them as fresh
        # provider output later.
        output_evidence = _file_evidence(output_artifact)
        state.update(
            {
                "output_path": output_evidence["path"] if output_evidence else str(output_artifact),
                "output_hash": output_evidence["hash"] if output_evidence else None,
                "output_baseline": output_evidence,
                "output_baseline_exists": bool(output_evidence and output_evidence["exists"]),
                "output_baseline_hash": output_evidence["hash"] if output_evidence else None,
                "output_baseline_version": output_evidence["version"] if output_evidence else None,
            }
        )
        _sync_attempt(state)
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "start")
        return state


def _spawn_claim_response(
    state: dict[str, Any],
    *,
    spawn_allowed: bool,
    claim_status: str,
    next_action: str,
    claim_token: str | None = None,
) -> dict[str, Any]:
    """Return claim authority without ever persisting the bearer token.

    ``spawn_allowed`` is deliberately response-local.  The lifecycle state
    always keeps it false so a replay of ``delegation start`` (or a plain
    state read) can never be mistaken for authority to call the host tool.
    """

    response = json.loads(json.dumps(state, ensure_ascii=False))
    response.update(
        {
            "spawn_allowed": bool(spawn_allowed),
            "claim_status": claim_status,
            "claim_token": claim_token if spawn_allowed else None,
            "next_action": next_action,
        }
    )
    return response


def claim_native_spawn(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    claimant_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Atomically elect the sole caller allowed to invoke the native host.

    A bearer token is returned exactly once and only to the winning call.
    Exact replays intentionally do *not* re-issue authority: a caller that
    lost the response cannot know whether provider creation began and must
    reconcile instead of risking a duplicate spawn.
    """

    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    claimant = str(claimant_id or "").strip()
    source_attempt_id = str(expected_attempt_id or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    if not claimant:
        raise LifecycleConflict("claimant_id is required")
    if len(claimant) > 256:
        raise LifecycleConflict("claimant_id is too long")
    fingerprint = _operation_fingerprint(
        "claim_spawn",
        source_attempt_id,
        {"claimant_id": claimant},
    )

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"delegation attempt not found for task {task_id}")
        _validate_persisted_session_identity(state)
        if _exact_replay(
            state,
            idempotency_key=key,
            operation="claim_spawn",
            source_attempt_id=source_attempt_id,
            fingerprint=fingerprint,
        ):
            return _spawn_claim_response(
                state,
                spawn_allowed=False,
                claim_status="claim_replay",
                next_action="wait_for_claim_lease_then_recover",
            )
        _assert_attempt_cas(state, expected_attempt_id, "claim_spawn")

        if lifecycle_is_terminal(state):
            return _spawn_claim_response(
                state,
                spawn_allowed=False,
                claim_status="terminal",
                next_action="stop",
            )
        if str(state.get("execution_transport") or "").strip().lower() != "native":
            raise LifecycleConflict(
                "native spawn claim requires native execution transport"
            )

        phase = str(state.get("phase") or "").strip().lower()
        if phase != "spawn_requested":
            if phase == "reconciling":
                claim_status, next_action = "reconciling", "reconcile_or_wait"
            elif phase in TERMINAL_PHASES:
                claim_status, next_action = "terminal", "stop"
            elif phase in {"spawned", "attached", "running", "cancel_requested"}:
                claim_status, next_action = "provider_task_in_flight", "attach_or_wait"
            else:
                claim_status, next_action = "not_spawnable", "stop"
            return _spawn_claim_response(
                state,
                spawn_allowed=False,
                claim_status=claim_status,
                next_action=next_action,
            )

        if str(state.get("spawn_claim_status") or "unclaimed") != "unclaimed":
            return _spawn_claim_response(
                state,
                spawn_allowed=False,
                claim_status="already_claimed",
                next_action="wait_for_claim_lease_then_recover",
            )

        token = "mst-native-claim-" + secrets.token_urlsafe(32)
        token_hash = "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = _now_iso()
        state.update(
            {
                "spawn_claim_status": "claimed",
                "spawn_claim_owner": claimant,
                "spawn_claim_token_hash": token_hash,
                "spawn_claimed_at": now,
                "spawn_claim_expires_at": _native_spawn_claim_expires_at(),
                "spawn_claim_consumed_at": None,
                # Authority is response-local; never make persisted state or a
                # start replay independently spawnable.
                "spawn_allowed": False,
                "fallback_allowed": False,
            }
        )
        _record_event(
            state,
            "claim_spawn",
            key,
            source_attempt_id=source_attempt_id,
            fingerprint=fingerprint,
            claimant_id=claimant,
            claim_status="claimed",
        )
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "claim_spawn")
        return _spawn_claim_response(
            state,
            spawn_allowed=True,
            claim_status="claimed",
            claim_token=token,
            next_action="spawn_then_acknowledge",
        )


def _mutate_state(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    idempotency_key: str,
    event: str,
    expected_transport: str | None,
    allowed_phases: set[str] | None,
    operation_payload: dict[str, Any],
    mutate,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    source_attempt_id = str(expected_attempt_id or "").strip()
    fingerprint = _operation_fingerprint(event, source_attempt_id, operation_payload)
    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"native attempt not found for task {task_id}")
        _validate_persisted_session_identity(state)
        if _exact_replay(
            state,
            idempotency_key=key,
            operation=event,
            source_attempt_id=source_attempt_id,
            fingerprint=fingerprint,
        ):
            return state
        _assert_attempt_cas(state, expected_attempt_id, event)
        _assert_nonterminal_lifecycle(state, event)
        if expected_transport is not None:
            actual_transport = str(state.get("execution_transport") or "").strip().lower()
            if actual_transport != expected_transport:
                raise LifecycleConflict(
                    f"{event} requires {expected_transport} execution transport, "
                    f"found '{actual_transport or 'missing'}'"
                )
        phase = str(state.get("phase") or "").strip().lower()
        if allowed_phases is not None and phase not in allowed_phases:
            raise LifecycleConflict(f"invalid {event} transition from phase '{phase}'")
        mutate(state)
        _settle_terminal_reconciliation(state)
        _record_event(
            state,
            event,
            key,
            source_attempt_id=source_attempt_id,
            fingerprint=fingerprint,
        )
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, event)
        return state


def acknowledge_native_spawn(
    *,
    base_dir: Path | str,
    task_id: str,
    spawn_status: str,
    idempotency_key: str,
    expected_attempt_id: str,
    provider_task_id: str | None = None,
    claim_token: str | None = None,
) -> dict[str, Any]:
    incoming = str(spawn_status or "").strip().lower()
    task_ref = str(provider_task_id or "").strip() or None
    token = str(claim_token or "").strip()
    token_hash = "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None

    def mutate(state: dict[str, Any]) -> None:
        if str(state.get("spawn_claim_status") or "") != "claimed":
            raise LifecycleConflict("native spawn acknowledgement requires an active spawn claim")
        persisted_hash = str(state.get("spawn_claim_token_hash") or "")
        if not token_hash or not persisted_hash or not hmac.compare_digest(token_hash, persisted_hash):
            raise LifecycleConflict("native spawn claim token mismatch")
        existing_ref = str(state.get("provider_task_id") or "").strip() or None
        if existing_ref and task_ref and existing_ref != task_ref:
            raise LifecycleConflict("provider task ID cannot change after acknowledgement")
        state["provider_task_id"] = existing_ref or task_ref
        state["last_heartbeat"] = _now_iso()
        state["spawn_claim_token_hash"] = None
        state["spawn_claim_consumed_at"] = _now_iso()

        if state["provider_task_id"] or incoming in {"accepted", "created_with_task_id"}:
            if incoming == "created_with_task_id" and not state["provider_task_id"]:
                raise LifecycleConflict("created_with_task_id acknowledgement requires provider_task_id")
            state.update(
                {
                    "spawn_status": "created_with_task_id" if state["provider_task_id"] else "accepted",
                    "start_acknowledged": True,
                    "phase": "spawned",
                    "status": "running",
                    "spawn_allowed": False,
                    "fallback_allowed": False,
                    "spawn_claim_status": "consumed",
                }
            )
            return
        if incoming == "definitive_not_created":
            state.update(
                {
                    "spawn_status": "definitive_not_created",
                    "start_acknowledged": False,
                    "phase": "planned",
                    "status": "definitive_not_created",
                    "spawn_allowed": False,
                    "fallback_allowed": True,
                    "failure_domain": "native_transport_pre_creation",
                    "spawn_claim_status": "definitive_not_created",
                }
            )
            return
        if incoming in {"rejected", "unavailable", "indeterminate", "outcome_unknown", "unknown"}:
            state.update(
                {
                    "spawn_status": "outcome_unknown",
                    "phase": "reconciling",
                    "status": "reconciling",
                    "spawn_allowed": False,
                    "fallback_allowed": False,
                    "failure_domain": "native_transport_indeterminate",
                    "spawn_claim_status": "indeterminate",
                }
            )
            return
        raise LifecycleConflict(f"unsupported spawn acknowledgement: {incoming}")

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="acknowledge",
        expected_transport="native",
        allowed_phases={"spawn_requested"},
        operation_payload={
            "spawn_status": incoming,
            "provider_task_id": task_ref,
            "claim_token_hash": token_hash,
        },
        mutate=mutate,
    )


def attach_native_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    attach_status: str,
    idempotency_key: str,
    expected_attempt_id: str,
) -> dict[str, Any]:
    incoming = str(attach_status or "").strip().lower()

    def mutate(state: dict[str, Any]) -> None:
        if not state.get("start_acknowledged") and not state.get("provider_task_id"):
            raise LifecycleConflict("cannot attach before native start acknowledgement")
        state["last_heartbeat"] = _now_iso()
        if incoming in {"attached", "success"}:
            state.update({"phase": "attached", "status": "running", "attach_status": "attached"})
            return
        if incoming in {"failed", "timeout", "unknown", "indeterminate"}:
            state.update(
                {
                    "phase": "reconciling",
                    "status": "reconciling",
                    "attach_status": incoming,
                    "fallback_allowed": False,
                    "spawn_allowed": False,
                    "failure_domain": "native_attach",
                }
            )
            return
        raise LifecycleConflict(f"unsupported attach status: {incoming}")

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="attach",
        expected_transport="native",
        allowed_phases={"spawned"},
        operation_payload={"attach_status": incoming},
        mutate=mutate,
    )


def heartbeat_native_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    idempotency_key: str,
    expected_attempt_id: str,
    provider_state: str = "running",
    parent_heartbeat: str | None = None,
) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        if str(state.get("phase") or "") in TERMINAL_PHASES:
            raise LifecycleConflict("terminal native attempt cannot heartbeat")
        now = _now_iso()
        state["last_heartbeat"] = now
        state["parent_heartbeat"] = parent_heartbeat or now
        state["provider_state"] = str(provider_state or "running")
        if state.get("phase") == "attached":
            state["phase"] = "running"
        state["status"] = "running" if state.get("phase") != "reconciling" else "reconciling"

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="heartbeat",
        expected_transport="native",
        allowed_phases={"spawned", "attached", "running", "reconciling"},
        operation_payload={"provider_state": provider_state, "parent_heartbeat": parent_heartbeat},
        mutate=mutate,
    )


def complete_native_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    completion_signal: str,
    idempotency_key: str,
    expected_attempt_id: str,
    output_path: Path | str | None = None,
    failure_domain: str | None = None,
) -> dict[str, Any]:
    signal = str(completion_signal or "").strip().lower()
    requested_output_path = (
        str(Path(output_path).resolve(strict=False)) if output_path is not None else None
    )

    def mutate(state: dict[str, Any]) -> None:
        now = _now_iso()
        state["completion_signal"] = signal
        state["exit_code"] = None
        state["last_heartbeat"] = now
        state["terminated_at"] = now
        state["fallback_allowed"] = False
        state["spawn_allowed"] = False
        state["failure_domain"] = failure_domain or state.get("failure_domain")
        persisted_output_path = str(state.get("output_path") or "").strip() or None
        if requested_output_path and persisted_output_path and requested_output_path != persisted_output_path:
            raise LifecycleConflict("completion output path does not match persisted output_path")
        if requested_output_path and not persisted_output_path:
            raise LifecycleConflict("completion cannot introduce an unbound output_path")
        output = _file_evidence(persisted_output_path)
        if output:
            state["output_path"] = output["path"]
            state["output_hash"] = output["hash"]

        if signal in {"completed", "succeeded", "success"}:
            baseline = state.get("output_baseline")
            baseline_exists = bool(state.get("output_baseline_exists"))
            baseline_hash = state.get("output_baseline_hash")
            baseline_version = state.get("output_baseline_version")
            evidence_status: str | None = None
            if not isinstance(baseline, dict):
                evidence_status = "missing_output_baseline"
            elif not output or not output.get("exists"):
                evidence_status = "missing_result"
            elif int(output.get("size") or 0) == 0:
                evidence_status = "empty_result"
            elif baseline_exists:
                if output.get("hash") == baseline_hash and output.get("version") == baseline_version:
                    evidence_status = "unchanged_result"
                else:
                    evidence_status = "preexisting_result"

            state["output_freshness"] = {
                "baseline_exists": baseline_exists,
                "baseline_hash": baseline_hash,
                "baseline_version": baseline_version,
                "completion_exists": bool(output and output.get("exists")),
                "completion_hash": output.get("hash") if output else None,
                "completion_version": output.get("version") if output else None,
                "completion_size": output.get("size") if output else None,
                "valid": evidence_status is None,
                "reason": evidence_status,
            }
            if evidence_status is not None:
                state.update(
                    {
                        "phase": "failed",
                        "status": evidence_status,
                        "failure_domain": "output_evidence",
                    }
                )
                return
            state.update({"phase": "done", "status": "completed"})
            return
        if signal in {"failed", "error"}:
            state.update({"phase": "failed", "status": "failed", "failure_domain": failure_domain or "task"})
            return
        if signal in {"cancelled", "canceled"}:
            state.update({"phase": "terminated", "status": "cancelled", "cancel_status": "confirmed"})
            return
        if signal in {"timeout", "timed_out", "unknown", "indeterminate"}:
            state.update(
                {
                    "phase": "reconciling",
                    "status": "reconciling",
                    "failure_domain": failure_domain or "native_outcome_indeterminate",
                    "terminated_at": None,
                }
            )
            return
        raise LifecycleConflict(f"unsupported completion signal: {signal}")

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="complete",
        expected_transport="native",
        allowed_phases={"spawned", "attached", "running", "reconciling"},
        operation_payload={
            "completion_signal": signal,
            "output_path": requested_output_path,
            "failure_domain": failure_domain,
        },
        mutate=mutate,
    )


def request_external_fallback(
    *,
    base_dir: Path | str,
    task_id: str,
    idempotency_key: str,
    expected_attempt_id: str,
    attempt_id: str | None = None,
    orca_client: Any | None = None,
) -> dict[str, Any]:
    fallback_route: dict[str, Any] | None = None
    settings = _resolved_delegation_settings(base_dir)
    if settings.get("orca_enabled"):
        with _task_lock(base_dir, task_id):
            preview = _load_state(base_dir, task_id)
            if not isinstance(preview, dict):
                raise LifecycleConflict(f"delegation attempt not found for task {task_id}")
            _validate_persisted_session_identity(preview)
            _assert_attempt_cas(preview, expected_attempt_id, "fallback_route")
            preview_host = str(preview.get("host") or "headless")
            preview_provider = str(preview.get("provider") or "")
            preview_scope = str(preview.get("scope") or "implementation")
            preview_worktree = str(preview.get("worktree_dir") or "")
        fallback_route = resolve_delegation_route(
            base_dir=base_dir,
            host=preview_host,
            provider=preview_provider,
            scope=preview_scope,
            capability_status="unavailable",
            external_adapter_available=None,
            worktree_dir=preview_worktree,
            orca_client=orca_client,
        )
        if fallback_route.get("route") != "external":
            raise ExternalAdapterUnavailable(
                "missing_cli: definitive native non-creation fallback is not externally routable"
            )

    def mutate(state: dict[str, Any]) -> None:
        if (
            state.get("execution_transport") != "native"
            or state.get("spawn_status") != "definitive_not_created"
            or not state.get("fallback_allowed")
            or state.get("provider_task_id")
            or state.get("start_acknowledged")
        ):
            raise LifecycleConflict("external fallback is not allowed after native task creation or indeterminate outcome")
        native_attempt_id = str(state.get("attempt_id") or "")
        external_attempt_id = str(
            attempt_id or f"{state['task_id']}-external-{uuid.uuid4().hex[:12]}"
        )
        prompt_snapshot_artifact = _artifact_path(
            base_dir,
            task_id,
            None,
            "prompt-"
            + hashlib.sha256(external_attempt_id.encode("utf-8")).hexdigest()[:16]
            + ".snapshot.md",
        )
        context_snapshot_artifact, context_snapshot_bytes, context_snapshot_hash = (
            _mst_context_binding(
                base_dir=base_dir,
                task_id=task_id,
                attempt_id=external_attempt_id,
                mst_session_id=str(state.get("mst_session_id") or ""),
                root_mst_id=str(state.get("root_mst_id") or ""),
                raw_context=os.environ.get("MST_CONTEXT_JSON", ""),
            )
        )
        _atomic_write_private_bytes(context_snapshot_artifact, context_snapshot_bytes)
        prior_route_fingerprint = state.get("route_fingerprint")
        fallback_decision = dict(fallback_route) if isinstance(fallback_route, dict) else {
            "route": "external",
            "execution_transport": "external",
            "host": state.get("host"),
            "provider": state.get("provider"),
            "scope": state.get("scope"),
        }
        fallback_decision.update(
            {
                "reason_code": "external_fallback_after_definitive_not_created",
                "route_cause": "definitive_not_created",
                "source_route_fingerprint": prior_route_fingerprint,
            }
        )
        fallback_decision["route_fingerprint"] = _route_fingerprint(fallback_decision)
        _sync_attempt(state)
        for previous in state["attempts"]:
            previous["current_attempt"] = False
            if str(previous.get("attempt_id") or "") == native_attempt_id:
                previous["fallback_to"] = external_attempt_id
        fallback_now = datetime.now(timezone.utc)
        state.update(
            {
                "attempt_id": external_attempt_id,
                "execution_transport": "external",
                "launch_surface": str(
                    fallback_decision.get("launch_surface") or "direct"
                ),
                "requested_launch_surface": str(
                    fallback_decision.get("requested_launch_surface") or "direct"
                ),
                "launch_surface_status": str(
                    fallback_decision.get("launch_surface_status") or "disabled"
                ),
                "external_control_surface": "provider_cli_adapter",
                "route_reason": "external_fallback_after_definitive_not_created",
                "route_decision": fallback_decision,
                "route_fingerprint": fallback_decision["route_fingerprint"],
                "phase": "planned",
                "status": "fallback_requested",
                "fallback_from": native_attempt_id,
                "fallback_to": None,
                "fallback_allowed": False,
                "spawn_allowed": False,
                "provider_task_id": None,
                "pid": None,
                "exit_code": None,
                "completion_signal": None,
                "failure_domain": None,
                "started_at": fallback_now.isoformat(),
                "last_heartbeat": fallback_now.isoformat(),
                "external_claim_expires_at": _external_claim_expires_at(fallback_now),
                "orca_cli_argv": list(
                    (fallback_decision.get("orca_preflight") or {}).get("cli_argv") or []
                ),
                "orca_worktree_selector": (
                    (fallback_decision.get("orca_preflight") or {}).get(
                        "worktree_selector"
                    )
                ),
                "orca_terminal_title": None,
                "orca_terminal_handle": None,
                "orca_launch_status": (
                    "planned"
                    if fallback_decision.get("launch_surface") == "orca"
                    else "not_requested"
                ),
                "orca_launch_claim_owner": None,
                "orca_launch_claimed_at": None,
                "orca_create_invoked_at": None,
                "orca_reconciliation_required": False,
                "orca_reconciliation": None,
                "orca_cleanup_status": None,
                "prompt_snapshot_path": str(prompt_snapshot_artifact),
                "prompt_snapshot_hash": None,
                "prompt_snapshot_created_at": None,
                "mst_context_snapshot_path": str(context_snapshot_artifact),
                "mst_context_snapshot_hash": context_snapshot_hash,
                "output_claim_baseline": None,
                "io_exit_code": None,
            }
        )
    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="fallback",
        expected_transport="native",
        allowed_phases={"planned"},
        operation_payload={"external_attempt_id": attempt_id},
        mutate=mutate,
    )


def cancel_native_attempt(
    *, base_dir: Path | str, task_id: str, idempotency_key: str, expected_attempt_id: str
) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "native":
            raise LifecycleConflict("native cancellation requires a native current attempt")
        if str(state.get("phase") or "") in TERMINAL_PHASES:
            return
        if _native_spawn_claim_is_active(state):
            raise LifecycleConflict(
                "native spawn claim is still active; wait for acknowledgement or claim lease expiry"
            )
        if state.get("spawn_claim_status") == "claimed":
            _remove_private_claim_token_handle(base_dir, state)
            state.update(
                {
                    "spawn_claim_status": "indeterminate",
                    "spawn_claim_token_hash": None,
                    "spawn_claim_consumed_at": _now_iso(),
                }
            )
        state.update(
            {
                "phase": "reconciling",
                "status": "cancel_requested",
                "cancel_status": "unconfirmed",
                "cancel_requested_at": _now_iso(),
                "os_signal_attempted": False,
                "spawn_allowed": False,
                "fallback_allowed": False,
            }
        )

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="cancel",
        expected_transport="native",
        allowed_phases={"spawn_requested", "spawned", "attached", "running", "reconciling"},
        operation_payload={},
        mutate=mutate,
    )


def recover_native_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    idempotency_key: str,
    expected_attempt_id: str,
    provider_state: str = "unknown",
    parent_heartbeat: str | None = None,
    route_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "native":
            raise LifecycleConflict("native recovery requires a native current attempt")
        if str(state.get("phase") or "") in TERMINAL_PHASES:
            return
        if _native_spawn_claim_is_active(state):
            raise LifecycleConflict(
                "native spawn claim is still active; wait for acknowledgement or claim lease expiry"
            )
        if state.get("spawn_claim_status") == "claimed":
            _remove_private_claim_token_handle(base_dir, state)
            state.update(
                {
                    "spawn_claim_status": "indeterminate",
                    "spawn_claim_token_hash": None,
                    "spawn_claim_consumed_at": _now_iso(),
                }
            )
        persisted_provider_state = str(state.get("provider_state") or "unknown")
        provider_task_id = str(state.get("provider_task_id") or "") or None
        lookup_key = provider_task_id or f"attempt:{state.get('attempt_id')}"
        action_hash = hashlib.sha256(
            f"{state.get('provider')}:{lookup_key}:{state.get('attempt_id')}".encode("utf-8")
        ).hexdigest()[:24]
        action = {
            "kind": "provider_reconcile",
            "action_id": f"provider-reconcile:{action_hash}",
            "lookup_key": lookup_key,
            "provider": state.get("provider"),
            "provider_task_id": provider_task_id,
            "attempt_id": state.get("attempt_id"),
            "status": "pending",
            "completion_accepted": False,
            "requested_at": _now_iso(),
            "required_result_fields": ["provider_state", "completion_signal", "observed_at"],
        }
        state.update(
            {
                "phase": "reconciling",
                "status": "reconciling",
                "provider_reconciliation_required": True,
                "os_signal_attempted": False,
                "spawn_allowed": False,
                "fallback_allowed": False,
                "recovered_at": _now_iso(),
                "parent_heartbeat": parent_heartbeat or state.get("parent_heartbeat"),
                "recovery_evidence": {
                    "provider_state": persisted_provider_state,
                    "provider_task_id": provider_task_id,
                    "parent_heartbeat": parent_heartbeat or state.get("parent_heartbeat"),
                    "caller_provider_state_claim": str(provider_state or "unknown"),
                    "caller_claim_trusted": False,
                },
                "reconciliation_action": action,
                "route_validation": route_validation or state.get("route_validation"),
            }
        )

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="recover",
        expected_transport="native",
        allowed_phases={"spawn_requested", "spawned", "attached", "running", "reconciling"},
        operation_payload={"parent_heartbeat": parent_heartbeat, "route_validation": route_validation},
        mutate=mutate,
    )


def get_reconciliation_action(
    *, base_dir: Path | str, task_id: str, expected_attempt_id: str
) -> dict[str, Any]:
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"delegation attempt not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "reconcile_action")
        action = state.get("reconciliation_action")
        if (
            lifecycle_is_terminal(state)
            or state.get("provider_reconciliation_required") is not True
            or not isinstance(action, dict)
            or action.get("status") != "pending"
            or action.get("completion_accepted") is not False
        ):
            raise LifecycleConflict("no pending provider reconciliation action")
        return dict(action)


def start_external_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    provider: str,
    worktree_dir: Path | str,
    idempotency_key: str,
    route_reason: str,
    scope: str = "analysis",
    read_only: bool = True,
    prompt_file: Path | str | None = None,
    running_log_path: Path | str | None = None,
    trace_path: Path | str | None = None,
    output_path: Path | str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    reasoning_effort_source: str | None = None,
    mst_session_id: str | None = None,
    root_mst_id: str | None = None,
    parent_session_id: str | None = None,
    attempt_id: str | None = None,
    fallback_from: str | None = None,
    route_decision: dict[str, Any] | None = None,
    mst_context_json: str | None = None,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    normalized_provider = _normalized_provider(provider)
    identity = _canonical_delegation_identity(
        mst_session_id=mst_session_id,
        root_mst_id=root_mst_id,
        parent_session_id=parent_session_id,
    )
    resolved_attempt_id = str(attempt_id or f"{task_id}-external-{uuid.uuid4().hex[:12]}")
    running_artifact, trace_artifact, output_artifact = _lifecycle_artifact_paths(
        base_dir=base_dir,
        task_id=task_id,
        running_log_path=running_log_path,
        trace_path=trace_path,
        output_path=output_path,
    )
    prompt_snapshot_artifact = _artifact_path(
        base_dir,
        task_id,
        None,
        "prompt-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + ".snapshot.md",
    )
    context_snapshot_artifact, context_snapshot_bytes, context_snapshot_hash = (
        _mst_context_binding(
            base_dir=base_dir,
            task_id=task_id,
            attempt_id=str(attempt_id or key),
            mst_session_id=identity["mst_session_id"],
            root_mst_id=identity["root_mst_id"],
            raw_context=(
                mst_context_json
                if mst_context_json is not None
                else os.environ.get("MST_CONTEXT_JSON", "")
            ),
        )
    )
    _validate_external_control_plane_artifacts(
        base_dir=base_dir,
        task_id=task_id,
        worktree_dir=worktree_dir,
        artifacts={
            "prompt snapshot": prompt_snapshot_artifact,
            "MST context snapshot": context_snapshot_artifact,
            "running log": running_artifact,
            "trace": trace_artifact,
            "output": output_artifact,
        },
    )
    decision = dict(route_decision) if isinstance(route_decision, dict) else {
        "route": "external",
        "execution_transport": "external",
        "provider": normalized_provider,
        "reason_code": str(route_reason),
        "scope": str(scope),
    }
    decision.setdefault("route_fingerprint", _route_fingerprint(decision))
    if decision.get("route") != "external":
        raise LifecycleConflict("persisted route does not authorize external start")
    prompt_evidence = _file_evidence(prompt_file)
    output_evidence = _file_evidence(output_artifact)
    start_payload = {
        "attempt_id": attempt_id,
        "provider": normalized_provider,
        "worktree_dir": str(Path(worktree_dir).resolve(strict=False)),
        "scope": scope,
        "read_only": bool(read_only),
        "model": str(model) if model is not None else None,
        "reasoning_effort": str(reasoning_effort) if reasoning_effort is not None else None,
        "reasoning_effort_source": str(reasoning_effort_source) if reasoning_effort_source is not None else None,
        "mst_session_id": identity["mst_session_id"],
        "root_mst_id": identity["root_mst_id"],
        "parent_session_id": identity["parent_session_id"],
        "route_fingerprint": decision.get("route_fingerprint"),
        "launch_surface": decision.get("launch_surface", "direct"),
        "prompt_hash": prompt_evidence.get("hash") if prompt_evidence else None,
        "prompt_snapshot_path": str(prompt_snapshot_artifact),
        "mst_context_snapshot_hash": context_snapshot_hash,
        "running_log_path": str(running_artifact),
        "trace_path": str(trace_artifact),
        "output_path": str(output_artifact),
        "fallback_from": fallback_from,
    }
    start_fingerprint = _operation_fingerprint("external_start", "", start_payload)
    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        existing = _load_state(base_dir, task_id)
        if isinstance(existing, dict):
            _validate_persisted_session_identity(existing)
            if _exact_replay(
                existing,
                idempotency_key=key,
                operation="external_start",
                source_attempt_id="",
                fingerprint=start_fingerprint,
            ):
                return existing
        if isinstance(existing, dict) and str(existing.get("phase") or "") not in TERMINAL_PHASES:
            raise LifecycleConflict("task already has an active attempt")
        guard = validate_native_worktree(
            base_dir=base_dir,
            task_id=task_id,
            worktree_dir=worktree_dir,
            read_only=bool(read_only),
            scope=scope,
        )
        _prepare_lifecycle_artifact_paths(
            running_artifact,
            trace_artifact,
            output_artifact,
        )
        _atomic_write_private_bytes(context_snapshot_artifact, context_snapshot_bytes)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        state: dict[str, Any] = {
            "schema_version": 1,
            "mst_session_id": identity["mst_session_id"],
            "root_mst_id": identity["root_mst_id"],
            "parent_session_id": identity["parent_session_id"],
            "task_id": task_id,
            "attempt_id": resolved_attempt_id,
            "current_attempt": True,
            "execution_transport": "external",
            "launch_surface": str(decision.get("launch_surface") or "direct"),
            "requested_launch_surface": str(
                decision.get("requested_launch_surface") or "direct"
            ),
            "launch_surface_status": str(
                decision.get("launch_surface_status") or "disabled"
            ),
            "external_control_surface": "provider_cli_adapter",
            "host": str(decision.get("host") or "headless"),
            "provider": normalized_provider,
            "provider_task_id": None,
            "route_reason": str(route_reason),
            "route_decision": decision,
            "route_fingerprint": str(decision["route_fingerprint"]),
            "phase": "planned",
            "status": "planned",
            "spawn_allowed": False,
            "fallback_allowed": False,
            "fallback_from": fallback_from,
            "pid": None,
            "exit_code": None,
            "completion_signal": None,
            "external_claim_expires_at": _external_claim_expires_at(now_dt),
            "orca_cli_argv": list(
                (decision.get("orca_preflight") or {}).get("cli_argv") or []
            ),
            "orca_worktree_selector": (
                (decision.get("orca_preflight") or {}).get("worktree_selector")
            ),
            "orca_terminal_title": None,
            "orca_terminal_handle": None,
            "orca_launch_status": (
                "planned" if decision.get("launch_surface") == "orca" else "not_requested"
            ),
            "orca_launch_claim_owner": None,
            "orca_launch_claimed_at": None,
            "orca_create_invoked_at": None,
            "orca_reconciliation_required": False,
            "orca_reconciliation": None,
            "orca_cleanup_status": None,
            "failure_domain": None,
            "started_at": now,
            "last_heartbeat": now,
            "worktree_dir": str(Path(worktree_dir).resolve(strict=False)),
            "worktree_guard": guard,
            "scope": str(scope),
            "read_only": bool(read_only),
            "model": str(model) if model is not None else None,
            "reasoning_effort": str(reasoning_effort) if reasoning_effort is not None else None,
            "reasoning_effort_source": str(reasoning_effort_source) if reasoning_effort_source is not None else None,
            "prompt_file": prompt_evidence["path"] if prompt_evidence else None,
            "prompt_hash": prompt_evidence["hash"] if prompt_evidence else None,
            "prompt_snapshot_path": str(prompt_snapshot_artifact),
            "prompt_snapshot_hash": None,
            "prompt_snapshot_created_at": None,
            "mst_context_snapshot_path": str(context_snapshot_artifact),
            "mst_context_snapshot_hash": context_snapshot_hash,
            "context_files_read": [prompt_evidence] if prompt_evidence else [],
            "running_log_path": str(running_artifact),
            "log_path": str(running_artifact),
            "trace_path": str(trace_artifact),
            "output_path": output_evidence["path"] if output_evidence else str(output_artifact),
            "output_hash": output_evidence["hash"] if output_evidence else None,
            "output_baseline": output_evidence,
            "output_baseline_exists": bool(output_evidence and output_evidence.get("exists")),
            "output_baseline_hash": output_evidence.get("hash") if output_evidence else None,
            "output_baseline_version": output_evidence.get("version") if output_evidence else None,
            "output_claim_baseline": None,
            "io_exit_code": None,
            "attempts": [],
            "lifecycle_events": [],
            "idempotency_keys": {},
        }
        if isinstance(existing, dict):
            state["attempts"] = [dict(item) for item in existing.get("attempts", []) if isinstance(item, dict)]
        _record_event(
            state,
            "external_start",
            key,
            source_attempt_id="",
            fingerprint=start_fingerprint,
        )
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "external_start")
        return state


def _resolve_external_executable(provider: str, binary: Path | str | None) -> str:
    requested = str(binary).strip() if binary is not None else _external_binary(provider)
    if not requested:
        raise ExternalAdapterUnavailable(f"missing_cli: no binary configured for provider {provider}")
    if os.path.sep in requested:
        candidate = Path(requested)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        raise ExternalAdapterUnavailable(f"missing_cli: required binary '{requested}' is unavailable")
    resolved = shutil.which(requested)
    if not resolved:
        raise ExternalAdapterUnavailable(f"missing_cli: required binary '{requested}' is unavailable")
    return resolved


def _external_bound_path(
    state: dict[str, Any],
    field: str,
    requested: Path | str,
) -> Path:
    persisted_text = str(state.get(field) or "").strip()
    if not persisted_text:
        raise LifecycleConflict(f"external authorization is missing {field} binding")
    persisted = Path(persisted_text).resolve(strict=False)
    incoming = Path(requested).resolve(strict=False)
    if incoming != persisted:
        raise LifecycleConflict(f"external {field} does not match persisted binding")
    return persisted


def _validate_external_attempt_bindings(
    *,
    base_dir: Path | str,
    state: dict[str, Any],
    task_id: str,
    expected_attempt_id: str,
    provider: str,
    worktree_dir: Path | str,
    prompt_file: Path | str,
    prompt_snapshot_path: Path | str | None = None,
    model: str | None,
    scope: str,
    read_only: bool,
    running_log_path: Path | str,
    trace_path: Path | str,
    output_path: Path | str,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    _assert_attempt_cas(state, expected_attempt_id, "external_claim")
    if state.get("current_attempt") is not True:
        raise LifecycleConflict("external authorization is not the current attempt")
    if str(state.get("task_id") or "") != task_id:
        raise LifecycleConflict("external task does not match persisted binding")
    if state.get("execution_transport") != "external":
        raise LifecycleConflict("external claim cannot execute a native or non-external attempt")
    if state.get("provider_reconciliation_required"):
        raise LifecycleConflict("external authorization is reconciling")

    decision = _validate_persisted_route(state)
    if decision.get("route") != "external":
        raise LifecycleConflict("persisted route does not authorize external execution")
    normalized_provider = _normalized_provider(provider)
    if _normalized_provider(str(state.get("provider") or "")) != normalized_provider:
        raise LifecycleConflict("external provider does not match persisted binding")
    decision_provider = str(decision.get("provider") or "").strip()
    if decision_provider and _normalized_provider(decision_provider) != normalized_provider:
        raise LifecycleConflict("external route provider does not match persisted binding")

    persisted_worktree = _external_bound_path(state, "worktree_dir", worktree_dir)
    persisted_prompt = _external_bound_path(state, "prompt_file", prompt_file)
    if not persisted_prompt.is_file():
        raise LifecycleConflict(f"prompt file not found: {persisted_prompt}")
    try:
        prompt_bytes = persisted_prompt.read_bytes()
    except OSError as exc:
        raise LifecycleConflict(f"cannot read bound prompt file: {exc}") from exc
    prompt_hash = "sha256:" + hashlib.sha256(prompt_bytes).hexdigest()
    if prompt_hash != state.get("prompt_hash"):
        raise LifecycleConflict("external prompt hash does not match persisted binding")
    prompt_snapshot = _external_bound_path(
        state,
        "prompt_snapshot_path",
        prompt_snapshot_path,
    )

    persisted_model = str(state.get("model")) if state.get("model") is not None else None
    incoming_model = str(model) if model is not None else None
    if incoming_model != persisted_model:
        raise LifecycleConflict("external model does not match persisted binding")
    persisted_effort = (
        str(state.get("reasoning_effort"))
        if state.get("reasoning_effort") is not None
        else None
    )
    incoming_effort = str(reasoning_effort) if reasoning_effort is not None else None
    if incoming_effort != persisted_effort:
        raise LifecycleConflict("external reasoning effort does not match persisted binding")
    if str(scope) != str(state.get("scope")):
        raise LifecycleConflict("external scope does not match persisted binding")
    if bool(read_only) != bool(state.get("read_only")):
        raise LifecycleConflict("external read_only does not match persisted binding")

    running = _external_bound_path(state, "running_log_path", running_log_path)
    trace = _external_bound_path(state, "trace_path", trace_path)
    output = _external_bound_path(state, "output_path", output_path)
    _validate_external_control_plane_artifacts(
        base_dir=base_dir,
        task_id=task_id,
        worktree_dir=persisted_worktree,
        artifacts={
            "prompt snapshot": prompt_snapshot,
            "running log": running,
            "trace": trace,
            "output": output,
        },
    )
    if len({persisted_prompt, running, trace, output, prompt_snapshot}) != 5:
        raise LifecycleConflict(
            "external prompt/snapshot/running/trace/output artifact paths must be distinct"
        )
    guard = state.get("worktree_guard")
    if not isinstance(guard, dict) or guard.get("ok") is not True:
        raise LifecycleConflict("external authorization is missing worktree evidence")

    fallback_from = str(state.get("fallback_from") or "").strip()
    if fallback_from:
        current_attempt = str(state.get("attempt_id") or "")
        attempts = [item for item in state.get("attempts", []) if isinstance(item, dict)]
        source = next(
            (item for item in attempts if str(item.get("attempt_id") or "") == fallback_from),
            None,
        )
        if not isinstance(source, dict) or str(source.get("fallback_to") or "") != current_attempt:
            raise LifecycleConflict("external fallback lineage is incomplete")

    return {
        "provider": normalized_provider,
        "worktree_dir": persisted_worktree,
        "prompt_file": persisted_prompt,
        "prompt_hash": prompt_hash,
        "prompt_bytes": prompt_bytes,
        "prompt_snapshot_path": prompt_snapshot,
        "model": persisted_model,
        "reasoning_effort": persisted_effort,
        "reasoning_effort_source": state.get("reasoning_effort_source"),
        "scope": str(state.get("scope")),
        "read_only": bool(state.get("read_only")),
        "running_log_path": running,
        "trace_path": trace,
        "output_path": output,
    }


def claim_external_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    provider: str,
    worktree_dir: Path | str,
    prompt_file: Path | str,
    prompt_snapshot_path: Path | str | None = None,
    model: str | None,
    scope: str,
    read_only: bool,
    running_log_path: Path | str,
    trace_path: Path | str,
    output_path: Path | str,
    pid: int,
    pid_start_time: str | None,
    started_by_pid: int | None,
    idempotency_key: str,
    mst_session_id: str | None,
    reasoning_effort: str | None = None,
    _private_resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically consume one persisted external authorization.

    A claim is intentionally single-use: even an identical retry after the
    planned -> running transition is rejected before provider process spawn.
    """

    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    try:
        marker_pid = int(pid)
    except (TypeError, ValueError) as exc:
        raise LifecycleConflict("external claim requires a valid pid") from exc
    if marker_pid <= 0:
        raise LifecycleConflict("external claim requires a positive pid")
    identity = _canonical_delegation_identity(mst_session_id=mst_session_id)

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        if state.get("mst_session_id") != identity["mst_session_id"]:
            raise LifecycleConflict("external authorization MST_SESSION_ID mismatch")
        _assert_attempt_cas(state, expected_attempt_id, "external_claim")
        _assert_nonterminal_lifecycle(state, "issue external claim authority")
        phase = str(state.get("phase") or "").strip().lower()
        status = str(state.get("status") or "").strip().lower()
        if phase != "planned":
            raise LifecycleConflict(f"external claim requires planned phase, found '{phase or 'missing'}'")
        if status in {"stale", "orphaned", "reconciling", "cancel_requested"}:
            raise LifecycleConflict(f"external claim rejects stale/non-runnable status '{status}'")
        if state.get("external_claim_id") or state.get("external_claimed_at"):
            raise LifecycleConflict("external authorization was already claimed")
        expires_at = _parse_iso_datetime(state.get("external_claim_expires_at"))
        if expires_at is not None and datetime.now(timezone.utc) >= expires_at:
            raise LifecycleConflict("external authorization is stale and expired")
        if _idempotent_replay(state, key):
            raise LifecycleConflict("external authorization claim key was already consumed")

        bindings = _validate_external_attempt_bindings(
            base_dir=base_dir,
            state=state,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            provider=provider,
            worktree_dir=worktree_dir,
            prompt_file=prompt_file,
            prompt_snapshot_path=(
                prompt_snapshot_path or state.get("prompt_snapshot_path") or ""
            ),
            model=model,
            reasoning_effort=reasoning_effort,
            scope=scope,
            read_only=read_only,
            running_log_path=running_log_path,
            trace_path=trace_path,
            output_path=output_path,
        )
        guard = validate_native_worktree(
            base_dir=base_dir,
            task_id=task_id,
            worktree_dir=bindings["worktree_dir"],
            read_only=bindings["read_only"],
            scope=bindings["scope"],
        )
        now = _now_iso()
        claim_id = "claim-" + hashlib.sha256(
            f"{task_id}:{expected_attempt_id}:{marker_pid}:{now}:{uuid.uuid4().hex}".encode("utf-8")
        ).hexdigest()[:24]
        snapshot_evidence = _atomic_write_private_bytes(
            bindings["prompt_snapshot_path"],
            bindings["prompt_bytes"],
        )
        if snapshot_evidence.get("hash") != bindings["prompt_hash"]:
            raise LifecycleConflict("external prompt snapshot hash does not match authorization")
        output_claim_baseline = _truncate_external_output_for_claim(bindings["output_path"])
        if _private_resources is not None:
            _private_resources.clear()
            _private_resources.update(
                {
                    "prompt_bytes": bytes(bindings["prompt_bytes"]),
                    "prompt_hash": bindings["prompt_hash"],
                    "output_claim_baseline": dict(output_claim_baseline),
                    "output_fd": _open_claimed_external_output_fd(
                        bindings["output_path"],
                        output_claim_baseline,
                    ),
                }
            )
        state.update(
            {
                "phase": "running",
                "status": "running",
                "pid": marker_pid,
                "pid_start_time": str(pid_start_time or "").strip() or f"pid:{marker_pid}:claimed_at:{now}",
                "started_by_pid": int(started_by_pid) if started_by_pid else None,
                "external_claim_id": claim_id,
                "external_claimed_at": now,
                "external_claim_consumed_at": None,
                "prompt_snapshot_path": snapshot_evidence["path"],
                "prompt_snapshot_hash": snapshot_evidence["hash"],
                "prompt_snapshot_created_at": now,
                "prompt_snapshot_role": "audit_only",
                "artifact_binding_version": 2,
                "output_claim_baseline": output_claim_baseline,
                "output_claim": {
                    "canonical_path": output_claim_baseline["path"],
                    "parent_device": output_claim_baseline["parent_device"],
                    "parent_inode": output_claim_baseline["parent_inode"],
                    "baseline_kind": output_claim_baseline["kind"],
                    "baseline_device": output_claim_baseline["device"],
                    "baseline_inode": output_claim_baseline["inode"],
                    "baseline_link_count": output_claim_baseline["link_count"],
                    "fresh_inode": bool(output_claim_baseline.get("fresh_inode")),
                    "baseline_hash": output_claim_baseline["hash"],
                },
                "prompt_execution": {
                    "status": "captured",
                    "hash": bindings["prompt_hash"],
                    "byte_count": len(bindings["prompt_bytes"]),
                    "transport": "claim_memory",
                    "captured_at": now,
                },
                "output_hash": output_claim_baseline.get("hash"),
                "worktree_guard": guard,
                "exit_code": None,
                "completion_signal": None,
                "failure_domain": None,
                "last_heartbeat": now,
            }
        )
        claim_payload = {
            "provider": bindings["provider"],
            "worktree_dir": str(bindings["worktree_dir"]),
            "prompt_hash": bindings["prompt_hash"],
            "prompt_snapshot_hash": snapshot_evidence["hash"],
            "model": bindings["model"],
            "reasoning_effort": bindings["reasoning_effort"],
            "scope": bindings["scope"],
            "read_only": bindings["read_only"],
            "running_log_path": str(bindings["running_log_path"]),
            "trace_path": str(bindings["trace_path"]),
            "output_path": str(bindings["output_path"]),
            "pid": marker_pid,
        }
        fingerprint = _operation_fingerprint("external_claim", expected_attempt_id, claim_payload)
        _record_event(
            state,
            "external_claim",
            key,
            source_attempt_id=expected_attempt_id,
            fingerprint=fingerprint,
            claim_id=claim_id,
        )
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "external_claim")
        return state


def heartbeat_external_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    pid: int,
    monitor_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_heartbeat")
        _assert_nonterminal_lifecycle(state, "external heartbeat")
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external heartbeat requires a claimed external attempt")
        phase = str(state.get("phase") or "").strip().lower()
        if phase != "running":
            raise LifecycleConflict(f"external heartbeat cannot update phase '{phase or 'missing'}'")
        if int(state.get("pid") or 0) != int(pid):
            raise LifecycleConflict("external heartbeat pid does not match claim owner")
        if isinstance(monitor_updates, dict):
            for field in ("delegate_monitor", "delegate_io_attention_events"):
                if field in monitor_updates:
                    state[field] = monitor_updates[field]
        state["last_heartbeat"] = _now_iso()
        _sync_attempt(state)
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "external_heartbeat")
        return state


def _external_process_start_time(pid: int) -> str:
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        parts = text.rsplit(") ", 1)
        if len(parts) == 2:
            fields = parts[1].split()
            if len(fields) > 19:
                return "proc:" + fields[19]
    try:
        observed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = observed.stdout.strip() if observed.returncode == 0 else ""
    return "ps:" + value if value else ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _external_cancel_grace_seconds() -> float:
    raw = os.environ.get("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "").strip()
    try:
        value = float(raw) if raw else EXTERNAL_CANCEL_GRACE_SECONDS
    except ValueError:
        value = EXTERNAL_CANCEL_GRACE_SECONDS
    return min(10.0, max(EXTERNAL_CANCEL_POLL_SECONDS, value))


def attach_external_provider_process(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    claim_owner_pid: int,
    provider_pid: int,
    provider_pgid: int,
    provider_pid_start_time: str | None,
    prompt_execution_hash: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """CAS-bind the dedicated provider process group before waiting on it."""

    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    try:
        owner_pid = int(claim_owner_pid)
        child_pid = int(provider_pid)
        child_pgid = int(provider_pgid)
    except (TypeError, ValueError) as exc:
        raise LifecycleConflict("external provider attachment requires numeric process identities") from exc
    if owner_pid <= 0 or child_pid <= 0 or child_pgid <= 0:
        raise LifecycleConflict("external provider attachment requires positive process identities")
    if child_pgid != child_pid:
        raise LifecycleConflict("external provider must own a dedicated process group")

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_provider_attach")
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external provider attachment requires a claimed attempt")
        if str(state.get("phase") or "") != "running":
            raise LifecycleConflict("external provider attachment requires running phase")
        if int(state.get("pid") or 0) != owner_pid:
            raise LifecycleConflict("external provider attachment claim owner mismatch")
        if prompt_execution_hash != str(state.get("prompt_hash") or ""):
            raise LifecycleConflict("external provider prompt execution hash mismatch")

        existing_pid = state.get("provider_pid")
        existing_pgid = state.get("provider_pgid")
        existing_start = str(state.get("provider_pid_start_time") or "")
        incoming_start = str(provider_pid_start_time or "").strip()
        if not incoming_start:
            raise LifecycleConflict("external provider start identity is unavailable")
        if existing_pid is not None or existing_pgid is not None:
            if (
                int(existing_pid or 0) == child_pid
                and int(existing_pgid or 0) == child_pgid
                and existing_start == incoming_start
            ):
                return state
            raise LifecycleConflict("external provider attachment conflicts with persisted identity")
        _assert_nonterminal_lifecycle(state, "attach external provider authority")

        now = _now_iso()
        state.update(
            {
                "provider_pid": child_pid,
                "provider_pgid": child_pgid,
                "provider_pid_start_time": incoming_start,
                "provider_attached_at": now,
                "prompt_execution": {
                    **dict(state.get("prompt_execution") or {}),
                    "status": "provider_attached",
                    "hash": prompt_execution_hash,
                    "transport": "stdin_claimed_fd",
                },
                "last_heartbeat": now,
            }
        )
        fingerprint = _operation_fingerprint(
            "external_provider_attach",
            expected_attempt_id,
            {
                "claim_owner_pid": owner_pid,
                "provider_pid": child_pid,
                "provider_pgid": child_pgid,
                "provider_pid_start_time": incoming_start,
                "prompt_execution_hash": prompt_execution_hash,
            },
        )
        _record_event(
            state,
            "external_provider_attach",
            key,
            source_attempt_id=expected_attempt_id,
            fingerprint=fingerprint,
        )
        _sync_attempt(state)
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "external_provider_attach")
        return state


def release_external_provider_exec(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    claim_owner_pid: int,
    provider_pid: int,
    provider_pgid: int,
    provider_pid_start_time: str,
    gate_write_fd: int,
    idempotency_key: str,
) -> dict[str, Any]:
    """Linearize provider exec after attachment and before cancellation can commit."""

    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("external provider exec release requires idempotency_key")
    try:
        owner_pid = int(claim_owner_pid)
        child_pid = int(provider_pid)
        child_pgid = int(provider_pgid)
        control_fd = int(gate_write_fd)
    except (TypeError, ValueError) as exc:
        raise LifecycleConflict("external provider exec release requires numeric identities") from exc
    incoming_start = str(provider_pid_start_time or "").strip()
    if owner_pid <= 0 or child_pid <= 0 or child_pgid <= 0 or control_fd < 0 or not incoming_start:
        raise LifecycleConflict("external provider exec release identity is incomplete")

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_provider_exec_release")
        _assert_nonterminal_lifecycle(state, "release external provider exec authority")
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external provider exec release requires a claimed attempt")
        if str(state.get("phase") or "") != "running":
            raise LifecycleConflict("external provider exec release requires running phase")
        if int(state.get("pid") or 0) != owner_pid:
            raise LifecycleConflict("external provider exec release claim owner mismatch")
        if (
            int(state.get("provider_pid") or 0) != child_pid
            or int(state.get("provider_pgid") or 0) != child_pgid
            or str(state.get("provider_pid_start_time") or "") != incoming_start
        ):
            raise LifecycleConflict("external provider exec release attachment mismatch")
        if state.get("provider_exec_released_at"):
            raise LifecycleConflict("external provider exec gate was already released")

        now = _now_iso()
        authorize_fingerprint = _operation_fingerprint(
            "external_provider_exec_authorize",
            expected_attempt_id,
            {
                "claim_owner_pid": owner_pid,
                "provider_pid": child_pid,
                "provider_pgid": child_pgid,
                "provider_pid_start_time": incoming_start,
            },
        )
        state.update(
            {
                "provider_exec_release_status": "authorized",
                "provider_exec_authorized_at": now,
                "last_heartbeat": now,
            }
        )
        try:
            _record_event(
                state,
                "external_provider_exec_authorize",
                f"{key}:authorize",
                source_attempt_id=expected_attempt_id,
                fingerprint=authorize_fingerprint,
            )
            _sync_attempt(state)
            _atomic_save(native_state_path(base_dir, task_id), state)
            _append_history(base_dir, state, "external_provider_exec_authorize")
        except (OSError, ValueError) as exc:
            raise LifecycleConflict(
                f"external provider exec authorization evidence could not be persisted: {exc}"
            ) from exc

        try:
            written = os.write(control_fd, b"1")
        except OSError as exc:
            raise LifecycleConflict(f"external provider exec gate release failed: {exc}") from exc
        if written != 1:
            raise LifecycleConflict("external provider exec gate release was incomplete")

        try:
            state.update(
                {
                    "provider_exec_release_status": "released",
                    "provider_exec_released_at": now,
                    "prompt_execution": {
                        **dict(state.get("prompt_execution") or {}),
                        "status": "exec_released",
                        "transport": "stdin_claimed_fd",
                    },
                    "last_heartbeat": now,
                }
            )
            fingerprint = _operation_fingerprint(
                "external_provider_exec_release",
                expected_attempt_id,
                {
                    "claim_owner_pid": owner_pid,
                    "provider_pid": child_pid,
                    "provider_pgid": child_pgid,
                    "provider_pid_start_time": incoming_start,
                },
            )
            _record_event(
                state,
                "external_provider_exec_release",
                key,
                source_attempt_id=expected_attempt_id,
                fingerprint=fingerprint,
            )
            _sync_attempt(state)
            _atomic_save(native_state_path(base_dir, task_id), state)
            _append_history(base_dir, state, "external_provider_exec_release")
        except (OSError, ValueError) as exc:
            raise LifecycleConflict(
                f"external provider exec release evidence could not be persisted: {exc}"
            ) from exc
        return state


def record_external_prompt_delivery(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    claim_owner_pid: int,
    provider_pid: int,
    prompt_execution_hash: str,
    prompt_transport: str,
    idempotency_key: str,
) -> dict[str, Any]:
    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external prompt delivery requires a claimed attempt")
        if int(state.get("pid") or 0) != int(claim_owner_pid):
            raise LifecycleConflict("external prompt delivery claim owner mismatch")
        if int(state.get("provider_pid") or 0) != int(provider_pid):
            raise LifecycleConflict("external prompt delivery provider mismatch")
        if prompt_execution_hash != str(state.get("prompt_hash") or ""):
            raise LifecycleConflict("external prompt delivery hash mismatch")
        state["prompt_execution"] = {
            **dict(state.get("prompt_execution") or {}),
            "status": "delivered",
            "hash": prompt_execution_hash,
            "transport": str(prompt_transport),
            "delivered_at": _now_iso(),
        }

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="external_prompt_delivered",
        expected_transport="external",
        allowed_phases={"running"},
        operation_payload={
            "claim_owner_pid": int(claim_owner_pid),
            "provider_pid": int(provider_pid),
            "prompt_execution_hash": prompt_execution_hash,
            "prompt_transport": str(prompt_transport),
        },
        mutate=mutate,
    )


def _provider_identity_matches(
    *,
    provider_pid: int,
    provider_pgid: int,
    provider_pid_start_time: str,
) -> tuple[bool, str]:
    if not _pid_alive(provider_pid):
        return (not _process_group_alive(provider_pgid), "provider_gone")
    try:
        current_pgid = os.getpgid(provider_pid)
    except ProcessLookupError:
        return (not _process_group_alive(provider_pgid), "provider_gone")
    except OSError:
        return False, "provider_group_unverifiable"
    if int(current_pgid) != int(provider_pgid):
        return False, "provider_group_identity_mismatch"
    current_start = _external_process_start_time(provider_pid)
    if not provider_pid_start_time or not current_start:
        return False, "provider_start_identity_unverifiable"
    if current_start != provider_pid_start_time:
        return False, "provider_start_identity_mismatch"
    return True, "provider_identity_match"


def _terminate_external_provider_group(
    *,
    provider_pid: int,
    provider_pgid: int,
    provider_pid_start_time: str,
    allow_unverified_direct_child: bool,
) -> dict[str, Any]:
    identity_ok, identity_reason = _provider_identity_matches(
        provider_pid=provider_pid,
        provider_pgid=provider_pgid,
        provider_pid_start_time=provider_pid_start_time,
    )
    group_alive_before = _process_group_alive(provider_pgid)
    if not group_alive_before:
        return {
            "status": "already_gone",
            "identity_reason": identity_reason,
            "term_sent": False,
            "kill_sent": False,
            "group_observed_gone": True,
        }
    if not identity_ok and not allow_unverified_direct_child:
        return {
            "status": "identity_blocked",
            "identity_reason": identity_reason,
            "term_sent": False,
            "kill_sent": False,
            "group_observed_gone": False,
        }

    term_sent = False
    kill_sent = False
    term_error: str | None = None
    kill_error: str | None = None
    try:
        os.killpg(provider_pgid, signal.SIGTERM)
        term_sent = True
    except ProcessLookupError:
        pass
    except OSError as exc:
        term_error = _redact_secret_text(str(exc))
    deadline = time.monotonic() + _external_cancel_grace_seconds()
    while _process_group_alive(provider_pgid) and time.monotonic() < deadline:
        time.sleep(EXTERNAL_CANCEL_POLL_SECONDS)
    if _process_group_alive(provider_pgid):
        try:
            os.killpg(provider_pgid, signal.SIGKILL)
            kill_sent = True
        except ProcessLookupError:
            pass
        except OSError as exc:
            kill_error = _redact_secret_text(str(exc))
        deadline = time.monotonic() + _external_cancel_grace_seconds()
        while _process_group_alive(provider_pgid) and time.monotonic() < deadline:
            time.sleep(EXTERNAL_CANCEL_POLL_SECONDS)
    gone = not _process_group_alive(provider_pgid)
    return {
        "status": "terminated" if gone else "termination_unconfirmed",
        "identity_reason": identity_reason,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "term_error": term_error,
        "kill_error": kill_error,
        "group_observed_gone": gone,
    }


def request_external_cancel(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    signal_name: str,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized_signal = str(signal_name or "TERM").strip().upper()

    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "external" or not state.get(
            "external_claim_id"
        ):
            raise LifecycleConflict("external cancellation requires a claimed external attempt")
        if not state.get("pid"):
            raise LifecycleConflict("external cancellation requires a bound wrapper pid")
        state.update(
            {
                "phase": "cancel_requested",
                "status": "cancel_requested",
                "signal": normalized_signal,
                "cancel_requested_at": _now_iso(),
                "last_heartbeat": _now_iso(),
            }
        )

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="external_cancel_requested",
        expected_transport="external",
        allowed_phases={"running", "cancel_requested", "reconciling"},
        operation_payload={"signal": normalized_signal},
        mutate=mutate,
    )


def _external_reconciliation_action(
    state: dict[str, Any],
    *,
    next_operation: str,
    reason_code: str,
) -> dict[str, Any]:
    provider_pid = int(state.get("provider_pid") or 0) or None
    provider_pgid = int(state.get("provider_pgid") or 0) or None
    provider_start = str(state.get("provider_pid_start_time") or "") or None
    attempt_id = str(state.get("attempt_id") or "")
    lookup_key = (
        f"pid:{provider_pid}:pgid:{provider_pgid}:start:{provider_start}"
        if provider_pid and provider_pgid and provider_start
        else f"attempt:{attempt_id}"
    )
    action_hash = hashlib.sha256(
        f"{state.get('provider')}:{lookup_key}:{attempt_id}:{next_operation}".encode("utf-8")
    ).hexdigest()[:24]
    return {
        "kind": "provider_reconcile",
        "action_id": f"provider-reconcile:{action_hash}",
        "lookup_key": lookup_key,
        "provider": state.get("provider"),
        "provider_task_id": state.get("provider_task_id"),
        "provider_pid": provider_pid,
        "provider_pgid": provider_pgid,
        "provider_pid_start_time": provider_start,
        "attempt_id": attempt_id,
        "status": "pending",
        "completion_accepted": False,
        "requested_at": _now_iso(),
        "reason_code": str(reason_code),
        "next_operation": str(next_operation),
        "required_result_fields": [
            "provider_state",
            "completion_signal",
            "group_observed_gone",
            "observed_at",
        ],
    }


def mark_external_cancel_reconciling(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    reason_value = str(reason or "provider_identity_unverifiable").strip()

    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external reconciliation requires a claimed attempt")
        state.update(
            {
                "phase": "reconciling",
                "status": "reconciling",
                "failure_domain": "provider_identity_unverifiable",
                "provider_reconciliation_required": True,
                "reconciliation_action": _external_reconciliation_action(
                    state,
                    next_operation="inspect_external_provider_identity",
                    reason_code=reason_value,
                ),
                "provider_reap_evidence": {
                    "status": "identity_blocked",
                    "identity_reason": reason_value,
                    "group_observed_gone": False,
                },
                "last_heartbeat": _now_iso(),
            }
        )

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="external_cancel_reconcile_blocked",
        expected_transport="external",
        allowed_phases={"cancel_requested"},
        operation_payload={"reason": reason_value},
        mutate=mutate,
    )


def record_external_reap_unconfirmed(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    cancellation_requested: bool,
    provider_reap_evidence: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    evidence = dict(provider_reap_evidence)

    def mutate(state: dict[str, Any]) -> None:
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external reap reconciliation requires a claimed attempt")
        state.update(
            {
                "phase": "cancel_requested" if cancellation_requested else "reconciling",
                "status": "cancel_requested" if cancellation_requested else "reconciling",
                "failure_domain": "external_provider_group_unconfirmed",
                "provider_reconciliation_required": True,
                "reconciliation_action": _external_reconciliation_action(
                    state,
                    next_operation="reconcile_external_provider_group",
                    reason_code=str(evidence.get("status") or "provider_group_unconfirmed"),
                ),
                "provider_reap_evidence": evidence,
                "exit_code": None,
                "completion_signal": None,
                "terminated_at": None,
                "last_heartbeat": _now_iso(),
            }
        )
        if state.get("launch_surface") == "orca":
            state.update(
                {
                    "orca_reconciliation_required": True,
                    "orca_cleanup_status": "ready_to_preserve",
                    "orca_cleanup_ready_at": _now_iso(),
                }
            )

    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=idempotency_key,
        event="external_provider_reap_unconfirmed",
        expected_transport="external",
        allowed_phases={"running", "cancel_requested", "reconciling"},
        operation_payload={
            "cancellation_requested": bool(cancellation_requested),
            "provider_reap_evidence": evidence,
        },
        mutate=mutate,
    )


def finalize_external_attempt(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    pid: int,
    exit_code: int,
    io_exit_code: int = 0,
    completion_signal: str,
    running_log_path: Path | str,
    trace_path: Path | str,
    output_path: Path | str,
    idempotency_key: str,
    provider_pid: int | None = None,
    provider_pgid: int | None = None,
    provider_pid_start_time: str | None = None,
    provider_prompt_hash: str | None = None,
    provider_reap_evidence: dict[str, Any] | None = None,
    output_bytes: bytes | None = None,
    output_fd: int | None = None,
    stderr_evidence: dict[str, Any] | None = None,
    external_command_metadata: dict[str, Any] | None = None,
    external_execution_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")
    signal = str(completion_signal or "").strip().lower()
    if signal not in {"process_exit", "process_timeout", "process_cancelled"}:
        raise LifecycleConflict(f"unsupported external completion signal: {signal}")
    try:
        real_exit_code = int(exit_code)
        real_io_exit_code = int(io_exit_code)
        claim_pid = int(pid)
    except (TypeError, ValueError) as exc:
        raise LifecycleConflict("external finalization requires real pid and exit_code values") from exc

    with _worktree_lease_lock(base_dir), _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_finalize")
        if _idempotent_replay(state, key):
            raise LifecycleConflict("external finalization key was already consumed")
        _assert_nonterminal_lifecycle(state, "finalize external attempt")
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external finalization requires a claimed external attempt")
        if int(state.get("pid") or 0) != claim_pid:
            raise LifecycleConflict("external finalization pid does not match claim owner")
        phase = str(state.get("phase") or "").strip().lower()
        cancellation_recorded = phase in {"terminated", "cancel_requested"} or str(state.get("status") or "").lower() in {
            "cancelled",
            "canceled",
            "terminated",
            "cancel_requested",
        }
        will_cancel = cancellation_recorded or signal == "process_cancelled"
        publish_allowed = bool(
            not will_cancel
            and signal == "process_exit"
            and real_exit_code == 0
            and real_io_exit_code == 0
        )
        if phase != "running" and not cancellation_recorded:
            raise LifecycleConflict(f"external finalization cannot reanimate phase '{phase or 'missing'}'")

        running = _external_bound_path(state, "running_log_path", running_log_path)
        trace = _external_bound_path(state, "trace_path", trace_path)
        output = _external_bound_path(state, "output_path", output_path)
        claim_baseline = (
            state.get("output_claim_baseline")
            if isinstance(state.get("output_claim_baseline"), dict)
            else {}
        )
        publish_error: str | None = None
        try:
            if output_bytes is not None and publish_allowed:
                if output_fd is not None:
                    output_evidence = _publish_external_output_to_claimed_fd(
                        output_fd=int(output_fd),
                        path=output,
                        content=bytes(output_bytes),
                        claim_baseline=claim_baseline,
                    )
                else:
                    output_evidence = _atomic_publish_external_output(
                        output,
                        bytes(output_bytes),
                        claim_baseline,
                    )
            else:
                output_evidence = _external_output_evidence(
                    output,
                    claim_baseline,
                    require_baseline_inode=True,
                )
        except LifecycleConflict as exc:
            output_evidence = None
            publish_error = str(exc)
            real_io_exit_code = real_io_exit_code or 1
        prompt_snapshot = _file_evidence(state.get("prompt_snapshot_path"))
        prompt_snapshot_ok = bool(
            prompt_snapshot
            and prompt_snapshot.get("exists")
            and prompt_snapshot.get("hash") == state.get("prompt_snapshot_hash")
            and prompt_snapshot.get("hash") == state.get("prompt_hash")
        )
        execution_hash = str(provider_prompt_hash or "")
        prompt_execution_state = (
            state.get("prompt_execution")
            if isinstance(state.get("prompt_execution"), dict)
            else {}
        )
        prompt_execution_ok = bool(
            execution_hash
            and execution_hash == str(state.get("prompt_hash") or "")
            and execution_hash
            == str(prompt_execution_state.get("hash") or "")
            and str(prompt_execution_state.get("status") or "") == "delivered"
        )
        output_fresh = bool(
            output_evidence
            and output_evidence.get("exists")
            and int(output_evidence.get("size") or 0) > 0
            and output_evidence.get("hash") != claim_baseline.get("hash")
        )
        effective_signal = "process_cancelled" if cancellation_recorded else signal
        now = _now_iso()
        if effective_signal == "process_cancelled":
            terminal_phase = "terminated"
            terminal_status = "cancelled"
            failure_domain = "external_cancelled"
        elif effective_signal == "process_timeout":
            terminal_phase = "failed"
            terminal_status = "failed"
            failure_domain = "external_timeout"
        elif real_exit_code != 0:
            terminal_phase = "failed"
            terminal_status = "failed"
            failure_domain = "external_cli"
        elif real_io_exit_code != 0:
            terminal_phase = "failed"
            terminal_status = "failed"
            failure_domain = "external_output_io"
        elif not prompt_execution_ok:
            terminal_phase = "failed"
            terminal_status = "failed"
            failure_domain = "prompt_delivery_evidence"
        elif not output_fresh:
            terminal_phase = "failed"
            terminal_status = "empty_result"
            failure_domain = "output_evidence"
        else:
            terminal_phase = "done"
            terminal_status = "fallback_completed" if state.get("fallback_from") else "completed"
            failure_domain = None

        state.update(
            {
                "phase": terminal_phase,
                "status": terminal_status,
                "exit_code": real_exit_code,
                "io_exit_code": real_io_exit_code,
                "completion_signal": effective_signal,
                "failure_domain": failure_domain,
                "output_path": output_evidence["path"] if output_evidence else str(output),
                "output_hash": output_evidence["hash"] if output_evidence else None,
                "output_freshness": {
                    "status": "fresh" if output_fresh else "missing_empty_or_unchanged",
                    "baseline_hash": claim_baseline.get("hash"),
                    "observed_hash": output_evidence.get("hash") if output_evidence else None,
                    "observed_size": output_evidence.get("size") if output_evidence else None,
                },
                "output_publish": {
                    "status": (
                        "cancelled_not_published"
                        if will_cancel
                        else "not_published_non_success"
                        if not publish_allowed
                        else "published"
                        if output_evidence
                        and (
                            output_evidence.get("atomic_replace")
                            or output_evidence.get("descriptor_bound")
                        )
                        else "legacy_verified"
                        if output_evidence
                        else "failed"
                    ),
                    "hash": output_evidence.get("hash") if output_evidence else None,
                    "size": output_evidence.get("size") if output_evidence else None,
                    "device": output_evidence.get("device") if output_evidence else None,
                    "inode": output_evidence.get("inode") if output_evidence else None,
                    "atomic_replace": bool(output_evidence and output_evidence.get("atomic_replace")),
                    "descriptor_bound": bool(output_evidence and output_evidence.get("descriptor_bound")),
                    "published_at": output_evidence.get("published_at") if output_evidence else None,
                    "error": publish_error,
                },
                "prompt_snapshot_audit": {
                    "status": "match" if prompt_snapshot_ok else "drifted_or_missing",
                    "observed_hash": prompt_snapshot.get("hash") if prompt_snapshot else None,
                    "expected_hash": state.get("prompt_snapshot_hash"),
                    "audit_only": True,
                },
                "prompt_execution": {
                    **dict(state.get("prompt_execution") or {}),
                    "status": "verified" if prompt_execution_ok else "unverified",
                    "hash": execution_hash or (state.get("prompt_execution") or {}).get("hash"),
                    "verified_at": now,
                },
                "running_log_path": str(running),
                "log_path": str(running),
                "trace_path": str(trace),
                "last_heartbeat": now,
                "terminated_at": now,
                "external_claim_consumed_at": now,
                "provider_pid": int(provider_pid) if provider_pid else state.get("provider_pid"),
                "provider_pgid": int(provider_pgid) if provider_pgid else state.get("provider_pgid"),
                "provider_pid_start_time": (
                    str(provider_pid_start_time)
                    if provider_pid_start_time
                    else state.get("provider_pid_start_time")
                ),
            }
        )
        if isinstance(provider_reap_evidence, dict):
            state["provider_reap_evidence"] = dict(provider_reap_evidence)
        if isinstance(stderr_evidence, dict):
            state["stderr_evidence"] = stderr_evidence
        if isinstance(external_command_metadata, dict):
            state["external_command_metadata"] = external_command_metadata
        if isinstance(external_execution_binding, dict):
            state["external_execution_binding"] = external_execution_binding
        _settle_terminal_reconciliation(state)
        final_payload = {
            "pid": claim_pid,
            "provider_pid": int(provider_pid) if provider_pid else state.get("provider_pid"),
            "provider_pgid": int(provider_pgid) if provider_pgid else state.get("provider_pgid"),
            "provider_prompt_hash": execution_hash or None,
            "exit_code": real_exit_code,
            "io_exit_code": real_io_exit_code,
            "completion_signal": effective_signal,
            "running_log_path": str(running),
            "trace_path": str(trace),
            "output_path": str(output),
        }
        fingerprint = _operation_fingerprint("external_finalize", expected_attempt_id, final_payload)
        _record_event(
            state,
            "external_finalize",
            key,
            source_attempt_id=expected_attempt_id,
            fingerprint=fingerprint,
            exit_code=real_exit_code,
            completion_signal=effective_signal,
        )
        _atomic_save(native_state_path(base_dir, task_id), state)
        _append_history(base_dir, state, "external_finalize")
        return state


def reconcile_external_cancel_after_runner_loss(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Finish cancellation only when an orphaned provider group is attributable."""

    task_id = _validate_task_id(task_id)
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_cancel_reconcile")
        _assert_nonterminal_lifecycle(state, "reconcile external cancellation")
        if state.get("execution_transport") != "external" or not state.get("external_claim_id"):
            raise LifecycleConflict("external cancellation reconciliation requires a claimed attempt")
        if str(state.get("phase") or "") != "cancel_requested":
            raise LifecycleConflict("external cancellation reconciliation requires cancel_requested phase")
        owner_pid = int(state.get("pid") or 0)
        provider_pid = int(state.get("provider_pid") or 0)
        provider_pgid = int(state.get("provider_pgid") or 0)
        provider_start = str(state.get("provider_pid_start_time") or "")
        running_log = str(state.get("running_log_path") or "")
        trace_path = str(state.get("trace_path") or "")
        output_path = str(state.get("output_path") or "")
        prompt_hash = str((state.get("prompt_execution") or {}).get("hash") or state.get("prompt_hash") or "")

    if owner_pid > 0 and _pid_alive(owner_pid):
        raise LifecycleConflict("external runner is still alive; it owns provider reaping")

    if provider_pid <= 0 or provider_pgid <= 0:
        return record_external_reap_unconfirmed(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            cancellation_requested=False,
            provider_reap_evidence={
                "status": "runner_lost_before_provider_attach",
                "identity_reason": "provider_identity_was_not_persisted",
                "term_sent": False,
                "kill_sent": False,
                "group_observed_gone": False,
                "reaped_by_supervisor": False,
                "wrapper_crashed": True,
            },
            idempotency_key=f"{idempotency_key}:reap-unconfirmed",
        )
    elif not _process_group_alive(provider_pgid):
        reap = {
            "status": "provider_group_already_gone",
            "term_sent": False,
            "kill_sent": False,
            "group_observed_gone": True,
            "reaped_by_supervisor": False,
            "wrapper_crashed": True,
        }
    else:
        identity_ok, identity_reason = _provider_identity_matches(
            provider_pid=provider_pid,
            provider_pgid=provider_pgid,
            provider_pid_start_time=provider_start,
        )
        if not identity_ok:
            with _task_lock(base_dir, task_id):
                current = _load_state(base_dir, task_id)
                if not isinstance(current, dict):
                    raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
                _assert_attempt_cas(current, expected_attempt_id, "external_cancel_reconcile")
                _assert_nonterminal_lifecycle(current, "record external reconciliation")
                current.update(
                    {
                        "phase": "reconciling",
                        "status": "reconciling",
                        "failure_domain": "provider_identity_unverifiable",
                        "provider_reconciliation_required": True,
                        "reconciliation_action": _external_reconciliation_action(
                            current,
                            next_operation="inspect_external_provider_identity",
                            reason_code=identity_reason,
                        ),
                        "provider_reap_evidence": {
                            "status": "identity_blocked",
                            "identity_reason": identity_reason,
                            "group_observed_gone": False,
                            "wrapper_crashed": True,
                        },
                        "last_heartbeat": _now_iso(),
                    }
                )
                _sync_attempt(current)
                _atomic_save(native_state_path(base_dir, task_id), current)
                _append_history(base_dir, current, "external_cancel_reconcile_blocked")
                return current
        with _task_lock(base_dir, task_id):
            current = _load_state(base_dir, task_id)
            if not isinstance(current, dict):
                raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
            _assert_attempt_cas(current, expected_attempt_id, "external_cancel_reconcile")
            _assert_nonterminal_lifecycle(current, "terminate external provider group")
            if str(current.get("phase") or "") != "cancel_requested":
                raise LifecycleConflict(
                    "external provider termination requires cancel_requested phase"
                )
            if (
                int(current.get("provider_pid") or 0) != provider_pid
                or int(current.get("provider_pgid") or 0) != provider_pgid
                or str(current.get("provider_pid_start_time") or "") != provider_start
            ):
                raise LifecycleConflict(
                    "external provider identity changed before termination authority"
                )
            reap = _terminate_external_provider_group(
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start,
                allow_unverified_direct_child=False,
            )
        reap["reaped_by_supervisor"] = False
        reap["wrapper_crashed"] = True
        if reap.get("group_observed_gone") is not True:
            return record_external_reap_unconfirmed(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                cancellation_requested=True,
                provider_reap_evidence=reap,
                idempotency_key=f"{idempotency_key}:reap-unconfirmed",
            )

    return finalize_external_attempt(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        pid=owner_pid,
        exit_code=143,
        io_exit_code=0,
        completion_signal="process_cancelled",
        running_log_path=running_log,
        trace_path=trace_path,
        output_path=output_path,
        idempotency_key=idempotency_key,
        provider_pid=provider_pid or None,
        provider_pgid=provider_pgid or None,
        provider_pid_start_time=provider_start or None,
        provider_prompt_hash=prompt_hash or None,
        provider_reap_evidence=reap,
    )


def _external_command(
    *,
    provider: str,
    executable: str,
    prompt: str,
    worktree_dir: Path | str,
    model: str | None,
    read_only: bool,
    reasoning_effort: str | None = None,
) -> tuple[list[str], str]:
    worktree = str(Path(worktree_dir).resolve(strict=False))
    command = [executable]
    if provider == "codex":
        command.extend(["exec", "--sandbox", "read-only"] if read_only else ["exec", "--full-auto"])
        if model:
            command.extend(["-m", str(model)])
        if reasoning_effort:
            command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        command.extend(["-C", worktree, "-"])
        return command, "stdin"
    if provider == "claude":
        command.append("-p")
        if model:
            command.extend(["--model", str(model)])
        if reasoning_effort:
            command.extend(["--effort", str(reasoning_effort)])
        command.extend(["--permission-mode", "plan" if read_only else "acceptEdits", "--add-dir", worktree])
        return command, "stdin"
    if provider == "agy":
        command.extend(["--print", prompt])
        if reasoning_effort:
            command.extend(["--effort", str(reasoning_effort)])
        if not read_only:
            command.append("--dangerously-skip-permissions")
        command.extend(["--add-dir", worktree])
        return command, "argv_transient"
    raise ExternalAdapterUnavailable(f"missing_cli: no external adapter for provider {provider}")


def _redact_secret_text(value: str, limit: int = 2048) -> str:
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*[^\s]+",
        r"\1=[REDACTED]",
        value,
    )
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-[REDACTED]", redacted)
    return redacted[-limit:]


def _stderr_evidence(stderr: str) -> dict[str, Any]:
    raw = stderr or ""
    redacted_tail = _redact_secret_text(raw)
    return {
        "sha256": "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "byte_count": len(raw.encode("utf-8")),
        "truncated": len(raw) > len(redacted_tail),
        "redacted_tail": redacted_tail,
    }


def _external_command_metadata(
    *,
    provider: str,
    executable: str,
    model: str | None,
    worktree_dir: Path | str,
    prompt_hash: str | None,
    prompt_transport: str,
    read_only: bool,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    model_value = str(model or "")
    worktree_value = str(Path(worktree_dir).resolve(strict=False))
    return {
        "provider": provider,
        "binary_name": Path(executable).name,
        "prompt_transport": prompt_transport,
        "prompt_hash": prompt_hash,
        "model_hash": "sha256:" + hashlib.sha256(model_value.encode("utf-8")).hexdigest(),
        "reasoning_effort": reasoning_effort,
        "worktree_hash": "sha256:" + hashlib.sha256(worktree_value.encode("utf-8")).hexdigest(),
        "permission_profile": "read-only" if read_only else "workspace-write",
    }


def _atomic_write_runtime_bytes(path: Path, content: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.runtime")
    fd: int | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp, flags, 0o600)
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while persisting external runtime log")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temp, path)
    except OSError as exc:
        raise LifecycleConflict(f"external runtime log could not be persisted: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    evidence = _file_evidence(path)
    if not evidence or not evidence.get("exists"):
        raise LifecycleConflict("external runtime log evidence is missing")
    return evidence


def _temporary_stage_bytes(handle: Any) -> bytes:
    try:
        size = int(os.fstat(handle.fileno()).st_size)
        return os.pread(handle.fileno(), size, 0) if size > 0 else b""
    except OSError as exc:
        raise LifecycleConflict(f"external anonymous output stage cannot be read: {exc}") from exc


def _protected_external_output_patterns(provider_env: dict[str, str]) -> tuple[bytes, ...]:
    """Return exact encodings that must never reach persisted provider output."""

    context = str(provider_env.get("MST_CONTEXT_JSON") or "")
    if not context:
        return ()
    candidates = {
        context,
        json.dumps(context, ensure_ascii=False)[1:-1],
        json.dumps(context, ensure_ascii=True)[1:-1],
    }
    return tuple(
        sorted(
            (value.encode("utf-8") for value in candidates if value),
            key=len,
            reverse=True,
        )
    )


def _redact_protected_external_output(
    content: bytes | None,
    protected_patterns: tuple[bytes, ...],
) -> bytes:
    redacted = bytes(content or b"")
    replacement = b"[REDACTED_MST_CONTEXT_JSON]"
    for pattern in protected_patterns:
        redacted = redacted.replace(pattern, replacement)
    return redacted


def run_external_adapter(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    provider: str,
    prompt_file: Path | str,
    worktree_dir: Path | str,
    output_path: Path | str,
    idempotency_key: str,
    binary: Path | str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    scope: str = "implementation",
    read_only: bool = False,
    monitor_callback: Callable[[dict[str, Any], Path], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Claim, supervise, publish, and finalize one protected external attempt."""

    normalized_provider = _normalized_provider(provider)
    prompt_path = Path(prompt_file).resolve(strict=False)
    resolved_worktree = Path(worktree_dir).resolve(strict=False)
    resolved_output = Path(output_path).resolve(strict=False)
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("idempotency_key is required")

    with _task_lock(base_dir, task_id):
        prepared = _load_state(base_dir, task_id)
        if not isinstance(prepared, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(prepared)
        _assert_attempt_cas(prepared, expected_attempt_id, "external_run")
        if _idempotent_replay(prepared, key):
            return prepared
        _assert_nonterminal_lifecycle(prepared, "run external adapter")
        decision = _validate_persisted_route(prepared)
        if decision.get("route") != "external" or prepared.get("execution_transport") != "external":
            raise LifecycleConflict("external adapter cannot execute a native or non-external attempt")
        phase = str(prepared.get("phase") or "")
        if phase != "planned":
            raise LifecycleConflict(f"external adapter cannot execute from phase '{phase}'")
        if normalized_provider != _normalized_provider(str(prepared.get("provider") or "")):
            raise LifecycleConflict("external provider does not match persisted provider binding")
        if resolved_worktree != Path(str(prepared.get("worktree_dir") or "")).resolve(strict=False):
            raise LifecycleConflict("external worktree does not match persisted worktree binding")
        if prompt_path != Path(str(prepared.get("prompt_file") or "")).resolve(strict=False):
            raise LifecycleConflict("external prompt path does not match persisted prompt binding")
        if resolved_output != Path(str(prepared.get("output_path") or "")).resolve(strict=False):
            raise LifecycleConflict("external output path does not match persisted output binding")
        persisted_model = str(prepared.get("model")) if prepared.get("model") is not None else None
        requested_model = str(model) if model is not None else None
        if requested_model != persisted_model:
            raise LifecycleConflict("external model does not match persisted model binding")
        persisted_effort = (
            str(prepared.get("reasoning_effort"))
            if prepared.get("reasoning_effort") is not None
            else None
        )
        requested_effort = str(reasoning_effort) if reasoning_effort is not None else None
        if requested_effort != persisted_effort:
            raise LifecycleConflict("external reasoning effort does not match persisted binding")
        if str(scope) != str(prepared.get("scope")):
            raise LifecycleConflict("external scope does not match persisted scope binding")
        if bool(read_only) != bool(prepared.get("read_only")):
            raise LifecycleConflict("external read_only does not match persisted read_only binding")
        running_log = Path(str(prepared.get("running_log_path") or "")).resolve(strict=False)
        trace_path = Path(str(prepared.get("trace_path") or "")).resolve(strict=False)
        snapshot_path = Path(str(prepared.get("prompt_snapshot_path") or "")).resolve(strict=False)
        persisted_session_id = str(prepared.get("mst_session_id") or "").strip() or None
        context_binding_required = bool(
            prepared.get("mst_context_snapshot_path")
            or prepared.get("mst_context_snapshot_hash")
            or prepared.get("launch_surface") == "orca"
            or prepared.get("requested_launch_surface") == "orca"
        )

    effective_env = dict(os.environ if env is None else env)
    inherited_context = effective_env.get("MST_CONTEXT_JSON")
    if context_binding_required or str(inherited_context or "").strip():
        effective_env["MST_CONTEXT_JSON"] = load_persisted_mst_context(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            inherited_context=inherited_context,
        )

    # Missing binaries remain a definitive pre-creation failure. Every failure
    # after the claim is terminal and consumes the authorization.
    executable = _resolve_external_executable(normalized_provider, binary)
    process: subprocess.Popen[bytes] | None = None
    prompt_stage: Any = None
    gate_config_stage: Any = None
    stdout_stage: Any = None
    stderr_stage: Any = None
    protected_output_patterns: tuple[bytes, ...] = ()
    gate_read_fd: int | None = None
    gate_write_fd: int | None = None
    claimed_output_fd: int | None = None
    private_resources: dict[str, Any] = {}
    observed_signals: list[int] = []

    def observe_signal(signum: int, _frame: Any) -> None:
        observed_signals.append(signum)
        if process is not None:
            try:
                os.killpg(process.pid, signum)
            except OSError:
                pass

    can_install_handlers = threading.current_thread() is threading.main_thread()
    previous_handlers: dict[int, Any] = {}
    if can_install_handlers:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, observe_signal)

    try:
        claim = claim_external_attempt(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            provider=normalized_provider,
            worktree_dir=resolved_worktree,
            prompt_file=prompt_path,
            prompt_snapshot_path=snapshot_path,
            model=persisted_model,
            reasoning_effort=persisted_effort,
            scope=scope,
            read_only=read_only,
            running_log_path=running_log,
            trace_path=trace_path,
            output_path=resolved_output,
            pid=os.getpid(),
            pid_start_time=_external_process_start_time(os.getpid()) or f"runner:{os.getpid()}",
            started_by_pid=os.getppid(),
            idempotency_key=f"{key}:claim",
            mst_session_id=persisted_session_id,
            _private_resources=private_resources,
        )
        prompt_bytes = bytes(private_resources.get("prompt_bytes") or b"")
        prompt_execution_hash = str(private_resources.get("prompt_hash") or "")
        claimed_output_fd = int(private_resources["output_fd"])
        if not prompt_execution_hash or prompt_execution_hash != str(claim.get("prompt_hash") or ""):
            raise LifecycleConflict("claimed prompt bytes are unavailable to the external supervisor")
        try:
            prompt_text = prompt_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return finalize_external_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                pid=os.getpid(),
                exit_code=127,
                io_exit_code=1,
                completion_signal="process_exit",
                running_log_path=running_log,
                trace_path=trace_path,
                output_path=resolved_output,
                idempotency_key=key,
                provider_prompt_hash=prompt_execution_hash,
                stderr_evidence=_stderr_evidence(str(exc)),
            )

        command, prompt_transport = _external_command(
            provider=normalized_provider,
            executable=executable,
            prompt=prompt_text,
            worktree_dir=resolved_worktree,
            model=persisted_model,
            reasoning_effort=persisted_effort,
            read_only=read_only,
        )
        command_metadata = _external_command_metadata(
            provider=normalized_provider,
            executable=executable,
            model=persisted_model,
            reasoning_effort=persisted_effort,
            worktree_dir=resolved_worktree,
            prompt_hash=prompt_execution_hash,
            prompt_transport="stdin_claimed_fd" if prompt_transport == "stdin" else prompt_transport,
            read_only=read_only,
        )
        run_payload = {
            "provider": normalized_provider,
            "prompt_file": str(prompt_path),
            "prompt_snapshot_path": str(claim.get("prompt_snapshot_path") or ""),
            "prompt_hash": prompt_execution_hash,
            "prompt_source": "claim_memory",
            "model": persisted_model,
            "reasoning_effort": persisted_effort,
            "worktree_dir": str(resolved_worktree),
            "output_path": str(resolved_output),
            "timeout": timeout,
            "scope": scope,
            "read_only": read_only,
            "route_fingerprint": claim.get("route_fingerprint"),
        }

        with _task_lock(base_dir, task_id):
            pre_spawn_state = _load_state(base_dir, task_id) or {}
            _assert_attempt_cas(pre_spawn_state, expected_attempt_id, "external_pre_spawn")
            _assert_nonterminal_lifecycle(
                pre_spawn_state,
                "release external provider spawn authority",
            )
            pre_spawn_phase = str(pre_spawn_state.get("phase") or "")
        if observed_signals or pre_spawn_phase == "cancel_requested":
            return finalize_external_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                pid=os.getpid(),
                exit_code=(
                    130
                    if observed_signals and observed_signals[-1] == signal.SIGINT
                    else 143
                ),
                io_exit_code=0,
                completion_signal="process_cancelled",
                running_log_path=running_log,
                trace_path=trace_path,
                output_path=resolved_output,
                idempotency_key=key,
                provider_prompt_hash=prompt_execution_hash,
                provider_reap_evidence={
                    "status": "cancelled_before_provider_spawn",
                    "group_observed_gone": True,
                },
                external_command_metadata=command_metadata,
                external_execution_binding=run_payload,
            )
        if pre_spawn_phase != "running":
            raise LifecycleConflict(
                f"external provider gate cannot start from phase '{pre_spawn_phase or 'missing'}'"
            )

        try:
            if prompt_transport == "stdin":
                prompt_stage = tempfile.TemporaryFile(mode="w+b")
                written = prompt_stage.write(prompt_bytes)
                if written is not None and int(written) != len(prompt_bytes):
                    raise OSError("anonymous prompt stage accepted a partial write")
                prompt_stage.flush()
                os.fsync(prompt_stage.fileno())
                prompt_stage.seek(0)
            gate_config_stage = tempfile.TemporaryFile(mode="w+b")
            provider_env = dict(effective_env)
            protected_output_patterns = _protected_external_output_patterns(provider_env)
            # Orca selects the outer launch surface only. The provider process
            # must never inherit wrapper flags or credentials from that CLI.
            provider_env.pop("ORCA_CLI_COMMAND", None)
            gate_config = json.dumps(
                {"argv": command, "env": provider_env},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            written = gate_config_stage.write(gate_config)
            if written is not None and int(written) != len(gate_config):
                raise OSError("anonymous provider gate config accepted a partial write")
            gate_config_stage.flush()
            os.fsync(gate_config_stage.fileno())
            gate_config_stage.seek(0)
            gate_read_fd, gate_write_fd = os.pipe()
            gate_env = {
                "LC_ALL": "C",
                "MST_EXTERNAL_EXEC_GATE_FD": str(gate_read_fd),
                "MST_EXTERNAL_EXEC_CONFIG_FD": str(gate_config_stage.fileno()),
            }
            stdout_stage = tempfile.TemporaryFile(mode="w+b")
            stderr_stage = tempfile.TemporaryFile(mode="w+b")
            with _task_lock(base_dir, task_id):
                pre_popen_state = _load_state(base_dir, task_id) or {}
                _assert_attempt_cas(
                    pre_popen_state,
                    expected_attempt_id,
                    "external_pre_popen",
                )
                _assert_nonterminal_lifecycle(
                    pre_popen_state,
                    "spawn external provider gate",
                )
                if str(pre_popen_state.get("phase") or "") != "running":
                    raise LifecycleConflict(
                        "external provider gate requires running phase immediately before spawn"
                    )
                process = subprocess.Popen(
                    [sys.executable, "-I", "-S", "-c", _EXTERNAL_EXEC_GATE_CODE],
                    cwd=resolved_worktree,
                    stdin=prompt_stage if prompt_transport == "stdin" else subprocess.DEVNULL,
                    stdout=stdout_stage,
                    stderr=stderr_stage,
                    text=False,
                    env=gate_env,
                    pass_fds=(gate_read_fd, gate_config_stage.fileno()),
                    start_new_session=True,
                )
            os.close(gate_read_fd)
            gate_read_fd = None
        except OSError as exc:
            return finalize_external_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                pid=os.getpid(),
                exit_code=127,
                io_exit_code=0,
                completion_signal="process_exit",
                running_log_path=running_log,
                trace_path=trace_path,
                output_path=resolved_output,
                idempotency_key=key,
                provider_prompt_hash=prompt_execution_hash,
                stderr_evidence=_stderr_evidence(str(exc)),
                external_command_metadata=command_metadata,
                external_execution_binding=run_payload,
            )

        provider_pid = int(process.pid)
        try:
            provider_pgid = int(os.getpgid(provider_pid))
        except OSError:
            provider_pgid = provider_pid
        provider_start_time = _external_process_start_time(provider_pid)
        try:
            attach_external_provider_process(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                claim_owner_pid=os.getpid(),
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start_time,
                prompt_execution_hash=prompt_execution_hash,
                idempotency_key=f"{key}:provider-attach",
            )
            if observed_signals:
                raise LifecycleConflict("external provider exec release was cancelled")
            if gate_write_fd is None:
                raise LifecycleConflict("external provider exec gate descriptor is unavailable")
            release_external_provider_exec(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                claim_owner_pid=os.getpid(),
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start_time,
                gate_write_fd=gate_write_fd,
                idempotency_key=f"{key}:provider-exec-release",
            )
            os.close(gate_write_fd)
            gate_write_fd = None
        except LifecycleConflict as exc:
            if gate_write_fd is not None:
                try:
                    os.close(gate_write_fd)
                except OSError:
                    pass
                gate_write_fd = None
            reap = _terminate_external_provider_group(
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start_time,
                allow_unverified_direct_child=True,
            )
            try:
                process.wait(timeout=_external_cancel_grace_seconds())
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(provider_pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as signal_exc:
                    reap["post_wait_kill_error"] = _redact_secret_text(str(signal_exc))
                try:
                    process.wait(timeout=_external_cancel_grace_seconds())
                except subprocess.TimeoutExpired:
                    pass
            group_observed_gone = not _process_group_alive(provider_pgid)
            reap.update(
                {
                    "status": (
                        "reaped_after_provider_attach_failure"
                        if group_observed_gone
                        else "termination_unconfirmed"
                    ),
                    "group_observed_gone": group_observed_gone,
                    "reaped_by_supervisor": True,
                    "provider_returncode": process.returncode,
                    "provider_attach_error": _redact_secret_text(str(exc)),
                }
            )
            cancelling = bool(observed_signals)
            current = _load_state(base_dir, task_id) or {}
            cancelling = cancelling or str(current.get("phase") or "") == "cancel_requested"
            if not group_observed_gone:
                return record_external_reap_unconfirmed(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=expected_attempt_id,
                    cancellation_requested=cancelling,
                    provider_reap_evidence=reap,
                    idempotency_key=f"{key}:attach-reap-unconfirmed",
                )
            return finalize_external_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                pid=os.getpid(),
                exit_code=143 if cancelling else 126,
                io_exit_code=0,
                completion_signal="process_cancelled" if cancelling else "process_exit",
                running_log_path=running_log,
                trace_path=trace_path,
                output_path=resolved_output,
                idempotency_key=key,
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start_time,
                provider_prompt_hash=prompt_execution_hash,
                provider_reap_evidence=reap,
                stderr_evidence=_stderr_evidence(str(exc)),
                external_command_metadata=command_metadata,
                external_execution_binding=run_payload,
            )

        stdout = b""
        stderr = b""
        started_monotonic = time.monotonic()
        cancel_started_at: float | None = None
        timeout_started_at: float | None = None
        cancel_term_attempted = False
        cancel_kill_attempted = False
        cancel_term_sent = False
        cancel_kill_sent = False
        cancel_term_error: str | None = None
        cancel_kill_error: str | None = None
        live_termination_unconfirmed = False
        timed_out = False
        prompt_io_failed = False
        if not prompt_io_failed:
            try:
                record_external_prompt_delivery(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=expected_attempt_id,
                    claim_owner_pid=os.getpid(),
                    provider_pid=provider_pid,
                    prompt_execution_hash=prompt_execution_hash,
                    prompt_transport="stdin_claimed_fd" if prompt_transport == "stdin" else prompt_transport,
                    idempotency_key=f"{key}:prompt-delivery",
                )
            except LifecycleConflict:
                prompt_io_failed = True

        raw_heartbeat_interval = os.environ.get("MST_DISPATCH_HEARTBEAT_INTERVAL", "").strip()
        try:
            heartbeat_interval = float(raw_heartbeat_interval) if raw_heartbeat_interval else 120.0
        except ValueError:
            heartbeat_interval = 120.0
        heartbeat_interval = min(120.0, max(EXTERNAL_CANCEL_POLL_SECONDS, heartbeat_interval))
        next_heartbeat = started_monotonic + heartbeat_interval
        while process.poll() is None:
            current_state = _load_state(base_dir, task_id) or {}
            cancellation_requested = bool(observed_signals) or str(current_state.get("phase") or "") == "cancel_requested"
            now_monotonic = time.monotonic()
            if cancellation_requested:
                if cancel_started_at is None:
                    cancel_started_at = now_monotonic
                if not cancel_term_attempted:
                    cancel_term_attempted = True
                    try:
                        os.killpg(provider_pgid, signal.SIGTERM)
                        cancel_term_sent = True
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        cancel_term_error = _redact_secret_text(str(exc))
                if (
                    not cancel_kill_attempted
                    and now_monotonic - cancel_started_at >= _external_cancel_grace_seconds()
                    and _process_group_alive(provider_pgid)
                ):
                    cancel_kill_attempted = True
                    try:
                        os.killpg(provider_pgid, signal.SIGKILL)
                        cancel_kill_sent = True
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        cancel_kill_error = _redact_secret_text(str(exc))
                if (
                    now_monotonic - cancel_started_at >= 2 * _external_cancel_grace_seconds()
                    and process.poll() is None
                ):
                    live_termination_unconfirmed = True
                    break
            if timeout is not None and now_monotonic - started_monotonic >= max(0, int(timeout)):
                timed_out = True
                if timeout_started_at is None:
                    timeout_started_at = now_monotonic
                if not cancel_kill_attempted:
                    cancel_kill_attempted = True
                    try:
                        os.killpg(provider_pgid, signal.SIGKILL)
                        cancel_kill_sent = True
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        cancel_kill_error = _redact_secret_text(str(exc))
                if (
                    now_monotonic - timeout_started_at >= _external_cancel_grace_seconds()
                    and process.poll() is None
                ):
                    live_termination_unconfirmed = True
                    break
            if now_monotonic >= next_heartbeat:
                try:
                    staged_stdout = _redact_protected_external_output(
                        _temporary_stage_bytes(stdout_stage), protected_output_patterns
                    )
                    staged_stderr = _redact_protected_external_output(
                        _temporary_stage_bytes(stderr_stage), protected_output_patterns
                    )
                    _atomic_write_runtime_bytes(running_log, staged_stdout + staged_stderr)
                    monitor_updates = (
                        monitor_callback(current_state, running_log)
                        if monitor_callback is not None
                        else None
                    )
                    heartbeat_external_attempt(
                        base_dir=base_dir,
                        task_id=task_id,
                        expected_attempt_id=expected_attempt_id,
                        pid=os.getpid(),
                        monitor_updates=monitor_updates,
                    )
                except LifecycleConflict:
                    pass
                next_heartbeat = now_monotonic + heartbeat_interval
            time.sleep(EXTERNAL_CANCEL_POLL_SECONDS)

        if live_termination_unconfirmed and process.poll() is None:
            stdout = _redact_protected_external_output(
                _temporary_stage_bytes(stdout_stage), protected_output_patterns
            )
            stderr = _redact_protected_external_output(
                _temporary_stage_bytes(stderr_stage), protected_output_patterns
            )
            reap_evidence = {
                "status": "termination_unconfirmed",
                "identity_reason": "provider_process_remained_live_after_bounded_signals",
                "term_attempted": cancel_term_attempted,
                "term_sent": cancel_term_sent,
                "term_error": cancel_term_error,
                "kill_attempted": cancel_kill_attempted,
                "kill_sent": cancel_kill_sent,
                "kill_error": cancel_kill_error,
                "group_observed_gone": False,
                "reaped_by_supervisor": False,
                "provider_returncode": None,
            }
            try:
                _atomic_write_runtime_bytes(running_log, (stdout or b"") + (stderr or b""))
            except LifecycleConflict as exc:
                reap_evidence["running_log_error"] = str(exc)
            return record_external_reap_unconfirmed(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                cancellation_requested=bool(observed_signals)
                or str((_load_state(base_dir, task_id) or {}).get("phase") or "")
                == "cancel_requested",
                provider_reap_evidence=reap_evidence,
                idempotency_key=f"{key}:live-reap-unconfirmed",
            )

        process.wait()
        stdout = _redact_protected_external_output(
            _temporary_stage_bytes(stdout_stage), protected_output_patterns
        )
        stderr = _redact_protected_external_output(
            _temporary_stage_bytes(stderr_stage), protected_output_patterns
        )

        cancelled = bool(observed_signals) or str((_load_state(base_dir, task_id) or {}).get("phase") or "") == "cancel_requested"
        group_alive_after_wait = _process_group_alive(provider_pgid)
        if group_alive_after_wait:
            reap_evidence = _terminate_external_provider_group(
                provider_pid=provider_pid,
                provider_pgid=provider_pgid,
                provider_pid_start_time=provider_start_time,
                allow_unverified_direct_child=True,
            )
        else:
            reap_evidence = {
                "status": "reaped",
                "identity_reason": "provider_wait_completed",
                "term_sent": cancel_term_sent,
                "kill_sent": cancel_kill_sent,
                "group_observed_gone": True,
            }
        reap_evidence["reaped_by_supervisor"] = True
        reap_evidence["provider_returncode"] = process.returncode

        if reap_evidence.get("group_observed_gone") is not True:
            try:
                _atomic_write_runtime_bytes(running_log, (stdout or b"") + (stderr or b""))
            except LifecycleConflict as exc:
                reap_evidence["running_log_error"] = str(exc)
            return record_external_reap_unconfirmed(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                cancellation_requested=cancelled,
                provider_reap_evidence=reap_evidence,
                idempotency_key=f"{key}:reap-unconfirmed",
            )

        if cancelled:
            exit_code = 130 if observed_signals and observed_signals[-1] == signal.SIGINT else 143
            completion_signal = "process_cancelled"
        elif timed_out or int(process.returncode) == 124:
            exit_code = 124
            completion_signal = "process_timeout"
        else:
            exit_code = int(process.returncode)
            completion_signal = "process_exit"

        io_exit_code = 0
        try:
            _atomic_write_runtime_bytes(running_log, (stdout or b"") + (stderr or b""))
        except LifecycleConflict:
            io_exit_code = 1
        if reap_evidence.get("group_observed_gone") is not True:
            io_exit_code = io_exit_code or 1
        if prompt_io_failed:
            io_exit_code = io_exit_code or 1
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        return finalize_external_attempt(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            pid=os.getpid(),
            exit_code=exit_code,
            io_exit_code=io_exit_code,
            completion_signal=completion_signal,
            running_log_path=running_log,
            trace_path=trace_path,
            output_path=resolved_output,
            idempotency_key=key,
            provider_pid=provider_pid,
            provider_pgid=provider_pgid,
            provider_pid_start_time=provider_start_time,
            provider_prompt_hash=prompt_execution_hash,
            provider_reap_evidence=reap_evidence,
            output_bytes=stdout or b"",
            output_fd=claimed_output_fd,
            stderr_evidence=_stderr_evidence(stderr_text),
            external_command_metadata=command_metadata,
            external_execution_binding=run_payload,
        )
    finally:
        for descriptor in (gate_read_fd, gate_write_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if claimed_output_fd is None:
            private_fd = private_resources.get("output_fd")
            if isinstance(private_fd, int):
                claimed_output_fd = private_fd
        if claimed_output_fd is not None:
            try:
                os.close(claimed_output_fd)
            except OSError:
                pass
        for stage in (prompt_stage, gate_config_stage, stdout_stage, stderr_stage):
            if stage is not None:
                try:
                    stage.close()
                except OSError:
                    pass
        if can_install_handlers:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)


def _orca_client_from_state(state: dict[str, Any], client: Any | None = None) -> Any:
    if client is not None:
        return client
    command = state.get("orca_cli_argv")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise LifecycleConflict("persisted Orca attempt is missing its selected CLI command")
    try:
        resolved = orca_delegation_mod.resolve_orca_cli()
        if str(resolved[0]) != str(command[0]):
            raise LifecycleConflict(
                "selected Orca executable changed after attempt authorization"
            )
        return orca_delegation_mod.OrcaClient(command_argv=resolved)
    except orca_delegation_mod.OrcaCommandError as exc:
        raise LifecycleConflict(str(exc)) from exc


def _record_orca_state_event(
    *,
    base_dir: Path | str,
    state: dict[str, Any],
    event: str,
    idempotency_key: str,
    operation_payload: dict[str, Any],
) -> dict[str, Any]:
    fingerprint = _operation_fingerprint(
        event,
        str(state.get("attempt_id") or ""),
        operation_payload,
    )
    _record_event(
        state,
        event,
        idempotency_key,
        source_attempt_id=str(state.get("attempt_id") or ""),
        fingerprint=fingerprint,
    )
    _sync_attempt(state)
    _atomic_save(native_state_path(base_dir, str(state["task_id"])), state)
    _append_history(base_dir, state, event)
    return state


def _orca_terminal_command(
    *,
    state: dict[str, Any],
    mst_script: Path | str | None,
) -> str:
    session_id = str(state.get("mst_session_id") or "").strip()
    if not session_id:
        raise LifecycleConflict("Orca launch requires canonical MST_SESSION_ID")
    script = Path(mst_script or _common._mst_script_path()).resolve(strict=False)
    argv = [
        "env",
        f"MST_SESSION_ID={session_id}",
        sys.executable,
        str(script),
        "dispatch",
        "run-external",
        "--task-id",
        str(state.get("task_id") or ""),
        "--expected-attempt-id",
        str(state.get("attempt_id") or ""),
        "--idempotency-key",
        f"{state.get('task_id')}:{state.get('attempt_id')}:run:v2",
    ]
    return shlex.join(argv)


def _fallback_orca_before_create(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    idempotency_key: str,
    error: Exception,
) -> dict[str, Any]:
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_precreate_fallback")
        if state.get("orca_create_invoked_at"):
            raise LifecycleConflict("Orca fallback is forbidden after terminal create invocation")
        original = state.get("route_decision", {}).get("original_route_decision")
        if not isinstance(original, dict):
            raise LifecycleConflict("Orca route is missing its original fallback decision")
        state.update(
            {
                "orca_launch_status": "preflight_failed",
                "orca_reconciliation_required": False,
                "launch_surface_status": "preflight_failed",
                "orca_preflight_failure": {
                    "reason_code": "orca_preflight_failed",
                    "message": str(error),
                    "observed_at": _now_iso(),
                    "create_invoked": False,
                },
            }
        )
        fallback = json.loads(json.dumps(original, ensure_ascii=False))
        fallback.update(
            {
                "requested_launch_surface": "orca",
                "launch_surface": "direct",
                "launch_surface_status": "preflight_failed",
            }
        )
        fallback["route_fingerprint"] = _route_fingerprint(fallback)
        if fallback.get("route") == "external":
            state.update(
                {
                    "launch_surface": "direct",
                    "route_decision": fallback,
                    "route_fingerprint": fallback["route_fingerprint"],
                    "route_reason": str(fallback.get("reason_code") or "external"),
                    "phase": "planned",
                    "status": "planned",
                    "fallback_allowed": False,
                }
            )
        else:
            state.update(
                {
                    "phase": "failed",
                    "status": "launch_fallback_required",
                    "failure_domain": "orca_precreate_preflight",
                    "fallback_allowed": True,
                    "fallback_route_decision": fallback,
                    "terminated_at": _now_iso(),
                }
            )
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_precreate_fallback",
            idempotency_key=idempotency_key,
            operation_payload={
                "fallback_route": fallback.get("route"),
                "reason": str(error),
            },
        )


def reconcile_orca_terminal(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    client: Any | None = None,
) -> dict[str, Any]:
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_terminal_reconcile")
        if state.get("launch_surface") != "orca":
            raise LifecycleConflict("Orca reconciliation requires an Orca launch surface")
        selector = str(state.get("orca_worktree_selector") or "")
        title = str(state.get("orca_terminal_title") or "")
        initial_handle = str(state.get("orca_terminal_handle") or "")
        if not selector.startswith("path:/") or not title:
            raise LifecycleConflict("Orca reconciliation metadata is incomplete")
        selected_client = _orca_client_from_state(state, client)

    list_error: str | None = None
    try:
        terminals = selected_client.list_terminals(selector=selector)
    except Exception as exc:
        terminals = []
        list_error = str(exc)
    matches = [
        item
        for item in terminals
        if orca_delegation_mod.terminal_title(item) == title
        and orca_delegation_mod.terminal_handle(item)
    ]
    handle = (
        orca_delegation_mod.terminal_handle(matches[0]) if len(matches) == 1 else None
    )

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_terminal_reconcile")
        if (
            not handle
            and not initial_handle
            and state.get("orca_terminal_handle")
            and state.get("orca_launch_status") == "created"
        ):
            # A concurrent creator persisted its authoritative response while
            # this caller was listing. Never replace that handle with a stale
            # zero-match observation from before the terminal became visible.
            return state
        now = _now_iso()
        state["orca_reconciliation"] = {
            "status": "reacquired" if handle else "unresolved",
            "match_count": len(matches),
            "worktree_selector": selector,
            "terminal_title": title,
            "error": list_error,
            "observed_at": now,
        }
        if handle:
            state.update(
                {
                    "orca_terminal_handle": handle,
                    "orca_launch_status": "created",
                    "orca_handle_acquired_at": now,
                    "orca_reconciliation_required": False,
                }
            )
            if (
                str(state.get("phase") or "") == "reconciling"
                and not state.get("external_claim_id")
                and state.get("provider_reconciliation_required") is True
            ):
                state.update(
                    {
                        "phase": "planned",
                        "status": "planned",
                        "provider_reconciliation_required": False,
                        "reconciliation_action": None,
                    }
                )
        else:
            state.update(
                {
                    "orca_terminal_handle": None,
                    "orca_launch_status": "create_unknown",
                    "orca_reconciliation_required": True,
                    "fallback_allowed": False,
                }
            )
            if not state.get("external_claim_id") and not lifecycle_is_terminal(state):
                state.update(
                    {
                        "phase": "reconciling",
                        "status": "orca_create_unknown",
                        "provider_reconciliation_required": True,
                        "reconciliation_action": {
                            "kind": "orca_terminal_reconcile",
                            "action_id": f"orca-terminal:{task_id}:{expected_attempt_id}",
                            "lookup_key": f"{selector}|{title}",
                            "status": "pending",
                            "completion_accepted": False,
                        },
                    }
                )
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_terminal_reconcile",
            idempotency_key=f"{task_id}:{expected_attempt_id}:orca-reconcile:{now}",
            operation_payload={"match_count": len(matches), "handle": handle},
        )


def launch_external_via_orca(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    idempotency_key: str,
    client: Any | None = None,
    mst_script: Path | str | None = None,
) -> dict[str, Any]:
    task_id = _validate_task_id(task_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise LifecycleConflict("Orca launch requires idempotency_key")
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "orca_launch")
        if state.get("execution_transport") != "external" or state.get("launch_surface") != "orca":
            raise LifecycleConflict("Orca launch requires a persisted external Orca route")
        if lifecycle_is_terminal(state):
            return state
        if (
            state.get("orca_terminal_handle")
            and state.get("orca_launch_status") == "created"
        ):
            return state
        if state.get("orca_create_invoked_at"):
            needs_reconcile = True
        else:
            needs_reconcile = False
        selected_client = _orca_client_from_state(state, client)
        worktree = Path(str(state.get("worktree_dir") or "")).resolve(strict=False)

    if needs_reconcile:
        return reconcile_orca_terminal(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            client=selected_client,
        )

    try:
        preflight = selected_client.preflight(worktree)
    except Exception as exc:
        return _fallback_orca_before_create(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            idempotency_key=f"{key}:preflight-fallback",
            error=exc,
        )
    selector = str(preflight.get("worktree_selector") or "")
    exact_selector = f"path:{worktree}"
    if selector != exact_selector:
        return _fallback_orca_before_create(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            idempotency_key=f"{key}:selector-fallback",
            error=LifecycleConflict("Orca preflight selector does not match the exact MST worktree"),
        )

    raced_create_invocation = False
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_launch_claim")
        _assert_nonterminal_lifecycle(state, "claim Orca terminal launch")
        if state.get("orca_create_invoked_at"):
            raced_create_invocation = True
        else:
            title = f"MST/{task_id}/{expected_attempt_id}"
            command = _orca_terminal_command(state=state, mst_script=mst_script)
            now = _now_iso()
            state.update(
                {
                    "orca_worktree_selector": exact_selector,
                    "orca_terminal_title": title,
                    "orca_launch_status": "create_invoked",
                    "orca_launch_claim_owner": f"pid:{os.getpid()}",
                    "orca_launch_claimed_at": now,
                    # Persist before invoking the side effect. From this point on,
                    # every uncertainty reconciles and never falls back/spawns.
                    "orca_create_invoked_at": now,
                    "fallback_allowed": False,
                }
            )
            _record_orca_state_event(
                base_dir=base_dir,
                state=state,
                event="orca_terminal_create_invoked",
                idempotency_key=f"{key}:create-invoked",
                operation_payload={"selector": exact_selector, "title": title},
            )

    if raced_create_invocation:
        return reconcile_orca_terminal(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            client=selected_client,
        )

    try:
        created = selected_client.create_terminal(
            selector=exact_selector,
            title=title,
            command=command,
        )
        handle = orca_delegation_mod.terminal_handle(created) or str(
            created.get("terminal_handle") or ""
        )
        if not handle:
            raise orca_delegation_mod.OrcaCreateUncertain(
                "Orca terminal create response omitted the handle"
            )
    except Exception:
        return reconcile_orca_terminal(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=expected_attempt_id,
            client=selected_client,
        )

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_launch_created")
        state.update(
            {
                "orca_terminal_handle": handle,
                "orca_launch_status": "created",
                "orca_handle_acquired_at": _now_iso(),
                "orca_reconciliation_required": False,
            }
        )
        if (
            str(state.get("phase") or "") == "reconciling"
            and not state.get("external_claim_id")
            and state.get("provider_reconciliation_required") is True
            and str(state.get("status") or "") == "orca_create_unknown"
        ):
            state.update(
                {
                    "phase": "planned",
                    "status": "planned",
                    "provider_reconciliation_required": False,
                    "reconciliation_action": None,
                }
            )
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_terminal_created",
            idempotency_key=f"{key}:created",
            operation_payload={"handle": handle, "selector": exact_selector, "title": title},
        )


def finalize_orca_terminal(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    client: Any | None = None,
) -> dict[str, Any]:
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_terminal_finalize")
        if state.get("launch_surface") != "orca":
            return state
        selected_client = _orca_client_from_state(state, client)
        successful = state.get("phase") == "done" and state.get("status") in {
            "completed",
            "fallback_completed",
        }
        if not successful:
            state["orca_cleanup_status"] = "preserved"
            state["orca_cleanup_observed_at"] = _now_iso()
            return _record_orca_state_event(
                base_dir=base_dir,
                state=state,
                event="orca_terminal_preserved",
                idempotency_key=f"{task_id}:{expected_attempt_id}:orca-preserve",
                operation_payload={"phase": state.get("phase"), "status": state.get("status")},
            )
        if (
            state.get("orca_cleanup_status") != "ready_to_close"
            or not state.get("orca_cleanup_ready_at")
        ):
            raise LifecycleConflict(
                "Orca success cleanup requires durable out-of-tab controller evidence"
            )
        handle = str(state.get("orca_terminal_handle") or "")
        selector = str(state.get("orca_worktree_selector") or "")
        title = str(state.get("orca_terminal_title") or "")

    close_error: str | None = None
    if handle:
        try:
            selected_client.close_terminal(handle=handle)
        except Exception as exc:
            close_error = str(exc)
            handle = ""
    if not handle:
        try:
            matches = [
                item
                for item in selected_client.list_terminals(selector=selector)
                if orca_delegation_mod.terminal_title(item) == title
                and orca_delegation_mod.terminal_handle(item)
            ]
            if len(matches) == 1:
                handle = str(orca_delegation_mod.terminal_handle(matches[0]) or "")
                selected_client.close_terminal(handle=handle)
                close_error = None
            elif close_error is None:
                close_error = f"terminal reacquisition matched {len(matches)} terminals"
        except Exception as exc:
            close_error = str(exc)

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_terminal_finalize")
        state.update(
            {
                "orca_terminal_handle": handle or state.get("orca_terminal_handle"),
                "orca_cleanup_status": "closed" if close_error is None and handle else "close_failed",
                "orca_cleanup_error": close_error,
                "orca_cleanup_observed_at": _now_iso(),
            }
        )
        if state["orca_cleanup_status"] == "closed":
            state["orca_launch_status"] = "closed"
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_terminal_closed" if state["orca_cleanup_status"] == "closed" else "orca_terminal_close_failed",
            idempotency_key=f"{task_id}:{expected_attempt_id}:orca-close",
            operation_payload={"handle": handle or None, "error": close_error},
        )


def mark_orca_cleanup_ready(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
) -> dict[str, Any]:
    """Publish the final in-tab evidence before an outer controller closes the tab."""

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_cleanup_ready")
        if state.get("launch_surface") != "orca":
            return state
        if not lifecycle_is_terminal(state):
            raise LifecycleConflict("Orca cleanup cannot become ready before lifecycle finalization")
        successful = state.get("phase") == "done" and state.get("status") in {
            "completed",
            "fallback_completed",
        }
        state["orca_cleanup_status"] = (
            "ready_to_close" if successful else "ready_to_preserve"
        )
        state["orca_cleanup_ready_at"] = _now_iso()
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_terminal_cleanup_ready",
            idempotency_key=f"{task_id}:{expected_attempt_id}:orca-cleanup-ready",
            operation_payload={
                "phase": state.get("phase"),
                "status": state.get("status"),
                "cleanup_status": state.get("orca_cleanup_status"),
            },
        )


def record_orca_worker_failure(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    reason_code: str = "orca_worker_start_failed",
) -> dict[str, Any]:
    """Bound an in-terminal failure and hand preservation back to the controller."""

    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
        _assert_attempt_cas(state, expected_attempt_id, "orca_worker_failure")
        if state.get("launch_surface") != "orca" or lifecycle_is_terminal(state):
            return state
        now = _now_iso()
        state.update(
            {
                "phase": "reconciling",
                "status": "orca_worker_failed",
                "failure_domain": str(reason_code or "orca_worker_start_failed"),
                "provider_reconciliation_required": True,
                "orca_reconciliation_required": True,
                "orca_cleanup_status": "ready_to_preserve",
                "orca_cleanup_ready_at": now,
                "fallback_allowed": False,
                "reconciliation_action": _external_reconciliation_action(
                    state,
                    next_operation="reconcile_orca_worker",
                    reason_code=str(reason_code or "orca_worker_start_failed"),
                ),
                "last_heartbeat": now,
            }
        )
        return _record_orca_state_event(
            base_dir=base_dir,
            state=state,
            event="orca_worker_failure",
            idempotency_key=f"{task_id}:{expected_attempt_id}:orca-worker-failure",
            operation_payload={"reason_code": str(reason_code or "orca_worker_start_failed")},
        )


def wait_for_orca_cleanup_ready(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    poll_interval: float = 0.2,
    stale_timeout: float = 300.0,
) -> dict[str, Any]:
    """Wait in the launch caller, which is outside the Orca-owned terminal."""

    progress_signature: tuple[Any, ...] | None = None
    progress_deadline = time.monotonic() + max(0.01, float(stale_timeout))
    while True:
        timed_out = False
        with _task_lock(base_dir, task_id):
            state = _load_state(base_dir, task_id)
            if not isinstance(state, dict):
                raise LifecycleConflict(f"external lifecycle state not found for task {task_id}")
            _assert_attempt_cas(state, expected_attempt_id, "orca_cleanup_wait")
            if state.get("launch_surface") != "orca":
                return state
            if state.get("orca_cleanup_status") in {
                "ready_to_close",
                "ready_to_preserve",
                "closed",
                "preserved",
                "close_failed",
            }:
                return state
            if state.get("phase") == "reconciling" or state.get(
                "provider_reconciliation_required"
            ) or state.get("orca_reconciliation_required"):
                return state
            current_signature = (
                state.get("phase"),
                state.get("status"),
                state.get("last_heartbeat"),
                state.get("orca_launch_status"),
                state.get("external_claim_id"),
            )
            if current_signature != progress_signature:
                progress_signature = current_signature
                progress_deadline = time.monotonic() + max(0.01, float(stale_timeout))
            timed_out = time.monotonic() >= progress_deadline
        if timed_out:
            return record_orca_worker_failure(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=expected_attempt_id,
                reason_code="orca_worker_heartbeat_stale",
            )
        time.sleep(max(0.01, float(poll_interval)))


def run_persisted_external_adapter(
    *,
    base_dir: Path | str,
    task_id: str,
    expected_attempt_id: str,
    idempotency_key: str,
    binary: Path | str | None = None,
    timeout: int | None = None,
    monitor_callback: Callable[[dict[str, Any], Path], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Run only from persisted bindings so argv cannot retarget execution."""

    normalized_task_id = _validate_task_id(task_id)
    with _task_lock(base_dir, normalized_task_id):
        state = _load_state(base_dir, normalized_task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"external lifecycle state not found for task {normalized_task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "external_run")
        provider = str(state.get("provider") or "")
        prompt_file = str(state.get("prompt_file") or "")
        worktree_dir = str(state.get("worktree_dir") or "")
        output_path = str(state.get("output_path") or "")
        model = str(state.get("model")) if state.get("model") is not None else None
        reasoning_effort = (
            str(state.get("reasoning_effort"))
            if state.get("reasoning_effort") is not None
            else None
        )
        scope = str(state.get("scope") or "implementation")
        read_only = bool(state.get("read_only"))
    result = run_external_adapter(
        base_dir=base_dir,
        task_id=normalized_task_id,
        expected_attempt_id=expected_attempt_id,
        provider=provider,
        prompt_file=prompt_file,
        worktree_dir=worktree_dir,
        output_path=output_path,
        idempotency_key=idempotency_key,
        binary=binary,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout=timeout,
        scope=scope,
        read_only=read_only,
        monitor_callback=monitor_callback,
    )
    return result


def _mark_bridge_result(
    *, base_dir: Path | str, task_id: str, expected_attempt_id: str, idempotency_key: str
) -> dict[str, Any]:
    with _task_lock(base_dir, task_id):
        state = _load_state(base_dir, task_id)
        if not isinstance(state, dict):
            raise LifecycleConflict(f"delegation attempt not found for task {task_id}")
        _validate_persisted_session_identity(state)
        _assert_attempt_cas(state, expected_attempt_id, "bridge_result")
        if lifecycle_is_terminal(state):
            return state
    return _mutate_state(
        base_dir=base_dir,
        task_id=task_id,
        expected_attempt_id=expected_attempt_id,
        idempotency_key=f"{idempotency_key}:bridge",
        event="bridge_result",
        expected_transport=None,
        allowed_phases=None,
        operation_payload={},
        mutate=lambda state: None,
    )


def execute_delegation_bridge(
    *,
    base_dir: Path | str,
    task_id: str,
    host: str,
    provider: str,
    bridge: Any,
    worktree_dir: Path | str,
    scope: str,
    read_only: bool,
    prompt_file: Path | str,
    output_path: Path | str,
    idempotency_key: str,
    external_binary: Path | str | None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    reasoning_effort_source: str | None = None,
) -> dict[str, Any]:
    """Small host-bridge coordinator used by skills and deterministic tests."""

    task_id = _validate_task_id(task_id)
    with _bridge_lock(base_dir, task_id):
        existing = _load_state(base_dir, task_id)
        bridge_key = f"{idempotency_key}:bridge"
        if isinstance(existing, dict) and _idempotent_replay(existing, bridge_key):
            return existing
        if isinstance(existing, dict) and lifecycle_is_terminal(existing):
            return existing
        try:
            executable = _resolve_external_executable(_normalized_provider(provider), external_binary)
            external_available = True
        except ExternalAdapterUnavailable:
            executable = None
            external_available = False

        if isinstance(existing, dict):
            persisted_route = _validate_persisted_route(existing)
            if existing.get("execution_transport") == "native":
                current_route = resolve_delegation_route(
                    base_dir=base_dir,
                    host=str(existing.get("host") or host),
                    provider=str(existing.get("provider") or provider),
                    scope=str(existing.get("scope") or scope),
                    capability_status=str(existing.get("capability_status") or "unknown"),
                    external_adapter_available=external_available,
                    worktree_dir=existing.get("worktree_dir") or worktree_dir,
                )
                if _route_policy_signature(current_route) != _route_policy_signature(persisted_route):
                    existing = recover_native_attempt(
                        base_dir=base_dir,
                        task_id=task_id,
                        expected_attempt_id=str(existing.get("attempt_id") or ""),
                        idempotency_key=f"{idempotency_key}:route-drift",
                        route_validation={
                            "status": "drift",
                            "persisted_route_fingerprint": existing.get("route_fingerprint"),
                            "current_route_fingerprint": current_route.get("route_fingerprint"),
                        },
                    )
                    return _mark_bridge_result(
                        base_dir=base_dir,
                        task_id=task_id,
                        expected_attempt_id=str(existing["attempt_id"]),
                        idempotency_key=idempotency_key,
                    )

        if isinstance(existing, dict) and existing.get("execution_transport") == "external":
            phase = str(existing.get("phase") or "")
            if phase != "planned":
                return existing
            if not executable:
                raise ExternalAdapterUnavailable("missing_cli: persisted external attempt has no provider CLI")
            if existing.get("launch_surface") == "orca":
                state = launch_external_via_orca(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(existing.get("attempt_id") or ""),
                    idempotency_key=f"{idempotency_key}:orca-launch",
                )
            else:
                state = run_external_adapter(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(existing.get("attempt_id") or ""),
                    provider=provider,
                    prompt_file=existing.get("prompt_file") or prompt_file,
                    worktree_dir=worktree_dir,
                    output_path=existing.get("output_path") or output_path,
                    idempotency_key=f"{idempotency_key}:external-run",
                    binary=executable,
                    model=(str(existing.get("model")) if existing.get("model") is not None else None),
                    reasoning_effort=(
                        str(existing.get("reasoning_effort"))
                        if existing.get("reasoning_effort") is not None
                        else None
                    ),
                    scope=str(existing.get("scope") or scope),
                    read_only=bool(existing.get("read_only")),
                )
            return _mark_bridge_result(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                idempotency_key=idempotency_key,
            )

        state = existing if isinstance(existing, dict) else None
        if state is None:
            if reasoning_effort_source is None:
                resolved_execution = reasoning_effort_mod.resolve_execution(
                    provider,
                    explicit_model=model,
                    explicit_reasoning_effort=reasoning_effort,
                    base_dir=base_dir,
                )
                model = resolved_execution.get("model")
                reasoning_effort = resolved_execution.get("reasoning_effort")
                reasoning_effort_source = str(
                    resolved_execution.get("reasoning_effort_source") or "default"
                )
            else:
                reasoning_effort_mod.validate_reasoning_effort(provider, model, reasoning_effort)
            route = resolve_delegation_route(
                base_dir=base_dir,
                host=host,
                provider=provider,
                scope=scope,
                capability_status="unknown",
                external_adapter_available=external_available,
                worktree_dir=worktree_dir,
            )
            capability = str(route["capability_status"])
            if route["route"] == "native_candidate" and route.get("handshake_required"):
                capability = str(bridge.capability(_normalized_provider(provider)) or "unknown").strip().lower()
                route = resolve_delegation_route(
                    base_dir=base_dir,
                    host=host,
                    provider=provider,
                    scope=scope,
                    capability_status=capability,
                    external_adapter_available=external_available,
                    worktree_dir=worktree_dir,
                )
            if route["route"] == "blocked":
                raise ExternalAdapterUnavailable(
                    f"missing_cli: external adapter unavailable after {route['route_cause']}"
                )
            if route["route"] == "external":
                state = start_external_attempt(
                    base_dir=base_dir,
                    task_id=task_id,
                    provider=provider,
                    worktree_dir=worktree_dir,
                    idempotency_key=f"{idempotency_key}:external-start",
                    route_reason=route["reason_code"],
                    scope=scope,
                    read_only=read_only,
                    prompt_file=prompt_file,
                    output_path=output_path,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    reasoning_effort_source=reasoning_effort_source,
                    route_decision=route,
                )
                if state.get("launch_surface") == "orca":
                    state = launch_external_via_orca(
                        base_dir=base_dir,
                        task_id=task_id,
                        expected_attempt_id=str(state.get("attempt_id") or ""),
                        idempotency_key=f"{idempotency_key}:orca-launch",
                    )
                else:
                    state = run_external_adapter(
                        base_dir=base_dir,
                        task_id=task_id,
                        expected_attempt_id=str(state.get("attempt_id") or ""),
                        provider=provider,
                        prompt_file=prompt_file,
                        worktree_dir=worktree_dir,
                        output_path=output_path,
                        idempotency_key=f"{idempotency_key}:external-run",
                        binary=executable,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        scope=scope,
                        read_only=read_only,
                    )
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state["attempt_id"]),
                    idempotency_key=idempotency_key,
                )

            state = start_native_attempt(
                base_dir=base_dir,
                task_id=task_id,
                idempotency_key=f"{idempotency_key}:native-start",
                host=host,
                provider=provider,
                worktree_dir=worktree_dir,
                scope=scope,
                read_only=read_only,
                capability_status=capability,
                route_reason=route["reason_code"],
                route_decision=route,
                prompt_file=prompt_file,
                output_path=output_path,
                model=model,
                reasoning_effort=reasoning_effort,
                reasoning_effort_source=reasoning_effort_source,
            )
            native_attempt_id = str(state["attempt_id"])
            if state.get("phase") == "reconciling":
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=native_attempt_id,
                    idempotency_key=idempotency_key,
                )
            claim = claim_native_spawn(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=native_attempt_id,
                claimant_id=f"host-bridge:{idempotency_key}",
                idempotency_key=f"{idempotency_key}:spawn-claim",
            )
            if not claim.get("spawn_allowed") or not claim.get("claim_token"):
                state = recover_native_attempt(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=native_attempt_id,
                    provider_state="unknown_after_spawn_claim",
                    idempotency_key=f"{idempotency_key}:claim-reconcile",
                )
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=native_attempt_id,
                    idempotency_key=idempotency_key,
                )
            claim_token = str(claim["claim_token"])
            try:
                spawn_result = bridge.spawn(
                    {
                        "task_id": task_id,
                        "attempt_id": native_attempt_id,
                        "provider": provider,
                        "host": host,
                        "scope": scope,
                        "read_only": read_only,
                        "worktree_dir": str(Path(worktree_dir).resolve(strict=False)),
                        "prompt_file": str(prompt_file),
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "idempotency_key": f"{idempotency_key}:host-spawn",
                    }
                )
            except Exception:
                state = acknowledge_native_spawn(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=native_attempt_id,
                    spawn_status="outcome_unknown",
                    claim_token=claim_token,
                    idempotency_key=f"{idempotency_key}:spawn-exception",
                )
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state["attempt_id"]),
                    idempotency_key=idempotency_key,
                )
            if not isinstance(spawn_result, dict):
                spawn_result = {"spawn_status": "outcome_unknown"}
            state = acknowledge_native_spawn(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=native_attempt_id,
                spawn_status=str(spawn_result.get("spawn_status") or "outcome_unknown"),
                provider_task_id=str(spawn_result.get("provider_task_id") or "") or None,
                claim_token=claim_token,
                idempotency_key=f"{idempotency_key}:acknowledge",
            )
        else:
            phase = str(state.get("phase") or "")
            if phase == "spawn_requested":
                state = recover_native_attempt(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state["attempt_id"]),
                    provider_state="unknown_after_restart",
                    idempotency_key=f"{idempotency_key}:resume-reconcile",
                )
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state["attempt_id"]),
                    idempotency_key=idempotency_key,
                )
            if phase in TERMINAL_PHASES or phase == "reconciling":
                return _mark_bridge_result(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state["attempt_id"]),
                    idempotency_key=idempotency_key,
                )

        if state.get("spawn_status") == "definitive_not_created":
            if not executable:
                raise ExternalAdapterUnavailable("missing_cli: native task was not created and fallback CLI is unavailable")
            native_attempt_id = str(state["attempt_id"])
            state = request_external_fallback(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=native_attempt_id,
                idempotency_key=f"{idempotency_key}:fallback",
            )
            if state.get("launch_surface") == "orca":
                state = launch_external_via_orca(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state.get("attempt_id") or ""),
                    idempotency_key=f"{idempotency_key}:orca-launch",
                )
            else:
                state = run_external_adapter(
                    base_dir=base_dir,
                    task_id=task_id,
                    expected_attempt_id=str(state.get("attempt_id") or ""),
                    provider=provider,
                    prompt_file=prompt_file,
                    worktree_dir=worktree_dir,
                    output_path=output_path,
                    idempotency_key=f"{idempotency_key}:external-run",
                    binary=executable,
                    model=(str(state.get("model")) if state.get("model") is not None else None),
                    reasoning_effort=(
                        str(state.get("reasoning_effort"))
                        if state.get("reasoning_effort") is not None
                        else None
                    ),
                    scope=scope,
                    read_only=read_only,
                )
            return _mark_bridge_result(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                idempotency_key=idempotency_key,
            )
        if state.get("phase") == "reconciling":
            return _mark_bridge_result(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                idempotency_key=idempotency_key,
            )

        provider_task_id = state.get("provider_task_id")
        if state.get("phase") == "spawned":
            try:
                attach_status = bridge.attach(provider_task_id)
            except Exception:
                attach_status = "failed"
            state = attach_native_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                attach_status=str(attach_status or "failed"),
                idempotency_key=f"{idempotency_key}:attach",
            )
        if state.get("phase") == "reconciling":
            return _mark_bridge_result(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                idempotency_key=idempotency_key,
            )
        try:
            provider_state = str(bridge.poll(provider_task_id) or "unknown")
            result = bridge.result(provider_task_id)
        except Exception:
            state = recover_native_attempt(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                provider_state="unknown",
                idempotency_key=f"{idempotency_key}:result-reconcile",
            )
            return _mark_bridge_result(
                base_dir=base_dir,
                task_id=task_id,
                expected_attempt_id=str(state["attempt_id"]),
                idempotency_key=idempotency_key,
            )
        if not isinstance(result, dict):
            result = {"completion_signal": "unknown"}
        output_value = result.get("output")
        if isinstance(output_value, str):
            output = Path(output_path).resolve(strict=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(output_value, encoding="utf-8")
        signal = str(result.get("completion_signal") or ("completed" if provider_state == "terminal" else "unknown"))
        state = complete_native_attempt(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=str(state["attempt_id"]),
            completion_signal=signal,
            output_path=output_path,
            failure_domain="task" if signal in {"failed", "error"} else None,
            idempotency_key=f"{idempotency_key}:complete",
        )
        return _mark_bridge_result(
            base_dir=base_dir,
            task_id=task_id,
            expected_attempt_id=str(state["attempt_id"]),
            idempotency_key=idempotency_key,
        )


def _normalized_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    return "agy" if provider == "gemini" else provider


def _external_binary(provider: str) -> str:
    return "agy" if provider == "agy" else provider


def _scope_enabled(scope: str, configured_scope: Any) -> bool:
    requested = str(scope or "implementation").strip().lower()
    if isinstance(configured_scope, (list, tuple, set)):
        enabled = {str(item).strip().lower() for item in configured_scope}
        return requested in enabled or "all" in enabled or "*" in enabled

    configured = str(configured_scope or "all").strip().lower()
    if configured in {"all", "any", "*", "enabled"}:
        return True
    if configured in {"none", "disabled", "off"}:
        return False
    if configured == "review-and-exploration-only":
        return requested in {"review", "exploration", "ideation", "discussion", "debug", "analysis"}
    if configured.endswith("-only"):
        return requested == configured[: -len("-only")]
    enabled = {item.strip() for item in configured.split(",") if item.strip()}
    return requested in enabled


def plan_delegation_route(
    *,
    host: str,
    provider: str,
    transport_policy: str = NATIVE_FIRST_POLICY,
    scope: str = "implementation",
    native_enabled: bool = True,
    configured_scope: Any = "all",
    capability_status: str = "unknown",
    external_adapter_available: bool | None = None,
    orca_enabled: bool = False,
    orca_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a pure route decision without launching either transport."""

    normalized_host = str(host or "headless").strip().lower()
    normalized_provider = _normalized_provider(provider)
    capability = str(capability_status or "unknown").strip().lower()
    if capability not in CAPABILITY_STATUSES:
        capability = "unknown"
    policy = str(transport_policy or NATIVE_FIRST_POLICY).strip().lower()
    binary = _external_binary(normalized_provider)
    if external_adapter_available is None:
        external_available = bool(binary and shutil.which(binary))
    else:
        external_available = bool(external_adapter_available)

    route_cause = "same_host_native_capable"
    native_candidate = True
    if normalized_host == "headless":
        route_cause = "headless_host"
        native_candidate = False
    elif normalized_provider not in NATIVE_PROVIDERS:
        route_cause = "provider_has_no_native_bridge"
        native_candidate = False
    elif normalized_host != normalized_provider:
        route_cause = "cross_provider"
        native_candidate = False
    elif policy != NATIVE_FIRST_POLICY:
        route_cause = "policy_disabled"
        native_candidate = False
    elif not native_enabled:
        route_cause = "native_disabled"
        native_candidate = False
    elif not _scope_enabled(scope, configured_scope):
        route_cause = "scope_disabled"
        native_candidate = False
    elif capability == "unavailable":
        route_cause = "capability_unavailable"
        native_candidate = False

    payload: dict[str, Any] = {
        "host": normalized_host,
        "provider": normalized_provider,
        "transport_policy": policy,
        "scope": str(scope or "implementation"),
        "configured_scope": configured_scope,
        "native_enabled": bool(native_enabled),
        "capability_status": capability,
        "required_capability": REQUIRED_CAPABILITY,
        "handshake_required": capability == "unknown" and native_candidate,
        "external_adapter": {"provider": normalized_provider, "binary": binary, "available": external_available},
    }
    if native_candidate:
        payload.update(
            {
                "route": "native_candidate",
                "execution_transport": "native",
                "reason_code": (
                    "capability_handshake_required" if capability == "unknown" else route_cause
                ),
                "route_cause": route_cause,
            }
        )
    elif external_available:
        payload.update(
            {
                "route": "external",
                "execution_transport": "external",
                "reason_code": route_cause,
                "route_cause": route_cause,
                "handshake_required": False,
            }
        )
    else:
        payload.update(
            {
                "route": "blocked",
                "execution_transport": None,
                "reason_code": "missing_cli",
                "route_cause": route_cause,
                "handshake_required": False,
                "failure_kind": "missing_cli",
            }
        )

    original = json.loads(json.dumps(payload, ensure_ascii=False))
    orca_applicable = payload.get("route") == "external"
    preflight = dict(orca_preflight) if isinstance(orca_preflight, dict) else {}
    preflight_ready = bool(
        orca_enabled
        and orca_applicable
        and external_available
        and preflight.get("ok") is True
        and str(preflight.get("runtime_scope") or "local").lower() == "local"
        and str(preflight.get("worktree_selector") or "").startswith("path:/")
    )
    payload.update(
        {
            "requested_launch_surface": "orca" if orca_enabled and orca_applicable else "direct",
            "launch_surface": "orca" if preflight_ready else "direct",
            "launch_surface_status": (
                "ready"
                if preflight_ready
                else "disabled"
                if not orca_enabled
                else "not_applicable"
                if not orca_applicable
                else "preflight_failed"
                if preflight
                else "preflight_required"
            ),
        }
    )
    if orca_enabled and orca_applicable:
        payload["orca_preflight"] = {
            key: preflight.get(key)
            for key in (
                "ok",
                "runtime_scope",
                "worktree_dir",
                "worktree_selector",
                "cli_argv",
                "reason_code",
                "message",
            )
            if preflight.get(key) is not None
        }
    if preflight_ready:
        payload["original_route_decision"] = original
        payload["original_route_fingerprint"] = _route_fingerprint(original)
    return payload


def build_capability_handshake(
    *,
    base_dir: Path | str | None,
    host: str,
    provider: str,
    capability_status: str,
    external_adapter_available: bool | None,
    scope: str = "implementation",
    reason_code: str | None = None,
) -> dict[str, Any]:
    route = resolve_delegation_route(
        base_dir=base_dir,
        host=host,
        provider=provider,
        scope=scope,
        capability_status=capability_status,
        external_adapter_available=external_adapter_available,
    )
    return {
        **route,
        "spawn_status": None,
        "provider_task_id": None,
        "external_adapter_available": route["external_adapter"]["available"],
        "capability_reason_code": str(reason_code or route["reason_code"]),
    }


def _resolved_delegation_settings(base_dir: Path | str | None = None) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "transport_policy": NATIVE_FIRST_POLICY,
        "native_enabled": True,
        "configured_scope": "all",
        "orca_enabled": False,
        "config_provenance": "builtin",
    }
    resolved_base = Path(base_dir).resolve(strict=False) if base_dir is not None else _common.BASE_DIR
    if resolved_base is None:
        return settings

    candidates = [
        Path(resolved_base) / "config.resolved.json",
        Path(resolved_base) / "config.json",
        _common._plugin_root() / "templates" / "defaults" / "config.json",
    ]
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            continue
        delegation = payload.get("delegation") if isinstance(payload, dict) else None
        if not isinstance(delegation, dict):
            continue

        orca = delegation.get("orca") if isinstance(delegation.get("orca"), dict) else {}
        if isinstance(orca.get("enabled"), bool):
            settings["orca_enabled"] = orca["enabled"]
        canonical_present = "transport_policy" in delegation or "native" in delegation
        if canonical_present:
            policy = delegation.get("transport_policy")
            native = delegation.get("native") if isinstance(delegation.get("native"), dict) else {}
            if isinstance(policy, str) and policy.strip():
                settings["transport_policy"] = policy.strip()
            if isinstance(native.get("enabled"), bool):
                settings["native_enabled"] = native["enabled"]
            else:
                settings["native_enabled"] = settings["transport_policy"] == NATIVE_FIRST_POLICY
            if isinstance(native.get("scope"), (str, list)):
                settings["configured_scope"] = native["scope"]
        else:
            legacy = delegation.get("native_codex_subagents")
            if isinstance(legacy, dict):
                enabled = legacy.get("enabled") is not False
                settings["transport_policy"] = NATIVE_FIRST_POLICY if enabled else "external-only"
                settings["native_enabled"] = enabled
                if isinstance(legacy.get("scope"), (str, list)):
                    settings["configured_scope"] = legacy["scope"]
        settings["config_provenance"] = str(path)
        return settings
    return settings


def _route_fingerprint(route: dict[str, Any]) -> str:
    evidence = {
        key: route.get(key)
        for key in (
            "host",
            "provider",
            "transport_policy",
            "scope",
            "configured_scope",
            "native_enabled",
            "capability_status",
            "route",
            "execution_transport",
            "reason_code",
            "route_cause",
            "handshake_required",
            "requested_launch_surface",
            "launch_surface",
            "launch_surface_status",
            "original_route_fingerprint",
        )
    }
    raw = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_route_fingerprint(route: dict[str, Any]) -> str:
    """Fingerprint used before launch_surface became an orthogonal route axis."""

    evidence = {
        key: route.get(key)
        for key in (
            "host",
            "provider",
            "transport_policy",
            "scope",
            "configured_scope",
            "native_enabled",
            "capability_status",
            "route",
            "execution_transport",
            "reason_code",
            "route_cause",
            "handshake_required",
        )
    }
    raw = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_persisted_route(state: dict[str, Any]) -> dict[str, Any]:
    decision = state.get("route_decision")
    if not isinstance(decision, dict):
        raise LifecycleConflict("persisted delegation attempt is missing route_decision")
    expected = str(state.get("route_fingerprint") or "")
    actual = _route_fingerprint(decision)
    decision_fingerprint = str(decision.get("route_fingerprint") or actual)
    legacy_launch_fields_absent = not any(
        key in decision
        for key in (
            "requested_launch_surface",
            "launch_surface",
            "launch_surface_status",
            "original_route_fingerprint",
        )
    )
    legacy = _legacy_route_fingerprint(decision)
    legacy_valid = (
        legacy_launch_fields_absent
        and expected == legacy
        and decision_fingerprint == legacy
    )
    if not expected or (not legacy_valid and (expected != actual or decision_fingerprint != actual)):
        raise LifecycleConflict("persisted delegation route fingerprint mismatch")
    route_transport = decision.get("execution_transport")
    if route_transport and route_transport != state.get("execution_transport"):
        raise LifecycleConflict("persisted delegation route transport mismatch")
    return decision


def _route_policy_signature(route: dict[str, Any]) -> tuple[Any, ...]:
    requested_launch_surface = route.get("requested_launch_surface")
    launch_surface = route.get("launch_surface")
    if requested_launch_surface is None and launch_surface is None:
        # Attempts persisted before Orca existed are semantically equivalent
        # to the default-off direct launch surface.
        requested_launch_surface = "direct"
        launch_surface = "direct"
    return (
        route.get("route"),
        route.get("transport_policy"),
        route.get("native_enabled"),
        route.get("configured_scope"),
        route.get("scope"),
        requested_launch_surface,
        launch_surface,
    )


def resolve_delegation_route(
    *,
    base_dir: Path | str | None,
    host: str,
    provider: str,
    scope: str,
    capability_status: str,
    external_adapter_available: bool | None,
    transport_policy: str | None = None,
    native_enabled: bool | None = None,
    configured_scope: Any = None,
    worktree_dir: Path | str | None = None,
    orca_client: Any | None = None,
) -> dict[str, Any]:
    settings = _resolved_delegation_settings(base_dir)
    normalized_provider = _normalized_provider(provider)
    resolved_external_available = (
        bool(shutil.which(_external_binary(normalized_provider)))
        if external_adapter_available is None
        else bool(external_adapter_available)
    )
    base_route = plan_delegation_route(
        host=host,
        provider=provider,
        transport_policy=transport_policy or settings["transport_policy"],
        scope=scope,
        native_enabled=settings["native_enabled"] if native_enabled is None else native_enabled,
        configured_scope=settings["configured_scope"] if configured_scope is None else configured_scope,
        capability_status=capability_status,
        external_adapter_available=resolved_external_available,
        orca_enabled=False,
    )
    orca_preflight: dict[str, Any] | None = None
    if settings["orca_enabled"] and base_route.get("route") == "external":
        if not resolved_external_available:
            orca_preflight = {
                "ok": False,
                "reason_code": "provider_cli_missing",
                "message": "the protected provider adapter is unavailable",
            }
        elif worktree_dir is None or not str(worktree_dir).strip():
            orca_preflight = None
        else:
            try:
                client = orca_client or orca_delegation_mod.OrcaClient()
                orca_preflight = client.preflight(worktree_dir)
            except (
                orca_delegation_mod.OrcaCommandError,
                orca_delegation_mod.OrcaPreflightError,
            ) as exc:
                orca_preflight = {
                    "ok": False,
                    "reason_code": "orca_preflight_failed",
                    "message": str(exc),
                }
    route = plan_delegation_route(
        host=host,
        provider=provider,
        transport_policy=transport_policy or settings["transport_policy"],
        scope=scope,
        native_enabled=settings["native_enabled"] if native_enabled is None else native_enabled,
        configured_scope=settings["configured_scope"] if configured_scope is None else configured_scope,
        capability_status=capability_status,
        external_adapter_available=resolved_external_available,
        orca_enabled=settings["orca_enabled"],
        orca_preflight=orca_preflight,
    )
    route["config_provenance"] = settings["config_provenance"]
    route["route_fingerprint"] = _route_fingerprint(route)
    return route


def _cli_base_dir() -> Path:
    if _common.BASE_DIR is None:
        raise LifecycleConflict(".gran-maestro base directory is required")
    return Path(_common.BASE_DIR)


def _emit_cli_action(action, *, terminal_success_required: bool = False) -> int:
    try:
        payload = action()
    except (
        LifecycleConflict,
        ExternalAdapterUnavailable,
        reasoning_effort_mod.ReasoningEffortError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "reason_code": "missing_cli" if isinstance(exc, ExternalAdapterUnavailable) else "lifecycle_conflict",
                    "message": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    if terminal_success_required and not (
        payload.get("phase") == "done"
        and payload.get("status") in {"completed", "fallback_completed"}
    ):
        return 3
    return 0


def cmd_delegation_route(args: argparse.Namespace) -> int:
    external_available = None
    if args.external_available:
        external_available = True
    elif args.external_unavailable:
        external_available = False
    payload = resolve_delegation_route(
        base_dir=_cli_base_dir(),
        host=args.host,
        provider=args.provider,
        transport_policy=args.transport_policy,
        scope=args.scope,
        native_enabled=args.native_enabled,
        configured_scope=args.configured_scope,
        capability_status=args.capability_status,
        external_adapter_available=external_available,
        worktree_dir=args.worktree_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 2 if payload["route"] == "blocked" else 0


def _explicit_external_availability(args: argparse.Namespace) -> bool | None:
    if getattr(args, "external_available", False):
        return True
    if getattr(args, "external_unavailable", False):
        return False
    return None


def cmd_delegation_capability(args: argparse.Namespace) -> int:
    payload = build_capability_handshake(
        base_dir=_cli_base_dir(),
        host=args.host,
        provider=args.provider,
        capability_status=args.capability_status,
        external_adapter_available=_explicit_external_availability(args),
        scope=args.scope,
        reason_code=args.reason_code,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 2 if payload["route"] == "blocked" else 0


def cmd_delegation_start(args: argparse.Namespace) -> int:
    def action() -> dict[str, Any]:
        execution = reasoning_effort_mod.resolve_execution(
            args.provider,
            args.selector,
            explicit_model=args.model,
            explicit_reasoning_effort=args.reasoning_effort,
        )
        return start_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            attempt_id=args.attempt_id,
            idempotency_key=args.idempotency_key,
            host=args.host,
            provider=args.provider,
            capability_status=args.capability_status,
            route_reason=args.route_reason,
            worktree_dir=args.worktree_dir,
            scope=args.scope,
            read_only=args.read_only,
            prompt_file=args.prompt_file,
            context_files=args.context_file,
            running_log_path=args.running_log_path,
            trace_path=args.trace_path,
            output_path=args.output_path,
            model=execution.get("model"),
            reasoning_effort=execution.get("reasoning_effort"),
            reasoning_effort_source=execution.get("reasoning_effort_source"),
            mst_session_id=args.mst_session_id,
            root_mst_id=args.root_mst_id,
            parent_session_id=args.parent_session_id,
            parent_heartbeat=args.parent_heartbeat,
        )

    return _emit_cli_action(
        action
    )


def cmd_delegation_claim_spawn(args: argparse.Namespace) -> int:
    def action() -> dict[str, Any]:
        payload = claim_native_spawn(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            claimant_id=args.claimant_id,
            idempotency_key=args.idempotency_key,
        )
        token = str(payload.get("claim_token") or "")
        if payload.get("spawn_allowed") and token:
            secret_dir = _cli_base_dir() / "run" / ".claim-secrets"
            token_name = hashlib.sha256(token.encode("utf-8")).hexdigest() + ".token"
            evidence = _atomic_write_private_bytes(secret_dir / token_name, token.encode("utf-8"))
            payload["claim_token_file"] = evidence["path"]
            payload["claim_token"] = None
            payload["token_delivery"] = "private_one_shot_file"
        else:
            payload["claim_token_file"] = None
        return payload

    return _emit_cli_action(action)


def _read_private_claim_token_file(base_dir: Path, path_value: str) -> tuple[str, Path]:
    root = (base_dir / "run" / ".claim-secrets").resolve(strict=False)
    candidate = Path(path_value).resolve(strict=False)
    if candidate.parent != root or candidate.suffix != ".token":
        raise LifecycleConflict("claim token file is outside the private claim directory")
    try:
        file_stat = candidate.lstat()
    except OSError as exc:
        raise LifecycleConflict(f"claim token file is unavailable: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode) or candidate.is_symlink():
        raise LifecycleConflict("claim token file must be a regular non-symlink file")
    if file_stat.st_mode & 0o077:
        raise LifecycleConflict("claim token file permissions are too broad")
    try:
        token = candidate.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LifecycleConflict(f"cannot read claim token file: {exc}") from exc
    if not token:
        raise LifecycleConflict("claim token file is empty")
    return token, candidate


def cmd_delegation_acknowledge(args: argparse.Namespace) -> int:
    def action() -> dict[str, Any]:
        token, token_path = _read_private_claim_token_file(
            _cli_base_dir(),
            args.claim_token_file,
        )
        payload = acknowledge_native_spawn(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            spawn_status=args.spawn_status,
            provider_task_id=args.provider_task_id,
            claim_token=token,
            idempotency_key=args.idempotency_key,
        )
        try:
            token_path.unlink()
        except FileNotFoundError:
            pass
        return payload

    return _emit_cli_action(action)


def cmd_delegation_attach(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: attach_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            attach_status=args.attach_status,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_heartbeat(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: heartbeat_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            provider_state=args.provider_state,
            parent_heartbeat=args.parent_heartbeat,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_complete(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: complete_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            completion_signal=args.completion_signal,
            output_path=args.output_path,
            failure_domain=args.failure_domain,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_fallback(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: request_external_fallback(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.expected_attempt_id,
            attempt_id=args.attempt_id,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_cancel(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: cancel_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_recover(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: recover_native_attempt(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
            provider_state=args.provider_state,
            parent_heartbeat=args.parent_heartbeat,
            idempotency_key=args.idempotency_key,
        )
    )


def cmd_delegation_reconcile_action(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: get_reconciliation_action(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.attempt_id,
        )
    )


def cmd_delegation_external_run(args: argparse.Namespace) -> int:
    return _emit_cli_action(
        lambda: run_external_adapter(
            base_dir=_cli_base_dir(),
            task_id=args.task_id,
            expected_attempt_id=args.expected_attempt_id,
            provider=args.provider,
            prompt_file=args.prompt_file,
            worktree_dir=args.worktree_dir,
            output_path=args.output_path,
            idempotency_key=args.idempotency_key,
            binary=args.binary,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            timeout=args.timeout,
            scope=args.scope,
            read_only=args.read_only,
        ),
        terminal_success_required=True,
    )


def register(subparsers) -> None:
    delegation = subparsers.add_parser("delegation")
    delegation_sub = delegation.add_subparsers(dest="subcommand")

    route = delegation_sub.add_parser("route", help="plan native-first delegation transport")
    route.add_argument("--host", choices=["codex", "claude", "headless"], required=True)
    route.add_argument("--provider", choices=["codex", "claude", "agy", "gemini"], required=True)
    route.add_argument("--transport-policy")
    route.add_argument("--scope", default="implementation")
    route.add_argument("--worktree-dir")
    route.add_argument("--configured-scope")
    route.add_argument("--capability-status", choices=sorted(CAPABILITY_STATUSES), default="unknown")
    native_toggle = route.add_mutually_exclusive_group()
    native_toggle.add_argument("--native-enabled", dest="native_enabled", action="store_true")
    native_toggle.add_argument("--native-disabled", dest="native_enabled", action="store_false")
    route.set_defaults(native_enabled=None)
    availability = route.add_mutually_exclusive_group()
    availability.add_argument("--external-available", action="store_true")
    availability.add_argument("--external-unavailable", action="store_true")
    route.add_argument("--pretty", action="store_true")

    capability = delegation_sub.add_parser("capability", help="normalize a host native capability handshake")
    capability.add_argument("--host", choices=["codex", "claude", "headless"], required=True)
    capability.add_argument("--provider", choices=["codex", "claude", "agy", "gemini"], required=True)
    capability.add_argument("--capability-status", choices=sorted(CAPABILITY_STATUSES), required=True)
    capability.add_argument("--scope", default="implementation")
    capability.add_argument("--reason-code")
    capability_availability = capability.add_mutually_exclusive_group()
    capability_availability.add_argument("--external-available", action="store_true")
    capability_availability.add_argument("--external-unavailable", action="store_true")

    start = delegation_sub.add_parser("start", help="record a native spawn request")
    start.add_argument("--task-id", required=True)
    start.add_argument("--attempt-id")
    start.add_argument("--idempotency-key", required=True)
    start.add_argument("--host", choices=["codex", "claude"], required=True)
    start.add_argument("--provider", choices=["codex", "claude"], required=True)
    start.add_argument("--capability-status", choices=sorted(CAPABILITY_STATUSES), default="available")
    start.add_argument("--route-reason", default="same_host_native_capable")
    start.add_argument("--worktree-dir", required=True)
    start.add_argument("--scope", default="implementation")
    start.add_argument("--read-only", action="store_true")
    start.add_argument("--prompt-file")
    start.add_argument("--context-file", action="append")
    start.add_argument("--running-log-path")
    start.add_argument("--trace-path")
    start.add_argument("--output-path")
    start.add_argument("--model")
    start.add_argument("--selector", default="default")
    start.add_argument("--reasoning-effort")
    start.add_argument("--mst-session-id")
    start.add_argument("--root-mst-id")
    start.add_argument("--parent-session-id")
    start.add_argument("--parent-heartbeat")

    claim_spawn = delegation_sub.add_parser(
        "claim-spawn", help="atomically claim one-shot native host spawn authority"
    )
    claim_spawn.add_argument("--task-id", required=True)
    claim_spawn.add_argument("--attempt-id", required=True)
    claim_spawn.add_argument("--claimant-id", required=True)
    claim_spawn.add_argument("--idempotency-key", required=True)

    acknowledge = delegation_sub.add_parser("acknowledge", help="record native spawn acknowledgement")
    acknowledge.add_argument("--task-id", required=True)
    acknowledge.add_argument("--attempt-id", required=True)
    acknowledge.add_argument(
        "--spawn-status",
        choices=["accepted", "rejected", "indeterminate", "definitive_not_created", "created_with_task_id", "outcome_unknown"],
        required=True,
    )
    acknowledge.add_argument("--provider-task-id")
    acknowledge.add_argument("--claim-token-file", required=True)
    acknowledge.add_argument("--idempotency-key", required=True)

    attach = delegation_sub.add_parser("attach", help="record native attach outcome")
    attach.add_argument("--task-id", required=True)
    attach.add_argument("--attempt-id", required=True)
    attach.add_argument("--attach-status", choices=["attached", "failed", "timeout", "unknown", "indeterminate"], required=True)
    attach.add_argument("--idempotency-key", required=True)

    heartbeat = delegation_sub.add_parser("heartbeat", help="record native provider and parent heartbeat")
    heartbeat.add_argument("--task-id", required=True)
    heartbeat.add_argument("--attempt-id", required=True)
    heartbeat.add_argument("--provider-state", default="running")
    heartbeat.add_argument("--parent-heartbeat")
    heartbeat.add_argument("--idempotency-key", required=True)

    complete = delegation_sub.add_parser("complete", help="record native completion signal")
    complete.add_argument("--task-id", required=True)
    complete.add_argument("--attempt-id", required=True)
    complete.add_argument(
        "--completion-signal",
        choices=["completed", "succeeded", "success", "failed", "error", "cancelled", "canceled", "timeout", "timed_out", "unknown", "indeterminate"],
        required=True,
    )
    complete.add_argument("--output-path")
    complete.add_argument("--failure-domain")
    complete.add_argument("--idempotency-key", required=True)

    fallback = delegation_sub.add_parser("fallback", help="link an external attempt after definitive non-creation")
    fallback.add_argument("--task-id", required=True)
    fallback.add_argument("--expected-attempt-id", required=True)
    fallback.add_argument("--attempt-id")
    fallback.add_argument("--idempotency-key", required=True)

    cancel = delegation_sub.add_parser("cancel", help="request provider-side cancellation without an OS signal")
    cancel.add_argument("--task-id", required=True)
    cancel.add_argument("--attempt-id", required=True)
    cancel.add_argument("--idempotency-key", required=True)

    recover = delegation_sub.add_parser("recover", help="mark a PID-less attempt for provider reconciliation")
    recover.add_argument("--task-id", required=True)
    recover.add_argument("--attempt-id", required=True)
    recover.add_argument("--provider-state", default="unknown")
    recover.add_argument("--parent-heartbeat")
    recover.add_argument("--idempotency-key", required=True)

    reconcile_action = delegation_sub.add_parser(
        "reconcile-action", help="read the pending provider reconciliation action"
    )
    reconcile_action.add_argument("--task-id", required=True)
    reconcile_action.add_argument("--attempt-id", required=True)

    external_run = delegation_sub.add_parser("external-run", help="run the selected provider CLI fallback adapter")
    external_run.add_argument("--task-id", required=True)
    external_run.add_argument("--expected-attempt-id", required=True)
    external_run.add_argument("--provider", choices=["codex", "claude", "agy", "gemini"], required=True)
    external_run.add_argument("--prompt-file", required=True)
    external_run.add_argument("--worktree-dir", required=True)
    external_run.add_argument("--output-path", required=True)
    external_run.add_argument("--idempotency-key", required=True)
    external_run.add_argument("--binary")
    external_run.add_argument("--model")
    external_run.add_argument("--reasoning-effort")
    external_run.add_argument("--timeout", type=int)
    external_run.add_argument("--scope", default="implementation")
    external_run.add_argument("--read-only", action="store_true")
