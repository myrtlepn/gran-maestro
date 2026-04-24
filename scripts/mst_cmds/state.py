from __future__ import annotations

import argparse
import copy
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
from scripts.mst_cmds import _common
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

def _resolve_owner_ppid() -> int:
    ppid_env = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid_env.isdigit():
        return int(ppid_env)
    return os.getppid()


def _snapshot_session_id() -> str:
    session_env = os.environ.get("MST_SNAPSHOT_SESSION_ID", "").strip()
    if session_env:
        return session_env
    ppid_env = os.environ.get("MST_STATE_PPID", "").strip()
    if ppid_env:
        return ppid_env
    return str(os.getppid())


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
    if session_id.variant != uuid.RFC_4122 or canonical != raw_value:
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
    session_id = _resolve_owner_session_id(ppid)

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


def cmd_state_set_workflow(args):
    state_base_dir = _skill_state_base_dir()
    state_path = _workflow_state_file(state_base_dir)
    now = _workflow_state_timestamp()

    try:
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            payload = _workflow_state_default_payload(now)

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            next_action = {}

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
        _workflow_state_atomic_write(state_path, payload)

        if args.active:
            _inject_owner_metadata_if_missing(args)

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
    except Exception as exc:
        print(f"[mst] warning: failed to update workflow state: {exc}", file=sys.stderr)
        return 0

    return 0

def cmd_state_set(args):
    from scripts._skill_state import set_snapshot
    from scripts._flow_logger import append_skill_event, flow_log_path, safe_session_id

    state_base_dir = _skill_state_base_dir()
    project_root = state_base_dir.parent
    session_id = _snapshot_session_id()
    data = set_snapshot(
        state_base_dir,
        skill=args.skill,
        step=args.step,
        total=args.total,
        return_to=args.return_to,
        session_id=session_id,
    )
    try:
        parent_skill, parent_step = _parse_return_to_parent(args.return_to)
        flow_path = flow_log_path(project_root, rotate=True)
        log_session_id = safe_session_id(session_id)
        duration_ms = _previous_enter_duration_ms(flow_path, log_session_id, args.skill)
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
                rotate=True,
            )
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_get(args):
    from scripts._skill_state import get_snapshot

    data = get_snapshot(_skill_state_base_dir(), session_id=_snapshot_session_id())
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0

def cmd_state_clear(args):
    from scripts._skill_state import clear_snapshot

    clear_snapshot(_skill_state_base_dir(), session_id=_snapshot_session_id())
    print("스냅샷 초기화 완료")
    return 0


def cmd_state_mark_paused(args):
    from scripts._skill_state import mark_paused

    data = mark_paused(_skill_state_base_dir(), session_id=args.session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_resume_paused(args):
    from scripts._skill_state import resume_paused

    data = resume_paused(_skill_state_base_dir(), session_id=args.session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
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

    state_mark_paused = state_sub.add_parser("mark-paused")
    state_mark_paused.add_argument("--session-id", required=True)

    state_resume_paused = state_sub.add_parser("resume-paused")
    state_resume_paused.add_argument("--session-id", required=True)

    state_paused_count = state_sub.add_parser("paused-count")
    state_paused_count.add_argument("--session-id", required=True)
