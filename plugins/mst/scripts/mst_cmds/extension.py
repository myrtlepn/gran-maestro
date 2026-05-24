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

def _dir_content_hash(directory: Path) -> str:
    EXCLUDED_HASH_PARTS = {"node_modules", ".git", ".omc"}

    if not directory.exists():
        return ""

    hasher = hashlib.sha256()

    try:
        entries = sorted(
            [entry for entry in directory.rglob("*") if entry.is_file() and not entry.is_symlink()],
            key=lambda entry: str(entry.relative_to(directory).as_posix()),
        )
    except Exception:
        return ""

    for path in entries:
        relative_path = path.relative_to(directory)
        if relative_path.name == ".content-hash":
            continue
        if any(part in EXCLUDED_HASH_PARTS for part in relative_path.parts):
            continue
        try:
            hasher.update(str(relative_path.as_posix()).encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(path.read_bytes())
        except Exception:
            continue

    return hasher.hexdigest()

def _ensure_copy_impl(plugin_root: Path, home_dir: Path) -> int:
    if sys.platform == "win32":
        print("미지원 OS", file=sys.stderr)
        return 1

    src = plugin_root / "extension"
    dst = home_dir / "chrome-extension"

    is_project = (plugin_root / ".git").exists() and src.is_dir()
    if is_project:
        print("프로젝트 설치 감지. 직접 경로 사용 권장", file=sys.stderr)
        print("skipped")
        return 0

    if not src.exists():
        if dst.exists():
            print("경고: 플러그인 extension/ 경로가 없어 stale 상태일 수 있습니다.", file=sys.stderr)
        print("unchanged")
        return 0

    try:
        home_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[extension ensure-copy] 대상 상위 디렉토리 생성 실패: {exc}", file=sys.stderr)
        print("unchanged")
        return 0

    if not dst.exists():
        try:
            shutil.copytree(src, dst)
        except Exception as exc:
            print(f"[extension ensure-copy] extension 복사 실패: {exc}", file=sys.stderr)
            print("unchanged")
            return 0
        try:
            (dst / ".content-hash").write_text(_dir_content_hash(src), encoding="utf-8")
        except Exception:
            pass
        print("created")
        return 0

    src_hash = _dir_content_hash(src)
    dst_hash = ""
    try:
        dst_hash = (dst / ".content-hash").read_text(encoding="utf-8").strip()
    except Exception:
        pass

    if src_hash != dst_hash:
        try:
            shutil.rmtree(dst)
            shutil.copytree(src, dst)
        except Exception as exc:
            print(f"[extension ensure-copy] 버전 변경 반영 실패: {exc}", file=sys.stderr)
            print("unchanged")
            return 0
        try:
            (dst / ".content-hash").write_text(src_hash, encoding="utf-8")
        except Exception:
            pass
        print("updated")
        return 0

    print("unchanged")
    return 0

def cmd_extension_ensure_copy(args):
    plugin_root = _common._plugin_root()
    home_dir = Path.home() / ".gran-maestro"
    return _ensure_copy_impl(plugin_root, home_dir)


def register(subparsers):
    sub = subparsers
    ext = sub.add_parser("extension")
    ext_sub = ext.add_subparsers(dest="subcommand")
    ext_sub.add_parser("ensure-copy")
