from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
REPO_ROOT = Path(__file__).resolve().parents[1]
MST_CLI = [sys.executable, str(REPO_ROOT / "scripts" / "mst.py")]
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


def _write_mixed_user_global_settings(home: Path) -> Path:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "mcp__plugin_oh-my-claudecode_x__ask_codex",
                    "hooks": [
                        {"type": "command", "command": "~/.claude/scripts/maestro-guard.sh"}
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "~/.claude/scripts/log-prompt.sh"},
                        {"type": "command", "command": "~/.claude/scripts/check-version.sh"},
                    ],
                }
            ],
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "~/.claude/hooks/mst-stop-hook.sh --global-wrapper",
                        }
                    ],
                }
            ],
        }
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return settings_path


def _settings_commands_by_event(settings: dict) -> dict[tuple[str, str], list[str]]:
    commands: dict[tuple[str, str], list[str]] = {}
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            matcher = entry.get("matcher", "")
            commands[(event, matcher)] = [
                hook["command"]
                for hook in entry.get("hooks", [])
                if isinstance(hook, dict) and isinstance(hook.get("command"), str)
            ]
    return commands


def _payload(cwd: Path | None = None, tool_name: str = CODEX_TOOL) -> str:
    payload: dict[str, str] = {"tool_name": tool_name}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return json.dumps(payload)


def _plugin_version() -> str:
    return json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


def _write_registered_project(project: Path) -> None:
    (project / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "hooks" / "mst-stop-hook.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
                                }
                            ],
                        }
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_cache_install(cache_root: Path, *, version: str, include_registry: bool) -> None:
    install_root = cache_root / version
    (install_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (install_root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "mst", "version": version, "hooks": "./hooks/hooks.json"}, indent=2) + "\n",
        encoding="utf-8",
    )
    hooks_dir = install_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    if include_registry:
        (hooks_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
                                    }
                                ],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    (hooks_dir / "mst-stop-hook.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")


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


def test_cleanup_preserves_mixed_user_global_hooks_and_event_membership(tmp_path: Path):
    home = tmp_path / "home"
    user_settings_path = _write_mixed_user_global_settings(home)
    before_bytes = user_settings_path.read_bytes()
    before_commands = _settings_commands_by_event(json.loads(before_bytes))

    project = tmp_path / "project"
    project.mkdir()
    (project / ".gran-maestro").mkdir()
    (project / ".claude" / "hooks").mkdir(parents=True)
    (project / ".claude" / "hooks" / "mst-stop-hook.sh").write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
                                }
                            ],
                        }
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update({"HOME": str(home), "MST_PROJECT_ROOT": str(project)})
    dry_run = subprocess.run(
        MST_CLI + ["on", "cleanup", "--json", "--dry-run"],
        cwd=str(project),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    dry_run_payload = json.loads(dry_run.stdout)

    apply = subprocess.run(
        MST_CLI + [
            "on",
            "cleanup",
            "--json",
            "--dry-run-id",
            dry_run_payload["dry_run_id"],
        ],
        cwd=str(project),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert apply.returncode == 0, apply.stderr
    apply_payload = json.loads(apply.stdout)

    after_bytes = user_settings_path.read_bytes()
    after_commands = _settings_commands_by_event(json.loads(after_bytes))
    assert after_bytes == before_bytes
    assert after_commands == before_commands

    observed = {
        (hook["event"], hook["matcher"], hook["command"]): hook
        for hook in dry_run_payload["user_global"]["hooks"]
    }
    for key, commands in before_commands.items():
        event, matcher = key
        for command in commands:
            assert (event, matcher, command) in observed
    assert observed[("Stop", "", "~/.claude/hooks/mst-stop-hook.sh --global-wrapper")][
        "known_global"
    ] is False
    assert apply_payload["plugin_core"]["status"] == "canonical"
    assert all(
        hook["classification"] == "user_global"
        for hook in dry_run_payload["user_global"]["hooks"]
    )


@pytest.mark.parametrize("fixture_name", ["manifest_failure", "cache_failure"])
def test_cleanup_user_global_membership_preserved_across_manifest_and_cache_failures(tmp_path: Path, fixture_name: str):
    home = tmp_path / f"home-{fixture_name}"
    user_settings_path = _write_mixed_user_global_settings(home)
    before_bytes = user_settings_path.read_bytes()
    before_commands = _settings_commands_by_event(json.loads(before_bytes))

    project = tmp_path / f"project-{fixture_name}"
    project.mkdir()
    _write_registered_project(project)

    if fixture_name == "manifest_failure":
        (project / ".claude-plugin").mkdir()
    else:
        cache_root = home / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst"
        _write_cache_install(cache_root, version="0.57.6", include_registry=True)
        _write_cache_install(cache_root, version=_plugin_version(), include_registry=False)

    env = os.environ.copy()
    env.update({"HOME": str(home), "MST_PROJECT_ROOT": str(project)})
    proc = subprocess.run(
        MST_CLI + ["on", "cleanup", "--json"],
        cwd=str(project),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    after_bytes = user_settings_path.read_bytes()
    after_commands = _settings_commands_by_event(json.loads(after_bytes))
    assert after_bytes == before_bytes
    assert after_commands == before_commands
    if fixture_name == "manifest_failure":
        assert "missing_plugin_manifest" in json.dumps(payload["diagnostics"], ensure_ascii=False)
    else:
        assert "cache_sync_failure" in json.dumps(payload["diagnostics"], ensure_ascii=False)


def test_cleanup_unknown_user_global_preserves_mixed_user_global_hooks_on_failure_path(tmp_path: Path):
    home = tmp_path / "home"
    user_settings_path = _write_mixed_user_global_settings(home)
    before_bytes = user_settings_path.read_bytes()
    before_commands = _settings_commands_by_event(json.loads(before_bytes))

    project = tmp_path / "project"
    project.mkdir()
    (project / ".gran-maestro").mkdir()
    (project / ".claude" / "hooks").mkdir(parents=True)
    (project / ".claude" / "hooks" / "mst-stop-hook.sh").write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
                                }
                            ],
                        }
                    ],
                    "PreToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict",
                                }
                            ],
                        }
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (project / ".claude" / "hooks" / "project-unknown-hook.sh").write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update({"HOME": str(home), "MST_PROJECT_ROOT": str(project)})
    dry_run = subprocess.run(
        MST_CLI + ["on", "cleanup", "--json", "--dry-run"],
        cwd=str(project),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    dry_run_payload = json.loads(dry_run.stdout)

    after_bytes = user_settings_path.read_bytes()
    after_commands = _settings_commands_by_event(json.loads(after_bytes))
    assert after_bytes == before_bytes
    assert after_commands == before_commands
    diagnostics = [
        item
        for item in dry_run_payload.get("diagnostics", [])
        if item.get("code") == "unknown_hook_command"
    ]
    assert diagnostics
    assert diagnostics[0]["result"] == "safe-skip"
    assert diagnostics[0]["reason"] == "manual-review"
