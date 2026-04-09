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

def cmd_timestamp(args):
    """현재 UTC ISO 타임스탬프를 stdout 출력."""
    from scripts._state_manager import timestamp_now
    print(timestamp_now())
    return 0


def register(subparsers):
    sub = subparsers
    ts = sub.add_parser("timestamp")
    ts_sub = ts.add_subparsers(dest="subcommand")

    ts_now = ts_sub.add_parser("now")
    ts_now.set_defaults(func=cmd_timestamp)
