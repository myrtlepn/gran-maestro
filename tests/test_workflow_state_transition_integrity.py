"""DOD-003: workflow state transition integrity regression tests for state set-workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"
PPID = 99901


def _state_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "tmp" / f"mst-state-{PPID}.json"


def _prepare_workspace(workspace: Path) -> None:
    (workspace / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)


def _run(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MST_STATE_PPID": str(PPID)}
    return subprocess.run(
        [sys.executable, str(MST), "state", "set-workflow", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _read_state(workspace: Path) -> dict:
    return json.loads(_state_path(workspace).read_text(encoding="utf-8"))


def test_agile_loop_active_preserved_across_skill_transitions(tmp_path):
    _prepare_workspace(tmp_path)
    first = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:plan",
        "--req", "",
        "--auto", "true",
        "--agile-loop-active", "true",
    )
    assert first.returncode == 0, first.stderr

    second = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:request",
        "--req", "PLN-999",
        "--auto", "true",
    )
    assert second.returncode == 0, second.stderr

    state = _read_state(tmp_path)
    assert state["agile_loop_active"] is True
    assert state["current_skill"] == "mst:request"
    assert state["active_req"] == "PLN-999"


def test_disabling_agile_loop_resets_block_count(tmp_path):
    _prepare_workspace(tmp_path)
    # 초기 상태 구성
    init = _run(tmp_path, "--active", "true", "--skill", "mst:agile", "--req", "")
    assert init.returncode == 0, init.stderr

    # block_count 직접 주입
    state_path = _state_path(tmp_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["block_count"] = 5
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # agile-loop-active=false 전환
    result = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:agile",
        "--agile-loop-active", "false",
    )
    assert result.returncode == 0, result.stderr

    state = _read_state(tmp_path)
    assert state["agile_loop_active"] is False
    assert state["block_count"] == 0


def test_inactive_workflow_clears_current_skill_and_req(tmp_path):
    _prepare_workspace(tmp_path)
    setup = _run(
        tmp_path,
        "--active", "true",
        "--skill", "mst:approve",
        "--req", "REQ-999",
    )
    assert setup.returncode == 0, setup.stderr
    assert _read_state(tmp_path)["current_skill"] == "mst:approve"

    teardown = _run(
        tmp_path,
        "--active", "false",
        "--auto", "false",
    )
    assert teardown.returncode == 0, teardown.stderr

    state = _read_state(tmp_path)
    assert state["workflow_active"] is False
    assert state["current_skill"] == ""
    assert state["active_req"] == ""
