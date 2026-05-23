from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_host_context(workspace: Path, *, host: str, event: str = "", payload: dict | None = None, env: dict | None = None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "host",
            "context",
            "--host",
            host,
            "--event",
            event,
            "--json",
        ],
        cwd=workspace,
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_codex_host_context_uses_supervisor_tick_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)

    context = _run_host_context(
        workspace,
        host="codex",
        event="queue-drain",
        payload={"session_id": "codex-session-1", "permission_mode": "full-auto"},
        env={"MST_SESSION_ID": "MST-REQ-001-20260523T000000000Z-codex0001"},
    )

    assert context["host"] == "codex"
    assert context["event"] == "queue-drain"
    assert context["mst_session_id"] == "MST-REQ-001-20260523T000000000Z-codex0001"
    assert context["host_session_id"] == "codex-session-1"
    assert context["adapter"]["tick_source"] == "supervisor"
    assert context["adapter"]["uses_queue_supervisor"] is True
    assert context["adapter"]["uses_claude_hooks"] is False


def test_claude_host_context_preserves_hook_tick_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)

    context = _run_host_context(
        workspace,
        host="claude",
        event="Stop",
        payload={"session_id": "claude-session-1", "transcript_path": "/tmp/transcript.jsonl"},
        env={"MST_SESSION_ID": "MST-REQ-002-20260523T000000000Z-claude0001"},
    )

    assert context["host"] == "claude"
    assert context["event"] == "Stop"
    assert context["mst_session_id"] == "MST-REQ-002-20260523T000000000Z-claude0001"
    assert context["host_session_id"] == "claude-session-1"
    assert context["transcript_path"] == "/tmp/transcript.jsonl"
    assert context["adapter"]["tick_source"] == "hook"
    assert context["adapter"]["uses_claude_hooks"] is True
    assert context["adapter"]["uses_queue_supervisor"] is False


def test_host_context_keeps_host_session_diagnostic_when_mst_session_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)

    env = {key: value for key, value in os.environ.items() if key != "MST_SESSION_ID"}
    context = _run_host_context(
        workspace,
        host="codex",
        payload={"session_id": "codex-diagnostic-session"},
        env=env,
    )

    assert context["mst_session_id"] is None
    assert context["host_session_id"] == "codex-diagnostic-session"
    assert "diagnostic" not in context
