from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
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


def main() -> int:
    test_plugin_manifest_declares_hooks_file()
    print("PASS test_plugin_manifest_declares_hooks_file")
    test_plugin_manifest_hooks_file_exposes_expected_events()
    print("PASS test_plugin_manifest_hooks_file_exposes_expected_events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
