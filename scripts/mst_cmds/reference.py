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
    DEFAULT_REFERENCE_CONFIG,
    DEFAULT_REFERENCE_KEYWORDS,
    _parse_utc_datetime,
    _plugin_root,
    deep_merge,
    load_json,
    save_json,
)

def references_dir() -> Path:
    return _common.BASE_DIR / "references"

def _normalize_reference_id(value: str) -> str:
    ref_id = (value or "").strip().upper()
    if not re.fullmatch(r"REF-\d+", ref_id):
        raise ValueError(f"Invalid reference id: {value}")
    return ref_id

def _reference_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "reference.json"

def _reference_content_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "content.md"

def _iter_reference_paths():
    pattern = str(references_dir() / "REF-*" / "reference.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]

def _coerce_positive_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback

def _load_reference_config():
    config = dict(DEFAULT_REFERENCE_CONFIG)
    config["keywords_whitelist"] = list(DEFAULT_REFERENCE_KEYWORDS)

    resolved = load_json(_common.BASE_DIR / "config.resolved.json")
    if not isinstance(resolved, dict):
        defaults = load_json(_plugin_root() / "templates" / "defaults" / "config.json") or {}
        overrides = load_json(_common.BASE_DIR / "config.json") or {}
        resolved = deep_merge(defaults, overrides)

    raw_reference = resolved.get("reference")
    if not isinstance(raw_reference, dict):
        return config

    config["cache_ttl_days"] = _coerce_positive_int(
        raw_reference.get("cache_ttl_days"),
        DEFAULT_REFERENCE_CONFIG["cache_ttl_days"],
    )
    config["cutoff_threshold_months"] = _coerce_positive_int(
        raw_reference.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )
    config["auto_search"] = bool(raw_reference.get("auto_search", DEFAULT_REFERENCE_CONFIG["auto_search"]))
    config["max_searches_per_step"] = _coerce_positive_int(
        raw_reference.get("max_searches_per_step"),
        DEFAULT_REFERENCE_CONFIG["max_searches_per_step"],
    )

    keywords = raw_reference.get("keywords_whitelist")
    if isinstance(keywords, list):
        normalized = []
        for keyword in keywords:
            text = str(keyword).strip()
            if text:
                normalized.append(text)
        if normalized:
            config["keywords_whitelist"] = normalized

    return config

def _compute_reference_expires_at(searched_at, cache_ttl_days: int):
    searched_dt = _parse_utc_datetime(searched_at)
    if searched_dt is None:
        return None
    return (searched_dt + timedelta(days=cache_ttl_days)).isoformat()

def _check_reference_freshness(reference_data, config=None, now=None):
    if not isinstance(reference_data, dict):
        return "expired"

    searched_dt = _parse_utc_datetime(reference_data.get("searched_at"))
    if searched_dt is None:
        return "expired"

    if config is None:
        config = _load_reference_config()
    ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])
    cutoff_months = _coerce_positive_int(
        config.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )

    now_dt = now or datetime.now(timezone.utc)
    freshness = "fresh"
    if searched_dt + timedelta(days=ttl_days) < now_dt:
        freshness = "stale"

    cutoff_delta = timedelta(days=cutoff_months * 30)
    if (now_dt - searched_dt) > cutoff_delta:
        freshness = "expired"
    return freshness

def _detect_reference_keywords(text: str, keywords_whitelist=None):
    if not isinstance(text, str) or not text.strip():
        return []

    keywords = keywords_whitelist
    if keywords is None:
        keywords = _load_reference_config().get("keywords_whitelist", [])
    if not isinstance(keywords, list):
        return []

    lowered = text.lower()
    matches = []
    for keyword in keywords:
        candidate = str(keyword).strip()
        if not candidate:
            continue
        if candidate.lower() in lowered:
            matches.append(candidate)
    return sorted(set(matches))

def _build_reference_prompt_block(reference_entries, model_cutoff_date: str, now=None):
    now_dt = now or datetime.now(timezone.utc)
    lines = [
        "[REFERENCE_CONTEXT]",
        f"current_date: {now_dt.date().isoformat()}",
        f"model_cutoff: {model_cutoff_date}",
    ]
    if not isinstance(reference_entries, list) or not reference_entries:
        lines.append("references: none")
    else:
        lines.append("references:")
        for entry in reference_entries:
            if not isinstance(entry, dict):
                continue
            lines.append(
                "- {id} ({freshness}) {topic} | {url}".format(
                    id=entry.get("id", "-"),
                    freshness=entry.get("freshness", "unknown"),
                    topic=entry.get("topic", "-"),
                    url=entry.get("url", "-"),
                )
            )
    lines.append("[/REFERENCE_CONTEXT]")
    return "\n".join(lines)

def _load_reference(ref_id: str):
    normalized_id = _normalize_reference_id(ref_id)
    ref_path = _reference_path(normalized_id)
    content_path = _reference_content_path(normalized_id)
    data = load_json(ref_path)
    if not isinstance(data, dict):
        raise ValueError(f"{normalized_id} not found")

    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    data["id"] = normalized_id
    data["topic"] = str(data.get("topic", ""))
    data["url"] = str(data.get("url", ""))
    data["summary"] = str(data.get("summary", ""))
    data["searched_at"] = str(data.get("searched_at", ""))
    expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
    data["expires_at"] = expires_at or str(data.get("expires_at", ""))
    data["freshness"] = _check_reference_freshness(data, config=config)
    data["content_path"] = str(Path(".gran-maestro") / "references" / normalized_id / "content.md")
    try:
        if content_path.exists():
            content = content_path.read_text(encoding="utf-8")
            data["content"] = content if content else None
        else:
            data["content"] = None
    except (OSError, UnicodeDecodeError):
        data["content"] = None
    return data, ref_path

def _save_reference(data, content=None):
    ref_id = _normalize_reference_id(data.get("id", ""))
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    payload = dict(data)
    payload["id"] = ref_id
    payload["topic"] = str(payload.get("topic", ""))
    payload["url"] = str(payload.get("url", ""))
    payload["summary"] = str(payload.get("summary", ""))
    searched_at = str(payload.get("searched_at", "")).strip()
    if not searched_at:
        searched_at = datetime.now(timezone.utc).isoformat()
    payload["searched_at"] = searched_at
    expires_at = _compute_reference_expires_at(searched_at, cache_ttl_days)
    payload["expires_at"] = expires_at or str(payload.get("expires_at", ""))
    payload["freshness"] = _check_reference_freshness(payload, config=config)
    payload["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
    save_json(_reference_path(ref_id), payload)

    content_path = _reference_content_path(ref_id)
    content_path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        if not content_path.exists():
            content_path.write_text("", encoding="utf-8")
    else:
        content_path.write_text(str(content), encoding="utf-8")

def _next_reference_id():
    cmd = [
        sys.executable,
        str(_common._mst_script_path()),
        "counter",
        "next",
        "--type",
        "ref",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_common.BASE_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "counter next failed")

    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("counter next produced no id")

def cmd_reference_add(args):
    try:
        reference_id = _next_reference_id()
    except RuntimeError as exc:
        print(f"Error: failed to allocate reference id ({exc})", file=sys.stderr)
        return 1

    payload = {
        "id": reference_id,
        "topic": str(args.topic),
        "url": str(args.url),
        "summary": str(args.summary),
        "searched_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_reference(payload, content=args.content)
    data, _ = _load_reference(reference_id)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(reference_id)
    return 0

def cmd_reference_get(args):
    try:
        data, _ = _load_reference(args.reference_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(
            f"{data.get('id', '')} "
            f"[{data.get('freshness', 'unknown')}] "
            f"{data.get('topic', '')} - {data.get('url', '')}"
        )
    return 0

def cmd_reference_list(args):
    entries = []
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    for ref_path in _iter_reference_paths():
        data = load_json(ref_path)
        if not isinstance(data, dict):
            continue

        ref_id = str(data.get("id") or ref_path.parent.name).upper()
        data["id"] = ref_id
        data["topic"] = str(data.get("topic", ""))
        data["url"] = str(data.get("url", ""))
        data["summary"] = str(data.get("summary", ""))
        data["searched_at"] = str(data.get("searched_at", ""))
        expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
        data["expires_at"] = expires_at or str(data.get("expires_at", ""))
        data["freshness"] = _check_reference_freshness(data, config=config)
        data["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
        entries.append(data)

    entries.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No references found.")
        return 0

    print(f"{'ID':<8} {'Freshness':<10} {'Topic':<32} {'URL'}")
    print("-" * 100)
    for entry in entries:
        topic = entry.get("topic", "")
        if len(topic) > 31:
            topic = topic[:28] + "..."
        print(
            f"{entry.get('id', ''):<8} "
            f"{entry.get('freshness', 'unknown'):<10} "
            f"{topic:<32} "
            f"{entry.get('url', '')}"
        )
    return 0

def cmd_reference_search(args):
    keyword = (args.keyword or "").strip().lower()
    if not keyword:
        if args.json:
            print("[]")
        else:
            print("No matching references found.")
        return 0

    matches = []
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])
    for ref_path in _iter_reference_paths():
        data = load_json(ref_path)
        if not isinstance(data, dict):
            continue

        topic = str(data.get("topic", ""))
        summary = str(data.get("summary", ""))
        if keyword not in topic.lower() and keyword not in summary.lower():
            continue

        ref_id = str(data.get("id") or ref_path.parent.name).upper()
        data["id"] = ref_id
        data["url"] = str(data.get("url", ""))
        data["topic"] = topic
        data["summary"] = summary
        data["searched_at"] = str(data.get("searched_at", ""))
        expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
        data["expires_at"] = expires_at or str(data.get("expires_at", ""))
        data["freshness"] = _check_reference_freshness(data, config=config)
        data["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
        matches.append(data)

    matches.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if not matches:
        print("No matching references found.")
        return 0

    for item in matches:
        print(
            f"{item.get('id', '')} [{item.get('freshness', 'unknown')}] "
            f"{item.get('topic', '')} - {item.get('url', '')}"
        )
    return 0

def cmd_reference_update(args):
    try:
        data, _ = _load_reference(args.reference_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed = False
    if args.topic is not None:
        data["topic"] = str(args.topic)
        changed = True
    if args.url is not None:
        data["url"] = str(args.url)
        changed = True
    if args.summary is not None:
        data["summary"] = str(args.summary)
        changed = True
    if args.searched_at is not None:
        data["searched_at"] = str(args.searched_at)
        changed = True
    if args.content is not None:
        changed = True

    if not changed:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_reference(data, content=args.content)
    updated, _ = _load_reference(data.get("id", ""))

    if args.json:
        print(json.dumps(updated, ensure_ascii=False, indent=2))
    else:
        print(updated.get("id"))
    return 0


def register(subparsers):
    sub = subparsers
    reference = sub.add_parser("reference")
    reference_sub = reference.add_subparsers(dest="subcommand")

    reference_add = reference_sub.add_parser("add")
    reference_add.add_argument("--topic", required=True)
    reference_add.add_argument("--url", required=True)
    reference_add.add_argument("--summary", required=True)
    reference_add.add_argument(
        "--content",
        help=(
            "content.md용 raw 발췌를 저장한다. 결론 요약만 입력하지 말고 원문 근거를 남긴다 "
            "(예: 인용, 표, 코드 스니펫 + 출처 URL/날짜)."
        ),
    )
    reference_add.add_argument("--json", action="store_true")

    reference_get = reference_sub.add_parser("get")
    reference_get.add_argument("reference_id")
    reference_get.add_argument("--json", action="store_true")

    reference_list = reference_sub.add_parser("list")
    reference_list.add_argument("--json", action="store_true")

    reference_search = reference_sub.add_parser("search")
    reference_search.add_argument("--keyword", required=True)
    reference_search.add_argument("--json", action="store_true")

    reference_update = reference_sub.add_parser("update")
    reference_update.add_argument("reference_id")
    reference_update.add_argument("--topic")
    reference_update.add_argument("--url")
    reference_update.add_argument("--summary")
    reference_update.add_argument("--searched-at")
    reference_update.add_argument(
        "--content",
        help=(
            "content.md를 raw 발췌 중심으로 갱신한다. 결론 요약만 입력하지 말고 원문 근거를 보강한다 "
            "(예: 인용, 표, 코드 스니펫 + 출처 URL/날짜)."
        ),
    )
    reference_update.add_argument("--json", action="store_true")
