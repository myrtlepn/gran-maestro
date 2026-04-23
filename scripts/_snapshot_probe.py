#!/usr/bin/env python3
"""Probe the current session snapshot from Claude hook stdin JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from _flow_logger import append_event, safe_session_id

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _parse_stdin(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_id_from_transcript(transcript_path: Any) -> Tuple[str, str]:
    if not isinstance(transcript_path, str) or not transcript_path.strip():
        return "", ""
    basename = Path(transcript_path).name
    stem = basename[:-6] if basename.endswith(".jsonl") else Path(basename).stem
    if UUID_RE.match(stem):
        return stem, "transcript_path"
    return "", ""


def resolve_session_id(payload: Dict[str, Any]) -> Tuple[str, str]:
    direct = payload.get("session_id")
    if isinstance(direct, str) and direct.strip():
        return safe_session_id(direct.strip()), "session_id"
    return _session_id_from_transcript(payload.get("transcript_path"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _extract_return_to(snapshot: Dict[str, Any]) -> Tuple[str, str]:
    value = snapshot.get("returnTo")
    if isinstance(value, dict):
        skill = value.get("skill")
        step = value.get("step")
        return (
            str(skill).strip() if skill is not None else "",
            str(step).strip() if step is not None else "",
        )
    if isinstance(value, str):
        skill, sep, step = value.partition("/")
        return skill.strip(), step.strip() if sep else ""
    return "", ""


def probe(project_root: Path, raw_stdin: str) -> Dict[str, Any]:
    payload = _parse_stdin(raw_stdin)
    session_id, session_id_source = resolve_session_id(payload)
    hook_event_name = str(payload.get("hook_event_name") or "")
    transcript_path = str(payload.get("transcript_path") or "")
    resolution_failed = not bool(session_id)
    if resolution_failed and (hook_event_name or transcript_path):
        session_id = "unknown"

    snapshot_path = project_root / ".gran-maestro" / "state" / safe_session_id(session_id) / "snapshot.json"
    snapshot: Dict[str, Any] = {}
    snapshot_present = snapshot_path.is_file()
    snapshot_digest = ""
    if snapshot_present:
        try:
            snapshot_digest = _sha256_file(snapshot_path)
            loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                snapshot = loaded
        except Exception:
            snapshot = {}

    return_to_skill, return_to_step = _extract_return_to(snapshot)
    result = {
        "session_id": session_id,
        "session_id_source": session_id_source,
        "session_id_resolution_failed": resolution_failed,
        "hook_event_name": hook_event_name,
        "transcript_path": transcript_path,
        "snapshot_present": snapshot_present,
        "snapshot_path": str(snapshot_path),
        "snapshot_digest": snapshot_digest,
        "stdin_digest": _sha256_text(raw_stdin),
        "current_skill": str(snapshot.get("currentSkill") or snapshot.get("current_skill") or ""),
        "current_step": snapshot.get("currentStep", snapshot.get("current_step", "")),
        "total_steps": snapshot.get("totalSteps", snapshot.get("total_steps", "")),
        "status": "" if snapshot.get("status") is None else str(snapshot.get("status") or ""),
        "return_to_skill": return_to_skill,
        "return_to_step": return_to_step,
    }

    if resolution_failed:
        try:
            append_event(
                project_root,
                session_id,
                "session_id_resolution_failed",
                {
                    "stdin_digest": result["stdin_digest"],
                    "transcript_path": result["transcript_path"],
                    "ppid": str(os.getppid()),
                },
            )
        except Exception:
            pass

    return result


def _format_shell(payload: Dict[str, Any]) -> str:
    mapping = {
        "SESSION_ID": payload["session_id"],
        "SESSION_ID_SOURCE": payload["session_id_source"],
        "SESSION_ID_RESOLUTION_FAILED": "true" if payload["session_id_resolution_failed"] else "false",
        "HOOK_EVENT_NAME": payload["hook_event_name"],
        "TRANSCRIPT_PATH": payload["transcript_path"],
        "SNAPSHOT_PRESENT": "true" if payload["snapshot_present"] else "false",
        "SNAPSHOT_PATH": payload["snapshot_path"],
        "SNAPSHOT_DIGEST": payload["snapshot_digest"],
        "STDIN_DIGEST": payload["stdin_digest"],
        "SNAPSHOT_CURRENT_SKILL": payload["current_skill"],
        "SNAPSHOT_CURRENT_STEP": payload["current_step"],
        "SNAPSHOT_TOTAL_STEPS": payload["total_steps"],
        "SNAPSHOT_STATUS": payload["status"],
        "SNAPSHOT_RETURN_TO_SKILL": payload["return_to_skill"],
        "SNAPSHOT_RETURN_TO_STEP": payload["return_to_step"],
    }
    lines = []
    for key, value in mapping.items():
        lines.append(f"{key}={shlex.quote(str(value))}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    raw_stdin = os.sys.stdin.read() or ""
    payload = probe(Path(args.project_root).resolve(), raw_stdin)
    if args.format == "shell":
        print(_format_shell(payload))
    else:
        print(_json_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
