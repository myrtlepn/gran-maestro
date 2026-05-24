---
name: archive
description: "세션 아카이브를 관리합니다. 오래된 ideation/discussion/request/capture 항목을 압축 보관하고, 아카이브 현황 조회/복원/삭제를 수행합니다. 사용자가 '아카이브', '정리', '세션 정리'를 말하거나 /mst:archive를 호출할 때 사용."
user-invocable: true
argument-hint: "[--run [--type {ideation|discussion|requests|cap}]] [--restore {ID}] [--purge [--max-age-days N] [--dry-run]] [--list]"
---

# maestro:archive

타입별(ideation/discussion/requests/captures) 최근 N개 항목만 활성 유지하고, 초과분을 `archived/`에 tar.gz 압축 보관합니다.

## 설정 참조

`Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get archive)`의 `archive` 섹션:

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `max_active_sessions` | 200 | 타입별 활성 유지 갯수 |
| `archive_retention_days` | 90 | 아카이브 보존 기간. 숫자=N일 후 purge 대상, 신규 프로젝트 기본값은 90일 |
| `auto_archive_on_create` | true | 새 세션 생성 시 자동 아카이브 체크 |
| `archive_directory` | `{type_dir}/archived` | 타입별 아카이브 저장 경로 (자동) |

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

### 인자 없음: 아카이브 현황 표시

`archive` 설정 로드 → 각 타입 디렉토리 스캔(IDN-*/DSC-*/REQ-* 수, CAP-* 수) + `archived/`의 tar.gz 파일 수/디스크 사용량 확인 → 현황 표시:

```
Gran Maestro — 아카이브 현황
═══════════════════════════════════════

설정: max_active=20, retention=90일, auto_archive=ON

타입         활성    아카이브   상태
─────────────────────────────────────
ideation     12      0         OK
discussion    8      0         OK
requests     23      0         초과 (3개 아카이브 대상)

아카이브 디스크 사용량: 0 B
```

### `--run`: 수동 아카이브 실행

`--type {ideation|discussion|requests|cap}`로 특정 타입만 실행 가능.

1. 대상 타입 스캔 → `session.json`/`request.json` 읽기
2. **진행 중 세션 보호**: `done`/`completed`/`cancelled` 아닌 세션은 절대 아카이브 금지
   - **captures 예외**: captures 타입은 status 기반이 아닌 TTL 기반 아카이브를 적용합니다. 7일 TTL 만료 + linked_plan 비활성인 캡처만 아카이브 대상이며, pending/selected 상태라도 TTL이 만료되면 아카이브됩니다.
3. 완료 세션을 `created_at` 오래된 순 정렬 → `max_active_sessions` 초과분 선별
4. `{type_dir}/archived/` 생성 후 tar.gz 압축 (원본 삭제):
   ```bash
   tar -czf {PROJECT_ROOT}/.gran-maestro/{type_dir}/archived/{type}-{ID_from}-{ID_to}-{YYYYMMDD}.tar.gz \
     -C {PROJECT_ROOT}/.gran-maestro/{type_dir} {session_dirs...}
   ```
5. `archive_retention_days` 기준으로 만료된 tar.gz를 purge 대상에 포함한다 (mtime 기준, 기본 90일)
6. 결과 요약 표시:

```
아카이브 완료
─────────────────────────────────────
requests: 3개 세션 아카이브됨
  → requests-REQ001-REQ003-20260217.tar.gz (24.5 KB)
  원본 삭제 완료

만료 아카이브 삭제: 0개
```

### `--restore {ID}`: 아카이브에서 세션 복원

1. ID 접두사(REQ/IDN/DSC/DBG/CAP)로 타입 결정 → `archived/`에서 해당 ID 포함 tar.gz 탐색
2. 목록 확인: `tar -tzf {archive_file} | grep {ID}`
3. 세션 디렉토리만 추출: `tar -xzf {archive_file} -C {PROJECT_ROOT}/.gran-maestro/{type_dir} {session_dir}`
4. 복원 결과 표시; 아카이브 파일 자체는 삭제 안 함

### `purge [--max-age-days N] [--dry-run]`: 오래된 아카이브 삭제

- 미지정: `archive.archive_retention_days` 기준 만료 파일 삭제 (기본 90일)
- `--max-age-days N`: 이번 실행에서만 N일보다 오래된 tar.gz를 삭제 대상으로 본다
- `--dry-run`: 삭제하지 않고 대상 목록과 총 byte만 출력한다
- 출력은 `Purged N archive(s), total B bytes (retention=Nd)` 형식이다

### `--list`: 아카이브된 세션 목록 표시

각 타입 `archived/`의 tar.gz 파일 스캔 → `tar -tzf {archive_file}`로 내용 확인 → 타입별 그룹화 표시:

```
Gran Maestro — 아카이브 목록
═══════════════════════════════════════

ideation (2 archives):
  ideation-IDN001-IDN005-20260210.tar.gz (15.2 KB)
    IDN-001, IDN-002, IDN-003, IDN-004, IDN-005
  ideation-IDN006-IDN010-20260215.tar.gz (18.7 KB)
    IDN-006, IDN-007, IDN-008, IDN-009, IDN-010

discussion (1 archive):
  discussion-DSC001-DSC003-20260212.tar.gz (8.3 KB)
    DSC-001, DSC-002, DSC-003

requests (1 archive):
  requests-REQ001-REQ010-20260214.tar.gz (42.1 KB)
    REQ-001 ~ REQ-010
```

## 자동 아카이브 프로토콜 (다른 스킬에서 호출)

`archive.auto_archive_on_create=true` 시 새 세션 생성 시점에 자동 체크:
1. 해당 타입 세션 수 확인 → `max_active_sessions` 초과 시:
   - 완료된(done/completed/cancelled) 세션만 아카이브 대상 → 오래된 순 정렬 → tar.gz 압축 + 원본 삭제
   - `[Archive] {type} {N}개 세션 아카이브됨 → {archive_filename}` 알림
2. 완료 후 새 세션 생성 진행

## 진행 중 세션 보호 규칙

`done`/`completed`/`cancelled` 아닌 모든 항목은 자동/수동 아카이브 모두에서 절대 아카이브 금지 (예: `analyzing`, `collecting`, `phase1_analysis`, `phase2_execution` 등).

Requests는 `ACTIVE_PHASE_STATUSES` guard도 적용한다. `pending`, `phase1_analysis`, `phase2_execution`, `reviewing`, `phase3_review`, `merging`, `merge_conflict` 등 활성 phase 요청은 오래되어도 stale/cleanup 후보에서 보호되며, gardening scan 요약의 `protected_active_requests`로 보호 건수를 확인할 수 있다.

## counter.json 보호 규칙

각 타입 디렉토리의 `counter.json`은 절대 삭제 금지 — ID 단조 증가 카운터로 아카이브/정리 대상 아님. `--run` 시 대상 디렉토리(IDN-*/DSC-*/DBG-*/REQ-*/CAP-*)만 처리, `counter.json`은 건드리지 않음.

## 디렉토리 구조

```
.gran-maestro/
├── ideation/
│   ├── IDN-* (active) + counter.json
│   └── archived/
│       └── ideation-IDN001-IDN005-20260217.tar.gz
├── discussion/
│   ├── DSC-* (active) + counter.json
│   └── archived/
│       └── discussion-DSC001-DSC003-20260217.tar.gz
├── requests/
│   ├── REQ-* (active) + counter.json
│   └── archived/
│       └── requests-REQ001-REQ010-20260217.tar.gz
├── captures/
│   ├── CAP-* (active) + counter.json
│   └── archived/
│       └── captures-CAP001-CAP003-20260217.tar.gz
├── debug/
│   ├── DBG-* + counter.json
│   └── archived/
└── plans/
    └── PLN-*.md
```

## 에러 처리

| 상황 | 대응 |
|------|------|
| `{type_dir}/archived/` 생성 실패 | 쓰기 권한 확인 안내 |
| tar 명령 실패 | 에러 메시지 표시, 원본 보존 (삭제하지 않음) |
| 복원 시 ID를 찾을 수 없음 | 아카이브 목록 표시 + 올바른 ID 안내 |
| 복원 대상 디렉토리가 이미 존재 | 덮어쓰기 전 사용자 확인 |
| `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get archive)` 결과에 archive 섹션 없음 | 기본값 사용 (max_active=20, retention=null, auto=true) |

## 예시

```
/mst:archive                          # 현황 표시
/mst:archive --run                    # 모든 타입 아카이브 실행
/mst:archive --run --type ideation    # ideation만 아카이브
/mst:archive --run --type cap          # captures만 아카이브 (TTL 기반)
/mst:archive --restore IDN-003        # IDN-003 복원
/mst:archive --list                   # 아카이브 목록
/mst:archive --purge                  # 기본 retention(90일) 기준 만료 아카이브 삭제
/mst:archive --purge --dry-run        # 삭제 없이 purge 대상 미리보기
/mst:archive --purge --max-age-days 30  # 30일보다 오래된 아카이브 삭제
```

## 문제 해결

- "아카이브 대상 없음" → 모든 세션 진행 중이거나 활성 수가 `max_active_sessions` 이하
- "복원 후 세션 미표시" → 복원된 `session.json`/`request.json` 상태 확인
- "디스크 부족" → `--purge --dry-run`으로 삭제 대상을 확인한 뒤 `--purge` 실행 또는 `archive_retention_days` 조정
