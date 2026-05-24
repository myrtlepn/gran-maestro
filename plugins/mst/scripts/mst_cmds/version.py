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
    _project_root,
    _read_versions,
    load_json,
    save_json,
)

def cmd_version_get(args):
    versions = _read_versions()
    print(versions["package"])
    return 0

def cmd_version_check(args):
    versions = _read_versions()
    pkg = versions["package"]
    plugin = versions["plugin"]
    market = versions["marketplace"]
    ext_manifest = versions["ext_manifest"]
    ext_package = versions["ext_package"]
    if (
        pkg == plugin == market == ext_manifest == ext_package
        and pkg != ""
    ):
        print(f"✓ {pkg} (동기화됨)")
        return 0
    else:
        print(f"✗ 버전 불일치:")
        print(f"  package.json:              {pkg}")
        print(f"  plugin.json:               {plugin}")
        print(f"  marketplace.json:          {market}")
        print(f"  extension/manifest.json:   {ext_manifest}")
        print(f"  extension/package.json:    {ext_package}")
        return 1

def cmd_version_bump(args):
    versions = _read_versions()
    current = versions["package"]
    if not (
        current == versions["plugin"] == versions["marketplace"] == versions["ext_manifest"] == versions["ext_package"]
    ):
        print("Error: version mismatch")
        print(f"  package.json:              {versions['package']}")
        print(f"  plugin.json:               {versions['plugin']}")
        print(f"  marketplace.json:          {versions['marketplace']}")
        print(f"  extension/manifest.json:   {versions['ext_manifest']}")
        print(f"  extension/package.json:    {versions['ext_package']}")
        return 1

    parts = current.split(".")
    if len(parts) != 3:
        print(f"Error: cannot parse version '{current}'", file=sys.stderr)
        return 1
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        print(f"Error: cannot parse version '{current}'", file=sys.stderr)
        return 1

    level = args.level
    if level == "patch":
        patch += 1
    elif level == "minor":
        minor += 1
        patch = 0
    elif level == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        print(f"Error: unknown bump level '{level}'", file=sys.stderr)
        return 1

    new_version = f"{major}.{minor}.{patch}"
    root = _project_root()

    # Update package.json
    pkg_path = root / "package.json"
    pkg_data = load_json(pkg_path) or {}
    pkg_data["version"] = new_version
    save_json(pkg_path, pkg_data)

    # Update plugin.json
    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_data["version"] = new_version
    save_json(plugin_path, plugin_data)

    # Update marketplace.json
    market_path = root / ".claude-plugin" / "marketplace.json"
    market_data = load_json(market_path) or {}
    plugins = market_data.get("plugins") or [{}]
    plugins[0]["version"] = new_version
    market_data["plugins"] = plugins
    save_json(market_path, market_data)

    # Update extension manifest
    ext_manifest_path = root / "extension" / "manifest.json"
    ext_manifest_data = load_json(ext_manifest_path) or {}
    ext_manifest_data["version"] = new_version
    save_json(ext_manifest_path, ext_manifest_data)

    # Update extension package.json
    ext_package_path = root / "extension" / "package.json"
    ext_package_data = load_json(ext_package_path) or {}
    ext_package_data["version"] = new_version
    save_json(ext_package_path, ext_package_data)

    print(new_version)
    return 0


def register(subparsers):
    sub = subparsers
    ver = sub.add_parser("version")
    ver_sub = ver.add_subparsers(dest="subcommand")

    ver_get = ver_sub.add_parser("get")
    ver_check = ver_sub.add_parser("check")
    ver_bump = ver_sub.add_parser("bump")
    ver_bump.add_argument("level", choices=["patch", "minor", "major"])
