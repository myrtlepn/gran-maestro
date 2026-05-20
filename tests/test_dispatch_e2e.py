import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "MST-AGI-040-20260520T000000000Z-dispe2e1"
ROOT_MST_ID = "AGI-040"


def _run_mst(workspace: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_stub_codex(bin_dir: Path) -> None:
    path = bin_dir / "codex"
    path.write_text(
        "#!/bin/sh\n"
        "sleep 300\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _wait_for_file(path: Path, timeout_sec: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"state file was not created in time: {path}")


def test_dispatch_e2e_build_register_heartbeat_list_kill_cycle(tmp_path):
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_stub_codex(bin_dir)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["MST_SESSION_ID"] = SESSION_ID

    task_id = "dispatch-e2e-task-001"
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("dispatch e2e prompt", encoding="utf-8")
    log_file = workspace / "dispatch-e2e.log"

    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-e2e",
        env=env,
    )
    assert built.returncode == 0, built.stderr
    command = built.stdout.strip()

    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state_file = base / "run" / f"{task_id}.json"

    try:
        _wait_for_file(state_file)
        running_state = json.loads(state_file.read_text(encoding="utf-8"))
        assert running_state.get("phase") == "running"
        assert running_state.get("mst_session_id") == SESSION_ID
        assert running_state.get("root_mst_id") == ROOT_MST_ID

        last_heartbeat = str(running_state.get("last_heartbeat", ""))
        for _ in range(3):
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
            updated_state = json.loads(state_file.read_text(encoding="utf-8"))
            assert updated_state.get("phase") == "running"
            assert isinstance(updated_state.get("last_heartbeat"), str) and updated_state["last_heartbeat"]
            assert updated_state["last_heartbeat"] != last_heartbeat
            last_heartbeat = updated_state["last_heartbeat"]
            time.sleep(0.02)

        listed_before = _run_mst(
            workspace,
            "dispatch",
            "list",
            "--format",
            "json",
            "--stale-threshold",
            "60",
        )
        assert listed_before.returncode == 0, listed_before.stderr
        rows_before = json.loads(listed_before.stdout)
        by_task_before = {row["task_id"]: row for row in rows_before}
        assert by_task_before[task_id]["status"] == "running"

        killed = _run_mst(
            workspace,
            "dispatch",
            "kill",
            "--task-id",
            task_id,
            "--signal",
            "TERM",
        )
        assert killed.returncode == 0, killed.stderr

        proc.wait(timeout=5)

        terminated_state = json.loads(state_file.read_text(encoding="utf-8"))
        assert terminated_state.get("phase") == "terminated"
        assert terminated_state.get("mst_session_id") == SESSION_ID
        assert terminated_state.get("root_mst_id") == ROOT_MST_ID
        assert isinstance(terminated_state.get("terminated_at"), str) and terminated_state["terminated_at"]

        listed_after = _run_mst(
            workspace,
            "dispatch",
            "list",
            "--format",
            "json",
            "--stale-threshold",
            "60",
        )
        assert listed_after.returncode == 0, listed_after.stderr
        rows_after = json.loads(listed_after.stdout)
        by_task_after = {row["task_id"]: row for row in rows_after}
        assert by_task_after[task_id]["status"] == "terminated"

        active_tasks = {row["task_id"] for row in rows_after if row.get("status") in {"running", "stale"}}
        assert task_id not in active_tasks
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
