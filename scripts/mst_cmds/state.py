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
from typing import List, Optional, Tuple
from scripts.mst_cmds import _common
from scripts.mst_cmds.state_cmd import register_state_validate
from scripts.mst_cmds._common import (
    _parse_bool_arg,
    _skill_state_base_dir,
    _workflow_state_atomic_write,
    _workflow_state_default_payload,
    _workflow_state_file,
    _workflow_state_load,
    _workflow_state_timestamp,
    next_action,
    queue_enqueue,
)

_ATOMIC_WRITE_COUNTER = itertools.count(1)


class TakeoverStormError(RuntimeError):
    pass


def _resolve_owner_ppid() -> int:
    ppid_env = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid_env.isdigit():
        return int(ppid_env)
    return os.getppid()


def _snapshot_session_id() -> str:
    session_env = os.environ.get("MST_SNAPSHOT_SESSION_ID", "").strip()
    if session_env:
        return session_env
    ppid_env = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid_env:
        return ppid_env
    return str(os.getppid())


def _session_id_from_hook_stdin() -> Optional[str]:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        raw = sys.stdin.read()
        if not raw.strip():
            return None
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    direct = payload.get("session_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    transcript_path = payload.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path.strip():
        stem = Path(transcript_path).name
        if stem.endswith(".jsonl"):
            return stem[:-6]
        return Path(stem).stem
    return None


def _current_uuid_session_id() -> Optional[str]:
    from scripts._skill_state import UUID_RE

    candidates = [
        os.environ.get("MST_SESSION_ID", "").strip(),
        os.environ.get("MST_SNAPSHOT_SESSION_ID", "").strip(),
        _resolve_owner_session_id(_resolve_owner_ppid()) or "",
        _session_id_from_hook_stdin() or "",
    ]
    for candidate in candidates:
        if UUID_RE.match(candidate):
            return candidate
    return None


def _agile_session_path(agi_id: str) -> Path:
    return _common.BASE_DIR / "agile" / agi_id / "session.json"


def _request_json_path(req_id: str) -> Path:
    return _common.BASE_DIR / "requests" / req_id / "request.json"


def _plan_json_path(pln_id: str) -> Path:
    return _common.BASE_DIR / "plans" / pln_id / "plan.json"


def _load_json_object(path: Path) -> Optional[dict]:
    data = _common.load_json(path)
    return data if isinstance(data, dict) else None


def _normalize_agi_id_for_recover(value: str) -> str:
    agi_id = (value or "").strip().upper()
    if not re.fullmatch(r"AGI-\d+", agi_id):
        raise ValueError(f"Invalid AGI id: {value}")
    return agi_id


def _normalize_takeover_resource_id(value: str, prefix: str) -> str:
    resource_id = (value or "").strip().upper()
    if not re.fullmatch(rf"{re.escape(prefix)}-\d+", resource_id):
        raise ValueError(f"Invalid {prefix} id: {value}")
    return resource_id


def _takeover_config() -> dict:
    config = _common._load_config_for_get()
    takeover = config.get("takeover") if isinstance(config, dict) else {}
    return takeover if isinstance(takeover, dict) else {}


def _takeover_float_config(key: str, default: float) -> float:
    value = _takeover_config().get(key)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _takeover_int_config(key: str, default: int) -> int:
    value = _takeover_config().get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _takeover_flock_timeout_sec() -> float:
    return _takeover_float_config("flock_timeout_sec", 5.0)


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


def _with_locked_json_update(path: Path, mutator, *, lock_timeout_sec: Optional[float] = None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        timeout_sec = _takeover_flock_timeout_sec() if lock_timeout_sec is None else lock_timeout_sec
        _common._lock_exclusive_with_timeout(f, timeout_sec=timeout_sec)
        try:
            f.seek(0)
            raw = f.read()
            try:
                payload = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            updated = mutator(dict(payload))
            if not isinstance(updated, dict):
                raise TypeError("locked JSON mutator must return a dict")
            _atomic_json_write(path, updated)
            return updated
        finally:
            _common._unlock(f)


def _takeover_storm_path(resource_id: str) -> Path:
    return _common.BASE_DIR / "state" / "_takeover_storm" / f"{resource_id}.json"


def _check_takeover_storm(resource_id: str) -> None:
    window_sec = _takeover_float_config("storm_window_sec", 5.0)
    max_attempts = _takeover_int_config("storm_max_attempts", 3)
    now = time.time()
    path = _takeover_storm_path(resource_id)

    def _mutate(payload: dict) -> dict:
        raw_attempts = payload.get("attempts")
        attempts = [
            float(value)
            for value in raw_attempts
            if isinstance(value, (int, float)) and now - float(value) <= window_sec
        ] if isinstance(raw_attempts, list) else []
        if len(attempts) >= max_attempts - 1:
            raise TakeoverStormError(
                f"[storm detected] {window_sec:g}초 내 {max_attempts}회 takeover 시도 - 잠시 후 재시도"
            )
        attempts.append(now)
        return {"attempts": attempts}

    try:
        _with_locked_json_update(path, _mutate)
    except TakeoverStormError:
        raise
    except Exception as exc:
        print(f"[storm detected] warning: failed to update storm counter for {resource_id}: {exc}", file=sys.stderr)


def _takeover_json_owner(resource_id: str, json_path: Path) -> int:
    session_id = _current_uuid_session_id()
    if not session_id:
        print("Error: current session_id is required (MST_SESSION_ID or MST_SNAPSHOT_SESSION_ID UUID v4)", file=sys.stderr)
        return 1

    payload = _load_json_object(json_path)
    if payload is None:
        print(f"Error: durable state not found: {json_path}", file=sys.stderr)
        return 1

    previous_owner = payload.get("owner_session_id")
    previous_owner = previous_owner.strip() if isinstance(previous_owner, str) and previous_owner.strip() else None
    if previous_owner == session_id:
        print(f"[takeover] no-op: {resource_id} already owned by current session")
        return 0

    try:
        _check_takeover_storm(resource_id)
    except TakeoverStormError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    def _mutate_owner(current: dict) -> dict:
        current["owner_session_id"] = session_id
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        return current

    try:
        updated = _with_locked_json_update(json_path, _mutate_owner)
    except TimeoutError as exc:
        print(f"[takeover] error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[takeover] error: failed to takeover owner for {resource_id}: {exc}", file=sys.stderr)
        return 1

    print(
        f"[takeover] {resource_id}: owner_session_id "
        f"{previous_owner or '<none>'} -> {updated.get('owner_session_id')}"
    )
    return 0


def cmd_takeover_agile(args) -> int:
    try:
        agi_id = _normalize_takeover_resource_id(args.agi, "AGI")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return _takeover_json_owner(agi_id, _agile_session_path(agi_id))


def cmd_takeover_request(args) -> int:
    try:
        req_id = _normalize_takeover_resource_id(args.id, "REQ")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return _takeover_json_owner(req_id, _request_json_path(req_id))


def cmd_takeover_plan(args) -> int:
    try:
        pln_id = _normalize_takeover_resource_id(args.id, "PLN")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return _takeover_json_owner(pln_id, _plan_json_path(pln_id))


def _read_snapshot_read_only(session_id: str) -> bool:
    from scripts._skill_state import load_snapshot

    snapshot = load_snapshot(_skill_state_base_dir(), session_id=session_id)
    return isinstance(snapshot, dict) and snapshot.get("read_only") is True


def _owner_mismatch_read_only(agi_id: str, session_id: str) -> tuple[bool, Optional[str]]:
    session_payload = _load_json_object(_agile_session_path(agi_id))
    if session_payload is None:
        return False, None
    owner = session_payload.get("owner_session_id")
    if not isinstance(owner, str) or not owner.strip():
        return False, None
    owner = owner.strip()
    if owner == session_id:
        return False, owner
    return True, owner


def _resource_owner_mismatch(resource_id: str, session_id: str) -> tuple[bool, Optional[str]]:
    token = (resource_id or "").strip().upper()
    if token.startswith("AGI-"):
        return _owner_mismatch_read_only(token, session_id)
    if token.startswith("REQ-"):
        request_payload = _load_json_object(_request_json_path(token))
        if request_payload is None:
            return False, None
        owner = request_payload.get("owner_session_id")
        if not isinstance(owner, str) or not owner.strip():
            return False, None
        owner = owner.strip()
        if owner == session_id:
            return False, owner
        return True, owner
    return False, None


def _check_read_only(req_or_agi_id: str) -> int:
    """Return non-zero when current session must not mutate durable state."""
    token = (req_or_agi_id or "").strip().upper()
    session_id = _current_uuid_session_id()
    if not session_id:
        return 0
    mismatch, _ = _resource_owner_mismatch(token, session_id)
    if mismatch or _read_snapshot_read_only(session_id):
        print("[read-only] 현재 session이 owner가 아님. --takeover로 소유권 이전 후 재시도", file=sys.stderr)
        return 1
    return 0


def _append_cross_session_recover_event(
    session_id: str,
    agi_id: str,
    previous_owner: Optional[str],
    *,
    takeover: bool,
) -> Path:
    from scripts._flow_logger import flow_detail_path

    project_root = _skill_state_base_dir().parent
    path = flow_detail_path(project_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "event": "cross_session_recover",
        "agi_id": agi_id,
        "previous_owner_session_id": previous_owner,
        "new_owner_session_id": session_id,
        "takeover": bool(takeover),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False))
        f.write("\n")
    return path


def _parse_return_to_parent(value: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    if not value:
        return None, None
    skill, sep, step_text = value.partition("/")
    if not skill or not sep or not step_text:
        return None, None
    try:
        return skill, int(step_text)
    except ValueError:
        return None, None


def _parse_flow_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _previous_enter_duration_ms(flow_path: Path, session_id: str, skill: str) -> Optional[float]:
    try:
        if not flow_path.exists():
            return None
        previous_at = None
        for raw_line in flow_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("session_id") == session_id
                and entry.get("skill") == skill
                and entry.get("event_type") == "enter"
            ):
                previous_at = _parse_flow_timestamp(entry.get("timestamp"))
        if previous_at is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - previous_at).total_seconds() * 1000)
    except Exception:
        return None


def _resolve_owner_session_id(ppid: int) -> Optional[str]:
    if not _common.BASE_DIR:
        return None
    bridge_path = _common.BASE_DIR / "tmp" / f"claude-session-{ppid}.id"
    try:
        raw_value = bridge_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw_value:
        return None
    try:
        session_id = uuid.UUID(raw_value)
    except ValueError:
        return None
    canonical = str(session_id)
    if session_id.variant != uuid.RFC_4122 or session_id.version != 4 or canonical != raw_value:
        return None
    return canonical


def _inject_owner_metadata_to_json(json_path: Path, ppid: int, session_id: Optional[str]) -> None:
    """Write owner metadata into json_path only when fields are absent (idempotent)."""
    data = _common.load_json(json_path)
    if not isinstance(data, dict):
        return
    should_write = False
    if "owner_ppid" not in data:
        data["owner_ppid"] = ppid
        should_write = True
    if "owner_session_id" not in data:
        data["owner_session_id"] = session_id
        should_write = True
    if not should_write:
        return
    tmp_path = json_path.with_name(f"{json_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, json_path)


def _inject_owner_metadata_if_missing(args) -> None:
    ppid = _resolve_owner_ppid()
    session_id = _resolve_owner_session_id(ppid)

    req_id = (getattr(args, "req", "") or "").strip()
    if req_id.startswith("REQ-") and _common.BASE_DIR:
        req_json = _common.BASE_DIR / "requests" / req_id / "request.json"
        if req_json.exists():
            try:
                _inject_owner_metadata_to_json(req_json, ppid, session_id)
            except Exception as exc:
                print(f"[mst] warning: failed to inject owner metadata into {req_json}: {exc}", file=sys.stderr)

    next_source = (getattr(args, "next_source", "") or "").strip()
    source_skill = (getattr(args, "source_skill", "") or "").strip()
    if next_source.startswith("PLN-") and source_skill == "mst:plan" and _common.BASE_DIR:
        plan_json = _common.BASE_DIR / "plans" / next_source / "plan.json"
        if plan_json.exists():
            try:
                _inject_owner_metadata_to_json(plan_json, ppid, session_id)
            except Exception as exc:
                print(f"[mst] warning: failed to inject owner metadata into {plan_json}: {exc}", file=sys.stderr)


def _state_migration_base_dir() -> Path:
    env_base = os.environ.get("MST_BASE_DIR", "").strip()
    if env_base:
        return Path(env_base)
    if _common.BASE_DIR:
        return _common.BASE_DIR.parent
    return Path.cwd()


def _collect_migration_targets(base_dir: Path) -> list[dict]:
    """Collect legacy PPID state directories and owner_ppid-only metadata files."""
    targets = []
    state_dir = base_dir / ".gran-maestro" / "state"
    if state_dir.is_dir():
        for child in state_dir.iterdir():
            if not child.is_dir() or not child.name.isdigit():
                continue
            snapshot = child / "snapshot.json"
            if not snapshot.is_file():
                continue
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            targets.append({
                "type": "rename_dir",
                "path": str(child),
                "ppid": int(child.name),
                "owner_session_id": data.get("owner_session_id"),
            })

    patterns = [
        ".gran-maestro/agile/AGI-*/objective/objective.json",
        ".gran-maestro/requests/REQ-*/request.json",
        ".gran-maestro/plans/PLN-*/plan.json",
    ]
    for pattern in patterns:
        for json_path in base_dir.glob(pattern):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and "owner_ppid" in data and "owner_session_id" not in data:
                targets.append({"type": "owner_field", "path": str(json_path), "data": data})
    return targets


def _create_backup(base_dir: Path, targets: list, backup_dir: Optional[Path] = None) -> Path:
    if backup_dir is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = base_dir / ".gran-maestro" / "backups" / f"state-migrate-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        src = Path(target["path"])
        if not src.exists():
            continue
        dst = backup_dir / src.relative_to(base_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    return backup_dir


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in itertools.count(1):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate


def _migrate_ppid_dir(ppid_dir: Path, owner_session_id: Optional[str], base_dir: Path) -> Tuple[Path, Path]:
    ppid = ppid_dir.name
    state_dir = base_dir / ".gran-maestro" / "state"
    target_name = owner_session_id if isinstance(owner_session_id, str) and owner_session_id.strip() else f"legacy-{ppid}"
    target_dir = state_dir / target_name
    if target_dir.exists() and target_dir != ppid_dir:
        target_dir = _next_available_path(state_dir / f"legacy-{ppid}")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    ppid_dir.rename(target_dir)
    return ppid_dir, target_dir


def _migrate_owner_field(json_path: Path, ppid_to_session_map: dict) -> Tuple[dict, dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}, {}
    ppid = data.get("owner_ppid")
    before = {"owner_ppid": ppid}
    data.pop("owner_ppid", None)
    session_id = ppid_to_session_map.get(ppid)
    if session_id is None:
        try:
            session_id = ppid_to_session_map.get(int(ppid))
        except (TypeError, ValueError):
            session_id = None
    if session_id:
        data["owner_session_id"] = session_id
        after = {"owner_session_id": session_id}
    else:
        data["legacy_owner_ppid"] = ppid
        after = {"legacy_owner_ppid": ppid}
    _atomic_json_write(json_path, data)
    return before, after


def _apply_migration(base_dir: Path, targets: list, log_path: Path, dry_run: bool = False) -> int:
    """Apply PPID to session_id migration and write a user-observable log."""
    log_lines = []
    ppid_to_session = {}

    for target in targets:
        if target.get("type") != "rename_dir":
            continue
        ppid = target.get("ppid")
        owner_session_id = target.get("owner_session_id")
        if owner_session_id:
            ppid_to_session[ppid] = owner_session_id
        src = Path(target["path"])
        target_name = owner_session_id if owner_session_id else f"legacy-{ppid}"
        dst = base_dir / ".gran-maestro" / "state" / target_name
        if dst.exists() and dst != src:
            dst = _next_available_path(base_dir / ".gran-maestro" / "state" / f"legacy-{ppid}")
        if not dry_run:
            _, dst = _migrate_ppid_dir(src, owner_session_id, base_dir)
        log_lines.append(f"rename_dir: {src} -> {dst}")

    for target in targets:
        if target.get("type") != "owner_field":
            continue
        json_path = Path(target["path"])
        data = target.get("data") if isinstance(target.get("data"), dict) else {}
        ppid = data.get("owner_ppid")
        session_id = ppid_to_session.get(ppid)
        if session_id is None:
            try:
                session_id = ppid_to_session.get(int(ppid))
            except (TypeError, ValueError):
                session_id = None
        before = {"owner_ppid": ppid}
        after = {"owner_session_id": session_id} if session_id else {"legacy_owner_ppid": ppid}
        if not dry_run:
            before, after = _migrate_owner_field(json_path, ppid_to_session)
        log_lines.append(
            "owner_field: "
            f"{json_path} "
            f"{json.dumps(before, ensure_ascii=False)} -> {json.dumps(after, ensure_ascii=False)}"
        )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    return len(log_lines)


def _run_dry_run(base_dir: Path) -> int:
    targets = _collect_migration_targets(base_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = base_dir / ".gran-maestro" / "backups" / f"state-migrate-{timestamp}"
    out_targets = []
    ppid_to_session = {
        target["ppid"]: target.get("owner_session_id")
        for target in targets
        if target["type"] == "rename_dir" and target.get("owner_session_id")
    }

    for target in targets:
        if target["type"] == "rename_dir":
            session_id = target.get("owner_session_id")
            if session_id:
                to_path = str(base_dir / ".gran-maestro" / "state" / session_id)
            else:
                to_path = str(base_dir / ".gran-maestro" / "state" / f"legacy-{target['ppid']}")
            out_targets.append({
                "type": "rename_dir",
                "from": target["path"],
                "to": to_path,
            })
        elif target["type"] == "owner_field":
            data = target.get("data") or {}
            ppid = data.get("owner_ppid")
            session_id = ppid_to_session.get(ppid)
            if session_id is None:
                try:
                    session_id = ppid_to_session.get(int(ppid))
                except (TypeError, ValueError):
                    session_id = None
            field = "owner_session_id" if session_id else "legacy_owner_ppid"
            out_targets.append({
                "type": "json_field",
                "path": target["path"],
                "from": "owner_ppid",
                "to": field,
            })

    print(json.dumps(
        {"targets": out_targets, "backup_path": str(backup_path)},
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def _run_rollback(base_dir: Path) -> int:
    backups_dir = base_dir / ".gran-maestro" / "backups"
    if not backups_dir.is_dir():
        print("error: no backup directory found", file=sys.stderr)
        return 1

    candidates = sorted(
        [
            path
            for path in backups_dir.iterdir()
            if path.is_dir() and path.name.startswith("state-migrate-")
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    if not candidates:
        print("error: no state-migrate-* backup found", file=sys.stderr)
        return 1

    latest = candidates[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = base_dir / ".gran-maestro" / "logs" / f"state-migrate-rollback-{timestamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines = []

    for src in latest.rglob("*"):
        if src.is_file():
            rel = src.relative_to(latest)
            dst = base_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log_lines.append(f"restore: {dst}")

    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    print(f"rolled back from {latest}; log={log_path}")
    return 0


def _run_verify(base_dir: Path) -> int:
    state_dir = base_dir / ".gran-maestro" / "state"
    issues = []
    if state_dir.is_dir():
        for child in state_dir.iterdir():
            if child.is_dir() and child.name.isdigit():
                issues.append(f"numeric_ppid_dir_remains: {child}")

    for pattern in [
        ".gran-maestro/agile/AGI-*/objective/objective.json",
        ".gran-maestro/requests/REQ-*/request.json",
        ".gran-maestro/plans/PLN-*/plan.json",
    ]:
        for json_path in base_dir.glob(pattern):
            try:
                text = json_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if (
                '"owner_ppid"' in text
                and '"owner_session_id"' not in text
                and '"legacy_owner_ppid"' not in text
            ):
                issues.append(f"owner_ppid_remains: {json_path}")

    backups_dir = base_dir / ".gran-maestro" / "backups"
    backup_present = backups_dir.is_dir() and any(
        path.is_dir() and path.name.startswith("state-migrate-") for path in backups_dir.iterdir()
    )
    status = "PASS" if not issues else "FAIL"
    print(json.dumps(
        {"status": status, "issues": issues, "backup_present": backup_present},
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if status == "PASS" else 1


def _run_migrate_default(base_dir: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = base_dir / ".gran-maestro" / "logs" / f"state-migrate-{timestamp}.log"
    backup_dir = base_dir / ".gran-maestro" / "backups" / f"state-migrate-{timestamp}"
    lock_path = base_dir / ".gran-maestro" / "tmp" / "mst-state-migrate.lock"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    targets = _collect_migration_targets(base_dir)
    if not targets:
        log_path.write_text("[no changes]\n", encoding="utf-8")
        print("no_changes: legacy PPID state 없음")
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)
    _create_backup(base_dir, targets, backup_dir)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        _common._lock_exclusive_with_timeout(lock_file, timeout_sec=5)
        try:
            changes = _apply_migration(base_dir, targets, log_path, dry_run=False)
        finally:
            _common._unlock(lock_file)

    print(f"migrated: {changes} item(s); backup={backup_dir}; log={log_path}")
    return 0


def migrate(args: argparse.Namespace) -> int:
    """state migrate: PPID -> session_id migration entry point."""
    base_dir = _state_migration_base_dir()
    if args.dry_run:
        return _run_dry_run(base_dir)
    if args.rollback:
        return _run_rollback(base_dir)
    if args.verify:
        return _run_verify(base_dir)
    return _run_migrate_default(base_dir)


def cmd_state_set_workflow(args):
    state_base_dir = _skill_state_base_dir()
    state_path = _workflow_state_file(state_base_dir)
    now = _workflow_state_timestamp()

    try:
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            payload = _workflow_state_default_payload(now)

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            next_action = {}

        payload["workflow_active"] = bool(args.active)
        payload["current_skill"] = args.skill if args.active else ""
        payload["active_req"] = args.req if args.active else ""
        payload["iteration"] = payload.get("iteration") if isinstance(payload.get("iteration"), int) else 0
        payload["agile_loop_active"] = (
            payload.get("agile_loop_active")
            if isinstance(payload.get("agile_loop_active"), bool)
            else False
        )
        payload["steering_disabled"] = (
            payload.get("steering_disabled")
            if isinstance(payload.get("steering_disabled"), bool)
            else False
        )
        block_count = payload.get("block_count")
        payload["block_count"] = (
            block_count
            if isinstance(block_count, int) and not isinstance(block_count, bool)
            else 0
        )
        payload["last_block_reason"] = (
            payload.get("last_block_reason")
            if isinstance(payload.get("last_block_reason"), str)
            else ""
        )

        if args.agile_loop_active is not None:
            payload["agile_loop_active"] = bool(args.agile_loop_active)
            if not payload["agile_loop_active"]:
                payload["block_count"] = 0
        if args.steering_disabled is not None:
            payload["steering_disabled"] = bool(args.steering_disabled)

        payload["updated_at"] = now

        if args.active:
            expected_skill = args.next_skill or ""
            source_id = args.next_source or ""
            source_skill = args.source_skill or args.skill or ""
            auto_mode = bool(args.auto)
            next_action.update(
                {
                    "skill": expected_skill,
                    "source": source_id,
                    "auto": auto_mode,
                    "expected_skill": expected_skill,
                    "source_skill": source_skill,
                    "source_id": source_id,
                    "auto_mode": auto_mode,
                }
            )
        else:
            next_action.update(
                {
                    "skill": "",
                    "source": "",
                    "auto": False,
                    "expected_skill": "",
                    "source_skill": "",
                    "source_id": "",
                    "auto_mode": False,
                }
            )

        payload["next_action"] = next_action
        _workflow_state_atomic_write(state_path, payload)

        if args.active:
            _inject_owner_metadata_if_missing(args)

        if bool(getattr(args, "enqueue", False)) and payload.get("next_action"):
            na = payload.get("next_action", {})
            if isinstance(na, dict) and na.get("expected_skill"):
                auto_flag = bool(na.get("auto_mode", na.get("auto", False)))
                args_base = str(na.get("args", "") or "").strip()
                queue_args = args_base
                if auto_flag:
                    args_tokens = args_base.split()
                    if "-a" not in args_tokens and "--auto" not in args_tokens:
                        queue_args = f"{args_base} -a".strip()
                try:
                    queue_enqueue(
                        {
                            "skill": str(na.get("expected_skill", "")),
                            "args": queue_args,
                            "source_skill": str(na.get("source_skill", "")),
                            "source_id": str(na.get("source_id", "")),
                            "resource_id": str(na.get("source_id", "")),
                            "auto": auto_flag,
                        }
                    )
                except Exception as queue_exc:
                    print(f"[mst] warning: failed to enqueue next_action: {queue_exc}", file=sys.stderr)

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[mst] warning: failed to update workflow state: {exc}", file=sys.stderr)
        return 0

    return 0

def cmd_state_set(args):
    from scripts._skill_state import set_snapshot
    from scripts._flow_logger import append_skill_event, flow_log_path, safe_session_id

    state_base_dir = _skill_state_base_dir()
    project_root = state_base_dir.parent
    session_id = _snapshot_session_id()
    data = set_snapshot(
        state_base_dir,
        skill=args.skill,
        step=args.step,
        total=args.total,
        return_to=args.return_to,
        session_id=session_id,
    )
    try:
        parent_skill, parent_step = _parse_return_to_parent(args.return_to)
        flow_path = flow_log_path(project_root, rotate=True)
        log_session_id = safe_session_id(session_id)
        duration_ms = _previous_enter_duration_ms(flow_path, log_session_id, args.skill)
        append_skill_event(
            project_root,
            session_id,
            skill=args.skill,
            step=args.step,
            total_steps=args.total,
            event_type="enter",
            parent_skill=parent_skill,
            parent_step=parent_step,
            duration_ms=duration_ms,
            rotate=True,
        )
        if args.step == args.total:
            append_skill_event(
                project_root,
                session_id,
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                event_type="commit",
                parent_skill=parent_skill,
                parent_step=parent_step,
                duration_ms=0,
                rotate=True,
            )
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_get(args):
    from scripts._skill_state import get_snapshot

    data = get_snapshot(_skill_state_base_dir(), session_id=_snapshot_session_id())
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_clear(args):
    from scripts._skill_state import clear_snapshot

    clear_snapshot(_skill_state_base_dir(), session_id=_snapshot_session_id())
    print("스냅샷 초기화 완료")
    return 0


def cmd_state_recover(args):
    from scripts._skill_state import (
        load_snapshot,
        recover_agile_snapshot_from_durable_state,
        snapshot_path,
    )

    try:
        agi_id = _normalize_agi_id_for_recover(args.agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    session_id = _current_uuid_session_id()
    if not session_id:
        print("Error: current session_id is required (MST_SESSION_ID or MST_SNAPSHOT_SESSION_ID UUID v4)", file=sys.stderr)
        return 1

    state_base_dir = _skill_state_base_dir()
    existing = load_snapshot(state_base_dir, session_id=session_id)
    if existing is not None:
        print(json.dumps(existing, ensure_ascii=False, indent=2))
        return 0

    session_path = _agile_session_path(agi_id)
    session_payload = _load_json_object(session_path)
    if session_payload is None:
        print(f"[cross-session recover] warning: durable session not found: {session_path}", file=sys.stderr)
        return 0

    previous_owner = session_payload.get("owner_session_id")
    previous_owner = previous_owner.strip() if isinstance(previous_owner, str) and previous_owner.strip() else None
    read_only = bool(previous_owner and previous_owner != session_id and not getattr(args, "takeover", False))

    if previous_owner and previous_owner != session_id and getattr(args, "takeover", False):
        def _mutate_owner(payload: dict) -> dict:
            payload["owner_session_id"] = session_id
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            return payload

        try:
            _check_takeover_storm(agi_id)
            _with_locked_json_update(session_path, _mutate_owner)
        except TakeoverStormError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except TimeoutError as exc:
            print(f"[cross-session recover] error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[cross-session recover] error: failed to takeover owner: {exc}", file=sys.stderr)
            return 1

    try:
        snapshot = recover_agile_snapshot_from_durable_state(
            state_base_dir,
            agi_id,
            session_id=session_id,
            read_only=read_only,
        )
    except Exception as exc:
        print(f"[cross-session recover] warning: failed durable fallback: {exc}", file=sys.stderr)
        return 0
    if snapshot is None:
        print(f"[cross-session recover] warning: durable session not found: {session_path}", file=sys.stderr)
        return 0

    flow_path = _append_cross_session_recover_event(
        session_id,
        agi_id,
        previous_owner,
        takeover=bool(getattr(args, "takeover", False) and not read_only),
    )
    if read_only:
        print(
            f"[cross-session recover] read-only (owner mismatch: previous={previous_owner}, current={session_id})"
        )
    for warning in snapshot.get("warnings", []) if isinstance(snapshot.get("warnings"), list) else []:
        print(f"[cross-session recover] warning: {warning}", file=sys.stderr)
    print(f"[cross-session recover] snapshot={snapshot_path(state_base_dir, session_id)}")
    print(f"[cross-session recover] flow-detail={flow_path}")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_state_mark_paused(args):
    from scripts._skill_state import mark_paused

    data = mark_paused(_skill_state_base_dir(), session_id=args.session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_resume_paused(args):
    from scripts._skill_state import resume_paused

    data = resume_paused(_skill_state_base_dir(), session_id=args.session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_paused_count(args):
    from scripts._skill_state import paused_count

    print(paused_count(_skill_state_base_dir(), session_id=args.session_id))
    return 0


def register(subparsers):
    sub = subparsers
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="subcommand")

    state_set = state_sub.add_parser("set")
    state_set.add_argument("--skill", required=True)
    state_set.add_argument("--step", type=int, required=True)
    state_set.add_argument("--total", type=int, required=True)
    state_set.add_argument("--return-to", dest="return_to")

    state_set_workflow = state_sub.add_parser("set-workflow")
    state_set_workflow.add_argument("--active", type=_parse_bool_arg, required=True)
    state_set_workflow.add_argument("--skill", default="")
    state_set_workflow.add_argument("--req", default="")
    state_set_workflow.add_argument("--next-skill", dest="next_skill", default="")
    state_set_workflow.add_argument("--next-source", dest="next_source", default="")
    state_set_workflow.add_argument("--source-skill", dest="source_skill", default="")
    state_set_workflow.add_argument("--auto", type=_parse_bool_arg, default=False)
    state_set_workflow.add_argument("--enqueue", type=_parse_bool_arg, default=False)
    state_set_workflow.add_argument("--agile-loop-active", dest="agile_loop_active", type=_parse_bool_arg)
    state_set_workflow.add_argument("--steering-disabled", dest="steering_disabled", type=_parse_bool_arg)

    state_sub.add_parser("get")
    state_sub.add_parser("clear")

    state_migrate = state_sub.add_parser("migrate")
    mode_group = state_migrate.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--verify", action="store_true")
    mode_group.add_argument("--rollback", action="store_true")
    state_migrate.set_defaults(func=migrate)

    state_recover = state_sub.add_parser("recover")
    state_recover.add_argument("agi_id")
    state_recover.add_argument("--takeover", action="store_true")

    state_mark_paused = state_sub.add_parser("mark-paused")
    state_mark_paused.add_argument("--session-id", required=True)

    state_resume_paused = state_sub.add_parser("resume-paused")
    state_resume_paused.add_argument("--session-id", required=True)

    state_paused_count = state_sub.add_parser("paused-count")
    state_paused_count.add_argument("--session-id", required=True)
    register_state_validate(state_sub)

    recover = sub.add_parser("recover")
    recover.add_argument("agi_id")
    recover.add_argument("--takeover", action="store_true")
