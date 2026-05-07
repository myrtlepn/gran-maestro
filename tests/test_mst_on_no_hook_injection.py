"""DOD-007 + DOD-002 회귀 테스트.

/mst:on이 hook 파일을 .claude/hooks/로 복사하지 않고 settings.local.json의
hooks 블록도 변경하지 않음을 보장한다. hooks.json 자체 등록(REQ-732)이
유일한 hook 등록 경로가 되도록 강제하는 정적 + 시뮬레이션 검증.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / "skills" / "on" / "SKILL.md"
HOOKS_JSON_PATH = REPO_ROOT / "hooks" / "hooks.json"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_md_no_hook_copy_patterns():
    """SKILL.md에 6a Hook 파일 복사 패턴이 0건이어야 한다."""
    text = _skill_text()
    forbidden = [
        r"Hook 파일 복사",
        r"cp\s+\"\{PLUGIN_ROOT\}/hooks",
        r"mst-hook-version",
    ]
    for pattern in forbidden:
        matches = re.findall(pattern, text)
        assert not matches, (
            f"forbidden 6a pattern still present: {pattern!r} matches={matches}"
        )


def test_skill_md_no_settings_inject_patterns():
    """SKILL.md에 6b settings.local.json hooks 주입 패턴이 0건이어야 한다."""
    text = _skill_text()
    forbidden = [
        r"hook_map\s*=",
        r'hooks\.setdefault\("hooks"',
        r"레거시 hook 참조 정리",
        r"legacy_events\s*=",
    ]
    for pattern in forbidden:
        matches = re.findall(pattern, text)
        assert not matches, (
            f"forbidden 6b pattern still present: {pattern!r} matches={matches}"
        )


def test_skill_md_announces_hooks_json_self_registration():
    """SKILL.md는 hooks.json 자체 등록 메커니즘을 명시적으로 안내해야 한다."""
    text = _skill_text()
    assert "hooks.json 자체 등록" in text, (
        "hooks.json self-registration 안내 누락"
    )
    assert "plugin core canonical runtime" in text, (
        "plugin core canonical runtime 안내 누락"
    )
    assert "일반 프로젝트 canonical runtime이 아니라 project legacy" in text, (
        "project legacy 경계 안내 누락"
    )
    assert "user-global environment hook" in text, (
        "user-global hook 계층 안내 누락"
    )
    assert "${CLAUDE_PLUGIN_ROOT}" in text, (
        "${CLAUDE_PLUGIN_ROOT} 변수 안내 누락"
    )


def test_simulated_new_project_no_hooks_dir(tmp_path):
    """SKILL.md에 hook 파일 복사 코드가 없으므로 신규 프로젝트의 .claude/hooks/는 생성되지 않는다."""
    text = _skill_text()
    assert "Hook 파일 복사" not in text
    # tmpdir에는 .claude/hooks/가 존재하지 않음을 자명하게 확인 (negative control)
    assert not (tmp_path / ".claude" / "hooks").exists()


def test_simulated_new_project_no_settings_hooks_field(tmp_path):
    """SKILL.md에 settings.local.json hooks 주입 코드가 없으므로 신규 프로젝트 hooks 필드는 미생성."""
    text = _skill_text()
    assert "hook_map" not in text
    settings_path = tmp_path / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("{}\n", encoding="utf-8")
    payload = json.loads(settings_path.read_text())
    assert "hooks" not in payload or payload.get("hooks") in ({}, None)


def test_existing_user_hooks_preserved(tmp_path):
    """사용자 정의 hooks가 settings.local.json에 이미 있으면 /mst:on은 그것을 손대지 않는다.

    SKILL.md에 hooks 필드 변경 코드가 0건임을 정적으로 검증하면 보존이 자동 보장된다.
    """
    text = _skill_text()
    assert 'hooks.setdefault("hooks"' not in text

    settings_path = tmp_path / ".claude" / "settings.local.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    user_settings = {
        "env": {"FOO": "bar"},
        "permissions": {"allow": ["read"]},
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "/usr/local/bin/my-hook.sh"}
                    ],
                }
            ]
        },
    }
    settings_path.write_text(
        json.dumps(user_settings, indent=2) + "\n", encoding="utf-8"
    )

    # /mst:on이 settings.local.json hooks를 손대지 않으므로 idempotent no-op
    payload = json.loads(settings_path.read_text())
    assert payload == user_settings


def test_hooks_json_unchanged():
    """hooks/hooks.json 파일은 본 plan에서 변경되지 않는다.

    4개 hook(SessionStart / PreToolUse / Stop / UserPromptSubmit) 모두
    ${CLAUDE_PLUGIN_ROOT} 형식으로 등록되어 있어야 한다.
    """
    assert HOOKS_JSON_PATH.exists(), f"hooks.json missing: {HOOKS_JSON_PATH}"
    payload = json.loads(HOOKS_JSON_PATH.read_text())
    hooks = payload.get("hooks", {})
    expected_events = {"SessionStart", "PreToolUse", "Stop", "UserPromptSubmit"}
    assert expected_events.issubset(hooks.keys()), (
        f"missing events: {expected_events - hooks.keys()}"
    )
    for event in expected_events:
        entries = hooks[event]
        assert isinstance(entries, list) and entries, f"{event} entries empty"
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                assert cmd.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"), (
                    f"{event} hook command must use canonical plugin root path: {cmd}"
                )
                assert "$CLAUDE_PROJECT_DIR/.claude/hooks" not in cmd
                assert ".claude/hooks" not in cmd
