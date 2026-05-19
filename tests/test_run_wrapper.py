import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
UUID_V4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _run_mst(workspace: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _run_mst_without_session_env(
    workspace: Path,
    *args: str,
    optimized: bool = False,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("MST_SESSION_ID", None)
    executable = [sys.executable]
    if optimized:
        executable.append("-O")
    return subprocess.run(
        [*executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def _run_mst_with_session_env(
    workspace: Path,
    session_id: str,
    *args: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["MST_SESSION_ID"] = session_id
    env.pop("MST_CONTEXT_JSON", None)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
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


def test_run_child_env_gets_generated_session_id_without_parent_env(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst_without_session_env(
        workspace,
        "run",
        "--task-id",
        "T-SESSION-ENV",
        "--provider",
        "codex",
        "--model",
        "test-model",
        "--log-dir",
        str(log_dir),
        "--",
        sys.executable,
        "-c",
        "import os; print(os.environ.get('MST_SESSION_ID', ''))",
    )

    assert proc.returncode == 0, proc.stderr
    observed = proc.stdout.strip().splitlines()[-1]
    assert UUID_V4_RE.match(observed)
    assert observed in (log_dir / "running.log").read_text(encoding="utf-8")


def test_run_child_env_guard_survives_python_optimized_mode(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    proc = _run_mst_without_session_env(
        workspace,
        "run",
        "--task-id",
        "T-SESSION-ENV-O",
        "--provider",
        "codex",
        "--model",
        "test-model",
        "--log-dir",
        str(log_dir),
        "--",
        sys.executable,
        "-c",
        "import os; print(os.environ.get('MST_SESSION_ID', ''))",
        optimized=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert UUID_V4_RE.match(proc.stdout.strip().splitlines()[-1])


def test_run_wrapper_uses_parent_canonical_session_for_child_state_and_trace(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()
    session_id = "MST-AGI-030-20260505T010203000Z-runwrap01"

    proc = _run_mst_with_session_env(
        workspace,
        session_id,
        "run",
        "--task-id",
        "T-CANONICAL-SESSION",
        "--provider",
        "codex",
        "--model",
        "test-model",
        "--log-dir",
        str(log_dir),
        "--trace",
        "REQ-TEST/04/canonical-session",
        "--",
        sys.executable,
        "-c",
        "import os; print(os.environ.get('MST_SESSION_ID', ''))",
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == session_id

    state = json.loads(
        (workspace / ".gran-maestro" / "run" / "T-CANONICAL-SESSION.json").read_text(encoding="utf-8")
    )
    assert state["mst_session_id"] == session_id
    assert state["root_mst_id"] == "AGI-030"

    trace_content = next((log_dir / "traces").glob("codex-canonical-session-*.md")).read_text(encoding="utf-8")
    assert f"mst_session_id: {session_id}" in trace_content
    assert "root_mst_id: AGI-030" in trace_content


def test_heartbeat_thread_updates(tmp_path):
    """AC-002: heartbeat thread가 실행 중에 주기적으로 state 파일을 갱신하는지 검증.

    기존 테스트의 약점: final write가 항상 last_heartbeat를 갱신하므로
    heartbeat thread가 비어있어도 started_at != last_heartbeat가 성립.
    해결: wrapper를 백그라운드로 실행하고 실행 중간 시점(T+2.5s)에서
    state 파일의 last_heartbeat를 관찰자가 직접 읽어 갱신을 확인.
    """
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()
    state_file = workspace / ".gran-maestro" / "run" / "T-HB-MID.json"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(MST_SCRIPT),
            "run",
            "--task-id",
            "T-HB-MID",
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
            "sleep 4",
        ],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        deadline = time.time() + 3
        while not state_file.exists() and time.time() < deadline:
            time.sleep(0.1)
        assert state_file.exists(), "state 파일이 생성되지 않음"

        initial = json.loads(state_file.read_text(encoding="utf-8"))
        initial_heartbeat = initial["last_heartbeat"]

        time.sleep(2.5)

        assert proc.poll() is None, "wrapper가 예상보다 먼저 종료됨"
        mid = json.loads(state_file.read_text(encoding="utf-8"))
        mid_heartbeat = mid["last_heartbeat"]

        assert mid["phase"] == "running", f"phase가 running이 아님: {mid['phase']}"
        assert mid_heartbeat != initial_heartbeat, (
            f"heartbeat thread가 갱신하지 않음: initial={initial_heartbeat}, mid={mid_heartbeat}"
        )
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


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
    assert "task_id: T-TRACE" in content, f"task_id 누락: {content[:200]}"
    assert "exit_code: 0" in content, f"exit_code 누락: {content[:200]}"
    assert "trace_label: REQ-TEST/01/unit-test" in content, f"trace_label 누락: {content[:200]}"
    assert "provider: codex" in content


def test_wrapper_timeout_sigterm(tmp_path):
    """AC-001: --timeout 초과 시 wrapper가 subprocess를 종료하고 non-zero로 반환"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    start = time.time()
    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "T-TIMEOUT",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(log_dir),
        "--timeout",
        "2",
        "--",
        "bash",
        "-c",
        "sleep 20",
        timeout=15,
    )
    elapsed = time.time() - start

    assert elapsed < 10, f"wrapper가 timeout을 무시함: {elapsed}s"
    assert proc.returncode != 0, "timeout 시 non-zero exit code여야 함"

    state_file = workspace / ".gran-maestro" / "run" / "T-TIMEOUT.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["phase"] in ("done", "terminated")
    assert "exit_code" in state


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
