from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import math
import os
import re
import shlex
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
def _headless_completion_evidence(
    entry: dict,
    terminal_status: str,
    reason: str | None,
    *,
    host_context: dict | None = None,
    execution: dict | None = None,
) -> dict:
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
    if isinstance(host_context, dict):
        evidence["host_context"] = copy.deepcopy(host_context)
        evidence["supervisor_tick"] = {
            "host": host_context.get("host"),
            "tick_source": (host_context.get("adapter") or {}).get("tick_source")
            if isinstance(host_context.get("adapter"), dict)
            else None,
            "queue_entry_id": entry.get("entry_id") or entry.get("id"),
            "skill": entry.get("skill"),
            "args": entry.get("args"),
        }
    if isinstance(execution, dict):
        evidence["execution"] = copy.deepcopy(execution)
    return evidence
def _headless_failure_payload(
    entry: dict,
    terminal_status: str,
    reason: str,
    *,
    host_context: dict | None = None,
    execution: dict | None = None,
) -> dict:
    payload = _headless_completion_evidence(
        entry,
        terminal_status,
        reason,
        host_context=host_context,
        execution=execution,
    )
    payload["reason"] = reason
    return payload

def _queue_host_context(args, entry: dict) -> dict:
    from scripts.mst_cmds import host as host_cmd

    event = str(getattr(args, "event", "") or "queue-drain").strip() or "queue-drain"
    payload = {
        "session_id": entry.get("host_session_id") or entry.get("session_id"),
        "mst_session_id": entry.get("mst_session_id"),
        "permission_mode": entry.get("permission_mode"),
        "model": entry.get("model"),
    }
    return host_cmd.build_host_context(
        host=str(getattr(args, "host", "") or "headless"),
        event=event,
        payload=payload,
    )

def _supervisor_runner_command(args) -> list[str]:
    runner = str(getattr(args, "runner", "") or os.environ.get("MST_SUPERVISOR_RUNNER") or "").strip()
    if not runner:
        return []
    return shlex.split(runner)

def _execute_supervisor_runner(args, entry: dict, host_context: dict) -> tuple[str, str | None, str | None, dict]:
    command = _supervisor_runner_command(args)
    execution = {
        "mode": "runner",
        "runner_configured": bool(command),
        "command": command,
    }
    if not command:
        reason = "supervisor runner not configured"
        execution["status"] = "failed"
        execution["reason"] = reason
        return "failed", None, reason, execution

    request = {
        "entry": copy.deepcopy(entry),
        "host_context": copy.deepcopy(host_context),
        "invocation": {
            "skill": entry.get("skill"),
            "args": entry.get("args"),
            "resource_id": entry.get("resource_id"),
        },
    }
    timeout = float(getattr(args, "execute_timeout", 300.0) or 300.0)
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        reason = f"supervisor runner timed out after {timeout:g}s"
        execution.update(
            {
                "status": "failed",
                "reason": reason,
                "timeout_seconds": timeout,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
        )
        return "failed", None, reason, execution
    except OSError as exc:
        reason = f"supervisor runner failed to start: {exc}"
        execution.update({"status": "failed", "reason": reason})
        return "failed", None, reason, execution

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    execution.update(
        {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    )
    if proc.returncode != 0:
        reason = stderr or stdout or f"supervisor runner exited {proc.returncode}"
        execution.update({"status": "failed", "reason": reason})
        return "failed", None, reason, execution

    if not stdout:
        execution["status"] = "empty_result"
        return "empty_result", None, "supervisor runner returned no result", execution

    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        reason = f"supervisor runner returned invalid JSON: {exc}"
        execution.update({"status": "failed", "reason": reason})
        return "failed", None, reason, execution

    if not isinstance(parsed, dict):
        reason = "supervisor runner returned non-object JSON"
        execution.update({"status": "failed", "reason": reason, "parsed": parsed})
        return "failed", None, reason, execution

    runner_status = str(parsed.get("terminal_status") or parsed.get("status") or "done").strip() or "done"
    if runner_status not in QUEUE_TERMINAL_STATUSES - {"consumed"}:
        runner_status = "failed"
    result_value = parsed.get("result")
    if result_value is None:
        result = "ok" if runner_status == "done" else None
    elif isinstance(result_value, str):
        result = result_value
    else:
        result = json.dumps(result_value, ensure_ascii=False, sort_keys=True)
    reason_value = parsed.get("reason") or parsed.get("error")
    reason = str(reason_value).strip() if reason_value is not None else None
    execution.update({"status": runner_status, "parsed": parsed})
    if reason:
        execution["reason"] = reason
    return runner_status, result, reason, execution

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

    host_context = _queue_host_context(args, entry)
    execution = None

    if getattr(args, "execute", False):
        terminal_status, result, reason, execution = _execute_supervisor_runner(args, entry, host_context)
    else:
        terminal_status = str(entry.get("headless_terminal_status") or "done").strip() or "done"
        if terminal_status not in QUEUE_TERMINAL_STATUSES - {"consumed"}:
            terminal_status = "failed"
        reason = _headless_terminal_reason(entry, terminal_status)
        result = "ok"

    evidence = _headless_completion_evidence(
        entry,
        terminal_status,
        reason,
        host_context=host_context,
        execution=execution,
    )
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
        "host_context": host_context,
        "supervisor_host": host_context.get("host"),
        "supervisor_tick_source": (host_context.get("adapter") or {}).get("tick_source")
        if isinstance(host_context.get("adapter"), dict)
        else None,
    }
    if isinstance(execution, dict):
        extra_fields["execution"] = execution

    if terminal_status in QUEUE_NON_SUCCESS_TERMINAL_STATUSES:
        failure_payload = _headless_failure_payload(
            entry,
            terminal_status,
            reason or terminal_status,
            host_context=host_context,
            execution=execution,
        )
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
            result=result or "ok",
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
    queue_drain_headless_cmd.add_argument(
        "--host",
        choices=["claude", "codex", "headless"],
        default="headless",
    )
    queue_drain_headless_cmd.add_argument("--event", default="queue-drain")
    queue_drain_headless_cmd.add_argument("--execute", action="store_true")
    queue_drain_headless_cmd.add_argument("--runner", default="")
    queue_drain_headless_cmd.add_argument("--execute-timeout", dest="execute_timeout", type=float, default=300.0)
    queue_drain_headless_cmd.add_argument("--json", action="store_true")
