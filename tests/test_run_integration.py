# ## 발견된 이슈
# - 현재 구현에서 `dispatch list`는 `--json` 플래그를 지원하지 않아 `--format json`을 사용해야 한다.

import json
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST = REPO_ROOT / "scripts" / "mst.py"


def _run_mst_bg(workspace, *args):
    """wrapper를 백그라운드로 실행. Popen 반환."""
    return subprocess.Popen(
        [sys.executable, str(MST), *args],
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _run_mst(workspace, *args, timeout=30):
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_wrapper_e2e_happy_path(tmp_path):
    """AC-001: wrapper → run/*.json → running.log → traces/ E2E"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    task_dir = tmp_path / "req" / "tasks" / "01"
    task_dir.mkdir(parents=True)

    proc = _run_mst(
        workspace,
        "run",
        "--task-id",
        "REQ-TEST-01",
        "--provider",
        "codex",
        "--model",
        "test-model",
        "--log-dir",
        str(task_dir),
        "--trace",
        "REQ-TEST/01/integration",
        "--",
        "bash",
        "-c",
        "echo line1; sleep 0.5; echo line2; exit 0",
    )

    assert proc.returncode == 0, proc.stderr

    state_file = workspace / ".gran-maestro" / "run" / "REQ-TEST-01.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["phase"] == "done"
    assert state["exit_code"] == 0

    log_content = (task_dir / "running.log").read_text()
    assert "line1" in log_content
    assert "line2" in log_content

    traces = list((task_dir / "traces").glob("codex-integration-*.md"))
    assert len(traces) == 1, f"expected 1 trace file, got {len(traces)}"


def test_heartbeat_keeps_alive_during_run(tmp_path):
    """AC-002: heartbeat_interval=1로 4초 실행 시 stale_threshold=2에서도 running 상태 유지"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    proc = _run_mst_bg(
        workspace,
        "run",
        "--task-id",
        "T-ALIVE",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(task_dir),
        "--heartbeat-interval",
        "1",
        "--",
        "bash",
        "-c",
        "sleep 4",
    )
    try:
        # 2초 대기 (heartbeat가 2회 갱신될 시간)
        time.sleep(2.5)
        # dispatch list로 stale_threshold=2 확인
        result = _run_mst(
            workspace,
            "dispatch",
            "list",
            "--stale-threshold",
            "2",
            "--format",
            "json",
            timeout=10,
        )
        assert result.returncode == 0
        rows = json.loads(result.stdout) if result.stdout.strip() else []
        target = next((r for r in rows if r.get("task_id") == "T-ALIVE"), None)
        assert target is not None, f"T-ALIVE not in dispatch list: {rows}"
        # heartbeat 갱신이 정상이면 stale이 아니어야 함
        assert target.get("status") != "stale", f"expected non-stale, got {target}"
    finally:
        proc.wait(timeout=15)


def test_stale_detection_on_sigkill(tmp_path):
    """AC-003: SIGKILL로 강제 종료 시 heartbeat 정지 → stale 판정"""
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    task_dir = tmp_path / "task"
    task_dir.mkdir()

    proc = _run_mst_bg(
        workspace,
        "run",
        "--task-id",
        "T-STALE",
        "--provider",
        "codex",
        "--model",
        "test",
        "--log-dir",
        str(task_dir),
        "--heartbeat-interval",
        "1",
        "--",
        "bash",
        "-c",
        "sleep 20",
    )
    try:
        time.sleep(2)  # 시작 대기
        # 강제 KILL (SIGTERM이 아닌 SIGKILL로 cleanup 경로 우회)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)

        # stale 판정 기다리기 (stale_threshold=1로 즉시 stale)
        time.sleep(2)

        result = _run_mst(
            workspace,
            "dispatch",
            "list",
            "--stale-threshold",
            "1",
            "--format",
            "json",
            timeout=10,
        )
        assert result.returncode == 0
        rows = json.loads(result.stdout) if result.stdout.strip() else []
        target = next((r for r in rows if r.get("task_id") == "T-STALE"), None)
        # SIGKILL 후에는 state 파일이 phase=running에 머물고 heartbeat 갱신이 멈춤 → stale
        assert target is not None
        assert target.get("status") == "stale", f"expected stale, got {target}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
