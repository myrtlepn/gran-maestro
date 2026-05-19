from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
CODEX_HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.codex.json"
EXPECTED_HOOK_EVENTS = {
    "SessionStart",
    "PreToolUse",
    "Stop",
    "UserPromptSubmit",
}


def test_plugin_manifest_declares_hooks_file() -> None:
    payload = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))

    assert payload["hooks"] == "./hooks/hooks.json"


def test_plugin_manifest_hooks_file_exposes_expected_events() -> None:
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    hooks_path = REPO_ROOT / plugin["hooks"]
    hooks_payload = json.loads(hooks_path.read_text(encoding="utf-8"))

    assert hooks_path == HOOKS_JSON
    assert set(hooks_payload["hooks"]) == EXPECTED_HOOK_EVENTS


def test_canonical_hook_commands_use_plugin_root_only() -> None:
    hooks_payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))

    for event, entries in hooks_payload["hooks"].items():
        assert entries, f"{event} must declare at least one hook entry"
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                assert command.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"), (
                    f"{event} must use plugin-root canonical hook command: {command}"
                )
                assert "$CLAUDE_PROJECT_DIR/.claude/hooks" not in command
                assert ".claude/hooks" not in command


def test_codex_hook_fixture_manifest_exposes_expected_events() -> None:
    payload = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))

    assert payload["mode"] == "fixture-only"
    assert payload["adapter_runner"] == "./scripts/codex-hook-adapter-fixture.mjs"
    assert set(payload["hooks"]) == EXPECTED_HOOK_EVENTS


def test_codex_hook_fixture_manifest_uses_plugin_relative_adapter_commands() -> None:
    hooks_payload = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))

    for event, entries in hooks_payload["hooks"].items():
        assert entries, f"{event} must declare at least one adapter entry"
        for entry in entries:
            for hook in entry.get("hooks", []):
                command = hook.get("command", "")
                path_token = command.split(" ", 1)[0]
                assert path_token.startswith("./"), (
                    f"{event} must use plugin-root relative command: {command}"
                )
                assert ".." not in path_token
                assert not path_token.startswith("/")
                assert ".claude/hooks" not in command
                assert "$CLAUDE_PROJECT_DIR/.claude/hooks" not in command
                assert "~/.claude" not in command


def test_codex_hook_fixture_manifest_has_zero_duplicate_registration_commands() -> None:
    canonical = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    codex = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))

    canonical_tuples = {
        (event, entry.get("matcher", ""), hook.get("command", ""))
        for event, entries in canonical["hooks"].items()
        for entry in entries
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    }
    codex_tuples = {
        (event, entry.get("matcher", ""), hook.get("command", ""))
        for event, entries in codex["hooks"].items()
        for entry in entries
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    }

    assert canonical_tuples.isdisjoint(codex_tuples)


def main() -> int:
    test_plugin_manifest_declares_hooks_file()
    print("PASS test_plugin_manifest_declares_hooks_file")
    test_plugin_manifest_hooks_file_exposes_expected_events()
    print("PASS test_plugin_manifest_hooks_file_exposes_expected_events")
    test_canonical_hook_commands_use_plugin_root_only()
    print("PASS test_canonical_hook_commands_use_plugin_root_only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
