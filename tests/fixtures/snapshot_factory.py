"""Snapshot builders for MST stop-hook tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_snapshot(
    skill: str,
    step: int,
    total: int,
    stack: list[dict[str, Any]] | None = None,
    return_to: dict[str, Any] | str | None = None,
    completed: bool = False,
) -> dict:
    """Build a snapshot payload compatible with scripts/_snapshot_probe.py."""
    payload = {
        "currentSkill": skill,
        "currentStep": step,
        "totalSteps": total,
        "skillStack": list(stack or []),
        "status": "committed" if completed else "active",
        "updatedAt": _timestamp_now(),
    }
    if return_to is not None:
        payload["returnTo"] = return_to
    return payload


def write_snapshot(project_root: Path, session_id: str, payload: dict) -> Path:
    """Atomically write state/{session_id}/snapshot.json."""
    path = project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        data = dict(payload)
        data.setdefault("sessionId", session_id)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return path
