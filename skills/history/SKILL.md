---
name: history
description: "완료된 요청의 이력을 조회합니다. 사용자가 '이력', '히스토리', '완료된 요청'을 말하거나 /mst:history를 호출할 때 사용. 활성 요청 목록은 /mst:list를, 특정 요청 상세 상태는 /mst:inspect를 사용."
user-invocable: true
argument-hint: "[{REQ-ID}] [--limit {N}]"
---

# maestro:history

완료된 요청의 이력을 조회합니다 (요약, 소요 시간, 에이전트 사용량, 피드백 라운드 수 등).

## DOD-005 session ledger contract

`/mst:history`는 완료된 요청 이력 조회 스킬이고, 실행 중 PM flow의 event source of truth는
`python3 {PLUGIN_ROOT}/scripts/mst.py history log|verify|head --session {mst_session_id}`입니다.
이 CLI는 `.gran-maestro/sessions/{mst_session_id}/history.*` 단일 ledger만 조회하며,
`mst_session_id` 단위 event row, append-only `history.head`/`history.verify`, split-ledger violation,
no legacy fallback 원칙을 공유합니다.

- `mst.py history log --session {mst_session_id}`: 같은 session ledger의 검증된 event row를 seq 순서로 조회합니다.
- `mst.py history verify --session {mst_session_id}`: ledger tail, local head, policy mirror head, verify state를 같은 session key로 대조합니다.
- `mst.py history head --session {mst_session_id}`: 검증된 append-only head를 표시합니다.
- `mst.py hook log`는 hook event 확인용 backward-compatible subset입니다. canonical query는 `mst.py history ... --session`입니다.
- DOD-005는 event row 조회와 head/verify 관찰 가능성까지만 포함합니다. DOD-006 recover bundle restoration과 DOD-017 dashboard/execution-flow projection 완료를 암시하지 않습니다.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

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

**스크립트 우선 실행**: `python3 {PLUGIN_ROOT}/scripts/mst.py request history` 실행. 성공 시 출력 그대로 사용. 실패 시 fallback.

**Fallback:**
1. `{PROJECT_ROOT}/.gran-maestro/requests/` 스캔
2. `status: completed` 또는 `status: cancelled`인 요청 필터링
3. 특정 REQ ID 지정 시 상세 이력, 미지정 시 요약 목록

## 출력 형식 (목록)

```
Gran Maestro — 완료 이력
═══════════════════════════════════════

REQ-001  "사용자 인증 기능 추가"
  완료: 2026-02-14 14:30  |  소요: 4h 30m
  Tasks: 3  |  Feedback: 1회  |  Agent: codex x2, agy x1

REQ-003  "설정 페이지 리팩토링"
  완료: 2026-02-13 17:00  |  소요: 1h 15m
  Tasks: 1  |  Feedback: 0회  |  Agent: codex x1
```

## 출력 형식 (상세)

```
/mst:history REQ-001

Gran Maestro — REQ-001 이력
═══════════════════════════════════════

Phase 1: PM 분석 (45m)
  - Analysis Squad: Analyst + Architect + /mst:codex + /mst:agy
  - 스펙: 3개 태스크, 8개 수락조건

Phase 2: 외주 실행 (2h 15m)
  - REQ-001-01: codex (38m) — JWT 미들웨어
  - REQ-001-02: agy (1h 20m) — 로그인 UI
  - REQ-001-03: codex (38s) — 유저 모델 테스트

Phase 3: PM 리뷰 (30m)
  - Review Squad: /mst:codex (security + quality + verification)
  - 결과: PARTIAL (AC-2 미충족)

Phase 4: 피드백 1회 (45m)
  - 이슈: JWT 만료 처리 누락
  - 재실행: codex → 수정 완료

Phase 5: 수락 완료
  - Squash merge → main
  - 변경: +342 / -28 lines, 5 files
```

## 옵션

- `--limit {N}`: 최근 N개만 표시 (기본: 10)
- `--archive`: 아카이브된 세션 조회
- `--archive {ID}`: 아카이브에서 특정 세션 상세 조회
- `--archive --type {ideation|discussion|requests}`: 특정 타입만 필터

## 아카이브 조회

### `--archive` (목록)

1. 각 `{PROJECT_ROOT}/.gran-maestro/{ideation,discussion,requests,debug}/archived/` 디렉토리의 .tar.gz 파일 스캔
2. 각 파일의 내용 목록을 확인하여 세션 ID 추출
3. 타입별로 그룹화하여 표시:

```
Gran Maestro — 아카이브된 세션
═══════════════════════════════════════

ideation:
  IDN-001 ~ IDN-005  (ideation-IDN001-IDN005-20260210.tar.gz, 15.2 KB)
  IDN-006 ~ IDN-010  (ideation-IDN006-IDN010-20260215.tar.gz, 18.7 KB)

discussion:
  DSC-001 ~ DSC-003  (discussion-DSC001-DSC003-20260212.tar.gz, 8.3 KB)

requests:
  REQ-001 ~ REQ-010  (requests-REQ001-REQ010-20260214.tar.gz, 42.1 KB)
```

`--type` 옵션으로 특정 타입만 필터링 가능.

### `--archive {ID}` (상세 조회)

1. ID 접두사(REQ/IDN/DSC/DBG)로 타입 결정 → `archived/`에서 해당 ID 포함 tar.gz 탐색
2. 임시 위치에 추출: `tar -xzf {archive_file} -C /tmp/gran-maestro-archive-view/ {session_dir}`
3. `session.json`/`request.json` 읽어 상세 정보 + 주요 파일 요약 표시
4. 임시 파일 정리

```
Gran Maestro — 아카이브 상세: IDN-003
═══════════════════════════════════════

주제: "마이크로서비스 vs 모놀리식"
상태: completed
생성일: 2026-01-15 10:30
아카이브: ideation-IDN001-IDN005-20260210.tar.gz

  파일 목록:
  session.json, opinion-{역할(provider)}.md (참여자별),
  synthesis.md

복원하려면: /mst:archive --restore IDN-003
```

## 예시

```
/mst:history              # 전체 완료 이력
/mst:history REQ-001      # 특정 요청 상세 이력
/mst:history --limit 5    # 최근 5개
/mst:history --archive              # 아카이브된 세션 목록 (모든 타입)
/mst:history --archive IDN-003      # 아카이브에서 특정 세션 상세 조회
/mst:history --archive --type ideation  # ideation 아카이브만 필터
```

## 문제 해결

- "완료 요청 없음" → `/mst:list --all`로 전체 상태 확인
- "ID 없음" → ID 형식 `REQ-NNN` 확인; `/mst:list --completed`로 완료 ID 조회
- "이력 불완전" → `requests/{REQ-ID}/request.json` Phase 기록 확인
- "아카이브 ID 없음" → `/mst:history --archive` 또는 `/mst:archive --list`
