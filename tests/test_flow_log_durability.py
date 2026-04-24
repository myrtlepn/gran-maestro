import json
import os
import random
import signal
import subprocess
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MONTH = "202604"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _set_flow_env(monkeypatch, log_dir: Path, session_id: str) -> None:
    monkeypatch.setenv("MST_FLOW_LOG_DIR", str(log_dir))
    monkeypatch.setenv("MST_FLOW_LOG_MONTH", MONTH)
    monkeypatch.setenv("MST_SNAPSHOT_SESSION_ID", session_id)
    monkeypatch.delenv("MST_STATE_PPID", raising=False)


def _assert_json_lines(path: Path) -> None:
    if not path.exists():
        return

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"{path}:{line_number} contains a partial JSON line") from exc


def _kill_and_wait(proc: subprocess.Popen, delay: float) -> None:
    time.sleep(delay)
    try:
        os.kill(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=2)


def _state_set_driver(workspace: Path, entries: int = 20) -> subprocess.Popen:
    script = (
        "import subprocess\n"
        "import time\n"
        f"for index in range({entries}):\n"
        "    subprocess.run([\n"
        "        'python3',\n"
        f"        {str(MST_SCRIPT)!r},\n"
        "        'state',\n"
        "        'set',\n"
        "        '--skill',\n"
        "        'loop',\n"
        "        '--step',\n"
        "        str(index + 1),\n"
        "        '--total',\n"
        f"        {str(entries)!r},\n"
        "    ], check=False)\n"
        "    time.sleep(0.05)\n"
    )
    return subprocess.Popen(["python3", "-c", script], cwd=workspace)


def _hook_event_driver(workspace: Path, session_id: str, entries: int = 20) -> subprocess.Popen:
    script = (
        "import time\n"
        "from pathlib import Path\n"
        "from scripts._flow_logger import append_hook_event\n"
        f"project_root = {str(workspace)!r}\n"
        f"session_id = {session_id!r}\n"
        f"for index in range({entries}):\n"
        "    append_hook_event(\n"
        "        project_root=Path(project_root),\n"
        "        session_id=session_id,\n"
        "        hook_event='Stop',\n"
        "        decision='allow',\n"
        "        layer='durability',\n"
        "        reason=f'iteration-{index}',\n"
        "        ppid='test',\n"
        "        rotate=True,\n"
        "    )\n"
        "    time.sleep(0.05)\n"
    )
    return subprocess.Popen(["python3", "-c", script], cwd=REPO_ROOT)


def test_flow_ndjson_sigkill_preserves_lines(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    log_dir = tmp_path / "logs"
    _set_flow_env(monkeypatch, log_dir, "test-s-flow")

    proc = _state_set_driver(workspace)
    _kill_and_wait(proc, 0.3)

    _assert_json_lines(log_dir / f"flow-{MONTH}.ndjson")


def test_flow_detail_ndjson_sigkill_preserves_lines(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    log_dir = tmp_path / "logs"
    session_id = "test-s-detail"
    _set_flow_env(monkeypatch, log_dir, session_id)

    proc = _hook_event_driver(workspace, session_id)
    _kill_and_wait(proc, 0.3)

    _assert_json_lines(log_dir / session_id / f"flow-detail-{MONTH}.ndjson")


def test_sigkill_timing_jitter_no_partial(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    log_dir = tmp_path / "logs"
    _set_flow_env(monkeypatch, log_dir, "test-s-jitter")

    for index in range(5):
        proc = _state_set_driver(workspace, entries=20)
        _kill_and_wait(proc, random.uniform(0.1, 0.5))
        _assert_json_lines(log_dir / f"flow-{MONTH}.ndjson")
