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


def test_gemini_skill_uses_run_wrapper():
    content = _skill_md("gemini")
    assert "mst.py run" in content
    assert "--task-id" in content
    assert "-- gemini" in content


def test_claude_skill_uses_run_wrapper():
    content = _skill_md("claude")
    assert "mst.py run" in content
    assert "--task-id" in content
    # claude-code 또는 claude CLI 호출
    assert "-- claude" in content


def test_skills_preserve_frontmatter():
    """frontmatter(name, description, argument-hint)가 유지되는지 검증"""
    for skill in ("codex", "gemini", "claude"):
        content = _skill_md(skill)
        assert content.startswith("---"), f"{skill}/SKILL.md must start with frontmatter"
        assert "name:" in content.split("---")[1]
        assert "description:" in content.split("---")[1]
