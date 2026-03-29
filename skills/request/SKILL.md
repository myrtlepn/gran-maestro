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
- `{PROJECT_ROOT}/.gran-maestro/` 디렉토리 생성, `.gitignore`에 `.gran-maestro/` 등록 (미존재 시)
- 플러그인 루트 확인, `config.json` / `agents.json` 없으면 `templates/defaults/`에서 복사
- `{PROJECT_ROOT}/.gran-maestro/mode.json` 확인: `active: false`이거나 파일 없음 → 아래 내용으로 생성/업데이트:

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

## Anti-Rationalization Checklist

- 합리화 패턴: "plan에서 이미 분석했으니 코드베이스 탐색을 축약해도 된다." | 확인 증거: spec `§0 Context Manifest`에 실제 탐색 근거 파일 경로를 남긴다.
- 합리화 패턴: "단순 요청이니 AC를 짧게 쓰고 Given/When/Then/Test를 생략한다." | 확인 증거: 각 AC를 Given/When/Then/Test 형식으로 작성하고 AC ID를 `request.json.tasks[].covers_ac`에 매핑한다.
- 합리화 패턴: "속도를 위해 승인/사전검토 분기를 임의로 건너뛴다." | 확인 증거: 실행 로그에 `AUTO_APPROVE` 결정 근거(CLI/config)와 적용 경로를 출력한다.

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

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

### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 관련 spec 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**:
   - `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`에서 `reference.auto_search` 확인.
   - `reference.auto_search == true`일 때만 자동 WebSearch 허용.
   - 설정 미존재 시 기본값: `cache_ttl_days=7`, `cutoff_threshold_months=1`, `max_searches_per_step=3`.
1. **키워드 감지**:
   - 요청 원문, plan 컨텍스트, Step 1c 탐색 결과, 접근법 후보 텍스트에서 `library/framework/api/sdk/protocol/version/dependency` 계열(한국어 동의어 포함) 키워드를 감지.
2. **3단계 신선도 체크**:
   - (a) `.gran-maestro/references/` 캐시 존재 확인: `python3 {PLUGIN_ROOT}/scripts/mst.py reference search --keyword "{keyword}" --json`
   - (b) TTL 체크: `searched_at + cache_ttl_days` 경과 여부로 `fresh/stale` 판정
   - (c) cutoff 괴리 체크: 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired` 판정
3. **WebSearch 트리거**:
   - 캐시 없음 또는 `stale/expired`일 때만 검색.
   - `reference.auto_search == true`일 때만 실행, Step당 최대 `max_searches_per_step` 유지.
4. **REF 저장**:
   - 검색 결과를 `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{핵심 요약}"`로 저장.
5. **프롬프트 주입**:
   - 이후 spec 작성 프롬프트와 outsource brief 컨텍스트에 `[REFERENCE_CONTEXT]`를 주입한다.
   - 형식:
     ```text
     [REFERENCE_CONTEXT]
     current_date: {YYYY-MM-DD}
     model_cutoff: {cutoff_date_or_unknown}
     references:
     - REF-001 (fresh|stale|expired) {topic} | {url}
     [/REFERENCE_CONTEXT]
     ```
   - 참조가 없으면 `references: none`으로 명시한다.

### Step 0: 아카이브 체크 (자동)

`archive.auto_archive_on_create`가 true이면:
- **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request count --active` → 초과 시 `python3 {PLUGIN_ROOT}/scripts/mst.py archive run --max {max_active_sessions}`
- **Fallback**: REQ-* 디렉토리 수 확인 → 초과분 tar.gz 압축 후 원본 삭제

상세 아카이브 로직은 `/mst:archive` 스킬의 "자동 아카이브 프로토콜" 참조.

### Step 0.5: 에이전트 기본값 취득 (MANDATORY)

> ⚠️ 이 단계는 건너뛸 수 없음: spec.md Assigned Agent 결정 전 반드시 실행.
> 이 단계 없이 spec.md 작성 금지.

Read(`{PROJECT_ROOT}/.gran-maestro/config.resolved.json`) → `workflow.default_agent` 추출 → DEFAULT_AGENT 변수 보관.
파일이 없으면 `templates/defaults/config.json`에서 `workflow.default_agent`와 `agent_assignments`를 Read하여 DEFAULT_AGENT 및 도메인 추론 기준으로 사용한다.

이후 모든 spec.md의 Assigned Agent 필드는 반드시
`[config: {DEFAULT_AGENT}] → ...` 형식으로 DEFAULT_AGENT를 명시해야 한다.
DEFAULT_AGENT 미확인 상태의 Assigned Agent 결정은 에러로 처리한다.
`agent_assignments` 읽기 시 `_`로 시작하는 키(`_comment` 등)는 에이전트명으로 간주하지 않는다.
config.resolved.json이 없으면 `templates/defaults/config.json`의 `agent_assignments`를 fallback으로 Read한다.

#### auto_mode config 읽기

1. `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`에서 `config.auto_mode.request` 값을 확인한다.
2. CLI 인자에서 `--auto` / `-a`가 감지되지 않았고 `config.auto_mode.request == true`이면:
   - `AUTO_APPROVE=true`로 설정 (`request.json.auto_approve=true`)
   - `"[config] auto_mode.request=true — 자동 승인 모드 활성화"` 메시지를 표시한다.
3. CLI 인자에 `--auto` / `-a`가 있으면 config 값은 무시한다 (CLI 우선).

### Step 1: 요청 생성/재개

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

1. 재개 대상 감지:
   - CLI 인자에 `--resume REQ-NNN`이 있으면 `RESUME_REQ_ID=REQ-NNN`으로 설정
   - `--resume`이 없어도, 자유 인자에 단일 `REQ-NNN` 패턴이 있으면 하위 호환으로 `RESUME_REQ_ID=REQ-NNN`으로 해석
   - `--resume` 값과 자유 인자 REQ-ID가 동시에 존재하고 서로 다르면 오류로 중단
2. `RESUME_REQ_ID`가 설정된 경우(기존 REQ 재개 분기):
   - `{PROJECT_ROOT}/.gran-maestro/requests/{RESUME_REQ_ID}/request.json` Read
   - 파일이 없으면 오류 출력 후 중단 (`신규 REQ 생성 금지`)
   - `status` 검증:
     - 허용: `pending_dependency`, `phase1_analysis`, `spec_ready`
     - 거부: `done`, `completed`, `accepted`, `cancelled` (이미 완료/종료된 REQ 재개 금지)
   - `pending_dependency` 상태면 `dependencies.blockedBy`를 확인:
     - 비어있지 않으면 아직 의존성 대기 상태이므로 중단
     - 비어있으면 `status`를 `phase1_analysis`로 전이 후 진행
   - `--plan PLN-NNN`이 함께 제공된 경우 `source_plan` 정합성 확인:
     - 기존 `source_plan`이 없으면 `source_plan: "PLN-NNN"`으로 보강
     - 기존 `source_plan`이 다른 값이면 오류로 중단
   - `request.json.auto_approve`는 현재 실행 컨텍스트의 `AUTO_APPROVE` 값으로 동기화
   - 이 분기에서는 **REQ 채번/디렉토리 생성/신규 request.json 생성을 수행하지 않는다**
3. `RESUME_REQ_ID`가 없는 경우(신규 REQ 생성 분기):
   - 새 요청 ID 채번 (REQ-NNN):
     - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next` → 출력 ID 사용 (counter.json 자동 업데이트)
     - **Fallback (counter.json 기반)**:
     - `{PROJECT_ROOT}/.gran-maestro/requests/counter.json` 파일 Read
     - **파일 존재 시**: `next_id = last_id + 1`
     - **파일 미존재 시** (최초 또는 복구):
       a. `requests/`, `requests/completed/`, `archive/requests-*` tar.gz 파일명에서 최대 번호 결정
       b. `counter.json` 생성: `{ "last_id": {max_number} }`, `next_id = last_id + 1`
     - `counter.json` 업데이트: `{ "last_id": {next_id} }`
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
   - `request.json`의 `auto_approve` 값은 `AUTO_APPROVE` 변수로 결정:
     - CLI `--auto` / `-a` 플래그 인자 내 어느 위치든 감지 시 `AUTO_APPROVE=true` (최우선)
     - CLI 플래그가 없고 `config.auto_mode.request=true`이면 `AUTO_APPROVE=true`
     - 그 외 `AUTO_APPROVE=false`
   - `request.json`의 `source_plan` 필드는 **항상 기록**한다:
     - `null`: plan 없이 생성된 신규 REQ
     - `"PLN-NNN"`: plan 기반 생성 REQ
     - (레거시) 필드 부재: 구버전 데이터로 간주
   - `request.json`의 `dag_auto_chain` 필드는 **선택 기록**한다:
     - `false`(기본): 현재 REQ만 실행 (기존 동작)
     - `true`: 같은 plan의 연결된 REQ를 DAG 순서로 자동 연쇄 실행
     - (레거시) 필드 부재: `false`로 간주
4. PM Conductor 역할로 Phase 1 분석 수행 (`agents/pm-conductor.md`의 `<phase1_protocol>` 준수):
   a. 요청 파싱 및 복잡도 분류 (simple | standard | complex)
   b. Simple → 단독 분석 / Standard·Complex → Analysis Squad 팀 소환
   c. 코드베이스 탐색 (`config.phase1_exploration.roles` 기반 병렬):
      > ⚠️ **탐색 목적**: 구현 절차를 미리 결정하기 위함이 아닙니다.
      > 아래 세 가지에만 집중합니다:
      > ① 기존 패턴·컨벤션 파악 (에이전트가 따라야 할 것)
      > ② 핵심 진입점 식별 (에이전트가 탐색 시작할 1~3개 파일/디렉토리)
      > ③ 충돌 가능성 감지 (변경 시 영향받는 기존 코드)
      > 구체적인 구현 방법은 에이전트가 worktree에서 직접 판단합니다.

      config 읽기: `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`의 `phase1_exploration.roles` 참조
      각 role의 모델 결정: `phase1_exploration.roles.{role}.tier` → `providers[agent][tier]`로 resolve (tier 미지정 시 `providers[agent].default_tier` 사용)
      ① `symbol_tracing` role agent [background dispatch] — enabled=true인 경우, 정밀 심볼 추적
      ② `broad_scan` role agent [background dispatch] — enabled=true인 경우, 광역 탐색 (①과 동일 응답에서 dispatch)
         enabled=false인 role은 dispatch 생략
      ③ Claude 직접 탐색 [즉시 시작] — ①② dispatch 직후 Read/Glob/Grep 자율 실행
         (탐색 범위는 Claude 자율 판단, 중복 허용, 별도 지침 없음)
      수신된 결과(enabled role들)를 Claude 직접 탐색 컨텍스트와 함께 종합
      총 소요 = max(enabled_roles_time, claude_direct_time) — 추가 지연 없음
      반드시 `Skill(skill: "mst:codex/gemini", ...)` 도구로 호출 — MCP 직접 호출 금지
      role agent 기본값: symbol_tracing=codex, broad_scan=gemini
   c-ref. **Reference Lookup 실행 (Step 1c 완료 직후, Step h 이전, MANDATORY)**:
      - Step 1c 탐색 산출물(핵심 파일/패턴/충돌 가능성) + 요청 원문 + plan 컨텍스트를 입력으로 `Reference Lookup Protocol`을 실행한다.
      - `reference.auto_search != true`이면 자동 WebSearch 없이 기존 REF 캐시 조회만 수행한다.
      - 생성된 `[REFERENCE_CONTEXT]`를 `reference_context_block` 변수로 보관하고, Step h spec 작성 프롬프트에 반드시 주입한다.
      - spec 본문에 검색 결과 원문을 장문 복사하지 않고, REF-ID/주제/신선도 중심으로 요약 반영한다.
   c-arch. **아키텍처 논의 게이트 (Step 1d-arch)**:
      - 실행 시점: Step 1c 탐색 완료 직후 (Step 1e 이전)
      - PM은 탐색 결과를 바탕으로 트리거 조건 A·B·C를 점검:
        - A. 의존 fan-out이 넓어져 다수 모듈에 연쇄 영향이 예상되는가?
        - B. 인터페이스 계약(API/함수 시그니처/이벤트 계약) 변경이 필요한가?
        - C. 데이터 흐름의 분기점(입력/출력 경로, 상태 전이 경계) 변경이 있는가?
      - PM 확신도(`pm_arch_confidence`, 0.0~1.0)를 산정하고 `workflow.arch_gate_threshold`와 비교해 게이트 개폐를 결정:
      - pm_arch_confidence 산정 기준 (rubric):
        - 0.0~0.3: 변경 범위 명확, 단일 모듈 한정, 기존 패턴 단순 적용 가능
        - 0.4~0.6: 일부 모듈 의존성 변경 예상되나 영향 범위 파악 가능
        - 0.7~1.0: 다수 모듈 연쇄 영향, 아키텍처 방향 불명확, 설계 리스크 존재
      - 트리거-게이트 결정 관계:
        - Gate Open 조건: A/B/C 중 1개 이상 충족 AND `pm_arch_confidence >= arch_gate_threshold`
        - Gate Close 조건: A/B/C 모두 미충족 (`pm_arch_confidence` 무관) 또는 `pm_arch_confidence < arch_gate_threshold`
      - `arch_gate_threshold` 읽기 순서:
        1. `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`의 `workflow.arch_gate_threshold`
        2. fallback: `templates/defaults/config.json`의 `workflow.arch_gate_threshold`
        3. 최종 fallback: `0.7`
      - `--plan` bypass 조건 (plan.md 선로드 필요):
        - `--plan PLN-NNN`이 제공된 경우, plan.md가 아직 Read되지 않았다면 여기서 먼저 Read
        - Read 후 plan.md에 아키텍처 방향이 이미 결정된 경우
          (예: `## 아키텍처 결정` 섹션, 기술스택 확정, 접근법 명시)
          → 게이트 실행 없이 skip. `req-arch-decision.md`에 `gate: skip`, `reason: "plan 참조"` 저장.
        - `--plan` 미제공 시 bypass 없이 게이트 정상 실행
      - AUTO_APPROVE=false + Gate Open:
        - `AskUserQuestion`으로 방향 선택 요청 (기본 선택지 2개 + 보조 선택지 3종):
          1. "제안 방향으로 진행"
          2. "방향을 바꿔서 직접 입력"
          3. (보조, PM 판단 시 포함) `ideation` 실행
          4. (보조, PM 판단 시 포함) `discussion` 실행
          5. (보조, PM 판단 시 포함) `explore` 재실행
      - AUTO_APPROVE=true + Gate Open:
        - `AskUserQuestion` 없이 PM이 자율 결정:
          - 방향이 미확정/발산 필요 → `Skill(skill: "mst:ideation", args: "{주제} --from-request")`
          - 방향은 있으나 리스크·합의가 복잡 → `Skill(skill: "mst:discussion", args: "{주제} --from-request")`
          - 두 조건 동시 충족 → `discussion` 우선
          - 두 조건 모두 미충족 → `ideation` 기본 (방향 탐색 우선)
      - Gate Open이든 Close든, 게이트 판단 결과를 `REQ-NNN/discussion/req-arch-decision.md`에 저장한다.
        ```yaml
        gate: open | close | skip
        reason: "plan 참조, gate skip" | "트리거 미충족" | "confidence 충분" | "게이트 열림"
        confidence: 0.75
        threshold: 0.7
        triggers:
          A: true | false
          B: true | false
          C: true | false
        result: ideation | discussion | none
        arch_direction: "방향 요약 (gate open 시만)"
        ```
      - Gate Open 후 방향 확정 시에만 spec.md에 `## 아키텍처 영향도 검토` 섹션을 삽입한다. Gate Close 또는 skip 시 미삽입.
   d-1. `--from-debug DBG-NNN` 제공 여부 처리:
      - `debug/DBG-NNN/debug-report.md` Read (미존재 시 경고 후 플래그 무시)
      - `debug_context` 메모리 보관: `linked_debug_id`, `root_cause`, `fix_suggestions`, `affected_files`
      - `request.json`에 `"linked_debug": "DBG-NNN"` 필드 추가
      - `spec.md` 작성 시 `## 디버그 연계` 섹션 자동 삽입 (참조 세션/근본 원인/수정 제안/영향 파일)
      - `--from-debug`와 `--plan` 동시 시: `--plan` 우선, debug_context는 보조 유지
   d-0. **active plan resolver** (`--plan` 미지정 시, Step d 직전):
      - 실행 조건: CLI 인자와 자연어 본문에서 `PLN-NNN`이 감지되지 않은 경우
      - `plans/*/plan.json`을 스캔해 `status == "active"`인 plan만 후보로 수집한다.
      - 후보는 `updated_at` 내림차순으로 정렬한다 (동률 시 ID 역순).
      - 후보 0건: resolver skip, `source_plan: null` 유지, 일반 request 플로우 진행
      - 후보 1건:
        - 최신 1건을 자동 제안: `[제안] 활성 plan {PLN-NNN} ({title})`
        - `AUTO_APPROVE=false`: `AskUserQuestion`으로 확인
          - **"{PLN-NNN}으로 진행"**: `resolved_plan_id = "PLN-NNN"`
          - **"plan 없이 진행"**: resolver 종료 (`source_plan: null` 유지)
        - `AUTO_APPROVE=true`: `resolved_plan_id = "PLN-NNN"` 자동 채택
      - 후보 2건 이상:
        - `AUTO_APPROVE=false`: `AskUserQuestion`으로 후보 선택 (최신순) + "plan 없이 진행"
          - **"{PLN-NNN}으로 진행"**: 선택된 `PLN-NNN`을 `resolved_plan_id`로 설정
          - **"plan 없이 진행"**: resolver 종료 (`source_plan: null` 유지)
        - `AUTO_APPROVE=true`: 최신 1건 자동 채택, 해당 `PLN-NNN`을 `resolved_plan_id`로 설정, 나머지는 로그에 후보로 기록
      - `resolved_plan_id`가 설정되면 Step d에서 `--plan PLN-NNN`과 동일하게 처리한다.
   d. `--plan` 제공 여부 처리:
      - `--plan PLN-NNN` 또는 자연어 `PLN-NNN` 또는 `resolved_plan_id` 감지 시 `plans/PLN-NNN/plan.json` + `plan.md` Read
      - plan Read 성공 시: `request.json`에 `source_plan: "PLN-NNN"` 기록; `plan.json`의 `linked_requests`에 REQ-NNN 추가, `status` `active` → `in_progress`
      - plan.md 결정사항·범위·제약을 Phase 1 인풋으로 사용
      - **plan type 전략 감지 (MANDATORY, plan.json Read 직후)**:
        - `plan_type = plan.json.type` (`type` 필드 미존재 시 `"code"`)
        - `type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)` 시도
        - `plan_strategy = type_strategies[plan_type] || type_strategies["code"]`
        - `type-strategies.json` Read 실패/파싱 실패/키 누락 시 `plan_strategy = {"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`로 fallback한다.
        - `plan_strategy.template == "templates/doc-request.md"`:
          - `DOC_SPEC_MODE=true` 설정
          - 즉시 `§ Doc Spec Flow` 섹션 규칙을 적용한다.
        - 그 외:
          - `DOC_SPEC_MODE=false` 설정
          - 기존 코드 개발 경로(Step e~h)를 변경 없이 그대로 유지한다.
      - **§0 Context Manifest 후보 수집 (MANDATORY)**:
        - 1차 소스: plan.md의 범위 섹션(`## 범위` 또는 `## 2. 범위`)에서 `시작점 힌트` 파일 목록을 추출하여 `context_manifest_files` 변수에 저장
        - 1차 소스가 비어있으면 fallback: Step 1c 탐색 결과의 핵심 진입 파일 + 요청 분석 결과에서 1~3개 파일 경로를 추론해 채움 (디렉토리 경로는 대표 진입 파일로 정규화)
        - 파일 존재 검증은 수행하지 않음 (hint 성격)
        - `context_manifest_files`는 최소 1개 이상 유지 (빈 목록 금지)
      - **linked_designs 감지** (`plan.json`의 `linked_designs` 배열 비어있지 않을 때):
        - 각 DES-NNN에 대해 `{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/design.json` Read
          - 파일 미존재 시: 해당 DES skip (silent)
        - `stitch_project_url` + `screens[]`(`title`, `url`, `html_file`) 추출 → `des_context` 변수 보관
          - `html_file`이 null, undefined, 또는 빈 문자열이면 `"N/A"`로 치환
          - `html_file`이 존재하면 프로젝트 루트 절대경로를 앞에 붙여 절대경로로 변환 (예: `{PROJECT_ROOT}/.gran-maestro/designs/DES-001/screen-001.html`)
        - `request.json`에 `"linked_designs": ["DES-NNN", ...]` 필드 추가
        - spec.md §10 자동 채움 포맷 (아래):
          ```markdown
          ## 10. UI 설계 (Stitch)

          - Stitch 프로젝트: {stitch_project_url}
          - 생성 화면:
            - {screens[0].title}: {screens[0].url}
              구현 코드: {screens[0].html_file 절대경로 또는 N/A}
            - {screens[1].title}: {screens[1].url}
              구현 코드: {screens[1].html_file 절대경로 또는 N/A}
            ...
          ```
        - `screens[]`가 비어있으면 "생성 화면" 행 생략, 프로젝트 URL만 기입
        - `linked_designs` 배열이 비어있으면 전체 블록 skip (silent)
      - **캡처 참조 감지** (plan.md의 `## 캡처 참조` 섹션이 존재할 때):
        - plan.md의 `## 캡처 참조` 테이블 파싱: 각 행에서 CAP ID 추출
        - 참조된 각 CAP-NNN에 대해 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json` Read
          - 파일 미존재 시: 해당 CAP의 테이블 행에 "[CAP-NNN 미존재]" 표시 후 나머지 진행
        - `capture.json`에서 `selector`, `css_path`, `memo`, `screenshot_path` 추출 → `cap_context` 변수 보관
          - `screenshot_path`가 null이거나 파일 미존재 시: Screenshot 열에 `"N/A"` 표시
        - `request.json`에 `"linked_captures": ["CAP-NNN", ...]` 필드 추가
        - spec.md §11 `## 캡처 컨텍스트` 자동 채움 포맷 (아래):
          ```markdown
          ## 11. 캡처 컨텍스트

          > 이 섹션은 plan에서 캡처 참조가 인계된 경우에만 작성합니다.
          > 에이전트는 이 정보를 구현 시 참고하여 대상 요소의 정확한 위치를 파악합니다.

          | CAP ID | 요소 | CSS Path | Memo | Screenshot |
          |--------|------|----------|------|------------|
          | CAP-001 | {selector} | {css_path} | {memo} | {screenshot_path} |
          | CAP-002 | {selector} | {css_path} | {memo} | {screenshot_path} |
          ...
          ```
        - 다수 캡처 참조 (10개 이상): 상위 5개만 인라인 테이블에 포함 + "추가 N개 캡처 — `{PROJECT_ROOT}/.gran-maestro/captures/` 디렉토리의 개별 `capture.json` 참조" 안내
          - 상위 5개 정렬 순서: plan.md 테이블 나열 순서 (사용자가 배치한 순서)
        - `## 캡처 참조` 섹션이 비어있거나 존재하지 않으면 전체 블록 skip (silent) — spec.md에 `## 캡처 컨텍스트` 섹션 미삽입
      - **linked_intent 주입** (`plan.json` Read 성공 + `linked_intent` 필드가 존재할 때, --plan 미제공 또는 plan.json Read 실패(사일런트 모드 시) 이 블록 전체 skip):
        - `plan.json`의 `linked_intent` 필드를 읽어 INTENT_ID 취득
        - 실행:
          ```bash
          python3 {PLUGIN_ROOT}/scripts/mst.py intent get {INTENT_ID} --json
          ```
        - 반환된 metadata(feature, situation, motivation, goal)를 spec.md `## Intent (JTBD)` 섹션에 주입:
          ```markdown
          ## Intent (JTBD)

          - When I: {situation}
          - I want to: {feature}
          - So I can: {goal}
          - Motivation: {motivation}
          ```
        - `linked_intent` 미존재 시 skip (비차단); 명령 실패 시 warn만 출력, 워크플로우 차단 금지
      - **분리 실행 감지**: plan.md의 `## 분리 실행` 섹션에 2개 이상 단계 시 다중 REQ 생성 모드:
        1. REQ-NNN = 1단계(①), 2단계부터 REQ 채번·생성 (`status: "pending_dependency"`, `blockedBy` 설정)
           - 모든 단계 REQ의 `request.json`에 `source_plan: "PLN-NNN"`를 동일하게 기록한다.
        2. 1단계 `request.json`에 `dependencies.blocks` 설정, `plan.json`에 모든 REQ ID 추가
        3. **첫 REQ DAG 자동 연쇄 실행 확인** (1단계 REQ만):
           - 조건: 후속 REQ가 1개 이상 (`pending_dependency`)
           - `AUTO_APPROVE=true`:
             - 명시 동의 원칙상 AskUserQuestion 생략
             - 1단계 `request.json`의 `dag_auto_chain`은 기본값 `false` 유지
           - `AUTO_APPROVE=false`:
             - AskUserQuestion:
               - 질문: `"연결된 REQ {N}개({REQ-ID 목록})를 자동으로 연이어 실행할까요?"`
               - 선택지 1: `"예 — DAG 순서로 자동 연쇄"`
               - 선택지 2: `"아니오 — 이 REQ만 실행"`
             - "예" 선택 시: 1단계 `request.json`에 `dag_auto_chain: true` 기록
             - "아니오" 선택 시: `dag_auto_chain: false` 유지
        4. 사용자에게 생성 결과 요약 표시; spec 생성은 **REQ-NNN (1단계)에만** 수행
      - plan.json/plan.md 미존재 시 경고 후 사일런트 모드로 전환 (`source_plan`은 기존 값 유지: 기본 `null`)
   d-doc. **§ Doc Spec Flow** (`DOC_SPEC_MODE=true`일 때만 실행):
      - 진입 조건: Step d에서 `plan_strategy.template == "templates/doc-request.md"` 감지
      - 비진입 조건: `DOC_SPEC_MODE=false` (기존 로직 유지, 이 섹션 전체 skip)
      - 문서 plan 입력 수집:
        - `plan.md`에서 `## TOC 초안`, `## 소스 조사 결과`, `## 검증 계획` 섹션을 각각 Read하여 `doc_toc`, `doc_sources`, `doc_verification_plan` 변수로 보관한다.
        - 셋 중 하나라도 누락되면 경고 후 중단한다 (fallback 없음).
        - `plan.json`의 `doc_sub_type` 값을 우선 사용해 `doc_sub_type`을 결정한다 (`tutorial|howto|reference|explanation|adr|operational`만 허용).
        - `doc_sub_type`이 비어있거나 허용 목록 밖이면 `plan.md`의 문서 목적(예: 설명/참조/튜토리얼/How-to/ADR/운영) 텍스트를 읽어 아래 매핑으로 보정한다:
          - `tutorial`: `tutorial`, `튜토리얼`
          - `howto`: `howto`, `how-to`, `가이드`, `문제 해결`
          - `reference`: `reference`, `참조`, `레퍼런스`, `api reference`
          - `explanation`: `explanation`, `설명`, `개념`, `배경`
          - `adr`: `adr`, `decision`, `rfc`, `결정`
          - `operational`: `operational`, `운영`, `runbook`, `sop`, `playbook`
        - 위 두 단계로도 결정되지 않으면 `doc_sub_type="explanation"`을 기본값으로 사용한다 (기존 doc 기본 동작 유지).
        - `templates/defaults/type-strategies.json`의 `doc.sub_types[doc_sub_type]`에서 `verification`/`checklist`를 읽어 `doc_subtype_verification`, `doc_subtype_checklist`로 보관한다. 누락 시 `explanation` 전략으로 fallback한다.
      - 문서 spec 변환 규칙 (`templates/spec.md` 재사용):
        - `§1 요약`/`§2 범위`는 코드 구현이 아닌 문서 작성 목적·독자·산출물 기준으로 작성한다.
        - `§3 수락 조건` AC는 Given/When/Then/Test 형식을 유지하되 아래 문서 품질 기준으로 작성한다.
          - 정확성: 주장·명령·예시가 `doc_sources` 근거와 일치해야 한다.
          - 완결성: `doc_toc`의 섹션이 누락 없이 spec 범위와 태스크에 반영되어야 한다.
          - 독자적합성: plan에서 정의한 대상 독자의 수준/역할/톤 요구를 충족해야 한다.
          - subtype 적용: AC에 `doc_subtype_verification` 검증 방식과 `doc_subtype_checklist` 항목을 반영한다 (미지정 시 explanation 기준 유지).
      - 태스크 분해 규칙 (문서 전용):
        - `doc_toc`의 상위 섹션(기본 `##`, 필요 시 `###`) 1개를 1개 집필 태스크로 분해한다.
        - 각 태스크 설명에는 해당 섹션에서 참조할 `doc_sources` 근거와 `doc_verification_plan` + `doc_subtype_checklist` 검증 항목을 함께 기록한다.
        - TOC 순서를 기본 실행 순서로 사용하고, 선행 의존이 있으면 `blockedBy`로 연결한다.
      - 이후 Step 적용:
        - Step h의 spec 작성 시 위 변환 규칙을 우선 적용한다.
        - Step h-1의 다중 태스크 분해는 본 섹션의 TOC 기반 분해 규칙을 우선 적용한다.
   e. **모호한 요구사항 처리**:
      - [--plan]: plan.md 결정 사항을 따름
      - [--plan 없음]: PM이 모호함 수준 평가:
        - **minor**: 합리적 가정 수립 → spec.md "가정 사항" 섹션에 기록 → 진행
        - **significant**: 사용자 질문 없이 팀 판단 프로세스 실행:
            1. PM 자율 판단으로 ideation(다각도 비교) / discussion(리스크/합의) 선택
            2. `Skill(skill: "mst:ideation"/"mst:discussion", args: "{주제} --from-request")` 실행
            3. 핵심 3~5개 추출 → "[AI 팀 의견]" 요약 표시 후 자동 진행
            4. 결과를 `REQ-NNN/discussion/req-ambiguity-{synthesis|consensus}.md`에 저장
            5. spec.md `## 9. 팀 판단 기반 결정` 섹션에 기록
   f. **디버그 의도 감지 (LLM 판단)**: 버그/에러/원인분석 등 디버깅 의도 감지 시:
      - `auto_trigger_from_request=true`: `/mst:debug` 자동 호출 후 이 워크플로우 종료
      - `false`: `/mst:debug` 사용 안내 후 일반 워크플로우 진행
   g. 접근 방식 결정 시 **Ideation 자동 트리거 (LLM 판단)**: 아래 중 하나 해당 시 `Skill(skill: "mst:ideation", args: "{주제} --from-request")` 호출:
      - Step 1d-arch(c-arch)에서 이미 ideation/discussion이 실행된 경우 이 단계는 **반드시 skip한다** (중복 실행 방지)
      - `complex` 분류, 트레이드오프 불명확, 고영향 의사결정, PM 단독 판단 확신 부족
      - 기술 스택·아키텍처·구현 접근법 결정 (plan 미사용 시, 또는 plan에서 의도적으로 미결 상태로 남긴 경우)
      - 코드베이스 탐색(4c) 결과가 접근법 선택에 영향을 줄 만큼 중요한 패턴을 발견한 경우
      > ⚠️ plan에서 기술 접근법을 결정하지 않는 것은 의도된 설계입니다.
      > 코드베이스를 직접 본 상태에서 결정하는 이 단계가 더 정확한 판단을 제공합니다.
      - 결과(`synthesis.md`)를 spec 작성에 반영하고 `discussion/req-approach-synthesis.md`에 저장
      - simple 요청/접근 방식 명백한 경우 ideation 없이 진행

      **게이트 오픈 조건** (하나 이상 해당 시):
      - `complex` 분류, 트레이드오프 불명확, 고영향 의사결정, PM 단독 판단 확신 부족
      - 기술 스택·아키텍처·구현 접근법 결정 (plan 미사용 시, 또는 plan에서 의도적으로 미결 상태로 남긴 경우)
      - 코드베이스 탐색(1c) 결과가 접근법 선택에 영향을 줄 만큼 중요한 패턴을 발견한 경우

      **게이트 오픈 처리**:
      - `AUTO_APPROVE=false`:
        AskUserQuestion으로 사용자에게 접근 방식 확인:
          - PM이 코드베이스 탐색 결과를 바탕으로 후보 접근법 2~3개를 선택지로 제시
          - 각 선택지에 트레이드오프(장점/단점/적합한 상황) 포함
          - 보조 선택지로 "ideation으로 다각도 검토" 포함 (PM 판단 시)
          - 사용자 답변 반영 후 g-1로 진행
      - `AUTO_APPROVE=true`:
        `Skill(skill: "mst:ideation", args: "{주제} --from-request")` 자율 실행
          - 결과(`synthesis.md`)를 spec 작성에 반영
          - `discussion/req-approach-synthesis.md`에 저장
   g-1. **구현 수준 리서치 패스** (Step g 완료 직후, Step h 진입 전)

      > **목적**: plan의 Strategic Review(3.8)가 전략 수준 리서치를 담당하듯,
      > 이 단계는 코드베이스 탐색 + 접근법 확정 이후 **구현 수준**의 표준·대안을 능동적으로 점검한다.
      > pre-review(h-2)가 spec 작성 후 사후 체크라면, 이 단계는 spec 작성 전 사전 점검이다.

      **트리거 조건** (하나 이상 해당 시 실행):
      - `complex` 분류
      - 신규 라이브러리·패턴·API 도입 (코드베이스 탐색에서 전례 미발견)
      - Step g에서 ideation/discussion이 실행된 경우
      - PM이 구현 접근법 확신도를 0.7 미만으로 자체 산정한 경우

      **skip 조건** (하나라도 해당 시 skip):
      - `simple` 분류 AND 코드베이스 내 동일 패턴 적용 전례 존재
      - `--plan` 제공 AND plan.md에 구현 방식이 구체적으로 명시된 경우
      - `discussion/req-impl-research.md` 존재 시 (동일 REQ에서 이미 실행됨)
      - `AUTO_APPROVE=true` — 단, 아래 **AUTO_APPROVE 자율 처리** 참조

      **AUTO_APPROVE=true 처리**:
      - 기본적으로 skip하되, PM이 구현 접근법 확신도(`impl_confidence`)를 0.0~1.0으로 자체 산정
      - PM은 아래 순서로 **자력으로 확신도를 높이는 것을 최우선**으로 한다:
        1. 코드베이스 재탐색 (Glob/Grep) → 기존 패턴·전례 확인
        2. WebSearch로 구현 수준 표준 확인
        3. 위 두 단계 후 확신도 재산정
      - 재산정 후 확신도 분기:
        - `impl_confidence >= 0.7`: PM 자율 판단으로 spec 보정(필요 시) 후 h-0 진행
        - `impl_confidence < 0.7`: PM이 ideation/discussion 필요 여부를 **추가로 판단**:
          - 접근법 방향 자체가 불명확하거나 발산이 필요한 경우 → `Skill(skill: "mst:ideation", args: "{주제} --from-request")` 실행
          - 리스크·트레이드오프 합의가 필요한 경우 → `Skill(skill: "mst:discussion", args: "{주제} --from-request")` 실행
          - 위 두 조건 모두 해당하지 않으면 → PM 자율 판단으로 처리 (ideation/discussion 호출 금지)
      - 모든 자율 처리 결과는 `req-impl-research.md`에 기록

      **실행 절차** (`AUTO_APPROVE=false`인 경우):
      1. **코드베이스 패턴 재점검** (Glob/Grep):
         - spec에서 사용할 라이브러리·API의 기존 용례를 코드베이스에서 탐색
         - 동일 목적의 기존 유틸·헬퍼·추상화 존재 여부 확인
      2. **구현 수준 WebSearch** (PM 판단 시 실행):
         - `{라이브러리} {버전} best practices`, `{패턴} implementation guide`
         - `{접근법} common pitfalls {언어/프레임워크}`
         - ⚠️ 전략 수준 검색 금지 — 구현 방식에 한정 (라이브러리 선택, 아키텍처 방향 전환은 범위 밖)
      3. **결과 분류**:
         - `ALIGNED`: 표준 패턴과 일치, 코드베이스 내 대안 없음
         - `DEVIATION`: spec 접근법이 표준에서 벗어남 (이유 없는 경우 보정 필요)
         - `DUPLICATE`: 코드베이스에 동일·유사 구현 존재 (재사용 검토 필요)
         - `BETTER_ALTERNATIVE`: 동일 목적의 더 단순한 구현 방법 발견
      4. **처리**:
         - `ALIGNED`: 결과 저장 후 h-0으로 진행
         - `DEVIATION` / `BETTER_ALTERNATIVE`:
           - AskUserQuestion으로 사용자에게 에스컬레이션:
             - 현재 spec 접근법과 발견된 표준/대안을 나란히 제시
             - 각 선택지에 **장점 / 단점 / 적합한 상황** 포함
             - "현재 spec 방향 유지": 이유를 spec 가정 사항에 기록 후 h-0 진행
             - "표준/대안으로 spec 수정": PM이 spec 보정 후 h-0 진행
         - `DUPLICATE` (CRITICAL — 완전 중복 구현):
           - AskUserQuestion으로 사용자에게 에스컬레이션:
             - 기존 구현 위치·범위와 신규 구현 의도를 함께 제시
             - 각 선택지에 **장점 / 단점 / 적합한 상황** 포함
             - "기존 구현 재사용으로 spec 수정": spec 보정 후 h-0 진행
             - "새로 구현 (이유 있음)": 이유를 spec 가정 사항에 기록 후 h-0 진행
      5. **결과 저장**: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/discussion/req-impl-research.md`
         ```yaml
         trigger: complex | new_library | post_ideation | low_confidence
         impl_confidence: 0.0~1.0  # AUTO_APPROVE=true 시만 기록
         codebase_findings:
           - type: DUPLICATE | BETTER_ALTERNATIVE | NONE
             detail: "..."
         web_search:
           - query: "..."
             finding: "..."
         result: ALIGNED | DEVIATION | DUPLICATE | BETTER_ALTERNATIVE
         spec_changes: "변경 없음 | {변경 내용 요약}"
         ```
   1.8. **구현 세부 Q&A Pass** (Step 1g 완료 직후, Step h-0 이전):
      - `AUTO_APPROVE=true`면 이 단계 전체를 완전 skip하고 Step h-0으로 즉시 진행
      - `AUTO_APPROVE=false`면 아래 7개 카테고리를 **고정 순서로 순차 처리**한다:
        1) 에러/실패 처리
        2) 엣지케이스
        3) 데이터 변경
        4) 호환성
        5) 성능
        6) 테스트 범위
        7) 배포 전략
      - `--plan PLN-NNN`(또는 `resolved_plan_id`)이 있는 경우:
        - 각 카테고리마다 plan.md(`제약사항`, `우선순위(MoSCoW)`, 관련 결정 섹션)에서 대응 값을 먼저 탐색한다.
        - 값이 명확히 매핑되면 질문을 생략하고 `"plan에서 확인됨"` 요약만 출력한다.
        - 값이 없거나 매핑이 불확실하면 기본 동작으로 `AskUserQuestion`을 실행한다 (추정 금지).
      - `--plan`이 없으면 기존 규칙대로 7개 카테고리를 모두 `AskUserQuestion`으로 질문한다.
      - `AskUserQuestion`을 호출하는 카테고리는 동시 1개만 질문한다.
      - 각 질문에는 반드시 `"해당 없음"` 선택지를 포함한다.
      - 선택지 수는 총 6개 이내를 유지한다 (핵심 선택지 + 보조 선택지 합산).
      - **모호한 답변 처리 (카테고리별 최대 3회)**:
        - 답변이 불명확하면, 직전 답변을 반영해 더 구체적인 선택지로 재질문한다.
        - 3회 내 명확한 답변이 확보되지 않으면 PM이 해당 카테고리를 **가장 안전한 선택**으로 자동 결정한다.
        - 자동 결정 시 결정 사유를 내부 메모에 남기고 다음 카테고리로 진행한다.
      - 수집된 Q&A 결과는 spec.md 작성 시 반드시 반영:
        - §3 수락 조건(AC) 상세에 반영
        - §3.5 Constraints에 반영
   1.9. **테스트 전략 게이트 (Test Strategy Gate)** (Step 1.8 완료 직후, Step h-0 이전):
      - **실행 조건**:
        - 먼저 `test_enforcement`를 로드한다.
          - 1순위: `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`의 `test_enforcement`
          - 2순위 fallback: `templates/defaults/config.json`의 `test_enforcement`
          - 둘 다 없으면 기본값 사용:
            - `enabled=true`
            - `backend_tdd=true`
            - `web_execution_test=true`
            - `exempt_patterns=["*.md","*.json","*.yml","*.yaml","*.txt","*.css"]`
            - `require_exemption_reason=true`
        - `test_enforcement.enabled=true`이면 plan의 `## 테스트 전략` 섹션 유무와 무관하게 **항상 실행**한다.
        - `test_enforcement.enabled=false`이면 기존 동작을 유지한다:
          - plan.md에 `## 테스트 전략` 섹션이 존재하고 `적용 여부: 적용`인 경우에만 실행
          - 섹션이 없거나 `적용 여부: 적용 안 함`이면 skip
      - **코드베이스 탐색 (Glob/Grep, MANDATORY)**:
        - `package.json`에서 test runner를 감지한다 (`jest`, `vitest`, `mocha`, `pytest` 등).
        - `tsconfig.json`, `.eslintrc*`, `eslint.config.*`, `prettier.config.*`, `.prettierrc*` 존재 여부를 확인한다.
        - `playwright.config.*` 또는 `cypress.config.*` 존재 여부를 확인한다.
        - `test/` 또는 `__tests__/` 디렉토리 존재 여부를 확인한다.
        - 빌드 스크립트 존재 여부를 확인한다 (`package.json scripts.build`, `Makefile`의 `build` 타깃 등).
      - **7종 추천 로직** (탐색 결과 기반):
        1. 빌드 확인 `[build-check]`:
           - 빌드 명령이 감지되면 추천한다.
           - 예: `npm run build`, `pnpm build`, `yarn build`, `make build`
        2. 린트/포맷 `[lint-check]`:
           - 린터/포맷터 설정이 감지되면 추천한다.
           - 예: `npx eslint .`, `npx prettier --check .`
        3. Unit Test `[unit-test]`:
           - 테스트 러너가 감지되면 추천한다.
           - plan.md `## 테스트 전략`의 목표 커버리지가 설정된 경우 해당 목표를 명시한다.
        4. Integration/API Test `[integration]` 또는 `[api-test]`:
           - DB 연동 변경 또는 API 엔드포인트 변경 신호가 있으면 추천한다.
        5. E2E/Browser Test `[e2e-browser]`:
           - playwright/cypress 설정이 감지되면 추천한다.
        6. Visual Regression `[visual]`:
           - 아래 **고비용 테스트 정책**을 모두 충족할 때만 추천한다.
        7. Performance Test `[performance]`:
           - 아래 **고비용 테스트 정책**을 모두 충족할 때만 추천한다.
      - **고비용 테스트 정책 (CRITICAL)**:
        - Visual Regression/Performance는 아래 조건을 모두 만족할 때만 추천한다.
          1) 관련 도구가 프로젝트에 설치되어 있음
          2) 현재 변경이 해당 테스트 유형의 대상임 (UI 변경 / 성능 크리티컬 변경)
          3) PM이 명확한 근거를 1줄 이상 제시함
        - 하나라도 미충족이면 추천 목록에서 제외한다.
      - **사용자 확인**:
        - `AUTO_APPROVE=false`: AskUserQuestion으로 추천 목록을 제시하고 사용자 확인/수정을 반영한다.
        - `AUTO_APPROVE=true`: PM이 추천 목록을 자율 확정한다.
      - **test_enforcement 강제 규칙 (MANDATORY)**:
        - `test_enforcement.enabled=true`일 때:
          - 변경 파일이 `exempt_patterns`에 100% 매칭되면 테스트 면제를 적용하고 사유를 기록한다.
            - 기본 사유: `"비코드 수정(exempt_patterns 매칭)"`
            - `require_exemption_reason=true`이면 spec 본문 또는 내부 메모에 사유 기록이 없을 경우 에러로 처리한다.
          - 테스트 러너 미감지 시 테스트 면제를 적용하고 사유를 기록한다.
            - 사유: `"테스트 프레임워크 미존재"`
          - 위 두 면제 조건이 아니면 테스트 AC를 반드시 포함한다.
        - `test_enforcement.enabled=false`일 때는 기존 권장 정책(면제 기록 강제 없음)을 유지한다.
      - **spec AC 반영 규칙**:
        - 확정된 테스트 항목을 spec.md AC에 테스트 유형 보조 태그로 부여한다.
        - 보조 태그는 기존 `[automatable]`/`[manual]`/`[browser-test]` 뒤에 추가한다.
        - 각 유형별 원칙은 해당 태그가 부여된 AC에만 2~3줄로 선별 주입한다 (전체 AC 일괄 주입 금지).
        - `test_enforcement.backend_tdd=true`이고 백엔드 도메인 태스크이면 핵심 테스트 AC에 `[tdd-required]`를 부여하고 구현 지시문에 `"테스트를 먼저 작성한 후 구현하세요 (TDD)"`를 반드시 포함한다.
        - `test_enforcement.web_execution_test=true`이고 웹/프론트엔드 도메인 태스크이면 최소 1개 AC에 `[e2e-browser]` 또는 `[browser-test]`를 부여하고 구현 지시문에 `"실행 테스트를 작성하고 통과시킨 후 구현 완료로 판단하세요"`를 반드시 포함한다.
      - **유형별 원칙 (하드코딩, MANDATORY)**:
        - `[build-check]`: "빌드 명령어 성공(exit 0) 확인. 빌드 오류 시 구현 실패로 간주."
        - `[lint-check]`: "린터/포맷터 규칙 위반 0건 확인. --fix 자동 수정 허용."
        - `[unit-test]`: "AAA 패턴(Arrange-Act-Assert) 준수. 각 테스트는 하나의 동작만 검증. 외부 의존성만 mock."
        - `[integration]`: "실제 DB/서비스 사용. 테스트 시딩 필수. 격리된 환경에서 실행."
        - `[e2e-browser]`: "Page Object 패턴 권장. 스크린샷 첨부. 안정적 selector 사용."
        - `[api-test]`: "Given-When-Then 구조. status + body + schema 검증."
        - `[visual]`: "베이스라인 이미지 비교. 캡처 조건(뷰포트, 지연) 명시."
        - `[performance]`: "워밍업/반복/임계값 명시. 회귀 감지 기준 정의."
      - **도구 미설치 시 처리**:
        - 추천된 테스트 도구가 미설치면 graceful skip 처리 후 설치 명령어를 안내한다.
        - 사용자에게 `"LLM이 설치를 도와드릴까요?"` 옵션을 제공한다.
        - `test_enforcement.enabled=true`에서 test runner 자체가 미감지인 경우는 도구 설치 안내와 별개로 `"테스트 프레임워크 미존재"` 면제 사유를 반드시 기록한다.
        - 도구 미설치로 인해 request 워크플로우를 차단하지 않는다.
   h-0. **Stitch 트리거 감지** (config.stitch.enabled=true인 경우):
      - 명시적 디자인 요청("화면 디자인해줘", "Stitch로", "목업", "시안" 등):
        ⚠️ **`mcp__stitch__*` 도구를 직접 호출하는 것은 절대 금지.**
        반드시 `Skill(skill: "mst:stitch", args: "--req REQ-NNN {요청 내용}")` 스킬을 통해서만 호출합니다.
        → Stitch 완료 후 spec.md 작성 계속
      - 그 외(새 화면 추가/약한 신호): approve Phase 2.5에서 제안, 이 단계 skip
      - 본 단계에서 UI 관련 여부 플래그 `ui_related`를 유지한다:
        - `ui_related=true`: 명시적 디자인 요청 또는 새 화면 추가/약한 UI 신호 감지
        - `ui_related=false`: 그 외
   h-0.5. **Assigned Agent 기본값 보관**: spec.md 작성 직전, `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`의 `workflow.default_agent` 값을 읽어 Assigned Agent 필드의 기본값으로 설정한다. `templates/spec.md`의 Decision Tree(0~3단계)는 이 기본값의 override 조건으로만 동작한다. config 미참조 시 `claude-dev` 자동 선택은 금지. `config.resolved.json`이 없으면 `templates/defaults/config.json`의 `agent_assignments`를 fallback으로 Read한다. 이때 `workflow.default_agent`도 `templates/defaults/config.json`에서 함께 Read하여 DEFAULT_AGENT로 사용한다.
   h-0.6. **Intent Context Load (MANDATORY)**:
      - `{PROJECT_ROOT}/.gran-maestro/request-context.md`를 반드시 Read한다.
        - 파일이 없으면 아래 초기 템플릿으로 생성 후 즉시 Read한다 (비차단):
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
      - 이후 request 스킬의 모든 `AskUserQuestion`(재질문/에스컬레이션 포함)에서 과거 선호를 `description`에 명시적으로 인용한다.
        - 권장 형식: `이전에 "{statement}"를 선호하셨습니다. 이번에도 동일하게 적용할까요?`
        - `freq` 숫자 직접 인용 금지 (경향 문장만 사용).
      - 사용자가 인용 선호를 반박하면 해당 statement를 `request_disputed_preferences`에 수집하고 Step 6의 요약 트리거 입력으로 전달한다.
      - `intent_fidelity.enabled` 값을 먼저 확인한다.
        - 1순위: `{PROJECT_ROOT}/.gran-maestro/config.resolved.json`의 `intent_fidelity.enabled`
        - 2순위 fallback: `templates/defaults/config.json`의 `intent_fidelity.enabled`
        - 둘 다 없으면 기본값 `true`
      - `intent_fidelity.enabled=false`면 이 단계 전체를 skip한다 (`intent_context`, `docs_context`, `intent_snapshot` 모두 비활성; 에러 아님).
      - `--plan PLN-NNN` 제공 시:
        - plan.md에서 `## 요청 (Refined)` + `## Intent (JTBD)` + `## 인수 기준 초안`을 Read하여 `intent_context`로 보관한다.
        - `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.ids.json`을 Read하여 PAC preflight를 수행한다 (비차단):
          - 파일 존재 시: `[{id,text,grade,tags?}]` 목록을 `pac_preflight_checklist`로 로드한다 (`tags` 미존재 시 빈 배열로 간주).
          - 각 PAC의 `tags`에서 `TIER-A`/`TIER-B`를 인식해 `pac_tier`를 결정한다.
            - `tags`에 `TIER-A`가 있으면 `pac_tier="TIER-A"`
            - 그 외 `TIER-B`가 있으면 `pac_tier="TIER-B"`
            - 둘 다 없으면 기본값 `pac_tier="TIER-B"`로 간주한다 (기존 plan.ids.json 하위 호환)
          - 파일 미존재 시: warn 출력 후 plan.md `## 인수 기준 초안`에서 임시 PAC 목록을 추론한다 (비차단).
          - 로드된 PAC 전체 ID를 `pac_anchor_list`로 보관하고 이후 spec AC 작성/게이트 프롬프트 앞단에 고정 주입한다.
          - preflight 단계에서는 request emit을 차단하지 않는다.
        - docs 후보를 plan.md에서 수집한다:
          - `## 연관 컨텍스트` 표에 포함된 `docs/` 경로
          - plan.md 본문 내 `docs/`로 시작하는 문서 경로
        - docs 후보가 비어있으면 `docs_context`는 빈 목록으로 유지하고 graceful skip 처리한다.
      - `--plan` 미제공 시:
        - 사용자 요청 원문(`request.json.original_request`)을 `intent_context`로 보관한다.
        - docs 후보는 아래 두 소스만 사용한다:
          - Step 1c 코드베이스 탐색에서 발견한 `docs/` 파일
          - 사용자 요청에서 명시적으로 언급한 문서 경로
        - 별도의 `docs/` 전체 스캔은 수행하지 않는다.
      - `docs_context` 구성 규칙:
        - docs 후보를 dedupe한 뒤 존재하는 파일만 Read한다 (미존재 경로는 warn 후 skip).
        - 후보가 최종적으로 0개면 에러 없이 graceful skip한다.
        - 각 docs 항목마다 아래 정보를 추출해 저장한다:
          - `path`
          - `last_modified` (`git log -1 --format=%cI {path}` 우선, 실패 시 `stat` fallback)
          - `핵심 요구사항` 1~3줄 요약
      - 활성화 판정:
        - `intent_context_active=true`: `--plan`으로 intent 섹션을 확보했거나 `docs_context`가 1개 이상일 때
        - `intent_context_active=false`: 그 외 (예: docs 없는 프로젝트에서 `--plan` 없이 단순 요청)
   h. **Implementation Spec 작성** (`templates/spec.md` 템플릿 사용); `--plan` 없으면 `## 가정 사항` 섹션 포함
      > ⚠️ **spec.md 작성 원칙**: spec은 "무엇을 달성해야 하는가 + 알아야 할 맥락"만 기술합니다.
      > - **포함**: AC (완료 기준), 범위 경계, 제약 조건, 패턴 힌트, 시작점 1~3개, 의존성
      > - **제외**: 수정 파일 exhaustive 목록, 단계별 구현 절차, 에지케이스 사전 열거
      > 구체적인 구현 방법은 에이전트가 worktree를 직접 탐색하며 결정합니다.
      - **UI 관련 DESIGN.md 자동 참조 (MANDATORY, graceful)**:
        - 조건: `ui_related=true` + `{PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md` 파일 존재
        - 동작 1: DESIGN.md를 Read하여 `design_system_context`로 보관하고, `context_manifest_files`에 `.gran-maestro/designs/DESIGN.md`를 dedupe 추가한다.
          - spec.md에는 아래 중 하나로 경로를 반드시 기록한다:
            - `## §0 Context Manifest` 목록에 포함 (권장, 기본값)
            - 또는 별도 `## 디자인 시스템 참조` 섹션에 `- .gran-maestro/designs/DESIGN.md` 기록
        - 동작 2: outsource brief(`templates/impl-request.md`) 생성 시 `{{IMPL_CONTEXT}}`에 아래 문구를 반드시 주입하도록 지침을 남긴다.
          - `DESIGN.md를 반드시 Read하여 디자인 규칙을 준수하세요.`
        - DESIGN.md가 없으면 위 두 동작 모두 skip한다 (graceful).
      - **AC 타입 확장 규칙 (MANDATORY)**:
        - AC 헤더 타입 태그는 `[automatable]`, `[manual]`, `[browser-test]` 3가지를 허용한다.
        - `browser-test`는 실제 브라우저 상호작용 검증이 필요한 AC에 사용한다 (UI 흐름, 클릭/입력, 화면 렌더링, 시각적 회귀 확인 등).
        - plan의 `## 인수 기준 초안` 또는 대화 컨텍스트에 `브라우저 테스트`, `실제 브라우저`, `스크린샷 검증`, `Playwright`, `Claude in Chrome` 신호가 있으면 AC를 `[browser-test]`로 분류한다.
        - `test_enforcement.web_execution_test=true`이고 웹/프론트엔드 태스크이면 위 신호가 약해도 `[browser-test]` 또는 `[e2e-browser]` AC를 최소 1개 포함한다.
        - `[browser-test]` AC도 기존 Given/When/Then/Test 형식을 그대로 유지한다.
        - `Test:`는 실행 대상 URL/화면 + 핵심 사용자 동작 + 기대 결과를 포함해 작성한다 (예: `Playwright 또는 Claude in Chrome으로 /settings 진입 후 Save 클릭 시 성공 토스트 표시 확인`).
      - **[tdd-required] 보조 태그 규칙 (MANDATORY)**:
        - h-0.6에서 로드한 `pac_preflight_checklist` 기준으로 `pac_tier="TIER-A"`인 PAC에 매핑된 Spec AC 헤더에는 `[tdd-required]`를 자동 부여한다.
        - `test_enforcement.backend_tdd=true`이고 백엔드 도메인 태스크이면 핵심 테스트 AC에도 `[tdd-required]`를 자동 부여한다 (PAC tier와 무관).
        - `pac_tier="TIER-B"`인 PAC는 `[tdd-required]`를 자동 부여하지 않는다.
        - `[tdd-required]`는 기존 보조 태그(`impact-check`, `regression-test` 등)와 독립적으로 공존하며 기존 라우팅/검증 규칙을 변경하지 않는다.
      - **[impact-check] 보조 태그 변환 규칙 (MANDATORY)**:
        - plan PAC에 `[IMPACT]` 태그가 있거나 `plan.ids.json` 항목의 `tags`에 `"IMPACT"`가 포함되면, 변환된 Spec AC 헤더에 `[impact-check]` 보조 태그를 반드시 포함한다.
        - `[impact-check]`는 기존 보조 태그 체계(`[unit-test]`, `[api-test]`, ...)에 편입되며 Given/When/Then/Test 형식은 기존 규칙을 그대로 따른다.
        - 복수 보조 태그가 공존하면 라우팅 우선순위는 `[impact-check]`가 최우선이며, impact_reviewer 위임 대상으로 표시한다.
        - `[IMPACT]` PAC가 없는 plan/spec에서는 이 규칙을 graceful skip하고 기존 보조 태그 변환 동작을 유지한다 (하위 호환).
      - **Tier 에스컬레이션 규칙 (MANDATORY)**:
        - 구현 에이전트는 코드 복잡도/리스크 근거가 충분한 경우 `TIER-B` PAC를 `TIER-A`로 상향 에스컬레이션할 수 있다.
        - 상향 에스컬레이션된 PAC/AC에는 `[tdd-required]`를 추가 적용한다.
        - `TIER-A`를 `TIER-B`로 하향 에스컬레이션하는 것은 명시적으로 금지한다.
      - **PAC 매핑 규칙 ( `--plan` 제공 시, MANDATORY )**:
        - h-0.6에서 확보한 `pac_preflight_checklist`의 각 PAC를 spec AC에 최소 1회 매핑한다.
        - spec 본문에 `## 3.3 PAC Mapping` 섹션을 추가해 아래 표를 작성한다:
          - `PAC ID | Grade(MUST/SHOULD) | Mapped Spec AC IDs | Coverage`
        - MUST PAC는 `Mapped Spec AC IDs`가 비어 있으면 안 된다.
        - plan에 없는 신규 spec AC는 `Coverage`를 `SPEC_ONLY`로 표시해 scope creep 추적 대상으로 남긴다.
        - `[IMPACT]` PAC도 일반 PAC와 동일하게 Coverage를 추적한다 (`Mapped Spec AC IDs` 비우지 않음 권장).
      - **`## §0 Context Manifest` 자동 채움 규칙 (MANDATORY)**:
        - Step d에서 수집한 `context_manifest_files`를 bullet 목록으로 삽입한다.
        - `--plan`이 없는 경우에도 동일 규칙 적용: Step 1c 탐색 결과 + 요청 분석 기반으로 `context_manifest_files`를 구성한다.
        - §0 본문 가이드라인 문구(완전하지 않을 수 있음 + 자율 탐색 유지)는 템플릿 문구를 그대로 유지한다.
        - 최종 spec.md의 §0 목록은 최소 1개 이상 파일 경로를 포함해야 한다.
      - **`## 3.2 Intent Trace` 작성 규칙 (MANDATORY)**:
        - `intent_context_active=true`일 때만 §3.2를 채운다.
        - 각 AC마다 최소 1개 의도 근거를 연결한다 (근거 출처: plan.md `§요청 (Refined)`/`§Intent (JTBD)`/`§인수 기준 초안` 또는 `docs_context`의 문서 경로).
        - AC 근거를 찾지 못하면 `의도 근거` 칸에 `[INTENT-GAP]`을 표기한다.
        - docs를 근거로 사용한 경우 `intent_snapshot`에 아래 3개를 기록한다:
          - `doc_path`
          - `last_modified`
          - `spec_generated_at`
        - `intent_context_active=false`면 §3.2 섹션 전체를 skip한다 (에러 아님).
   h-0.7. **Regression Test 선행 태스크 생성** (Step h-1 이전, MANDATORY):
      - 목적: 기존 코드 수정 REQ에서 코드 변경 전에 **기존 동작 보존 회귀 검증** 태스크를 선행 배치한다.
      - 트리거 조건(모두 충족 시 생성):
        - 수정 대상에 기존 파일/함수의 **비즈니스 로직 변경**이 포함됨.
        - 단순 boilerplate 변경만이 아님.
      - 제외 조건:
        - boilerplate-only 변경 (예: import 추가, 라우터 등록, wiring/설정 연결만 변경).
        - 완전 신규 기능 (새 파일만 생성, 기존 코드 비즈니스 로직 변경 없음).
      - 생성 규칙:
        - 각 코드 수정 태스크 앞에 `"기존 기능 regression test 작성"` 성격의 선행 태스크를 생성한다.
        - 선행 태스크는 후행 코드 수정 태스크의 `blockedBy` 선행 조건으로 연결한다.
        - 태스크 범위는 반드시 **수정 대상 파일/함수 + 1단계 연관 모듈(static import/caller)** 로 한정한다.
        - 테스트 방식은 **새 테스트 작성**을 기본으로 하며, 기존 테스트가 있으면 **기존 테스트와 병행 실행**한다.
      - Spec AC 보조 태그 부여 규칙 (`[impact-check]` 패턴 준용):
        - 위 선행 태스크로 생성/변환되는 AC 헤더에는 `[regression-test]` 보조 태그를 포함한다.
        - `[regression-test]`는 기존 보조 태그 체계(`[unit-test]`, `[api-test]`, ...)에 편입되며 Given/When/Then/Test 형식을 그대로 따른다.
        - 복수 보조 태그 공존 시 `[impact-check]` 우선 라우팅 규칙은 유지하고, `[regression-test]`는 Pass A의 회귀 테스트 실행 대상으로 함께 보존한다.
      - 역할 구분 (PLN-291 하위호환, MANDATORY):
        - `[IMPACT]`/`[impact-check]` = 수정 영향으로 **다른 영역**이 깨지지 않았는지 확인.
        - `[regression-test]` = **수정 대상 자체**의 기존 동작이 유지되는지 확인.
        - 동일 파일 대상이라도 검증 목적이 다르므로 중복이 아니다.

   h-1. **다중 태스크 분해 처리** (PM 자율 판단 — plan 유무와 무관):
      - plan.md에 `## 태스크 분해` 섹션이 있더라도 무시한다. 태스크 분해는 plan의 관심사가 아니며 코드베이스 탐색 결과를 바탕으로 아래 기준에 따라 PM이 독자적으로 결정한다.
      - pm-conductor.md Step 6.6 판단 따름; 2단계 이상 결정 시 동일 절차

      **태스크 분해 기준 (우선순위 순)**:

      - **순서 의존성 기준 (0차, 최우선)**: 선행 결과물 없이는 후행 작업을 시작할 수 없는 경우 → 직렬 태스크로 분리.
        예: DB 스키마 변경 → API 엔드포인트 → UI 연동. blockedBy/blocks로 순서 명시.
        단순히 "나중에 하면 좋겠다" 수준은 직렬화 대상이 아님 — 실제 결과물 의존이 있을 때만.

      - **중간 검증 가능성 기준 (0.5차)**: 작업 중간 지점에서 독립적으로 검증할 수 있는 경계가 존재하는 경우 → 그 경계를 기준으로 분리.
        분리 판단 질문:
        ① "절반만 완료한 상태에서 '이게 잘 됐나?' 확인할 수 있는가?" → YES면 분리 경계
        ② "T01만 완료하고 T02를 안 해도 코드베이스가 망가지지 않는가?" → YES면 분리 가능
        분리 금지: 중간 상태가 어느 것도 단독 검증 불가능한 경우 (예: UI와 API를 절반씩) → 하나의 태스크로 묶기.
        파일 수·라인 수는 분리 기준이 아님.

      - **기능 책임 단위 분리 기준 (1차)**: 동일 태스크에 서로 다른 비즈니스 기능이 혼재하는 경우 → 기능 단위로 분리 (파일 타입·수가 아닌 기능 책임 범위 기준). 파일 타입 혼재(`.ts` + `.md`)는 분리의 필요충분조건이 아님 — 동일 기능 책임 내 보조 파일은 같은 태스크에 포함 가능. agent 배정은 h-0.5 단계 참조.

      - **레이어 분리 기준 (2차)**: 동일 기능 단위라도 프론트엔드(.tsx/.jsx/UI 컴포넌트)와 백엔드(API/DB/서버 로직) 작업이 모두 포함되고 각각 독립 커밋/테스트 단위가 될 만큼 충분하면 → 레이어별 2개 태스크로 분리. 백엔드 T: API 및 DB 로직 → codex-dev 또는 default_agent; 프론트엔드 T: UI 컴포넌트·페이지 → gemini-dev (.tsx/.jsx 포함 시). blockedBy 설정: 백엔드 API가 완료되어야 연동 가능하면 `blockedBy: [백엔드T]`, UI 스타일만 독립 개발 가능하면 병렬 허용. 단, 프론트만 or 백엔드만 수정하면 1차 기준만 적용 (레이어 분리 불필요).

      **스텝 0.5 (선행): 책임 겹침 방지 검증**
      - 분해된 각 태스크의 기능 책임을 한 줄씩 열거한다
        예: T01 = "JWT 토큰 발급", T02 = "토큰 검증 미들웨어", T03 = "프로필 UI 컴포넌트"
      - 두 태스크 간 동일·유사한 기능 책임 발견 시:
        - 완전 동일: 하나로 병합
        - 선행 관계: blockedBy로 직렬화
      - 겹침 없이 검증 통과 후에만 스텝 0으로 진행

      **스텝 0 (선행): 의존성 및 배정 확정**
      - 모든 태스크 ID, blockedBy/blocks, 에이전트 배정을 단일 thinking에서 확정한다 (이후 Write 또는 서브에이전트 어느 경로든 이 테이블을 불변 입력으로 사용)
      - [--plan]: plan.md 결정사항 기반; [--plan 없음]: PM 자율 판단 기반

      **스텝 1 (분기): 독립 태스크 수 판단**
      - 독립 태스크(blocks/blockedBy 없는 것) 수 계산:
        - 독립 태스크 < 2개: 기존 순차 Write 유지
        - 독립 태스크(blocks/blockedBy 없는 것) 2개 이상: **Phase A 필수 실행**
          - [Phase A — MUST] Write 동시 호출: 단일 응답 내 N개 Write 동시 호출 (각 spec.md에 스텝 0 의존성 테이블 그대로 기입)
          - [Phase B] 서브에이전트 병렬 (아래 사유가 명시된 경우에만 허용):
            - reasoning 복잡도가 높고 태스크별 독립 코드베이스 탐색이 필요한 경우
            - `Task(subagent_type: "general-purpose", run_in_background: true)` 로 N개 병렬 dispatch
            - 각 서브에이전트에 의존성 테이블 + 에이전트 배정 결과를 읽기 전용으로 주입 (프롬프트에 포함): 서브에이전트는 해당 값을 §7, §8에 그대로 기입, 의존성/배정 결정 금지
            - Phase B로 spec을 작성한 서브에이전트와 별개로 PM이 prereview 에이전트를 dispatch (역할 분리)
            - PM 재량만으로 Phase A를 미실행하는 것은 금지

      **스텝 2 (검증): 양방향 의존성 검증 훅** (모든 spec.md Write 완료 직후 실행)
      - 각 spec의 blocks 목록을 읽어 대상 태스크 spec의 blockedBy 포함 여부 확인; 역방향도 동일하게 검증
      - blocks/blockedBy 양방향 일치 검증: 불일치 발견 시 오류 메시지 출력 + request.json의 tasks 배열 업데이트 차단 (spec.md는 유지, PM이 수동 수정 후 재시도)
      - 부분 실패 (k/N spec 성공) 시: 실패 태스크 ID 목록 표시 + 해당 태스크 spec.md만 재작성 재시도 안내 (성공 태스크 유지)

   i. 태스크 디렉토리 일괄 생성: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/tasks/01..N` (N개 동시 생성)
   j. **spec.md 병렬 Write**: (의존성 고정 후) 단일 응답 내 N개 Write 동시 호출로 저장
   h-2. **Spec Pre-review Pass** (모든 spec.md Write 완료 + 검증 훅 통과 후 실행)

      **실행 조건** (순서대로, 변경 없음):
      `--prereview` → 강제 실행 (다른 skip 조건 무시); `--auto`/`-a` 또는 `AUTO_APPROVE=true` → skip;
      `--no-prereview` → skip; `workflow.spec_prereview=false` → skip; 모두 통과 시 실행

      **에스컬레이션 모드**: `AUTO_APPROVE=true`면 `"pm-self"`, 그 외(`AUTO_APPROVE=false`)는 항상 `"user"`

      **config 읽기** (신규):
      - `max_iterations` = `config.workflow.spec_prereview_max_iterations` (미설정 시 기본 3)
      - `escalation_trigger` = `config.workflow.spec_prereview_escalation_trigger` (미설정 시 기본 `"major"`)
      - `minor_escalation_threshold` = `config.workflow.spec_prereview_minor_escalation_threshold` (미설정 시 null — 기능 비활성)
      - `current_iteration` = 1

      **[PREREVIEW LOOP — current_iteration 기준 반복]**

      prereview-prompt.md N개 동시 Write (단일 응답):
      각 `tasks/NN/prereview-prompt.md`를 `templates/spec-prereview-prompt.md` + 변수 치환으로 생성

      에이전트 병렬 dispatch (변경 없음):
      a. claude-dev 2개+ 태스크: `Task(run_in_background: true)` 직접 호출
         codex-dev/gemini-dev: `Skill(skill: "mst:{agent}", run_in_background: true)` 사용

      결과 수집 및 이슈 분류:
      b. 태스크별 결과를 CRITICAL/MAJOR/MINOR로 분류
         - `NO_ISSUES` 응답: 해당 태스크 이슈 없음
         - 실패 응답: "[Pre-review skip]" 출력 후 해당 태스크 건너뜀

      **escalate 판단**:
      - `escalation_trigger = "critical"`: CRITICAL 이슈 1개 이상 → escalate
      - `escalation_trigger = "major"`: CRITICAL 또는 MAJOR 이슈 1개 이상 → escalate
      - `escalation_trigger = "minor"`: CRITICAL/MAJOR/MINOR 이슈 1개 이상 → escalate

      **[escalate = true]**:

      **user 모드** (`escalation_mode = "user"`):
      - AskUserQuestion: 수집된 이슈 목록 제시 (CRITICAL/MAJOR 우선 표시) + 선택지:
        - "반영하고 재리뷰": PM이 이슈를 spec.md에 반영 후 루프 재진입
        - "반영 없이 진행": 루프 즉시 종료
      - "반영하고 재리뷰" 선택 시:
        - escalate 이슈를 PM이 해당 spec.md에 Edit으로 반영
        - `current_iteration < max_iterations` → `current_iteration++` → **LOOP 재진입**
        - `current_iteration >= max_iterations` → 루프 종료

      **pm-self 모드** (`escalation_mode = "pm-self"`):
      - PM이 자체 판단으로 escalate 이슈를 spec.md에 Edit으로 반영
      - `current_iteration < max_iterations` → `current_iteration++` → **LOOP 재진입**
      - `current_iteration >= max_iterations` → 루프 종료

      **[escalate = false]** (escalation_trigger 미만 이슈만 존재 또는 전체 NO_ISSUES):

      **MINOR 임계값 에스컬레이션 체크** (minor_escalation_threshold != null인 경우):
      ⚠️ 이 로직은 escalate=false 분기 내부에서 별도로 처리한다
         (escalate=true 분기로 점프하지 않음 — 구조 복잡도 방지).
      - threshold 정규화: threshold <= 0이면 threshold = 1로 치환
      - 전체 MINOR 이슈 갯수 합산 (MINOR_COUNT)
      - MINOR_COUNT > 0 AND MINOR_COUNT >= minor_escalation_threshold → CRITICAL로 취급:
        - "[MINOR 임계값 초과] N개 MINOR 이슈가 임계값({threshold})을 초과하여 확인이 필요합니다" 안내 표시

        **user 모드** (`escalation_mode = "user"`):
        - AskUserQuestion으로 MINOR 이슈 목록 제시 + 선택지:
          - "반영하고 재리뷰" / "반영 없이 진행"
          - "반영 없이 진행" 선택 시: 루프 즉시 종료
          - "반영하고 재리뷰" 선택 시: PM이 이슈를 spec.md에 Edit으로 반영 후 루프 재진입
            - `current_iteration < max_iterations` → `current_iteration++` → **LOOP 재진입**
            - `current_iteration >= max_iterations` → 루프 종료

        **pm-self 모드** (`escalation_mode = "pm-self"`):
        - PM이 자체 판단으로 MINOR 이슈를 spec.md에 Edit으로 반영
        - `current_iteration < max_iterations` → `current_iteration++` → **LOOP 재진입**
        - `current_iteration >= max_iterations` → 루프 종료

      - MINOR_COUNT < minor_escalation_threshold 또는 minor_escalation_threshold == null → escalation_mode에 따라:
        - **user 모드** (`escalation_mode = "user"`): MINOR 이슈 목록을 AskUserQuestion으로 제시 + 선택지 "반영하고 재리뷰" / "반영 없이 진행"
          - "반영하고 재리뷰": PM이 이슈를 spec.md에 Edit으로 반영 후 루프 재진입 (max_iterations 확인)
          - "반영 없이 진행": 루프 종료
        - **pm-self 모드** (`escalation_mode = "pm-self"`): PM이 자체 반영 후 루프 종료 (기존 동작)
      - 전체 NO_ISSUES: 수정 없이 루프 종료

      **[PREREVIEW LOOP 종료]**

      c. 이슈가 1개 이상 존재했던 경우 spec.md 끝에 `## 구현 전 검토 (Pre-review Q&A)` 테이블 추가
         (최종 iteration의 이슈 및 반영 결과 기준)

   k. `request.json`의 `tasks` 배열에 태스크 메타데이터 추가 (spec.md 저장 직후, 다중 태스크 시 02, 03... 포함):
      `id`, `title`, `status: "pending"`, `agent`(필수 — 누락 금지), `spec: "tasks/01/spec.md"`, `covers_ac: ["AC-001", ...]`
      - `covers_ac`는 해당 태스크가 담당하는 spec §3 수락 조건 ID 목록으로 채운다 (예: `["AC-001", "AC-003"]`).
   h-exit. **A Gate (PAC Coverage, blocking)**:
      - 실행 조건: `--plan PLN-NNN` 제공 && `pac_trace.enabled == true`
      - 입력:
        - `plan.ids.json`의 PAC 목록 (`id`, `grade`)
        - spec `## 3.3 PAC Mapping` (없으면 fail-safe로 빈 매핑 취급)
      - 판정:
        - MUST PAC 중 `Mapped Spec AC IDs`가 0건인 항목이 1개라도 있으면 **blocking**
        - SHOULD PAC 누락은 warning으로 기록하되 blocking 아님
      - blocking 동작:
        1. request emit 중단 (`spec_ready` 상태 확정 금지)
        2. `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/pac-missing-report.md` 생성
        3. 누락 MUST PAC ID 목록과 보완 가이드 출력
        4. MUST 커버리지 100% 달성 후에만 gate 해제
      - 역방향 검증:
        - spec에만 있고 plan PAC에 매핑되지 않은 AC(`SPEC_ONLY`)는 `scope creep warning`으로 기록한다 (`pac_trace.scope_creep_warning == true`일 때).
      - 이 게이트는 preflight(h-0.6)와 달리 **반드시 blocking**으로 동작한다 (`pac_trace.blocking == true` 기본값).
   l. (A Gate 통과 후) `request.json`의 `status`를 `"spec_ready"`로 업데이트
5. ⚠️ **spec.md 작성 완료 확인** — spec.md 미존재 시 스킬 종료 금지
6. 스펙 요약 표시 + 승인 안내 (두 가지 명령을 모두 명시):
   - 일반: `/mst:approve REQ-NNN`
   - 자율 모드: `/mst:approve -a REQ-NNN` (이후 단계를 중간 승인 없이 자동 실행)
   - **[필수] 할당 에이전트 보고**: `[할당 예정] REQ-NNN → {agent명} ({provider})` 형식으로 명시 (다중 REQ 시 개별 명시)
   - ⚠️ `/mst:approve` 수신 전까지: 코드 수정·파일 편집·커밋 전면 금지
   - **Q&A 선호 요약 백그라운드 트리거 (MANDATORY, 비차단)**:
     - spec.md 저장 완료 직후 아래 입력으로 백그라운드 agent 1회 호출 (`run_in_background: true`)
       - `{PROJECT_ROOT}/.gran-maestro/qa-raw/REQ-NNN.jsonl`
       - `{PROJECT_ROOT}/.gran-maestro/request-context.md`
     - 입력 파일이 없으면 warn 후 skip (차단 금지)
     - 갱신 규칙:
       1. Preference Table을 Source of Truth로 유지 (`id/domain/type/statement/weight/freq/last_seen/tags`)
       2. 강한 표현(절대/반드시/싫어/금지 등) 감지 시 `weight=HIGH` 자동 부여
       3. `request_disputed_preferences`에는 `[DISPUTED]` 태그 반영
       4. Prompt Hints는 Table 기반 파생으로 재생성, 빈도 숫자 직접 인용 금지
       5. 200줄 초과 시 150줄로 압축 (`[DISPUTED]` 우선 제거, `HIGH` 보호)
     - 예시 호출: `Task(subagent_type: "general-purpose", run_in_background: true, prompt: "{REQ-NNN QA 요약 프롬프트}")`
     - 실패 시 warn만 출력하고 승인 안내 흐름을 계속 진행한다
   - `auto_approve=true` 상태에서는 승인 단계를 스킵하고 `Skill(skill: "mst:approve", args: "-a REQ-NNN")`로 자동 진입한다 (`-a` 생략 금지)
   - **세션 중 자율 모드 전환**: spec 요약 표시 후 대기 중 사용자가 "auto로", "자율 모드로", "-a로" 등을 입력하면 `/mst:approve -a REQ-NNN`으로 자동 진입한다


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

## 옵션

- `--auto` / `-a`: 스펙 자동 승인 모드 (사용자 승인 단계 스킵, `auto_approve: true`)
  - 요청 앞(`/mst:request --auto "요청"`) 또는 뒤(`/mst:request "요청" --auto`) 모두 허용
  - `--auto` / `-a` 모드 또는 `config.auto_mode.request=true`(`AUTO_APPROVE=true`)에서는 Spec Pre-review Pass(h-2)를 skip한다
- `--resume REQ-NNN`: 기존 REQ 재개 모드 (신규 REQ 생성 금지)
  - approve DAG 연쇄 호출 계약: `Skill(skill: "mst:request", args: "--plan PLN-NNN --resume REQ-NNN -a")`
  - 하위 호환: `--resume` 없이 `REQ-NNN` 단독 인자도 재개로 해석
- `--prereview`: config 설정 무관하게 Pre-review Pass 강제 실행
- `--no-prereview`: config 설정 무관하게 Pre-review Pass skip

## 예시

```
/mst:request "JWT 기반 사용자 인증 기능을 추가해줘"
/mst:request --auto "로그인 버튼 색상을 파란색으로 변경"
/mst:request -a "로그인 버튼 색상을 파란색으로 변경"
/mst:request "사용자 프로필 페이지에 아바타 업로드 기능 추가" --auto
/mst:request --plan PLN-233 --resume REQ-352 -a
/mst:request --plan PLN-233 -a REQ-352
```

## 문제 해결

- `.gran-maestro/` 생성 실패 → git 저장소 여부 및 쓰기 권한 확인
- `mode.json` 잠금 충돌 → `mode.json.lock` 수동 삭제
- 요청 ID 충돌 → `requests/` 하위 중복 REQ 폴더 검증
