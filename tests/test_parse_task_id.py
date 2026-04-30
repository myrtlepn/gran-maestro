"""Tests for AD-006 Python mirror: scripts/mst_cmds/_common.parse_task_id.

The TS counterpart lives in src/core/task-id.test.ts and must accept and reject
the same set of inputs.
"""
from __future__ import annotations

import pytest

from scripts.mst_cmds._common import parse_task_id


@pytest.mark.parametrize(
    "raw_id,expected",
    [
        ("REQ-001-01", ("REQ-001", "01")),
        ("REQ-100-T01", ("REQ-100", "T01")),
        ("REQ-100-T01-X", ("REQ-100", "T01-X")),
        ("REQ-9999-Z", ("REQ-9999", "Z")),
    ],
)
def test_parse_task_id_accepts_valid_ids(raw_id: str, expected: tuple[str, str]) -> None:
    assert parse_task_id(raw_id) == expected


@pytest.mark.parametrize(
    "raw_id",
    [
        "req-001-01",  # lowercase prefix
        "",  # empty
        "REQ-001",  # bare request id
        "REQ-",  # no digits
        "REQ-abc-01",  # non-numeric request id
        "REQ-001-",  # trailing dash with no segment
    ],
)
def test_parse_task_id_rejects_invalid_ids(raw_id: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_task_id(raw_id)
    assert "invalid task id:" in str(excinfo.value)


def test_parse_task_id_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        parse_task_id(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        parse_task_id(12345)  # type: ignore[arg-type]
