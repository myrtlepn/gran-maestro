from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts._flow_logger import _fsync_counters, append_hook_event, append_skill_event, flow_log_path


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _append_skill_events(project_root: Path, count: int) -> Path | None:
    path = None
    for index in range(count):
        path = append_skill_event(
            project_root,
            "test-s",
            skill="demo",
            step=index + 1,
            total_steps=count,
            event_type="enter",
        )
    return path


def _append_hook_events(project_root: Path, count: int) -> Path | None:
    path = None
    for index in range(count):
        path = append_hook_event(
            project_root,
            "test-s",
            hook_event="Stop",
            decision="allow",
            layer="fsync",
            reason=f"iteration-{index}",
        )
    return path


def test_skill_event_fsync_frequency(tmp_path, monkeypatch):
    project_root = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_FLUSH_EVERY_N", "5")
    _fsync_counters.clear()

    with patch("scripts._flow_logger.os.fsync") as mock_fsync:
        path = _append_skill_events(project_root, 10)

    assert path == flow_log_path(project_root)
    assert mock_fsync.call_count == 2


def test_hook_event_fsync_frequency(tmp_path, monkeypatch):
    project_root = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_FLUSH_EVERY_N", "5")
    _fsync_counters.clear()

    with patch("scripts._flow_logger.os.fsync") as mock_fsync:
        path = _append_hook_events(project_root, 10)

    assert path is not None
    assert mock_fsync.call_count == 2


def test_default_threshold_no_fsync(tmp_path, monkeypatch):
    project_root = _workspace(tmp_path)
    monkeypatch.delenv("MST_FLOW_LOG_FLUSH_EVERY_N", raising=False)
    _fsync_counters.clear()

    with patch("scripts._flow_logger.os.fsync") as mock_fsync:
        path = _append_skill_events(project_root, 5)

    assert path == flow_log_path(project_root)
    assert mock_fsync.call_count == 0


def test_fsync_failure_fail_open(tmp_path, monkeypatch, capsys):
    project_root = _workspace(tmp_path)
    monkeypatch.setenv("MST_FLOW_LOG_FLUSH_EVERY_N", "5")
    _fsync_counters.clear()

    with patch("scripts._flow_logger.os.fsync", side_effect=OSError("disk full")):
        path = _append_skill_events(project_root, 5)

    captured = capsys.readouterr()
    assert path == flow_log_path(project_root)
    assert path.exists()
    assert captured.err.startswith("[flow-logger] fsync failed:")
