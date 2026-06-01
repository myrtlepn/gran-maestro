from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_SKILL = REPO_ROOT / "skills" / "plan" / "SKILL.md"
AGILE_PLAN_SKILL = REPO_ROOT / "skills" / "agile-plan" / "SKILL.md"


def test_plan_skill_finalizes_with_next_step_commands() -> None:
    text = PLAN_SKILL.read_text(encoding="utf-8")

    assert "다음 단계 실행 명령:" in text
    assert "/mst:request --plan PLN-NNN" in text
    assert "/mst:request --plan PLN-NNN -a" in text
    assert "/mst:approve REQ-NNN" in text
    assert "/mst:list" in text
    assert "마지막 줄 뒤에 추가 설명, 인사, 요약을 붙이지 않는다" in text


def test_agile_plan_skill_finalizes_with_next_step_commands() -> None:
    text = AGILE_PLAN_SKILL.read_text(encoding="utf-8")

    assert "다음 단계 실행 명령:" in text
    assert "/mst:agile --resume AGI-NNN" in text
    assert "/mst:agile --resume {AGI_ID}" in text
    assert "/mst:resume --wakeup-hint stop-recover" in text
    assert "[MST skill=agile-plan step=returned return_to={RETURN_TO}]" in text
    assert "마지막 줄 뒤에 추가 설명, 인사, 요약을 붙이지 않는다" in text
