# Plan Review — Architect (DEPRECATED)

> ⚠️ 이 템플릿은 더 이상 plan review에서 사용되지 않습니다.
> 코드 수준 아키텍처 검토는 /mst:request 단계의 Spec Pre-review Pass에서 수행됩니다.
> plan review는 전략적 수준(intent_validator, scope_critic)으로 재설계되었습니다.

- Plan ID: {{PLN_ID}}

## 리뷰 관점

시스템 정합성·실현 가능성 관점에서 검토하라. 기존 아키텍처와의 충돌, 의존성 누락, 레이어 위반, 기술 부채 관점에서 플랜의 맹점을 찾아라. 제안된 변경이 현재 코드베이스 패턴과 일관성이 있는지 확인하라.

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
