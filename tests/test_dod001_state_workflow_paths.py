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
ROOT_SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
STALE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LEGACY_PPID = "919191"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _init_workspace(path: Path) -> None:
    (path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_SESSION_ID"] = ROOT_SESSION_ID
    env["MST_STATE_PPID"] = LEGACY_PPID
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_workflow_and_snapshot_paths_use_mst_session_id_only() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)

        workflow = _run_mst(
            workspace,
            "state",
            "set-workflow",
            "--active",
            "true",
            "--skill",
            "mst:request",
            "--req",
            "REQ-804",
            "--next-skill",
            "mst:approve",
            "--next-source",
            "REQ-804",
            "--source-skill",
            "mst:request",
            "--auto",
            "true",
        )
        assert workflow.returncode == 0, workflow.stderr

        workflow_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{ROOT_SESSION_ID}.json"
        ppid_path = workspace / ".gran-maestro" / "tmp" / f"mst-state-{LEGACY_PPID}.json"
        assert workflow_path.exists()
        assert not ppid_path.exists()
        workflow_payload = json.loads(workflow_path.read_text(encoding="utf-8"))
        assert workflow_payload["mst_session_id"] == ROOT_SESSION_ID
        assert workflow_payload["legacy_diagnostics"]["MST_STATE_PPID"] == LEGACY_PPID

        snapshot = _run_mst(
            workspace,
            "state",
            "set",
            "--skill",
            "mst:request",
            "--step",
            "1",
            "--total",
            "3",
        )
        assert snapshot.returncode == 0, snapshot.stderr

        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        assert snapshot_path.exists()
        snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot_payload["mst_session_id"] == ROOT_SESSION_ID
        assert snapshot_payload["sessionId"] == ROOT_SESSION_ID
        canonical_set = {workflow_payload["mst_session_id"], snapshot_payload["mst_session_id"]}
        assert canonical_set == {ROOT_SESSION_ID}
        assert LEGACY_PPID not in canonical_set


def test_recover_stale_owner_fails_without_snapshot_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        agi_dir = workspace / ".gran-maestro" / "agile" / "AGI-030"
        agi_dir.mkdir(parents=True, exist_ok=True)
        session_path = agi_dir / "session.json"
        session_path.write_text(
            json.dumps(
                {
                    "id": "AGI-030",
                    "status": "active",
                    "current_sprint": "S2",
                    "owner_session_id": STALE_SESSION_ID,
                    "owner_ppid": 12345,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = _files(workspace)

        result = _run_mst(workspace, "state", "recover", "AGI-030")

        assert result.returncode != 0
        assert _files(workspace) == before
        assert "mst_session_id mismatch" in f"{result.stdout}\n{result.stderr}"


def test_resume_stale_snapshot_fails_without_payload_mutation() -> None:
    with _workspace() as raw_workspace:
        workspace = Path(raw_workspace)
        _init_workspace(workspace)
        snapshot_path = workspace / ".gran-maestro" / "state" / ROOT_SESSION_ID / "snapshot.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(
                {
                    "sessionId": ROOT_SESSION_ID,
                    "mst_session_id": STALE_SESSION_ID,
                    "currentSkill": "mst:request",
                    "currentStep": 1,
                    "totalSteps": 3,
                    "status": "active",
                    "paused": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before_hash = _sha256(snapshot_path)

        result = _run_mst(workspace, "state", "resume-paused", "--session-id", ROOT_SESSION_ID)

        assert result.returncode != 0
        assert _sha256(snapshot_path) == before_hash
        assert "snapshot mst_session_id mismatch" in f"{result.stdout}\n{result.stderr}"


def main() -> int:
    tests = [
        test_workflow_and_snapshot_paths_use_mst_session_id_only,
        test_recover_stale_owner_fails_without_snapshot_mutation,
        test_resume_stale_snapshot_fails_without_payload_mutation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
