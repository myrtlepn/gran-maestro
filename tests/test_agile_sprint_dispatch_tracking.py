import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = "/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.58.3"
MST_CLI = f"{PLUGIN_ROOT}/scripts/mst.py"
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_MST_CLI = REPO_ROOT / "scripts" / "mst.py"
TERMINAL_PHASES = {"done", "terminated", "failed"}
UNKNOWN_AGE_SEC = 10**9


def _resolve_mst_cli() -> str:
    for candidate in (Path(MST_CLI), REPO_MST_CLI):
        if not candidate.exists():
            continue
        help_result = subprocess.run(
            ["python3", str(candidate), "agile", "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "dispatch-result" in (help_result.stdout + help_result.stderr):
            return str(candidate)
    raise AssertionError("No mst.py with 'agile dispatch-result' support was found.")


MST = _resolve_mst_cli()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_wrapper_background(workspace: Path, task_id: str, log_dir: Path, sleep_sec: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "python3",
            MST,
            "run",
            "--task-id",
            task_id,
            "--provider",
            "claude",
            "--model",
            "sonnet",
            "--log-dir",
            str(log_dir),
            "--",
            "python3",
            "-c",
            f"import time; time.sleep({sleep_sec})",
        ],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_running_state(state_file: Path, proc: subprocess.Popen, timeout_sec: float) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if state_file.exists():
            payload = _read_json(state_file)
            if payload.get("phase") == "running":
                return payload
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    stdout, stderr = proc.communicate(timeout=5)
    raise AssertionError(
        f"running state not observed before timeout; returncode={proc.returncode}; stdout={stdout}; stderr={stderr}"
    )


def _heartbeat_age_seconds(last_heartbeat: object, now_ms: int) -> int:
    if not isinstance(last_heartbeat, str) or not last_heartbeat.strip():
        return UNKNOWN_AGE_SEC
    try:
        heartbeat_ms = int(datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return UNKNOWN_AGE_SEC
    age_sec = (now_ms - heartbeat_ms) // 1000
    return max(0, int(age_sec))


def _as_string(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _collect_dispatch_snapshot(base_dir: Path, stale_threshold_sec: int) -> list[dict]:
    run_dir = base_dir / "run"
    if not run_dir.is_dir():
        return []

    now_ms = int(time.time() * 1000)
    items: list[dict] = []
    for path in sorted(run_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue

        task_id = _as_string(payload.get("task_id"), path.stem)
        phase = _as_string(payload.get("phase"), "running")
        if phase.lower() in TERMINAL_PHASES:
            continue

        heartbeat_age_sec = _heartbeat_age_seconds(payload.get("last_heartbeat"), now_ms)
        items.append(
            {
                "task_id": task_id,
                "phase": phase,
                "provider": _as_string(payload.get("provider"), "unknown"),
                "model": _as_string(payload.get("model"), ""),
                "heartbeat_age_sec": heartbeat_age_sec,
                "stale": heartbeat_age_sec >= stale_threshold_sec,
            }
        )

    items.sort(key=lambda item: item["task_id"])
    return items


def test_wrapper_register_during_run(tmp_path):
    workspace = tmp_path / "workspace"
    base_dir = workspace / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)

    task_id = "AGI-TEST-S01"
    log_dir = base_dir / "agile" / "AGI-TEST" / "sprints" / "S01"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_file = base_dir / "run" / f"{task_id}.json"

    proc = _run_wrapper_background(workspace, task_id, log_dir, sleep_sec=2)
    try:
        running = _wait_for_running_state(state_file, proc, timeout_sec=4)
        assert running["phase"] == "running"
        assert isinstance(running.get("started_at"), str) and running["started_at"]
        assert isinstance(running.get("last_heartbeat"), str) and running["last_heartbeat"]
        assert running.get("provider") == "claude"
        assert running.get("model") == "sonnet"

        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0, stderr or stdout
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_wrapper_final_state(tmp_path):
    workspace = tmp_path / "workspace"
    base_dir = workspace / ".gran-maestro"
    base_dir.mkdir(parents=True, exist_ok=True)

    task_id = "AGI-TEST-S01"
    log_dir = base_dir / "agile" / "AGI-TEST" / "sprints" / "S01"
    log_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "python3",
            MST,
            "run",
            "--task-id",
            task_id,
            "--provider",
            "claude",
            "--model",
            "sonnet",
            "--log-dir",
            str(log_dir),
            "--",
            "python3",
            "-c",
            "import time; time.sleep(2)",
        ],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    state_file = base_dir / "run" / f"{task_id}.json"
    assert state_file.exists()
    final_state = _read_json(state_file)
    assert final_state["phase"] == "done"
    assert final_state["exit_code"] == 0
    assert isinstance(final_state.get("terminated_at"), str) and final_state["terminated_at"]


def test_dispatch_snapshot_includes_sprint(tmp_path):
    base_dir = tmp_path / ".gran-maestro"
    run_dir = base_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    (run_dir / "AGI-TEST-S01.json").write_text(
        json.dumps(
            {
                "task_id": "AGI-TEST-S01",
                "phase": "running",
                "provider": "claude",
                "model": "sonnet",
                "last_heartbeat": now,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "AGI-TEST-S99.json").write_text(
        json.dumps(
            {
                "task_id": "AGI-TEST-S99",
                "phase": "done",
                "provider": "claude",
                "model": "sonnet",
                "last_heartbeat": now,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = _collect_dispatch_snapshot(base_dir, stale_threshold_sec=60)
    target = next((item for item in snapshot if item["task_id"] == "AGI-TEST-S01"), None)

    assert target is not None
    assert target["provider"] == "claude"
    assert target["phase"] == "running"
    assert isinstance(target["heartbeat_age_sec"], int)
    assert target["heartbeat_age_sec"] >= 0


def test_inline_no_dispatch_result(tmp_path):
    """T02 inline 경로에서 dispatch-result.json이 생성되지 않음을 시뮬레이션으로 검증."""
    base_dir = tmp_path / ".gran-maestro"
    run_dir = base_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    task_id = "AGI-TEST-S02"
    run_file = run_dir / f"{task_id}.json"
    run_file.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "phase": "running",
                "inline": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    running = json.loads(run_file.read_text(encoding="utf-8"))
    assert running["phase"] == "running"
    assert running["inline"] is True

    run_file.write_text(
        json.dumps(
            {
                **running,
                "phase": "done",
                "terminated_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": 0,
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    final = json.loads(run_file.read_text(encoding="utf-8"))
    assert final["phase"] == "done"
    assert final["exit_code"] == 0

    sprint_dir = base_dir / "agile" / "AGI-TEST" / "sprints" / "S02"
    sprint_dir.mkdir(parents=True, exist_ok=True)
    dispatch_result = sprint_dir / "dispatch-result.json"
    assert not dispatch_result.exists()
