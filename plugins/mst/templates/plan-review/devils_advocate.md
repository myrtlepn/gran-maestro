# Plan Review — Devil's Advocate (DEPRECATED)

> ⚠️ 이 템플릿은 더 이상 plan review에서 사용되지 않습니다.
> plan review는 전략적 수준(intent_validator, scope_critic)으로 재설계되었습니다.
> 대안 탐색은 plan의 ideation/discussion 또는 Strategic Review의 외부 리서치에서 수행됩니다.

# Plan Review — Devil's Advocate

- Plan ID: {{PLN_ID}}

## 리뷰 관점

PM의 가정에 반론을 제기하라. 숨겨진 복잡도, 엣지 케이스, 더 나은 대안의 존재 여부를 탐색하라. 낙관적 가정에 의문을 제기하고, 접근 방식의 리스크와 비용을 명시하라.

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
