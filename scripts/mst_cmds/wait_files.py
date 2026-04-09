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
)

def cmd_wait_files(args):
    files = args.files
    total = len(files)

    # 타임아웃 우선순위: CLI 인자 > config.json > 기본값 600s
    cfg = load_json(_common.BASE_DIR / "config.json") or {}
    if args.timeout is not None:
        timeout_s = args.timeout
    else:
        timeout_ms = cfg.get("timeouts", {}).get("wait_files_ms", 600000)
        timeout_s = timeout_ms / 1000
    min_content_wait = cfg.get("min_content_wait", 5)
    try:
        min_content_wait = float(min_content_wait)
    except (TypeError, ValueError):
        min_content_wait = 5

    completed = set()
    empty_files_seen = {}
    start = time.time()

    while time.time() - start < timeout_s:
        for f in files:
            if f in completed:
                continue

            if os.path.exists(f):
                size = os.path.getsize(f)
                if size > 0:
                    completed.add(f)
                    name = os.path.basename(f)
                    print(f"[{len(completed)}/{total}] {name} 완료", flush=True)
                else:
                    now = time.time()
                    if f not in empty_files_seen:
                        empty_files_seen[f] = now
                    elif min_content_wait > 0 and now - empty_files_seen[f] < min_content_wait:
                        continue
                    # 빈 파일이 생성되어도 즉시 완료로 처리하지 않고 재확인
            else:
                empty_files_seen.pop(f, None)

        if len(completed) == total:
            print("ALL_READY", flush=True)
            return 0

        time.sleep(1)

    print(f"TIMEOUT ({len(completed)}/{total})", flush=True)
    return 1


def register(subparsers):
    sub = subparsers
    wf = sub.add_parser("wait-files")
    wf.add_argument("files", nargs="+", help="대기할 파일 경로 목록")
    wf.add_argument("--timeout", type=float, default=None,
                    help="타임아웃 (초). 미지정 시 config.json의 timeouts.wait_files_ms 사용")
