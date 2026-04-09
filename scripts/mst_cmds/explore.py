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
    save_json,
)

_EXPLORE_INDEX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._-])(?:\.{1,2}/|/)?(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"
)

_EXPLORE_INDEX_STOPWORDS = {
    "and", "are", "for", "from", "into", "that", "the", "this", "with",
    "있는", "으로", "에서", "이다", "하는", "사항", "결과", "요약", "추가", "탐색",
    "범위", "구조적", "관계", "영역", "제안", "파일", "경로", "기준", "확인",
}

def _extract_markdown_section(text: str, title: str) -> str:
    heading_re = re.compile(
        rf"^\s{{0,3}}#{{1,6}}\s+(?:\*\*)?{re.escape(title)}(?:\*\*)?\s*$",
        re.MULTILINE,
    )
    match = heading_re.search(text)
    if not match:
        return ""

    section_start = match.end()
    remainder = text[section_start:]
    next_heading = re.search(r"^\s{0,3}#{1,6}\s+.+$", remainder, re.MULTILINE)
    section_end = section_start + (next_heading.start() if next_heading else len(remainder))
    return text[section_start:section_end].strip()

def _normalize_path_candidate(raw: str):
    candidate = (raw or "").strip().strip("`*\"'()[]{}<>.,;:")
    if not candidate:
        return None
    if "://" in candidate or candidate.startswith("/mst:"):
        return None
    if "/" not in candidate:
        return None
    return candidate

def _extract_paths(text: str):
    seen = set()
    paths = []
    for raw in _EXPLORE_INDEX_PATH_RE.findall(text or ""):
        candidate = _normalize_path_candidate(raw)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        paths.append(candidate)
    return paths

def _extract_keywords(text: str, limit: int = 30):
    cleaned = re.sub(r"`[^`]+`", " ", text or "")
    cleaned = _EXPLORE_INDEX_PATH_RE.sub(" ", cleaned)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[가-힣]{2,}", cleaned)

    frequencies = {}
    for token in tokens:
        keyword = token.lower()
        if keyword in _EXPLORE_INDEX_STOPWORDS or keyword.startswith("exp-"):
            continue
        frequencies[keyword] = frequencies.get(keyword, 0) + 1

    ranked = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
    return [keyword for keyword, _ in ranked[:limit]]

def cmd_explore_index(args):
    report_path = Path(args.report).expanduser()
    if not report_path.is_absolute():
        report_path = (Path.cwd() / report_path).resolve()
    if not report_path.exists() or not report_path.is_file():
        print(f"Error: report file not found: {report_path}", file=sys.stderr)
        return 1

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to read report file ({exc})", file=sys.stderr)
        return 1

    scope_section = _extract_markdown_section(report_text, "탐색 범위")
    findings_section = _extract_markdown_section(report_text, "발견 사항")
    relations_section = _extract_markdown_section(report_text, "구조적 관계")

    scope_files = _extract_paths(scope_section)
    finding_keywords = _extract_keywords(findings_section)
    related_paths = _extract_paths("\n".join([findings_section, relations_section]))
    if not related_paths:
        related_paths = _extract_paths(report_text)

    payload = {
        "탐색 범위 파일 목록": scope_files,
        "발견 사항 키워드": finding_keywords,
        "관련 파일 경로": related_paths,
    }

    output_path = Path(args.output).expanduser() if args.output else report_path.with_name("index.json")
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()

    try:
        save_json(output_path, payload)
    except OSError as exc:
        print(f"Error: failed to write index file ({exc})", file=sys.stderr)
        return 1

    print(str(output_path))
    return 0


def register(subparsers):
    sub = subparsers
    explore = sub.add_parser("explore")
    explore_sub = explore.add_subparsers(dest="subcommand")
    explore_index = explore_sub.add_parser("index", help="explore-report.md 파싱 후 index.json 생성")
    explore_index.add_argument("--report", required=True, help="입력 explore-report.md 경로")
    explore_index.add_argument("--output", help="출력 index.json 경로 (기본: report 파일과 동일 디렉토리)")
