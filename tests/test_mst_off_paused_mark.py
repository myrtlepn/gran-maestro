"""REQ-693/T01: mst:on/off paused snapshot marker tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
OFF_SKILL = REPO_ROOT / "skills" / "off" / "SKILL.md"
ON_SKILL = REPO_ROOT / "skills" / "on" / "SKILL.md"
SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
ISO_8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True)
    return workspace


def _snapshot_path(workspace: Path, session_id: str = SESSION_ID) -> Path:
    return workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"


def _write_snapshot(workspace: Path, payload: dict, session_id: str = SESSION_ID) -> Path:
    path = _snapshot_path(workspace, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_snapshot(workspace: Path, session_id: str = SESSION_ID) -> dict:
    return json.loads(_snapshot_path(workspace, session_id).read_text(encoding="utf-8"))


def _run_state(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("MST_STATE_PPID", None)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "state", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_mst_off_marks_paused():
    content = OFF_SKILL.read_text(encoding="utf-8")

    assert "state mark-paused --session-id \"$SESSION_ID\"" in content
    assert "state paused-count --session-id \"$SESSION_ID\"" in content
    assert "진행 중 체인 ${PAUSED_COUNT}건 일시 정지" in content
    assert "/mst:on" in content


def test_mst_on_resumes_paused():
    content = ON_SKILL.read_text(encoding="utf-8")

    assert "state paused-count --session-id \"$SESSION_ID\"" in content
    assert "paused 체인 ${PAUSED_COUNT}건 발견" in content
    assert "AUTO_MODE=true" in content
    assert "state resume-paused --session-id \"$SESSION_ID\"" in content

    start = content.index("<!-- paused-resume:start -->")
    end = content.index("<!-- paused-resume:end -->")
    paused_section = content[start:end]
    assert "AskUserQuestion" not in paused_section


def test_state_helper_commands(tmp_path):
    workspace = _workspace(tmp_path)
    _write_snapshot(
        workspace,
        {
            "sessionId": SESSION_ID,
            "currentSkill": "mst:agile",
            "currentStep": 1,
            "totalSteps": 3,
            "status": "active",
        },
    )

    mark = _run_state(workspace, "mark-paused", "--session-id", SESSION_ID)

    assert mark.returncode == 0, mark.stderr
    marked = _read_snapshot(workspace)
    assert marked["paused"] is True
    assert ISO_8601_UTC_RE.match(marked["paused_at"])
    assert ISO_8601_UTC_RE.match(marked["updatedAt"])

    paused_count = _run_state(workspace, "paused-count", "--session-id", SESSION_ID)

    assert paused_count.returncode == 0, paused_count.stderr
    assert paused_count.stdout.strip() == "1"

    resume = _run_state(workspace, "resume-paused", "--session-id", SESSION_ID)

    assert resume.returncode == 0, resume.stderr
    resumed = _read_snapshot(workspace)
    assert resumed["paused"] is False
    assert ISO_8601_UTC_RE.match(resumed["resumed_at"])
    assert resumed["paused_at"] == marked["paused_at"]

    resumed_count = _run_state(workspace, "paused-count", "--session-id", SESSION_ID)

    assert resumed_count.returncode == 0, resumed_count.stderr
    assert resumed_count.stdout.strip() == "0"
