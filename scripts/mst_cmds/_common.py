from __future__ import annotations

import argparse
import copy
import errno
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

from scripts.mst_cmds.env_alias_compat import canonical_session_id_from_env
from scripts._state_schema import TERMINAL
from scripts._state_normalize import migrate_legacy_status

if os.name == "nt":
    import msvcrt
else:
    import fcntl

BASE_DIR_NAME = ".gran-maestro"
BASE_DIR: Path = None
_MST_SESSION_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def set_base_dir(base_dir: Path | None) -> Path | None:
    global BASE_DIR
    BASE_DIR = base_dir
    return BASE_DIR


def _plugin_root():
    """플러그인 루트 경로 반환 (scripts/ 상위)."""
    return Path(__file__).resolve().parents[2]


def _scripts_dir() -> Path:
    return _plugin_root() / "scripts"


def _mst_script_path() -> Path:
    return _scripts_dir() / "mst.py"

def find_base_dir(start: Path = None) -> Path:
    """Walk up from start (or cwd) to find .gran-maestro/"""
    if start is None:
        start = Path.cwd()
    current = start.resolve()
    while True:
        candidate = current / ".gran-maestro"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            print("Error: .gran-maestro/ directory not found in any ancestor directory.", file=sys.stderr)
            sys.exit(1)
        current = parent

def load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def deep_merge(base, override, depth=0):
    if depth > 20:
        return override

    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    result = dict(base)
    for key, override_value in override.items():
        base_value = base.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = deep_merge(base_value, override_value, depth + 1)
        elif isinstance(override_value, list):
            result[key] = override_value
        else:
            result[key] = override_value
    return result

def _base_dir_name() -> str:
    return BASE_DIR.name if BASE_DIR is not None else BASE_DIR_NAME


def base_dir_from_project(project_root: Path) -> Path:
    return project_root / _base_dir_name()


def cwd_base_dir() -> Path:
    return Path.cwd().resolve() / _base_dir_name()


def requests_dir() -> Path:
    return BASE_DIR / "requests"


def plans_dir() -> Path:
    return BASE_DIR / "plans"


def run_dir() -> Path:
    path = BASE_DIR / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_dir_no_create() -> Path:
    return BASE_DIR / "run" if BASE_DIR is not None else cwd_base_dir() / "run"


def state_dir(base_dir: Path | None = None) -> Path:
    return (base_dir or BASE_DIR) / "state"


def is_path_safe_mst_session_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text and _MST_SESSION_ID_SAFE_RE.fullmatch(text) and ".." not in text)


def _json_object_from_env(name: str) -> dict | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def structured_mst_session_id_from_env() -> str | None:
    for env_name in ("MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        payload = _json_object_from_env(env_name)
        if not isinstance(payload, dict):
            continue
        value = payload.get("mst_session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        core = payload.get("core_rehydration")
        if isinstance(core, dict):
            value = core.get("mst_session_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def canonical_mst_session_id_from_env_or_context() -> str | None:
    env_value = canonical_session_id_from_env()
    context_value = structured_mst_session_id_from_env()
    if env_value and context_value and env_value != context_value:
        raise ValueError("MST_SESSION_ID and structured mst_session_id mismatch")
    value = env_value or context_value
    if value and not is_path_safe_mst_session_id(value):
        raise ValueError("invalid mst_session_id path segment")
    return value


def require_mst_session_id_for_mutation(subject: str = "state write") -> str:
    value = canonical_mst_session_id_from_env_or_context()
    if not value:
        raise ValueError(f"missing MST_SESSION_ID for {subject}")
    return value


def legacy_session_diagnostics() -> dict:
    diagnostics: dict[str, object] = {}
    ppid = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid:
        diagnostics["MST_STATE_PPID"] = ppid
    snapshot_alias = os.environ.get("MST_SNAPSHOT_SESSION_ID", "").strip()
    if snapshot_alias:
        diagnostics["MST_SNAPSHOT_SESSION_ID"] = snapshot_alias
    for env_name in ("MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        payload = _json_object_from_env(env_name)
        if not isinstance(payload, dict):
            continue
        hook_session_id = payload.get("session_id")
        if isinstance(hook_session_id, str) and hook_session_id.strip():
            diagnostics["hook_session_id"] = hook_session_id.strip()
        transcript_path = payload.get("transcript_path")
        if isinstance(transcript_path, str) and transcript_path.strip():
            stem = Path(transcript_path).name
            diagnostics["hook_transcript_stem"] = stem[:-6] if stem.endswith(".jsonl") else Path(stem).stem
    return diagnostics


def sessions_dir(project_root: Path) -> Path:
    return base_dir_from_project(project_root) / "sessions"


def worktrees_dir(project_root: Path) -> Path:
    return base_dir_from_project(project_root) / "worktrees"


def tmp_dir(project_root: Path) -> Path:
    return base_dir_from_project(project_root) / "tmp"


def backups_dir(base_dir: Path) -> Path:
    return base_dir / "backups"


def logs_dir(base_dir: Path) -> Path:
    return base_dir / "logs"

def iter_request_dirs(include_completed=False):
    """Yield (req_id, path, data) tuples."""
    for req_path in sorted(requests_dir().glob("REQ-*")):
        if not req_path.is_dir():
            continue
        rj = load_json(req_path / "request.json")
        if rj:
            yield rj.get("id", req_path.name), req_path, rj
    if include_completed:
        archived = type_archived_dir("req")
        if archived.exists():
            for arc_file in sorted(archived.glob("*.tar.gz")):
                try:
                    with tarfile.open(arc_file, "r:gz") as tar:
                        for member in tar.getmembers():
                            if (member.name.endswith("/request.json")
                                    and member.name.count("/") == 1):
                                f = tar.extractfile(member)
                                if f:
                                    rj = json.loads(f.read().decode("utf-8"))
                                    yield rj.get("id", member.name.split("/")[0]), arc_file, rj
                except Exception:
                    pass

def iter_plan_dirs():
    """Yield (pln_id, path, data) tuples."""
    pd = plans_dir()
    if not pd.exists():
        return
    for pln_path in sorted(pd.glob("PLN-*")):
        if not pln_path.is_dir():
            continue
        pj = load_json(pln_path / "plan.json")
        if pj:
            yield pj.get("id", pln_path.name), pln_path, pj

WORKFLOW_MAX_ITERATIONS = 20

WORKFLOW_STALL_LIMIT = 3

WORKFLOW_TERMINAL_STATUSES = frozenset(status.lower() for status in TERMINAL)

def _request_json_path(req_id: str) -> Path:
    return BASE_DIR / "requests" / req_id / "request.json"

def _plan_json_path(pln_id: str) -> Path:
    return BASE_DIR / "plans" / pln_id / "plan.json"

def _load_request(req_id: str):
    return load_json(_request_json_path(req_id))

def _load_plan(pln_id: str):
    return load_json(_plan_json_path(pln_id))

def _phase_value(raw_phase) -> Optional[int]:
    try:
        return int(raw_phase)
    except (TypeError, ValueError):
        return None

def _phase_status_tuple(data):
    return _phase_value(data.get("current_phase")), str(data.get("status", ""))

def _is_terminal(phase: Optional[int], status: str) -> bool:
    status_normalized = (status or "").lower()
    if status_normalized in WORKFLOW_TERMINAL_STATUSES:
        return True
    if phase != 5:
        return False
    migrated_status = migrate_legacy_status(status_normalized).lower()
    return migrated_status in WORKFLOW_TERMINAL_STATUSES

def next_action(current_phase, status):
    phase = _phase_value(current_phase)
    status_normalized = (status or "").lower()
    if status_normalized in WORKFLOW_TERMINAL_STATUSES:
        return None
    if phase == 1 and status_normalized in {"phase1_analysis", "spec_ready"}:
        return "mst:approve"
    if phase == 2 and status_normalized == "phase2_execution":
        return "mst:approve"
    if phase == 3 and status_normalized == "phase3_review":
        return "mst:approve"
    if phase == 5:
        return "mst:accept"
    return None

def _skill_state_base_dir() -> Path:
    local_base_dir = Path.cwd().resolve() / ".gran-maestro"
    try:
        session_id = canonical_mst_session_id_from_env_or_context()
    except Exception:
        session_id = None

    def has_session_state(base_dir: Path | None) -> bool:
        if not base_dir or not session_id:
            return False
        return (
            (base_dir / "tmp" / f"mst-state-{session_id}.json").exists()
            or (base_dir / "state" / session_id / "snapshot.json").exists()
        )

    if has_session_state(local_base_dir):
        return local_base_dir
    if BASE_DIR and os.access(BASE_DIR, os.W_OK) and has_session_state(BASE_DIR):
        return BASE_DIR
    if local_base_dir.exists():
        return local_base_dir
    if BASE_DIR and os.access(BASE_DIR, os.W_OK):
        return BASE_DIR
    return local_base_dir

def _parse_bool_arg(value):
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Expected true/false.")

def _workflow_state_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _workflow_state_default_payload(now: str):
    return {
        "workflow_active": False,
        "next_action": {
            "skill": "",
            "source": "",
            "auto": False,
            "expected_skill": "",
            "source_skill": "",
            "source_id": "",
            "auto_mode": False,
        },
        "current_skill": "",
        "active_req": "",
        "iteration": 0,
        "agile_loop_active": False,
        "steering_disabled": False,
        "block_count": 0,
        "last_block_reason": "",
        "last_active_at": None,
        "updated_at": now,
    }

def _workflow_state_file(base_dir: Path) -> Path:
    session_id = require_mst_session_id_for_mutation("workflow state path")
    return base_dir / "tmp" / f"mst-state-{session_id}.json"

def _workflow_state_load(path: Path):
    payload = load_json(path)
    if isinstance(payload, dict):
        return payload
    return None

def is_pid_alive(pid) -> bool:
    """Return True iff the given PID is currently alive.

    Returns False on:
      - TypeError / ValueError (pid cannot be cast to int)
      - OSError (pid is not accessible or dead)
    Never raises.
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
        return True
    except (OSError, PermissionError):
        return False

def _resolve_base_dir_for_session_anchor(base_dir: Path | None = None) -> Path | None:
    if base_dir is not None:
        return Path(base_dir)
    if BASE_DIR is not None:
        return BASE_DIR
    current = Path.cwd().resolve()
    while True:
        candidate = current / ".gran-maestro"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent

def resolve_started_by_pid(base_dir: Path | None = None) -> int:
    raw = os.environ.get("MST_STATE_PPID", "").strip()
    if raw:
        try:
            pid = int(raw)
        except ValueError:
            pid = 0
        if pid > 0:
            return pid

    resolved_base = _resolve_base_dir_for_session_anchor(base_dir)
    if resolved_base is not None:
        candidates = []
        for anchor_path in (resolved_base / "tmp").glob("mst-session-anchor-*.pid"):
            try:
                anchor_pid = int(anchor_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            if not is_pid_alive(anchor_pid):
                continue
            try:
                mtime = anchor_path.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, anchor_pid))
        if candidates:
            candidates.sort()
            return candidates[-1][1]

    return int(os.getppid())

def read_workflow_state_auto_mode(
    skill_name: str,
    expected_source_id: Optional[str] = None,
    ttl_minutes: int = 30,
) -> Optional[bool]:
    """
    Returns auto_mode value from tmp/mst-state-{mst_session_id}.json IFF all authoritative
    conditions pass. Returns None when state should be treated as absent
    (caller must fall back to config/default).

    Authoritative gates:
      1) payload.workflow_active == True
      2) payload.next_action.expected_skill == skill_name
      3) when expected_source_id is provided:
         payload.next_action.source_id == expected_source_id
      4) payload.updated_at within ttl_minutes of now (UTC)
    On ANY failure (missing file, JSON parse error, key missing, gate fail,
    stale state) -> return None (never raise).
    """
    try:
        state_path = _workflow_state_file(_skill_state_base_dir())
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            return None

        if payload.get("workflow_active") is not True:
            return None

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            return None
        if "expected_skill" not in next_action or next_action.get("expected_skill") != skill_name:
            return None
        if expected_source_id is not None:
            if "source_id" not in next_action or next_action.get("source_id") != expected_source_id:
                return None

        if "updated_at" not in payload:
            return None
        updated_at_raw = payload.get("updated_at")
        if not isinstance(updated_at_raw, str):
            return None
        updated_at_text = updated_at_raw.strip()
        if not updated_at_text:
            return None
        if updated_at_text.endswith("Z"):
            updated_at_text = f"{updated_at_text[:-1]}+00:00"
        updated_at = datetime.fromisoformat(updated_at_text)
        if updated_at.tzinfo is None:
            return None
        updated_at_utc = updated_at.astimezone(timezone.utc)

        ttl_delta = timedelta(minutes=int(ttl_minutes))
        if ttl_delta.total_seconds() < 0:
            return None
        now_utc = datetime.now(timezone.utc)
        age = now_utc - updated_at_utc
        if age < timedelta(0) or age > ttl_delta:
            return None

        if "auto_mode" not in next_action:
            return None
        auto_mode = next_action.get("auto_mode")
        if not isinstance(auto_mode, bool):
            return None
        return auto_mode
    except Exception:
        return None

def _workflow_state_atomic_write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)

def _queue_path() -> Path:
    path = _skill_state_base_dir() / "pending.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def _queue_lock_path() -> Path:
    return _skill_state_base_dir() / "pending.ndjson.lock"

def _queue_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def _queue_parse_entries(raw_lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    for line in raw_lines:
        text = line.strip()
        if not text:
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entry_id = value.get("entry_id")
            if not isinstance(entry_id, str) or not entry_id.strip():
                value["entry_id"] = uuid.uuid4().hex
            entries.append(value)
    return entries

def _queue_build_entry(data: dict) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "entry_id": uuid.uuid4().hex,
        "skill": str(data.get("skill", "")),
        "args": str(data.get("args", "")),
        "source_skill": str(data.get("source_skill", "")),
        "source_id": str(data.get("source_id", "")),
        "resource_id": str(data.get("resource_id", "")),
        "auto": bool(data.get("auto", False)),
        "status": "queued",
        "created_at": _queue_timestamp(),
        "consumed_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
    }

def _validate_enqueue_entry(entry: dict) -> None:
    """auto=true인 entry가 args에 -a/--auto 토큰을 포함하는지 검증."""
    if not isinstance(entry, dict):
        return
    auto = bool(entry.get("auto", False))
    if not auto:
        return
    args = entry.get("args", "") or ""
    if not isinstance(args, str):
        args = str(args)
    tokens = args.split()
    if "-a" in tokens or "--auto" in tokens:
        return
    raise ValueError(
        "queue_enqueue: auto=true entry는 args에 '-a' 또는 '--auto' 토큰을 포함해야 합니다 "
        f"(skill={entry.get('skill')!r}, args={args!r})"
    )

_WINDOWS_LOCK_BYTES = 0x7FFFFFFF

def _lock_shared(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_RLCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_SH)

def _lock_exclusive(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)

def _lock_exclusive_with_timeout(file_obj, timeout_sec: float = 5.0, poll_interval: float = 0.05):
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    if os.name == "nt":
        while True:
            try:
                file_obj.seek(0)
                msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, _WINDOWS_LOCK_BYTES)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"lock timeout ({timeout_sec}s) - another session is writing")
                time.sleep(poll_interval)

    while True:
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (BlockingIOError, OSError) as exc:
            if isinstance(exc, OSError) and exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lock timeout ({timeout_sec}s) - another session is writing")
            time.sleep(poll_interval)

def _unlock(file_obj):
    if os.name == "nt":
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, _WINDOWS_LOCK_BYTES)
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)

def _queue_read_entries() -> list[dict]:
    path = _queue_path()
    if not path.exists():
        return []

    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_shared(lock_f)
        try:
            if not path.exists():
                return []
            with open(path, "r", encoding="utf-8") as f:
                return _queue_parse_entries(f.read().splitlines())
        finally:
            _unlock(lock_f)

def _queue_compact(mutator):
    path = _queue_path()
    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_exclusive(lock_f)
        try:
            if not path.exists():
                new_entries, result = mutator([])
                if new_entries:
                    tmp_name = None
                    try:
                        tmp = tempfile.NamedTemporaryFile(
                            mode="w",
                            encoding="utf-8",
                            delete=False,
                            dir=str(path.parent),
                            prefix=".pending.",
                            suffix=".tmp",
                        )
                        tmp_name = tmp.name
                        for entry in new_entries:
                            tmp.write(_compact_json(entry) + "\n")
                        tmp.flush()
                        os.fsync(tmp.fileno())
                        tmp.close()
                        os.replace(tmp_name, path)
                    except Exception:
                        if tmp_name:
                            try:
                                os.unlink(tmp_name)
                            except OSError:
                                pass
                        raise
                return result

            with open(path, "r", encoding="utf-8") as f:
                entries = _queue_parse_entries(f.read().splitlines())
            new_entries, result = mutator(entries)

            tmp_name = None
            try:
                tmp = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                    dir=str(path.parent),
                    prefix=".pending.",
                    suffix=".tmp",
                )
                tmp_name = tmp.name
                for entry in new_entries:
                    tmp.write(_compact_json(entry) + "\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp_name, path)
            except Exception:
                if tmp_name:
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                raise
            return result
        finally:
            _unlock(lock_f)

def queue_enqueue(data: dict) -> dict:
    _validate_enqueue_entry(data)
    entry = _queue_build_entry(data)
    path = _queue_path()
    lock_path = _queue_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    line = _compact_json(entry) + "\n"

    with open(lock_path, "a+", encoding="utf-8") as lock_f:
        _lock_exclusive(lock_f)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            _unlock(lock_f)

    return entry

def queue_peek() -> dict | None:
    for entry in _queue_read_entries():
        if entry.get("status") == "queued":
            return copy.deepcopy(entry)
    return None

def queue_mark_running(entry_id: str) -> dict | None:
    target_entry_id = str(entry_id or "")
    if not target_entry_id:
        return None

    def _mutator(entries):
        for entry in entries:
            if entry.get("entry_id") != target_entry_id:
                continue
            if entry.get("status") != "queued":
                return entries, None
            entry["status"] = "running"
            entry["consumed_at"] = _queue_timestamp()
            return entries, copy.deepcopy(entry)
        return entries, None

    return _queue_compact(_mutator)

def queue_pop() -> dict | None:
    while True:
        peeked = None
        for entry in _queue_read_entries():
            if entry.get("status") == "queued":
                peeked = entry
                break
        if peeked is None:
            return None
        entry_id = peeked.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            continue
        result = queue_mark_running(entry_id)
        if result is not None:
            return result

def queue_list(status: str | None) -> list[dict]:
    entries = _queue_read_entries()
    if not status or status == "all":
        return entries
    return [entry for entry in entries if entry.get("status") == status]

def queue_complete(action_id: str, result: str | None = None) -> dict | None:
    """Mark queue entry complete by `entry_id` (preferred) or legacy `id`."""
    now = _queue_timestamp()
    warn = None

    def _mutator(entries):
        nonlocal warn
        for entry in entries:
            matches_entry_id = entry.get("entry_id") == action_id
            matches_id = entry.get("id") == action_id
            if not (matches_entry_id or matches_id):
                continue
            status = str(entry.get("status", ""))
            if status in ("done", "failed"):
                warn = f"already terminal: {action_id}"
                return entries, copy.deepcopy(entry)
            entry["status"] = "done"
            entry["completed_at"] = now
            if result is not None:
                entry["result"] = result
            return entries, copy.deepcopy(entry)
        warn = f"action not found: {action_id}"
        return entries, None

    output = _queue_compact(_mutator)
    if warn:
        print(f"[mst] warning: {warn}", file=sys.stderr)
    return output

def queue_fail(action_id: str, error: str | None = None) -> dict | None:
    """Mark queue entry failed by `entry_id` (preferred) or legacy `id`."""
    now = _queue_timestamp()
    warn = None

    def _mutator(entries):
        nonlocal warn
        for entry in entries:
            matches_entry_id = entry.get("entry_id") == action_id
            matches_id = entry.get("id") == action_id
            if not (matches_entry_id or matches_id):
                continue
            status = str(entry.get("status", ""))
            if status in ("done", "failed"):
                warn = f"already terminal: {action_id}"
                return entries, copy.deepcopy(entry)
            entry["status"] = "failed"
            entry["completed_at"] = now
            if error is not None:
                entry["error"] = error
            return entries, copy.deepcopy(entry)
        warn = f"action not found: {action_id}"
        return entries, None

    output = _queue_compact(_mutator)
    if warn:
        print(f"[mst] warning: {warn}", file=sys.stderr)
    return output

def queue_count(status: str = "queued") -> int:
    return len(queue_list(status))

def _create_intent_store():
    try:
        from scripts.intent_store import IntentStoreError, SqliteIntentStore
        store = SqliteIntentStore(BASE_DIR.parent)
    except ImportError as exc:
        print(
            f"Error: intent store dependency missing ({exc}). Install with: pip install pyyaml",
            file=sys.stderr,
        )
        return None, Exception
    except Exception as exc:
        print(f"Error: failed to initialize intent store ({exc})", file=sys.stderr)
        return None, Exception
    return store, IntentStoreError

def fact_checks_dir() -> Path:
    return BASE_DIR / "fact-checks"

def _normalize_fact_check_id(value: str) -> str:
    fc_id = (value or "").strip().upper()
    if not re.fullmatch(r"FC-\d+", fc_id):
        raise ValueError(f"Invalid fact-check id: {value}")
    return fc_id

def _fact_check_path(fc_id: str) -> Path:
    return fact_checks_dir() / fc_id / "fact-check.json"

def _iter_fact_check_paths():
    pattern = str(fact_checks_dir() / "FC-*" / "fact-check.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]

DEFAULT_REFERENCE_KEYWORDS = [
    "library",
    "framework",
    "api",
    "sdk",
    "protocol",
    "version",
    "dependency",
    "react",
    "next.js",
    "typescript",
    "python",
    "node",
    "라이브러리",
    "프레임워크",
    "의존성",
    "버전",
]

DEFAULT_REFERENCE_CONFIG = {
    "cache_ttl_days": 7,
    "cutoff_threshold_months": 1,
    "auto_search": True,
    "max_searches_per_step": 3,
}

def agile_dir() -> Path:
    return BASE_DIR / "agile"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _normalize_agi_id(value: str) -> str:
    agi_id = (value or "").strip().upper()
    if not re.fullmatch(r"AGI-\d+", agi_id):
        raise ValueError(f"Invalid AGI id: {value}")
    return agi_id

def _normalize_link_id(value: str, prefix: str) -> str:
    token = (value or "").strip().upper()
    if not token:
        raise ValueError(f"Invalid {prefix} id: {value}")
    if not token.startswith(f"{prefix}-"):
        raise ValueError(f"Invalid {prefix} id: {value}")
    return token

def _split_csv_values(raw_values) -> List[str]:
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    values = []
    for raw_value in raw_values:
        for token in str(raw_value).split(","):
            cleaned = token.strip()
            if cleaned:
                values.append(cleaned)
    return values

_SOURCE_MAPPING_RE = re.compile(
    r"^<!--\s*source-mapping:\s*original=(?P<original>\S+)\s+sections=\[(?P<sections>.*?)\]\s*-->$"
)

def _parse_source_mapping_sections(raw_sections: str) -> tuple[list[str], list[str]]:
    sections: list[str] = []
    errors: list[str] = []

    for raw_token in str(raw_sections).split(","):
        token = raw_token.strip()
        if not token:
            continue
        if token.startswith(("'", '"')):
            if len(token) < 2 or token[-1] != token[0]:
                errors.append(f"invalid section token: {raw_token.strip()}")
                continue
            token = token[1:-1].strip()
        elif token.endswith(("'", '"')):
            errors.append(f"invalid section token: {raw_token.strip()}")
            continue
        if not token:
            errors.append(f"invalid section token: {raw_token.strip()}")
            continue
        sections.append(token)

    if not sections:
        errors.append("sections list is empty")

    return sections, errors

def parse_source_mapping(text: str) -> dict:
    result = {
        "original": None,
        "sections": [],
        "valid": False,
        "errors": [],
    }
    lines = str(text).splitlines()
    if not lines:
        result["errors"].append("source-mapping metadata is missing in first line")
        return result

    first_line = lines[0].strip()
    if not first_line:
        result["errors"].append("source-mapping metadata is missing in first line")
        return result

    match = _SOURCE_MAPPING_RE.fullmatch(first_line)
    if match is None:
        result["errors"].append("source-mapping metadata is missing or malformed in first line")
        return result

    sections, section_errors = _parse_source_mapping_sections(match.group("sections"))
    if section_errors:
        result["errors"].extend(section_errors)
        return result

    result["original"] = match.group("original")
    result["sections"] = sections
    result["valid"] = True
    return result

def _strip_balanced_quotes(value: str) -> str:
    token = str(value).strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1].strip()
    return token

def _extract_frontmatter_block(content: str) -> dict:
    lines = str(content).splitlines(keepends=True)
    payload = {
        "has_frontmatter": False,
        "frontmatter": "",
        "prefix": "",
        "suffix": str(content),
        "errors": [],
    }
    if not lines:
        return payload

    probe_index = 0
    first_line = lines[0].strip()
    if _SOURCE_MAPPING_RE.fullmatch(first_line):
        probe_index = 1

    while probe_index < len(lines) and not lines[probe_index].strip():
        probe_index += 1

    if probe_index >= len(lines) or lines[probe_index].strip() != "---":
        return payload

    for end_index in range(probe_index + 1, len(lines)):
        if lines[end_index].strip() != "---":
            continue
        payload["has_frontmatter"] = True
        payload["frontmatter"] = "".join(lines[probe_index + 1:end_index])
        payload["prefix"] = "".join(lines[:probe_index])
        payload["suffix"] = "".join(lines[end_index + 1:])
        return payload

    payload["errors"].append("frontmatter block is malformed")
    return payload

def _extract_yaml_scalar(frontmatter: str, key: str):
    pattern = re.compile(rf"(?m)^[ \t]*{re.escape(str(key))}[ \t]*:[ \t]*([^\n\r]*)[ \t]*$")
    match = pattern.search(str(frontmatter))
    if match is None:
        return None
    return _strip_balanced_quotes(match.group(1))

def _extract_yaml_list(frontmatter: str, key: str):
    lines = str(frontmatter).splitlines()
    key_re = re.compile(rf"^(\s*){re.escape(str(key))}\s*:\s*(.*?)\s*$")
    item_re = re.compile(r"^\s*-\s*(.*?)\s*$")

    for index, line in enumerate(lines):
        key_match = key_re.match(line)
        if key_match is None:
            continue

        inline = key_match.group(2).strip()
        if inline:
            if inline.startswith("[") and inline.endswith("]"):
                tokens, token_errors = _parse_source_mapping_sections(inline[1:-1])
                return [] if token_errors else tokens
            parsed = _strip_balanced_quotes(inline)
            return [parsed] if parsed else []

        key_indent = len(key_match.group(1))
        items = []
        probe = index + 1
        while probe < len(lines):
            next_line = lines[probe]
            if not next_line.strip():
                probe += 1
                continue
            leading_spaces = len(next_line) - len(next_line.lstrip(" "))
            if leading_spaces <= key_indent:
                break
            item_match = item_re.match(next_line)
            if item_match is None:
                break
            token = _strip_balanced_quotes(item_match.group(1))
            if token:
                items.append(token)
            probe += 1
        return items
    return None

def _normalize_tbd(value):
    if value is None:
        return "TBD"
    token = str(value).strip()
    if not token or token.upper() == "TBD":
        return "TBD"
    return token

def parse_agile_detail_metadata(content: str) -> dict:
    source_mapping = parse_source_mapping(content)
    frontmatter = _extract_frontmatter_block(content)
    evidence = {}

    artifact_paths = _extract_yaml_list(frontmatter.get("frontmatter"), "artifact_paths")
    entrypoint_path = _extract_yaml_scalar(frontmatter.get("frontmatter"), "entrypoint_path")
    entrypoint = _extract_yaml_scalar(frontmatter.get("frontmatter"), "entrypoint")
    reason = _extract_yaml_scalar(frontmatter.get("frontmatter"), "reason")
    integration_smoke_id = _extract_yaml_scalar(frontmatter.get("frontmatter"), "integration_smoke_id")
    verify_cmd = _extract_yaml_scalar(frontmatter.get("frontmatter"), "verify_cmd")
    expected_signal = _extract_yaml_scalar(frontmatter.get("frontmatter"), "expected_signal")

    has_plan_fields = any(
        field is not None
        for field in (artifact_paths, entrypoint_path, entrypoint, reason)
    )
    has_runtime_fields = any(
        field is not None
        for field in (integration_smoke_id, verify_cmd, expected_signal)
    )

    if has_plan_fields:
        plan = {}
        if artifact_paths is not None:
            plan["artifact_paths"] = artifact_paths
        if entrypoint_path is not None:
            plan["entrypoint_path"] = entrypoint_path
        if entrypoint is not None:
            plan["entrypoint"] = entrypoint
        if reason is not None:
            plan["reason"] = reason
        evidence["plan"] = plan

    if has_runtime_fields:
        runtime = {}
        if integration_smoke_id is not None:
            runtime["integration_smoke_id"] = integration_smoke_id
        if verify_cmd is not None:
            runtime["verify_cmd"] = verify_cmd
        if expected_signal is not None:
            runtime["expected_signal"] = expected_signal
        evidence["runtime"] = runtime

    return {
        "source_mapping": source_mapping,
        "evidence": evidence,
        "has_frontmatter": bool(frontmatter.get("has_frontmatter")),
        "errors": list(frontmatter.get("errors") or []),
    }

def _agi_session_dir(agi_id: str) -> Path:
    return agile_dir() / agi_id

def _agi_session_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "session.json"

def _agi_events_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "events.ndjson"

def _agi_objective_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "objective.md"

def _agi_objective_changelog_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "changelog.ndjson"

def _agi_links_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "index" / "links.json"

def _agile_sprint_log_path() -> Path:
    return agile_dir() / "sprint-log.json"

def _append_agile_sprint_log(entry: dict):
    path = _agile_sprint_log_path()
    existing = load_json(path)
    rows = existing if isinstance(existing, list) else []
    rows.append(entry)
    save_json(path, rows)

def _append_ndjson(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))
        f.write("\n")

def _append_agile_event(agi_id: str, event: str, payload=None):
    event_data = {
        "timestamp": _now_iso(),
        "event": event,
    }
    if isinstance(payload, dict):
        event_data.update(payload)
    _append_ndjson(_agi_events_path(agi_id), event_data)

def _load_agile_session(agi_id: str):
    session_path = _agi_session_path(agi_id)
    data = load_json(session_path)
    if not isinstance(data, dict):
        raise ValueError(f"{agi_id} session not found")
    return data, session_path

def _save_agile_session(agi_id: str, data):
    payload = dict(data)
    payload["id"] = agi_id
    payload["updated_at"] = _now_iso()
    save_json(_agi_session_path(agi_id), payload)
    return payload


class _ObjectiveDodItem(dict):
    """Backward-compatible DoD item mapping.

    `evidence_refs` is now a first-class field, but legacy tests and callers may
    compare against dicts that do not include this key.
    """

    def __eq__(self, other):
        if not isinstance(other, dict):
            return super().__eq__(other)
        left = dict(self)
        right = dict(other)
        if "evidence_refs" not in right:
            left.pop("evidence_refs", None)
        if "evidence_refs" not in left:
            right.pop("evidence_refs", None)
        return left == right


def _collect_objective_dod_items(content: str) -> dict[str, dict[str, object]]:
    pattern = re.compile(
        (
            r"<!--\s*"
            r"dod:\s*(?P<dod>[A-Za-z0-9_-]+)\s+"
            r"status:\s*(?P<status>\w+)\s+"
            r"priority:\s*(?P<priority>\w+)"
            r"(?:\s+domain:\s*(?P<domain>[A-Za-z0-9_\-]+))?"
            r"(?:\s+evidence_refs:\[(?P<evidence_refs>[^\]]*)\])?"
            r"\s*-->"
        ),
        re.IGNORECASE,
    )
    items = {}
    for match in pattern.finditer(content):
        dod_id = match.group("dod").upper()
        domain_match = match.group("domain")
        evidence_match = match.group("evidence_refs")
        if evidence_match:
            evidence_refs = [ref.strip() for ref in evidence_match.split(",") if ref.strip()]
        else:
            evidence_refs = []
        items[dod_id] = _ObjectiveDodItem({
            "status": match.group("status").lower(),
            "priority": match.group("priority").lower(),
            "domain": domain_match.lower() if domain_match else "unknown",
            "evidence_refs": evidence_refs,
        })
    return items

def _load_agile_config_merged() -> dict:
    defaults_config = load_json(_plugin_root() / "templates" / "defaults" / "config.json")
    resolved_config = load_json(BASE_DIR / "config.resolved.json")
    defaults_agile = defaults_config.get("agile") if isinstance(defaults_config, dict) else {}
    resolved_agile = resolved_config.get("agile") if isinstance(resolved_config, dict) else {}
    defaults_agile = defaults_agile if isinstance(defaults_agile, dict) else {}
    resolved_agile = resolved_agile if isinstance(resolved_agile, dict) else {}
    return deep_merge(defaults_agile, resolved_agile)

def _find_latest_agi_id() -> Optional[str]:
    latest_id = None
    latest_number = -1
    root = agile_dir()
    if not root.exists():
        return None

    for candidate in root.glob("AGI-*"):
        if not candidate.is_dir():
            continue
        matched = re.fullmatch(r"AGI-(\d+)", candidate.name)
        if matched is None:
            continue
        number = int(matched.group(1))
        if number > latest_number:
            latest_number = number
            latest_id = candidate.name
    return latest_id

def _normalize_drift_surface_entry(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    return cleaned.strip(" -")

def _extract_drift_surface_candidate(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line or line.startswith("<!--"):
        return ""

    bullet_match = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line)
    if bullet_match is None:
        return ""
    candidate = bullet_match.group(1).strip()
    candidate = re.sub(r"^\[[xX ]\]\s*", "", candidate)
    candidate = re.sub(r"^DOD-[A-Za-z0-9_-]+\s*:\s*", "", candidate, flags=re.IGNORECASE)
    return _normalize_drift_surface_entry(candidate)

def _extract_objective_surface_entries(content: str) -> list[str]:
    entries: list[str] = []
    seen = set()
    section_kind = None

    for raw_line in str(content or "").splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
        if heading is not None:
            title = re.sub(r"[*`_]+", "", heading.group(1)).strip().lower()
            if "jtbd" in title:
                section_kind = "jtbd"
            elif "project dod" in title or "프로젝트 dod" in title or "프로젝트 완료 기준" in title:
                section_kind = "dod"
            else:
                section_kind = None
            continue

        if section_kind not in {"jtbd", "dod"}:
            continue

        candidate = _extract_drift_surface_candidate(raw_line)
        if not candidate:
            continue
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(candidate)

    if entries:
        return entries

    # Fallback for legacy objective formats.
    for raw_line in str(content or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        candidate = _extract_drift_surface_candidate(stripped)
        if not candidate:
            continue
        if not (
            re.search(r"\b(?:when i|i want to|so i can)\b", candidate, flags=re.IGNORECASE)
            or re.search(r"\bDOD-\w+", stripped, flags=re.IGNORECASE)
        ):
            continue
        dedupe_key = candidate.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        entries.append(candidate)
    return entries

def _agile_state_ledger_path() -> Path:
    return agile_dir() / "agile-state.json"

def _load_agile_state_payload() -> tuple[list[dict], int, str]:
    data = load_json(_agile_state_ledger_path())
    if isinstance(data, list):
        entries = [item for item in data if isinstance(item, dict)]
        return entries, 0, "list"
    if isinstance(data, dict):
        raw_entries = data.get("entries")
        entries = [item for item in raw_entries if isinstance(item, dict)] if isinstance(raw_entries, list) else []
        raw_reopened = data.get("reopened_count", 0)
        try:
            reopened_count = int(raw_reopened)
        except (TypeError, ValueError):
            reopened_count = 0
        return entries, max(0, reopened_count), "dict"
    return [], 0, "none"

def _save_agile_state_payload(entries: list[dict], reopened_count: int, *, as_dict: bool):
    if as_dict:
        save_json(
            _agile_state_ledger_path(),
            {
                "entries": list(entries),
                "reopened_count": max(0, int(reopened_count)),
            },
        )
        return
    save_json(_agile_state_ledger_path(), list(entries))

def _load_agile_config_cast(key: str, default, caster):
    for path in (BASE_DIR / "config.resolved.json", _plugin_root() / "templates" / "defaults" / "config.json"):
        cfg = load_json(path)
        agile_cfg = cfg.get("agile") if isinstance(cfg, dict) else None
        if not isinstance(agile_cfg, dict) or key not in agile_cfg:
            continue
        try:
            return caster(agile_cfg.get(key))
        except (TypeError, ValueError):
            continue
    return default

def _load_agile_int_config(key: str, fallback: int) -> int:
    return _load_agile_config_cast(key, fallback, int)

TYPE_DIRS = {
    "req": ("requests", "REQ"),
    "idn": ("ideation", "IDN"),
    "dsc": ("discussion", "DSC"),
    "dbg": ("debug", "DBG"),
    "exp": ("explore",   "EXP"),
    "pln": ("plans",     "PLN"),
    "des": ("designs",   "DES"),
    "cap": ("captures", "CAP"),
    "fc": ("fact-checks", "FC"),
    "ref": ("references", "REF"),
    "intent": ("intent", "INTENT"),
    "agi": ("agile", "AGI"),
}

JSON_FILE_MAP = {
    "req": "request.json",
    "pln": "plan.json",
    "des": "design.json",
    "cap": "capture.json",
    "fc": "fact-check.json",
    "ref": "reference.json",
}

def type_archived_dir(type_key: str) -> Path:
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "archived"

def get_counter_path(type_key: str, dir_override: str = None) -> Path:
    if dir_override:
        return Path(dir_override) / "counter.json"
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "counter.json"

def _parse_utc_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        normalized = value
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _capture_is_plan_active(plan_id):
    if not plan_id:
        return False
    plan_data = load_json(plans_dir() / str(plan_id) / "plan.json")
    if not isinstance(plan_data, dict):
        return False
    return plan_data.get("status") in ("active", "in_progress")

def _capture_expired(meta, now):
    created_at = _parse_utc_datetime(meta.get("created_at", "")) if isinstance(meta, dict) else None
    if created_at is None:
        return False
    ttl_expires_at = _parse_utc_datetime(meta.get("ttl_expires_at", ""))
    expires_at = ttl_expires_at or (created_at + timedelta(days=7))
    return now >= expires_at

def _project_root() -> Path:
    cwd = Path.cwd().resolve()
    worktrees_root = BASE_DIR / "worktrees"

    candidate = cwd
    while (
        candidate != BASE_DIR
        and candidate != worktrees_root
        and candidate.parent != worktrees_root
        and candidate.parent != candidate
    ):
        candidate = candidate.parent

    if candidate.parent == worktrees_root:
        return candidate

    return BASE_DIR.parent

def _read_versions() -> dict:
    """5파일에서 버전 읽기."""
    root = _project_root()
    pkg = load_json(root / "package.json") or {}
    plugin = load_json(root / ".claude-plugin" / "plugin.json") or {}
    market = load_json(root / ".claude-plugin" / "marketplace.json") or {}
    ext_manifest = load_json(root / "extension" / "manifest.json") or {}
    ext_package = load_json(root / "extension" / "package.json") or {}
    return {
        "package":     pkg.get("version", ""),
        "plugin":      plugin.get("version", ""),
        "marketplace": (market.get("plugins") or [{}])[0].get("version", ""),
        "ext_manifest": ext_manifest.get("version", ""),
        "ext_package":  ext_package.get("version", ""),
    }

def _resolve_archive_max_active(max_active_cfg, type_key: Optional[str]) -> int:
    value = max_active_cfg
    if isinstance(max_active_cfg, dict):
        value = max_active_cfg.get(type_key) if type_key else None
        if value is None:
            value = max_active_cfg.get("default", 200)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 200

def _archive_run_type(type_key: str, max_active: int, emit_output: bool) -> int:
    subdir, prefix = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    src_dir = BASE_DIR / subdir
    dst_dir = type_archived_dir(type_key)
    dst_dir.mkdir(parents=True, exist_ok=True)

    dirs = sorted(src_dir.glob(f"{prefix}-*"))
    json_file = JSON_FILE_MAP.get(type_key, "session.json")

    if type_key == "cap":
        now = datetime.now(timezone.utc)
        to_archive = []
        for d in dirs:
            if not d.is_dir():
                continue
            data = load_json(d / json_file) or {}
            if not _capture_expired(data, now):
                continue
            linked_plan = (data.get("linked_plan") or "").upper()
            if not _capture_is_plan_active(linked_plan):
                to_archive.append(d)
    else:
        completed = [d for d in dirs if d.is_dir() and
                     (load_json(d / json_file) or {}).get("status") in ("completed", "cancelled", "done", "consensus_reached", "converged")]

        if len(dirs) - len(completed) <= max_active:
            if emit_output:
                print("No archiving needed.")
            return 0

        to_archive = completed[:len(dirs) - max_active]

    if not to_archive:
        if emit_output:
            if type_key == "cap":
                print("No captures to archive.")
            else:
                print("No completed sessions to archive.")
        return 0

    ids = [d.name for d in to_archive]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"{subdir}-{ids[0]}-to-{ids[-1]}-{timestamp}.tar.gz"
    archive_path = dst_dir / archive_name

    if type_key == "cap":
        for d in to_archive:
            cap_json = d / json_file
            cap_data = load_json(cap_json) or {}
            cap_data["status"] = "archived"
            save_json(cap_json, cap_data)

    with tarfile.open(archive_path, "w:gz") as tar:
        for d in to_archive:
            tar.add(d, arcname=d.name)

    for d in to_archive:
        shutil.rmtree(d)

    if emit_output:
        print(f"Archived {len(to_archive)} sessions → {archive_name}")
    return len(to_archive)

def _compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

def _load_config_for_get():
    resolved = load_json(BASE_DIR / "config.resolved.json")
    if isinstance(resolved, dict):
        return resolved

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json")
    overrides = load_json(BASE_DIR / "config.json")
    if isinstance(defaults, dict) and isinstance(overrides, dict):
        return deep_merge(defaults, overrides)
    if isinstance(defaults, dict):
        return defaults
    if isinstance(overrides, dict):
        return overrides
    return {}

def _flat_diff(old, new, prefix=""):
    changes = {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        if old != new:
            changes[prefix or "<root>"] = (old, new)
        return changes

    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        full_key = f"{prefix}.{key}" if prefix else key
        old_value = old.get(key)
        new_value = new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changes.update(_flat_diff(old_value, new_value, full_key))
        elif old_value != new_value:
            changes[full_key] = (old_value, new_value)
    return changes


# AD-006: regex-based task ID parsing.
TASK_ID_PATTERN = re.compile(r"^(REQ-\d+)(?:-(.+))?$")
TASK_SEGMENT_PATTERN = re.compile(r"^\w+(-\w+)*$")


def parse_task_id(raw_id):
    r"""Parse a task ID like REQ-001-01 or REQ-100-T01-X into (request_id, task_segment).

    Mirrors the TS parseTaskId in src/core/task-id.ts. Raises ValueError if the
    input does not match ``^REQ-\d+(-\w+)*$``. Bare request IDs (REQ-001)
    are not task identifiers and also raise.
    """
    if not isinstance(raw_id, str):
        raise ValueError(f"invalid task id: {raw_id!r}")
    match = TASK_ID_PATTERN.match(raw_id)
    if not match or not match.group(2):
        raise ValueError(f"invalid task id: {raw_id}")
    segment = match.group(2)
    if not TASK_SEGMENT_PATTERN.match(segment):
        raise ValueError(f"invalid task id: {raw_id}")
    return match.group(1), segment
