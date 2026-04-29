from __future__ import annotations

from typing import Any, Dict, Optional

from scripts.mst_cmds._common import (
    _skill_state_base_dir,
    _workflow_state_file,
    _workflow_state_load,
)


def read_workflow_state() -> Optional[Dict[str, Any]]:
    """Read the current workflow state via the shared state helpers."""
    payload = _workflow_state_load(_workflow_state_file(_skill_state_base_dir()))
    return payload if isinstance(payload, dict) else None
