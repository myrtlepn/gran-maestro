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

        stale_path = run_dir / f"{stale_task}.json"
        active_path = run_dir / f"{active_task}.json"
        _write_state(
            stale_path,
            {
                "task_id": stale_task,
                "pid": stale_proc.pid,
                "provider": "codex",
                "model": "gpt-test",
                "phase": "running",
                "status": "running",
                "worktree_dir": str(workspace),
                "last_heartbeat": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
            },
        )
        _write_state(
            active_path,
            {
                "task_id": active_task,
                "pid": active_proc.pid,
                "provider": "agy",
                "model": "agy-test",
                "phase": "running",
                "status": "running",
                "worktree_dir": str(workspace),
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            },
        )

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


def test_dispatch_lists_and_cancels_pidless_native_without_os_signal(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    task_id = "native-stale"
    state_path = run_dir / f"{task_id}.json"
    state_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "attempt_id": "native-a1",
                "execution_transport": "native",
                "provider": "codex",
                "provider_task_id": "provider-native-1",
                "phase": "running",
                "status": "running",
                "pid": None,
                "last_heartbeat": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
                "idempotency_keys": {},
                "lifecycle_events": [],
                "attempts": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    listed = _run_mst(
        workspace,
        "dispatch",
        "list",
        "--format",
        "json",
        "--stale-threshold",
        "60",
    )
    assert listed.returncode == 0, listed.stderr
    row = json.loads(listed.stdout)[0]
    assert row["status"] == "orphaned"
    assert row["execution_transport"] == "native"
    assert row["provider_task_id"] == "provider-native-1"
    assert row["pid"] is None

    cancelled = _run_mst(workspace, "dispatch", "kill", "--task-id", task_id)
    assert cancelled.returncode == 0, cancelled.stderr
    summary = json.loads(cancelled.stdout)
    assert summary == {
        "terminated": 0,
        "cancel_requested": 1,
        "reconcile_requested": 0,
        "blocked": 0,
    }
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "reconciling"
    assert state["cancel_status"] == "unconfirmed"
    assert state["os_signal_attempted"] is False


def test_dispatch_native_status_uses_provider_state_and_parent_heartbeat(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    def write(task_id: str, *, provider_state: str, parent_age: int) -> None:
        _write_state(
            run_dir / f"{task_id}.json",
            {
                "task_id": task_id,
                "attempt_id": f"{task_id}-a1",
                "execution_transport": "native",
                "provider": "codex",
                "provider_task_id": f"provider-{task_id}",
                "provider_state": provider_state,
                "phase": "running",
                "status": "running",
                "pid": None,
                "last_heartbeat": (now - timedelta(seconds=120)).isoformat(),
                "parent_heartbeat": (now - timedelta(seconds=parent_age)).isoformat(),
            },
        )

    write("native-provider-live", provider_state="running", parent_age=5)
    write("native-orphan", provider_state="running", parent_age=120)
    write("native-unknown", provider_state="unknown", parent_age=5)

    listed = _run_mst(
        workspace,
        "dispatch",
        "list",
        "--format",
        "json",
        "--stale-threshold",
        "60",
    )
    assert listed.returncode == 0, listed.stderr
    rows = {row["task_id"]: row for row in json.loads(listed.stdout)}
    assert rows["native-provider-live"]["status"] == "running"
    assert rows["native-orphan"]["status"] == "orphaned"
    assert rows["native-unknown"]["status"] == "reconciling"
    assert rows["native-orphan"]["reconciliation_required"] is True

    reconciled = _run_mst(
        workspace,
        "dispatch",
        "kill",
        "--stale",
        "--stale-threshold",
        "60",
    )
    assert reconciled.returncode == 0, reconciled.stderr
    assert json.loads(reconciled.stdout)["reconcile_requested"] == 1
    orphan_state = json.loads((run_dir / "native-orphan.json").read_text(encoding="utf-8"))
    assert orphan_state["reconciliation_action"]["provider_task_id"] == "provider-native-orphan"
    assert orphan_state["reconciliation_action"]["status"] == "pending"
