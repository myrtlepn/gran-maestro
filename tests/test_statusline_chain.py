import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"


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


def test_chain_render_from_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(seconds=2),
            "skillStack": [
                {"skill": "plan", "step": 4, "enteredAt": _iso_ago(minutes=8)},
                {"skill": "request", "step": 2, "enteredAt": _iso_ago(minutes=15)},
            ],
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(r"plan\(8m\) > request\(15m\) > codex\([2-9]s\)", last_line), last_line


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        ({"seconds": 45}, r"scale\(4[5-9]s\)"),
        ({"minutes": 8}, r"scale\(8m\)"),
        ({"hours": 2}, r"scale\(2h\)"),
        ({"days": 3}, r"scale\(3d\)"),
    ],
)
def test_format_elapsed_scale_in_snapshot_chain(tmp_path, delta, expected):
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "scale",
            "enteredAt": _iso_ago(**delta),
            "skillStack": [],
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert re.fullmatch(expected, last_line), last_line


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 5, 6])
def test_snapshot_chain_truncate_after_four_nodes(tmp_path, depth):
    workspace = tmp_path / "workspace"
    nodes = [f"skill{i}" for i in range(1, depth + 1)]
    stack = [
        {"skill": skill, "step": index, "enteredAt": _iso_ago(minutes=8)}
        for index, skill in enumerate(nodes[:-1], start=1)
    ]
    _write_snapshot(
        workspace,
        {
            "currentSkill": nodes[-1],
            "enteredAt": _iso_ago(minutes=8),
            "skillStack": stack,
        },
    )

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    if depth <= 4:
        expected = " > ".join(f"{skill}(8m)" for skill in nodes)
    else:
        expected = f"{nodes[0]}(8m) > ... > {nodes[-1]}(8m)"
    assert last_line == expected


@pytest.mark.parametrize("case", ["missing", "invalid", "empty"])
def test_bad_or_empty_snapshot_falls_back_to_idle(tmp_path, case):
    workspace = tmp_path / "workspace"
    path = _snapshot_path(workspace)
    if case == "invalid":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
    elif case == "empty":
        _write_snapshot(workspace, {"currentSkill": "", "skillStack": []})

    result = _run_statusline(workspace)
    last_line = _last_line(result)

    assert last_line == "MST idle"


def test_bad_snapshot_preserves_state_then_transcript_fallback_order(tmp_path):
    workspace = tmp_path / "workspace"
    path = _snapshot_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    _write_state(
        workspace,
        {
            "current_skill": "mst:state",
            "updated_at": _iso_ago(minutes=6),
        },
    )
    transcript_path = workspace / "session.jsonl"
    _write_transcript(transcript_path)

    result = _run_statusline(workspace, json.dumps({"transcript_path": str(transcript_path)}))
    last_line = _last_line(result)

    assert re.fullmatch(r"state\(6m\)", last_line), last_line
