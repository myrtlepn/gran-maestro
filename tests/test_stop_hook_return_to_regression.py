"""REQ-744/T02: stop-hook return_to reasons route through /mst:resume."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


def _session_id() -> str:
    return str(uuid.uuid4())


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


def _write_state_for_current_ppid(project_root: Path, payload: dict) -> None:
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _run_hook(project_root: Path, payload: dict) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(project_root),
    }
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False),
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _stdout_json(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, (
        "stop hook must exit 0\n"
        f"stdout:\n{result.stdout!r}\n"
        f"stderr:\n{result.stderr!r}"
    )
    non_empty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(non_empty_lines) == 1, (
        "stop hook stdout must contain exactly one non-empty JSON decision line\n"
        f"stdout:\n{result.stdout!r}\n"
        f"stderr:\n{result.stderr!r}"
    )
    return json.loads(non_empty_lines[0])


RESUME_COMMAND = "/mst:resume --wakeup-hint stop-recover"


def test_snapshot_return_to_resume_pattern(tmp_path):
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

    result = _run_hook(
        project_root,
        {
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": "request sub-flow is complete.",
        },
    )

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "[RETURN-TO] snapshot return_to=plan/4" in payload["reason"]
    assert RESUME_COMMAND in payload["reason"]
    assert "SNAPSHOT_RETURN_TO_SKILL=plan" in payload["reason"]
    assert "SNAPSHOT_RETURN_TO_STEP=4" in payload["reason"]
    assert "continue from step" not in payload["reason"]
    assert "return to mst:plan" not in payload["reason"]


def test_subskill_return_to_resume_pattern(tmp_path):
    project_root = _init_project_root(tmp_path)
    session_id = _session_id()
    _write_state_for_current_ppid(
        project_root,
        {
            "workflow_active": True,
            "current_skill": "mst:request",
            "active_req": "",
            "iteration": 0,
            "agile_loop_active": False,
            "next_action": None,
        },
    )

    result = _run_hook(
        project_root,
        {
            "session_id": session_id,
            "last_assistant_message": "Sub-skill complete return_to=request/2",
        },
    )

    payload = _stdout_json(result)
    assert payload["decision"] == "block"
    assert "[RETURN-TO] Sub-skill returned with return_to=request/2" in payload["reason"]
    assert RESUME_COMMAND in payload["reason"]
    assert "RETURN_TO_SKILL=request" in payload["reason"]
    assert "RETURN_TO_STEP=2" in payload["reason"]
    assert "continue from step" not in payload["reason"]
    assert "return to mst:request" not in payload["reason"]
