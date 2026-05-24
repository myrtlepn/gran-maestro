# Debug Report — {SESSION_ID}

## 이슈
{ISSUE}

## Executive Summary
{3~5문장으로 조사 결과를 요약. Symptom/Hypothesis/Experiment/Result의 핵심 흐름과 최종 수정 방향을 한눈에 파악할 수 있도록 서술}

---

## 참여 조사자

| 조사자 | 역할 | 상태 | Provider |
|--------|------|------|----------|
| Claude | 자체 조사 (코드베이스 탐색 + 4-Phase 검증) | {done/failed} | claude |
{각 investigator별로 아래 형식을 반복}
| {INVESTIGATOR_KEY} | {ROLE} | {done/timeout/failed} | {PROVIDER} |

---

## 조사 결과 요약 (4-Phase)

{각 조사자별로 아래 형식을 반복}

### Claude (자체 조사)
#### Symptom (증상)
{관찰된 현상, 재현 조건, 영향 범위}

#### Hypothesis (가설)
{가능한 근본 원인 가설 1~3개와 우선순위}

#### Experiment (실험)
{가설 검증을 위해 수행한 절차/명령/코드 추적과 파일:라인}

#### Result (결과)
{실험 결과, 가설 채택/기각, 최종 결론, 수정 제안}

#### Open Questions (추가 조사 필요 영역)
{아직 검증되지 않은 항목}

### {INVESTIGATOR_KEY} ({ROLE})
#### Symptom (증상)
{관찰된 현상, 재현 조건, 영향 범위}

#### Hypothesis (가설)
{가능한 근본 원인 가설 1~3개와 우선순위}

#### Experiment (실험)
{가설 검증을 위해 수행한 절차/명령/코드 추적과 파일:라인}

#### Result (결과)
{실험 결과, 가설 채택/기각, 최종 결론, 수정 제안}

#### Open Questions (추가 조사 필요 영역)
{아직 검증되지 않은 항목}

---

## 교차 검증 (Cross-Validation)

여러 조사자의 Symptom/Hypothesis/Experiment/Result 일관성을 기준으로 확신도를 판정합니다.

| # | Symptom | Hypothesis | Experiment | Result | 지목한 조사자 | 확신도 | 파일 위치 |
|---|---------|------------|-----------|--------|-------------|--------|----------|
| 1 | {증상} | {가설} | {검증 절차} | {검증 결과} | {조사자 목록} | 높음/중간/낮음 | {file:line} |
| 2 | ... | ... | ... | ... | ... | ... | ... |

### 확신도 기준
- **높음**: 2명 이상이 동일 Symptom/Hypothesis를 제시하고, Experiment와 Result가 서로 일치
- **중간**: 1명 지목이지만 Experiment/Result 증거가 명확
- **낮음**: 가설 제시만 있고 Experiment/Result 근거가 약함 (추가 검증 필요)

---

## 근본 원인 분석 (Root Cause Analysis)

### 1차 원인 (가장 유력)
- **위치**: {file:line}
- **설명**: {근본 원인 상세 설명}
- **근거 (가설-실험-결과 연결)**: {어떤 가설이 어떤 실험으로 검증되었고 어떤 결과로 확정되었는지}
- **재현 경로**: {이 원인이 증상으로 이어지는 코드 경로}

### 2차 원인 (보조 요인, 해당 시)
- **위치**: {file:line}
- **설명**: {보조 원인 설명}
- **근거 (가설-실험-결과 연결)**: {근거}

---

## 수정 제안 (우선순위)

### 1순위: {수정 제안 제목} (필수)
- **대상 파일**: {file:line}
- **수정 내용**: {구체적 수정 방안}
- **예상 효과**: {이 수정이 해결하는 증상/가설}
- **주의사항**: {수정 시 영향 범위, 사이드이펙트}

### 2순위: {수정 제안 제목} (권장)
- **대상 파일**: {file:line}
- **수정 내용**: {구체적 수정 방안}
- **예상 효과**: {이 수정이 해결하는 증상/가설}

### 3순위: {수정 제안 제목} (선택, 해당 시)
- **대상 파일**: {file:line}
- **수정 내용**: {구체적 수정 방안}

---

## Architect Escalation (3회 연속 실패 시 자동 위임)

- **Triggered**: {yes/no}
- **Trigger Condition**: {3 consecutive failed fix attempts in same DBG session}
- **Triggered At**: {ISO-8601 or N/A}
- **Status**: {requested/completed/failed/N/A}
- **Reason**: {위임 사유}
- **Output**: {architect-review.md 경로 또는 N/A}

---

## 추가 조사 필요 영역

- {심층 분석이 필요한 미확인 영역}
- {타임아웃으로 조사가 완료되지 않은 영역}

## 관련 파일

| 파일 | 유형 | 설명 |
|------|------|------|
| finding-claude.md | Claude 조사 결과 | 자체 조사 상세 |
{각 investigator별}
| finding-{INVESTIGATOR_KEY}.md | {PROVIDER} 조사 결과 | {ROLE} 상세 |
