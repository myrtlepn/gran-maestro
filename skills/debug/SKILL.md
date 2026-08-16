---
name: debug
description: "설정된 AI 에이전트들이 병렬로 버그를 조사하고 종합 리포트를 생성합니다. 사용자가 '디버그', '버그 찾아줘', '문제 분석'을 말하거나 /mst:debug를 호출할 때 사용. 1회성 의견 수집은 /mst:ideation을, 합의 토론은 /mst:discussion을 사용."
user-invocable: true
argument-hint: "{버그/이슈 설명} [--focus {파일패턴}]"
---

# maestro:debug

설정된 AI 팀원들이 **병렬로 버그를 조사**하고 PM(Claude)이 결과를 합쳐 종합 디버그 리포트를 생성합니다. Maestro 모드 활성 여부에 관계없이 사용 가능합니다.

## ideation/discussion과의 차이

| | ideation | discussion | **debug** |
|---|---|---|---|
| 목적 | 다양한 관점 수집 (발산) | 합의 도달 (수렴) | **버그 탐지 (조사)** |
| Claude 역할 | 종합자 (PM) | 사회자 (PM) | **종합자 (PM)** |
| 에이전트 역할 | 의견 제시 | 토론 참여 | **독립 조사 → 결과 문서** |
| 라운드 | 1회 | N회 반복 | **1회 (병렬 조사 후 합류)** |
| 종료 조건 | PM 종합 완료 | 참여자 합의 | **에이전트 합류 완료** |
| 출력 | synthesis.md | consensus.md | **debug-report.md** |

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

<!-- @include _shared/user-profile-read.md -->
### MANDATORY Read: `~/.claude/user-profile.json` (User Input Boundary 컨텍스트, 비차단)

1. `~/.claude/user-profile.json`을 Read한다.
   - 파일이 없으면 `user_profile_context = null`로 처리하고 **기존 동작을 유지**한다 (graceful fallback).
2. 파일이 있으면 JSON을 파싱하고 아래 필드만 사용한다.
   - `role` (string)
   - `experience_level` (string)
   - `domain_knowledge` (string[])
   - `communication_style` (string)
3. JSON 파싱 실패 또는 타입 불일치 시 warn만 출력하고 `user_profile_context = null`로 처리한다 (워크플로우 차단 금지).
4. 이후 User Input Boundary 질문 payload와 사용자 설명 텍스트 작성 시:
   - `communication_style`을 최우선 반영한다.
   - `experience_level`/`domain_knowledge`에 맞춰 용어 수준과 설명 깊이를 조절한다.
   - 누락 필드는 추정하지 않고, 존재하는 필드만 참고한다.
<!-- @end-include -->

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/debug/` 디렉토리 존재 확인, 없으면 생성
2. 새 세션 ID 채번 (DBG-NNN):
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type dbg` → 출력 ID 사용
   - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/debug/counter.json` 파일 Read
     - **파일 존재 시**: `next_id = last_id + 1`
     - **파일 미존재 시** (최초 또는 복구):
       a. `{PROJECT_ROOT}/.gran-maestro/debug/` 하위의 기존 DBG-* 디렉토리 스캔
       b. `{PROJECT_ROOT}/.gran-maestro/archive/` 내 `debug-*` tar.gz 파일명에서 ID 범위 추출
       c. 모든 소스에서 최대 번호 결정 → `counter.json` 생성: `{ "last_id": {max_number} }`
       d. `next_id = last_id + 1`
     - `counter.json` 업데이트: `{ "last_id": {next_id} }`
3. `{PROJECT_ROOT}/.gran-maestro/debug/DBG-NNN/` 디렉토리 생성 (NNN은 3자리 zero-padded)
4. `session.json` 작성:

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "id": "DBG-NNN",
  "issue": "{사용자 이슈 설명}",
  "focus": "{--focus 값 또는 null}",
  "status": "analyzing",
  "created_at": "{TS — mst.py timestamp now 출력값}",
  "dispatch_started_at": null,
  "investigators": {
    "codex": { "role": "", "status": "pending", "provider": "codex", "started_at": null, "completed_at": null },
    "agy": { "role": "", "status": "pending", "provider": "agy", "started_at": null, "completed_at": null }
  },
  "participant_config": { "codex": 1, "agy": 1, "claude": 0 },
  "merge_wait_ms": 60000,
  "fix_attempts": {
    "total_attempts": 0,
    "consecutive_failures": 0,
    "last_request_id": null,
    "last_result": null,
    "last_checked_at": null,
    "architect_escalation": {
      "triggered": false,
      "triggered_at": null,
      "status": "pending",
      "reason": null,
      "output_file": null
    }
  }
}
```

`investigators`는 config의 `debug.agents`를 읽어 생성합니다.
### investigators 동적 생성 규칙
1. 각 provider(codex, agy, claude)의 count 읽기
2. count == 1 → 키 이름은 provider 그대로
3. count > 1 → 첫 번째는 `{provider}`, 이후는 `{provider}-2`, `{provider}-3` ...
4. 각 항목에 `provider` 필드 기록
5. 합계 검증: 1~6명, 위반 시 에러 후 중단

`debug.agents` 키 없으면 기본값 `{ codex:1, agy:1, claude:0 }` 사용.

### fix_attempts 추적 규칙
1. Step 7에서 `/mst:request --from-debug {DBG-NNN}` 실행이 종료될 때마다 `fix_attempts`를 갱신합니다.
2. 판정 기준 (판정 소스: `{PROJECT_ROOT}/.gran-maestro/requests/{last_request_id}/request.json`의 `status` 필드):
   - **성공**: `request.json.status`가 `done`, `completed`, 또는 `accepted`인 경우
   - **실패**: Skill 호출 에러/중단, 또는 `request.json.status`가 위 값이 아닌 경우 (예: `failed`, `cancelled`)
3. 갱신 방식:
   - 성공: `total_attempts += 1`, `consecutive_failures = 0`, `last_result = "success"`, `last_request_id = "{최근 REQ-NNN}"`
   - 실패: `total_attempts += 1`, `consecutive_failures += 1`, `last_result = "failed"`, `last_request_id = "{최근 REQ-NNN 또는 null}"`
4. 동일 DBG 세션에서는 Step 7 재진입 시 기존 `session.json.fix_attempts`를 Read하여 누적 카운터를 이어갑니다.
5. **레거시 폴백**: `session.json`에 `fix_attempts` 키가 없으면(구버전 세션) Step 1 초기값(`total_attempts: 0`, `consecutive_failures: 0`, `architect_escalation.triggered: false`)을 자동 주입한 뒤 정상 진행합니다.

### Step 1.5: PM 역할 배정 (Investigation Assignment)

PM이 이슈를 분석하여 `investigators` 수만큼 조사 역할을 배정합니다.
- 이슈 분석: 증상, 재현 조건, 관련 모듈, 의심 영역 파악
- 조사 각도 배정: Codex(코드 레벨 추적), AGY(광역 컨텍스트), Claude(설계 의도/아키텍처)
- `session.json` 업데이트: `investigators[key].role` 기록, `status: "investigating"`

### AUTO-CONTINUE 원칙 (CRITICAL)

> **이 스킬의 모든 Step은 사용자 입력 없이 자율적으로 진행합니다.**
> - 백그라운드 작업 완료 시 사용자에게 확인 질문 금지
> - 모든 단계는 사용자 입력 없이 자동 진행
> - Step 2~5는 완전 자동, Step 6에서만 사용자 보고

### 병렬 Write 원칙 (CRITICAL)

독립 파일 Write는 하나의 응답에서 동시에 수행:
- `session.json`, 프롬프트 여러 개를 함께 생성
- 순차 쓰기를 피해 병렬성 보장

### Step 2: 에이전트 백그라운드 파견

`investigators` 키를 순회하여 조사 프롬프트를 작성하고 **즉시 백그라운드로 파견**합니다.

> **Claude 모델 결정**: config.resolved.json의 `models.providers.claude[debug.agents.claude.tier || default_tier]`로 resolve (미설정 시 `"sonnet"` 폴백).

#### 2a. Dispatch 프롬프트 조립 — feature flag 분기

config 확인:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py config get prompt_builder.enabled prompt_builder.fallback_on_error
```

##### (a) prompt_builder.enabled=true (하이브리드 JSON 경로)
1. 조사 공통 컨텍스트(이슈 설명, 집중 영역 등)를 `.gran-maestro/tmp/ctx-{session_id}.md`로 Write
2. `dispatch-input.json` Write:
   ```json
   {
     "format": "mst.dispatch",
     "schema_version": 1,
     "common": {
       "topic": "{DBG-NNN 이슈 제목}",
       "constraints": ["..."],
       "reference_context_file": ".gran-maestro/tmp/ctx-{session_id}.md"
     },
     "tasks": [
       {"role": "{investigatorKey}", "angle": "{role}", "ask": "조사 지침 ≤200자 또는 ask_file"}
     ]
   }
   ```
   - `tasks[]`는 `investigators` 키를 순회하여 작성
   - 각 task의 `role` 값은 `"{investigatorKey}"` 그대로 설정 (split 결과 파일이 `{investigatorKey}-prompt.md`로 생성되어 기존 dispatch 경로 호환)
   - 200자 초과 또는 줄바꿈 포함 시 `ask_file` 경로로 분리
3. CLI 호출: `python3 {PLUGIN_ROOT}/scripts/mst.py prompt build --input {absolute_path}/dispatch-input.json --out-dir {absolute_path}/prompts --sid {session_id}`
4. 성공 시: `python3 {PLUGIN_ROOT}/scripts/mst.py session split-prompts --dir {absolute_path}/prompts` 호출 → `prompts/{investigatorKey}-prompt.md` 개별 파일 생성 → 기존 dispatch (2b 단계) 그대로 실행
5. 실패 시 repair 1회 재요청 → 그래도 실패면 (b) 경로로 자동 전환

##### (b) prompt_builder.enabled=false 또는 CLI fallback
- 기존 개별 파일 직접 Write 경로 **그대로 유지** (변경 금지)

##### fallback 규약 (MANDATORY)
- CLI 오류 시 stderr/stdout을 Read, PM이 구조화 errors JSON 기반으로 JSON 수정 후 1회 재시도 (repair 1회)
- 재시도 실패 시 (b) 경로로 자동 전환 (`fallback_on_error=true`일 때)
- `fallback_on_error=false`이면 워크플로우 중단 + 사용자 에스컬레이션
- 참고: `mst.py prompt build`는 오류 반환만 담당, repair 1회/fallback 전환은 본 스킬(debug)의 책임이다

#### 2b. 프롬프트 파일 작성

`investigators` 키를 순회하여 `prompts/{investigatorKey}-prompt.md`를 **하나의 메시지에서 동시에 Write**합니다.

**프롬프트 작성 포맷:**

```markdown
# 버그 조사 요청

## 이슈
{사용자가 보고한 이슈 전체 내용}

## 당신의 조사 역할
당신은 {provider}입니다. 조사 각도: **{role}**

## 조사 지침
1. 아래 관점에서 코드베이스를 철저히 조사하세요
2. 구체적인 파일명, 라인 번호, 코드 스니펫을 포함하세요
3. 발견한 문제의 근본 원인(root cause)을 추론하세요
4. 수정 방안이 있다면 제안하세요

## 집중 영역
{--focus 값이 있으면 해당 파일 패턴, 없으면 "코드베이스 전체"}

## 출력 형식
응답을 {output_file}에 마크다운으로 작성하세요. 다음 섹션을 포함:
- **Symptom (증상)**: 관찰된 현상, 재현 조건, 영향 범위를 파일/라인 근거와 함께 명시
- **Hypothesis (가설)**: 가능한 근본 원인 가설(1~3개)과 우선순위, 각 가설의 근거
- **Experiment (실험)**: 가설 검증을 위해 수행한 코드 추적/재현 절차/명령 및 확인한 파일:라인
- **Result (결과)**: 실험 결과, 가설 채택/기각 판단, 최종 원인 결론, 수정 제안
- **Open Questions (추가 조사 필요 영역)**: 아직 검증되지 않은 항목과 후속 확인 계획

글자 수 제한: {config.collaborative_debug.finding_char_limit}자 이내
```

#### 2c. 병렬 호출

> investigator별 shared route/lifecycle을 먼저 적용한다. Same-host Codex는 collaboration, same-host Claude는 `Task(run_in_background: true)`, external route는 provider process/wrapper로 실행한다.

- `provider: "codex"`, external lane only (same-host native candidate는 collaboration agent):
  ```
  Bash(
    run_in_background: true,
    command: "codex exec --sandbox workspace-write -m $(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex debug 2>/dev/null || echo \"gpt-5.3-codex\") -C $(pwd) \"$(cat {absolute_path}/prompts/{investigatorKey}-prompt.md)\" > {absolute_path}/finding-{investigatorKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/finding-{investigatorKey}.md; exit $EC"
  )
  ```
- `provider: "agy"`:
  ```
  Bash(
    run_in_background: true,
    command: "agy --print \"$(cat {absolute_path}/prompts/{investigatorKey}-prompt.md)\" --dangerously-skip-permissions > {absolute_path}/finding-{investigatorKey}.md < /dev/null 2>&1; EC=$?; echo \"EXIT_CODE:$EC\" >> {absolute_path}/finding-{investigatorKey}.md; exit $EC"
  )
  ```
- `provider: "claude"`, same-host native candidate:
  ```
  Task(
    subagent_type: "general-purpose",
    run_in_background: true,
    prompt: "{absolute_path}/prompts/{investigatorKey}-prompt.md를 Read하고 직접 조사한다. DELEGATION BOUNDARY를 준수하고 결과를 {absolute_path}/finding-{investigatorKey}.md에 Write한 뒤 완료 보고"
  )
  ```
  `route=external`이면 nested Task를 만들지 않고 parent가 `/mst:claude` managed wrapper를 호출한다.

각 호출의 background task ID를 `session.json`에 기록합니다.

### Step 4: 합류 (Merge)

에이전트 파견 후 결과를 합류합니다.

#### 4a. 즉시 확인

`investigators` 순회 → `finding-{investigatorKey}.md` 존재 여부 확인:
- 존재 + 비어있지 않음 → `"done"`, 미존재/비었음 → `"in_progress"`

#### 4b. 대기 (필요 시)

모든 investigator `done`이면 즉시 Step 5 진행.

`in_progress` investigator가 있으면:
다음 명령을 실행하고 결과를 기다리세요 (타임아웃: `config.collaborative_debug.merge_wait_ms` ÷ 1000 초, 기본 60):
python3 {PLUGIN_ROOT}/scripts/mst.py wait-files \
  --timeout {config.collaborative_debug.merge_wait_ms을 1000으로 나눈 값, 기본 60} \
  {in_progress investigator들의 {absolute_path}/finding-{investigatorKey}.md 절대 경로 목록}

마지막 줄이 ALL_READY면 즉시 Step 4c로 진행.
TIMEOUT이면 완료된 결과만 사용, 미완료는 `"timeout"` 기록 후 Step 4c 진행.

#### 4c. session.json 업데이트

> ⏱️ **타임스탬프 취득 (MANDATORY)**:
> `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
> 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
> 출력값을 `merge_completed_at` 필드에 기입한다. 날짜만 기입 금지.

```json
{
  "status": "synthesizing",
  "investigators": {
    "codex": { "status": "done", ... },
    "agy": { "status": "timeout", ... }
  },
  "merge_completed_at": "{TS — mst.py timestamp now 출력값}"
}
```

### Step 5: 종합 리포트 작성

`status: "done"`인 `finding-{investigatorKey}.md`를 Read → `debug-report.md` 생성:
- 중복 제거 + 교차 검증: 다수 조사자가 동일 문제 지목 시 확신도 상승, 단독 발견은 "추가 검증 필요"
- 근본 원인 통합 최종 진단
- 수정 방안 우선순위 정렬 (P0/P1/P2)
- `session.json.fix_attempts.architect_escalation.triggered == true`이면 architect 위임 이력(트리거 조건/시각/결과 파일)을 `debug-report.md`에 포함

`session.json`의 `status`를 `"completed"`로 변경.

### Step 6: 사용자 보고

`debug-report.md`의 내용을 사용자에게 표시합니다.

표시 포맷:
```
## DBG-NNN 디버그 리포트

### 참여 조사자
- {investigatorKey} ({role}, {provider}): {status}  ← investigators 키 순서대로 반복
  (예: codex, codex-2, agy, claude 등 설정에 따라 동적 나열)

### 핵심 발견
{가장 확신도 높은 문제 1~3개}

### 수정 제안
{우선순위별 수정 방안}

### Architect 승격 (조건부)
{3회 연속 실패 시 자동 위임 결과 요약, 미발생 시 "없음"}

---
상세 리포트: .gran-maestro/debug/DBG-NNN/debug-report.md
```

### Step 7: 다음 단계 안내

> ℹ️ **AUTO-CONTINUE 예외**: 사용자 의사 확인 필요 → AskUserQuestion 사용.
> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

`AskUserQuestion`으로 선택지 제시:
- **"수정 작업 시작 (→ /mst:request)"**:
  1. `Skill(skill: "mst:request", args: "--from-debug {DBG-NNN} {이슈 제목 앞 50자}")` 실행
  2. 서브스킬 반환 직후 `session.json.fix_attempts` 갱신:
     - 성공: `total_attempts += 1`, `consecutive_failures = 0`, `last_result = "success"`, `last_request_id = "{최근 REQ-NNN}"`
     - 실패: `total_attempts += 1`, `consecutive_failures += 1`, `last_result = "failed"`, `last_request_id = "{최근 REQ-NNN 또는 null}"`
     - `last_checked_at`은 반드시 현재 UTC ISO-8601 타임스탬프로 기록
  3. `consecutive_failures >= 3` && (`architect_escalation.triggered == false` || `architect_escalation.status == "failed"`)이면 즉시 architect 자동 위임 (첫 위임 실패 후 추가 3회 실패 시 재위임 허용):
     ```text
     Task(
       subagent_type: "general-purpose",
       prompt: "{PROJECT_ROOT}/agents/architect.md를 Read한 뒤, DBG-NNN의 finding/debug-report를 기반으로 구조적 결함 재검토 문서 작성. 출력: {absolute_path}/architect-review.md"
     )
     ```
  4. architect 위임 시 `session.json.fix_attempts.architect_escalation` 업데이트:
     - `triggered: true`
     - `triggered_at: {UTC ISO-8601}`
     - `status: "requested" | "completed" | "failed"`
     - `reason: "3 consecutive failed fix attempts in same debug session"`
     - `output_file: "{absolute_path}/architect-review.md"`
  5. `debug-report.md`에 `## Architect Escalation` 섹션을 추가/갱신하여 위임 사실과 결과 파일 경로를 기록
- **"플랜으로 정제 후 진행 (→ /mst:plan)"** → `Skill(skill: "mst:plan", args: "--from-debug {DBG-NNN} {이슈 제목 앞 50자}")`
- **"리포트만 확인 (종료)"** → 스킬 종료

## 에러 처리

- 과반 이상 done: 정상 합성
- 과반 미만 done: 완료 결과만으로 리포트 생성 (미완료 수 명시)
- 전원 미완료/타임아웃: 에러 + 재시도 안내
- CLI 미설치: 해당 AI 스킵

## 세션 파일 구조

```
.gran-maestro/debug/DBG-NNN/
├── session.json
├── prompts/
│   ├── {investigatorKey}-prompt.md
│   └── ...
├── finding-{investigatorKey}.md
└── debug-report.md
```

## 옵션

- `--focus {파일패턴}`: 조사 범위를 특정 파일 패턴으로 제한 (예: `src/auth/**/*.ts`)

## 예시

```
/mst:debug "로그인 시 간헐적으로 401 에러가 발생합니다"
/mst:debug --focus src/api/**/*.ts "API 응답이 비정상적으로 느립니다"
/mst:debug "빌드 시 타입 에러가 발생하는데 원인을 모르겠습니다"
```

## 참고

- investigators 동적 배정은 ideation 규칙을 디버그용으로 재사용. roles 대신 investigators 사용은 디버그 고유 스키마.
- claude 포함 모든 provider가 동일 형식으로 investigators에 포함됩니다.
