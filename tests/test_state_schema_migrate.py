from __future__ import annotations

import pytest

from scripts._state_normalize import _WARNED_MIGRATIONS, migrate_legacy_status


@pytest.fixture(autouse=True)
def _reset_warned_migrations() -> None:
    _WARNED_MIGRATIONS.clear()


def test_completed_to_done(capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate_legacy_status("completed") == "done"

    stderr = capsys.readouterr().err
    assert "[mst-state] migrated 'completed' → 'done'" in stderr


def test_accepted_to_done(capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate_legacy_status("accepted") == "done"

    stderr = capsys.readouterr().err
    assert "[mst-state] migrated 'accepted' → 'done'" in stderr


def test_passthrough(capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate_legacy_status("done") == "done"
    assert migrate_legacy_status("pending") == "pending"
    assert migrate_legacy_status("executing") == "executing"
    assert migrate_legacy_status("foo") == "foo"

    stderr = capsys.readouterr().err
    assert stderr == ""


def test_warn_once_dedup(capsys: pytest.CaptureFixture[str]) -> None:
    assert migrate_legacy_status("completed") == "done"
    assert migrate_legacy_status("completed") == "done"

    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(lines) == 1
