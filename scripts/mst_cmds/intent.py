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
    _create_intent_store,
)

def _next_intent_id():
    cmd = [
        sys.executable,
        str(_common._mst_script_path()),
        "counter",
        "next",
        "--type",
        "intent",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_common.BASE_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "counter next failed")

    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("counter next produced no id")

def cmd_intent_add(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    try:
        intent_id = _next_intent_id()
        motivation = args.motivation if args.motivation is not None else args.goal
        created = store.add(
            intent_id,
            feature=args.feature,
            situation=args.situation,
            motivation=motivation,
            goal=args.goal,
            linked_req=args.req,
            linked_plan=args.plan,
            related_intent=args.related_intent,
            tags=args.tag,
            files=args.file,
        )
    except RuntimeError as exc:
        print(f"Error: failed to allocate intent id ({exc})", file=sys.stderr)
        return 1
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(created, ensure_ascii=False, indent=2))
    else:
        print(created["id"])
    return 0

def cmd_intent_get(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        data = store.get(args.intent_id)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if data is None:
        print(f"Error: {args.intent_id} not found.", file=sys.stderr)
        return 1

    if args.json:
        output = {k: v for k, v in data.items() if k != "raw"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        meta = data.get("metadata", {})
        body = data.get("body", data.get("raw", ""))
        lines = ["---"]
        for key in ("id", "feature", "linked_req", "linked_plan", "related_intent", "tags", "files", "created_at"):
            val = meta.get(key)
            if isinstance(val, list):
                lines.append(f'{key}: {json.dumps(val, ensure_ascii=False)}')
            else:
                lines.append(f'{key}: {json.dumps(val, ensure_ascii=False)}')
        lines.append("---")
        lines.append(body)
        print("\n".join(lines))
    return 0

def cmd_intent_list(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        entries = store.list()
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.req:
        entries = [entry for entry in entries if entry.get("linked_req") == args.req]
    if args.plan:
        entries = [entry for entry in entries if entry.get("linked_plan") == args.plan]

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No intents found.")
        return 0

    print(f"{'ID':<12} {'Created':<12} {'Feature'}")
    print("-" * 80)
    for entry in entries:
        print(
            f"{entry.get('id', ''):<12} {entry.get('created_at', ''):<12} "
            f"{entry.get('feature', '')}"
        )
    return 0

def cmd_intent_update(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    update_fields = {}
    for key in ("feature", "situation", "motivation", "goal", "created_at"):
        value = getattr(args, key, None)
        if value is not None:
            update_fields[key] = value
    if args.req is not None:
        update_fields["linked_req"] = args.req
    if args.plan is not None:
        update_fields["linked_plan"] = args.plan
    if args.related_intent is not None:
        update_fields["related_intent"] = args.related_intent
    if args.tag is not None:
        update_fields["tags"] = args.tag
    if args.file is not None:
        update_fields["files"] = args.file

    if not update_fields:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    try:
        updated = store.update(args.intent_id, **update_fields)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(updated, ensure_ascii=False, indent=2))
    else:
        print(updated["id"])
    return 0

def cmd_intent_delete(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    try:
        deleted = store.delete(args.intent_id)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Deleted {deleted['id']}")
    return 0

def cmd_intent_search(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        matches = store.search(args.keyword)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    for match in matches:
        print(f"{match.get('id')}:{match.get('line')}:{match.get('text')}")
    return 0

def cmd_intent_lookup(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        entries = store.lookup(args.files)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    for entry in entries:
        files = ", ".join(entry.get("files", []))
        print(f"{entry.get('id')}: {files}")
    return 0

def cmd_intent_related(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        related = store.related(args.intent_id, depth=args.depth)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(related, ensure_ascii=False, indent=2))
        return 0

    print(f"Source: {related.get('source')} (depth={related.get('depth')})")
    for item in related.get("related", []):
        reasons = ", ".join(item.get("reasons", []))
        print(f"{item.get('id')} [depth={item.get('depth')}] {reasons}")
    return 0

def cmd_intent_rebuild(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        index = store.rebuild()
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    entry_count = len(index.get("entries", []))
    print(f"Rebuilt .gran-maestro/intent/intent.db ({entry_count} entries)")
    return 0


def register(subparsers):
    sub = subparsers
    intent = sub.add_parser("intent")
    intent_sub = intent.add_subparsers(dest="subcommand")

    intent_add = intent_sub.add_parser("add")
    intent_add.add_argument("--req", dest="req")
    intent_add.add_argument("--plan", dest="plan")
    intent_add.add_argument("--feature", required=True)
    intent_add.add_argument("--situation", required=True)
    intent_add.add_argument("--motivation")
    intent_add.add_argument("--goal", required=True)
    intent_add.add_argument("--related-intent", dest="related_intent", action="append", default=[])
    intent_add.add_argument("--tag", dest="tag", action="append", default=[])
    intent_add.add_argument("--file", dest="file", action="append", default=[])
    intent_add.add_argument("--json", action="store_true")

    intent_get = intent_sub.add_parser("get")
    intent_get.add_argument("intent_id")
    intent_get.add_argument("--json", action="store_true")

    intent_list = intent_sub.add_parser("list")
    intent_list.add_argument("--req", dest="req")
    intent_list.add_argument("--plan", dest="plan")
    intent_list.add_argument("--json", action="store_true")

    intent_update = intent_sub.add_parser("update")
    intent_update.add_argument("intent_id")
    intent_update.add_argument("--feature")
    intent_update.add_argument("--situation")
    intent_update.add_argument("--motivation")
    intent_update.add_argument("--goal")
    intent_update.add_argument("--req", dest="req")
    intent_update.add_argument("--plan", dest="plan")
    intent_update.add_argument("--related-intent", dest="related_intent", action="append")
    intent_update.add_argument("--tag", dest="tag", action="append")
    intent_update.add_argument("--file", dest="file", action="append")
    intent_update.add_argument("--created-at", dest="created_at")
    intent_update.add_argument("--json", action="store_true")

    intent_delete = intent_sub.add_parser("delete")
    intent_delete.add_argument("intent_id")

    intent_search = intent_sub.add_parser("search")
    intent_search.add_argument("keyword")
    intent_search.add_argument("--json", action="store_true")

    intent_lookup = intent_sub.add_parser("lookup")
    intent_lookup.add_argument("--files", nargs="+", required=True)
    intent_lookup.add_argument("--json", action="store_true")

    intent_related = intent_sub.add_parser("related")
    intent_related.add_argument("intent_id")
    intent_related.add_argument("--depth", type=int, default=1)
    intent_related.add_argument("--json", action="store_true")

    intent_sub.add_parser("rebuild")
