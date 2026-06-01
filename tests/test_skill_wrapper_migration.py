from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _skill_md(name: str) -> str:
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_codex_skill_uses_run_wrapper():
    content = _skill_md("codex")
    assert "mst.py run" in content, "codex SKILL.md must invoke mst.py run wrapper"
    # wrapper 호출 형식 검증: run --task-id ... -- codex exec
    assert "--task-id" in content
    assert "-- codex exec" in content or "-- codex" in content


def test_agy_skill_uses_run_wrapper():
    content = _skill_md("agy")
    assert "mst.py run" in content
    assert "--task-id" in content
    assert "-- agy --print" in content


def test_gemini_skill_is_deprecated_wrapper():
    content = _skill_md("gemini")
    assert "Deprecated compatibility wrapper" in content
    assert "/mst:agy" in content
    assert "gemini -p" not in content


def test_claude_skill_uses_run_wrapper():
    content = _skill_md("claude")
    assert "mst.py run" in content
    assert "--task-id" in content
    assert "--provider claude" in content
    assert "provider-owned subprocess" in content


def test_skills_preserve_frontmatter():
    """frontmatter(name, description, argument-hint)가 유지되는지 검증"""
    for skill in ("codex", "agy", "gemini", "claude"):
        content = _skill_md(skill)
        assert content.startswith("---"), f"{skill}/SKILL.md must start with frontmatter"
        assert "name:" in content.split("---")[1]
        assert "description:" in content.split("---")[1]


def test_skills_document_task_id_placeholder():
    """AC-004: 3개 SKILL.md에 {task_id} placeholder 유도 규칙 명시"""
    for skill in ("codex", "agy", "claude"):
        content = _skill_md(skill)
        assert "{task_id}" in content, f"{skill}: {{task_id}} 언급 없음"
        assert "Placeholder 유도 규칙" in content or "REQ-ID" in content, (
            f"{skill}: placeholder 유도 규칙 문서화 누락"
        )


def test_codex_skill_model_resolve_simplified():
    """AC-005: skills/codex/SKILL.md의 모델 resolve 방법 A/B 블록 제거"""
    content = _skill_md("codex")
    assert "방법 A" not in content, "방법 A 블록이 아직 남아있음"
    assert "방법 B" not in content, "방법 B 블록이 아직 남아있음"
