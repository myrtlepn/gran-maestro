from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.mst_cmds import cleanup


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), f"cleanup.{name} contract helper is missing"
    return value


def _cleanup_api_or_skip(name: str):
    value = getattr(cleanup, name, None)
    if not callable(value):
        pytest.skip(f"cleanup.{name} is not implemented yet")
    return value


def test_required_stop_hook_cleanup_contract_api_exists() -> None:
    _require_cleanup_api("decide_stop_hook_cleanup")
    _require_cleanup_api("run_cleanup_with_lock_report")
    _require_cleanup_api("stophook_target_pid_from_env")


@pytest.mark.parametrize("abnormal_exit", ["SIGINT", "SIGTERM", "exit-42", "KeyboardInterrupt"])
@pytest.mark.parametrize("marker_validity", ["missing", "dead", "start_time_mismatch", "alive-single-shot"])
def test_stop_hook_abnormal_single_shot_fallthrough_matrix(abnormal_exit: str, marker_validity: str) -> None:
    decide = _cleanup_api_or_skip("decide_stop_hook_cleanup")
    marker = None
    hook_target_pid = None
    if marker_validity == "alive-single-shot":
        hook_target_pid = 7777
        marker = {
            "session_id": "hook-sid",
            "pid": 7777,
            "mode": "single-shot",
            "start_time": 1000.0,
        }
    elif marker_validity != "missing":
        marker = {
            "session_id": "hook-sid",
            "pid": 7777,
            "mode": "marathon",
            "start_time": 1000.0,
        }

    report = decide(
        abnormal_exit=abnormal_exit,
        hook_session_id="hook-sid",
        marker=marker,
        marker_validity="active" if marker_validity == "alive-single-shot" else marker_validity,
        hook_target_pid=hook_target_pid,
        hook_process_pid=os.getpid(),
    )

    assert report["action"] == "fallthrough"
    assert report["real_cleanup"] is True


@pytest.mark.skipif(os.name == "nt", reason="cleanup flock timeout contract is POSIX-only")
def test_stop_hook_lock_timeout_reports_stub_under_six_seconds(tmp_path: Path) -> None:
    import fcntl

    run_with_lock = _cleanup_api_or_skip("run_cleanup_with_lock_report")
    project_root = tmp_path / "project"
    lock_path = project_root / ".gran-maestro" / "cleanup.lock"
    lock_path.parent.mkdir(parents=True)

    with lock_path.open("a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        report = run_with_lock(
            project_root=project_root,
            entrypoint="stophook",
            session_id="hook-sid",
            timeout_seconds=0.2,
            cleanup_fn=lambda _context: {"status": "ok", "real_cleanup": True},
        )
        elapsed = time.monotonic() - started
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    assert elapsed < 6.0
    assert report["status"] == "skipped"
    assert report["reason"] == "flock-timeout"
    assert report.get("real_cleanup") is not True


def test_stophook_target_pid_env_is_the_only_authoritative_target(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_target = _cleanup_api_or_skip("stophook_target_pid_from_env")

    monkeypatch.delenv("MST_HOOK_TARGET_PID", raising=False)
    assert parse_target(os.environ) is None

    monkeypatch.setenv("MST_HOOK_TARGET_PID", "not-an-int")
    assert parse_target(os.environ) is None

    monkeypatch.setenv("MST_HOOK_TARGET_PID", "7777")
    assert parse_target(os.environ) == 7777
