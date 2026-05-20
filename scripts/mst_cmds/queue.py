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
    _compact_json,
    _parse_bool_arg,
    QUEUE_NON_SUCCESS_TERMINAL_STATUSES,
    QUEUE_TERMINAL_STATUSES,
    queue_complete,
    queue_count,
    queue_enqueue,
    queue_finalize,
    queue_fail,
    queue_list,
    queue_peek,
    queue_pop,
)

def _print_queue_value(value, as_json: bool):
    if value is None:
        print("null")
        return

    if as_json:
        print(_compact_json(value))
        return

    if isinstance(value, list):
        if not value:
            print("(empty)")
            return
        for entry in value:
            print(
                f"{entry.get('id', '')}  {entry.get('status', '')}  "
                f"{entry.get('skill', '')}  {entry.get('args', '')}"
            )
        return

    print(
        f"{value.get('id', '')}  {value.get('status', '')}  "
        f"{value.get('skill', '')}  {value.get('args', '')}"
    )
def _headless_terminal_reason(entry: dict, terminal_status: str) -> str | None:
    reason = str(entry.get("headless_terminal_reason") or "").strip()
    if reason:
        return reason
    defaults = {
        "failed": "headless queue item failed",
        "empty_result": "headless queue item returned no result",
        "blocked": "headless queue item is blocked",
    }
    return defaults.get(terminal_status)
def _headless_next_action(entry: dict) -> dict | None:
    payload = entry.get("headless_next_action")
    return copy.deepcopy(payload) if isinstance(payload, dict) else None
def _write_json_file(path_value: str, payload: dict) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def _headless_completion_evidence(entry: dict, terminal_status: str, reason: str | None) -> dict:
    evidence = {
        "entry_id": entry.get("entry_id"),
        "id": entry.get("id"),
        "skill": entry.get("skill"),
        "args": entry.get("args"),
        "resource_id": entry.get("resource_id"),
        "source_skill": entry.get("source_skill"),
        "source_id": entry.get("source_id"),
        "terminal_status": terminal_status,
        "idempotency_key": entry.get("idempotency_key"),
        "next_action_idempotency_key": entry.get("next_action_idempotency_key"),
        "completion_evidence_path": entry.get("completion_evidence_path"),
        "failure_metadata_path": entry.get("failure_metadata_path"),
        "canonical_session_id": entry.get("canonical_session_id"),
        "mst_session_id": entry.get("mst_session_id"),
        "queue_session_id": entry.get("queue_session_id"),
        "legacy_diagnostics": copy.deepcopy(entry.get("legacy_diagnostics"))
        if isinstance(entry.get("legacy_diagnostics"), dict)
        else None,
    }
    if reason:
        evidence["reason"] = reason
    next_action = _headless_next_action(entry)
    if next_action:
        evidence["next_action"] = next_action
    return evidence
def _headless_failure_payload(entry: dict, terminal_status: str, reason: str) -> dict:
    payload = _headless_completion_evidence(entry, terminal_status, reason)
    payload["reason"] = reason
    return payload

def cmd_queue_enqueue(args):
    entry = queue_enqueue(
        {
            "skill": args.skill,
            "args": args.args,
            "source_skill": args.source_skill,
            "source_id": args.source_id,
            "resource_id": args.resource_id,
            "auto": args.auto,
        }
    )
    _print_queue_value(entry, args.json)
    return 0

def cmd_queue_peek(args):
    _print_queue_value(queue_peek(), args.json)
    return 0

def cmd_queue_pop(args):
    _print_queue_value(queue_pop(), args.json)
    return 0

def cmd_queue_list(args):
    _print_queue_value(queue_list(args.status), args.json)
    return 0

def cmd_queue_complete(args):
    _print_queue_value(queue_complete(args.id, result=args.result), args.json)
    return 0

def cmd_queue_fail(args):
    _print_queue_value(queue_fail(args.id, error=args.error), args.json)
    return 0

def cmd_queue_count(args):
    count = queue_count(args.status)
    if args.json:
        print(_compact_json({"status": args.status, "count": count}))
    else:
        print(count)
    return 0
def cmd_queue_drain_headless(args):
    entry = queue_pop()
    if entry is None:
        payload = {"status": "empty", "reason": "queue_empty"}
        _print_queue_value(payload, True if args.json else True)
        return 0

    terminal_status = str(entry.get("status") or "").strip()
    if terminal_status == "consumed":
        payload = {"status": "duplicate", "action": entry}
        _print_queue_value(payload, True if args.json else True)
        return 0

    terminal_status = str(entry.get("headless_terminal_status") or "done").strip() or "done"
    if terminal_status not in QUEUE_TERMINAL_STATUSES - {"consumed"}:
        terminal_status = "failed"
    reason = _headless_terminal_reason(entry, terminal_status)

    evidence = _headless_completion_evidence(entry, terminal_status, reason)
    _write_json_file(str(entry["completion_evidence_path"]), evidence)

    extra_fields = {
        "canonical_session_id": entry.get("canonical_session_id"),
        "mst_session_id": entry.get("mst_session_id"),
        "queue_session_id": entry.get("queue_session_id"),
        "completion_evidence_path": entry.get("completion_evidence_path"),
        "failure_metadata_path": entry.get("failure_metadata_path"),
        "next_action_idempotency_key": entry.get("next_action_idempotency_key"),
        "legacy_diagnostics": copy.deepcopy(entry.get("legacy_diagnostics"))
        if isinstance(entry.get("legacy_diagnostics"), dict)
        else None,
    }

    if terminal_status in QUEUE_NON_SUCCESS_TERMINAL_STATUSES:
        failure_payload = _headless_failure_payload(entry, terminal_status, reason or terminal_status)
        _write_json_file(str(entry["failure_metadata_path"]), failure_payload)
        finalized = queue_finalize(
            str(entry.get("entry_id") or entry.get("id") or ""),
            terminal_status=terminal_status,
            error=reason or terminal_status,
            extra_fields=extra_fields,
        )
    else:
        finalized = queue_finalize(
            str(entry.get("entry_id") or entry.get("id") or ""),
            terminal_status="done",
            result="ok",
            extra_fields=extra_fields,
        )

    payload = {"status": "drained", "action": finalized}
    _print_queue_value(payload, True if args.json else True)
    return 0


def register(subparsers):
    sub = subparsers
    queue = sub.add_parser("queue")
    queue_sub = queue.add_subparsers(dest="subcommand")

    queue_enqueue_cmd = queue_sub.add_parser("enqueue")
    queue_enqueue_cmd.add_argument("--skill", required=True)
    queue_enqueue_cmd.add_argument("--args", required=True)
    queue_enqueue_cmd.add_argument("--source-skill", dest="source_skill", default="")
    queue_enqueue_cmd.add_argument("--source-id", dest="source_id", default="")
    queue_enqueue_cmd.add_argument("--resource-id", dest="resource_id", default="")
    queue_enqueue_cmd.add_argument("--auto", type=_parse_bool_arg, default=False)
    queue_enqueue_cmd.add_argument("--json", action="store_true")

    queue_peek_cmd = queue_sub.add_parser("peek")
    queue_peek_cmd.add_argument("--json", action="store_true")

    queue_pop_cmd = queue_sub.add_parser("pop")
    queue_pop_cmd.add_argument("--json", action="store_true")

    queue_list_cmd = queue_sub.add_parser("list")
    queue_list_cmd.add_argument(
        "--status",
        choices=["queued", "running", "done", "failed", "blocked", "empty_result", "consumed", "cancelled", "all"],
        default="all",
    )
    queue_list_cmd.add_argument("--json", action="store_true")

    queue_complete_cmd = queue_sub.add_parser("complete")
    queue_complete_cmd.add_argument("--id", required=True)
    queue_complete_cmd.add_argument("--result", default=None)
    queue_complete_cmd.add_argument("--json", action="store_true")

    queue_fail_cmd = queue_sub.add_parser("fail")
    queue_fail_cmd.add_argument("--id", required=True)
    queue_fail_cmd.add_argument("--error", default=None)
    queue_fail_cmd.add_argument("--json", action="store_true")

    queue_count_cmd = queue_sub.add_parser("count")
    queue_count_cmd.add_argument(
        "--status",
        choices=["queued", "running", "done", "failed", "blocked", "empty_result", "consumed", "cancelled"],
        default="queued",
    )
    queue_count_cmd.add_argument("--json", action="store_true")

    queue_drain_headless_cmd = queue_sub.add_parser("drain-headless")
    queue_drain_headless_cmd.add_argument("--json", action="store_true")
