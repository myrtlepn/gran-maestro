import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "mst-session-init.sh"
VALID_SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"


def _workspace_tmp_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "tmp"


def _bridge_path(workspace: Path, ppid: int) -> Path:
    return _workspace_tmp_path(workspace) / f"claude-session-{ppid}.id"


def _state_path(workspace: Path, ppid: int) -> Path:
    return _workspace_tmp_path(workspace) / f"mst-state-{ppid}.json"


def _hook_env(workspace: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(workspace),
        "CLAUDE_CONFIG_DIR": str(workspace / ".claude"),
    }


def _run_hook(workspace: Path, stdin_payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        cwd=workspace,
        input=stdin_payload,
        capture_output=True,
        text=True,
        check=False,
        env=_hook_env(workspace),
    )


def test_write_bridge_on_valid_uuid(tmp_path):
    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    bridge_path = _bridge_path(tmp_path, owner_ppid)
    assert bridge_path.exists()
    assert bridge_path.read_text(encoding="utf-8").strip() == VALID_SESSION_ID
    assert stat.S_IMODE(bridge_path.stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "stdin_payload",
    [
        json.dumps({"session_id": "not-a-uuid", "transcript_path": ""}),
        json.dumps({"session_id": "123e4567-e89b-42d3-7456-426614174000", "transcript_path": ""}),
        json.dumps({"session_id": "", "transcript_path": ""}),
    ],
)
def test_skip_on_invalid_uuid(tmp_path, stdin_payload):
    owner_ppid = os.getpid()

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    assert not _bridge_path(tmp_path, owner_ppid).exists()


@pytest.mark.parametrize("stdin_payload", ["", "not json"])
def test_skip_on_empty_or_non_json_stdin(tmp_path, stdin_payload):
    owner_ppid = os.getpid()

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    assert not _bridge_path(tmp_path, owner_ppid).exists()


def test_roundtrip_with_resolve_owner_session_id(tmp_path):
    from scripts.mst_cmds import _common
    from scripts.mst_cmds.state import _resolve_owner_session_id

    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    previous_base_dir = _common.BASE_DIR
    try:
        _common.set_base_dir(tmp_path / ".gran-maestro")
        assert _resolve_owner_session_id(owner_ppid) == VALID_SESSION_ID
    finally:
        _common.set_base_dir(previous_base_dir)


def test_write_initial_state_preserved(tmp_path):
    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    state_path = _state_path(tmp_path, owner_ppid)
    assert state_path.exists()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["workflow_active"] is False
    assert payload["current_skill"] == ""
    assert payload["next_action"]["skill"] == ""
