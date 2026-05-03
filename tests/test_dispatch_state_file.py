import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"


def _run_mst(workspace: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_dispatch_register_and_heartbeat_updates_state_file(tmp_path):
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)
    env = {"MST_SESSION_ID": SESSION_ID}

    task_id = "task-state-001"
    register = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert register.returncode == 0, register.stderr

    run_file = base / "run" / f"{task_id}.json"
    assert run_file.exists()

    data = json.loads(run_file.read_text(encoding="utf-8"))
    assert data["pid"] == 12345
    assert data["mst_session_id"] == SESSION_ID
    assert data["phase"] == "running"
    assert data["provider"] == "codex"
    assert data["model"] == "gpt-test"
    assert data["worktree_dir"] == str(workspace)
    assert isinstance(data.get("started_at"), str) and data["started_at"]
    assert isinstance(data.get("last_heartbeat"), str) and data["last_heartbeat"]

    first_heartbeat = data["last_heartbeat"]
    time.sleep(0.02)

    heartbeat = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--phase",
        "running",
        env=env,
    )
    assert heartbeat.returncode == 0, heartbeat.stderr

    data_after = json.loads(run_file.read_text(encoding="utf-8"))
    assert data_after["phase"] == "running"
    assert data_after["last_heartbeat"] != first_heartbeat

    final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "0",
        env=env,
    )
    assert final.returncode == 0, final.stderr

    data_final = json.loads(run_file.read_text(encoding="utf-8"))
    assert data_final["phase"] == "done"
    assert data_final["exit_code"] == 0
    assert isinstance(data_final.get("terminated_at"), str) and data_final["terminated_at"]
