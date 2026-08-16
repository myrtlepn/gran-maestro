---
name: discussion
description: "설정된 AI 팀원들이 합의에 도달할 때까지 반복 토론합니다. 사용자가 '토론', '합의', '디스커션'을 말하거나 /mst:discussion를 호출할 때 사용. 1회성 의견 수집은 /mst:ideation 사용."
user-invocable: true
argument-hint: "{주제 또는 IDN-NNN} [--max-rounds {N}] [--focus {분야}]"
---

# maestro:discussion

설정된 AI 팀원들이 **합의에 도달할 때까지** 반복 토론합니다. PM(Claude)이 사회자 역할로 발산점을 식별하고 수렴을 유도합니다. Maestro 모드 활성 여부에 관계없이 사용 가능합니다.

## ideation과의 차이

| | ideation | discussion |
|---|---|---|
| 목적 | 다양한 관점 수집 (발산) | 합의 도달 (수렴) |
| 라운드 | 1회 | N회 반복 |
| 종료 조건 | PM 종합 완료 | 참여자 합의 또는 max rounds |
| 출력 | synthesis.md | consensus.md |

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

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/discussion/` 디렉토리 존재 확인, 없으면 생성
2. 새 세션 ID 채번 (DSC-NNN):
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type dsc` → 출력 ID 사용
   - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/discussion/counter.json` 파일 Read
     - **파일 존재 시**: `next_id = last_id + 1`
     - **파일 미존재 시** (최초 또는 복구):
       a. `{PROJECT_ROOT}/.gran-maestro/discussion/` 하위의 기존 DSC-* 디렉토리 스캔
       b. `{PROJECT_ROOT}/.gran-maestro/archive/` 내 `discussion-*` tar.gz 파일명에서 ID 범위 추출 (예: `discussion-DSC001-DSC006-*.tar.gz` → max 6)
       c. 모든 소스에서 최대 번호 결정 → `counter.json` 생성: `{ "last_id": {max_number} }`
       d. `next_id = last_id + 1`
     - `counter.json` 업데이트: `{ "last_id": {next_id} }`
3. `{PROJECT_ROOT}/.gran-maestro/discussion/DSC-NNN/` 디렉토리 생성 (NNN은 3자리 zero-padded)
4. `session.json` 작성:

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "id": "DSC-NNN",
  "topic": "{사용자 주제}",
  "source_ideation": "{IDN-NNN 또는 null}",
  "focus": "{focus 또는 null}",
  "status": "analyzing",
  "max_rounds": "{Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get discussion.default_max_rounds) 출력값}",
  "current_round": 0,
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "participants": [
    { "key": "architect(codex)", "role": "architect", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "ux(codex)", "role": "ux", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "security(codex)", "role": "security", "perspective": "", "type": "opinion", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    { "key": "architecture(agy)", "role": "architecture", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "cost(agy)", "role": "cost", "perspective": "", "type": "opinion", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null },
    { "key": "risk(claude)", "role": "risk", "perspective": "", "type": "opinion", "status": "pending", "provider": "claude", "started_at": null, "completed_at": null }
  ],
  "critics": {
    "claude": { "status": "pending", "provider": "claude" }
  },
  "critic_count": 1,
  "participant_config": { "codex": 3, "agy": 2, "claude": 1 },
  "rounds": []
}
```

`participants`는 config의 `discussion.agents`를 읽어 생성합니다.
### participants 동적 생성 규칙
1. 각 provider(codex, agy, claude)의 count 읽기
2. count == 1 → key는 `{role}(provider)` 형태
3. count > 1 → role 키를 순차 생성, `{role}(provider)` 형태 유지
4. 각 항목에 `provider` 필드 기록
5. 합계 검증: 2~7명, 위반 시 에러 후 중단
6. count == 0 → 해당 provider 완전 skip

`participants` 키 없으면 기본값 `{ codex:1, agy:1, claude:1 }` 사용.

### Step 1.5: PM 역할 배정

PM이 주제/포커스를 분석해 `participants` 수만큼 관점을 배정하고 `critics`를 결정합니다.
- Codex/AGY/Claude 강점에 맞춰 관점 배정
- Critic 규칙: Claude 1명+ → Claude 우선, Claude 0명 → Codex → AGY. critic_count 2 → 2명 배정

`session.json`에 `participants`, `critics`, `critic_count`, `participant_config`, `status: "initializing"` 기록.

### AUTO-CONTINUE 원칙 (CRITICAL)

> - 백그라운드 작업 완료 시 사용자에게 확인 질문 금지
> - 모든 단계는 사용자 입력 없이 자동 진행
> - 모든 호출이 모두 완료되면 즉시 다음 step 진행
> - Step 4e 종료 판단은 PM이 자율적으로 처리
> - 최종 사용자 보고는 Step 6에서만
> - ⚠️ Step 4c 건너뜀 금지: critic_count > 0이면 opinions 수집 후 반드시 Critic 평가 수행

### 프롬프트 파일 생성 원칙 (CRITICAL)

`shared-context.md`는 단독 Write, 프롬프트 파일은 **단일 combined 파일 Write → 스크립트 split** 패턴을 사용합니다:
- `session.json`, `shared-context.md` 작성은 기존대로 단일 응답 내 Write 처리
- 프롬프트 파일(N+M개)은 `prompts/combined-prompts.txt` **1개**에 `===SPLIT: {filename}===` 구분기호로 모두 포함
- combined-prompts.txt Write 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/NN/prompts` 실행

### Step 2: 초기 의견 수집

**IDN-NNN 입력 시**: ideation 의견 파일들을 `rounds/00/{participant.key}.md`로 복사 → Step 4 진입

**새 주제인 경우**:

1. **Dispatch 프롬프트 조립 — feature flag 분기**

   config 확인:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py config get prompt_builder.enabled prompt_builder.fallback_on_error
   ```

   #### (a) prompt_builder.enabled=true (하이브리드 JSON 경로, 권장)
   1. `shared-context.md` 본문을 `.gran-maestro/tmp/ctx-{session_id}.md`로 Write (기존 shared-context.md와 동일 내용, tmp 복사본)
   2. `dispatch-input.json`을 아래 스키마로 Write:
      ```json
      {
        "format": "mst.dispatch",
        "schema_version": 1,
        "common": {
          "topic": "{DSC-NNN 주제}",
          "constraints": ["..."],
          "reference_context_file": ".gran-maestro/tmp/ctx-{session_id}.md"
        },
        "tasks": [
          {"role": "{participant.key}", "angle": "{perspective}", "ask": "핵심 질문 1~3개 ≤200자"},
          {"role": "{participant.key}", "angle": "{perspective}", "ask_file": ".gran-maestro/tmp/task-{role}-ask.md"}
        ]
      }
      ```
      - `format: "mst.dispatch"`, `schema_version: 1`
      - `common`: `topic`, `constraints[]`, `reference_context_file: ".gran-maestro/tmp/ctx-{session_id}.md"`
      - `tasks[]`: 각 participant/critic마다 `{role: "{participant.key}", angle: "{perspective}", ask: "...≤200자"}` 또는 `ask_file: "..."}`
      - 200자 초과 질문은 `.gran-maestro/tmp/task-{role}-ask.md`로 Write 후 `ask_file` 경로 참조
   3. CLI 호출:
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py prompt build \
        --input {absolute_path}/dispatch-input.json \
        --out-dir {absolute_path}/rounds/00/prompts \
        --sid {session_id}
      ```
   4. 성공 시 생성된 `rounds/00/prompts/combined-prompts.txt`를 기존대로 `session split-prompts`로 분할:
      ```bash
      python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/00/prompts
      ```
      → `rounds/00/prompts/{participant.key}-prompt.md` × N, `rounds/00/prompts/critique-{criticKey}-prompt.md` × M 자동 생성
   5. 실패 시 (exit != 0) → (b) fallback 경로로 자동 전환

   #### (b) prompt_builder.enabled=false 또는 CLI fallback (기존 직접 조립 경로)
   **단일 응답에서 동시 Write 후 split 실행**:
   - `rounds/00/shared-context.md` — 주제 배경 + 핵심 논점
   - `rounds/00/prompts/combined-prompts.txt` — N+M개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함
     (participant N개 + critic M개, 아래 포맷 그대로 적용)

   combined-prompts.txt Write 완료 직후:
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/00/prompts
   ```
   → `rounds/00/prompts/{participant.key}-prompt.md` × N, `rounds/00/prompts/critique-{criticKey}-prompt.md` × M 자동 생성

   #### fallback 규약 (MANDATORY)
   (a) 경로 실행 중 `mst.py prompt build`가 exit 2/3 등 실패 반환 시:
   - stderr 로그와 구조화 errors JSON을 Read
   - PM이 지적된 오류를 기반으로 JSON을 1회 수정 후 재시도 (repair 1회)
   - 재시도 실패 시 즉시 (b) 기존 직접 조립 경로로 전환 (workflow 차단 금지)
   - `config.prompt_builder.fallback_on_error=false`이면 repair 실패 시 워크플로우를 중단하고 사용자 에스컬레이션

   참고: `mst.py prompt build`는 오류 반환만 담당하며, repair 1회/fallback 전환은 본 스킬(discussion)의 책임이다.

   이후 2번(participant Task 발송)부터는 기존 내용 그대로 진행.

개별 프롬프트 포맷 (Round 0):
```markdown
# {Role} 관점 의견 요청 — DSC-NNN Round 0

## 공유 컨텍스트
{absolute_path}/rounds/00/shared-context.md 파일을 Read하세요.

## 당신의 역할
{perspective} 관점에서 분석합니다.

## 질문
{역할별 핵심 질문 1~3개}

## 출력 요구사항
- {absolute_path}/rounds/00/{participant.key}.md에 저장
- {response_char_limit}자 이내
```

Critic 프롬프트 템플릿 (Round 0):
```markdown
# Critic 평가 요청 — {session_id}  Round 0

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/rounds/00/{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/rounds/00/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

2. **participant + critic provider 동시 발송** (단일 응답):

   각 participant/critic에 shared routing protocol을 독립 적용한다. Same-host Codex는 collaboration agent, same-host Claude는 Task/Agent와 native lifecycle을 사용한다. 아래 Bash 예시는 `route=external` 전용이다.

   > **모델 결정**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get discussion.agents.claude.tier models.providers.claude.default_tier)`로 tier를 구한 뒤 `models.providers.claude[{tier}]`로 resolve (opus / sonnet)

   participant 발송 (`participants` 동적 순회):
   - `provider: "codex"`, external lane only:
     ```
     Bash(
       run_in_background: true,
       command: "codex exec --sandbox workspace-write -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/00/prompts/{participant.key}-prompt.md)\" > {absolute_path}/rounds/00/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/{participant.key}.md; exit $EC"
     )
     ```
   - `provider: "agy"`:
     ```
     Bash(
       run_in_background: true,
       command: "agy --print \"$(cat {absolute_path}/rounds/00/prompts/{participant.key}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/rounds/00/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/{participant.key}.md; exit $EC"
     )
     ```
   - `provider: "claude"`, same-host native candidate:
     ```
     Task(
       subagent_type: "general-purpose",
       model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
       run_in_background: true,
       prompt: "{absolute_path}/rounds/00/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. DELEGATION BOUNDARY를 준수하고 결과를 {absolute_path}/rounds/00/{participant.key}.md에 Write. 완료 후 '완료'"
     )
     ```
     `route=external`이면 `/mst:claude` managed wrapper를 사용한다.

   critic 동시 발송 (`critics` 동적 순회):
   - `provider: "codex"`, external lane only:
     ```
     Bash(
       run_in_background: true,
       command: "codex exec --sandbox workspace-write -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/rounds/00/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/critique-{criticKey}.md; exit $EC"
     )
     ```
   - `provider: "agy"`:
     ```
     Bash(
       run_in_background: true,
       command: "agy --print \"$(cat {absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/rounds/00/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/00/critique-{criticKey}.md; exit $EC"
     )
     ```
   - `provider: "claude"`, same-host native candidate:
     ```
     Task(
       subagent_type: "general-purpose",
       model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
       run_in_background: true,
       prompt: "{absolute_path}/rounds/00/prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판적 시각으로 분석. DELEGATION BOUNDARY를 준수하고 결과를 {absolute_path}/rounds/00/critique-{criticKey}.md에 Write. 완료 후 '완료'"
     )
     ```
     `route=external`이면 `/mst:claude` managed wrapper를 사용한다.

3. **진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
의견 수집 중  ({session_id}  Round 0)
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

각 호출은 route가 선택한 host-native background agent 또는 external background process로 병렬 실행됩니다.

### Step 3: PM 초기 종합

`rounds/00/synthesis.md` 생성: `rounds/00/{participant.key}.md` 순회 → `templates/discussion-round-synthesis.md` 템플릿 사용 → `status: "debating"`, `current_round: 0`

#### Step 3.5: Critic 초기 평가 (단일 라운드 수렴 시)

`critic_count >= 1`이면: `rounds/00` 응답 기반으로 `rounds/00/prompts/critique-{criticKey}-prompt.md` 생성 → Step 4c와 동일 방식으로 `rounds/00/critique-{criticKey}.md` 저장. Step 4 미실행 시에도 Critic 평가 보장.

> **NOTE**: "Step 4c와 동일 방식"은 Step 2 (R0)의 provider route를 다시 적용한다는 뜻이다. Same-host Codex/Claude는 native bridge, `route=external`인 Codex/AGY/Claude만 managed process/wrapper를 사용하며 경로는 `rounds/00/prompts/critique-{criticKey}-prompt.md` → `rounds/00/critique-{criticKey}.md`다.

### Step 3.6: Round 0 완료 상태 업데이트

`participants` 순회 → `rounds/00/{participant.key}.md` 존재 여부 확인 (성공: `"done"`, 실패: `"failed"`)

`session.json` 단일 Write:
- `participants` 상태 반영, `rounds` 배열에 `{ "round": 0, "status": "completed" }` 추가, `current_round: 0`, `status: "debating"`

### Step 4: 토론 라운드 (반복)

#### 4a. PM이 맞춤 프롬프트 작성

이전 라운드 발산점 기반으로 **단일 응답에서 Write 후 split 실행**:
- `rounds/NN/shared-context.md` — 이전 라운드 입장 요약 테이블 + 발산점 목록
- `rounds/NN/prompts/combined-prompts.txt` — N개 프롬프트를 `===SPLIT: {filename}===` 구분기호로 구분하여 1개 파일에 모두 포함

combined-prompts.txt Write 완료 직후:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/rounds/NN/prompts
```
→ `rounds/NN/prompts/{participant.key}-prompt.md` × N 자동 생성

> Round N의 critic 프롬프트가 있는 경우 같은 combined 파일에 포함하여 함께 split

`shared-context.md` 구조 (Round N):
```markdown
# DSC-NNN Round N — 공유 컨텍스트

## 이전 라운드 입장 요약
| 역할 | 핵심 주장 |
|------|----------|
| {role} ({provider}) | {1~2줄 요약} |
...

## 핵심 발산점
1. {발산점 1}
2. {발산점 2}

## 이번 라운드 목표
{PM이 수렴 방향 제시}
```

개별 프롬프트 포맷 (Round N):
```markdown
# {Role} 반론 수용 요청 — DSC-NNN Round N

## 공유 컨텍스트
{absolute_path}/rounds/NN/shared-context.md 파일을 Read하세요.

## 당신의 역할
{role} 관점에서 응답합니다.
이전 라운드 당신의 핵심 입장: {1~2줄}

## 이번 라운드 질문
{역할에 맞춘 반론/수렴 질문 1~3개}

## 출력 요구사항
- {absolute_path}/rounds/NN/{participant.key}.md에 저장
- {response_char_limit}자 이내
```

#### 4b. 역할 기반 병렬 호출

**단일 응답에서** participant 프롬프트 파일 + critic 프롬프트 파일을 함께 생성 후, participant + critic의 route-selected background 호출을 동시 발송한다.

Critic 프롬프트 템플릿 (Round N):
```markdown
# Critic 평가 요청 — {session_id}  Round {N}

## 대기 지시
다음 명령을 실행하고 결과를 기다리세요:
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files {participants 순회 → {absolute_path}/rounds/NN/{participant.key}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 다음 단계를 수행합니다.
TIMEOUT이면 완료된 파일들만으로 진행합니다.

## 역할
비판적 시각에서 모든 의견의 허점, 엣지 케이스, 반론을 식별합니다.

## 출력 요구사항
- {absolute_path}/rounds/NN/critique-{criticKey}.md에 저장
- {critique_char_limit}자 이내
```

participant 발송 (`participants` 동적 순회):
- participant별 shared route/lifecycle을 먼저 적용한다. 아래 Codex Bash는 external lane only이고 same-host Codex는 collaboration agent를 사용한다.
- `provider: "codex"`, external lane only:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --sandbox workspace-write -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md)\" > {absolute_path}/rounds/NN/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/{participant.key}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/rounds/NN/{participant.key}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/{participant.key}.md; exit $EC"
  )
  ```
- `provider: "claude"`, same-host native candidate:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/rounds/NN/prompts/{participant.key}-prompt.md 파일을 Read하고 지시에 따라 분석. DELEGATION BOUNDARY를 준수하고 결과를 {absolute_path}/rounds/NN/{participant.key}.md에 Write. 완료 후 '완료'"
  )
  ```
  `route=external`이면 `/mst:claude` managed wrapper를 사용한다.

critic 동시 발송 (`critics` 동적 순회):
- critic별 shared route/lifecycle을 먼저 적용한다. 아래 Codex Bash는 external lane only이고 same-host Codex는 collaboration agent를 사용한다.
- `provider: "codex"`, external lane only:
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --sandbox workspace-write -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex discussion 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md)\" > {absolute_path}/rounds/NN/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/rounds/NN/critique-{criticKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/rounds/NN/critique-{criticKey}.md; exit $EC"
  )
  ```
- `provider: "claude"`, same-host native candidate:
  ```
  Task(
    subagent_type: "general-purpose",
    model: "{config.models.providers.claude[discussion.agents.claude.tier || default_tier]}",
    run_in_background: true,
    prompt: "{absolute_path}/rounds/NN/prompts/critique-{criticKey}-prompt.md 파일을 Read하고 비판적 시각으로 분석. DELEGATION BOUNDARY를 준수하고 결과를 {absolute_path}/rounds/NN/critique-{criticKey}.md에 Write. 완료 후 '완료'"
  )
  ```
  `route=external`이면 `/mst:claude` managed wrapper를 사용한다.

**진행 상황 출력** (모든 Task() dispatch 완료 직후):

```
토론 라운드 {N}  ({session_id})
─────────────────────────────
  [→] {participant.role}  ({participant.provider})   ← participants 배열 동적 순회
  ...

  ── 비평 ──
  [→] critic: {criticKey}  ({critic.provider})       ← critics 객체 동적 순회
─────────────────────────────
완료 알림을 기다리는 중...
```

- critics가 없으면 `── 비평 ──` 섹션 전체 생략
- 목록은 `participants` 배열, `critics` 객체를 각각 동적 순회 (고정 인원 표기 금지)

### Step 4c. Critic 완료 확인 ⚠️ MANDATORY

> **절대 건너뛰기 금지**: `critic_count > 0`이면 Step 4d로 진행하기 전 `critique-{criticKey}.md` 파일이 존재해야 한다.

`critics` 키 순회 → `rounds/NN/critique-{criticKey}.md` 존재 + 비어있지 않음: `"done"`, 아니면: `"failed"`.
실패 시 에러 처리는 기존 에러 처리 섹션 준수.

### Step 4d. 라운드 종합

> **사전 조건**: `critic_count > 0`이면 `rounds/NN/critique-{criticKey}.md` 존재 필수. 없으면 Step 4c로 복귀.

- 입력: `rounds/{NN-1}/synthesis.md` + `rounds/NN/{participant.key}.md` + `rounds/NN/critique-{criticKey}.md`
- 출력: `rounds/NN/synthesis.md` (`templates/discussion-round-synthesis.md` 동적 표 사용)
- `status`, `current_round` 업데이트

### Step 4d.5: Round N 완료 상태 업데이트

`participants` 순회 → `rounds/NN/{participant.key}.md` 존재 여부 (성공: `"done"`, 실패: `"failed"`)
`critics` 순회 → `rounds/NN/critique-{criticKey}.md` 존재 여부 (성공: `"done"`, 실패: `"failed"`)

`session.json` 단일 Write: `participants`/`critics` 상태 반영, `rounds` 배열에 `{ "round": N, "status": "completed" }` 추가, `current_round: N`

### Step 4e. 수렴 판단

PM이 합의 정도 판정: 기준 충족 또는 최대 라운드 도달 시 Step 5, 미충족 시 다음 라운드 수행.

### Step 5: 합의문 작성

최종 consensus.md 생성: `participants` 키/Provider 동적 나열, 미합의 사항 행 반복, 라운드 합의 이력 및 critic 기여 기록.

## 에러 처리

- 과반 이상 성공: 실패 항목 제외 후 진행
- 과반 미만 성공: PM 자체 보완 분석
- 전원 실패: 에러 + 재시도 안내

## 세션 파일 구조

```
.gran-maestro/discussion/DSC-NNN/
├── session.json
├── rounds/
│   ├── 00/
│   │   ├── shared-context.md           # 공유 배경 컨텍스트 (Step 2 병렬 Write)
│   │   ├── prompts/
│   │   │   ├── {participant.key}-prompt.md  # 경량 프롬프트 (shared-context.md Read 지시 포함)
│   │   │   ├── critique-{criticKey}-prompt.md
│   │   │   └── synthesis-prompt.md
│   │   ├── {participant.key}.md
│   │   ├── critique-{criticKey}.md
│   │   └── synthesis.md
│   └── NN/
│       ├── shared-context.md           # 이전 입장 요약 + 발산점 (Step 4a 병렬 Write)
│       ├── prompts/
│       │   ├── {participant.key}-prompt.md  # 경량 프롬프트 (shared-context.md Read 지시 포함)
│       │   └── critique-{criticKey}-prompt.md
│       ├── {participant.key}.md
│       ├── critique-{criticKey}.md
│       └── synthesis.md
├── consensus.md
```

## 옵션

- `--focus {architecture|ux|performance|security|cost}`: 분석 포커스 지정
- `--max-rounds {N}`: 최대 토론 라운드 지정

## 참고

총합 2~7명 규칙과 participants/critics 동적 배정은 ideation과 동일.
