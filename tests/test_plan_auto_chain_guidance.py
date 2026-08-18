from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_SKILL = REPO_ROOT / "skills" / "plan" / "SKILL.md"


def test_plan_auto_mode_finishes_the_nested_chain_without_stale_approve_guidance() -> None:
    content = PLAN_SKILL.read_text(encoding="utf-8")

    assert 'Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")' in content
    assert "approve -a → review --auto → accept -a" in content
    assert "전체 체인이 terminal success이면 `자동 체인 완료:` 블록으로 끝내고" in content
    assert "수동 `/mst:approve` 안내를 출력하지 않고" in content
    assert "자동 체인 완료:\n     request → approve → review → accept" in content


def test_plan_manual_mode_still_points_to_approve() -> None:
    content = PLAN_SKILL.read_text(encoding="utf-8")

    assert (
        "`AUTO_MODE=false`: plan 스킬 최종 마무리의 마지막 블록에 "
        "`다음 단계 실행 명령:\\n  /mst:approve REQ-NNN`을 출력한다."
    ) in content
