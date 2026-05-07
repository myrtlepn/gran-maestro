from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import _skill_state
from scripts.mst_cmds import current_work_handoff
from scripts.mst_cmds import execution_flow
from scripts.mst_cmds import prompt_correlation
from scripts.mst_cmds import state
from scripts.mst_cmds import writer_coverage


SCHEMA_VERSION = 1
DEFAULT_EVIDENCE_PATH = ".gran-maestro/state-machine-health/evidence.json"
HASH_LENGTH = 64

AXES = (
    "transition_order",
    "step_bounds",
    "stack_linkage",
    "guard_evidence",
    "history_linkage",
    "projection_freshness",
    "writer_coverage",
    "identity_boundary",
    "current_work_handoff",
    "prompt_correlation",
    "ki001_sprint_close_targeting",
)

SOURCE_SURFACES = {
    "execution_flow": "scripts/mst_cmds/execution_flow.py",
    "state": "scripts/mst_cmds/state.py",
    "skill_state": "scripts/_skill_state.py",
    "current_work_handoff": "scripts/mst_cmds/current_work_handoff.py",
    "writer_coverage": "scripts/mst_cmds/writer_coverage.py",
    "prompt_correlation": "scripts/mst_cmds/prompt_correlation.py",
}

PAC_BY_AXIS = {
    "transition_order": "PAC-2",
    "step_bounds": "PAC-3",
    "stack_linkage": "PAC-4",
    "guard_evidence": "PAC-5",
    "history_linkage": "PAC-6",
    "projection_freshness": "PAC-7",
    "writer_coverage": "PAC-8",
    "identity_boundary": "PAC-9",
    "current_work_handoff": "PAC-10",
    "prompt_correlation": "PAC-11",
    "ki001_sprint_close_targeting": "PAC-12",
}


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


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _safe_session_id(value: Any) -> str:
    text = _text(value)
    if not text or "/" in text or ".." in text:
        return ""
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    return text if all(char in allowed for char in text) else ""


def _hash(value: Any) -> str:
    text = _text(value)
    return text if len(text) == HASH_LENGTH else ""


def _evidence_path(value: Any, mst_session_id: str = "") -> str:
    text = _text(value)
    if text.startswith(".gran-maestro/") and ".." not in text:
        return text
    if mst_session_id:
        return f".gran-maestro/sessions/{mst_session_id}/state-machine-health.json"
    return DEFAULT_EVIDENCE_PATH


def _canonical_selector(context: dict[str, Any]) -> str:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
    return (
        _safe_session_id(env.get("MST_SESSION_ID"))
        or _safe_session_id(structured.get("mst_session_id"))
        or _safe_session_id(context.get("canonical_mst_session_id"))
        or _safe_session_id(context.get("mst_session_id"))
    )


def _identity_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    diagnostics = identity.get("legacy_diagnostics") if isinstance(identity.get("legacy_diagnostics"), dict) else {}
    result = dict(diagnostics)
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}

    for source_key, target_key in (
        ("MST_STATE_PPID", "owner_pid"),
        ("MST_SNAPSHOT_SESSION_ID", "snapshot_session_id"),
    ):
        value = _text(env.get(source_key))
        if value:
            result.setdefault(target_key, value)
    for source_key, target_key in (
        ("session_id", "hook_session_id"),
        ("owner_session_id", "owner_session_id"),
        ("owner_pid", "owner_pid"),
        ("owner_ppid", "owner_ppid"),
    ):
        value = _text(structured.get(source_key))
        if value:
            result.setdefault(target_key, value)
    transcript_path = _text(structured.get("transcript_path") or context.get("transcript_path"))
    if transcript_path:
        name = Path(transcript_path).name
        stem = name[:-6] if name.endswith(".jsonl") else Path(name).stem
        if stem:
            result.setdefault("hook_transcript_stem", stem)
    return result


def _axis(
    axis: str,
    status: str,
    code: str,
    reason: str,
    *,
    evidence_path: Any = None,
    event_hash: Any = None,
    mst_session_id: str = "",
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "axis": axis,
        "status": status,
        "code": code,
        "reason": reason,
    }
    bounded_hash = _hash(event_hash)
    if bounded_hash:
        payload["event_hash"] = bounded_hash
    else:
        payload["evidence_path"] = _evidence_path(evidence_path, mst_session_id)
    for key, value in details.items():
        if value is not None:
            payload[key] = value
    return payload


def _event_type(event: dict[str, Any]) -> str:
    return _text(event.get("event_type") or event.get("type"))


def _event_evidence(event: dict[str, Any]) -> tuple[Any, Any]:
    return event.get("evidence_path"), event.get("event_hash")


def _validate_transition_order(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    events = [item for item in context.get("events", []) if isinstance(item, dict)]
    if not events:
        return _axis(
            "transition_order",
            "unknown",
            "transition_events_missing",
            "skill lifecycle events were not present in bounded input",
            mst_session_id=mst_session_id,
        )

    closed_frames: set[str] = set()
    terminal_seen = False
    terminal_resume = False
    for event in events:
        event_type = _event_type(event)
        frame = _text(event.get("stack_frame_id")) or _text(event.get("frame_id")) or _text(event.get("skill"))
        if event_type.startswith("terminal."):
            terminal_seen = True
            if event.get("safe_to_resume") is True:
                terminal_resume = True
        elif terminal_seen and event_type.startswith("continue."):
            terminal_resume = True
        if event_type in {"skill.exit", "skill.recover"} and frame:
            closed_frames.add(frame)
        elif event_type == "skill.step" and frame in closed_frames:
            evidence_path, event_hash = _event_evidence(event)
            return _axis(
                "transition_order",
                "fail",
                "transition_step_after_exit",
                "skill.step followed exit or recover for the same stack frame",
                evidence_path=evidence_path,
                event_hash=event_hash,
                mst_session_id=mst_session_id,
            )

    handoff = context.get("current_work_handoff") if isinstance(context.get("current_work_handoff"), dict) else {}
    next_action = handoff.get("next_action") if isinstance(handoff.get("next_action"), dict) else {}
    if handoff.get("safe_to_resume") is True:
        terminal_resume = True
    if terminal_resume or _text(next_action.get("action_type")) in {"continue_skill", "resume_workflow"} and terminal_seen:
        return _axis(
            "transition_order",
            "fail",
            "terminal_resume_safe_continuation",
            "terminal flow exposed resume-safe continuation",
            evidence_path=handoff.get("evidence_path"),
            mst_session_id=mst_session_id,
        )

    return _axis(
        "transition_order",
        "pass",
        "transition_order_valid",
        "skill lifecycle events follow the allowed bounded order",
        evidence_path=events[-1].get("evidence_path"),
        event_hash=events[-1].get("event_hash"),
        mst_session_id=mst_session_id,
    )


def _workflow_value(snapshot: dict[str, Any], canonical_key: str, legacy_key: str) -> Any:
    workflow = snapshot.get("workflow") if isinstance(snapshot.get("workflow"), dict) else {}
    if canonical_key in workflow:
        return workflow.get(canonical_key)
    return snapshot.get(legacy_key)


def _validate_step_bounds(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    snapshot = context.get("snapshot") if isinstance(context.get("snapshot"), dict) else {}
    current_step = _workflow_value(snapshot, "current_step", "currentStep")
    total_steps = _workflow_value(snapshot, "total_steps", "totalSteps")
    evidence_path = snapshot.get("evidence_path")

    if not isinstance(current_step, int) or isinstance(current_step, bool):
        return _axis(
            "step_bounds",
            "unknown",
            "step_current_missing",
            "current_step was not available as an integer",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if not isinstance(total_steps, int) or isinstance(total_steps, bool):
        return _axis(
            "step_bounds",
            "unknown",
            "step_total_missing",
            "total_steps was not available as an integer",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if current_step < 0:
        return _axis(
            "step_bounds",
            "fail",
            "step_negative",
            "current_step is below zero",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if current_step > total_steps:
        return _axis(
            "step_bounds",
            "fail",
            "step_exceeds_total",
            "current_step exceeds total_steps",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    return _axis(
        "step_bounds",
        "pass",
        "step_bounds_valid",
        "current_step is within total_steps",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
    )


def _return_to(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("returnTo")
    if isinstance(value, dict):
        return value
    continuation = snapshot.get("continuation") if isinstance(snapshot.get("continuation"), dict) else {}
    value = continuation.get("return_to")
    return value if isinstance(value, dict) else {}


def _frame_matches(frame: dict[str, Any], return_to: dict[str, Any]) -> bool:
    if _text(frame.get("skill")) != _text(return_to.get("skill")):
        return False
    if "step" not in return_to:
        return True
    return frame.get("step") == return_to.get("step")


def _validate_stack_linkage(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    snapshot = context.get("snapshot") if isinstance(context.get("snapshot"), dict) else {}
    evidence_path = snapshot.get("evidence_path")
    if not snapshot:
        return _axis(
            "stack_linkage",
            "unknown",
            "stack_snapshot_missing",
            "state snapshot was not present",
            mst_session_id=mst_session_id,
        )

    state_contract = state._state_snapshot_contract_failure(snapshot, mst_session_id) if mst_session_id else None
    if snapshot.get("schema_version") != 1 or "mst_session_id" not in snapshot or "workflow" not in snapshot:
        return _axis(
            "stack_linkage",
            "unknown",
            "legacy_snapshot_only",
            "legacy snapshot fields are diagnostic-only for health validation",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    stack = _skill_state._normalize_stack(snapshot.get("skillStack"))
    continuation = snapshot.get("continuation") if isinstance(snapshot.get("continuation"), dict) else {}
    if isinstance(continuation.get("stack_depth"), int) and continuation["stack_depth"] != len(stack):
        return _axis(
            "stack_linkage",
            "fail",
            "stack_depth_mismatch",
            "continuation stack_depth does not match skillStack depth",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    return_to = _return_to(snapshot)
    if return_to and (not stack or not _frame_matches(stack[-1], return_to)):
        return _axis(
            "stack_linkage",
            "fail",
            "stack_return_to_mismatch",
            "return_to does not match the current legacy stack frame",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if state_contract is not None:
        return _axis(
            "stack_linkage",
            "fail",
            "state_snapshot_contract_invalid",
            "canonical state snapshot contract failed",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    return _axis(
        "stack_linkage",
        "pass",
        "stack_linkage_valid",
        "canonical snapshot and legacy stack linkage are consistent",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
    )


def _validate_guard_evidence(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    outcomes = [item for item in context.get("guard_outcomes", []) if isinstance(item, dict)]
    if not outcomes:
        return _axis(
            "guard_evidence",
            "unknown",
            "guard_evidence_unknown",
            "guard outcome evidence was not available",
            mst_session_id=mst_session_id,
        )
    for outcome in outcomes:
        if not _text(outcome.get("reason")) or not (_text(outcome.get("evidence_path")) or _hash(outcome.get("event_hash"))):
            return _axis(
                "guard_evidence",
                "fail",
                "guard_evidence_missing",
                "guard outcome is missing bounded reason or evidence",
                evidence_path=outcome.get("evidence_path"),
                event_hash=outcome.get("event_hash"),
                mst_session_id=mst_session_id,
            )
    for row in _writer_rows(context):
        writer_id = _text(row.get("writer_id"))
        if writer_id in {"policy_writer", "stop_continuation_writer"} and _text(row.get("status")) in {
            "not_seen",
            "write_failed",
            "schema_invalid",
        }:
            return _axis(
                "guard_evidence",
                "fail",
                "guard_evidence_missing",
                "guard writer coverage evidence is missing or invalid",
                evidence_path=row.get("evidence_path"),
                mst_session_id=mst_session_id,
            )
    return _axis(
        "guard_evidence",
        "pass",
        "guard_evidence_present",
        "guard outcomes include bounded reason and evidence",
        evidence_path=outcomes[0].get("evidence_path"),
        event_hash=outcomes[0].get("event_hash"),
        mst_session_id=mst_session_id,
    )


def _validate_history_linkage(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    ledger = context.get("ledger")
    if isinstance(ledger, dict):
        ledger_result = execution_flow.validate_source_ledger_projection_source(ledger)
        if ledger_result.get("status") != "ok":
            diagnostic = (ledger_result.get("diagnostics") or [{}])[0]
            return _axis(
                "history_linkage",
                "fail",
                _text(diagnostic.get("code")) or "history_linkage_invalid",
                _text(diagnostic.get("reason")) or "verified ledger linkage failed",
                evidence_path=ledger_result.get("ledger_path"),
                mst_session_id=mst_session_id,
            )

    linkage = context.get("history_linkage") if isinstance(context.get("history_linkage"), dict) else {}
    if not linkage:
        return _axis(
            "history_linkage",
            "unknown",
            "history_linkage_unknown",
            "history linkage evidence was not available",
            mst_session_id=mst_session_id,
        )
    evidence_path = linkage.get("evidence_path")
    event_hash = linkage.get("event_hash")
    if linkage.get("hash_chain_valid") is False:
        return _axis(
            "history_linkage",
            "fail",
            "history_hash_chain_broken",
            "verified event hash chain is broken",
            evidence_path=evidence_path,
            event_hash=event_hash,
            mst_session_id=mst_session_id,
        )
    projection_head = _text(linkage.get("projection_source_head"))
    verified_head = _text(linkage.get("verified_ledger_head"))
    snapshot_head = _text(linkage.get("snapshot_history_head"))
    if projection_head and verified_head and projection_head != verified_head:
        return _axis(
            "history_linkage",
            "fail",
            "history_head_mismatch",
            "projection source head does not match verified ledger head",
            evidence_path=evidence_path,
            event_hash=event_hash,
            mst_session_id=mst_session_id,
        )
    if snapshot_head and verified_head and snapshot_head != verified_head:
        return _axis(
            "history_linkage",
            "fail",
            "history_head_mismatch",
            "snapshot history head does not match verified ledger head",
            evidence_path=evidence_path,
            event_hash=event_hash,
            mst_session_id=mst_session_id,
        )
    mirror_head = _text(linkage.get("mirror_head"))
    verify_head = _text(linkage.get("verify_head"))
    if (mirror_head and verified_head and mirror_head != verified_head) or (verify_head and verified_head and verify_head != verified_head):
        return _axis(
            "history_linkage",
            "fail",
            "history_mirror_verify_mismatch",
            "mirror or verify head does not match verified ledger head",
            evidence_path=evidence_path,
            event_hash=event_hash,
            mst_session_id=mst_session_id,
        )
    return _axis(
        "history_linkage",
        "pass",
        "history_linkage_valid",
        "history source, snapshot, mirror, and verify heads are linked",
        evidence_path=evidence_path,
        event_hash=event_hash,
        mst_session_id=mst_session_id,
    )


def _is_stale_marked(projection: dict[str, Any], handoff: dict[str, Any]) -> bool:
    freshness = handoff.get("projection_freshness") if isinstance(handoff.get("projection_freshness"), dict) else {}
    return (
        projection.get("stale") is True
        or projection.get("regenerate_required") is True
        or _text(freshness.get("status")) == "stale"
    )


def _validate_projection_freshness(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    projection = context.get("execution_flow_projection") if isinstance(context.get("execution_flow_projection"), dict) else {}
    handoff = context.get("current_work_handoff") if isinstance(context.get("current_work_handoff"), dict) else {}
    if not projection and handoff:
        wrapped_handoff = {
            "schema_version": 1,
            "identity": context.get("identity"),
            "source_history_head": handoff.get("source_history_head"),
            "current_history_head": handoff.get("current_history_head"),
            "history_head_evidence_path": handoff.get("evidence_path"),
        }
        current_work_handoff._projection_freshness(wrapped_handoff, mst_session_id, _text(context.get("generated_at")) or "unknown")
    source_head = _text(projection.get("source_history_head") or handoff.get("source_history_head"))
    current_head = _text(projection.get("current_verified_head") or handoff.get("current_history_head"))
    evidence_path = projection.get("evidence_path") or handoff.get("evidence_path")
    if not source_head or not current_head:
        return _axis(
            "projection_freshness",
            "unknown",
            "projection_head_missing",
            "projection source or current verified head was not available",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if source_head == current_head:
        return _axis(
            "projection_freshness",
            "pass",
            "projection_fresh",
            "projection source head matches current verified head",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    if _is_stale_marked(projection, handoff):
        return _axis(
            "projection_freshness",
            "pass",
            "projection_stale_marked",
            "projection source head changed and stale marker is present",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    return _axis(
        "projection_freshness",
        "fail",
        "projection_stale_unmarked",
        "projection source head changed without stale or regenerate marker",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
    )


def _writer_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    coverage = context.get("writer_coverage") if isinstance(context.get("writer_coverage"), dict) else {}
    rows = coverage.get("writers")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    projected = writer_coverage.project_writer_coverage(coverage or context)
    projected_rows = projected.get("writers")
    return [row for row in projected_rows if isinstance(row, dict)] if isinstance(projected_rows, list) else []


def _validate_writer_coverage(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    rows = _writer_rows(context)
    coverage = context.get("writer_coverage") if isinstance(context.get("writer_coverage"), dict) else {}
    evidence_path = coverage.get("evidence_path")
    if not rows:
        return _axis(
            "writer_coverage",
            "unknown",
            "writer_coverage_unknown",
            "writer coverage matrix was not available",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    for row in rows:
        status = _text(row.get("status"))
        if status in {"not_seen", "write_failed", "schema_invalid"}:
            return _axis(
                "writer_coverage",
                "fail",
                f"writer_{status}",
                f"writer coverage row reported {status}",
                evidence_path=row.get("evidence_path") or evidence_path,
                mst_session_id=mst_session_id,
            )
        if status not in {"ok", "observed", "not_applicable"} and row.get("observed") is not True:
            return _axis(
                "writer_coverage",
                "unknown",
                "writer_coverage_unknown",
                "writer coverage status could not be determined",
                evidence_path=row.get("evidence_path") or evidence_path,
                mst_session_id=mst_session_id,
            )
    return _axis(
        "writer_coverage",
        "pass",
        "writer_coverage_satisfied",
        "expected writers are observed or not applicable",
        evidence_path=rows[0].get("evidence_path") or evidence_path,
        mst_session_id=mst_session_id,
    )


def _validate_identity_boundary(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    identity = context.get("identity") if isinstance(context.get("identity"), dict) else {}
    env = identity.get("env") if isinstance(identity.get("env"), dict) else {}
    structured = identity.get("context") if isinstance(identity.get("context"), dict) else {}
    env_sid = _safe_session_id(env.get("MST_SESSION_ID"))
    structured_sid = _safe_session_id(structured.get("mst_session_id"))
    result = execution_flow.resolve_canonical_mst_session_identity(
        {"mst_session_id": structured_sid} if structured_sid else {},
        {"MST_SESSION_ID": env_sid} if env_sid else {},
    )
    diagnostics = _identity_diagnostics(context)
    if (env_sid and structured_sid and env_sid != structured_sid) or result.get("status") != "ok":
        return _axis(
            "identity_boundary",
            "fail",
            "canonical_diagnostic_identity_conflict",
            "canonical MST_SESSION_ID and structured mst_session_id conflict or are missing",
            evidence_path=f".gran-maestro/sessions/{mst_session_id or 'unknown'}/identity.json",
            mst_session_id=mst_session_id,
            diagnostics=diagnostics,
        )
    return _axis(
        "identity_boundary",
        "pass",
        "canonical_identity_valid",
        "canonical identity source is MST_SESSION_ID or structured mst_session_id",
        evidence_path=f".gran-maestro/sessions/{mst_session_id}/identity.json",
        mst_session_id=mst_session_id,
        diagnostics=diagnostics,
    )


def _validate_current_work_handoff(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    handoff = context.get("current_work_handoff") if isinstance(context.get("current_work_handoff"), dict) else {}
    if not handoff:
        projected = current_work_handoff.project_current_work_handoff(context)
        handoff = projected if isinstance(projected, dict) else {}
    evidence_path = handoff.get("evidence_path") or (handoff.get("evidence_paths") or [None])[0]
    if handoff.get("safe_to_resume") is True:
        return _axis(
            "current_work_handoff",
            "fail",
            "terminal_safe_to_resume_true",
            "current-work handoff is resume-safe after terminal state",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    next_action = handoff.get("next_action") if isinstance(handoff.get("next_action"), dict) else {}
    if handoff.get("paused") is True and _text(next_action.get("action_type")) == "continue_skill":
        return _axis(
            "current_work_handoff",
            "fail",
            "paused_continue_mismatch",
            "paused handoff exposes continue action",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    continuation = handoff.get("continue") if isinstance(handoff.get("continue"), dict) else {}
    queued = continuation.get("queued_action") if isinstance(continuation.get("queued_action"), dict) else None
    if queued is not None and (
        _text(queued.get("action_type")) != _text(next_action.get("action_type"))
        or _text(queued.get("target")) != _text(next_action.get("target"))
    ):
        return _axis(
            "current_work_handoff",
            "fail",
            "queued_action_not_reflected",
            "continue.queued_action is not reflected in current-work next_action",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    return _axis(
        "current_work_handoff",
        "pass",
        "current_work_handoff_valid",
        "current-work handoff safety fields are consistent",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
    )


def _anchor_items(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = timeline.get("prompt_anchors") if isinstance(timeline.get("prompt_anchors"), dict) else {}
    items = anchors.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _validate_prompt_correlation(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    timeline = context.get("prompt_timeline") if isinstance(context.get("prompt_timeline"), dict) else {}
    if not timeline:
        timeline = prompt_correlation.project_prompt_timeline(context)
    evidence_paths = timeline.get("evidence_paths") if isinstance(timeline.get("evidence_paths"), list) else []
    evidence_path = evidence_paths[0] if evidence_paths else f".gran-maestro/sessions/{mst_session_id}/prompt-timeline.json"
    anchors = _anchor_items(timeline)
    if not anchors:
        return _axis(
            "prompt_correlation",
            "unknown",
            "prompt_correlation_unknown",
            "prompt submitted anchor was not available",
            evidence_path=evidence_path,
            mst_session_id=mst_session_id,
        )
    prompt_writer_missing = any(
        _text(row.get("writer_id")) == "prompt_writer"
        and _text(row.get("status")) in {"not_seen", "write_failed", "schema_invalid"}
        for row in _writer_rows(context)
    )
    for anchor in anchors:
        following = anchor.get("following_events") if isinstance(anchor.get("following_events"), dict) else {}
        items = [item for item in following.get("items", []) if isinstance(item, dict)] if isinstance(following.get("items"), list) else []
        if not items:
            return _axis(
                "prompt_correlation",
                "fail",
                "prompt_writer_coverage_missing" if prompt_writer_missing else "prompt_correlation_gap",
                "prompt submitted anchor has no correlated following event",
                evidence_path=evidence_path,
                event_hash=anchor.get("event_hash"),
                mst_session_id=mst_session_id,
            )
        for item in items:
            if not isinstance(item.get("correlation_range"), dict) or not _text(item.get("evidence_path")):
                return _axis(
                    "prompt_correlation",
                    "fail",
                    "prompt_writer_coverage_missing" if prompt_writer_missing else "prompt_correlation_gap",
                    "prompt following event lacks correlation range or evidence",
                    evidence_path=evidence_path,
                    event_hash=anchor.get("event_hash"),
                    mst_session_id=mst_session_id,
                )
    return _axis(
        "prompt_correlation",
        "pass",
        "prompt_correlation_valid",
        "prompt submitted anchors are linked to following event evidence",
        evidence_path=evidence_path,
        event_hash=anchors[0].get("event_hash"),
        mst_session_id=mst_session_id,
    )


def _validate_ki001(context: dict[str, Any], mst_session_id: str) -> dict[str, Any]:
    issues = [item for item in context.get("known_issues", []) if isinstance(item, dict)]
    for issue in issues:
        if issue.get("id") != "KI-001":
            continue
        target = _text(issue.get("cleanup_target"))
        branch = _text(issue.get("active_branch"))
        cleanup_performed = issue.get("destructive_cleanup_performed") is True
        if target in {"project_root", "master", "active_branch"} or branch in {"master", "main"}:
            return _axis(
                "ki001_sprint_close_targeting",
                "fail",
                "ki001_sprint_close_cleanup_target",
                "sprint-close targeted project root or active master branch",
                evidence_path=issue.get("evidence_path"),
                mst_session_id=mst_session_id,
                cleanup_performed=cleanup_performed,
            )
    evidence_path = issues[0].get("evidence_path") if issues else ".gran-maestro/agile/AGI-031/known-issues.json"
    return _axis(
        "ki001_sprint_close_targeting",
        "pass",
        "ki001_targeting_valid",
        "KI-001 is represented as validation evidence without destructive cleanup",
        evidence_path=evidence_path,
        mst_session_id=mst_session_id,
        cleanup_performed=False,
    )


def _summary(axes: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = {"pass": 0, "fail": 0, "unknown": 0}
    for axis in axes:
        status = axis.get("status")
        if status in by_status:
            by_status[status] += 1
    return {
        "total": len(axes),
        "pass": by_status["pass"],
        "fail": by_status["fail"],
        "unknown": by_status["unknown"],
        "by_status": by_status,
    }


def _overall_status(axes: list[dict[str, Any]]) -> str:
    statuses = {axis.get("status") for axis in axes}
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def _fixture_catalog(axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for axis in axes:
        axis_name = str(axis["axis"])
        catalog.append(
            {
                "id": axis_name,
                "pac": PAC_BY_AXIS.get(axis_name, "PAC-15"),
                "status": axis["status"],
                "code": axis["code"],
                "evidence_path": _evidence_path(axis.get("evidence_path")),
            }
        )
    catalog.append(
        {
            "id": "bounded_output",
            "pac": "PAC-15",
            "status": "pass",
            "code": "raw_payload_excluded",
            "evidence_path": ".gran-maestro/requests/REQ-828/review/state-machine-health-evidence.md",
        }
    )
    return catalog


def validate_state_machine_health(fixture_or_context: Any) -> dict[str, Any]:
    context = _load_context(fixture_or_context)
    mst_session_id = _canonical_selector(context)
    axes = [
        _validate_transition_order(context, mst_session_id),
        _validate_step_bounds(context, mst_session_id),
        _validate_stack_linkage(context, mst_session_id),
        _validate_guard_evidence(context, mst_session_id),
        _validate_history_linkage(context, mst_session_id),
        _validate_projection_freshness(context, mst_session_id),
        _validate_writer_coverage(context, mst_session_id),
        _validate_identity_boundary(context, mst_session_id),
        _validate_current_work_handoff(context, mst_session_id),
        _validate_prompt_correlation(context, mst_session_id),
        _validate_ki001(context, mst_session_id),
    ]
    axes_by_name = {axis["axis"]: axis for axis in axes}
    ordered_axes = [axes_by_name[name] for name in AXES]
    summary = _summary(ordered_axes)
    return _hashable_json({
        "schema_version": SCHEMA_VERSION,
        "status": _overall_status(ordered_axes),
        "mst_session_id": mst_session_id,
        "canonical_mst_session_id": mst_session_id,
        "lookup_key": mst_session_id,
        "partition_key": mst_session_id,
        "recovery_selector": mst_session_id,
        "source_surfaces": dict(SOURCE_SURFACES),
        "summary": summary,
        "axes": ordered_axes,
        "fixture_catalog": _fixture_catalog(ordered_axes),
        "legacy_diagnostics": _identity_diagnostics(context),
        "raw_payload_excluded": True,
        "requires_new_dashboard_route": False,
        "requires_new_hud_display_model": False,
    })
