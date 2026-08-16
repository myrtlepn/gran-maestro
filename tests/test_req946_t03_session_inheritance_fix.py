from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Insert REPO_ROOT into sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mst_cmds import _common
from scripts.mst_cmds import session as session_mod

TEST_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
TEST_ROOT_ID = "AGI-030"


@pytest.fixture(autouse=True)
def clean_mst_env():
    """Ensure environment is clean of MST parameters before each test."""
    original_env = os.environ.copy()
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        os.environ.pop(key, None)
    yield
    os.environ.clear()
    os.environ.update(original_env)


def test_sid_only_inheritance():
    """REQ-946 T03 R2: Validate SID-only inheritance without MST_CONTEXT_JSON."""
    os.environ["MST_SESSION_ID"] = TEST_SESSION_ID

    child_env = session_mod.child_env_with_required_session_context()

    assert child_env["MST_SESSION_ID"] == TEST_SESSION_ID
    assert "MST_CONTEXT_JSON" in child_env

    ctx = json.loads(child_env["MST_CONTEXT_JSON"])
    assert ctx["mst_session_id"] == TEST_SESSION_ID
    assert ctx["root_mst_id"] == TEST_ROOT_ID
    assert ctx["schema_version"] == 1


def test_context_only_inheritance():
    """REQ-946 T03 R2: Validate context-only inheritance without MST_SESSION_ID."""
    context_data = {
        "schema_version": 1,
        "mst_session_id": TEST_SESSION_ID,
        "root_mst_id": TEST_ROOT_ID,
    }
    os.environ["MST_CONTEXT_JSON"] = json.dumps(context_data)

    child_env = session_mod.child_env_with_required_session_context()

    assert child_env["MST_SESSION_ID"] == TEST_SESSION_ID
    assert "MST_CONTEXT_JSON" in child_env

    ctx = json.loads(child_env["MST_CONTEXT_JSON"])
    assert ctx["mst_session_id"] == TEST_SESSION_ID
    assert ctx["root_mst_id"] == TEST_ROOT_ID


def test_both_source_consistency_success():
    """REQ-946 T03 R2: Validate both sources present and consistent."""
    context_data = {
        "schema_version": 1,
        "mst_session_id": TEST_SESSION_ID,
        "root_mst_id": TEST_ROOT_ID,
    }
    os.environ["MST_SESSION_ID"] = TEST_SESSION_ID
    os.environ["MST_CONTEXT_JSON"] = json.dumps(context_data)

    child_env = session_mod.child_env_with_required_session_context()

    assert child_env["MST_SESSION_ID"] == TEST_SESSION_ID
    ctx = json.loads(child_env["MST_CONTEXT_JSON"])
    assert ctx["mst_session_id"] == TEST_SESSION_ID
    assert ctx["root_mst_id"] == TEST_ROOT_ID


def test_both_source_consistency_mismatch_fails():
    """REQ-946 T03 R2: Mismatched SID and context should raise a validation failure."""
    context_data = {
        "schema_version": 1,
        "mst_session_id": "MST-AGI-030-20260503T130813382Z-different",
        "root_mst_id": TEST_ROOT_ID,
    }
    os.environ["MST_SESSION_ID"] = TEST_SESSION_ID
    os.environ["MST_CONTEXT_JSON"] = json.dumps(context_data)

    with pytest.raises(_common.ContractValidationError) as exc_info:
        session_mod.child_env_with_required_session_context()

    assert "mismatch" in str(exc_info.value).lower()
