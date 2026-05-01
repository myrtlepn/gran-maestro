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
    load_json,
)


def _canonical_uuid4(value: str) -> str | None:
    try:
        parsed = uuid.UUID(str(value).strip())
    except (TypeError, ValueError):
        return None
    canonical = str(parsed)
    if parsed.variant != uuid.RFC_4122 or parsed.version != 4 or canonical != str(value).strip():
        return None
    return canonical


def _session_id_from_payload(raw: str) -> str | None:
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    direct = payload.get("session_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    transcript_path = payload.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path.strip():
        stem = Path(transcript_path).name
        return stem[:-6] if stem.endswith(".jsonl") else Path(stem).stem
    return None


def _session_id_from_stdin_or_env_payload() -> str | None:
    raw = os.environ.get("MST_HOOK_STDIN_RAW", "")
    if raw:
        return _session_id_from_payload(raw)
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        return _session_id_from_payload(sys.stdin.read())
    except Exception:
        return None


def _session_id_from_bridge() -> str | None:
    base_dir = _common.BASE_DIR
    if base_dir is None:
        env_base = os.environ.get("MST_BASE_DIR", "").strip()
        base_dir = Path(env_base) if env_base else None
    if base_dir is None:
        return None
    bridge_path = base_dir / "tmp" / f"claude-session-{os.getppid()}.id"
    try:
        return _canonical_uuid4(bridge_path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def resolve_session_id_value() -> str:
    env_value = os.environ.get("MST_SESSION_ID", "").strip()
    if env_value:
        return env_value

    for candidate in (
        _session_id_from_bridge(),
        _session_id_from_stdin_or_env_payload(),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return str(uuid.uuid4())


def ensure_session_id_in_env() -> str:
    session_id = resolve_session_id_value()
    if not session_id:
        raise RuntimeError("MST_SESSION_ID could not be resolved")
    os.environ["MST_SESSION_ID"] = session_id
    return session_id


def child_env_with_session_id() -> dict[str, str]:
    session_id = ensure_session_id_in_env()
    child_env = os.environ.copy()
    child_env["MST_SESSION_ID"] = session_id
    return child_env


def cmd_session_resolve(args):
    session_id = resolve_session_id_value()
    if args.json:
        print(json.dumps({"session_id": session_id}, ensure_ascii=False))
    else:
        print(session_id)
    return 0

def cmd_session_split_prompts(args):
    if not args.prompts_dir:
        print("Error: directory not found", file=sys.stderr)
        return 1

    prompts_dir = Path(args.prompts_dir)
    if not prompts_dir.exists():
        print("Error: directory not found", file=sys.stderr)
        return 1

    combined_path = prompts_dir / "combined-prompts.txt"
    if not combined_path.exists():
        print("Error: combined-prompts.txt not found", file=sys.stderr)
        return 1

    content = combined_path.read_text(encoding="utf-8")
    marker_re = re.compile(r"^===SPLIT: (.+)===$")
    generated = []
    target_name = None
    target_lines = []

    for raw_line in content.splitlines(keepends=True):
        m = marker_re.match(raw_line.strip())
        if m:
            if target_name is not None:
                out_path = prompts_dir / target_name
                out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
                generated.append(str(out_path))
                print(str(out_path))
            target_name = m.group(1)
            target_lines = []
            continue

        if target_name is not None:
            target_lines.append(raw_line)

    if target_name is not None:
        out_path = prompts_dir / target_name
        out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
        generated.append(str(out_path))
        print(str(out_path))

    return 0

def cmd_session_list(args):
    session_type = args.type
    type_map = {"ideation": ("ideation", "IDN"), "discussion": ("discussion", "DSC"), "debug": ("debug", "DBG")}
    types_to_scan = [type_map[session_type]] if session_type in type_map else list(type_map.values())

    for subdir, prefix in types_to_scan:
        sdir = _common.BASE_DIR / subdir
        if not sdir.exists():
            continue
        for sess in sorted(sdir.glob(f"{prefix}-*")):
            if not sess.is_dir():
                continue
            sj = load_json(sess / "session.json") or {}
            topic = (sj.get("topic") or sj.get("title") or "")[:50]
            print(f"{sess.name:<15} {subdir:<12} {topic}")
    return 0

def cmd_session_inspect(args):
    sess_id = args.session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix, "ideation")
    sess_path = _common.BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj:
        print(json.dumps(sj, ensure_ascii=False, indent=2))
    return 0

def cmd_session_complete(args):
    sess_id = args.session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix)
    if subdir is None:
        print(f"Error: Unknown session type '{prefix}'. Expected IDN/DSC/DBG.", file=sys.stderr)
        return 1
    sess_path = _common.BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj is None:
        print(f"Error: session.json not found for {sess_id}.", file=sys.stderr)
        return 1
    if sj.get("status") == "completed":
        print(f"{sess_id} is already completed.")
        return 0
    from scripts._state_manager import complete
    complete(_common.BASE_DIR, sess_id)
    print(f"Completed: {sess_id}")
    return 0


def register(subparsers):
    sub = subparsers
    sess = sub.add_parser("session")
    sess_sub = sess.add_subparsers(dest="subcommand")

    sess_list = sess_sub.add_parser("list")
    sess_list.add_argument("--type", choices=["ideation", "discussion", "debug"])

    sess_inspect = sess_sub.add_parser("inspect")
    sess_inspect.add_argument("session_id")

    sess_complete = sess_sub.add_parser("complete")
    sess_complete.add_argument("session_id")

    sess_resolve = sess_sub.add_parser("resolve")
    sess_resolve.add_argument("--json", action="store_true")

    sess_split = sess_sub.add_parser("split-prompts", help="combined-prompts.txt를 개별 프롬프트 파일로 분리")
    sess_split.add_argument("--dir", dest="prompts_dir", required=False, help="prompts 디렉토리 경로")
