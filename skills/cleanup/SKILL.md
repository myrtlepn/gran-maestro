---
name: cleanup
description: "세션을 일괄 정리합니다. ideation/discussion/debug/plans은 최근 N개만 유지하고, completed requests를 최소 유지 갯수 이상 아카이브하며, 오래된 활성 requests는 사용자 선택으로 정리합니다. 사용자가 '정리', '클린업', '청소'를 말하거나 /mst:cleanup을 호출할 때 사용."
user-invocable: true
argument-hint: "[--run] [--dry-run]"
---

# maestro:cleanup

한 번의 호출로 ideation, discussion, debug, plans, requests를 일괄 정리합니다. Maestro 모드 활성 여부 무관.

## archive 스킬과의 차이

| 항목 | `/mst:cleanup` | `/mst:archive` |
|------|---------------|----------------|
| 목적 | **한 번에 전부** 정리 | 타입별 세밀 관리 |
| 동작 | 3단계 자동 + 인터랙티브 | 수동 지정 |
| 복원 | 지원 안 함 (`/mst:archive --restore` 사용) | 지원 |
| 대상 | ideation + discussion + debug + plans + requests 일괄 | `--type`으로 개별 지정 |

## 설정 참조

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get cleanup)`의 `cleanup` 섹션:

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `ideation_keep_count` | 10 | ideation 세션 유지 갯수 |
| `discussion_keep_count` | 10 | discussion 세션 유지 갯수 |
| `debug_keep_count` | 10 | debug 세션 유지 갯수 |
| `plan_keep_count`      | 10 | plans 세션 유지 갯수 |
| `request_keep_count`   | 10 | requests 최소 유지 갯수 (최신 N개 보존) |
| `old_request_threshold_hours` | 24 | 오래된 requests 판단 기준 (시간) |

설정 없으면 기본값 사용.

## 실행 프로토콜

<!-- @include _shared/path-rules.md -->
> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
<!-- @end-include -->

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (AskUserQuestion 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 `AskUserQuestion`과 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->

### 인자 없음: 정리 대상 미리보기

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get cleanup archive)`로 `cleanup`/`archive` 설정 로드 → 각 타입 스캔:
- **Ideation/Discussion/Debug**: 각 타입 디렉토리에서 `session.json`의 `created_at`/`status` 읽기 → 내림차순 정렬 → keep_count 초과 중 `done`/`completed` 세션 수 카운트
- **Plans**: `plans/PLN-*`의 `plan.json`에서 `status`/`created_at` 읽기 → 내림차순 정렬 → `plan_keep_count` 초과 중 `completed`/`archived` 상태 카운트
- **Requests (자동)**: `request.json`에서 `done`/`completed`/`cancelled` 선별 → 최신 `request_keep_count`개 제외 후 아카이브 대상 카운트
- **Requests (인터랙티브)**: 미완료 요청 중 `old_request_threshold_hours` 이상 경과 카운트

미리보기 표시:

```
Gran Maestro — Cleanup 미리보기
═══════════════════════════════════════

[자동 정리]
  ideation    : 3개 세션 아카이브 대상 (유지: 10, 현재: 13, 완료: 3)
  discussion  : 0개 (유지: 10, 현재: 5)
  debug       : 0개 (유지: 10, 현재: 2)
  plans       : 2개 아카이브 대상 (유지: 10, 현재: 12, 완료: 2)
  requests    : 5개 done/completed/cancelled 아카이브 대상 (유지: 10, 현재: 15)

[인터랙티브 정리]
  requests    : 1개 활성 요청이 24시간 이상 경과
    REQ-013: JWT 인증 구현 (phase2_execution, 3일 전)

실행하려면: /mst:cleanup --run
```

### `--run`: 정리 실행

3단계로 순차 실행.

#### Step 1: Ideation / Discussion / Debug / Plans 정리 (자동)

각 타입별로: 스캔 → `created_at` 내림차순 정렬 → 최근 `{type}_keep_count`개 유지 → 나머지 중 `done`/`completed`만 아카이브 대상 (진행 중 세션 보호) → `{type}/archived/` 생성 후 tar.gz 압축:
```bash
tar -czf {PROJECT_ROOT}/.gran-maestro/{type}/archived/{type}-{ID_from}-{ID_to}-{YYYYMMDD}.tar.gz \
  -C {PROJECT_ROOT}/.gran-maestro/{type} {session_dirs...}
```
원본 삭제 → `[Cleanup] {type} {N}개 아카이브됨`

Plans 정리: `plans/PLN-*` 스캔 → `plan.json`의 `created_at` 내림차순 정렬 → 최근 `plan_keep_count`개 유지 → 나머지 중 `status`가 `completed` 또는 `archived`인 것만 아카이브 대상 (`active` 상태 보호) → `plans/archived/` 생성 후 tar.gz 압축:
```bash
tar -czf {PROJECT_ROOT}/.gran-maestro/plans/archived/plans-{ID_from}-{ID_to}-{YYYYMMDD}.tar.gz \
  -C {PROJECT_ROOT}/.gran-maestro/plans {plan_dirs...}
```
원본 삭제 → `[Cleanup] plans {N}개 아카이브됨`

#### Step 2: Completed Requests 정리 (자동, 최소 유지 적용)

`requests/REQ-*` 스캔 → `request.json`의 `created_at` 내림차순 정렬 → `done`/`completed`/`cancelled` 선별 → 최신 `request_keep_count`개는 보존 (keep count 내 완료 요청 보호) → 나머지 아카이브 대상 → tar.gz 압축 후 원본 삭제 → `[Cleanup] requests {N}개 아카이브됨`

#### Step 3: 오래된 활성 Requests 인터랙티브 정리

1. 남은 REQ-* 중 `old_request_threshold_hours` 이상 경과한 요청 필터링
2. 대상 없으면 스킵
3. `AskUserQuestion` 멀티 토글 (최대 4개, 오래된 순; label: `{REQ-ID}: {title 앞 20자}`, description: 상태/생성 시각)
4. 4개 초과 시 가장 오래된 4개만 표시 후 재실행 안내
5. 선택된 요청 개별 tar.gz 압축 후 원본 삭제 → `[Cleanup] {N}개 아카이브됨 (사용자 선택)`
6. 미선택 시: `오래된 요청 정리를 건너뛰었습니다.`

#### 최종 결과 표시

```
Gran Maestro — Cleanup 완료
═══════════════════════════════════════

ideation    : 3개 아카이브됨 → ideation-IDN001-IDN003-20260218.tar.gz
discussion  : 0개 (정리 대상 없음)
debug       : 0개 (정리 대상 없음)
plans       : 2개 아카이브됨 → plans-PLN001-PLN002-20260218.tar.gz
requests    : 5개 done/completed 아카이브됨 → requests-REQ001-REQ005-20260218.tar.gz
              1개 사용자 선택 아카이브됨 → requests-REQ013-20260218.tar.gz

총 6개 세션 정리 완료
```

### `--dry-run`: 모의 실행

`--run`과 동일 로직이나 실제 압축/삭제 없이 `[DRY-RUN]` 접두어로 대상만 표시. Step 3의 AskUserQuestion도 호출하지 않고 대상 목록만 표시.

```
Gran Maestro — Cleanup 모의 실행
═══════════════════════════════════════

[DRY-RUN] ideation: 3개 아카이브 예정
  IDN-001 (completed, 2026-02-10)
  IDN-002 (completed, 2026-02-11)
  IDN-003 (completed, 2026-02-12)

[DRY-RUN] discussion: 정리 대상 없음

[DRY-RUN] plans: 2개 아카이브 예정
  PLN-001 (completed, 2026-02-10)
  PLN-002 (completed, 2026-02-11)

[DRY-RUN] requests (done/completed): 2개 아카이브 예정
  REQ-001 (completed, 2026-02-05)
  REQ-002 (cancelled, 2026-02-08)

[DRY-RUN] requests (오래된 활성): 1개 사용자 선택 대상
  REQ-013: JWT 인증 구현 (phase2_execution, 3일 전)

실행하려면: /mst:cleanup --run
```

## 진행 중 세션 보호 규칙

- **자동 정리 (Step 1, 2)**: `done`/`completed`/`cancelled` 세션만 아카이브
- **Plans**: `plan.json`의 `status`가 `active`인 플랜은 아카이브 제외
            (`completed`, `archived` 상태만 아카이브 대상)
- **인터랙티브 정리 (Step 3)**: 사용자 명시 선택 세션만 아카이브 (상태 무관)
- 진행 중 세션은 keep count 초과여도 자동 삭제 안 함

## 에러 처리

| 상황 | 대응 |
|------|------|
| `.gran-maestro/` 디렉토리 없음 | "Maestro가 초기화되지 않았습니다. `/mst:on`으로 시작하세요." |
| `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get cleanup)` 결과에 `cleanup` 섹션 없음 | 기본값 사용 (`keep=10, threshold=24h`) |
| tar 명령 실패 | 에러 메시지 표시, 원본 보존 (삭제하지 않음) |
| `session.json` / `request.json` 파싱 실패 | 해당 세션 건너뛰고 경고 표시 |
| 아카이브 디렉토리 쓰기 불가 | 권한 확인 안내 |

## 예시

```
/mst:cleanup               # 정리 대상 미리보기
/mst:cleanup --run         # 3단계 정리 실행
/mst:cleanup --dry-run     # 모의 실행 (변경 없이 대상만 표시)
```

## 문제 해결

- "정리 대상 없음" → 세션이 keep count 이내이거나 completed/오래된 requests 없음
- "진행 중 세션 정리 불가" → Step 1/2가 자동 보호; 강제 정리는 `/mst:archive --run`
- 복원 필요 시 → `/mst:archive --restore {ID}` (cleanup 스킬은 복원 미지원)
