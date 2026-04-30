from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.mst_cmds import _common


COUNTER_KEYS = ("CORE-BLOCK", "POLICY-BLOCK", "PENDING", "OVERRIDE", "WARN")
EVENT_TYPE_TO_COUNTER = {
    "core_block": "CORE-BLOCK",
    "policy_block": "POLICY-BLOCK",
    "confirm_requested": "PENDING",
    "pending_confirm_created": "PENDING",
    "override_granted": "OVERRIDE",
    "warn_auto_allow": "WARN",
}
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _zero_counts() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def _valid_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or "/" in value or ".." in value or not SESSION_ID_RE.fullmatch(value):
        return ""
    return value


def read_counters(session_id: str, project_root: Path) -> dict[str, int]:
    counts = _zero_counts()
    clean_session_id = _valid_session_id(session_id)
    if not clean_session_id:
        return counts

    history_path = _common.sessions_dir(Path(project_root)) / clean_session_id / "history.ndjson"
    if not history_path.is_file():
        return counts

    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return counts

    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        event = row.get("event")
        if not isinstance(event, dict):
            continue
        counter_key = EVENT_TYPE_TO_COUNTER.get(event.get("type"))
        if counter_key:
            counts[counter_key] += 1

    return counts


def format_line(session_id: str, project_root: Path) -> str:
    counts = read_counters(session_id, project_root)
    return " ".join(f"[{key}:{counts[key]}]" for key in COUNTER_KEYS)
