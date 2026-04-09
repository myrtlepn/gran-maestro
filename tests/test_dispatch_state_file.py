import json
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dispatch_register_and_heartbeat_updates_state_file(tmp_path):
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)

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
    )
    assert register.returncode == 0, register.stderr

    run_file = base / "run" / f"{task_id}.json"
    assert run_file.exists()

    data = json.loads(run_file.read_text(encoding="utf-8"))
    assert data["pid"] == 12345
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
    )
    assert final.returncode == 0, final.stderr

    data_final = json.loads(run_file.read_text(encoding="utf-8"))
    assert data_final["phase"] == "done"
    assert data_final["exit_code"] == 0
    assert isinstance(data_final.get("terminated_at"), str) and data_final["terminated_at"]
