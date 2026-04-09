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

def cmd_measure_stop_rate(args):
    script_path = _common._scripts_dir() / "measure_stop_rate.py"
    cmd = [sys.executable, str(script_path)]

    if args.snapshots_dir:
        cmd.extend(["--snapshots-dir", args.snapshots_dir])
    if args.pretty:
        cmd.append("--pretty")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_common.BASE_DIR.parent),
    )

    if result.stdout:
        print(result.stdout.rstrip("\n"))
    if result.stderr:
        print(result.stderr.rstrip("\n"), file=sys.stderr)
    return result.returncode


def register(subparsers):
    sub = subparsers
    measure = sub.add_parser("measure")
    measure_sub = measure.add_subparsers(dest="subcommand")
    measure_stop_rate = measure_sub.add_parser("stop-rate")
    measure_stop_rate.add_argument("--snapshots-dir")
    measure_stop_rate.add_argument("--pretty", action="store_true")
