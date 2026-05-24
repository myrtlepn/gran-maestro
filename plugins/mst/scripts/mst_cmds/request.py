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
    iter_request_dirs,
)

ADVERSARIAL_REVIEW_PERSPECTIVES = ("edge", "flow", "persona", "nfr", "integration")
ADVERSARIAL_REVIEW_OUTPUT_SCHEMA = {
    "findings": [
        {
            "type": "...",
            "description": "...",
            "suggested_dod": "...",
            "severity": "critical|major|minor",
        }
    ]
}

def _advance_phase2_result(req_id: str, request_path: Path | None, request_data: dict | None) -> dict:
    if not isinstance(request_data, dict):
        return {
            "req_id": req_id,
            "ready": False,
            "advanced": False,
            "reason": "unknown_request",
            "incomplete_tasks": [],
        }

    completion = _common.phase2_completion_state(request_data)
    return {
        "req_id": req_id,
        "ready": completion["ready"],
        "advanced": False,
        "reason": completion["reason"],
        "incomplete_tasks": completion["incomplete_tasks"],
        "request_path": str(request_path) if request_path is not None else None,
    }


def phase2_status(req_id: str) -> dict:
    normalized_req_id = str(req_id).strip().upper()
    request_path = _common.requests_dir() / normalized_req_id / "request.json"
    request_data = _common.load_json(request_path)
    if not isinstance(request_data, dict):
        return {
            "req_id": normalized_req_id,
            "ready": False,
            "advanced": False,
            "reason": "unknown_request",
            "incomplete_tasks": [],
            "request_path": str(request_path),
        }
    return _advance_phase2_result(normalized_req_id, request_path, request_data)


def advance_phase2_if_ready(req_id: str, *, check: bool = False) -> dict:
    normalized_req_id = str(req_id).strip().upper()
    request_path = _common.requests_dir() / normalized_req_id / "request.json"
    request_data = _common.load_json(request_path)
    result = _advance_phase2_result(normalized_req_id, request_path, request_data)
    reconcile_queue = _common.ensure_request_phase2_reconcile_actions(
        normalized_req_id,
        request_data=request_data,
    )
    if reconcile_queue.get("attempt_count") or reconcile_queue.get("manual_reconcile_required"):
        result["reconcile_queue"] = reconcile_queue
    if not result["ready"] or check:
        return result

    review_summary = request_data.get("review_summary")
    if not isinstance(review_summary, dict):
        review_summary = {}
    else:
        review_summary = dict(review_summary)

    review_status = str(review_summary.get("status") or "").strip().lower()
    if review_status not in {"passed", "failed"}:
        review_summary["status"] = "pending_phase3_review"

    updated = copy.deepcopy(request_data)
    updated["current_phase"] = 3
    updated["status"] = "phase3_review"
    updated["review_summary"] = review_summary
    _common.save_json(request_path, updated)

    result["advanced"] = True
    return result


def record_phase2_dispatch_attempt(req_id: str, **kwargs) -> dict:
    return _common.record_phase2_dispatch_attempt(req_id, **kwargs)


def _print_phase2_dispatch_attempt_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    print(
        f"{result.get('task_num')}: recorded phase2 dispatch attempt "
        f"{result.get('attempt_id')} ({result.get('task_id')})"
    )


def _print_advance_phase2_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    if result.get("advanced"):
        print(f"{result.get('req_id')}: advanced to phase3_review")
    elif result.get("ready"):
        print(f"{result.get('req_id')}: ready for phase3_review")
    else:
        print(f"{result.get('req_id')}: not ready ({result.get('reason')})")


def _advance_phase2_guard_blocked_result(req_id: str) -> dict:
    return {
        "req_id": str(req_id).strip().upper(),
        "ready": False,
        "advanced": False,
        "reason": "guard_blocked",
        "guard_blocked": True,
        "guard_message": "canonical read-only guard blocked phase transition",
        "incomplete_tasks": [],
    }


def _load_adversarial_review_config() -> dict:
    plugin_root = _common._plugin_root()
    defaults = _common.load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    resolved = _common.load_json(_common.BASE_DIR / "config.resolved.json") or {}
    overrides = _common.load_json(_common.BASE_DIR / "config.json") or {}
    merged = _common.deep_merge(defaults, resolved)
    merged = _common.deep_merge(merged, overrides)
    agile_cfg = merged.get("agile") if isinstance(merged, dict) else {}
    review_cfg = agile_cfg.get("adversarial_review") if isinstance(agile_cfg, dict) else {}
    return review_cfg if isinstance(review_cfg, dict) else {}


def _validate_adversarial_review_enabled(perspective: str) -> int:
    review_cfg = _load_adversarial_review_config()
    if review_cfg.get("enabled", True) is False:
        print("adversarial_review is globally disabled", file=sys.stderr)
        return 2
    perspectives = review_cfg.get("perspectives")
    perspectives = perspectives if isinstance(perspectives, dict) else {}
    perspective_cfg = perspectives.get(perspective)
    perspective_cfg = perspective_cfg if isinstance(perspective_cfg, dict) else {}
    if perspective_cfg.get("enabled", True) is False:
        print(f"perspective '{perspective}' is disabled", file=sys.stderr)
        return 2
    return 0


def _adversarial_review_template_path(perspective: str) -> Path:
    return (
        _common._plugin_root()
        / "scripts"
        / "adversarial_review"
        / "perspectives"
        / f"{perspective}.md"
    ).resolve()


def _emit_adversarial_review_payload(context_files: List[Path], perspective: str) -> int:
    payload = {
        "context_files": [str(path.resolve()) for path in context_files],
        "role_template": str(_adversarial_review_template_path(perspective)),
        "output_schema": ADVERSARIAL_REVIEW_OUTPUT_SCHEMA,
        "perspective": perspective,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0

def format_table_row(req_id, data):
    status = data.get("status", "?")
    phase = data.get("current_phase", "?")
    title = (data.get("title") or "")[:55]
    return f"{req_id:<12} P{phase:<3} {status:<28} {title}"

def cmd_request_list(args):
    rows = []
    include_completed = (args.scope == "all")
    for req_id, path, data in iter_request_dirs(include_completed):
        status = data.get("status", "")
        if args.scope == "active" and status == "completed":
            continue
        if args.scope == "completed" and status != "completed":
            continue
        rows.append((req_id, data))

    if args.format == "json":
        for req_id, data in rows:
            print(json.dumps({"id": req_id, **data}))
    else:
        print(f"{'ID':<12} {'Phase':<4} {'Status':<28} {'Title'}")
        print("-" * 80)
        for req_id, data in rows:
            print(format_table_row(req_id, data))
    return 0

def cmd_request_inspect(args):
    req_id = args.req_id.upper()
    for rid, path, data in iter_request_dirs(include_completed=True):
        if rid == req_id:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            # also show task specs if present
            tasks_dir = path / "tasks"
            if tasks_dir.exists():
                for task_path in sorted(tasks_dir.iterdir()):
                    spec = task_path / "spec.md"
                    if spec.exists():
                        print(f"\n--- {task_path.name}/spec.md ---")
                        print(spec.read_text(encoding="utf-8")[:2000])
            return 0
    print(f"Error: {req_id} not found.", file=sys.stderr)
    return 1

def cmd_request_history(args):
    rows = []
    for req_id, path, data in iter_request_dirs(include_completed=True):
        if data.get("status") == "completed":
            rows.append((req_id, data))
    if not rows:
        print("No completed requests found.")
        return 0
    print(f"{'ID':<12} {'Status':<28} {'Title'}")
    print("-" * 80)
    for req_id, data in rows:
        print(format_table_row(req_id, data))
    return 0

def cmd_request_filter(args):
    for req_id, path, data in iter_request_dirs(include_completed=False):
        if args.phase is not None and data.get("current_phase") != args.phase:
            continue
        # pending_dependency는 --status 명시 없는 한 기본 제외
        if not args.status and data.get("status") == "pending_dependency":
            continue
        if args.status and data.get("status") != args.status:
            continue
        if args.priority and data.get("priority", "normal") != args.priority:
            continue
        if args.format == "json":
            print(json.dumps({"id": req_id, **data}))
        else:
            print(format_table_row(req_id, data))
    return 0

def cmd_request_count(args):
    count = 0
    include_completed = (args.scope == "all")
    for req_id, path, data in iter_request_dirs(include_completed):
        status = data.get("status", "")
        if args.scope == "active" and status == "completed":
            continue
        if args.scope == "completed" and status != "completed":
            continue
        count += 1
    print(count)
    return 0

def cmd_request_cancel(args):
    req_id = args.req_id.upper()
    for rid, path, data in iter_request_dirs(include_completed=True):
        if rid == req_id:
            if data.get("status") == "cancelled":
                print(f"{req_id} is already cancelled.")
                return 0
            from scripts._state_manager import cancel
            cancel(_common.BASE_DIR, req_id)
            print(f"Cancelled: {req_id}")
            return 0
    print(f"Error: {req_id} not found.", file=sys.stderr)
    return 1

def cmd_request_set_phase(args):
    """REQ의 current_phase와 status를 원자적으로 변경."""
    from scripts.mst_cmds.state import _check_read_only
    from scripts._state_manager import set_phase

    read_only_status = _check_read_only(args.req_id)
    if read_only_status:
        return read_only_status
    set_phase(_common.BASE_DIR, args.req_id, args.phase, args.status)
    print(f"{args.req_id}: phase={args.phase}, status={args.status}")
    return 0


def cmd_request_phase2_status(args):
    result = phase2_status(args.req_id)
    _print_advance_phase2_result(result, args.json)
    return 0


def cmd_request_advance_phase2_if_ready(args):
    if not args.check:
        from scripts.mst_cmds.state import _check_read_only

        read_only_status = _check_read_only(args.req_id)
        if read_only_status:
            if args.json:
                _print_advance_phase2_result(
                    _advance_phase2_guard_blocked_result(args.req_id),
                    True,
                )
            return read_only_status
    result = advance_phase2_if_ready(args.req_id, check=args.check)
    _print_advance_phase2_result(result, args.json)
    return 0


def cmd_request_record_phase2_dispatch_attempt(args):
    from scripts.mst_cmds.state import _check_read_only

    read_only_status = _check_read_only(args.req_id)
    if read_only_status:
        return read_only_status

    result = record_phase2_dispatch_attempt(
        args.req_id,
        task_num=args.task_num,
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        dispatched_at=args.dispatched_at,
        agent=args.agent,
        worktree_path=args.worktree_path,
        log_path=args.log_path,
        expected_task_status_before=args.expected_task_status_before,
        status=args.status,
        run_state_path=args.run_state_path,
    )
    _print_phase2_dispatch_attempt_result(result, args.json)
    return 0


def cmd_request_takeover(args):
    from scripts.mst_cmds.state import cmd_takeover_request

    return cmd_takeover_request(args)


def cmd_request_review(args):
    perspective = str(args.perspective).strip()
    enabled_status = _validate_adversarial_review_enabled(perspective)
    if enabled_status:
        return enabled_status

    req_path = Path(args.req_path).expanduser().resolve()
    if not req_path.exists() or not req_path.is_dir():
        print(f"Error: request not found: {req_path}", file=sys.stderr)
        return 1

    context_files = sorted((req_path / "tasks").glob("*/spec.md"))
    if not context_files:
        print(f"Error: request specs not found: {req_path}", file=sys.stderr)
        return 1

    return _emit_adversarial_review_payload(context_files, perspective)


def register(subparsers):
    sub = subparsers
    req = sub.add_parser("request")
    req_sub = req.add_subparsers(dest="subcommand")

    req_list = req_sub.add_parser("list")
    req_list.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    req_list.add_argument("--all", dest="scope", action="store_const", const="all")
    req_list.add_argument("--completed", dest="scope", action="store_const", const="completed")
    req_list.add_argument("--format", choices=["table", "json"], default="table")

    req_inspect = req_sub.add_parser("inspect")
    req_inspect.add_argument("req_id")

    req_history = req_sub.add_parser("history")
    req_history.add_argument("--all", action="store_true")

    req_filter = req_sub.add_parser("filter")
    req_filter.add_argument("--phase", type=int)
    req_filter.add_argument("--status")
    req_filter.add_argument("--priority")
    req_filter.add_argument("--format", choices=["table", "json"], default="table")

    req_count = req_sub.add_parser("count")
    req_count.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    req_count.add_argument("--all", dest="scope", action="store_const", const="all")
    req_count.add_argument("--completed", dest="scope", action="store_const", const="completed")

    req_cancel = req_sub.add_parser("cancel")
    req_cancel.add_argument("req_id")

    req_takeover = req_sub.add_parser("takeover")
    req_takeover.add_argument("--id", required=True)

    req_set_phase = req_sub.add_parser("set-phase")
    req_set_phase.add_argument("req_id")
    req_set_phase.add_argument("phase", type=int)
    req_set_phase.add_argument("status")

    req_phase2_status = req_sub.add_parser("phase2-status")
    req_phase2_status.add_argument("req_id")
    req_phase2_status.add_argument("--json", action="store_true")

    req_advance_phase2 = req_sub.add_parser("advance-phase2-if-ready")
    req_advance_phase2.add_argument("req_id")
    req_advance_phase2.add_argument("--check", action="store_true")
    req_advance_phase2.add_argument("--json", action="store_true")

    req_record_phase2_dispatch_attempt = req_sub.add_parser("record-phase2-dispatch-attempt")
    req_record_phase2_dispatch_attempt.add_argument("req_id")
    req_record_phase2_dispatch_attempt.add_argument("--task-num", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--task-id", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--attempt-id", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--dispatched-at", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--agent", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--worktree-path", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--log-path", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--expected-task-status-before", required=True)
    req_record_phase2_dispatch_attempt.add_argument("--status")
    req_record_phase2_dispatch_attempt.add_argument("--run-state-path")
    req_record_phase2_dispatch_attempt.add_argument("--json", action="store_true")

    req_review = req_sub.add_parser("review")
    req_review.add_argument("--req-path", required=True)
    req_review.add_argument("--perspective", required=True, choices=ADVERSARIAL_REVIEW_PERSPECTIVES)
    req_review.add_argument("--json", action="store_true", required=True)
