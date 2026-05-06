from __future__ import annotations

from typing import Any, Dict, Optional

import os

from scripts.mst_cmds._common import (
    _skill_state_base_dir,
    _workflow_state_file,
    _workflow_state_load,
)


def read_workflow_state() -> Optional[Dict[str, Any]]:
    """Read the current workflow state via the shared state helpers."""
    base_dir = _skill_state_base_dir()
    try:
        path = _workflow_state_file(base_dir)
    except ValueError:
        legacy_ppid = os.environ.get("MST_STATE_PPID", "").strip()
        if not legacy_ppid.isdigit():
            return None
        path = base_dir / "tmp" / f"mst-state-{legacy_ppid}.json"
    payload = _workflow_state_load(path)
    return payload if isinstance(payload, dict) else None
