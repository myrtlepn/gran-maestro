# Sprint {CURRENT_SPRINT} Execution — {AGI_ID}

## Mission

아래 context 기반으로 Sprint {CURRENT_SPRINT}을 실행하라.
실행 체인: /mst:plan -a "{DoD 설명}" && /mst:request -a && /mst:approve -a && /mst:accept
원문 대량 삽입 금지: prompt 본문에 objective/spec/plan 원문 전체를 복사하지 말고, 아래 path-first context contract를 기준으로 Read/inspection 후 실행하라.

## Context Contract

[CONTEXT_FILES]
- objective: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
- objective_ids: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json or NO_OBJECTIVE_IDS
- plan: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.md or NO_SOURCE_PLAN
- plan_json: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.json or NO_PLAN_JSON
- plan_ids: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.ids.json or NO_PLAN_IDS
- spec: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md or NO_ACTIVE_SPEC
- spec_context_manifest: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md#§0-Context-Manifest or NO_SPEC_CONTEXT_MANIFEST
- sprint_context: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/integration-context.md or NO_SPRINT_CONTEXT
- previous_feedback: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/retrospective.md or NO_PREVIOUS_FEEDBACK
- previous_result: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/result.json or NO_PREVIOUS_RESULT
[/CONTEXT_FILES]

[WORK_CONTRACT]
- read_requirements: 구현 전 위 context file과 spec §0 Context Manifest 파일을 직접 Read/inspection한다.
- output_contract: agile/agile-plan/prompt-template 변경 파일, dispatch result contract, completion report를 보고한다.
- verification_contract: verify_cmd, expected_signal, integration_smoke_id를 보고한다.
- failure_contract: timeout, empty result, blocked, missing_context 상태를 구조화해 남긴다.
[/WORK_CONTRACT]

[DISPATCH_RESULT_CONTRACT]
- dispatch_result_path: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/dispatch-result.json
- trace_path: {AGI_ID}/S{NN}/dispatch
- running_log_path: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/running.log
- success_signal: exit_code == 0 AND dispatch-result.json exists AND completion report includes verification evidence
- failure_signal: exit_code != 0 OR timeout OR empty result OR missing_context OR missing dispatch-result.json
- lifecycle_evidence: running log / trace / exit_code / output-failure contract / session metadata
[/DISPATCH_RESULT_CONTRACT]

[COMPLETION_REPORT]
- changed files
- simplifications made
- remaining risks
- Read/inspection evidence
- verification evidence
[/COMPLETION_REPORT]

## Context (7-Layer, Path-First)

### [固定層] Objective
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
- JTBD, 프로젝트 DoD, 제약, 설계 결정, NFR, 리스크 포함
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json (존재 시) and report `NO_OBJECTIVE_IDS` if absent

### [活性層] Selected DoD
이번 Sprint 대상 DoD:
{SELECTED_DOD_LIST}
- 각 DoD의 ID, 텍스트, priority, evidence 필드 포함
Read: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.md / plan.json / plan.ids.json when present, otherwise report `NO_SOURCE_PLAN`, `NO_PLAN_JSON`, `NO_PLAN_IDS`

### [變化層] Previous Sprint Result
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/result.json
- 직전 Sprint에서 계획한 것, 완료한 것, PLN/REQ ID

### [回顧層] Previous Sprint Retrospective
Read: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/retrospective.json
- lessons_learned: {PREVIOUS_LESSONS}
- direction: {PREVIOUS_DIRECTION}
- 이 교훈과 방향을 이번 Sprint 계획에 반영하라.
- retrospective 또는 evidence 파일이 없으면 `NO_PREVIOUS_FEEDBACK` 또는 `missing_context`로 보고한다.

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
Active spec이 있으면 Read: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md and spec §0 Context Manifest, 없으면 `NO_ACTIVE_SPEC`, `NO_SPEC_CONTEXT_MANIFEST`를 completion report에 남긴다.

## Execution Rules

1. `/mst:plan -a`에서 위 7-layer context와 `[CONTEXT_FILES]` block을 활용하여 plan을 생성한다.
2. `/mst:request -a`에서 plan 기반으로 spec을 작성한다.
3. `/mst:approve -a`에서 태스크를 실행한다.
4. `/mst:accept`에서 결과를 머지한다.
5. context file을 읽지 못했거나 spec §0 Context Manifest를 확인할 수 없으면 추론으로 메우지 말고 `missing_context` 또는 `NO_*` reason을 남긴다.
6. completion report에는 `changed files`, `simplifications made`, `remaining risks`, `Read/inspection evidence`, `verification evidence`를 반드시 포함한다.

## Post-Execution (MANDATORY)

`/mst:plan -a -> /mst:request -a -> /mst:approve -a -> /mst:accept` chain이 완료되면, `/mst:accept` 직후 아래 두 명령을 반드시 순서대로 실행한다.
슬롯(`{AGI_ID}`, `{N}`, `{PLN_ID}`, `{REQ_ID}` 등)은 parent dispatch 조립 단계에서 치환된다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} --status {success|failed} --planned "..." --completed "..." --pln {PLN_ID} --req {REQ_ID} --sprint-kind user_observable --user-observable-change "..." --json
python3 {PLUGIN_ROOT}/scripts/mst.py agile retrospective {AGI_ID} --sprint {N} --status done --succeeded "..." --failed '[]' --velocity-planned N --velocity-completed N --limitations "..." --lessons "..." --direction "..." --json
```

completion report에는 최소 아래 값을 포함한다:
- verify_cmd: {실행한 검증 명령}
- expected_signal: {성공 판정 신호}
- integration_smoke_id: {스모크/통합 검증 ID}
- dispatch_result_path: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/dispatch-result.json
- failure_status: `none | timeout | empty result | blocked | missing_context | exit_code_nonzero`
