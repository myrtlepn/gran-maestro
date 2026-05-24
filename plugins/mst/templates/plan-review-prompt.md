# Plan Review Request — {{ROLE}}

- Plan ID: {{PLN_ID}}
- Role: {{ROLE}}

## 리뷰 관점 (Perspective)

{{PERSPECTIVE}}

## 검토 대상 — 플랜 초안

{{PLAN_DRAFT}}

## 사용자 Q&A 컨텍스트

{{QA_SUMMARY}}

## 역할별 PERSPECTIVE 참조

<!-- architect: 시스템 정합성·실현 가능성·기존 아키텍처 충돌 -->
<!-- devils_advocate: PM 가정 반론·엣지 케이스·리스크·대안 존재 여부 -->
<!-- completeness: 누락 기능·미정의 동작·측정 불가 AC·범위 모호함 -->
<!-- ux_reviewer: UI 흐름 모호함·접근성·인터랙션 누락·사용자 경험 -->

## 출력 형식 (Output Format)

이슈가 없으면 첫 줄에 "NO_ISSUES"만 반환.

이슈가 있으면 아래 형식으로 반환:

CRITICAL: {제목} — {설명} (사용자에게 반드시 질문 필요)
MAJOR: {제목} — {설명} (PM이 판단 필요)
MINOR: {제목} — {설명} (PM이 자체 처리 가능)

각 항목은 한 줄, 최대 10개.
