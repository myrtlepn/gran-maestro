from __future__ import annotations

import argparse
import copy
import fcntl
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
    WORKFLOW_MAX_ITERATIONS,
    WORKFLOW_STALL_LIMIT,
    _is_terminal,
    _load_plan,
    _load_request,
    _phase_status_tuple,
    next_action,
)

def _run_claude(cmd):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_common.BASE_DIR.parent),
    )
    if result.stdout:
        print(result.stdout.rstrip("\n"))
    if result.stderr:
        print(result.stderr.rstrip("\n"), file=sys.stderr)
    return result.returncode

def _run_req_workflow(req_id: str, max_iterations: int = WORKFLOW_MAX_ITERATIONS) -> int:
    unchanged_count = 0
    req_id = req_id.upper()

    for _ in range(max_iterations):
        before = _load_request(req_id)
        if not before:
            print(f"[workflow] Request not found: {req_id}", file=sys.stderr)
            return 1
        before_phase, before_status = _phase_status_tuple(before)
        if _is_terminal(before_phase, before_status):
            return 0

        action = next_action(before_phase, before_status)
        if action is None:
            print(
                f"[workflow] No action for state (phase={before_phase}, status={before_status})",
                file=sys.stderr,
            )
            return 1

        _run_claude(["claude", f"/{action}", req_id, "-a"])

        after = _load_request(req_id)
        if not after:
            print(f"[workflow] Request not found after action: {req_id}", file=sys.stderr)
            return 1
        after_phase, after_status = _phase_status_tuple(after)

        if _is_terminal(after_phase, after_status):
            return 0

        if (after_phase, after_status) == (before_phase, before_status):
            unchanged_count += 1
            if unchanged_count >= WORKFLOW_STALL_LIMIT:
                print(
                    f"[workflow] Stalled: (phase={after_phase}, status={after_status}) unchanged for 3 iterations",
                    file=sys.stderr,
                )
                return 1
        else:
            unchanged_count = 0

    print(f"[workflow] Max iterations ({max_iterations}) reached", file=sys.stderr)
    return 1

def _plan_linked_requests(pln_id: str):
    plan = _load_plan(pln_id)
    if not plan:
        return []
    linked = plan.get("linked_requests")
    if not isinstance(linked, list):
        return []
    return [req_id.upper() for req_id in linked if isinstance(req_id, str)]

def _incomplete_requests(req_ids):
    incomplete = []
    for req_id in req_ids:
        req = _load_request(req_id)
        if not req:
            continue
        phase, status = _phase_status_tuple(req)
        if not _is_terminal(phase, status):
            incomplete.append(req_id)
    return incomplete

def _topo_sort_requests(req_ids):
    index_map = {req_id: idx for idx, req_id in enumerate(req_ids)}
    indegree = {req_id: 0 for req_id in req_ids}
    graph = {req_id: [] for req_id in req_ids}

    for req_id in req_ids:
        req = _load_request(req_id) or {}
        deps = req.get("dependencies")
        if not isinstance(deps, dict):
            continue
        blocked_by = deps.get("blockedBy")
        if not isinstance(blocked_by, list):
            continue
        for dep in blocked_by:
            dep_id = dep.upper() if isinstance(dep, str) else None
            if dep_id not in indegree:
                continue
            indegree[req_id] += 1
            graph[dep_id].append(req_id)

    ready = sorted(
        [req_id for req_id, degree in indegree.items() if degree == 0],
        key=lambda req_id: index_map[req_id],
    )
    ordered = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for nxt in graph[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda req_id: index_map[req_id])

    if len(ordered) == len(req_ids):
        return ordered
    return sorted(req_ids, key=lambda req_id: index_map[req_id])

def cmd_workflow_run(args):
    target = args.target.upper()

    if target.startswith("REQ-"):
        return _run_req_workflow(target)

    if not target.startswith("PLN-"):
        print("Error: target must be PLN-NNN or REQ-NNN.", file=sys.stderr)
        return 1

    linked = _plan_linked_requests(target)
    pending = _incomplete_requests(linked)

    if not pending:
        _run_claude(["claude", "/mst:request", "--plan", target, "-a"])
        linked = _plan_linked_requests(target)
        pending = _incomplete_requests(linked)
        if not pending:
            print(f"[workflow] No runnable requests linked to {target}", file=sys.stderr)
            return 1

    for req_id in _topo_sort_requests(pending):
        result = _run_req_workflow(req_id)
        if result != 0:
            return result
    return 0


def register(subparsers):
    sub = subparsers
    workflow = sub.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="subcommand")
    workflow_run = workflow_sub.add_parser("run")
    workflow_run.add_argument("target", help="PLN-NNN 또는 REQ-NNN")
