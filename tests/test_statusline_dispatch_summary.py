import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"


def _run_statusline(workspace: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_dispatch_state(path: Path, task_id: str, heartbeat: datetime) -> None:
    payload = {
        "task_id": task_id,
        "phase": "running",
        "provider": "codex",
        "model": "gpt-test",
        "last_heartbeat": heartbeat.isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_statusline_includes_dispatch_summary_prefix(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    _write_dispatch_state(run_dir / "test-01.json", "test-01", now - timedelta(seconds=30))
    _write_dispatch_state(run_dir / "test-02.json", "test-02", now - timedelta(seconds=90))

    result = _run_statusline(workspace)
    assert result.returncode == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    last_line = lines[-1]

    match = re.search(r"MST 2 run · oldest (\d+)s", last_line)
    assert match, last_line
    oldest = int(match.group(1))
    assert oldest >= 80


def test_statusline_omits_dispatch_summary_when_no_run_files(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".gran-maestro" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    result = _run_statusline(workspace)
    assert result.returncode == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    last_line = lines[-1]

    assert re.search(r"MST \d+ run · oldest \d+s", last_line) is None
