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

def cmd_set_status(args):
    """지정 ID의 status 필드 + updated_at 갱신."""
    from scripts._state_manager import set_status
    set_status(_common.BASE_DIR, args.id, args.status)
    return 0

def cmd_set_field(args):
    """지정 ID의 단일 JSON 필드 업데이트."""
    from scripts._state_manager import set_field
    set_field(_common.BASE_DIR, args.id, args.field, args.value)
    return 0


def register(subparsers):
    sub = subparsers
    set_status_cmd = sub.add_parser("set-status")
    set_status_cmd.add_argument("id", help="REQ-NNN / PLN-NNN / DBG-NNN 등")
    set_status_cmd.add_argument("status", help="새 상태값")
    set_status_cmd.set_defaults(func=cmd_set_status)

    set_field_cmd = sub.add_parser("set-field")
    set_field_cmd.add_argument("id", help="REQ-NNN / PLN-NNN / DBG-NNN 등")
    set_field_cmd.add_argument("field", help="JSON 필드명")
    set_field_cmd.add_argument("value", help="새 값 (문자열)")
    set_field_cmd.set_defaults(func=cmd_set_field)
