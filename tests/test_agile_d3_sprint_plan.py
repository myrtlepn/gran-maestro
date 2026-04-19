"""AC-001~005 검증: d3.sprint_plan_threshold + Step 3.9 agile 분기 + 재지시 루프."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_config_has_sprint_plan_threshold():
    cfg_path = PROJECT_ROOT / "templates" / "defaults" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    d3 = cfg.get("d3", {})
    assert d3.get("sprint_plan_threshold") == 0.15
    assert d3.get("max_escalation_retries", 3) == 3


def test_plan_skill_has_sprint_plan_threshold_branch():
    skill_path = PROJECT_ROOT / "skills" / "plan" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert "sprint_plan_threshold" in text
    assert "agile_context_active" in text
    # 두 키워드가 Step 3.9 맥락에서 함께 등장하는지 확인 (간단 휴리스틱)
    # Step 3.9 섹션 추출
    step_39_start = text.find("### Step 3.9")
    assert step_39_start >= 0
    step_39_end = text.find("\n### Step 4", step_39_start)
    if step_39_end < 0:
        step_39_end = len(text)
    step_39_section = text[step_39_start:step_39_end]
    assert "sprint_plan_threshold" in step_39_section
    assert "agile_context_active" in step_39_section


def test_plan_skill_has_redirect_loop_spec():
    skill_path = PROJECT_ROOT / "skills" / "plan" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    # 재지시 루프 관련 키워드
    assert "재지시" in text or "redirect" in text.lower()
    assert "max_escalation_retries" in text
    assert "known-issues" in text or "known_issues" in text


def test_plan_skill_requires_easy_option_labels():
    skill_path = PROJECT_ROOT / "skills" / "plan" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert "선택지 표기 형식" in text
    assert "알파벳 또는 숫자만" in text
    assert "금지 예시: `α`, `β`, `γ`, `i`, `ii`, `iii`, `I`, `II`, `III`" in text


def test_agile_plan_skill_requires_easy_option_labels():
    skill_path = PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert "질문/선택지 표기 규칙" in text
    assert "알파벳 또는 숫자만" in text
    assert "그리스 문자·로마 숫자 금지" in text
    assert "[objective 후보] A) {후보1} B) {후보2} C) {후보3}" in text
