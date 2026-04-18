from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_accept_step_0_1_doc_exists():
    skill_doc = ROOT / "skills" / "accept" / "SKILL.md"
    assert skill_doc.exists(), f"missing file: {skill_doc}"
    content = skill_doc.read_text(encoding="utf-8")
    assert "Step 0.1: 자율 모드 감지" in content
    assert "AUTO_MODE" in content
    assert "-a" in content


def test_accept_keeps_auto_mode_and_dag_policy_separation():
    skill_doc = ROOT / "skills" / "accept" / "SKILL.md"
    content = skill_doc.read_text(encoding="utf-8")

    assert "AUTO_MODE와 DAG 연쇄 정책 분리" in content
    assert "workflow.auto_approve_on_unblock" in content
    assert "approve의 auto-accept guard 차단은 AUTO_MODE와 별개" in content
