# Implementation Spec

- Request ID: {REQ_ID}
- Task ID: {TASK_ID}
- Created: {DATE}
- Status: pending | queued | executing | pre_check | pre_check_failed | review | feedback | merging | merge_conflict | done | failed | cancelled
- Assigned Agent: [config: {DEFAULT_AGENT}] → [도메인: {추론된 도메인}] → 최종: {에이전트}
- Assigned Team: {에이전트 팀 구성 설명}
- Worktree: {PROJECT_ROOT}/.gran-maestro/worktrees/{TASK_ID}
- Complexity: {Lite | Standard | High-Risk}

## §0 Context Manifest

> 구현 시작 전 이 목록의 파일을 가장 먼저 Read하세요.
> 이 목록이 완전하지 않을 수 있으며, 에이전트는 자율 탐색을 유지해야 합니다.

- {필수 컨텍스트 파일 경로 1}
- {필수 컨텍스트 파일 경로 2}
- {필수 컨텍스트 파일 경로 3}

## §1 요약 (Summary)

{모든 구현 태스크 완료 후 수행할 통합 테스트 태스크의 목적을 1~2문장으로 기술}

## §2 테스트 범위 (Scope: Integration / Incremental / Regression)

- **통합 검증 (Integration Validation)**: {구현 태스크 간 연동 동작과 E2E 흐름 검증 범위}
- **증분 테스트 (Incremental Test)**: {이번 변경으로 추가/수정된 기능의 핵심 시나리오 검증 범위}
- **회귀 테스트 (Regression Test)**: {변경 영향권 내 기존 기능 정상 동작 검증 범위}

## §3 통합 AC (Integrated Acceptance Criteria)

> 구현 태스크들의 AC를 종합하여 Given/When/Then + Test 형식으로 재구성합니다.

#### AC-001 [MUST] [manual]
Given: {모든 구현 태스크가 완료됨}
When: {주요 사용자/시스템 통합 시나리오 실행}
Then: {구현 태스크들의 핵심 AC가 충돌 없이 함께 충족됨}
Test: {통합 검증 절차 또는 명령}

#### AC-002 [MUST] [automatable]
Given: {변경된 기능과 연관된 테스트 환경 준비}
When: {증분 테스트 + 회귀 테스트 실행}
Then: {신규/변경 기능은 정상 동작하고 기존 기능 회귀가 없음}
Test: {실행 명령어 또는 자동화 스크립트}

## §4 회귀 테스트 항목 (Regression Checklist)

- [ ] {회귀 테스트 항목 1 — PM 영향도 분석 기반}
- [ ] {회귀 테스트 항목 2}

## §5 의존성 (Dependencies)

- 선행 작업 (blockedBy): [{구현 태스크 ID 전체}]
- 후행 작업 (blocks): []

## §6 에이전트 팀 구성 (Agent Team)

- 실행: {에이전트명} ({도메인})
- 사유: {선택 이유}
