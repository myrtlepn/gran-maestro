import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from scripts._skill_state import _normalize_stack, apply_event, get_snapshot, set_snapshot
from scripts.mst_cmds import _common
from scripts.mst_cmds import hooks as hooks_cmd
from scripts.mst_cmds import state as state_cmd
from scripts.mst_cmds.hooks import _hooks_post_skill_continuation


ISO_8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")
REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_state(workspace: Path, *args: str, ppid: Optional[str] = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if ppid is None:
        env.pop("MST_STATE_PPID", None)
    else:
        env["MST_STATE_PPID"] = ppid
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "state", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_state_set_uses_mst_state_ppid_snapshot_path(tmp_path):
    workspace = _workspace(tmp_path)

    result = _run_state(
        workspace,
        "set",
        "--skill",
        "mst:plan",
        "--step",
        "1",
        "--total",
        "5",
        ppid="12345",
    )

    assert result.returncode == 0, result.stderr
    snapshot_path = workspace / ".gran-maestro" / "state" / "12345" / "snapshot.json"
    assert snapshot_path.exists()
    assert not (workspace / ".gran-maestro" / "state" / "default" / "snapshot.json").exists()
    data = _read_json(snapshot_path)
    assert data["currentSkill"] == "mst:plan"
    assert data["currentStep"] == 1


def test_state_get_isolates_snapshots_by_mst_state_ppid(tmp_path):
    workspace = _workspace(tmp_path)
    base_dir = workspace / ".gran-maestro"
    set_snapshot(base_dir, skill="mst:plan", step=1, total=5, session_id="12345")
    set_snapshot(base_dir, skill="mst:request", step=2, total=3, session_id="67890")

    result = _run_state(workspace, "get", ppid="12345")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["sessionId"] == "12345"
    assert data["currentSkill"] == "mst:plan"
    assert data["currentStep"] == 1
    assert "mst:request" not in result.stdout


def test_get_snapshot_falls_back_to_default_without_writing_default(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    default_path = base_dir / "state" / "default" / "snapshot.json"
    set_snapshot(base_dir, skill="mst:legacy", step=3, total=7)
    before_default = default_path.read_text(encoding="utf-8")

    fallback = get_snapshot(base_dir, session_id="12345")
    set_snapshot(base_dir, skill="mst:plan", step=1, total=5, session_id="12345")

    assert fallback is not None
    assert fallback["sessionId"] == "default"
    assert fallback["currentSkill"] == "mst:legacy"
    assert (base_dir / "state" / "12345" / "snapshot.json").exists()
    assert default_path.read_text(encoding="utf-8") == before_default


def test_snapshot_session_id_uses_getppid_when_mst_state_ppid_unset(monkeypatch):
    monkeypatch.delenv("MST_STATE_PPID", raising=False)
    expected = str(os.getppid())

    assert state_cmd._snapshot_session_id() == expected
    assert hooks_cmd._snapshot_session_id() == expected


@pytest.mark.parametrize("ppid_env", ["", "   "])
def test_snapshot_session_id_uses_getppid_when_mst_state_ppid_blank(monkeypatch, ppid_env):
    monkeypatch.setenv("MST_STATE_PPID", ppid_env)
    expected = str(os.getppid())

    assert state_cmd._snapshot_session_id() == expected
    assert hooks_cmd._snapshot_session_id() == expected


def test_snapshot_session_id_prefers_mst_state_ppid(monkeypatch):
    monkeypatch.setenv("MST_STATE_PPID", "12345")

    assert state_cmd._snapshot_session_id() == "12345"
    assert hooks_cmd._snapshot_session_id() == "12345"


def test_state_commands_use_current_ppid_when_mst_state_ppid_unset(tmp_path):
    workspace = _workspace(tmp_path)
    expected_session_id = str(os.getpid())

    set_result = _run_state(
        workspace,
        "set",
        "--skill",
        "mst:plan",
        "--step",
        "1",
        "--total",
        "5",
    )
    get_result = _run_state(workspace, "get")
    clear_result = _run_state(workspace, "clear")

    assert set_result.returncode == 0, set_result.stderr
    assert get_result.returncode == 0, get_result.stderr
    assert clear_result.returncode == 0, clear_result.stderr
    data = json.loads(get_result.stdout)
    assert data["sessionId"] == expected_session_id
    assert data["currentSkill"] == "mst:plan"
    assert not (
        workspace / ".gran-maestro" / "state" / expected_session_id / "snapshot.json"
    ).exists()
    assert not (workspace / ".gran-maestro" / "state" / "default" / "snapshot.json").exists()


def test_state_commands_use_current_ppid_when_mst_state_ppid_blank(tmp_path):
    workspace = _workspace(tmp_path)
    expected_session_id = str(os.getpid())

    set_result = _run_state(
        workspace,
        "set",
        "--skill",
        "mst:plan",
        "--step",
        "1",
        "--total",
        "5",
        ppid="   ",
    )
    get_result = _run_state(workspace, "get", ppid="   ")
    clear_result = _run_state(workspace, "clear", ppid="   ")

    assert set_result.returncode == 0, set_result.stderr
    assert get_result.returncode == 0, get_result.stderr
    assert clear_result.returncode == 0, clear_result.stderr
    data = json.loads(get_result.stdout)
    assert data["sessionId"] == expected_session_id
    assert data["currentSkill"] == "mst:plan"
    assert not (
        workspace / ".gran-maestro" / "state" / expected_session_id / "snapshot.json"
    ).exists()
    assert not (workspace / ".gran-maestro" / "state" / "default" / "snapshot.json").exists()


def test_hooks_post_skill_continuation_uses_mst_state_ppid(tmp_path, monkeypatch, capsys):
    base_dir = tmp_path / ".gran-maestro"
    set_snapshot(
        base_dir,
        skill="mst:child",
        step=1,
        total=1,
        return_to="parent/2",
        session_id="12345",
    )
    set_snapshot(
        base_dir,
        skill="mst:child",
        step=1,
        total=1,
        return_to="other/9",
        session_id="67890",
    )
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    monkeypatch.setenv("MST_STATE_PPID", "12345")

    _hooks_post_skill_continuation("mst:child")

    output = capsys.readouterr().out
    assert "return_to=parent/2" in output
    assert "return_to=other/9" not in output


def test_hooks_post_skill_continuation_uses_current_ppid_when_mst_state_ppid_unset(
    tmp_path, monkeypatch, capsys
):
    base_dir = tmp_path / ".gran-maestro"
    current_ppid = str(os.getppid())
    set_snapshot(
        base_dir,
        skill="mst:child",
        step=1,
        total=1,
        return_to="parent/2",
        session_id=current_ppid,
    )
    set_snapshot(
        base_dir,
        skill="mst:child",
        step=1,
        total=1,
        return_to="default/9",
    )
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    monkeypatch.delenv("MST_STATE_PPID", raising=False)

    _hooks_post_skill_continuation("mst:child")

    output = capsys.readouterr().out
    assert "return_to=parent/2" in output
    assert "return_to=default/9" not in output


def test_enter_records_entered_at():
    snapshot = {
        "sessionId": "default",
        "currentSkill": "A",
        "currentStep": 2,
        "totalSteps": 3,
        "enterCount": 1,
        "skillStack": [],
        "status": "active",
    }

    updated = apply_event(snapshot, "enter", skill="B", step=1, total=5)

    assert len(updated["skillStack"]) == 1
    frame = updated["skillStack"][0]
    assert frame["skill"] == "A"
    assert frame["step"] == 2
    assert ISO_8601_UTC_RE.match(frame["enteredAt"])
    assert frame["enteredAt"] == updated["enteredAt"] == updated["updatedAt"]


def test_normalize_stack_backward_compat():
    stack = [
        {"skill": "without-time", "step": 1},
        {"skill": "with-time", "step": 2, "enteredAt": "2026-04-18T10:11:12.000Z"},
        {"skill": "bad-time", "step": 3, "enteredAt": 123},
    ]

    assert _normalize_stack(stack) == [
        {"skill": "without-time", "step": 1},
        {"skill": "with-time", "step": 2, "enteredAt": "2026-04-18T10:11:12.000Z"},
        {"skill": "bad-time", "step": 3},
    ]
