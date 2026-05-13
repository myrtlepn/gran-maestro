"""REQ-744/T02: stop-hook /mst:resume handoff into resolver enqueue."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
RESUME_COMMAND = "/mst:resume --wakeup-hint stop-recover"


def _session_id() -> str:
    return "MST-AGI-036-20260513T120000000Z-resumee2e"


def _init_project_root(tmp_path: Path) -> Path:
    (tmp_path / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (tmp_path / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".gran-maestro" / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_snapshot(project_root: Path, session_id: str, payload: dict) -> None:
    snapshot_path = project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_hook(project_root: Path, payload: dict) -> subprocess.CompletedProcess:
    session_id = payload.get("mst_session_id")
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(project_root),
    }
    if isinstance(session_id, str) and session_id.strip():
        env["MST_SESSION_ID"] = session_id
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst(
    project_root: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=project_root,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    return json.loads(result.stdout)


def test_stop_hook_to_resolver_e2e(tmp_path):
    project_root = _init_project_root(tmp_path)
    session_id = _session_id()
    _write_snapshot(
        project_root,
        session_id,
        {
            "sessionId": session_id,
            "currentSkill": "request",
            "currentStep": 4,
            "totalSteps": 4,
            "status": "active",
            "returnTo": {"skill": "plan", "step": 4},
        },
    )

    stop_result = _run_hook(
        project_root,
        {
            "mst_session_id": session_id,
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": "request sub-flow is complete.",
        },
    )

    stop_payload = _stdout_json(stop_result)
    assert stop_payload["decision"] == "block"
    assert "[RETURN-TO] Sub-skill returned with return_to=plan/4" in stop_payload["reason"]
    assert RESUME_COMMAND in stop_payload["reason"]

    resolved = _run_mst(
        project_root,
        "resolve-next-action",
        "--wakeup-hint",
        "stop-recover",
        "--enqueue",
        "--json",
        env={"CLAUDE_SESSION_ID": session_id},
    )
    assert resolved.returncode == 0, resolved.stderr
    assert json.loads(resolved.stdout) == {
        "command": "/mst:plan (continue from step 4)",
        "source": "wakeup-hint:stop-recover",
    }

    peek = _run_mst(project_root, "queue", "peek", "--json")
    assert peek.returncode == 0, peek.stderr
    queued = json.loads(peek.stdout)
    assert queued["skill"] == "mst:plan"
    assert queued["args"] == "(continue from step 4)"
    assert queued["source_skill"] == "wakeup-hint"
    assert queued["source_id"] == "stop-recover"
    assert queued["status"] == "queued"
