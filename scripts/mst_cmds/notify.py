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

def cmd_notify(args):
    from _notifier import notify
    data = json.loads(args.data) if args.data else {}
    ok = notify(args.event_type, data)
    if ok:
        print(f"notify: {args.event_type} 전송됨")
    else:
        print(f"notify: {args.event_type} 실패 (서버 미실행 또는 연결 오류)")
    return 0


def register(subparsers):
    sub = subparsers
    notify_parser = sub.add_parser("notify")
    notify_parser.add_argument("event_type")
    notify_parser.add_argument("data", nargs="?", default=None)
