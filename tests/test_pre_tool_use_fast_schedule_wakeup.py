from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hooks.lib import pre_tool_use_fast


BLOCK_REASON = "ScheduleWakeup is blocked during MST workflow chain (workflow_active=true)."
PPID = "75701"
REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".gran-maestro" / "tmp").mkdir(parents=True)
    return project


def _state_path(project: Path) -> Path:
    return project / ".gran-maestro" / "tmp" / f"mst-state-{PPID}.json"


def _timestamp(delta_seconds: int = 0) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_state(project: Path, payload: dict) -> None:
    _state_path(project).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _payload() -> dict:
    return {"tool_name": "ScheduleWakeup", "tool_input": {"delaySeconds": 1500}}


def _run(project: Path, home: Path) -> int:
    return pre_tool_use_fast.hardcoded_core_check(project, home, _payload())


def _set_workflow(project: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MST_STATE_PPID": PPID}
    return subprocess.run(
        [sys.executable, str(MST), "state", "set-workflow", *args],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_block_when_workflow_active(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(project, {"workflow_active": True, "updated_at": _timestamp()})

    result = _run(project, tmp_path / "home")

    err = capsys.readouterr().err
    assert result == 2
    assert "MST-SCHEDULE-WAKEUP-BLOCK" in err
    assert BLOCK_REASON in err
    assert "ScheduleWakeup이 차단되었습니다" in err
    assert "scripts/mst-loop.sh" in err
    assert "/mst:resume" in err


def test_pass_when_workflow_inactive(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(project, {"workflow_active": False, "updated_at": _timestamp()})

    result = _run(project, tmp_path / "home")

    assert result == 0
    assert "MST-SCHEDULE-WAKEUP-BLOCK" not in capsys.readouterr().err


def test_grace_period_within_30s(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(
        project,
        {
            "workflow_active": False,
            "last_active_at": _timestamp(-25),
            "updated_at": _timestamp(),
        },
    )

    result = _run(project, tmp_path / "home")

    assert result == 2
    assert "MST-SCHEDULE-WAKEUP-BLOCK" in capsys.readouterr().err


def test_grace_period_after_30s(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(
        project,
        {
            "workflow_active": False,
            "last_active_at": _timestamp(-35),
            "updated_at": _timestamp(),
        },
    )

    result = _run(project, tmp_path / "home")

    assert result == 0
    assert "MST-SCHEDULE-WAKEUP-BLOCK" not in capsys.readouterr().err


def test_grace_period_after_active_to_inactive_transition(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(
        project,
        {
            "workflow_active": True,
            "last_active_at": _timestamp(-31 * 60),
            "updated_at": _timestamp(),
        },
    )
    transition = _set_workflow(project, "--active", "false", "--auto", "false")
    assert transition.returncode == 0, transition.stderr

    result = _run(project, tmp_path / "home")

    assert result == 2
    assert "MST-SCHEDULE-WAKEUP-BLOCK" in capsys.readouterr().err


def test_no_last_active_at_field(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(project, {"workflow_active": True, "updated_at": _timestamp()})

    result = _run(project, tmp_path / "home")

    assert result == 2
    assert BLOCK_REASON in capsys.readouterr().err


def test_escape_hatch_env(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    monkeypatch.setenv("MST_ALLOW_SCHEDULE_WAKEUP", "1")
    _write_state(project, {"workflow_active": True, "updated_at": _timestamp()})

    result = _run(project, tmp_path / "home")

    assert result == 0
    assert "[mst] ScheduleWakeup escape hatch used" in capsys.readouterr().err


def test_loop_user_protected(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    assert _run(project, tmp_path / "home") == 0

    _write_state(project, {"workflow_active": False, "updated_at": _timestamp()})
    assert _run(project, tmp_path / "home") == 0
    assert "MST-SCHEDULE-WAKEUP-BLOCK" not in capsys.readouterr().err


def test_expired_workflow_state_passes(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    monkeypatch.setenv("MST_STATE_PPID", PPID)
    _write_state(project, {"workflow_active": True, "updated_at": _timestamp(-31 * 60)})

    result = _run(project, tmp_path / "home")

    assert result == 0
    assert "MST-SCHEDULE-WAKEUP-BLOCK" not in capsys.readouterr().err
