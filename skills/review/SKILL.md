---
name: review
description: "구현 완성도를 반복 검토합니다. AC 충족 여부 검증 + 병렬 코드/아키텍처/UI 리뷰 수행. 갭 발견 시 태스크 자동 추가 후 재실행. approve 루프 내에서 자동 호출되거나 /mst:review REQ-NNN으로 직접 실행 가능."
user-invocable: true
argument-hint: "[REQ-ID] [--auto]"
---

# maestro:review

구현 완성도를 반복 검토합니다. spec §3 AC 체크리스트 검증(인컨텍스트)과 코드/아키텍처/UI 리뷰(background 에이전트 병렬)를 동시 수행하여 갭을 탐지하고, 발견 시 태스크를 자동 생성합니다.

## 전제조건 가드 (수동 호출 시)

`/mst:review REQ-NNN` 직접 호출 시 실행 전 아래를 검증합니다.

1. **REQ-ID 필수**: `$ARGUMENTS`에 `REQ-NNN` 패턴이 없으면 "REQ-ID를 지정하세요 (예: /mst:review REQ-001)" 안내 후 종료.
2. **Phase 2 완료 태스크 존재**: `request.json.tasks` 배열에서 `status`가 `committed`, `completed`, `done`, `accepted` 중 하나인 태스크가 1개 이상이어야 실행. 미충족 시 "Phase 2 완료 후 실행하세요" 안내 후 종료.
   - 이 조건은 approve 루프 내 호출 시에는 적용하지 않음 (approve가 `request advance-phase2-if-ready`로 사전 검증).

## Gate

### Entry

- REQ-ID와 수동 호출 전제조건(`committed`, `completed`, `done`, `accepted` 상태 태스크)을 먼저 검증한다.
- RV 회차 메타데이터(`review.json`, `request.json.review_iterations`)를 생성한 뒤 검증을 시작한다.
- Spec AC/Plan AC 및 변경 파일 컨텍스트를 수집해 Pass A 판정 근거를 확보한다.

### Exit

- `pass_a_result`와 `review.json.status`가 확정되어야 종료할 수 있다.
- 현재 회차 `review_iterations[].status`를 `completed`로 갱신하고 `review_summary`를 동기화한다.
- 갭 발견 시 생성된 태스크 ID와 `gap_source`를 기록해 approve 재실행 경로를 명시한다.

### 금지 패턴

- AC가 단순해 보인다는 이유로 Pass A 증거 수집을 생략한다.
- MUST AC FAIL 상태에서 Pass B/수락 경로로 진행한다.
- 도구 미가용(SKIP)을 구현 실패(FAIL)로 오판해 워크플로우를 왜곡한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "AC가 쉬워 보여서 역방향 검증 없이 PASS 처리해도 된다." | 확인 증거: `ac-results.md` 또는 `pass-a-result.md`에 AC별 근거 ref를 남긴다.
- 합리화 패턴: "리뷰 이슈가 경미해 보여 태스크 생성/분기를 생략한다." | 확인 증거: `review_issues_summary`의 severity 카운트와 선택 분기(b/c)를 `review.json`에 기록한다.
- 합리화 패턴: "Intent Trace가 없으니 임의 해석으로 계속 진행한다." | 확인 증거: `intent_fidelity_skip_reason` 또는 `review-intent-fidelity.md` 경로를 명시한다.

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

### Step 1: 초기화

> 이 Step의 목적: 리뷰 반복 회차 메타데이터를 초기화한다 / 핵심 출력물: `RV-NNN` 디렉토리, `review.json`, `request.json.review_iterations` 갱신

1. **RV 채번**: `request.json.review_iterations.length + 1` → 3자리 0패딩 → `RV-001`, `RV-002`, ...
2. **디렉토리 생성**: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/reviews/RV-NNN/`
3. **review.json 생성**:
   ```json
   {
     "id": "RV-NNN",
     "req_id": "REQ-NNN",
     "iteration": N,
     "status": "reviewing",
     "created_at": "<ISO8601>",
     "previous_severity_counts": { "critical": 0, "major": 0, "minor": 0 }
   }
   ```
   - `previous_severity_counts`: iteration 1은 `{0,0,0}`, iteration 2+는 직전 회차 값을 복사 (누락 시 0 fallback).
4. **request.json 업데이트**:
   - `review_iterations` 배열에 `{ "rv_id": "RV-NNN", "created_at": "<ISO8601>", "status": "in_progress" }` 항목 추가 (Step 5 완료 후 `"completed"`로 갱신).
   - `review_summary` = `{ "iteration": N, "status": "reviewing" }` 업데이트.

### Step 2: 컨텍스트 로드

> 이 Step의 목적: AC 검증/리뷰에 필요한 입력 컨텍스트를 수집한다 / 핵심 출력물: AC 목록, 변경 파일 목록, config 기반 실행 파라미터

1. **Spec AC 목록 수집**: 모든 `tasks/NN/spec.md` Read → `## 3. 수락 조건` 섹션에서 AC 항목 추출.
1-b. **Plan AC(PAC) 수집 (source_plan 존재 시)**:
   - `request.json.source_plan` 필드 확인 후 값이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json`을 우선 Read한다.
   - `plan.ids.json` 존재 시: 각 항목의 `id(PAC-N)`, `text`, `grade(MUST|SHOULD)`, `tags?`를 그대로 로드한다 (`tags` 미존재 시 빈 배열로 간주).
   - `plan.ids.json` 미존재 시(레거시 호환): `plan.md`의 `## 인수 기준 초안`을 추출해 `PLAN-AC-N` 임시 ID를 부여한다.
   - `source_plan` 미존재 또는 인수 기준 섹션 자체가 없으면 이 단계 skip.
   - 수집된 Plan AC/PAC는 Spec AC와 **분리하여 관리** (Pass A에서 별도 섹션으로 검증).
1-b-1. **리뷰 전략 결정 (source_plan → plan.json.type → type-strategies.json 체인, MANDATORY)**:
   - `request.json.source_plan` 값이 있으면 `plan.json`을 Read하고 `type` 필드를 확인한다 (`type` 누락/Read 실패 시 `"code"` fallback).
   - `strategy = type_strategies[plan_type] || type_strategies["code"]`; Read/파싱/키 누락 시 `{"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`로 fallback.
1-c. **Spec AC 타입 태그 파싱**: 각 AC 헤더의 `[automatable]`/`[manual]`/`[browser-test]`를 파싱하여 `ac_type`으로 보관 (태그 누락 시 기본값 `manual`).
1-d. **테스트 유형 보조 태그 파싱**: AC 헤더에서 보조 태그를 추가 파싱하여 `ac_test_type`으로 보관.
   - 인식 보조 태그: `[build-check]`, `[lint-check]`, `[unit-test]`, `[integration]`, `[api-test]`, `[e2e-browser]`, `[visual]`, `[performance]`, `[impact-check]`, `[regression-test]`
   - 보조 태그 없으면 `ac_test_type = null`. 복수 보조 태그는 첫 번째만 사용.
   - `[e2e-browser]`는 기존 `browser-test` 실행 분기 재사용. `[impact-check]`는 `impact_reviewer` 라우팅 대상. `[regression-test]`는 regression 검증 대상.
2. **변경 파일 목록 수집**: `git log --name-only` 또는 `git diff <base>..HEAD --name-only` 기반으로 REQ 관련 변경 파일 목록 작성.
2-a. **spec 직접 참조 파일 컨텍스트 확장 (MANDATORY)**:
   - 대상: 각 태스크 `spec.md`의 `## 영향 파일` + `## 관련 파일` 섹션의 직접 경로만 수집 (재귀 확장 금지, 디렉토리는 1-depth만).
   - 우선순위(중복 제거 후): ① `changed_files ∩ spec_direct_refs` ② `## 영향 파일` 전용 ③ `## 관련 파일` 전용.
   - 축약 규칙: `<= 200 lines`는 원문 전체, `> 200 lines`는 `head 80 + keyword 120 + tail 20`.
     - `keyword 120`: AC ID, changed file basename, `Given|When|Then|Test|TODO|FIXME|export|class|function` 매칭 라인 (상한 120줄).
   - 산출물: `spec_reference_files`, `spec_reference_context_block`. 유효 경로 0건이면 graceful skip.
3. **AC별 파일 매핑 준비**: 각 AC 항목과 관련 변경 파일 연결.
4. **Intent lookup (비차단)**: `python3 {PLUGIN_ROOT}/scripts/mst.py intent lookup --files {changed_files}` 실행.
   - 조회된 INTENT가 존재하면 `feature/situation/motivation/goal`을 리뷰어 프롬프트에 의도 위반 체크 컨텍스트로 주입. 결과 없으면 skip (비차단).
4-b. **Intent Trace 컨텍스트 수집 (intent_fidelity 전용)**:
   - 현재 태스크 `spec.md`의 `## 3.2 Intent Trace` 섹션을 `{INTENT_TRACE_SECTION}`으로 보관.
   - `source_plan` 존재 시: `plan.md`의 `## 요청 (Refined)` + `## Intent (JTBD)`를 `{PLAN_INTENT_CONTEXT}`로 보관.
   - `Intent Trace`의 `근거 출처`에 포함된 `docs/` 경로를 Read하여 `{INTENT_DOCS_CONTEXT}`로 보관 (없으면 skip).
   - 섹션 미존재 시: `intent_fidelity_skip_reason = "Intent Fidelity 리뷰 skip (Intent Trace 없음)"` 설정 후 auto-skip.
4-c. **Reference 컨텍스트 수집 (MANDATORY)**:
   - Step 2 입력에서 외부 의존성 키워드를 감지하고 `Reference Lookup Protocol`을 실행한다.
   - 결과를 `reference_context_block`으로 보관해 Pass B 모든 리뷰어 프롬프트에 공통 주입한다.
5. **config 로드**: `Bash(python3 {PLUGIN_ROOT}/scripts/mst.py config get review.roles review.cross_validation intent_fidelity review.max_iterations auto_mode.review auto_mode.max_review_iterations test_enforcement)`로 아래 값을 확인.
   - `review.roles.*` 에이전트 키 (code_reviewer/arch_reviewer/ui_reviewer/intent_fidelity/impact_reviewer/adversarial_reviewer/browser_tester 각각의 agent/tier/enabled)
   - `review.cross_validation`: `enabled`(기본 false), `min_reviewers`(기본 2), `line_proximity`(기본 10)
   - `intent_fidelity`: `enabled`(기본 true), `mode`(기본 `"blocking"`), `should_warning_log`(기본 true), `should_escalation_threshold`(기본 3)
   - `review.max_iterations`(기본 10), `auto_mode.review`(true이면 AUTO_MODE=true), `auto_mode.max_review_iterations`(>0이면 max_iterations override)
   - `test_enforcement` 로드 (하위 호환 MANDATORY): 1순위 config, 2순위 `templates/defaults/config.json`, 기본값 `{enabled:true, backend_tdd:true, web_execution_test:true, exempt_patterns:["*.md","*.json","*.yml","*.yaml","*.txt","*.css"], require_exemption_reason:true}`.
   - 우선순위: `AUTO_MODE`: CLI `--auto` > `config.auto_mode.review` > false. `max_iterations`(AUTO_MODE시): `auto_mode.max_review_iterations` > `review.max_iterations` > 10.

### Step 2.5: Static Validation Gate (MANDATORY)

> 이 Step의 목적: Pass A 진입 전에 정적 실패를 선차단한다 / 핵심 출력물: `static_validation_gate_result`, `static-validation-report.md`

- Step 2 직후 즉시 실행. Step 3(Pass A) 시작 전 완료 필수.
- 모든 하위 검증이 통과해야 `static_validation_gate_result=pass`. 미통과 시 Step 4(Pass B) 진입 금지.
- `static-validation-report.md`에 각 검증의 `Command/Expected/Actual/Exit Code`를 기록한다.

#### TS 타입체크 게이트

- 실행 조건: `changed_files`에 `*.ts`/`*.tsx` 1개 이상 + `tsconfig*.json` 1개 이상 존재.
- 실행: `package.json.scripts.typecheck` 존재 시 `npm run typecheck`, 미존재 시 `npx tsc --noEmit`.
- 실패 처리: `pass_a_result=fail`, `failure_class=implementation`, `static_validation_gate_result=fail` → Step 3/4 skip, Step 6(e) 경로.

#### 빌드 게이트

- 실행 조건: `package.json.scripts.build` 존재.
- 실행: `npm run build`.
- 실패 처리: TS 타입체크 게이트와 동일.

#### spec 참조 파일 존재성 게이트

- 실행 조건: `spec_reference_files.length > 0`.
- 실행: 각 경로에 `test -e <path>`.
- 실패 처리(미존재 1개 이상): `review.json.status="gap_found"`, `gap_source="ac_gap"`, `static_validation_gate_result="gap_found"` → 누락 파일 근거로 갭 태스크 생성 후 Step 6(c) 경로.

#### Step 3/4 연결 규칙 (호환성 보장)

- Step 3 진입: `static_validation_gate_result == "pass"`일 때만 허용.
- Step 4(Pass B) 진입: `pass_a_result=="pass"` AND `static_validation_gate_result=="pass"` AND `coverage_matrix_gate_result==pass` AND `full_backend_test_gate_result in {pass, pass_with_warning}`.

### Step 3: Pass A — 인수 판정 (AC 충족성 검증)

> 이 Step의 목적: AC 충족 여부를 확정해 Pass B 진입 가능성을 결정한다 / 핵심 출력물: `pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`

#### Pass A 타입 분기 (if 1개, MANDATORY)

- `if strategy.review_mode == "fulltext"`: 코드 중심 AC 해석 대신 문서 품질 AC 기준(정확성/완결성/독자적합성)으로 판정. 근거는 `evidence-ledger.md`에 기록.
- `else`: 기존 Pass A 절차를 그대로 적용한다. (변경 금지)

#### evidence-ledger.md 생성 프로토콜 (Pass A 내부, MANDATORY)

- 저장 경로: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/evidence-ledger.md`
- Step 3 시작 시 아래 헤더로 파일을 생성한다.
  ```markdown
  # Evidence Ledger — RV-NNN

  ## Spec AC 검증 증거
  | ID | Type | Command | Expected | Actual | Exit Code |
  |----|------|---------|----------|--------|-----------|

  ## Plan AC (PAC) 검증 증거
  | ID | Type | Command | Expected | Actual | Exit Code |
  |----|------|---------|----------|--------|-----------|
  ```
- Spec AC 기록 규칙 (MANDATORY):
  - `[automatable]` AC: `Test:` 명령 실행 직후 append. `Command`=실행 명령, `Expected`=AC의 Then/Test 기대 결과, `Actual`=stdout/stderr 요약, `Exit Code`=종료 코드.
  - `[manual]` AC: `Command`=`manual-judgement`, `Expected`=AC의 Then 문장, `Actual`=PM 판정 근거, `Exit Code`=`N/A`.
- Plan AC(PAC) 기록 규칙 (MANDATORY):
  - `source_plan`+`plan.ids.json` 있으면 동일 형식으로 append. 없으면 PAC 섹션 skip.
  - PAC의 실행 명령이 없으면 `manual-judgement`로 기록하고 PM 판정 근거를 `Actual`에 남긴다. `Exit Code`=`N/A`.
- append 타이밍 (MANDATORY): 각 AC/PAC의 PASS/FAIL/SKIP 판정 직후 즉시 append (배치 저장 금지). Exit Code 기록은 판정 직후 실제 종료 코드를 사용한다. 기존 `pass-a-result.md`를 대체하지 않는다.

#### test_enforcement 게이트 (Pass A 내부, MANDATORY)

- `test_enforcement.enabled=true`일 때, 소스 코드 변경에 테스트 AC가 누락되면 자동으로 gap 생성.
- 소스 코드 변경 판정: `changed_files` 중 `exempt_patterns`에 매칭되지 않는 파일 1개 이상이면 `source_code_changed=true`. 모두 매칭이면 면제 적용.
- `require_exemption_reason=true`이면 면제 사유를 `ac-results.md` 또는 `review-report.md`에 기록.
- test runner 미감지(`jest|vitest|mocha|pytest` 등) 시 테스트 면제 적용.
- 테스트 AC 존재 판정 (면제 아님 + `source_code_changed=true`): 아래 중 하나라도 충족이면 테스트 AC 존재.
  - `ac_type==browser-test`, `ac_test_type`이 `[unit-test]`/`[integration]`/`[api-test]`/`[e2e-browser]`/`[regression-test]`, AC `Test:`에 테스트 실행 명령 명시.
- 모두 미충족이면: `pass_a_result=fail`, `failure_class=implementation`, `failed_ac_ids`에 `AC-TEST-ENFORCEMENT` 추가, `evidence`에 `"gap: 테스트 미작성 (test_enforcement)"` 기록. MUST/SHOULD 판정 선행 적용.
- `test_enforcement.enabled=false` 또는 키 미존재 시 기존 동작 유지 (graceful fallback).

#### browser-test AC 실행 분기 (Pass A 내부, MANDATORY)

- 대상: `ac_type == browser-test`로 파싱된 Spec AC.
- 저장 경로: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/` (결과: `results.json`, 스크린샷: `screenshots/*.webp`)

실행 순서:
1. `mkdir -p {.../browser-tests/BT-{RV-NNN}/screenshots}` 생성.
2. 실행 모드 결정: `review.roles.browser_tester.agent` 존재 시 `execution_mode=delegated`, 없으면 `execution_mode=pm_direct`.
3. `execution_mode==delegated`이면 browser-test AC 실행을 서브에이전트에 위임한다.
   - 프롬프트를 파일로 저장 후 전달: `Write → {.../reviews/{RV_ID}/browser-tester-prompt.md}`
   - 프롬프트에 포함: 대상 AC 목록, 실행/스크린샷 규칙, 결과 반환 스키마.
   - 에이전트 실패/타임아웃/파싱 실패 시 해당 AC를 `FAIL` 또는 `SKIP(agent_failed)`로 기록 후 계속.
4. `execution_mode==pm_direct`이면 아래 절차를 따른다.
   - 도구 우선순위: 1) Playwright CLI 스킬, 2) Claude in Chrome MCP (`mcp__claude-in-chrome__computer`). 결과를 `tool` 변수에 기록: `"playwright" | "claude-in-chrome" | "unavailable"`.
   - 사전 검증 프로토콜 (MANDATORY, `tool != "unavailable"`일 때):
     - Step 1: 열린 탭 나열/대상 탭 식별 (Claude in Chrome: `tabs_context_mcp`, Playwright: `TEST_URL`로 navigate).
     - Step 2: 사전 스크린샷 캡처 → `screenshots/precheck-{AC-ID}.webp` 저장.
     - Step 3: 주요 선택자 DOM 존재 확인 (Claude in Chrome: `find`, Playwright: `locator`/`waitForSelector`).
     - 1단계라도 실패 시 1회 재시도 후 재시도도 실패 시 해당 AC를 `FAIL` 처리.
   - AC 실행: `Given/When/Then/Test` 그대로 실행, 결과 후 스크린샷 캡처 필수.
     - Playwright: `Skill(skill: "playwright-cli", args: "screenshot --url {TEST_URL} --output {SCREENSHOT_PATH}")`
     - Claude in Chrome: `mcp__claude-in-chrome__computer(action: "screenshot", tabId: {...})` → `python3 -c "import base64,sys; ..."`로 파일 저장.
     - 저장 후 `ls -la {SCREENSHOT_PATH}`로 검증. 실패 시 `results[].screenshot=null` + `[WARN]` 출력.
   - 도구 미가용 시: 해당 AC를 `SKIP(tool_unavailable)`로 기록 (MUST AC라도 `pass_a_failed` 강등 안 함).

- `results.json` 최소 스키마:
  ```json
  {
    "id": "BT-RV-NNN",
    "rv_id": "RV-NNN",
    "created_at": "<ISO8601>",
    "tool": "playwright | claude-in-chrome | unavailable",
    "summary": { "pass": 0, "fail": 0, "skip": 0 },
    "results": [
      { "ac_id": "AC-001", "status": "PASS | FAIL | SKIP", "reason": "...", "screenshot": "screenshots/AC-001.webp", "precheck_screenshot": "screenshots/precheck-AC-001.webp" }
    ]
  }
  ```
- browser-test AC 결과는 `ac-results.md` 근거란에도 반영한다.

자세한 절차: `templates/protocols/pass-a-protocol.md` 참조

#### 테스트 유형 보조 태그 실행 분기 (Pass A 내부, 선택적)

> `ac_test_type`이 설정된 AC에만 적용. `ac_test_type == null`인 AC는 기존 동작.

#### [impact-check] AC DEFERRED 분기 (Pass A 내부, MANDATORY)

- Pass A에서 PASS/FAIL 미확정, `DEFERRED`로 기록 (`ac-results.md`에 `DEFERRED (→ Pass B impact_reviewer)` 명시).
- `DEFERRED` 항목은 MUST/SHOULD 카운트 및 `pass_a_failed` 판정/집계에서 제외.
- `[impact-check]` AC 0건이면 graceful skip.

#### [regression-test] AC 실행 분기 (Pass A 내부, MANDATORY)

- AC `Test:` 필드의 회귀 테스트 명령어 실행. exit code 0이면 PASS, 아니면 FAIL.
- FAIL 시 해당 review iteration을 `pass_a_failed`로 처리 (일반 SHOULD 경고 정책보다 우선). 실패 근거는 `ac-results.md`와 `pass-a-result.md`에 기록.
- `[regression-test]` AC 0건이면 graceful skip.

**보조 태그별 실행 규칙** (공통: AC의 `Test:` 필드 명령어 기반, 도구 미설치 시 `SKIP(tool_unavailable)`):

| 보조 태그 | 실행 방법 | PASS 조건 |
|-----------|-----------|-----------|
| `[build-check]` | `Test:` 빌드 명령 실행 | exit code 0 |
| `[lint-check]` | `Test:` 린트 명령 실행 | 위반 0건 |
| `[unit-test]` | `Test:` 테스트 명령 실행 (커버리지 목표 있으면 `--coverage` 추가) | 전체 PASS + 커버리지 충족 |
| `[integration]` / `[api-test]` | `Test:` 테스트 명령 실행 | 전체 PASS |
| `[e2e-browser]` | browser-test AC 실행 분기 재사용 | 동일 |
| `[visual]` | 비주얼 비교 도구 감지 후 실행 | 도구 정의 기준 |
| `[performance]` | 벤치마크 도구 감지 후 실행 | 도구 정의 기준 |

- 실행 결과는 `ac-results.md` 근거란 반영 + `evidence-ledger.md`에 즉시 append.

---

### Step 3.4: Spec↔Diff Coverage Matrix Gate (MANDATORY)

> 이 Step의 목적: Pass A 직후 AC-ID/PAC-ID 기준의 Spec↔Diff 양방향 커버리지를 기계적으로 검증해 Pass B 진입 누락을 차단한다 / 핵심 출력물: `coverage_matrix_gate_result`, `coverage-matrix.json`, `coverage-matrix.md`

- 진입 조건: `pass_a_result==pass` AND `static_validation_gate_result=="pass"`일 때만 실행. `pass_a_result==fail`이면 skip.
- 산출물 경로: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/coverage-matrix.{json|md}`

#### coverage-matrix.json 스키마 (MANDATORY)

```json
{
  "spec_to_diff": [
    { "id": "AC-001 | PAC-4", "kind": "spec_ac | plan_ac", "grade": "MUST | SHOULD", "ac_type": "automatable | manual | browser-test", "mapped_diff_refs": ["src/module/file.ts#L10"], "is_mapped": true, "unmapped_reason": "" }
  ],
  "diff_to_spec": [
    { "diff_ref": "src/module/file.ts#L10", "mapped_ids": ["AC-001", "PAC-4"], "is_mapped": true, "unmapped_reason": "" }
  ],
  "summary": { "spec_total": 0, "spec_mapped_count": 0, "spec_unmapped_count": 0, "must_total": 0, "must_mapped_count": 0, "must_unmapped_count": 0, "diff_total": 0, "diff_mapped_count": 0, "diff_unmapped_count": 0 }
}
```

- `spec_to_diff[]`: Spec AC + Plan AC(PAC) 각 1행, diff ref와 양방향 추적.
- `diff_to_spec[]`: `changed_files` 기준 각 변경이 어떤 AC/PAC와 연결되는지. 미매핑 변경은 `is_mapped=false`.
- `summary.must_unmapped_count`: `grade=MUST`인 AC/PAC 중 `is_mapped=false` 개수.

#### coverage-matrix.md 생성 규칙 (MANDATORY)

사람 검토용 요약 리포트. 최소 포함: `Spec -> Diff` 표, `Diff -> Spec` 표, 요약 블록(`must_unmapped_count`, `spec_unmapped_count`, `diff_unmapped_count`).

#### Hard Gate (MANDATORY)

- `must_unmapped_count == 0`이면 `coverage_matrix_gate_result = pass`.
- `must_unmapped_count > 0`이면:
  - `coverage_matrix_gate_result = gap_found`, `review.json.status = "gap_found"`, `gap_source = "ac_gap"`.
  - unmapped MUST AC/PAC별 갭 태스크를 Step 6(c) 규약(`generated_by: "review"`)으로 자동 생성.
  - Step 3.5/Step 4 진입 차단 → Step 6(c)/(d) 경로.
- SHOULD-only unmapped는 경고 기록만 (blocking 사유 불가). 기존 Pass A 판정 필드 변경 금지.

---

### Step 3.5: Full Backend Test Gate (MANDATORY)

> 이 Step의 목적: Pass A 완료 후 Pass B 진입 전에 외부 프로젝트 worktree의 **백엔드 전체 테스트**를 강제 실행한다 / 핵심 출력물: `full_backend_test_gate_result`, `full-backend-test-report.md`, 보강-재테스트 이력

- 진입 조건: `pass_a_result==pass` AND `coverage_matrix_gate_result==pass`일 때만 실행.
- 차단 규칙: 전체 테스트 100% PASS 전까지 **Step 4(Pass B) 진입 금지**.
- 범위: Node 기반 백엔드 테스트만. 프론트엔드/E2E(`playwright`, `cypress`, `selenium`, `puppeteer`) 제외.

#### package.json `scripts.test` 자동 탐지 (MANDATORY)

- `package.json.scripts.test` 자동 탐지. 기본값(`echo "Error: no test specified" && exit 1` 또는 빈 문자열)이면 `"테스트 없음"`으로 판단.

#### "테스트 없음" 분기 (MANDATORY)

- `full-backend-test-report.md`에 `status: NO_TESTS_DETECTED` 기록 후 반드시 사용자 확인 요청 (AUTO_MODE=true여도 AskUserQuestion 생략 불가).
- 허용 → `full_backend_test_gate_result = pass_with_warning` → Step 4 진행.
- 비허용 → `full_backend_test_gate_result = fail` → Step 6(c)/(d) 경로.

#### 실행/실패 분석 프로토콜 (MANDATORY)

1. `npm test` 실행. 로그 저장: `{.../reviews/{RV-NNN}/full-backend-test.log}`.
2. 실패 테스트 1개 이상이면 각 항목을 `explore` 기반 원인 분석.
3. `intent`/`plan`/`spec` 3중 문맥과 비교해 의도성 판정:
   - `INTENTIONAL`: 의도적 동작 변경과 일치 → 테스트 기대값/fixture/assertion 수정 태스크 자동 디스패치.
   - `UNINTENTIONAL`: 회귀/부수효과 → 소스 코드 + 테스트 보강 태스크 자동 디스패치.
   - `UNCERTAIN`: 증거 불충분 → `UNINTENTIONAL`로 처리.
   - 공통: 생성 태스크는 `generated_by: "review"` 규약 재사용. 태스크 완료 후 전체 재테스트.

#### 보강-재테스트 루프 (최대 10회, MANDATORY)

- 루프: 테스트 실행 → 실패 시 explore 분석 + 의도 판정 → 분기별 태스크 디스패치 → 보강 완료 후 재테스트.
- 10회 이내 100% PASS: `full_backend_test_gate_result = pass` → Step 4 허용.
- 10회 초과 FAIL: `limit_reached`로 기록 + 사용자 에스컬레이션. 11회째 자동 시도 금지.

#### 결과 리포트 + `evidence-ledger.md` 연계 (MANDATORY)

- 리포트: `{.../reviews/{RV-NNN}/full-backend-test-report.md}`
  ```markdown
  # Full Backend Test Report — RV-NNN
  - status: PASS | PASS_WITH_WARNING | FAIL | LIMIT_REACHED | NO_TESTS_DETECTED
  - attempts: N/10
  - command: npm test
  - summary: total=<N>, passed=<N>, failed=<N>, skipped=<N>

  ## Failed Tests
  | Test | Intent Verdict | Classification | Root Cause (explore) | Action |
  |------|----------------|----------------|----------------------|--------|

  ## Escalation
  - escalated: true|false
  - reason: <사유>
  ```
- `evidence-ledger.md` 연계: 각 테스트 실행 직후 `ID=AC-FULL-BACKEND-TEST-GATE`, `Type=automatable`, `Command=npm test`, `Expected=전체 100% PASS`, `Actual=pass/fail 카운트`, `Exit Code=실제 종료 코드`로 append.

#### Step 4/5 연결 규칙 (호환성 보장)

- Step 4 허용: `coverage_matrix_gate_result==pass` AND `full_backend_test_gate_result in {pass, pass_with_warning}`.
- Step 4 차단: `coverage_matrix_gate_result==gap_found` 또는 `full_backend_test_gate_result in {fail, limit_reached}` → Step 6(c)/(d) 경로.

---

### Step 4: Pass B — 코드/문서 품질 검증

> 이 Step의 목적: Pass A 통과 산출물을 기반으로 코드/설계/UI/의도 충실도/영향 범위/적대적 관점 갭을 찾는다 / 핵심 출력물: `ac-results.md`, `review-code.md`, `review-arch.md`, `review-ui.md`, `review-intent-fidelity.md`, `review-impact.md`, `review-adversarial.md`

#### Pass B 타입 분기 (if 1개, MANDATORY)

- `if strategy.review_mode == "fulltext"`: 코드 리뷰 프롬프트 대신 문서 구조/품질 리뷰 프롬프트 사용. 검토 기준: 정확성/완결성/독자적합성/구조·가독성. 입력은 문서 전문(full text), diff 요약은 참고만. 결과 산출 경로는 기존과 동일 (`review-code.md` 재사용).
- `else`: 기존 Pass B 절차를 그대로 적용한다. (변경 금지)

##### strategy.review_mode=="fulltext" Pass B 전문 리뷰 규칙 (MANDATORY)

1. 리뷰 대상 문서는 `spec §2 변경 범위` 기준으로 식별하고 `Read`로 원문 전체를 로드 (요약본/부분 diff 사용 금지).
2. 체크리스트 (모든 항목 필수): 정확성(claim이 소스/근거와 일치), 완결성(TOC 항목 누락 없이 반영), 독자적합성(plan 목적/독자/결과물 조건 부합), 구조(H1/H2/H3 계층, 섹션 순서, 문단 흐름 일관성).
3. `review-code.md`에 4개 축별 `PASS|FAIL`과 근거를 표 형태로 기록. FAIL 항목은 수정 권고 포함.

Pass B는 Claude(인컨텍스트)와 background 에이전트 6개를 동시 시작합니다.

```
Claude (인컨텍스트):        spec §3 AC 체크리스트 순차 검증  ─┐
code-reviewer (bg):        구현 레벨 리뷰                  ─┤─→ Step 5에서 PM 취합 → review-report.md
arch-reviewer (bg):        설계/계획 레벨 리뷰              ─┤
ui-reviewer (bg):          UI 설계 검토 (조건부)            ─┤
intent-fidelity (bg):      원본 의도 대비 구현 일치 검증     ─┤
impact-reviewer (bg):      영향 범위(회귀 영향) 분석         ─┤
adversarial-reviewer (bg): 공격 표면 기반 적대적 리뷰       ─┘
```

#### Claude 인컨텍스트: AC 검증

- 각 AC 항목별로 관련 코드/설정 파일 Read.
- PASS / FAIL / UNKNOWN 판정 후 근거 기록.
- **Plan AC(PAC)가 있으면 Spec AC와 별도 섹션으로 검증**. Plan AC는 관찰 가능한 결과/동작 기준으로 판정. MUST 등급 미충족은 spec AC 실패와 동일 처리.
- 결과를 `reviews/RV-NNN/ac-results.md`에 저장:
  ```markdown
  # AC 검증 결과 — RV-NNN

  ## Spec AC
  | AC | 등급 | 판정 | 근거 |
  |----|------|------|------|
  | AC-1 | MUST | ✅ PASS | ... |

  ## Plan AC (PLN-NNN)
  | AC | 판정 | 근거 |
  |----|------|------|
  | PAC-1 | ✅ PASS | ... |
  ```
  `source_plan` 미존재 시 Plan AC 섹션 생략.

#### Background 에이전트 dispatch

background 에이전트는 `run_in_background: true` 옵션으로 dispatch합니다.

| 역할 키 | 검토 관점 | config 키 |
|---------|-----------|-----------|
| `code_reviewer` | 누락 로직, 버그, 엣지케이스, 테스트 누락 + 테스트 패턴 준수 검증(spec 주입 원칙 기준, 미준수 시 [MAJOR]) | `review.roles.code_reviewer.agent` |
| `arch_reviewer` | spec 의도 vs 구현 방향, 통합 일관성 + Scope Audit(`SCOPE_CREEP`/`OMISSION`, plan.md 상위 목표 대비 적합성, 불필요 파일 변경 여부. 미발견 시 `"확인 완료 — 해당 없음"` 명시) | `review.roles.arch_reviewer.agent` |
| `ui_reviewer` | Stitch 시안 vs 실제 UI, UX 흐름 일관성 | `review.roles.ui_reviewer.agent` |
| `intent_fidelity` | plan 요청+docs 대비 구현 일치. spec §3.2 Intent Trace 항목을 구현 증거와 대조. Missing/Partial/Verified 분류. blocking 모드에서 MUST Partial/Missing은 pass/fail 반영, SHOULD는 warning | `review.roles.intent_fidelity.agent` |
| `impact_reviewer` | `git diff --name-only` 기준 변경 파일 → 역추적(enhanced_analysis=true시 2단계, false시 1단계) → 기능 깨짐 판단. [impact-check] AC Given/When/Then 전담 판정. 영향 rubric: 공개 API/라우트=CRITICAL, 공유 컴포넌트/유틸=MAJOR, 내부 모듈=MINOR | `review.roles.impact_reviewer.agent` |
| `adversarial_reviewer` | 보안/데이터 무결성/동시성/롤백 안전/null·timeout/버전 스큐/관측성 등 attack surface 관점. finding에 `attack_surface`+`confidence(0~1)` 필수 | `review.roles.adversarial_reviewer.agent` |

모델 resolve: `providers[agent][review.roles.{role}.tier || default_tier]`

### 테스트 패턴 준수 검증 (code_reviewer 추가 관점)

spec.md에 유형별 원칙이 주입된 AC가 있는 경우:
1. 해당 AC의 보조 태그([unit-test], [api-test] 등)와 주입된 원칙(2-3줄)을 확인한다.
2. 구현된 테스트 코드가 해당 원칙을 따르는지 검증한다.
3. 미준수 항목은 [MAJOR] 등급으로 보고한다.
4. 보조 태그가 없는 AC는 이 검증을 skip한다.

각 리뷰어(code/arch/ui/impact/adversarial)는 발견한 이슈에 반드시 `[CRITICAL]`, `[MAJOR]`, `[MINOR]` 등급을 태깅해야 한다 (`templates/review-request.md`의 등급 판별 가이드 및 보안 오버라이드 규칙 적용).
adversarial_reviewer는 등급 태깅과 별개로 finding별 `confidence`를 필수로 포함 (Step 5에서 confidence 기준 재매핑).
intent_fidelity는 등급 대신 `Verified/Partial/Missing` + `INTENT-GAP` 카운트를 출력한다.

arch_reviewer dispatch 시 `templates/review-request.md`의 `{{PERSPECTIVE}}`에 Scope Audit 지시를 반드시 포함한다.

각 에이전트 출력 파일 경로:
- code_reviewer → `reviews/RV-NNN/review-code.md`
- arch_reviewer → `reviews/RV-NNN/review-arch.md`
- ui_reviewer → `reviews/RV-NNN/review-ui.md`
- intent_fidelity → `reviews/RV-NNN/review-intent-fidelity.md`
- impact_reviewer → `reviews/RV-NNN/review-impact.md`
- adversarial_reviewer → `reviews/RV-NNN/review-adversarial.md`

공통 프롬프트 변수:
- `{{SPEC_PATH}}`: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{NN}/spec.md` 절대경로
- `{{PLAN_PATH}}`: `source_plan` 존재 시 `plan.md` 절대경로, 미존재 시 `"N/A"`
- `{{REFERENCE_CONTEXT}}`: Step 2에서 생성한 블록 (모든 리뷰어 프롬프트에 동일 주입)
- `{{SPEC_REFERENCE_CONTEXT}}`: Step 2-a에서 생성한 블록 (모든 리뷰어 프롬프트에 동일 주입)
- `if strategy.review_mode == "fulltext"`: 프롬프트 본문에 문서 전문 직접 포함, code_reviewer 포커스를 문서 품질 체크리스트로 고정.

#### impact_reviewer dispatch 입력 규칙

- `review.roles.impact_reviewer.enabled != true`이면 auto-skip.
- 변경 파일 목록이 비어있으면 auto-skip.
- `enhanced_analysis` 기본값: `true`.
- `{{PERSPECTIVE}}`에 포함할 지시:
  - `enhanced_analysis=true`: 2단계 역추적 → 의존 파일 소스 Read → 기능 깨짐 판단. `review-impact.md`에 확인 파일 목록/판단 근거/함께 수정 필요 파일(수정 방향) 기록.
  - `enhanced_analysis=false`: 1단계 역추적 + 기존 [IMPACT] 태그 체계 유지.
  - 동적 import/런타임 의존성 추적 제외. rubric: 공개 API/라우트=[CRITICAL], 공유 컴포넌트/유틸=[MAJOR], 내부 모듈=[MINOR].
  - `[impact-check]` AC가 있으면 AC별 Given/When/Then 충족 여부를 PASS/FAIL/SKIP로 판정하고 `review-impact.md`에 `AC ID | Grade | Verdict | Evidence` 표로 기록.

#### adversarial_reviewer dispatch 입력 규칙

- `review.roles.adversarial_reviewer.enabled != true`이면 auto-skip.
- 프롬프트 템플릿: `templates/adversarial-review-prompt.md`. Read 실패 시 비차단 skip.
- timeout/에이전트 에러가 발생해도 워크플로우 중단 안 함. Step 5에서 `[ADVERSARIAL: SKIPPED — {사유}]`로 표시.

#### [impact-check] AC 전담 판정 규칙 (Pass B, impact_reviewer)

- `[impact-check]` AC 1개 이상이면 impact_reviewer가 Given/When/Then 조건 전담 판정.
- 판정 결과는 `review-impact.md`에 AC별 verdict로 기록.
- `[MUST]` 등급 FAIL 1건이라도 있으면 해당 iteration 실패 → Step 6 `gap_found` 분기.
- `impact_reviewer.enabled != true`이고 `[impact-check]` AC 존재 시 해당 AC verdict=`SKIP` + 경고 출력 (비차단, 하위 호환).

#### impact_reviewer 결과 처리 규칙 (Pass B 공통)

- `review-impact.md`의 `[CRITICAL]`/`[MAJOR]`/`[MINOR]` 이슈 파싱.
- `[CRITICAL]` 또는 `[MAJOR]` 1건 이상이면 `FAIL(gap_found)` → Step 6(c). 생성 태스크 description에 `함께 수정 필요 파일` 목록 + 수정 방향 필수.
- `[MINOR]`만이면 warning 기록만, `gap_found` 트리거 안 함.
- `[impact-check]` AC 존재 여부와 무관하게 적용.

#### intent_fidelity dispatch 입력 규칙

- `intent_fidelity.enabled != true`이면 skip.
- `spec.md`에 `## 3.2 Intent Trace`가 없으면 auto-skip.
- 전달 컨텍스트: `spec.md` 원문, 구현 diff, plan 원본 요청, spec §3.2 Intent Trace 원문, docs 컨텍스트.
- 출력 파일: `reviews/RV-NNN/review-intent-fidelity.md`.
  ```markdown
  # Intent Fidelity 리포트 — RV-NNN

  ## 검증 요약
  - ✅ Verified: N개 / ⚠️ Partial: N개 / ❌ Missing: N개 / ℹ️ INTENT-GAP: N개

  ## 상세
  | AC-ID | 의도 근거 | 구현 증거 | 판정 | 비고 |
  |-------|-----------|-----------|------|------|
  ```

#### 프롬프트 파일 사전 저장 (MANDATORY)

> ⚠️ **파이프 방식 금지**: `echo "$PROMPT" | codex exec ... "$(cat)"` 패턴 사용 금지 (shell command substitution이 파이프 연결 전 평가되어 빈 문자열 전달).

dispatch 전 각 리뷰어 프롬프트를 반드시 파일로 먼저 저장한다:
```
Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/{role}-prompt.md
```
저장 완료 확인 후 dispatch한다.

#### 에이전트 유형별 dispatch 패턴

**`codex` 에이전트**:
```bash
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex {tier} 2>/dev/null || echo "gpt-5.3-codex");
  command: 'set -o pipefail; codex exec --full-auto -m "$MODEL" -C {PROJECT_ROOT} "$(cat {PROMPT_FILE})" < /dev/null 2>&1 | tee {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/{role}-running.log',
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)
```

**`gemini` 에이전트**:
```bash
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model gemini {tier} 2>/dev/null);
  command: 'set -o pipefail && cd {PROJECT_ROOT} && gemini -p "$(cat {PROMPT_FILE})"${MODEL:+ --model "$MODEL"} --approval-mode yolo --sandbox=false < /dev/null 2>&1 | tee {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/{role}-running.log',
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)
```

**`claude`/`claude-dev` 에이전트**:
```
Agent(
  subagent_type: "general-purpose",
  prompt: {PROMPT_FILE 파일 내용 — Read 후 전달},
  run_in_background: true,
  mode: "acceptEdits"
)
```
플랜 B: `acceptEdits`에서 Write가 차단될 경우 `mode: "auto"`로 전환.

**스킵 조건 요약**:
- `ui_reviewer`: `request.json.stitch_screens` 비어있고 `frontend/` 변경 파일 없음 → auto-skip.
- `impact_reviewer`: `enabled=false` 또는 변경 파일 목록 비어있음 → auto-skip.
- `adversarial_reviewer`: `enabled=false` → auto-skip.
- `intent_fidelity`: `enabled=false` 또는 `## 3.2 Intent Trace` 미존재 → auto-skip.
- `impact_reviewer` 비활성 + `[impact-check]` AC 존재 시: AC별 `SKIP` 경고 기록 (비차단).

### Step 5: 완료 대기 및 취합

> 이 Step의 목적: Pass B 산출물을 수집·요약해 리뷰 결과를 단일 리포트로 정리한다 / 핵심 출력물: `review-report.md`

1. **완료 폴링**: background 에이전트(skip 제외) 완료 대기.
   - 에이전트 실패 시: 해당 역할 "에이전트 실패" 표시 후 나머지 취합 계속.
   - fallback (FILE_NOT_FOUND): 각 `review-*.md` 파일이 없으면 Agent 반환값(`TaskOutput`)에서 텍스트 추출. `# ` 또는 `## ` 헤더 1개 이상이면 유효로 간주, PM이 해당 경로에 Write. 그 외 "에이전트 실패" 처리.
2. **취합 파일**: `ac-results.md` + `review-code.md` + `review-arch.md` + `review-ui.md` + `review-intent-fidelity.md` + `review-impact.md` + `review-adversarial.md` + `coverage-matrix.json/md` + `full-backend-test-report.md`(선택).
3. **review-report.md 작성**: `reviews/RV-NNN/review-report.md`
   ```markdown
   # 리뷰 리포트 — RV-NNN (REQ-NNN 반복 N)

   ## Spec AC 검증 결과
   - ✅ 충족 AC N개 / ❌ 미충족/갭 N개

   ## Plan AC 검증 결과 (PLN-NNN)
   <!-- source_plan 없으면 이 섹션 생략 -->

   ## Spec↔Diff Coverage Matrix 결과
   - MUST unmapped: N건 / Spec unmapped: N건 / Diff unmapped: N건
   - 상세: `coverage-matrix.md`, `coverage-matrix.json`

   ## Full Backend Test Gate 결과
   - 상태: PASS | PASS_WITH_WARNING | FAIL | LIMIT_REACHED | NO_TESTS_DETECTED
   - 시도 횟수: N/10 / 테스트 요약: total/passed/failed/skipped
   - 상세: `full-backend-test-report.md` (없으면 "Step 3.5 skip")

   ## 교차 매트릭스 (파일 × attack_surface) — finding 3개+ 시
   - 조건 미충족 시: `finding < 3 (matrix skip)`
   - 셀 표기: `F-NN [합의|단독 발견|상충]` / sources: [role1, role2, ...]

   ## 코드 리뷰 주요 발견 사항
   ## 아키텍처 리뷰 주요 발견 사항
   ## UI 리뷰 주요 발견 사항
   ## Intent Fidelity 검증 결과
   - 모드: blocking(기본) | advisory
   - ✅ Verified N개 / ⚠️ Partial N개 / ❌ Missing N개 / ℹ️ INTENT-GAP N개
   ## 영향 범위 분석 결과
   ## Adversarial 리뷰 결과
   ```

4. **adversarial finding 통합 (MANDATORY)**:
   - `confidence` 기준 severity 재매핑: `>=0.8` → CRITICAL, `0.5~0.79` → MAJOR, `0.2~0.49` → MINOR, `<0.2` → DROP.
   - finding에 `F-NN` 식별자 부여.

5. **교차 검증 승격 + sources 병기 (MANDATORY)**:
   - `review.cross_validation.enabled == true`이면, `max(2, min_reviewers)`명 이상이 동일 파일·라인 근접(`line_proximity`) 영역을 지적 시 severity +1단계 승격.
   - finding에 `sources: [역할1, 역할2, ...]` + `source: "cross_validation"` 메모.
   - 라벨: `합의`(2개+ 역할 지적) / `단독 발견`(1개) / `상충`(상반된 verdict 공존).

6. **교차 매트릭스 포맷 (MANDATORY)**:
   - 최종 finding(DROP 제외) 3개 이상이면 report 상단에 `파일 × attack_surface` 격자 생성.
   - 행=파일 경로, 열=attack_surface(보안/데이터 무결성/동시성/롤백 안전/null·timeout/버전 스큐/관측성).

7. **adversarial non-blocking 처리 (MANDATORY)**:
   - timeout/에이전트 에러/템플릿 누락 시 adversarial만 skip, 기존 역할 취합 계속.
   - report에 `[ADVERSARIAL: SKIPPED — {사유}]` 섹션 필수. adversarial skip 단독 사유로 `gap_found` 트리거 안 함.

### Step 6: 갭 처리 분기

> 이 Step의 목적: AC 갭/코드리뷰 이슈 상태에 따라 후속 경로를 확정한다 / 핵심 출력물: `review.json.status` 및 재실행/수락 분기 결정

AC 미충족(갭) 여부와 코드리뷰 이슈 여부에 따라 5개 분기로 처리합니다.

Pass B에서 `[MUST] [impact-check]` AC FAIL 1건이라도 있으면 `review.json.status = "gap_found"` → `(c)` 분기.

> **Step 5 완료 시 공통 절차**: 분기 처리 완료 후 `request.json.review_iterations` 현재 회차 `status`를 `"in_progress"` → `"completed"`로 갱신.

#### PM 판정 기계화 Boolean Gate (Step 6 선행, MANDATORY)

`PM_PASS = MUST_AUTOMATABLE_PASS AND EVIDENCE_COMPLETE AND NO_BLOCKING_EXCEPTION`

1. `MUST_AUTOMATABLE_PASS`: MUST 등급 + `ac_type==automatable` Spec AC/PAC만 대상. 1건이라도 fail이면 false. `manual`/`browser-test` MUST AC는 별도 플래그(`manual_must_flag`, `browser_test_must_flag`)로만 관리.
   - 판정 정규화: PASS→pass, FAIL→fail, TIMEOUT→fail, `N/A`(na_reason 비어있으면)→fail.
2. `EVIDENCE_COMPLETE`: `review.json`, `evidence-ledger.md`, `coverage-matrix.json`, `coverage-matrix.md` 모두 존재+비어있지 않으면 true.
3. `NO_BLOCKING_EXCEPTION`: `pass_a_result==fail`, `static_validation_gate_result in {fail,gap_found}`, `coverage_matrix_gate_result==gap_found`, `full_backend_test_gate_result in {fail,limit_reached}`, blocking 모드 intent_fidelity 실패가 모두 없어야 true.
4. 기존 Step 6 분기가 `(a)`(pass 후보)일 때만 최종 확정 직전에 평가. `PM_PASS=false`이면 `(a)` 취소 → `(c)` 경로 강등 (`review.json.status="gap_found"`, `gap_source="ac_gap"`). 이미 확정된 `(b)/(c)/(d)/(e)`는 덮어쓰지 않음.

#### 커스텀 Loop 종료 조건 게이트 (Step 6 선행)

> 기존 분기 판정이 `(a)`로 확정되기 직전에만 AND로 추가 평가한다.

1. `request.json.source_plan` 기준으로 `plan.md`의 `## Loop 종료 조건` 섹션을 Read하여 `custom_loop_conditions` 로드.
2. `source_plan` 미존재/파일 미존재/섹션 미존재/본문 비어있음이면 `custom_loop_conditions=[]` → 커스텀 게이트 skip (하위 호환).
3. 기존 판정이 `(a)`이면 `custom_loop_conditions`를 AND로 평가:
   - `연속 무변경 수렴`: 이번 iteration의 gap/diff와 직전 iteration 비교 시 새 gap/diff 없어야 통과.
   - `고정 N회 반복`: `review_iterations.length >= N`일 때만 통과.
   - 그 외 자연어 조건: PM이 현재 iteration 상태 기반으로 충족 여부 판정.
4. 조건 미충족 시 `(a)` 취소 → `(c)` 경로. 모두 충족 시 기존 `(a)` 진행.

#### Intent Fidelity 결과 반영 규칙 (Step 6 공통)

1. `review-intent-fidelity.md` 존재 시 `Verified/Partial/Missing/INTENT-GAP` 카운트 파싱.
2. `tasks[현재 태스크].self_check.intent_fidelity_result`에 기록: `{ "verified": N, "partial": N, "missing": N, "intent_gaps": N, "report_path": "reviews/RV-NNN/review-intent-fidelity.md" }`.
3. `intent_fidelity.mode` 기본값 `"blocking"`. `"advisory"`일 때만 완화 동작.
4. `advisory` 모드: 리포트만 출력, pass/fail 판정 미반영.
5. `blocking` 모드: MUST AC(또는 MUST PAC에 매핑된 AC)에서 `Partial`/`Missing` 1건이라도 → `gap_found` → `(c)` 경로. SHOULD AC의 `Partial`/`Missing`은 warning만.
6. SHOULD warning 로깅 (`should_warning_log == true`): `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/warnings.log`에 JSONL(`timestamp`, `req_id`, `rv_id`, `ac_id`, `module`, `result`, `reason`).
7. 동일 `module`에서 SHOULD warning 누적 횟수가 `should_escalation_threshold` 이상이면 review-report에 `"MUST escalation review required"` 플래그 추가 (즉시 blocking 아님).

#### (a) 갭 없음 + 코드리뷰 이슈 없음 (+ blocking 모드면 intent_fidelity 통과)

- `review.json.status = "passed"`, `request.json.review_summary = { "iteration": N, "status": "passed" }` 업데이트.
- Phase 3 PASS 반환. approve가 Phase 5(mst:accept)를 호출 — review는 mst:accept를 직접 호출하지 않는다.

#### (b) 갭 없음 + 코드리뷰 이슈만 있음 (AC는 통과, 설계/품질 이슈)

코드리뷰 이슈를 등급별로 분류한 뒤 자동 처리 분기를 수행합니다.

##### (b) enabled 가드

`config.review.severity_auto_fix.enabled` 확인:
- `false`: 기존 (b) 동작으로 fallback
  - **`--auto` 모드**: 이슈를 report에만 기록하고 Phase 5 자동 진행. `review.json.status = "passed"`.
  - **일반 모드**: `AskUserQuestion` → `[이슈 무시하고 수락]`(Phase 5) 또는 `[이슈를 태스크로 추가]`((c)와 동일 경로).
- `true`: 아래 등급별 분기 진행.

##### (b) 사전 처리: 이슈 파싱 및 등급 분류

1. **리뷰어 태깅 파싱**: `review-report.md`에서 `[CRITICAL]`/`[MAJOR]`/`[MINOR]` 접두사 파싱. 태깅 없는 이슈는 MAJOR로 기본 분류. adversarial finding은 Step 5 confidence 매핑 완료 항목만 포함 (DROP 제외).

2. **PM 재조정 (보안 오버라이드)**: `config.review.severity_auto_fix.security_override_keywords` 배열 키워드가 이슈 텍스트에 포함되면 무조건 CRITICAL 승격 (대소문자 무시).

3. **Severity 역행 감지 (iteration 2+ MANDATORY)**:
   - 직전 회차 `review.json`에서 `previous_severity_counts`를 현재 회차에 기록.
   - 동일 이슈 판정: 동일 파일 경로 + 라인 번호 차이 `<= 10` + 정규화된 설명 동일(대소문자 무시, 연속 공백 제거, 접두사 제거).
   - 동일 이슈 재발 시 자동 CRITICAL 승격. `source: "severity_regression_guard"` 기록.

4. **Pass B 교차 검증 승격 (`review.cross_validation.enabled == true`)**:
   - 동일 파일 경로 + 라인 번호 차이 `<= line_proximity`에서 `max(2, min_reviewers)`명 이상 지적 시 +1단계 승격 (CRITICAL 상한 고정). `source: "cross_validation"` + `sources: [역할...]` 기록.

5. **등급별 카운트 산출**: 재조정 후 `critical_count`, `major_count`, `minor_count` 산출.

6. **`review_issues_summary` 기록**: `review.json`과 `request.json` 해당 iteration 양쪽에 기록.

##### (b-1) CRITICAL 또는 MAJOR가 1건 이상 존재

- **`--auto` 모드**: CRITICAL/MAJOR → `(c)` 경로. MINOR → `review_issues_summary.skipped` 기록 후 스킵. `gap_source: "code_review_issues"`.
- **일반 모드**: `AskUserQuestion` → `[CRITICAL/MAJOR N건 태스크로 추가]`((c) 경로, MINOR는 b-2/b-3 규칙 적용) 또는 `[전체 이슈 무시하고 수락]`(Phase 5).

##### (b-2) MINOR만 존재 + 개수 <= threshold (스킵+리포트)

- **MINOR-only high-pass 보호 가드 (MANDATORY)**:
  - `review_issues_summary.auto_accept_guard` 항상 기록: `skipped_minor_count`, `protection_flags_count`, `blocked`, `blocked_reasons`.
  - auto accept 허용 계약은 `review_issues_summary.auto_accept_guard.blocked == false`일 때만 성립한다.
  - `skipped_minor_count > 0` 또는 `protection_flags_count > 0`이면 `blocked=true` → `(c)` 경로.
- `blocked==false` AND `minor_count <= config.review.severity_auto_fix.minor_skip_threshold`일 때만: MINOR를 `review-report.md` + `review_issues_summary.skipped`에 기록, `review.json.status = "passed"`.

##### (b-3) MINOR만 존재 + 개수 > threshold (자동 태스크 생성)

- `(c)`와 동일 경로. `gap_source: "code_review_issues"`. `review.json.status = "gap_found"`.
- `minor_skip_threshold`가 `0`이면 모든 MINOR도 자동 처리 대상.

##### (b) `--auto` 모드 동작 요약

| 등급 | 동작 |
|------|------|
| CRITICAL | 자동 태스크 생성 + 재외주 (c 경로) |
| MAJOR | 자동 태스크 생성 + 재외주 (c 경로) |
| MINOR | `minor_skip_threshold` + `auto_accept_guard` 검사. 가드 차단 시 (c) 경로. CRITICAL/MAJOR+MINOR 혼재 시 MINOR 스킵. |

#### (c) 갭 있음 + iteration ≤ max_iterations

1. 갭별 새 태스크 spec.md 자동 작성: `tasks/NN+1/spec.md` (기존 최대 번호 +1).
   - `request.json.tasks` 항목: `{ "id": "NN", "title": "<갭 설명>", "status": "pending", "agent": null, "spec": "tasks/NN/spec.md", "generated_by": "review" }`.
   - impact_reviewer 이슈 태스크라면 description에 `함께 수정 필요 파일` + 수정 방향 포함.
2. `request.json.tasks` 배열 업데이트.
3. `request.json.review_summary = { "iteration": N, "status": "gap_fixing" }` 업데이트.
4. `review.json` 업데이트: `{ "status": "gap_found", "gaps_found": M, "tasks_created": [...], "gap_source": "ac_gap | code_review_issues | intent_fidelity" }`.
5. approve 스킬에 갭 목록 + 새 태스크 ID 반환 → approve가 Phase 2 재실행 제어. — 텍스트만 출력하고 멈추지 않는다.

#### (d) 갭 있음 + iteration > max_iterations

- **`--auto` 모드**: `review.json.status = "limit_reached"`, `review_summary.status = "limit_reached"` 기록 후 종료.
- **일반 모드**: `AskUserQuestion` → `[추가 반복 허용 (+1회)]`(max_iterations 임시 +1 후 (c) 실행) / `[현재 상태로 수락]`(Phase 5, `status="passed"` 강제) / `[중단]`.

#### (e) Pass A 실패 (MUST AC 실패 감지)

1. `review.json.status = "pass_a_failed"` 기록.
2. `request.json.review_summary = { "iteration": N, "status": "pass_a_failed" }` 업데이트.
3. **스키마 Read (필수)**: `templates/schemas/pass-a-result.md`를 Read하여 필수 필드/형식을 확인한 후 작성한다.
4. **pass-a-result.md 저장**: `reviews/RV-NNN/pass-a-result.md`에 아래 스키마로 저장.
5. review는 `mst:feedback`을 직접 호출하지 않고 **종료**합니다.
6. approve에 `pass_a_failed` 상태 반환 → approve가 재외주 대상 태스크를 선별하여 Phase 2 재실행.

##### pass-a-result.md 스키마

저장 경로: `reviews/RV-NNN/pass-a-result.md`

```yaml
pass_a_result: fail
failed_ac_ids:
  - AC-XX
failure_class: ac_unclear | interpretation | implementation
evidence:
  - ac_id: AC-XX
    type: log | screenshot | metric | manual
    ref: "실패 증거 경로 또는 설명"
    summary: "실패 내용 요약"
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `pass_a_result` | string | 항상 `"fail"`. |
| `failed_ac_ids` | string[] | FAIL 판정된 MUST 등급 AC ID 목록. |
| `failure_class` | string | `ac_unclear`(AC 기준 불명확) \| `interpretation`(해석 차이) \| `implementation`(구현 누락/오류). |
| `evidence` | array | 각 실패 AC의 증거 목록. 각 항목: `{ ac_id, type, ref, summary }`. |

approve는 이 파일에서 `failed_ac_ids`와 `failure_class`를 파싱하여 재외주 대상 태스크를 선별한다.

## 수동 호출 모드 (/mst:review REQ-NNN)

approve 루프 밖에서 직접 호출 시 Step 1~4 동일 실행 후 Step 5 결과를 사용자에게 직접 보고합니다.

### 결과별 동작

| 결과 | 동작 |
|------|------|
| PASS (갭 없음, 이슈 없음) | "리뷰 통과. 갭 없음" 보고 후 종료. REQ 미accept 시 `/mst:accept REQ-NNN` 안내. |
| 갭 발견 | 태스크 자동 추가 + `review_summary` 업데이트 후 종료. "갭 N개 발견, T0N 태스크 추가됨. `/mst:approve REQ-NNN` 으로 재실행하세요" 안내. |
| 코드리뷰 이슈만 | report 출력 후 사용자 선택 → [태스크 추가] 또는 [무시]. 태스크 추가 시 `/mst:approve REQ-NNN` 안내. |

**`--auto` 플래그**: approve `--auto` 실행 시 내부 컨텍스트로 전달됨. `/mst:review REQ-NNN --auto` 직접 호출도 가능.

## request.json 스키마 변경

`mst:review` 실행 시 `request.json`에 아래 필드가 추가/갱신됩니다.

```json
{
  "review_iterations": [
    {
      "rv_id": "RV-001",
      "created_at": "2026-03-01T00:00:00Z",
      "gaps_found": 2,
      "tasks_created": ["03", "04"],
      "status": "completed"
    }
  ],
  "review_summary": { "iteration": 1, "status": "gap_fixing" },
  "tasks": [
    {
      "id": "02",
      "self_check": {
        "intent_fidelity_result": {
          "verified": 3, "partial": 1, "missing": 0, "intent_gaps": 1,
          "report_path": "reviews/RV-001/review-intent-fidelity.md"
        }
      }
    }
  ]
}
```

### review_iterations 배열

| 필드 | 설명 |
|------|------|
| `rv_id` | RV 채번 (`RV-NNN`). `review_iterations.length + 1` 기반. |
| `created_at` | 회차 시작 시각 (ISO8601). |
| `gaps_found` | 발견된 갭 수. |
| `tasks_created` | 갭으로 생성된 태스크 ID 배열. |
| `status` | Step 1에서 `"in_progress"` 초기화, Step 5 완료 후 `"completed"` 갱신. |
| `previous_severity_counts` | (선택) 직전 iteration severity 카운트. `{ "critical": number, "major": number, "minor": number }` |
| `review_issues_summary` | (선택) 등급별 코드리뷰 이슈 요약. `review.json.review_issues_summary`와 동일 구조. |

### plan_iterations 배열 (정의 전용)

`mst:review`는 이 필드를 **정의만 참조**하며 생성/갱신 로직을 수행하지 않는다 (기록 책임은 `plan -a`).

| 필드 | 설명 |
|------|------|
| `iteration_no` | plan 사후 점검 반복 번호(1부터). |
| `trigger` | 실행 트리거 (`post_review`, `manual_retry`, `auto_retry` 등). |
| `started_at` / `ended_at` | 반복 시작/종료 시각 (ISO8601). |
| `result` | 반복 결과 (`passed`, `failed`, `needs_followup` 등). |

### tasks[].self_check.intent_fidelity_result

| 필드 | 타입 | 설명 |
|------|------|------|
| `verified` | number | 구현 증거 충분 항목 수 |
| `partial` | number | 구현 증거 불충분 항목 수 |
| `missing` | number | 구현 누락 항목 수 |
| `intent_gaps` | number | 의도 근거 없는 AC 수 |
| `report_path` | string | `reviews/RV-NNN/review-intent-fidelity.md` |

### review_summary 객체

| 필드 | 설명 |
|------|------|
| `iteration` | 현재(마지막) 회차 번호. |
| `status` | `reviewing` \| `gap_fixing` \| `passed` \| `limit_reached` \| `pass_a_failed` |

- `reviewing`: Step 1~4 진행 중. `gap_fixing`: 갭 발견, 태스크 추가됨. `passed`: 갭 없음. `limit_reached`: `--auto` 모드에서 max_iterations 초과. `pass_a_failed`: MUST AC 실패.

### review.json

`reviews/RV-NNN/review.json` 구조:

```json
{
  "id": "RV-NNN",
  "req_id": "REQ-NNN",
  "iteration": N,
  "status": "passed | gap_found | reviewing | pass_a_failed",
  "created_at": "<ISO8601>",
  "previous_severity_counts": { "critical": 0, "major": 0, "minor": 0 },
  "gaps_found": 0,
  "tasks_created": [],
  "gap_source": "ac_gap | code_review_issues | intent_fidelity | null",
  "review_issues_summary": {
    "critical": 0, "major": 0, "minor": 0,
    "auto_fixed": [],
    "skipped": []
  },
  "pm_gate": {
    "pm_pass": true,
    "must_automatable_pass": true,
    "evidence_complete": true,
    "no_blocking_exception": true,
    "manual_must_flag": { "count": 0 },
    "browser_test_must_flag": { "count": 0 }
  }
}
```

`pm_gate`는 Step 6 Boolean Gate 계산 결과 선택 필드 (하위 호환).

### review_issues_summary 스키마

```json
{
  "review_issues_summary": {
    "critical": 2, "major": 1, "minor": 3,
    "auto_fixed": [
      { "severity": "CRITICAL", "description": "SQL injection 취약점", "task_id": "05" }
    ],
    "skipped": [
      { "severity": "MINOR", "description": "변수명 컨벤션 불일치" }
    ],
    "auto_accept_guard": {
      "skipped_minor_count": 2,
      "protection_flags_count": 0,
      "blocked": true,
      "blocked_reasons": ["review_issues_summary.auto_accept_guard.skipped_minor_count > 0"]
    }
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `critical` / `major` / `minor` | number | 각 등급 이슈 수 (보안 오버라이드/역행 감지 승격 반영 후). |
| `auto_fixed` | array | 자동 태스크 생성된 이슈. `{ severity, description, task_id }`. |
| `skipped` | array | 스킵 처리된 이슈. `{ severity, description }`. |
| `auto_accept_guard` | object | auto accept 허용/차단 메타. `{ skipped_minor_count, protection_flags_count, blocked, blocked_reasons }`. |

### gap_source / approve → review_issues_summary 데이터 전달

| `gap_source` 값 | 의미 |
|------|------|
| `"ac_gap"` | AC 미충족 (Step 5 (c)/(d) 분기). |
| `"code_review_issues"` | 코드리뷰 이슈 (Step 5 (b) 분기). |
| `"intent_fidelity"` | blocking 모드 intent-fidelity 실패. |
| `null` | 갭 없음 (`status: "passed"`). |

approve는 최신 `reviews/RV-NNN/review.json`을 Read하여 `review_issues_summary`를 참조하고, 등급별 후속 분기(재외주/PM 직접 수정/스킵)를 결정합니다.
