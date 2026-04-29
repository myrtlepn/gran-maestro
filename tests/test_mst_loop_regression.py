from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
LOOP_SCRIPT = REPO_ROOT / "scripts" / "mst-loop.sh"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _install_fake_claude(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake = bin_dir / "claude"
    fake.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

case "$*" in
  *"/mst:resume"*) ;;
  *) echo "unexpected claude invocation: $*" >&2; exit 64 ;;
esac

ENTRY_JSON=$(python3 "$PLUGIN_ROOT/scripts/mst.py" queue pop --json)
ACTION_ID=$(printf '%s' "$ENTRY_JSON" | python3 -c 'import json, sys; data=json.load(sys.stdin); print(data.get("id", "") if isinstance(data, dict) else "")')

if [[ -n "$ACTION_ID" ]]; then
  python3 "$PLUGIN_ROOT/scripts/mst.py" queue complete --id "$ACTION_ID" --result ok --json >/dev/null
fi
""",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_enqueue_loop_complete_five_e2e_scenarios(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    _install_fake_claude(fake_bin)

    scenarios = [
        ("mst:request", "--plan PLN-572 -a", True),
        ("mst:approve", "-a REQ-743", True),
        ("mst:agile", "--resume AGI-010 -a", True),
        ("mst:review", "REQ-743", False),
        ("mst:accept", "REQ-743", False),
    ]
    expected_ids = []

    for skill, args, auto in scenarios:
        proc = _run_mst(
            workspace,
            "queue",
            "enqueue",
            "--skill",
            skill,
            "--args",
            args,
            "--auto",
            str(auto).lower(),
            "--json",
        )
        assert proc.returncode == 0, proc.stderr
        expected_ids.append(json.loads(proc.stdout)["id"])

    env = os.environ.copy()
    env["PLUGIN_ROOT"] = str(REPO_ROOT)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    loop = subprocess.run(
        ["bash", str(LOOP_SCRIPT), "--max-iterations", "10", "--sleep", "0"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert loop.returncode == 0, loop.stderr
    assert "[mst-loop] done" in loop.stdout

    done = _run_mst(workspace, "queue", "list", "--status", "done", "--json")
    queued = _run_mst(workspace, "queue", "list", "--status", "queued", "--json")
    running = _run_mst(workspace, "queue", "list", "--status", "running", "--json")

    assert done.returncode == 0, done.stderr
    assert queued.returncode == 0, queued.stderr
    assert running.returncode == 0, running.stderr
    done_items = json.loads(done.stdout)
    assert [item["id"] for item in done_items] == expected_ids
    assert all(item["result"] == "ok" for item in done_items)
    assert json.loads(queued.stdout) == []
    assert json.loads(running.stdout) == []
