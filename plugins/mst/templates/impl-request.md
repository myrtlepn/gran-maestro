# Implementation Request — Self-Exploration Mode

- Request: {{REQ_ID}} / Task: {{TASK_ID}}
- Worktree: {{WORKTREE_PATH}}
- Spec: {{SPEC_PATH}}
- Plan: {{PLAN_PATH}}

## Plan JSON 메타 컨텍스트

반드시 Read 하세요: 아래 경로의 `plan.json`을 Read하여 plan 메타(cynefin_domain, linked_objective, linked_intent, linked_captures)를 확인하세요. 미존재 시 이 섹션을 skip합니다.

{{PLAN_JSON_META}}

## PAC 수락 기준 목록

반드시 Read 하세요: 아래 경로의 `plan.ids.json`을 Read하여 PAC 등급(id/grade/tags/text)을 확인하세요. 미존재 시 이 섹션을 skip합니다.

{{PAC_LIST}}

## Agile Objective 컨텍스트

반드시 Read 하세요: 아래 경로의 `objective.md`를 Read하여 JTBD 요약·프로젝트 DoD·성공 지표를 확인하세요. 미존재 시 이 섹션을 skip합니다.

{{OBJECTIVE_SECTION}}

## DOD-003 CONTEXT_FILES

[CONTEXT_FILES]
- objective: `OBJECTIVE_SECTION`에 주입된 `objective.md` 경로 또는 `NO_LINKED_OBJECTIVE`
- objective_ids: `OBJECTIVE_SECTION`에 주입된 `objective.ids.json` 경로 또는 `NO_OBJECTIVE_IDS`
- plan: `{{PLAN_PATH}}` 또는 `NO_SOURCE_PLAN`
- plan_json: `PLAN_JSON_META`에 주입된 `plan.json` 경로 또는 `NO_PLAN_JSON`
- plan_ids: `PAC_LIST`에 주입된 `plan.ids.json` 경로 또는 `NO_PLAN_IDS`
- spec: `{{SPEC_PATH}}`
- spec_context_manifest: `{{SPEC_PATH}}#§0-Context-Manifest` 또는 `NO_CONTEXT_MANIFEST`
- previous_feedback: `{{PREV_FEEDBACK_PATH}}` 또는 `N/A`
[/CONTEXT_FILES]

누락 컨텍스트는 조용히 생략하지 말고 `NO_LINKED_OBJECTIVE`, `NO_OBJECTIVE_IDS`, `NO_SOURCE_PLAN`, `NO_PLAN_JSON`, `NO_PLAN_IDS`, `NO_CONTEXT_MANIFEST`, `missing_context`, 또는 명시적 skip reason으로 남기세요.

## DOD-003 WORK_CONTRACT

[WORK_CONTRACT]
- read_requirements: 구현 전 위 context file과 spec `§0 Context Manifest` 파일을 직접 Read/inspection한다.
- output_contract: 변경 파일 목록, 생성/수정한 테스트, completion report, `Read/inspection evidence`를 보고한다.
- verification_contract: `verify_cmd`, `expected_signal`, 실행 결과를 보고한다.
- failure_contract: `timeout`, `empty result`, `blocked`, `missing_context` 상태를 구조화해 남긴다.
[/WORK_CONTRACT]

## 원본 문서 직접 확인 계약

source_plan이 있는 경우 구현 전 PM 요약이 아니라 아래 원본을 직접 Read/inspection 하세요.

- `{{SPEC_PATH}}` 및 해당 파일의 `## §0 Context Manifest`에 나열된 모든 파일
- `{{PLAN_PATH}}`가 `NO_SOURCE_PLAN`이 아니면 해당 `plan.md`
- `PLAN_JSON_META`에 주입된 `plan.json` 경로와 `linked_intent` 원본 또는 조회 결과
- `PAC_LIST`에 주입된 `plan.ids.json` 경로와 PAC 원문(id/grade/tags/text)
- `OBJECTIVE_SECTION`에 주입된 `objective.md`/`objective.ids.json` 경로가 있으면 해당 원본
- `OBJECTIVE_SECTION` 또는 spec `§0 Context Manifest`에 `context-transfer-contract.md`가 있으면 해당 원본

linked objective/intent 또는 PAC 파일이 없는 legacy plan은 해당 산출물만 graceful skip하고, `plan.md`, `plan.json`, `plan.ids.json`(존재 시), spec `§0 Context Manifest` 확인 지시는 유지하세요.

완료 보고에는 `Read/inspection evidence`를 남기세요: 확인한 원본 파일 경로, 확인한 핵심 섹션(예: `§0 Context Manifest`, `plan.md`, `plan.ids.json`, linked objective/intent), 그리고 PM 요약과 원본 사이의 불일치 여부를 간단히 기록합니다. `completion report`에는 변경 파일 목록, 생성/수정한 테스트, `verify_cmd`, `expected_signal`, 실행 결과를 포함하세요.

## 구현 컨텍스트 (PM 작성)

{{IMPL_CONTEXT}}

## 자기탐색 지시

아래 순서로 스펙을 직접 탐색하라. PM이 제공한 요약에 의존하지 말고 원본 파일을 직접 읽어라.

0. `{{SPEC_PATH}}`의 `## §0 Context Manifest` 섹션을 확인하고, 나열된 파일 목록을 구현 전 가장 먼저 Read하라 (목록이 비어있거나 파일이 없으면 경고 후 다음 단계 진행)
1. 스펙 직접 읽기: `cat {{SPEC_PATH}}` (또는 Read 도구)
1.1. plan 직접 읽기 (source_plan이 있는 경우만): `{{PLAN_PATH}}`가 `NO_SOURCE_PLAN`이 아니면 `cat {{PLAN_PATH}}` (또는 Read 도구), `NO_SOURCE_PLAN`이면 source_plan 없음으로 보고 이 단계를 skip
1.2. source_plan이 있는 경우 `PLAN_JSON_META`, `PAC_LIST`, `OBJECTIVE_SECTION`에 주입된 원본 경로를 직접 Read/inspection하고, 존재하지 않는 linked objective/intent는 `NO_LINKED_OBJECTIVE`, `NO_OBJECTIVE_IDS`, `NO_PLAN_JSON`, `NO_PLAN_IDS`, `missing_context`, 또는 명시적 skip 사유를 기록하라
1.5. §10 UI 설계(Stitch) 섹션에 "구현 코드" 경로가 있으면 해당 HTML 파일을 Read하여 디자인 시안을 파악하되, 기술 스택에 맞게 구현하세요 (HTML을 그대로 복사하지 말 것)
2. §2 변경 범위의 파일 목록 파악
3. §3 수락 조건을 기준으로 구현
4. [MANDATORY] §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요 (커밋은 PM이 처리)
5. 완료 시 `completion report`에 변경 파일 목록, 생성/수정한 테스트, `verify_cmd`, `expected_signal`, 실행 결과, `missing_context` 또는 skip 사유를 남겨라

## 이전 피드백 (Phase 4 → 재실행 시)

{{PREV_FEEDBACK_PATH}}

(첫 실행 시: N/A — 이 섹션을 무시하라)

## 규칙

- spec §2의 변경 범위 외 파일 수정 금지
- 추가 기능, 리팩토링, 스타일 변경 금지
- git commit은 하지 마세요 — PM이 직접 커밋합니다
- [MANDATORY] 완료 전 §5 테스트 명령어를 실행하고 출력 전체를 응답에 포함하세요
- `test_enforcement.backend_tdd=true`일 때 — 테스트를 먼저 작성한 후 구현하세요 (TDD)
