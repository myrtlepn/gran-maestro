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
)

def cmd_context_gather(args):
    root = _project_root()

    # Git Status
    git_status_data = {"modified": 0, "added": 0, "deleted": 0}
    git_status_raw = None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(root)
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            for line in lines:
                if len(line) >= 2:
                    xy = line[:2]
                    if "M" in xy:
                        git_status_data["modified"] += 1
                    elif "A" in xy or "?" in xy:
                        git_status_data["added"] += 1
                    elif "D" in xy:
                        git_status_data["deleted"] += 1
            git_status_raw = lines
        else:
            git_status_raw = None
    except Exception:
        git_status_raw = None

    # Recent Changes
    diff_n = getattr(args, "diff", 1) or 1
    recent_changes = []
    try:
        result = subprocess.run(
            ["git", "diff", f"HEAD~{diff_n}..HEAD", "--name-only"],
            capture_output=True, text=True, cwd=str(root)
        )
        if result.returncode == 0:
            recent_changes = [l for l in result.stdout.splitlines() if l.strip()]
        else:
            recent_changes = None
    except Exception:
        recent_changes = None

    # Version
    versions = _read_versions()
    version_synced = (
        versions["package"]
        == versions["plugin"]
        == versions["marketplace"]
        == versions["ext_manifest"]
        == versions["ext_package"]
        and versions["package"] != ""
    )

    # Skills
    skills_list = []
    skills_dir = root / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                skill_name = None
                try:
                    for line in skill_md.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("name:"):
                            skill_name = line[5:].strip().strip('"').strip("'")
                            break
                except Exception:
                    pass
                skills_list.append(skill_name if skill_name else skill_dir.name)
            else:
                skills_list.append(skill_dir.name)

    # Agents
    agents_list = []
    agents_dir = root / "agents"
    if agents_dir.exists():
        for agent_file in sorted(agents_dir.glob("*.md")):
            agents_list.append(agent_file.stem)

    fmt = getattr(args, "format", "text") or "text"
    include_skills = getattr(args, "skills", True)
    include_agents = getattr(args, "agents", True)

    if fmt == "json":
        output = {
            "git_status": git_status_data if git_status_raw is not None else "(git 없음)",
            "recent_changes": recent_changes if recent_changes is not None else "(git 없음)",
            "version": {
                "package":     versions["package"],
                "plugin":      versions["plugin"],
                "marketplace": versions["marketplace"],
                "synced":      version_synced,
            },
        }
        if include_skills:
            output["skills"] = skills_list
        if include_agents:
            output["agents"] = agents_list
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # text format
        print("## Git Status")
        if git_status_raw is None:
            print("(git 없음)")
        else:
            print(f"Modified: {git_status_data['modified']} | Added: {git_status_data['added']} | Deleted: {git_status_data['deleted']}")
        print()

        print(f"## Recent Changes (HEAD~{diff_n}..HEAD)")
        if recent_changes is None:
            print("(git 없음)")
        elif recent_changes:
            for f in recent_changes:
                print(f)
        else:
            print("(변경 없음)")
        print()

        print("## Version")
        print(f"package.json:      {versions['package']}")
        print(f"plugin.json:       {versions['plugin']}")
        print(f"marketplace.json:  {versions['marketplace']}")
        print("✓ 동기화됨" if version_synced else "✗ 불일치")
        print()

        if include_skills:
            print(f"## Skills ({len(skills_list)})")
            print(", ".join(skills_list) if skills_list else "(없음)")
            print()

        if include_agents:
            print(f"## Agents ({len(agents_list)})")
            print(", ".join(agents_list) if agents_list else "(없음)")
            print()

    return 0


def register(subparsers):
    sub = subparsers
    ctx = sub.add_parser("context")
    ctx_sub = ctx.add_subparsers(dest="subcommand")

    ctx_gather = ctx_sub.add_parser("gather")
    ctx_gather.add_argument("--diff", type=int, default=1)
    ctx_gather.add_argument("--skills", action="store_true", default=True)
    ctx_gather.add_argument("--no-skills", dest="skills", action="store_false")
    ctx_gather.add_argument("--agents", action="store_true", default=True)
    ctx_gather.add_argument("--no-agents", dest="agents", action="store_false")
    ctx_gather.add_argument("--format", choices=["text", "json"], default="text")
