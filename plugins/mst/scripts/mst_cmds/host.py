from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from scripts.mst_cmds import _common


HOSTS = {"claude", "codex", "headless"}


def _read_stdin_payload() -> dict[str, Any]:
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
    except json.JSONDecodeError:
        return {"raw_stdin": raw, "parse_error": "invalid_json"}
    return payload if isinstance(payload, dict) else {"raw_stdin": payload, "parse_error": "payload_not_object"}


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _resolve_host(raw_host: str, env: dict[str, str], payload: dict[str, Any]) -> str:
    requested = _clean(raw_host).lower()
    if requested in HOSTS:
        return requested
    for value in (
        _clean(env.get("MST_HOST")).lower(),
        _clean(payload.get("host")).lower(),
        _clean(payload.get("runtime_host")).lower(),
    ):
        if value in HOSTS:
            return value
    if env.get("CLAUDECODE") or env.get("CLAUDE_PLUGIN_ROOT") or payload.get("transcript_path"):
        return "claude"
    if (
        env.get("CODEX_PLUGIN_ROOT")
        or env.get("CODEX_SESSION_ID")
        or env.get("CODEX_THREAD_ID")
        or env.get("CODEX_HOME")
        or env.get("CODEX_SANDBOX")
        or env.get("CODEX_CI")
    ):
        return "codex"
    return "headless"


def _host_session_id(host: str, env: dict[str, str], payload: dict[str, Any]) -> str | None:
    if host == "claude":
        return (
            _clean(payload.get("session_id"))
            or _clean(payload.get("claude_session_id"))
            or _clean(env.get("CLAUDE_SESSION_ID"))
            or None
        )
    if host == "codex":
        return (
            _clean(payload.get("session_id"))
            or _clean(payload.get("codex_session_id"))
            or _clean(env.get("CODEX_SESSION_ID"))
            or None
        )
    return _clean(payload.get("session_id")) or None


def _canonical_mst_session_id(payload: dict[str, Any]) -> tuple[str | None, dict[str, str] | None]:
    try:
        value = _common.canonical_mst_session_id_from_env_or_context()
    except ValueError as exc:
        return None, {"kind": "canonical_mst_session_error", "message": str(exc)}
    payload_value = _clean(payload.get("mst_session_id"))
    if payload_value:
        try:
            from scripts.mst_cmds.session import validate_mst_session_id

            payload_value = validate_mst_session_id(payload_value).mst_session_id
        except ValueError as exc:
            return None, {"kind": "canonical_mst_session_error", "message": str(exc)}
        if value and value != payload_value:
            return None, {
                "kind": "canonical_mst_session_error",
                "message": "MST_SESSION_ID and host payload mst_session_id mismatch",
            }
        value = value or payload_value
    return value, None


def build_host_context(*, host: str = "auto", event: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    env = os.environ
    resolved_host = _resolve_host(host, env, payload)
    mst_session_id, diagnostic = _canonical_mst_session_id(payload)
    project_root = _common.BASE_DIR.parent if _common.BASE_DIR is not None else Path.cwd().resolve()

    context = {
        "host": resolved_host,
        "event": _clean(event) or None,
        "project_root": str(project_root.resolve(strict=False)),
        "plugin_root": str(_common._plugin_root().resolve(strict=False)),
        "mst_session_id": mst_session_id,
        "host_session_id": _host_session_id(resolved_host, env, payload),
        "transcript_path": _clean(payload.get("transcript_path")) or None,
        "permission_mode": (
            _clean(payload.get("permission_mode"))
            or _clean(env.get("CODEX_PERMISSION_MODE"))
            or _clean(env.get("CLAUDE_PERMISSION_MODE"))
            or None
        ),
        "model": _clean(payload.get("model")) or _clean(env.get("CODEX_MODEL")) or _clean(env.get("CLAUDE_MODEL")) or None,
        "adapter": {
            "tick_source": "hook" if resolved_host == "claude" else "supervisor",
            "uses_claude_hooks": resolved_host == "claude",
            "uses_queue_supervisor": resolved_host in {"codex", "headless"},
        },
    }
    if diagnostic is not None:
        context["diagnostic"] = diagnostic
    return context


def cmd_host_context(args):
    payload = _read_stdin_payload()
    context = build_host_context(host=args.host, event=args.event, payload=payload)
    print(json.dumps(context, ensure_ascii=False, separators=(",", ":") if args.json else None, indent=None if args.json else 2))
    return 0


def register(subparsers):
    host = subparsers.add_parser("host")
    host_sub = host.add_subparsers(dest="subcommand")

    context = host_sub.add_parser("context")
    context.add_argument("--host", choices=["auto", "claude", "codex", "headless"], default="auto")
    context.add_argument("--event", default="")
    context.add_argument("--json", action="store_true")
