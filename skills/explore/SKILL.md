---
name: explore
description: "에이전트들이 코드베이스를 백그라운드로 자율 탐색해 원하는 정보를 찾아옵니다. 사용자가 '탐색', '코드 찾아줘', '어디 있어'를 말하거나 /mst:explore를 호출할 때 사용."
user-invocable: true
argument-hint: "{탐색 목표 설명} [--focus {파일패턴|관점키워드}] [--from EXP-NNN]"
---

# maestro:explore

설정된 AI 팀원들이 **병렬로 코드베이스를 탐색**하고 PM(Claude)이 결과를 합쳐 종합 탐색 리포트를 생성합니다.

## debug와의 차이

| 항목 | debug | **explore** |
|---|---|---|
| 조사자 키 | investigators | **explorers** |
| 개별 산출물 | finding-{key}.md | **explore-{key}.md** |
| 종합 리포트 | debug-report.md | **explore-report.md** |
| claude 참여 방식 | investigator로 직접 참여 가능 | **explorers에서 제외, claude_synthesis로만 종합** |

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

<!-- @include _shared/delegation-routing.md -->
### Provider Delegation Routing Protocol (MANDATORY)

이 프로토콜은 이 스킬 아래의 모든 provider 실행 예시보다 우선한다. provider 작업을 시작하기 전에 parent host가 route와 lifecycle evidence를 소유하고, child는 실제 할당 작업만 수행한다.

#### 0. 모델과 추론 난이도를 함께 확정한다

각 호출은 provider 시작 전에 호출 종류의 `{selector}`(예: `ideation`, `review.roles.security_reviewer`, `models.roles.developer.0`)로 `python3 {PLUGIN_ROOT}/scripts/mst.py resolve-execution "{provider}" "{selector}" --pretty`를 반드시 실행한다.

응답의 `model`, `reasoning_effort`, `reasoning_effort_source`는 하나의 binding이다. null(`inherit`)이면 override/CLI flag를 생략하고, invalid·unsupported·capability 부재는 우회 없이 **blocked**다.
우선순위는 호출별 concrete > provider `default_reasoning_effort`이며 호출별 `inherit`은 기본값을 건너뛴다. non-null effort는 Codex native `reasoning_effort`, Claude native `effort`, lifecycle/dispatch `--reasoning-effort`로 전달하고 항상 `--selector`를 함께 쓴다. Orca는 이미 `route=external`인 실행의 launch surface일 뿐이며 지원 범위와 binding을 바꾸지 않는다.

#### 1. Route를 먼저 확정한다

1. `python3 {PLUGIN_ROOT}/scripts/mst.py host context --json`을 실행하고 JSON의 `host`를 읽는다. 이 호출 실패, 잘못된 JSON, 알 수 없는 host는 임의 추정하지 말고 **blocked**로 종료한다.
2. 이어서 반드시 아래 중앙 planner를 호출한다. `{scope}`는 현재 작업의 실제 scope(`implementation`, `review`, `exploration`, `ideation`, `discussion`, `debug`, `analysis`)이고, `{provider}`는 선택된 `codex | claude | agy`다.

   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py delegation route \
     --host "{host}" \
     --provider "{provider}" \
     --scope "{scope}" \
     --worktree-dir "{worktree_path}" \
     --capability-status "{available|unknown|unavailable}"
   ```

3. route 결과 외의 근거로 transport를 바꾸지 않는다.
   - `route=native_candidate`: 같은 host/provider의 native bridge만 사용한다. `handshake_required=true`이면 실제 host tool 가용성을 확인한 뒤 진행한다.
   - `route=external`: 이 경우에만 아래에 남아 있는 managed wrapper, `dispatch build`, provider CLI adapter 예시를 사용할 수 있다.
   - `route=blocked`, CLI non-zero, lifecycle 응답의 `status=blocked`, 또는 현재 attempt의 `phase=reconciling`: 즉시 fail closed 한다. 같은 task/worktree에 새 agent나 external process를 시작하지 않는다.

   `requested_launch_surface=orca`, `launch_surface=orca`이면 transport는 계속 `external`이고 MST 보호 runner만 Orca background terminal에서 시작된다. Caller가 Orca Run/Task/Dispatch를 호출하거나 terminal을 직접 만들지 않는다. 중앙 Python launcher만 exact `path:{worktree_path}` selector와 `MST/{task_id}/{attempt_id}` title을 사용한다. Terminal create 호출 전 확정 실패만 원래 route로 돌아갈 수 있으며, 호출 이후 response/handle 불명은 fallback 또는 재실행하지 않고 기존 attempt를 reconcile한다.

#### 2. `native_candidate` 실행과 evidence

Native spawn **전** parent가 `delegation start`를 호출하고 반환된 `attempt_id`를 이후 모든 CAS 호출에 사용한다. `start`는 lifecycle 준비만 하며, 신규 응답이나 exact replay 모두 그 자체로 spawn 권한을 주지 않는다(`spawn_allowed=false`).

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py delegation start \
  --task-id "{task_id}" \
  --idempotency-key "{task_id}:start:{stable_key}" \
  --host "{host}" \
  --provider "{provider}" \
  --capability-status available \
  --route-reason "{route.reason_code}" \
  --worktree-dir "{worktree_path}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --scope "{scope}" \
  --prompt-file "{prompt_file}" \
  --output-path "{output_path}"
```

`analysis|review|exploration|ideation|discussion|debug`가 실제 read-only 작업이고 별도 linked worktree를 쓰지 않는 경우에만 `--read-only`를 추가한다. 구현·수정 작업에는 이 예외를 사용하지 않는다.

그 다음 parent invocation별 고유한 `{claimant_id}`로 single-use spawn claim을 요청한다. **오직 이 호출에서 `spawn_allowed=true`와 non-empty private `claim_token_file`을 함께 받은 단 한 caller만** native host tool을 한 번 호출할 수 있다. raw bearer token은 CLI JSON, argv, process listing, tool transcript, child prompt에 노출하지 않는다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py delegation claim-spawn \
  --task-id "{task_id}" \
  --attempt-id "{attempt_id}" \
  --claimant-id "{claimant_id}" \
  --idempotency-key "{task_id}:claim:{claimant_id}"
```

`spawn_allowed=false`, `claim_status=claim_replay|already_claimed|reconciling|provider_task_in_flight|terminal`, 빈 `claim_token_file`, 또는 claim 응답 유실/불명확 상태에서는 host tool을 호출하지 않는다. `claim_replay|already_claimed`는 winner의 claim lease가 살아 있는 동안 **wait만** 하며 `recover`/`cancel`로 ownership을 빼앗지 않는다. lease 만료 뒤에만 `delegation recover`로 reconcile하고, 그 외에는 `next_action`에 따라 기존 provider task에 attach/wait한다. claim exact replay는 bearer token/파일을 다시 발급하지 않는다. 따라서 claim 결과를 잃은 caller도 외부 fallback이나 중복 native spawn을 시도하지 않는다.

- `host=codex, provider=codex`: Codex collaboration native tools를 사용한다. `collaboration.spawn_agent`로 spawn하고, resolved effort가 non-null이면 `reasoning_effort`를 전달한다. host가 제공하는 attach/follow-up 수단으로 같은 task에 연결하며, `collaboration.wait_agent`로 대기한 뒤 전달된 completion result를 수집한다. 병렬 fan-out은 독립 task마다 native agent를 하나씩 spawn한다.
- `host=claude, provider=claude`: Claude의 `Task(...)` 또는 `Agent(...)` native tool로 spawn하고, resolved effort가 non-null이면 `effort`를 전달한다. background task는 host의 `TaskOutput`/resume 결과로 대기·수집한다.
- 정상 same-host 경로에서 `codex exec`, `claude` CLI, `mst.py run --provider {same_provider}`, 같은 provider의 managed wrapper, 또는 nested `/mst:claude`/`/mst:codex`를 호출하지 않는다.

Native tool 응답마다 claim winner parent가 다음 순서로 evidence를 기록한다. `{claim_token_file}`은 winner 응답의 mode `0400` private one-shot handle이며 `acknowledge` 성공 시 삭제된다. 내용을 읽거나 복사하거나 child/user/log에 전달하지 않는다. 각 명령의 JSON 응답에서 `status`/`phase`를 확인하고 blocked/reconciling이면 더 진행하지 않는다.

1. spawn 성공 및 provider task ID 수신: `delegation acknowledge --task-id "{task_id}" --attempt-id "{attempt_id}" --claim-token-file "{claim_token_file}" --spawn-status created_with_task_id --provider-task-id "{provider_task_id}" --idempotency-key "{task_id}:ack:{stable_key}"`
2. host task 연결 확인: `delegation attach --task-id "{task_id}" --attempt-id "{attempt_id}" --attach-status attached --idempotency-key "{task_id}:attach:{stable_key}"`
3. 대기 중 주기적 생존 증거: `delegation heartbeat --task-id "{task_id}" --attempt-id "{attempt_id}" --provider-state running --idempotency-key "{task_id}:heartbeat:{sequence}"`
4. host result 수집 직후 parent가 성공 결과의 **비어 있지 않은 전체 내용**을 bound `{output_path}`의 sibling temp file에 먼저 쓰고 atomic replace한 뒤, fresh hash/size를 확인한다. child에게 이 파일 쓰기를 맡기거나 기존 파일을 재사용하지 않는다.
5. 결과 파일 evidence가 준비된 뒤에만: `delegation complete --task-id "{task_id}" --attempt-id "{attempt_id}" --completion-signal "{succeeded|failed|timeout|unknown}" --output-path "{output_path}" --idempotency-key "{task_id}:complete:{stable_key}"`

Native spawn이 task 생성 전에 **명확히** 실패한 경우에만 claim winner가 같은 `--claim-token-file "{claim_token_file}"`로 `spawn-status=definitive_not_created`를 acknowledge한 뒤 `delegation fallback --expected-attempt-id "{attempt_id}" ...`를 요청할 수 있다. 그 후 capability를 `unavailable`로 route planner에 다시 전달해 `route=external`을 받은 경우에만 external lane을 실행한다. claim 결과 유실, `accepted`, task ID 발급, attach 실패/timeout, child 실패, unknown/indeterminate 결과 뒤에는 external fallback을 금지하고 reconcile 상태를 유지한다.

#### 2-A. External lane authorization

`route=external` 판정만으로 provider command를 직접 만들지 않는다. Fresh headless/cross-provider external lane은 command 생성 전에 중앙 planner 결과를 state에 고정한다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py dispatch authorize-external \
  --provider "{provider}" \
  --task-id "{task_id}" \
  --prompt-file "{prompt_file}" \
  --worktree-dir "{worktree_path}" \
  --running-log-path "{running_log}" \
  --trace-path "{trace_path}" \
  --output-path "{output_path}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --scope "{scope}" \
  --idempotency-key "{task_id}:external-authorize:{stable_key}" \
  {read_only_flag}
```

이 명령은 실제 host를 다시 확인하고 중앙 route가 여전히 `external`일 때만 current external attempt와 model/running/trace/output binding을 저장한다. 구현·수정 lane은 registered linked worktree를 사용하고 `{read_only_flag}`를 비운다. 실제 read-only scope만 `--read-only`를 사용한다. 반환된 `attempt_id`와 동일한 artifact binding을 external wrapper에 전달한다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py dispatch build \
  --provider "{provider}" \
  --task-id "{task_id}" \
  --prompt-file "{prompt_file}" \
  --worktree-dir "{worktree_path}" \
  --log-file "{running_log}" \
  --model "{model}" \
  --selector "{selector}" \
  {reasoning_effort_flag} \
  --expected-attempt-id "{external_attempt_id}"
```

Native definitive non-creation fallback이면 새 authorization을 만들지 않고 `delegation fallback`이 반환한 external `attempt_id`를 `--expected-attempt-id`로 사용한다. Builder는 current attempt의 task/provider/resolved worktree/prompt hash/route를 재검증하므로 native, reconciling, stale attempt, 또는 mismatch 상태에서는 command를 만들지 않는다. Codex/Claude와 Orca-enabled AGY 보호 wrapper는 provider command나 split claim/finalize shell을 포함하지 않고 `dispatch run-external` 단일 감독자만 호출한다. `launch_surface=orca`일 때 builder는 중앙 `dispatch launch-external`을 호출하고, 그 launcher가 만든 terminal 안에서 동일한 `dispatch run-external`을 실행한다. 성공 finalize 뒤에만 tab을 닫고 실패·취소·unknown은 보존하며 terminal 출력이 아니라 MST output/lifecycle evidence를 authoritative로 본다. 감독자는 먼저 side effect가 없는 anonymous exec gate를 띄워 PID/PGID/start identity를 CAS로 attach하고, 같은 task lock 안에서 취소보다 먼저 exec 권한이 확정된 경우에만 실제 provider를 release한다. claim에서 캡처한 정확한 prompt bytes를 전달하고, provider process group을 회수한 뒤 fresh single-link inode로 claim해 계속 보유한 non-following output descriptor로 결과를 게시한다. prompt/snapshot/running/trace/output alias와 MST state·lock·history reserved path alias는 provider spawn 전에 차단한다. `claim-external`/`heartbeat-external`/`finalize-external`을 별도로 호출하거나 prompt snapshot/output pathname을 shell에서 다시 열지 않는다. Orca `terminal create --command`에는 task/attempt/session 같은 안전한 식별자만 넣고 prompt 본문·snapshot/running/trace/output path·claim secret·descriptor number를 넣지 않는다.

#### 3. Child prompt 격리 규칙

모든 native child prompt에는 다음 제약을 그대로 포함한다.

```text
DELEGATION BOUNDARY (MANDATORY)
- Complete the assigned task yourself; do not delegate or spawn another provider agent.
- Do not invoke codex/claude provider CLIs, /mst:codex, /mst:claude, or a same-provider managed wrapper.
- Do not call `mst.py delegation` lifecycle commands and do not edit `.gran-maestro/run`, session, or history state; the parent owns routing and evidence.
- Work only in the assigned worktree/scope and return the result/evidence to the parent.
```

아래 skill별 dispatch 예시는 이 protocol의 route로 gate한다. Provider CLI/managed wrapper 예시는 오직 `route=external`일 때만 사용한다. `Task`/`Agent`/Codex collaboration 예시는 host와 provider가 일치하는 `route=native_candidate`일 때만 사용하고 child boundary와 native lifecycle evidence를 함께 적용한다.
<!-- @end-include -->

### MANDATORY Read: `~/.claude/user-profile.json` (AskUserQuestion 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 사용자 설명 텍스트, 탐색 가이드 문구, 최종 리포트 요약 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.

### Step 0: 아카이브 체크 (자동)

`archive.auto_archive_on_create=true` 시 `EXP-*` 세션 수 확인 → `max_active_sessions` 초과 시 완료 세션 아카이브 후 진행

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/explore/` 디렉토리 존재 확인, 없으면 생성
2. 새 세션 ID 채번 (EXP-NNN):
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type exp`
   - 반환값 검증 (**순서 엄수 — 1→2→3**):
     1. `EXP-EXP-` 이중 접두사 감지 시 sanitize → 단일 `EXP-`만 유지 (최우선)
     2. `EXP-NNN` 형태면 유효성 확인 후 그대로 사용
     3. 숫자만 반환되면 `EXP-{zero-padded}`로 1회만 접두사 부여
   - ⚠️ **수동 접두사 추가 절대 금지 (CRITICAL)**: `mst.py counter next --type exp`는 이미 `EXP-` 접두사를 포함하여 반환합니다. 반환값에 수동으로 `EXP-`를 추가하면 `EXP-EXP-` 이중 접두사가 발생합니다. 반환값을 그대로 사용하되, 위 검증만 수행하세요.
   - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/explore/counter.json` Read
     - 파일 존재 시 `next_id = last_id + 1`
     - 파일 미존재 시 기존 `EXP-*` 디렉토리/아카이브를 스캔해 max 번호를 복구하고 `counter.json` 생성
3. `{PROJECT_ROOT}/.gran-maestro/explore/EXP-NNN/` 디렉토리 생성
4. `session.json` 작성

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "schema_version": "1.0",
  "id": "EXP-NNN",
  "goal": "{사용자 탐색 목표}",
  "focus": "{--focus 값 또는 null}",
  "status": "exploring",
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "merge_completed_at": null,
  "completed_at": null,
  "failed_at": null,
  "explorers": {
    "codex": {
      "role": "",
      "status": "pending",
      "provider": "codex",
      "tier": "default",
      "started_at": null,
      "completed_at": null,
      "output_file": "explore-codex.md",
      "task_id": null,
      "exit_code": null
    },
    "agy": {
      "role": "",
      "status": "pending",
      "provider": "agy",
      "tier": "default",
      "started_at": null,
      "completed_at": null,
      "output_file": "explore-agy.md",
      "task_id": null,
      "exit_code": null
    }
  },
  "claude_synthesis": {
    "status": "pending",
    "started_at": null,
    "completed_at": null,
    "output_file": "explore-report.md"
  },
  "participant_config": {
    "codex": { "count": 1, "tier": "default" },
    "agy": { "count": 1, "tier": "default" },
    "claude": { "count": 1, "tier": "default" }
  },
  "merge_wait_ms": 60000,
  "error": null
}
```

`explorers`는 config의 `explore.agents`를 읽어 동적 생성합니다.

### explorers 동적 생성 규칙
1. provider(`codex`, `agy`, `claude`)별 count/tier를 읽어 `participant_config`를 `{provider: {count, tier}}` 구조로 기록
2. `claude`는 `explorers` 생성 대상에서 **항상 제외**하고 `claude_synthesis`로만 사용
3. count == 1이면 explorer 키는 `{provider}`
4. count > 1이면 `{provider}`, `{provider}-2`, `{provider}-3`... 순으로 생성
5. 각 explorer 항목에 `provider` 및 `tier` 필드를 기록 (tier는 config의 `explore.agents.{provider}.tier` 값을 전파, 미설정 시 `"default"`)
6. explorer 합계는 1~6명으로 제한, 위반 시 에러로 중단

`explore.agents`가 없으면 기본값 `{ codex:1, agy:1, claude:1 }`을 사용합니다.

### 레거시 읽기 호환 (SHOULD)

- `schema_version`이 없는 세션은 legacy로 간주하고, Read 시 canonical 형태로 normalize한다.
- Write는 항상 canonical 스키마(`schema_version`, `explorers=object`, `participant_config={provider:{count,tier}}`)로만 수행한다.

**필드별 변환 테이블**:

| 레거시 형태 | canonical 변환 |
|------------|---------------|
| `participant_config.{provider}: number` (예: `"codex": 2`) | `{ "count": 2, "tier": "default" }` |
| `participant_config.{provider}: string` (예: `"codex_model": "..."`) | `{ "count": 1, "tier": "default" }` (모델명은 무시) |
| `claude_synthesis: true` | `{ "status": "done", "started_at": null, "completed_at": null, "output_file": "explore-report.md" }` |
| `claude_synthesis: false` | `{ "status": "pending", "started_at": null, "completed_at": null, "output_file": "explore-report.md" }` |
| `claude_synthesis: { ... }` (object, 필드 누락) | 누락 필드를 기본값으로 보정 (`status: "pending"`, `output_file: "explore-report.md"`) |
| `explorers: [array]` (배열 형태) | 각 항목의 `key` 필드를 object 키로 사용하여 object로 변환 |
| `explorers[].tier` 필드 누락 | `"tier": "default"` 보정 |

세션 구조:
- `EXP-NNN/session.json`
- `EXP-NNN/prompts/explore-{explorerKey}-prompt.md`
- `EXP-NNN/prompts/synthesis-prompt.md`
- `EXP-NNN/explore-{explorerKey}.md`
- `EXP-NNN/explore-report.md`

### Step 1.5: PM 역할 배정

PM(Claude)이 탐색 목표를 분석하여 `explorers` 수만큼 역할을 배정합니다.
- 목표 분석: 확인할 기능/경로/의존/증거 수준 정의
- 조사 각도 배정:
  - Codex: 코드 레벨 추적, 파일/심볼/호출 경로 중심
  - AGY: 아키텍처, 흐름, 모듈 간 관계 중심
- `session.json` 업데이트:
  - `explorers[key].role` 기록
  - `status: "dispatching"`으로 전이

### AUTO-CONTINUE 원칙 (CRITICAL)

> **이 스킬의 모든 Step은 사용자 입력 없이 자율적으로 진행합니다.**
> - 백그라운드 작업 완료 시 사용자 확인 질문 금지
> - Step 2~5는 완전 자동 진행
> - 작업 실패 시에도 가능한 범위까지 자동 복구/합성 후 상태를 종료(`completed` 또는 `failed`)한다
> - 단, Step 5 종료 보고 직후 다음 단계 선택은 `AskUserQuestion`으로 처리한다 (AUTO-CONTINUE 예외)

### 병렬 Write 원칙 (CRITICAL)

독립 파일 Write는 하나의 응답에서 동시에 수행합니다.
- `session.json` + 여러 프롬프트 파일 동시 생성/업데이트
- explorer별 상태 업데이트를 가능한 한 일괄 반영
- 불필요한 순차 쓰기로 병목을 만들지 않음

### Step 2: explorer 백그라운드 파견

`explorers` 키를 순회하여 provider별로 동시 실행합니다.

> **Claude 모델 결정**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get explore.agents.claude.tier models.providers.claude.default_tier)`로 tier를 구한 뒤 `models.providers.claude[{tier}]`로 resolve (미설정 시 `"sonnet"` 폴백).

#### 2a. Dispatch 프롬프트 조립 — feature flag 분기

config 확인:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py config get prompt_builder.enabled prompt_builder.fallback_on_error
```

##### (a) prompt_builder.enabled=true (하이브리드 JSON 경로)
1. 탐색 공통 컨텍스트(목표, 집중 영역, 이전 세션 요약 등)를 `.gran-maestro/tmp/ctx-{session_id}.md`로 Write
2. `dispatch-input.json` Write:
   ```json
   {
     "format": "mst.dispatch",
     "schema_version": 1,
     "common": {
       "topic": "{EXP-NNN 탐색 목표}",
       "constraints": ["읽기 전용 탐색만 수행, 파일 수정/생성 금지", "..."],
       "reference_context_file": ".gran-maestro/tmp/ctx-{session_id}.md"
     },
     "tasks": [
       {"role": "explore-{explorerKey}", "angle": "{role}", "ask": "탐색 지침 ≤200자 또는 ask_file"}
     ]
   }
   ```
   - `tasks[]`는 `explorers` 키를 순회하여 작성
   - 각 task의 `role` 값은 `"explore-{explorerKey}"`로 설정 (split 결과 파일이 `explore-{explorerKey}-prompt.md`로 생성되어 기존 dispatch 경로 호환)
   - 200자 초과 또는 줄바꿈 포함 시 `ask_file` 경로로 분리
3. CLI 호출: `python3 {PLUGIN_ROOT}/scripts/mst.py prompt build --input {absolute_path}/dispatch-input.json --out-dir {absolute_path}/prompts --sid {session_id}`
4. 성공 시: `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts` 호출 → `prompts/explore-{explorerKey}-prompt.md` 개별 파일 생성 → 기존 dispatch (2b 단계) 그대로 실행
5. 실패 시 repair 1회 재요청 → 그래도 실패면 (b) 경로로 자동 전환

##### (b) prompt_builder.enabled=false 또는 CLI fallback
- 기존 개별 파일 직접 Write 경로 **그대로 유지** (변경 금지)

##### fallback 규약 (MANDATORY)
- CLI 오류 시 stderr/stdout을 Read, PM이 구조화 errors JSON 기반으로 JSON 수정 후 1회 재시도 (repair 1회)
- 재시도 실패 시 (b) 경로로 자동 전환 (`fallback_on_error=true`일 때)
- `fallback_on_error=false`이면 워크플로우 중단 + 사용자 에스컬레이션
- 참고: `mst.py prompt build`는 오류 반환만 담당, repair 1회/fallback 전환은 본 스킬(explore)의 책임이다

#### 2b. 프롬프트 파일 작성

`explorers` 키를 순회하여 `prompts/explore-{explorerKey}-prompt.md`를 **하나의 메시지에서 동시에 Write**합니다.

프롬프트에는 반드시 **"읽기 전용 탐색만 수행, 파일 수정/생성 금지"**를 명시하고 결과를 `explore-{explorerKey}.md`에 작성하도록 지정합니다.

##### 2a-1. `--from EXP-NNN` 요약 주입 규칙 (옵션)

- `--from EXP-NNN`이 지정되면 `{PROJECT_ROOT}/.gran-maestro/explore/EXP-NNN/explore-report.md`에서 **`후속 탐색용 요약` 섹션만** 추출한다.
- 이전 세션 본문 전체, 개별 explorer 원문, 기타 섹션은 주입하지 않는다.
- 추출 텍스트는 최대 500토큰 이내로 제한한다 (초과 시 잘라서 사용).
- 프롬프트에 `이전 세션 요약 컨텍스트` 블록으로 삽입하고, 없거나 추출 실패 시 해당 블록을 생략한다.

#### 프롬프트 작성 포맷

```markdown
# 코드베이스 탐색 요청

## 탐색 목표
{사용자 탐색 목표 전체 내용}

## 당신의 역할
당신은 {provider} 탐색자입니다. 담당 각도: **{role}**

## 조사 지침
1. 코드베이스를 읽기 전용으로 탐색하고 증거를 수집한다.
2. 파일 경로, 심볼명, 라인 번호를 가능한 한 구체적으로 제시한다.
3. 추론과 사실을 구분해 작성한다.
4. 의심 지점은 확인이 필요한 이유를 함께 적는다.
5. 파일 수정/생성/삭제는 절대 수행하지 않는다.

## 집중 영역
{--focus 값이 있으면 해당 패턴, 없으면 "코드베이스 전체"}

## 이전 세션 요약 컨텍스트 (선택)
{--from이 있으면 EXP-NNN의 "후속 탐색용 요약"만 500토큰 이내로 주입, 없으면 이 섹션 생략}

## 출력 형식
응답을 `{output_file}`에 마크다운으로 작성하고 아래 섹션을 포함한다.
- **탐색 범위**: 실제로 확인한 파일/모듈/심볼 범위
- **발견 사항**: 확인된 사실/패턴 목록 (`파일:라인` 표기)
- **구조적 관계**: 모듈/호출/데이터 흐름 관계
- **미탐색 영역**: 아직 확인하지 못했거나 증거가 부족한 영역
- **후속 탐색 제안**: 다음 탐색 우선순위와 제안 경로

글자 수 제한: `{config.collaborative_explore.finding_char_limit}`자 이내
```

#### 2c. 병렬 호출

> explorer별 shared route/lifecycle을 먼저 적용한다. Same-host Codex는 collaboration agent로 병렬화하고, 아래 provider process는 `route=external`일 때만 실행한다.

- `provider: "codex"`, external lane only (same-host native candidate는 collaboration agent):
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --full-auto -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex explore 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/prompts/explore-{explorerKey}-prompt.md)\" > {absolute_path}/explore-{explorerKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/explore-{explorerKey}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/prompts/explore-{explorerKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/explore-{explorerKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/explore-{explorerKey}.md; exit $EC"
  )
  ```

각 호출의 background task ID를 `session.json`에 기록합니다.

#### 2d. dispatch 시작 시각 기록

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 실패 시 UTC ISO 폴백으로 생성한다.

`session.json` 업데이트:
- `status: "waiting"`
- `dispatch_started_at: "{TS}"`
- 각 `explorers[key].status: "in_progress"`
- 각 `explorers[key].started_at: "{TS}"`

### Step 3: 백그라운드 탐색 완료 대기 & Claude PM 종합

#### 3a. 즉시 확인

`explorers`를 순회하여 `explore-{explorerKey}.md` 존재 여부/내용을 확인:
- 파일 존재 + 비어있지 않음 + `EXIT_CODE:` 존재 → 후보 상태 `done` 또는 `failed`(exit code 기반)
- 파일 미존재 또는 비어있음 또는 `EXIT_CODE:` 미기록 → `in_progress`

#### 3b. 대기 (MANDATORY, 필요 시)

모든 explorer가 완료 상태면 즉시 Step 3c로 진행.

`in_progress` explorer가 있으면 아래 명령으로 대기:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files \
  --timeout {config.collaborative_explore.merge_wait_ms를 1000으로 나눈 값, 기본 60} \
  {in_progress explorer들의 {absolute_path}/explore-{explorerKey}.md 절대 경로 목록}
```

분기 처리:
- 마지막 줄이 `ALL_READY`면 즉시 Step 3c 진행
- 마지막 줄이 `TIMEOUT`이면 완료된 결과만 사용하고 미완료 explorer는 `timeout`으로 기록 후 Step 3c 진행

#### 3c. session.json 업데이트

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `merge_completed_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "status": "synthesizing",
  "explorers": {
    "codex": { "status": "done", "completed_at": "{TS}", "exit_code": 0 },
    "agy": { "status": "timeout", "completed_at": null, "exit_code": null }
  },
  "merge_completed_at": "{TS — mst.py timestamp now 출력값}"
}
```

### Step 4: Claude 종합 리포트 작성

1. `status in ["done"]`인 `explore-{explorerKey}.md`만 입력으로 사용
2. `prompts/synthesis-prompt.md` 생성 후 Claude로 종합 실행
3. 결과를 `explore-report.md`로 저장 (아래 표준 섹션을 반드시 유지)
4. `claude_synthesis.status` 갱신:
   - 성공 시 `done`
   - 실패 시 `failed` + 원인 기록

`explore-report.md` 표준 섹션:
- **탐색 범위**
- **발견 사항**
- **구조적 관계**
- **미탐색 영역**
- **후속 탐색 제안**
- **후속 탐색용 요약** (최대 500토큰, `--from` 주입 전용 요약)

### Step 5: 상태 종료 및 사용자 보고

1. 종료 조건 판정:
   - 유효한 탐색 결과 1개 이상 + 리포트 생성 성공 → `status: "completed"`
   - 리포트 생성 실패 또는 유효한 결과 0개 → `status: "failed"`
2. 종료 타임스탬프 기록:
   - `completed`면 `completed_at` 필수
   - `failed`면 `failed_at` 필수
3. 사용자에게 `explore-report.md` 요약과 경로를 표시

표시 포맷:

```markdown
## EXP-NNN 탐색 리포트

### 참여 탐색자
- {explorerKey} ({role}, {provider}): {status}

### 핵심 발견
{신뢰도 높은 발견 1~3개}

### 참고 경로
- 상세 리포트: {PROJECT_ROOT}/.gran-maestro/explore/EXP-NNN/explore-report.md
```

4. 사용자 보고 직후 `AskUserQuestion`으로 다음 단계를 안내한다.
   - **"추가 탐색 (→ /mst:explore)"**
     - 실행: `Skill(skill: "mst:explore", args: "--from {EXP-NNN} {사용자 후속 탐색 질문}")`
     - 규칙: 현재 세션 ID를 `--from`에 **자동 포함**한다.
   - **"요청으로 전환 (→ /mst:request)"**
     - 실행: `Skill(skill: "mst:request", args: "--from-explore {EXP-NNN} {탐색 목표 앞 50자}")`
   - **"플랜으로 정제 (→ /mst:plan)"**
     - 실행: `Skill(skill: "mst:plan", args: "--from-explore {EXP-NNN} {탐색 목표 앞 50자}")`
   - **"종료"**
     - 스킬 종료

## 상태 전이 규칙 (MANDATORY)

### 허용 전이 경로

```
exploring → dispatching → waiting → synthesizing → completed
                                                  → failed
```

| 현재 상태 | 허용 전이 대상 |
|-----------|---------------|
| `exploring` | `dispatching`, `failed` |
| `dispatching` | `waiting`, `failed` |
| `waiting` | `synthesizing`, `failed` |
| `synthesizing` | `completed`, `failed` |
| `completed` | (터미널 — 전이 불가) |
| `failed` | (터미널 — 전이 불가) |

### 실패 전이
- **어느 상태에서든** `failed`로 전이 가능: `* → failed`
- `failed` 전이 시 반드시 `failed_at` 타임스탬프를 기록한다.

### 금지 전이 (CRITICAL)
- `completed → (any non-terminal)`: **절대 금지**. 완료된 세션을 다시 열 수 없다.
- `failed → (any non-terminal)`: **절대 금지**. 실패한 세션을 다시 열 수 없다.
- 터미널 상태(`completed`, `failed`)는 **불변**이다. 재시도가 필요하면 새 세션을 생성한다.

중간 실패가 있어도 상태를 열린 채로 두지 않습니다. 반드시 `completed` 또는 `failed`로 닫습니다.

## 에러 처리

- **케이스 1: 과반 이상 done**
  - 완료된 `explore-*` 결과로 정상 합성 진행
  - 타임아웃/실패 explorer는 리포트에 명시 후 `completed` 가능
- **케이스 2: 과반 미만 done**
  - 완료된 결과만으로 축약 리포트 생성
  - 미완료 explorer 수/원인을 리포트 상단에 고지
  - 합성 성공 시 `completed`, 합성 실패 시 `failed`
- **케이스 3: 전원 미완료 또는 전원 TIMEOUT**
  - 종합 단계 중단
  - `status: "failed"` + `failed_at` + `error` 기록
  - 재시도 명령/원인(환경/권한/모델)을 안내
- **케이스 4: CLI 미설치 (codex/agy)**
  - 해당 provider를 `skipped`로 표시하고 계속 진행
  - 가용 provider가 1명 이상이면 진행, 0명이면 즉시 `failed`
- **케이스 5: `mst.py counter next --type exp` 실패**
  - fallback counter 복구 로직으로 1회 재시도
  - ID 형식 sanitize로 `EXP-EXP` 방지
  - 재시도도 실패하면 `failed`로 종료
- **케이스 6: 타임스탬프 명령 실패**
  - UTC ISO 폴백 사용
  - 폴백 실패 시 상태 기록 불가이므로 즉시 `failed` 종료

## 세션 파일 구조

```
.gran-maestro/explore/EXP-NNN/
├── session.json
├── prompts/
│   ├── explore-{explorerKey}-prompt.md
│   └── synthesis-prompt.md
├── explore-{explorerKey}.md
└── explore-report.md
```

## 옵션

- `--focus {파일패턴|관점키워드}`: 탐색 범위를 파일 패턴 또는 관점 키워드로 지정 (예: `src/auth/**/*.ts`, `architecture`, `data-flow`, `security-surface`)
- `--from EXP-NNN`: 이전 탐색 세션의 `후속 탐색용 요약`만(최대 500토큰) 주입해 연속 탐색을 수행

## 예시

```
/mst:explore "로그인 흐름에서 토큰 검증 경로를 찾아줘"
/mst:explore --focus src/api/**/*.ts "API 라우팅과 에러 처리 흐름을 정리해줘"
/mst:explore --from EXP-012 --focus data-flow "결제 승인 이후 정산까지 데이터 흐름을 이어서 추적해줘"
/mst:explore "이 저장소에서 결제 모듈이 어디서 시작되는지 추적해줘"
```

## 참고

- Phase 1(초기화/스키마/상태 전이) 규칙을 유지하면서 Phase 2/3 확장(`--from`, 산출물 표준화, 다음 단계 안내, `--focus` 관점 키워드)을 추가 포함합니다.
- `explorers`는 object canonical 스키마를 사용하며 배열 표현을 금지합니다.
