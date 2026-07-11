---
name: feedback
description: "Gran Maestro 워크플로우 내에서 수동 피드백을 제공합니다 (Phase 4). 사용자가 진행 중인 요청에 대해 '피드백'을 말하거나 /mst:feedback을 호출할 때 사용. 일반적인 코드 수정 요청이나 워크플로우 외부의 '수정해줘', '변경해줘'에는 사용하지 않음."
user-invocable: true
argument-hint: "{REQ-ID} {피드백 내용}"
---

# maestro:feedback

사용자가 직접 피드백을 제공하여 Phase 4(피드백 루프)를 트리거합니다.

## 필수 입력 스키마

mst:feedback 실행 시 아래 정보를 반드시 제공해야 합니다:

- `failure_class`: `ac_unclear | interpretation | implementation` 중 하나 (필수)
  - `ac_unclear`: AC/spec 자체가 모호하거나 불완전한 경우
  - `interpretation`: 구현 의도와 실제 결과가 불일치한 경우
  - `implementation`: 올바른 의도로 구현했으나 실행 오류가 발생한 경우
- `evidence`: AC-ID 매핑 배열 (최소 1개 필수). 각 항목은 아래 필드를 포함해야 함:
  - `ac_id`: 관련 AC ID (예: `AC-01`). `spec.md`의 AC-ID와 일치해야 함. 불일치 시 경고를 표시하고 PM이 확인하도록 안내함 (차단은 아님). `ac_id`가 누락된 경우 경고를 표시하며 차단 여부는 PM이 판단함.
  - `type`: `log | screenshot | metric | manual`
  - `ref`: 증거 경로 또는 설명
  - `summary`: 실패 내용 요약
- `next_action`: 재작업 지시 내용 (구현 방법을 지시하지 않고, 어느 AC/기준을 복구해야 하는지만 명시)

**스키마 검증 규칙 (차단):**
- `failure_class`가 제공되지 않았거나 허용값(`ac_unclear | interpretation | implementation`) 외의 값이면 → 오류를 반환하고 피드백 저장 및 전파를 차단함
- `evidence` 배열이 비어 있거나 제공되지 않았으면 → "evidence가 없으면 판정 불가" 오류를 반환하고 차단함

## 실패 분류별 자동 라우팅

라우팅 기준: `templates/protocols/failure-routing.md` 참조

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

#### 1. Route를 먼저 확정한다

1. `python3 {PLUGIN_ROOT}/scripts/mst.py host context --json`을 실행하고 JSON의 `host`를 읽는다. 이 호출 실패, 잘못된 JSON, 알 수 없는 host는 임의 추정하지 말고 **blocked**로 종료한다.
2. 이어서 반드시 아래 중앙 planner를 호출한다. `{scope}`는 현재 작업의 실제 scope(`implementation`, `review`, `exploration`, `ideation`, `discussion`, `debug`, `analysis`)이고, `{provider}`는 선택된 `codex | claude | agy`다.

   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py delegation route \
     --host "{host}" \
     --provider "{provider}" \
     --scope "{scope}" \
     --capability-status "{available|unknown|unavailable}"
   ```

3. route 결과 외의 근거로 transport를 바꾸지 않는다.
   - `route=native_candidate`: 같은 host/provider의 native bridge만 사용한다. `handshake_required=true`이면 실제 host tool 가용성을 확인한 뒤 진행한다.
   - `route=external`: 이 경우에만 아래에 남아 있는 managed wrapper, `dispatch build`, provider CLI adapter 예시를 사용할 수 있다.
   - `route=blocked`, CLI non-zero, lifecycle 응답의 `status=blocked`, 또는 현재 attempt의 `phase=reconciling`: 즉시 fail closed 한다. 같은 task/worktree에 새 agent나 external process를 시작하지 않는다.

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

- `host=codex, provider=codex`: Codex collaboration native tools를 사용한다. `collaboration.spawn_agent`로 spawn하고, host가 제공하는 attach/follow-up 수단으로 같은 task에 연결하며, `collaboration.wait_agent`로 대기한 뒤 전달된 completion result를 수집한다. 병렬 fan-out은 독립 task마다 native agent를 하나씩 spawn한다.
- `host=claude, provider=claude`: Claude의 `Task(...)` 또는 `Agent(...)` native tool로 spawn한다. background task는 host의 `TaskOutput`/resume 결과로 대기·수집한다.
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
  --expected-attempt-id "{external_attempt_id}"
```

Native definitive non-creation fallback이면 새 authorization을 만들지 않고 `delegation fallback`이 반환한 external `attempt_id`를 `--expected-attempt-id`로 사용한다. Builder는 current attempt의 task/provider/resolved worktree/prompt hash/route를 재검증하므로 native, reconciling, stale attempt, 또는 mismatch 상태에서는 command를 만들지 않는다. Codex/Claude 보호 wrapper는 provider command나 split claim/finalize shell을 포함하지 않고 `dispatch run-external` 단일 감독자만 호출한다. 감독자는 먼저 side effect가 없는 anonymous exec gate를 띄워 PID/PGID/start identity를 CAS로 attach하고, 같은 task lock 안에서 취소보다 먼저 exec 권한이 확정된 경우에만 실제 provider를 release한다. claim에서 캡처한 정확한 prompt bytes를 stdin으로 전달하고, provider process group을 회수한 뒤 fresh single-link inode로 claim해 계속 보유한 non-following output descriptor로 결과를 게시한다. prompt/snapshot/running/trace/output alias와 MST state·lock·history reserved path alias는 provider spawn 전에 차단한다. `claim-external`/`heartbeat-external`/`finalize-external`을 별도로 호출하거나 prompt snapshot/output pathname을 shell에서 다시 열지 않는다. Prompt 본문·snapshot path·claim secret·descriptor number는 argv/state/history에 확장하지 않는다.

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

1. `$ARGUMENTS`에서 REQ ID + 피드백 내용 파싱
   > 이 Step의 목적: 피드백 대상 요청과 입력 본문을 식별한다 / 핵심 출력물: 유효한 `REQ-ID`와 원본 피드백 텍스트
2. Feedback Composer 활성화 → 구조화된 피드백 문서 변환 → `tasks/NN/feedback-RN.md` 저장
   > 이 Step의 목적: 자유 입력 피드백을 실행 가능한 포맷으로 정규화한다 / 핵심 출력물: `feedback-RN.md`
3. 실패 유형 분류 및 라우팅:
   > 이 Step의 목적: 실패 원인을 `failure_class`로 고정하고 후속 경로를 결정한다 / 핵심 출력물: `failure_class` 기반 라우팅 결정

   라우팅 기준: `templates/protocols/failure-routing.md` 참조
4. 피드백 라운드 카운터 증가; 최대 횟수(기본 5회) 초과 시 사용자 개입 요청
   > 이 Step의 목적: 반복 피드백 루프의 상한을 관리한다 / 핵심 출력물: 증가된 피드백 라운드 카운터와 초과 시 개입 신호

### 외주 재실행 프로토콜 (구현 오류 시)

**반드시 provider에 외주하고 Claude(PM)는 직접 코드를 수정하지 않는다. 각 재실행 전에 shared route를 적용하며 same-host Codex/Claude는 native agent, external route만 managed `/mst:*` entrypoint를 사용한다.**

1. spec.md에서 `Assigned Agent` 확인
2. 수정 프롬프트 구성: spec.md §3 수락 조건 + feedback-RN.md 수정 요청 + §5 테스트 명령
3. 외주 실행:
   - codex-dev → same-host `native_candidate`는 collaboration agent + native lifecycle; `route=external`만 `Skill("mst:codex", "--dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
   - agy-dev → external route의 `Skill("mst:agy", "--dir {worktree_path} --files {worktree_path}/**/* --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
   - claude-dev → same-host `native_candidate`는 Task/Agent + native lifecycle; `route=external`만 `Skill("mst:claude", "--prompt-file {prompt_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
4. **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 2 phase2_execution`; 실패 시 fallback으로 `current_phase`=2, `status`=`phase2_execution` 직접 업데이트 → 완료 후 사전 검증 → Phase 3
5. **외주 재실행 완료 후 Phase 3 복귀**:
   - **자동 실행 경로**: approve 스킬이 활성 상태(approve 루프)인 경우, Phase 3(mst:review)은 approve 루프에서 자동으로 재트리거됨
   - **수동 실행 경로**: feedback이 독립 호출된 경우, 재작업 완료 후 `/mst:approve REQ-NNN`을 수동으로 호출해 Phase 3을 재시작해야 함

## 문제 해결

- "해당 요청을 찾을 수 없음" → REQ ID 형식 확인; `/mst:list`로 조회
- "최대 피드백 횟수 초과" → `/mst:settings workflow.max_feedback_rounds` 확인; 값 증가 또는 `/mst:request`로 스펙 재작성
- "활성 태스크 없음" → `/mst:inspect {REQ-ID}`로 Phase 2~3 여부 확인
