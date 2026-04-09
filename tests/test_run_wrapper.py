import json
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_run_basic_tee_and_state(tmp_path):
    """AC-001: stdout/stderr tee + run/{task_id}.json 생성 + 종료 필드 기록"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "T-TEST-001",
        "--provider",
        "codex",
        "--model",
        "test-model",
        "--log-dir",
        str(log_dir),
        "--",
        "bash",
        "-c",
        "echo hello; echo err >&2",
    )

    assert proc.returncode == 0, proc.stderr
    running_log = (log_dir / "running.log").read_text(encoding="utf-8")
    assert "hello" in running_log
    assert "err" in running_log

    state_file = workspace / ".gran-maestro" / "run" / "T-TEST-001.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["task_id"] == "T-TEST-001"
    assert state["phase"] == "done"
    assert state["exit_code"] == 0
    assert "started_at" in state
    assert "terminated_at" in state
    assert "pid" in state


def test_heartbeat_thread_updates(tmp_path):
    """AC-002: heartbeat_interval=1로 3초 실행 시 last_heartbeat가 started_at과 다르게 갱신"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "T-HB",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(log_dir),
        "--heartbeat-interval",
        "1",
        "--",
        "bash",
        "-c",
        "sleep 3",
        timeout=30,
    )
    assert proc.returncode == 0

    state = json.loads((workspace / ".gran-maestro" / "run" / "T-HB.json").read_text(encoding="utf-8"))
    assert state["started_at"] != state["last_heartbeat"]
    assert state["phase"] == "done"


def test_run_preserves_exit_code(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "T-EXIT",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(log_dir),
        "--",
        "bash",
        "-c",
        "exit 7",
    )
    assert proc.returncode == 7
    state = json.loads((workspace / ".gran-maestro" / "run" / "T-EXIT.json").read_text(encoding="utf-8"))
    assert state["exit_code"] == 7


def test_trace_file_generation(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "T-TRACE",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(log_dir),
        "--trace",
        "REQ-TEST/01/unit-test",
        "--",
        "bash",
        "-c",
        "echo traced",
    )
    assert proc.returncode == 0

    traces_dir = log_dir / "traces"
    trace_files = list(traces_dir.glob("codex-unit-test-*.md"))
    assert len(trace_files) == 1
    content = trace_files[0].read_text(encoding="utf-8")
    assert "task_id" in content.lower() or "T-TRACE" in content
    assert "exit_code" in content.lower() or "0" in content


def test_sigterm_propagation(tmp_path):
    """AC-005: SIGTERM 수신 시 subprocess로 전파되고 state에 phase=done 기록"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = subprocess.Popen(
        [
            sys.executable,
            str(MST_SCRIPT),
            "run",
            "--task-id",
            "T-SIG",
            "--provider",
            "codex",
            "--model",
            "test",
            "--log-dir",
            str(log_dir),
            "--",
            "bash",
            "-c",
            "sleep 10",
        ],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)

    state_file = workspace / ".gran-maestro" / "run" / "T-SIG.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["phase"] in ("done", "terminated")


def test_missing_required_args(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)

    proc = _run_mst(
        workspace,
        "run",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(tmp_path),
        "--",
        "echo",
        "hi",
    )
    assert proc.returncode != 0
