# -*- coding: utf-8 -*-
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"
SESSION_ID = "71402"
UTF8_SEPARATOR = " › "
ASCII_SEPARATOR = " > "


def _run_statusline(workspace: Path, payload: str = "{}") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["MST_STATE_PPID"] = SESSION_ID

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


def _write_snapshot(workspace: Path, payload: dict) -> Path:
    path = workspace / ".gran-maestro" / "state" / SESSION_ID / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _three_level_snapshot() -> dict:
    return {
        "currentSkill": "codex",
        "enteredAt": _iso_ago(minutes=1),
        "skillStack": [
            {"skill": "agile", "enteredAt": _iso_ago(minutes=5)},
            {"skill": "request", "enteredAt": _iso_ago(minutes=3)},
        ],
    }


def test_utf8_separator_3_levels(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    workspace = tmp_path / "workspace"
    _write_snapshot(workspace, _three_level_snapshot())

    last_line = _last_line(_run_statusline(workspace))

    assert last_line.count(UTF8_SEPARATOR) == 2
    assert ASCII_SEPARATOR not in last_line
    assert "agile(" in last_line
    assert "request(" in last_line
    assert "codex(" in last_line


def test_ascii_fallback_separator(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setenv("LC_ALL", "C")
    workspace = tmp_path / "workspace"
    _write_snapshot(workspace, _three_level_snapshot())

    last_line = _last_line(_run_statusline(workspace))

    assert ASCII_SEPARATOR in last_line
    assert UTF8_SEPARATOR not in last_line
    assert "agile(" in last_line
    assert "request(" in last_line
    assert "codex(" in last_line


def test_truncation_4_plus_levels(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(minutes=1),
            "skillStack": [
                {"skill": "agile", "enteredAt": _iso_ago(minutes=5)},
                {"skill": "plan", "enteredAt": _iso_ago(minutes=4)},
                {"skill": "request", "enteredAt": _iso_ago(minutes=3)},
            ],
        },
    )

    last_line = _last_line(_run_statusline(workspace))

    assert last_line == "agile(5m) › ... › codex(1m)"
    assert "..." in last_line
    assert "plan(" not in last_line
    assert "request(" not in last_line


def test_step_total_preserved_in_current(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(minutes=1),
            "step": 2,
            "total": 5,
            "skillStack": [
                {"skill": "agile", "enteredAt": _iso_ago(minutes=5)},
                {"skill": "plan", "enteredAt": _iso_ago(minutes=4)},
                {"skill": "request", "enteredAt": _iso_ago(minutes=3)},
            ],
        },
    )

    last_line = _last_line(_run_statusline(workspace))

    assert "[2/5]" in last_line
    assert last_line.endswith("codex[2/5]")


def test_current_step_total_fallback_fields_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "enteredAt": _iso_ago(minutes=1),
            "currentStep": 3,
            "totalSteps": 7,
            "skillStack": [],
        },
    )

    last_line = _last_line(_run_statusline(workspace))

    assert last_line == "codex[3/7]"


def test_step_total_preserved_in_stack_label(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    workspace = tmp_path / "workspace"
    _write_snapshot(
        workspace,
        {
            "currentSkill": "codex",
            "skillStack": [
                {"skill": "agile", "enteredAt": _iso_ago(minutes=5), "step": 1, "total": 2},
            ],
        },
    )

    last_line = _last_line(_run_statusline(workspace))

    assert last_line == "agile[1/2] › codex"
