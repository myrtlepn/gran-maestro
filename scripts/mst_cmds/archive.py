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
    _archive_run_type,
    _resolve_archive_max_active,
    load_json,
    type_archived_dir,
)

def cmd_archive_run(args):
    type_key = getattr(args, "type", None) or "req"
    max_active = _load_archive_max_active(args.max, type_key)
    _archive_run_type(type_key, max_active, emit_output=True)
    return 0

def _load_archive_max_active(cli_max: Optional[int], type_key: Optional[str] = None) -> int:
    if cli_max is not None:
        return cli_max

    config_paths = [
        _common.BASE_DIR / ".." / ".gran-maestro" / "config.json",
        _common.BASE_DIR.parent / "config.json",
    ]
    cfg = None
    for path in config_paths:
        loaded = load_json(path)
        if loaded is not None:
            cfg = loaded
            break

    max_active_cfg = 20
    if isinstance(cfg, dict):
        max_active_cfg = cfg.get("archive", {}).get("max_active_sessions", 20)
    return _resolve_archive_max_active(max_active_cfg, type_key)

def cmd_archive_run_all(args):
    counts = {}
    had_error = False
    for type_key in TYPE_DIRS:
        try:
            max_active = _load_archive_max_active(args.max, type_key)
            counts[type_key] = _archive_run_type(type_key, max_active=max_active, emit_output=False)
        except Exception as exc:
            print(f"[Archive] {type_key} 정리 실패: {exc}", file=sys.stderr)
            counts[type_key] = 0
            had_error = True

    if sum(counts.values()) == 0 and not had_error:
        print("[Archive] 정리 대상 없음")
        return 0

    summary = ", ".join(f"{k}:{counts[k]}" for k in counts.keys())
    print(f"[Archive] 전체 정리 완료 — {summary}")
    return 0

def cmd_archive_list(args):
    has_any = False
    filter_type = getattr(args, "type", None)
    for type_key, (subdir, _) in TYPE_DIRS.items():
        if filter_type and filter_type != type_key:
            continue
        archived = type_archived_dir(type_key)
        if not archived.exists():
            continue
        for a in sorted(archived.glob("*.tar.gz")):
            size_kb = a.stat().st_size // 1024
            print(f"{a.name:<60} {size_kb:>6} KB")
            has_any = True
    if not has_any:
        print("No archives found.")
    return 0

def cmd_archive_restore(args):
    target = args.archive_id.upper()
    prefix = target[:3]
    prefix_to_type = {"REQ": "req", "IDN": "idn", "DSC": "dsc", "DBG": "dbg", "CAP": "cap"}
    type_key = prefix_to_type.get(prefix, "req")
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    archived = type_archived_dir(type_key)
    restore_dir = _common.BASE_DIR / subdir

    for arc in sorted(archived.glob("*.tar.gz")):
        with tarfile.open(arc, "r:gz") as tar:
            names = tar.getnames()
            matching = [n for n in names if n.startswith(target + "/") or n == target]
            if matching:
                tar.extractall(path=restore_dir, members=[tar.getmember(n) for n in matching])
                print(f"Restored {target} from {arc.name}")
                return 0
    print(f"Error: {args.archive_id} not found in any archive.", file=sys.stderr)
    return 1


def register(subparsers):
    sub = subparsers
    arc = sub.add_parser("archive")
    arc_sub = arc.add_subparsers(dest="subcommand")

    arc_run = arc_sub.add_parser("run")
    arc_run.add_argument("--type", choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "agi"], default="req")
    arc_run.add_argument("--max", type=int)
    arc_run.add_argument("--dir")

    arc_run_all = arc_sub.add_parser("run-all")
    arc_run_all.add_argument("--max", type=int)

    arc_list = arc_sub.add_parser("list")
    arc_list.add_argument("--type")

    arc_restore = arc_sub.add_parser("restore")
    arc_restore.add_argument("archive_id")
