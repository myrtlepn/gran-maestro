from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.mst_cmds import cleanup


OLD_SID = "11111111-1111-4111-8111-111111111111"
NEW_SID = "22222222-2222-4222-9222-222222222222"


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), f"cleanup.{name} contract helper is missing"
    return value


def _cleanup_api_or_skip(name: str):
    value = getattr(cleanup, name, None)
    if not callable(value):
        pytest.skip(f"cleanup.{name} is not implemented yet")
    return value


def test_required_takeover_marker_contract_api_exists() -> None:
    _require_cleanup_api("recover_takeover_active_marker")
    _require_cleanup_api("scan_active_flow_markers")
    _require_cleanup_api("active_marker_skip_inputs")


def _write_marker(active_dir: Path, sid: str, **overrides: object) -> Path:
    payload = {
        "session_id": sid,
        "pid": 12345,
        "start_time": 1000.0,
        "mode": "marathon",
        "created_at": "2026-05-03T00:00:00Z",
    }
    payload.update(overrides)
    path = active_dir / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", ["old-only", "new-only", "both-present", "rename-failure"])
def test_takeover_active_marker_recovery_leaves_only_new_active_scan_input(tmp_path: Path, case: str) -> None:
    recover = _cleanup_api_or_skip("recover_takeover_active_marker")
    scan = _cleanup_api_or_skip("scan_active_flow_markers")
    active_dir = tmp_path / ".gran-maestro" / "active-flow"

    if case in {"old-only", "both-present", "rename-failure"}:
        _write_marker(active_dir, OLD_SID)
    if case in {"new-only", "both-present"}:
        _write_marker(active_dir, NEW_SID, created_at="2026-05-03T00:00:01Z")

    def rename_func(src: Path, dst: Path) -> None:
        if case == "rename-failure":
            raise OSError("simulated rename failure")
        src.rename(dst)

    report = recover(active_dir=active_dir, old_sid=OLD_SID, new_sid=NEW_SID, rename_func=rename_func)
    scanned = scan(active_dir)
    active_session_ids = [item["session_id"] for item in scanned if item.get("status") != "ignored"]

    assert report["status"] in {"renamed", "new-canonical", "old-ignored", "rename-fallback"}
    assert active_session_ids == [NEW_SID]
    assert (active_dir / f"{NEW_SID}.json").exists()

    old_path = active_dir / f"{OLD_SID}.json"
    if old_path.exists():
        assert _read(old_path)["status"] == "ignored"


def test_takeover_old_marker_cannot_cause_cleanup_skip_after_recovery(tmp_path: Path) -> None:
    recover = _cleanup_api_or_skip("recover_takeover_active_marker")
    decide_skip_inputs = _cleanup_api_or_skip("active_marker_skip_inputs")
    active_dir = tmp_path / ".gran-maestro" / "active-flow"
    _write_marker(active_dir, OLD_SID)
    _write_marker(active_dir, NEW_SID)

    recover(active_dir=active_dir, old_sid=OLD_SID, new_sid=NEW_SID)
    skip_inputs = decide_skip_inputs(active_dir)

    assert [item["session_id"] for item in skip_inputs] == [NEW_SID]
