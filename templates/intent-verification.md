# Intent Verification Template

> approve 스킬 Step 5.7(설계 의도 검증 루프)에서 검증 에이전트에게 전달하는 프롬프트 템플릿입니다.
> PM Conductor가 변수를 치환한 뒤 검증 에이전트에 전달합니다.
> 출력 포맷은 §2.2 기준을 따릅니다 (verification-loop-design.md).

<intent_verification>
<context>
You are a verification agent for Gran Maestro approve workflow (Step 5.7).
Your task is to compare the plan's design intent against the actual implementation
in the worktree and produce a structured verification report.

Request: {REQ_ID}
Plan: {PLN_ID}
Iteration: {ITERATION}
Worktree path: {WORKTREE_PATH}
</context>

<comparison_targets>
## 비교 대상

### Architecture Decisions (AD 목록)

{AD_LIST}

### Plan Acceptance Criteria (PAC 목록)

{PAC_LIST}

### 구조 명세 (Structure Spec)

{STRUCTURE_SPEC}
</comparison_targets>

<judgment_criteria>
## 판정 기준

각 항목(AD, PAC, 구조 명세)에 대해 아래 3단계 기준으로 판정합니다.

- **반영됨**: plan에 명시된 결정/조건이 코드에서 관찰 가능한 형태로 구현됨
- **부분반영**: 결정의 일부만 구현되었거나, 의도는 맞지만 누락된 세부사항이 있음
- **미반영**: 결정이 코드에 반영되지 않았거나, 상충하는 구현이 존재함

판정 시 반드시 코드의 구체적 증거(파일명, 함수명, 라인 등)를 근거로 제시하세요.
추론이나 가정이 아닌 실제 관찰된 코드를 기반으로 판정합니다.
</judgment_criteria>

<output_format>
## 출력 포맷

아래 구조를 그대로 따라 리포트를 작성하세요. 섹션 순서와 표 구조를 변경하지 마세요.

---

# 설계 의도 검증 리포트

> REQ: {REQ_ID}
> Plan: {PLN_ID}
> Iteration: {ITERATION}
> 생성일: {YYYY-MM-DD HH:MM}

## 요약

| 구분 | 반영됨 | 부분반영 | 미반영 | 합계 |
|------|--------|----------|--------|------|
| AD | {n} | {n} | {n} | {n} |
| PAC (MUST) | {n} | {n} | {n} | {n} |
| PAC (SHOULD) | {n} | {n} | {n} | {n} |
| 구조 명세 | {n} | {n} | {n} | {n} |

## 항목별 판정

### AD-001: {결정 제목}
- **판정**: 반영됨 / 부분반영 / 미반영
- **근거**: {코드에서 확인한 구체적 증거 — 파일명, 함수명, 구현 패턴 등}
- **미반영 내용** (해당 시): {누락된 부분 설명}

### PAC-001: {PAC 설명}
- **판정**: 반영됨 / 부분반영 / 미반영
- **근거**: {코드에서 확인한 구체적 증거}
- **미반영 내용** (해당 시): {누락된 부분 설명}

(모든 AD 및 PAC 항목에 대해 위 구조를 반복합니다)

## 보완 필요 항목 (미반영 + 부분반영)

1. {항목 ID}: {보완 내용 요약}
2. ...

(미반영 및 부분반영 항목이 없으면 "보완 필요 항목 없음"으로 표기합니다)

---
</output_format>

<rules>
- 판정은 반드시 3가지 중 하나로만 표기하세요: "반영됨", "부분반영", "미반영"
- 근거는 구체적인 코드 증거를 포함해야 합니다 (파일명, 함수명, 코드 패턴 등)
- "미반영 내용" 필드는 판정이 "미반영" 또는 "부분반영"인 경우에만 작성합니다
- 요약 테이블의 합계는 반영됨 + 부분반영 + 미반영의 합이어야 합니다
- "보완 필요 항목" 섹션에는 미반영과 부분반영 항목 모두 포함합니다
- 비교 대상이 없는 구분(예: 구조 명세가 없는 경우)은 요약 테이블에서 해당 행을 제외합니다
</rules>
</intent_verification>

## 변수 목록

| 변수 | 설명 | 소스 |
|------|------|------|
| `{PLN_ID}` | Plan ID | `request.json`의 `source_plan` 필드 |
| `{REQ_ID}` | Request ID | `request.json`의 `id` 필드 |
| `{AD_LIST}` | plan의 Architecture Decision 목록 | `plans/PLN-NNN/plan.md` `## Architecture Decisions` 섹션 |
| `{PAC_LIST}` | Plan Acceptance Criteria 목록 (ID, grade, 설명) | `plans/PLN-NNN/plan.ids.json` |
| `{STRUCTURE_SPEC}` | 디렉토리 구조, 모듈 분리, 데이터 흐름 등 구조 명세 | `plans/PLN-NNN/plan.md` 관련 섹션 |
| `{WORKTREE_PATH}` | 구현 태스크가 커밋된 git worktree 경로 | `request.json`의 `worktree` 필드 |
| `{ITERATION}` | 현재 검증-보완 루프 반복 횟수 (1부터 시작) | Step 5.7 루프 카운터 |
