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

## Post-Execution (MANDATORY)

`/mst:plan -a -> /mst:request -a -> /mst:approve -a -> /mst:accept` chain이 완료되면, `/mst:accept` 직후 아래 두 명령을 반드시 순서대로 실행한다.
슬롯(`{AGI_ID}`, `{N}`, `{PLN_ID}`, `{REQ_ID}` 등)은 parent dispatch 조립 단계에서 치환된다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} --status {success|failed} --planned "..." --completed "..." --pln {PLN_ID} --req {REQ_ID} --sprint-kind user_observable --user-observable-change "..." --json
python3 {PLUGIN_ROOT}/scripts/mst.py agile retrospective {AGI_ID} --sprint {N} --status done --succeeded "..." --failed '[]' --velocity-planned N --velocity-completed N --limitations "..." --lessons "..." --direction "..." --json
```
