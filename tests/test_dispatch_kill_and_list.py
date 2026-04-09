import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
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


def _start_sleep_process() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])


def _write_state(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_dispatch_list_and_kill_stale(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    stale_proc = _start_sleep_process()
    active_proc = _start_sleep_process()

    try:
        stale_task = "task-stale"
        active_task = "task-active"

        stale_reg = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            stale_task,
            "--pid",
            str(stale_proc.pid),
            "--provider",
            "codex",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
        )
        assert stale_reg.returncode == 0, stale_reg.stderr

        active_reg = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            active_task,
            "--pid",
            str(active_proc.pid),
            "--provider",
            "gemini",
            "--model",
            "gemini-test",
            "--worktree-dir",
            str(workspace),
        )
        assert active_reg.returncode == 0, active_reg.stderr

        stale_path = run_dir / f"{stale_task}.json"
        active_path = run_dir / f"{active_task}.json"

        stale_data = json.loads(stale_path.read_text(encoding="utf-8"))
        stale_data["last_heartbeat"] = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        _write_state(stale_path, stale_data)

        active_data = json.loads(active_path.read_text(encoding="utf-8"))
        active_data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        _write_state(active_path, active_data)

        started = time.monotonic()
        listed = _run_mst(
            workspace,
            "dispatch",
            "list",
            "--format",
            "json",
            "--stale-threshold",
            "60",
        )
        elapsed = time.monotonic() - started

        assert listed.returncode == 0, listed.stderr
        assert elapsed < 1.0

        rows = json.loads(listed.stdout)
        by_task = {row["task_id"]: row for row in rows}

        assert by_task[stale_task]["status"] == "stale"
        assert by_task[active_task]["status"] == "running"

        killed = _run_mst(
            workspace,
            "dispatch",
            "kill",
            "--stale",
            "--signal",
            "TERM",
            "--stale-threshold",
            "60",
        )
        assert killed.returncode == 0, killed.stderr

        stale_proc.wait(timeout=5)
        assert active_proc.poll() is None

        stale_after = json.loads(stale_path.read_text(encoding="utf-8"))
        active_after = json.loads(active_path.read_text(encoding="utf-8"))

        assert isinstance(stale_after.get("terminated_at"), str) and stale_after["terminated_at"]
        assert active_after.get("terminated_at") in (None, "")
    finally:
        for proc in (stale_proc, active_proc):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
