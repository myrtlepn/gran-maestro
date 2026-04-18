import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SKILL = REPO_ROOT / "skills" / "request" / "SKILL.md"
PLAN_SKILL = REPO_ROOT / "skills" / "plan" / "SKILL.md"
DEFAULTS_CONFIG = REPO_ROOT / "templates" / "defaults" / "config.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_defaults_define_shared_high_pass_guard_constants():
    cfg = json.loads(_read(DEFAULTS_CONFIG))
    workflow = cfg.get("workflow", {})
    guard = workflow.get("high_pass_guard")

    assert isinstance(guard, dict), "workflow.high_pass_guard must exist in defaults config"
    required_flags = [
        "enabled",
        "confidence_supporting_only",
        "require_external_execution_evidence",
        "require_independent_judgement",
        "block_self_report_only_pass",
        "plan_bypass_requires_explicit_rationale",
    ]
    for key in required_flags:
        assert key in guard, f"missing workflow.high_pass_guard.{key}"

    reason_tokens = guard.get("reason_tokens")
    assert isinstance(reason_tokens, dict), "reason_tokens must be a mapping"
    for key in (
        "self_report_only_block",
        "external_evidence_missing",
        "independent_judgement_required",
        "risk_signal_review_required",
    ):
        assert key in reason_tokens, f"missing reason token: {key}"


def test_request_reason_tokens_remain_aligned_with_defaults():
    cfg = json.loads(_read(DEFAULTS_CONFIG))
    reason_tokens = cfg["workflow"]["high_pass_guard"]["reason_tokens"]
    request_text = _read(REQUEST_SKILL)
    plan_text = _read(PLAN_SKILL)

    for key in reason_tokens:
        assert key in request_text, f"request skill must document reason token: {key}"

    assert "req-arch-decision.md" in request_text
    assert '"risk_signal_review_required"' in request_text
    assert "risk_signal_review_required" in plan_text


def test_request_arch_gate_blocks_confidence_only_close_on_risk_signal():
    text = _read(REQUEST_SKILL)

    assert "workflow.high_pass_guard" in text
    assert "confidence 값만으로 gate를 닫을 수 없다" in text
    assert "외부 실행 증거" in text
    assert "분리된 판정 단계" in text
    assert "plan 기반 명시적 우회 근거" in text
    assert "risk_signal_review_required" in text


def test_plan_auto_mode_treats_confidence_as_supporting_signal_only():
    text = _read(PLAN_SKILL)
    section_anchor = "#### [AUTO_MODE 판단 패턴] (Step 2~3, Step 3.8 공통)"
    start = text.find(section_anchor)
    assert start >= 0, "AUTO_MODE 판단 패턴 section must exist"

    end = text.find("\n### Step 2.1", start)
    section = text[start:] if end < 0 else text[start:end]

    assert "workflow.high_pass_guard" in section
    assert "confidence는 보조 신호" in section
    assert "self-report만으로 pass를 확정하지 않는다" in section
    assert "외부 실행 증거" in section
    assert "분리된 판정 단계" in section
    assert "confidence >= CONFIDENCE_THRESHOLD" in section

    hard_gate_idx = section.find("Hard Gate")
    confidence_idx = section.find("confidence >= CONFIDENCE_THRESHOLD")
    assert hard_gate_idx >= 0, "hard gate guidance must exist"
    assert confidence_idx > hard_gate_idx, "hard gate must be evaluated before confidence branch"
