# Objective: {프로젝트 이름}

> AGI-ID: {AGI-NNN}
> 생성일: {YYYY-MM-DD}
> 버전: v1
> 상태: active

---

## JTBD 레이어

| 필드 | 내용 |
|------|------|
| **When I** | {어떤 상황/컨텍스트에서} |
| **I want to** | {달성하고 싶은 핵심 목표} |
| **So I can** | {기대되는 가치/결과} |
| **성공 지표** | {측정 가능한 완료 기준 — 예: "X 기능이 Y 조건에서 Z ms 이내 응답"} |
| **Definition of Done** | {프로젝트 전체 완료를 판단하는 구체적인 기준} |

---

## Epic/Story 레이어

<!-- Epic 형식: ### Epic-{N}: {제목} -->
<!-- Story 형식: - [ ] S{NN}: {제목} | status: {todo|in_progress|done|blocked} | priority: {high|medium|low} | deps: [{S-ID}] | sprint_target: {N|TBD} -->

### Epic-1: {Epic 제목}

> 설명: {이 Epic이 다루는 범위와 목적}

- [ ] S01: {Story 제목} | status: todo | priority: high | deps: [] | sprint_target: 1
- [ ] S02: {Story 제목} | status: todo | priority: medium | deps: [S01] | sprint_target: 2

### Epic-2: {Epic 제목}

> 설명: {이 Epic이 다루는 범위와 목적}

- [ ] S03: {Story 제목} | status: todo | priority: high | deps: [] | sprint_target: 1
- [ ] S04: {Story 제목} | status: todo | priority: low | deps: [S03] | sprint_target: TBD

---

## Checklist 레이어

<!-- 각 Story에 대한 테스트/문서/리뷰 게이트를 정의합니다 -->
<!-- 형식: #### S{NN} 게이트 -->

#### S01 게이트
- [ ] 테스트: {단위 테스트 / 통합 테스트 / E2E 테스트 요건}
- [ ] 문서: {작성해야 할 문서 또는 "해당 없음"}
- [ ] 리뷰: {리뷰 필요 여부 및 리뷰어 또는 "자동 승인"}

#### S02 게이트
- [ ] 테스트: {단위 테스트 / 통합 테스트 / E2E 테스트 요건}
- [ ] 문서: {작성해야 할 문서 또는 "해당 없음"}
- [ ] 리뷰: {리뷰 필요 여부 및 리뷰어 또는 "자동 승인"}

#### S03 게이트
- [ ] 테스트: {단위 테스트 / 통합 테스트 / E2E 테스트 요건}
- [ ] 문서: {작성해야 할 문서 또는 "해당 없음"}
- [ ] 리뷰: {리뷰 필요 여부 및 리뷰어 또는 "자동 승인"}

#### S04 게이트
- [ ] 테스트: {단위 테스트 / 통합 테스트 / E2E 테스트 요건}
- [ ] 문서: {작성해야 할 문서 또는 "해당 없음"}
- [ ] 리뷰: {리뷰 필요 여부 및 리뷰어 또는 "자동 승인"}

---

## 변경 이력

> 상태 변경은 `mst.py agile objective-transition` 및 `objective-check`로만 수행합니다.
> 버전 스냅샷: `objective/history/v{N}.md` | 변경 로그: `objective/changelog.ndjson`

| 버전 | 날짜 | 변경 내용 | 변경 사유 |
|------|------|-----------|-----------|
| v1 | {YYYY-MM-DD} | 최초 생성 | Q&A 또는 기존 문서 파싱 |
