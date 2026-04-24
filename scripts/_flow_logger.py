#!/usr/bin/env python3
"""Append flow-detail.ndjson events for Gran Maestro hook diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


FLOW_LOG_FILENAME = "flow.ndjson"


def timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_session_id(value: str) -> str:
    cleaned = []
    for char in str(value or ""):
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "unknown"


def flow_detail_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "state" / safe_session_id(session_id) / "flow-detail.ndjson"


def flow_log_path(project_root: Path, *, override: Optional[str] = None) -> Path:
    log_dir = os.environ.get("MST_FLOW_LOG_DIR") or override
    if log_dir:
        return Path(log_dir) / FLOW_LOG_FILENAME
    return project_root / ".gran-maestro" / "logs" / FLOW_LOG_FILENAME


def _load_json_object(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"--data must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("--data must be a JSON object")
    return payload


def _load_snapshot(snapshot_path: Optional[str]) -> Optional[Any]:
    if not snapshot_path:
        return None
    path = Path(snapshot_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def append_event(
    project_root: Path,
    session_id: str,
    event_type: str,
    data: Dict[str, Any],
    *,
    snapshot_path: Optional[str] = None,
    stdin_digest: Optional[str] = None,
    ppid: Optional[str] = None,
) -> Path:
    event_data = dict(data)
    snapshot_dump = _load_snapshot(snapshot_path)
    if snapshot_dump is not None:
        event_data.setdefault("snapshot_dump", snapshot_dump)
    if stdin_digest:
        event_data.setdefault("stdin_digest", stdin_digest)
    if ppid:
        event_data.setdefault("ppid", ppid)

    entry = {
        "timestamp": timestamp_now(),
        "event_type": str(event_type or "event"),
        "session_id": safe_session_id(session_id),
        "data": event_data,
    }

    path = flow_detail_path(project_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
    return path


def append_skill_event(
    project_root: Path,
    session_id: str,
    *,
    skill: str,
    step: int,
    total_steps: int,
    event_type: str,
    parent_skill: Optional[str] = None,
    parent_step: Optional[int] = None,
    duration_ms: Optional[float] = None,
    extras: Optional[Dict[str, Any]] = None,
    schema_version: int = 1,
) -> Optional[Path]:
    try:
        entry = {
            "timestamp": timestamp_now(),
            "session_id": safe_session_id(session_id),
            "skill": str(skill),
            "step": step,
            "total_steps": total_steps,
            "event_type": str(event_type),
            "parent_skill": parent_skill,
            "parent_step": parent_step,
            "duration_ms": duration_ms,
            "extras": extras if isinstance(extras, dict) else {},
            "schema_version": schema_version,
        }
        path = flow_log_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", buffering=1) as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
        return None


def append_command(args: argparse.Namespace) -> int:
    data = _load_json_object(args.data)
    append_event(
        Path(args.project_root).resolve(),
        args.session_id,
        args.event_type,
        data,
        snapshot_path=args.snapshot_path,
        stdin_digest=args.stdin_digest,
        ppid=args.ppid,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append")
    append.add_argument("--project-root", default=os.getcwd())
    append.add_argument("--session-id", required=True)
    append.add_argument("--event-type", required=True)
    append.add_argument("--data", default="{}")
    append.add_argument("--snapshot-path")
    append.add_argument("--stdin-digest")
    append.add_argument("--ppid")
    append.set_defaults(func=append_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
