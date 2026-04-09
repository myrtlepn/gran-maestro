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
    TYPE_DIRS,
    get_counter_path,
    load_json,
    save_json,
)

def cmd_counter_next(args):
    counter_path = get_counter_path(args.type, args.dir)
    subdir, prefix = TYPE_DIRS.get(args.type, ("requests", "REQ"))
    scan_root = Path(args.dir) if args.dir else _common.BASE_DIR / subdir
    disk_max = 0
    for path in scan_root.glob(f"{prefix}-*"):
        if args.type != "intent" and not path.is_dir():
            continue
        if args.type == "intent" and not (path.is_dir() or path.is_file()):
            continue
        try:
            n = int(path.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if n > disk_max:
            disk_max = n

    scan_root.mkdir(parents=True, exist_ok=True)
    data = load_json(counter_path) or {}
    last_id = max(data.get("last_id", 0), disk_max)
    next_id = last_id + 1
    save_json(counter_path, {"last_id": next_id})
    print(f"{prefix}-{next_id:03d}")
    return 0

def cmd_counter_peek(args):
    counter_path = get_counter_path(args.type, args.dir)
    data = load_json(counter_path) or {"last_id": 0}
    _, prefix = TYPE_DIRS.get(args.type, ("requests", "REQ"))
    last_id = data.get("last_id", 0)
    print(f"{prefix}-{last_id + 1:03d} (next, current last_id={last_id})")
    return 0


def register(subparsers):
    sub = subparsers
    ctr = sub.add_parser("counter")
    ctr_sub = ctr.add_subparsers(dest="subcommand")

    ctr_next = ctr_sub.add_parser("next")
    ctr_next.add_argument(
        "--type",
        choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "fc", "ref", "intent", "agi"],
        default="req",
    )
    ctr_next.add_argument("--dir")

    ctr_peek = ctr_sub.add_parser("peek")
    ctr_peek.add_argument(
        "--type",
        choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "fc", "ref", "intent", "agi"],
        default="req",
    )
    ctr_peek.add_argument("--dir")
