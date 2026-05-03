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
ROOT_SESSION_ID = "MST-AGI-030-20260503T130813382Z-k7f3q9x2"
STALE_SESSION_ID = "MST-REQ-805-20260503T131853000Z-r4n8vd1c"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_SESSION_ID"] = ROOT_SESSION_ID
    for key in ("MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW", "MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=_env(env),
        check=False,
        timeout=30,
    )


def _files(workspace: Path) -> set[str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return set()
    return {str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()}


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    result: dict[str, str] = {}
    if not base.exists():
        return result
    for path in sorted(base.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _register_child(workspace: Path, task_id: str, env: dict[str, str] | None) -> subprocess.CompletedProcess[str]:
    return _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )


def test_stale_dispatch_payload_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

        result = _register_child(
            workspace,
            "stale-dispatch-payload",
            {"MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID})},
        )

        assert result.returncode != 0
        assert _files(workspace) == before
        assert "mismatch" in f"{result.stdout}\n{result.stderr}"


def test_stale_dispatch_heartbeat_payload_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        run_path = workspace / ".gran-maestro" / "run" / "stale-heartbeat.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(
            json.dumps(
                {
                    "task_id": "stale-heartbeat",
                    "mst_session_id": ROOT_SESSION_ID,
                    "phase": "running",
                    "last_heartbeat": "2026-05-03T00:00:00+00:00",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = _hashes(workspace)

        result = _run_mst(
            workspace,
            "dispatch",
            "heartbeat",
            "--task-id",
            "stale-heartbeat",
            "--phase",
            "running",
            env={"MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID})},
        )

        assert result.returncode != 0
        assert _hashes(workspace) == before
        assert "mismatch" in f"{result.stdout}\n{result.stderr}"


def test_stale_state_path_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        stale_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{ROOT_SESSION_ID}.json"
        stale_path.write_text(
            json.dumps({"mst_session_id": STALE_SESSION_ID, "workflow_active": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        before = _hashes(workspace)

        result = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--next-skill",
            "mst:approve",
        )

        assert result.returncode != 0
        assert _hashes(workspace) == before
        assert "workflow mst_session_id mismatch" in f"{result.stdout}\n{result.stderr}"


def test_stale_ledger_event_context_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        before = _files(workspace)

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
            env={"MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID})},
        )

        assert result.returncode != 0
        assert _files(workspace) == before
        assert "mismatch" in f"{result.stdout}\n{result.stderr}"


def test_stale_snapshot_payload_fails_without_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps({"sessionId": ROOT_SESSION_ID, "mst_session_id": STALE_SESSION_ID}, indent=2) + "\n",
            encoding="utf-8",
        )
        before = _hashes(workspace)

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
        )

        assert result.returncode != 0
        assert _hashes(workspace) == before
        assert "snapshot mst_session_id mismatch" in f"{result.stdout}\n{result.stderr}"


def main() -> int:
    tests = [
        test_stale_dispatch_payload_fails_without_mutation,
        test_stale_dispatch_heartbeat_payload_fails_without_mutation,
        test_stale_state_path_fails_without_mutation,
        test_stale_ledger_event_context_fails_without_mutation,
        test_stale_snapshot_payload_fails_without_mutation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
