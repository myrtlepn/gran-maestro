from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.mst_cmds.dod008_evidence import project_dod008_evidence


MAX_STACK_ITEMS = 20
ALLOWED_FRESHNESS_STATUS = (
    "fresh",
    "stale",
    "identity_mismatch",
    "no_history",
    "unknown",
)
ALLOWED_NEXT_ACTION_TYPE = (
    "continue_skill",
    "resume_workflow",
    "run_request",
    "approve_request",
    "accept_request",
    "resume_agile_sprint",
    "resolve_blocker",
    "wait_for_user",
    "no_action_available",
    "unknown",
)
ALLOWED_BLOCKER_TYPE = (
    "pending_dependency",
    "failed_validation",
    "missing_accept",
    "protected_branch",
    "stale_projection",
    "identity_mismatch",
    "policy_blocked",
    "missing_source",
    "schema_invalid",
    "unknown",
)
DEFAULT_EVIDENCE_PATH = ".gran-maestro/sessions/{mst_session_id}/history.head"


class _HashableDict(dict):
    __hash__ = object.__hash__


class _HashableList(list):
    __hash__ = object.__hash__


def _hashable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return _HashableDict((key, _hashable_json(child)) for key, child in value.items())
    if isinstance(value, list):
        return _HashableList(_hashable_json(child) for child in value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_context(fixture_or_context: Any) -> dict[str, Any]:
    if isinstance(fixture_or_context, dict):
        return fixture_or_context
    if isinstance(fixture_or_context, (str, Path)):
        try:
            payload = json.loads(Path(fixture_or_context).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _safe_mst_session_id(value: Any) -> str:
    text = _safe_text(value)
    if not text or "/" in text or ".." in text:
        return ""
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in text):
        return ""
    return text


def _identity(context: dict[str, Any]) -> dict[str, Any]:
    return context.get("identity") if isinstance(context.get("identity"), dict) else {}


def _identity_env(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    return identity.get("env") if isinstance(identity.get("env"), dict) else {}


def _identity_structured(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    return identity.get("context") if isinstance(identity.get("context"), dict) else {}


def _canonical_selector(context: dict[str, Any]) -> str:
    env_value = _safe_mst_session_id(_identity_env(context).get("MST_SESSION_ID"))
    structured_value = _safe_mst_session_id(_identity_structured(context).get("mst_session_id"))
    if env_value:
        return env_value
    if structured_value:
        return structured_value
    return _safe_mst_session_id(context.get("canonical_mst_session_id")) or _safe_mst_session_id(context.get("mst_session_id"))


def _identity_mismatch(context: dict[str, Any]) -> bool:
    env_value = _safe_mst_session_id(_identity_env(context).get("MST_SESSION_ID"))
    structured_value = _safe_mst_session_id(_identity_structured(context).get("mst_session_id"))
    return bool(env_value and structured_value and env_value != structured_value)


def _legacy_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(context)
    diagnostics = identity.get("legacy_diagnostics") if isinstance(identity.get("legacy_diagnostics"), dict) else {}
    result = dict(diagnostics)

    env = _identity_env(context)
    owner_pid = _safe_text(env.get("MST_STATE_PPID"))
    if owner_pid:
        result.setdefault("owner_pid", owner_pid)

    structured = _identity_structured(context)
    hook_session_id = _safe_text(structured.get("session_id"))
    if hook_session_id:
        result.setdefault("hook_session_id", hook_session_id)
    owner_session_id = _safe_text(structured.get("owner_session_id"))
    if owner_session_id:
        result.setdefault("owner_session_id", owner_session_id)
    transcript_path = _safe_text(structured.get("transcript_path"))
    if transcript_path:
        name = Path(transcript_path).name
        stem = name[:-6] if name.endswith(".jsonl") else Path(name).stem
        if stem:
            result.setdefault("hook_transcript_stem", stem)
    if _identity_mismatch(context):
        result.setdefault("identity_mismatch", "MST_SESSION_ID and structured mst_session_id differ")
    return result


def _evidence_path(value: Any, mst_session_id: str) -> str:
    text = _safe_text(value)
    if text.startswith(".gran-maestro/") and ".." not in text:
        return text
    return DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")


def _bounded_stack(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    raw_sources = context.get("task_sources")
    sources = [item for item in raw_sources if isinstance(item, dict)] if isinstance(raw_sources, list) else []
    items: list[dict[str, str]] = []
    for source in sources[:MAX_STACK_ITEMS]:
        items.append(
            {
                "kind": _safe_text(source.get("kind")) or "unknown",
                "id": _safe_text(source.get("id")) or "unknown",
                "title": _safe_text(source.get("title")) or "Untitled current work",
                "status": _safe_text(source.get("status")) or "unknown",
                "owner": _safe_text(source.get("owner")) or "unknown",
                "phase": _safe_text(source.get("phase")) or "unknown",
                "source": _safe_text(source.get("source")) or "unknown",
                "evidence_path": _evidence_path(source.get("evidence_path"), mst_session_id),
            }
        )
    return {
        "max_items": MAX_STACK_ITEMS,
        "truncated": len(sources) > MAX_STACK_ITEMS,
        "total": len(sources),
        "items": items,
    }


def _active_workflow(context: dict[str, Any], mst_session_id: str) -> dict[str, Any] | None:
    workflow = context.get("active_workflow")
    if not isinstance(workflow, dict):
        return None
    return {
        "skill": _safe_text(workflow.get("skill")) or "unknown",
        "source_id": _safe_text(workflow.get("source_id")) or "",
        "auto": bool(workflow.get("auto")),
        "status": _safe_text(workflow.get("status")) or "unknown",
        "evidence_path": _evidence_path(workflow.get("evidence_path"), mst_session_id),
    }


def _default_next_action(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    queue = context.get("resume_queue") if isinstance(context.get("resume_queue"), dict) else {}
    skill = _safe_text(queue.get("skill"))
    source_id = _safe_text(queue.get("source_id"))
    if skill:
        return {
            "action_type": "resume_workflow",
            "label": f"Resume {skill}",
            "target": source_id,
            "command_hint": f"/{skill} {_safe_text(queue.get('args'))}".strip(),
            "reason": "resume queue contains the next bounded action",
            "confidence": 0.7,
            "evidence_path": _evidence_path(queue.get("evidence_path"), mst_session_id),
        }
    return {
        "action_type": "no_action_available",
        "label": "No current-work action available",
        "target": "",
        "command_hint": "",
        "reason": "no next action source was present in bounded projection inputs",
        "confidence": 0.0,
        "evidence_path": DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown"),
    }


def _next_action(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    source = context.get("next_action_source")
    raw = source if isinstance(source, dict) else _default_next_action(context, mst_session_id)
    action_type = _safe_text(raw.get("action_type"))
    if action_type not in ALLOWED_NEXT_ACTION_TYPE:
        action_type = "unknown"
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = 0.0
    confidence = min(1.0, max(0.0, float(confidence)))
    return {
        "action_type": action_type,
        "allowed_action_type": list(ALLOWED_NEXT_ACTION_TYPE),
        "label": _safe_text(raw.get("label")) or "Unknown next action",
        "target": _safe_text(raw.get("target")),
        "command_hint": _safe_text(raw.get("command_hint")),
        "reason": _safe_text(raw.get("reason")) or "next action was derived from bounded current-work sources",
        "confidence": confidence,
        "evidence_path": _evidence_path(raw.get("evidence_path"), mst_session_id),
    }


def _history_head(value: Any) -> str | None:
    text = _safe_text(value)
    return text or None


def _freshness_status(context: dict[str, Any]) -> str:
    if context.get("schema_version") != 1:
        return "unknown"
    if _identity_mismatch(context):
        return "identity_mismatch"
    source_head = _history_head(context.get("source_history_head"))
    current_head = _history_head(context.get("current_history_head"))
    if source_head is None and current_head is None:
        return "no_history"
    if source_head is None or current_head is None:
        return "unknown"
    return "fresh" if source_head == current_head else "stale"


def _projection_freshness(context: dict[str, Any], mst_session_id: str, generated_at: str) -> dict[str, Any]:
    status = _freshness_status(context)
    dod008 = project_dod008_evidence(context, mst_session_id=mst_session_id, generated_at=context.get("generated_at"))
    dod008_freshness = dod008.get("projection_freshness") if isinstance(dod008.get("projection_freshness"), dict) else {}
    return {
        "status": status,
        "allowed_status": list(ALLOWED_FRESHNESS_STATUS),
        "source_history_head": _history_head(context.get("source_history_head")),
        "current_history_head": (
            _history_head(context.get("current_verified_head"))
            or _history_head(context.get("verified_history_head"))
            or _history_head(context.get("current_history_head"))
            or _history_head(dod008.get("verified_history_head"))
        ),
        "generated_at": generated_at,
        "code": _safe_text(dod008_freshness.get("code")) or status,
        "basis": _safe_text(dod008_freshness.get("basis")) or "history_head",
        "evidence_path": _evidence_path(dod008_freshness.get("evidence_path") or context.get("history_head_evidence_path"), mst_session_id),
    }


def _blocker(
    blocker_type: str,
    *,
    message: str,
    mst_session_id: str,
    evidence_path: Any = None,
    status: str = "blocked",
    recoverable: bool = True,
    next_action_type: str = "resolve_blocker",
) -> dict[str, Any]:
    if blocker_type not in ALLOWED_BLOCKER_TYPE:
        blocker_type = "unknown"
    if next_action_type not in ALLOWED_NEXT_ACTION_TYPE:
        next_action_type = "resolve_blocker"
    return {
        "blocker_type": blocker_type,
        "status": status,
        "message": message,
        "evidence_path": _evidence_path(evidence_path, mst_session_id),
        "recoverable": bool(recoverable),
        "next_action_type": next_action_type,
    }


def _source_blockers(context: dict[str, Any], mst_session_id: str) -> list[dict[str, Any]]:
    raw_sources = context.get("blocker_sources")
    sources = [item for item in raw_sources if isinstance(item, dict)] if isinstance(raw_sources, list) else []
    blockers: list[dict[str, Any]] = []
    for source in sources:
        blockers.append(
            _blocker(
                _safe_text(source.get("blocker_type")) or "unknown",
                message=_safe_text(source.get("message")) or "current-work blocker",
                mst_session_id=mst_session_id,
                evidence_path=source.get("evidence_path"),
                status=_safe_text(source.get("status")) or "blocked",
                recoverable=bool(source.get("recoverable")),
                next_action_type=_safe_text(source.get("next_action_type")) or "resolve_blocker",
            )
        )
    return blockers


def _automatic_blockers(
    context: dict[str, Any],
    *,
    mst_session_id: str,
    freshness_status: str,
    stack: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if context.get("schema_version") != 1:
        blockers.append(
            _blocker(
                "schema_invalid",
                message="current-work handoff source schema_version is missing or unsupported",
                mst_session_id=mst_session_id,
                evidence_path=context.get("schema_evidence_path"),
                recoverable=False,
                next_action_type="resolve_blocker",
            )
        )
    if freshness_status == "identity_mismatch":
        blockers.append(
            _blocker(
                "identity_mismatch",
                message="canonical MST_SESSION_ID and structured mst_session_id do not match",
                mst_session_id=mst_session_id,
                evidence_path=context.get("identity_evidence_path"),
                recoverable=True,
                next_action_type="resolve_blocker",
            )
        )
    if freshness_status == "stale":
        blockers.append(
            _blocker(
                "stale_projection",
                message="current history head differs from projection source_history_head",
                mst_session_id=mst_session_id,
                evidence_path=context.get("history_head_evidence_path"),
                recoverable=True,
                next_action_type="resolve_blocker",
            )
        )
    active_workflow_missing = not isinstance(context.get("active_workflow"), dict)
    if active_workflow_missing and int(stack.get("total") or 0) == 0:
        blockers.append(
            _blocker(
                "missing_source",
                message="current-work handoff has no active workflow or task source",
                mst_session_id=mst_session_id,
                evidence_path=context.get("source_evidence_path"),
                recoverable=True,
                next_action_type="resume_workflow",
            )
        )
    return blockers


def _unique_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for blocker in blockers:
        key = (
            str(blocker.get("blocker_type") or ""),
            str(blocker.get("message") or ""),
            str(blocker.get("evidence_path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(blocker)
    return result


def _evidence_paths(*sections: Any) -> list[str]:
    paths: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            evidence = value.get("evidence_path")
            if isinstance(evidence, str) and evidence.startswith(".gran-maestro/") and evidence not in paths:
                paths.append(evidence)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for section in sections:
        collect(section)
    return paths


def project_current_work_handoff(fixture_or_context: Any) -> dict[str, Any]:
    """Return a bounded, read-only current-work handoff projection.

    The canonical selector is MST_SESSION_ID or structured mst_session_id. Hook
    UUIDs, transcript stems, owner values, and legacy aliases are carried only
    as diagnostics and are never used as lookup, partition, recovery, or repair
    sources.
    """
    context = _load_context(fixture_or_context)
    mst_session_id = _canonical_selector(context)
    generated_at = _safe_text(context.get("generated_at")) or _utc_now()
    stack = _bounded_stack(context, mst_session_id)
    workflow = _active_workflow(context, mst_session_id)
    action = _next_action(context, mst_session_id)
    freshness = _projection_freshness(context, mst_session_id, generated_at)
    blockers = _unique_blockers(
        _source_blockers(context, mst_session_id)
        + _automatic_blockers(
            context,
            mst_session_id=mst_session_id,
            freshness_status=str(freshness["status"]),
            stack=stack,
        )
    )
    evidence_paths = _evidence_paths(workflow, stack, action, blockers, freshness)
    if not evidence_paths:
        evidence_paths = [DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")]

    return _hashable_json(
        {
            "schema_version": 1,
            "mst_session_id": mst_session_id,
            "canonical_mst_session_id": mst_session_id,
            "lookup_key": mst_session_id,
            "partition_key": mst_session_id,
            "recovery_selector": mst_session_id,
            "source_history_head": _history_head(context.get("source_history_head")),
            "generated_at": generated_at,
            "projection_freshness": freshness,
            "active_workflow": workflow,
            "current_task_stack": stack,
            "next_action": action,
            "blockers": blockers,
            "legacy_diagnostics": _legacy_diagnostics(context),
            "evidence_paths": evidence_paths,
        }
    )


def _cli_context(args: argparse.Namespace) -> dict[str, Any]:
    context = _load_context(getattr(args, "context", None)) if getattr(args, "context", None) else {}
    if not isinstance(context, dict):
        context = {}
    session_id = _safe_mst_session_id(getattr(args, "session_id", None))
    if session_id:
        context.setdefault("mst_session_id", session_id)
        context.setdefault("canonical_mst_session_id", session_id)
        identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
        env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
        env.setdefault("MST_SESSION_ID", session_id)
        structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
        structured.setdefault("mst_session_id", session_id)
        identity["env"] = env
        identity["context"] = structured
        context["identity"] = identity
    if getattr(args, "source_head", None):
        context.setdefault("source_history_head", _safe_text(args.source_head))
    if getattr(args, "current_head", None):
        context.setdefault("current_history_head", _safe_text(args.current_head))
    context.setdefault("schema_version", 1)
    return context


def cmd_current_work_handoff(args: argparse.Namespace) -> int:
    payload = project_current_work_handoff(_cli_context(args))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("current-work-handoff")
    parser.add_argument("--context", default=None, help="read bounded projection context JSON")
    parser.add_argument("--session-id", dest="session_id", default=None)
    parser.add_argument("--source-head", dest="source_head", default=None)
    parser.add_argument("--current-head", dest="current_head", default=None)
