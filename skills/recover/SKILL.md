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

### 외주 실행/재실행 프로토콜

Phase 2 상태(`pending`/`queued`/`executing`/`pre_check_failed`/`feedback`)는 **반드시 `/mst:codex` 또는 `/mst:gemini` 외주**; Claude(PM) 직접 코드 작성 금지.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

1. `Assigned Agent` 기준: `codex` → `mst:codex`; `gemini` → `mst:gemini`
2. Worktree 존재 시 이어서 실행; 없으면 새로 생성
3. 외주 실행:
   ```
   Skill(skill: "mst:codex", args: "{프롬프트} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-impl")
   Skill(skill: "mst:gemini", args: "{프롬프트} --dir {worktree_path} --files {worktree_path}/**/* --trace {REQ-ID}/{TASK-NUM}/phase2-impl")
   ```
4. `feedback` 상태: feedback-RN.md 수정 요청을 프롬프트에 포함
5. 완료 후 사전 검증 (테스트+타입 체크) → Phase 3


<!-- @include _shared/skill-execution-marker.md -->
## 스킬 실행 마커 (MANDATORY)

- 모든 응답의 첫 줄 또는 각 Step 시작 줄에 아래 마커를 출력한다.
- 기본 마커 포맷: `[MST skill={name} step={N}/{M} return_to={parent_skill/step | null}]`
- 필드 규칙:
  - `skill`: 현재 실행 중인 스킬 이름
  - `step`: 현재 단계(`N/M`) 또는 서브스킬 종료 시 `returned`
  - `return_to`: 최상위 스킬이면 `null`, 서브스킬이면 `{parent_skill}/{step_number}`
- 서브스킬 종료 마커: `[MST skill={subskill} step=returned return_to={parent/step}]`
- C/D 분리 마커 규칙을 추가로 사용하지 않는다. 반드시 단일 MST 마커만 사용한다.
- 예시:
  - `[MST skill={name} step=1/3 return_to=null]`
  - `[MST skill={subskill} step=returned return_to={parent_skill}/{step_number}]`
<!-- @end-include -->

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
- REQ 수 ≤ 3: 각 REQ를 개별 옵션으로 나열 + "전체 복구 (all)" 옵션
- REQ 수 ≥ 4: 오래된 순 첫 3개 REQ 옵션 + "전체 복구 (all)" 옵션 (4개째 이후는 Other로 직접 입력)

**옵션 포맷**:
- label: `"{REQ-ID}: {title 앞 25자}"`
- description: `"마지막 Phase: {N} ({상태}) | 태스크: {요약}"`

**"전체 복구 (all)" 옵션**:
- label: `"전체 복구 (all)"`
- description: `"복구 가능한 모든 요청을 순서대로 재개합니다"`

Other (자유 입력): 목록에 없는 REQ ID를 직접 입력하거나 콤마 구분으로 복수 지정 가능
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
