from datetime import datetime, timezone
import contextlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional
import warnings

try:
    import fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False


def timestamp_now() -> str:
    """Return current UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _safe_session_id(value: str) -> str:
    cleaned = []
    for char in value:
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "default"


def snapshot_path(base_dir: Path, session_id: str = "default") -> Path:
    """Return snapshot.json path for a session."""
    return base_dir / "state" / _safe_session_id(session_id) / "snapshot.json"


def snapshots_dir(base_dir: Path) -> Path:
    """Return session-end snapshots directory."""
    return base_dir / "state" / "snapshots"


@contextlib.contextmanager
def _acquire_session_lock(base_dir: Path, session_id: str):
    lock_dir = base_dir / "state" / _safe_session_id(session_id)
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / ".snapshot.lock"
    if not HAS_FCNTL:
        warnings.warn("fcntl not available; running without RMW serialization")
        yield None
        return

    timeout_sec = float(os.environ.get("AGILE_STATE_LOCK_TIMEOUT_SEC", "5"))
    deadline = time.monotonic() + timeout_sec
    fd = open(lock_path, "a+")
    try:
        while True:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    warnings.warn(f"lock timeout after {timeout_sec}s; continuing without lock")
                    break
                time.sleep(0.05)
        yield fd
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fd.close()


def load_snapshot(base_dir: Path, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """Load snapshot JSON. Return None when absent or invalid."""
    path = snapshot_path(base_dir, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically via temp file, fsync, and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if hasattr(os, "O_DIRECTORY"):
            dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _base_snapshot(session_id: str) -> Dict[str, Any]:
    from scripts.mst_cmds.state import _resolve_owner_ppid, _resolve_owner_session_id

    owner_ppid = _resolve_owner_ppid()
    return {
        "sessionId": session_id,
        "owner_ppid": owner_ppid,
        "owner_session_id": _resolve_owner_session_id(owner_ppid),
        "currentSkill": "",
        "currentStep": 0,
        "totalSteps": 0,
        "enterCount": 0,
        "skillStack": [],
        "status": "idle",
        "updatedAt": timestamp_now(),
    }


def _normalize_stack(value: Any) -> list:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill")
        step = item.get("step")
        if isinstance(skill, str) and isinstance(step, (int, float, str)) and not isinstance(step, bool):
            frame = {"skill": skill, "step": step}
            entered_at = item.get("enteredAt")
            if isinstance(entered_at, str):
                frame["enteredAt"] = entered_at
            normalized.append(frame)
    return normalized


def _parse_return_to(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    skill, sep, step_text = value.partition("/")
    if not skill:
        return None
    parsed: Dict[str, Any] = {"skill": skill}
    if sep and step_text:
        try:
            num = float(step_text)
            parsed["step"] = int(num) if num == int(num) else num
        except (ValueError, OverflowError):
            pass
    return parsed


def _snapshot_file_suffix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_session_snapshot(
    base_dir: Path,
    snapshot: Dict[str, Any],
    *,
    session_id: str,
    reason: str,
) -> None:
    ended_at = timestamp_now()
    stack = _normalize_stack(snapshot.get("skillStack"))
    payload = dict(snapshot)
    payload["sessionId"] = session_id
    payload["skillStack"] = stack
    payload["sessionEndedAt"] = ended_at
    payload["sessionEndReason"] = reason
    payload["stackDepth"] = len(stack)
    file_name = f"{_safe_session_id(session_id)}-{_snapshot_file_suffix()}-{reason}.json"
    _atomic_write_json(snapshots_dir(base_dir) / file_name, payload)


def apply_event(
    snapshot: Optional[Dict[str, Any]],
    event: str,
    *,
    session_id: str = "default",
    skill: Optional[str] = None,
    step: Optional[int] = None,
    total: Optional[int] = None,
    return_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply enter/commit/fail event and return new snapshot."""
    data = dict(snapshot or _base_snapshot(session_id))
    data["sessionId"] = session_id
    stack = _normalize_stack(data.get("skillStack"))
    event_time = timestamp_now()

    if event == "enter":
        if not isinstance(skill, str) or not skill:
            raise ValueError("skill is required for enter")
        if not isinstance(step, int) or not isinstance(total, int):
            raise ValueError("step and total are required for enter")

        current_skill = data.get("currentSkill")
        current_step = data.get("currentStep")
        if isinstance(current_skill, str) and current_skill and isinstance(current_step, int):
            stack.append({"skill": current_skill, "step": current_step, "enteredAt": event_time})

        data["currentSkill"] = skill
        data["currentStep"] = step
        data["totalSteps"] = total
        existing_enter_count = data.get("enterCount")
        if not isinstance(existing_enter_count, int) or existing_enter_count < 0:
            existing_enter_count = 0
        data["enterCount"] = existing_enter_count + 1
        data["status"] = "active"
        data["enteredAt"] = event_time
        data.pop("committedAt", None)
        data.pop("failedAt", None)

        parsed_return_to = _parse_return_to(return_to)
        if parsed_return_to:
            data["returnTo"] = parsed_return_to
        else:
            data.pop("returnTo", None)

    elif event in ("commit", "fail"):
        frame = stack.pop() if stack else None
        if isinstance(frame, dict):
            data["currentSkill"] = frame.get("skill", "")
            data["currentStep"] = frame.get("step", 0)
        data["status"] = "committed" if event == "commit" else "failed"
        if event == "commit":
            data["committedAt"] = event_time
            data.pop("failedAt", None)
        else:
            data["failedAt"] = event_time
            data.pop("committedAt", None)
    else:
        raise ValueError(f"unknown event: {event}")

    data["skillStack"] = stack
    data["updatedAt"] = event_time
    return data


def enter(
    base_dir: Path,
    *,
    skill: str,
    step: int,
    total: int,
    session_id: str = "default",
    return_to: Optional[str] = None,
) -> Dict[str, Any]:
    with _acquire_session_lock(base_dir, session_id):
        snapshot = load_snapshot(base_dir, session_id)
        updated = apply_event(
            snapshot,
            "enter",
            session_id=session_id,
            skill=skill,
            step=step,
            total=total,
            return_to=return_to,
        )
        _atomic_write_json(snapshot_path(base_dir, session_id), updated)
        return updated


def commit(base_dir: Path, session_id: str = "default") -> Dict[str, Any]:
    with _acquire_session_lock(base_dir, session_id):
        snapshot = load_snapshot(base_dir, session_id)
        if snapshot is None:
            raise FileNotFoundError("snapshot not found")
        stack_before = _normalize_stack(snapshot.get("skillStack"))
        updated = apply_event(snapshot, "commit", session_id=session_id)
        _atomic_write_json(snapshot_path(base_dir, session_id), updated)
        if not stack_before:
            _write_session_snapshot(base_dir, updated, session_id=session_id, reason="commit")
        return updated


def fail(base_dir: Path, session_id: str = "default") -> Dict[str, Any]:
    with _acquire_session_lock(base_dir, session_id):
        snapshot = load_snapshot(base_dir, session_id)
        if snapshot is None:
            raise FileNotFoundError("snapshot not found")
        stack_before = _normalize_stack(snapshot.get("skillStack"))
        updated = apply_event(snapshot, "fail", session_id=session_id)
        _atomic_write_json(snapshot_path(base_dir, session_id), updated)
        if not stack_before:
            _write_session_snapshot(base_dir, updated, session_id=session_id, reason="fail")
        return updated


def set_snapshot(
    base_dir: Path,
    *,
    skill: str,
    step: int,
    total: int,
    return_to: Optional[str] = None,
    session_id: str = "default",
) -> Dict[str, Any]:
    """CLI helper for state set."""
    return enter(
        base_dir,
        skill=skill,
        step=step,
        total=total,
        return_to=return_to,
        session_id=session_id,
    )


def get_snapshot(base_dir: Path, session_id: str = "default") -> Optional[Dict[str, Any]]:
    snapshot = load_snapshot(base_dir, session_id)
    if snapshot is not None or session_id == "default":
        return snapshot
    return load_snapshot(base_dir, "default")


def _load_json_object(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_sprint_number(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().upper()
        if raw.startswith("S"):
            raw = raw[1:]
        if raw.isdigit():
            return int(raw)
    return None


def _latest_sprint_result(agi_dir: Path, current_sprint: Any) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    sprint_root = agi_dir / "sprints"
    if not sprint_root.exists():
        return None, None

    candidates: list[tuple[int, Path]] = []
    current_num = _parse_sprint_number(current_sprint)
    for result_path in sprint_root.glob("S*/result.json"):
        sprint_name = result_path.parent.name.upper()
        if not re.fullmatch(r"S\d+", sprint_name):
            continue
        sprint_num = int(sprint_name[1:])
        if current_num is not None and sprint_num > current_num:
            continue
        candidates.append((sprint_num, result_path))

    for _, result_path in sorted(candidates, reverse=True):
        payload = _load_json_object(result_path)
        if payload is None:
            continue
        status = str(payload.get("status", "")).strip().lower()
        if status in {"failed", "failure", "cancelled", "canceled", "error"}:
            continue
        return result_path.parent.name, payload
    return None, None


def _reconstruct_agile_skill_stack(
    session_payload: Dict[str, Any],
    sprint_id: Optional[str],
    result_payload: Optional[Dict[str, Any]],
) -> tuple[list[Dict[str, Any]], list[str]]:
    warnings_out: list[str] = []
    entered_at = timestamp_now()
    frame: Dict[str, Any] = {"skill": "agile", "step": "2.2.x", "enteredAt": entered_at}
    if sprint_id:
        frame["sprint"] = sprint_id
    if isinstance(result_payload, dict):
        target_dod = result_payload.get("target_dod") or result_payload.get("dod_ref")
        if isinstance(target_dod, str) and target_dod.strip():
            frame["target_dod"] = target_dod.strip()
        status = result_payload.get("status")
        if isinstance(status, str) and status.strip():
            frame["last_result_status"] = status.strip()
    else:
        warnings_out.append("recent sprint result not found; recovered agile top-level stack only")

    if _parse_sprint_number(session_payload.get("current_sprint")) is None:
        warnings_out.append("current_sprint unavailable; recovered agile top-level stack only")
    return [frame], warnings_out


def recover_agile_snapshot_from_durable_state(
    base_dir: Path,
    agi_id: str,
    *,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    """Create current-session snapshot from durable AGI session state."""
    safe_agi_id = str(agi_id or "").strip().upper()
    if not re.fullmatch(r"AGI-\d+", safe_agi_id):
        raise ValueError(f"Invalid AGI id: {agi_id}")
    from scripts.mst_cmds.session import validate_mst_session_id

    validate_mst_session_id(str(session_id or ""))

    agi_dir = base_dir / "agile" / safe_agi_id
    session_path = agi_dir / "session.json"
    session_payload = _load_json_object(session_path)
    if session_payload is None:
        return None

    sprint_id, result_payload = _latest_sprint_result(agi_dir, session_payload.get("current_sprint"))
    stack, warnings_out = _reconstruct_agile_skill_stack(session_payload, sprint_id, result_payload)
    now = timestamp_now()
    owner_ppid = session_payload.get("owner_ppid")
    snapshot = {
        "sessionId": session_id,
        "owner_ppid": owner_ppid if isinstance(owner_ppid, int) and not isinstance(owner_ppid, bool) else None,
        "owner_session_id": session_payload.get("owner_session_id"),
        "agi_id": safe_agi_id,
        "currentSkill": "agile",
        "currentStep": stack[-1].get("step") if stack else "2.2.x",
        "totalSteps": 0,
        "enterCount": 1,
        "skillStack": stack,
        "status": "active",
        "durableFallback": True,
        "durableSessionPath": str(session_path),
        "current_sprint": session_payload.get("current_sprint"),
        "agile_status": session_payload.get("status"),
        "updatedAt": now,
    }
    if sprint_id:
        snapshot["recovered_sprint"] = sprint_id
    if warnings_out:
        snapshot["warnings"] = warnings_out

    with _acquire_session_lock(base_dir, session_id):
        _atomic_write_json(snapshot_path(base_dir, session_id), snapshot)
    return snapshot


def mark_paused(base_dir: Path, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """Mark an existing active snapshot as paused."""
    snapshot = load_snapshot(base_dir, session_id)
    if snapshot is None:
        return None
    if snapshot.get("status") in ("committed", "failed"):
        return snapshot

    event_time = timestamp_now()
    updated = dict(snapshot)
    updated["sessionId"] = session_id
    updated["paused"] = True
    updated["paused_at"] = event_time
    updated.pop("resumed_at", None)
    updated["updatedAt"] = event_time
    _atomic_write_json(snapshot_path(base_dir, session_id), updated)
    return updated


def resume_paused(base_dir: Path, session_id: str = "default") -> Optional[Dict[str, Any]]:
    """Clear a paused marker from an existing snapshot."""
    snapshot = load_snapshot(base_dir, session_id)
    if snapshot is None:
        return None

    event_time = timestamp_now()
    updated = dict(snapshot)
    updated["sessionId"] = session_id
    updated["paused"] = False
    updated["resumed_at"] = event_time
    updated["updatedAt"] = event_time
    _atomic_write_json(snapshot_path(base_dir, session_id), updated)
    return updated


def paused_count(base_dir: Path, session_id: str = "default") -> int:
    """Return 1 when the session snapshot is marked paused, otherwise 0."""
    snapshot = load_snapshot(base_dir, session_id)
    if isinstance(snapshot, dict) and snapshot.get("paused") is True:
        return 1
    return 0


def clear_snapshot(base_dir: Path, session_id: str = "default") -> None:
    snapshot = load_snapshot(base_dir, session_id)
    if snapshot is not None:
        stack = _normalize_stack(snapshot.get("skillStack"))
        status = snapshot.get("status")
        if stack or status not in ("committed", "failed"):
            _write_session_snapshot(base_dir, snapshot, session_id=session_id, reason="clear")

    path = snapshot_path(base_dir, session_id)
    if path.exists():
        path.unlink()


if __name__ == "__main__":
    raise SystemExit("Do not run directly. Use python3 scripts/mst.py state ...")
