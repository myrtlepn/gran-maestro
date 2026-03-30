# Objective: {프로젝트 이름}

> AGI-ID: {AGI-NNN}
> 생성일: {YYYY-MM-DD}
> 버전: v1
> 상태: active

---

## 진행 상태 요약

- 진행률: `0/0 (0.0%)`
- 완료 기준: `status:done`인 DoD 수 / 전체 DoD 수
> 주석: 본 objective에는 스프린트 횟수/완료 시점 예측을 기재하지 않는다.

---

## JTBD 레이어

| 필드 | 내용 |
|------|------|
| **When I** | {어떤 상황/컨텍스트에서} |
| **I want to** | {달성하고 싶은 핵심 목표} |
| **So I can** | {기대되는 가치/결과} |
| **성공 지표** | {측정 가능한 완료 기준} |
| **프로젝트 DoD** | {프로젝트 완료를 판정하는 상위 기준} |

---

## Epic 의존성 / 순서

```text
EPIC-001 -> EPIC-002 -> EPIC-003 -> EPIC-004 -> EPIC-005
```

---

## Epic 레이어 (목표 + 구조화 DoD 체크리스트)

### EPIC-001: {Epic 목표 제목}

> 목표: {이 Epic이 달성해야 할 관찰 가능한 결과}

- [ ] DOD-001: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
  - Detail (optional): {외부 참조만으로 부족할 때 보충 설명}
<!-- epic:EPIC-001 dod:DOD-001 status:todo -->
- [ ] DOD-002: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-001 dod:DOD-002 status:todo -->
- [ ] DOD-003: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-001 dod:DOD-003 status:todo -->

### EPIC-002: {Epic 목표 제목}

> 목표: {이 Epic이 달성해야 할 관찰 가능한 결과}

- [ ] DOD-004: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-002 dod:DOD-004 status:todo -->
- [ ] DOD-005: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-002 dod:DOD-005 status:todo -->
- [ ] DOD-006: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-002 dod:DOD-006 status:todo -->

### EPIC-003: {Epic 목표 제목}

> 목표: {이 Epic이 달성해야 할 관찰 가능한 결과}

- [ ] DOD-007: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-003 dod:DOD-007 status:todo -->

### EPIC-004: {Epic 목표 제목}

> 목표: {이 Epic이 달성해야 할 관찰 가능한 결과}

- [ ] DOD-008: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-004 dod:DOD-008 status:todo -->

### EPIC-005: {Epic 목표 제목}

> 목표: {이 Epic이 달성해야 할 관찰 가능한 결과}

- [ ] DOD-009: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- epic:EPIC-005 dod:DOD-009 status:todo -->

---

## 변경 이력

> 상태 변경은 `mst.py agile objective-transition` 및 `objective-check`로만 수행합니다.
> 버전 스냅샷: `objective/history/v{N}.md` | 변경 로그: `objective/changelog.ndjson`

| 버전 | 날짜 | 변경 내용 | 변경 사유 |
|------|------|-----------|-----------|
| v1 | {YYYY-MM-DD} | 최초 생성 | Q&A 또는 기존 문서 파싱 |
