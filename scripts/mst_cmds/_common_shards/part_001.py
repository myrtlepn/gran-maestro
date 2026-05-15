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
RUNTIME_ROOT_POINTER_FIELDS = (
    "canonical_runtime_root",
    "runtime_metadata_root",
    "mst_runtime_root",
    "MST_RUNTIME_ROOT",
)
RUNTIME_LEGACY_DIAGNOSTIC_FIELDS = (
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
RUNTIME_CONTEXT_SECTIONS = (
    "current_session",
    "session",
    "child_metadata",
    "child",
    "request",
    "metadata",
)
def _runtime_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
def _runtime_normalize_path(value: object) -> str | None:
    text = _runtime_string(value)
    if not text:
        return None
    return str(Path(text).expanduser().resolve(strict=False))
def _runtime_payloads(context: dict) -> list[tuple[str, dict]]:
    payloads: list[tuple[str, dict]] = [("context", context)]
    for section in RUNTIME_CONTEXT_SECTIONS:
        value = context.get(section)
        if isinstance(value, dict):
            payloads.append((section, value))
    return payloads
def _runtime_pointer_sources(context: dict) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    for name, payload in _runtime_payloads(context):
        for field in RUNTIME_ROOT_POINTER_FIELDS:
            value = _runtime_string(payload.get(field))
            normalized = _runtime_normalize_path(value)
            if value and normalized:
                sources.append({
                    "source": f"{name}.{field}",
                    "field": field,
                    "value": value,
                    "normalized": normalized,
                })
    return sources
def _runtime_legacy_diagnostics(context: dict) -> dict[str, dict[str, object]]:
    diagnostics: dict[str, dict[str, object]] = {}
    for name, payload in _runtime_payloads(context):
        section: dict[str, object] = {}
        for field in RUNTIME_LEGACY_DIAGNOSTIC_FIELDS:
            value = payload.get(field)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            section[field] = value
        if section:
            diagnostics[name] = section
    return diagnostics
def _runtime_trusted_original_root(context: dict) -> str | None:
    direct = _runtime_normalize_path(context.get("trusted_original_runtime_root"))
    if direct:
        return direct
    project_root = _runtime_normalize_path(context.get("trusted_original_project_root"))
    if project_root:
        return str((Path(project_root) / _base_dir_name()).resolve(strict=False))
    if context.get("original_project_root_trusted") is True:
        original_root = _runtime_normalize_path(context.get("original_project_root"))
        if original_root:
            return str((Path(original_root) / _base_dir_name()).resolve(strict=False))
    return None
def _runtime_local_roots(context: dict) -> list[dict[str, object]]:
    roots: list[dict[str, object]] = []
    raw_roots = context.get("local_runtime_roots")
    if isinstance(raw_roots, list):
        for index, value in enumerate(raw_roots):
            normalized = _runtime_normalize_path(value)
            if normalized:
                roots.append({"source": f"local_runtime_roots[{index}]", "normalized": normalized})
    for field in ("local_runtime_root", "cwd_runtime_root", "detected_runtime_root"):
        normalized = _runtime_normalize_path(context.get(field))
        if normalized:
            roots.append({"source": field, "normalized": normalized})
    if context.get("has_local_gran_maestro") is True:
        current = _runtime_normalize_path(context.get("current_cwd") or context.get("current_root"))
        if current:
            roots.append({"source": "current_cwd/.gran-maestro", "normalized": str((Path(current) / _base_dir_name()).resolve(strict=False))})
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for root in roots:
        normalized = str(root["normalized"])
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(root)
    return deduped
def _runtime_context_mst_session_id(context: dict, explicit_mst_session_id: str | None) -> str | None:
    if explicit_mst_session_id:
        return explicit_mst_session_id
    for _, payload in _runtime_payloads(context):
        value = _runtime_string(payload.get("mst_session_id"))
        if value:
            return value
    return None
def _runtime_context_req_id(context: dict, explicit_req_id: str | None) -> str | None:
    if explicit_req_id:
        return explicit_req_id
    for field in ("req_id", "request_id", "id"):
        value = _runtime_string(context.get(field))
        if value:
            return value
    request = context.get("request")
    if isinstance(request, dict):
        value = _runtime_string(request.get("id") or request.get("req_id"))
        if value:
            return value
    return None
def _runtime_safe_component(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if is_path_safe_mst_session_id(text):
        return text
    return None
def _runtime_metadata_paths(canonical_runtime_root: str, mst_session_id: str | None, req_id: str | None) -> dict[str, str]:
    root = Path(canonical_runtime_root)
    paths: dict[str, str] = {
        "runtime_root": str(root),
        "sessions_dir": str(root / "sessions"),
        "state_dir": str(root / "state"),
        "requests_dir": str(root / "requests"),
        "worktrees_dir": str(root / "worktrees"),
    }
    safe_session_id = _runtime_safe_component(mst_session_id)
    if safe_session_id:
        session_dir = root / "sessions" / safe_session_id
        state_session_dir = root / "state" / safe_session_id
        paths.update({
            "session_dir": str(session_dir),
            "session_history": str(session_dir / "history.jsonl"),
            "execution_flow": str(session_dir / "execution-flow.json"),
            "lifecycle_events": str(session_dir / "lifecycle.ndjson"),
            "state_session_dir": str(state_session_dir),
            "state_snapshot": str(state_session_dir / "snapshot.json"),
            "flow_detail": str(state_session_dir / "flow-detail.ndjson"),
        })
    safe_req_id = _runtime_safe_component(req_id)
    if safe_req_id:
        request_dir = root / "requests" / safe_req_id
        paths.update({
            "request_dir": str(request_dir),
            "request_json": str(request_dir / "request.json"),
        })
    return paths
def _runtime_root_payload(
    *,
    classification: str,
    allowed: bool,
    canonical_runtime_root: str | None,
    metadata_paths: dict[str, str] | None,
    diagnostics: dict[str, object],
    legacy_diagnostics: dict[str, dict[str, object]],
    reason: str,
) -> dict[str, object]:
    return {
        "classification": classification,
        "allowed": allowed,
        "canonical_runtime_root": canonical_runtime_root,
        "metadata_paths": metadata_paths or {},
        "diagnostics": diagnostics,
        "legacy_diagnostics": legacy_diagnostics,
        "reason": reason,
        "destructive_action_allowed": False,
    }
def resolve_canonical_runtime_root_state(context, *, mst_session_id=None, req_id=None) -> dict[str, object]:
    payload = context if isinstance(context, dict) else {}
    pointer_sources = _runtime_pointer_sources(payload)
    pointer_roots = sorted({str(source["normalized"]) for source in pointer_sources})
    local_roots = _runtime_local_roots(payload)
    trusted_original_root = _runtime_trusted_original_root(payload)
    diagnostics: dict[str, object] = {
        "pointer_sources": pointer_sources,
        "local_runtime_roots": local_roots,
        "trusted_original_runtime_root": trusted_original_root,
    }
    legacy_diagnostics = _runtime_legacy_diagnostics(payload)

    if len(pointer_roots) > 1:
        return _runtime_root_payload(
            classification="split_runtime_root_blocked",
            allowed=False,
            canonical_runtime_root=None,
            metadata_paths=None,
            diagnostics=diagnostics,
            legacy_diagnostics=legacy_diagnostics,
            reason="runtime_root_pointer_mismatch",
        )

    resolved_session_id = _runtime_context_mst_session_id(payload, mst_session_id)
    resolved_req_id = _runtime_context_req_id(payload, req_id)
    if pointer_roots:
        canonical_root = pointer_roots[0]
        return _runtime_root_payload(
            classification="canonical_runtime_root",
            allowed=True,
            canonical_runtime_root=canonical_root,
            metadata_paths=_runtime_metadata_paths(canonical_root, resolved_session_id, resolved_req_id),
            diagnostics=diagnostics,
            legacy_diagnostics=legacy_diagnostics,
            reason="explicit_runtime_root_pointer",
        )

    if trusted_original_root:
        conflicting_local_roots = [root for root in local_roots if root.get("normalized") != trusted_original_root]
        diagnostics["conflicting_local_runtime_roots"] = conflicting_local_roots
        if conflicting_local_roots:
            return _runtime_root_payload(
                classification="split_runtime_root_blocked",
                allowed=False,
                canonical_runtime_root=None,
                metadata_paths=None,
                diagnostics=diagnostics,
                legacy_diagnostics=legacy_diagnostics,
                reason="local_runtime_root_conflicts_with_trusted_original",
            )
        return _runtime_root_payload(
            classification="trusted_original_root",
            allowed=True,
            canonical_runtime_root=trusted_original_root,
            metadata_paths=_runtime_metadata_paths(trusted_original_root, resolved_session_id, resolved_req_id),
            diagnostics=diagnostics,
            legacy_diagnostics=legacy_diagnostics,
            reason="trusted_original_runtime_root_fallback",
        )

    if local_roots:
        return _runtime_root_payload(
            classification="split_runtime_root_blocked",
            allowed=False,
            canonical_runtime_root=None,
            metadata_paths=None,
            diagnostics=diagnostics,
            legacy_diagnostics=legacy_diagnostics,
            reason="missing_trusted_runtime_root_pointer",
        )

    return _runtime_root_payload(
        classification="missing_runtime_root",
        allowed=False,
        canonical_runtime_root=None,
        metadata_paths=None,
        diagnostics=diagnostics,
        legacy_diagnostics=legacy_diagnostics,
        reason="missing_canonical_runtime_root_pointer",
    )
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
        core = payload.get("core_rehydration")
        if isinstance(core, dict):
            value = core.get("mst_session_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        value = payload.get("mst_session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
CANONICAL_SESSION_SOURCE_PRECEDENCE = [
    "env:MST_SESSION_ID",
    "structured:mst_session_id",
    "session_metadata:mst_session_id",
    "snapshot_path:mst_session_id",
    "snapshot_body:mst_session_id",
]
def canonical_session_source_precedence() -> list[str]:
    return list(CANONICAL_SESSION_SOURCE_PRECEDENCE)
def canonical_mst_session_id_from_env_or_context() -> str | None:
    if len(sys.argv) > 1 and sys.argv[1] == "dispatch" and os.environ.get("MST_INVOCATION_HISTORY_ACTIVE") != "1":
        return None
    env_value = canonical_session_id_from_env()
    context_value = structured_mst_session_id_from_env()
    if env_value and context_value and env_value != context_value:
        raise ValueError("MST_SESSION_ID and structured mst_session_id mismatch")
    value = env_value or context_value
    if value:
        from scripts.mst_cmds.session import validate_mst_session_id

        try:
            return validate_mst_session_id(value).mst_session_id
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
    return value
def require_mst_session_id_for_mutation(subject: str = "state write") -> str:
    value = canonical_mst_session_id_from_env_or_context()
    if not value:
        raise ValueError(f"missing MST_SESSION_ID for {subject}")
    return value
def canonical_state_payload_fields(mst_session_id: str) -> dict:
    from scripts.mst_cmds.session import validate_mst_session_id

    parsed = validate_mst_session_id(mst_session_id)
    return {
        "schema_version": 1,
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
    }
def canonical_state_payload_error(payload: dict, mst_session_id: str) -> str | None:
    if not isinstance(payload, dict):
        return "state payload must be a JSON object"

    from scripts.mst_cmds.session import validate_mst_session_id, validate_root_mst_id

    parsed = validate_mst_session_id(mst_session_id)
    raw_session_id = payload.get("mst_session_id")
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        return "state payload missing mst_session_id"
    if raw_session_id.strip() != parsed.mst_session_id:
        return f"state payload mst_session_id mismatch: path={parsed.mst_session_id} payload={raw_session_id.strip()}"

    raw_schema_version = payload.get("schema_version")
    if raw_schema_version != 1:
        return "state payload schema_version missing or unsupported"

    raw_root = payload.get("root_mst_id")
    if not isinstance(raw_root, str) or not raw_root.strip():
        return "state payload missing root_mst_id"
    try:
        payload_root = validate_root_mst_id(raw_root.strip())
    except ValueError as exc:
        return str(exc)
    if payload_root != parsed.root_mst_id:
        return f"state payload root_mst_id mismatch: session={parsed.root_mst_id} payload={payload_root}"

    return None
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
def session_identity_non_success_code(error: object | None = None, diagnostics: dict | None = None) -> str | None:
    text = str(error or "")
    if "MST_SESSION_ID and structured mst_session_id mismatch" in text:
        return "mst_session_id_mismatch"
    if "invalid structured mst_session_id" in text:
        return "invalid_canonical_mst_session_id"
    if "missing MST_SESSION_ID" in text or "missing canonical MST_SESSION_ID" in text:
        return "legacy_identity_not_canonical_source" if diagnostics else "missing_canonical_mst_session_id"
    if error is None:
        return "legacy_identity_not_canonical_source" if diagnostics else "missing_canonical_mst_session_id"
    return None
def session_identity_non_success_payload(
    subject: str,
    message: str | None = None,
    *,
    code: str | None = None,
    error: object | None = None,
    invocation_class: str = "external_invocation",
) -> dict:
    diagnostics = legacy_session_diagnostics()
    resolved_code = code or session_identity_non_success_code(error, diagnostics) or "missing_canonical_mst_session_id"
    observed_sources = {
        "env:MST_SESSION_ID": {
            "present": bool(canonical_session_id_from_env()),
            "value": canonical_session_id_from_env(),
        },
        "structured:mst_session_id": {
            "present": bool(structured_mst_session_id_from_env()),
            "value": structured_mst_session_id_from_env(),
        },
        "session_metadata:mst_session_id": {
            "present": False,
            "value": None,
        },
        "snapshot_path:mst_session_id": {
            "present": False,
            "value": None,
        },
        "snapshot_body:mst_session_id": {
            "present": False,
            "value": None,
        },
    }
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
    return {
        "status": "error",
        "code": resolved_code,
        "message": message or str(error or "") or f"{subject} requires canonical MST_SESSION_ID or structured mst_session_id",
        "created_new_session": False,
        "canonical_mst_session_id": None,
        "valid": False,
        "reason": reason_map.get(resolved_code, resolved_code),
        "action": action_map.get(resolved_code, "emit_diagnostic_no_mutation"),
        "source_precedence": canonical_session_source_precedence(),
        "observed_sources": observed_sources,
        "invocation_class": invocation_class,
        "legacy_diagnostics": diagnostics,
        "mutation_performed": False,
    }
class ContractValidationError(ValueError):
    def __init__(
        self,
        *,
        target: str,
        field: str,
        reason: str,
        code: str = "state_contract_validation_failed",
    ):
        super().__init__(f"validation failed: target={target} field={field} reason={reason}")
        self.target = target
        self.field = field
        self.reason = reason
        self.code = code
def validation_failure_payload(
    *,
    target: str,
    field: str,
    reason: str,
    code: str = "state_contract_validation_failed",
    message: str | None = None,
    **details,
) -> dict:
    payload = {
        "status": "validation_failed",
        "target": target,
        "field": field,
        "reason": reason,
        "code": code,
        "failure_class": "state_contract_validation",
        "message": message or reason,
        "created_new_session": False,
    }
    payload.update(details)
    return payload
def state_inconsistency_failure_payload(
    *,
    code: str,
    message: str,
    mst_session_id: str | None = None,
    root_mst_id: str | None = None,
    **details,
) -> dict:
    payload = {
        "status": "error",
        "code": code,
        "message": message,
        "failure_class": "state_inconsistency",
        "terminal_event": "terminal.state_inconsistency",
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
    }
    if mst_session_id:
        payload["mst_session_id"] = mst_session_id
    if root_mst_id:
        payload["root_mst_id"] = root_mst_id
    payload.update(details)
    return payload
def emit_validation_failure(
    *,
    target: str,
    field: str,
    reason: str,
    code: str = "state_contract_validation_failed",
    message: str | None = None,
    **details,
) -> int:
    payload = validation_failure_payload(
        target=target,
        field=field,
        reason=reason,
        code=code,
        message=message,
        **details,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"{payload['code']}: {payload['message']}", file=sys.stderr)
    return 1
def raise_validation_failure(
    *,
    target: str,
    field: str,
    reason: str,
    code: str = "state_contract_validation_failed",
) -> None:
    raise ContractValidationError(target=target, field=field, reason=reason, code=code)
def emit_session_identity_non_success(
    subject: str,
    message: str | None = None,
    *,
    code: str | None = None,
    error: object | None = None,
    invocation_class: str = "external_invocation",
) -> int:
    payload = session_identity_non_success_payload(
        subject,
        message,
        code=code,
        error=error,
        invocation_class=invocation_class,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 1
def is_session_identity_non_success_error(error: object) -> bool:
    return session_identity_non_success_code(error, legacy_session_diagnostics()) is not None
def is_missing_canonical_session_error(error: object) -> bool:
    text = str(error)
    return "missing MST_SESSION_ID" in text or "missing canonical MST_SESSION_ID" in text
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
PHASE2_READY_TASK_STATUSES = frozenset({"committed", "completed", "done", "accepted"})
def _phase2_incomplete_task(task) -> dict | None:
    if not isinstance(task, dict):
        return {"id": None, "status": None}
    task_id = task.get("id")
    task_status = task.get("status")
    status = str(task_status).strip().lower() if isinstance(task_status, str) else None
    if status in PHASE2_READY_TASK_STATUSES:
        return None
    return {
        "id": str(task_id).strip() if isinstance(task_id, str) and task_id.strip() else None,
        "status": status,
    }
def phase2_completion_state(request_data: dict) -> dict:
    phase, status = _phase_status_tuple(request_data)
    if phase != 2 or status.strip().lower() != "phase2_execution":
        return {
            "ready": False,
            "reason": "not_phase2_execution",
            "incomplete_tasks": [],
        }

    tasks = request_data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return {
            "ready": False,
            "reason": "missing_tasks",
            "incomplete_tasks": [],
        }

    incomplete_tasks = []
    for task in tasks:
        incomplete = _phase2_incomplete_task(task)
        if incomplete is not None:
            incomplete_tasks.append(incomplete)

    if incomplete_tasks:
        return {
            "ready": False,
            "reason": "incomplete_tasks",
            "incomplete_tasks": incomplete_tasks,
        }

    return {
        "ready": True,
        "reason": None,
        "incomplete_tasks": [],
    }
def all_phase2_tasks_ready(data: dict) -> bool:
    return phase2_completion_state(data).get("ready") is True
def _request_json_path(req_id: str) -> Path:
    return BASE_DIR / "requests" / req_id / "request.json"
def _plan_json_path(pln_id: str) -> Path:
    return BASE_DIR / "plans" / pln_id / "plan.json"
def _load_request(req_id: str):
    return load_json(_request_json_path(req_id))
def _normalize_request_id(req_id: object) -> str:
    text = str(req_id).strip().upper()
    if not text:
        raise ValueError("req_id is required")
    return text
def _normalize_task_num(task_num: object) -> str:
    text = str(task_num).strip()
    if not text:
        raise ValueError("task_num is required")
    match = re.search(r"(\d+)$", text)
    if match:
        return match.group(1).zfill(2)
    return text.upper()
def _task_matches_task_num(task: object, task_num: str) -> bool:
    if not isinstance(task, dict):
        return False
    candidates = []
    for key in ("task_num", "id"):
        value = task.get(key)
        if value is not None:
            candidates.append(value)
    for candidate in candidates:
        try:
            if _normalize_task_num(candidate) == task_num:
                return True
        except ValueError:
            continue
    return False
def record_phase2_dispatch_attempt(req_id: str, **kwargs) -> dict:
    normalized_req_id = _normalize_request_id(req_id)
    request_path = _request_json_path(normalized_req_id)
    request_data = load_json(request_path)
    if not isinstance(request_data, dict):
        raise FileNotFoundError(f"request.json not found or invalid for {normalized_req_id}")

    required_fields = (
        "task_num",
        "task_id",
        "attempt_id",
        "dispatched_at",
        "agent",
        "worktree_path",
        "log_path",
        "expected_task_status_before",
    )
    missing_fields = [field for field in required_fields if not str(kwargs.get(field) or "").strip()]
    if missing_fields:
        raise ValueError(f"missing required phase2 dispatch metadata fields: {', '.join(missing_fields)}")

    task_num = _normalize_task_num(kwargs["task_num"])
    attempt_id = str(kwargs["attempt_id"]).strip()

    background_attempts = request_data.get("background_task_ids")
    if background_attempts is None:
        background_attempts = []
    elif not isinstance(background_attempts, list):
        raise ValueError("request background_task_ids must be a list")

    for entry in background_attempts:
        if isinstance(entry, dict) and str(entry.get("attempt_id") or "").strip() == attempt_id:
            raise ValueError(
                f"duplicate phase2 dispatch attempt_id for {normalized_req_id}: {attempt_id}"
            )

    tasks = request_data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"request tasks missing or invalid for {normalized_req_id}")

    matching_task = None
    for task in tasks:
        task_attempts = task.get("attempts")
        if task_attempts is None:
            task_attempts = []
        elif not isinstance(task_attempts, list):
            task_label = str(task.get("id") or task.get("task_num") or "?").strip() or "?"
            raise ValueError(
                f"request task attempts must be a list for {normalized_req_id} task {task_label}"
            )

        for entry in task_attempts:
            if isinstance(entry, dict) and str(entry.get("attempt_id") or "").strip() == attempt_id:
                raise ValueError(
                    f"duplicate phase2 dispatch attempt_id for {normalized_req_id}: {attempt_id}"
                )

        if matching_task is None and _task_matches_task_num(task, task_num):
            matching_task = task
    if matching_task is None:
        raise ValueError(f"task_num {task_num} not found in request {normalized_req_id}")

    task_attempts = matching_task.get("attempts")
    if task_attempts is None:
        task_attempts = []
    elif not isinstance(task_attempts, list):
        raise ValueError(f"request task attempts must be a list for {normalized_req_id} task {task_num}")

    background_entry = {}
    for key, value in kwargs.items():
        if value is not None:
            background_entry[key] = value
    background_entry["task_num"] = task_num
    background_entry["status"] = str(kwargs.get("status") or "running").strip() or "running"

    task_attempt = {
        "attempt_id": attempt_id,
        "task_id": str(kwargs["task_id"]).strip(),
        "task_num": task_num,
        "dispatched_at": str(kwargs["dispatched_at"]).strip(),
        "agent": str(kwargs["agent"]).strip(),
        "worktree_path": str(kwargs["worktree_path"]).strip(),
        "log_path": str(kwargs["log_path"]).strip(),
        "expected_task_status_before": str(kwargs["expected_task_status_before"]).strip(),
        "status": background_entry["status"],
    }
    for optional_key in ("run_state_path",):
        optional_value = kwargs.get(optional_key)
        if optional_value is not None:
            task_attempt[optional_key] = optional_value

    background_attempts.append(background_entry)
    task_attempts.append(task_attempt)
    matching_task["attempts"] = task_attempts
    request_data["background_task_ids"] = background_attempts
    save_json(request_path, request_data)
    background_entry["reconcile_queue"] = upsert_reconcile_phase2_action(
        normalized_req_id,
        attempt=background_entry,
    )
    return background_entry
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
        session_id = require_mst_session_id_for_mutation("workflow state read")
        state_path = _workflow_state_file(_skill_state_base_dir())
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            return None
        if canonical_state_payload_error(payload, session_id) is not None:
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
def _is_workflow_queue_entry(entry: object) -> bool:
    return isinstance(entry, dict) and bool(str(entry.get("skill") or "").strip())
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
            if _is_workflow_queue_entry(value):
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
