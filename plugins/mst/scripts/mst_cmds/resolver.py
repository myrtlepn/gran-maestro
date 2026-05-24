from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

from scripts._skill_state import load_snapshot
from scripts.mst_cmds.env_alias_compat import legacy_session_id_from_env
from scripts.mst_cmds._common import _skill_state_base_dir, queue_enqueue, queue_peek
from scripts.mst_cmds._state_manager import read_workflow_state

ResolveSource = Literal["queue", "workflow_state", "wakeup-hint:stop-recover", "no-op"]


class ResolveResult(TypedDict):
    command: Optional[str]
    source: ResolveSource


class WorkflowAction(TypedDict, total=False):
    skill: str
    expected_skill: str
    source: str
    source_skill: str
    source_id: str
    args: str
    auto: bool
    auto_mode: bool


def _compact_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _normalize_skill_command(skill: object) -> str:
    value = str(skill or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        return value
    if value.startswith("mst:"):
        return f"/{value}"
    return f"/mst:{value}"


def _normalize_queue_skill(skill: object) -> str:
    value = str(skill or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        value = value[1:]
    if value.startswith("mst:"):
        return value
    return f"mst:{value}"


def _command_from_shards(skill: object, args: object = "") -> Optional[str]:
    command = _normalize_skill_command(skill)
    if not command:
        return None
    args_text = str(args or "").strip()
    return f"{command} {args_text}" if args_text else command


def _source_args(skill: str, source_id: str) -> str:
    if not source_id:
        return ""
    if skill in ("mst:request", "/mst:request", "request") and source_id.startswith("PLN-"):
        return f"--plan {source_id}"
    return source_id


def _workflow_action(payload: Optional[dict[str, Any]]) -> Optional[WorkflowAction]:
    if not isinstance(payload, dict) or payload.get("workflow_active") is not True:
        return None
    value = payload.get("next_action")
    if not isinstance(value, dict):
        return None
    skill = str(value.get("expected_skill") or value.get("skill") or "").strip()
    if not skill:
        return None
    action: WorkflowAction = {
        "skill": skill,
        "expected_skill": skill,
        "source": str(value.get("source") or "").strip(),
        "source_skill": str(value.get("source_skill") or "").strip(),
        "source_id": str(value.get("source_id") or value.get("source") or "").strip(),
        "args": str(value.get("args") or "").strip(),
        "auto": bool(value.get("auto_mode", value.get("auto", False))),
        "auto_mode": bool(value.get("auto_mode", value.get("auto", False))),
    }
    return action


def _workflow_args(action: WorkflowAction) -> str:
    args_text = str(action.get("args") or "").strip()
    if not args_text:
        args_text = _source_args(str(action.get("skill") or ""), str(action.get("source_id") or ""))
    if bool(action.get("auto_mode", action.get("auto", False))):
        tokens = args_text.split()
        if "-a" not in tokens and "--auto" not in tokens:
            args_text = f"{args_text} -a".strip()
    return args_text


def _enqueue_workflow_action(action: WorkflowAction) -> None:
    queue_enqueue(
        {
            "skill": str(action.get("expected_skill") or action.get("skill") or ""),
            "args": _workflow_args(action),
            "source_skill": str(action.get("source_skill") or ""),
            "source_id": str(action.get("source_id") or ""),
            "resource_id": str(action.get("source_id") or ""),
            "auto": bool(action.get("auto_mode", action.get("auto", False))),
        }
    )


def _conversation_id_from_transcript(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    name = Path(path_value).name
    stem = name[:-6] if name.endswith(".jsonl") else Path(name).stem
    return stem or None


def resolve_conversation_id(explicit: Optional[str] = None) -> Optional[str]:
    if explicit and explicit.strip():
        return explicit.strip()
    env_value = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if env_value:
        return env_value
    for key in ("CLAUDE_TRANSCRIPT_PATH", "TRANSCRIPT_PATH", "MST_TRANSCRIPT_PATH"):
        inferred = _conversation_id_from_transcript(os.environ.get(key, "").strip())
        if inferred:
            return inferred
    return None


def _snapshot_session_candidates(conversation_id: Optional[str]) -> list[str]:
    legacy_session_id, _legacy_alias = legacy_session_id_from_env(warn=True)
    candidates = [
        conversation_id or "",
        legacy_session_id or "",
        str(os.getppid()),
        "default",
    ]
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _return_to_from_env() -> tuple[str, str]:
    skill = (
        os.environ.get("RETURN_TO_SKILL", "").strip()
        or os.environ.get("SNAPSHOT_RETURN_TO_SKILL", "").strip()
    )
    step = (
        os.environ.get("RETURN_TO_STEP", "").strip()
        or os.environ.get("SNAPSHOT_RETURN_TO_STEP", "").strip()
    )
    return skill, step


def _return_to_from_snapshot(conversation_id: Optional[str]) -> tuple[str, str]:
    base_dir = _skill_state_base_dir()
    for session_id in _snapshot_session_candidates(conversation_id):
        snapshot = load_snapshot(base_dir, session_id=session_id)
        if not isinstance(snapshot, dict):
            continue
        value = snapshot.get("returnTo")
        if isinstance(value, dict):
            skill = str(value.get("skill") or "").strip()
            step = str(value.get("step") or "").strip()
            if skill:
                return skill, step
        if isinstance(value, str) and value.strip():
            skill, sep, step = value.partition("/")
            return skill.strip(), step.strip() if sep else ""
    return "", ""


def _stop_recover_action(conversation_id: Optional[str]) -> Optional[WorkflowAction]:
    skill, step = _return_to_from_env()
    if not skill:
        skill, step = _return_to_from_snapshot(conversation_id)
    queue_skill = _normalize_queue_skill(skill)
    if not queue_skill:
        return None
    args = f"(continue from step {step})" if step else ""
    return {
        "skill": queue_skill,
        "expected_skill": queue_skill,
        "source": "wakeup-hint:stop-recover",
        "source_skill": "wakeup-hint",
        "source_id": "stop-recover",
        "args": args,
        "auto": False,
        "auto_mode": False,
    }


def _emit(result: ResolveResult, as_json: bool) -> None:
    if as_json:
        print(_compact_json(result))
        return
    if result["command"]:
        print(result["command"])


def resolve_result(args: argparse.Namespace) -> ResolveResult:
    queue_entry = queue_peek()
    if queue_entry is not None:
        return {
            "command": _command_from_shards(queue_entry.get("skill"), queue_entry.get("args")),
            "source": "queue",
        }

    action = _workflow_action(read_workflow_state())
    if action is not None:
        if bool(getattr(args, "enqueue", False)) and not bool(getattr(args, "dry_run", False)):
            _enqueue_workflow_action(action)
        return {
            "command": _command_from_shards(action.get("skill"), _workflow_args(action)),
            "source": "workflow_state",
        }

    conversation_id = resolve_conversation_id(getattr(args, "conversation_id", None))
    if getattr(args, "wakeup_hint", None) == "stop-recover":
        action = _stop_recover_action(conversation_id)
        if action is not None:
            if bool(getattr(args, "enqueue", False)) and not bool(getattr(args, "dry_run", False)):
                _enqueue_workflow_action(action)
            return {
                "command": _command_from_shards(action.get("skill"), _workflow_args(action)),
                "source": "wakeup-hint:stop-recover",
            }

    return {"command": None, "source": "no-op"}


def resolve_next_action(args: argparse.Namespace) -> int:
    _emit(resolve_result(args), bool(getattr(args, "json", False)))
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("resolve-next-action")
    parser.add_argument("--conversation-id", dest="conversation_id", default=None)
    parser.add_argument("--wakeup-hint", dest="wakeup_hint", default=None)
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
