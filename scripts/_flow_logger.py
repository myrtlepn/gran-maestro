#!/usr/bin/env python3
"""Append flow-detail.ndjson events for Gran Maestro hook diagnostics."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


FLOW_LOG_FILENAME = "flow.ndjson"
FLOW_DETAIL_FILENAME = "flow-detail.ndjson"
MONTH_ENV_RE = re.compile(r"^\d{6}$")
_FLUSH_ENV_RE = re.compile(r"^\d+$")
_fsync_counters: Dict[str, int] = {}
_ATEXIT_REGISTERED = False


def _get_dotted_path(data: Dict[str, Any], dotted_path: str) -> Optional[Any]:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _resolve_flush_every_n() -> int:
    env_value = os.environ.get("MST_FLOW_LOG_FLUSH_EVERY_N", "").strip()
    if _FLUSH_ENV_RE.match(env_value):
        return int(env_value)

    for config_path in (
        Path.cwd() / ".gran-maestro" / "config.resolved.json",
        Path.cwd() / ".gran-maestro" / "config.json",
    ):
        try:
            value = _get_dotted_path(json.loads(config_path.read_text(encoding="utf-8")), "logs.flush_every_n")
        except Exception:
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and _FLUSH_ENV_RE.match(value.strip()):
            return int(value.strip())

    return 100


def _maybe_fsync(path: Path, handle) -> None:
    try:
        flush_every_n = _resolve_flush_every_n()
        if flush_every_n <= 0:
            return

        path_str = str(path)
        current = _fsync_counters.get(path_str, 0) + 1
        if current >= flush_every_n:
            os.fsync(handle.fileno())
            _fsync_counters[path_str] = 0
        else:
            _fsync_counters[path_str] = current
    except Exception as exc:
        print(f"[flow-logger] fsync failed: {exc}", file=sys.stderr)


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


def _rotated_filename(basename: str) -> str:
    month = os.environ.get("MST_FLOW_LOG_MONTH", "").strip()
    if not MONTH_ENV_RE.match(month):
        month = datetime.now(timezone.utc).strftime("%Y%m")
    if "." in basename:
        name, _, ext = basename.rpartition(".")
        return f"{name}-{month}.{ext}"
    return f"{basename}-{month}"


def flow_detail_path(project_root: Path, session_id: str, *, rotate: bool = False) -> Path:
    filename = _rotated_filename(FLOW_DETAIL_FILENAME) if rotate else FLOW_DETAIL_FILENAME
    return project_root / ".gran-maestro" / "state" / safe_session_id(session_id) / filename


def flow_log_path(project_root: Path, *, override: Optional[str] = None, rotate: bool = False) -> Path:
    log_dir = os.environ.get("MST_FLOW_LOG_DIR") or override
    filename = _rotated_filename(FLOW_LOG_FILENAME) if rotate else FLOW_LOG_FILENAME
    if log_dir:
        return Path(log_dir) / filename
    return project_root / ".gran-maestro" / "logs" / filename


def _extract_session_id_from_path(path_str: str) -> Optional[str]:
    match = re.search(r"state/([^/]+)/", path_str)
    return match.group(1) if match else None


def _find_project_root(path_str: str) -> Path:
    path = Path(path_str).resolve()
    for ancestor in [path, *path.parents]:
        if (ancestor / ".gran-maestro").is_dir():
            return ancestor
    return Path.cwd()


def _register_session_end_flush() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    if os.environ.get("MST_FLOW_DISABLE_ATEXIT", "").strip() == "1":
        return
    atexit.register(_session_end_flush)
    _ATEXIT_REGISTERED = True


def _session_end_flush() -> None:
    try:
        import json as json_module
        import os as os_module
        import sys as sys_module
        from pathlib import Path as PathClass
    except Exception:
        return

    try:
        snapshot = list(_fsync_counters.keys())
    except Exception:
        snapshot = []

    for path_str in snapshot:
        try:
            path = PathClass(path_str)
            if path.exists():
                fd = os_module.open(str(path), os_module.O_WRONLY | os_module.O_APPEND)
                try:
                    os_module.fsync(fd)
                finally:
                    os_module.close(fd)

            session_id = (
                _extract_session_id_from_path(path_str)
                or os_module.environ.get("MST_SNAPSHOT_SESSION_ID")
                or "unknown"
            )
            project_root = _find_project_root(path_str)
            flow_path = flow_log_path(project_root, rotate=True)
            flow_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": timestamp_now(),
                "session_id": safe_session_id(session_id),
                "skill": "_session",
                "step": 0,
                "total_steps": 0,
                "event_type": "flow_session_end",
                "parent_skill": None,
                "parent_step": None,
                "duration_ms": None,
                "extras": {},
                "schema_version": 1,
            }
            with open(flow_path, "a", encoding="utf-8", buffering=1) as handle:
                handle.write(json_module.dumps(entry, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        except Exception as exc:
            try:
                print(f"[flow-logger] session end flush failed: {exc}", file=sys_module.stderr)
            except Exception:
                pass
        finally:
            try:
                _fsync_counters.pop(path_str, None)
            except Exception:
                pass


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


def _append_json_line(path: Path, entry: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", buffering=1) as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        _maybe_fsync(path, handle)


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
    _append_json_line(path, entry)
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
    rotate: bool = False,
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
        path = flow_log_path(project_root, rotate=rotate)
        _append_json_line(path, entry)
        if rotate and os.environ.get("MST_FLOW_LOG_DIR") and "MST_FLOW_LOG_MONTH" not in os.environ:
            _append_json_line(Path(os.environ["MST_FLOW_LOG_DIR"]) / FLOW_LOG_FILENAME, entry)
        return path
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
        return None


def append_hook_event(
    project_root: Path,
    session_id: str,
    *,
    hook_event: str,
    decision: str,
    layer: str,
    reason: Optional[str] = None,
    anchor: Optional[str] = None,
    return_to: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
    snapshot_digest: Optional[str] = None,
    snapshot_diff: Optional[str] = None,
    stdin_json_digest: Optional[str] = None,
    error: Optional[str] = None,
    ppid: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
    schema_version: int = 1,
    rotate: bool = False,
) -> Optional[Path]:
    del extras
    try:
        entry = {
            "timestamp": timestamp_now(),
            "session_id": safe_session_id(session_id),
            "ppid": ppid,
            "hook_event": str(hook_event),
            "decision": str(decision),
            "layer": str(layer),
            "reason": reason,
            "anchor": anchor,
            "return_to": return_to if isinstance(return_to, dict) else return_to,
            "duration_ms": duration_ms,
            "snapshot_digest": snapshot_digest,
            "snapshot_diff": snapshot_diff,
            "stdin_json_digest": stdin_json_digest,
            "error": error,
            "schema_version": schema_version,
        }
        path = flow_detail_path(project_root, session_id, rotate=rotate)
        log_dir = os.environ.get("MST_FLOW_LOG_DIR")
        if log_dir:
            path = Path(log_dir) / safe_session_id(session_id) / path.name
        _append_json_line(path, entry)
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


_register_session_end_flush()


if __name__ == "__main__":
    raise SystemExit(main())
