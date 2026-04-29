from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = {
    "SessionStart": REPO_ROOT / "hooks" / "mst-session-init.sh",
    "PreToolUse": REPO_ROOT / "hooks" / "mst-pre-tool-use.sh",
    "Stop": REPO_ROOT / "hooks" / "mst-stop-hook.sh",
    "UserPromptSubmit": REPO_ROOT / "hooks" / "mst-auto-chain-context.sh",
}


def _prepare_workspace(workspace: Path) -> None:
    (workspace / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    for name in ("scripts", "templates"):
        target = workspace / name
        if not target.exists():
            target.symlink_to(REPO_ROOT / name, target_is_directory=True)


def _run_hook(workspace: Path, hook_event: str, payload: dict) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "HOME": str(workspace / "home"),
        "CLAUDE_CONFIG_DIR": str(workspace / "home" / ".claude"),
        "MST_STATE_PPID": str(os.getpid()),
    }
    return subprocess.run(
        ["bash", str(HOOKS[hook_event])],
        cwd=workspace,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def _read_ledger(workspace: Path) -> list[dict]:
    ledger = workspace / ".gran-maestro" / "hooks-ledger.ndjson"
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]


def test_each_hook_writes_start_and_complete_ledger_records(tmp_path: Path) -> None:
    cases = {
        "SessionStart": {"session_id": "123e4567-e89b-12d3-a456-426614174000"},
        "PreToolUse": {"session_id": "sess-pre", "tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        "Stop": {"session_id": "sess-stop"},
        "UserPromptSubmit": {"session_id": "sess-user", "transcript_path": str(tmp_path / "missing.jsonl")},
    }

    for hook_event, payload in cases.items():
        workspace = tmp_path / hook_event
        _prepare_workspace(workspace)

        result = _run_hook(workspace, hook_event, payload)

        assert result.returncode == 0, f"{hook_event} stderr:\n{result.stderr}"
        records = _read_ledger(workspace)
        assert [record["phase"] for record in records] == ["start", "complete"]
        assert {record["hook_event"] for record in records} == {hook_event}
        assert records[0]["exit_code"] is None
        assert records[1]["exit_code"] == 0
        assert records[0]["payload_digest"] == records[1]["payload_digest"]
        assert records[0]["session_id"] == payload["session_id"]
        assert records[0]["invocation_source"] == "settings_local"
