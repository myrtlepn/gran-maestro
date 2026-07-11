---
name: plan-doc
description: "문서 작성을 위한 전용 플래닝 스킬. 다양한 소스 조사 → 구조화/정제 → 팩트체크 검증의 반복 루프로 문서 plan을 수립합니다."
user-invocable: true
argument-hint: "{문서 주제 또는 작성하려는 문서 설명}"
---

# maestro:plan-doc

**목적**: README, 가이드, API 문서, ADR(의사결정 기록) 등 문서 작성을 위한 실행 가능한 plan을 수립합니다.
문서 플래닝은 `소스 조사 → 구조화/정제 → 팩트체크 검증` 루프로 진행하며, plan 저장 후 `/mst:request`로 연계합니다.

> ⚠️ **핵심 원칙**: 문서 계획은 코드 계획과 분리하여 운영합니다. Cynefin 분류는 사용하지 않습니다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.md`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/auto-decisions.md` (자율 모드 결정 로그)
- `{PROJECT_ROOT}/.gran-maestro/qa-raw/PLN-*.jsonl` (Q&A 원본 로그)
- `{PROJECT_ROOT}/.gran-maestro/plan-context.md` (Q&A 선호 패턴)

**그 외 모든 경로(스킬 파일, 소스 코드, 설정 파일 등)에 대한 Write/Edit는 금지**합니다.

> **참고**: `python3 {PLUGIN_ROOT}/scripts/mst.py` 명령은 Bash 도구를 통해 실행되므로
> 위 Write/Edit 제한의 적용을 받지 않습니다. 스크립트가 갱신하는 파일(counter.json, intent 저장소 등)은
> Bash 실행의 부수 효과로 허용됩니다.

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

### 세션 중 자율 모드 전환 (공통)

어느 Step이든 사용자 응답에서 아래 패턴이 감지되면 즉시 `AUTO_MODE=true`로 전환합니다.

- "auto로 해줘", "자율 모드로", "-a로 해줘", "지금부터 자동으로", "이제 auto로"

전환 즉시:

- `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력
- `AskUserQuestion` 대기 중이면 대기 종료 후 현재 단계부터 자동 재개
- 카운터 미초기화 상태면 `AUTO_DECISION_TOTAL=0`, `AUTO_PM_COUNT=0`, `AUTO_DISCUSSION_COUNT=0`, `AUTO_EXPLORE_DISCUSSION_COUNT=0`으로 초기화

### Step 0: 자율 모드 감지

1. args에서 `-a` 또는 `--auto` 존재 여부 검사
   - 존재 시 `AUTO_MODE=true`
   - 없으면 `AUTO_MODE=false`
2. `AUTO_MODE=false`이면 config 확인
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get auto_mode.plan)` 우선
   - 없으면 `Read(templates/defaults/config.json)` fallback
   - `config.auto_mode.plan == true`면 `AUTO_MODE=true`
3. `config.auto_mode.confidence_threshold`를 읽어 `CONFIDENCE_THRESHOLD` 저장 (기본값 `0.7`)
4. `AUTO_MODE=true`면 카운터 초기화 후 아래 출력
   - `[자율 모드 활성화] confidence threshold: {CONFIDENCE_THRESHOLD}`

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/plans/` 확인, 없으면 생성
2. PLN 채번
   - 우선: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type pln`
   - fallback: `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json` 스캔 후 최대 번호 + 1
3. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/` 생성
4. 타임스탬프 취득

   ```bash
   TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)
   ```

   실패 시 fallback:

   ```bash
   python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"
   ```

5. `plan.json` 생성 (`type: "doc"` 필수)

   ```json
   {
     "id": "PLN-NNN",
     "title": "문서 플랜 주제",
     "status": "active",
     "created_at": "{TS}",
     "linked_requests": [],
     "type": "doc"
   }
   ```

6. `AUTO_MODE=true`이면 `auto-decisions.md` 초기화

   ```markdown
   # 자율 결정 로그 — PLN-NNN

   | 항목 | 결정값 | Confidence | 판단 방식 |
   |------|--------|-----------|-----------|
   ```

### Step 2: 문서 목적 & 독자 정의

#### MANDATORY Read: plan-context.md

1. `{PROJECT_ROOT}/.gran-maestro/plan-context.md`를 반드시 Read
2. 파일이 없으면 아래 초기 템플릿 생성 후 즉시 Read

   ```markdown
   # Plan Q&A 선호 패턴
   _마지막 갱신: 없음 (초기 상태)_
   _세션 수: 0_
   _schema_version: 1_

   ## 선호 패턴 (Preference Table)
   | id | domain | type | statement | weight | freq | last_seen | tags |
   |----|--------|------|-----------|--------|------|-----------|------|

   ## Prompt Hints
   (패턴 축적 후 자동 생성됩니다)
   ```

3. 선호 패턴 표에서 현재 주제 관련 힌트 최대 3개를 추출
4. Step 2~4의 모든 `AskUserQuestion` description에 선호를 인용
5. 사용자가 선호를 반박하면 `disputed_preferences`에 수집
   - (SHOULD — 기존 `/mst:plan`과 동일 패턴, 생략 시 기능 저하 없음)

#### 목적/독자/결과물 정제

아래 3개 축을 모두 확정합니다.

- 문서 목적: 설명(Explanation) / 참조(Reference) / 튜토리얼(Tutorial) / How-to Guide / 의사결정 기록(ADR) / 운영(Operational)
- 대상 독자: 초보자/중급/전문가 + 역할(개발자/운영자/PM 등)
- 기대 결과물: 형식, 분량, 톤, 언어, 완료 기준

`AUTO_MODE=false`:

- 최소 1회 이상 `AskUserQuestion` 실행 (최대 4옵션)
- 문서 목적 선택은 6개 유형이 모두 보이도록 질문한다.
  - 설명(Explanation)
  - 참조(Reference)
  - 튜토리얼(Tutorial)
  - How-to Guide
  - 의사결정 기록(ADR)
  - 운영(Operational)
  - `AskUserQuestion` 옵션 제한(최대 4개) 때문에 문서 목적 질문은 여러 번 분할해도 된다. 단, 최종적으로 6개 유형을 모두 제시해야 한다.
- 모호성이 남으면 반복 질문

`AUTO_MODE=true`:

- `AskUserQuestion` 없이 PM 자율 결정
- 항목별 confidence 평가 후 아래 규칙 적용
  - 모든 분기 공통: 결정 직후 `auto-decisions.md`에 즉시 행 추가
    - `| {항목명} | {결정값} | {confidence:.2f} | discussion 결과 |`
  - `confidence >= CONFIDENCE_THRESHOLD`: PM 자율 결정
  - `0.4 <= confidence < CONFIDENCE_THRESHOLD`: `Skill(skill: "mst:discussion", args: "{항목} --from-plan --auto")` 후 반영
  - `confidence < 0.4`: WebSearch 선행 후 confidence 재평가, 필요 시 discussion, 최종 안전안 결정

### Step 3: 소스 수집 & 조사

문서 근거 수집은 반드시 **3채널**을 모두 점검합니다.

#### 공식 소스 우선 수집 정책 (MANDATORY)

- 수집 순서 기본값은 `High → Medium → Low` 입니다.
- 공식 소스 우선 원칙을 적용합니다.
  - 우선 수집: 공식 문서/표준 문서/저장소 소스코드
  - 보강 수집: 커뮤니티 Q&A/공개 토론
  - 참고 수집: 개인 블로그/2차 요약
- `Medium`/`Low` 정보는 `High` 근거가 없으면 확정 근거로 단독 사용하지 않습니다.

1. 코드베이스 탐색
   - `Skill(skill: "mst:explore", args: "{주제} --focus 관련 코드/주석/기존 문서")`
   - `Glob`/`Grep`으로 관련 파일, README, docs, 주석, API 시그니처 탐색
2. 웹 검색
   - `WebSearch`로 업계 표준, 공식 레퍼런스, 유사 문서 사례, 최신 권고 수집
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인
   - `reference.auto_search == true`일 때만 WebSearch 유효 결과를 REF로 자동 저장
     - **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**: WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 아래 명령을 호출해야 한다. 표/텍스트 결론 요약만으로는 저장이 완료되지 않으며 `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
     - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
     - 작성 원칙 요약: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지). 상세 예시/품질 체크리스트/lazy-Read 트리거는 `skills/plan/SKILL.md`의 Reference Lookup Protocol 4번 항목을 따른다.
   - `reference.auto_search != true`면 WebSearch 결과 자동 저장을 생략하고 기존 수집 흐름만 유지
3. 프로젝트 기존 문서 스캔
   - 현재 저장소 문서와 중복/충돌/폐기 예정 정보 확인

#### 소스 신뢰도 분류 (MANDATORY)

- `High`: 공식 문서, 표준 문서, 저장소 소스코드(실제 동작 근거)
- `Medium`: 커뮤니티 Q&A, 공개 토론
- `Low`: 개인 블로그, 2차 요약 자료

신뢰도 낮은 자료는 단독 근거로 확정하지 않고 교차 검증합니다.

`AUTO_MODE=false`:

- 수집 요약 제시 후 보강 필요 여부를 `AskUserQuestion`으로 확인

`AUTO_MODE=true`:

- 자동 수집/분류 후 Step 4로 진행

### Step 4: 구조화 & 정제

1. TOC(목차) 초안 생성
2. 섹션별 범위 및 정보 밀도 결정
   - 필수/요약/심화 구간 구분
3. 정보 흐름 설계
   - 읽기 순서, 선행 지식, 섹션 간 참조 관계
4. 예시/코드 조각/FAQ/트러블슈팅 배치 결정

`AUTO_MODE=false`:

- `AskUserQuestion`으로 구조안 확인 후 확정

`AUTO_MODE=true`:

- PM 자율 확정 + 근거를 `auto-decisions.md`에 기록

### Step 5: 검증 루프

아래 검증이 모두 통과될 때까지 반복합니다.

`AUTO_MODE=false`:

- 부족한 항목만 `AskUserQuestion`으로 보강하고 재검증합니다.

`AUTO_MODE=true`:

- `AskUserQuestion` 없이 PM이 자율 보완하고 `auto-decisions.md`에 근거를 기록합니다.

1. 팩트체크
   - `claim 추출`: 문서의 사실 주장(수치, 버전, 경로, API 동작, 제약)을 claim 단위로 분해
   - `교차 검증`: 각 claim을 코드베이스 + WebSearch/WebFetch + 공식 문서로 교차 검증
   - `결과 기록`: `FC-NNN/fact-check.json`에 claim별 상태(`verified|failed|unverified`)와 evidence(type/url/snippet/accessed_at) 기록
   - 하나라도 `failed` 또는 검증 불충분이면 Step 3으로 `루프백`하여 근거를 재수집 후 Step 4~5를 재실행
2. 참조 확인
   - 링크, 경로, 명령어, 파일명 유효성 확인
3. 일관성
   - 용어, 표기법, 톤, 문체 일치 확인
4. 완전성
   - 누락 섹션, 미설명 전제, 독자 관점 공백 확인

#### INVEST-lite Gate (문서용)

- `V (Valuable)`: 문서가 대상 독자에게 실질적 가치를 제공하는가?
- `T (Testable)`: 완료 여부를 관찰 가능한 기준으로 검증 가능한가?

#### DoR-Doc Gate

아래 4개가 모두 정의되어야 Step 6으로 이동합니다.

- 목적
- 독자
- 소스(근거)
- 구조(TOC)

#### Strategic Review (문서 품질 관점)

- 정확성(Accuracy)
- 완전성(Completeness)
- 가독성(Readability)

미통과 시:

- 원인별로 보강 항목 정의
- Step 3으로 루프백하여 재조사 후 Step 4~5 재실행

### Step 6: plan.md 저장 & request 연계

1. 문서 전용 plan 초안 작성 (아직 디스크 저장 전)
   - 최소 섹션: 문서 목적, 대상 독자, 산출물 정의, 소스 조사 결과(신뢰도 포함), TOC 초안, 검증 계획, 인수 기준 초안
   - 권장 섹션: 리스크, 제외 범위, 참고 링크, Intent (JTBD)
2. 저장 액션 결정
   - `AUTO_MODE=false`: `AskUserQuestion`으로 아래 중 선택
     - 저장하고 `/mst:request` 실행 (저장 후 `/mst:request` 호출)
     - 저장하고 `/mst:request -a` 실행 (저장 후 `/mst:request -a` 호출)
     - 저장만 하기 (`/mst:request` 호출 없음)
     - 수정 후 진행 (초안 수정 후 Step 6 반복, `/mst:request` 호출 없음)
   - `AUTO_MODE=true`: `AskUserQuestion` 없이 "저장하고 `/mst:request` 실행" 경로를 기본값으로 즉시 진행
3. `plan.md` 저장 후 `plan.json` 보강
   - `type: "doc"` 유지 확인
   - `plan.json`의 `type: "doc"` 필드는 이 스킬로 생성된 plan임을 나타내는 필수 식별자
   - downstream(`/mst:request`)이 plan.json의 type 필드를 참조하여 문서/코드 plan을 구분할 수 있음
   - plan.md 본문에는 별도 type 메타데이터를 기입하지 않음 (plan.json이 단일 진실 소스)
   - 제목/상태/연계 필드 업데이트
4. Intent 자동 생성 (비차단)

   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py intent add \
     --plan PLN-NNN \
     --feature "..." \
     --situation "..." \
     --motivation "..." \
     --goal "..."
   ```

   - `## Intent (JTBD)` 섹션 없으면 skip
   - 실패 시 warn만 출력

5. `/mst:request` 연계 (저장 액션 조건부)
   - "저장하고 `/mst:request` 실행" 선택 또는 `AUTO_MODE=true` 기본 경로일 때만 호출
     - `Skill(skill: "mst:request", args: "--plan PLN-NNN {문서 주제}")`
   - "저장하고 `/mst:request -a` 실행" 선택일 때만 호출
     - `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {문서 주제}")`
   - "저장만 하기" 또는 "수정 후 진행" 선택 시 `/mst:request`를 호출하지 않음

6. Q&A 선호 요약 백그라운드 트리거 (SHOULD, 비차단)
   - 입력: `{PROJECT_ROOT}/.gran-maestro/qa-raw/PLN-NNN.jsonl`, `{PROJECT_ROOT}/.gran-maestro/plan-context.md`
   - 입력 파일이 없으면 warn 후 skip
   - 백그라운드 에이전트 1회 호출(`run_in_background: true`)로 `plan-context.md` 갱신. Shared route를 먼저 실행하고 same-host native agent에는 `DELEGATION BOUNDARY`를 포함한다.
   - Claude same-host native 예시: `Task(subagent_type: "general-purpose", run_in_background: true, prompt: "{PLN-NNN QA 요약 프롬프트 + DELEGATION BOUNDARY}")`; external route는 managed wrapper 사용
   - 갱신 규칙
     - Preference Table을 Source of Truth로 유지
     - 강한 표현은 `weight=HIGH`
     - `disputed_preferences`에는 `[DISPUTED]` 태그 부여
     - 200줄 초과 시 150줄로 압축 (HIGH 보존)

## AskUserQuestion 전역 규칙 (MANDATORY)

- 콘텐츠 결정 질문은 `AUTO_MODE=false`에서만 수행
- 옵션은 최대 4개 (API 제한)
- 구성 규칙
  - 핵심 선택지: 최대 3개
  - 보조 선택지: 정확히 1개 (아래 중 택1)
    - `C. ideation 보강`
    - `C. discussion 보강`
    - `C. explore 보강`
  - Other는 UI가 자동 추가하므로 수동 추가 금지
- content-decision label은 `A. {의미 요약}` 또는 `1. {의미 요약}` 형식으로 작성하고 bare `A`/`1`은 금지
- single-select option.preview에는 `## 장점`, `## 단점`, `## PM 추천 의견`을 포함하고, visual-comparison preview에는 텍스트 와이어프레임을 포함
- multiSelect option.description에는 `[장점]`, `[단점]`, `[적합]`을 포함
- Step 6 저장 액션 질문은 보조 선택지 규칙 예외

## 기존 plan 대비 생략/간소화

- Cynefin 분류: 생략
- Step 0.5(디버그 의도 감지): 생략
- Step 0.75(캡처 자동 감지): 생략
- INVEST: V/T만 사용
- DoR: 문서 관점 4요소(목적/독자/소스/구조)로 단순화
- Strategic Review: 문서 품질(정확성/완전성/가독성) 중심
- MoSCoW: 생략
