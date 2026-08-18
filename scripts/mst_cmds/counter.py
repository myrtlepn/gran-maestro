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
    TYPE_DIRS,
    get_counter_path,
    load_json,
    save_json,
)

def cmd_counter_next(args):
    if args.type == "ref":
        from scripts.mst_cmds import reference as reference_mod

        try:
            print(reference_mod.reserve_reference_id_for_counter(args.dir))
            return 0
        except reference_mod.ReferenceError as exc:
            return reference_mod._emit_error(exc.code, exc.message, exc.outcome)

    from scripts.mst_cmds import session as session_mod

    counter_path = get_counter_path(args.type, args.dir)
    subdir, prefix = TYPE_DIRS.get(args.type, ("requests", "REQ"))
    scan_root = Path(args.dir) if args.dir else _common.BASE_DIR / subdir
    lock_base = Path(args.dir) if args.dir else _common.BASE_DIR
    with session_mod.open_root_type_bootstrap_lock(lock_base, args.type) as lock_handle:
        _common._lock_exclusive_with_timeout(lock_handle, timeout_sec=30.0, poll_interval=0.01)
        try:
            next_id = session_mod.next_root_number(scan_root, args.type, load_json(counter_path) or {})
            scan_root.mkdir(parents=True, exist_ok=True)
            save_json(counter_path, {"last_id": next_id})
            print(f"{prefix}-{next_id:03d}")
            return 0
        finally:
            _common._unlock(lock_handle)

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
