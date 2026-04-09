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
    _project_root,
    load_json,
    save_json,
)

def cmd_agents_check(args):
    root = _project_root()
    agents_dir = root / "agents"
    fs_agents = set()
    if agents_dir.exists():
        for f in agents_dir.glob("*.md"):
            fs_agents.add(f"./agents/{f.name}")

    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_agents = set(plugin_data.get("agents") or [])

    missing = fs_agents - plugin_agents   # in fs but not in plugin.json
    ghost = plugin_agents - fs_agents     # in plugin.json but not in fs

    if not missing and not ghost:
        print(f"✓ agents 배열 동기화됨 ({len(fs_agents)}개)")
        return 0

    for entry in sorted(missing):
        print(f"+ {entry}")
    for entry in sorted(ghost):
        print(f"- {entry}")
    return 1

def cmd_agents_sync(args):
    root = _project_root()
    agents_dir = root / "agents"
    fs_agents = []
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*.md")):
            fs_agents.append(f"./agents/{f.name}")

    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_data["agents"] = fs_agents
    save_json(plugin_path, plugin_data)
    print(f"Updated agents: {fs_agents}")
    return 0


def register(subparsers):
    sub = subparsers
    agt = sub.add_parser("agents")
    agt_sub = agt.add_subparsers(dest="subcommand")

    agt_check = agt_sub.add_parser("check")
    agt_sync = agt_sub.add_parser("sync")
