from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
STATUSLINE = REPO_ROOT / "scripts" / "mst-statusline.sh"
FAST_PRE_TOOL = REPO_ROOT / "hooks" / "lib" / "pre_tool_use_fast.py"
ROOT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
OTHER_SESSION_ID = "MST-AGI-030-20260503T130813382Z-z9y8x7w6"
LEGACY_PPID = "424242"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
    ):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hashes_under(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        str(child.relative_to(path)): hashlib.sha256(child.read_bytes()).hexdigest()
        for child in sorted(path.rglob("*"))
        if child.is_file()
    }


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=_clean_env(env),
        check=False,
        timeout=30,
    )


def _run_statusline(workspace: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STATUSLINE)],
        cwd=workspace,
        input="{}\n",
        capture_output=True,
        text=True,
        env=_clean_env(env),
        check=False,
        timeout=30,
    )


def _run_stop_hook(workspace: Path, payload: dict, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    home = workspace / "home"
    home.mkdir(parents=True, exist_ok=True)
    hook_env = {
        "HOME": str(home),
        "MST_CLAUDE_HOME": str(home),
        "MST_STOP_HOOK_CLEANUP_DISABLE": "1",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(STOP_HOOK)],
        cwd=workspace,
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        env=_clean_env(hook_env),
        check=False,
        timeout=30,
    )


def _run_fast_pre_tool(workspace: Path, payload: dict, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FAST_PRE_TOOL), str(workspace)],
        cwd=workspace,
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        env=_clean_env(env),
        check=False,
        timeout=30,
    )


def _stop_decision(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_statusline_does_not_select_legacy_ppid_or_default_snapshots() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "state" / LEGACY_PPID / "snapshot.json",
            {"sessionId": "legacy-ppid-session", "currentSkill": "legacy:ppid", "currentStep": 1, "totalSteps": 3},
        )
        _write_json(
            workspace / ".gran-maestro" / "state" / "default" / "snapshot.json",
            {"sessionId": "legacy-default-session", "currentSkill": "legacy:default", "currentStep": 1, "totalSteps": 3},
        )

        result = _run_statusline(workspace, env={"MST_STATE_PPID": LEGACY_PPID})

        assert result.returncode == 0, result.stderr
        assert "legacy:ppid" not in result.stdout
        assert "legacy:default" not in result.stdout
        assert "MST idle" in result.stdout


def test_pre_tool_fast_path_ignores_mst_state_ppid_for_schedule_wakeup() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "tmp" / f"mst-state-{LEGACY_PPID}.json",
            {"workflow_active": True, "current_skill": "mst:request"},
        )

        result = _run_fast_pre_tool(
            workspace,
            {"tool_name": "ScheduleWakeup", "tool_input": {}},
            env={"MST_STATE_PPID": LEGACY_PPID},
        )

        assert result.returncode == 0, result.stderr
        assert "ScheduleWakeup is blocked" not in result.stderr


def _t02_alias_only_snapshot_payload_blocks_mutation_without_repair() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        _write_json(
            snapshot_path,
            {"sessionId": ROOT_SESSION_ID, "currentSkill": "legacy:alias-only", "currentStep": 1, "totalSteps": 2},
        )
        before = _hashes_under(workspace / ".gran-maestro")

        result = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env={"MST_SESSION_ID": ROOT_SESSION_ID},
        )

        assert result.returncode != 0
        assert _hashes_under(workspace / ".gran-maestro") == before
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "mst_session_id" not in payload


def test_owner_ppid_only_workflow_state_is_diagnostic_without_canonical_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before_state = _hashes_under(workspace / ".gran-maestro" / "state")

        wrapper = subprocess.run(
            [
                "bash",
                "-c",
                """
set -euo pipefail
mkdir -p .gran-maestro/requests/REQ-PPID
printf '{"id":"REQ-PPID","status":"active","owner_ppid":%s}\n' "$$" > .gran-maestro/requests/REQ-PPID/request.json
MST_SESSION_ID="$1" MST_STOP_HOOK_CLEANUP_DISABLE=1 HOME="$2/home" MST_CLAUDE_HOME="$2/home" bash "$3" <<JSON
{"hook_event_name":"Stop","mst_session_id":"$1","session_id":"claude-diagnostic"}
JSON
""",
                "_",
                ROOT_SESSION_ID,
                str(workspace),
                str(STOP_HOOK),
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
            timeout=30,
        )

        decision = _stop_decision(wrapper)
        assert decision["decision"] == "approve"
        assert "active workflow session detected" not in decision["reason"]
        assert "owner_ppid-only workflow state ignored" in wrapper.stderr
        assert _hashes_under(workspace / ".gran-maestro" / "state") == before_state
        assert not (workspace / ".gran-maestro" / "sessions" / ROOT_SESSION_ID).exists()


def test_owner_session_id_only_active_resource_does_not_select_workflow() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "requests" / "REQ-OWNER" / "request.json",
            {"id": "REQ-OWNER", "status": "active", "owner_session_id": ROOT_SESSION_ID},
        )

        result = _run_stop_hook(
            workspace,
            {"hook_event_name": "Stop", "mst_session_id": ROOT_SESSION_ID, "session_id": "claude-diagnostic"},
            env={"MST_SESSION_ID": ROOT_SESSION_ID},
        )

        decision = _stop_decision(result)
        assert decision["decision"] == "approve"
        assert "active workflow session detected" not in decision["reason"]
        assert not (workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID).exists()


def _write_recover_agile_fixture(workspace: Path, mst_session_id: str | None, owner_session_id: str) -> None:
    agi_dir = workspace / ".gran-maestro" / "agile" / "AGI-030"
    payload = {
        "id": "AGI-030",
        "status": "executing",
        "current_sprint": 1,
        "owner_ppid": 12345,
        "owner_session_id": owner_session_id,
    }
    if mst_session_id is not None:
        payload["mst_session_id"] = mst_session_id
    _write_json(agi_dir / "session.json", payload)
    _write_json(agi_dir / "sprints" / "S01" / "result.json", {"status": "success", "target_dod": "DOD-003"})


def test_state_recover_ignores_owner_session_id_mismatch_diagnostically() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_recover_agile_fixture(workspace, ROOT_SESSION_ID, OTHER_SESSION_ID)

        result = _run_mst(workspace, "state", "recover", "AGI-030", env={"MST_SESSION_ID": ROOT_SESSION_ID})

        assert result.returncode == 0, result.stderr
        assert "owner_session_id ignored" in result.stderr
        snapshot = json.loads(
            (workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json").read_text(encoding="utf-8")
        )
        assert snapshot["mst_session_id"] == ROOT_SESSION_ID
        assert snapshot["root_mst_id"] == "AGI-030"
        assert snapshot.get("read_only") is not True
        assert "owner_session_id" not in snapshot


def test_state_recover_mst_session_id_mismatch_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_recover_agile_fixture(workspace, OTHER_SESSION_ID, ROOT_SESSION_ID)
        before = _hashes_under(workspace / ".gran-maestro" / "state")

        result = _run_mst(workspace, "state", "recover", "AGI-030", env={"MST_SESSION_ID": ROOT_SESSION_ID})

        assert result.returncode != 0
        assert f"mst_session_id mismatch: env={ROOT_SESSION_ID} payload={OTHER_SESSION_ID}" in result.stderr
        assert _hashes_under(workspace / ".gran-maestro" / "state") == before


def test_state_recover_missing_mst_session_id_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_recover_agile_fixture(workspace, None, ROOT_SESSION_ID)
        before = _hashes_under(workspace / ".gran-maestro" / "state")

        result = _run_mst(workspace, "state", "recover", "AGI-030", env={"MST_SESSION_ID": ROOT_SESSION_ID})

        assert result.returncode != 0
        assert "missing mst_session_id in durable session" in result.stderr
        assert _hashes_under(workspace / ".gran-maestro" / "state") == before


def main() -> int:
    tests = [
        test_statusline_does_not_select_legacy_ppid_or_default_snapshots,
        test_pre_tool_fast_path_ignores_mst_state_ppid_for_schedule_wakeup,
        test_owner_ppid_only_workflow_state_is_diagnostic_without_canonical_mutation,
        test_owner_session_id_only_active_resource_does_not_select_workflow,
        test_state_recover_ignores_owner_session_id_mismatch_diagnostically,
        test_state_recover_mst_session_id_mismatch_fails_without_mutation,
        test_state_recover_missing_mst_session_id_fails_without_mutation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
