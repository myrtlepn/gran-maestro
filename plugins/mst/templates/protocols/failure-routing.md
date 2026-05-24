# Failure Routing Protocol

## 실패 분류별 자동 라우팅

`failure_class` 값에 따라 아래 라우팅을 자동으로 수행합니다:

| failure_class | 라우팅 대상 | 판단 기준 |
|---|---|---|
| `ac_unclear` | PM spec 재정의 태스크 생성 (Phase 1 보완 우선) | Given/When/Then이 비어 있거나 측정 불가 표현으로 AC 판정 자체가 불가능한 경우 |
| `interpretation` | Dev Agent 재작업 외주 (의도 보강 포함) | 실행은 되지만 결과가 AC `Then`과 불일치하는 경우 |
| `implementation` | Dev Agent 버그 수정 외주 (`evidence` 첨부) | 예외/타입/빌드/테스트 실패 등 실행 오류가 확인된 경우 |

## 실행 프로토콜 Step 3 라우팅

> 이 Step의 목적: 실패 원인을 `failure_class`로 고정하고 후속 경로를 결정한다 / 핵심 출력물: `failure_class` 기반 라우팅 결정

| failure_class | 라우팅 대상 | 판단 기준 |
|---|---|---|
| `ac_unclear` | Phase 1 보완 (PM spec 보강 후 승인 대기) | AC 자체가 모호해 통과/실패 판정이 불가능한 경우 (예: Given/When/Then 누락, 측정 불가 표현) |
| `interpretation` | Phase 2 재실행 (의도 정렬 중심 재외주) | 실행은 되지만 AC `Then`이 요구한 동작과 다른 결과가 나오는 경우 |
| `implementation` | Phase 2 재실행 (오류 수정 중심 재외주) | 예외, TypeError, 빌드 실패, 테스트 assertion 실패 등 실행 오류가 발생한 경우 |

- **설계 재검토 (PM 판단)**: `failure_class` 3종으로 분류 불가한 경우에만 PM이 명시적으로 `/mst:ideation` 호출
  - 해당 사례: 요구사항 자체가 변경됨
  - 해당 사례: 동일 태스크 재작업 반복에도 AC를 충족할 수 없는 구조적 한계
  - 해당 사례: 기술 스택 변경 또는 아키텍처 전면 재설계 필요
