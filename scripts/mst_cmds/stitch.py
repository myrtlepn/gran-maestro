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

def cmd_stitch_sleep(args):
    """Stitch 비동기 생성 대기용 인터벌 sleep."""
    interval = args.interval
    print(f"[Stitch] {interval}초 대기 중...", flush=True)
    time.sleep(interval)
    print("SLEEP_DONE", flush=True)
    return 0


def register(subparsers):
    sub = subparsers
    stitch = sub.add_parser("stitch")
    stitch_sub = stitch.add_subparsers(dest="subcommand")

    stitch_sleep = stitch_sub.add_parser("sleep")
    stitch_sleep.add_argument(
        "--interval", type=float, default=30.0,
        help="대기 시간(초). 기본값 30."
    )
