import json
import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE_SCRIPT = REPO_ROOT / "scripts" / "mst-statusline.sh"


def _run_statusline(workspace: Path, payload: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home_dir = workspace / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home_dir)
    env["CLAUDE_CONFIG_DIR"] = str(home_dir / ".claude")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"

    return subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        cwd=workspace,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _last_output_line(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, "statusline output is empty"
    return lines[-1]


def test_prefix_claude_idle(tmp_path):
    workspace = tmp_path / "workspace"
    payload = json.dumps({"model": {"display_name": "Opus", "id": "claude-opus-4-7"}})

    result = _run_statusline(workspace, payload)
    last_line = _last_output_line(result)

    assert last_line == "[Claude/Opus] MST idle"


@pytest.mark.parametrize(
    ("model", "provider", "expected_model"),
    [
        ({"id": "claude-opus-4-7", "display_name": "Opus"}, "Claude", "Opus"),
        ({"id": "gpt-5.3-codex", "display_name": "Codex"}, "OpenAI", "Codex"),
        ({"id": "agy-default"}, "AGY", None),
        ({"id": "gemini-3.1-pro-preview"}, "Gemini", None),
    ],
)
def test_provider_family_detection(tmp_path, model, provider, expected_model):
    workspace = tmp_path / "workspace"
    payload = json.dumps({"model": model}, ensure_ascii=False)

    result = _run_statusline(workspace, payload)
    last_line = _last_output_line(result)

    assert last_line.startswith(f"[{provider}/"), last_line
    assert last_line.endswith(" MST idle"), last_line
    prefix = last_line.split(" ", 1)[0]
    if expected_model is not None:
        assert prefix == f"[{provider}/{expected_model}]"
    else:
        assert prefix not in {f"[{provider}]", f"[{provider}/]"}


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"model":null}',
        '{"model":{}}',
        "",
        "not-json",
    ],
)
def test_graceful_skip_when_model_missing(tmp_path, payload):
    workspace = tmp_path / "workspace"

    result = _run_statusline(workspace, payload)
    last_line = _last_output_line(result)

    assert last_line == "MST idle"
    assert not last_line.startswith("[")


def test_unknown_family_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    payload = json.dumps({"model": {"id": "llama-8b-instruct", "display_name": "Llama 8B"}})

    result = _run_statusline(workspace, payload)
    last_line = _last_output_line(result)

    assert re.match(r"^\[Unknown(?:/[^\]]+)?\] MST idle$", last_line), last_line
