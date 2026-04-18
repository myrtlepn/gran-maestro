---
name: plan
description: "어떤 질문이나 문제든 해결 접근법을 어떻게 가져갈 것인지 계획합니다. 사용자와 대화(또는 -a 자율 모드)로 모호성을 제거하고, 결정사항·범위·제약을 정제한 뒤 실행 가능한 plan.md를 작성합니다."
user-invocable: true
argument-hint: "{플래닝 주제 또는 해결하고 싶은 질문/문제}"
---

# maestro:plan

**목적**: 어떤 질문이나 문제를 다루든, *그 해결책을 어떻게 접근할 것인지*에 대한 계획을 수립합니다.
사용자와 Q&A 대화를 통해 모호성을 제거하고, 합의된 결정사항을 `templates/plan.md` 형식의 plan.md로 저장합니다.

핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.md`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json`
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/auto-decisions.md` (자율 모드 결정 로그용)
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/ambiguity-log.md` (모호성 해소 로그용)
- `{PROJECT_ROOT}/.gran-maestro/captures/CAP-*/capture.json` (status/consumed_at/linked_plan 업데이트용)

**그 외 모든 경로(스킬 파일, 소스 코드, 설정 파일 등)에 대한 Write/Edit 사용은 절대 금지입니다.**

- Stitch 관련 작업은 반드시 `Skill(skill: "mst:stitch", args: "...")`를 통해 실행한다.
- Plan 생략, request 우회 구현 등 의미 게이트 규칙은 아래 `## Gate`를 따른다.

허용 경로 외 수정 요청 시: 즉시 중단 → "plan.md에 기록합니다" 알림 → 의도를 plan.md 요구사항 섹션에 흡수


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

## Gate

### Entry

- `/mst:plan` 호출 시 주제 성격과 무관하게 Step 0.1~4 전체 프로토콜을 실행 대상으로 잠근다.
- 시작 전에 Write/Edit 허용 경로가 `PLN-*` 산출물 및 `CAP-*` 상태 갱신 경로인지 확인한다.
- `AUTO_MODE=false`이면 최소 1회 Q&A 또는 `AskUserQuestion` 기반 분기 근거를 확보한다.

### Exit

- `plan.md`와 `plan.json`이 생성되고 저장 경로/ID(PLN-NNN)가 확정되어야 종료할 수 있다.
- `저장하고 /mst:request 실행` 경로는 `plan.md` 디스크 저장 확인 후 1회만 호출한다.
- 범위 밖 수정 요청은 plan 요구사항으로 흡수 기록하고 코드/설정 파일은 수정하지 않는다.

### 금지 패턴

- "단순하니 plan 생략/축약"을 이유로 Step 0.1~4를 건너뛴다.
- `plan.md` 저장 전에 `mst:request` 호출 또는 직접 구현(코드 수정)으로 전환한다.
- `mcp__stitch__*`를 직접 호출해 스킬 경유 규칙을 우회한다.
- "컨텍스트 압박"을 이유로 sub-plan chain(plan→request→approve→accept)을 우회하여 직접 `codex exec` + master 커밋으로 전환한다. 격리 실행이 필요하면 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 경로를 사용한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "요구사항이 명확해 보이니 Cynefin 분류를 생략해도 된다." | 확인 증거: PM이 분류한 Cynefin 도메인과 적용 전략을 한 줄 통지로 출력한다.
- 합리화 패턴: "질문 없이도 충분하니 Q&A를 건너뛰자." | 확인 증거: `AskUserQuestion` 실행 로그 또는 `auto-decisions.md`의 대응 결정 항목을 남긴다.
- 합리화 패턴: "파일 저장 확인은 생략하고 다음 스킬로 넘어가자." | 확인 증거: `plan.md` 저장 경로와 실행 분기(`저장만/요청 실행`)를 명시한다.
- 합리화 패턴: "WebSearch 결과를 표로 정리했으니 REF 저장은 생략해도 된다." | 확인 증거: WebSearch 실행 횟수와 동일한 횟수의 `Bash(mst.py reference add ...)` 호출 로그가 존재한다.
- 합리화 패턴: "컨텍스트 한계에 도달했으니 체인을 건너뛰고 직접 codex로 끝내자." | 확인 증거: 체인 우회가 필요한 경우 반드시 `mst:codex --dispatch` 또는 `mst:claude --dispatch` 사용 로그가 `auto-decisions.md` 또는 `retrospective.md`에 남아있어야 한다.

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

<!-- @include _shared/hooks-sync.md -->
### Step -1: Hooks 자동 동기화 (MANDATORY, 비차단)

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py hooks sync --silent || true
```

플러그인 버전이 `.claude/hooks/.mst-hook-version`과 다르면 hook 파일을 자동 동기화합니다. 동일 버전이면 no-op(수 ms). 실패해도 워크플로우를 차단하지 않습니다.
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

<!-- @include _shared/reference-lookup.md -->
### Reference Lookup Protocol (MANDATORY)

외부 의존성(라이브러리/API/프레임워크/버전/프로토콜) 관련 판단은 아래 공통 프로토콜을 따른다.

0. **자동 트리거 게이트**:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get reference.auto_search)`로 `reference.auto_search`를 확인한다.
   - `reference.auto_search == true`일 때만 자동 WebSearch를 허용한다.
   - 설정 미존재 시 기본값: `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**:
   - 현재 단계 입력 컨텍스트에서 외부 의존성 키워드(라이브러리/API/프레임워크/버전/프로토콜 계열)를 감지한다.
   - `reference.llm_auto_trigger == true`이면 키워드 매칭과 별도로 PM이 "인터넷에 최신 정보가 있을 법한 내용"이라고 판단할 때 자율적으로 WebSearch를 트리거한다.
   - `reference.llm_auto_trigger == false`이면 기존 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**:
   - (a) `.gran-maestro/references/` 캐시 존재를 `python3 {PLUGIN_ROOT}/scripts/mst.py reference search --keyword "{keyword}" --json`으로 확인한다.
   - (b) TTL 체크: `searched_at + cache_ttl_days` 경과 여부로 `fresh/stale`를 판정한다.
   - (c) cutoff 괴리 체크: 현재 시각 대비 `cutoff_threshold_months` 초과 시 `expired`를 판정한다.
3. **WebSearch 트리거**:
   - 캐시 없음 또는 `stale/expired`일 때만 검색한다.
   - `reference.auto_search == true`일 때만 실행하고, Step당 최대 `max_searches_per_step`을 유지한다.
   - `reference.auto_fact_check == true`이면 검색 결과의 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
   - `reference.auto_fact_check == false`이면 기존 동작(검색 결과를 그대로 다음 단계로 전달)을 유지한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**:
   - WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 `mst.py reference add`를 호출해야 한다.
   - 표/텍스트 결론 요약만으로는 저장이 완료되지 않는다. `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙 요약: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 상세 예시/품질 체크리스트/lazy-Read 트리거는 `skills/plan/SKILL.md`의 Reference Lookup Protocol 4번 항목을 동일 기준으로 따른다.
5. **프롬프트 주입**:
   - 이후 단계 프롬프트 컨텍스트에 `[REFERENCE_CONTEXT]`를 주입한다.
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
<!-- @end-include -->

#### Plan-specific Reference Guidance

1. **키워드 감지 보강**:
   - 현재 plan 텍스트(사용자 요청, 주제, 미결 항목, discussion/ideation 입력 후보)에서 아래 계열 키워드를 감지한다.
   - 계열: `library/framework/api/sdk/protocol/version/dependency` 및 한국어 동의어(라이브러리/프레임워크/의존성/버전).
   - 감지 키워드가 없고 `reference.llm_auto_trigger == false`이면 검색을 생략하고 `references: none` 컨텍스트만 유지한다.
2. **3단계 신선도 체크 보강**:
   - 키워드별 반복으로 수행한다.
   - (a) 캐시 존재 확인: `.gran-maestro/references/`에서 `python3 {PLUGIN_ROOT}/scripts/mst.py reference search --keyword "{keyword}" --json`으로 후보 REF를 조회한다.
   - (b) TTL 확인: `searched_at` 기준 `cache_ttl_days` 이내면 `fresh`, 초과면 `stale`.
   - (c) cutoff 괴리 확인: 현재 시각과 `searched_at`의 차이가 `cutoff_threshold_months`를 넘으면 `expired`로 승격한다.
3. **WebSearch 트리거 보강**:
   - 캐시 없음 또는 freshness가 `stale/expired`인 항목만 검색 대상으로 선정한다.
   - `reference.auto_search == true`일 때만 `WebSearch`를 실행하며, Step당 `max_searches_per_step`를 넘기지 않는다.
4. **REF 저장 확장 가이드**:
   - 결론 한 문단 요약만 저장하지 않는다. `summary`는 한 줄 인덱스, `content.md`는 원문 근거(raw 발췌) 저장 용도다.
   - WebSearch N건 실행 → `mst.py reference add` 최소 N회 호출 (1:1 대응 원칙).
   - 저장 명령 예시: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - `--content` 작성 원칙:
     - 인용/표/코드 스니펫 중 최소 1종 이상을 포함하고, 가능하면 2종 이상을 함께 저장한다.
     - 각 발췌 블록 옆에 `출처 URL`과 `날짜`(또는 버전)를 반드시 함께 남긴다.
     - content.md 길이 상한은 강제 규칙이 아니라 가이드라인으로만 다룬다.
   - 예시 A (인용):
     - `> 인용: "..."` 형태로 핵심 문장을 원문 그대로 발췌
     - 메타데이터: `출처: https://example.com/doc`, `날짜: 2026-04-12`
   - 예시 B (표):
     - 아래처럼 원문 표를 구조 보존해 복사
       `| 열 | 값 |`
     - 메타데이터: `출처 URL: https://example.com/pricing`, `날짜: 2026-04-12`
   - 예시 C (코드 스니펫):
     - API 시그니처/설정 예시는 코드 펜스로 보존
       ```text
       curl https://api.example.com/v1/foo
       ```
     - 메타데이터: `출처 URL: https://example.com/api`, `날짜: 2026-04-12`
   - 신규 REF 품질 체크리스트 (저장 전 점검):
     - Findings: 이번 검색에서 확정적으로 얻은 사실이 명시되어 있는가
     - Quotes: 원문 문장/표현 인용이 포함되어 있는가
     - Data: 수치/표/시그니처 등 재사용 가능한 구조 데이터가 있는가
     - Context: 출처 URL과 날짜(또는 버전), 적용 맥락이 함께 기록되어 있는가
   - PM lazy-Read 트리거 (`content.md Read` 필수):
     - 버전 선택/업그레이드 결정을 할 때
     - 가격/요금 근거를 확정할 때
     - API 시그니처/파라미터를 확정할 때
     - deprecation 여부를 판단할 때
     - 구성 옵션(default/flags/env)을 결정할 때
5. **프롬프트 주입 보강**:
   - 이후 의사결정 프롬프트(질문 생성, ideation/discussion 호출 인자)에 `[REFERENCE_CONTEXT]`를 주입한다.
   - `model_cutoff`는 현재 모델 cutoff 문자열(미확인 시 `unknown`)을 사용한다.
### Step 0.5: 디버그 의도 감지 & 자동 실행

**`--from-debug DBG-NNN` 직접 진입:** `debug/DBG-NNN/debug-report.md` Read (미존재 시 경고 후 Step 1) → `debug_context` 활성화(`linked_debug_id`, `root_cause`, `fix_suggestions`, `affected_files`) → Step 1로 진행

**키워드 기반 감지 (`--from-debug` 없는 경우):** 버그/에러/오류/안됨/고쳐/crash/타임아웃 등 감지 시:
1. "디버그 의도 감지, /mst:debug 먼저 실행" 통지
2. `Skill(skill: "mst:debug", args: "{이슈}")` 즉시 실행 (`--focus` 있으면 전달)
3. `debug-report.md` 완료 대기 후 Read → `debug_context` 보관 (DBG ID/근본 원인/수정 제안 P0~P2/영향 파일)
4. Step 1~2로 진행 시 `debug_context` 활성 상태 유지

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

**미감지 시:** Step 1로 진행.

**`--from-picks` 감지 (--from-debug 처리 후 실행):**

`--from-picks [CAP-001] [CAP-003] "요청 텍스트"` 형태 파싱:
1. args에서 `--from-picks` 키워드 감지
2. `--from-picks` 뒤의 `[CAP-NNN]` 패턴을 모두 추출 → `capture_ids` 배열 보관
3. 각 `capture_ids`에 대해 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json` Read
   - 미존재 시: "[CAP-NNN] 캡처를 찾을 수 없습니다" 경고 출력 후 해당 ID 건너뜀
   - 이미 `consumed` 상태: "CAP-NNN은 이미 consumed 상태입니다" 경고 표시 후 재사용 허용
4. 성공적으로 Read한 캡처 데이터를 `capture_context` 배열에 보관 (ID, url, selector, memo, screenshot 등)
5. `--from-debug`와 동시 입력 시: `--from-debug` 우선 처리(debug_context) → `capture_context`는 보조 컨텍스트로 유지
6. `--from-picks` 미사용 시: `capture_context`는 빈 배열 → 이후 로직 영향 없음 (하위 호환)

### Step 0.75: [CAP-NNN] 자동 감지 (Step 0.5 직후)

Step 0.5 처리 완료 후, `--from-picks` 유무와 무관하게 사용자 입력 텍스트 전체에서 `/\[?CAP-\d{3,}\]?/gi` 패턴 매칭 수행:
1. 매칭된 각 ID에 대해: Step 0.5에서 이미 `capture_context`에 보관된 ID는 중복 Read 하지 않음
2. 신규 매칭 ID만 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json` Read
   - 미존재 시: "[CAP-NNN] 캡처를 찾을 수 없습니다" 경고 출력 후 해당 ID 건너뜀
   - 이미 `consumed` 상태: 경고 표시 후 재사용 허용
3. `capture_context`에 합집합 처리 (ID 기준 중복 제거)
4. 캡처가 5개 초과 시 요약 모드 적용: ID + memo + screenshot_path만 보관 (html_snapshot 생략)
5. 매칭 결과 없으면 `capture_context`는 Step 0.5 상태 유지 → 이후 로직 영향 없음

### 세션 중 자율 모드 전환 (공통)

**어느 Step이든** 사용자 응답에서 다음 패턴을 감지하면 즉시 `AUTO_MODE=true`로 전환합니다:
- 자연어 예시: "auto로 해줘", "자율 모드로", "-a로 해줘", "지금부터 자동으로", "이제 auto로"
- 전환 즉시: `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력
- `AskUserQuestion` 대기 중이었다면: 대기를 종료하고 현재 단계부터 `AUTO_MODE=true` 적용하여 재개
- `AUTO_DECISION_TOTAL`, `AUTO_PM_COUNT` 등 카운터가 미초기화 상태이면 `0`으로 즉시 초기화

### Step 0.1: 자율 모드 감지

1. args 전체 토큰에서 `-a` 또는 `--auto` 존재 여부를 검사:
   - 하나라도 존재하면 `AUTO_MODE=true` (args 어느 위치든 허용)
   - 없으면 `AUTO_MODE=false`
2. `AUTO_MODE=false`인 경우 state guarded fallback을 시도한다:
   - 2.5. args에 `-a`/`--auto`가 없으면, `{PLUGIN_ROOT}/scripts` 경유로
     `read_workflow_state_auto_mode("mst:plan")` 호출
   - 반환값이 bool이면 `AUTO_MODE`에 채택
   - `None`이면 Step 3(config fallback)로 진행
3. `AUTO_MODE=false`인 경우 config를 읽어 `config.auto_mode.plan` 확인:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get auto_mode.plan)` 우선
   - 키가 없으면 `Read(templates/defaults/config.json)` fallback
   - `auto_mode.plan == true`면 `AUTO_MODE=true`
4. `config.auto_mode.confidence_threshold`를 읽어 `CONFIDENCE_THRESHOLD`에 저장:
   - 미설정 시 기본값 `0.7`
   - CLI 플래그(`-a`/`--auto`)가 config보다 우선한다
5. `workflow.high_pass_guard`를 읽어 `HIGH_PASS_GUARD`에 저장:
   - `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get workflow.high_pass_guard)` 우선
   - 키가 없으면 `Read(templates/defaults/config.json)` fallback
   - 미설정 시 기본값:
     - `enabled=true`
     - `confidence_supporting_only=true`
     - `require_external_execution_evidence=true`
     - `require_independent_judgement=true`
     - `block_self_report_only_pass=true`
     - `plan_bypass_requires_explicit_rationale=true`
6. 우선순위는 `args > state(guarded) > config > default(false)`를 적용한다.
7. `AUTO_MODE=true`이면 아래 초기값을 메모리에 보관:
   - `AUTO_DECISION_TOTAL=0`
   - `AUTO_PM_COUNT=0`
   - `AUTO_DISCUSSION_COUNT=0`
   - `AUTO_EXPLORE_DISCUSSION_COUNT=0`
   - `[자율 모드 활성화] confidence threshold: {CONFIDENCE_THRESHOLD}` 출력

### Step 1: 초기화

1. `{PROJECT_ROOT}/.gran-maestro/plans/` 디렉토리 확인, 없으면 생성
2. PLN 번호 채번:
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py counter next --type pln` → PLN-NNN ID 사용
     (최초 실행 시 자동으로 plans/PLN-* 디렉토리 스캔해 counter.json 초기화)
   - **Fallback**: `plans/PLN-*/plan.json` 스캔 → 최대 번호 `+1` (최초: `001`); 파일은 아직 작성 안 함
3. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/` 디렉토리 생성
3.5. `AUTO_MODE=true`이면 워크플로우 state를 즉시 기록한다 (non-blocking):

   ```bash
   MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
     --active true \
     --skill mst:plan \
     --req "" \
     --next-skill mst:request \
     --next-source PLN-NNN \
     --source-skill mst:plan \
     --auto true \
   || echo "[mst:plan] warning: failed to update workflow state" >&2
   ```

   - `AUTO_MODE=false`에서는 이 호출을 실행하지 않는다.
4. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.json` 먼저 작성:

   > ⏱️ **타임스탬프 취득 (MANDATORY)**:
   > `TS=$(python3 {PLUGIN_ROOT}/scripts/mst.py timestamp now)`
   > 위 명령 실패 시 폴백: `python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())"`
   > 출력값을 `created_at` 필드에 기입한다. 날짜만 기입 금지.

   ```json
   {
     "id": "PLN-NNN",
     "title": "플랜 주제",
     "status": "active",
     "created_at": "{TS — mst.py timestamp now 출력값}",
     "linked_requests": []
   }
   ```

5. `AUTO_MODE=true`이면 `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/auto-decisions.md`를 즉시 초기화:

   ```markdown
   # 자율 결정 로그 — PLN-NNN

   > 자율 모드(-a)로 실행됨. 아래 항목들이 PM에 의해 자율 결정되었습니다.

   | 항목 | 결정값 | Confidence | 판단 방식 | 강제 여부 |
   |------|--------|-----------|-----------|-----------|
   ```

   `강제 여부` 값은 `강제(L1)` 또는 `자율`만 사용한다.

### Step 1.2: Cynefin 도메인 분류 & 전략 제안 (MANDATORY)

PM이 요청을 아래 기준으로 4개 도메인 중 하나로 분류한다.

**분류 기준**:
| 도메인 | 신호 |
|--------|------|
| Simple | 기존 패턴 직접 적용 가능, 범위 명확, 유사 구현 전례 다수 |
| Complicated | 전문가 분석 필요, 접근법 2~3가지 후보 존재, 트레이드오프 있음 |
| Complex | 정답 불명확, 실험 필요, 요구사항이 탐색적 성격, 범위가 유동적 |
| Chaotic | 버그/장애/긴급 상황, 즉각 대응 필요 |

**도메인별 plan 전략**:
- Simple → 모호성 루프 간소화 가능 (단, plan 자체를 스킵하는 것은 금지 — "Fast-track"은 모호성 루프 축소를 의미하며, plan 워크플로우 자체를 건너뛰는 것이 아님)
- Complicated → Step 2.5(ideation/discussion) 적극 권장
- Complex → REQ 분리(Step 3.5) 강력 권장, 단계적 탐색 제안
- Chaotic → /mst:debug 먼저 실행 후 plan 재개 안내

**AUTO_MODE 공통 (질문 없이 PM 자율 분류 + 한 줄 통지)**:
PM이 자율 분류하고, 분류 결과와 적용 전략을 한 줄 통지로 출력한 뒤 다음 Step으로 진행한다.
AskUserQuestion으로 도메인 선택을 묻지 않는다. 사용자가 이의를 제기하면 자연어 응답으로 재분류한다.

통지 포맷: `[Cynefin: {도메인}] {적용 전략 요약}`
- Simple: `[Cynefin: Simple] 모호성 루프 간소화, D3 Gate skip으로 진행합니다.`
- Complicated: `[Cynefin: Complicated] ideation/discussion 적극 활용, D3 Gate 필수로 진행합니다.`
- Complex: `[Cynefin: Complex] REQ 분리 강력 권장, 단계적 탐색으로 진행합니다.`
- Chaotic: `[Cynefin: Chaotic] /mst:debug 선행 후 plan 재개합니다.`

**AUTO_MODE=true 추가 동작**:
auto-decisions.md에 분류 근거를 기록한다.

Cynefin 자동 분류 보조 규칙(가드레일):
- 요구사항 텍스트에서 아래 신호를 스캔한다.
  - 트레이드오프 신호 (예: 대안 비교, 장단점 균형, 우선순위 충돌)
  - 외부 의존성 신호 (예: 외부 API/SDK, 외부 팀·벤더·정책 의존)
  - 비결정적 표현 신호 (예: 불확실/상황에 따라/실험 필요/가정 기반)
- 위 3개 신호 중 1개라도 감지되면 `Complicated` 이상으로 자동 플래그한다.
- PM이 `Simple`로 분류했더라도 자동 플래그가 존재하면 Step 2.5의 `discussion` 실행을 권장하고, 수용/미수용 근거를 auto-decisions.md에 기록한다.

**plan.json 저장**:
`"cynefin_domain": "simple" | "complicated" | "complex" | "chaotic"` 필드 추가

### Step 1.5: 유사 Plan 참조 (선택적)

1. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-*/plan.json` 파일 목록 조회
2. 각 파일의 `title` 필드와 현재 요청 주제를 비교 (LLM 의미 유사도 판단)
3. 유사도 상위 3개 후보 식별 (없으면 silent skip)
4. AUTO_MODE=false: AskUserQuestion으로 후보 목록 제시 + 재사용 여부 확인
   - 각 후보: PLN-NNN, 제목, 생성일 표시
   - "재사용할 결정사항 선택" / "참조하지 않음"
   - 선택 시: 해당 plan.md Read → 결정사항·제약·범위를 현재 세션 컨텍스트에 보관
5. AUTO_MODE=true: 유사도가 높다고 판단되면 자동 참조 + auto-decisions.md 기록
6. 참조 대상으로 확정된 각 plan에 대해 해당 `plan.json`의 `linked_intent` 필드를 확인한다.
7. `linked_intent`가 존재하면 아래 명령으로 intent 본문을 Read하여 현재 세션 컨텍스트에 `referenced_intent`로 보관한다.
   ```bash
   python3 {PLUGIN_ROOT}/scripts/mst.py intent get {INTENT_ID} --json
   ```
8. `linked_intent`가 없으면 intent 로드를 생략한다 (graceful skip, 비차단).
9. `mst.py intent get` 명령이 실패하면 warn만 출력하고 `referenced_intent` 보관을 생략한다 (워크플로우 차단 금지).

### Step 2: 초기 분석 & 첫 미결 항목 처리

#### MANDATORY Read: plan-context.md (선호 패턴 컨텍스트)

1. `{PROJECT_ROOT}/.gran-maestro/plan-context.md`를 반드시 Read한다.
   - 파일이 없으면 아래 초기 템플릿으로 생성 후 즉시 Read한다 (비차단):
     ```markdown
     # Plan Q&A 선호 패턴
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
2. `## 선호 패턴 (Preference Table)`에서 현재 주제와 관련된 패턴 최대 3개를 `preference_hints`로 추출한다.
3. Step 2~3의 모든 `AskUserQuestion`에서 과거 선호를 `description`에 명시적으로 인용한다.
   - 권장 형식: `이전에 "{statement}"를 선호하셨습니다. 이번에도 동일하게 적용할까요?`
   - `freq` 숫자 직접 인용 금지 (경향 문장만 사용).
4. 사용자가 인용 선호를 반박하면 해당 statement를 `disputed_preferences`에 수집하고 Step 4 저장 시 백그라운드 요약 입력으로 전달한다.

#### Step 2-R: Reference Lookup 실행 (Step 2 분석 직후, Step 2.5 이전, MANDATORY)

1. Step 2에서 정리된 요청 맥락(주제, 미결 항목, 제약, 우선순위 후보)을 입력으로 `Reference Lookup Protocol`을 실행한다.
2. `reference.auto_search != true`이면 자동 WebSearch는 금지하고, 기존 REF 캐시 조회 결과만 컨텍스트로 사용한다.
3. 생성된 `[REFERENCE_CONTEXT]` 블록을 Step 2.5/Step 3의 모든 판단 프롬프트(ideation/discussion/explore 포함)에 주입한다.
4. 본 단계는 구현 지시가 아니라 **판단 최신화 보조** 목적이다. plan 본문에 검색 결과를 복사하지 말고 REF-ID 중심으로 참조한다.

**`debug_context` 활성 시:** 근본 원인+수정 제안을 초기 컨텍스트로 선반영 → `[디버그 조사 결과 요약]` 블록 표시(근본 원인/수정 제안 P0~/영향 파일) → 구현 범위·우선순위·분리 실행 여부를 핵심 미결 항목으로 정리

**`capture_context` 활성 시 (비어있지 않을 때):** 캡처 데이터를 초기 컨텍스트로 선반영 → `[캡처 참조 요약]` 블록 표시:

```
[캡처 참조 요약]
| ID | URL | Selector | Memo |
|----|-----|----------|------|
| CAP-001 | https://... | .btn-primary | 색상 변경 필요 |

> 스크린샷: `.gran-maestro/captures/CAP-001/screenshot.webp`
```

캡처 컨텍스트를 활용하여 요청의 구체적 맥락(대상 요소, 현재 상태, 사용자 메모)을 초기 분석에 반영한다.
`debug_context`와 `capture_context` 모두 활성이면 둘 다 표시 (debug가 상위, capture가 보조).

**실행 분기:**

- `AUTO_MODE=false`:
  - PM이 요청을 분석하여 해결 접근법과 관련된 핵심 미결 항목(범위·우선순위·방향·접근법 등)을 파악한다.
  - **요청이 단순·명확해 보이더라도 반드시 최소 1회 `AskUserQuestion`으로 대화를 시작한다.** (Fast-track 금지)
    - 대부분 명확하다고 판단되는 경우: PM이 현재 이해와 접근 방향 초안을 제시하고 "이 방향으로 진행할까요?" 형태의 확인 질문을 포함하여 제시
    - 미결 항목이 있는 경우: 가장 중요한 미결 항목 1~2개에 대한 질문 제시
  - `AskUserQuestion` 없이 Step 4로 직행하는 것은 **어떤 경우에도 허용하지 않는다.**
- `AUTO_MODE=true`: Step 2~3에서 `AskUserQuestion` 호출 금지. Step 2에서 우선순위가 가장 높은 미결 항목 1건을 먼저 처리한 뒤 Step 3 반복으로 이어간다. 단, ideation/discussion 호출은 생략 대상이 아니라 결정 품질 확보 절차로 필요 시 즉시 수행한다.

#### [AUTO_MODE 판단 패턴] (Step 2~3, Step 3.8 공통)

프레이밍 원칙:
- `confidence`는 PM의 유능함 점수가 아니라, 현재 근거의 충분도를 표현하는 작업 신호다.
- confidence는 보조 신호이며, high-pass 단독 근거로 사용하지 않는다.
- `discussion/ideation` 호출은 확신 부족의 대체재가 아니라, 결정 품질과 반례 점검을 높이는 표준 절차다.
- 높은 confidence 자체를 discussion 생략의 정당화로 사용하지 않는다.

`AUTO_MODE=true`일 때 각 미결 항목을 아래 순서로 처리:
1. PM이 해당 항목의 confidence score(0.0~1.0)를 자체 산정
2. `workflow.high_pass_guard` Hard Gate를 confidence 분기보다 먼저 평가:
   - self-report만으로 pass를 확정하지 않는다.
   - 입력 증거가 LLM self-report(markdown/json)만 있고 외부 실행 증거가 없으면 confidence와 무관하게 discussion 경로로 강제한다.
   - 분리된 판정 단계(예: discussion/ideation/독립 리뷰)가 없으면 confidence와 무관하게 discussion 경로로 강제한다.
   - 영향 범위·다중 모듈·상태 전이·계약 변경 중 하나라도 감지되면 `risk_signal_review_required`로 기록하고 confidence 단독 high-pass를 금지한다.
   - Hard Gate에 걸린 경우 `auto-decisions.md`에 즉시 행 추가:
     - `| {항목명} | {결정값} | {confidence:.2f} | hard-gate ({reason_token}) | 강제(L1) |`
3. `confidence >= CONFIDENCE_THRESHOLD` AND Hard Gate 통과:
   - PM 자율 결정을 기본 경로로 수행
   - 단, 대안 비교·영향 범위·이해관계자 정렬이 중요한 항목은 confidence가 높아도 Step 2.5의 `discussion/ideation`을 호출해 결정 품질을 보강할 수 있다.
   - `auto-decisions.md`에 즉시 행 추가:
     - discussion/ideation 미호출 시: `| {항목명} | {결정값} | {confidence:.2f} | PM 자율 판단 | 자율 |`
     - discussion/ideation 호출 시: `| {항목명} | {결정값} | {confidence:.2f} | 고신뢰+discussion 보강 | 자율 |`
   - 카운터 업데이트:
     - discussion/ideation 미호출 시: `AUTO_DECISION_TOTAL++`, `AUTO_PM_COUNT++`
     - discussion/ideation 호출 시: `AUTO_DECISION_TOTAL++`, `AUTO_DISCUSSION_COUNT++`
4. `CONFIDENCE_THRESHOLD > confidence >= 0.4`:
   - `Skill(skill: "mst:discussion", args: "{현재 미결 항목} --from-plan --auto")`
   - `consensus.md` 핵심 3~5개 추출 후 결정에 반영
   - `auto-decisions.md`에 즉시 행 추가:
     - `| {항목명} | {결정값} | {confidence:.2f} | discussion 결과 | 자율 |`
   - 카운터 업데이트: `AUTO_DECISION_TOTAL++`, `AUTO_DISCUSSION_COUNT++`
5. `confidence < 0.4`:
   - `WebSearch(query: "{관련 업계 표준/유사 사례 검색어}")` 선행 (필요 시 복수 실행)
   - 검색 결과 반영 후 confidence 재산정
   - 재산정 confidence `>= 0.4`이면 discussion 실행 후 반영
   - 재산정 confidence `< 0.4`이면 PM이 **가장 안전한 선택**으로 자율 결정
   - `auto-decisions.md`에 즉시 행 추가:
     - `| {항목명} | {결정값} | {confidence:.2f} | web-search→discussion 결과 | 자율 |`
   - 카운터 업데이트: `AUTO_DECISION_TOTAL++`, `AUTO_EXPLORE_DISCUSSION_COUNT++`
6. 로그 기록은 plan.md 저장 시 일괄 처리하지 않고, **각 항목 결정 직후 Edit로 즉시 append**한다

**공통:** Step 2 분석 후 자동 ideation/discussion 판단 필요 시 Step 2.5 실행 (confidence 수준과 무관하게 품질 보강이 필요하면 우선 적용 가능)

### Step 2.1: 모호성 해소 루프 (MANDATORY)

> ⚠️ AUTO_MODE=false일 때 모든 항목이 클리어될 때까지 이 루프를 반복한다.
> 루프 종료 조건: 아래 모든 체크리스트 항목에 대해 PM이 "명확함"으로 판단할 때.

#### 추론 가능 시 질문 생략 (MANDATORY, AUTO_MODE=false)

> PM은 아래 체크리스트 항목 각각에 대해, 직전 대화 컨텍스트에서 답을 **추론 가능한지 먼저 판단**합니다. 추론 가능하면 `AskUserQuestion`을 **생략**하고 plan.md 초안에 `(PM 추론)` 표기로 값을 기입합니다. 추론 불가한 항목만 기존 루프(Round N AskUserQuestion)로 질문합니다.
>
> **추론 가능 판정 기준**: 직전 대화 또는 툴호출 결과에 해당 값이 직접 명시되어 있거나, 문맥상 명백히 함의된 경우만 추론 가능으로 본다. 애매하거나 복수 해석이 가능하면 불가 처리.
>
> **`(PM 추론)` 표기 예시**: `WHO: 어드민 사용자 (role=admin) (PM 추론)`
>
> **배치 옵션**: 동일 Step에서 추론 불가 필드가 2개 이상 남을 경우, `AskUserQuestion`의 `questions[]` 배열로 1회 호출에 묶어 발행할 수 있다 (강제 아님).
>
> AUTO_MODE=true 분기는 기존 `[AUTO_MODE 판단 패턴]` 그대로 동작하며, 이 규칙은 AUTO_MODE=false에서만 적용된다.

#### 체크리스트 항목

**5W1H**:
1. WHO: 이 plan의 사용자/수혜자가 구체적으로 특정되었는가?
2. WHAT: 변경·추가·제거할 대상이 정확히 정의되었는가?
3. WHY: 비즈니스 근거/목적이 명시되었는가?
4. WHEN: 완료 시점 또는 트리거 조건이 있는가?
5. WHERE: 영향 받는 화면/시스템/모듈이 특정되었는가?
6. HOW MUCH: 성공을 수치·관찰로 측정할 수 있는가?
7. HOW: 접근 방향이 대략 정해졌는가? (기술 상세 아님 — 전략 방향)

**NFR**:
8. 성능 목표: 응답 시간, 처리량, 부하 등 명시가 필요한가?
9. 보안 요구사항: 인증·인가·데이터 보호 관련 요구가 있는가?
10. 접근성/호환성: 특정 기기, OS, 브라우저, 스크린리더 요구가 있는가?
11. 오류 처리: 실패 시 동작(롤백, 알림, 재시도 등) 정의가 필요한가?

**직관적 추가 항목** (PM이 현재 요청을 읽고 자연스럽게 의문이 드는 것):
- PM이 자율 판단으로 0~3개 추가 작성 (형식: "N. [질문 내용]이 명확한가?")
- 너무 기술적이거나 구현 수준의 질문은 제외한다

#### 루프 실행 절차

```
ROUND = 1
WHILE (미클리어 항목 존재):
  1. PM이 체크리스트 전체를 점검하여 미클리어 항목 목록 추출
  2. 미클리어 항목이 없으면 루프 종료 → Step 2.3으로 진행
  3. 미클리어 항목을 그룹화하여 AskUserQuestion 1회로 최대 4개 항목을 질문
     (선택지 형식이 적합하지 않은 경우 자유 텍스트 답변 유도)
  4. 사용자 답변을 각 항목에 반영
  5. ambiguity-log.md에 Round N 기록:
     - 미클리어 항목 목록
     - 각 항목의 사용자 답변
     - 반영 후 해소 여부 (해소/미해소)
  6. ROUND++
  (루프 재시작)
```

**AUTO_MODE=true**:
- AskUserQuestion 없이 PM이 각 항목을 자율 판단으로 해소
- 각 항목 해소 결과를 auto-decisions.md에 즉시 기록
- 외부 정보가 필요한 항목은 WebSearch 실행 후 판단

**`ambiguity-log.md` 형식**:
```markdown
# 모호성 해소 로그 — PLN-NNN

## Round 1 — {타임스탬프}

### 미클리어 항목
| 번호 | 항목 | 질문 내용 |
|------|------|-----------|
| 1 | WHO | 사용자가 구체적으로 특정되지 않음 |

### 사용자 답변
- WHO: "어드민 사용자 (role=admin인 계정)"

### 해소 결과
| 번호 | 항목 | 해소 여부 |
|------|------|-----------|
| 1 | WHO | 해소 |

## Round 2 — {타임스탬프}
...
```

### Step 2.3: 제약사항 수집 (MANDATORY Q&A)

> ⚠️ AUTO_MODE=false일 때 이 단계는 **추론 불가 항목이 1개 이상 남으면** AskUserQuestion을 반드시 실행한다. 모든 항목이 추론 가능으로 판정되어 `(PM 추론)` 표기로 기입되면 AskUserQuestion을 생략할 수 있다 (아래 "추론 가능 시 생략" 블록 참조). 추론 판정 근거 없이 임의로 생략하는 것은 금지한다.

**AUTO_MODE=false**:
> **추론 가능 시 생략 (MANDATORY)**: PM은 Out-of-scope·기술적 제약·비즈니스 제약·MoSCoW 각 항목에 대해, 직전 대화 컨텍스트에서 값을 추론 가능한지 먼저 판정한다.
> 추론 가능한 항목은 `AskUserQuestion`을 생략하고 plan.md의 `## 제약사항` / `## 우선순위 (MoSCoW)` 섹션에 `(PM 추론)` 표기로 기입한다.
> 추론 불가한 항목만 기존 통합 AskUserQuestion 흐름으로 질문한다. 판정 기준은 Step 2.1의 "추론 가능 시 질문 생략" 블록과 동일.

아래 3가지를 하나의 AskUserQuestion으로 통합 질문한다:

질문 제목: "이 plan의 제약사항을 확인합니다."

1. **하지 않을 것 (Out-of-scope)**:
   - 이번 plan에서 명시적으로 제외할 기능/범위가 있는가?
   - 예: "모바일 대응 제외", "레거시 API 유지" 등

2. **기술적 제약**:
   - 사용해야 하거나 사용하면 안 되는 기술 스택/버전/도구가 있는가?
   - 예: "Node 18 이상", "PostgreSQL 전용", "외부 라이브러리 추가 불가" 등

3. **비즈니스 제약**:
   - 기간, 예산, 법규, 외부 의존성, 팀 역량 등의 제약이 있는가?
   - 예: "2주 내 완료", "GDPR 준수 필수" 등

각 항목에 "해당 없음" 선택지 포함.
답변은 plan.md `## 제약사항` 섹션에 반영한다.

4. **MoSCoW 우선순위** (제약사항 수집 직후 이어서 질문):
   - Must have: 없으면 plan 실패로 간주되는 핵심 항목
   - Should have: 중요하지만 없어도 완료 가능한 항목
   - Could have: 여유 있으면 추가할 항목
   - Won't have (this time): 명시적으로 이번에 제외
   - Cynefin이 Simple인 경우 Must / Won't만 확인하고 나머지 생략 가능
   - 답변은 plan.md `## 우선순위 (MoSCoW)` 섹션에 반영한다

**AUTO_MODE=true**:
PM이 요청 맥락에서 제약사항과 MoSCoW를 자율 추론하고 auto-decisions.md에 기록한다.

### Step 2.4: 테스트 전략 의도 수집 (선택적 Q&A)

> 이 단계는 테스트 방법론 적용 의도만 수집한다. 코드베이스 탐색·구현 수준 결정은 수행하지 않는다.

> ⚠️ **AUTO_MODE 가드 (CRITICAL — 최우선 평가)**:
> `AUTO_MODE=true`이면 아래 `AUTO_MODE=false` 블록 전체를 건너뛰고 즉시 AUTO_MODE=true 블록을 실행한다.
> preset 값(`test_strategy`)을 읽거나 평가하지 않는다.

**AUTO_MODE=true** (최우선 분기):
- PM이 요청 맥락에서 테스트 방법론 적용 여부와 목표 커버리지 필요 여부를 자율 판단한다.
- config의 `plan_qa_presets.test_strategy` 값이 `"ask"` 이외의 preset이면 해당 preset을 자율 판단의 기본값으로 채택한다.
- 판단 근거와 결정 결과를 auto-decisions.md에 기록한다.
- 결과를 plan.md `## 테스트 전략` 섹션에 반영한다.
- **AskUserQuestion 호출 절대 금지.**

**AUTO_MODE=false**:
- `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get plan_qa_presets.test_strategy)` 값을 먼저 확인한다.
  - 키가 없으면 `templates/defaults/config.json`의 `plan_qa_presets.test_strategy`에서 fallback한다.
- 값이 `"ask"`가 아니면 AskUserQuestion을 생략하고 preset을 자동 적용한다.
  - `"apply-80"` → 테스트 방법론 `"적용"`, 목표 커버리지 `"80%"`
  - `"apply-90"` → 테스트 방법론 `"적용"`, 목표 커버리지 `"90%"`
  - `"apply-no-coverage"` → 테스트 방법론 `"적용"`, 목표 커버리지 `"설정 안 함"`
  - `"skip"` → 테스트 방법론 `"적용 안 함"`
- 값이 `"ask"`이면 AskUserQuestion을 1회만 수행한다.
  - 질문: `"이 plan에 테스트 방법론을 어떻게 적용할까요?"`
  - ⚠️ 이 질문은 보조 선택지 규칙 적용 제외 (핵심 선택지 4개 + Other 자동 추가만 사용)
  - 핵심 선택지 4개:
    - `"적용 (80% 커버리지)"`
    - `"적용 (90% 커버리지)"`
    - `"적용 (커버리지 미설정)"`
    - `"적용 안 함"`
  - 자유 입력은 AskUserQuestion의 Other(자동 추가)로 받는다.
- 결과를 plan.md `## 테스트 전략` 섹션에 반영한다.
- `"적용 안 함"` 선택 시 이후 워크플로우는 기존과 동일하게 진행한다 (하위 호환 유지).

### Step 2.45: Loop 종료 조건 수집 (선택적 Q&A)

> 이 단계는 review 반복 루프의 추가 종료 조건을 수집한다. 조건 미설정 시 기존 종료 조건(AC 통과 + max_iterations)을 유지한다.

> ⚠️ **AUTO_MODE 가드 (CRITICAL — 최우선 평가)**:
> `AUTO_MODE=true`이면 아래 `AUTO_MODE=false` 블록 전체를 건너뛰고 즉시 AUTO_MODE=true 블록을 실행한다.
> preset 값(`loop_exit`)을 읽거나 평가하지 않는다. AskUserQuestion 호출 절대 금지.

**AUTO_MODE=true** (최우선 분기):
- PM이 기본 프리셋 `"기존 검증 통과(기본값)"`을 자율 선택한다.
- config의 `plan_qa_presets.loop_exit` 값이 `"ask"` 이외의 preset이면 해당 preset을 자율 판단의 기본값으로 채택한다.
- 판단 근거와 결정 결과를 auto-decisions.md에 기록한다.
- 결과를 plan.md `## Loop 종료 조건` 섹션에 반영한다.
- **AskUserQuestion 호출 절대 금지.**

**AUTO_MODE=false**:
- `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get plan_qa_presets.loop_exit)` 값을 먼저 확인한다.
  - 키가 없으면 `templates/defaults/config.json`의 `plan_qa_presets.loop_exit`에서 fallback한다.
- 값이 `"ask"`가 아니면 AskUserQuestion을 생략하고 preset을 자동 적용한다.
  - `"default_pass"` → 기존 종료 조건(AC 통과 + max_iterations) 유지
  - `"convergence"` → 연속 무변경 수렴 조건 적용
  - `"fixed_n"` → 고정 N회 반복 조건 적용 (`plan_qa_presets.loop_exit_n` 사용, 기본값 3)
- 값이 `"ask"`이면 기존 질문 흐름을 유지한다.
  - AskUserQuestion으로 아래 질문을 먼저 수행한다.
    - 질문: `"이 plan의 반복 검증 종료 조건을 설정합니다."`
    - ⚠️ 이 질문은 보조 선택지 규칙 적용 제외 (핵심 선택지 3개 + Other 자동 추가만 사용)
    - 핵심 선택지 3개:
      - `"기존 검증 통과(기본값)"` — 추가 조건 없이 기존 동작 유지
      - `"연속 무변경 수렴"` — 이전 iteration 대비 새로운 gap/diff가 없을 때 종료
      - `"고정 N회 반복"` — 지정한 반복 횟수 도달 시 종료
    - 자유 입력은 AskUserQuestion의 Other(자동 추가)로 받는다.
  - `"고정 N회 반복"` 선택 시 후속 AskUserQuestion으로 N값을 수집한다.
    - 질문: `"고정 반복 횟수 N을 입력해주세요."`
    - 입력값은 자연수(1 이상)로 수집한다.
  - 첫 선택이 `"연속 무변경 수렴"` 또는 `"고정 N회 반복"` 또는 Other일 때, 복수 조건 AND 조합 여부를 후속 AskUserQuestion으로 확인한다.
    - 질문: `"추가 조건을 더 설정하시겠습니까? (AND 조합)"`
    - 선택지: `"추가 조건 설정"` / `"이대로 진행"`
    - `"추가 조건 설정"` 선택 시 동일한 핵심 선택지 3개(+Other 자동 추가) 질문을 반복하고, `"이대로 진행"` 선택 시 수집을 종료한다.
- 수집된 결과를 plan.md `## Loop 종료 조건` 섹션에 반영한다.

### Step 2.6: 의존성 확인 (MANDATORY)

> ⚠️ AUTO_MODE=false일 때 **추론 불가 항목이 1개 이상 남으면** 반드시 AskUserQuestion으로 확인한다. 모든 항목이 추론 가능으로 판정되어 `(PM 추론)` 표기로 기입되면 AskUserQuestion을 생략할 수 있다 (아래 "추론 가능 시 생략" 블록 참조).

**AUTO_MODE=false**:
> **추론 가능 시 생략 (MANDATORY)**: PM은 선행 필요(blockedBy)/연관(relatedTo)/없음 판단에 대해 직전 대화 컨텍스트에서 추론 가능한지 먼저 판정한다. 추론 가능하면 `AskUserQuestion`을 생략하고 plan.md `## 의존성` 섹션에 `(PM 추론)` 표기로 기입한다. 판정 기준은 Step 2.1 규칙과 동일.

질문: "이 plan이 의존하거나 연관된 다른 작업이 있나요?"

- 선행 필요 (blockedBy): 이 plan 시작 전 완료되어야 하는 PLN/REQ
- 연관 (relatedTo): 영향을 주고받는 PLN/REQ
- "없음" 선택지 포함

수집된 의존성은 plan.md `## 의존성` 섹션에 기록:
```markdown
## 의존성
- 선행 필요: PLN-NNN (제목) — 이유
- 연관: REQ-NNN (제목) — 이유
- 없음
```

**AUTO_MODE=true**:
PM이 자율 판단 후 auto-decisions.md에 기록한다.

### Step 2.5: PM 자동 판단 (해석 B)

> ⚠️ **기술 스택·아키텍처·코드 수준 접근법 결정은 plan 단계에서 수행하지 않습니다.**
> 코드베이스 탐색이 필요한 기술적 결정은 /mst:request 단계에서 코드 탐색 결과를 바탕으로 수행됩니다.
> plan에서 다루는 결정은 **비즈니스 방향·사용자 경험·범위·우선순위** 수준에 한정합니다.

아래 조건 해당 시 첫 질문 전에 PM이 먼저 실행:
- **ideation**: 접근법 2개 이상+트레이드오프 모호, 사용자 경험/비즈니스 방향 결정, PM 확신 낮음
- **discussion**: 복잡한 트레이드오프+팀 합의 필요, 비즈니스 리스크 큰 결정

트리거 시: "[이유]로 [ideation/discussion] 먼저 실행" 통지 → `Skill(skill: "mst:ideation/discussion", args: "{주제}")` → 핵심 3~5개 요약 → 후속 결정 문맥으로 선반영 (`AUTO_MODE=false`면 질문, `AUTO_MODE=true`면 자율 판단 패턴)

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

동일 세션/주제/타입 완료 이력 있으면 새 세션 생성 없이 기존 결과 재사용 (동일 형식으로 재질문).

> **[전역 규칙] AskUserQuestion 선택지 구성 (API 제약: 최대 4개 옵션)**
> `AUTO_MODE=false`에서 콘텐츠 결정 관련 모든 `AskUserQuestion` 호출 시:
> - **핵심 선택지**: 최대 3개 (실제 답변 옵션)
> - **보조 선택지**: 반드시 1개 — ideation · discussion · explore 중 현재 맥락에 가장 적합한 것을 택 1
> - **Other**: 자동 추가 (사용자 자유 텍스트 입력용, 수동 포함 금지)
> - Step 4 저장 액션 AskUserQuestion은 보조 선택지 규칙 제외.

> **[전역 규칙] 선택지 장단점·추천 필수 — 모든 다중 선택지 AskUserQuestion 공통**
> 선택지가 2개 이상인 모든 `AskUserQuestion`에서 각 선택지에는 **장점·단점·추천하는 상황**을 `description` 또는 `markdown` 필드에 **반드시 포함**한다.
> 사용자에게 여러 선택지를 제시한다는 것은 각 선택지의 장단점이 다르다는 의미이므로, 어떤 Step이든 예외 없이 적용한다.
> - 내용 없이 라벨만 있는 빈 선택지(예: "직접 설명할게", "자유 입력")는 **절대 금지**한다.
> - 적용 제외: 순수한 예/아니오 확인 질문, 정보 수집형 자유 텍스트 질문에만 한정한다.
> - 구체적인 표현 형식은 아래 "선택지 장단점 표현: 2가지 유형"을 따른다.

### Step 3: 반복 정제

- `AUTO_MODE=false`: 사용자 답변 반영해 PM이 추가 질문 필요성 자율 판단, 핵심 결정 사항이 명확해질 때까지 반복
- `AUTO_MODE=true`: 사용자 질문 없이 PM이 미결 항목을 순차 처리하고, 각 항목마다 `[AUTO_MODE 판단 패턴]`을 적용해 결정/로그 기록을 완료할 때까지 반복
- `AUTO_MODE=false`에서만 모든 질문은 `AskUserQuestion`으로 **동시 1개만**; **총 옵션 최대 4개** (API 하드 제한: 핵심 3개 + 보조 1개, Other는 자동 추가)
- **보조 선택지 (`AUTO_MODE=false`, 반드시 1개 포함 — 생략 불가)**:
  PM이 현재 질문 맥락에 가장 적합한 것을 **3가지 중 1개만** 선택:
  - `"다각도 의견 모으기 (ideation)"` — 접근법이 2개 이상이고 트레이드오프가 불명확할 때
  - `"팀 토론으로 합의 찾기 (discussion)"` — 복잡한 비즈니스 결정으로 합의가 필요할 때
  - `"코드베이스 탐색 + 웹검색 (explore)"` — 관련 파일·현재 구현·패턴 파악 및 외부 사례 검색이 필요할 때

#### Step 3.2: 사용자 선택 기반 재질문 흐름 (`AUTO_MODE=false`)

고정 선택지 선택 **또는 사용자가 텍스트로 직접 ideation/discussion/explore 요청** 시 현재 주제로 해당 스킬 실행:

> ⚠️ **직접 요청 감지**: 사용자가 "discussion 해줘", "ideation 돌려줘", "explore 해줘", "코드 찾아줘", "웹 검색해줘", "사례 찾아줘" 등 텍스트로 직접 요청한 경우에도 고정 선택지 선택과 동일하게 이 흐름을 따른다. 스킬 실행 후 반드시 Step 3으로 복귀해야 한다.
>
> `AUTO_MODE=true`에서는 본 절의 재질문 흐름 대신 `[AUTO_MODE 판단 패턴]`을 사용한다.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

**ideation/discussion 선택 시:**
- `Skill(skill: "mst:ideation/discussion", args: "{현재 질문 주제} --focus {관련 분야}")`
- 동일 세션/주제/타입 이력 있으면 재사용 (재실행 방지)
- 완료 후 `synthesis.md`/`consensus.md` Read → 핵심 3~5개를 `[AI 팀 의견 요약]`으로 표시 → **즉시 같은 턴에서** Step 3으로 복귀하여 원 질문 동일 포맷으로 `AskUserQuestion` 재실행 (plan 흐름 종료 금지)

**웹 검색 선택 시:**
- `WebSearch(query: "{현재 질문과 관련된 업계 표준/유사 사례/대안 검색어}")` (필요 시 복수 실행)
- 검색 결과 핵심을 `[외부 리서치 결과]`로 요약 표시 → **즉시 같은 턴에서** Step 3으로 복귀하여 원 질문 동일 포맷으로 `AskUserQuestion` 재실행 (plan 흐름 종료 금지)

**explore 선택 시:**
- `Skill(skill: "mst:explore", args: "{현재 질문 주제} --focus {관련 파일/기능}")`
- `WebSearch("{현재 질문 주제} 사례 구현 패턴")` 로 외부 사례·대안 솔루션 검색
- 완료 후 `explore-report.md` Read → 탐색 결과 핵심을 `[코드베이스 탐색 결과]`로, 웹 검색 결과를 `[웹 검색 결과]`로 각각 요약 표시 → **즉시 같은 턴에서** Step 3으로 복귀하여 원 질문 동일 포맷으로 `AskUserQuestion` 재실행 (plan 흐름 종료 금지)

#### 시각적 미리보기 활용 (UI/레이아웃 선택 시)

UI 레이아웃/컴포넌트 구조/화면 흐름/정보 밀도 비교가 필요한 단일 선택(`multiSelect: false`) 시 각 옵션에 ASCII 도식 첨부:
- **`description`**: 짧은 텍스트 설명 (하단 표시)
- **`markdown`**: ASCII 도식 (우측 미리보기 패널)

ASCII 도식 작성 규칙:
```
┌─────────────┐   ← 박스로 영역 구분
│  컴포넌트    │
│  ┌────────┐ │   ← 중첩 구조 표현
│  │  내부  │ │
│  └────────┘ │
└─────────────┘
[버튼A] [버튼B]   ← 인라인 요소
─────────────────  ← 구분선
```

> ⚠️ `multiSelect: true` 질문에서는 미리보기 패널이 비활성화되므로
> 복수 선택이 필요한 경우엔 단일 선택 질문 여러 개로 분리하거나 텍스트 설명으로 대체한다.

#### 선택지 장단점 표현: 2가지 유형

선택지가 2개 이상인 모든 `AskUserQuestion`에서, 각 선택지는 아래 **2가지 유형 중 하나**를 반드시 적용한다.
선택지가 여러 개 존재한다는 것 자체가 각 선택지의 장단점이 다르다는 의미이므로, Step·주제와 무관하게 일관 적용한다.
적용 제외: 순수한 예/아니오 확인, 정보 수집형 자유 텍스트 질문에만 한정한다.

**유형 1: description 3줄형 + ASCII 도식 (UI/레이아웃 선택 시)**

`description`에 키워드 요약, `markdown`에 ASCII 도식을 배치한다.

```
description: |
  [장점] 콤마 구분 키워드 나열
  [단점] 콤마 구분 키워드 나열
  [적합] 콤마 구분 키워드 나열
markdown: |
  ┌─────────────┐
  │  컴포넌트    │
  └─────────────┘
```

- 이모티콘 사용 금지 — 반드시 `[장점]`, `[단점]`, `[적합]` 대괄호 텍스트 태그를 사용한다.
- `[적합]`은 선택적이다. 적합 상황이 불명확하면 `[장점]`/`[단점]` 2줄만으로 충분하다.

**유형 2: 간결한 description + markdown 상세 설명 (그 외 트레이드오프 선택 시)**

`description`에는 한 줄 요약만 쓰고, `markdown`에 장단점·근거·PM 추천 의견을 자세하게 서술한다.
키워드 나열이 아닌 **문장 단위로 충분히 설명**하여 사용자가 선택 근거를 명확히 이해할 수 있게 한다.

```
description: "타입 안전성과 IDE 지원이 우수하나 초기 설정 비용이 있는 접근"
markdown: |
  ## 장점
  - **타입 안전성**: 컴파일 타임에 타입 오류를 잡아내므로 런타임 버그가 크게 줄어듭니다.
    특히 여러 모듈 간 인터페이스가 복잡한 현재 프로젝트 구조에서 효과가 큽니다.
  - **리팩토링 용이**: IDE가 자동으로 참조를 추적하므로 대규모 리네임이나
    시그니처 변경을 안전하게 수행할 수 있습니다.

  ## 단점
  - **초기 설정 비용**: tsconfig 구성, 빌드 파이프라인 조정, 기존 JS 파일의
    점진적 마이그레이션 등 도입 초기에 작업량이 발생합니다.
  - **빌드 단계 필요**: 트랜스파일 과정이 추가되어 핫 리로드 속도에
    약간의 영향이 있을 수 있습니다.

  ## PM 추천 의견
  현재 프로젝트의 규모와 장기 유지보수 계획을 고려하면 이 접근이 적합합니다.
  초기 설정 비용은 1~2일 내에 회수 가능하고, 이후 개발 속도 향상이 기대됩니다.
```

- `markdown` 상세 설명은 **유형 2 적용 시 반드시 작성**한다 (생략 금지).
- PM은 각 장단점 항목을 1~2문장으로 구체적 근거와 현재 프로젝트 맥락을 포함하여 서술한다.
- `## PM 추천 의견` 섹션으로 PM의 판단과 근거를 명시한다.

### Step 3.3: INVEST Gate

Q&A 반복 종료 판단 직후, DoR-Discovery(Step 3.4) 진입 전에 INVEST 6개 기준을 PM이 내부 점검한다.
**미충족 기준만** 사용자에게 질문하고, 충족 기준은 Q&A 없이 자동 통과한다.

**기준별 PM 판단 질문**:

| 기준 | 전체명 | PM 내부 판단 질문 |
|------|--------|-------------------|
| I | Independent | 이 작업이 다른 플랜/REQ의 완료 없이 독립적으로 실행 가능한가? |
| N | Negotiable | 세부 구현 방식이 협상·조정 가능한 상태인가? (방향은 정해졌어도 세부는 유연한가?) |
| V | Valuable | 사용자 또는 비즈니스에 명확한 가치가 있는가? (왜 필요한지 답할 수 있는가?) |
| E | Estimable | 작업 크기(복잡도/범위)를 대략적으로 추정할 수 있는가? |
| S | Small | 단일 REQ에서 완결 가능한 범위인가? (너무 크거나 모호하지 않은가?) |
| T | Testable | 완료 여부를 검증할 수 있는 기준(AC)이 정의 가능한가? |

**`AUTO_MODE=false` 처리**:
- 충족 기준: Q&A 없이 통과
- 미충족 기준: `AskUserQuestion`으로 아래 포맷에 따라 질문
  - 질문 헤더: `[INVEST 검증 — {기준약어}: {기준 전체명}]`
  - 선택지 유형: 단답형(예/아니오) 또는 복수 선택지 (PM 판단으로 질문 성격에 맞게 구성)
  - 예시: `[INVEST 검증 — S: Small]` 헤더와 함께 "단일 REQ로 완결하기 너무 클 수 있습니다. 범위를 조정하거나 두 REQ로 분리할까요?" 형태로 제시
  - **S 미충족**: 분리 동의 시 Step 3.5 REQ 분리 흐름으로 연계; 유지 선택 시 S 기준 예외 통과 후 근거를 plan.md에 기록
  - **T 미충족**: 답변 반영 후 Step 4에서 AC 초안 섹션 작성을 명시적으로 유도
  - **I/N/V/E 미충족**: 답변을 plan 결정사항에 반영하고 Gate 재점검 없이 진행

**`AUTO_MODE=true` 처리**:
- 모든 기준을 `[AUTO_MODE 판단 패턴]`으로 처리 (사용자 Q&A 없이 PM 자율 판단)
- 각 기준 판단 결과를 `auto-decisions.md`에 즉시 기록:
  `| INVEST-{기준약어} | {충족/미충족 — 조치 내용} | {confidence:.2f} | PM 자율 판단 | 자율 |`
- S 미충족 자율 처리: PM이 범위 축소 또는 분리 방향을 결정하고 Step 3.5 연계
- T 미충족 자율 처리: PM이 AC 초안을 직접 작성하여 plan 초안에 반영

**전체 충족 시**: 별도 Q&A 없이 Step 3.4 (DoR-Discovery Gate)로 진행

### Step 3.4: DoR-Discovery Gate

Q&A 종료 판단 직후, plan 초안 진행 전 5개 항목을 PM이 내부 점검한다.
모든 항목이 충족되면 Step 3.5로 진행하고, 하나라도 미충족이면 처리 방식에 따라 분기한다.

**체크리스트**:
1. **문제 정의**: 무엇이 없거나 잘못되었는지 명확한가?
2. **대상 사용자/시스템**: 이 plan의 수혜자/영향 범위가 특정되었는가?
3. **성공 지표 초안**: 완료됐음을 측정할 수 있는 결과가 정의되었는가?
4. **제외 범위 초안**: 이번에 다루지 않을 항목이 식별되었는가?
5. **핵심 리스크 Top3**: 구현 실패 또는 범위 이탈의 주요 위험이 파악되었는가?

**미충족 처리**:
- `AUTO_MODE=false`:
  ```
  WHILE (미충족 항목 존재):
    1. 미충족 항목 목록 출력
    2. AskUserQuestion으로 각 항목을 보완할 정보 질문 (항목당 1회)
    3. 답변 반영 후 체크리스트 재점검
    4. 모든 항목 충족될 때까지 반복 (루프 종료 금지)
  ```
- `AUTO_MODE=true`: PM이 미충족 항목을 자율 결정하고 `auto-decisions.md`에 기록 후 진행

### Step 3.5: REQ 책임 분리 (PM 필수 검토)

#### REQ 분리 원칙

아래 중 하나라도 해당 시 분리 실행 제안 후 사용자 동의 요청:
- 레이어 혼재(백엔드+프론트), 도메인 혼재, 독립 완결 가능, 타임라인 차이, 영역 충돌 위험, 리스크 성격 차이

분리 확정 시: plan.md `## 분리 실행` 섹션에 각 책임 단위 기록.

규모가 클수록 REQ를 더 적극적으로 분리해야 합니다. 규모가 크다는 이유로 mst:request를 건너뛰고 직접 구현하는 것은 절대 금지합니다.

> **태스크 분해는 plan 범위 밖**: REQ 내부의 태스크 분해는 mst:request 단계에서 코드베이스 탐색 결과를 바탕으로 결정합니다. plan에서는 다루지 않습니다.

### Step 3.8: Strategic Review Pass (선택적)

> ℹ️ 이 단계는 코드베이스 탐색이 아닌 **전략적 의사결정 지원**에 초점을 맞춥니다.
> 기술 구현 수준의 검토는 /mst:request 단계의 Spec Pre-review Pass에서 수행됩니다.

#### 3.8.0: config 읽기 및 enabled 확인

Bash(`python3 {PLUGIN_ROOT}/scripts/mst.py config get plan_review`) → plan_review 섹션 취득
plan_review 섹션이 없으면 → Read(templates/defaults/config.json) → plan_review 섹션으로 fallback
`enabled` 값을 메모리에 보관

- **enabled == false**: 이 단계 전체 skip → Step 4로 진행
- **enabled == true**: 아래 3.8.1부터 실행

#### 3.8.1: PM 내부 초안 작성

3.8.1 시작 직후 `{PROJECT_ROOT}/.gran-maestro/plan-context.md`를 다시 Read하여 최신 선호 패턴을 전략 검토 입력으로 병합한다.
- `weight=HIGH` 패턴은 전략 선택의 우선 제약으로 반영한다.
- `[DISPUTED]` 태그 패턴은 기본 추천안에서 제외하고, 필요 시에만 "검증 필요 패턴"으로 별도 표기한다.

Q&A 대화 내용을 바탕으로 PM이 플랜 초안 텍스트를 작성한다 (디스크 미저장, 메모리 내).
이 초안은 Step 4에서 최종 제시될 내용의 초기 버전이다.

#### 3.8.2: 전략적 분석 수행

PM이 plan 초안을 바탕으로 아래 세 관점에서 직접 분석을 수행한다:

**관점 A — 의도 검증 (Intent Validation)**:
- 사용자가 요청한 것(what)과 실제로 필요한 것(why)의 갭 분석
- "X를 원한다고 했지만, 진짜 문제는 Y일 수 있다" 패턴 탐지
- 근본 문제(root problem)가 plan.md의 범위에서 해결되는지 확인
- **JTBD 근본 과업 확인**: "사용자/시스템이 이 plan을 통해 완수하려는 근본 과업(Job)은 무엇인가?"를 명시적으로 확인한다. 근본 과업이 plan 범위에서 해결되지 않으면 `MAJOR` 이슈로 분류한다.

**관점 B — 외부 리서치 (Industry Research)**:
필요하다고 판단되는 항목에 한해 `WebSearch` 도구로 검색 (전체 실행 강제 아님):
- 업계 표준·권장 패턴: `WebSearch(query: "{plan 주제} best practices")`
- 대안 솔루션: `WebSearch(query: "{plan 주제} alternatives comparison")`
- 흔한 함정: `WebSearch(query: "{plan 주제} common pitfalls problems")`

**관점 C — 범위 위험 감지 (Scope Risk Detection)**:
- 범위 크립(scope creep) 징후 탐지: 요구사항이 점진적으로 확장될 조짐
- "이 범위로 가면 나중에 Y 문제가 생길 수 있다" 전략적 경고
- plan 외부로 번지는 영향 범위 예측

#### 3.8.3: 이슈 분류 및 처리

PM이 분석 결과를 이슈로 분류:
- `CRITICAL:` 방향이 근본적으로 잘못됨 (의도 오해, 심각한 범위/전략 문제)
- `MAJOR:` 중요한 대안·리스크가 고려되지 않음
- `MINOR:` 참고할 만한 외부 사례·패턴
- `NO_ISSUES`: 전략적 문제 없음

이슈 처리:

**오실레이션 탐지 (재정제 전 PM 판단 — `AUTO_MODE=false`)**:

사용자 답변을 반영하여 재정제하기 전, PM이 먼저 아래를 질적으로 판단한다:
- 이번 이슈 목록이 직전 라운드 이슈 목록과 실질적으로 동일한가?
  (표현이 달라도 내용·핵심이 같으면 "동일"로 판단)
- 동일하다고 판단되면: 에이전트 재dispatch 없이 반복 이슈를 하나로 합성하여 사용자에게 에스컬레이션한다.
  → "같은 이슈가 반복되고 있습니다. 방향을 결정해 주세요." 형식으로 CRITICAL 수준으로 올린다.
- 동일하지 않으면: 아래 정상 재정제 흐름으로 진행한다.

> ⚠️ 이 판단은 수치 계산 없이 PM의 질적 판단으로만 수행한다. 별도 에이전트 호출 금지.

**`AUTO_MODE=false`**:
- CRITICAL/MAJOR 이슈 존재 시: `AskUserQuestion`으로 이슈 제시 + 선택지:
  - 각 이슈를 해소하는 구체적 옵션
  - **"반영 없이 진행"**: 이슈를 무시하고 Step 4로 바로 이동
  - **보조 선택지 필수 포함**: ideation · discussion · explore 중 **1개 반드시 추가** (Step 3 규칙 동일 적용)
  - 사용자 답변 반영하여 PM 초안 재정제
- MINOR 이슈만: PM이 자체 판단으로 plan 초안에 참고 메모로 반영 → Step 4 진행
- NO_ISSUES: 바로 Step 4 진행

**`AUTO_MODE=true`**:
- 모든 이슈를 `[AUTO_MODE 판단 패턴]`으로 처리
- 각 결정은 즉시 `auto-decisions.md`에 기록하고 PM 초안에 반영
- NO_ISSUES: 바로 Step 4 진행

**리스크 레지스터 자동 생성**:
- 이슈 분류 완료 후, 발견된 이슈를 리스크 레지스터 표로 변환한다
- 매핑 규칙: CRITICAL → 가능성/영향 모두 "상", MAJOR → "중", MINOR → "하"
- 이슈 없음(NO_ISSUES): "식별된 리스크 없음" 한 줄만 기재
- plan.md 초안(Step 4)에 `## 리스크 레지스터` 섹션으로 포함:
  ```markdown
  ## 리스크 레지스터
  | 리스크 | 가능성 | 영향 | 완화 방안 |
  |--------|--------|------|-----------|
  | {이슈 설명} | 상/중/하 | 상/중/하 | {PM 제안 완화 방안} |
  ```

Step 3.9 진입 시 초안은 전략적 검토가 반영된 정제 버전이다.

### Step 3.9: D3 Reverse Simulation Gate (MANDATORY)

> 목적: request 단계 진입 전, plan AC(인수 기준 초안)의 해석 분기점과 모호성을 역방향으로 점검해 의도 전달 손실을 차단한다.

#### 3.9.0: D3/PAC Trace config 로드

- `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get d3 pac_trace)`로 `d3`, `pac_trace` 섹션을 읽는다.
- 키가 없으면 `templates/defaults/config.json`의 동일 섹션으로 fallback한다.
- 기본값:
  - `d3.enabled=true`
  - `d3.agents.codex={count:2,tier:"premium"}`
  - `d3.agents.gemini={count:0,tier:"premium"}`
  - `d3.agents.claude={count:0,tier:"economy"}`
  - `d3.cynefin_skip=["simple","chaotic"]`
  - `d3.light_mode=true`
  - `d3.ambiguity_threshold=0.2`
  - `d3.sprint_plan_threshold=0.15` (agile 컨텍스트에서 sprint-plan D3 게이트에 사용, AD-RV-001)
  - `d3.max_escalation_retries=3`
  - `pac_trace.enabled=true`
- `d3.enabled != true`면 이 단계 전체를 skip하고 Step 4로 진행한다.
- 현재 Cynefin 도메인이 `d3.cynefin_skip`에 포함되면 D3를 자동 skip하고 Step 4로 진행한다.
- 현재 Cynefin 도메인이 `complicated` 또는 `complex`이면 D3 실행을 필수로 적용한다.

#### 3.9.1: AC 앵커 정규화 (PAC 임시 앵커)

- plan 초안의 `## 인수 기준 초안` 불릿 목록을 정규화(순서/중복 제거)하여 D3 입력 리스트를 만든다.
- D3 실행 중에는 현재 불릿 순서를 기준으로 `PAC-1..N` 임시 앵커를 메모리에서 부여한다.
- 이 앵커 목록은 D3 프롬프트 앞단에 고정 주입한다.
- Step 4 저장 시 동일 순서를 기준으로 `plan.ids.json`에 영구 PAC를 생성해 드리프트를 방지한다.

#### 3.9.2: light D3 기본 실행 (독립 에이전트)

- D3 실행 에이전트는 config의 `d3.agents`를 기준으로 결정한다 (`debug.agents`, `explore.agents`와 동일 패턴):
  1. `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get d3.agents)`를 우선 사용
  2. 키가 없으면 `templates/defaults/config.json`의 `d3.agents`로 fallback
  3. 둘 다 없으면 기본값 `codex={count:2,tier:"premium"}`, `gemini={count:0,tier:"premium"}`, `claude={count:0,tier:"economy"}` 적용
  4. provider별 `count > 0` 항목만 dispatch 대상에 포함하고, 각 provider의 `count`만큼 독립 실행 엔트리를 생성
  5. 각 실행 엔트리의 모델 tier는 `d3.agents.{provider}.tier`를 사용하고, 모델명은 `config.models.providers.{provider}[tier || default_tier]`로 resolve
- D3는 반드시 **독립 컨텍스트**로 호출한다:
  - 허용 패턴: `Task(subagent_type: "general-purpose")` 또는 `Skill(skill: "mst:codex")` / `Skill(skill: "mst:gemini")` / `Skill(skill: "mst:claude")`
  - 입력 제한: AC 텍스트 + 용어집 + 제약만 전달, plan 대화 맥락은 전달하지 않는다.
- 기본 실행은 `d3.light_mode=true` 기준으로 수행한다 (저비용 모드).
- `complicated`/`complex` 도메인에서는 D3 실행 전에 AC 형식/완결성 micro-screen을 1회 수행한다.
- AC별 출력 필수 항목:
  - `interpretation_branches`: 구현자가 다르게 해석할 수 있는 분기점
  - `ambiguity_type`: `AMBIGUOUS_SUBJECT | AMBIGUOUS_CONDITION | AMBIGUOUS_OUTCOME | MISSING_EDGE_CASE`
  - `is_ambiguous`: `true | false`
  - `confidence`: `0.0~1.0`
- `is_ambiguous=true`로 판정된 AC만 full D3로 escalation한다.
- 동일 AC가 3회 연속 `confidence < 0.4`이면 일반 재시도 대신 아키텍트 리뷰 큐로 escalation path를 전환한다.

#### 3.9.3: D3 blocking 게이트 판정

- 판정 지표:
  - `ambiguous_count` = `is_ambiguous=true`인 AC 개수
  - `ambiguity_ratio = ambiguous_count / total_ac`
  - 임계치:
    - `agile_context_active=true`이면 `d3.sprint_plan_threshold` 우선 사용 (기본 0.15, AD-RV-001 — sprint-plan은 objective detail보다 관대하게 허용)
    - 그 외에는 기존 `d3.ambiguity_threshold` 사용 (기본 0.2)
- `ambiguity_ratio > threshold`이면 request 진입을 차단하고 아래를 수행한다:
  1. `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/d3-findings.md` 생성
  2. 모호 AC 목록 + 유형 + 분기점 + 보완 제안 기록
  3. AC 수정 후 Step 3.9를 재실행 (회귀)
- 임계치 이하이면 D3 통과로 간주하고 Step 4로 진행한다.

#### 3.9.4: 자동 재지시 루프 (AD-RV-003)

임계치 초과 판정 시 사용자 에스컬레이션 대신 자동 재지시 루프를 수행한다. 이 루프는 `agile_context_active=true`일 때만 강제 적용되며, 일반 plan에서도 동일 로직을 재사용할 수 있다.

1. `d3-findings.md` 기록 후 plan 초안 보완을 위한 재지시 메시지 생성:
   - "모호 AC 목록과 보완 제안을 반영해 plan 초안을 수정한 뒤 Step 3.9를 재실행하세요."
2. 재지시 루프 카운터 `d3_redirect_retries`를 증가시키고 3.9.2를 재실행한다.
3. `d3_redirect_retries > d3.max_escalation_retries` (기본 3)가 되면 루프 종료:
   - warning 로그 출력: `"[D3 재지시 소진] {max} 회 재시도 후에도 임계치 초과. 현재 plan으로 진행합니다."`
   - `mst.py agile known-issues add` 호출로 known issue 등록 (agile_context_active=true일 때만):
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues add {AGI_ID} \
       --title "D3 sprint-plan 재지시 소진" \
       --detail "PLN-{NNN} — {max} 회 재시도 후 모호도 임계치 초과. 수동 검토 필요." \
       --severity medium
     ```
   - `d3_redirect_exhausted=true` 플래그를 plan.json에 기록
4. 사용자 에스컬레이션 금지 — 자동 복구 루프만 수행한다 (AD-RV-003, AD-INT-002와 일관).

### Step 4: plan.md 초안 제시, 저장, 요청 연계

> **`(PM 추론)` 수정 경로**: 초안에 `(PM 추론)` 표기로 기입된 항목에 대해 사용자가 "수정 필요"로 지시하면, PM은 같은 턴에서 해당 항목만 반영해 초안을 재제시하고 수정되지 않은 다른 항목에 대해서는 재질문하지 않는다.

#### UI 감지 (Step 4 진입 시)

plan 주제, 요청 텍스트, 결정사항 섹션을 대상으로 아래 두 가지 방식 중 하나라도 해당하면 UI로 판단한다:

**1. 키워드 매칭**: 아래 단어가 포함된 경우
`화면`, `UI`, `페이지`, `대시보드`, `컴포넌트`, `레이아웃`, `프론트엔드`, `디자인`, `화면 설계`, `목업`, `시안`

**2. 의미 판단 (LLM)**: 키워드 없어도 plan 내용상 새 화면/UI 흐름 생성이 필요하거나 기존 화면/UI가 크게 수정된다고 판단되는 경우
- 예: "로그인 흐름 구성", "어드민 메뉴 신설", "결제 단계 추가", "온보딩 프로세스 설계", "기존 대시보드 레이아웃 재구성", "설정 화면 주요 섹션 추가/제거" 등
- 판단 기준: 사용자가 새로운 화면이나 UI 흐름을 만들거나, 기존 화면이 크게 수정되는 상황인가?

- **감지됨 + `AUTO_MODE=false`**:
  - Step 4 저장 액션 AskUserQuestion 전에 아래 질문을 **반드시 1회** 실행한다:
    - 질문: `review 단계에서 브라우저 UI 테스트도 같이 진행할까요?`
    - 선택지:
      - **"브라우저 UI 테스트 진행"**: plan 초안에 `## 브라우저 테스트` 섹션 추가 (`enabled: true`) → **즉시 Step 4.1 (테스트 흐름 수집)으로 진행**
      - **"이번에는 생략"**: plan 초안에 `## 브라우저 테스트` 섹션 추가 (`enabled: false`)
  - 저장 액션 AskUserQuestion 선택지에 4번째 옵션 "스티치로 디자인 시안 보기" 추가
- **감지됨 + `AUTO_MODE=true`**:
  - AskUserQuestion 없이 PM이 `브라우저 UI 테스트 진행(enabled: true)`을 기본값으로 자율 결정하고 `auto-decisions.md`에 근거 기록
  - **즉시 Step 4.1 (테스트 흐름 수집)의 AUTO_MODE=true 분기를 실행**
  - PM이 `mst:stitch`를 자동 호출해 시안을 초안에 반영
- **미감지** → Stitch 단계 없이 진행

#### Agile 컨텍스트 감지 (Step 4 진입 시, MANDATORY + graceful)

1. 현재 plan 입력 args 본문에 아래 3개 태그가 모두 존재하는지 검사한다:
   - `[고정층]`
   - `[활성층]`
   - `[변화층]`
2. 3개 태그가 모두 있으면 `agile_context_active=true`, 없으면 `agile_context_active=false`로 처리한다.
3. `agile_context_active=true`일 때:
   - `[고정층] 목적 파일:` 라인에서 objective.md 경로를 추출해 `objective_context_path`로 보관한다.
   - objective.md를 Read하여 JTBD 요약, 프로젝트 DoD 전체 항목, 성공 지표를 추출해 `objective_context`로 보관한다.
   - objective.md가 없거나 파싱 실패하면 `objective_context_path`만 유지하고 세부 항목은 `[미확인]`으로 표기한다 (워크플로우 차단 금지).
4. `agile_context_active=false`이면 `objective_context` 처리 전체를 skip한다 (하위 호환).

#### Step 4.1: 테스트 흐름 수집 (브라우저 테스트 "진행" 선택 시 MANDATORY)

> 이 단계는 브라우저 테스트 `enabled: true` 확정 직후에만 실행한다.
> `enabled: false`(생략) 또는 UI 미감지 시 이 단계 전체를 skip한다 (하위 호환).

**PM 추론 절차** (AUTO_MODE 공통):

1. plan 대화 맥락(인수 기준 초안, 결정사항, 범위 섹션)에서 아래 두 카테고리의 테스트 흐름을 추론한다:
   - **신규 기능 (new)**: 이번 plan에서 새로 추가/변경하는 기능의 핵심 사용자 흐름
   - **기존 기능 회귀 (regression)**: 이번 변경으로 영향받을 수 있는 기존 기능의 핵심 사용자 흐름
2. 각 흐름은 1줄 설명으로 작성한다 (예: "설정 페이지에서 저장 버튼 클릭 시 변경사항 반영 확인")

**`AUTO_MODE=false`**:

PM이 추론한 테스트 흐름을 아래 형식으로 텍스트 출력한 후 AskUserQuestion으로 확인한다:

```
[예상 테스트 흐름]

신규 기능:
  1. {흐름 설명}
  2. {흐름 설명}

기존 기능 회귀:
  1. {흐름 설명}
  2. {흐름 설명}
```

AskUserQuestion:
- 질문: `"위 테스트 흐름을 확인합니다. 추가할 흐름이 있으면 입력해주세요."`
- 선택지:
  - **"위 흐름으로 확정"**: 현재 목록 그대로 확정 → test_flows에 반영
  - **"흐름 수정 필요"**: 제거하거나 변경할 흐름을 자유 텍스트로 입력 → PM이 반영 후 동일 질문 반복
  - **"코드베이스 탐색 + 웹검색 (explore)"**: 관련 기존 기능을 코드베이스에서 탐색하여 회귀 흐름 보완
- Other(자동 추가): 사용자가 추가 흐름을 자유 텍스트로 입력

사용자가 Other로 추가 흐름을 입력한 경우:
1. 입력된 흐름을 목록에 추가한다
2. 후속 AskUserQuestion: `"추가된 흐름을 반영했습니다. 더 추가할 흐름이 있나요?"`
   - **"더 이상 없음 — 확정"**: 최종 목록 확정 → test_flows에 반영
   - **"흐름 수정 필요"**: 수정 입력 후 반복
   - **"코드베이스 탐색 + 웹검색 (explore)"**: 탐색 후 보완
   - Other: 추가 흐름 입력 → 이 루프 반복

**`AUTO_MODE=true`**:

PM이 자율 추론한 테스트 흐름을 AskUserQuestion 없이 바로 확정한다.
`auto-decisions.md`에 아래 형식으로 기록:
`| 테스트 흐름 수집 | {N}개 흐름 (신규 {X}개 + 회귀 {Y}개) | {confidence:.2f} | PM 자율 판단 | 자율 |`

**test_flows 반영**:

확정된 테스트 흐름을 `## 브라우저 테스트` 섹션에 아래 형식으로 포함한다:

```markdown
## 브라우저 테스트
- enabled: true
- execution_phase: review-pass-a
- tools: playwright | claude-in-chrome | auto
- test_flows:
  - [new] {신규 기능 흐름 1}
  - [new] {신규 기능 흐름 2}
  - [regression] {기존 기능 회귀 흐름 1}
  - [regression] {기존 기능 회귀 흐름 2}
```

각 항목의 `[new]` / `[regression]` 태그는 review 단계에서 테스트 우선순위 및 분류에 사용된다.

1. 대화 내용 반영한 plan 초안 텍스트 제시 (**파일은 아직 작성하지 않음**)
   - **`## 인수 기준 초안` 섹션을 반드시 포함한다**: "이 plan이 완료됐다는 것은:" 프리픽스로 시작하는 불릿 리스트 형식으로 작성한다.
     - 내용은 구현 방법(코드/기술 상세)이 아닌 **관찰 가능한 결과/동작** 중심으로 기술한다.
     - 예시: `이 plan의 구현이 완료됐다는 것은:\n- 사용자가 X 화면에서 Y 버튼을 누르면 Z 결과가 표시된다\n- PM이 직접 브라우저에서 확인 가능한 동작이 존재한다`
     - 이 섹션은 `mst:request --plan PLN-NNN` 실행 시 spec.md의 AC(Given-When-Then) 초안으로 자동 변환된다. 비어있어도 저장은 허용하나 가능한 한 채워서 작성한다.
     - Step 4 저장 시 각 불릿은 순서대로 `PAC-N` ID가 자동 부여되며, 필요 시 `[MUST]`/`[SHOULD]` 등급 태그를 문장 앞에 포함할 수 있다 (미기입 시 MUST로 간주).
     - 각 PAC 항목에는 위험도 태그 `[TIER-A]` 또는 `[TIER-B]`를 반드시 포함한다.
       - 분류 기준: `TIER-A`는 비즈니스 규칙·상태 전이·데이터 변환, `TIER-B`는 UI·문구·설정·저위험 변경.
       - 둘 다 미부여된 항목은 저장 시 기본값 `TIER-B`로 간주한다 (하위 호환).
     - 영향 예상 항목 작성 규칙: 기능 PAC 작성 시 변경 영향이 예상되는 기존 기능/화면/흐름이 있으면 해당 검증 항목을 **독립 불릿**으로 추가하고 문장 앞에 `[IMPACT]` 태그를 포함한다.
     - `[IMPACT]` 항목의 기본 등급은 `[SHOULD]`로 권장한다. 영향도가 높다고 판단되면 PM 재량으로 `[MUST]`를 사용할 수 있다.
     - `[IMPACT]`는 모든 PAC에 1:1로 강제하지 않는다. 영향이 예상되는 항목에만 선택적으로 추가한다.
     - `[IMPACT]` 항목이 0개인 plan은 영향도 절차를 graceful skip하고 기존 PAC 생성/요청 연계 동작을 그대로 유지한다 (하위 호환).
     - 예시: `- [SHOULD] [IMPACT] 기존 설정 화면의 입력 폼이 정상 렌더링되고 저장 기능이 동작한다`
   - **`## 범위 예산 (Appetite)` / `## 제외 범위 (No-go Scope)` 섹션을 반드시 포함한다**: 두 섹션은 선택 항목이며 빈 값 placeholder를 허용한다.
   - `## 제약사항` 섹션 (Step 2.3 수집 결과)
   - `## 우선순위 (MoSCoW)` 섹션 (Step 2.3 MoSCoW 결과)
   - `## 의존성` 섹션 (Step 2.6 수집 결과)
   - `## 리스크 레지스터` 섹션 (Step 3.8.3 생성 결과)
   - **`## Intent (JTBD)` 섹션** (권장 — 생략 시 intent 파일 미생성):
     - When I: [어떤 상황에서]
     - I want to: [무엇을 하고 싶은지]
     - So I can: [어떤 목적/가치를 달성할 수 있는지]
   - **`## Objective 컨텍스트` 섹션** (`agile_context_active=true`일 때만 조건부 생성):
     - objective.md 파일 경로: `{objective_context_path}`
     - JTBD 요약: `{objective_jtbd_summary}`
     - 프로젝트 DoD 전체 항목: `{objective_project_dod_items}`
     - 성공 지표: `{objective_success_metrics}`
     - 섹션 예시:
       ```markdown
       ## Objective 컨텍스트
       - objective.md: {objective_context_path}
       - JTBD 요약: {objective_jtbd_summary}
       - 프로젝트 DoD:
         - {objective_project_dod_item_1}
         - {objective_project_dod_item_2}
       - 성공 지표:
         - {objective_success_metric_1}
         - {objective_success_metric_2}
       ```
     - `agile_context_active=false`이면 이 섹션을 생성하지 않는다 (하위 호환).
   - UI 감지 시 `## 브라우저 테스트` 섹션 추가:
     - `enabled: true | false`
     - `execution_phase: review-pass-a`
     - `tools: playwright | claude-in-chrome | auto`
     - `test_flows:` (Step 4.1에서 수집된 흐름 목록, `enabled: true`인 경우에만 포함)
   - `debug_context` 또는 `capture_context` 활성, 또는 `UI 감지됨 + {PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md 존재` 시 `## 연관 컨텍스트` 섹션 포함 — **파일 경로만 기록, 내용 복사 금지**:
     ```markdown
     ## 연관 컨텍스트

     > 상세 내용은 아래 파일을 직접 참조하세요. 내용을 이 파일에 복사하지 않습니다.

     | 유형 | ID | 파일 경로 |
     |------|----|-----------|
     | 디버그 조사 | DBG-NNN | `.gran-maestro/debug/DBG-NNN/debug-report.md` |
     | 캡처 | CAP-NNN | `.gran-maestro/captures/CAP-NNN/capture.json` |
     | 디자인 시스템 | DESIGN.md | .gran-maestro/designs/DESIGN.md |
     ```
     연관된 DBG/CAP ID별로 행을 추가한다. UI 감지됨 + `{PROJECT_ROOT}/.gran-maestro/designs/DESIGN.md` 존재 시 디자인 시스템 행을 추가하고, DESIGN.md가 없으면 해당 행은 추가하지 않는다 (graceful skip). 근본 원인·수정 제안·URL·selector·memo 등 **내용은 일절 기입하지 않는다**.
2. 저장 전 Confidence Score Matrix 자가평가 수행
   - PM이 plan 초안을 아래 4축으로 0.0~1.0 범위에서 자가평가한다.

     | 축 | 질문 | 점수 |
     |----|------|------|
     | Clarity | 요구사항·제약에 모호성/중의적 표현이 없는가? | 0.0~1.0 |
     | Feasibility | 범위 내에서 기술적으로 실현 가능한가? | 0.0~1.0 |
     | Decoupling | REQ 단위가 결합도 낮게 분리되었는가? | 0.0~1.0 |
     | Completeness | 후속 Agent가 코드 작성하기에 정보가 충분한가? | 0.0~1.0 |

   - 점수는 4축 요약 표 형태로 출력한다.
   - **0.5 미만 항목**에는 "수정 후 진행" 권고를 표시한다.
   - `AUTO_MODE=true`에서는 0.5 미만 축을 자율 보완하고 근거를 `auto-decisions.md`에 기록한 뒤 진행한다.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

3. 저장 액션 결정:
   - `AUTO_MODE=false`: `AskUserQuestion`으로 선택지 제시
     - **"저장하고 /mst:request 실행"**: plan.md 저장 후 mst:request 호출 (직접 구현 아님 — REQ 생성+spec.md 작성으로 이동)
     - **"저장하고 /mst:request -a 실행 (자율 모드)"**: plan.md 저장 후 mst:request를 자율 모드(-a)로 호출 — 중간 승인 없이 approve까지 자동 진행
     - **"수정 후 진행"**: 수정 내용 입력 후 Step 4 반복
     - **"저장만 하기"**: plan.md만 저장, mst:request는 수동 실행
       → 저장 완료 후 출력: `{PLN-NNN}으로 저장됨. 다음 명령으로 구현 사양(spec.md)을 작성할 수 있습니다.\n  - 일반: /mst:request --plan {PLN-NNN}\n  - 자율 모드: /mst:request --plan {PLN-NNN} -a` (**절대 /mst:approve를 안내하지 않음**)
       → 즉시 이어서 `AskUserQuestion`: **"지금 /mst:request 실행할까요?"**
         - **"실행"**: `Skill(skill: "mst:request", args: "--plan PLN-NNN {주제}")`
         - **"자율 모드 실행"**: `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")`
         - **"종료"**: 추가 호출 없이 plan 스킬 종료
     - **"스티치로 디자인 시안 보기"** *(UI 키워드 감지 시에만 표시)*: Stitch로 디자인 시안을 생성하고 plan에 통합
   - `AUTO_MODE=true`: `AskUserQuestion` 없이 **"저장하고 /mst:request 실행"** 경로를 기본값으로 즉시 진행 (직접 구현 아님 — REQ 생성+spec.md 작성으로 이동. 규모·복잡도와 무관하게 이 경로만 허용)
4. 저장 선택 시 `plans/PLN-NNN/plan.md` 작성; `debug_context` 활성 시 `plan.json`에 `"linked_debug"` 추가

   #### linked_objective 기록 (agile 컨텍스트 전용, MANDATORY)

   - `agile_context_active=true`일 때만 `plan.json`에 `"linked_objective"` 필드를 추가한다.
   - 값 결정 규칙:
     1. `objective_context_path`에서 `/agile/(AGI-\d+)/objective/objective.md` 패턴으로 AGI ID를 추출한다.
     2. 추출 성공 시: `"linked_objective": "AGI-NNN"` 기록
     3. 추출 실패 시: `"linked_objective": null` 기록 (graceful fallback)
   - `agile_context_active=false`이면 `"linked_objective"`를 기록하지 않는다 (기존 동작 유지, 하위 호환).

   #### AUTO_MODE next_action 기록 (MANDATORY)

   - `AUTO_MODE=true`이고 저장 액션이 `"저장하고 /mst:request 실행"` 또는 `"저장하고 /mst:request -a 실행"` 경로인 경우, `plan.json`에 아래 `next_action` 필드를 **반드시 기록**한다:
     ```json
     {
       "next_action": {
         "expected_skill": "mst:request",
         "source_skill": "mst:plan",
         "source_id": "PLN-NNN",
         "auto_mode": true,
         "project_root": "{PROJECT_ROOT}",
         "created_at": "{TS}"
       }
     }
     ```
   - 같은 조건에서 `{PROJECT_ROOT}/.gran-maestro/tmp/mst-next-action-${PPID}.json`를 Bash로 즉시 생성한다 (plan.json 기록 직후):
     ```bash
     mkdir -p "{PROJECT_ROOT}/.gran-maestro/tmp"
     cat > "{PROJECT_ROOT}/.gran-maestro/tmp/mst-next-action-${PPID}.json" <<EOF
     {"expected_skill":"mst:request","source_skill":"mst:plan","source_id":"PLN-NNN","auto_mode":true,"project_root":"{PROJECT_ROOT}","created_at":"{TS}"}
     EOF
     ```
   - `AUTO_MODE=false` 또는 `"저장만 하기"` 경로에서는 `next_action` 필드를 기록하지 않고 `.gran-maestro/tmp/` 마커도 생성하지 않는다.
   - `.gran-maestro/tmp/` 마커와 `plan.json.next_action` 클리어는 `mst:request` push hook이 authoritative 하게 처리한다 (순차 best-effort).

   #### PAC-N ID 자동 부여 + plan.ids.json 생성 (MANDATORY)

   - 저장 직전 `## 인수 기준 초안`의 불릿 목록을 순서대로 정규화한다.
   - 각 항목에 `PAC-N` ID를 자동 부여한다 (`PAC-1`, `PAC-2`, ...).
   - 등급은 아래 규칙으로 결정한다:
     - 항목에 `[SHOULD]` 태그가 있으면 `grade="SHOULD"`
     - 그 외는 `grade="MUST"`
   - 태그는 아래 규칙으로 결정한다:
     - `[IMPACT]` 태그가 있으면 `tags`에 `"IMPACT"`를 추가한다.
     - `[TIER-A]` 태그가 있으면 `tags`에 `"TIER-A"`를 추가한다.
     - `[TIER-B]` 태그가 있으면 `tags`에 `"TIER-B"`를 추가한다.
     - `[TIER-A]`/`[TIER-B]`가 모두 없으면 기본값 `"TIER-B"`를 `tags`에 추가한다.
     - 기존 태그(`IMPACT`)와 Tier 태그는 독립적으로 공존하며, 기존 등급/태그 동작을 변경하지 않는다.
   - `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.ids.json` 파일을 반드시 생성/갱신한다.
   - 포맷:
     ```json
     [
       { "id": "PAC-1", "text": "...", "grade": "MUST", "tags": ["TIER-B"] },
       { "id": "PAC-2", "text": "...", "grade": "SHOULD", "tags": ["IMPACT", "TIER-A"] }
     ]
     ```
   - 하위호환: 기존 `plan.ids.json` 항목에 `tags` 필드가 없어도 오류로 처리하지 않고 `tags=[]`로 간주한다.
   - `pac_trace.enabled != true`여도 파일 생성은 유지한다 (하위 단계 호환 목적).

   #### Intent 파일 자동 생성 (비차단)

   plan.md 저장 직후, `## Intent (JTBD)` 섹션이 존재하고 비어있지 않으면:
   - `When I`, `I want to`, `So I can` 항목 추출 후 아래 매핑으로 명령 실행:
     - `When I` → `--situation`
     - `I want to` → `--feature`
     - `So I can` → `--goal` 및 `--motivation` (동일 값 사용)
   - Step 4의 `§0 Context Manifest`에서 수집한 관련 파일 목록을 `context_manifest_files`로 보관한다.
   - `context_manifest_files`가 비어있지 않으면 각 파일 경로를 `--file "{파일경로}"` 형태로 intent add 명령에 전달한다.
   - `context_manifest_files`가 비어있으면 `--file` 인자 없이 intent add 명령을 실행한다 (graceful skip, 비차단).
   - 예시 (파일 목록이 있을 때):
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py intent add \
       --plan PLN-NNN \
       --feature "..." \
       --situation "..." \
       --motivation "..." \
       --goal "..." \
       --file "{context_manifest_files[0]}" \
       --file "{context_manifest_files[1]}"
     ```
   - 실행:
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py intent add \
       --plan PLN-NNN \
       --feature "..." \
       --situation "..." \
       --motivation "..." \
       --goal "..."
     ```
   - 반환된 INTENT_ID를 `plan.json`의 `linked_intent` 필드에 기록:
     ```json
     { "linked_intent": "INTENT-NNN" }
     ```
   - `## Intent (JTBD)` 섹션이 없거나 비어있으면 skip (비차단)
   - 명령 실패 시 warn만 출력, 워크플로우 차단 금지

   - `capture_context` 활성 시 **plan.md 저장 시점에 일괄 처리 (atomic)**:
     - 참조된 각 캡처의 `{PROJECT_ROOT}/.gran-maestro/captures/CAP-NNN/capture.json`을 Edit:
       - `status` → `"consumed"`
       - `consumed_at` → 현재 시각 (mst.py timestamp now 또는 fallback)
       - `linked_plan` → `"PLN-NNN"` (생성된 plan ID)
     - 세 필드를 동일 시점(plan.md 저장)에 일괄 업데이트
     - `plan.json`에 `"linked_captures": ["CAP-001", "CAP-003"]` 추가

   #### Q&A 선호 요약 백그라운드 트리거 (MANDATORY, 비차단)

   plan.md 저장 직후 아래를 수행한다:
   - 입력 파일: `{PROJECT_ROOT}/.gran-maestro/qa-raw/PLN-NNN.jsonl`, `{PROJECT_ROOT}/.gran-maestro/plan-context.md`
   - 입력 파일이 없으면 warn 후 skip (워크플로우 차단 금지)
   - 백그라운드 agent를 1회 호출해(`run_in_background: true`) `plan-context.md`를 갱신한다.
     - 예시 호출: `Task(subagent_type: "general-purpose", run_in_background: true, prompt: "{PLN-NNN QA 요약 프롬프트}")`
   - 갱신 규칙:
     1. Preference Table을 Source of Truth로 유지한다 (`id/domain/type/statement/weight/freq/last_seen/tags`).
     2. 강한 표현(절대/반드시/싫어/금지 등) 감지 시 `weight=HIGH`를 부여한다.
     3. Step 2에서 수집한 `disputed_preferences`에는 `[DISPUTED]` 태그를 부여한다.
     4. Prompt Hints는 Table 기반 파생으로 재생성하며, 빈도 숫자를 직접 인용하지 않는다.
     5. 파일 길이가 200줄을 초과하면 150줄로 압축한다.
        - 제거 우선순위: `[DISPUTED]` → `NORMAL + freq=1 + 90일 미갱신` → 유사 statement 병합
        - `weight=HIGH` 항목은 압축 대상에서 제외한다.
   - 실패 시 warn만 출력하고 다음 단계로 진행한다.
5. **"저장하고 /mst:request 실행" / "저장하고 /mst:request -a 실행" 경로**: ⚠️ **plan.md 디스크 기록 확인 후에만** 단 1회 호출 (미저장 상태 호출 절대 금지)
   - `AUTO_MODE=true`: `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")`
   - `AUTO_MODE=false`, 일반 실행: `Skill(skill: "mst:request", args: "--plan PLN-NNN {주제}")`
   - `AUTO_MODE=false`, 자율 모드 선택 시: `Skill(skill: "mst:request", args: "--plan PLN-NNN -a {주제}")`
   - `## 분리 실행` 섹션이 있으면 mst:request가 다중 REQ 자동 생성
   - ⚠️ **spec.md 작성 완료 전 plan 스킬 종료 금지**
6. Stitch 연계 (`AUTO_MODE=false`에서 선택했거나, `AUTO_MODE=true`에서 UI 감지된 경우):
   1. `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {plan 주제}")` 호출
      - ⚠️ `mcp__stitch__*` 도구 직접 호출 절대 금지 — 반드시 위 Skill 도구 경유
   2. 호출 완료 후 생성된 Stitch 프로젝트/화면 정보를 plan 초안에 `## 디자인 시안` 섹션으로 추가:
      - DES-NNN ID + 프로젝트 URL
      - 각 화면: 화면명 + Stitch URL + **html_file 경로** (`{PROJECT_ROOT}/.gran-maestro/designs/DES-NNN/screen-NNN.html`)
      - html_file이 null(미추출)인 경우 해당 행 생략
      - plan.md는 여전히 디스크에 저장되지 않은 초안 상태를 유지
   3. `AUTO_MODE=false`면 Step 4 재표시 (저장/수정 선택 가능), `AUTO_MODE=true`면 저장 경로로 계속 진행
7. `AUTO_MODE=true`이고 plan.md 저장 완료 후 아래 요약을 반드시 출력:

   ```text
   [자율 실행 완료]
   PLN-NNN 플랜이 자율 모드로 완성되었습니다.
   - 총 자율 결정: {AUTO_DECISION_TOTAL}건
   - PM 자율 판단: {AUTO_PM_COUNT}건
   - discussion 사용: {AUTO_DISCUSSION_COUNT}건
   - web-search→discussion 사용: {AUTO_EXPLORE_DISCUSSION_COUNT}건

   자세한 결정 내역: .gran-maestro/plans/PLN-NNN/auto-decisions.md
   ```

## 출력 형식

`templates/plan.md`를 기본 템플릿으로 사용하여 plan.md를 작성합니다.
