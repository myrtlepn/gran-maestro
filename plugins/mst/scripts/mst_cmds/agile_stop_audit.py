from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.mst_cmds._common import _agi_session_dir, _normalize_agi_id


def _stop_audit_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "stop-audit.ndjson"


def _load_stop_audit_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []

    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    return entries


def _normalize_group_key(value) -> str:
    if value is None:
        return "null"
    return str(value)


def cmd_agile_stop_audit_list(args):
    try:
        agi_id = _normalize_agi_id(args.agi)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    entries = _load_stop_audit_entries(_stop_audit_path(agi_id))
    classification = getattr(args, "classification", None)
    if classification:
        entries = [
            entry
            for entry in entries
            if str(entry.get("classification", "")).strip() == classification
        ]

    if getattr(args, "json", False):
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    print("event_id | timestamp | classification | declared_reason")
    for entry in entries:
        event_id = str(entry.get("event_id", "")).strip()
        timestamp = str(entry.get("timestamp", "")).strip()
        row_classification = str(entry.get("classification", "")).strip()
        declared_reason = _normalize_group_key(entry.get("declared_reason"))
        print(f"{event_id} | {timestamp} | {row_classification} | {declared_reason}")
    return 0


def cmd_agile_stop_audit_aggregate(args):
    try:
        agi_id = _normalize_agi_id(args.agi)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    entries = _load_stop_audit_entries(_stop_audit_path(agi_id))
    group_by = str(args.group_by).strip()

    counts: dict[str, int] = {}
    for entry in entries:
        key = _normalize_group_key(entry.get(group_by))
        counts[key] = counts.get(key, 0) + 1

    for key in sorted(counts.keys()):
        print(f"{key}: {counts[key]}")
    return 0


def cmd_agile_stop_audit(args):
    subcommand = getattr(args, "stop_audit_subcommand", None)
    dispatch = {
        "list": cmd_agile_stop_audit_list,
        "aggregate": cmd_agile_stop_audit_aggregate,
    }
    fn = dispatch.get(subcommand)
    if fn is None:
        print("Error: stop-audit subcommand is required (list|aggregate)", file=sys.stderr)
        return 1
    return fn(args)
