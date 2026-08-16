from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = REPO_ROOT / "hooks" / "mst-session-init.sh"
VALID_SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
VALID_MST_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"


def _workspace_tmp_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "tmp"


def _bridge_path(workspace: Path, ppid: int) -> Path:
    return _workspace_tmp_path(workspace) / f"claude-session-{ppid}.id"


def _state_path(workspace: Path, session_id: str) -> Path:
    return _workspace_tmp_path(workspace) / f"mst-state-{session_id}.json"


def _hook_env(workspace: Path, mst_session_id: str | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(workspace),
        "CLAUDE_CONFIG_DIR": str(workspace / ".claude"),
    }
    env.pop("MST_SESSION_ID", None)
    if mst_session_id is not None:
        env["MST_SESSION_ID"] = mst_session_id
    return env


def _run_hook(
    workspace: Path,
    stdin_payload: str,
    *,
    mst_session_id: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        cwd=workspace,
        input=stdin_payload,
        capture_output=True,
        text=True,
        check=False,
        env=_hook_env(workspace, mst_session_id),
    )


def test_legacy_uuid_is_diagnostic_only_and_does_not_write_bridge(tmp_path):
    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    assert not _bridge_path(tmp_path, owner_ppid).exists()
    assert not (tmp_path / ".gran-maestro").exists()


def test_explicit_canonical_entry_preserves_owner_bridge(tmp_path):
    from scripts.mst_cmds import _common
    from scripts.mst_cmds.state import _resolve_owner_session_id

    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(
        tmp_path,
        stdin_payload,
        mst_session_id=VALID_MST_SESSION_ID,
    )

    assert result.returncode == 0, result.stderr
    bridge_path = _bridge_path(tmp_path, owner_ppid)
    assert bridge_path.read_text(encoding="utf-8").strip() == VALID_SESSION_ID
    assert stat.S_IMODE(bridge_path.stat().st_mode) == 0o644
    previous_base_dir = _common.BASE_DIR
    try:
        _common.set_base_dir(tmp_path / ".gran-maestro")
        assert _resolve_owner_session_id(owner_ppid) == VALID_SESSION_ID
    finally:
        _common.set_base_dir(previous_base_dir)


def test_explicit_canonical_bridge_remains_available_to_state_and_agile_consumers(
    tmp_path,
    monkeypatch,
    capsys,
):
    from scripts._skill_state import _base_snapshot
    from scripts.mst_cmds import _common
    from scripts.mst_cmds.agile import cmd_agile_init

    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )
    result = _run_hook(
        tmp_path,
        stdin_payload,
        mst_session_id=VALID_MST_SESSION_ID,
    )
    assert result.returncode == 0, result.stderr

    for key in (
        "MST_CONTEXT_B64",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_SESSION_ID",
        "MST_SNAPSHOT_SESSION_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MST_STATE_PPID", str(owner_ppid))

    previous_base_dir = _common.BASE_DIR
    try:
        _common.set_base_dir(tmp_path / ".gran-maestro")
        snapshot = _base_snapshot(VALID_MST_SESSION_ID)
        assert snapshot["owner_ppid"] == owner_ppid
        assert snapshot["owner_session_id"] == VALID_SESSION_ID

        assert cmd_agile_init(SimpleNamespace(steering_every=3, json=False)) == 0
        capsys.readouterr()
        agile_session = json.loads(
            (tmp_path / ".gran-maestro" / "agile" / "AGI-001" / "session.json").read_text(
                encoding="utf-8"
            )
        )
        assert agile_session["owner_ppid"] == owner_ppid
        assert agile_session["owner_session_id"] == VALID_SESSION_ID
    finally:
        _common.set_base_dir(previous_base_dir)


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


def test_legacy_uuid_does_not_become_owner_session_id(tmp_path):
    from scripts.mst_cmds import _common
    from scripts.mst_cmds.state import _resolve_owner_session_id

    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    assert not _bridge_path(tmp_path, owner_ppid).exists()
    previous_base_dir = _common.BASE_DIR
    try:
        _common.set_base_dir(tmp_path / ".gran-maestro")
        assert _resolve_owner_session_id(owner_ppid) is None
    finally:
        _common.set_base_dir(previous_base_dir)


def test_legacy_uuid_does_not_write_initial_state(tmp_path):
    owner_ppid = os.getpid()
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(tmp_path, stdin_payload)

    assert result.returncode == 0, result.stderr
    assert not _state_path(tmp_path, str(owner_ppid)).exists()
    assert not (tmp_path / ".gran-maestro").exists()


def test_explicit_canonical_entry_initializes_canonical_state(tmp_path):
    stdin_payload = json.dumps(
        {"session_id": VALID_SESSION_ID, "transcript_path": "/tmp/x.jsonl"}
    )

    result = _run_hook(
        tmp_path,
        stdin_payload,
        mst_session_id=VALID_MST_SESSION_ID,
    )

    assert result.returncode == 0, result.stderr
    state_path = _state_path(tmp_path, VALID_MST_SESSION_ID)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["workflow_active"] is False
    assert payload["current_skill"] == ""
    assert payload["next_action"]["skill"] == ""


def test_session_init_exports_session_id_to_child_sync(tmp_path):
    project_root = tmp_path / "project"
    claude_home = tmp_path / "home"
    (project_root / ".gran-maestro").mkdir(parents=True)
    (project_root / ".gran-maestro" / "config.resolved.json").write_text(
        json.dumps({"gardening": {"auto_archive": {"enabled": True, "session_init_guard_seconds": 0}}}),
        encoding="utf-8",
    )
    (project_root / ".claude-plugin").mkdir()
    (project_root / ".claude-plugin" / "plugin.json").write_text('{"version":"TEST"}\n', encoding="utf-8")
    (project_root / "hooks").mkdir()
    (project_root / "scripts").mkdir()
    fake_mst = project_root / "scripts" / "mst.py"
    fake_mst.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib\n"
        "pathlib.Path('.gran-maestro/tmp/hook-child-session-id.txt').write_text("
        "os.environ.get('MST_SESSION_ID', ''), encoding='utf-8')\n",
        encoding="utf-8",
    )
    cache_target = claude_home / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst" / "TEST"
    marketplace_target = claude_home / ".claude" / "plugins" / "marketplaces" / "gran-maestro"
    cache_target.mkdir(parents=True)
    marketplace_target.mkdir(parents=True)

    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        cwd=project_root,
        input=json.dumps({"mst_session_id": VALID_MST_SESSION_ID, "session_id": VALID_SESSION_ID}),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(claude_home),
            "MST_CLAUDE_HOME": str(claude_home),
            "PLUGIN_ROOT": str(project_root),
            "MST_SESSION_ID": VALID_MST_SESSION_ID,
        },
    )

    assert result.returncode == 0, result.stderr
    env_file = project_root / ".gran-maestro" / "tmp" / "hook-child-session-id.txt"
    for _ in range(50):
        if env_file.exists():
            break
        time.sleep(0.02)
    assert env_file.read_text(encoding="utf-8") == VALID_MST_SESSION_ID
