from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import itertools
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
from typing import Callable, Iterable, List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    is_pid_alive,
    load_json,
    requests_dir,
    type_archived_dir,
)

CLEANUP_ENTRY_INVENTORY = {
    "phase5": {
        "source": "scripts/mst_cmds/agile.py",
        "wrapper": "run_cleanup_with_lock_report",
    },
    "mstloop": {
        "source": "scripts/mst-loop.sh",
        "wrapper": "run_cleanup_with_lock_report",
    },
    "stophook": {
        "source": "hooks/mst-stop-hook.sh",
        "wrapper": "run_cleanup_with_lock_report",
    },
    "stale-marker": {
        "source": "scripts/mst_cmds/cleanup.py",
        "wrapper": "run_cleanup_with_lock_report",
    },
    "direct-cli": {
        "source": "scripts/mst_cmds/cleanup.py",
        "wrapper": "run_cleanup_with_lock_report",
    },
}

_ATOMIC_WRITE_COUNTER = itertools.count(1)
_MARKER_LOCK_COUNTER = itertools.count(1)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{next(_ATOMIC_WRITE_COUNTER)}")
    try:
        with open(tmp_path, "x", encoding="utf-8") as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
        _fsync_parent_dir(path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_json_object(path: Path) -> dict:
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def _active_flow_dir(project_root: Path) -> Path:
    return Path(project_root) / ".gran-maestro" / "active-flow"


def _active_marker_path(active_dir: Path, session_id: str) -> Path:
    return Path(active_dir) / f"{session_id}.json"


def run_cleanup_with_lock_report(
    *,
    project_root: Path,
    entrypoint: str,
    session_id: str,
    cleanup_fn: Callable[[dict], dict],
    timeout_seconds: float = 5.0,
) -> dict:
    project_root = Path(project_root)
    lock_path = project_root / ".gran-maestro" / "cleanup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    context = {
        "entrypoint": entrypoint,
        "session_id": session_id,
        "lock_path": str(lock_path),
    }
    started = time.monotonic()

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        try:
            effective_timeout = min(max(0.0, float(timeout_seconds)), 5.0)
            _common._lock_exclusive_with_timeout(lock_file, timeout_sec=effective_timeout, poll_interval=0.01)
        except TimeoutError:
            wait_seconds = time.monotonic() - started
            report = {
                "status": "skipped",
                "reason": "flock-timeout",
                "entrypoint": entrypoint,
                "session_id": session_id,
                "lock_path": str(lock_path),
                "wait_seconds": wait_seconds,
            }
            print(
                f"[cleanup] flock-timeout entrypoint={entrypoint} session_id={session_id} "
                f"lock_path={lock_path} wait_seconds={wait_seconds:.3f}",
                file=sys.stderr,
            )
            return report
        try:
            lock_file.seek(0)
            try:
                lock_payload = json.loads(lock_file.read() or "{}")
            except json.JSONDecodeError:
                lock_payload = {}
            now_epoch = time.time()
            coalesce_window = min(max(0.0, float(timeout_seconds)), 1.0)
            last_started_at = lock_payload.get("last_cleanup_started_at") if isinstance(lock_payload, dict) else None
            if isinstance(last_started_at, (int, float)) and now_epoch - float(last_started_at) <= coalesce_window:
                return {
                    **context,
                    "status": "skipped",
                    "reason": "cleanup-in-progress",
                    "wait_seconds": time.monotonic() - started,
                }
            lock_file.seek(0)
            lock_file.truncate()
            json.dump(
                {
                    "last_cleanup_started_at": now_epoch,
                    "entrypoint": entrypoint,
                    "session_id": session_id,
                },
                lock_file,
                ensure_ascii=False,
                indent=2,
            )
            lock_file.write("\n")
            lock_file.flush()
            os.fsync(lock_file.fileno())
            result = cleanup_fn(dict(context))
            if not isinstance(result, dict):
                result = {"status": "ok", "result": result}
            return {**context, **result}
        finally:
            _common._unlock(lock_file)


def _default_process_start_time(pid: int) -> Optional[float]:
    if os.name == "nt":
        raise NotImplementedError("process start_time is unsupported on Windows")
    proc_stat = Path("/proc") / str(pid) / "stat"
    proc_root = Path("/proc")
    if proc_stat.exists() and (proc_root / "stat").exists():
        stat_text = proc_stat.read_text(encoding="utf-8")
        stat_tail = stat_text.rsplit(")", 1)[1].strip().split()
        start_ticks = float(stat_tail[19])
        ticks_per_second = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
        boot_time = None
        for line in (proc_root / "stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                boot_time = float(line.split()[1])
                break
        if boot_time is None:
            raise NotImplementedError("process boot time is unavailable")
        return boot_time + (start_ticks / float(ticks_per_second))

    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )
    text = completed.stdout.strip()
    if completed.returncode != 0 or not text:
        return None
    parsed = datetime.strptime(" ".join(text.split()), "%a %b %d %H:%M:%S %Y")
    return time.mktime(parsed.timetuple())


def validate_active_flow_marker(
    marker: Optional[dict],
    *,
    pid_alive: Callable[[int], bool] = is_pid_alive,
    process_start_time: Callable[[int], Optional[float]] = _default_process_start_time,
) -> dict:
    if not isinstance(marker, dict):
        return {"validity": "missing", "reason": "missing"}
    try:
        pid = int(marker.get("pid"))
    except (TypeError, ValueError):
        return {"validity": "dead", "reason": "invalid-pid", "marker": marker}
    try:
        expected_start = float(marker.get("start_time"))
    except (TypeError, ValueError):
        return {"validity": "start_time_mismatch", "reason": "missing-start-time", "marker": marker}

    try:
        alive = pid_alive(pid)
    except Exception:
        return {"validity": "start_time_mismatch", "reason": "pid-lookup-unavailable", "marker": marker}
    if not alive:
        return {"validity": "dead", "reason": "pid-dead", "marker": marker}
    try:
        actual_start = process_start_time(pid)
    except Exception:
        return {"validity": "start_time_mismatch", "reason": "start-time-unavailable", "marker": marker}
    if actual_start is None:
        return {"validity": "start_time_mismatch", "reason": "start-time-unavailable", "marker": marker}
    try:
        actual = float(actual_start)
    except (TypeError, ValueError):
        return {"validity": "start_time_mismatch", "reason": "start-time-unavailable", "marker": marker}
    if abs(actual - expected_start) <= 1.0:
        return {"validity": "active", "reason": "pid-and-start-time-match", "marker": marker}
    return {"validity": "start_time_mismatch", "reason": "start-time-mismatch", "marker": marker}


def write_active_flow_marker(
    *,
    session_id: str,
    pid: int,
    start_time: float,
    mode: str,
    marker_dir: Optional[Path] = None,
    project_root: Optional[Path] = None,
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    update_seq: Optional[int] = None,
    lock_timeout_seconds: float = 5.0,
    extra: Optional[dict] = None,
) -> dict:
    if marker_dir is None:
        if project_root is None:
            raise ValueError("write_active_flow_marker requires marker_dir or project_root")
        marker_dir = _active_flow_dir(Path(project_root))
    marker_dir = Path(marker_dir)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = _active_marker_path(marker_dir, session_id)
    lock_path = marker_dir / f"{session_id}.json.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        _common._lock_exclusive_with_timeout(lock_file, timeout_sec=lock_timeout_seconds)
        lock_acquired_seq = next(_MARKER_LOCK_COUNTER)
        try:
            existing = _load_json_object(marker_path)
            now = _utc_now_iso()
            payload = dict(existing)
            payload.update(extra or {})
            payload.update(
                {
                    "session_id": session_id,
                    "pid": int(pid),
                    "start_time": float(start_time),
                    "mode": mode,
                    "created_at": existing.get("created_at") or created_at or now,
                    "updated_at": updated_at or now,
                    "update_seq": update_seq if update_seq is not None else int(existing.get("update_seq") or 0) + 1,
                    "lock_acquired_seq": lock_acquired_seq,
                    "last_lock_writer_pid": os.getpid(),
                }
            )
            _atomic_json_write(marker_path, payload)
            return dict(payload)
        finally:
            _common._unlock(lock_file)


def should_stophook_single_shot_fallthrough(
    marker: Optional[dict],
    *,
    hook_session_id: Optional[str],
    hook_target_pid,
) -> bool:
    if not isinstance(marker, dict):
        return False
    try:
        marker_pid = int(marker.get("pid"))
        target_pid = int(hook_target_pid)
    except (TypeError, ValueError):
        return False
    return (
        marker.get("mode") == "single-shot"
        and bool(hook_session_id)
        and marker.get("session_id") == hook_session_id
        and marker_pid == target_pid
    )


def decide_cleanup_action(
    *,
    entrypoint: str,
    marker: Optional[dict],
    marker_validity: str,
    hook_session_id: Optional[str] = None,
    hook_target_pid=None,
    hook_process_pid: Optional[int] = None,
) -> dict:
    validity = marker_validity or "missing"
    marker_mode = marker.get("mode") if isinstance(marker, dict) else None
    if entrypoint == "phase5":
        action = "real-cleanup+unlink" if validity != "missing" else "real-cleanup"
    elif entrypoint == "mstloop":
        action = "skip" if validity == "active" else "real-cleanup"
    elif entrypoint == "stophook":
        if validity != "active":
            action = "fallthrough"
        elif marker_mode == "single-shot":
            action = "fallthrough-if-hook-session-and-MST_HOOK_TARGET_PID-match-else-skip"
        else:
            action = "skip"
    elif entrypoint == "stale-marker":
        if validity == "active":
            action = "skip"
        elif validity == "missing":
            action = "stub-report"
        else:
            action = "real-cleanup"
    else:
        action = "real-cleanup"
    resolved_action = action
    if action == "fallthrough-if-hook-session-and-MST_HOOK_TARGET_PID-match-else-skip":
        resolved_action = (
            "fallthrough"
            if should_stophook_single_shot_fallthrough(
                marker,
                hook_session_id=hook_session_id,
                hook_target_pid=hook_target_pid,
            )
            else "skip"
        )
    return {
        "action": action,
        "resolved_action": resolved_action,
        "real_cleanup": resolved_action in {"real-cleanup", "real-cleanup+unlink", "fallthrough"},
        "unlink_marker": action == "real-cleanup+unlink",
        "hook_process_pid": hook_process_pid,
    }


def stophook_target_pid_from_env(env: Optional[dict] = None) -> Optional[int]:
    raw = (env or os.environ).get("MST_HOOK_TARGET_PID")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def decide_stop_hook_cleanup(
    *,
    abnormal_exit: Optional[str],
    hook_session_id: Optional[str],
    marker: Optional[dict],
    marker_validity: str,
    hook_target_pid=None,
    hook_process_pid: Optional[int] = None,
) -> dict:
    if hook_target_pid is None:
        hook_target_pid = stophook_target_pid_from_env()
    decision = decide_cleanup_action(
        entrypoint="stophook",
        marker=marker,
        marker_validity=marker_validity,
        hook_session_id=hook_session_id,
        hook_target_pid=hook_target_pid,
        hook_process_pid=hook_process_pid,
    )
    action = decision["resolved_action"]
    if abnormal_exit and marker_validity != "active":
        action = "fallthrough"
    return {
        **decision,
        "action": action,
        "abnormal_exit": abnormal_exit,
        "real_cleanup": action == "fallthrough",
    }


def filter_stophook_kill_candidates(
    candidates: Iterable,
    *,
    marker_pid=None,
    hook_process_pid: Optional[int] = None,
) -> list[int]:
    excluded = set()
    for value in (marker_pid, hook_process_pid if hook_process_pid is not None else os.getpid()):
        try:
            excluded.add(int(value))
        except (TypeError, ValueError):
            pass
    result: list[int] = []
    for candidate in candidates or []:
        try:
            pid = int(candidate)
        except (TypeError, ValueError):
            continue
        if pid > 0 and pid not in excluded:
            result.append(pid)
    return result


def scan_active_flow_markers(active_dir: Path) -> list[dict]:
    active_dir = Path(active_dir)
    if not active_dir.is_dir():
        return []
    markers: list[dict] = []
    for path in sorted(active_dir.glob("*.json")):
        if path.name.endswith(".lock"):
            continue
        payload = _load_json_object(path)
        if not payload:
            continue
        payload.setdefault("session_id", path.stem)
        payload["path"] = str(path)
        markers.append(payload)
    return markers


def active_marker_skip_inputs(active_dir: Path) -> list[dict]:
    return [marker for marker in scan_active_flow_markers(active_dir) if marker.get("status") != "ignored"]


def _ignored_marker_payload(payload: dict, *, ignored_for_session_id: str) -> dict:
    updated = dict(payload)
    updated["status"] = "ignored"
    updated["ignored_for_session_id"] = ignored_for_session_id
    updated["ignored_at"] = _utc_now_iso()
    return updated


def recover_takeover_active_marker(
    *,
    active_dir: Path,
    old_sid: str,
    new_sid: str,
    rename_func: Optional[Callable[[Path, Path], None]] = None,
) -> dict:
    active_dir = Path(active_dir)
    active_dir.mkdir(parents=True, exist_ok=True)
    old_path = _active_marker_path(active_dir, old_sid)
    new_path = _active_marker_path(active_dir, new_sid)
    rename_func = rename_func or (lambda src, dst: src.rename(dst))

    if new_path.exists():
        if old_path.exists():
            _atomic_json_write(old_path, _ignored_marker_payload(_load_json_object(old_path), ignored_for_session_id=new_sid))
            return {"status": "old-ignored", "old_sid": old_sid, "new_sid": new_sid}
        return {"status": "new-canonical", "old_sid": old_sid, "new_sid": new_sid}

    if not old_path.exists():
        payload = {
            "session_id": new_sid,
            "pid": os.getpid(),
            "start_time": time.time(),
            "mode": "marathon",
            "created_at": _utc_now_iso(),
            "recovered_from_session_id": old_sid,
        }
        _atomic_json_write(new_path, payload)
        return {"status": "new-canonical", "old_sid": old_sid, "new_sid": new_sid}

    old_payload = _load_json_object(old_path)
    new_payload = dict(old_payload)
    new_payload["session_id"] = new_sid
    new_payload["recovered_from_session_id"] = old_sid
    new_payload["updated_at"] = _utc_now_iso()
    try:
        rename_func(old_path, new_path)
        _atomic_json_write(new_path, new_payload)
        return {"status": "renamed", "old_sid": old_sid, "new_sid": new_sid}
    except OSError:
        _atomic_json_write(new_path, new_payload)
        if old_path.exists():
            _atomic_json_write(old_path, _ignored_marker_payload(old_payload, ignored_for_session_id=new_sid))
        return {"status": "rename-fallback", "old_sid": old_sid, "new_sid": new_sid}


def plan_cleanup_targets(
    *,
    project_root: Path,
    entrypoint: str,
    target_session_id: Optional[str] = None,
    markers: Optional[list[dict]] = None,
    marker_validity: Optional[dict[str, str]] = None,
    active_sessions: Optional[set[str]] = None,
    active_worktrees: Optional[set[str]] = None,
    active_branches: Optional[set[str]] = None,
    candidate_pids: Optional[Iterable] = None,
    candidate_worktrees: Optional[Iterable] = None,
    candidate_meta: Optional[Iterable] = None,
    candidate_branches: Optional[Iterable] = None,
) -> dict:
    project_root = Path(project_root)
    active_sessions = set(active_sessions or set())
    active_worktrees = {str(Path(path)) for path in (active_worktrees or set())}
    active_branches = set(active_branches or set())
    marker_validity = marker_validity or {}
    protected_pids: set[int] = {os.getpid()}

    for marker in markers or []:
        sid = str(marker.get("session_id") or "")
        if marker_validity.get(sid) == "active":
            active_sessions.add(sid)
            try:
                protected_pids.add(int(marker.get("pid")))
            except (TypeError, ValueError):
                pass

    remove_worktrees = [
        str(Path(path))
        for path in (candidate_worktrees or [])
        if str(Path(path)) not in active_worktrees
    ]
    archive_meta = [
        str(Path(path))
        for path in (candidate_meta or [])
        if str(Path(path).parent) not in active_worktrees
    ]
    delete_branches = [
        str(branch)
        for branch in (candidate_branches or [])
        if str(branch) not in active_branches
    ]
    kill_pids = [
        pid for pid in filter_stophook_kill_candidates(candidate_pids or [], marker_pid=None, hook_process_pid=os.getpid())
        if pid not in protected_pids
    ]

    return {
        "project_root": str(project_root),
        "entrypoint": entrypoint,
        "target_session_id": target_session_id,
        "active_sessions": sorted(active_sessions),
        "remove_worktrees": remove_worktrees,
        "archive_meta": archive_meta,
        "delete_branches": delete_branches,
        "kill_pids": kill_pids,
    }


def write_active_flow_marker_for_pid(
    *,
    project_root: Path,
    session_id: str,
    pid: int,
    mode: str,
    extra: Optional[dict] = None,
) -> dict:
    try:
        start_time = _default_process_start_time(int(pid))
    except Exception:
        start_time = None
    if start_time is None:
        start_time = time.time()
    return write_active_flow_marker(
        project_root=Path(project_root),
        session_id=session_id,
        pid=int(pid),
        start_time=float(start_time),
        mode=mode,
        extra=extra,
    )


def _cleanup_completed_requests(args) -> dict:
    dirs = sorted(requests_dir().glob("REQ-*"))
    stale = []
    for d in dirs:
        if not d.is_dir():
            continue
        data = load_json(d / "request.json") or {}
        if data.get("status") in ("completed", "cancelled"):
            stale.append((d, data))

    if not stale:
        print("Nothing to clean up.")
        return {"status": "ok", "archived": 0}

    print(f"Found {len(stale)} completed/cancelled sessions:")
    for d, data in stale:
        print(f"  {d.name}: {data.get('title', '')[:50]}")

    if args.dry_run:
        print("[dry-run] No changes made.")
        return {"status": "ok", "dry_run": True, "archived": 0}

    dst_dir = type_archived_dir("req")
    dst_dir.mkdir(parents=True, exist_ok=True)
    ids = [d.name for d in stale]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if len(ids) == 1:
        archive_name = f"requests-{ids[0]}-{timestamp}.tar.gz"
    else:
        archive_name = f"requests-{ids[0]}-to-{ids[-1]}-{timestamp}.tar.gz"
    archive_path = dst_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        for d, _ in stale:
            tar.add(d, arcname=d.name)

    for d, _ in stale:
        shutil.rmtree(d)

    print(f"Archived {len(stale)} sessions → {archive_name}")
    return {"status": "ok", "archived": len(stale), "archive": str(archive_path)}


def cmd_cleanup(args):
    project_root = _common.BASE_DIR.parent
    session_id = os.environ.get("MST_SESSION_ID", "").strip() or "direct-cli"
    result = run_cleanup_with_lock_report(
        project_root=project_root,
        entrypoint="direct-cli",
        session_id=session_id,
        timeout_seconds=5.0,
        cleanup_fn=lambda _context: _cleanup_completed_requests(args),
    )
    if result.get("status") == "skipped":
        print(f"[cleanup] skipped: {result.get('reason', 'unknown')}", file=sys.stderr)
    return 0


def register(subparsers):
    sub = subparsers
    cln = sub.add_parser("cleanup")
    cln.add_argument("--dry-run", action="store_true")
