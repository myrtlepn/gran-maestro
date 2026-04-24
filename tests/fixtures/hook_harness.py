"""Shared subprocess helpers for MST stop-hook tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


def run_hook(
    project_root: Path,
    payload: dict,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run the real MST stop hook with JSON stdin."""
    if not HOOK.is_file():
        raise FileNotFoundError(f"hook not found: {HOOK}")

    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **dict(env or {})},
    )


def read_flow_detail(project_root: Path, session_id: str) -> list[dict]:
    """Read flow-detail.ndjson records for a session."""
    flow_path = project_root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
    if not flow_path.is_file():
        return []

    records = []
    for line in flow_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def stdout_json(result: subprocess.CompletedProcess) -> dict:
    """Parse the hook decision JSON from stdout."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "hook must always emit a decision JSON"
    return json.loads(result.stdout)
