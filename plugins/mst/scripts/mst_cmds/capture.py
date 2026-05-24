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
    _capture_expired,
    _capture_is_plan_active,
    _parse_utc_datetime,
    load_json,
    plans_dir,
    requests_dir,
    save_json,
)

def _capture_linked_requests_done(plan_id):
    if not plan_id:
        return False
    plan_data = load_json(plans_dir() / str(plan_id) / "plan.json")
    if not isinstance(plan_data, dict):
        return False
    linked_requests = plan_data.get("linked_requests")
    if not isinstance(linked_requests, list) or not linked_requests:
        return False

    for req_id in linked_requests:
        request_paths = [
            requests_dir() / req_id / "request.json",
            requests_dir() / "completed" / req_id / "request.json",
        ]
        req_path = next((p for p in request_paths if p.exists()), None)
        if req_path is None:
            return False
        req_data = load_json(req_path) or {}
        if req_data.get("status") not in ("completed", "cancelled"):
            return False
    return True

def cmd_capture_ttl_check(args):
    captures_dir = _common.BASE_DIR / "captures"
    if not captures_dir.exists():
        print("No captures directory.")
        return 0

    now = datetime.now(timezone.utc)
    warn_threshold = timedelta(hours=24)
    expired = []

    for cap_dir in sorted(captures_dir.glob("CAP-*")):
        if not cap_dir.is_dir():
            continue
        cap_path = cap_dir / "capture.json"
        meta = load_json(cap_path) or {}

        changed = False
        created_at = _parse_utc_datetime(meta.get("created_at", ""))
        if created_at is None:
            continue

        ttl_warned_at = _parse_utc_datetime(meta.get("ttl_warned_at", ""))
        if ttl_warned_at is None and now - created_at >= warn_threshold:
            meta["ttl_warned_at"] = now.isoformat()
            changed = True

        if _capture_expired(meta, now):
            linked_plan = (meta.get("linked_plan") or "").upper()
            if not _capture_is_plan_active(linked_plan):
                expired.append(cap_dir.name)

        if _capture_linked_requests_done(meta.get("linked_plan")):
            if meta.get("status") not in ("done", "cancelled"):
                meta["status"] = "done"
                changed = True

        if changed:
            save_json(cap_path, meta)

    if expired:
        print("Expired captures:")
        for name in expired:
            print(name)
    else:
        print("No expired captures.")
    return 0

def _parse_capture_ids(raw_caps):
    cap_ids = []
    skipped = []
    seen = set()
    for token in str(raw_caps or "").split(","):
        raw_token = token.strip()
        if not raw_token:
            continue
        cap_id = raw_token.upper()
        if cap_id in seen:
            continue
        seen.add(cap_id)
        if not re.fullmatch(r"^CAP-\d+$", cap_id):
            skipped.append(raw_token)
            print(f"[WARN] invalid CAP ID format skipped: {raw_token}", file=sys.stderr)
            continue
        cap_ids.append(cap_id)
    return cap_ids, skipped

def _capture_status_enum():
    schema_path = _common._project_root() / "templates" / "defaults" / "capture-schema.json"
    schema = load_json(schema_path)
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    status_def = properties.get("status")
    if not isinstance(status_def, dict):
        return None
    enum = status_def.get("enum")
    if not isinstance(enum, list):
        return None
    statuses = {status for status in enum if isinstance(status, str)}
    return statuses or None

def cmd_capture_mark_consumed(args):
    cap_ids, parse_skipped = _parse_capture_ids(args.caps)
    if not cap_ids and not parse_skipped:
        print("Error: --caps requires at least one CAP ID", file=sys.stderr)
        return 1

    plan_id = str(args.plan or "").strip().upper()
    if not plan_id:
        print("Error: --plan is required", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    captures_dir = _common.BASE_DIR / "captures"
    schema_statuses = _capture_status_enum()
    updated = []
    skipped = list(parse_skipped)

    if schema_statuses is None:
        print("[WARN] capture status enum unavailable from schema; validation skipped", file=sys.stderr)

    for cap_id in cap_ids:
        cap_path = captures_dir / cap_id / "capture.json"
        capture = load_json(cap_path)
        if not isinstance(capture, dict):
            skipped.append(cap_id)
            print(f"[WARN] capture not found: {cap_id}", file=sys.stderr)
            continue

        current_status = capture.get("status")
        if current_status == "consumed":
            skipped.append(cap_id)
            print(f"[WARN] capture already consumed: {cap_id}", file=sys.stderr)
            continue
        if schema_statuses is not None and current_status not in schema_statuses:
            print(
                f"[WARN] capture has invalid status: {cap_id} ({current_status!r})",
                file=sys.stderr,
            )

        capture["status"] = "consumed"
        capture["consumed_at"] = now
        capture["linked_plan"] = plan_id
        try:
            save_json(cap_path, capture)
        except Exception as exc:
            skipped.append(cap_id)
            print(f"[WARN] failed to save capture: {cap_id} ({exc})", file=sys.stderr)
            continue
        updated.append(cap_id)

    if args.json:
        print(json.dumps({"updated": updated, "skipped": skipped, "plan": plan_id}, ensure_ascii=False))
        return 0

    if updated:
        print("Updated captures:")
        for cap_id in updated:
            print(cap_id)
    if skipped:
        print("Skipped captures:")
        for cap_id in skipped:
            print(cap_id)
    return 0


def register(subparsers):
    sub = subparsers
    cap = sub.add_parser("capture")
    cap_sub = cap.add_subparsers(dest="subcommand")
    cap_ttl_check = cap_sub.add_parser("ttl-check")
    cap_ttl_check.set_defaults(func=cmd_capture_ttl_check)
    cap_mark_consumed = cap_sub.add_parser("mark-consumed")
    cap_mark_consumed.add_argument("--caps", required=True, help="comma-separated CAP IDs")
    cap_mark_consumed.add_argument("--plan", required=True, help="PLN-ID")
    cap_mark_consumed.add_argument("--json", action="store_true")
