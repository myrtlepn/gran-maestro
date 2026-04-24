import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from scripts import _skill_state
from scripts._skill_state import commit, enter


try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by HAS_FCNTL monkeypatch below.
    fcntl = None


def _lock_path(base_dir: Path, session_id: str) -> Path:
    return base_dir / "state" / session_id / ".snapshot.lock"


def _snapshot_path(base_dir: Path, session_id: str) -> Path:
    return base_dir / "state" / session_id / "snapshot.json"


def _read_snapshot(base_dir: Path, session_id: str) -> dict:
    return json.loads(_snapshot_path(base_dir, session_id).read_text(encoding="utf-8"))


def _assert_lock_released(lock_path: Path) -> None:
    if fcntl is None:
        pytest.skip("fcntl is not available on this platform")

    with open(lock_path, "a+") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


def _enter_after_barrier(
    base_dir_text: str,
    session_id: str,
    skill: str,
    ready_path_text: str,
) -> None:
    ready_path = Path(ready_path_text)
    ready_path.write_text(str(os.getpid()), encoding="utf-8")
    while len(list(ready_path.parent.glob("ready-*"))) < 2:
        time.sleep(0.01)

    enter(Path(base_dir_text), skill=skill, step=1, total=1, session_id=session_id)


def _hold_lock(lock_path_text: str, ready_path_text: str, hold_sec: float) -> None:
    if fcntl is None:
        return

    lock_path = Path(lock_path_text)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as fd:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        Path(ready_path_text).write_text("ready", encoding="utf-8")
        time.sleep(hold_sec)
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_enter_creates_lock_file(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    session_id = "session-enter"
    lock_path = _lock_path(base_dir, session_id)

    enter(base_dir, skill="A", step=1, total=1, session_id=session_id)

    assert lock_path.exists()
    _assert_lock_released(lock_path)


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_commit_uses_same_lock(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    session_id = "session-commit"
    lock_path = _lock_path(base_dir, session_id)
    enter(base_dir, skill="A", step=1, total=1, session_id=session_id)
    lock_path.unlink()

    commit(base_dir, session_id=session_id)

    assert lock_path.exists()
    _assert_lock_released(lock_path)


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_concurrent_enter_no_lost_update(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    session_id = "session-concurrent"
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    processes = [
        multiprocessing.Process(
            target=_enter_after_barrier,
            args=(str(base_dir), session_id, skill, str(sync_dir / f"ready-{skill}")),
        )
        for skill in ("A", "B")
    ]

    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    for process in processes:
        assert process.exitcode == 0

    snapshot = _read_snapshot(base_dir, session_id)
    stack_skills = [frame["skill"] for frame in snapshot["skillStack"]]
    represented_skills = stack_skills + [snapshot["currentSkill"]]
    assert sorted(represented_skills) == ["A", "B"]
    assert snapshot["enterCount"] == 2


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_lock_timeout_fallthrough(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"
    session_id = "session-timeout"
    lock_path = _lock_path(base_dir, session_id)
    ready_path = tmp_path / "lock-ready"
    process = multiprocessing.Process(
        target=_hold_lock,
        args=(str(lock_path), str(ready_path), 2.0),
    )

    process.start()
    try:
        deadline = time.monotonic() + 5
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists()

        monkeypatch.setenv("AGILE_STATE_LOCK_TIMEOUT_SEC", "1")
        with pytest.warns(UserWarning, match="lock timeout after 1.0s; continuing without lock"):
            updated = enter(base_dir, skill="A", step=1, total=1, session_id=session_id)

        assert updated["currentSkill"] == "A"
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert process.exitcode == 0


def test_fcntl_import_fallback(tmp_path, monkeypatch):
    base_dir = tmp_path / ".gran-maestro"

    monkeypatch.setattr(_skill_state, "HAS_FCNTL", False)
    with pytest.warns(
        UserWarning,
        match="fcntl not available; running without RMW serialization",
    ):
        updated = enter(
            base_dir,
            skill="A",
            step=1,
            total=1,
            session_id="session-no-fcntl",
        )

    assert updated["currentSkill"] == "A"


@pytest.mark.skipif(fcntl is None, reason="fcntl is not available on this platform")
def test_lock_file_path_convention(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    session_id = "session-path"
    expected = base_dir / "state" / session_id / ".snapshot.lock"

    enter(base_dir, skill="A", step=1, total=1, session_id=session_id)

    assert _lock_path(base_dir, session_id) == expected
    assert expected.exists()
