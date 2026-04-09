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
    load_json,
    save_json,
)

def cmd_priority(args):
    task_id = args.task_id.upper()
    parts = task_id.split("-")
    if len(parts) != 3:
        print(f"Error: invalid task ID '{args.task_id}'. Expected REQ-XXX-YY format.", file=sys.stderr)
        return 1

    req_id = f"{parts[0]}-{parts[1]}"
    task_num = parts[2]

    status_paths = [
        _common.BASE_DIR / "requests" / req_id / "tasks" / task_num / "status.json",
        _common.BASE_DIR / "requests" / "completed" / req_id / "tasks" / task_num / "status.json",
    ]
    status_path = next((p for p in status_paths if p.exists()), None)
    if status_path is None:
        print(f"Error: task {args.task_id} not found", file=sys.stderr)
        return 1

    data = load_json(status_path)
    if data is None:
        print(f"Error: failed to load status.json for {args.task_id}", file=sys.stderr)
        return 1

    if args.before:
        data["priority"] = "high"
        data["priority_before"] = args.before.upper()
        data.pop("priority_after", None)
    elif args.after:
        data["priority"] = "low"
        data["priority_after"] = args.after.upper()
        data.pop("priority_before", None)
    else:
        data["priority"] = "normal"
        data.pop("priority_before", None)
        data.pop("priority_after", None)

    save_json(status_path, data)
    print(f"priority updated: {task_id}")
    return 0


def register(subparsers):
    sub = subparsers
    pri = sub.add_parser("priority")
    pri.add_argument("task_id")
    pri.add_argument("--before")
    pri.add_argument("--after")
