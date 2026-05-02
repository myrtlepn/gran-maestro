from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from scripts.mst_cmds import cleanup


FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), (
        f"scripts.mst_cmds.cleanup.{name} is required by REQ-800 T01. "
        "T02 should route every production cleanup entry through this shared lock/report wrapper API."
    )
    return value


def _cleanup_api_or_skip(name: str):
    value = getattr(cleanup, name, None)
    if not callable(value):
        pytest.skip(f"cleanup.{name} is not implemented yet")
    return value


def _load_inventory() -> list[dict]:
    return json.loads((FIXTURES / "cleanup_entry_inventory.json").read_text(encoding="utf-8"))


def test_cleanup_entry_inventory_is_complete() -> None:
    rows = _load_inventory()

    assert {row["entrypoint"] for row in rows} == {
        "phase5",
        "mstloop",
        "stophook",
        "stale-marker",
        "direct-cli",
    }
    for row in rows:
        source = REPO_ROOT / row["source"]
        assert source.exists(), f"inventory source missing: {row['source']}"
        assert row["required_wrapper"] == "run_cleanup_with_lock_report"


def test_production_cleanup_entries_are_guarded_by_shared_wrapper() -> None:
    inventory = getattr(cleanup, "CLEANUP_ENTRY_INVENTORY", None)
    assert isinstance(inventory, dict), (
        "cleanup.CLEANUP_ENTRY_INVENTORY must map production entrypoints to their "
        "source path and shared wrapper so bypasses are test-detectable."
    )

    for row in _load_inventory():
        entry = inventory.get(row["entrypoint"])
        assert isinstance(entry, dict), f"missing inventory row for {row['entrypoint']}"
        assert entry.get("source") == row["source"]
        assert entry.get("wrapper") == row["required_wrapper"]


def test_required_cleanup_concurrency_contract_api_exists() -> None:
    _require_cleanup_api("run_cleanup_with_lock_report")
    _require_cleanup_api("plan_cleanup_targets")


@pytest.mark.skipif(os.name == "nt", reason="cleanup flock contract is POSIX-only")
def test_shared_cleanup_wrapper_allows_exactly_one_real_cleanup(tmp_path: Path) -> None:
    run_with_lock = _cleanup_api_or_skip("run_cleanup_with_lock_report")
    project_root = tmp_path / "project"
    (project_root / ".gran-maestro").mkdir(parents=True)
    barrier = threading.Barrier(8)
    real_entries: list[str] = []
    reports: list[dict] = []
    lock = threading.Lock()

    def real_cleanup(report_context: dict) -> dict:
        with lock:
            real_entries.append(report_context["session_id"])
        time.sleep(0.2)
        return {"status": "ok", "real_cleanup": True}

    def caller(index: int) -> None:
        barrier.wait(timeout=2)
        report = run_with_lock(
            project_root=project_root,
            entrypoint="mstloop",
            session_id=f"sid-{index}",
            timeout_seconds=0.5,
            cleanup_fn=real_cleanup,
        )
        with lock:
            reports.append(report)

    started = time.monotonic()
    threads = [threading.Thread(target=caller, args=(idx,), daemon=True) for idx in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=6)
    elapsed = time.monotonic() - started

    assert all(not thread.is_alive() for thread in threads)
    assert elapsed < 6.0
    assert len(real_entries) == 1
    assert len(reports) == 8
    losers = [report for report in reports if report.get("status") != "ok"]
    assert len(losers) == 7
    assert {report.get("status") for report in losers} <= {"skipped"}
    assert {report.get("reason") for report in losers} <= {"cleanup-in-progress", "flock-timeout"}
    assert (project_root / ".gran-maestro" / "cleanup.lock").exists()


@pytest.mark.skipif(os.name == "nt", reason="cleanup flock timeout contract is POSIX-only")
def test_lock_timeout_returns_stub_report_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
            session_id="sid-timeout",
            timeout_seconds=0.2,
            cleanup_fn=lambda _context: {"status": "ok"},
        )
        elapsed = time.monotonic() - started
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)

    captured = capsys.readouterr()
    assert elapsed < 6.0
    assert report["status"] == "skipped"
    assert report["reason"] == "flock-timeout"
    assert report["entrypoint"] == "stophook"
    assert report["session_id"] == "sid-timeout"
    assert report["lock_path"] == str(lock_path)
    assert 0 <= float(report["wait_seconds"]) <= 0.5
    assert "flock-timeout" in captured.err
    assert "Traceback" not in captured.err


def test_active_resources_are_not_mutated_by_concurrent_cleanup_fixture(tmp_path: Path) -> None:
    plan_cleanup = _cleanup_api_or_skip("plan_cleanup_targets")
    project_root = tmp_path / "project"
    active_worktree = project_root / ".gran-maestro" / "worktrees" / "REQ-800-T99"
    active_meta = active_worktree / "meta.json"
    active_branch = "gran-maestro/main/REQ-800-T99"
    active_worktree.mkdir(parents=True)
    active_meta.write_text(json.dumps({"owner_session_id": "active-sid"}), encoding="utf-8")

    plan = plan_cleanup(
        project_root=project_root,
        entrypoint="stale-marker",
        target_session_id="old-stale-sid",
        active_sessions={"active-sid"},
        active_worktrees={str(active_worktree)},
        active_branches={active_branch},
    )

    assert str(active_worktree) not in set(plan.get("remove_worktrees", []))
    assert str(active_meta) not in set(plan.get("archive_meta", []))
    assert active_branch not in set(plan.get("delete_branches", []))
    assert plan.get("kill_pids", []) == []
