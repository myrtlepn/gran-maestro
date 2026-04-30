"""DOD-003 회귀 테스트 — hooks/hooks.json에 4개 hook 이벤트가 모두 등록되어 있고
스크립트 파일이 실제로 존재하며 실행 가능한지 검증.

REQ-732(PLN-561)에서 hooks.json 자체 등록을 도입했고, 본 테스트는 향후 외부 PR이
hooks.json 등록을 누락 또는 손상시키면 즉시 fail하도록 회귀를 차단한다.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
HOOKS_DIR = REPO_ROOT / "hooks"

EXPECTED_EVENTS = {
    "SessionStart": {"matcher": "", "script": "mst-session-init.sh"},
    "PreToolUse": {"matcher": "Skill", "script": "mst-pre-tool-use.sh"},
    "Stop": {"matcher": "", "script": "mst-stop-hook.sh"},
    "UserPromptSubmit": {"matcher": "", "script": "mst-auto-chain-context.sh"},
}


def test_hooks_json_exists():
    assert HOOKS_JSON.exists(), f"hooks.json missing: {HOOKS_JSON}"


def test_hooks_json_valid_schema():
    payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "hooks" in payload
    assert isinstance(payload["hooks"], dict)


def test_all_four_events_registered():
    payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = payload["hooks"]
    missing = set(EXPECTED_EVENTS.keys()) - set(hooks.keys())
    assert not missing, f"missing events: {missing}"


def test_each_event_has_correct_matcher_and_command():
    payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = payload["hooks"]
    for event, expected in EXPECTED_EVENTS.items():
        entries = hooks.get(event, [])
        assert isinstance(entries, list) and entries, f"{event} entries empty"
        # entry에 expected matcher가 포함된 항목이 1개 이상 있어야 한다
        match_count = 0
        for entry in entries:
            assert isinstance(entry, dict), f"{event} entry not dict"
            if entry.get("matcher", "") != expected["matcher"]:
                continue
            for h in entry.get("hooks", []):
                assert isinstance(h, dict), f"{event} hook not dict"
                cmd = h.get("command", "")
                assert "${CLAUDE_PLUGIN_ROOT}" in cmd, (
                    f"{event} command missing ${{CLAUDE_PLUGIN_ROOT}}: {cmd}"
                )
                assert expected["script"] in cmd, (
                    f"{event} command does not reference {expected['script']}: {cmd}"
                )
                match_count += 1
        assert match_count >= 1, (
            f"{event} has no entry with matcher={expected['matcher']!r} pointing to {expected['script']}"
        )


def test_each_hook_script_file_exists():
    for expected in EXPECTED_EVENTS.values():
        script = HOOKS_DIR / expected["script"]
        assert script.exists(), f"hook script missing: {script}"


def test_each_hook_script_is_executable():
    for expected in EXPECTED_EVENTS.values():
        script = HOOKS_DIR / expected["script"]
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, f"hook script not user-executable: {script}"


def test_pretooluse_uses_skill_matcher():
    """옛 프로젝트가 누락하던 PreToolUse(matcher='Skill')가 등록되어 있는지 명시 검증."""
    payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    pre = payload["hooks"].get("PreToolUse", [])
    matchers = [e.get("matcher") for e in pre if isinstance(e, dict)]
    assert "Skill" in matchers, f"PreToolUse(matcher='Skill') not registered, got: {matchers}"


def test_pretooluse_uses_schedule_wakeup_matcher():
    """ScheduleWakeup native tool calls must route through the same PreToolUse hook."""
    payload = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    pre = payload["hooks"].get("PreToolUse", [])
    matchers = [e.get("matcher") for e in pre if isinstance(e, dict)]
    assert "Skill" in matchers, f"PreToolUse(matcher='Skill') not registered, got: {matchers}"
    assert "ScheduleWakeup" in matchers, (
        f"PreToolUse(matcher='ScheduleWakeup') not registered, got: {matchers}"
    )

    schedule_entries = [
        e for e in pre if isinstance(e, dict) and e.get("matcher") == "ScheduleWakeup"
    ]
    assert schedule_entries, "ScheduleWakeup matcher entry missing"
    commands = [
        h.get("command", "")
        for entry in schedule_entries
        for h in entry.get("hooks", [])
        if isinstance(h, dict)
    ]
    assert any("mst-pre-tool-use.sh" in cmd for cmd in commands), commands
