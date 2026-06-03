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
    load_json,
    save_json,
)

def cmd_task_set_commit(args):
    task_id = args.task_id.upper()
    match = re.match(r"^(REQ-\d+)-T(\d{2})$", task_id)
    if not match:
        print(
            f"Error: invalid task ID '{args.task_id}'. "
            "Expected REQ-NNN-TNN format.",
            file=sys.stderr
        )
        return 1

    if not args.commit_hash:
        print("Error: commit hash is required.", file=sys.stderr)
        return 1

    req_id = match.group(1)

    request_paths = [
        _common.BASE_DIR / "requests" / req_id / "request.json",
        _common.BASE_DIR / "requests" / "completed" / req_id / "request.json",
    ]
    request_path = next((p for p in request_paths if p.exists()), None)
    if request_path is None:
        print(f"Error: request.json not found for {req_id}", file=sys.stderr)
        return 1

    data = load_json(request_path)
    if data is None:
        print(f"Error: failed to load request.json for {req_id}", file=sys.stderr)
        return 1

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        print(f"Error: tasks field not found in {request_path}", file=sys.stderr)
        return 1

    for task in tasks:
        if isinstance(task, dict) and task.get("id", "").upper() == task_id:
            task["commit_hash"] = args.commit_hash
            task["commit_message"] = args.commit_message or ""
            branch = str(getattr(args, "branch", "") or "").strip()
            worktree_path = str(getattr(args, "worktree_path", "") or "").strip()
            if branch:
                task["branch"] = branch
            if worktree_path:
                task["worktree_path"] = worktree_path
            break
    else:
        print(f"Error: task {task_id} not found in request.json", file=sys.stderr)
        return 1

    save_json(request_path, data)
    print(f"commit metadata saved: {task_id}")
    return 0


def register(subparsers):
    sub = subparsers
    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="subcommand")
    task_set_commit = task_sub.add_parser("set-commit")
    task_set_commit.add_argument("task_id")
    task_set_commit.add_argument("commit_hash", nargs="?")
    task_set_commit.add_argument("commit_message", nargs="?")
    task_set_commit.add_argument("--branch")
    task_set_commit.add_argument("--worktree-path")
