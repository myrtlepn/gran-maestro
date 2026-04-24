import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_statusline(workspace: Path, payload: str = "{}") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _last_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines[-1]


def _iso_ago(**kwargs) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


def _write_snapshot(workspace: Path, payload: dict) -> Path:
    path = workspace / ".gran-maestro" / "state" / str(os.getpid()) / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_run(
    workspace: Path,
    task_id: str,
    provider: str,
    heartbeat: str,
    *,
    phase: str = "running",
    skill: str = "",
    started_by_pid: Optional[int] = os.getpid(),
) -> None:
    path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "pid": 12345,
        "phase": phase,
        "provider": provider,
        "model": "test-model",
        "worktree_dir": str(workspace),
        "last_heartbeat": heartbeat,
    }
    if started_by_pid is not None:
        payload["started_by_pid"] = started_by_pid
    if skill:
        payload["skill"] = skill
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_oldest_auto_scale_and_prefix_absorption(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "plan",
            "enteredAt": _iso_ago(minutes=1),
            "skillStack": [],
        },
    )
    _write_run(workspace, "REQ-700-T01", "codex", _iso_ago(seconds=30))
    _write_run(workspace, "REQ-700-T02", "gemini", _iso_ago(minutes=2))
    _write_run(workspace, "REQ-700-T03", "claude", _iso_ago(days=9))

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert "· oldest" not in last_line
    assert "MST 3 run" not in last_line
    assert re.search(r"oldest \d+s", last_line) is None
    assert re.fullmatch(
        r"plan\(1m\) > \[codex:REQ-700-T01\(3[0-9]s\), gemini:REQ-700-T02\(2m\), claude:REQ-700-T03\(9d\)\]",
        last_line,
    ), last_line


def test_run_json_skill_field(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    with_skill = _run_mst(
        workspace,
        "run",
        "--provider",
        "codex",
        "--task-id",
        "REQ-700-T01",
        "--skill",
        "mst:codex",
        "--model",
        "test-model",
        "--log-dir",
        str(log_dir),
        "--",
        "true",
    )
    assert with_skill.returncode == 0, with_skill.stderr

    data = json.loads((workspace / ".gran-maestro" / "run" / "REQ-700-T01.json").read_text(encoding="utf-8"))
    assert data["skill"] == "mst:codex"
    assert data["task_id"] == "REQ-700-T01"
    assert data["provider"] == "codex"
    assert data["phase"] == "done"
    assert data["worktree_dir"] == str(workspace)

    no_skill = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--provider",
        "gemini",
        "--task-id",
        "REQ-700-T02",
        "--pid",
        "12345",
        "--model",
        "test-model",
        "--worktree-dir",
        str(workspace),
    )
    assert no_skill.returncode == 0, no_skill.stderr

    data = json.loads((workspace / ".gran-maestro" / "run" / "REQ-700-T02.json").read_text(encoding="utf-8"))
    assert data["skill"] == ""
    assert data["pid"] == 12345
    assert data["provider"] == "gemini"


def test_parallel_group_node(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "request",
            "enteredAt": _iso_ago(minutes=2),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
            ],
        },
    )
    _write_run(workspace, "REQ-700-T01", "codex", _iso_ago(minutes=2), skill="mst:codex")
    _write_run(workspace, "REQ-700-T02", "gemini", _iso_ago(minutes=3), skill="mst:gemini")

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(
        r"plan\(8m\) > request\(2m\) > \[codex:REQ-700-T01\(2m\), gemini:REQ-700-T02\(3m\)\]",
        last_line,
    ), last_line


def test_dispatch_group_keeps_only_current_ppid_running_runs(tmp_path):
    workspace = tmp_path / "workspace"
    _write_run(workspace, "A", "codex", _iso_ago(seconds=30), started_by_pid=os.getpid())
    _write_run(workspace, "B", "gemini", _iso_ago(seconds=30), started_by_pid=11111)
    _write_run(workspace, "C", "claude", _iso_ago(seconds=30), phase="done", started_by_pid=os.getpid())

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(r"\[codex:A\(3[0-9]s\)\]", last_line), last_line
    assert "B" not in last_line
    assert "C" not in last_line


def test_dispatch_group_silently_drops_legacy_run_without_started_by_pid(tmp_path):
    workspace = tmp_path / "workspace"
    _write_run(workspace, "legacy", "codex", _iso_ago(seconds=30), started_by_pid=None)

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert last_line == "MST idle"
    assert "legacy" not in last_line


def test_no_dispatch_no_group(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro" / "run").mkdir(parents=True, exist_ok=True)
    _write_snapshot(
        workspace,
        {
            "currentSkill": "request",
            "enteredAt": _iso_ago(minutes=2),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
            ],
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert last_line == "plan(8m) > request(2m)"
    assert "[" not in last_line
    assert "]" not in last_line
