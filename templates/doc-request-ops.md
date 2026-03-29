# Documentation Request — Self-Exploration Mode (Ops)

- Request: {{REQ_ID}} / Task: {{TASK_ID}}
- Worktree: {{WORKTREE_PATH}}
- Spec: {{SPEC_PATH}}
- Plan: {{PLAN_PATH}}

## 문서 컨텍스트 (PM 작성)

{{DOC_CONTEXT}}

## 자기탐색 지시

아래 순서로 스펙을 직접 탐색하라. PM이 제공한 요약에 의존하지 말고 원본 파일을 직접 읽어라.

0. `{{SPEC_PATH}}`의 `## §0 Context Manifest` 섹션을 확인하고, 나열된 파일 목록을 문서 작성 전 가장 먼저 Read하라 (목록이 비어있거나 파일이 없으면 경고 후 다음 단계 진행)
1. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구)
1.1. plan 직접 읽기 (source_plan이 있는 경우만): `{{PLAN_PATH}}`가 `"N/A"`가 아니면 `cat {{PLAN_PATH}}` (또는 Read 도구), `"N/A"`면 source_plan 없음으로 보고 이 단계를 skip
2. `§2 변경 범위`와 `§3 수락 조건`에서 문서 대상 파일/섹션, TOC, 소스 목록, 검증 계획을 추출하라
3. 운영 문서 구조를 아래 템플릿으로 작성하라
   - `Trigger`
   - `Steps`
   - `Escalation`
   - `Rollback`
4. 실행 절차 작성: 단계별로 명령어/기대 결과/실패 신호를 포함해 작성하라
5. 명령어 검증: Steps에 포함된 각 명령어를 dry-run 기준으로 검증하고 결과를 기록하라
6. 롤백 절차 작성: 실패 시 되돌리는 명령/조건/완료 기준을 명확히 작성하라
7. 팩트체크/검증 분기: `sub_type=operational` (`verification=operational_validity`) 규칙으로 claim 단위 `verified|failed|unverified` 판정 후 근거를 기록하라. 실패/미확정 claim은 재작성 후 재검증하라
   - `commands_valid`: 명령어 유효성이 검증되었는가 (dry-run 또는 동등 검증 포함)
   - `rollback_defined`: 롤백 절차가 존재하고 실행 조건이 명시되었는가
8. [MANDATORY] 최종 응답에 "절차 작성 → dry-run 검증 → 롤백 검증" 결과를 순서대로 요약해 포함하라 (커밋은 PM이 처리)

## 이전 피드백 (Phase 4 → 재실행 시)

{{PREV_FEEDBACK_PATH}}

(첫 실행 시: N/A — 이 섹션을 무시하라)

## 규칙

- spec §2의 변경 범위 외 파일 수정 금지
- 추가 기능, 리팩토링, 스타일 변경 금지
- git commit은 하지 마세요 — PM이 직접 커밋합니다
- [MANDATORY] 운영 절차 검증 결과(명령어 유효성, 롤백 존재)와 claim별 판정(verified/failed/unverified)을 응답에 포함하세요
- 불확실한 내용은 단정하지 말고 `failed` 또는 `unverified`로 표시하세요
