from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.mst_cmds.dod008_evidence import project_dod008_evidence
from scripts.mst_cmds.native_delegation import lifecycle_is_terminal


MAX_STACK_ITEMS = 20
MAX_LIFECYCLE_ITEMS = 50
MAX_LIFECYCLE_ITEMS_HARD_LIMIT = 200
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
ALLOWED_COMPLETION_STATUS = (
    "completed",
    "failed",
    "empty_result",
    "blocked",
    "unknown",
)
ALLOWED_CONTINUATION_STATE = (
    "parent_continuation_ready",
    "recovery_ready",
    "already_consumed",
    "no_completion_evidence",
)
ALLOWED_LIFECYCLE_CONSUMER_STATUS = (
    "success",
    "non_success",
    "gap",
)


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


def _safe_idempotency_key(value: Any) -> str:
    text = _safe_text(value)
    if not text or "/" in text or ".." in text:
        return ""
    return text if all(31 < ord(char) < 127 for char in text) else ""


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


def _consumed_idempotency_keys(context: dict[str, Any]) -> set[str]:
    raw = context.get("consumed_idempotency_keys")
    keys = [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    return {key for key in (_safe_idempotency_key(item) for item in keys) if key}


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


def _completion_from_lifecycle(lifecycle_consumer: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(lifecycle_consumer, dict):
        return {}
    gaps = lifecycle_consumer.get("gaps")
    if lifecycle_consumer.get("consumer_status") == "gap" or (
        isinstance(gaps, list) and bool(gaps)
    ):
        linkage = lifecycle_consumer.get("attempt_linkage")
        linkage = linkage if isinstance(linkage, dict) else {}
        final_status = lifecycle_consumer.get("final_status")
        final_status = final_status if isinstance(final_status, dict) else {}
        return {
            "status": "unknown",
            "task_id": _safe_text(linkage.get("task_id"))
            or _safe_text(lifecycle_consumer.get("task_id")),
            "parent_mst_session_id": _safe_text(linkage.get("parent_session_id")),
            "completion_evidence_path": "",
            "next_action_idempotency_key": "",
            "completed_at": _safe_text(final_status.get("terminated_at")),
        }
    status = _safe_text(lifecycle_consumer.get("lifecycle_status"))
    if status in {"completed", "fallback_completed"}:
        completion_status = "completed"
    elif status in {
        "failed",
        "missing_result",
        "unchanged_result",
        "preexisting_result",
        "missing_output_baseline",
    }:
        completion_status = "failed"
    elif status == "empty_result":
        completion_status = "empty_result"
    elif status in {"blocked", "orphaned", "reconciling", "cancel_requested", "cancelled"}:
        completion_status = "blocked"
    else:
        return {}
    linkage = lifecycle_consumer.get("attempt_linkage")
    linkage = linkage if isinstance(linkage, dict) else {}
    artifacts = lifecycle_consumer.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    output = artifacts.get("output") if isinstance(artifacts.get("output"), dict) else {}
    trace = artifacts.get("trace") if isinstance(artifacts.get("trace"), dict) else {}
    final_status = lifecycle_consumer.get("final_status")
    final_status = final_status if isinstance(final_status, dict) else {}
    attempt_id = _safe_text(linkage.get("attempt_id"))
    return {
        "status": completion_status,
        "task_id": _safe_text(linkage.get("task_id")) or _safe_text(lifecycle_consumer.get("task_id")),
        "parent_mst_session_id": _safe_text(linkage.get("parent_session_id")),
        "completion_evidence_path": _safe_text(output.get("path")) or _safe_text(trace.get("path")),
        "next_action_idempotency_key": f"delegation-{attempt_id}-continuation" if attempt_id else "",
        "completed_at": _safe_text(final_status.get("terminated_at")),
    }


def _dispatch_completion(
    context: dict[str, Any],
    mst_session_id: str,
    next_action: dict[str, Any],
    lifecycle_consumer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lifecycle_gaps = (
        lifecycle_consumer.get("gaps")
        if isinstance(lifecycle_consumer, dict)
        and isinstance(lifecycle_consumer.get("gaps"), list)
        else []
    )
    lifecycle_invalid = bool(
        isinstance(lifecycle_consumer, dict)
        and (
            lifecycle_consumer.get("consumer_status") == "gap"
            or lifecycle_gaps
        )
    )
    raw: dict[str, Any] = {}
    if not lifecycle_invalid and isinstance(context.get("dispatch_completion"), dict):
        raw = context["dispatch_completion"]
    if not raw or lifecycle_invalid:
        raw = _completion_from_lifecycle(lifecycle_consumer)
    completion_status = _safe_text(raw.get("status"))
    if completion_status not in ALLOWED_COMPLETION_STATUS:
        completion_status = "unknown"
    parent_session_id = _safe_mst_session_id(raw.get("parent_mst_session_id")) or mst_session_id
    task_id = _safe_text(raw.get("task_id"))
    completion_evidence_path = _evidence_path(raw.get("completion_evidence_path"), mst_session_id)
    action_idempotency_key = (
        _safe_idempotency_key(raw.get("next_action_idempotency_key"))
        or _safe_idempotency_key(next_action.get("idempotency_key"))
    )
    consumed_keys = _consumed_idempotency_keys(context)
    already_consumed = bool(action_idempotency_key and action_idempotency_key in consumed_keys)

    continuation_state = "no_completion_evidence"
    status_code = "completion_evidence_missing"
    result_class = "pending"
    if already_consumed:
        continuation_state = "already_consumed"
        status_code = "continuation_already_consumed"
        result_class = "duplicate"
    elif completion_status == "completed":
        continuation_state = "parent_continuation_ready"
        status_code = "dispatch_completed"
        result_class = "success"
    elif completion_status == "failed":
        continuation_state = "recovery_ready"
        status_code = "dispatch_failed"
        result_class = "non_success"
    elif completion_status == "empty_result":
        continuation_state = "recovery_ready"
        status_code = "dispatch_empty_result"
        result_class = "non_success"
    elif completion_status == "blocked":
        continuation_state = "recovery_ready"
        status_code = "dispatch_blocked"
        result_class = "non_success"
    elif raw:
        status_code = "dispatch_unknown"
        result_class = "non_success"

    return {
        "parent_mst_session_id": parent_session_id,
        "task_id": task_id,
        "completion_status": completion_status,
        "allowed_completion_status": list(ALLOWED_COMPLETION_STATUS),
        "continuation_state": continuation_state,
        "allowed_continuation_state": list(ALLOWED_CONTINUATION_STATE),
        "status_code": status_code,
        "result_class": result_class,
        "completion_evidence_path": completion_evidence_path,
        "evidence_path": completion_evidence_path,
        "next_action_idempotency_key": action_idempotency_key,
        "consumption_status": "already_consumed" if already_consumed else "ready",
        "consumable": continuation_state in {"parent_continuation_ready", "recovery_ready"},
        "duplicate_prevented": already_consumed,
        "completed_at": _safe_text(raw.get("completed_at")),
    }


def _continuation_projection(next_action: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    state = _safe_text(handoff.get("continuation_state"))
    action = dict(next_action) if state in {"parent_continuation_ready", "recovery_ready"} else None
    return {
        "state": state or "no_completion_evidence",
        "queued_action": action,
        "idempotency_key": _safe_idempotency_key(handoff.get("next_action_idempotency_key")),
        "completion_evidence_path": _safe_text(handoff.get("completion_evidence_path")),
        "evidence_path": _safe_text(handoff.get("completion_evidence_path")),
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


def _load_lifecycle_artifact_payload(fixture_or_context: Any) -> dict[str, Any]:
    if isinstance(fixture_or_context, dict):
        for key in (
            "dispatch_lifecycle_artifact",
            "lifecycle_artifact",
            "dispatch_artifact",
        ):
            candidate = fixture_or_context.get(key)
            if isinstance(candidate, dict):
                return dict(candidate)
        for key in (
            "dispatch_lifecycle_artifact_path",
            "lifecycle_artifact_path",
            "dispatch_artifact_path",
            "run_state_path",
        ):
            candidate = fixture_or_context.get(key)
            if isinstance(candidate, (str, Path)):
                return _load_context(candidate)
        if any(key in fixture_or_context for key in ("task_id", "attempt_id", "attempts", "running_log_path", "trace_path")):
            return dict(fixture_or_context)
        return {}
    if isinstance(fixture_or_context, (str, Path)):
        return _load_context(fixture_or_context)
    return {}


def _artifact_path_projection(path_value: Any) -> dict[str, Any]:
    path_text = _safe_text(path_value)
    exists = False
    if path_text:
        try:
            exists = Path(path_text).is_file()
        except OSError:
            exists = False
    return {
        "path": path_text,
        "exists": exists,
    }


def _gap(code: str, *, field: str, message: str, path: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "field": field,
        "message": message,
        "path": _safe_text(path),
    }


def _append_missing_text_gap(gaps: list[dict[str, Any]], payload: dict[str, Any], field: str) -> None:
    if _safe_text(payload.get(field)):
        return
    gaps.append(
        _gap(
            "missing_required_field",
            field=field,
            message=f"lifecycle artifact field '{field}' is required",
        )
    )


def _append_missing_path_gap(
    gaps: list[dict[str, Any]],
    payload: dict[str, Any],
    field: str,
    *,
    required: bool,
    verify_exists: bool = True,
) -> dict[str, Any]:
    projection = _artifact_path_projection(payload.get(field))
    if not projection["path"]:
        if required:
            gaps.append(
                _gap(
                    "missing_required_field",
                    field=field,
                    message=f"lifecycle artifact field '{field}' is required",
                )
            )
        return projection
    if verify_exists and projection["exists"] is not True:
        gaps.append(
            _gap(
                "missing_referenced_file",
                field=field,
                message=f"referenced lifecycle artifact file is missing for '{field}'",
                path=projection["path"],
            )
        )
    return projection


def _attempt_summary(attempt: dict[str, Any], current_attempt_id: str) -> dict[str, Any]:
    attempt_id = _safe_text(attempt.get("attempt_id"))
    return {
        "attempt_id": attempt_id,
        "status": _safe_text(attempt.get("status")) or "unknown",
        "phase": _safe_text(attempt.get("phase")) or "unknown",
        "provider": _safe_text(attempt.get("provider")) or None,
        "provider_task_id": _safe_text(attempt.get("provider_task_id")) or None,
        "execution_transport": _safe_text(attempt.get("execution_transport")) or None,
        "completion_signal": _safe_text(attempt.get("completion_signal")) or None,
        "exit_code": attempt.get("exit_code"),
        "provider_reconciliation_required": bool(
            attempt.get("provider_reconciliation_required")
        ),
        "reconciliation_action": (
            dict(attempt["reconciliation_action"])
            if isinstance(attempt.get("reconciliation_action"), dict)
            else None
        ),
        "fallback_from": _safe_text(attempt.get("fallback_from")) or None,
        "fallback_to": _safe_text(attempt.get("fallback_to")) or None,
        "running_log_path": _safe_text(attempt.get("running_log_path")) or None,
        "trace_path": _safe_text(attempt.get("trace_path")) or None,
        "output_path": _safe_text(attempt.get("output_path")) or None,
        "is_current": bool(attempt_id and attempt_id == current_attempt_id),
    }


def project_lifecycle_artifact_consumer_summary(fixture_or_context: Any) -> dict[str, Any]:
    payload = _load_lifecycle_artifact_payload(fixture_or_context)
    attempts = payload.get("attempts") if isinstance(payload.get("attempts"), list) else []
    current_attempt_id = _safe_text(payload.get("attempt_id"))
    current_attempt_payload = {}
    for attempt in attempts:
        if isinstance(attempt, dict) and _safe_text(attempt.get("attempt_id")) == current_attempt_id:
            current_attempt_payload = dict(attempt)
            break
    if not current_attempt_payload and attempts and isinstance(attempts[-1], dict):
        current_attempt_payload = dict(attempts[-1])
    lifecycle_status = _safe_text(payload.get("status")) or "unknown"
    native_evidence_failures = {
        "missing_result",
        "unchanged_result",
        "preexisting_result",
        "missing_output_baseline",
    }
    final_statuses = {
        "completed",
        "failed",
        "empty_result",
        "blocked",
        "fallback_completed",
        "cancelled",
        *native_evidence_failures,
    }

    gaps: list[dict[str, Any]] = []
    for field in ("task_id", "attempt_id", "parent_session_id", "mst_session_id", "root_mst_id", "status", "started_at", "last_heartbeat"):
        _append_missing_text_gap(gaps, payload, field)
    if lifecycle_status in final_statuses:
        _append_missing_text_gap(gaps, payload, "terminated_at")
    if not attempts:
        gaps.append(
            _gap(
                "missing_required_field",
                field="attempts",
                message="lifecycle artifact attempts list is required",
            )
        )

    is_native = _safe_text(payload.get("execution_transport")).lower() == "native"
    output_required = lifecycle_status in {"completed", "fallback_completed", "empty_result"}
    raw_stderr_evidence = (
        payload.get("stderr_evidence")
        if isinstance(payload.get("stderr_evidence"), dict)
        else {}
    )
    stderr_evidence = {
        "sha256": _safe_text(raw_stderr_evidence.get("sha256")) or None,
        "byte_count": raw_stderr_evidence.get("byte_count"),
        "truncated": bool(raw_stderr_evidence.get("truncated")),
        "redacted_tail": _safe_text(raw_stderr_evidence.get("redacted_tail")),
    }
    central_external_stderr = bool(
        not is_native
        and payload.get("external_claim_id")
        and stderr_evidence["sha256"]
        and isinstance(stderr_evidence["byte_count"], int)
        and int(stderr_evidence["byte_count"]) >= 0
    )
    artifacts = {
        "running_log": _append_missing_path_gap(gaps, payload, "running_log_path", required=True),
        "stdout_log": _append_missing_path_gap(gaps, payload, "stdout_log_path", required=False),
        "stderr_log": _append_missing_path_gap(
            gaps,
            payload,
            "stderr_log_path",
            required=(
                lifecycle_status == "failed"
                and not is_native
                and not central_external_stderr
            ),
        ),
        "stderr_evidence": stderr_evidence if central_external_stderr else None,
        "trace": _append_missing_path_gap(gaps, payload, "trace_path", required=True),
        "output": _append_missing_path_gap(
            gaps,
            payload,
            "output_path",
            required=output_required,
            verify_exists=output_required,
        ),
    }

    context_files = payload.get("context_files_read") if isinstance(payload.get("context_files_read"), list) else []
    normalized_context_files: list[dict[str, Any]] = []
    for index, entry in enumerate(context_files):
        if not isinstance(entry, dict):
            continue
        normalized = {
            "path": _safe_text(entry.get("path")),
            "exists": bool(entry.get("exists")),
            "hash": _safe_text(entry.get("hash")) or None,
            "version": _safe_text(entry.get("version")) or None,
        }
        normalized_context_files.append(normalized)
        if normalized["path"] and normalized["exists"] is not True:
            gaps.append(
                _gap(
                    "missing_referenced_file",
                    field=f"context_files_read[{index}].path",
                    message="context file referenced by lifecycle artifact is missing",
                    path=normalized["path"],
                )
            )

    current_attempt_summary = _attempt_summary(current_attempt_payload, current_attempt_id)
    attempts_summary = [
        _attempt_summary(attempt, current_attempt_id)
        for attempt in attempts
        if isinstance(attempt, dict)
    ]
    terminal = _lifecycle_is_terminal(payload)
    reconciliation_action = (
        payload.get("reconciliation_action")
        if isinstance(payload.get("reconciliation_action"), dict)
        else None
    )
    if terminal:
        if payload.get("provider_reconciliation_required") is True:
            gaps.append(
                _gap(
                    "terminal_reconciliation_required",
                    field="provider_reconciliation_required",
                    message="terminal lifecycle state cannot require provider reconciliation",
                )
            )
        if reconciliation_action and (
            _safe_text(reconciliation_action.get("status")).lower() == "pending"
            or reconciliation_action.get("completion_accepted") is False
        ):
            gaps.append(
                _gap(
                    "terminal_pending_reconciliation",
                    field="reconciliation_action",
                    message="terminal lifecycle state cannot retain an actionable reconciliation",
                )
            )
        elif reconciliation_action:
            action_status = _safe_text(reconciliation_action.get("status")).lower()
            result = (
                reconciliation_action.get("result")
                if isinstance(reconciliation_action.get("result"), dict)
                else None
            )
            required_result_fields = (
                "provider_state",
                "completion_signal",
                "phase",
                "status",
                "observed_at",
                "evidence_source",
            )
            if (
                action_status not in {"resolved", "completed"}
                or reconciliation_action.get("completion_accepted") is not True
                or not _safe_text(reconciliation_action.get("resolved_at"))
                or result is None
                or any(not _safe_text(result.get(field)) for field in required_result_fields)
            ):
                gaps.append(
                    _gap(
                        "terminal_reconciliation_resolution_incomplete",
                        field="reconciliation_action",
                        message="terminal reconciliation evidence must be resolved and complete",
                    )
                )
    failure = None
    if lifecycle_status in {
        "failed",
        "empty_result",
        "blocked",
        "orphaned",
        "reconciling",
        "cancel_requested",
        "cancelled",
        *native_evidence_failures,
    }:
        evidence_paths = [
            artifacts["output"]["path"],
            artifacts["stderr_log"]["path"],
            artifacts["running_log"]["path"] if central_external_stderr else None,
            artifacts["trace"]["path"],
        ]
        failure = {
            "status": lifecycle_status,
            "exit_code": payload.get("exit_code"),
            "structured_error": payload.get("structured_error") if isinstance(payload.get("structured_error"), dict) else None,
            "evidence_paths": [path for path in evidence_paths if path],
        }

    if gaps:
        consumer_status = "gap"
    elif lifecycle_status in {"completed", "fallback_completed"}:
        consumer_status = "success"
    elif lifecycle_status in {
        "failed",
        "empty_result",
        "blocked",
        "orphaned",
        "reconciling",
        "cancel_requested",
        "cancelled",
        *native_evidence_failures,
    }:
        consumer_status = "non_success"
    else:
        consumer_status = "gap"

    return _hashable_json(
        {
            "consumer_status": consumer_status,
            "allowed_consumer_status": list(ALLOWED_LIFECYCLE_CONSUMER_STATUS),
            "task_id": _safe_text(payload.get("task_id")),
            "lifecycle_status": lifecycle_status,
            "provider": _safe_text(payload.get("provider")) or None,
            "host": _safe_text(payload.get("host")) or None,
            "provider_task_id": _safe_text(payload.get("provider_task_id")) or None,
            "execution_transport": _safe_text(payload.get("execution_transport")) or None,
            "completion_signal": _safe_text(payload.get("completion_signal")) or None,
            "exit_code": payload.get("exit_code"),
            "reconciliation_action": (
                dict(payload["reconciliation_action"])
                if isinstance(payload.get("reconciliation_action"), dict)
                else None
            ),
            "provider_reconciliation_required": bool(
                payload.get("provider_reconciliation_required")
            ),
            "fallback_from": _safe_text(payload.get("fallback_from")) or None,
            "fallback_to": _safe_text(payload.get("fallback_to")) or None,
            "running_log_path": _safe_text(payload.get("running_log_path")) or None,
            "trace_path": _safe_text(payload.get("trace_path")) or None,
            "output_path": _safe_text(payload.get("output_path")) or None,
            "attempt_linkage": {
                "task_id": _safe_text(payload.get("task_id")),
                "attempt_id": current_attempt_id,
                "parent_session_id": _safe_text(payload.get("parent_session_id")),
                "mst_session_id": _safe_text(payload.get("mst_session_id")),
                "root_mst_id": _safe_text(payload.get("root_mst_id")),
            },
            "current_attempt": current_attempt_summary,
            "attempts": attempts_summary,
            "artifacts": artifacts,
            "final_status": {
                "status": lifecycle_status,
                "phase": _safe_text(payload.get("phase")) or "unknown",
                "started_at": _safe_text(payload.get("started_at")),
                "last_heartbeat": _safe_text(payload.get("last_heartbeat")),
                "terminated_at": _safe_text(payload.get("terminated_at")),
                "exit_code": payload.get("exit_code"),
            },
            "failure": failure,
            "context_files_read": normalized_context_files,
            "gaps": gaps,
        }
    )


def _lifecycle_timestamp(payload: dict[str, Any]) -> str:
    for field in ("updated_at", "observed_at", "terminated_at", "last_heartbeat", "started_at"):
        value = _safe_text(payload.get(field))
        if value:
            return value
    return ""


def _lifecycle_is_terminal(payload: dict[str, Any]) -> bool:
    return lifecycle_is_terminal(payload)


def _native_history_payloads(base_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    path = base_dir / "history" / "native-delegation.ndjson"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        event = row.get("event") if isinstance(row.get("event"), dict) else row
        if isinstance(event, dict):
            payloads.append((path, dict(event)))
    return payloads


def project_lifecycle_artifacts_for_session(
    base_dir: Path | str,
    mst_session_id: str,
    *,
    include_terminal: bool = True,
    terminal_only: bool = False,
    limit: int = MAX_LIFECYCLE_ITEMS,
) -> list[dict[str, Any]]:
    """Project bounded lifecycle evidence selected only by canonical session ID.

    Current run-state files take precedence over the append-only native history
    mirror because they retain the complete attempts/reconciliation payload.
    History remains the read-only fallback after terminal run-state cleanup.
    """
    canonical_session_id = _safe_mst_session_id(mst_session_id)
    if not canonical_session_id:
        return []
    root = Path(base_dir).resolve(strict=False)
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    for source_path, payload in _native_history_payloads(root):
        if _safe_mst_session_id(payload.get("mst_session_id")) != canonical_session_id:
            continue
        task_id = _safe_text(payload.get("task_id"))
        if not task_id:
            continue
        previous = selected.get(task_id)
        if previous is None or _lifecycle_timestamp(payload) >= _lifecycle_timestamp(previous[1]):
            selected[task_id] = (source_path, payload)

    run_dir = root / "run"
    if run_dir.is_dir():
        for path in sorted(run_dir.glob("*.json")):
            payload = _load_context(path)
            if _safe_mst_session_id(payload.get("mst_session_id")) != canonical_session_id:
                continue
            task_id = _safe_text(payload.get("task_id")) or path.stem
            if task_id:
                selected[task_id] = (path, payload)

    bounded_limit = max(1, min(int(limit), MAX_LIFECYCLE_ITEMS_HARD_LIMIT))
    candidates: list[tuple[str, dict[str, Any]]] = []
    for source_path, payload in selected.values():
        terminal = _lifecycle_is_terminal(payload)
        if terminal_only and not terminal:
            continue
        if not include_terminal and terminal:
            continue
        summary = dict(project_lifecycle_artifact_consumer_summary(payload))
        summary["source_path"] = str(source_path)
        summary["terminal"] = terminal
        candidates.append((_lifecycle_timestamp(payload), summary))
    candidates.sort(key=lambda item: (item[0], str(item[1].get("task_id") or "")), reverse=True)
    return [_hashable_json(summary) for _, summary in candidates[:bounded_limit]]


def resolve_continuation_guard(fixture_or_context: Any, *, hook_event: str) -> dict[str, Any]:
    hook_name = "Stop" if hook_event == "Stop" else "SessionStart"
    hook_source = "hooks/mst-stop-hook.sh" if hook_name == "Stop" else "hooks/mst-session-init.sh"
    handoff = project_current_work_handoff(fixture_or_context)
    continuation = handoff.get("continuation_handoff") if isinstance(handoff.get("continuation_handoff"), dict) else {}
    state = _safe_text(continuation.get("continuation_state"))
    action = handoff.get("continue") if isinstance(handoff.get("continue"), dict) else {}
    queued_action = action.get("queued_action") if isinstance(action.get("queued_action"), dict) else None
    decision = state or "no_completion_evidence"
    return _hashable_json(
        {
            "hook_event": hook_name,
            "hook_source": hook_source,
            "decision": decision,
            "execution_allowed": state in {"parent_continuation_ready", "recovery_ready"},
            "duplicate_prevented": continuation.get("duplicate_prevented") is True,
            "consumed_idempotency_key": _safe_idempotency_key(continuation.get("next_action_idempotency_key")),
            "next_action": queued_action,
            "completion_evidence_path": _safe_text(continuation.get("completion_evidence_path")),
            "parent_mst_session_id": _safe_mst_session_id(continuation.get("parent_mst_session_id")),
        }
    )


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
    existing_consumer = context.get("lifecycle_artifact_consumer")
    if isinstance(existing_consumer, dict):
        lifecycle_consumer = dict(existing_consumer)
    elif _load_lifecycle_artifact_payload(context):
        lifecycle_consumer = project_lifecycle_artifact_consumer_summary(context)
    else:
        lifecycle_consumer = None
    handoff = _dispatch_completion(context, mst_session_id, action, lifecycle_consumer)
    continuation = _continuation_projection(action, handoff)
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
    evidence_paths = _evidence_paths(workflow, stack, action, blockers, freshness, handoff, continuation, lifecycle_consumer)
    if not evidence_paths:
        evidence_paths = [DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")]

    payload = {
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
        "continuation_handoff": handoff,
        "continue": continuation,
        "blockers": blockers,
        "legacy_diagnostics": _legacy_diagnostics(context),
        "evidence_paths": evidence_paths,
    }
    if lifecycle_consumer is not None:
        payload["lifecycle_artifact_consumer"] = lifecycle_consumer
    return _hashable_json(payload)


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
    if session_id and not isinstance(context.get("lifecycle_artifact_consumer"), dict):
        from scripts.mst_cmds import _common

        base_dir = _common.BASE_DIR
        if isinstance(base_dir, Path):
            lifecycle = project_lifecycle_artifacts_for_session(base_dir, session_id, limit=1)
            if lifecycle:
                context["lifecycle_artifact_consumer"] = lifecycle[0]
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
