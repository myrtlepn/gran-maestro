# Plan Review — Completeness (DEPRECATED)

> ⚠️ 이 템플릿은 더 이상 plan review에서 사용되지 않습니다.
> 구현 완전성 검토는 /mst:request 단계의 Spec Pre-review Pass에서 수행됩니다.
> plan review는 전략적 수준(intent_validator, scope_critic)으로 재설계되었습니다.

# Plan Review — Completeness

- Plan ID: {{PLN_ID}}

## 리뷰 관점

요구사항 완전성을 검토하라. 누락된 기능, 미정의 동작, 측정 불가능한 수락 조건, 범위 모호함을 찾아라. 하위 호환성, 마이그레이션, 에러 핸들링이 다루어졌는지 확인하라.

## 플랜 초안

{{PLAN_DRAFT}}

## Q&A 컨텍스트

{{QA_SUMMARY}}

## 출력 형식

이슈가 없으면 첫 줄에 "NO_ISSUES"만 반환.

이슈가 있으면 아래 형식으로 반환:

CRITICAL: {제목} — {설명} (사용자에게 반드시 질문 필요)
MAJOR: {제목} — {설명} (PM이 판단 필요)
MINOR: {제목} — {설명} (PM이 자체 처리 가능)

각 항목은 한 줄, 최대 10개.
