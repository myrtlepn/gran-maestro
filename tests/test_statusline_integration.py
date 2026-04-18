import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_statusline(workspace: Path, payload: str = "{}") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _last_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines[-1]


def _iso_ago(**kwargs) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


def _snapshot_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "state" / "default" / "snapshot.json"


def _write_snapshot(workspace: Path, payload: dict) -> Path:
    path = _snapshot_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_state(workspace: Path, payload: dict) -> None:
    state_dir = workspace / ".gran-maestro" / "tmp"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"mst-state-{os.getpid()}.json"
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_run(
    workspace: Path,
    task_id: str,
    provider: str,
    heartbeat: str,
    *,
    skill: str = "",
) -> Path:
    path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "pid": 12345,
        "phase": "running",
        "provider": provider,
        "model": "test-model",
        "worktree_dir": str(workspace),
        "last_heartbeat": heartbeat,
    }
    if skill:
        payload["skill"] = skill
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": _iso_ago(minutes=4),
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Skill",
                    "input": {"skill": "mst:transcript", "args": "REQ-668"},
                }
            ]
        },
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


def test_end_to_end_chain(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=0),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
            ],
        },
    )
    _write_run(
        workspace,
        "REQ-700-T01",
        "gemini",
        _iso_ago(seconds=30),
        skill="mst:gemini",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(
        r"plan\(8m\) > request\(15m\) > codex\([0-9]+s\) > "
        r"\[gemini:REQ-700-T01\(3[0-9]s\)\]",
        last_line,
    ), last_line


@pytest.mark.parametrize(
    "scenario",
    [
        "missing_snapshot_state_fallback",
        "legacy_snapshot_missing_entered_at",
        "missing_run_dir_snapshot_only",
        "dispatch_register_without_skill",
        "transcript_fallback_without_state_snapshot_or_dispatch",
    ],
)
def test_regression_scenarios(tmp_path, scenario):
    workspace = tmp_path / "workspace"
    payload = "{}"

    if scenario == "missing_snapshot_state_fallback":
        _write_state(
            workspace,
            {"current_skill": "mst:current", "updated_at": _iso_ago(minutes=5)},
        )
        expected = r"current\(5m\)"

    elif scenario == "legacy_snapshot_missing_entered_at":
        _write_snapshot(
            workspace,
            {
                "currentSkill": "codex",
                "enteredAt": _iso_ago(seconds=1),
                "skillStack": [{"skill": "legacy", "step": 1}],
            },
        )
        expected = r"legacy > codex\([0-9]+s\)"

    elif scenario == "missing_run_dir_snapshot_only":
        _write_snapshot(
            workspace,
            {
                "currentSkill": "request",
                "enteredAt": _iso_ago(minutes=2),
                "skillStack": [
                    {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=8)},
                ],
            },
        )
        expected = r"plan\(8m\) > request\(2m\)"

    elif scenario == "dispatch_register_without_skill":
        (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
        register = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--provider",
            "gemini",
            "--task-id",
            "REQ-700-T01",
            "--pid",
            "12345",
            "--model",
            "test-model",
            "--worktree-dir",
            str(workspace),
        )
        assert register.returncode == 0, register.stderr
        run_path = workspace / ".gran-maestro" / "run" / "REQ-700-T01.json"
        run_payload = json.loads(run_path.read_text(encoding="utf-8"))
        assert run_payload.get("skill", "") == ""
        run_payload["last_heartbeat"] = _iso_ago(seconds=30)
        run_path.write_text(json.dumps(run_payload, ensure_ascii=False), encoding="utf-8")
        expected = r"\[gemini:REQ-700-T01\(3[0-9]s\)\]"

    elif scenario == "transcript_fallback_without_state_snapshot_or_dispatch":
        transcript_path = workspace / "session.jsonl"
        _write_transcript(transcript_path)
        payload = json.dumps({"transcript_path": str(transcript_path)})
        expected = r"transcript\(4m\) \(REQ-668\)"

    else:
        raise AssertionError(f"unhandled scenario: {scenario}")

    result = _run_statusline(workspace, payload)
    last_line = _last_line(result)

    assert re.fullmatch(expected, last_line), last_line


def test_truncate_with_dispatch(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=1),
            "skillStack": [
                {"skill": "plan", "step": 1, "enteredAt": _iso_ago(minutes=20)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
                {"skill": "review", "step": 3, "enteredAt": _iso_ago(minutes=12)},
                {"skill": "approve", "step": 4, "enteredAt": _iso_ago(minutes=10)},
                {"skill": "dispatch", "step": 5, "enteredAt": _iso_ago(minutes=8)},
            ],
        },
    )
    _write_run(
        workspace,
        "REQ-800-T01",
        "codex",
        _iso_ago(minutes=2),
        skill="mst:codex",
    )
    _write_run(
        workspace,
        "REQ-800-T02",
        "gemini",
        _iso_ago(minutes=3),
        skill="mst:gemini",
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(
        r"plan\(20m\) > \.\.\. > codex\([0-9]+s\) > "
        r"\[codex:REQ-800-T01\(2m\), gemini:REQ-800-T02\(3m\)\]",
        last_line,
    ), last_line
