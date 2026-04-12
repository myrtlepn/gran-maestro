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
    _compact_json,
    _parse_bool_arg,
    queue_complete,
    queue_count,
    queue_enqueue,
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
        choices=["queued", "running", "done", "failed", "cancelled", "all"],
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
        choices=["queued", "running", "done", "failed", "cancelled"],
        default="queued",
    )
    queue_count_cmd.add_argument("--json", action="store_true")
