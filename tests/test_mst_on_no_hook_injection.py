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
DOC_HOOK_MODEL_PATHS = [
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "docs" / "CLAUDE.md",
    REPO_ROOT / "skills" / "on" / "SKILL.md",
    REPO_ROOT / "skills" / "_shared" / "hooks-sync.md",
]
DOC_LEGACY_HOOK_REFERENCE_PATHS = [
    *DOC_HOOK_MODEL_PATHS,
    REPO_ROOT / "docs" / "RELEASE.md",
]
CANONICAL_HOOK_TIER_TERMS = [
    "plugin core canonical runtime",
    "project legacy / source-dev helper",
    "user-global environment hook",
]
DOC_HOOK_MODEL_REQUIRED_TERMS = {
    REPO_ROOT / "CLAUDE.md": CANONICAL_HOOK_TIER_TERMS,
    REPO_ROOT / "docs" / "CLAUDE.md": CANONICAL_HOOK_TIER_TERMS,
    REPO_ROOT / "skills" / "on" / "SKILL.md": CANONICAL_HOOK_TIER_TERMS,
    REPO_ROOT / "skills" / "_shared" / "hooks-sync.md": [
        "project legacy / source-dev helper",
    ],
}
LEGACY_HOOK_ALLOWED_CONTEXT_PATTERNS = [
    r"\blegacy\b",
    r"레거시",
    r"source-dev",
    r"source repo",
    r"source 개발",
    r"\bcleanup\b",
    r"정리",
    r"\brepair\b",
    r"명시",
    r"\bexplicit\b",
    r"\bsync\b",
    r"historical",
    r"history",
    r"\bdiagnostic\b",
    r"진단",
    r"\bdoctor\b",
    r"not canonical",
    r"canonical runtime이 아니",
    r"canonical runtime 아님",
    r"canonical runtime으로 주입하면 안",
    r"canonical runtime으로 변경하지 않습니다",
    r"직접 수정 금지",
    r"보조",
    r"호환",
]
PROJECT_HOOK_CANONICAL_PATTERNS = [
    r"\.claude/hooks[^.\n]*(?:canonical runtime|canonical MST core|MST core canonical|유일한 canonical)",
    r"\$CLAUDE_PROJECT_DIR/\.claude/hooks[^.\n]*(?:canonical runtime|canonical MST core|MST core canonical|유일한 canonical)",
    r"settings\.local\.json[^.\n]*(?:canonical runtime|canonical MST core|MST core canonical|유일한 canonical|hook 등록 경로)",
]
PROJECT_HOOK_NEGATION_PATTERNS = [
    r"not canonical",
    r"아니",
    r"아님",
    r"안 됩니다",
    r"않",
    r"금지",
    r"cleanup",
    r"legacy",
    r"레거시",
]


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _line_context(lines: list[str], index: int, radius: int = 1) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:end])


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


def test_docs_use_canonical_hook_tier_terminology():
    """DOD-008 문서는 hook 책임 경계를 같은 3계층 용어로 설명해야 한다."""
    failures = []
    for path, required_terms in DOC_HOOK_MODEL_REQUIRED_TERMS.items():
        text = _read_text(path).lower()
        missing = [
            term
            for term in required_terms
            if term.lower() not in text
        ]
        if missing:
            failures.append(f"{_relative(path)} missing terms: {missing}")

    assert not failures, "\n".join(failures)


def test_skill_md_distinguishes_hooks_json_cleanup_and_user_global_boundaries():
    """`/mst:on` 문서는 plugin core, cleanup, user-global hook 경계를 분리해야 한다."""
    text = _skill_text()
    required = {
        "plugin manifest hooks reference": r'"hooks": "\./hooks/hooks\.json"',
        "hooks.json self-registration": r"hooks\.json 자체 등록",
        "plugin-root commands": r"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/",
        "legacy cleanup target": r"(cleanup 대상|cleanup.*stale|legacy.*cleanup)",
        "project legacy tier": r"project legacy / source-dev helper",
        "user-global tier": r"user-global environment hook",
        "user-global install target": r"~/.claude/(?:scripts|settings\.json)",
    }
    missing = [
        name
        for name, pattern in required.items()
        if not re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    ]

    assert not missing, f"SKILL.md missing hook boundary wording: {missing}"


def test_hooks_sync_docs_present_explicit_legacy_repair_boundary():
    """hooks sync 문서는 자동 canonical setup이 아닌 legacy/source-dev repair여야 한다."""
    path = REPO_ROOT / "skills" / "_shared" / "hooks-sync.md"
    text = _read_text(path)
    lower = text.lower()

    required_terms = {
        "hooks sync": r"hooks sync",
        "project legacy / source-dev helper": r"project legacy / source-dev helper",
        "repair": r"repair",
        "source-dev": r"source-dev",
        "non-canonical boundary": (
            r"(not canonical|canonical setup이 아니라|canonical runtime이 아니|"
            r"canonical runtime 아님)"
        ),
    }
    missing = [
        term
        for term, pattern in required_terms.items()
        if not re.search(pattern, lower, flags=re.IGNORECASE)
    ]
    assert not missing, f"{_relative(path)} missing hooks sync boundary terms: {missing}"

    forbidden = [
        r"canonical runtime으로 자동",
        r"일반 프로젝트.*자동 동기화",
    ]
    for pattern in forbidden:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        assert not matches, (
            f"{_relative(path)} presents hooks sync like automatic canonical setup: "
            f"{pattern!r} matches={matches}"
        )


def test_release_docs_include_hook_change_checklist_requirements():
    """릴리스 문서는 hook 변경 시 필요한 manifest/cache/test 검증을 모두 안내해야 한다."""
    path = REPO_ROOT / "docs" / "RELEASE.md"
    text = _read_text(path)
    required = {
        "plugin manifest": r"(plugin manifest|\.claude-plugin/plugin\.json|plugin\.json)",
        "hooks.json registration": r"hooks/hooks\.json",
        "source hooks": r"(source hooks|source `?hooks/`?|원본.*hooks)",
        "plugin cache packaging": r"(plugin cache packaging|cache packaging|plugin cache|캐시.*패키징)",
        "docs/tests consistency": r"(docs/tests|docs.*tests|문서.*테스트)",
        "no-injection tests": r"(no-injection|no hook injection|test_mst_on_no_hook_injection)",
        "cleanup tests": r"(cleanup|test_mst_on_cleanup)",
        "sync tests": r"(sync|hooks sync|test_sync_plugin_cache)",
        "worktree tests": r"(worktree|워크트리)",
        "global hook tests": r"(global hook|user-global|전역.*hook|test_global_user_hooks_safety)",
    }
    missing = [
        name
        for name, pattern in required.items()
        if not re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    ]

    assert not missing, f"{_relative(path)} missing hook release checklist items: {missing}"


def test_docs_legacy_claude_hooks_references_have_allowed_context():
    """.claude/hooks 언급은 legacy/source-dev/cleanup/repair 등 허용 맥락이어야 한다."""
    failures = []
    allowed = [
        re.compile(pattern, flags=re.IGNORECASE)
        for pattern in LEGACY_HOOK_ALLOWED_CONTEXT_PATTERNS
    ]

    for path in DOC_LEGACY_HOOK_REFERENCE_PATHS:
        lines = _read_text(path).splitlines()
        for index, line in enumerate(lines):
            if ".claude/hooks" not in line:
                continue
            context = _line_context(lines, index)
            if not any(pattern.search(context) for pattern in allowed):
                failures.append(
                    f"{_relative(path)}:{index + 1} lacks allowed legacy context:\n"
                    f"{context}"
                )

    assert not failures, "\n\n".join(failures)


def test_docs_do_not_present_project_hooks_or_settings_as_canonical_runtime():
    """일반 프로젝트 .claude/hooks/settings hooks block은 canonical runtime으로 보이면 안 된다."""
    failures = []
    canonical_patterns = [
        re.compile(pattern, flags=re.IGNORECASE)
        for pattern in PROJECT_HOOK_CANONICAL_PATTERNS
    ]
    negation_patterns = [
        re.compile(pattern, flags=re.IGNORECASE)
        for pattern in PROJECT_HOOK_NEGATION_PATTERNS
    ]

    for path in DOC_LEGACY_HOOK_REFERENCE_PATHS:
        lines = _read_text(path).splitlines()
        for index, line in enumerate(lines):
            if not any(pattern.search(line) for pattern in canonical_patterns):
                continue
            context = _line_context(lines, index)
            if any(pattern.search(context) for pattern in negation_patterns):
                continue
            failures.append(
                f"{_relative(path)}:{index + 1} presents project hook as canonical:\n"
                f"{context}"
            )

    assert not failures, "\n\n".join(failures)


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
