from __future__ import annotations

import json
import threading
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


def test_required_active_marker_contract_api_exists() -> None:
    _require_cleanup_api("validate_active_flow_marker")
    _require_cleanup_api("plan_cleanup_targets")
    _require_cleanup_api("write_active_flow_marker")


def test_active_marker_validation_uses_pid_and_epoch_start_time() -> None:
    validate = _cleanup_api_or_skip("validate_active_flow_marker")
    marker = {
        "session_id": "sid-active",
        "pid": 4242,
        "start_time": 1000.0,
        "mode": "marathon",
        "created_at": "2026-05-03T00:00:00Z",
    }

    assert validate(marker, pid_alive=lambda pid: True, process_start_time=lambda pid: 1001.0)["validity"] == "active"
    assert validate(marker, pid_alive=lambda pid: True, process_start_time=lambda pid: 1001.01)["validity"] == "start_time_mismatch"
    assert validate(marker, pid_alive=lambda pid: False, process_start_time=lambda pid: 1000.0)["validity"] == "dead"
    assert validate(marker, pid_alive=lambda pid: True, process_start_time=lambda pid: None)["validity"] == "start_time_mismatch"

    def permission_failure(_pid: int) -> float:
        raise PermissionError("denied")

    def unsupported(_pid: int) -> float:
        raise NotImplementedError("unsupported platform")

    assert validate(marker, pid_alive=lambda pid: True, process_start_time=permission_failure)["validity"] == "start_time_mismatch"
    assert validate(marker, pid_alive=lambda pid: True, process_start_time=unsupported)["validity"] == "start_time_mismatch"


def test_stale_marker_cleanup_does_not_target_new_active_resources(tmp_path: Path) -> None:
    plan_cleanup = _cleanup_api_or_skip("plan_cleanup_targets")
    project_root = tmp_path / "project"
    old_marker = {
        "session_id": "old-sid",
        "pid": 111,
        "start_time": 10.0,
        "mode": "marathon",
    }
    new_marker = {
        "session_id": "new-sid",
        "pid": 222,
        "start_time": 20.0,
        "mode": "marathon",
    }
    new_worktree = project_root / ".gran-maestro" / "worktrees" / "REQ-800-T01"
    new_meta = new_worktree / "meta.json"
    new_worktree.mkdir(parents=True)
    new_meta.write_text(json.dumps({"owner_session_id": "new-sid"}), encoding="utf-8")

    plan = plan_cleanup(
        project_root=project_root,
        entrypoint="stale-marker",
        target_session_id="old-sid",
        markers=[old_marker, new_marker],
        marker_validity={"old-sid": "dead", "new-sid": "active"},
        active_worktrees={str(new_worktree)},
        active_branches={"gran-maestro/main/REQ-800-T01"},
    )

    assert str(new_worktree) not in set(plan.get("remove_worktrees", []))
    assert str(new_meta) not in set(plan.get("archive_meta", []))
    assert "gran-maestro/main/REQ-800-T01" not in set(plan.get("delete_branches", []))
    assert 222 not in set(plan.get("kill_pids", []))


def test_same_sid_reentry_preserves_created_at_and_last_lock_writer_wins(tmp_path: Path) -> None:
    write_marker = _cleanup_api_or_skip("write_active_flow_marker")
    marker_dir = tmp_path / "project" / ".gran-maestro" / "active-flow"
    session_id = "same-sid"
    created_at = "2026-05-03T00:00:00Z"
    results: list[dict] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)
    result_lock = threading.Lock()

    def writer(seq: int) -> None:
        try:
            barrier.wait(timeout=2)
            result = write_marker(
                marker_dir=marker_dir,
                session_id=session_id,
                pid=1000 + seq,
                start_time=2000.0 + seq,
                mode="marathon",
                created_at=created_at,
                updated_at=f"2026-05-03T00:00:0{seq}Z",
                update_seq=seq,
                lock_timeout_seconds=1.0,
            )
            with result_lock:
                results.append(result)
        except BaseException as exc:  # pragma: no cover - assertion below reports it.
            with result_lock:
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(seq,), daemon=True) for seq in range(1, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=6)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    final_payload = json.loads((marker_dir / f"{session_id}.json").read_text(encoding="utf-8"))
    assert final_payload["session_id"] == session_id
    assert final_payload["created_at"] == created_at

    last_writer = max(results, key=lambda item: item["lock_acquired_seq"])
    assert final_payload["updated_at"] == last_writer["updated_at"]
    assert final_payload["update_seq"] == last_writer["update_seq"]
