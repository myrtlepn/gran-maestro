from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LOOP_SCRIPT = REPO_ROOT / "scripts" / "mst-loop.sh"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_empty_queue_normal_exit(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(REPO_ROOT)

    proc = subprocess.run(
        ["bash", str(LOOP_SCRIPT), "--dry-run", "--max-iterations", "1", "--sleep", "0"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "queue empty" in proc.stdout
    assert "[mst-loop] done" in proc.stdout


def test_e2e_3_iterations(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    for index in range(3):
        proc = _run_mst(
            workspace,
            "queue",
            "enqueue",
            "--skill",
            "mst:request",
            "--args",
            f"--plan PLN-{index}",
            "--json",
        )
        assert proc.returncode == 0, proc.stderr

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' "$*" >> "${CLAUDE_ARGS_LOG}"
if [[ "$*" != *"/mst:resume"* ]]; then
    exit 64
fi

MST_PY="${PLUGIN_ROOT}/scripts/mst.py"
PYTHON_BIN="${PYTHON:-python3}"
POPPED="$("$PYTHON_BIN" "$MST_PY" queue pop --json)"
ACTION_ID="$(printf '%s' "$POPPED" | "$PYTHON_BIN" -c 'import json, sys; data=json.load(sys.stdin); print(data.get("id", "") if data else "")')"

if [[ -n "$ACTION_ID" ]]; then
    "$PYTHON_BIN" "$MST_PY" queue complete --id "$ACTION_ID" --result mocked-resume --json >/dev/null
fi
""",
        encoding="utf-8",
    )
    claude.chmod(0o755)

    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(REPO_ROOT)
    env["PYTHON"] = sys.executable
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["CLAUDE_ARGS_LOG"] = str(tmp_path / "claude-args.log")

    proc = subprocess.run(
        ["bash", str(LOOP_SCRIPT), "--max-iterations", "3", "--sleep", "1"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=75,
    )

    assert proc.returncode == 0, proc.stderr
    assert "[mst-loop] iteration 1/3" in proc.stdout
    assert "[mst-loop] iteration 2/3" in proc.stdout
    assert "[mst-loop] iteration 3/3" in proc.stdout
    assert "[mst-loop] done" in proc.stdout
    claude_calls = (tmp_path / "claude-args.log").read_text(encoding="utf-8").splitlines()
    assert len(claude_calls) == 3
    assert all("/mst:resume" in call for call in claude_calls)

    queued = _run_mst(workspace, "queue", "list", "--status", "queued", "--json")
    running = _run_mst(workspace, "queue", "list", "--status", "running", "--json")
    done = _run_mst(workspace, "queue", "list", "--status", "done", "--json")

    assert queued.returncode == 0, queued.stderr
    assert running.returncode == 0, running.stderr
    assert done.returncode == 0, done.stderr
    assert json.loads(queued.stdout) == []
    assert json.loads(running.stdout) == []
    assert len(json.loads(done.stdout)) == 3
