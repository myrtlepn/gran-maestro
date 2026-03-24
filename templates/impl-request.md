# Implementation Request — Self-Exploration Mode

- Request: {{REQ_ID}} / Task: {{TASK_ID}}
- Worktree: {{WORKTREE_PATH}}
- Spec: {{SPEC_PATH}}
- Plan: {{PLAN_PATH}}

## 구현 컨텍스트 (PM 작성)

{{IMPL_CONTEXT}}

## 자기탐색 지시

아래 순서로 스펙을 직접 탐색하라. PM이 제공한 요약에 의존하지 말고 원본 파일을 직접 읽어라.

0. `{{SPEC_PATH}}`의 `## §0 Context Manifest` 섹션을 확인하고, 나열된 파일 목록을 구현 전 가장 먼저 Read하라 (목록이 비어있거나 파일이 없으면 경고 후 다음 단계 진행)
1. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구)
1.1. plan 직접 읽기 (source_plan이 있는 경우만): `{{PLAN_PATH}}`가 `"N/A"`가 아니면 `cat {{PLAN_PATH}}` (또는 Read 도구), `"N/A"`면 source_plan 없음으로 보고 이 단계를 skip
1.5. §10 UI 설계(Stitch) 섹션에 "구현 코드" 경로가 있으면 해당 HTML 파일을 Read하여 디자인 시안을 파악하되, 기술 스택에 맞게 구현하세요 (HTML을 그대로 복사하지 말 것)
2. §2 변경 범위의 파일 목록 파악
3. §3 수락 조건을 기준으로 구현
4. [MANDATORY] §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요 (커밋은 PM이 처리)

## 이전 피드백 (Phase 4 → 재실행 시)

{{PREV_FEEDBACK_PATH}}

(첫 실행 시: N/A — 이 섹션을 무시하라)

## 규칙

- spec §2의 변경 범위 외 파일 수정 금지
- 추가 기능, 리팩토링, 스타일 변경 금지
- git commit은 하지 마세요 — PM이 직접 커밋합니다
- [MANDATORY] 완료 전 §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요
- `test_enforcement.backend_tdd=true`일 때 — 테스트를 먼저 작성한 후 구현하세요 (TDD)
