---
name: codex
description: "Codex provider 작업을 native-first로 위임합니다. 사용자가 '코덱스 실행', '코덱스로', '코드 작업'을 말하거나 /mst:codex를 호출할 때 사용. 같은 Codex host에서는 collaboration agent를 우선하고, 중앙 route가 external일 때만 Codex CLI adapter를 사용합니다."
user-invocable: true
argument-hint: "{프롬프트} [--prompt-file {경로}] [--dir {경로}] [--json] [--trace {REQ/TASK/label}] [--network]"
---

# maestro:codex

Codex provider 위임의 단일 진입점. 같은 Codex host에서는 collaboration native agent를 우선하고, cross-provider/headless/legacy opt-out처럼 중앙 route가 `external`을 반환한 경우에만 CLI adapter를 사용합니다. Maestro 모드 활성 여부와 무관합니다.

## DOD-003 Context Transfer Contract

이 entrypoint는 구현/분석 위임 시 prompt-file path와 context file path를 먼저 전달하는 parent-owned lifecycle boundary다. `--prompt-file`이 있으면 prompt-file path가 canonical prompt source다. Native lane은 `mst.py delegation` lifecycle과 host task result를, external lane은 wrapper의 running log/exit code를 evidence로 남긴다.

```text
[CONTEXT_FILES]
- objective: {path or NO_LINKED_OBJECTIVE}
- objective_ids: {path or NO_OBJECTIVE_IDS}
- plan: {path or NO_SOURCE_PLAN}
- plan_json: {path or NO_PLAN_JSON}
- plan_ids: {path or NO_PLAN_IDS}
- spec: {path}
- spec_context_manifest: {path or NO_CONTEXT_MANIFEST}
- previous_feedback: {path or N/A}
[/CONTEXT_FILES]

[WORK_CONTRACT]
- read_requirements: 구현 전 위 context file path와 spec_context_manifest를 직접 Read/inspection한다.
- output_contract: prompt-file path, worktree path, task id, trace label, route/transport, output artifact 또는 completion report를 보고한다. External lane이면 running log path도 포함한다.
- verification_contract: verify_cmd, expected_signal, trace path, native completion signal 또는 external exit code를 보고한다.
- failure_contract: timeout, empty result, blocked, reconciling, missing_context, NO_SOURCE_PLAN, NO_CONTEXT_MANIFEST를 구조화해 남긴다.
[/WORK_CONTRACT]
```

- native lifecycle boundary: `mst.py delegation start/acknowledge/attach/heartbeat/complete`가 PID/exit-code를 꾸미지 않고 host-native result를 기록한다.
- external wrapper-owned lifecycle boundary: route가 `external`일 때만 `mst.py run`이 register, heartbeat, running log tee, trace, session metadata, cwd/worktree binding, output/failure contract와 exit code propagation을 소유한다.
- provider subprocess detail: 실제 provider argv 조합과 permission flags는 runtime-owned internals이며 active implementation guidance는 이를 사용자 대면 계약으로 승격하지 않는다.

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

1. 프롬프트/옵션 파싱 (`--network` 포함; 지정 시 `NETWORK_MODE=true`)
2. **프롬프트 소스**: `--prompt-file` 있으면 파일 우선 (미존재 시 에러 중단); 없으면 인라인 사용
3. `--dir` 지정 시 디렉토리 존재 확인 (없으면 에러 중단); 상대경로는 cwd 기준
4. `--trace` 모드 판별 (아래 섹션 참조)
5. 공통 routing protocol로 host와 route를 결정한다. `native_candidate`면 Codex collaboration spawn/attach/wait/result 경로를 실행하고 native lifecycle evidence를 기록한다.
6. `route=external`인 경우에만 기본 모델과 Codex sandbox 플래그를 resolve한다:
   ```bash
   SANDBOX_ARGS="--full-auto"
   if [ "${NETWORK_MODE:-false}" = "true" ]; then
     SANDBOX_ARGS="-s danger-full-access -a on-request"
   fi
   ```
7. **External lane only** — `route=external`인 경우에만 Codex CLI adapter 실행:
   ```bash
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex")
   SANDBOX_ARGS="--full-auto"
   [ "${NETWORK_MODE:-false}" = "true" ] && SANDBOX_ARGS="-s danger-full-access -a on-request"

   # 인라인 프롬프트
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     \
     --log-dir "{task_dir}" \
     --require-worktree \
     --worktree-dir "{working_dir}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "{prompt}"

   # --prompt-file
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     \
     --log-dir "{task_dir}" \
     --require-worktree \
     --worktree-dir "{working_dir}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "$(cat {prompt_file})"

   # --trace 모드
   python3 {PLUGIN_ROOT}/scripts/mst.py run \
     --task-id "{task_id}" \
     --provider codex \
     \
     --log-dir "{task_dir}" \
     --trace "{REQ-ID}/{TASK-NUM}/{label}" \
     --require-worktree \
     --worktree-dir "{working_dir}" \
     -- codex exec ${SANDBOX_ARGS} -m "$MODEL" -C {working_dir} "$(cat {prompt_file})"
   ```
8. **결과 처리**: native lane은 host completion result와 nullable `exit_code`를 보존하고 `delegation complete`를 기록한다. External lane은 `--trace` → Trace 문서 자동 생성 후 exit code 반환, `--output` → 파일 저장, 둘 다 없음 → 결과 표시로 처리한다.

## Trace 모드 (워크플로우 내 자동 문서화)

`route=external`에서 `--trace {REQ-ID}/{TASK-NUM}/{label}` 인자를 wrapper에 전달하면 실행 완료 시 `{task_dir}/traces/codex-{label}-{ts}.md` 파일이 자동 생성됩니다. Native lane은 shared routing protocol의 trace/output evidence를 사용합니다.

형식: `--trace {REQ-ID}/{TASK-NUM}/{label}` (예: `REQ-001/01/phase2-impl`)

실행 예:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py run \
  --task-id REQ-001-01 \
  --provider codex \
  --model gpt-5.3-codex \
  --log-dir .gran-maestro/requests/REQ-001/tasks/01 \
  --trace REQ-001/01/phase2-impl \
  --require-worktree \
  --worktree-dir {worktree} \
  -- codex exec --full-auto -m gpt-5.3-codex -C {worktree} "$(cat {prompt_file})"
```

wrapper는 자동으로 다음을 처리합니다.
- `.gran-maestro/run/{task_id}.json`에 dispatch 상태 기록 (register + heartbeat)
- stdout/stderr를 `{log_dir}/running.log`에 tee
- 종료 시 exit_code 및 final phase 기록
- `--trace` 전달 시 `traces/*.md` 자동 생성

> **금지 마커 (MANDATORY)**: 이 스킬은 `NEXT_ACTION`, `step=returned`, `[MST skill=...]` 마커를 **절대 출력하지 않는다**.
> 이 마커들은 부모 스킬(approve 등)의 책임이며, 서브스킬이 출력하면 부모가 "이미 처리됨"으로 혼동한다.

> **Completion evidence (MANDATORY)**: external lane은 `mst.py run` 종료 코드를 기록한다. Native lane은 host completion signal을 기록하고 `exit_code=null`을 그대로 보존한다.

## 옵션

- `--prompt-file {path}`: 프롬프트를 파일에서 읽기 (인라인 프롬프트 대신). Native child 또는 external adapter에 같은 canonical prompt source를 전달한다.
- `--dir {path}`: 작업 디렉토리 지정 (기본: 현재 디렉토리)
- `--json`: JSON 형태로 구조화된 출력
- `--ephemeral`: 상태를 보존하지 않는 일회성 실행
- `--output {file}`: 결과를 파일로 저장 (독립 호출용)
- `--trace {REQ/TASK/label}`: 워크플로우 trace 문서 자동 생성 (stdout 반환 안 함)
- `--network`: Codex sandbox를 `-s danger-full-access -a on-request`로 전환 (미지정 시 `--full-auto`)

> `--trace`와 `--output`이 동시에 지정되면 `--trace`가 우선합니다.
> `--prompt-file`과 인라인 프롬프트가 동시에 지정되면 `--prompt-file`이 우선합니다.

## 예시

```
/mst:codex "이 프로젝트의 아키텍처를 분석해줘"
/mst:codex --prompt-file .gran-maestro/requests/REQ-001/tasks/01/prompts/phase2-impl.md --dir {worktree} --trace REQ-001/01/phase2-impl
/mst:codex --network --prompt-file .gran-maestro/requests/REQ-001/tasks/01/prompts/phase2-impl.md --dir {worktree} --trace REQ-001/01/phase2-impl
```

## 주의사항 / 문제 해결

- 같은 Codex host의 native lane에는 Codex CLI가 필요하지 않다. `route=external`인 경우에만 `codex --version` preflight가 필요하며 미설치 시 route의 `blocked/missing_cli` 결과를 그대로 보고한다.
- `--network`는 명시적으로 위험 권한을 허용하므로 네트워크가 반드시 필요한 작업에서만 사용
- `--full-auto` 모드는 기본 sandbox(workspace-write) 기준 파일 수정 권한이 있으므로 주의
- `--trace` 모드에서는 전체 결과가 파일에만 저장되고 부모 컨텍스트에 반환 안 됨
- "타임아웃" → `/mst:settings timeouts.cli_large_task_ms` 확인
- "trace 디렉토리 생성 실패" → `requests/{REQ-ID}/tasks/{TASK-NUM}/` 경로 확인

## Agile Sub-plan Isolated Execution (수동 격리 실행)

agile Sprint loop에서 컨텍스트 압박이 심해질 때, sub-plan 전체 체인(plan→request→approve→accept)을 별도 Codex agent 컨텍스트에서 실행할 수 있습니다. Same-host는 native collaboration agent를 사용하고, `route=external`일 때만 codex exec 격리 경로를 사용합니다. 이는 옵션 A(수동 escape hatch)로 제공되며 Sprint loop 자체를 우회하지 않습니다.

### 사용 예시

```bash
# 부모 세션에서 sub-plan worktree를 만들고 /mst:codex route로 전체 체인 실행
/mst:codex exec --dir .gran-maestro/worktrees/AGI-001/sprint-3/sub-plan-2 \
  "/mst:plan -a '사용자 프로필 편집 기능' && /mst:request -a --plan PLN-NNN && /mst:approve -a && /mst:accept"
```

### worktree 경로 규칙

```
{PROJECT_ROOT}/.gran-maestro/worktrees/AGI-NNN/sprint-N/sub-plan-M/
```

### 결과 확인

격리 실행 완료 후 부모 Sprint 세션에서 다음을 확인:

1. 생성된 REQ ID(`.gran-maestro/requests/REQ-NNN/request.json`)
2. 최종 커밋 SHA(`git -C {worktree_path} log -1 --format=%H`)
3. 실행 성공 여부(`sprints/sprint-N/result.json`)

### 주의사항

- 격리 실행은 Sprint의 **순차 실행이 기본**이며 이 escape hatch는 컨텍스트 압박 예외 상황에서만 사용합니다.
- 실행 후 반드시 `auto-decisions.md` 또는 `retrospective.md`에 격리 실행 사유와 결과를 기록해야 합니다 (Anti-Rationalization Checklist 준수).
- Sprint 2.2.3 자동 dispatch는 `config.agile.dispatch.enabled`와 `config.agile.dispatch.provider`를 기준으로 분기합니다. Codex-primary 기본값은 `agile.dispatch.provider=codex`이며, native lane은 delegation lifecycle이 host result를, external lane만 `mst.py run --provider codex -- codex exec ...`가 running log와 exit code를 수집합니다.
