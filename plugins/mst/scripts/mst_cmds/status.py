from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    _load_config_for_get,
    _skill_state_base_dir,
    _workflow_state_file,
    load_json,
)


MODEL_WINDOWS = {
    "claude-opus-4-7": 1_000_000,
    "claude-sonnet-4-6": 200_000,
}

TOKEN_KEYS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _read_stdin_payload() -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_int(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _message_payload(row: dict) -> dict:
    message = row.get("message")
    if isinstance(message, dict):
        return message
    return row


def _extract_model_id(row: dict) -> str:
    for container in (_message_payload(row), row):
        model = container.get("model") if isinstance(container, dict) else None
        if isinstance(model, str) and model.strip():
            return model.strip()
        if isinstance(model, dict):
            for key in ("id", "display_name", "name"):
                value = model.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _extract_usage(row: dict) -> dict:
    message = _message_payload(row)
    usage = message.get("usage") if isinstance(message, dict) else None
    if isinstance(usage, dict):
        return usage
    usage = row.get("usage")
    if isinstance(usage, dict):
        return usage
    return {}


def _load_last_transcript_message(transcript_path: str) -> dict | None:
    if not transcript_path:
        return None
    path = Path(transcript_path)
    try:
        last_row = None
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                if isinstance(row, dict):
                    last_row = row
        return last_row
    except Exception:
        return None


def _model_window(model_id: str) -> int | None:
    value = (model_id or "").strip().lower()
    if not value:
        return None
    for key, window in MODEL_WINDOWS.items():
        if key in value:
            return window
    return None


def _context_usage_from_transcript(transcript_path: str) -> tuple[int, int | None, float | None, bool]:
    last_row = _load_last_transcript_message(transcript_path)
    if not isinstance(last_row, dict):
        return 0, None, None, False

    usage = _extract_usage(last_row)
    input_tokens = _as_int(usage.get("input_tokens"))
    cache_read_tokens = _as_int(usage.get("cache_read_input_tokens"))
    cache_creation_tokens = _as_int(usage.get("cache_creation_input_tokens"))
    context_tokens = input_tokens + cache_read_tokens + cache_creation_tokens
    cache_available = cache_read_tokens > 0 or cache_creation_tokens > 0

    model_id = os.environ.get("CLAUDE_MODEL", "").strip() or _extract_model_id(last_row)
    window = _model_window(model_id)
    context_pct = None
    if window:
        context_pct = round(context_tokens / window, 6)
    return context_tokens, window, context_pct, cache_available


def _resolve_state_file(raw_path: str | None) -> Path:
    if raw_path:
        return Path(raw_path)
    return _workflow_state_file(_skill_state_base_dir())


def _state_flags(state_file: Path) -> tuple[bool, bool]:
    payload = load_json(state_file)
    if not isinstance(payload, dict):
        return False, False
    workflow_active = payload.get("workflow_active") is True
    next_action = payload.get("next_action")
    next_action_auto = False
    if isinstance(next_action, dict):
        next_action_auto = next_action.get("auto_mode") is True
    return workflow_active, next_action_auto


def _auto_approve_on_unblock() -> bool:
    try:
        config = _load_config_for_get()
    except Exception:
        return False
    workflow = config.get("workflow") if isinstance(config, dict) else None
    if not isinstance(workflow, dict):
        return False
    return workflow.get("auto_approve_on_unblock") is True


def cmd_status_context_usage(args):
    stdin_payload = _read_stdin_payload()
    transcript_path = getattr(args, "transcript_path", None)
    if not transcript_path:
        value = stdin_payload.get("transcript_path")
        transcript_path = value if isinstance(value, str) else ""

    context_tokens, window, context_pct, cache_available = _context_usage_from_transcript(
        transcript_path or ""
    )
    workflow_active, next_action_auto = _state_flags(_resolve_state_file(getattr(args, "state_file", None)))
    auto_approve = _auto_approve_on_unblock()
    output = {
        "context_pct": context_pct,
        "context_tokens": context_tokens,
        "model_window": window,
        "cache_available": cache_available,
        "auto_approve_on_unblock": auto_approve,
        "workflow_active": workflow_active,
        "in_auto_chain": workflow_active or next_action_auto,
    }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


def register(subparsers):
    status = subparsers.add_parser("status")
    status_sub = status.add_subparsers(dest="subcommand")

    context_usage = status_sub.add_parser("context-usage")
    context_usage.add_argument("--transcript-path", default="")
    context_usage.add_argument("--state-file", default="")
