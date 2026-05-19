---
name: request
description: "요구사항을 분석하고 구현 스펙(spec.md)을 작성합니다. 실행 승인은 /mst:approve로 별도 진행합니다. 사용자가 '구현해줘', '만들어줘', '개발해줘', '추가해줘'를 말하거나 /mst:request를 호출할 때 사용."
user-invocable: true
argument-hint: "[--auto|-a] [--resume REQ-NNN | REQ-NNN | {요청 내용}]"
---

# maestro:request

Gran Maestro 워크플로우의 시작점. 사용자의 요청을 받아 PM 분석 Phase에 진입합니다.

## 모드 전환 (자동 부트스트래핑)

Maestro 모드 비활성 시 자동 활성화:
- `{PROJECT_ROOT}/.gran-maestro/` 디렉토리 생성, `.gitignore`에 등록 (미존재 시)
- `config.json` / `agents.json` 없으면 `templates/defaults/`에서 복사
- `mode.json` 확인: `active: false`이거나 파일 없음 → 아래 내용으로 생성/업데이트:

   > ⏱️ **타임스탬프 취득 (MANDATORY)**:
   > `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
   > 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
   > 출력값을 `activated_at` 필드에 기입한다. 날짜만 기입 금지.

     ```json
     {
       "active": true,
       "activated_at": "{TS — mst.py timestamp now 출력값}",
       "auto_deactivate": true,
       }
     ```
- `requests/`, `worktrees/` 디렉토리 확인, 없으면 생성
- 사용자에게 모드 전환 알림 (첫 활성화 시에만)

## Gate

### Entry

- Step 0.5에서 `workflow.default_agent`를 읽어 Assigned Agent 결정 근거를 확보한다.
- `--resume/--plan` 해석과 `source_plan` 정합성을 완료한 뒤에만 spec 작성 단계로 진입한다.
- 실행 범위를 spec 산출(`request.json`, `tasks/*/spec.md`)로 제한하고 구현 행위는 차단한다.

### Exit

- 모든 대상 태스크의 `spec.md`가 생성되고 `request.json.tasks` 메타데이터가 동기화되어야 한다.
- `request.json.status`가 `spec_ready`(또는 auto approve 연계 상태)로 갱신되어야 한다.
- 승인 안내(`/mst:approve` 또는 `/mst:approve -a`) 또는 자동 진입 로그가 남아야 한다.

### 금지 패턴

- spec 저장/승인 확인 전에 코드 수정, 파일 편집, 빌드, 커밋을 수행한다.
- `workflow.default_agent` 확인 없이 Assigned Agent를 추정으로 기입한다.
- plan 컨텍스트가 있는데도 탐색/근거 수집을 생략하고 AC를 형식적으로 작성한다.
- "컨텍스트 압박"을 이유로 sub-plan chain을 우회하여 직접 `codex exec` + master 커밋으로 전환한다. 격리 실행이 필요하면 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 경로를 사용한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "plan에서 이미 분석했으니 코드베이스 탐색을 축약해도 된다." | 확인 증거: spec `§0 Context Manifest`에 실제 탐색 근거 파일 경로를 남긴다.
- 합리화 패턴: "단순 요청이니 AC를 짧게 쓰고 Given/When/Then/Test를 생략한다." | 확인 증거: 각 AC를 Given/When/Then/Test 형식으로 작성하고 AC ID를 `request.json.tasks[].covers_ac`에 매핑한다.
- 합리화 패턴: "속도를 위해 승인/사전검토 분기를 임의로 건너뛴다." | 확인 증거: 실행 로그에 `AUTO_APPROVE` 결정 근거(CLI/config)와 적용 경로를 출력한다.
- 합리화 패턴: "컨텍스트 한계에 도달했으니 체인을 건너뛰고 직접 codex로 끝내자." | 확인 증거: 체인 우회가 필요한 경우 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 사용 로그가 `auto-decisions.md` 또는 `retrospective.md`에 남아있어야 한다.
- 합리화 패턴: "컨텍스트가 길어졌으니/토큰 효율을 위해/변경 추적 품질을 위해 다음 단계를 새 세션에서 진행하는 게 낫다." | 확인 증거: 자동 연쇄 진입 컨텍스트 블록의 수치(context_pct, auto_approve_on_unblock)를 인용하여 chain 지속이 정상 경로임을 명시한 뒤 다음 스킬을 자동 호출한다.

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

State execution contract: state write commands inherit `MST_SESSION_ID` from the current session or receive equivalent structured context; do not inject process-scoped identity into canonical writes.

Parent session inheritance contract: child invocation, subprocess, and hook execution inherit parent `MST_SESSION_ID`; children must not issue arbitrary `mst_session_id`. Hook payload `mst_session_id` is allowed only when it matches the inherited parent `MST_SESSION_ID`.

DOD-007 canonical identity boundary: `MST_SESSION_ID` / `mst_session_id`만 canonical identity source다. Legacy-only input(`MST_STATE_PPID`, `owner_ppid`, `owner_session_id`, `owner_pid`, Claude hook `session_id`, transcript UUID, `MST_SNAPSHOT_SESSION_ID`, legacy aliases `sessionId`/`session_id`)은 diagnostic-only이며 canonical source, fallback, alias, migration requirement가 아니다. Legacy-only input은 session/state/history/snapshot/recovery/lock mutation 없이 structured non-success로 종료해야 한다. Canonical `MST_SESSION_ID`/`mst_session_id`와 legacy 값이 충돌하면 canonical identity가 우선하고 legacy 값은 override/repair/merge/persist source가 될 수 없다.

DOD-009 session identity glossary: `mst_session_id` is the canonical state machine identity payload/context field issued by `mst.py` as `MST-{root_mst_id}-{started_at_compact}-{random}`; it partitions `.gran-maestro/state/{mst_session_id}/snapshot.json` and `.gran-maestro/sessions/{mst_session_id}/history.*`. `MST_SESSION_ID` is the environment variable carrying the same canonical identity through child invocation, subprocess, and hook execution. A root resource ID such as `AGI-030`, `PLN-638`, or `REQ-*` can be the root component inside `mst_session_id`, but it is not the full canonical session identity. A process diagnostic ID such as `owner_pid`, `MST_STATE_PPID`, hook `session_id`, or transcript UUID is diagnostic-only; diagnostic output is allowed, but those values are not canonical source, fallback, alias, migration requirement. legacy aliases such as `session_id`, `sessionId`, or `MST_SNAPSHOT_SESSION_ID` are compatibility diagnostics and not canonical source, fallback, alias, migration requirement. source precedence is validated history ledger, validated state snapshot, then prompt summary as diagnostic-only context.

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

<!-- @include _shared/reference-lookup.md -->
### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인한다. `true`일 때만 자동 WebSearch를 허용한다. 설정 미존재 시 기본값은 `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**: 현재 단계 입력에서 외부 의존성 키워드를 감지한다. `reference.llm_auto_trigger == true`이면 PM이 최신 정보가 필요하다고 판단할 때도 WebSearch를 트리거한다. `false`이면 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**: (a) `.gran-maestro/references/` 캐시를 `reference search --keyword "{keyword}" --json`으로 확인, (b) `searched_at + cache_ttl_days` 기준 `fresh/stale` 판정, (c) 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired` 판정.
3. **WebSearch 트리거**: 캐시 없음 또는 `stale/expired`일 때만 검색한다. `reference.auto_search == true`일 때만 실행하고 Step당 `max_searches_per_step`을 넘지 않는다. `reference.auto_fact_check == true`이면 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**: WebSearch를 1건이라도 실행했으면 결과마다 `Bash`로 `mst.py reference add`를 호출한다. 표/텍스트 결론 요약만으로는 저장 완료가 아니며 `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 예시 A (인용): `> 인용: "{원문 핵심 문장}" (출처: {URL}, 날짜: {YYYY-MM-DD})`
   - 예시 B (표): `| 열 | 값 |` 형태의 raw markdown table과 출처 URL을 보존한다.
   - 예시 C (코드 스니펫): fenced code block(```text)으로 raw 코드와 문서 URL/버전을 남긴다.
   - 신규 REF 품질 체크리스트 (저장 전 점검): Findings: 결론 1~3줄. Quotes: 짧은 원문 인용+URL. Data: 표/버전/날짜/수치. Context: 현재 plan 판단에 필요한 이유.
   - PM lazy-Read 트리거 (`content.md Read` 필수): summary만으로 부족하거나 표/코드/원문 뉘앙스가 결론에 영향을 주면 반드시 `content.md`를 Read한다.
5. **프롬프트 주입**: 이후 단계 프롬프트에 `[REFERENCE_CONTEXT]`를 주입한다. 형식: `current_date`, `model_cutoff`, `references: REF-001 (fresh|stale|expired) {topic} | {url}`. 참조가 없으면 `references: none`으로 명시한다.
<!-- @end-include -->

### Step 0: 아카이브 체크 (자동)

`archive.auto_archive_on_create`가 true이면:
- **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request count --active` → 초과 시 `python3 {PLUGIN_ROOT}/scripts/mst.py archive run --max {max_active_sessions}`
- **Fallback**: REQ-* 디렉토리 수 확인 → 초과분 tar.gz 압축 후 원본 삭제

상세 아카이브 로직은 `/mst:archive` 스킬의 "자동 아카이브 프로토콜" 참조.

### Step 0.5: 에이전트 기본값 취득 (MANDATORY)

> ⚠️ 이 단계는 건너뛸 수 없음: spec.md Assigned Agent 결정 전 반드시 실행. 이 단계 없이 spec.md 작성 금지.

Bash(`python3 {PLUGIN_ROOT}/scripts/mst.py config get workflow.default_agent auto_mode.request --json`) → 결과를 `request_bootstrap_config`로 보관하고 `workflow.default_agent`를 추출해 DEFAULT_AGENT 변수에 저장한다. 같은 preload의 `auto_mode.request` 값은 아래 auto_mode 판단에서 재사용한다.
파일이 없으면 `templates/defaults/config.json`에서 `workflow.default_agent`와 `agent_assignments`를 Read하여 DEFAULT_AGENT 및 도메인 추론 기준으로 사용한다.

모든 spec.md의 Assigned Agent 필드는 반드시 `[config: {DEFAULT_AGENT}] → ...` 형식으로 DEFAULT_AGENT를 명시해야 한다. DEFAULT_AGENT 미확인 상태의 Assigned Agent 결정은 에러로 처리한다. `agent_assignments` 읽기 시 `_`로 시작하는 키는 에이전트명으로 간주하지 않는다. `config.resolved.json` 없으면 `templates/defaults/config.json`의 `agent_assignments`를 fallback으로 Read한다.

#### auto_mode config 읽기

1. CLI 인자에서 `--auto` / `-a` 감지 시 `AUTO_APPROVE=true`로 설정한다 (CLI 최우선).
1.5. CLI 인자에 `-a`/`--auto`가 없으면 state guarded fallback을 시도한다:
   - `{PLUGIN_ROOT}/scripts` 경유로 `read_workflow_state_auto_mode("mst:request", expected_source_id)` 호출
   - `expected_source_id`: `--plan PLN-NNN`이 있으면 `PLN-NNN`, `--resume REQ-NNN`이 있으면 `REQ-NNN`, 둘 다 없으면 `None`
   - 반환값이 bool이면 `AUTO_APPROVE`에 채택; `None`이면 Step 2(config)로 진행
2. Step 0.5의 `request_bootstrap_config`에서 `auto_mode.request` 값을 확인한다. preload가 없으면 같은 batched 명령을 1회 재실행해 복구한다. `true`면 `AUTO_APPROVE=true`.
3. 최종 우선순위: `args > state(guarded) > config > default(false)`.

### Step 1: 요청 생성/재개

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

1. 재개 대상 감지:
   - CLI 인자에 `--resume REQ-NNN`이 있으면 `RESUME_REQ_ID=REQ-NNN`
   - `--resume` 없어도 자유 인자에 단일 `REQ-NNN` 패턴이 있으면 하위 호환으로 재개로 해석
   - `--resume` 값과 자유 인자 REQ-ID가 동시에 존재하고 서로 다르면 오류로 중단
2. `RESUME_REQ_ID`가 설정된 경우(기존 REQ 재개 분기):
   - `{PROJECT_ROOT}/.gran-maestro/requests/{RESUME_REQ_ID}/request.json` Read
   - 파일이 없으면 오류 출력 후 중단 (`신규 REQ 생성 금지`)
   - `status` 검증: 허용 = `pending_dependency`, `phase1_analysis`, `spec_ready`; 거부 = `done`, `completed`, `accepted`, `cancelled`
   - `pending_dependency` 상태면 `dependencies.blockedBy`를 확인: 비어있지 않으면 중단, 비어있으면 `phase1_analysis`로 전이 후 진행
   - `--plan PLN-NNN` 함께 제공 시 `source_plan` 정합성 확인: 기존 `source_plan` 없으면 보강, 다른 값이면 오류
   - `request.json.auto_approve`는 현재 실행 컨텍스트의 `AUTO_APPROVE` 값으로 동기화
   - 이 분기에서는 **REQ 채번/디렉토리 생성/신규 request.json 생성을 수행하지 않는다**
3. `RESUME_REQ_ID`가 없는 경우(신규 REQ 생성 분기):
   - 새 요청 ID 채번 (REQ-NNN):
     - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next` → 출력 ID 사용
     - **Fallback**: `{PROJECT_ROOT}/.gran-maestro/requests/counter.json` Read → `next_id = last_id + 1`; 파일 미존재 시 `requests/`, `requests/completed/`, `archive/requests-*`에서 최대 번호 결정 후 `counter.json` 생성
   - `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/` 디렉토리 생성 (NNN은 3자리 zero-padded), 하위 `tasks/`, `discussion/`, `design/` 서브디렉토리도 함께 생성
   - 요청 메타데이터 기록 (`request.json`):

   > ⏱️ **타임스탬프 취득 (MANDATORY)**:
   > `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
   > 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
   > 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

   ```json
   {
     "id": "REQ-NNN",
     "title": "{사용자 요청 요약}",
     "original_request": "{전체 요청 텍스트}",
     "status": "phase1_analysis",
     "current_phase": 1,
     "created_at": "{TS — mst.py timestamp now 출력값}",
     "auto_approve": false,
     "source_plan": null,
     "dag_auto_chain": false,
     "tasks": [],
     "dependencies": { "blockedBy": [], "relatedTo": [], "blocks": [] },
     "stitch_screens": []
   }
   ```
   - `auto_approve`: CLI `--auto`/`-a` 감지 시 `true` (최우선); 없고 `config.auto_mode.request=true`이면 `true`; 그 외 `false`
   - `source_plan`: `null`(plan 없이 생성), `"PLN-NNN"`(plan 기반), 필드 부재(구버전)
   - `dag_auto_chain`: `false`(기본, 현재 REQ만), `true`(DAG 연쇄 실행), 필드 부재 시 `false` 간주
   - DOD-005 scope split: `request` 단계는 merge authority를 부여하지 않는다. `request.json.detected_base`는 approve 이후 session branch로 기록될 수 있고, `original_base_branch`/`original_base_sha`는 final original merge evidence로만 후속 단계에서 기록/사용한다.
   - `AUTO_APPROVE=true`이면 workflow state를 기록한다 (non-blocking):
     - `ACTIVE_REQ_ID`는 재개 분기에서는 `RESUME_REQ_ID`, 신규 생성 분기에서는 `REQ-NNN`
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
       --active true \
       --skill mst:request \
       --req "${ACTIVE_REQ_ID}" \
       --next-skill mst:approve \
       --next-source "${ACTIVE_REQ_ID}" \
       --source-skill mst:request \
       --auto true \
     || echo "[mst:request] warning: failed to update workflow state" >&2
     ```
   - `AUTO_APPROVE=false`에서는 이 호출을 실행하지 않는다.
4. PM Conductor 역할로 Phase 1 분석 수행 (`agents/pm-conductor.md`의 `<phase1_protocol>` 준수):
   a. 요청 파싱 및 복잡도 분류 (simple | standard | complex)
   b. Simple → 단독 분석 / Standard·Complex → Analysis Squad 팀 소환
   c. 코드베이스 탐색 (`config.phase1_exploration.roles` 기반 병렬):
      > ⚠️ **탐색 목적**: ① 기존 패턴·컨벤션 파악 ② 핵심 진입점 식별(1~3개 파일/디렉토리) ③ 충돌 가능성 감지. 구체적인 구현 방법은 에이전트가 worktree에서 직접 판단한다.

      config 읽기: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get phase1_exploration.roles)` 출력의 `phase1_exploration.roles` 참조
      각 role의 모델 결정: `phase1_exploration.roles.{role}.tier` → `providers[agent][tier]`로 resolve (tier 미지정 시 `providers[agent].default_tier` 사용)
      ① `symbol_tracing` role agent [background dispatch] — enabled=true인 경우
      ② `broad_scan` role agent [background dispatch] — enabled=true인 경우 (①과 동일 응답에서 dispatch)
      ③ Claude 직접 탐색 [즉시 시작] — Read/Glob/Grep 자율 실행 (탐색 범위 자율 판단, 중복 허용)
      수신된 결과를 Claude 직접 탐색 컨텍스트와 함께 종합. 총 소요 = max(enabled_roles_time, claude_direct_time).
      반드시 `Skill(skill: "mst:codex/gemini", ...)` 도구로 호출 — MCP 직접 호출 금지. role agent 기본값: symbol_tracing=codex, broad_scan=gemini
   c-ref. **Reference Lookup 실행 (Step 1c 완료 직후, Step h 이전, MANDATORY)**:
      - Step 1c 탐색 산출물 + 요청 원문 + plan 컨텍스트를 입력으로 `Reference Lookup Protocol`을 실행한다.
      - `reference.auto_search != true`이면 기존 REF 캐시 조회만 수행한다.
      - 생성된 `[REFERENCE_CONTEXT]`를 `reference_context_block`으로 보관하고 Step h spec 작성 프롬프트에 반드시 주입한다.
   c-arch. **아키텍처 논의 게이트 (Step 1d-arch)**:
      - 실행 시점: Step 1c 탐색 완료 직후 (Step 1e 이전)
      - PM은 탐색 결과를 바탕으로 트리거 조건 A·B·C를 점검:
        - A. 의존 fan-out이 넓어져 다수 모듈에 연쇄 영향이 예상되는가?
        - B. 인터페이스 계약(API/함수 시그니처/이벤트 계약) 변경이 필요한가?
        - C. 데이터 흐름의 분기점(입력/출력 경로, 상태 전이 경계) 변경이 있는가?
      - `pm_arch_confidence`(0.0~1.0) 산정 기준:
        - 0.0~0.3: 변경 범위 명확, 단일 모듈 한정, 기존 패턴 단순 적용 가능
        - 0.4~0.6: 일부 모듈 의존성 변경 예상되나 영향 범위 파악 가능
        - 0.7~1.0: 다수 모듈 연쇄 영향, 아키텍처 방향 불명확, 설계 리스크 존재
      - workflow gate preload: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get workflow.arch_gate_threshold workflow.high_pass_guard --json)` 결과를 `workflow_gate_config`로 보관한다.
      - `arch_gate_threshold` 읽기: `workflow_gate_config`의 `workflow.arch_gate_threshold` 사용 → fallback `templates/defaults/config.json` → fallback `0.7`
      - `workflow.high_pass_guard` 읽기: 같은 `workflow_gate_config`의 `workflow.high_pass_guard` 사용 → fallback `templates/defaults/config.json` → fallback: `enabled=true`, `confidence_supporting_only=true`, `require_external_execution_evidence=true`, `require_independent_judgement=true`, `block_self_report_only_pass=true`, `plan_bypass_requires_explicit_rationale=true`
      - 하드 게이트 규칙 (`enabled=true` 기준):
        - reason token 키: `self_report_only_block`, `external_evidence_missing`, `independent_judgement_required`, `"risk_signal_review_required"`.
        - `confidence`는 보조 신호이며, risk signal(A/B/C) 중 하나라도 감지되면 confidence 값만으로 gate를 닫을 수 없다.
        - 입력 증거가 LLM self-report만이고 외부 실행 증거가 없으면 gate를 닫지 않는다.
        - 외부 실행 증거와 분리된 판정 단계 중 하나라도 없으면 gate를 닫지 않는다.
        - 위 조건에 걸리면 `req-arch-decision.md`의 `reason`에 해당 reason token을 기록하고 추가 검토 경로를 유지한다.
      - 트리거-게이트 결정:
        - Gate Open: A/B/C 중 1개 이상 충족 AND (`pm_arch_confidence >= arch_gate_threshold` 또는 `high_pass_guard.enabled=true` 또는 self-report only + 증거 부족)
        - Gate Close: A/B/C 모두 미충족 AND self-report only 아님 AND 외부 실행 증거+분리된 판정 단계 모두 확인 AND (`pm_arch_confidence < arch_gate_threshold` 또는 명시적 비위험 근거 기록)
      - `--plan` bypass: `plan_bypass_requires_explicit_rationale=true`이면 plan 기반 명시적 우회 근거(외부 실행 증거 + 분리된 판정 단계 출처) 필수. 없으면 bypass 거부 → Gate Open. 허용 시에도 `req-arch-decision.md`에 `gate: skip`, `reason: "plan 참조 + explicit rationale"` 저장.
      - AUTO_APPROVE=false + Gate Open: `AskUserQuestion`으로 방향 선택 요청. label은 `"A. 제안 방향 진행"`, `"B. 방향 재지정"`, `"C. 보조 검토"`처럼 의미를 포함하고, 각 option은 description 또는 preview에 장점·단점·추천 상황을 담는다.
      - AUTO_APPROVE=true + Gate Open: PM 자율 결정. 방향 미확정/발산 필요 → ideation; 리스크·합의 복잡 → discussion; 동시 충족 → discussion 우선; 두 조건 미충족 → ideation 기본
      - Gate Open이든 Close든, 판단 결과를 `REQ-NNN/discussion/req-arch-decision.md`에 저장:
        ```yaml
        gate: open | close | skip
        reason: "..."
        confidence: 0.75
        threshold: 0.7
        triggers:
          A: true | false
          B: true | false
          C: true | false
        result: ideation | discussion | none
        arch_direction: "방향 요약 (gate open 시만)"
        ```
      - Gate Open 후 방향 확정 시에만 spec.md에 `## 아키텍처 영향도 검토` 섹션을 삽입한다. Gate Close/skip 시 미삽입.
   d-1. `--from-debug DBG-NNN` 제공 여부 처리:
      - `debug/DBG-NNN/debug-report.md` Read (미존재 시 경고 후 플래그 무시)
      - `debug_context` 보관: `linked_debug_id`, `root_cause`, `fix_suggestions`, `affected_files`
      - `request.json`에 `"linked_debug": "DBG-NNN"` 필드 추가; spec.md에 `## 디버그 연계` 섹션 자동 삽입
      - `--from-debug`와 `--plan` 동시 시: `--plan` 우선, debug_context는 보조 유지
   d-0. **active plan resolver** (`--plan` 미지정 시, Step d 직전):
      - 실행 조건: CLI 인자와 자연어 본문에서 `PLN-NNN`이 감지되지 않은 경우
      - `plans/*/plan.json`에서 `status == "active"`인 plan만 `updated_at` 내림차순으로 수집
      - 후보 0건: resolver skip, `source_plan: null` 유지
      - 후보 1건: 자동 제안. `AUTO_APPROVE=false` → AskUserQuestion으로 확인; `AUTO_APPROVE=true` → 자동 채택
      - 후보 2건 이상: `AUTO_APPROVE=false` → AskUserQuestion으로 선택; `AUTO_APPROVE=true` → 최신 1건 자동 채택, 나머지는 로그에 후보로 기록
      - `resolved_plan_id`가 설정되면 Step d에서 `--plan PLN-NNN`과 동일하게 처리한다.
   d. `--plan` 제공 여부 처리:
      - `--plan PLN-NNN` 또는 자연어 `PLN-NNN` 또는 `resolved_plan_id` 감지 시 `plans/PLN-NNN/plan.json` + `plan.md` Read
      - plan Read 성공 시: `request.json`에 `source_plan: "PLN-NNN"` 기록; `plan.json`의 `linked_requests`에 REQ-NNN 추가, `status` `active` → `in_progress`
      - plan.md 결정사항·범위·제약을 Phase 1 인풋으로 사용
      - **Objective 컨텍스트 감지 (MANDATORY)**:
        - plan.md에 `## Objective 컨텍스트` 섹션이 존재하면 파싱해 `objective_context` 변수로 보관 (`objective_md_path`, `jtbd_summary`, `project_dod_items[]`, `success_metrics[]`, `anchor_manifest_path`, `anchor_coverage_evidence`).
        - plan.json의 `linked_objective`, plan.md의 agile N계층 마커, `objective.ids.json`, 또는 `## Objective Trace`/objective anchor coverage evidence가 있으면 agile-origin으로 판정한다.
        - legacy/non-agile plan에서 섹션이 없으면 `objective_context=null`로 처리한다 (하위 호환).
        - agile-origin에서 objective_context 또는 anchor manifest가 없으면 silent skip 금지: plan/objective 경로에서 자동 복원하고, 복원 불가 시 `request.json`/spec preflight에 blocking 또는 MAJOR failure evidence를 남긴다.
      - **plan type 전략 감지 (MANDATORY, plan.json Read 직후)**:
        - `plan_type = plan.json.type` (미존재 시 `"code"`)
        - `plan_strategy = type_strategies[plan_type] || type_strategies["code"]` (`{PLUGIN_ROOT}/templates/defaults/type-strategies.json` Read)
        - Read 실패 시 fallback: `{"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`
        - `plan_strategy.template == "templates/doc-request.md"` → `DOC_SPEC_MODE=true`; 그 외 → `DOC_SPEC_MODE=false`
      - **§0 Context Manifest 후보 수집 (MANDATORY)**:
        - `source_plan`이 있으면 `plan.md`, `plan.json`, `plan.ids.json`을 `context_manifest_files`의 기본 시드로 먼저 추가한다.
        - agile-origin objective details가 있으면 `context-transfer-contract.md` 같은 objective details 원본을 dedupe 추가한다.
        - 현재 요청이 skill/template contract 변경이면 `skills/request/SKILL.md`, `skills/approve/SKILL.md`, `templates/impl-request.md`, `templates/spec.md` 같은 governing source를 dedupe 추가한다.
        - 1차 소스: plan.md의 범위 섹션에서 `시작점 힌트` 파일 목록 추출 → `context_manifest_files`
        - 1차 소스가 비어있으면 fallback: Step 1c 탐색 결과의 핵심 진입 파일 + 요청 분석에서 1~3개 경로 추론 (디렉토리는 대표 진입 파일로 정규화)
        - 필수 source를 찾지 못하면 silent skip 대신 spec 본문 또는 생성 메모에 `missing_context`, `NO_SOURCE_PLAN`, `NO_PLAN_JSON`, `NO_PLAN_IDS`, `NO_LINKED_OBJECTIVE`, `NO_OBJECTIVE_IDS`, `NO_CONTEXT_MANIFEST` 중 적절한 표식을 남긴다.
        - `context_manifest_files`는 최소 1개 이상 유지 (빈 목록 금지)
      - **linked_designs 감지** (`plan.json`의 `linked_designs` 배열 비어있지 않을 때):
        - 각 DES-NNN에 대해 `designs/DES-NNN/design.json` Read (미존재 시 silent skip)
        - `stitch_project_url` + `screens[]` 추출 → `des_context` 보관; `html_file`이 null/빈 문자열이면 `"N/A"`, 존재하면 절대경로로 변환
        - `request.json`에 `"linked_designs": ["DES-NNN", ...]` 추가
        - spec.md §10 자동 채움:
          ```markdown
          ## 10. UI 설계 (Stitch)
          - Stitch 프로젝트: {stitch_project_url}
          - 생성 화면:
            - {screens[0].title}: {screens[0].url}
              구현 코드: {screens[0].html_file 절대경로 또는 N/A}
          ```
          `screens[]` 비어있으면 프로젝트 URL만, `linked_designs` 비어있으면 전체 skip
      - **캡처 참조 감지** (plan.md의 `## 캡처 참조` 섹션이 존재할 때):
        - plan.md의 `## 캡처 참조` 테이블 파싱 → 각 CAP-NNN의 `capture.json` Read (`selector`, `css_path`, `memo`, `screenshot_path` 추출)
        - `request.json`에 `"linked_captures": ["CAP-NNN", ...]` 추가
        - spec.md §11 `## 캡처 컨텍스트` 자동 채움:
          ```markdown
          ## 11. 캡처 컨텍스트
          | CAP ID | 요소 | CSS Path | Memo | Screenshot |
          |--------|------|----------|------|------------|
          | CAP-001 | {selector} | {css_path} | {memo} | {screenshot_path} |
          ```
          10개 이상: 상위 5개만 인라인, "추가 N개 캡처 — captures/ 디렉토리의 capture.json 참조" 안내. 섹션 없으면 전체 skip.
      - **linked_intent 주입** (`plan.json`에 `linked_intent` 필드 존재 시):
        - `python3 {PLUGIN_ROOT}/scripts/mst.py intent get {INTENT_ID} --json`
        - 반환된 metadata(feature, situation, motivation, goal)를 spec.md `## Intent (JTBD)` 섹션에 주입. 실패 시 warn만 출력, 워크플로우 차단 금지.
      - **분리 실행 감지**: plan.md의 `## 분리 실행` 섹션에 2개 이상 단계 시 다중 REQ 생성 모드:
        1. REQ-NNN = 1단계(①), 2단계부터 REQ 채번·생성 (`status: "pending_dependency"`, `blockedBy` 설정). 모든 단계 REQ의 `request.json`에 `source_plan: "PLN-NNN"`을 동일하게 기록.
        2. 1단계 `request.json`에 `dependencies.blocks` 설정, `plan.json`에 모든 REQ ID 추가
        3. **첫 REQ DAG 자동 연쇄 실행 확인** (1단계 REQ만):
           - `AUTO_APPROVE=true`: AskUserQuestion 생략, 1단계 `dag_auto_chain=true` 자동 설정
           - `AUTO_APPROVE=false`: AskUserQuestion으로 "예(DAG 순서로 자동 연쇄)" / "아니오(이 REQ만 실행)" 확인
        4. 사용자에게 생성 결과 요약 표시; spec 생성은 **REQ-NNN (1단계)에만** 수행
      - plan.json/plan.md 미존재 시 경고 후 사일런트 모드로 전환 (`source_plan`은 기존 값 유지)
   d-doc. **§ Doc Spec Flow** (`DOC_SPEC_MODE=true`일 때만 실행):
      - 문서 plan 입력 수집: plan.md에서 `## TOC 초안`, `## 소스 조사 결과`, `## 검증 계획` 섹션 Read → `doc_toc`, `doc_sources`, `doc_verification_plan` 보관. 하나라도 누락 시 경고 후 중단.
      - `doc_sub_type`: `plan.json.doc_sub_type` 우선 (`tutorial|howto|reference|explanation|adr|operational`만 허용) → plan.md 목적 텍스트 매핑 → 최종 fallback `"explanation"`
      - `type-strategies.json`의 `doc.sub_types[doc_sub_type]`에서 `verification`/`checklist` 읽기 (누락 시 `explanation` 전략으로 fallback)
      - spec 변환 규칙: `§1 요약`/`§2 범위`는 문서 목적·독자·산출물 기준으로 작성; AC는 정확성·완결성·독자적합성·subtype 적용 기준으로 작성
      - 태스크 분해: `doc_toc`의 상위 섹션 1개 = 1개 집필 태스크; 각 태스크에 `doc_sources` 근거와 `doc_subtype_checklist` 검증 항목 포함; TOC 순서 기반 실행
      - Step h 및 h-1 분해 규칙은 본 섹션 규칙을 우선 적용한다.
   e. **모호한 요구사항 처리**:
      - [--plan]: plan.md 결정 사항을 따름
      - [--plan 없음]: PM이 모호함 수준 평가:
        - **minor**: 합리적 가정 수립 → spec.md "가정 사항" 섹션에 기록 → 진행
        - **significant**: PM 자율 판단으로 ideation(다각도 비교)/discussion(리스크/합의) 선택 → `Skill(skill: "mst:ideation"/"mst:discussion", args: "{주제} --from-request")` 실행 → 핵심 3~5개 추출 후 자동 진행 → `discussion/req-ambiguity-{synthesis|consensus}.md`에 저장 → spec.md `## 9. 팀 판단 기반 결정` 섹션에 기록
   f. **디버그 의도 감지 (LLM 판단)**: 버그/에러/원인분석 등 디버깅 의도 감지 시:
      - `auto_trigger_from_request=true`: `/mst:debug` 자동 호출 후 이 워크플로우 종료
      - `false`: `/mst:debug` 사용 안내 후 일반 워크플로우 진행
   g. 접근 방식 결정 시 **Ideation 자동 트리거 (LLM 판단)**: 아래 중 하나 해당 시 `Skill(skill: "mst:ideation", args: "{주제} --from-request")` 호출:
      - Step 1d-arch에서 이미 ideation/discussion이 실행된 경우 이 단계는 **반드시 skip한다** (중복 실행 방지)
      - `complex` 분류, 트레이드오프 불명확, 고영향 의사결정, PM 단독 판단 확신 부족
      - 기술 스택·아키텍처·구현 접근법 결정 (plan 미사용 시, 또는 plan에서 의도적으로 미결 상태로 남긴 경우)
      - 코드베이스 탐색(1c) 결과가 접근법 선택에 영향을 줄 만큼 중요한 패턴을 발견한 경우

      > ⚠️ plan에서 기술 접근법을 결정하지 않는 것은 의도된 설계입니다. 코드베이스를 직접 본 상태에서 결정하는 이 단계가 더 정확한 판단을 제공합니다.

      **게이트 오픈 처리**:
      - `AUTO_APPROVE=false`: AskUserQuestion으로 사용자에게 접근 방식 확인 (후보 2~3개, 트레이드오프 포함, 보조 선택지 "ideation으로 다각도 검토" 포함) → 답변 반영 후 g-1로 진행
      - `AUTO_APPROVE=true`: `Skill(skill: "mst:ideation", args: "{주제} --from-request")` 자율 실행 → 결과를 spec 작성에 반영 → `discussion/req-approach-synthesis.md`에 저장
      - simple 요청/접근 방식 명백한 경우 ideation 없이 진행
   g-1. **구현 수준 리서치 패스** (Step g 완료 직후, Step h 진입 전)

      **트리거 조건** (하나 이상 해당 시 실행): `complex` 분류, 신규 라이브러리·패턴·API 도입, Step g에서 ideation/discussion 실행, PM 구현 접근법 확신도 0.7 미만

      **skip 조건** (하나라도 해당 시 skip): `simple` 분류 AND 코드베이스 내 동일 패턴 전례 존재; `--plan` 제공 AND plan.md에 구현 방식 구체적으로 명시; `req-impl-research.md` 존재; `AUTO_APPROVE=true`(단, 아래 자율 처리 참조)

      **AUTO_APPROVE=true 처리**:
      - 기본 skip. PM이 `impl_confidence`(0.0~1.0) 자체 산정 후 자력으로 높이는 것 최우선: ① 코드베이스 재탐색 → ② WebSearch 구현 수준 표준 확인 → ③ 재산정
      - `impl_confidence >= 0.7`: PM 자율 판단으로 spec 보정 후 h-0 진행
      - `impl_confidence < 0.7`: 접근법 방향 불명확/발산 필요 → ideation; 리스크·트레이드오프 합의 필요 → discussion; 그 외 → PM 자율 판단 (ideation/discussion 호출 금지)
      - 모든 자율 처리 결과는 `req-impl-research.md`에 기록

      **실행 절차** (`AUTO_APPROVE=false`인 경우):
      1. **코드베이스 패턴 재점검** (Glob/Grep): spec에서 사용할 라이브러리·API의 기존 용례 탐색; 동일 목적의 기존 유틸·헬퍼·추상화 존재 여부 확인
      2. **구현 수준 WebSearch** (PM 판단 시 실행): `{라이브러리} {버전} best practices`, `{패턴} implementation guide`. 전략 수준 검색 금지 — 구현 방식에 한정.
      3. **결과 분류**: `ALIGNED`(표준 일치), `DEVIATION`(표준에서 벗어남), `DUPLICATE`(기존 구현 존재), `BETTER_ALTERNATIVE`(더 단순한 방법 발견)
      4. **처리**:
         - `ALIGNED`: 결과 저장 후 h-0 진행
         - `DEVIATION`/`BETTER_ALTERNATIVE`: AskUserQuestion으로 현재 spec 접근법 vs 발견된 표준/대안 나란히 제시 (장점/단점/적합한 상황 포함). "현재 방향 유지" 또는 "표준/대안으로 spec 수정" 선택.
         - `DUPLICATE` (CRITICAL): AskUserQuestion으로 기존 구현 위치·범위 vs 신규 구현 의도 제시. "기존 재사용으로 spec 수정" 또는 "새로 구현(이유 있음)" 선택.
      5. **결과 저장**: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/discussion/req-impl-research.md`
         ```yaml
         trigger: complex | new_library | post_ideation | low_confidence
         impl_confidence: 0.0~1.0  # AUTO_APPROVE=true 시만
         codebase_findings:
           - type: DUPLICATE | BETTER_ALTERNATIVE | NONE
             detail: "..."
         web_search:
           - query: "..."
             finding: "..."
         result: ALIGNED | DEVIATION | DUPLICATE | BETTER_ALTERNATIVE
         spec_changes: "변경 없음 | {변경 내용 요약}"
         ```
   1.7.5. **적대적 검토 silent review** (질문 생성 단계 직전):
      - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get agile.adversarial_review)`로 설정을 읽는다.
      - `agile.adversarial_review.enabled != true`이면 graceful skip 후 Step 1.8로 진행한다.
      - enabled perspective만 실행한다. 기본 enabled는 `edge`, `flow`, `integration`이며 `persona`, `nfr`은 설정이 true인 경우에만 실행한다.
      - 각 perspective마다 아래 CLI로 context 경로와 output schema 경로만 조회한다.
        ```bash
        python3 {PLUGIN_ROOT}/scripts/mst.py request review --req-path {path} --perspective {name} --json
        ```
      - 에이전트는 반드시 독립 컨텍스트로 호출한다. 허용 호출은 `Skill(skill:"mst:codex")` 또는 `Task(subagent_type:"general-purpose")`이다. 프롬프트에는 request 원문, plan 원문, spec 초안, DoD/JTBD 원문을 절대 포함하지 않는다.
        ```text
        역할: {perspective} 관점의 적대적 검토자.
        Read로 context_files 경로를 로드하고 output_schema에 맞게 findings JSON을 반환하시오.
        ```
      - findings는 round별 append 방식으로 `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/adversarial-review-findings.md`에 기록한다.
      - 수렴 조건은 `findings 배열이 비어있음 OR current_round >= max_rounds`이다. `max_rounds` 기본값은 3, `current_round` 초기값은 1이다.
      - `AUTO_MODE=true`: `parallel_in_auto_mode=true`이면 enabled perspective를 병렬 실행하고, false이면 순차 실행한다. `severity=critical` finding은 spec 작성 컨텍스트에 자동 반영하고 `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/auto-decisions.md`에 기록한다.
      - `AUTO_MODE=false`: 기본 실행은 `edge` + `flow` 2종을 순차 실행한다. critical severity finding만 사용자에게 `[적대적 검토 silent] N개 critical finding 감지` 형식으로 노출하고, 반영이 필요한 critical은 기존 질문 슬롯 안의 `AskUserQuestion` confirm에 통합한다. 별도 질문을 추가해 사용자에게 노출되는 질문 수를 절대 증가시키지 않는다.
      - critical이 아닌 severity는 사용자에게 노출하지 않고 내부 보강에만 사용한다. 질문 생성 prompt에는 `silent_review_findings` 추가 컨텍스트로 제공하되, 질문 수 한도와 기존 질문 생성 순서를 유지한다.
   1.8. **구현 세부 Q&A Pass** (Step 1g 완료 직후, Step h-0 이전):
      - `AUTO_APPROVE=true`면 이 단계 전체를 완전 skip하고 Step h-0으로 즉시 진행
      - `AUTO_APPROVE=false`면 아래 7개 카테고리를 **고정 순서로 순차 처리**한다:
        1) 에러/실패 처리 2) 엣지케이스 3) 데이터 변경 4) 호환성 5) 성능 6) 테스트 범위 7) 배포 전략
      - `--plan PLN-NNN`이 있는 경우: 각 카테고리마다 plan.md에서 대응 값을 먼저 탐색. 명확히 매핑되면 질문 생략 `"plan에서 확인됨"` 요약 출력. 없거나 불확실하면 `AskUserQuestion` 실행 (추정 금지).
      - `--plan` 없으면 7개 카테고리를 모두 `AskUserQuestion`으로 질문한다.
      - `AskUserQuestion`은 동시 1개만; 각 질문에 반드시 `"해당 없음"` 선택지 포함; 총 6개 이내 선택지.
      - **모호한 답변**: 카테고리별 최대 3회 재질문. 3회 내 명확한 답변 미확보 시 PM이 가장 안전한 선택으로 자동 결정 (결정 사유 내부 메모에 기록 후 다음 카테고리 진행).
      - 수집된 Q&A 결과는 spec.md §3 수락 조건(AC) 상세 및 §3.5 Constraints에 반드시 반영.
   1.9. **테스트 전략 게이트 (Test Strategy Gate)** (Step 1.8 완료 직후, Step h-0 이전):
      - **실행 조건**: `test_enforcement` 로드 (순위: `config get test_enforcement` → `templates/defaults/config.json` → 기본값: `enabled=true`, `backend_tdd=true`, `web_execution_test=true`, `exempt_patterns=["*.md","*.json","*.yml","*.yaml","*.txt","*.css"]`, `require_exemption_reason=true`).
        `enabled=true`이면 항상 실행; `enabled=false`이면 plan.md에 `## 테스트 전략` 섹션 존재 + `적용 여부: 적용`인 경우에만 실행.
      - **코드베이스 탐색 (Glob/Grep, MANDATORY)**: `package.json`에서 test runner 감지; `tsconfig.json`, `eslintrc*`, `prettier.config.*` 존재 여부; `playwright.config.*`/`cypress.config.*` 존재 여부; `test/`/`__tests__/` 디렉토리; 빌드 스크립트.
      - **7종 추천 로직** (탐색 결과 기반):
        | 태그 | 트리거 |
        |------|--------|
        | `[build-check]` | 빌드 명령 감지 |
        | `[lint-check]` | 린터/포맷터 설정 감지 |
        | `[unit-test]` | 테스트 러너 감지 |
        | `[integration]`/`[api-test]` | DB 연동 또는 API 엔드포인트 변경 신호 |
        | `[e2e-browser]` | playwright/cypress 설정 감지 |
        | `[visual]` | 고비용 테스트 정책 모두 충족 시만 |
        | `[performance]` | 고비용 테스트 정책 모두 충족 시만 |
      - **고비용 테스트 정책 (CRITICAL)**: Visual Regression/Performance는 ① 관련 도구 설치됨 ② 해당 테스트 유형의 대상임 ③ PM이 명확한 근거 1줄 이상 제시 — 모두 충족 시만 추천.
      - **사용자 확인**: `AUTO_APPROVE=false` → AskUserQuestion으로 추천 목록 확인/수정; `AUTO_APPROVE=true` → PM이 자율 확정.
      - **test_enforcement 강제 규칙 (MANDATORY)** (`enabled=true` 시):
        - 변경 파일이 `exempt_patterns`에 100% 매칭 → 테스트 면제 적용 + 사유 기록
        - 테스트 러너 미감지 → 테스트 면제 적용 + 사유 기록 (`"테스트 프레임워크 미존재"`)
        - 위 두 면제 조건 아니면 테스트 AC를 반드시 포함
        - `require_exemption_reason=true`이면 면제 사유 미기록 시 에러
      - **spec AC 반영 규칙**: 확정된 테스트 항목을 spec.md AC에 보조 태그로 부여 (`[automatable]`/`[manual]`/`[browser-test]` 뒤에 추가). 각 유형별 원칙은 해당 태그 AC에만 2~3줄 선별 주입 (전체 일괄 주입 금지).
        - `backend_tdd=true` + 백엔드 도메인: 핵심 테스트 AC에 `[tdd-required]` + `"테스트를 먼저 작성한 후 구현하세요 (TDD)"` (MANDATORY)
        - `web_execution_test=true` + 웹/프론트엔드: 최소 1개 AC에 `[e2e-browser]`/`[browser-test]` + `"실행 테스트를 작성하고 통과시킨 후 구현 완료로 판단하세요"` (MANDATORY)
      - **유형별 원칙 (하드코딩, MANDATORY)**:
        - `[build-check]`: "빌드 명령어 성공(exit 0) 확인. 빌드 오류 시 구현 실패로 간주."
        - `[lint-check]`: "린터/포맷터 규칙 위반 0건 확인. --fix 자동 수정 허용."
        - `[unit-test]`: "AAA 패턴(Arrange-Act-Assert) 준수. 각 테스트는 하나의 동작만 검증. 외부 의존성만 mock."
        - `[integration]`: "실제 DB/서비스 사용. 테스트 시딩 필수. 격리된 환경에서 실행."
        - `[e2e-browser]`: "Page Object 패턴 권장. 스크린샷 첨부. 안정적 selector 사용."
        - `[api-test]`: "Given-When-Then 구조. status + body + schema 검증."
        - `[visual]`: "베이스라인 이미지 비교. 캡처 조건(뷰포트, 지연) 명시."
        - `[performance]`: "워밍업/반복/임계값 명시. 회귀 감지 기준 정의."
      - 추천된 테스트 도구 미설치 시 graceful skip + 설치 명령어 안내. `enabled=true`에서 test runner 자체 미감지 시 `"테스트 프레임워크 미존재"` 면제 사유 반드시 기록. 워크플로우 차단 금지.
   h-0. **Stitch 트리거 감지** (config.stitch.enabled=true인 경우):
      - 명시적 디자인 요청("화면 디자인해줘", "Stitch로", "목업", "시안" 등):
        ⚠️ **`mcp__stitch__*` 도구를 직접 호출하는 것은 절대 금지.**
        반드시 `Skill(skill: "mst:stitch", args: "--req REQ-NNN {요청 내용}")` 스킬을 통해서만 호출합니다.
        → Stitch 완료 후 spec.md 작성 계속
      - 그 외(새 화면 추가/약한 신호): approve Phase 2.5에서 제안, 이 단계 skip
      - `ui_related` 플래그: 명시적 디자인 요청 또는 새 화면/약한 UI 신호 → `true`; 그 외 → `false`
   h-0.5. **Assigned Agent 기본값 보관**: spec.md 작성 직전, 가능하면 Step 0.5의 `request_bootstrap_config`에서 `workflow.default_agent`를 재사용한다. preload가 없으면 `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get workflow.default_agent auto_mode.request --json)`를 1회 재실행해 복구한다. `templates/spec.md`의 Decision Tree는 이 기본값의 override 조건으로만 동작. config 미참조 시 `claude-dev` 자동 선택은 금지. `config.resolved.json` 없으면 `templates/defaults/config.json`의 `agent_assignments`와 `workflow.default_agent`를 fallback으로 함께 Read한다.
   h-0.6. **Intent Context Load (MANDATORY)**:
      - `{PROJECT_ROOT}/.gran-maestro/request-context.md`를 반드시 Read한다. 파일이 없으면 아래 초기 템플릿으로 생성 후 즉시 Read한다 (비차단):
        ```markdown
        # Request Q&A 선호 패턴
        _마지막 갱신: 없음 (초기 상태)_
        _세션 수: 0_
        _schema_version: 1_

        > 아직 선호 패턴이 기록되지 않았습니다. 충분한 Q&A 세션 후 자동으로 채워집니다.

        ## 선호 패턴 (Preference Table)
        | id | domain | type | statement | weight | freq | last_seen | tags |
        |----|--------|------|-----------|--------|------|-----------|------|

        ## Prompt Hints
        (패턴 축적 후 자동 생성됩니다)
        ```
      - `request-context.md`에서 현재 요청과 관련된 패턴 최대 3개를 `request_preference_hints`로 추출한다.
      - 이후 모든 `AskUserQuestion`에서 과거 선호를 `description`에 명시적으로 인용한다 (권장 형식: `이전에 "{statement}"를 선호하셨습니다. 이번에도 동일하게 적용할까요?`). `freq` 숫자 직접 인용 금지.
      - 사용자가 인용 선호를 반박하면 `request_disputed_preferences`에 수집하고 Step 6의 요약 트리거 입력으로 전달한다.
      - `intent_fidelity.enabled` 확인: `config get intent_fidelity.enabled` → `templates/defaults/config.json` → 기본값 `true`. `false`이면 이 단계 전체 skip.
      - `--plan PLN-NNN` 제공 시:
        - plan.md에서 `## 요청 (Refined)` + `## Intent (JTBD)` + `## 인수 기준 초안`을 Read하여 `intent_context`로 보관한다.
        - `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.ids.json`을 Read하여 PAC preflight 수행 (비차단):
          - 파일 존재 시: `[{id,text,grade,tags?}]` 목록을 `pac_preflight_checklist`로 로드. `tags`에서 `TIER-A`/`TIER-B` 인식해 `pac_tier` 결정 (둘 다 없으면 `TIER-B` 기본).
          - 파일 미존재 시: warn 후 plan.md `## 인수 기준 초안`에서 임시 PAC 목록 추론 (비차단).
          - `pac_anchor_list`로 보관하고 이후 spec AC 작성 프롬프트 앞단에 고정 주입.
        - agile-origin objective trace가 있으면 `objective.ids.json` 및 plan의 `anchor_coverage_evidence`를 Read하여 `objective_anchor_list`로 보관한다. MUST objective anchor는 spec AC, `## 3.3 PAC Mapping`, 또는 `## 3.4 Epic DoD Mapping` 중 하나에 매핑되어야 하며 누락 ID는 MAJOR 이상 evidence로 남긴다.
        - docs 후보: plan.md `## 연관 컨텍스트` 표 및 본문 내 `docs/` 경로 수집.
      - `--plan` 미제공 시: `request.json.original_request`를 `intent_context`로 보관. docs 후보는 Step 1c 탐색 발견 `docs/` 파일 + 사용자 요청 명시 경로만 사용.
      - `docs_context` 구성: dedupe 후 존재하는 파일만 Read. 각 항목 `path`, `last_modified`, 핵심 요구사항 1~3줄 요약 추출.
      - 활성화 판정: `--plan` + intent 섹션 확보 또는 `docs_context` 1개 이상 → `intent_context_active=true`; 그 외 → `false`
   h. **Implementation Spec 작성** (`templates/spec.md` 템플릿 사용); `--plan` 없으면 `## 가정 사항` 섹션 포함
      > ⚠️ **spec.md 작성 원칙**: 포함 = AC(완료 기준), 범위 경계, 제약 조건, 패턴 힌트, 시작점 1~3개, 의존성. 제외 = 수정 파일 exhaustive 목록, 단계별 구현 절차, 에지케이스 사전 열거. 구체적인 구현 방법은 에이전트가 worktree를 직접 탐색하며 결정한다.
      - **UI 관련 DESIGN.md 자동 참조 (MANDATORY, graceful)**:
        - 조건: `ui_related=true` + `{PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md` 파일 존재
        - DESIGN.md Read → `design_system_context` 보관 → `context_manifest_files`에 dedupe 추가 (spec.md §0 또는 `## 디자인 시스템 참조` 섹션에 경로 기록)
        - outsource brief 생성 시 `{{IMPL_CONTEXT}}`에 `"DESIGN.md를 반드시 Read하여 디자인 규칙을 준수하세요."` 주입
        - DESIGN.md 없으면 전체 skip (graceful)
      - **AC 타입 확장 규칙 (MANDATORY)**: `[automatable]`, `[manual]`, `[browser-test]` 3가지 허용. `browser-test`는 실제 브라우저 상호작용 검증 필요 AC에 사용. plan 또는 대화에 `브라우저 테스트`/`Playwright`/`Claude in Chrome` 등 신호 있으면 `[browser-test]`로 분류. `web_execution_test=true` + 웹/프론트엔드 태스크이면 신호 약해도 최소 1개 포함. `[browser-test]` AC도 Given/When/Then/Test 형식 유지. `Test:`에는 실행 대상 URL/화면 + 핵심 동작 + 기대 결과 포함.
      - **[tdd-required] 보조 태그 규칙 (MANDATORY)**:
        - `pac_tier="TIER-A"`인 PAC에 매핑된 Spec AC 헤더에 `[tdd-required]` 자동 부여
        - `backend_tdd=true` + 백엔드 도메인 태스크이면 핵심 테스트 AC에도 자동 부여 (PAC tier 무관)
        - `TIER-B` PAC는 자동 부여 안 함; 기존 보조 태그와 독립 공존하며 기존 라우팅 변경 없음
      - **[impact-check] 보조 태그 변환 규칙 (MANDATORY)**: plan PAC에 `[IMPACT]` 태그 또는 `plan.ids.json` 항목 `tags`에 `"IMPACT"` 포함 시, 변환된 Spec AC 헤더에 `[impact-check]` 보조 태그를 반드시 포함. 복수 보조 태그 공존 시 `[impact-check]`가 최우선 라우팅. `[IMPACT]` PAC 없는 경우 graceful skip (하위 호환).
      - **Tier 에스컬레이션 규칙 (MANDATORY)**: 코드 복잡도/리스크 근거가 충분한 경우 `TIER-B` → `TIER-A` 상향 가능 (상향 시 `[tdd-required]` 추가 적용). `TIER-A` → `TIER-B` 하향 에스컬레이션은 명시적으로 금지.
      - **PAC 매핑 규칙 (`--plan` 제공 시, MANDATORY)**:
        - `pac_preflight_checklist`의 각 PAC를 spec AC에 최소 1회 매핑
        - spec 본문에 `## 3.3 PAC Mapping` 섹션: `PAC ID | Grade(MUST/SHOULD) | Mapped Spec AC IDs | Coverage`
        - MUST PAC의 `Mapped Spec AC IDs`는 비워서는 안 됨; plan에 없는 신규 spec AC는 `Coverage`를 `SPEC_ONLY`로 표시
      - **Objective anchor trace 규칙 (agile-origin, MANDATORY)**:
        - `objective_anchor_list`가 있으면 각 MUST objective anchor를 spec AC 또는 PAC/Epic DoD Mapping에 연결한다.
        - `anchor coverage` evidence(`anchor_total`, `anchor_mapped`, `anchor_missing_ids`)를 spec 작성 메모 또는 request evidence에 보존한다.
        - `anchor_missing_ids`가 비어있지 않으면 graceful fallback으로 닫지 않고 blocking/MAJOR failure evidence를 기록한다.
      - **`## §0 Context Manifest` 자동 채움 규칙 (MANDATORY)**:
        - `context_manifest_files`를 bullet 목록으로 삽입
        - `source_plan`이 있으면 `plan.md`, `plan.json`, `plan.ids.json`이 최종 목록에 포함되도록 보강한다.
        - objective details가 있으면 `context-transfer-contract.md` 같은 linked detail source를 dedupe 추가한다.
        - skill/template contract 작업이면 `skills/request/SKILL.md`, `skills/approve/SKILL.md`, `templates/impl-request.md`, `templates/spec.md`를 포함한다.
        - `objective_context.objective_md_path`가 있으면 dedupe 추가; 없으면 skip (graceful)
        - `--plan` 없는 경우에도 동일 규칙 적용 (Step 1c 탐색 + 요청 분석 기반)
        - `MST_SESSION_ID`와 active session worktree metadata가 있는 정상 경로에서는 session worktree를 effective project root로 관찰한 파일 경로를 우선 사용한다.
        - original checkout에서 호출된 경우에는 session worktree 재진입 또는 structured diagnostic 경계로 분류하고, legacy owner/session field를 effective root source로 사용하지 않는다.
        - 최종 목록에서 채울 수 없는 required context는 spec 요약 또는 생성 메모에 `missing_context`/`NO_*`/명시적 skip reason으로 남기고 조용히 생략하지 않는다.
        - 최종 §0 목록은 최소 1개 이상 파일 경로를 포함해야 한다
      - **`## 3.2 Intent Trace` 작성 규칙 (MANDATORY)**: `intent_context_active=true`일 때만 §3.2 채움. 각 AC마다 최소 1개 의도 근거 연결. 근거를 찾지 못하면 `[INTENT-GAP]` 표기. docs 근거 사용 시 `intent_snapshot`에 `doc_path`, `last_modified`, `spec_generated_at` 기록. `intent_context_active=false`면 §3.2 전체 skip.
      - **`## 3.4 Epic DoD Mapping` 작성 규칙 (조건부, MANDATORY)**: `objective_context` 존재 + `project_dod_items[]` 1개 이상일 때 생성한다. agile-origin objective anchor metadata가 있으면 §3.4를 skip하지 말고 objective trace evidence로 DoD/anchor → Spec AC 매핑을 남긴다. 표 형식: `DoD ID(or 항목) | DoD 설명 | Mapped Spec AC IDs | Coverage`. 매핑 가능한 AC 없으면 `[UNMAPPED]`/`Gap`. legacy/non-agile에서 `objective_context` 없거나 비어있으면 §3.4는 N/A 또는 skip 가능.
   h-0.7. **Regression Test 선행 태스크 생성** (Step h-1 이전, MANDATORY):
      - 트리거 조건(모두 충족 시 생성): 기존 파일/함수의 비즈니스 로직 변경 포함; 단순 boilerplate 변경만이 아님
      - 제외 조건: boilerplate-only 변경; 완전 신규 기능 (기존 코드 비즈니스 로직 변경 없음)
      - 생성 규칙:
        - 각 코드 수정 태스크 앞에 `"기존 기능 regression test 작성"` 성격의 선행 태스크 생성
        - 선행 태스크는 후행 코드 수정 태스크의 `blockedBy` 선행 조건으로 연결
        - 태스크 범위: **수정 대상 파일/함수 + 1단계 연관 모듈(static import/caller)** 로 한정
        - 테스트 방식: 새 테스트 작성 기본; 기존 테스트 있으면 병행 실행
      - Spec AC 보조 태그: 선행 태스크로 생성/변환되는 AC 헤더에 `[regression-test]` 보조 태그 포함. `[impact-check]` 우선 라우팅은 유지하고 `[regression-test]`는 Pass A의 회귀 테스트 실행 대상으로 보존.
      - 역할 구분 (PLN-291 하위호환, MANDATORY): `[impact-check]` = 수정 영향으로 **다른 영역**이 깨지지 않았는지. `[regression-test]` = **수정 대상 자체**의 기존 동작이 유지되는지. 동일 파일 대상이라도 검증 목적이 다르므로 중복이 아니다.

   h-1. **다중 태스크 분해 처리** (PM 자율 판단 — plan 유무와 무관):
      - plan.md의 `## 태스크 분해` 섹션이 있더라도 무시한다. 코드베이스 탐색 결과를 바탕으로 PM이 독자적으로 결정한다.
      - pm-conductor.md Step 6.6 판단 따름; 2단계 이상 결정 시 동일 절차

      **태스크 분해 기준 (우선순위 순)**:

      - **순서 의존성 기준 (0차, 최우선)**: 선행 결과물 없이는 후행 작업을 시작할 수 없는 경우 → 직렬 태스크로 분리. `blockedBy`/`blocks`로 순서 명시. 단순 "나중에 하면 좋겠다" 수준은 대상이 아님.
      - **중간 검증 가능성 기준 (0.5차)**: 중간 지점에서 독립 검증 가능한 경계 → 분리. ① "절반 완료 상태에서 독립 검증 가능?" ② "T01만 완료해도 코드베이스가 망가지지 않는가?" 둘 다 YES면 분리. 중간 상태가 단독 검증 불가이면 하나로 묶기. 파일 수·라인 수는 기준이 아님.
      - **기능 책임 단위 분리 기준 (1차)**: 동일 태스크에 서로 다른 비즈니스 기능 혼재 → 기능 단위로 분리. 파일 타입 혼재(`.ts` + `.md`)는 분리의 필요충분조건이 아님.
      - **레이어 분리 기준 (2차)**: 동일 기능 단위라도 프론트엔드(.tsx/.jsx/UI)와 백엔드(API/DB/서버) 각각 독립 커밋/테스트 단위가 될 만큼 충분하면 → 레이어별 2개 태스크. `blockedBy` 설정: 백엔드 API 완료 후 연동 필요하면 `blockedBy: [백엔드T]`, UI 스타일만 독립 개발 가능하면 병렬 허용.

      **스텝 0.5 (선행): 책임 겹침 방지 검증**: 분해된 각 태스크의 기능 책임을 한 줄씩 열거. 완전 동일이면 병합, 선행 관계이면 `blockedBy`로 직렬화. 겹침 없이 검증 통과 후에만 스텝 0으로 진행.

      **스텝 0 (선행): 의존성 및 배정 확정**: 모든 태스크 ID, `blockedBy`/`blocks`, 에이전트 배정을 단일 thinking에서 확정 (이후 Write 또는 서브에이전트 어느 경로든 불변 입력으로 사용).

      **스텝 1 (분기): 독립 태스크 수 판단**
      - 독립 태스크(`blocks`/`blockedBy` 없는 것) 수 계산:
        - 독립 태스크 < 2개: 기존 순차 Write 유지
        - 독립 태스크 2개 이상: **Phase A 필수 실행**
          - [Phase A — MUST] Write 동시 호출: 단일 응답 내 N개 Write 동시 호출 (각 spec.md에 스텝 0 의존성 테이블 그대로 기입)
          - [Phase B] 서브에이전트 병렬 (아래 사유가 명시된 경우에만 허용): reasoning 복잡도 높고 태스크별 독립 코드베이스 탐색 필요 시 → `Task(subagent_type: "general-purpose", run_in_background: true)` N개 병렬 dispatch. 각 서브에이전트에 의존성 테이블 + 에이전트 배정 결과를 읽기 전용으로 주입 (프롬프트에 포함): 서브에이전트는 §7, §8에 그대로 기입, 의존성/배정 결정 금지. Phase B로 spec 작성 시 별개로 PM이 prereview 에이전트 dispatch. PM 재량만으로 Phase A 미실행은 금지.

      **h-1.5 테스트 태스크 자동 생성** (스텝 1 직후, MANDATORY):
      - 모든 REQ에서 항상 1개 생성 (단일 구현 태스크 REQ 포함). 태스크 리스트의 마지막에 배치, ID는 마지막 구현 태스크 다음 순번.
      - 의존성 규칙 (양방향, MANDATORY): 테스트 태스크 `§5 blockedBy`에 모든 구현 태스크 ID 기입. 각 구현 태스크 `§5 blocks`에 테스트 태스크 ID 추가 (dedupe).
      - spec 작성 규칙: 반드시 `templates/test-spec.md` 템플릿 사용. `§2 테스트 범위`에 통합 검증+증분 테스트+회귀 테스트 명시. `§3 통합 AC`는 구현 태스크 핵심 AC를 Given/When/Then+Test 형식으로 종합 재구성. `§4 회귀 테스트 항목` 최소 1개 이상.
      - `request.json.tasks[]`에 테스트 태스크도 일반 태스크와 동일하게 메타데이터 기록.

      **스텝 2 (검증): 양방향 의존성 검증 훅** (모든 spec.md Write 완료 직후 실행)
      - 각 spec의 `blocks` 목록을 읽어 대상 태스크 spec의 `blockedBy` 포함 여부 확인; 역방향도 동일하게 검증.
      - 불일치 발견 시 오류 메시지 출력 + `request.json` tasks 배열 업데이트 차단 (spec.md는 유지, PM이 수동 수정 후 재시도).
      - `h-1.5`에서 추가한 구현 태스크 `blocks` ↔ 테스트 태스크 `blockedBy` 관계도 동일 규칙으로 검증.
      - 부분 실패 (k/N spec 성공) 시: 실패 태스크 ID 목록 표시 + 해당 태스크 spec.md만 재작성 안내 (성공 태스크 유지).

   i. 태스크 디렉토리 일괄 생성: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/tasks/01..N` (N개 동시 생성)
   j. **spec.md 병렬 Write**: (의존성 고정 후) 단일 응답 내 N개 Write 동시 호출로 저장
   h-2. **Spec Pre-review Pass** (모든 spec.md Write 완료 + 검증 훅 통과 후 실행)

      **실행 조건** (순서대로): `--prereview` → 강제 실행; `--auto`/`-a` 또는 `AUTO_APPROVE=true` → skip; `--no-prereview` → skip; `workflow.spec_prereview=false` → skip; 모두 통과 시 실행.

      **에스컬레이션 모드**: `AUTO_APPROVE=true`면 `"pm-self"`, 그 외는 `"user"`

      **config 읽기**: `max_iterations` = `config.workflow.spec_prereview_max_iterations` (기본 3); `escalation_trigger` = `config.workflow.spec_prereview_escalation_trigger` (기본 `"major"`); `minor_escalation_threshold` = `config.workflow.spec_prereview_minor_escalation_threshold` (기본 null — 비활성); `current_iteration = 1`

      **[PREREVIEW LOOP]**

      prereview-prompt.md N개 동시 Write: 각 `tasks/NN/prereview-prompt.md`를 `templates/spec-prereview-prompt.md` + 변수 치환으로 생성

      에이전트 병렬 dispatch: claude-dev 2개+ 태스크 → `Task(run_in_background: true)` 직접 호출; codex-dev/gemini-dev → `Skill(skill: "mst:{agent}", run_in_background: true)`

      결과 수집: 태스크별 결과를 CRITICAL/MAJOR/MINOR로 분류. `NO_ISSUES` → 이슈 없음. 실패 응답 → "[Pre-review skip]" 후 건너뜀.

      **escalate 판단**: `"critical"` → CRITICAL 1개 이상; `"major"` → CRITICAL/MAJOR 1개 이상; `"minor"` → 이슈 1개 이상

      **[escalate = true]**:
      - **user 모드**: AskUserQuestion으로 이슈 목록(CRITICAL/MAJOR 우선) 제시 + "반영하고 재리뷰" / "반영 없이 진행". "반영하고 재리뷰" 선택 시: PM이 spec.md에 Edit 반영 후 `current_iteration < max_iterations` → 루프 재진입; `>= max_iterations` → 루프 종료.
      - **pm-self 모드**: PM이 자체 판단으로 spec.md에 Edit 반영. `current_iteration < max_iterations` → 루프 재진입; `>= max_iterations` → 루프 종료.

      **[escalate = false]** (escalation_trigger 미만 이슈만 존재 또는 전체 NO_ISSUES):

      **MINOR 임계값 에스컬레이션 체크** (`minor_escalation_threshold != null`인 경우):
      - threshold <= 0이면 1로 치환. MINOR_COUNT 합산.
      - MINOR_COUNT >= minor_escalation_threshold → "[MINOR 임계값 초과]" 안내:
        - **user 모드**: AskUserQuestion으로 MINOR 이슈 목록 + "반영하고 재리뷰" / "반영 없이 진행". 재리뷰 선택 시 PM이 Edit 반영 후 루프 재진입 (max_iterations 확인).
        - **pm-self 모드**: PM이 자체 반영 후 루프 재진입 (max_iterations 확인).
      - MINOR_COUNT < threshold 또는 threshold==null:
        - **user 모드**: MINOR 이슈 목록 AskUserQuestion + "반영하고 재리뷰" / "반영 없이 진행".
        - **pm-self 모드**: PM이 자체 반영 후 루프 종료.
      - 전체 NO_ISSUES: 수정 없이 루프 종료.

      **[PREREVIEW LOOP 종료]**

      이슈가 1개 이상 존재했던 경우 spec.md 끝에 `## 구현 전 검토 (Pre-review Q&A)` 테이블 추가 (최종 iteration의 이슈 및 반영 결과 기준).

   k. `request.json`의 `tasks` 배열에 태스크 메타데이터 추가 (spec.md 저장 직후): `id`, `title`, `status: "pending"`, `agent`(필수 — 누락 금지), `spec: "tasks/01/spec.md"`, `covers_ac: ["AC-001", ...]`
   h-exit. **A Gate (PAC Coverage, blocking)**:
      - 실행 조건: `--plan PLN-NNN` 제공 && `pac_trace.enabled == true`
      - 판정: MUST PAC 중 `Mapped Spec AC IDs`가 0건인 항목이 1개라도 있으면 **blocking**. SHOULD PAC 누락은 warning (blocking 아님).
      - blocking 동작: ① request emit 중단 ② `pac-missing-report.md` 생성 ③ 누락 MUST PAC ID 목록 + 보완 가이드 출력 ④ MUST 커버리지 100% 달성 후 gate 해제
      - 역방향: spec에만 있고 plan PAC에 매핑 안 된 AC(`SPEC_ONLY`)는 `scope creep warning` 기록 (`pac_trace.scope_creep_warning=true` 시).
   l. (A Gate 통과 후) `request.json`의 `status`를 `"spec_ready"`로 업데이트
5. ⚠️ **spec.md 작성 완료 확인** — spec.md 미존재 시 스킬 종료 금지
6. 스펙 요약 표시 + 승인 안내 (두 가지 명령을 모두 명시):
   - 일반: `/mst:approve REQ-NNN`
   - 자율 모드: `/mst:approve -a REQ-NNN` (이후 단계를 중간 승인 없이 자동 실행)
   - **[필수] 할당 에이전트 보고**: `[할당 예정] REQ-NNN → {agent명} ({provider})` 형식으로 명시 (다중 REQ 시 개별 명시)
   - ⚠️ `/mst:approve` 수신 전까지: 코드 수정·파일 편집·커밋 전면 금지
   - **Q&A 선호 요약 백그라운드 트리거 (MANDATORY, 비차단)**:
     - spec.md 저장 완료 직후 백그라운드 agent 1회 호출 (`run_in_background: true`):
       - `{PROJECT_ROOT}/.gran-maestro/qa-raw/REQ-NNN.jsonl`
       - `{PROJECT_ROOT}/.gran-maestro/request-context.md`
     - 입력 파일 없으면 warn 후 skip (차단 금지)
     - 갱신 규칙: ① Preference Table을 Source of Truth로 유지 ② 강한 표현(절대/반드시/싫어/금지) 감지 시 `weight=HIGH` 자동 부여 ③ `request_disputed_preferences`에 `[DISPUTED]` 태그 반영 ④ Prompt Hints는 Table 기반 파생으로 재생성, 빈도 숫자 직접 인용 금지 ⑤ 200줄 초과 시 150줄로 압축 (`[DISPUTED]` 우선 제거, `HIGH` 보호)
     - `Task(subagent_type: "general-purpose", run_in_background: true, prompt: "{REQ-NNN QA 요약 프롬프트}")`
     - 실패 시 warn만 출력하고 승인 안내 흐름을 계속 진행한다
   - `auto_approve=true` 상태에서는 승인 단계를 스킵하고 `Skill(skill: "mst:approve", args: "-a REQ-NNN")`로 자동 진입한다 (`-a` 생략 금지)
   - **세션 중 자율 모드 전환**: spec 요약 표시 후 대기 중 사용자가 "auto로", "자율 모드로", "-a로" 등을 입력하면 `/mst:approve -a REQ-NNN`으로 자동 진입한다

## 옵션

- `--auto` / `-a`: 스펙 자동 승인 모드 (사용자 승인 단계 스킵, `auto_approve: true`)
  - 요청 앞(`/mst:request --auto "요청"`) 또는 뒤(`/mst:request "요청" --auto`) 모두 허용
  - `--auto`/`-a` 또는 `config.auto_mode.request=true`(`AUTO_APPROVE=true`)에서는 Spec Pre-review Pass(h-2)를 skip한다
- `--resume REQ-NNN`: 기존 REQ 재개 모드 (신규 REQ 생성 금지)
  - approve DAG 연쇄 호출 계약: `Skill(skill: "mst:request", args: "--plan PLN-NNN --resume REQ-NNN -a")`
  - 하위 호환: `--resume` 없이 `REQ-NNN` 단독 인자도 재개로 해석
- `--prereview`: config 설정 무관하게 Pre-review Pass 강제 실행
- `--no-prereview`: config 설정 무관하게 Pre-review Pass skip

## 예시

```
/mst:request "JWT 기반 사용자 인증 기능을 추가해줘"
/mst:request --auto "로그인 버튼 색상을 파란색으로 변경"
/mst:request --plan PLN-233 --resume REQ-352 -a
```

## 문제 해결

- `.gran-maestro/` 생성 실패 → git 저장소 여부 및 쓰기 권한 확인
- `mode.json` 잠금 충돌 → `mode.json.lock` 수동 삭제
