from __future__ import annotations

from pathlib import Path


def test_imports_from_generated() -> None:
    from scripts._state_schema import (  # noqa: F401
        ACTIVE_PHASE_STATUSES,
        RECOVERY_ACTIONS,
        TASK_STATUSES,
        TERMINAL,
        TRANSITIONS,
    )


def test_terminal_subset_of_task_statuses() -> None:
    from scripts._state_schema import TASK_STATUSES, TERMINAL

    assert set(TERMINAL).issubset(set(TASK_STATUSES))


def test_python_active_phase_statuses_match_typescript_source() -> None:
    import json
    import re

    from scripts._state_schema import ACTIVE_PHASE_STATUSES

    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "src" / "core" / "state-schema.ts").read_text(encoding="utf-8")
    match = re.search(
        r"export const ACTIVE_PHASE_STATUSES(?:\s*:[^=]+)?\s*=\s*(?P<value>.*?)\s*as const\s*;",
        source,
        re.DOTALL,
    )
    assert match is not None
    assert set(ACTIVE_PHASE_STATUSES) == set(json.loads(match.group("value")))


def test_no_hardcoded_workflow_terminal_in_common() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    common_py = repo_root / "scripts" / "mst_cmds" / "_common.py"
    source = common_py.read_text(encoding="utf-8")

    assert 'WORKFLOW_TERMINAL_STATUSES = {"done"' not in source


def test_execution_transitions_are_transport_neutral() -> None:
    from scripts._state_schema import TRANSITIONS

    execution_transitions = [row for row in TRANSITIONS if row.get("from") == "executing"]
    contract = " ".join(
        f"{row.get('condition', '')} {row.get('guard', '')}" for row in execution_transitions
    )
    assert "completion signal" in contract
    assert "native completion_signal=completed" in contract
    assert "external exit_code=0" in contract
    assert all(not row["condition"].startswith("CLI exit code") for row in execution_transitions)
