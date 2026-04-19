from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_LINE = (
    '- 합리화 패턴: "컨텍스트가 길어졌으니/토큰 효율을 위해/변경 추적 품질을 위해 '
    '다음 단계를 새 세션에서 진행하는 게 낫다." | 확인 증거: 자동 연쇄 진입 '
    '컨텍스트 블록의 수치(context_pct, auto_approve_on_unblock)를 인용하여 chain '
    "지속이 정상 경로임을 명시한 뒤 다음 스킬을 자동 호출한다."
)


def test_auto_chain_context_guard_line_exists_in_entrypoint_skills():
    for relative_path in (
        "skills/approve/SKILL.md",
        "skills/request/SKILL.md",
        "skills/plan/SKILL.md",
    ):
        content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "## Anti-Rationalization Checklist" in content
        assert GUARD_LINE in content, relative_path
