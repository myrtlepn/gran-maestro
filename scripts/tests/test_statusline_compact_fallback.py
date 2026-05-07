from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"
SID = "MST-AGI-031-20260507T020304000Z-dod006aa"
SOURCE_HEAD = "c" * 64
COUNTER_PATTERN = re.compile(r"^\[CORE-BLOCK:\d+\] \[POLICY-BLOCK:\d+\] ")


def _run_statusline(
    workspace: Path,
    payload: dict | None = None,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    env.pop("MST_SESSION_ID", None)
    env.pop("MST_STATE_PPID", None)
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=json.dumps(payload or {}, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines


def _mst_line(result: subprocess.CompletedProcess[str]) -> str:
    for line in reversed(_lines(result)):
        if not COUNTER_PATTERN.match(line):
            return line
    raise AssertionError(f"statusline output has no MST line: {result.stdout!r}")


def _write_snapshot(workspace: Path, session_id: str, payload: dict) -> Path:
    path = workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_hud_command(workspace: Path, command: str) -> None:
    path = workspace / "home" / ".claude" / "mst-statusline-backup.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"statusLine": {"command": command}}), encoding="utf-8")


def test_statusline_uses_compact_current_work_projection_when_hud_unavailable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        SID,
        {
            "schema_version": 1,
            "root_id": "AGI-031",
            "currentSkill": "mst:agile",
            "step": 2,
            "total": 4,
            "skillStack": [{"skill": "mst:plan", "id": "PLN-654"}],
            "source_history_head": SOURCE_HEAD,
            "current_history_head": SOURCE_HEAD,
            "nextAction": {
                "action_type": "resume_workflow",
                "label": "Review compact",
                "target": "REQ-827",
                "evidence_path": ".gran-maestro/requests/REQ-827/request.json",
            },
        },
    )

    result = _run_statusline(
        workspace,
        {"mst_session_id": SID},
        env_overrides={"MST_SESSION_ID": SID},
    )

    assert (
        _mst_line(result)
        == "MST AGI-031 mst:agile 2/4 stack:2 next:Review compact "
        "blocker:none fresh:fresh head:cccccccc"
    )


def test_statusline_schema_invalid_source_uses_compact_blocker(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_snapshot(workspace, SID, {"schema_version": 2, "root_id": "REQ-827"})

    result = _run_statusline(
        workspace,
        {"mst_session_id": SID},
        env_overrides={"MST_SESSION_ID": SID},
    )

    assert _mst_line(result) == "MST REQ-827 stack:0 next:unknown blocker:schema_invalid fresh:unknown"


def test_canonical_session_without_snapshot_uses_bounded_missing_source_fallback(tmp_path: Path) -> None:
    result = _run_statusline(
        tmp_path / "workspace",
        {"mst_session_id": SID},
        env_overrides={"MST_SESSION_ID": SID},
    )

    assert _mst_line(result) == "MST unknown stack:0 next:unknown blocker:missing_source fresh:no_history"


def test_statusline_preserves_external_hud_output_before_compact_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write_hud_command(workspace, "printf '%s\\n' HUD_READY")

    result = _run_statusline(workspace)
    lines = _lines(result)

    assert lines[0] == "HUD_READY"
    assert _mst_line(result) == "MST idle"
