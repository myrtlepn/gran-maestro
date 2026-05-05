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


def _write_canonical_snapshot_payload(base_dir: Path, session_id: str, payload: dict) -> dict:
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
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"{payload.get('code')}: {payload.get('message')}", file=sys.stderr)
    return 1


def _emit_validation_payload(payload: dict) -> int:
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


def _validate_recover_snapshot(snapshot: dict, session_id: str, root_mst_id: str, history_result) -> Optional[dict]:
    validation_error = _common.canonical_state_payload_error(snapshot, session_id)
    if validation_error is not None:
        code = "snapshot_root_mismatch" if "root_mst_id mismatch" in validation_error else "state_history_linkage_mismatch"
        return _recover_non_success(
            code,
            f"snapshot {validation_error}",
            session_id=session_id,
            root_mst_id=root_mst_id,
        )
    refs = _snapshot_history_refs(snapshot)
    if not refs:
        return _recover_non_success(
            "missing_history_linkage",
            "snapshot history head or last event reference is required",
            session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if history_result.tail_hash not in refs:
        return _recover_non_success(
            "stale_history_head",
            "snapshot history reference does not match validated ledger head",
            session_id=session_id,
            root_mst_id=root_mst_id,
            details={"expected_history_head": history_result.tail_hash, "snapshot_history_refs": sorted(refs)},
        )
    projection_error = _validate_snapshot_projection_matches_replay(snapshot, session_id, root_mst_id, history_result)
    if projection_error is not None:
        return projection_error
    return None


def _workflow_from_snapshot(snapshot: Optional[dict], root_payload: Optional[dict]) -> dict:
    if isinstance(snapshot, dict):
        workflow = snapshot.get("workflow")
        if isinstance(workflow, dict):
            return {
                "current_skill": workflow.get("current_skill") or snapshot.get("currentSkill") or "",
                "current_step": workflow.get("current_step", snapshot.get("currentStep", 0)),
                "total_steps": workflow.get("total_steps", snapshot.get("totalSteps", 0)),
                "status": workflow.get("status") or snapshot.get("status") or "",
            }
        return {
            "current_skill": snapshot.get("currentSkill") or "",
            "current_step": snapshot.get("currentStep", 0),
            "total_steps": snapshot.get("totalSteps", 0),
            "status": snapshot.get("status") or "",
        }
    return {
        "current_skill": "",
        "current_step": 0,
        "total_steps": 0,
        "status": root_payload.get("status") if isinstance(root_payload, dict) else "",
    }


def _next_skill_from_snapshot(snapshot: Optional[dict]) -> dict:
    next_action_value = snapshot.get("next_action") if isinstance(snapshot, dict) else None
    next_action_payload = next_action_value if isinstance(next_action_value, dict) else {}
    name = (
        next_action_payload.get("expected_skill")
        or next_action_payload.get("skill")
        or next_action_payload.get("next_skill")
        or ""
    )
    source_id = next_action_payload.get("source_id") or next_action_payload.get("source") or ""
    return {
        "name": name,
        "source_id": source_id,
        "auto": bool(next_action_payload.get("auto") or next_action_payload.get("auto_mode")),
        "metadata": next_action_payload,
    }


def _recovery_fingerprint(agi_id: str, session_id: str) -> str:
    context = _json_object_env("MST_CONTEXT_JSON")
    direct = context.get("recovery_fingerprint")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    core = context.get("core_rehydration")
    if isinstance(core, dict):
        nested = core.get("recovery_fingerprint")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    material = f"{session_id}:{agi_id}:recover"
    return "recover:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _append_recover_history_event(base_dir: Path, session_id: str, agi_id: str, recovery_fingerprint: str) -> None:
    from scripts.mst_cmds import session as session_mod

    parsed = session_mod.validate_mst_session_id(session_id)
    idempotency_key = f"{session_id}:skill.recover:{recovery_fingerprint}"
    session_mod.write_session_history_event(
        base_dir,
        session_id,
        {
            "schema_version": 1,
            "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
            "mst_session_id": parsed.mst_session_id,
            "root_mst_id": parsed.root_mst_id,
            "event_type": "skill.recover",
            "skill": "mst:recover",
            "resource_id": agi_id,
            "artifact_id": agi_id,
            "status": "rehydrated",
            "recovery_fingerprint": recovery_fingerprint,
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        },
    )


def _update_snapshot_history_head(state_base_dir: Path, session_id: str, snapshot: Optional[dict], previous_head: str, current_head: str) -> None:
    if not isinstance(snapshot, dict):
        return
    history = _history_ref_from_snapshot(snapshot)
    changed = False
    if history.get("head_hash") != current_head:
        history["head_hash"] = current_head
        changed = True
    if not isinstance(history.get("last_event_id"), str) or not history.get("last_event_id"):
        history["last_event_id"] = previous_head
        changed = True
    if changed:
        updated = dict(snapshot)
        updated["history"] = history
        _atomic_json_write(_snapshot_path_for_session(state_base_dir, session_id), updated)


def _recover_rehydration_bundle(
    *,
    session_id: str,
    root_mst_id: str,
    snapshot: Optional[dict],
    root_payload: Optional[dict],
    history_result,
    previous_history_head: str,
    recovery_fingerprint: str,
) -> dict:
    workflow = _workflow_from_snapshot(snapshot, root_payload)
    next_skill = _next_skill_from_snapshot(snapshot)
    workflow["next_skill"] = next_skill.get("name") or ""
    workflow["next_source"] = next_skill.get("source_id") or ""
    continuation = {}
    if isinstance(snapshot, dict) and isinstance(snapshot.get("continuation"), dict):
        continuation = copy.deepcopy(snapshot["continuation"])
    next_action = None
    if isinstance(snapshot, dict) and isinstance(snapshot.get("next_action"), dict):
        next_action = copy.deepcopy(snapshot["next_action"])
    if next_action is not None:
        continuation.setdefault("next_action", next_action)
    if isinstance(snapshot, dict) and snapshot.get("auto") is True:
        continuation.setdefault("mode", "continue_unless_critical")
        continuation.setdefault("critical_blocker", None)
    context = {
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "recovery_fingerprint": recovery_fingerprint,
    }
    return {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
        "continuation": continuation,
        "workflow": workflow,
        "current_skill": {
            "name": workflow.get("current_skill") or "",
            "step": workflow.get("current_step", 0),
            "total_steps": workflow.get("total_steps", 0),
            "status": workflow.get("status") or "",
        },
        "skill_stack": snapshot.get("skillStack", []) if isinstance(snapshot, dict) and isinstance(snapshot.get("skillStack"), list) else [],
        "next_skill": next_skill,
        "history": {
            "head_hash": history_result.tail_hash,
            "last_event_id": previous_history_head,
            "seq": history_result.tail_seq,
            "path": str(history_result.history_file),
        },
        "next_execution": {
            "env": {"MST_SESSION_ID": session_id},
            "context": context,
        },
        "source_precedence": ["validated_history_ledger", "validated_state_snapshot", "prompt_summary_diagnostic_only"],
        "prompt_summary_used_as_source": False,
        "recovery_fingerprint": recovery_fingerprint,
        "created_new_session": False,
    }


def _structured_legacy_alias_conflict(session_id: str) -> Optional[dict]:
    diagnostics = _common.legacy_session_diagnostics()
    snapshot_alias = diagnostics.get("MST_SNAPSHOT_SESSION_ID")
    if isinstance(snapshot_alias, str) and snapshot_alias.strip():
        try:
            from scripts.mst_cmds.session import validate_mst_session_id

            alias_session_id = validate_mst_session_id(snapshot_alias.strip()).mst_session_id
        except ValueError:
            alias_session_id = ""
        if alias_session_id and alias_session_id != session_id:
            return _recover_non_success(
                "legacy_identity_not_canonical_source",
                "MST_SNAPSHOT_SESSION_ID conflicts with canonical MST_SESSION_ID",
                session_id=session_id,
                details={"legacy_conflict_source": "MST_SNAPSHOT_SESSION_ID"},
            )
    return None


def _context_core_history_refs() -> set[str]:
    context = _json_object_env("MST_CONTEXT_JSON")
    core = context.get("core_rehydration")
    if not isinstance(core, dict):
        return set()
    history = core.get("history")
    if not isinstance(history, dict):
        return set()
    refs: set[str] = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = history.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    return refs


def _recover_context_contract_failure(
    *,
    session_id: str,
    root_mst_id: str,
    history_result,
    snapshot: Optional[dict],
) -> Optional[dict]:
    context = _json_object_env("MST_CONTEXT_JSON")
    if not context:
        return None
    if context.get("schema_version") is not None and context.get("schema_version") != 1:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="schema_version",
            reason="recover bundle schema_version must be 1",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    core = context.get("core_rehydration")
    has_legacy_identity = any(
        isinstance(context.get(key), str) and context.get(key, "").strip()
        for key in ("session_id", "sessionId", "owner_session_id")
    )
    if isinstance(core, dict):
        has_legacy_identity = has_legacy_identity or any(
            isinstance(core.get(key), str) and core.get(key, "").strip()
            for key in ("session_id", "sessionId", "owner_session_id")
        )
    if has_legacy_identity:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="legacy_identity",
            reason="legacy session identity is not a canonical source",
            code="legacy_identity_not_canonical_source",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if not isinstance(core, dict):
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration",
            reason="core_rehydration object is required",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if core.get("schema_version") != 1:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.schema_version",
            reason="core_rehydration.schema_version is required and must be 1",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if core.get("mst_session_id") != session_id:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.mst_session_id",
            reason="core_rehydration.mst_session_id must match MST_SESSION_ID",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if core.get("root_mst_id") != root_mst_id:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.root_mst_id",
            reason="core_rehydration.root_mst_id must match session root",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )

    history = core.get("history")
    if not isinstance(history, dict):
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.history_last_event_id",
            reason="core_rehydration.history is required",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    refs = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = history.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    if history_result.tail_hash not in refs:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.history_last_event_id",
            reason="core_rehydration history reference does not match validated ledger head",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
            expected_history_head=history_result.tail_hash,
            core_rehydration_history_refs=sorted(refs),
        )

    workflow = core.get("workflow")
    snapshot_next = _next_skill_from_snapshot(snapshot) if isinstance(snapshot, dict) else {}
    core_next_source = workflow.get("next_source") if isinstance(workflow, dict) else None
    core_next_skill = workflow.get("next_skill") if isinstance(workflow, dict) else None
    strict_current_fields = (
        "auto" in core
        or "continuation" in core
        or "current_skill" in core
        or (
            isinstance(snapshot_next, dict)
            and (
                (snapshot_next.get("source_id") and core_next_source and snapshot_next.get("source_id") != core_next_source)
                or (snapshot_next.get("name") and core_next_skill and snapshot_next.get("name") != core_next_skill)
            )
        )
    )
    if strict_current_fields:
        auto_missing = not isinstance(core.get("auto"), bool)
        continuation_missing = not isinstance(core.get("continuation"), dict)
        core_current_skill = core.get("current_skill")
        workflow_current_skill = workflow.get("current_skill") if isinstance(workflow, dict) else None
        current_skill_missing = not (
            (isinstance(core_current_skill, str) and core_current_skill.strip())
            or (isinstance(workflow_current_skill, str) and workflow_current_skill.strip())
        )
        if auto_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.auto",
                reason="core_rehydration.auto is required and must be boolean",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
        if continuation_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.continuation",
                reason="core_rehydration.continuation object is required",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
        if current_skill_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.current_skill",
                reason="core_rehydration.current_skill is required",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
    return None


def _history_tail_is_current_invocation_start_after_refs(history_result, refs: set[str]) -> bool:
    if not history_result.rows or not history_result.projections:
        return False
    projection = history_result.projections[-1]
    if projection.get("event_type") != "mst.invocation_start":
        return False
    if projection.get("prev_hash") not in refs:
        return False
    row = history_result.rows[-1]
    event = row.get("event") if isinstance(row, dict) else None
    if not isinstance(event, dict):
        return False
    return str(event.get("pid") or "") == str(os.getpid())


def _validate_context_rehydration_head_for_write(session_id: str) -> Optional[dict]:
    refs = _context_core_history_refs()
    if not refs:
        return None
    snapshot = _load_snapshot_for_session(_skill_state_base_dir(), session_id)
    snapshot_refs = _snapshot_history_refs(snapshot) if isinstance(snapshot, dict) else set()
    if refs & snapshot_refs:
        return None
    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return history_error
    assert history_result is not None
    if history_result.tail_hash not in refs and not _history_tail_is_current_invocation_start_after_refs(history_result, refs):
        return _recover_non_success(
            "stale_history_head",
            "core rehydration history reference does not match validated ledger head",
            session_id=session_id,
            root_mst_id=history_result.root_mst_id,
            details={
                "expected_history_head": history_result.tail_hash,
                "core_rehydration_history_refs": sorted(refs),
                "attempted_recovery": "validated ledger head before automatic state write",
                "next_safe_action": "inspect-only state/history consistency verification",
                "write_allowed": False,
                "mismatch_subject": "core_rehydration.history",
            },
        )
    return None


def _transition_depth_limit() -> int:
    raw = os.environ.get("MST_TRANSITION_DEPTH_LIMIT", "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 8
    return parsed if parsed > 0 else 8


def _continuation_chain_guard_for_write(session_id: str) -> Optional[dict]:
    contexts: list[dict] = []
    snapshot = _load_snapshot_for_session(_skill_state_base_dir(), session_id)
    if isinstance(snapshot, dict) and isinstance(snapshot.get("continuation"), dict):
        contexts.append(snapshot["continuation"])
    env_context = _json_object_env("MST_CONTEXT_JSON")
    core = env_context.get("core_rehydration")
    if isinstance(core, dict) and isinstance(core.get("continuation"), dict):
        contexts.append(core["continuation"])
    if not contexts:
        return None

    limit = _transition_depth_limit()
    selected: dict | None = None
    selected_depth = 0
    for continuation in contexts:
        raw_depth = continuation.get("transition_depth")
        try:
            depth = int(raw_depth)
        except (TypeError, ValueError):
            continue
        if depth > selected_depth:
            selected_depth = depth
            selected = continuation

    if selected is None or selected_depth <= limit:
        return None

    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return history_error
    root_mst_id = history_result.root_mst_id if history_result is not None else None
    return _recover_non_success(
        "recursive_transition_depth_exceeded",
        "recursive recover/compact/continuation depth exceeded safe automatic write limit",
        session_id=session_id,
        root_mst_id=root_mst_id,
        details={
            "transition_source": selected.get("transition_source") or "unknown",
            "transition_depth": selected_depth,
            "transition_depth_limit": limit,
            "chain_id": selected.get("chain_id") or "",
            "write_allowed": False,
            "next_safe_action": "inspect-only state/history consistency verification",
            "attempted_recovery": "downgraded automatic write after recursive transition guard",
            "mismatch_subject": "recursive_transition_guard",
        },
    )


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
    session_id = canonical_session_id_from_env() or _resolve_owner_session_id(ppid)

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
    gm_dir = _common.base_dir_from_project(base_dir)
    state_dir = _common.state_dir(gm_dir)
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
        backup_dir = _common.backups_dir(_common.base_dir_from_project(base_dir)) / f"state-migrate-{timestamp}"
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
    state_dir = _common.state_dir(_common.base_dir_from_project(base_dir))
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
        state_dir = _common.state_dir(_common.base_dir_from_project(base_dir))
        dst = state_dir / target_name
        if dst.exists() and dst != src:
            dst = _next_available_path(state_dir / f"legacy-{ppid}")
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
    gm_dir = _common.base_dir_from_project(base_dir)
    backup_path = _common.backups_dir(gm_dir) / f"state-migrate-{timestamp}"
    out_targets = []
    ppid_to_session = {
        target["ppid"]: target.get("owner_session_id")
        for target in targets
        if target["type"] == "rename_dir" and target.get("owner_session_id")
    }

    for target in targets:
        if target["type"] == "rename_dir":
            session_id = target.get("owner_session_id")
            state_dir = _common.state_dir(gm_dir)
            if session_id:
                to_path = str(state_dir / session_id)
            else:
                to_path = str(state_dir / f"legacy-{target['ppid']}")
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
    gm_dir = _common.base_dir_from_project(base_dir)
    backups_dir = _common.backups_dir(gm_dir)
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
    log_path = _common.logs_dir(gm_dir) / f"state-migrate-rollback-{timestamp}.log"
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
    gm_dir = _common.base_dir_from_project(base_dir)
    state_dir = _common.state_dir(gm_dir)
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

    backups_dir = _common.backups_dir(gm_dir)
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
    gm_dir = _common.base_dir_from_project(base_dir)
    log_path = _common.logs_dir(gm_dir) / f"state-migrate-{timestamp}.log"
    backup_dir = _common.backups_dir(gm_dir) / f"state-migrate-{timestamp}"
    lock_path = gm_dir / "tmp" / "mst-state-migrate.lock"

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
    now = _workflow_state_timestamp()

    try:
        session_id = _common.require_mst_session_id_for_mutation("workflow state write")
        state_path = _workflow_state_file(state_base_dir)
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            payload = _workflow_state_default_payload(now)
        else:
            valid_workflow, workflow_error = _validate_existing_workflow_payload(payload, session_id)
            if not valid_workflow:
                print(f"Error: workflow {workflow_error}", file=sys.stderr)
                return 1

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            next_action = {}

        was_active = payload.get("workflow_active") is True
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

        if args.active or (was_active and not args.active):
            payload["last_active_at"] = now

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
        payload.update(_common.canonical_state_payload_fields(session_id))
        diagnostics = _common.legacy_session_diagnostics()
        if diagnostics:
            payload["legacy_diagnostics"] = diagnostics
        _workflow_state_atomic_write(state_path, payload)

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
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("workflow state write")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[mst] error: failed to update workflow state: {exc}", file=sys.stderr)
        return 1

    return 0

def cmd_state_set(args):
    from scripts._skill_state import set_snapshot
    from scripts._flow_logger import append_skill_event, flow_log_path, safe_session_id

    state_base_dir = _skill_state_base_dir()
    project_root = state_base_dir.parent
    try:
        session_id = _snapshot_session_id()
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state set")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        try:
            payload = json.loads(validation_error)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return _emit_validation_payload(payload)
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    context_head_error = _validate_context_rehydration_head_for_write(session_id)
    if context_head_error is not None:
        return _emit_recover_non_success(context_head_error)
    transition_guard_error = _continuation_chain_guard_for_write(session_id)
    if transition_guard_error is not None:
        return _emit_recover_non_success(transition_guard_error)
    resource_id = _current_flow_resource_id()
    try:
        if args.step == 0:
            _append_skill_history_event(
                state_base_dir,
                session_id,
                event_type="skill.enter",
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                resource_id=resource_id,
            )
        _append_skill_history_event(
            state_base_dir,
            session_id,
            event_type="skill.step",
            skill=args.skill,
            step=args.step,
            total_steps=args.total,
            resource_id=resource_id,
        )
        if args.step == args.total:
            _append_skill_history_event(
                state_base_dir,
                session_id,
                event_type="skill.exit",
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                resource_id=resource_id,
                status="completed",
            )
    except Exception as exc:
        print(f"Error: failed to append skill history: {exc}", file=sys.stderr)
        return 1
    data = set_snapshot(
        state_base_dir,
        skill=args.skill,
        step=args.step,
        total=args.total,
        return_to=args.return_to,
        session_id=session_id,
    )
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
    try:
        parent_skill, parent_step = _parse_return_to_parent(args.return_to)
        flow_path = flow_log_path(project_root, rotate=True)
        log_session_id = safe_session_id(session_id)
        duration_ms = _previous_enter_duration_ms(flow_path, log_session_id, args.skill)
        extras = {"resource_id": resource_id} if resource_id else None
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
            extras=extras,
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
                extras=extras,
                rotate=True,
            )
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_get(args):
    from scripts._skill_state import load_snapshot

    try:
        session_id = _common.require_mst_session_id_for_mutation("state snapshot read")
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state get")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = load_snapshot(_skill_state_base_dir(), session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    contract_failure = _state_snapshot_contract_failure(data, session_id)
    if contract_failure is not None:
        return _emit_validation_payload(contract_failure)
    validation_error = _common.canonical_state_payload_error(data, session_id)
    if validation_error is not None:
        return _common.emit_validation_failure(
            target="state_snapshot",
            field="mst_session_id" if "mst_session_id" in validation_error else "state_snapshot",
            reason=f"snapshot {validation_error}",
        )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_clear(args):
    from scripts._skill_state import clear_snapshot

    try:
        session_id = _snapshot_session_id()
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state clear")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(_skill_state_base_dir(), session_id)
    if not valid_snapshot:
        try:
            payload = json.loads(validation_error)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return _emit_validation_payload(payload)
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    clear_snapshot(_skill_state_base_dir(), session_id=session_id)
    print("스냅샷 초기화 완료")
    return 0


def cmd_state_recover(args):
    from scripts._skill_state import (
        load_snapshot,
    )
    from scripts.mst_cmds import session as session_mod

    strict_rehydration = getattr(args, "command", "") == "recover"
    try:
        agi_id = _normalize_agi_id_for_recover(args.agi_id)
    except ValueError as exc:
        return _emit_recover_non_success(_recover_non_success("invalid_root_mst_id", str(exc)))

    session_id, source_error = _read_canonical_recover_session_id()
    if source_error is not None:
        return _emit_recover_non_success(source_error)
    assert session_id is not None
    legacy_conflict = _structured_legacy_alias_conflict(session_id)
    if legacy_conflict is not None:
        return _emit_recover_non_success(legacy_conflict)

    try:
        parsed = session_mod.validate_mst_session_metadata_consistency(
            _common.BASE_DIR,
            session_id,
            require_root_metadata=True,
            require_session_metadata=True,
        )
    except ValueError as exc:
        message = str(exc)
        if not strict_rehydration and "mst_session_id mismatch" not in message:
            message = f"mst_session_id mismatch: {message}"
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                message,
                session_id=session_id,
            )
        )
    if parsed.root_mst_id != agi_id:
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                f"recover root mismatch: arg={agi_id} session={parsed.root_mst_id}",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )

    session_path = _agile_session_path(agi_id)
    session_payload = _load_json_object(session_path)
    if session_payload is None:
        return _emit_recover_non_success(
            _recover_non_success(
                "missing_root_metadata",
                f"durable root session not found: {session_path}",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )

    previous_owner = session_payload.get("owner_session_id")
    previous_owner = previous_owner.strip() if isinstance(previous_owner, str) and previous_owner.strip() else None
    if previous_owner and previous_owner != session_id:
        print(
            f"[cross-session recover] diagnostic: owner_session_id ignored: "
            f"previous={previous_owner} current={session_id}",
            file=sys.stderr,
        )

    state_base_dir = _skill_state_base_dir()
    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return _emit_recover_non_success(history_error)
    assert history_result is not None

    existing = load_snapshot(state_base_dir, session_id=session_id)
    if existing is not None:
        snapshot_error = _validate_recover_snapshot(existing, session_id, parsed.root_mst_id, history_result)
        if snapshot_error is not None and (strict_rehydration or snapshot_error.get("code") != "missing_history_linkage"):
            return _emit_recover_non_success(snapshot_error)
    context_contract_error = _recover_context_contract_failure(
        session_id=session_id,
        root_mst_id=parsed.root_mst_id,
        history_result=history_result,
        snapshot=existing,
    )
    if context_contract_error is not None:
        return _emit_recover_non_success(context_contract_error)

    if previous_owner and previous_owner != session_id and getattr(args, "takeover", False):
        def _mutate_owner(payload: dict) -> dict:
            payload["owner_session_id"] = session_id
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            return payload

        try:
            _check_takeover_storm(agi_id)
            _with_locked_json_update(session_path, _mutate_owner)
        except TakeoverStormError as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_blocked", str(exc), session_id=session_id, root_mst_id=parsed.root_mst_id)
            )
        except TimeoutError as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_failed", str(exc), session_id=session_id, root_mst_id=parsed.root_mst_id)
            )
        except Exception as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_failed", f"failed to takeover owner: {exc}", session_id=session_id, root_mst_id=parsed.root_mst_id)
            )

    previous_history_head = history_result.tail_hash
    recovery_fingerprint = _recovery_fingerprint(agi_id, session_id)
    try:
        _append_recover_history_event(_common.BASE_DIR, session_id, agi_id, recovery_fingerprint)
        updated_history, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    except Exception as exc:
        return _emit_recover_non_success(
            _recover_non_success(
                "recover_history_append_failed",
                str(exc),
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )
    if history_error is not None:
        return _emit_recover_non_success(history_error)
    assert updated_history is not None

    _update_snapshot_history_head(state_base_dir, session_id, existing, previous_history_head, updated_history.tail_hash)
    envelope = _recover_rehydration_bundle(
        session_id=session_id,
        root_mst_id=parsed.root_mst_id,
        snapshot=existing,
        root_payload=session_payload,
        history_result=updated_history,
        previous_history_head=previous_history_head,
        recovery_fingerprint=recovery_fingerprint,
    )
    print(json.dumps({"status": "ok", "core_rehydration": envelope}, ensure_ascii=False, indent=2))
    return 0


def cmd_state_mark_paused(args):
    from scripts._skill_state import mark_paused

    session_id, error = _require_args_session_matches_env(args.session_id)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    state_base_dir = _skill_state_base_dir()
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    data = mark_paused(state_base_dir, session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_resume_paused(args):
    from scripts._skill_state import resume_paused

    session_id, error = _require_args_session_matches_env(args.session_id)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    state_base_dir = _skill_state_base_dir()
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    data = resume_paused(state_base_dir, session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
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
