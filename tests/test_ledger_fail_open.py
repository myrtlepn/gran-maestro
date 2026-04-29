from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_LIB = REPO_ROOT / "hooks" / "lib" / "ledger.bash"
AUTO_CHAIN_HOOK = REPO_ROOT / "hooks" / "mst-auto-chain-context.sh"


def test_ledger_library_write_failure_is_silent_and_successful(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
PROJECT_ROOT=/dev/null
STDIN_RAW={json.dumps(json.dumps({"session_id": "sess-fail"}))}
source {json.dumps(str(LEDGER_LIB))}
emit_ledger_start "SessionStart"
emit_ledger_complete "SessionStart" 0
"""
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_hook_ledger_lock_failure_does_not_change_exit_code_or_stderr(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ledger_dir = workspace / ".gran-maestro"
    (ledger_dir / "tmp").mkdir(parents=True, exist_ok=True)
    (ledger_dir / "hooks-ledger.ndjson.lock").write_text("not a directory\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(AUTO_CHAIN_HOOK)],
        cwd=workspace,
        input=json.dumps({"session_id": "sess-hook-fail", "transcript_path": "missing.jsonl"}),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(workspace / "home"),
            "CLAUDE_CONFIG_DIR": str(workspace / "home" / ".claude"),
            "MST_STATE_PPID": str(os.getpid()),
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
