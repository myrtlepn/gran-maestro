# Sprint {CURRENT_SPRINT} Execution — {AGI_ID}

## Mission

아래 context 기반으로 Sprint {CURRENT_SPRINT}을 실행하라.
실행 체인: /mst:plan -a "{DoD 설명}" && /mst:request -a && /mst:approve -a && /mst:accept

## Context (7-Layer)

### [固定層] Objective
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
- JTBD, 프로젝트 DoD, 제약, 설계 결정, NFR, 리스크 포함

### [活性層] Selected DoD
이번 Sprint 대상 DoD:
{SELECTED_DOD_LIST}
- 각 DoD의 ID, 텍스트, priority, evidence 필드 포함

### [變化層] Previous Sprint Result
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/result.json
- 직전 Sprint에서 계획한 것, 완료한 것, PLN/REQ ID

### [回顧層] Previous Sprint Retrospective
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/retrospective.json
- lessons_learned: {PREVIOUS_LESSONS}
- direction: {PREVIOUS_DIRECTION}
- 이 교훈과 방향을 이번 Sprint 계획에 반영하라.

### [課題層] Open Known Issues
{KNOWN_ISSUES_TEXT}
- 열린 이슈가 있으면 health fix 우선

### [累積層] Integration Context (MANDATORY Read)
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/integration-context.md
- 파일 분류(modify/wire/new-island), entrypoint 상태, wire 통합 지점
- 이전 산출물 위에 쌓을지 / 고칠지 판단 필수

### [制約層] Project DoD + Success Metrics
프로젝트 완료 기준: objective.md의 프로젝트 DoD 섹션 참조
성공 지표: objective.md의 성공 지표 참조

## Execution Rules

1. `/mst:plan -a`에서 위 7-layer context를 활용하여 plan을 생성한다.
2. `/mst:request -a`에서 plan 기반으로 spec을 작성한다.
3. `/mst:approve -a`에서 태스크를 실행한다.
4. `/mst:accept`에서 결과를 머지한다.

## Post-Execution Records (MANDATORY)

chain 완료 후 반드시 아래를 기록하라. 기록 누락 시 Sprint가 failed로 처리된다.

### 1. Sprint Result

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{SELECTED_DOD_IDS}" \
  --completed "{COMPLETED_DOD_IDS}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --sprint-kind user_observable|foundational \
  --user-observable-change "{사용자가 이제 할 수 있는 것}" \
  --foundational-reason "{관찰 불가한 이유 + 향후 관찰 가능 계획}" \
  --sprint-goals '{JSON array}' \
  --previous-lessons "{PREVIOUS_LESSONS}" \
  --json
```

sprint-kind 판단 기준:
- `user_observable`: 사용자 진입점 1개 이상이 추가/변경되거나, 기존 진입점의 동작이 가시적으로 변하는 경우
- `foundational`: 테스트 환경, 내부 스키마, 헬퍼 등 사용자에게 보이지 않는 변경

### 2. Sprint Retrospective

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile retrospective {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --succeeded "{성공한 DOD IDs}" \
  --failed '{"item":"{DOD_ID}","cause":"{실패 원인}","attempt":"{시도한 접근"}"}' \
  --velocity-planned {계획 항목 수} \
  --velocity-completed {완료 항목 수} \
  --limitations "{발견된 제약/블로커}" \
  --lessons "{이번 Sprint에서 배운 교훈}" \
  --direction "{다음 Sprint 우선순위/방향 제안}" \
  --json
```

### 3. Dispatch Result

아래 JSON을 파일로 저장:
경로: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/dispatch-result.json`

```json
{
  "agi_id": "{AGI_ID}",
  "sprint": {CURRENT_SPRINT},
  "status": "success|failed",
  "pln_id": "{PLN_ID}",
  "req_id": "{REQ_ID}",
  "commit_sha": "{마지막 커밋 SHA}",
  "sprint_kind": "user_observable|foundational",
  "worktree_path": "{worktree 경로}",
  "exit_code": 0,
  "failure_reason": null,
  "files_changed": {변경 파일 수},
  "result_recorded": true,
  "retrospective_recorded": true
}
```
