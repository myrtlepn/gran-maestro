from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ALLOWED_FRESHNESS_STATUS = {
    "fresh",
    "stale",
    "identity_mismatch",
    "no_history",
    "unknown",
}
MAX_ARRAY_ITEMS = 5
MAX_STRING_LENGTH = 80
MAX_COMPACT_TEXT_LENGTH = 160
TRUNCATION_SUFFIX = "…"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    return None


def _truncate(value: str, max_length: int, truncated: list[bool]) -> str:
    if len(value) <= max_length:
        return value
    truncated[0] = True
    if max_length <= len(TRUNCATION_SUFFIX):
        return TRUNCATION_SUFFIX[:max_length]
    return value[: max_length - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def _bounded_text(value: Any, truncated: list[bool], *, fallback: str | None = None) -> str | None:
    text = _safe_text(value)
    if not text:
        return fallback
    return _truncate(text, MAX_STRING_LENGTH, truncated)


def _freshness(source: dict[str, Any] | None) -> str:
    if not isinstance(source, dict):
        return "no_history"
    raw = source.get("projection_freshness")
    status = raw.get("status") if isinstance(raw, dict) else raw
    text = _safe_text(status)
    return text if text in ALLOWED_FRESHNESS_STATUS else "unknown"


def _stack_depth(source: dict[str, Any] | None) -> int:
    if not isinstance(source, dict):
        return 0
    stack = source.get("current_task_stack")
    if not isinstance(stack, dict):
        return 0
    total = _safe_int(stack.get("total"))
    if total is not None:
        return total
    items = stack.get("items")
    return len(items) if isinstance(items, list) else 0


def _next_action(source: dict[str, Any] | None, truncated: list[bool]) -> str:
    if not isinstance(source, dict):
        return "unknown"
    action = source.get("next_action")
    if not isinstance(action, dict):
        return "unknown"
    if action.get("action_type") == "no_action_available":
        return "unknown"
    label = _bounded_text(action.get("label"), truncated)
    return label or "unknown"


def _blocker(source: dict[str, Any] | None, truncated: list[bool]) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return {
            "code": "missing_source",
            "type": "missing_source",
            "status": "blocked",
            "recoverable": True,
            "next_action_type": "resume_workflow",
            "evidence_path": "",
        }
    blockers = source.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return None
    first = next((item for item in blockers if isinstance(item, dict)), None)
    if first is None:
        return None
    code = _bounded_text(first.get("blocker_type"), truncated, fallback="unknown") or "unknown"
    status = _bounded_text(first.get("status"), truncated, fallback="blocked") or "blocked"
    next_action_type = _bounded_text(first.get("next_action_type"), truncated, fallback="resolve_blocker") or "resolve_blocker"
    evidence_path = _bounded_text(first.get("evidence_path"), truncated, fallback="") or ""
    return {
        "code": code,
        "type": code,
        "status": status,
        "recoverable": bool(first.get("recoverable")),
        "next_action_type": next_action_type,
        "evidence_path": evidence_path,
    }


def _evidence_paths(source: dict[str, Any] | None, truncated: list[bool]) -> list[str]:
    if not isinstance(source, dict):
        return []
    raw_paths = source.get("evidence_paths")
    paths = [item for item in raw_paths if isinstance(item, str) and item.strip()] if isinstance(raw_paths, list) else []
    if len(paths) > MAX_ARRAY_ITEMS:
        truncated[0] = True
    return [_truncate(path.strip(), MAX_STRING_LENGTH, truncated) for path in paths[:MAX_ARRAY_ITEMS]]


def _compact_text(
    *,
    root_id: str,
    mst_session_id: str,
    current_skill: str | None,
    current_step: int | None,
    total_steps: int | None,
    stack_depth: int,
    next_action: str,
    blocker: dict[str, Any] | None,
    freshness: str,
    source_head: str | None,
    truncated: list[bool],
) -> str:
    identity = root_id if root_id != "unknown" else mst_session_id
    parts = ["MST", identity]
    if current_skill:
        if current_step is not None and total_steps is not None:
            parts.extend([current_skill, f"{current_step}/{total_steps}"])
        elif current_step is not None:
            parts.extend([current_skill, f"step:{current_step}"])
        else:
            parts.append(current_skill)
    blocker_code = "none"
    if isinstance(blocker, dict):
        blocker_code = _safe_text(blocker.get("code")) or "unknown"
    parts.extend(
        [
            f"stack:{stack_depth}",
            f"next:{next_action or 'unknown'}",
            f"blocker:{blocker_code}",
            f"fresh:{freshness or 'unknown'}",
        ]
    )
    head = _safe_text(source_head)
    if head:
        parts.append(f"head:{head[:8]}")
    return _truncate(" ".join(parts), MAX_COMPACT_TEXT_LENGTH, truncated)


def project_hud_statusline_compact(
    source: dict[str, Any] | None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Project a DOD-003 current-work handoff into HUD/statusline-safe fields."""
    truncated = [False]
    source_obj = source if isinstance(source, dict) else None
    missing_source = source_obj is None

    mst_session_id = _bounded_text(source_obj.get("mst_session_id") if source_obj else None, truncated, fallback="unknown") or "unknown"
    root_id = _bounded_text(source_obj.get("root_id") if source_obj else None, truncated, fallback="unknown") or "unknown"
    current_skill = None
    workflow = source_obj.get("active_workflow") if source_obj else None
    if isinstance(workflow, dict):
        current_skill = _bounded_text(workflow.get("skill"), truncated)
    current_step = _safe_int(source_obj.get("current_step") if source_obj else None)
    total_steps = _safe_int(source_obj.get("total_steps") if source_obj else None)
    stack_depth = _stack_depth(source_obj)
    next_action = _next_action(source_obj, truncated)
    blocker = _blocker(source_obj, truncated)
    source_head = _bounded_text(source_obj.get("source_history_head") if source_obj else None, truncated)
    freshness = _freshness(source_obj)

    reason = "current_work_projection"
    external_hud = source_obj.get("external_hud") if source_obj else None
    if missing_source:
        reason = "missing_source"
    elif isinstance(blocker, dict) and blocker.get("code") == "schema_invalid":
        reason = "schema_invalid"
    elif isinstance(external_hud, dict) and external_hud.get("available") is False:
        reason = "external_hud_unavailable"

    compact_text = _compact_text(
        root_id=root_id,
        mst_session_id=mst_session_id,
        current_skill=current_skill,
        current_step=current_step,
        total_steps=total_steps,
        stack_depth=stack_depth,
        next_action=next_action,
        blocker=blocker,
        freshness=freshness,
        source_head=source_head,
        truncated=truncated,
    )

    return {
        "schema_version": 1,
        "generated_at": _bounded_text(generated_at, truncated, fallback=_utc_now()) or _utc_now(),
        "mst_session_id": mst_session_id,
        "root_id": root_id,
        "current_skill": current_skill,
        "current_step": current_step,
        "total_steps": total_steps,
        "stack_depth": stack_depth,
        "next_action": next_action,
        "blocker": blocker,
        "source_head": source_head,
        "projection_freshness": freshness,
        "compact_text": compact_text,
        "evidence_paths": _evidence_paths(source_obj, truncated),
        "truncated": truncated[0],
        "reason": _bounded_text(reason, truncated, fallback="current_work_projection") or "current_work_projection",
    }
