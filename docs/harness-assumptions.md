# Gran Maestro Harness — 구성요소별 필요성 가정

> 원칙: "harness의 모든 구성요소는 모델이 독립적으로 수행할 수 없다는 가정을 인코딩하며,
> 이 가정은 스트레스 테스트할 가치가 있다."
> — Anthropic, "Harness design for long-running application development"

## 구성요소별 가정 테이블

| 구성요소 | 가정 (이것이 없으면?) | 스트레스 테스트 방법 |
|---------|---------------------|-------------------|
| Spec Prereview | 모델이 한 번에 좋은 스펙을 못 쓴다 → prereview 없으면 스펙 품질 저하, 리뷰 iteration 증가 | prereview 생략 후 review iteration 횟수 비교 |
| Design Wing (Architect/Schema/UI) | 모델이 아키텍처/스키마/UI를 동시에 고려 못 한다 → Wing 없으면 설계 일관성 저하 | Wing 없이 복잡한 요청 실행 후 아키텍처 리뷰 점수 비교 |
| Pass B 병렬 리뷰어 | 단일 리뷰어가 모든 관점을 놓친다 → 병렬 리뷰 없으면 이슈 탐지율 저하 | 리뷰어 1명으로 축소 후 미발견 이슈 비율 측정 |
| Sprint 구조 (agile) | 모델이 대규모 작업을 한 번에 못 한다 → Sprint 없으면 작업 응집도 저하 | Sprint 없이 단일 세션으로 대규모 작업 실행 |
| impact_reviewer | 모델이 사이드 이펙트를 스스로 감지 못 한다 → impact review 없으면 회귀 버그 증가 | impact review 생략 후 회귀 테스트 실패율 비교 |

## 동적 복잡도 조절 매트릭스

요청 복잡도에 따라 활성화되는 구성요소:

| 구성요소 | 단순 (AC 1-2개, 단일 파일) | 중간 (AC 3-5개, 2-5 파일) | 복잡 (AC 6+개, 다수 파일) |
|---------|--------------------------|--------------------------|-------------------------|
| Spec Prereview | 생략 | 1회 | config 기본값 (최대 10회) |
| Design Wing | 생략 | 조건부 (arch_gate) | 전체 활성 |
| Pass B 리뷰어 | 1명 (code_reviewer만) | 3명 (code+arch+impact) | 전체 활성 (5-7명) |
| Sprint 구조 | N/A | N/A | 필요 시 활성 |
| impact_reviewer | 생략 | 활성 | 활성 |

## 모델 개선에 따른 재평가 가이드

1. 새 모델 릴리스 시 위 테이블의 "스트레스 테스트 방법"을 실행하여 각 구성요소의 필요성을 재평가
2. 구성요소가 불필요해졌다면 `config.harness.dynamic_complexity`에서 해당 threshold를 조정
3. 완전히 불필요해진 구성요소는 config에서 비활성화하되, 코드는 제거하지 않고 보존 (향후 모델 성능 변동 대비)
