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
    _flat_diff,
    _plugin_root,
    deep_merge,
    load_json,
    save_json,
)

def _load_preset(preset_id):
    plugin_root = _plugin_root()
    manifest = load_json(plugin_root / "templates" / "defaults" / "presets" / "manifest.json")

    # 1) built-in preset lookup from manifest
    if isinstance(manifest, dict):
        presets = manifest.get("presets")
        if isinstance(presets, list):
            for entry in presets:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") != preset_id:
                    continue
                rel_file = entry.get("file")
                if isinstance(rel_file, str):
                    return load_json(plugin_root / "templates" / "defaults" / "presets" / rel_file)

    # 2) user preset lookup (path traversal guard)
    if not re.match(r"^[a-z0-9-]+$", preset_id):
        return None
    user_file = _common.BASE_DIR / "presets" / f"{preset_id}.json"
    if user_file.is_file():
        return load_json(user_file)

    return None

def _diff_from_base(base, current):
    diff = {}
    if not isinstance(base, dict) or not isinstance(current, dict):
        return diff

    for key, current_value in current.items():
        base_value = base.get(key)
        if isinstance(base_value, dict) and isinstance(current_value, dict):
            nested = _diff_from_base(base_value, current_value)
            if nested:
                diff[key] = nested
        elif current_value != base_value:
            diff[key] = current_value
    return diff

def cmd_preset_list(args):
    plugin_root = _plugin_root()
    builtin_manifest = load_json(plugin_root / "templates" / "defaults" / "presets" / "manifest.json")

    presets = []
    if isinstance(builtin_manifest, dict):
        for p in builtin_manifest.get("presets", []):
            if isinstance(p, dict):
                presets.append({**p, "source": "builtin"})

    user_dir = _common.BASE_DIR / "presets"
    if user_dir.is_dir():
        for preset_path in sorted(user_dir.glob("*.json")):
            presets.append({
                "id": preset_path.stem,
                "name": preset_path.stem,
                "source": "user",
                "file": str(preset_path),
            })

    if args.format == "json":
        print(json.dumps(presets, ensure_ascii=False, indent=2))
        return 0

    print(f"{'TYPE':<10} {'ID':<32} {'NAME'}")
    print("-" * 80)
    for preset in presets:
        source = "[builtin]" if preset.get("source") == "builtin" else "[user]"
        print(
            f"{source:<10} "
            f"{preset.get('id', ''):<32} "
            f"{preset.get('name', '')}"
        )
    return 0

def cmd_preset_apply(args):
    preset_data = _load_preset(args.preset_id)
    if not isinstance(preset_data, dict):
        print(f"Error: preset '{args.preset_id}' not found", file=sys.stderr)
        return 1

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    overrides = load_json(_common.BASE_DIR / "config.json") or {}
    current_resolved = deep_merge(defaults, overrides)
    merged = deep_merge(current_resolved, preset_data)
    if "agent_assignments" in preset_data:
        merged["agent_assignments"] = preset_data["agent_assignments"]
    next_overrides = _diff_from_base(defaults, merged)
    save_json(_common.BASE_DIR / "config.json", next_overrides)
    save_json(_common.BASE_DIR / "config.resolved.json", merged)

    changed = _flat_diff(current_resolved, merged)
    if changed:
        print(f"Applied preset '{args.preset_id}': {len(changed)} settings changed")
        for key, (old, new) in changed.items():
            print(f"  {key}: {old} → {new}")
    else:
        print(f"Preset '{args.preset_id}' has no changes")
    return 0

def cmd_preset_diff(args):
    preset_data = _load_preset(args.preset_id)
    if not isinstance(preset_data, dict):
        print(f"Error: preset '{args.preset_id}' not found", file=sys.stderr)
        return 1

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    overrides = load_json(_common.BASE_DIR / "config.json") or {}
    current_resolved = deep_merge(defaults, overrides)
    merged = deep_merge(current_resolved, preset_data)

    changed = _flat_diff(current_resolved, merged)
    if not changed:
        print(f"No changes — current config already matches preset '{args.preset_id}'")
        return 0

    print(f"Preset '{args.preset_id}' would change {len(changed)} settings:")
    for key, (old, new) in changed.items():
        print(f"  {key}: {old} → {new}")
    return 0

def cmd_preset_save(args):
    if not re.match(r"^[a-z0-9-]+$", args.preset_id):
        print(
            f"Error: preset ID must match ^[a-z0-9-]+$ (got '{args.preset_id}')",
            file=sys.stderr,
        )
        return 1

    user_dir = _common.BASE_DIR / "presets"
    user_dir.mkdir(parents=True, exist_ok=True)

    target = user_dir / f"{args.preset_id}.json"
    if target.is_file():
        print(f"Warning: overwriting existing user preset '{args.preset_id}'", file=sys.stderr)

    current = load_json(_common.BASE_DIR / "config.json") or {}
    save_json(target, current)
    print(f"Saved current config as user preset '{args.preset_id}'")
    return 0


def register(subparsers):
    sub = subparsers
    preset = sub.add_parser("preset")
    preset_sub = preset.add_subparsers(dest="subcommand")
    preset_list = preset_sub.add_parser("list", help="built-in and user presets")
    preset_list.add_argument("--format", choices=["table", "json"], default="table")
    preset_apply = preset_sub.add_parser("apply", help="apply preset to config overrides")
    preset_apply.add_argument("preset_id")
    preset_diff = preset_sub.add_parser("diff", help="preview preset diff against current config")
    preset_diff.add_argument("preset_id")
    preset_save = preset_sub.add_parser("save", help="save current config as user preset")
    preset_save.add_argument("preset_id")
