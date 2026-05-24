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

## 프로젝트 완료 기준 (DoD)

> 모든 항목은 관찰 가능한 결과 중심으로 작성하고, 구현 방법/기술 선택을 강제하지 않는다.
> 우선순위는 MoSCoW를 반영해 `priority`에 기록한다.

- [ ] DOD-001: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
  - Detail (optional): {외부 참조만으로 부족할 때 보충 설명}
<!-- dod:DOD-001 status:todo priority:must -->

- [ ] DOD-002: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- dod:DOD-002 status:todo priority:must -->

- [ ] DOD-003: {완료 시 관찰 가능한 결과 한 줄 요약}
  - Direction: {최소화 | 최대화 | 보장 | 유지}
  - Measure: {관찰/측정 가능한 지표}
  - Object: {측정 대상}
  - Context: {측정 조건/상황}
  - Target: {수치 목표 또는 기대 결과}
<!-- dod:DOD-003 status:todo priority:must -->

---

## 설계 결정 (Architecture Decisions)

> 구현 이전에 확정해야 할 설계 결정을 기록한다.

| ID | 결정 내용 | 근거 | 영향 범위 | 상태 |
|----|-----------|------|-----------|------|
| ADR-001 | {핵심 설계 결정} | {왜 이 결정을 했는가} | {영향 받는 영역} | proposed |

---

## 제약사항 (Out-of-scope / 기술 / 비즈니스)

### Out-of-scope
- {이번 범위에서 명시적으로 제외할 항목}

### 기술적 제약
- {사용/금지 기술, 버전, 도구, 플랫폼 제약}

### 비즈니스 제약
- {일정, 예산, 규정, 조직 의존성 등}

---

## 우선순위 (MoSCoW)

- **Must**
  - {없으면 프로젝트 실패로 간주되는 항목}
- **Should**
  - {중요하지만 단계적 적용 가능한 항목}
- **Could**
  - {여유가 있을 때 적용할 항목}
- **Won't (this time)**
  - {이번 범위에서 명시적으로 제외하는 항목}

---

## 프로젝트 NFR

| 분류 | 요구사항 | 측정 방식 |
|------|----------|-----------|
| 성능 | {응답시간/처리량/부하 목표} | {측정 기준} |
| 보안 | {인증/인가/데이터 보호 요구} | {검증 기준} |
| 호환성/접근성 | {브라우저/OS/디바이스/접근성 요구} | {검증 기준} |
| 오류 처리 | {실패 시 동작/복구/알림 정책} | {검증 기준} |

---

## 리스크 레지스터

| 리스크 | 가능성 | 영향 | 완화 방안 | 상태 |
|--------|--------|------|-----------|------|
| {주요 리스크} | {Low/Med/High} | {Low/Med/High} | {대응 전략} | open |

---

## 참조 레퍼런스

> Reference Lookup Protocol로 검증된 근거만 기록한다.

- REF-001: {주제} | {url} | {핵심 요약} | {fresh|stale|expired}

---

## 변경 이력

> 상태 변경은 `mst.py agile objective-transition` 및 `objective-check`로만 수행한다.
> 버전 스냅샷: `objective/history/v{N}.md` | 변경 로그: `objective/changelog.ndjson`

| 버전 | 날짜 | 변경 내용 | 변경 사유 |
|------|------|-----------|-----------|
| v1 | {YYYY-MM-DD} | 최초 생성 | Q&A 또는 기존 문서 파싱 |

---

## 상세 문서 (Details)

> objective.md는 인덱스/요약을 유지하고, 상세 원문은 `details/*.md`에 보존한다.

- [details/domain-a.md](details/domain-a.md) | 도메인: {도메인명} | 요약: {핵심 요약 1줄}
- [details/domain-b.md](details/domain-b.md) | 도메인: {도메인명} | 요약: {핵심 요약 1줄}
