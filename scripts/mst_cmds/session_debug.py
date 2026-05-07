from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.mst_cmds.current_work_handoff import project_current_work_handoff
from scripts.mst_cmds.prompt_correlation import project_prompt_timeline
from scripts.mst_cmds.writer_coverage import project_writer_coverage


PANEL_REGISTRY: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("identity", "Identity Mapping"),
    ("prompt_timeline", "Prompt Timeline"),
    ("current_work", "Current Work"),
    ("execution_flow", "Execution Flow"),
    ("writer_coverage", "Writer Coverage"),
    ("integrity_freshness", "Integrity & Freshness"),
    ("policy_block", "Policy/Block"),
)

DEFAULT_EVIDENCE_PATH = ".gran-maestro/sessions/{mst_session_id}/history.ndjson"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _safe_mst_session_id(value: Any) -> str:
    text = _safe_text(value)
    if not text or "/" in text or ".." in text:
        return ""
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in text):
        return ""
    return text


def _identity(fixture: dict[str, Any]) -> dict[str, Any]:
    return fixture.get("identity") if isinstance(fixture.get("identity"), dict) else {}


def _identity_env(fixture: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(fixture)
    return identity.get("env") if isinstance(identity.get("env"), dict) else {}


def _identity_context(fixture: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(fixture)
    return identity.get("context") if isinstance(identity.get("context"), dict) else {}


def _canonical_mst_session_id(fixture: dict[str, Any]) -> str:
    env_value = _safe_mst_session_id(_identity_env(fixture).get("MST_SESSION_ID"))
    context_value = _safe_mst_session_id(_identity_context(fixture).get("mst_session_id"))
    if env_value:
        return env_value
    if context_value:
        return context_value
    return _safe_mst_session_id(fixture.get("canonical_mst_session_id")) or _safe_mst_session_id(fixture.get("mst_session_id"))


def _generated_at(fixture: dict[str, Any]) -> str:
    return _safe_text(fixture.get("generated_at")) or _utc_now()


def _evidence_path(value: Any, mst_session_id: str) -> str:
    text = _safe_text(value)
    if text.startswith(".gran-maestro/") and ".." not in text:
        return text
    return DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")


def _collect_evidence_paths(*values: Any, mst_session_id: str) -> list[str]:
    paths: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            evidence = value.get("evidence_path")
            if isinstance(evidence, str) and evidence.startswith(".gran-maestro/") and ".." not in evidence and evidence not in paths:
                paths.append(evidence)
            evidence_paths = value.get("evidence_paths")
            if isinstance(evidence_paths, list):
                for item in evidence_paths:
                    if isinstance(item, str) and item.startswith(".gran-maestro/") and ".." not in item and item not in paths:
                        paths.append(item)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for value in values:
        collect(value)
    if not paths:
        paths.append(DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown"))
    return paths


def _bounded_writer_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    projection = fixture.get("writer_coverage")
    if isinstance(projection, dict):
        return projection
    return project_writer_coverage(fixture)


def _bounded_current_work_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    projection = fixture.get("current_work_handoff")
    if isinstance(projection, dict):
        return projection
    return project_current_work_handoff(fixture)


def _bounded_prompt_projection(fixture: dict[str, Any]) -> dict[str, Any]:
    projection = fixture.get("prompt_timeline")
    if isinstance(projection, dict):
        return projection
    return project_prompt_timeline(fixture)


def _history_status(fixture: dict[str, Any]) -> str:
    source_head = fixture.get("source_history_head")
    current_head = fixture.get("current_history_head")
    if source_head is None and current_head is None:
        return "no_history"
    if source_head is None or current_head is None:
        return "unknown"
    return "fresh" if source_head == current_head else "stale"


def _current_work_status(current_work: dict[str, Any]) -> str:
    blockers = current_work.get("blockers")
    if isinstance(blockers, list):
        meaningful = [
            blocker for blocker in blockers
            if isinstance(blocker, dict) and blocker.get("blocker_type") != "missing_source"
        ]
        if meaningful:
            return "blocked"
    workflow = current_work.get("active_workflow")
    stack = current_work.get("current_task_stack") if isinstance(current_work.get("current_task_stack"), dict) else {}
    total = stack.get("total")
    if isinstance(workflow, dict) or (isinstance(total, int) and total > 0):
        return "active"
    if isinstance(blockers, list):
        return "empty"
    return "unknown"


def _prompt_status(prompt_timeline: dict[str, Any], fixture: dict[str, Any]) -> str:
    anchors = prompt_timeline.get("prompt_anchors") if isinstance(prompt_timeline.get("prompt_anchors"), dict) else {}
    total = anchors.get("total")
    if isinstance(total, int) and total > 0:
        return "seen"
    return "no_history" if _history_status(fixture) == "no_history" else "not_seen"


def _latest_prompt_digest(prompt_timeline: dict[str, Any]) -> str:
    anchors = prompt_timeline.get("prompt_anchors") if isinstance(prompt_timeline.get("prompt_anchors"), dict) else {}
    items = anchors.get("items")
    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if isinstance(item, dict):
            digest = _safe_text(item.get("prompt_digest"))
            if digest:
                return digest
    return ""


def _writer_status(writer_coverage: dict[str, Any]) -> str:
    writers = writer_coverage.get("writers")
    if not isinstance(writers, list) or not writers:
        return "unknown"
    statuses = {row.get("status") for row in writers if isinstance(row, dict)}
    if statuses <= {"ok", "not_applicable"}:
        return "ok"
    if statuses & {"identity_mismatch", "write_failed", "schema_invalid"}:
        return "error"
    if statuses:
        return "warning"
    return "unknown"


def _integrity_status(fixture: dict[str, Any]) -> str:
    integrity = fixture.get("integrity") if isinstance(fixture.get("integrity"), dict) else {}
    status = _safe_text(integrity.get("status"))
    if status in {"ok", "stale", "mismatch", "no_history", "unknown"}:
        return status
    freshness = _history_status(fixture)
    if freshness == "fresh":
        return "unknown"
    if freshness == "stale":
        return "stale"
    return freshness


def _projection_status(fixture: dict[str, Any], current_work: dict[str, Any], prompt_timeline: dict[str, Any]) -> str:
    freshness = current_work.get("projection_freshness") if isinstance(current_work.get("projection_freshness"), dict) else {}
    status = _safe_text(freshness.get("status"))
    if status in {"fresh", "stale", "identity_mismatch", "no_history", "unknown"}:
        return status
    prompt_freshness = prompt_timeline.get("projection_freshness") if isinstance(prompt_timeline.get("projection_freshness"), dict) else {}
    status = _safe_text(prompt_freshness.get("status"))
    if status in {"fresh", "stale", "identity_mismatch", "no_history", "unknown"}:
        return status
    return _history_status(fixture)


def _summary(
    fixture: dict[str, Any],
    *,
    mst_session_id: str,
    generated_at: str,
    writer_coverage: dict[str, Any],
    current_work: dict[str, Any],
    prompt_timeline: dict[str, Any],
) -> dict[str, Any]:
    return {
        "identity": {
            "status": "ok" if mst_session_id else "unknown",
            "canonical_mst_session_id": mst_session_id,
        },
        "current_work": {
            "status": _current_work_status(current_work),
            "next_action_type": (
                current_work.get("next_action", {}).get("action_type")
                if isinstance(current_work.get("next_action"), dict)
                else "unknown"
            ),
        },
        "prompt": {
            "status": _prompt_status(prompt_timeline, fixture),
            "latest_prompt_digest": _latest_prompt_digest(prompt_timeline),
        },
        "writers": {
            "status": _writer_status(writer_coverage),
            "total": (
                len(writer_coverage.get("writers"))
                if isinstance(writer_coverage.get("writers"), list)
                else 0
            ),
        },
        "integrity": {
            "status": _integrity_status(fixture),
            "reason": _safe_text((fixture.get("integrity") or {}).get("reason") if isinstance(fixture.get("integrity"), dict) else "") or "verifier_not_in_scope",
        },
        "projection": {
            "status": _projection_status(fixture, current_work, prompt_timeline),
            "generated_at": generated_at,
        },
    }


def _diagnostic_only_identifiers(fixture: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    identity = _identity(fixture)
    diagnostics = identity.get("legacy_diagnostics") if isinstance(identity.get("legacy_diagnostics"), dict) else {}
    structured = _identity_context(fixture)
    env = _identity_env(fixture)

    candidates = {
        "hook_session_id": diagnostics.get("hook_session_id") or structured.get("session_id"),
        "owner_session_id": diagnostics.get("owner_session_id") or structured.get("owner_session_id"),
        "owner_pid": diagnostics.get("owner_pid") or structured.get("owner_pid") or env.get("MST_STATE_PPID"),
    }
    transcript_path = _safe_text(structured.get("transcript_path"))
    if transcript_path:
        name = Path(transcript_path).name
        candidates["hook_transcript_stem"] = name[:-6] if name.endswith(".jsonl") else Path(name).stem

    for kind, value in candidates.items():
        text = _safe_text(value)
        if text:
            result.append({"kind": kind, "value": text, "classification": "diagnostic_only"})
    return result


def _identity_detail(fixture: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    detail = {
        "panel_id": "identity",
        "canonical_mst_session_id": mst_session_id,
        "lookup_key": mst_session_id,
        "partition_key": mst_session_id,
        "repair_source": "canonical_mst_session_id",
        "migration_source": "canonical_mst_session_id",
        "diagnostic_only_identifiers": _diagnostic_only_identifiers(fixture),
    }
    detail["evidence_paths"] = _collect_evidence_paths(detail, fixture.get("identity"), mst_session_id=mst_session_id)
    return detail


def _execution_flow_detail(fixture: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    source = fixture.get("execution_flow") if isinstance(fixture.get("execution_flow"), dict) else {}
    detail = {
        "panel_id": "execution_flow",
        "current_node": source.get("current_node") if source else "unknown",
        "last_transition": source.get("last_transition") if source else "unknown",
        "next_action": source.get("next_action") if source else "unknown",
        "node_health": source.get("node_health") if isinstance(source.get("node_health"), dict) else {"status": "unknown", "reason": "verifier_not_in_scope"},
        "edge_health": source.get("edge_health") if isinstance(source.get("edge_health"), dict) else {"status": "unknown", "reason": "verifier_not_in_scope"},
    }
    detail["evidence_paths"] = _collect_evidence_paths(source, mst_session_id=mst_session_id)
    return detail


def _integrity_detail(fixture: dict[str, Any], *, mst_session_id: str, generated_at: str) -> dict[str, Any]:
    source = fixture.get("integrity") if isinstance(fixture.get("integrity"), dict) else {}
    detail = {
        "panel_id": "integrity_freshness",
        "status": _integrity_status(fixture),
        "reason": _safe_text(source.get("reason")) or "verifier_not_in_scope",
        "source_history_head": source.get("source_history_head", fixture.get("source_history_head")),
        "current_history_head": source.get("current_history_head", fixture.get("current_history_head")),
        "generated_at": generated_at,
    }
    detail["evidence_paths"] = _collect_evidence_paths(source, detail, mst_session_id=mst_session_id)
    return detail


def _policy_blocks(fixture: dict[str, Any], prompt_timeline: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = fixture.get("policy_blocks")
    if isinstance(blocks, list):
        return [
            {
                "indicator": _safe_text(item.get("indicator")) or "policy_block",
                "status": _safe_text(item.get("status")) or "unknown",
                "evidence_path": item.get("evidence_path"),
            }
            for item in blocks
            if isinstance(item, dict)
        ]
    indicators = prompt_timeline.get("policy_block_indicators") if isinstance(prompt_timeline.get("policy_block_indicators"), dict) else {}
    if isinstance(indicators.get("count"), int) and indicators["count"] > 0:
        return [{"indicator": "policy_block", "status": "blocked", "evidence_path": None}]
    return []


def _policy_detail(fixture: dict[str, Any], prompt_timeline: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    blocks = _policy_blocks(fixture, prompt_timeline)
    indicator_names = {str(block.get("indicator") or "") for block in blocks}
    detail = {
        "panel_id": "policy_block",
        "indicators": {
            "policy_block": "policy_block" in indicator_names,
            "core_block": "core_block" in indicator_names,
            "confirm_requested": "confirm_requested" in indicator_names,
            "override_granted": "override_granted" in indicator_names,
        },
        "empty_state": len(blocks) == 0,
        "items": [
            {
                "indicator": _safe_text(block.get("indicator")) or "policy_block",
                "status": _safe_text(block.get("status")) or "unknown",
                "evidence_path": _evidence_path(block.get("evidence_path"), mst_session_id),
            }
            for block in blocks[:20]
        ],
        "max_items": 20,
        "total": len(blocks),
        "truncated": len(blocks) > 20,
    }
    detail["evidence_paths"] = _collect_evidence_paths(detail, mst_session_id=mst_session_id)
    return detail


def _writer_detail(writer_coverage: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    detail = {
        "panel_id": "writer_coverage",
        "source_projection": "DOD-002",
        "summary": writer_coverage.get("summary") if isinstance(writer_coverage.get("summary"), dict) else {},
        "writers": writer_coverage.get("writers") if isinstance(writer_coverage.get("writers"), list) else [],
    }
    detail["evidence_paths"] = _collect_evidence_paths(detail, writer_coverage, mst_session_id=mst_session_id)
    return detail


def _current_work_detail(current_work: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    detail = {
        "panel_id": "current_work",
        "source_projection": "DOD-003",
        "active_workflow": current_work.get("active_workflow"),
        "current_task_stack": current_work.get("current_task_stack"),
        "next_action": current_work.get("next_action"),
        "blockers": current_work.get("blockers") if isinstance(current_work.get("blockers"), list) else [],
        "projection_freshness": current_work.get("projection_freshness"),
    }
    detail["evidence_paths"] = _collect_evidence_paths(detail, current_work, mst_session_id=mst_session_id)
    return detail


def _prompt_timeline_detail(prompt_timeline: dict[str, Any], *, mst_session_id: str) -> dict[str, Any]:
    detail = {
        "panel_id": "prompt_timeline",
        "source_projection": "DOD-004",
        "prompt_anchors": prompt_timeline.get("prompt_anchors"),
        "policy_block_indicators": prompt_timeline.get("policy_block_indicators"),
        "core_block_indicators": prompt_timeline.get("core_block_indicators"),
        "projection_freshness": prompt_timeline.get("projection_freshness"),
        "correlation_basis": prompt_timeline.get("correlation_basis"),
    }
    detail["evidence_paths"] = _collect_evidence_paths(detail, prompt_timeline, mst_session_id=mst_session_id)
    return detail


def _summary_detail(summary: dict[str, Any], *, mst_session_id: str, evidence_paths: list[str]) -> dict[str, Any]:
    return {
        "panel_id": "summary",
        "summary": summary,
        "evidence_paths": evidence_paths or [DEFAULT_EVIDENCE_PATH.format(mst_session_id=mst_session_id or "unknown")],
    }


def _selected_detail(
    fixture: dict[str, Any],
    *,
    panel_id: str,
    mst_session_id: str,
    generated_at: str,
    summary: dict[str, Any],
    evidence_paths: list[str],
    writer_coverage: dict[str, Any],
    current_work: dict[str, Any],
    prompt_timeline: dict[str, Any],
) -> dict[str, Any]:
    if panel_id == "identity":
        return _identity_detail(fixture, mst_session_id=mst_session_id)
    if panel_id == "prompt_timeline":
        return _prompt_timeline_detail(prompt_timeline, mst_session_id=mst_session_id)
    if panel_id == "current_work":
        return _current_work_detail(current_work, mst_session_id=mst_session_id)
    if panel_id == "execution_flow":
        return _execution_flow_detail(fixture, mst_session_id=mst_session_id)
    if panel_id == "writer_coverage":
        return _writer_detail(writer_coverage, mst_session_id=mst_session_id)
    if panel_id == "integrity_freshness":
        return _integrity_detail(fixture, mst_session_id=mst_session_id, generated_at=generated_at)
    if panel_id == "policy_block":
        return _policy_detail(fixture, prompt_timeline, mst_session_id=mst_session_id)
    return _summary_detail(summary, mst_session_id=mst_session_id, evidence_paths=evidence_paths)


def _panel_status(panel_id: str, summary: dict[str, Any], fixture: dict[str, Any], prompt_timeline: dict[str, Any]) -> str:
    if panel_id == "identity":
        return str(summary["identity"]["status"])
    if panel_id == "prompt_timeline":
        return str(summary["prompt"]["status"])
    if panel_id == "current_work":
        return str(summary["current_work"]["status"])
    if panel_id == "execution_flow":
        source = fixture.get("execution_flow") if isinstance(fixture.get("execution_flow"), dict) else {}
        health = source.get("node_health") if isinstance(source.get("node_health"), dict) else {}
        return _safe_text(health.get("status")) or "unknown"
    if panel_id == "writer_coverage":
        return str(summary["writers"]["status"])
    if panel_id == "integrity_freshness":
        return str(summary["integrity"]["status"])
    if panel_id == "policy_block":
        return "blocked" if _policy_blocks(fixture, prompt_timeline) else "clear"
    return str(summary["projection"]["status"])


def _panels(summary: dict[str, Any], fixture: dict[str, Any], prompt_timeline: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"id": panel_id, "label": label, "status": _panel_status(panel_id, summary, fixture, prompt_timeline)}
        for panel_id, label in PANEL_REGISTRY
    ]


def _panel_details(
    fixture: dict[str, Any],
    *,
    mst_session_id: str,
    generated_at: str,
    summary: dict[str, Any],
    evidence_paths: list[str],
    writer_coverage: dict[str, Any],
    current_work: dict[str, Any],
    prompt_timeline: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        panel_id: _selected_detail(
            fixture,
            panel_id=panel_id,
            mst_session_id=mst_session_id,
            generated_at=generated_at,
            summary=summary,
            evidence_paths=evidence_paths,
            writer_coverage=writer_coverage,
            current_work=current_work,
            prompt_timeline=prompt_timeline,
        )
        for panel_id, _ in PANEL_REGISTRY
    }


def project_session_debug_dashboard(fixture: dict[str, Any]) -> dict[str, Any]:
    context = fixture if isinstance(fixture, dict) else {}
    mst_session_id = _canonical_mst_session_id(context)
    generated_at = _generated_at(context)
    writer_coverage = _bounded_writer_projection(context)
    current_work = _bounded_current_work_projection(context)
    prompt_timeline = _bounded_prompt_projection(context)
    summary = _summary(
        context,
        mst_session_id=mst_session_id,
        generated_at=generated_at,
        writer_coverage=writer_coverage,
        current_work=current_work,
        prompt_timeline=prompt_timeline,
    )
    evidence_paths = _collect_evidence_paths(
        writer_coverage,
        current_work,
        prompt_timeline,
        context.get("execution_flow"),
        context.get("integrity"),
        context.get("policy_blocks"),
        mst_session_id=mst_session_id,
    )
    selected_panel_id = _safe_text(context.get("selected_panel_id")) or "summary"
    if selected_panel_id not in {panel_id for panel_id, _ in PANEL_REGISTRY}:
        selected_panel_id = "summary"
    panel_details = _panel_details(
        context,
        mst_session_id=mst_session_id,
        generated_at=generated_at,
        summary=summary,
        evidence_paths=evidence_paths,
        writer_coverage=writer_coverage,
        current_work=current_work,
        prompt_timeline=prompt_timeline,
    )
    selected_detail = panel_details[selected_panel_id]

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "mst_session_id": mst_session_id,
        "summary": summary,
        "panels": _panels(summary, context, prompt_timeline),
        "panel_details": panel_details,
        "selected_detail": selected_detail,
        "evidence_paths": evidence_paths,
    }
