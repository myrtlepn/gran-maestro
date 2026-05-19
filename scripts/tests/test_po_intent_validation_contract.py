from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
IMPL_REQUEST = REPO_ROOT / "templates" / "impl-request.md"
APPROVE_SKILL = REPO_ROOT / "skills" / "approve" / "SKILL.md"
REVIEW_SKILL = REPO_ROOT / "skills" / "review" / "SKILL.md"
ACCEPT_SKILL = REPO_ROOT / "skills" / "accept" / "SKILL.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_source_plan_impl_prompt_requires_original_document_inspection() -> None:
    impl = _text(IMPL_REQUEST)
    approve = _text(APPROVE_SKILL)

    assert "원본 문서 직접 확인 계약" in impl
    assert "PM 요약" in impl
    assert "Read/inspection" in impl
    assert "§0 Context Manifest" in impl
    assert "plan.md" in impl
    assert "plan.json" in impl
    assert "plan.ids.json" in impl
    assert "linked_intent" in impl
    assert "objective.md" in impl
    assert "objective.ids.json" in impl
    assert "PAC 원문(id/grade/tags/text)" in impl

    assert "linked_intent" in approve
    assert "intent get {INTENT_ID}" in approve
    assert "plan.ids.json" in approve
    assert "id`, `grade`, `tags`, `text`" in approve
    assert "PM 작성 요약만 신뢰하지 말고" in approve
    assert "Read/inspection evidence" in approve
    assert "NO_SOURCE_PLAN" in approve


def test_review_po_intent_validation_contract_matches_accept_schema() -> None:
    review = _text(REVIEW_SKILL)
    accept = _text(ACCEPT_SKILL)

    for required in (
        "po_intent_validation",
        "verdict",
        "compared_sources",
        "compared_changes",
        "rationale",
        "missing_or_mismatched_intent",
    ):
        assert required in review
        assert required in accept

    assert "PASS | FAIL | SKIP" in review
    assert "po-intent-validation.json" in review
    assert "review.json.po_intent_validation" in review
    assert "original_documents" in review
    assert "plan" in review
    assert "plan_ac" in review
    assert "spec_intent_trace" in review
    assert "changed_file | diff" in review
    assert "PM 요약만 근거" in review
    assert "PASS 금지" in review

    assert "po_intent_validation.verdict == PASS" in accept
    assert "expected=PASS" in accept
    assert "compared_sources 비어 있음" in accept
    assert "compared_changes 비어 있음" in accept
    assert "rationale 누락" in accept
    assert "missing_or_mismatched_intent 누락" in accept


def test_accept_blocks_without_latest_completed_po_pass() -> None:
    accept = _text(ACCEPT_SKILL)

    assert "request.json`의 `review_iterations` 배열만 사용" in accept
    assert "status == \"completed\"" in accept
    assert "가장 뒤의 completed 항목" in accept
    assert "다른 REQ의 review artifact" in accept
    assert "최신 completed review artifact 없음" in accept
    assert "po_intent_validation 없음" in accept
    assert "verdict != \"PASS\"" in accept
    assert "FAIL`, `SKIP`, 빈 값, 알 수 없는 값" in accept


def test_po_pass_does_not_offset_existing_gates() -> None:
    accept = _text(ACCEPT_SKILL)
    review = _text(REVIEW_SKILL)

    assert "PAC/objective/evidence-ledger 검증 전용" in accept
    assert "서로 대체 관계가 아니다" in accept
    assert "기존 PAC/objective/evidence-ledger 검증을 약화하거나 대체하지 않는다" in accept
    assert "상쇄할 수 없다" in accept
    assert "위 5번 또는 6번에서 이미 블로킹된 실패" in accept

    assert "기존 `intent_fidelity` 산출물이나 blocking 판정을 대체하지 않는다" in review
    assert "기존 PAC/objective/evidence-ledger 실패" in review
    assert "blocking 모드 intent_fidelity 실패를 상쇄할 수 없다" in review


def test_legacy_without_source_plan_skips_po_gate_without_failing() -> None:
    impl = _text(IMPL_REQUEST)
    review = _text(REVIEW_SKILL)
    accept = _text(ACCEPT_SKILL)

    assert "source_plan이 있는 경우" in impl
    assert "graceful skip" in impl
    assert "legacy plan" in impl

    assert "source_plan`이 없으면 `po_intent_validation.verdict=\"SKIP\"" in review
    assert "reason=\"NO_SOURCE_PLAN\"" in review
    assert "원본 비교를 임의 PASS 처리하지 않는다" in review

    assert "PO intent validation gate skip: reason=NO_SOURCE_PLAN" in accept
    assert "PO gate로 실패시키지 않는다" in accept
    assert "다음 단계 진행 (하위 호환)" in accept
