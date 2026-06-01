---
name: recover
description: "미완료 요청을 복구하고 마지막 Phase부터 재개합니다. 사용자가 '복구', '재개', '이어서', '계속해줘'를 말하거나 /mst:recover를 호출할 때 사용. 새 요청 시작에는 /mst:request를 사용. queue(pending.ndjson) 기반 단일 pop 재진입은 /mst:resume을 사용하며, mst-loop wrapper가 이 경로를 호출합니다."
user-invocable: true
argument-hint: "[{REQ-ID}] [{TASK-ID}]"
---

# maestro:resume

Claude Code 세션 종료 후 진행 중이던 워크플로우를 복구합니다.
파일 기반 상태에서 자동으로 복구 가능한 태스크를 탐색합니다.

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

### 인자 없이 (`/mst:recover`)
먼저 `{PROJECT_ROOT}/.gran-maestro/state/*/snapshot.json`을 스캔한다.
- 유효한 snapshot.json 발견 시 아래 형식으로 출력:
  - `중단된 스킬: {skill}, Step {N}/{M}`
- 각 항목별 재개 안내를 함께 출력:
  - `재개: /mst:{skill}` (필요 시 Step 정보 포함)
- state 스캔 블록 실행 후, 아래 cleaned worktree orphan 청소를 먼저 수행하고 기존 REQ/태스크 복구 로직을 그대로 수행한다.

### cleaned worktree orphan 청소 (`PAC-6`)

REQ/태스크 복구 목록을 만들기 전에 `{PROJECT_ROOT}/.gran-maestro/worktrees/*.meta.json` 중
`state == "cleaned"`인 메타를 순회한다. cleaned 메타는 정상적으로는 실제 worktree 디렉토리,
git worktree 등록, 작업 브랜치가 모두 없어야 한다.

아래 조건 중 하나라도 참이면 해당 메타를 orphan으로 판단한다.
- `git worktree list --porcelain` 결과에 메타의 `path`가 여전히 존재한다.
- `git branch --list {branch}` 결과가 존재한다.
- 메타의 `path` 디렉토리/경로가 실제 파일시스템에 존재한다.

orphan 감지 및 정리는 helper를 사용한다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py worktree detect-orphans --clean --json
```

helper는 orphan마다 아래 순서로 강제 정리한다.
1. worktree 등록 또는 path가 남아 있으면:
   `python3 {PLUGIN_ROOT}/scripts/mst.py worktree remove --path {p} --force`
2. branch가 남아 있으면:
   `git branch -D {branch}`
3. 위 정리가 성공하면:
   `{PROJECT_ROOT}/.gran-maestro/worktrees/{taskId}.meta.json` 제거

recover 자체 로그는 stdout에 간결히 남긴다. `--json` 결과의 `orphans[]`를 확인해 아래 형식으로 출력한다.

```text
[recover-orphan] detected taskId={taskId} path={p} branch={branch} reasons={worktree_listed,branch_exists,path_exists}
[recover-orphan] cleaned taskId={taskId}
```

정리 실패(`failed`가 비어 있지 않음) 시에는 해당 taskId와 실패 command/message를 출력하고, 메타를 삭제하지 않는다.
정상 cleaned 메타(실제 디렉토리/브랜치/등록 없음)는 출력 없이 skip한다.

`requests/` 전체 스캔 → terminal 상태(completed/cancelled/failed) 제외 → 태스크 `status.json` 확인 → 복구 가능 목록 표시 → `AskUserQuestion`으로 복구 대상 선택 → 해당 Phase 재개

### 특정 요청 (`/mst:recover REQ-001`)
`request.json` + 모든 태스크 상태 확인 → 마지막 활성 Phase 판별 → 재개

### 특정 태스크 (`/mst:recover REQ-001-01`)
`tasks/01/status.json` + `spec.md`의 `Assigned Agent` 확인 → 상태별 복구:
- `executing` → CLI 프로세스 확인 → 없으면 외주 재실행
- `review` → 리뷰 재개 (git diff, phase3_protocol)
- `feedback` → 피드백 문서 기반 외주 재실행
- `merging` → merge 상태 확인 후 재개
- `merge_conflict` → `git -C {worktree_path} status`로 충돌 파일 목록 확인 후 출력 →
  AskUserQuestion:
  - "충돌 수동 해소 후 재개": 사용자가 수동으로 충돌 해소 완료 후:
    1. 충돌 마커 잔존 검증: `git -C {worktree_path} diff --check` (마커 있으면 중단 + 재해소 안내)
    2. `git -C {worktree_path} add -A`
    3. `git -C {worktree_path} commit -m "Resolve merge conflicts in {REQ-ID}/{TASK-ID}"`
    4. Phase 5 (머지 단계)로 재개
  - "worktree 재생성 후 재실행": ⚠️ **미커밋 변경 사항이 영구 소실됩니다** — 사용자에게 경고 후 진행:
    1. `python3 {PLUGIN_ROOT}/scripts/mst.py worktree remove --path {worktree_path} --force` (--force 필수: merge_conflict 상태에서는 미커밋 변경 존재, prune 자동 실행 포함)
    2. 새 worktree 생성 → Phase 2 처음부터 재실행
- `queued`/`pending`/`pre_check` → 외주 실행/사전 검증 재실행
- `pre_check_failed` → 실패 내용 포함 외주 재실행

`AskUserQuestion`으로 사용자 확인 후 실행

### 사용자 대면 복구 안내

- `merge_conflict` 상태는 자동으로 무시하거나 재시도하지 않는다. 충돌 파일 목록을 먼저 보여주고, 사용자가 `충돌 수동 해소 후 재개` 또는 `worktree 재생성 후 재실행` 중 하나를 선택하게 한다.
- 사용자가 충돌을 수동으로 해소한 뒤에는 `git diff --check`로 충돌 마커 잔존 여부를 검증한다. 마커가 남아 있으면 커밋하지 않고 재해소 안내를 출력한다.
- 태스크 ID 인자는 공통 `parse_task_id` 검증 규칙을 따른다. 잘못된 ID가 들어오면 `REQ-NNN-TNN` 계열 형식을 안내하고 복구 대상을 추측하지 않는다.
- `.gran-maestro/` 경로는 프로젝트 루트에 문자열로 직접 붙이지 않고 공통 path helper를 기준으로 계산한다. 재개 안내에 경로를 출력할 때도 `{PROJECT_ROOT}/.gran-maestro/...` 절대경로 형식을 사용한다.

### 외주 실행/재실행 프로토콜

Phase 2 상태(`pending`/`queued`/`executing`/`pre_check_failed`/`feedback`)는 **반드시 `/mst:codex` 또는 `/mst:agy` 외주**; Claude(PM) 직접 코드 작성 금지.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

1. `Assigned Agent` 기준: `codex` → `mst:codex`; `agy` → `mst:agy`
2. Worktree 존재 시 이어서 실행; 없으면 새로 생성
3. 외주 실행:
   ```
   Skill(skill: "mst:codex", args: "{프롬프트} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-impl")
   Skill(skill: "mst:agy", args: "{프롬프트} --dir {worktree_path} --files {worktree_path}/**/* --trace {REQ-ID}/{TASK-NUM}/phase2-impl")
   ```
4. `feedback` 상태: feedback-RN.md 수정 요청을 프롬프트에 포함
5. 완료 후 사전 검증 (테스트+타입 체크) → Phase 3

## 복구 판단 매트릭스

| 마지막 상태 | 복구 동작 | Phase |
|------------|----------|-------|
| `pending` | 실행 큐에 삽입 | Phase 2 |
| `queued` | 큐에 재삽입 | Phase 2 |
| `executing` | 프로세스 확인 → 재실행 | Phase 2 |
| `pre_check` | 사전 검증 재실행 | Phase 2 |
| `pre_check_failed` | 피드백 첨부 재실행 | Phase 2 |
| `review` | 리뷰 재개 | Phase 3 |
| `feedback` | 피드백 기반 재실행 | Phase 4→2 |
| `merging` | merge 상태 확인 | Phase 5 |
| `merge_conflict` | 사용자에게 옵션 제시 | Phase 5 |

## Cross-session Recovery

AGI 세션은 Claude Code 대화가 바뀌어 현재 `MST_SESSION_ID`의
`.gran-maestro/state/{mst_session_id}/snapshot.json`이 없을 수 있다. 이 경우
`mst:recover`는 durable state를 recovery source로 사용한다.

DOD-005 경계: history source of truth는
`.gran-maestro/sessions/{mst_session_id}/history.*` 단일 ledger와 append-only
`history.head`/`history.verify` 조회다. recover bundle restoration은 DOD-006 범위이며,
`mst:recover` 문구는 DOD-005 완료를 dashboard/execution-flow projection(DOD-017) 완료로 해석하지 않는다.

DOD-006 경계: `recover/resume`는 canonical `mst_session_id`, root MST ID, state snapshot, history context를 복원해 다음 실행에 전달한다. 다음 실행에는 동일 `MST_SESSION_ID` env와 structured `mst_session_id` context를 전달한다. 복구 source of truth는 validated history ledger와 validated state snapshot이며, prompt summary는 diagnostic-only 보조 정보다. `MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`는 diagnostic-only이며 canonical fallback source가 아니다.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

동작:
- 현재 session snapshot이 있으면 기존 snapshot 복구 경로를 유지한다.
- 현재 session snapshot이 없으면 `.gran-maestro/agile/{AGI_ID}/session.json`과
  최근 `sprints/S*/result.json`을 읽어 `skillStack`을 재구성한다.
- 재구성된 snapshot은 `.gran-maestro/state/{current_session_id}/snapshot.json`에
  `status: "active"`로 생성된다.
- 복구 완료 시 current session의 `flow-detail.ndjson`에
  `event: "cross_session_recover"`가 기록된다.

복구 identity guard:
- `session.json.mst_session_id`가 현재 `MST_SESSION_ID`와 다르면 recover는 canonical mismatch로 실패하고 snapshot을 생성하지 않는다.
- legacy owner metadata는 compatibility diagnostic field이며 recover 성공, read-only 전환, mutation permission, takeover 필요 여부를 결정하지 않는다.
- `--takeover`는 legacy owner diagnostics를 현재 structured `MST_SESSION_ID`로 갱신하는 명시적 cleanup 옵션일 뿐, canonical recovery equality input이 아니다.

예시:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py recover AGI-001
python3 {PLUGIN_ROOT}/scripts/mst.py recover AGI-001 --takeover
python3 {PLUGIN_ROOT}/scripts/mst.py state recover AGI-001 --takeover
```

## 출력 형식 (목록)

```
Gran Maestro — 복구 가능한 요청
═══════════════════════════════════════

REQ-001  "사용자 인증 기능 추가"
  마지막 Phase: 2 (외주 실행)
  복구 가능 태스크:
  ├── 01: executing → 재실행 필요
  └── 02: pending → 큐에 삽입

REQ-003  "설정 페이지 리팩토링"
  마지막 Phase: 3 (PM 리뷰)
  복구 가능 태스크:
  └── 01: review → 리뷰 재개

═══════════════════════════════════════
```

목록 출력 후 `AskUserQuestion`으로 복구 대상 선택:

**옵션 구성**:
- REQ 수 ≤ 3: 각 REQ를 개별 옵션으로 나열 + `"D. 전체 복구"` 옵션
- REQ 수 ≥ 4: 오래된 순 첫 3개 REQ 옵션 + `"D. 전체 복구"` 옵션. 4개째 이후는 UI 자동 Other 입력으로 받는다.

**옵션 포맷**:
- label: `"A. {REQ-ID} {title 앞 18자}"`처럼 알파벳 prefix와 의미 요약을 함께 쓴다.
- description: `"[장점] 해당 요청만 안전하게 재개합니다. [단점] 나머지 요청은 대기합니다. [적합] 우선순위가 명확한 단건 복구에 적합합니다. 마지막 Phase: {N} ({상태}) | 태스크: {요약}"`

**전체 복구 옵션**:
- label: `"D. 전체 복구"`
- description: `"[장점] 복구 가능한 모든 요청을 순서대로 재개합니다. [단점] 실행 시간이 길어질 수 있습니다. [적합] 의존 체인을 한 번에 복구할 때 적합합니다."`

UI 자동 Other 입력: 목록에 없는 REQ ID를 직접 입력하거나 콤마 구분으로 복수 지정 가능
  예: `REQ-005` 또는 `REQ-005,REQ-007`

## 예시

```
/mst:recover              # 모든 미완료 요청 복구 목록
/mst:recover REQ-001      # 특정 요청 복구
/mst:recover REQ-001-01   # 특정 태스크 복구
```

## 문제 해결

- "복구 가능 요청 없음" → 모든 요청 완료/취소 상태; `/mst:list --all` 확인
- "ID 없음" → `REQ-NNN` 형식 확인; `/mst:list`로 조회
- "worktree 불일치" → `git worktree list`로 확인; 수동 정리 필요할 수 있음
