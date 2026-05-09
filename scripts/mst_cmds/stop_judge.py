from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scripts.mst_cmds import _common
from scripts.mst_cmds import session as session_cmds


DEFAULT_HOOK_TIMEOUT_MS = 5000
RETURN_TO_RE = re.compile(r"return_to=([A-Za-z0-9_:/-]+)")
TERMINAL_REQUEST_STATUSES = {"done", "completed", "accepted", "cancelled", "closed"}
TERMINAL_PLAN_STATUSES = {"done", "completed", "cancelled", "closed"}
ALLOW_MARKERS = ("[스티어링 체크포인트]", "[비상 스티어링]", "[Sprint 0]", "[자동 중단]")
ASK_USER_RE = re.compile(r'"(?:tool_name|name)"\s*:\s*"AskUserQuestion"|AskUserQuestion')
TEXT_QUESTION_PATTERNS = (
    "계속할까요",
    "진행할까요",
    "정리하고 계속",
    "요약하고 계속",
    "컨텍스트가 길어지고",
    "자연스러운 단락",
    "여기서 단락",
    "여기서 끊고",
    "여기서 마무리",
    "여기서 정지",
    "수동 재호출",
    "다시 호출",
    "세션 교체 후",
    "자연스럽게 멈추고",
    "자연스럽게 쉬고",
    "자연스럽게 끊고",
    "멈추고 잠시",
)
LEGITIMATE_STOP_REASONS = {"unrecoverable_external_failure", "fatal_user_judgment_required"}


def _project_root() -> Path:
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR.parent.resolve()
    return Path.cwd().resolve()


def _base_dir(project_root: Path) -> Path:
    return _common.base_dir_from_project(project_root)


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, str(exc)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid json: {exc}"
    if not isinstance(payload, dict):
        return None, "json payload must be an object"
    return payload, None


def _safe_text(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def _safe_session_path(value: Any) -> str:
    text = _safe_text(value)
    if not text or "/" in text or ".." in text or not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        return ""
    return text


def _legacy_identity_present(payload: Mapping[str, Any]) -> bool:
    return any(
        payload.get(key) not in (None, "")
        for key in ("session_id", "sessionId", "owner_session_id", "owner_ppid", "owner_sessionId")
    )


def _valid_structured_session_id(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    try:
        return session_cmds.validate_mst_session_id(value.strip()).mst_session_id, None
    except ValueError as exc:
        return None, str(exc)


def _normalize_canonical_session_id(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    env_id, env_error = _valid_structured_session_id(os.environ.get("MST_SESSION_ID"))
    stdin_id, stdin_error = _valid_structured_session_id(payload.get("mst_session_id"))
    if env_id and stdin_id and env_id != stdin_id:
        return None, f"mst_session_id mismatch: env:MST_SESSION_ID={env_id} stdin:mst_session_id={stdin_id}"
    if env_error:
        return None, env_error
    if stdin_error:
        return None, stdin_error
    return env_id or stdin_id, None


def _snapshot_session_id(payload: Mapping[str, Any], canonical_session_id: str | None) -> str:
    if canonical_session_id:
        return canonical_session_id
    for key in ("session_id", "sessionId"):
        value = _safe_session_path(payload.get(key))
        if value:
            return value
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript.strip():
        stem = Path(transcript).stem
        if _safe_session_path(stem):
            return stem
    return "unknown"


def _extract_return_to(payload: Mapping[str, Any], raw_stdin: str, snapshot: Mapping[str, Any] | None) -> str | None:
    value = payload.get("return_to")
    if isinstance(value, str) and value.strip():
        return value.strip()
    for text in (payload.get("last_assistant_message"), raw_stdin):
        if isinstance(text, str):
            match = RETURN_TO_RE.search(text)
            if match:
                return match.group(1)
    if isinstance(snapshot, Mapping):
        return_to = snapshot.get("returnTo")
        if isinstance(return_to, str) and return_to.strip():
            return return_to.strip()
        if isinstance(return_to, Mapping):
            skill = _safe_text(return_to.get("skill"))
            step = _safe_text(return_to.get("step"))
            if skill and step:
                return f"{skill}/{step}"
            if skill:
                return skill
    return None


def _snapshot_progress(snapshot: Mapping[str, Any] | None) -> tuple[bool, str, int | None, int | None, str]:
    if not isinstance(snapshot, Mapping):
        return False, "", None, None, ""
    current = snapshot.get("currentStep", snapshot.get("current_step"))
    total = snapshot.get("totalSteps", snapshot.get("total_steps"))
    status = _safe_text(snapshot.get("status")).lower()
    skill = _safe_text(snapshot.get("currentSkill") or snapshot.get("current_skill"))
    if isinstance(current, int) and isinstance(total, int) and current < total and status != "committed":
        return True, skill, current, total, status
    return False, skill, current if isinstance(current, int) else None, total if isinstance(total, int) else None, status


def _queued_next_action(payload: Mapping[str, Any], state_payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    def meaningful(candidate: Any) -> dict[str, Any] | None:
        if not isinstance(candidate, dict) or not candidate:
            return None
        if candidate.get("auto") is True:
            return deepcopy(candidate)
        for key, value in candidate.items():
            if key == "auto":
                continue
            if isinstance(value, str) and value.strip():
                return deepcopy(candidate)
            if value not in (None, "", False):
                return deepcopy(candidate)
        return None

    for candidate in (payload.get("queued_action"), payload.get("next_action")):
        action = meaningful(candidate)
        if action:
            return action
    if isinstance(state_payload, Mapping):
        action = meaningful(state_payload.get("next_action"))
        if action:
            return action
    return None


def _is_terminal_status(status: Any, terminal: set[str]) -> bool:
    return _safe_text(status).lower() in terminal


def _owner_ppid_matches(payload: Mapping[str, Any]) -> bool:
    raw_owner = payload.get("owner_ppid")
    if isinstance(raw_owner, bool) or raw_owner in (None, ""):
        return False
    try:
        owner = int(raw_owner)
    except (TypeError, ValueError):
        return False
    try:
        parent = int(os.environ.get("MST_STOP_HOOK_PARENT_PPID") or "0")
    except ValueError:
        parent = 0
    return owner == parent and owner > 0


def _scan_active_artifacts(project_root: Path, canonical_session_id: str | None) -> tuple[bool, bool]:
    base = _base_dir(project_root)
    owner_ppid_only_ignored = False
    active_same_session = False
    if not canonical_session_id:
        return False, False

    for path in sorted((base / "requests").glob("REQ-*/request.json")):
        payload, _error = _load_json_file(path)
        if not payload or _is_terminal_status(payload.get("status"), TERMINAL_REQUEST_STATUSES):
            continue
        artifact_session = _safe_text(payload.get("mst_session_id"))
        if artifact_session == canonical_session_id:
            active_same_session = True
        elif not artifact_session and payload.get("owner_ppid") not in (None, ""):
            owner_ppid_only_ignored = True

    for path in sorted((base / "plans").glob("PLN-*/plan.json")):
        payload, _error = _load_json_file(path)
        if not payload or _is_terminal_status(payload.get("status"), TERMINAL_PLAN_STATUSES):
            continue
        artifact_session = _safe_text(payload.get("mst_session_id"))
        if artifact_session == canonical_session_id:
            active_same_session = True
        elif not artifact_session and payload.get("owner_ppid") not in (None, ""):
            owner_ppid_only_ignored = True

    return active_same_session, owner_ppid_only_ignored


def _pending_delegate_attention(project_root: Path) -> dict[str, Any] | None:
    payload, _error = _load_json_file(_base_dir(project_root) / "run" / "attention.json")
    events = payload.get("delegate_io_attention_events") if isinstance(payload, Mapping) else None
    if not isinstance(events, list):
        return None
    now = datetime.now(timezone.utc)
    for event in events:
        if not isinstance(event, dict):
            continue
        expires_at = _safe_text(event.get("expires_at"))
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expiry = None
            if expiry and expiry < now:
                continue
        return deepcopy(event)
    return None


def _log_boundary_event(project_root: Path, event_type: str, task_id: str, result: str, message: str) -> None:
    log_path = project_root / ".gran-maestro" / "logs" / "boundary-guard.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    line = f"{ts} | mst-stop-hook.sh | {event_type} | {task_id} | {result} | {message}\n"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _evaluate_boundary(project_root: Path) -> tuple[str | None, list[dict[str, Any]]]:
    side_effects: list[dict[str, Any]] = []
    base = _base_dir(project_root)
    for req_path in sorted((base / "requests").glob("REQ-*/request.json")):
        request, _error = _load_json_file(req_path)
        if not request or not _is_terminal_status(request.get("status"), TERMINAL_REQUEST_STATUSES):
            continue
        if not _owner_ppid_matches(request):
            continue
        req_id = _safe_text(request.get("id")) or req_path.parent.name
        for meta_path in sorted((base / "worktrees").glob(f"{req_id}-*.meta.json")):
            meta, _meta_error = _load_json_file(meta_path)
            if not meta:
                continue
            state = _safe_text(meta.get("state"))
            if state == "conflict":
                _log_boundary_event(project_root, "blocked", req_id, "merge_conflict", "boundary_violation:merge_conflict")
                return "boundary_violation:merge_conflict", side_effects
            if state == "clean_failed":
                _log_boundary_event(project_root, "detected", req_id, "not_cleaned", "exit boundary violation detected")
                worktree = meta.get("path")
                if isinstance(worktree, str) and worktree.strip():
                    target = Path(worktree)
                    if not target.is_absolute():
                        target = project_root / target
                    if target.exists():
                        subprocess.run(
                            ["git", "worktree", "remove", "--force", str(target)],
                            cwd=project_root,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                    shutil.rmtree(target, ignore_errors=True)
                meta["state"] = "cleaned"
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                branch = _safe_text(meta.get("branch"))
                if branch:
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        cwd=project_root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                _log_boundary_event(project_root, "retry_success", req_id, "ok", "exit repair succeeded")
                side_effects.append({"kind": "boundary_repair", "reason": "clean_failed", "task_id": req_id})
    return None, side_effects


def _append_agile_audit(project_root: Path, classification: str, block_reason: str | None, message: str) -> None:
    agile_root = _base_dir(project_root) / "agile"
    active: list[tuple[str, Path]] = []
    for path in sorted(agile_root.glob("AGI-*/session.json")):
        payload, _error = _load_json_file(path)
        if payload and _safe_text(payload.get("status")).lower() == "active":
            active.append((_safe_text(payload.get("updated_at")), path.parent))
    if not active:
        return
    active.sort(key=lambda item: item[0])
    audit_path = active[-1][1] / "stop-audit.ndjson"
    existing = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.is_file() else []
    entry = {
        "event_id": f"SAT-{len(existing) + 1:06d}",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "agi_id": active[-1][1].name,
        "hook_stage": "Stop",
        "classification": classification,
        "outcome": "allow" if classification == "allowed" else classification,
        "block_reason": block_reason,
        "pm_last_turn_snippet": message[:200],
    }
    if classification == "allowed":
        entry["block_reason"] = "agile_allow_pattern_whitelisted"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _declared_stop_reason(message: str) -> str | None:
    match = re.search(r"\[MST\s+stop_intent\s+reason=([^\s\]]+)", message)
    return match.group(1).strip() if match else None


def _message_has_text_question_pattern(message: str) -> bool:
    return any(pattern in message for pattern in TEXT_QUESTION_PATTERNS)


def collect_stop_judge_context(
    *,
    project_root: Path,
    payload: Mapping[str, Any] | None,
    raw_stdin: str = "",
    hook_timeout_ms: int = DEFAULT_HOOK_TIMEOUT_MS,
    failsafe: str | None = None,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload_dict = dict(payload or {})
    context: dict[str, Any] = {
        "project_root": str(project_root),
        "payload": deepcopy(payload_dict),
        "raw_stdin": raw_stdin,
        "hook_timeout_ms": int(hook_timeout_ms),
        "signals": {},
        "diagnostics": dict(diagnostics or {}),
        "side_effects": [],
    }
    context["diagnostics"]["wrapper_mode"] = os.environ.get("MST_STOP_HOOK_WRAPPER") == "1"
    if failsafe:
        context["failsafe"] = failsafe
        return context

    context["diagnostics"]["legacy_identity_present"] = _legacy_identity_present(payload_dict)
    canonical_session_id, canonical_error = _normalize_canonical_session_id(payload_dict)
    context["diagnostics"]["canonical_mst_session_id"] = canonical_session_id
    if canonical_error:
        if "mismatch" in canonical_error:
            context["signals"]["canonical_mismatch"] = True
            context["diagnostics"]["canonical_session_error"] = canonical_error
        else:
            context["failsafe"] = "invalid_stdin"
            context["diagnostics"]["canonical_session_error"] = canonical_error
        return context

    base_dir = _base_dir(project_root)
    snapshot_session_id = _snapshot_session_id(payload_dict, canonical_session_id)
    snapshot_path = base_dir / "state" / snapshot_session_id / "snapshot.json"
    snapshot_payload, snapshot_error = _load_json_file(snapshot_path)
    snapshot_present = snapshot_path.is_file()
    context["diagnostics"]["snapshot_present"] = snapshot_present
    context["diagnostics"]["snapshot_session_id"] = snapshot_session_id
    if snapshot_error:
        context["diagnostics"]["snapshot_error"] = snapshot_error
    if snapshot_payload and canonical_session_id:
        snapshot_mst_id = _safe_text(snapshot_payload.get("mst_session_id"))
        if snapshot_mst_id and snapshot_mst_id != canonical_session_id:
            context["signals"]["canonical_mismatch"] = True
            context["diagnostics"]["snapshot_mst_session_id"] = snapshot_mst_id
            return context

    state_payload: dict[str, Any] | None = None
    if canonical_session_id:
        state_path = base_dir / "tmp" / f"mst-state-{canonical_session_id}.json"
        state_payload, state_error = _load_json_file(state_path)
        context["diagnostics"]["state_path"] = str(state_path)
        if state_error:
            context["signals"]["corrupted_mandatory_state"] = True
            context["diagnostics"]["state_error"] = state_error
            return context
        if state_payload:
            has_canonical_fields = any(key in state_payload for key in ("mst_session_id", "root_mst_id", "schema_version"))
            if has_canonical_fields:
                validation_error = _common.canonical_state_payload_error(state_payload, canonical_session_id)
                if validation_error:
                    if "mismatch" in validation_error:
                        context["signals"]["canonical_mismatch"] = True
                    else:
                        context["signals"]["corrupted_mandatory_state"] = True
                    context["diagnostics"]["state_validation_error"] = validation_error
                    return context

    message = _safe_text(payload_dict.get("last_assistant_message") or payload_dict.get("assistant_message") or payload_dict.get("message"))
    context["diagnostics"]["last_assistant_message"] = message
    context["signals"]["stop_hook_active"] = payload_dict.get("stop_hook_active") is True
    declared_stop_reason = _declared_stop_reason(message)
    if declared_stop_reason in LEGITIMATE_STOP_REASONS:
        context["signals"]["legitimate_stop_intent"] = declared_stop_reason

    return_to = _extract_return_to(payload_dict, raw_stdin, snapshot_payload)
    snapshot_in_progress, snapshot_skill, snapshot_current, snapshot_total, snapshot_status = _snapshot_progress(snapshot_payload)
    if return_to:
        context["signals"]["return_to"] = return_to
    if snapshot_in_progress:
        context["signals"]["snapshot_in_progress"] = {
            "skill": snapshot_skill,
            "current": snapshot_current,
            "total": snapshot_total,
        }
    if snapshot_present and snapshot_payload and not snapshot_in_progress and not return_to:
        context["signals"]["snapshot_terminal_or_unhandled"] = {
            "current": snapshot_current,
            "total": snapshot_total,
            "status": snapshot_status,
        }

    active_artifact, owner_ppid_only = _scan_active_artifacts(project_root, canonical_session_id)
    if active_artifact:
        context["signals"]["active_workflow_session"] = True
    if owner_ppid_only:
        context["signals"]["owner_ppid_only_ignored"] = True

    next_action = _queued_next_action(payload_dict, state_payload)
    if next_action:
        context["signals"]["queued_next_action"] = next_action
    if state_payload:
        if state_payload.get("workflow_active") is True:
            context["signals"]["workflow_active"] = True
        if state_payload.get("agile_loop_active") is True:
            context["signals"]["agile_loop_active"] = True
        context["diagnostics"]["current_skill"] = _safe_text(state_payload.get("current_skill") or state_payload.get("currentSkill"))
        context["diagnostics"]["updated_at"] = _safe_text(state_payload.get("updated_at"))
        context["diagnostics"]["steering_disabled"] = state_payload.get("steering_disabled") is True

    attention = _pending_delegate_attention(project_root)
    if attention:
        context["signals"]["delegate_io_attention"] = attention

    boundary_reason, boundary_side_effects = _evaluate_boundary(project_root)
    if boundary_reason:
        context["signals"]["boundary_repair_required"] = boundary_reason
    context["side_effects"].extend(boundary_side_effects)
    if payload_dict.get("boundary_repair_required") is True:
        context["signals"]["boundary_repair_required"] = "boundary repair required"
    elif isinstance(state_payload, Mapping) and state_payload.get("boundary_repair_required") is True:
        context["signals"]["boundary_repair_required"] = "boundary repair required"

    return context


def _decision(
    decision: str,
    reason: str,
    *,
    diagnostics: Mapping[str, Any] | None = None,
    side_effects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "diagnostics": dict(diagnostics or {}),
        "side_effects": list(side_effects or []),
    }


def _with_snapshot(reason: str, diagnostics: Mapping[str, Any]) -> str:
    if "snapshot_present=" in reason:
        return reason
    value = "true" if diagnostics.get("snapshot_present") else "false"
    return f"{reason} snapshot_present={value}"


def _workflow_reason(diagnostics: Mapping[str, Any], next_action: Mapping[str, Any] | None) -> str:
    reason = "Workflow active, continue current skill"
    if diagnostics.get("updated_at"):
        reason += f" updated_at={diagnostics['updated_at']}"
    if next_action:
        auto = next_action.get("auto")
        if auto is not False:
            skill = _safe_text(next_action.get("expected_skill") or next_action.get("skill"))
            source = _safe_text(next_action.get("source_id") or next_action.get("source"))
            if skill:
                reason += f". Suggested next skill: {skill}"
            if source:
                reason += f" from {source}"
    return reason


def reduce_stop_judge_decision(context: Mapping[str, Any]) -> dict[str, Any]:
    hook_timeout_ms = int(context.get("hook_timeout_ms") or DEFAULT_HOOK_TIMEOUT_MS)
    diagnostics = dict(context.get("diagnostics") or {})
    signals = dict(context.get("signals") or {})
    side_effects = list(context.get("side_effects") or [])
    failsafe = context.get("failsafe")
    wrapper_mode = diagnostics.get("wrapper_mode") is True
    message = _safe_text(diagnostics.get("last_assistant_message"))
    current_skill = _safe_text(diagnostics.get("current_skill"))

    if failsafe == "invalid_stdin":
        diagnostics["failsafe"] = failsafe
        return _decision("approve", "invalid stop hook stdin fail-open", diagnostics=diagnostics, side_effects=side_effects)
    if failsafe == "judge_timeout":
        diagnostics["failsafe"] = failsafe
        return _decision("approve", f"hook judge timeout (>{hook_timeout_ms}ms) fail-open", diagnostics=diagnostics, side_effects=side_effects)
    if failsafe == "startup_failure":
        diagnostics["failsafe"] = failsafe
        return _decision("approve", "hook judge startup failure fail-open", diagnostics=diagnostics, side_effects=side_effects)

    if signals.get("canonical_mismatch"):
        side_effects.append({"kind": "persist_block_state", "reason": "canonical_mismatch"})
        error = diagnostics.get("canonical_session_error")
        snapshot_mst_id = diagnostics.get("snapshot_mst_session_id")
        canonical_id = diagnostics.get("canonical_mst_session_id")
        if snapshot_mst_id and canonical_id:
            reason = f"mst_session_id mismatch: env={canonical_id} snapshot={snapshot_mst_id}"
        elif error:
            reason = str(error)
        else:
            reason = "canonical mst_session_id mismatch"
        return _decision("block", reason, diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("corrupted_mandatory_state"):
        side_effects.append({"kind": "persist_block_state", "reason": "corrupted_mandatory_state"})
        return _decision("block", "corrupted mandatory state", diagnostics=diagnostics, side_effects=side_effects)

    if signals.get("stop_hook_active"):
        _append_agile_audit(Path(str(context.get("project_root"))), "pass_through", "stop_hook_active_true", message)
        return _decision("approve", _with_snapshot("stop_hook_active_true", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("legitimate_stop_intent"):
        _append_agile_audit(Path(str(context.get("project_root"))), "allowed", None, message)
        return _decision("approve", _with_snapshot("workflow_inactive", diagnostics), diagnostics=diagnostics, side_effects=side_effects)

    active_agile = signals.get("agile_loop_active") or current_skill == "mst:agile"
    if active_agile and ASK_USER_RE.search(message):
        if any(marker in message for marker in ALLOW_MARKERS):
            _append_agile_audit(Path(str(context.get("project_root"))), "allowed", None, message)
            return _decision("approve", _with_snapshot("agile_allow_pattern_whitelisted", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
        side_effects.append({"kind": "persist_block_state", "reason": "ask_user_question"})
        return _decision("block", "AskUserQuestion is allowed only with agile whitelist markers.", diagnostics=diagnostics, side_effects=side_effects)
    agile_auto = context.get("payload", {}).get("agile_auto_mode") if isinstance(context.get("payload"), Mapping) else None
    queued_for_message = signals.get("queued_next_action")
    next_action_auto = isinstance(queued_for_message, Mapping) and queued_for_message.get("auto") is True
    steering_forces_block = agile_auto is True or next_action_auto or diagnostics.get("steering_disabled") is True
    if (signals.get("workflow_active") or signals.get("agile_loop_active")) and active_agile and steering_forces_block and _message_has_text_question_pattern(message):
        reason = "[SELF-PAUSE-DETECTED] text-based question patterns are blocked."
        reason += " AUTO_MODE=true or STEERING_DISABLED=true"
        return _decision("block", reason, diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("workflow_active") and current_skill != "mst:agile" and ASK_USER_RE.search(message):
        return _decision("approve", _with_snapshot("workflow_inactive", diagnostics), diagnostics=diagnostics, side_effects=side_effects)

    canonical_session_id = diagnostics.get("canonical_mst_session_id")
    if canonical_session_id is None:
        if wrapper_mode:
            return _decision("approve", _with_snapshot("no-mst-session", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
        return _decision("approve", "no canonical mst_session_id", diagnostics=diagnostics, side_effects=side_effects)

    if signals.get("return_to"):
        return_to = str(signals["return_to"])
        side_effects.append({"kind": "persist_block_state", "reason": "return_to"})
        reason = f"[RETURN-TO] Sub-skill returned with return_to={return_to}. Do NOT stop or pause. Run /mst:resume --wakeup-hint stop-recover."
        return _decision("block", _with_snapshot(reason, diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("snapshot_in_progress"):
        progress = signals["snapshot_in_progress"]
        if isinstance(progress, Mapping):
            skill = _safe_text(progress.get("skill")) or "unknown"
            current = progress.get("current")
            total = progress.get("total")
            try:
                step_label = f"{int(current) + 1}/{int(total)}"
            except Exception:
                step_label = "?/?"
            reason = f"[SNAPSHOT][step_progress] skill {skill} step {step_label}"
        else:
            reason = "snapshot progress incomplete"
        side_effects.append({"kind": "persist_block_state", "reason": "snapshot_in_progress"})
        return _decision("block", _with_snapshot(reason, diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("delegate_io_attention"):
        event = signals["delegate_io_attention"]
        event_id = _safe_text(event.get("event_id")) if isinstance(event, Mapping) else ""
        task_id = _safe_text(event.get("task_id")) if isinstance(event, Mapping) else ""
        reason = f"[DELEGATE-IO] pending delegate_io_attention event: event_id={event_id} task_id={task_id}"
        return _decision("block", reason, diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("active_workflow_session"):
        return _decision("block", "active workflow session detected", diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("owner_ppid_only_ignored"):
        diagnostics["owner_ppid_only_ignored"] = True
        return _decision("approve", _with_snapshot("owner_ppid-only workflow state ignored", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    if not wrapper_mode and signals.get("queued_next_action"):
        next_action = signals["queued_next_action"]
        skill = source = ""
        if isinstance(next_action, Mapping):
            skill = _safe_text(next_action.get("expected_skill") or next_action.get("skill"))
            source = _safe_text(next_action.get("source_id") or next_action.get("source"))
        side_effects.append({"kind": "persist_block_state", "reason": "queued_next_action"})
        return _decision("block", f"queued next_action present (skill={skill or '-'} source={source or '-'})", diagnostics=diagnostics, side_effects=side_effects)
    if not wrapper_mode and signals.get("agile_loop_active"):
        side_effects.append({"kind": "persist_block_state", "reason": "agile_loop_active"})
        return _decision("block", "agile loop active", diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("workflow_active"):
        next_action = signals.get("queued_next_action")
        side_effects.append({"kind": "persist_block_state", "reason": "workflow_active"})
        return _decision(
            "block",
            _workflow_reason(diagnostics, next_action if isinstance(next_action, Mapping) else None),
            diagnostics=diagnostics,
            side_effects=side_effects,
        )
    if signals.get("queued_next_action"):
        next_action = signals["queued_next_action"]
        skill = source = ""
        if isinstance(next_action, Mapping):
            skill = _safe_text(next_action.get("expected_skill") or next_action.get("skill"))
            source = _safe_text(next_action.get("source_id") or next_action.get("source"))
        side_effects.append({"kind": "persist_block_state", "reason": "queued_next_action"})
        return _decision("block", f"queued next_action present (skill={skill or '-'} source={source or '-'})", diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("agile_loop_active"):
        side_effects.append({"kind": "persist_block_state", "reason": "agile_loop_active"})
        return _decision("block", "[AGILE-CONTINUE] objective-check requires continuation", diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("boundary_repair_required"):
        reason = "boundary repair required" if signals["boundary_repair_required"] is True else str(signals["boundary_repair_required"])
        side_effects.append({"kind": "boundary_repair", "reason": reason})
        return _decision("block", _with_snapshot(reason, diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    if signals.get("snapshot_terminal_or_unhandled"):
        snap = signals["snapshot_terminal_or_unhandled"]
        if isinstance(snap, Mapping) and snap.get("current") == snap.get("total") and snap.get("status") == "committed":
            return _decision("approve", _with_snapshot("completion", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
        if isinstance(snap, Mapping) and snap.get("status") in ("", "none"):
            return _decision("approve", _with_snapshot("unhandled_path fallback", diagnostics), diagnostics=diagnostics, side_effects=side_effects)

    if wrapper_mode:
        return _decision("approve", _with_snapshot("workflow_inactive", diagnostics), diagnostics=diagnostics, side_effects=side_effects)
    return _decision("approve", "approved", diagnostics=diagnostics, side_effects=side_effects)


def format_stop_judge_wrapper_payload(decision: Mapping[str, Any]) -> dict[str, str]:
    return {"decision": str(decision.get("decision") or "approve"), "reason": str(decision.get("reason") or "approved")}


def apply_stop_judge_side_effects(*, project_root: Path, decision: Mapping[str, Any]) -> list[dict[str, Any]]:
    del project_root
    return [deepcopy(item) for item in list(decision.get("side_effects") or []) if isinstance(item, dict)]


def evaluate_stop_judge(
    *,
    project_root: Path,
    stdin_file: Path,
    hook_timeout_ms: int = DEFAULT_HOOK_TIMEOUT_MS,
) -> dict[str, Any]:
    try:
        raw_stdin = stdin_file.read_text(encoding="utf-8")
    except OSError as exc:
        context = collect_stop_judge_context(project_root=project_root, payload={}, hook_timeout_ms=hook_timeout_ms, failsafe="startup_failure", diagnostics={"stdin_file_error": str(exc)})
        return reduce_stop_judge_decision(context)
    try:
        payload = json.loads(raw_stdin or "{}")
    except json.JSONDecodeError as exc:
        context = collect_stop_judge_context(project_root=project_root, payload={}, raw_stdin=raw_stdin, hook_timeout_ms=hook_timeout_ms, failsafe="invalid_stdin", diagnostics={"stdin_json_error": str(exc)})
        return reduce_stop_judge_decision(context)
    if not isinstance(payload, dict):
        context = collect_stop_judge_context(project_root=project_root, payload={}, raw_stdin=raw_stdin, hook_timeout_ms=hook_timeout_ms, failsafe="invalid_stdin", diagnostics={"stdin_json_error": "stdin payload must be a JSON object"})
        return reduce_stop_judge_decision(context)
    context = collect_stop_judge_context(project_root=project_root, payload=payload, raw_stdin=raw_stdin, hook_timeout_ms=hook_timeout_ms)
    return reduce_stop_judge_decision(context)


def _emit_runtime_diagnostics(decision: Mapping[str, Any]) -> None:
    diagnostics = decision.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return
    if diagnostics.get("canonical_mst_session_id") is None:
        print("[mst-stop-hook] diagnostic: missing canonical parent MST_SESSION_ID/mst_session_id; no hook identity mutation.", file=sys.stderr)
    if diagnostics.get("owner_ppid_only_ignored"):
        print("[mst-stop-hook] owner_ppid-only workflow state ignored", file=sys.stderr)
    if diagnostics:
        print(json.dumps({"stop_judge_diagnostics": diagnostics}, ensure_ascii=False), file=sys.stderr)


def cmd_hook_stop_judge(args: Any) -> int:
    project_root = _project_root()
    try:
        decision = evaluate_stop_judge(project_root=project_root, stdin_file=Path(args.stdin_file).resolve(), hook_timeout_ms=int(args.hook_timeout_ms))
    except Exception as exc:  # pragma: no cover - defensive fallback for wrapper handoff
        decision = reduce_stop_judge_decision(
            {
                "failsafe": "startup_failure",
                "signals": {},
                "diagnostics": {"startup_exception": str(exc), "wrapper_mode": os.environ.get("MST_STOP_HOOK_WRAPPER") == "1"},
                "side_effects": [],
                "hook_timeout_ms": int(getattr(args, "hook_timeout_ms", DEFAULT_HOOK_TIMEOUT_MS) or DEFAULT_HOOK_TIMEOUT_MS),
            }
        )
    print(json.dumps(format_stop_judge_wrapper_payload(decision), ensure_ascii=False))
    _emit_runtime_diagnostics(decision)
    return 0
