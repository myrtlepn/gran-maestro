from __future__ import annotations

from pathlib import Path


def test_imports_from_generated() -> None:
    from scripts._state_schema import (  # noqa: F401
        RECOVERY_ACTIONS,
        TASK_STATUSES,
        TERMINAL,
        TRANSITIONS,
    )


def test_terminal_subset_of_task_statuses() -> None:
    from scripts._state_schema import TASK_STATUSES, TERMINAL

    assert set(TERMINAL).issubset(set(TASK_STATUSES))


def test_no_hardcoded_workflow_terminal_in_common() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    common_py = repo_root / "scripts" / "mst_cmds" / "_common.py"
    source = common_py.read_text(encoding="utf-8")

    assert 'WORKFLOW_TERMINAL_STATUSES = {"done"' not in source
