"""Project-root and session helpers for MST hook tests."""

from __future__ import annotations

import uuid
from pathlib import Path


def make_session_id() -> str:
    """Return a fresh session id."""
    return uuid.uuid4().hex


def init_project_root(tmp_path: Path) -> Path:
    """Create the minimum project-root shape expected by the stop hook."""
    project_root = tmp_path
    (project_root / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "agile").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)
    return project_root


def pair_sessions(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a project root with two independent session state directories."""
    project_root = init_project_root(tmp_path)
    first_session_id = make_session_id()
    second_session_id = make_session_id()
    (project_root / ".gran-maestro" / "state" / first_session_id).mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "state" / second_session_id).mkdir(parents=True, exist_ok=True)
    return project_root, first_session_id, second_session_id
