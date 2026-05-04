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


def _hashes(workspace: Path) -> dict[str, str]:
    base = workspace / ".gran-maestro"
    if not base.exists():
        return {}
    return {
        str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _combined(*results: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(f"{result.stdout}\n{result.stderr}" for result in results)


def test_ppid_only_state_boundaries_fail_without_selecting_legacy_paths() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "state" / LEGACY_PPID / "snapshot.json",
            {"sessionId": "legacy-ppid-session", "currentSkill": "legacy:ppid", "currentStep": 1, "totalSteps": 2},
        )
        _write_json(
            workspace / ".gran-maestro" / "state" / "default" / "snapshot.json",
            {"sessionId": "legacy-default-session", "currentSkill": "legacy:default", "currentStep": 1, "totalSteps": 2},
        )
        before = _hashes(workspace)

        env = {"MST_STATE_PPID": LEGACY_PPID}
        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--next-skill",
            "mst:approve",
            env=env,
        )
        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=env,
        )
        read = _run_mst(workspace, "state", "get", env=env)

        assert workflow.returncode != 0
        assert snapshot.returncode != 0
        assert read.returncode != 0
        assert _hashes(workspace) == before
        combined = _combined(workflow, snapshot, read)
        assert "missing MST_SESSION_ID" in combined
        assert "legacy:ppid" not in combined
        assert "legacy:default" not in combined
        assert not (workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID).exists()


def test_env_context_mismatch_is_no_mutation_for_state_and_workflow() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        _write_json(
            workspace / ".gran-maestro" / "requests" / "REQ-806" / "request.json",
            {"id": "REQ-806", "status": "active"},
        )
        before = _hashes(workspace)
        mismatch_env = {
            "MST_SESSION_ID": ROOT_SESSION_ID,
            "MST_CONTEXT_JSON": json.dumps({"mst_session_id": STALE_SESSION_ID}),
            "MST_STATE_PPID": LEGACY_PPID,
        }

        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--req",
            "REQ-806",
            env=mismatch_env,
        )
        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "1",
            env=mismatch_env,
        )

        assert workflow.returncode != 0
        assert snapshot.returncode != 0
        assert _hashes(workspace) == before
        combined = _combined(workflow, snapshot)
        assert "mismatch" in combined
        assert not (workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID).exists()
        assert not (workspace / ".gran-maestro" / "tmp" / f"mst-state-{ROOT_SESSION_ID}.json").exists()


def main() -> int:
    tests = [
        test_ppid_only_state_boundaries_fail_without_selecting_legacy_paths,
        test_env_context_mismatch_is_no_mutation_for_state_and_workflow,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
