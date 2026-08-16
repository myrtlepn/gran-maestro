---
name: agile-plan
description: "프로젝트 목표 + 설계 문서(objective.md)를 JTBD 기반 Q&A로 생성하고, 실행 전 검토 가능한 플래닝 세션을 초기화합니다."
user-invocable: true
argument-hint: "{프로젝트 목표 | --doc 파일경로 | --resume AGI-NNN} [--return-to parent/step] [-a|--auto]"
---

# maestro:agile-plan

**목적**: `/mst:agile-plan`으로 JTBD + 프로젝트 DoD 중심의 objective.md를 생성한다. 이 스킬은 플래닝 전용이며 Story 생성/실행은 담당하지 않는다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/objective.md` (신규 생성)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/details/*.md` (신규 생성)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/draft/objective.md` (staged draft)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/draft/details/*.md` (staged draft)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/clarification-context.md`
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/clarification-questions.md`
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/round-history.md`
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/adversarial-review-findings.md` (review transcript only; canonical JSON sidecar는 managed command 사용)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/quality-gate-log.md`
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/auto-decisions.md`
- `{PROJECT_ROOT}/.gran-maestro/state/{MST_SESSION_ID}/snapshot.json` (`agile init`이 반환한 `mst_session_id`, 상속된 `MST_SESSION_ID`, 또는 동일한 structured context로 기록되는 상태 파일)

그 외 모든 경로에 대한 Write/Edit 사용은 금지합니다.

- objective 상태 변경은 직접 편집이 아니라 `mst.py` 명령을 통해 수행한다.
- 프로젝트 DoD 체크리스트는 완료 판정의 유일한 게이트로 다룬다(DSC-047).

### Managed Artifact Contract (MANDATORY)

위 allowlist는 PM/에이전트의 직접 `Write/Edit` 도구 사용에만 적용한다. 아래 산출물은 직접 생성하지 말고 반드시 `mst.py` managed command를 통해 생성/갱신한다.

| 산출물 | 생성/갱신 경로 | 실패 시 처리 |
|--------|----------------|--------------|
| `objective.ids.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` 또는 `agile detail generate-anchors --details-dir ...` | completion blocker |
| `handoff-manifest.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | missing_context / completion blocker |
| `adversarial-review-findings.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | completion blocker |
| `finding-trace.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | completion blocker |
| `section-review-inventory.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | completion blocker |
| `d3-findings.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | completion blocker |
| `reference-links.json` | `python3 {PLUGIN_ROOT}/scripts/mst.py agile sidecar-build {AGI_ID}` | explicit skip reason 또는 fail_reference_handoff |
| `state/{MST_SESSION_ID}/snapshot.json` | `MST_SESSION_ID=... python3 {PLUGIN_ROOT}/scripts/mst.py state set ...` | structured non-success |
| `.gran-maestro/references/REF-*/` | `python3 {PLUGIN_ROOT}/scripts/mst.py reference add ...` | `NO_REFERENCE` / missing_context |
| DoD status marker 및 changelog | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition ...` | 전이 거부 |

managed command가 없거나 실패한 산출물을 직접 `Write/Edit`로 우회 생성하지 않는다. 실패는 해당 command 출력, sidecar schema validation, 또는 explicit skip reason으로 남긴다.

### Draft Lifecycle Contract (MANDATORY)

- 저장 전 초안은 먼저 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/draft/` 아래 staged draft로 materialize한다.
- 적대적 검토, source mapping, D3, anchor generation, handoff manifest 검증은 staged draft 또는 그 draft에서 생성한 sidecar evidence를 대상으로 수행한다.
- accepted `objective.md`와 `objective/details/*.md`는 mandatory gate가 모두 통과한 뒤에만 promote한다.
- gate 실패, review blocker, source mapping 실패, sidecar schema 실패가 있으면 accepted objective를 변경하지 않고 draft 경로와 failure reason만 남긴다.
- promotion 후에는 `objective-snapshot`, `objective-transition`, `sidecar-build`, `objective-check` 순서로 completion evidence를 재계산한다.

## Gate

### Entry

- Step 0.0에서 command identity/no-plan-mode preflight를 먼저 통과한다.
- preflight 통과 후 Step 0.2에서 `mst.py agile init`으로 AGI 세션을 생성한다.
- `--doc` 미지정 시 1A(Q&A 생성 모드), 지정 시 1B(문서 파싱 모드)로 분기한다.
- Story/작업 실행 루프로 진입하지 않는다. 이 스킬은 objective 생성까지만 수행한다.

### Exit

- `templates/objective.md` 포맷으로 objective.md 저장 완료
- `mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 완료
- `MST_SESSION_ID={MST_SESSION_ID} python3 {PLUGIN_ROOT}/scripts/mst.py state set --skill agile-plan --step 3 --total 3 [--return-to ...]` 기록 완료 (`MST_SESSION_ID`는 Step 0의 `agile init` 출력에서 확보하거나 현재 세션에서 상속됨)
- `--return-to`가 있으면 stop-hook continuation guard로 상위 스킬 복귀(re-feed), 없으면 독립 실행을 종료하고 `--resume` 안내
- 어떤 종료 경로든 사용자에게 보이는 마지막 마무리는 반드시 `다음 단계 실행 명령:` 블록으로 끝난다.
  - `--return-to` 존재: 자동 복귀가 정상 경로임을 밝히고, 수동 fallback 명령으로 `/mst:resume --wakeup-hint stop-recover`를 마지막에 출력한다.
  - `--return-to` 없음: `/mst:agile --resume AGI-NNN`을 마지막에 출력한다.
  - 마지막 줄 뒤에 추가 설명, 인사, 요약을 붙이지 않는다.

### 금지 패턴

- Story 레이어/Checklist 별도 실행 레이어를 objective에 생성하는 행위
- DoD 항목에 구현 방법(API 엔드포인트, 함수명, 파일명, 기술 스택)을 강제하는 행위
- Step 0 없이 objective 생성을 시작하는 행위
- 스프린트 횟수/완료 시점을 예측·확정·암시하는 표현을 objective/질문/보고에 기재하는 행위
- objective.md에 "예상 스프린트", "N회 스프린트", "X주 내 완료" 등 필드/문장을 추가하는 행위
- 캘린더 단위로 변환한 기간 추정(예: "4~8주 소요")을 기재하는 행위
- 과거 실적을 현재 프로젝트의 완료 시점/스프린트 횟수 예측 근거로 인용하는 행위

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

<!-- @include _shared/user-input-boundary.md -->
### User Input Boundary (MANDATORY)

사용자 입력이 필요한 지점에서는 host별 질문 도구를 직접 판단하지 말고 `question prepare`를 먼저 호출한다. 이 규칙은 기존 `AskUserQuestion` 직접 호출 지시보다 우선한다.

1. 질문 payload를 JSON 파일로 작성한다. 구조는 `templates/question-payload.schema.json`을 따른다.
2. 아래 CLI를 호출한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py question prepare \
     --skill {CURRENT_SKILL} \
     --step "{CURRENT_STEP}" \
     --resume-skill {CURRENT_SKILL} \
     --resume-args "{RESUME_ARGS}" \
     --payload-file {QUESTION_PAYLOAD_JSON} \
     --json
   ```
3. 반환값에 따라 분기한다.
   - `mode=claude_tool`: 반환된 `payload`로 `AskUserQuestion`을 호출한다.
   - `mode=pending_artifact`: 반환된 `user_message`를 사용자에게 보여주고 종료한다. 이 상태는 정상적인 사용자 입력 대기이며 임의 중단이 아니다.
   - `mode=auto_decision`: `AUTO_MODE=true` 경로로 질문 없이 계속하거나 blocker를 기록한다.
4. Codex/headless host에서는 `AskUserQuestion`을 직접 호출하지 않는다. pending question은 `.gran-maestro/questions/Q-*.json`에 저장되고 `/mst:resume --answer Q-...`로 재개한다.
5. workflow 중 임의 확인 질문이나 self-pause는 계속 금지한다. 정상 질문은 `question prepare`가 기록한 `awaiting_user_input` 상태와 payload hash가 일치할 때만 허용된다.
<!-- @end-include -->

---

### Step 0: 세션 초기화

`[MST skill=agile-plan step=0/3 return_to={RETURN_TO_OR_NULL}]`

#### 0.1 인자 파싱

| 플래그 | 설명 | 예시 |
|--------|------|------|
| `--doc 파일경로` | 기존 문서 파싱 모드 | `--doc docs/spec.md` |
| `--resume AGI-NNN` | 기존 AGI objective 재진입/recall patch 모드 | `--resume AGI-029` |
| `--return-to parent/step` | 서브스킬 복귀 지점 | `--return-to agile/1` |
| `-a`, `--auto` | parent agile 자율 모드 상속 | `--auto` |

- `--return-to` 미지정 시 독립 실행으로 간주 (`return_to=null`)
- `--auto`가 있거나 parent workflow state의 `auto=true`이면 `AUTO_MODE=true`로 고정한다. 이 값은 Step 0부터 Exit까지 유지하며 사용자 대기 질문을 생성하지 않는다.

#### Entry Mode Precedence Contract (MANDATORY)

Entry mode는 아래 순서로 deterministic하게 해석한다. 뒤 단계는 앞 단계 결정을 override하지 못한다.

1. `--resume AGI-NNN`: 기존 session/objective/history를 로드하며 `agile init`을 실행하지 않는다. recall patch manifest가 있으면 이 resume context 안에서만 Step 1P로 진입한다.
2. `--doc 파일경로`: `--resume`이 없을 때만 문서 파싱 모드(1B)를 선택한다.
3. Q&A objective 생성: `--resume`과 `--doc`이 모두 없을 때만 Step 1A를 선택한다.
4. `--return-to`: entry mode를 바꾸지 않는 exit routing only 값이다.
5. `--auto` 또는 parent workflow `auto=true`: entry mode를 바꾸지 않는 interaction policy 값이다.

충돌 해소 우선순위는 `CLI flags > inherited workflow state > config defaults > prompt summary diagnostic-only`이다. source precedence는 `validated history ledger`, `validated state snapshot`, `prompt summary diagnostic-only` 순서로만 읽으며 prompt summary는 canonical state를 만들거나 복구하는 source가 아니다.

상태 mutation에는 canonical `MST_SESSION_ID`/`mst_session_id`가 반드시 필요하다. canonical identity가 없거나 검증 실패하면 AGI/session/history/snapshot을 silent pass로 갱신하지 않고 structured non-success로 종료한다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, `sessionId`, `session_id`)은 diagnostic-only이며 canonical fallback이 아니다.

Regression fixture matrix는 최소한 아래 조합을 포함한다.
- `/mst:agile-plan --resume AGI-NNN --doc spec.md --return-to agile/1 --auto`: resume wins, doc ignored for mode, return-to is exit routing, auto only changes interaction policy.
- `/mst:agile-plan --doc spec.md` with no canonical identity mutation request: doc mode wins over Q&A.
- parent agile inherited `auto=true` without CLI `--auto`: AUTO_MODE=true, no AskUserQuestion wait.
- missing canonical `MST_SESSION_ID` on state write: structured non-success, no snapshot mutation.

#### 0.0 command identity/no-plan-mode preflight (MANDATORY, before side effects)

이 preflight는 `mst.py agile init`, 파일 생성, state 기록, 에이전트 위임보다 먼저 수행한다.

- 원시 입력의 command identity가 `/mst:agile-plan`으로 확정된 경우, 이 정체성을 Exit까지 고정한다.
- `/mst:agile-plan` 입력 본문에 `현재 구현을 변경`, `수정`, `구현 변경`, `개선`, `리팩터링`, `계획`, `구현`, `방향` 같은 구현 변경 또는 계획 수립 표현이 있어도 `/mst:plan`, `/mst:request`, Claude Code 내장 plan mode로 재분류하지 않는다.
- Claude Code 내장 plan mode로 진입하지 않는다. 어떤 단계에서도 `EnterPlanMode`를 호출하지 않고, transcript/tool-call/captured output에 `Entered plan mode`를 출력하지 않는다.
- 입력 형식이나 필수 정보 부족으로 objective/agile planning 입력으로 수용할 수 없으면, 아직 AGI 세션을 만들지 않은 상태로 수용 불가 사유를 보고하고 Step 0.5.3의 후보 제시 절차로만 이동한다.

#### 0.2 agile init 호출

0. `--resume AGI-NNN`이 있으면 `agile init`을 실행하지 않는다.
   - `python3 {PLUGIN_ROOT}/scripts/mst.py agile status AGI-NNN --json`으로 기존 session을 로드한다.
   - 로드 성공 시 기존 `AGI_ID`, `mst_session_id`, objective version/history를 그대로 사용한다. 새 AGI를 만들거나 objective를 새 파일로 복사하지 않는다.
   - `MST_SESSION_ID`는 session의 canonical `mst_session_id` 또는 상속된 structured context 값만 사용한다.
   - 재진입 목적이 recall patch이면 Step 1P로, 단순 정제 재진입이면 Step 1A.10 저장 규칙 검증으로 이동한다.
1. `--resume`이 없을 때만 `python3 {PLUGIN_ROOT}/scripts/mst.py agile init --steering-every 3 --json` 실행
2. 출력에서 `agi_id`를 파싱해 `AGI_ID`에 저장하고, `mst_session_id`를 파싱해 `MST_SESSION_ID`에 저장한다.
3. 이후 모든 `mst.py state ...` 호출은 아래처럼 동일한 canonical identity를 명시해 실행한다.
   ```bash
   MST_SESSION_ID="{MST_SESSION_ID}" \
   MST_CONTEXT_JSON='{"schema_version":1,"mst_session_id":"{MST_SESSION_ID}","root_mst_id":"{AGI_ID}"}' \
   python3 {PLUGIN_ROOT}/scripts/mst.py state ...
   ```
4. `[신규 세션] AGI-{NNN} 생성됨 (MST_SESSION_ID={MST_SESSION_ID}, 스티어링 설정은 agile에서 확정)` 출력
5. Step 1로 진행

### Step 0.5: 의도 분류 게이트

#### 0.5.0 command identity guard 확인 (MANDATORY)

- Step 0.0에서 command identity/no-plan-mode preflight가 이미 완료됐는지 확인한다. 완료되지 않았으면 Step 0.0으로 돌아가며, AGI/session/state side effect를 만들지 않는다.
- 원시 입력의 command identity가 `/mst:agile-plan`으로 확정된 경우, 이 정체성을 Exit까지 유지한다.
- 이 guard는 `/mst:agile-plan` command identity가 확정된 요청에만 적용한다. 일반 `/mst:plan` 및 `/mst:request` 요청의 command identity, 사용자 대면 라우팅, 산출물 절차는 변경하지 않는다.
- `/mst:agile-plan` 입력 본문에 `현재 구현을 변경`, `수정`, `구현 변경`, `개선`, `리팩터링`, `계획`, `구현`, `방향` 같은 구현 변경 또는 계획 수립 표현이 있어도 `/mst:plan`, `/mst:request`, Claude Code 내장 plan mode로 재분류하지 않는다.
- Claude Code 내장 plan mode로 진입하지 않는다. 어떤 단계에서도 `EnterPlanMode`를 호출하지 않고, transcript/tool-call/captured output에 `Entered plan mode`를 출력하지 않는다.
- 재현 fixture `/mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘`는 agile-plan 절차의 objective/agile planning 입력으로 먼저 처리한다.
- 입력 형식이나 필수 정보 부족으로 objective/agile planning 입력으로 수용할 수 없으면, agile-plan 응답 또는 산출물 안에 수용 불가 사유를 남기고 Step 0.5.2 또는 Step 0.5.3의 확인/후보 제시 절차를 따른다. 이 경우에도 다른 명령이나 내장 plan mode로 전환하지 않는다.

- PM은 요청 텍스트를 읽고 아래 질문을 내부 판단한다.
  - "이 요청이 새 프로젝트 objective를 정의하려는 의도인가?"
- confidence(0.0~1.0)를 산정한다.
- 기본 경로는 objective 생성이다. confidence가 낮을 때만 확인 질문을 수행한다.

#### 0.5.1 confidence >= 0.8 (직행)

1. `[의도 확인: objective 생성으로 진행]` 한 줄 통지를 출력한다.
2. Step 1A로 직행한다.
3. 요청 원문을 Step 1A JTBD Q&A의 초기 컨텍스트로 전달한다.

#### 0.5.2 confidence < 0.8 (1회 확인 질문)

질문/선택지 표기 규칙 (MANDATORY):
- 사용자가 직접 타이핑하기 쉬운 **알파벳 또는 숫자만** 사용한다.
- 허용 예시: `A`, `B`, `C`, `1`, `2`, `3`, `A1`, `B2`
- 금지 예시: `α`, `β`, `γ`, `i`, `ii`, `iii`, `I`, `II`, `III`
- objective 후보를 본문에 나열할 때도 동일 규칙을 적용한다.

1. AskUserQuestion으로 아래 확인 질문을 **1회만** 제시한다.
   - question: `이 요청을 objective 생성으로 진행할까요?`
   - options:
     - `objective 생성으로 진행`
     - `다른 의도 설명`
2. 사용자 응답이 `objective 생성으로 진행`이면 Step 1A로 진행한다.
3. Step 1A 진행 시 요청 원문 + Step 0.5 확인 대화 내용을 JTBD Q&A 초기 컨텍스트로 함께 전달한다.
4. 사용자 응답이 `다른 의도 설명`이면 Step 0.5.3으로 진행한다.
5. `AUTO_MODE=true`에서는 AskUserQuestion을 호출하지 않는다. confidence가 낮으면 `auto-decisions.md`와 `clarification-questions.md`에 blocker를 기록하고 structured non-success로 종료하거나, Step 0.5.3 후보 제시를 사용자 대기 없이 산출물로만 남긴다.

#### 0.5.3 메타/질문 처리 후 objective 선제시

> 목적: `/mst:agile-plan` 호출 자체는 objective 정의 의도 신호이지만, args 본문이 메타/질문이거나 0.5.2에서 "다른 의도"로 응답한 경우, 요청 동작을 먼저 수행한 뒤 objective 후보를 선제시한다.

1. 사용자가 실제로 요청한 동작(답변·설명·소규모 조사 등)을 먼저 수행한다.
2. 수행 결과를 바탕으로 **objective로 발전시킬 수 있는 후보 1~3개**를 선제시한다.
   - 형식: `[objective 후보] A. {후보1} B. {후보2} C. {후보3}` 또는 `[objective 후보] 1. {후보1} 2. {후보2} 3. {후보3}`
   - 후보 표기는 `A.`, `B.`, `C.`, `1.`, `2.`, `3.`처럼 쉬운 prefix와 의미 요약을 함께 사용한다. 그리스 문자·로마 숫자·bare prefix는 금지한다.
   - 후보가 도출되지 않으면 "objective 후보가 도출되지 않았습니다. agile-plan 입력으로 수용할 수 없는 사유: {사유}" 출력 후 종료한다. 다른 명령이나 내장 plan mode로 전환하지 않는다.
3. `AUTO_MODE=false`: AskUserQuestion으로 후보 중 선택받거나 UI 자동 Other로 직접 objective 입력받아 Step 1A로 진입한다. `"D. 종료"` 선택지를 포함한다.
4. `AUTO_MODE=true`: AskUserQuestion을 호출하지 않는다. 후보가 1개이고 objective 입력으로 충분하면 PM이 그 후보를 선택하고 근거를 `auto-decisions.md`에 기록한다. 후보가 2개 이상이거나 사용자 의존성이 있으면 `clarification-questions.md`에 blocker를 기록하고 structured non-success로 종료한다.
5. 선택된 주제를 Step 1A JTBD Q&A 초기 컨텍스트로 전달한다.

---

### Step 1: Objective 생성/정규화

`[MST skill=agile-plan step=1/3 return_to={RETURN_TO_OR_NULL}]`

`--doc`가 있으면 **1B**, 없으면 **1A**를 수행한다.

#### Step 1P: Recall Patch 재진입 모드 (Level 2 only)

`mst.py agile recall`이 patch manifest를 전달한 경우에는 아래 규칙을 우선 적용한다.

- **금지**: Step 1A 전체(Q&A/재귀 정제 루프) 재실행
- **허용**: manifest diff만 적용
  - DoD add/remove/reorder/split/merge
  - objective 문구 정밀화(의미 불변)
  - 통합 sprint 삽입
- 적용 후에는 Step 1A.10 저장 규칙(포맷/마커/evidence 필드)만 재검증하고 저장한다.
- objective 본질 변경(의미 변경)으로 판단되면 patch를 중단하고 Level 3 승인 경로로 에스컬레이트한다.
- Level 3 승인 manifest가 전달된 경우에는 아래 저장 규칙을 추가 적용한다.
  - objective.md의 JTBD/프로젝트 DoD 본문에 승인된 의미 변경만 반영한다.
  - objective.md frontmatter의 `version`을 1 증가시키고 `last_event_id`, `semantic_hash`를 갱신한다.
  - `.gran-maestro/agile/{AGI_ID}/objective/history/`에 append-only Level 3 변경 로그를 추가하고 기존 엔트리는 수정하지 않는다.

---

#### Step 1A: JTBD + 프로젝트 DoD Q&A 생성 모드

**목표**: JTBD 5개 질문과 프로젝트 단위 DoD/설계/제약 정보를 수집해 objective.md를 생성한다.

> ⚠️ **상세 보존 원칙 (CRITICAL — 전 Step 공통)**:
> 사용자가 대화 중 이야기한 **모든 설계 내용, 결정 근거, 합의 사항, 프로세스 설명, 기술 선택, 구조 명세**는
> objective 산출물(objective.md + details/*.md)에 **구체화·문서화**되어야 한다.
> - 사용자가 설명한 원본 설계는 요약/축약하지 않고 **원본 이상의 구체성**으로 details/에 기록한다.
> - plan 모드처럼 Q&A 정보까지 포함하여 더 구체화된 형태가 되어야 한다.
> - objective.md + details/ 하위 문서만으로 **충분히 개발할 수 있는 기반**이 되어야 한다.
> - 대화에서 논의되었으나 산출물 어디에도 기록되지 않은 내용이 있으면 **저장 전 보완 필수**.

##### 1A.1 JTBD Q&A (5개, 자연어 대화 순차 진행)

1. **Job Statement**: "어떤 상황에서 이 프로젝트를 진행하게 되었나요? (When I ...)"
2. **핵심 목표**: "이 프로젝트를 통해 무엇을 달성하고 싶으신가요? (I want to ...)"
3. **기대 결과**: "성공했을 때 얻게 되는 가치는 무엇인가요? (So I can ...)"
4. **성공 지표**: "완료를 어떻게 측정할 수 있을까요? (측정 가능한 지표)"
5. **완료 정의**: "프로젝트가 완료됐다고 판단하는 기준은 무엇인가요? (프로젝트 DoD)"

##### 1A.2 모호성 해소 체크리스트 (MANDATORY)

JTBD 직후 아래 항목을 점검한다. `WHO/WHAT/WHY`는 JTBD에서 이미 수집되므로 여기서 재질문하지 않는다.

1. **WHEN**: 완료 시점 또는 트리거 조건이 명확한가?
2. **WHERE**: 영향 받는 화면/시스템/모듈이 특정되었는가?
3. **HOW MUCH**: 성공이 수치 또는 관찰 기준으로 측정 가능한가?
4. **HOW**: 접근 방향(전략 수준)이 합의되었는가? (기술 구현 상세 제외)
5. **성능 NFR**: 응답시간/처리량/부하 목표가 필요한가?
6. **보안 NFR**: 인증/인가/데이터 보호 요구가 필요한가?
7. **호환성/접근성 NFR**: 디바이스/OS/브라우저/접근성 요구가 필요한가?
8. **오류 처리 NFR**: 실패 시 동작(복구/알림/재시도)이 정의되었는가?

운영 규칙:
- 미해결 항목이 있으면 자연어 대화로 보완하고 체크리스트를 재점검한다.
- 결과는 objective.md의 `프로젝트 NFR`, `설계 결정`, `프로젝트 완료 기준` 섹션에 반영한다.

##### 1A.2.5 목적 구체화 적대적 질문 게이트 (MANDATORY)

목적: JTBD/DoD 초기에 PM 자기과신으로 사용자 목적·범위·우선순위의 빈칸을 자동 보완하는 것을 막는다. 이 게이트는 D3의 후반 명료도 검증과 별개로, **사용자에게 물어야 할 질문**을 찾는 전방 안전망이다.

1. Step 1A.1~1A.2 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/clarification-context.md`에 저장한다. 포함 항목은 JTBD 5문항 답변, DoD 후보, 현재 제약/MoSCoW/NFR/리스크의 알려진 값과 미확인 값이다.
2. 독립 에이전트를 1회 이상 실행한다. Shared route를 먼저 실행해 same-host Codex는 collaboration, same-host Claude는 `Task`/`Agent`, external route만 managed provider entrypoint를 사용한다. Native child prompt에는 `DELEGATION BOUNDARY`를 포함하고 아래 형식을 따른다.
   ```text
   역할: objective clarification adversary.
   Read로 clarification-context.md를 로드하고, 사용자에게 물어야 하는 critical/major 모호성만 JSON findings로 반환하시오.
   각 finding에는 severity, requires_user_answer, question, recommended_answer, recommendation_rationale를 포함하시오.
   ```
3. `severity=critical|major` 또는 `requires_user_answer=true` 항목은 PM이 자동 보완하지 않는다. 반드시 아래 Critical/Major Clarification Batch Rule로 처리한다.
4. `minor` 항목은 PM이 objective 초안의 참고 리스크로 반영할 수 있지만, 사용자 의도·범위·우선순위에 영향을 주면 major로 승격한다.

##### Critical/Major Clarification Batch Rule (MANDATORY)

적용 범위: Step 1A.2.5, Step 1A.9 Strategic Review, Step 1A.9.7 적대적 검토, Step 1A.10.5 D3에서 발견된 사용자 의존 모호성.

1. `severity=critical|major`이거나 finding의 `requires_user_answer=true`인 항목은 PM이 추론 또는 자동 보완으로 닫을 수 없다.
2. PM은 각 항목에 대해 `질문`, `PM 추천 답변`, `추천 근거`, `틀렸을 때 영향`을 작성하고 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/clarification-questions.md`에 append한다.
3. 질문 횟수를 줄이기 위해 최대 5개 항목을 하나의 배치로 묶는다. 사용자에게는 아래 표를 먼저 보여준다.
   ```markdown
   | ID | 확인할 모호성 | PM 추천 답변 | 추천 근거 | 틀렸을 때 영향 |
   |----|---------------|--------------|-----------|----------------|
   | CQ-1 | ... | ... | ... | ... |
   ```
4. `AUTO_MODE=false`: 배치당 확인 질문 1회만 실행한다. AskUserQuestion을 사용할 수 있으면 선택지는 최대 4개로 고정한다.
   - `A. 추천안 모두 수락`: 표의 모든 PM 추천 답변을 사용자 승인 결정으로 반영
   - `B. 일부만 수정`: 사용자가 `CQ-1=...; CQ-3=...`처럼 수정할 수 있게 안내하고, 수정된 항목만 재반영
   - `C. 더 검토`: 현재 배치 전체를 `mst:discussion` 또는 `mst:ideation`으로 보강한 뒤 같은 배치를 재질문
   - `D. 범위 제외/보류`: 해당 항목을 Won't/No-go Scope 또는 리스크 레지스터에 기록
5. `AUTO_MODE=true`: critical/major 사용자 의존 모호성이 남아 있으면 자율로 진행하지 않는다. `auto-decisions.md`와 `clarification-questions.md`에 blocker를 기록하고 objective 확정을 중단한다.
6. 사용자가 `A. 추천안 모두 수락`을 선택한 경우에도 기록에는 `(PM 추천 — 사용자 일괄 승인)`으로 남긴다. PM 단독 결정으로 기록하지 않는다.

##### 1A.3 구조화 수집 단계 (MANDATORY, 순서 고정)

아래 4단계를 순서대로 수행하고, 각 결과를 objective.md에 즉시 반영한다.

1. **제약사항 수집**
   - Out-of-scope / 기술적 제약 / 비즈니스 제약을 확인한다.
   - 결과 반영: `## 제약사항 (Out-of-scope / 기술 / 비즈니스)`

2. **MoSCoW 우선순위 수집**
   - Must / Should / Could / Won't (this time)를 수집한다.
   - 결과 반영: `## 우선순위 (MoSCoW)`
   - DoD 항목의 `priority` 마커 값에 우선순위를 연결한다.

3. **리스크 식별 + 의존성 확인**
   - 리스크(가능성/영향/완화 방안)와 선행/연관 의존성을 함께 확인한다.
   - 의존성은 리스크 근거와 설계 결정 근거에 연결해 기록한다.
   - 결과 반영: `## 리스크 레지스터`, `## 설계 결정 (Architecture Decisions)`

4. **Reference Lookup Protocol 실행**
   - 최신성 검증이 필요한 외부 의존 정보는 공통 프로토콜로 수집/검증한다.
   - 결과 반영: `## 참조 레퍼런스`

##### 1A.3.4 Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 판단이 포함되면 아래를 적용한다.

0. **자동 트리거 게이트**
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search` 확인
   - 설정이 없으면 기본값 사용:
     - `cache_ttl_days=2`
     - `cutoff_threshold_months=0.5`
     - `max_searches_per_step=5`
     - `llm_auto_trigger=true`
     - `auto_fact_check=true`

1. **키워드 감지**
   - 현재 문맥에서 `library/framework/api/sdk/protocol/version/dependency` 및 한국어 동의어 감지
   - `llm_auto_trigger == true`면 키워드 매칭 외에도 최신성 리스크가 있으면 검색 가능

2. **3단계 신선도 체크**
   - (a) 캐시 조회: `mst.py reference search --keyword "{keyword}" --json`
   - (b) TTL 판정: `cache_ttl_days` 기준 `fresh/stale`
   - (c) cutoff 판정: `cutoff_threshold_months` 초과 시 `expired`

3. **검색 실행**
   - 캐시 없음 또는 `stale/expired`만 검색
   - `auto_search == true`일 때만 `WebSearch` 실행
   - `auto_fact_check == true`면 핵심 claim 1회 교차 검증

4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**
   - WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 `mst.py reference add`를 호출해야 한다.
   - 표/텍스트 결론 요약만으로는 저장이 완료되지 않는다 — `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - WebSearch N건 실행 → `mst.py reference add` 최소 N회 호출 (1:1 대응 원칙).
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙 요약: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 상세 예시/품질 체크리스트/lazy-Read 트리거는 `skills/plan/SKILL.md`의 Reference Lookup Protocol 4번 항목을 동일 기준으로 따른다.

5. **컨텍스트 주입 블록 생성**
   - 이후 판단 프롬프트에 아래 블록 주입:
   ```text
   [REFERENCE_CONTEXT]
   current_date: {YYYY-MM-DD}
   model_cutoff: {cutoff_date_or_unknown}
   references:
   - REF-001 (fresh|stale|expired) {topic} | {url}
   [/REFERENCE_CONTEXT]
   ```
   - 참조가 없으면 `references: none`

##### 1A.4 재귀 정제 루프 (MANDATORY)

아래 루프를 수행한다.

```text
WHILE (사용자 종료 선언 전):
  round += 1
  현재 상태 요약 -> PM 개선안 제시 -> 사용자 피드백 수집(자연어 대화) -> 반영 -> 수렴 체크
END WHILE
```

라운드 운영 규칙:
1. 라운드 시작 시 대시보드 URL을 항상 안내한다.
   - 대시보드 URL: `http://{host}:{port}/agile/{AGI_ID}/objective`
2. 라운드 시작 시 대시보드 변경 감지를 수행한다.
   - objective.md 수정/코멘트를 감지하면 아래를 출력한다.
   - `[대시보드 변경 감지] {N}건의 수정 / {M}건의 코멘트가 있었습니다`
   - 변경 미감지 또는 대시보드 미접속 시 텍스트 폴백으로 계속 진행한다.
3. 피드백 수집은 AskUserQuestion이 아닌 자연어 대화로 처리한다.
4. 각 라운드 종료 시 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/round-history.md`에 라운드 요약을 append한다.
5. **대화 내용 축적 (CRITICAL)**: 각 라운드에서 사용자가 설명한 설계 내용·결정 근거·프로세스·구조·기술 선택을 `detail_content_buffer`(메모리)에 도메인별로 축적한다.
   - 단순 "네/아니오" 응답은 제외하되, 사용자가 **왜 그렇게 결정했는지**, **어떤 구조로 만들고 싶은지**, **어떤 프로세스를 따르는지** 등 설계 의도가 담긴 발화는 반드시 축적한다.
   - 축적 시 원문을 보존하고, PM이 구체화·보강할 수 있다 (요약/축약 금지).
   - 이 버퍼는 Step 1A.9.5(도메인 클러스터링)와 1A.10(저장) 단계에서 details/*.md의 핵심 소재로 사용된다.
6. `AUTO_MODE=true`: 자연어 사용자 대기, AskUserQuestion, "종료하시겠습니까?"류 확인 질문을 생성하지 않는다.
   - 최대 `agile.objective_refinement.max_auto_rounds`(기본 2)까지만 PM 자율 정제를 수행한다.
   - 수렴하면 Step 1A.6으로 진행한다.
   - critical/major 사용자 의존 모호성이 남으면 `clarification-questions.md`와 `auto-decisions.md`에 blocker를 기록하고 structured non-success로 종료한다.
   - minor/PM 판단 가능 항목만 남으면 `auto-decisions.md`에 근거를 기록하고 진행한다.
7. `AUTO_MODE=false`: 사용자 대화 루프는 soft limit과 수렴 체크포인트를 반드시 적용하며, soft limit 도달 시에도 질문은 1회만 수행한다.

##### 1A.5 수렴 판정 + soft limit 체크포인트 (MANDATORY)

각 라운드 종료 시 직전 라운드 대비 delta를 측정한다.

1. 4축 delta 구성요소
   - `N_t`: DoD 추가·삭제 건수 정규화 값
   - `E_t`: DoD 본문 수정 건수 정규화 값
   - `S_t`: 구조 변경 이벤트(순서 재배치, split/merge, 의존성 변경) 정규화 값
   - `P_t`: 상태 변경/미해결 코멘트 영향도 정규화 값
2. 라운드 delta 계산
   - `D_t = (N_t + E_t + S_t + P_t) / 4`
3. 추세 계산(최근 3라운드)
   - `EMA3_t = alpha * D_t + (1 - alpha) * EMA3_(t-1)` (`alpha=0.5`, 초기값=`D_1`)
4. 종료 권장 2중 게이트 + 보조 조건 + 커버리지 AND 조건
   - 절대 조건: `D_t <= convergence_threshold_abs` (기본 0.12)
   - 추세 조건: `EMA3_t <= convergence_threshold_trend` (기본 0.18)
   - 보조 조건: 미해결 코멘트 `<= 1`
   - 커버리지 조건(MANDATORY, AND): `coverage_ratio >= config.agile.coverage_threshold` (기본 0.85) — `--doc` 모드 1A.10 직전 details/*.md 집합에 대해 `python3 {PLUGIN_ROOT}/scripts/mst.py agile coverage-check {원본문서경로} --details-dir {details_dir}`를 실행해 `coverage` 값을 사용한다. 이 조건이 미충족이면 다른 3개 조건이 통과해도 수렴 종료를 권장하지 않는다.
5. 4개 조건을 모두 만족하면 종료 권장 문구를 출력한다.
   - `[수렴 감지] 변경량이 임계값 이하입니다. 현재 상태로 확정할까요?`
6. 루프 종료는 사용자의 명시적 종료 선언으로만 확정한다.

soft limit:
- 기본 `soft_limit_rounds=8` (설정값이 있으면 우선 적용)
- `round == soft_limit_rounds`에 도달하면 합의사항/미해결 쟁점을 요약하고 종료/연장 선택을 받는다.
- `AUTO_MODE=true`에서는 soft limit 질문을 하지 않는다. `max_auto_rounds` 도달 시 수렴/blocked/auto-decision 중 하나의 structured branch로만 종료한다.

##### 1A.6 프로젝트 DoD 품질 게이트 (MANDATORY)

각 라운드 반영 직후(또는 최종 저장 직전) 9개 통합 품질 기준으로 DoD를 판정한다.

| # | 기준명 | 출처 | PM 판정 질문 |
|---|--------|------|-------------|
| 1 | 정확성 (Correctness) | IEEE 830 | 이 DoD가 프로젝트 목표(JTBD)와 일치하는가? |
| 2 | 비모호성 (Unambiguity) | IEEE+IREB | 해석 분기 없이 단 하나의 의미만 가지는가? |
| 3 | 완전성 (Completeness) | IEEE+IREB | 정상/에러/경계 조건이 모두 정의되었는가? |
| 4 | 일관성 (Consistency) | IEEE 830 | 다른 DoD 항목과 모순되지 않는가? |
| 5 | 검증가능성 (Verifiability) | IEEE+IREB | 관찰/측정으로 완료 여부를 판정할 수 있는가? |
| 6 | 필요성 (Necessity) | IREB | 이 DoD 없이는 프로젝트 목표 달성이 불가능한가? |
| 7 | 이해가능성 (Understandability) | IREB | 비기술 이해관계자도 의미를 이해할 수 있는가? |
| 8 | 중요도 순위 (Ranked) | IEEE 830 | 우선순위가 부여되었는가? |
| 9 | ODI 구조 (Outcome Format) | ODI | 방향+측정+대상+맥락+목표값이 포함되었는가? |

운영 규칙:
1. 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/quality-gate-log.md`에 DoD별 1행 요약으로 기록한다.
2. 컬럼: `DoD ID`, `pass/total`, `결과`, `실패 기준 수`, `타임스탬프`
3. `결과=fail`인 DoD만 `<details>`로 상세(`기준명`, `미충족 사유`)를 추가한다.
4. 모든 DoD가 9개 기준 전체 pass일 때만 다음 단계로 진행한다.

##### 1A.7 5중 가드레일 검증 (MANDATORY)

1. **How-free (DoD 전용)**: DoD 항목에 구현 방법(API 엔드포인트, 함수명, 파일명, 기술 스택)이 포함되면 거부하고 관찰 가능한 결과 문장으로 재질문한다. 단, `## 설계 결정 (Architecture Decisions)` 및 `objective/details/*.md`에서는 기술 상세를 허용한다.
2. **범위 가이드**: DoD 수량은 추천 범위(`dod_count_min`/`dod_count_max`, 기본 5~15)를 안내하되 차단하지 않는다
3. **So-that 검증**: 각 DoD가 `X 한다, so that 사용자는 Y 할 수 있다`로 연결되는지 확인
4. **Sprint 동결**: 진행 중 Sprint의 체크리스트 변경 금지, 변경은 스티어링 체크포인트에서만 반영
5. **Observable-by-Sprint 사고 프롬프트** (비차단): 각 DoD에 대해 PM은 내부적으로 다음 질문을 점검한다 - "이 DoD가 사용자 관찰 가능하게 만들어지는 Sprint는 어떤 형태인가?" (사용자 진입점 1개 이상이 추가/변경되는 Sprint, 또는 기존 진입점의 동작이 가시적으로 변하는 Sprint). 답이 모호하거나 "단위 헬퍼만"으로 끝나면 DoD를 더 작게 분해하거나 통합 진입점과 연결되도록 보강할 것을 권장한다. 답이 모호해도 저장은 허용하되, `quality-gate-log.md`에 `observable_by_sprint: unclear` 메타데이터 기록을 권장한다. 이 항목은 강제 게이트가 아닌 사고 보조 프롬프트다.

##### 1A.8 저장 전 준비도 게이트 (MANDATORY)

최종 저장(1A.10) 전에 아래를 확인한다.

1. 모든 DoD가 관찰 가능한 결과 문장으로 정의됨
2. DoD 우선순위가 MoSCoW와 정합함 (`priority` 마커 반영)
3. DoD 품질 게이트 9개 기준 전체 pass
4. JTBD 5개 필드 누락 없음
5. 정량 또는 관찰 가능한 성공 지표 최소 1개 존재
6. 제약/MoSCoW/NFR/리스크/설계 결정/참조 섹션이 비어 있지 않음
7. **대화 내용 완전성 검증 (CRITICAL)**: `detail_content_buffer`에 축적된 내용과 대화 이력을 대조하여, 사용자가 논의 중 제시한 설계·결정·프로세스·구조 중 아직 details/ 소재에 반영되지 않은 항목이 없는지 확인한다. 누락 항목이 있으면 저장 전 보완한다.

##### 1A.9 전략 검토 + Confidence Matrix (MANDATORY, 프로세스 전용)

> 이 단계는 저장 전 품질 강화용 **프로세스**이며 objective.md에 섹션으로 남기지 않는다.

1. **Strategic Review Pass**
   - 의도 검증: 요청한 것과 실제 필요한 것의 간극 분석
   - 외부 리서치: 필요한 항목만 `WebSearch`로 최신 패턴/대안/함정 점검
   - 범위 위험 감지: scope creep 및 후속 리스크 예측
2. **이슈 분류**
   - `CRITICAL` / `MAJOR` / `MINOR` / `NO_ISSUES`
   - `CRITICAL` 또는 `MAJOR` 존재 시, 저장 전에 Critical/Major Clarification Batch Rule로 보완 질의 후 재검토
3. **Confidence Matrix 자가평가**
   - 축: `Clarity`, `Feasibility`, `Risk Coverage`, `Evidence Freshness`, `Testability`
   - 점수: 각 0.0~1.0, 종합 점수는 가중 평균
   - 기본 임계치: 0.70
4. **저장 진행 조건**
   - 전략 검토에서 `CRITICAL` 해소 완료
   - 종합 confidence가 임계치 이상이거나, 임계치 미만 사유에 대해 사용자 승인 확보

##### 1A.9.2 디자인 단계 (MANDATORY)

전략 검토를 통과한 뒤, objective 저장 전에 디자인 단계를 수행한다.

###### 1A.9.2.1 UI 프로젝트 감지 (MANDATORY)

1. 먼저 아래 키워드 매칭을 수행한다.
   - `웹사이트`, `앱`, `화면`, `UI`, `페이지`, `대시보드`, `컴포넌트`, `레이아웃`, `프론트엔드`, `디자인`, `목업`, `시안`, `랜딩`, `포털`
2. 키워드 매칭이 없으면 LLM 의미 판단을 보조 실행한다.
   - 예: 사용자 대면 화면이 필수인 목표인지 판단
3. 두 검사 모두 미감지면 아래 로그 1줄만 출력하고 Step 1A.9.5로 직행한다.
   - `[디자인 단계 skip] UI 프로젝트 미감지`
4. `AUTO_MODE` 분기:
   - `AUTO_MODE=false`: 감지 시 사용자에게 디자인 단계 진행 여부를 1회 확인한다.
   - `AUTO_MODE=true`: 감지 시 사용자 확인 없이 자동 진입한다.

###### 1A.9.2.2 텍스트 와이어프레임 생성 (MANDATORY)

확정된 DoD/설계 결정을 기준으로 아래 3종을 모두 포함한 와이어프레임을 작성한다.

1. 전체 화면 목록: `화면명 + 1줄 설명`
2. 화면 간 네비게이션 흐름: `→` 기반 흐름
3. 화면별 ASCII 박스 레이아웃

저장 경로:
- `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/details/design-wireframe.md`

`AUTO_MODE` 분기:
- `AUTO_MODE=false`: 생성한 와이어프레임을 제시하고 보완 피드백을 반영한다.
- `AUTO_MODE=true`: 와이어프레임을 자동 생성/저장하고 핵심 결정 근거를 `auto-decisions.md`에 기록한다.

###### 1A.9.2.3 와이어프레임↔DoD/usecase 상호 정제 (MANDATORY)

1. 와이어프레임을 기준으로 DoD 보완/수정을 수행한다.
2. 화면별 usecase를 정리하고 `design-wireframe.md`에 함께 저장한다.
3. 대규모 기능 변경이 필요하면 Step 1A.6(품질 게이트)부터 1A.8까지 재실행한 뒤 1A.9.2로 재진입한다.

`AUTO_MODE` 분기:
- `AUTO_MODE=false`: DoD/usecase 변경안을 사용자와 합의 후 반영한다.
- `AUTO_MODE=true`: PM이 자율 반영하고 변경 사유/근거를 `auto-decisions.md`에 기록한다.

###### 1A.9.2.4 Stitch 시안 생성 (MANDATORY)

1. Stitch 호출은 반드시 아래 방식으로 수행한다.
   - `Skill(skill: "mst:stitch")`
2. 직접 `mcp__stitch__*` 도구 호출은 금지한다.
3. 실패 정의: `throw` / `timeout` / `빈 결과`
4. 실패 시 아래 로그를 출력하고 텍스트 와이어프레임으로 계속 진행한다.
   - `[Stitch 실패] {오류 요약} — 텍스트 와이어프레임으로 진행`

`AUTO_MODE` 분기:
- `AUTO_MODE=false`: 생성된 시안을 사용자에게 제시하고 선택/피드백을 반영한다.
- `AUTO_MODE=true`: 생성된 시안을 PM이 자율 선택하고 근거를 `auto-decisions.md`에 기록한다.

###### 1A.9.2.5 시안 기반 최종 조정 + 회귀 상한 (MANDATORY)

1. 시안을 기준으로 기능 설계/DoD를 최종 점검한다.
2. 기능 설계로 회귀가 필요하면 Step 1A.6부터 재실행 후 1A.9.2로 재진입한다.
3. 회귀 카운팅 단위는 다음으로 고정한다.
   - `디자인 단계에서 기능 설계로 회귀하는 방향 전환 1건 = 1회`

`AUTO_MODE` 분기:
- `AUTO_MODE=false`: 회귀 횟수 제한 없이 사용자 확정 시까지 반복 가능
- `AUTO_MODE=true`: `agile.design_regression_max`(기본 3) 상한을 적용한다.
  - 상한 도달 시 로그를 출력하고 `auto-decisions.md`에 기록한 뒤 Step 1A.9.5로 진행한다.

##### 1A.9.5 PM 도메인 클러스터링 (MANDATORY)

objective 저장 전에 수집된 모든 상세 내용을 도메인 단위로 정리한다.

1. 수집된 모든 상세 내용을 의미 기반으로 그룹화한다.
   - Q&A 모드(1A): 문답에서 수집된 설계 결정, 기술 선택, 프로세스, 구조 등 전체
   - `--doc` 모드(1B): 원본 문서의 섹션별 내용 전체 + Q&A 보완 내용. 원본 문서의 H1/H2 구조를 클러스터링 참고 입력으로 우선 활용한다.
2. 각 그룹에 대해 `details/{domain-slug}.md` 파일명을 제안하고, 도메인명 + 1줄 요약을 작성한다.
3. 사용자에게 클러스터링 결과(도메인/파일명/요약)를 확인받아 확정한다.
4. `AUTO_MODE`에서는 사용자 확인 대신 PM이 자율 확정하고 근거를 함께 기록한다.
5. 확정된 클러스터 맵은 Step 1A.10 저장 입력으로 사용한다.

##### 1A.9.6 완성된 모습 미리보기 + 정제 (MANDATORY, PM skip 가능)

Step 1A.9.5의 도메인 클러스터링 결과와 누적 `detail_content_buffer`를 입력으로, Step 1A.9.7 적대적 검토 전에 사용자가 "완성된 모습"을 검증할 수 있도록 자연어 미리보기와 정제 라운드를 수행한다. PM이 미리보기가 불필요하거나 오히려 흐름을 방해한다고 판단하면 사용자 질문 없이 skip할 수 있다.

###### PM skip

1. PM이 skip을 선택하면 `AskUserQuestion`을 사용하지 않는다.
2. 아래 로그 1줄만 출력하고 Step 1A.9.7로 진행한다.
   - `[완성 모습 미리보기 skip] {사유}`

###### 권장 3종 세션

진행 시 아래 3종을 자연어로 제시한다. PM은 프로젝트 성격상 필요하다고 판단하면 추가 시각화나 표를 자유롭게 더할 수 있다.

1. 사용자 동선: happy path와 edge 시나리오에서 사용자가 어떤 순서로 결과를 확인하는지 보여준다.
2. 시스템 지도 Before·After: 현재 구조와 완료 후 구조를 나란히 설명하고, 도메인별 책임과 연결 관계를 드러낸다.
3. 누락 확인 체크리스트: DoD/JTBD/도메인/리스크/운영 흐름에서 빠진 항목이 없는지 확인한다.

###### 정제 루프

1. 미리보기 라운드마다 사용자 피드백 또는 PM 판단으로 누락 보강 항목을 식별한다.
2. 각 라운드 종료 시 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/round-history.md`에 라운드 요약을 append한다.
3. 누락 보강 항목은 `detail_content_buffer`에 축적하고, Step 1A.10에서 `details/*.md`에 흡수한다.
4. `completion-preview.md` 같은 별도 산출물 파일은 생성하지 않는다.

**`AUTO_MODE` 분기:**
- `AUTO_MODE=false`: 사용자 확정 시까지 라운드 횟수 제한 없이 반복 가능
- `AUTO_MODE=true`: 최대 2회 반복한다. 설정값 `agile.completion_preview.max_rounds_auto`가 있으면 해당 값을 상한으로 사용한다.
  - 상한 도달 시 현재까지의 누락 보강 항목을 `detail_content_buffer`에 반영하고 Step 1A.9.7로 진행한다.

###### 회귀 처리

1. 정제 중 DoD 변경이 필요하면 Step 1A.6으로 회귀한다.
2. JTBD 변경이 필요하면 Step 1A.8로 회귀해 저장 전 준비도와 JTBD 정합성을 재확인한다.
3. 도메인 클러스터 변경이 필요하면 Step 1A.9.5로 회귀한다.
4. 회귀 카운팅 단위는 다음으로 고정한다.
   - `완성된 모습 미리보기에서 DoD/JTBD/도메인 정제로 회귀하는 방향 전환 1건 = 1회`
5. `AUTO_MODE=true`에서는 `agile.completion_preview.regression_max`(기본 2) 상한을 적용한다.
   - 상한 도달 시 로그를 출력하고 `auto-decisions.md`에 기록한 뒤 Step 1A.9.7로 진행한다.
6. `AUTO_MODE=false`에서는 사용자 확정 시까지 회귀 횟수 제한 없이 반복 가능하다.

### Step 1A.9.7 적대적 검토 게이트

Step 1A.9.5 도메인 클러스터링 (및 Step 1A.9.6 완성된 모습 미리보기/정제 — 통과 또는 PM skip) 직후, objective 저장 직전에 완전성 보강 목적의 적대적 검토를 수행한다. 이 게이트는 D3의 명료도 검증이 아니라 엣지케이스, 누락 흐름, 통합 경계, persona/NFR gap을 찾아 Step 1A.4 재귀 정제 루프에 "적대적 검토 라운드" 1회로 주입하는 절차다.

1. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.adversarial_review)`로 설정을 읽는다.
   - `agile.adversarial_review.enabled != true`이면 graceful skip 후 Step 1A.10으로 진행한다.
   - enabled perspective만 실행한다. 기본 enabled는 `edge`, `flow`, `integration`이며 `persona`, `nfr`은 설정이 true인 경우에만 실행한다.
   - `max_rounds` 기본값은 3, `current_round` 초기값은 1이다.
2. 현재 draft를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/draft/`에 materialize한다. 이 단계는 accepted objective promotion이 아니다.
3. 각 perspective마다 아래 CLI로 context 경로와 output schema 경로만 조회한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py agile review --agi {AGI_ID} --perspective {name} --draft-dir {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/draft --json
   ```
4. CLI 결과의 `context_source`가 `draft`인지 확인한다. `accepted`, `placeholder`, 빈 context, 또는 이전 objective 경로가 반환되면 review를 중단하고 draft materialization을 수정한다.
5. CLI 결과의 `context_files` 경로와 `output_schema` 경로만 독립 에이전트에 전달한다. Perspective마다 shared route를 적용하고 native candidate는 host agent, external은 managed provider entrypoint를 사용하며 반드시 독립 컨텍스트로 실행한다. Native child에는 `DELEGATION BOUNDARY`를 포함하고 plan/objective 원문, detail 본문, DoD/JTBD 원문은 절대 포함하지 않는다.
   ```text
   역할: {perspective} 관점의 적대적 검토자.
   Read로 context_files 경로를 로드하고 output_schema에 맞게 findings JSON을 반환하시오.
   ```
6. findings는 round별 append 방식으로 `{PROJECT_ROOT}/.gran-maestro/agile/AGI-NNN/objective/adversarial-review-findings.md`에 기록한다. 각 append 블록에는 `round`, `perspective`, `severity`, `finding`, `suggested_dod`, `requires_user_answer`, `question`, `recommended_answer`, 반영 여부를 포함한다.
7. 수렴 조건은 `findings 배열이 비어있음 OR current_round >= max_rounds`이다. 수렴 전에는 먼저 critical/major 사용자 의존 finding을 Critical/Major Clarification Batch Rule로 처리한다. 사용자 의존성이 없는 나머지 finding만 Step 1A.4 재귀 정제 루프의 추가 입력으로 반영하고 `current_round += 1` 후 재검토한다.
8. `AUTO_MODE=true`:
   - `parallel_in_auto_mode=true`이면 enabled perspective를 병렬 실행하고, false이면 순차 실행한다.
   - `severity=critical|major` 또는 `requires_user_answer=true` finding은 Critical/Major Clarification Batch Rule로 보낸다. PM이 자동 반영하지 않는다.
   - 그 외 finding만 자동 반영 가능하며 `{PROJECT_ROOT}/.gran-maestro/agile/AGI-NNN/auto-decisions.md`에 근거와 반영 내용을 기록한다.
9. `AUTO_MODE=false`:
   - 기본 실행은 `edge` + `flow` 2종을 순차 실행한다. 설정에서 다른 perspective가 enabled여도 PM이 필요하다고 판단한 경우에만 추가 실행한다.
   - `severity=critical|major` 또는 `requires_user_answer=true` finding은 Critical/Major Clarification Batch Rule로 묶어 사용자 confirm 후 objective/detail 보강에 반영한다. minor는 요약만 제시하고 사용자가 반영을 선택한 경우에만 재정제한다.

##### 1A.10 objective.md + details/*.md 저장

###### evidence 필드별 강제 시점 표

| 필드 | plan-time | sprint-runtime | sprint-end |
|------|-----------|----------------|------------|
| `artifact_paths` | 필수 (자동 채움) | - | 파일 실존 검증 |
| `entrypoint_path` | 필수 (`entrypoint: none` + `reason` 예외 허용) | - | grep 실매칭 검증 |
| `integration_smoke_id` | 예약 필수 (ID + user flow + 성공의도) | 선택 보강 | tests/ 실존 경로 강제 |
| `verify_cmd` | 골격 필수 (비대화식 실행 정의) | 실제 명령 확정 | 실행 + 신호 매칭, `true`/`exit 0`/`echo` 단독 거부 |
| `expected_signal` | TBD 허용 | TBD 해소 | 정규식/문자열 매칭 |

###### downstream context transfer contract (MANDATORY)

objective 저장 직후, downstream agile/request/approve handoff는 아래 path-first 계약을 기본으로 사용한다. objective anchor나 source plan이 없으면 조용히 생략하지 않고 명시적으로 보고한다.

```text
[CONTEXT_FILES]
- objective: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
- objective_ids: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json or NO_OBJECTIVE_IDS
- objective_details: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/details/{domain}.md or NO_OBJECTIVE_DETAILS
- plan: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.md or NO_SOURCE_PLAN
- plan_json: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.json or NO_PLAN_JSON
- plan_ids: {PROJECT_ROOT}/.gran-maestro/plans/{PLAN_ID}/plan.ids.json or NO_PLAN_IDS
- spec: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md or NO_ACTIVE_SPEC
- spec_context_manifest: {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{TASK_ID}/spec.md#§0-Context-Manifest or NO_CONTEXT_MANIFEST
- previous_feedback: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{PREV_SPRINT}/retrospective.md or NO_PREVIOUS_FEEDBACK
[/CONTEXT_FILES]

[WORK_CONTRACT]
- read_requirements: 구현 전 위 context file과 spec §0 Context Manifest 파일을 직접 Read/inspection한다.
- output_contract: agile/agile-plan/prompt-template 변경 파일, dispatch result contract, completion report를 보고한다.
- verification_contract: verify_cmd, expected_signal, integration_smoke_id를 보고한다.
- failure_contract: timeout, empty result, blocked, missing_context 상태를 구조화해 남긴다.
[/WORK_CONTRACT]
```

추가 규칙:
- `objective.ids.json`이 아직 생성되지 않았거나 읽기 실패면 `NO_OBJECTIVE_IDS` 또는 `missing_context`로 기록한다. objective anchor coverage evidence를 조용히 skip하지 않는다.
- source plan/spec context manifest가 없으면 `NO_SOURCE_PLAN`, `NO_PLAN_JSON`, `NO_PLAN_IDS`, `NO_CONTEXT_MANIFEST` 같은 explicit skip reason을 남긴다.
- downstream completion report에는 `Read/inspection evidence`, `changed files`, `simplifications made`, `remaining risks`, `verify_cmd`, `expected_signal`, `integration_smoke_id`를 포함한다.

`templates/objective.md` 포맷으로 아래 경로에 저장:

```
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/details/{domain}.md
```

저장 규칙:
- objective.md에는 아래 10개 핵심 섹션 순서를 유지한다.
  1. 진행 상태 요약
  2. JTBD 레이어
  3. 프로젝트 완료 기준 (DoD)
  4. 설계 결정 (Architecture Decisions)
  5. 제약사항 (Out-of-scope / 기술 / 비즈니스)
  6. 우선순위 (MoSCoW)
  7. 프로젝트 NFR
  8. 리스크 레지스터
  9. 참조 레퍼런스
  10. 변경 이력
- 디자인 단계(1A.9.2)를 거친 경우에만 `## 디자인 컨텍스트` 섹션을 추가한다. 디자인 단계를 거치지 않은 경우(비-UI 프로젝트 포함) 해당 섹션은 생성하지 않고 skip한다.
  - 섹션 위치: 위 10개 핵심 섹션 이후, `## 상세 문서 (Details)` 인덱스 이전
  - 기본 구조(디자인 단계 수행 + Stitch 시안 생성됨):
  ```markdown
  ## 디자인 컨텍스트

  > 이 프로젝트의 디자인 baseline입니다. sprint 진행 중 수정될 수 있습니다.

  - DES-ID: DES-NNN
  - Stitch 프로젝트 URL: {URL}
  - 생성일: {YYYY-MM-DD}
  - 상태: baseline | updated

  ### 화면 목록

  | 화면명 | Stitch URL | HTML 경로 | 설명 |
  |--------|-----------|-----------|------|
  | {화면명} | {url} | designs/DES-NNN/{screen-file}.html | {설명} |

  ### 화면 흐름

  {텍스트 와이어프레임에서 정의된 화면 간 네비게이션 흐름}

  ### 텍스트 와이어프레임

  {Step 1A.9.2.2에서 생성된 와이어프레임 원본 — 변경 추적용}
  ```
  - Stitch 미생성 fallback(`wireframe-only`) 구조:
  ```markdown
  ## 디자인 컨텍스트

  > 텍스트 와이어프레임만 생성됨 (Stitch 시안 미생성)

  - DES-ID: 없음
  - 상태: wireframe-only

  ### 텍스트 와이어프레임

  {와이어프레임 원본}
  ```
- `## 상세 문서 (Details)`에는 domain별 detail 파일 링크 + 도메인명 + 1줄 요약을 기록한다.
- detail 파일(`objective/details/*.md`)에는 해당 도메인의 **모든 상세 내용**을 원본 수준으로 보존한다(요약/축약 금지).
  - Q&A 모드(1A): 사용자와의 대화에서 논의된 **모든** 설계 내용을 원본 그대로 `## 상세 명세` 하위에 1:1 보존한다 — 설계 결정과 그 근거, 기술 선택과 비교 대안, 디렉토리 구조, 프로세스 흐름, Gate/체크리스트, 스키마/템플릿, 예시, 합의 사항 등. PM은 사용자 발화를 누락 없이 기록하며, 대화에서 논의되었으나 details/에 없는 내용이 있으면 안 된다.
  - `--doc` 모드(1B): 원본 문서의 해당 도메인 내용 전체 + Q&A로 추가 보완된 내용. 원본 문서에 기술된 내용이 details/에서 누락되어서는 안 된다.
  - 각 `details/{domain}.md` 파일의 **첫 줄**에는 반드시 source mapping 메타데이터를 작성한다.
    - `--doc` 모드 또는 원본문서가 있는 경우: `<!-- source-mapping: original=<원본경로> sections=[<H1/H2 헤더 목록>] -->`
    - Q&A 모드처럼 원본문서가 없는 경우: `<!-- source-mapping: source=conversation evidence=clarification-context.md sections=[<JTBD/결정/질문 묶음>] -->`
    - 대화 근거 파일이 없거나 만들 수 없는 예외 경로: `<!-- source-mapping: source=conversation skip_reason=<명시적 사유> sections=[<근거 묶음>] -->`
    - Q&A 모드에서 `original=objective.md`, `original=SKILL.md` 같은 가짜 원본문서 경로로 대체하지 않는다.
  - details 저장 직후 `.gran-maestro/agile/{AGI_ID}/objective/objective.ids.json` anchor manifest를 생성/갱신한다. 각 objective anchor는 `id`, `source_file`, `text`, `kind`, `grade`, `domain_slug`, `dod_refs`를 포함해야 하며, AD/설계 결정/DoD/NFR/리스크/체크리스트 성격의 MUST/SHOULD 요구를 deterministic하게 추적 가능해야 한다.
  - detail 파일 저장 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py agile detail validate-mapping {details_file_path}` 명령으로 source-mapping 메타데이터를 검증한다.
  - 모든 details 파일 저장 직후, `python3 {PLUGIN_ROOT}/scripts/mst.py agile coverage-check {원본문서경로} --details-dir {details_dir}` 명령으로 원본 ↔ details 집합 매칭률과 objective anchor coverage evidence를 검증한다. 매칭률이 임계 미만이면 저장을 **실패**로 처리하고, 누락된 원본 슬러그 목록을 사용자에게 보고한 뒤 details 보강 후 재실행한다. `objective.ids.json`이 존재하면 출력의 `anchor_total`, `anchor_mapped`, `anchor_missing_ids`도 확인하고 downstream trace 누락을 다음 agile/plan 단계의 known evidence로 보존한다.
- **detail 파일 내부 구조 규칙 (MANDATORY)**: 각 `details/{domain}.md` 파일은 아래 구조를 따른다.
  ```markdown
  # {도메인명}

  > 이 문서는 objective.md의 상세 참조 문서입니다.
  > 관련 DoD: DOD-NNN, DOD-MMM

  ## 개요
  {이 도메인이 다루는 영역의 1~2문장 요약}

  ## 설계 결정
  ### AD-NNN: {결정 제목}
  - **결정**: {무엇을 결정했는가}
  - **근거**: {왜 이렇게 결정했는가 — Q&A에서 논의된 이유}
  - **대안 검토**: {비교한 대안과 기각 사유}
  - **영향 범위**: {이 결정이 영향을 주는 영역}

  ## 상세 명세
  {대화에서 정제된 구체적 설계 내용 — tree 구조로 항목별 정리}
  {프로세스 흐름, Gate 체크리스트, 스키마, 템플릿, 디렉토리 구조, 예시 등}
  {원본 제시 내용 + Q&A를 통해 구체화/보강된 내용 모두 포함}

  ## Q&A 보강 사항
  {대화 중 추가로 결정/보완된 항목들 — 결정 내용 + 근거}
  ```
  - `## 상세 명세` 섹션이 핵심이다. 여기에 **대화를 통해 정제된 설계 원본**이 tree 구조(제목/소제목/불릿)로 항목별 정리되어야 한다.
  - 개발자가 이 파일만 읽고 해당 도메인의 구현 방향을 이해할 수 있어야 한다.
  - 사용자가 제시한 원본(텍스트/문서)이 있으면 그대로 복사하는 것이 아니라, **Q&A를 거쳐 정제·보강·구조화된 버전**을 기록한다.
- DoD는 다중행 구조(`Direction/Measure/Object/Context/Target`)를 사용한다.
- 모든 DoD 항목에 아래 마커를 포함한다.
  - `<!-- dod:DOD-NNN status:todo priority:must domain:{slug} -->`
  - `{slug}`는 해당 DoD가 속한 도메인의 상세 문서 파일명 (예: `details/intent-context-propagation.md` → `domain:intent-context-propagation`)
- `priority` 값은 MoSCoW 결과를 반영해 `must|should|could|wont` 중 하나를 사용한다.
- 전략 검토/Confidence Matrix 결과를 objective.md 섹션으로 남기지 않는다.

##### 1A.10.5 details D3 역방향 시뮬레이션 (MANDATORY)

Step 1A.10 저장 직후, 각 detail 파일에 대해 독립적으로 D3 검증을 수행한다.

1. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get d3.objective_detail_threshold)`에서 `d3.objective_detail_threshold`를 조회한다.
2. 값이 없으면 기본값 `0.1`을 사용한다.
3. `objective/details/*.md` 각 파일마다 독립 에이전트로 D3 역방향 시뮬레이션을 실행한다.
4. 판정은 기존 plan D3 Gate(`mst:plan` Step 3.9) 패턴을 따르되, 임계치는 `objective_detail_threshold`를 사용한다.
5. D3 출력에는 `severity`, `requires_user_answer`, `question`, `recommended_answer`, `recommendation_rationale`를 포함한다.
6. `severity=critical|major` 또는 `requires_user_answer=true`인 사용자 의존 모호성은 Critical/Major Clarification Batch Rule로 처리한다. PM이 자동 보완하지 않는다.
7. 그 외 모호도 점수가 임계치를 초과하면(명료도 90% 미만) 보완 요구를 생성하고 수정 후 재검증한다.

저장 후:
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 생성 요약 출력

---

#### Step 1B: --doc 문서 파싱 모드

**목표**: 기존 문서의 내용 전체를 프로젝트 DoD 중심 구조로 정규화하고, 원본 문서의 상세 내용을 details/에 도메인별로 전량 보존하며, 누락 항목을 Q&A로 보완한다.

##### 1B.1 문서 파싱

1. `Read({PROJECT_ROOT}/{--doc 경로})` 실행 (절대경로 변환)
2. 아래를 추출해 `PARSED_CONTEXT`에 저장
   - JTBD: When I / I want to / So I can / 성공 지표 / 완료 정의
   - DoD 후보: 완료 조건/체크리스트/검증 기준
   - 원본 문서 H1/H2 구조: 도메인 클러스터링 참고용 섹션 계층
   - 설계 결정/제약/MoSCoW/NFR/리스크/참조 정보
   - **원본 전문(Full Content)**: 도메인별 details/ 저장을 위해 원본 문서의 섹션별 내용 전체를 보관한다 (요약 아님)
3. DoD는 관찰 가능한 결과 기준으로 정규화하되, **원본 문서의 상세 내용(프로세스, Gate 체크리스트, 스키마, 템플릿, 예시 등)은 details/ 하위 문서에 도메인별로 전량 보존**한다. 원본에 기술된 내용이 objective 산출물 어디에도 없는 상태는 허용하지 않는다.

##### 1B.2 문서 기반 초기 정규화 (라운드 0)

1. `PARSED_CONTEXT` 기반으로 JTBD/DoD/설계/제약 초안을 생성한다.
2. 누락/모호 항목은 자연어 대화로 보완한다(AskUserQuestion 사용 금지).
3. DoD 보완 시 Step 1A.6의 9개 품질 기준을 즉시 적용한다.

##### 1B.3 공통 정제 프로토콜 적용 (MANDATORY)

`--doc` 모드도 아래 단계를 동일 적용한다.

- 모호성 해소 체크리스트: Step 1A.2
- 목적 구체화 적대적 질문 게이트: Step 1A.2.5
- 구조화 수집 단계: Step 1A.3
- Reference Lookup Protocol: Step 1A.3.4
- 재귀 정제 루프/수렴 판정: Step 1A.4~1A.5
- DoD 품질 게이트/5중 가드레일/준비도 게이트: Step 1A.6~1A.8
- 전략 검토 + Confidence Matrix(프로세스 전용): Step 1A.9
- 디자인 단계: Step 1A.9.2
- PM 도메인 클러스터링: Step 1A.9.5
- detail D3 역방향 시뮬레이션: Step 1A.10.5

##### 1B.4 objective.md 저장

- Step 1A.10/1A.10.5와 동일한 경로/포맷/마커/검증 규칙으로 저장
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 정규화 요약 출력

---

### Step 2: 종료 처리 및 복귀 연결

`[MST skill=agile-plan step=2/3 return_to={RETURN_TO_OR_NULL}]`

#### 2.1 state file 기록 (MANDATORY)

objective 저장 후 반드시 상태 스냅샷을 기록한다. State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

```bash
MST_SESSION_ID="{MST_SESSION_ID}" \
MST_CONTEXT_JSON='{"schema_version":1,"mst_session_id":"{MST_SESSION_ID}","root_mst_id":"{AGI_ID}"}' \
python3 {PLUGIN_ROOT}/scripts/mst.py state set \
  --skill agile-plan \
  --step 3 \
  --total 3 \
  [--return-to {RETURN_TO}]
```

#### 2.2 서브스킬 호출(return_to 존재) 처리

- `--return-to`가 있으면 아래 종료 마커와 다음 단계 실행 명령을 출력 후 즉시 종료:
  - `[MST skill=agile-plan step=returned return_to={RETURN_TO}]`
  - ```text
    다음 단계 실행 명령:
      /mst:resume --wakeup-hint stop-recover
    ```
- stop-hook continuation guard가 `return_to`를 감지하여 상위 스킬 re-feed를 강제한다.

#### 2.3 독립 실행(return_to 없음) 처리

- objective 생성 결과를 안내하고 종료한다.
- 사용자가 objective를 수동 검토/수정한 뒤 아래로 실행을 연결하도록 안내하고, 마지막 마무리는 반드시 아래 블록으로 끝낸다:
  ```text
  다음 단계 실행 명령:
    /mst:agile --resume {AGI_ID}
  ```

---

## Anti-Rationalization Checklist

- 합리화 패턴: "대략 N 스프린트면 되니 계획/보고에 넣어도 된다." | 확인 증거: objective.md, plan 입력, 중간/스티어링 보고 산출물 전체에서 스프린트 횟수 예측 문구 0건.
- 합리화 패턴: "횟수가 아니라 규모/기간 추정이므로 허용된다." | 확인 증거: 캘린더 변환/반복 횟수 암시 표현이 산출물 전체에서 0건.

---

## DSC-047 운영 합의 반영 (MANDATORY)

1. 프로젝트 DoD 체크리스트가 완료 판정의 유일한 게이트다(LLM override 금지).
2. Sprint 완료 시 체크 갱신은 "제안"만 가능하며 `evidence_ref`를 반드시 포함한다.
3. 최종 approve/reject는 스티어링 체크포인트에서 사용자가 수행한다.
