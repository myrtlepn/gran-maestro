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
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from scripts.mst_cmds import _common
from scripts.mst_cmds.env_alias_compat import (
    canonical_session_id_from_env,
    legacy_session_id_from_env,
    resolve_session_id_from_env,
)
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
    return _common.require_mst_session_id_for_mutation("state snapshot")
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
def _current_mst_session_id() -> Optional[str]:
    try:
        return _common.canonical_mst_session_id_from_env_or_context()
    except ValueError:
        return None
def _validate_existing_workflow_payload(payload: dict, session_id: str) -> tuple[bool, str]:
    error = _common.canonical_state_payload_error(payload, session_id)
    if error is not None:
        if error.startswith("state payload mst_session_id mismatch: "):
            return False, error.removeprefix("state payload ")
        return False, error
    return True, ""
def _state_snapshot_contract_failure(payload: dict, session_id: str) -> Optional[dict]:
    if not isinstance(payload, dict):
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="payload",
            reason="snapshot payload must be a JSON object",
        )

    parsed = None
    try:
        from scripts.mst_cmds.session import validate_mst_session_id, validate_root_mst_id

        parsed = validate_mst_session_id(session_id)
    except ValueError as exc:
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="mst_session_id",
            reason=str(exc),
        )

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="schema_version",
            reason="schema_version is required and must be 1",
        )

    raw_session_id = payload.get("mst_session_id")
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="mst_session_id",
            reason="mst_session_id is required",
        )
    if raw_session_id.strip() != parsed.mst_session_id:
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="mst_session_id",
            reason="snapshot path mst_session_id and payload mst_session_id mismatch",
            mst_session_id=parsed.mst_session_id,
        )

    raw_root = payload.get("root_mst_id")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="root_mst_id",
            reason="root_mst_id is required",
        )
    try:
        payload_root = validate_root_mst_id(raw_root.strip())
    except ValueError as exc:
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="root_mst_id",
            reason=str(exc),
        )
    if payload_root != parsed.root_mst_id:
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="root_mst_id",
            reason="root_mst_id must match root parsed from mst_session_id",
            root_mst_id=payload_root,
            expected_root_mst_id=parsed.root_mst_id,
        )

    workflow = payload.get("workflow")
    if not isinstance(workflow, dict):
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="workflow",
            reason="workflow object is required",
        )
    if not isinstance(workflow.get("current_skill"), str) or not workflow.get("current_skill", "").strip():
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="workflow.current_skill",
            reason="workflow.current_skill is required",
        )
    if not isinstance(workflow.get("current_step"), int) or isinstance(workflow.get("current_step"), bool):
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="workflow.current_step",
            reason="workflow.current_step must be an integer",
        )
    if not isinstance(workflow.get("status"), str) or not workflow.get("status", "").strip():
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="workflow.status",
            reason="workflow.status is required",
        )

    history = payload.get("history")
    if not isinstance(history, dict):
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="history",
            reason="history object is required",
        )
    last_event_id = history.get("last_event_id")
    if not isinstance(last_event_id, str) or not last_event_id.strip():
        return _common.validation_failure_payload(
            target="state_snapshot",
            field="history.last_event_id",
            reason="history.last_event_id is required",
        )
    return None
def _snapshot_path_for_session(base_dir: Path, session_id: str) -> Path:
    from scripts._skill_state import snapshot_path

    return snapshot_path(base_dir, session_id)
def _load_snapshot_for_session(base_dir: Path, session_id: str) -> Optional[dict]:
    from scripts._skill_state import load_snapshot

    payload = load_snapshot(base_dir, session_id=session_id)
    return payload if isinstance(payload, dict) else None
def _validate_existing_snapshot_for_write(base_dir: Path, session_id: str) -> tuple[bool, str]:
    try:
        from scripts.mst_cmds.session import validate_mst_session_metadata_consistency

        validate_mst_session_metadata_consistency(base_dir, session_id)
    except ValueError as exc:
        return False, str(exc)
    snapshot = _load_snapshot_for_session(base_dir, session_id)
    if not isinstance(snapshot, dict):
        return True, ""
    contract_failure = _state_snapshot_contract_failure(snapshot, session_id)
    if contract_failure is not None:
        return False, json.dumps(contract_failure, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    error = _common.canonical_state_payload_error(snapshot, session_id)
    if error is not None:
        if "mst_session_id mismatch" in error:
            existing = snapshot.get("mst_session_id")
            return False, f"snapshot mst_session_id mismatch: path={session_id} payload={str(existing).strip()}"
        return False, f"snapshot {error}"
    return True, ""
def _write_canonical_snapshot_payload(base_dir: Path, session_id: str, payload: dict, *, history_head_override: str = "") -> dict:
    canonical_fields = _common.canonical_state_payload_fields(session_id)
    payload.update(canonical_fields)
    payload["sessionId"] = session_id
    payload.pop("session_id", None)
    payload.pop("owner_ppid", None)
    payload.pop("owner_session_id", None)
    payload["workflow"] = {
        "current_skill": payload.get("currentSkill", ""),
        "current_step": payload.get("currentStep", 0),
        "total_steps": payload.get("totalSteps", 0),
        "status": payload.get("status", ""),
    }
    history = dict(payload.get("history")) if isinstance(payload.get("history"), dict) else {}
    history_head = history_head_override or _history_head_for_session(base_dir, session_id)
    if not history_head:
        history_head = hashlib.sha256(
            f"{session_id}:state.snapshot:{payload.get('currentSkill', '')}:{payload.get('currentStep', '')}".encode("utf-8")
        ).hexdigest()
    if history_head_override:
        history["last_event_id"] = history_head
        history["head_hash"] = history_head
    else:
        history.setdefault("last_event_id", history_head)
        history.setdefault("head_hash", history_head)
    payload["history"] = history
    stack = payload.get("skillStack")
    payload["continuation"] = {
        "stack_depth": len(stack) if isinstance(stack, list) else 0,
        "return_to": payload.get("returnTo"),
        "paused": payload.get("paused") is True,
    }
    diagnostics = _common.legacy_session_diagnostics()
    if diagnostics:
        payload["legacy_diagnostics"] = diagnostics
    error = _common.canonical_state_payload_error(payload, session_id)
    if error is not None:
        raise ValueError(error)
    _common.save_json(_snapshot_path_for_session(base_dir, session_id), payload)
    return payload
def _require_args_session_matches_env(args_session_id: str) -> tuple[Optional[str], Optional[str]]:
    try:
        session_id = _common.require_mst_session_id_for_mutation("recover/resume state write")
    except ValueError as exc:
        return None, str(exc)
    try:
        from scripts.mst_cmds.session import validate_mst_session_id

        validate_mst_session_id(args_session_id)
    except ValueError as exc:
        return None, str(exc)
    if args_session_id != session_id:
        return None, f"mst_session_id mismatch: env={session_id} arg={args_session_id}"
    return session_id, None
def _canonical_uuid4(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = uuid.UUID(value.strip())
    except ValueError:
        return None
    canonical = str(parsed)
    if parsed.variant != uuid.RFC_4122 or parsed.version != 4 or canonical != value.strip():
        return None
    return canonical
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
def _resource_json_path(resource_id: str) -> Optional[Path]:
    token = (resource_id or "").strip().upper()
    if token.startswith("AGI-"):
        return _agile_session_path(token)
    if token.startswith("REQ-"):
        return _request_json_path(token)
    if token.startswith("PLN-"):
        return _plan_json_path(token)
    return None
def _check_read_only(req_or_agi_id: str) -> int:
    """Return non-zero when canonical session identity does not match durable state."""
    session_id = _current_mst_session_id()
    if not session_id:
        return 0
    resource_path = _resource_json_path(req_or_agi_id)
    if resource_path is None:
        return 0
    payload = _load_json_object(resource_path)
    if payload is None:
        return 0
    payload_session_id = payload.get("mst_session_id")
    if isinstance(payload_session_id, str) and payload_session_id.strip() and payload_session_id.strip() != session_id:
        print(
            f"Error: mst_session_id mismatch: env={session_id} payload={payload_session_id.strip()}",
            file=sys.stderr,
        )
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
_RESOURCE_ID_RE = re.compile(r"^(?:AGI|REQ|PLN)-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
def _normalize_flow_resource_id(value: object, allowed_prefixes: Optional[set[str]] = None) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().upper()
    if _RESOURCE_ID_RE.fullmatch(candidate) and (
        allowed_prefixes is None or candidate.split("-", 1)[0] in allowed_prefixes
    ):
        return candidate
    return ""
def _current_flow_resource_id() -> str:
    try:
        state_path = _workflow_state_file(_skill_state_base_dir())
        payload = _workflow_state_load(state_path)
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return ""

    scoped_candidates = [
        (payload.get("active_req"), {"REQ"}),
        (payload.get("active_agi"), {"AGI"}),
        (payload.get("agi_id"), {"AGI"}),
        (payload.get("active_plan"), {"PLN"}),
        (payload.get("plan_id"), {"PLN"}),
    ]
    for candidate, allowed_prefixes in scoped_candidates:
        resource_id = _normalize_flow_resource_id(candidate, allowed_prefixes)
        if resource_id:
            return resource_id

    candidates = []
    next_action_value = payload.get("next_action")
    if isinstance(next_action_value, dict):
        candidates.extend(
            [
                next_action_value.get("source_id"),
                next_action_value.get("source"),
                next_action_value.get("resource_id"),
            ]
        )

    for candidate in candidates:
        resource_id = _normalize_flow_resource_id(candidate)
        if resource_id:
            return resource_id
    return ""
def _append_skill_history_event(
    base_dir: Path,
    session_id: str,
    *,
    event_type: str,
    skill: str,
    step: int | None = None,
    total_steps: int | None = None,
    resource_id: str = "",
    status: str = "",
) -> bool:
    from scripts.mst_cmds import session as session_mod

    session_path = session_mod.session_metadata_path(base_dir, session_id)
    if not session_path.is_file():
        return True
    session_mod.validate_mst_session_metadata_consistency(
        base_dir,
        session_id,
        require_session_metadata=True,
    )
    logical_attempt_id = os.environ.get("MST_LOGICAL_ATTEMPT_ID", "").strip() or "default"
    key_parts = [
        f"skill={skill}",
        f"step={step}" if step is not None else "",
        f"total={total_steps}" if total_steps is not None else "",
        f"attempt={logical_attempt_id}",
    ]
    idempotency_key = f"{session_id}:{event_type}:" + ":".join(part for part in key_parts if part)
    parsed = session_mod.validate_mst_session_id(session_id)
    created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    payload = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": event_type,
        "skill": skill,
        "logical_attempt_id": logical_attempt_id,
        "idempotency_key": idempotency_key,
        "created_at": created_at,
    }
    if step is not None:
        payload["step"] = step
    if total_steps is not None:
        payload["total_steps"] = total_steps
    if resource_id:
        payload["artifact_id"] = resource_id
        payload["resource_id"] = resource_id
    else:
        payload["artifact_id"] = skill
    if status:
        payload["status"] = status
    session_mod.write_session_history_event(base_dir, session_id, payload)
    return True
def _json_object_env(name: str) -> dict:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
def _recover_non_success(
    code: str,
    message: str,
    *,
    session_id: Optional[str] = None,
    root_mst_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> dict:
    state_inconsistency_codes = {
        "history_head_missing",
        "history_mirror_head_missing",
        "history_verify_missing",
        "history_head_mismatch",
        "history_mirror_head_mismatch",
        "history_verify_mismatch",
        "history_verify_stale",
        "stale_history_head",
        "recursive_transition_depth_exceeded",
        "snapshot_projection_mismatch",
        "state_history_linkage_mismatch",
    }
    if code in state_inconsistency_codes:
        payload = _common.state_inconsistency_failure_payload(
            code=code,
            message=message,
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    else:
        payload = {
            "status": "error",
            "code": code,
            "message": message,
            "created_new_session": False,
            "prompt_summary_used_as_source": False,
        }
        if session_id:
            payload["mst_session_id"] = session_id
        else:
            payload["canonical_mst_session_id"] = None
        if root_mst_id:
            payload["root_mst_id"] = root_mst_id
    payload["legacy_diagnostics"] = _common.legacy_session_diagnostics()
    if details:
        payload.update(details)
    return payload
def _emit_recover_non_success(payload: dict) -> int:
    payload.setdefault(
        "external_control_surface",
        "recover" if len(sys.argv) > 1 and sys.argv[1] == "recover" else "state",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"{payload.get('code')}: {payload.get('message')}", file=sys.stderr)
    return 1
def _emit_validation_payload(payload: dict) -> int:
    payload.setdefault("external_control_surface", "state")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"{payload.get('code')}: {payload.get('message') or payload.get('reason')}", file=sys.stderr)
    return 1
def _read_canonical_recover_session_id() -> tuple[Optional[str], Optional[dict]]:
    raw_context = os.environ.get("MST_CONTEXT_JSON", "").strip()
    if raw_context:
        try:
            context_payload = json.loads(raw_context)
        except json.JSONDecodeError as exc:
            return None, _recover_non_success("invalid_mst_context_json", f"MST_CONTEXT_JSON must be a JSON object: {exc}")
        if not isinstance(context_payload, dict):
            return None, _recover_non_success("invalid_mst_context_json", "MST_CONTEXT_JSON must be a JSON object")
    try:
        session_id = _common.canonical_mst_session_id_from_env_or_context()
    except ValueError as exc:
        return None, _recover_non_success("invalid_mst_session_id", str(exc))
    if session_id:
        return session_id, None
    diagnostics = _common.legacy_session_diagnostics()
    code = "legacy_identity_not_canonical_source" if diagnostics else "missing_canonical_mst_session_id"
    return None, _recover_non_success(
        code,
        "recover requires canonical MST_SESSION_ID or structured mst_session_id",
    )
def _load_recover_history(base_dir: Path, session_id: str):
    from scripts.mst_cmds import hook as hook_cmds

    try:
        return hook_cmds._load_validated_history(
            project_root=base_dir.parent,
            policy_home=hook_cmds._policy_home(),
            raw_session_id=session_id,
        ), None
    except hook_cmds.HistoryValidationError as exc:
        return None, _recover_non_success(
            exc.code,
            exc.message,
            session_id=session_id,
            details=exc.details,
        )
def _history_ref_from_snapshot(snapshot: dict) -> dict:
    history = snapshot.get("history")
    return dict(history) if isinstance(history, dict) else {}
def _snapshot_history_refs(snapshot: dict) -> set[str]:
    history = _history_ref_from_snapshot(snapshot)
    refs = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = history.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    return refs
def _ledger_replay_projection(history_result) -> dict:
    workflow = {
        "current_skill": "",
        "status": "",
        "next_skill": "",
        "next_source": "",
    }
    for row in history_result.rows:
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type == "skill.recover":
            continue
        if event_type.startswith("skill."):
            skill = event.get("skill")
            if isinstance(skill, str) and skill.strip():
                workflow["current_skill"] = skill.strip()
            status = event.get("status")
            workflow["status"] = status.strip() if isinstance(status, str) and status.strip() else "active"
        next_action = event.get("next_action")
        if isinstance(next_action, dict):
            skill = next_action.get("expected_skill") or next_action.get("skill") or next_action.get("next_skill")
            source = next_action.get("source_id") or next_action.get("source")
            workflow["next_skill"] = skill.strip() if isinstance(skill, str) and skill.strip() else ""
            workflow["next_source"] = source.strip() if isinstance(source, str) and source.strip() else ""
    return {
        "workflow": workflow,
        "history": {
            "last_event_id": history_result.tail_hash,
            "head_hash": history_result.tail_hash,
            "seq": history_result.tail_seq,
        },
    }
def _validate_snapshot_projection_matches_replay(
    snapshot: dict,
    session_id: str,
    root_mst_id: str,
    history_result,
) -> Optional[dict]:
    replay = _ledger_replay_projection(history_result)
    snapshot_workflow = snapshot.get("workflow") if isinstance(snapshot.get("workflow"), dict) else {}
    snapshot_next = _next_skill_from_snapshot(snapshot)
    comparisons = [
        (
            "workflow.current_skill",
            replay["workflow"].get("current_skill") or "",
            snapshot_workflow.get("current_skill") or snapshot.get("currentSkill") or "",
        ),
        (
            "workflow.status",
            replay["workflow"].get("status") or "",
            snapshot_workflow.get("status") or snapshot.get("status") or "",
        ),
        (
            "workflow.next_skill",
            replay["workflow"].get("next_skill") or "",
            snapshot_workflow.get("next_skill") or snapshot_next.get("name") or "",
        ),
        (
            "workflow.next_source",
            replay["workflow"].get("next_source") or "",
            snapshot_workflow.get("next_source") or snapshot_next.get("source_id") or "",
        ),
    ]
    mismatches = [
        {"field": field, "expected": expected, "actual": actual}
        for field, expected, actual in comparisons
        if expected and actual and expected != actual
    ]
    if not mismatches:
        return None
    return _recover_non_success(
        "snapshot_projection_mismatch",
        "snapshot projection does not match validated ledger replay",
        session_id=session_id,
        root_mst_id=root_mst_id,
        details={
            "expected_history_head": history_result.tail_hash,
            "mismatch_subject": "snapshot_projection",
            "projection_mismatches": mismatches,
            "ledger_replay_projection": replay,
            "source_precedence": [
                "validated_history_ledger",
                "validated_state_snapshot",
                "prompt_summary_diagnostic_only",
            ],
        },
    )
