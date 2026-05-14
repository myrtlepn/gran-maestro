from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
LEGACY_HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"

CORE_EVENTS = {"SessionStart", "Stop"}
CORE_SCRIPTS = {
    "SessionStart": "mst-session-init.sh",
    "Stop": "mst-stop-hook.sh",
}
SCHEMA_KEYS = {"reason", "action", "observed_sources", "source_precedence", "invocation_class"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _commands_by_event() -> dict[str, list[str]]:
    payload = _load_json(HOOKS_JSON)
    commands: dict[str, list[str]] = {}
    for event, entries in payload["hooks"].items():
        event_commands: list[str] = []
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command")
                if isinstance(command, str):
                    event_commands.append(command)
        commands[event] = event_commands
    return commands


def _classify_hook_command(command: str, *, user_global: bool = False) -> dict[str, str]:
    if command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"):
        return {
            "classification": "plugin_core",
            "reason": "canonical_plugin_hook_registration",
            "action": "load_as_mst_core_runtime",
        }
    if user_global:
        return {
            "classification": "user_global",
            "reason": "user_global_hook_diagnostic_only",
            "action": "preserve_without_mst_core_classification",
        }
    if ".claude/hooks/" in command or command.startswith("$CLAUDE_PROJECT_DIR/.claude/hooks/"):
        return {
            "classification": "project_legacy_source_dev",
            "reason": "legacy_project_hook_not_canonical_runtime",
            "action": "diagnostic_only_no_core_runtime",
        }
    return {
        "classification": "unknown",
        "reason": "manual_review",
        "action": "preserve_without_mst_core_classification",
    }


def test_hook_registration_chain_uses_plugin_manifest_and_plugin_root_commands() -> None:
    plugin = _load_json(PLUGIN_JSON)
    assert plugin["hooks"] == "./hooks/hooks.json"
    assert (REPO_ROOT / plugin["hooks"]).resolve() == HOOKS_JSON.resolve()

    commands = _commands_by_event()
    for event in CORE_EVENTS:
        expected = f"${{CLAUDE_PLUGIN_ROOT}}/hooks/{CORE_SCRIPTS[event]}"
        assert expected in commands[event]
        assert all("$CLAUDE_PROJECT_DIR/.claude/hooks" not in command for command in commands[event])
        assert all(".claude/hooks" not in command for command in commands[event])


def test_hook_registration_classifies_legacy_and_user_global_outside_plugin_core() -> None:
    canonical = _classify_hook_command("${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh")
    legacy = _classify_hook_command("$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh")
    user_global = _classify_hook_command("~/.claude/hooks/mst-stop-hook.sh --global-wrapper", user_global=True)

    assert canonical["classification"] == "plugin_core"
    assert legacy == {
        "classification": "project_legacy_source_dev",
        "reason": "legacy_project_hook_not_canonical_runtime",
        "action": "diagnostic_only_no_core_runtime",
    }
    assert user_global == {
        "classification": "user_global",
        "reason": "user_global_hook_diagnostic_only",
        "action": "preserve_without_mst_core_classification",
    }


def test_hook_registration_schema_owner_extension() -> None:
    diagnostic = {
        "valid": False,
        "reason": "legacy_project_hook_not_canonical_runtime",
        "action": "diagnostic_only_no_core_runtime",
        "observed_sources": {
            "plugin_manifest:hooks": {"value": "./hooks/hooks.json", "classification": "plugin_core"},
            "project_legacy:.claude/hooks": {
                "value": str(LEGACY_HOOKS_DIR),
                "classification": "project_legacy_source_dev",
            },
            "user_global:settings": {"value": "~/.claude/settings.json", "classification": "user_global"},
        },
        "source_precedence": [
            "plugin_manifest:hooks",
            "hooks_json:command",
            "project_legacy:.claude/hooks",
            "user_global:settings",
        ],
        "invocation_class": "hook_registration_fixture",
    }

    assert SCHEMA_KEYS <= diagnostic.keys()
    diagnostic["observed_sources"]["owner_session_id"] = {
        "value": None,
        "classification": "owner_extension_placeholder",
        "reason": "owner_resolution_not_evaluated_by_dod001",
        "action": "extend_without_schema_rename",
    }
    assert SCHEMA_KEYS <= diagnostic.keys()


def test_fixture_names_expose_identity_source_and_boundary() -> None:
    expected_shell_fixture = REPO_ROOT / "tests" / "hooks" / "test_dod001_session_identity_boundaries.sh"
    assert expected_shell_fixture.is_file()
    fixture_text = expected_shell_fixture.read_text(encoding="utf-8")
    for fixture_name in (
        "hook_boundary_env_only",
        "hook_boundary_stdin_only",
        "hook_boundary_env_stdin_same",
        "hook_boundary_env_stdin_conflict",
        "hook_boundary_invalid_env",
        "hook_boundary_missing",
        "hook_boundary_legacy_only",
    ):
        assert fixture_name in fixture_text

