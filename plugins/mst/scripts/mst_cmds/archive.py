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
        _common.BASE_DIR / "config.json",
        _common.BASE_DIR.parent / "config.json",
    ]
    cfg = None
    for path in config_paths:
        loaded = load_json(path)
        if loaded is not None:
            cfg = loaded
            break

    max_active_cfg = 200
    if isinstance(cfg, dict):
        max_active_cfg = cfg.get("archive", {}).get("max_active_sessions", 200)
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

DEFAULT_ARCHIVE_RETENTION_DAYS = 90


def _resolve_retention_days(cli_value: Optional[int]) -> int:
    """Determine effective retention days for ``archive purge``.

    Priority: CLI ``--max-age-days`` > config ``archive.retention_days`` /
    ``archive_retention_days`` > :data:`DEFAULT_ARCHIVE_RETENTION_DAYS`.
    AD-009: a ``null`` config value resolves to the safe default (90 days)
    rather than infinite retention, since cleanup-created archives would
    otherwise accumulate indefinitely.
    """
    if cli_value is not None:
        return int(cli_value)

    config_paths = [
        _common.BASE_DIR / "config.json",
        _common.BASE_DIR.parent / "config.json",
    ]
    cfg = None
    for path in config_paths:
        loaded = load_json(path)
        if loaded is not None:
            cfg = loaded
            break
    if isinstance(cfg, dict):
        archive_cfg = cfg.get("archive")
        if isinstance(archive_cfg, dict):
            value = archive_cfg.get("retention_days")
            if value is None:
                value = archive_cfg.get("archive_retention_days")
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        legacy_value = cfg.get("archive_retention_days")
        if isinstance(legacy_value, (int, float)) and legacy_value >= 0:
            return int(legacy_value)
    return DEFAULT_ARCHIVE_RETENTION_DAYS


def cmd_archive_purge(args):
    """AD-009: delete archived ``*.tar.gz`` files older than the retention.

    Walks every ``type_archived_dir(type_key)`` so that archives produced by
    ``archive run`` and ``cleanup`` (both write into the same per-type
    ``archived/`` directory) are subject to the same retention policy.
    """
    retention_days = _resolve_retention_days(getattr(args, "max_age_days", None))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    dry_run = bool(getattr(args, "dry_run", False))

    deleted = []
    total_bytes = 0
    for type_key in TYPE_DIRS:
        archived = type_archived_dir(type_key)
        if not archived.exists():
            continue
        for arc in sorted(archived.glob("*.tar.gz")):
            try:
                stat = arc.stat()
            except OSError:
                continue
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                continue
            size = stat.st_size
            total_bytes += size
            deleted.append((arc, size))
            if not dry_run:
                try:
                    arc.unlink()
                except OSError as exc:
                    print(f"[archive purge] failed to delete {arc}: {exc}", file=sys.stderr)

    label = "[dry-run] would delete" if dry_run else "Purged"
    print(
        f"{label} {len(deleted)} archive(s), total {total_bytes} bytes "
        f"(retention={retention_days}d)"
    )
    for arc, size in deleted:
        try:
            display = arc.relative_to(_common.BASE_DIR)
        except ValueError:
            display = arc
        print(f"  {display} ({size} bytes)")
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

    arc_purge = arc_sub.add_parser("purge")
    arc_purge.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        help="Override retention days (default: config archive.retention_days, or 90 if null)",
    )
    arc_purge.add_argument("--dry-run", action="store_true")
