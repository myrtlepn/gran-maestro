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
    TYPE_DIRS,
    _archive_run_type,
    _resolve_archive_max_active,
    _skill_state_base_dir,
    load_json,
)

def cmd_hooks_post_skill(args):
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            return 0

        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return 0

        skill = tool_input.get("skill", "")
        if not isinstance(skill, str):
            return 0

        # --- return_to continuation guard ---
        # Check snapshot for returnTo BEFORE archiving (archive may clear state)
        _hooks_post_skill_continuation(skill)

        if skill not in {"mst:accept", "mst:ideation", "mst:discussion", "mst:debug"}:
            return 0

        resolved = load_json(_common.BASE_DIR / "config.resolved.json") or {}
        archive_cfg = resolved.get("archive", {})
        if not isinstance(archive_cfg, dict):
            archive_cfg = {}

        if not archive_cfg.get("auto_archive_on_complete", True):
            return 0

        max_active_cfg = archive_cfg.get("max_active_sessions", 20)

        for type_key in TYPE_DIRS:
            try:
                max_active = _resolve_archive_max_active(max_active_cfg, type_key)
                _archive_run_type(type_key, max_active=max_active, emit_output=False)
            except Exception:
                pass
    except Exception:
        return 0
    return 0

def _hooks_post_skill_continuation(completed_skill: str) -> None:
    """If the snapshot has returnTo, emit a mandatory continuation message."""
    try:
        from scripts._skill_state import load_snapshot

        state_base_dir = _skill_state_base_dir()
        snapshot = load_snapshot(state_base_dir)
        if snapshot is None:
            return

        return_to = snapshot.get("returnTo")
        if not isinstance(return_to, dict):
            return

        parent_skill = return_to.get("skill", "")
        parent_step = return_to.get("step")
        if not parent_skill:
            return

        # Only emit when the completed skill is NOT the parent itself
        # (avoid loop when the parent skill completes normally)
        skill_short = completed_skill.replace("mst:", "")
        if skill_short == parent_skill:
            return

        step_info = f"/{parent_step}" if parent_step is not None else ""
        print(
            f"\n⚠️ MANDATORY CONTINUATION: "
            f"return_to={parent_skill}{step_info} detected. "
            f"The sub-skill '{completed_skill}' has completed and MUST return control to the parent skill. "
            f"You MUST immediately call Skill(skill: \"mst:{parent_skill}\") to resume. "
            f"Do NOT end the conversation or ask the user — continue NOW.\n"
        )
    except Exception:
        pass


def register(subparsers):
    sub = subparsers
    hooks = sub.add_parser("hooks")
    hooks_sub = hooks.add_subparsers(dest="subcommand")
    hooks_post_skill = hooks_sub.add_parser("post-skill")
    hooks_post_skill.set_defaults(func=cmd_hooks_post_skill)
