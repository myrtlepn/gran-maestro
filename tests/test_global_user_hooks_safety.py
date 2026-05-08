from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_TOOL = "mcp__plugin_oh-my-claudecode_x__ask_codex"
GEMINI_TOOL = "mcp__plugin_oh-my-claudecode_g__ask_gemini"


@pytest.fixture()
def global_scripts(tmp_path: Path) -> dict[str, Path]:
    script_dir = tmp_path / ".claude" / "scripts"
    script_dir.mkdir(parents=True)

    guard = script_dir / "maestro-guard.sh"
    guard.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if command -v jq >/dev/null 2>&1 && ! jq --version >/dev/null 2>&1; then
              exit 0
            fi
            payload="$(cat || true)"
            python3 - "{CODEX_TOOL}" "{GEMINI_TOOL}" "$payload" <<'PY'
            import json
            import pathlib
            import sys

            codex, gemini, payload = sys.argv[1], sys.argv[2], sys.argv[3]
            try:
                data = json.loads(payload) if payload.strip() else {{}}
            except Exception:
                raise SystemExit(0)
            if not isinstance(data, dict):
                raise SystemExit(0)
            cwd = data.get("cwd")
            tool_name = data.get("tool_name")
            if not isinstance(cwd, str) or tool_name not in {{codex, gemini}}:
                raise SystemExit(0)
            try:
                mode = json.loads((pathlib.Path(cwd) / ".gran-maestro" / "mode.json").read_text())
            except Exception:
                raise SystemExit(0)
            if not isinstance(mode, dict) or mode.get("active") is not True:
                raise SystemExit(0)
            skill = "mst:codex" if tool_name == codex else "mst:gemini"
            print(f'BLOCKED: use Skill(skill: "{{skill}}")')
            raise SystemExit(2)
            PY
            """
        ),
        encoding="utf-8",
    )

    log_prompt = script_dir / "log-prompt.sh"
    log_prompt.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            log_dir="${HOME:-}/.claude"
            mkdir -p "$log_dir" >/dev/null 2>&1 || exit 0
            printf 'prompt received\n' >> "$log_dir/prompt.log" 2>/dev/null || true
            exit 0
            """
        ),
        encoding="utf-8",
    )

    check_version = script_dir / "check-version.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "check-version.sh", check_version)

    for path in (guard, log_prompt, check_version):
        path.chmod(0o755)

    return {
        "maestro-guard.sh": guard,
        "log-prompt.sh": log_prompt,
        "check-version.sh": check_version,
    }


def _run_script(path: Path, stdin: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(path)],
        input=stdin,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=10,
    )


def _write_mode(project: Path, *, active: bool) -> None:
    mode_dir = project / ".gran-maestro"
    mode_dir.mkdir(parents=True)
    (mode_dir / "mode.json").write_text(json.dumps({"active": active}) + "\n", encoding="utf-8")


def _payload(cwd: Path | None = None, tool_name: str = CODEX_TOOL) -> str:
    payload: dict[str, str] = {"tool_name": tool_name}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return json.dumps(payload)


def test_maestro_guard_malformed_or_empty_stdin_passes(global_scripts: dict[str, Path]):
    script = global_scripts["maestro-guard.sh"]

    empty = _run_script(script, "")
    malformed = _run_script(script, "{not-json")

    assert empty.returncode == 0
    assert malformed.returncode == 0
    assert "BLOCKED" not in empty.stdout + empty.stderr
    assert "BLOCKED" not in malformed.stdout + malformed.stderr


def test_maestro_guard_non_mst_or_mode_missing_passes(tmp_path: Path, global_scripts: dict[str, Path]):
    script = global_scripts["maestro-guard.sh"]
    non_mst = tmp_path / "non-mst"
    non_mst.mkdir()
    active_project = tmp_path / "active"
    active_project.mkdir()
    _write_mode(active_project, active=True)

    missing_mode = _run_script(script, _payload(non_mst))
    missing_cwd = _run_script(script, _payload(None))
    outside_matcher = _run_script(script, _payload(active_project, "Read"))

    assert missing_mode.returncode == 0
    assert missing_cwd.returncode == 0
    assert outside_matcher.returncode == 0
    assert "BLOCKED" not in missing_mode.stdout + missing_mode.stderr
    assert "BLOCKED" not in missing_cwd.stdout + missing_cwd.stderr
    assert "BLOCKED" not in outside_matcher.stdout + outside_matcher.stderr


def test_maestro_guard_active_false_or_inactive_passes(tmp_path: Path, global_scripts: dict[str, Path]):
    script = global_scripts["maestro-guard.sh"]
    inactive_project = tmp_path / "inactive"
    inactive_project.mkdir()
    _write_mode(inactive_project, active=False)

    proc = _run_script(script, _payload(inactive_project))

    assert proc.returncode == 0
    assert "BLOCKED" not in proc.stdout + proc.stderr


def test_global_hooks_dependency_logging_user_prompt_fail_open(tmp_path: Path, global_scripts: dict[str, Path]):
    guard = global_scripts["maestro-guard.sh"]
    log_prompt = global_scripts["log-prompt.sh"]
    check_version = global_scripts["check-version.sh"]

    active_project = tmp_path / "active"
    active_project.mkdir()
    _write_mode(active_project, active=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("jq", "find"):
        path = fake_bin / name
        path.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
        path.chmod(0o755)
    path_env = f"{fake_bin}:/usr/bin:/bin"

    dependency_failure = _run_script(guard, _payload(active_project), {"PATH": path_env})
    assert dependency_failure.returncode == 0
    assert "BLOCKED" not in dependency_failure.stdout + dependency_failure.stderr

    home_file = tmp_path / "home-file"
    home_file.write_text("not a directory", encoding="utf-8")
    logging_failure = _run_script(
        log_prompt,
        env={"HOME": str(home_file), "CLAUDE_USER_PROMPT": "sensitive prompt text"},
    )
    assert logging_failure.returncode == 0
    assert "sensitive prompt text" not in logging_failure.stdout + logging_failure.stderr

    cache_root = tmp_path / "home" / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst"
    (cache_root / "1.2.3").mkdir(parents=True)
    version_failure = _run_script(
        check_version,
        env={"HOME": str(tmp_path / "home"), "PATH": path_env},
    )
    assert version_failure.returncode == 0


def test_maestro_guard_active_and_block_policy_violation(tmp_path: Path, global_scripts: dict[str, Path]):
    script = global_scripts["maestro-guard.sh"]
    active_project = tmp_path / "active"
    active_project.mkdir()
    _write_mode(active_project, active=True)

    codex = _run_script(script, _payload(active_project, CODEX_TOOL))
    gemini = _run_script(script, _payload(active_project, GEMINI_TOOL))

    assert codex.returncode == 2
    assert "BLOCKED" in codex.stdout
    assert 'Skill(skill: "mst:codex"' in codex.stdout
    assert gemini.returncode == 2
    assert "BLOCKED" in gemini.stdout
    assert 'Skill(skill: "mst:gemini"' in gemini.stdout


def test_user_global_settings_read_only(tmp_path: Path, global_scripts: dict[str, Path]):
    guard = global_scripts["maestro-guard.sh"]
    log_prompt = global_scripts["log-prompt.sh"]
    check_version = global_scripts["check-version.sh"]
    before = SETTINGS_PATH.read_bytes() if SETTINGS_PATH.exists() else None

    project = tmp_path / "project"
    project.mkdir()
    _write_mode(project, active=False)
    assert _run_script(guard, _payload(project)).returncode == 0
    assert _run_script(log_prompt, env={"HOME": str(tmp_path / "home"), "CLAUDE_USER_PROMPT": "hello"}).returncode == 0
    assert _run_script(check_version, env={"HOME": str(tmp_path / "home")}).returncode == 0

    after = SETTINGS_PATH.read_bytes() if SETTINGS_PATH.exists() else None
    assert after == before
