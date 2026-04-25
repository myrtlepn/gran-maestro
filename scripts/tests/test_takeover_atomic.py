from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds import state


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"

SID_A = "11111111-1111-4111-8111-111111111111"
SID_B = "22222222-2222-4222-9222-222222222222"
SID_C = "33333333-3333-4333-8333-333333333333"
SID_D = "44444444-4444-4444-8444-444444444444"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def set_base(root: Path) -> Path:
    base = root / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)
    _common.set_base_dir(base)
    return base


def run_mst(root: Path, *args: str, session_id: str = SID_B) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_SESSION_ID"] = session_id
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    return subprocess.run(
        ["python3", str(MST), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


def write_takeover_fixtures(root: Path, *, owner_session_id: str = SID_A) -> None:
    base = root / ".gran-maestro"
    write_json(base / "agile" / "AGI-726" / "session.json", {"id": "AGI-726", "owner_session_id": owner_session_id})
    write_json(base / "requests" / "REQ-726" / "request.json", {"id": "REQ-726", "owner_session_id": owner_session_id})
    write_json(base / "plans" / "PLN-726" / "plan.json", {"id": "PLN-726", "owner_session_id": owner_session_id})


def hold_flock(path: Path, hold_sec: float, locked: threading.Event) -> None:
    import fcntl

    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        locked.set()
        time.sleep(hold_sec)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def test_atomic_write_preserves_original_on_failure(tmp_path: Path) -> None:
    set_base(tmp_path)
    target = tmp_path / ".gran-maestro" / "state" / "atomic.json"
    original = {"owner_session_id": SID_A, "value": "original"}
    write_json(target, original)

    def fail_after_mutation(payload: dict) -> dict:
        payload["value"] = "changed"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        state._with_locked_json_update(target, fail_after_mutation)

    assert read_json(target) == original
    assert not list(target.parent.glob(f"{target.name}.tmp.*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock timeout behavior is covered on Unix")
def test_flock_timeout_after_configured_seconds(tmp_path: Path) -> None:
    base = set_base(tmp_path)
    write_json(base / "config.json", {"takeover": {"flock_timeout_sec": 0.2}})
    target = base / "state" / "locked.json"
    write_json(target, {"owner_session_id": SID_A})

    locker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, pathlib, sys, time\n"
                f"path = pathlib.Path({str(target)!r})\n"
                "f = path.open('a+', encoding='utf-8')\n"
                "fcntl.flock(f.fileno(), fcntl.LOCK_EX)\n"
                "print('locked', flush=True)\n"
                "time.sleep(2)\n"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert locker.stdout is not None
        assert locker.stdout.readline().strip() == "locked"
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            state._with_locked_json_update(target, lambda payload: payload)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.18
        assert elapsed < 1.5
    finally:
        locker.terminate()
        locker.wait(timeout=5)


def test_top_level_takeover_cli_dispatches(tmp_path: Path) -> None:
    set_base(tmp_path)
    write_takeover_fixtures(tmp_path)

    cases = [
        ("agile", "takeover", "--agi", "AGI-726", tmp_path / ".gran-maestro" / "agile" / "AGI-726" / "session.json"),
        ("request", "takeover", "--id", "REQ-726", tmp_path / ".gran-maestro" / "requests" / "REQ-726" / "request.json"),
        ("plan", "takeover", "--id", "PLN-726", tmp_path / ".gran-maestro" / "plans" / "PLN-726" / "plan.json"),
    ]
    for command, subcommand, flag, resource_id, path in cases:
        result = run_mst(tmp_path, command, subcommand, flag, resource_id)
        assert result.returncode == 0, result.stderr
        assert read_json(path)["owner_session_id"] == SID_B


def test_takeover_noop_when_current_session_already_owns_resource(tmp_path: Path) -> None:
    set_base(tmp_path)
    path = tmp_path / ".gran-maestro" / "requests" / "REQ-726" / "request.json"
    write_json(path, {"id": "REQ-726", "owner_session_id": SID_B, "marker": "unchanged"})

    result = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_B)

    assert result.returncode == 0, result.stderr
    assert "no-op" in result.stdout
    assert read_json(path) == {"id": "REQ-726", "owner_session_id": SID_B, "marker": "unchanged"}
    assert not (tmp_path / ".gran-maestro" / "state" / "_takeover_storm" / "REQ-726.json").exists()


def test_takeover_rejects_invalid_resource_id(tmp_path: Path) -> None:
    set_base(tmp_path)

    result = run_mst(tmp_path, "plan", "takeover", "--id", "REQ-726", session_id=SID_B)

    assert result.returncode != 0
    assert "Invalid PLN id" in result.stderr


def test_storm_detection_rejects_third_takeover_attempt(tmp_path: Path) -> None:
    set_base(tmp_path)
    write_json(
        tmp_path / ".gran-maestro" / "config.json",
        {"takeover": {"storm_window_sec": 5.0, "storm_max_attempts": 3}},
    )
    path = tmp_path / ".gran-maestro" / "requests" / "REQ-726" / "request.json"
    write_json(path, {"id": "REQ-726", "owner_session_id": SID_A})

    first = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_B)
    assert first.returncode == 0, first.stderr
    assert read_json(path)["owner_session_id"] == SID_B

    second = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_C)
    assert second.returncode == 0, second.stderr
    assert read_json(path)["owner_session_id"] == SID_C

    third = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_D)
    assert third.returncode != 0
    assert "[storm detected]" in third.stderr
    assert read_json(path)["owner_session_id"] == SID_C


@pytest.mark.skipif(os.name == "nt", reason="POSIX flock contention behavior is covered on Unix")
def test_concurrent_takeover_lock_contention(tmp_path: Path) -> None:
    set_base(tmp_path)
    write_json(
        tmp_path / ".gran-maestro" / "config.json",
        {"takeover": {"flock_timeout_sec": 0.2, "storm_window_sec": 5.0, "storm_max_attempts": 5}},
    )
    path = tmp_path / ".gran-maestro" / "requests" / "REQ-726" / "request.json"
    write_json(path, {"id": "REQ-726", "owner_session_id": SID_A})

    locked = threading.Event()
    locker = threading.Thread(target=hold_flock, args=(path, 1.0, locked), daemon=True)
    locker.start()
    assert locked.wait(timeout=1.0)

    blocked = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_B)
    locker.join(timeout=2.0)

    assert blocked.returncode != 0
    assert "lock timeout" in blocked.stderr.lower()
    assert read_json(path)["owner_session_id"] == SID_A

    retry = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_B)

    assert retry.returncode == 0, retry.stderr
    assert read_json(path)["owner_session_id"] == SID_B


def test_storm_window_resets_after_timeout(tmp_path: Path) -> None:
    set_base(tmp_path)
    write_json(
        tmp_path / ".gran-maestro" / "config.json",
        {"takeover": {"storm_window_sec": 0.5, "storm_max_attempts": 3}},
    )
    path = tmp_path / ".gran-maestro" / "requests" / "REQ-726" / "request.json"
    write_json(path, {"id": "REQ-726", "owner_session_id": SID_A})

    first = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_B)
    assert first.returncode == 0, first.stderr
    assert read_json(path)["owner_session_id"] == SID_B

    second = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_C)
    assert second.returncode == 0, second.stderr
    assert read_json(path)["owner_session_id"] == SID_C

    third = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_D)
    assert third.returncode != 0
    assert "[storm detected]" in third.stderr
    assert read_json(path)["owner_session_id"] == SID_C

    time.sleep(0.7)
    after_window = run_mst(tmp_path, "request", "takeover", "--id", "REQ-726", session_id=SID_D)

    assert after_window.returncode == 0, after_window.stderr
    assert read_json(path)["owner_session_id"] == SID_D
