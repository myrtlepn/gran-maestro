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
2. **committed 태스크 존재**: `request.json.tasks` 배열에서 `status == "committed"` 태스크가 1개 이상이어야 실행. 미충족 시 "Phase 2 완료(commit) 후 실행하세요" 안내 후 종료.
   - 이 조건은 approve 루프 내 호출 시에는 적용하지 않음 (approve가 사전 검증).

## Gate

### Entry

- REQ-ID와 수동 호출 전제조건(`committed` 태스크)을 먼저 검증한다.
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

review 단계에서 외부 의존성 관련 AC/리뷰 포인트가 보이면 아래 공통 프로토콜을 적용한다.

0. **자동 트리거 게이트**:
   - `config.resolved.json`의 `reference.auto_search`가 `true`일 때만 자동 WebSearch 허용.
   - 미설정 기본값: `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**:
   - spec AC, Plan AC, 변경 파일 설명, 리뷰 이슈 텍스트에서 외부 의존성 키워드(라이브러리/API/프레임워크/버전/프로토콜 계열)를 감지한다.
   - `reference.llm_auto_trigger == true`이면 키워드 매칭과 별도로 PM이 "인터넷에 최신 정보가 있을 법한 내용"이라고 판단할 때 자율적으로 WebSearch를 트리거한다.
   - `reference.llm_auto_trigger == false`이면 기존 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**:
   - (a) `.gran-maestro/references/` 캐시 존재 확인 (`mst.py reference search --keyword ... --json`)
   - (b) TTL 기준 `fresh/stale` 판정 (`cache_ttl_days`)
   - (c) cutoff 괴리 기준 `expired` 판정 (`cutoff_threshold_months`)
3. **WebSearch 트리거**:
   - 캐시 없음 또는 `stale/expired`인 항목만 검색.
   - 자동 검색은 `reference.auto_search == true`일 때만 실행.
   - `reference.auto_fact_check == true`이면 검색 결과의 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
   - `reference.auto_fact_check == false`이면 기존 동작(검색 결과를 그대로 다음 단계로 전달)을 유지한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**:
   - WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 `mst.py reference add`를 호출해야 한다.
   - 표/텍스트 결론 요약만으로는 저장이 완료되지 않는다 — `content.md`는 raw 발췌(원문 근거) 중심으로 남긴다.
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{raw 발췌 본문}"`
   - 작성 원칙 요약: 인용/표/코드 스니펫 + 출처 URL/날짜를 함께 기록한다 (`summary`는 한 줄 인덱스 유지).
   - 상세 예시/품질 체크리스트/lazy-Read 트리거는 `skills/plan/SKILL.md`의 Reference Lookup Protocol 4번 항목을 동일 기준으로 따른다.
5. **프롬프트 주입**:
   - Pass B 리뷰어 프롬프트에 아래 `[REFERENCE_CONTEXT]`를 공통 주입한다.
     ```text
     [REFERENCE_CONTEXT]
     current_date: {YYYY-MM-DD}
     model_cutoff: {cutoff_date_or_unknown}
     references:
     - REF-001 (fresh|stale|expired) {topic} | {url}
     [/REFERENCE_CONTEXT]
     ```
   - 참조 없음이면 `references: none`을 유지한다.


### Step 1: 초기화

> 이 Step의 목적: 리뷰 반복 회차 메타데이터를 초기화한다 / 핵심 출력물: `RV-NNN` 디렉토리, `review.json`, `request.json.review_iterations` 갱신

1. **RV 채번**: `request.json.review_iterations.length + 1` → 3자리 0패딩 → `RV-001`, `RV-002`, ...
   - `review_iterations` 배열이 비어있으면 `length = 0` → `RV-001` 정상 채번.
2. **디렉토리 생성**: `{PROJECT_ROOT}/.gran-maestro/requests/REQ-NNN/reviews/RV-NNN/`
3. **review.json 생성**:
   ```json
   {
     "id": "RV-NNN",
     "req_id": "REQ-NNN",
     "iteration": N,
     "status": "reviewing",
     "created_at": "<ISO8601>",
     "previous_severity_counts": {
       "critical": 0,
       "major": 0,
       "minor": 0
     }
   }
   ```
   - `previous_severity_counts` 채우기 규칙:
     - iteration 1: `{ "critical": 0, "major": 0, "minor": 0 }`
     - iteration 2+: 직전 회차(`RV-(N-1)`)의 `review_issues_summary.critical|major|minor` 값을 복사 (누락 시 0 fallback)
4. **request.json 업데이트**:
   - `review_iterations` 배열에 `{ "rv_id": "RV-NNN", "created_at": "<ISO8601>", "status": "in_progress" }` 항목 추가 (Step 5 완료 후 `"completed"`로 갱신).
   - `review_summary` = `{ "iteration": N, "status": "reviewing" }` 업데이트.

### Step 2: 컨텍스트 로드

> 이 Step의 목적: AC 검증/리뷰에 필요한 입력 컨텍스트를 수집한다 / 핵심 출력물: AC 목록, 변경 파일 목록, config 기반 실행 파라미터

1. **Spec AC 목록 수집**: 모든 `tasks/NN/spec.md` Read → `## 3. 수락 조건` 섹션에서 AC 항목 추출.
1-b. **Plan AC(PAC) 수집 (source_plan 존재 시)**:
   - `request.json.source_plan` 필드 확인 후 값이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json`을 우선 Read한다.
   - `plan.ids.json` 존재 시: 각 항목의 `id(PAC-N)`, `text`, `grade(MUST|SHOULD)`, `tags?`를 그대로 로드한다 (`tags` 미존재 시 빈 배열로 간주).
   - `plan.ids.json` 미존재 시(레거시 호환): `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`의 `## 인수 기준 초안`을 추출해 `PLAN-AC-N` 임시 ID를 부여한다.
   - `source_plan` 미존재 또는 인수 기준 섹션 자체가 없으면 이 단계 skip (경고 없이 무시).
   - 수집된 Plan AC/PAC는 Spec AC와 **분리하여 관리** (Pass A에서 별도 섹션으로 검증).
1-b-1. **리뷰 전략 결정 (source_plan → plan.json.type → type-strategies.json 체인, MANDATORY)**:
   - `request.json.source_plan` 값이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`을 Read하고 `type` 필드를 확인한다.
   - `plan_type = plan.json.type` (`type` 누락 또는 Read 실패 시 `"code"` fallback)
   - `type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)` 시도
   - `strategy = type_strategies[plan_type] || type_strategies["code"]`
   - `type-strategies.json` Read 실패/파싱 실패/키 누락 시 `strategy = {"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`로 fallback해 기존 코드 리뷰 경로를 유지한다.
1-c. **Spec AC 타입 태그 파싱**: 각 AC 헤더의 타입 태그(`[automatable]`, `[manual]`, `[browser-test]`)를 파싱하여 `ac_type`으로 보관한다.
   - 태그 누락 시 기본값은 `manual`.
   - `[browser-test]`는 Pass A에서 실제 브라우저 실행 분기 대상으로 표시한다.
1-d. **테스트 유형 보조 태그 파싱**: AC 헤더에서 `[automatable]`/`[manual]`/`[browser-test]` 이후의 보조 태그를 추가 파싱하여 `ac_test_type`으로 보관한다.
   - 인식 보조 태그: `[build-check]`, `[lint-check]`, `[unit-test]`, `[integration]`, `[api-test]`, `[e2e-browser]`, `[visual]`, `[performance]`, `[impact-check]`, `[regression-test]`
   - 보조 태그가 없으면 `ac_test_type = null` (기존 동작 유지, 하위 호환).
   - `[e2e-browser]` 보조 태그는 기존 `[browser-test]` ac_type 실행 분기를 재사용한다.
   - `[impact-check]` 보조 태그가 있으면 해당 AC를 `impact_reviewer` 라우팅 대상으로 표시한다.
   - `[regression-test]` 보조 태그가 있으면 해당 AC를 regression 검증 대상(선행 작성된 회귀 테스트 재실행)으로 표시한다.
   - 하나의 AC에 복수 보조 태그가 있으면 첫 번째 태그를 `ac_test_type`으로 사용한다.
2. **변경 파일 목록 수집**: `git log --name-only` 또는 `git diff <base>..HEAD --name-only` 기반으로 REQ 관련 변경 파일 목록 작성.
2-a. **spec 직접 참조 파일 컨텍스트 확장 (MANDATORY)**:
   - 대상: 각 태스크 `spec.md`의 `## 영향 파일` + `## 관련 파일` 섹션.
   - 수집 규칙:
     - 섹션 내 bullet/numbered list/inline code에 명시된 **직접 경로만** 수집한다.
     - 재귀 확장 금지: 수집한 파일이 추가 include를 가리켜도 따라가지 않는다.
     - 디렉토리 경로는 1-depth만 확장: 하위 "직계 파일"만 포함하고 하위 디렉토리는 제외한다.
     - 경로 해석은 `spec.md` 기준 상대경로를 우선하고, 절대경로는 그대로 사용한다.
   - 우선순위 정렬(중복 제거 후 유지):
     1. `changed_files ∩ spec_direct_refs`
     2. `## 영향 파일` 전용 항목
     3. `## 관련 파일` 전용 항목
   - 축약 규칙(리뷰어 컨텍스트 토큰 보호):
     - 파일 길이 `<= 200 lines`: 원문 전문을 그대로 포함한다.
     - 파일 길이 `> 200 lines`: `head 80 + keyword 120 + tail 20`으로 축약한다.
     - `keyword 120`은 AC ID, changed file basename, `Given|When|Then|Test|TODO|FIXME|export|class|function` 매칭 라인에서 상한 120줄을 추출한다.
     - head/keyword/tail은 라인 번호 기준 dedup 후 원래 순서로 합친다.
   - 산출물:
     - `spec_reference_files` (정렬/중복제거 완료된 파일 목록)
     - `spec_reference_context_block` (리뷰어 프롬프트 주입용 전문/축약 본문)
   - 섹션 미존재 또는 유효 경로 0건이면 graceful skip (`spec_reference_files=[]`).
3. **AC별 파일 매핑 준비**: 각 AC 항목과 관련 변경 파일 연결.
4. **Intent lookup (비차단)**: 변경 파일 목록을 기반으로 관련 Intent를 조회한다.
   - 실행:
     ```bash
     python3 {PLUGIN_ROOT}/scripts/mst.py intent lookup --files {changed_files}
     # {changed_files}: 공백 구분 파일 경로 목록 (예: --files file1.ts file2.md)
     # git diff 출력 변환: $(git diff master..HEAD --name-only | tr '\n' ' ')
     # 주의: 경로에 공백 포함 시 개별 인자로 전달 필요; 파일 수 과다(100개+) 시 상위 20개만 사용
     ```
   - 조회된 INTENT가 존재하면 해당 내용(feature, situation, motivation, goal)을 각 리뷰어 프롬프트에 **의도 위반 체크** 컨텍스트로 주입:
     ```
     [Intent 컨텍스트]
     - When I: {situation}
     - I want to: {feature}
     - So I can: {goal}
     - Motivation: {motivation}
     → 구현이 위 의도에 부합하는지 "의도 위반 체크" 관점에서 검토하세요.
     ```
   - INTENT 조회 결과 없으면 skip (비차단); 명령 실패 시 warn만 출력, 워크플로우 차단 금지
4-b. **Intent Trace 컨텍스트 수집 (intent_fidelity 전용)**: 현재 태스크 `spec.md`에서 `## 3.2 Intent Trace` 섹션 추출.
   - 섹션 존재 시: 섹션 원문을 `{INTENT_TRACE_SECTION}`으로 보관하고, `intent_fidelity` 프롬프트에 포함한다.
   - `request.json.source_plan` 존재 시: `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`에서 `## 요청 (Refined)` + `## Intent (JTBD)`를 추출하여 `{PLAN_INTENT_CONTEXT}`로 보관한다.
   - docs 컨텍스트: `Intent Trace`의 `근거 출처`에 포함된 `docs/` 경로 + `intent_snapshot`(존재 시)의 docs 경로를 dedup 후 Read하여 `{INTENT_DOCS_CONTEXT}`로 보관한다. docs가 없으면 skip.
   - 섹션 미존재 시: `intent_fidelity_skip_reason = "Intent Fidelity 리뷰 skip (Intent Trace 없음)"`를 설정하고 intent_fidelity dispatch를 auto-skip 처리한다.
4-c. **Reference 컨텍스트 수집 (MANDATORY)**:
   - Step 2 입력(AC 목록, 변경 파일, plan/request 요약)에서 외부 의존성 키워드를 감지하고 `Reference Lookup Protocol`을 실행한다.
   - 자동 WebSearch는 `reference.auto_search == true`일 때만 수행한다.
   - 결과를 `reference_context_block`으로 보관해 Pass B 모든 리뷰어 프롬프트에 공통 주입한다.
5. **config 로드**: `config.resolved.json`에서 아래 값을 확인.
   - `review.roles.*` 에이전트 키
   - `review.roles.browser_tester.agent` / `review.roles.browser_tester.tier` (존재 시 Pass A의 browser-test AC 실행 주체를 PM 직접 실행 → 서브에이전트 위임으로 전환)
   - `review.roles.impact_reviewer.enabled` / `review.roles.impact_reviewer.agent` / `review.roles.impact_reviewer.tier` / `review.roles.impact_reviewer.enhanced_analysis` (기본값: `true`)
   - `review.roles.intent_fidelity.agent` / `review.roles.intent_fidelity.tier`
   - `review.cross_validation.enabled` / `review.cross_validation.min_reviewers` / `review.cross_validation.line_proximity`
     - 기본값: `enabled=false`, `min_reviewers=2`, `line_proximity=10`
   - `intent_fidelity.enabled` (기본값: `true`)
   - `intent_fidelity.mode` (기본값: `"blocking"`)
   - `intent_fidelity.should_warning_log` (기본값: `true`)
   - `intent_fidelity.should_escalation_threshold` (기본값: `3`)
   - `review.max_iterations` 키 경로: `config.review.max_iterations` (미정의 시 기본값 10 사용)
   - `auto_mode.review` 키 경로: `config.auto_mode.review` (true이면 `AUTO_MODE=true`, `--auto` 플래그와 동일 동작)
   - `auto_mode.max_review_iterations` 키 경로: `config.auto_mode.max_review_iterations`
     - `AUTO_MODE=true` 이고 값이 설정되어 있으며 `> 0`이면 `max_iterations`를 이 값으로 override
     - `0` 이하이면 무시하고 `config.review.max_iterations` 값을 사용
   - `test_enforcement` 로드 (테스트 강제화, 하위 호환 MANDATORY):
     - 1순위: `config.resolved.json.test_enforcement`
     - 2순위 fallback: `templates/defaults/config.json.test_enforcement`
     - 둘 다 없으면 기본값 사용:
       - `enabled=true`
       - `backend_tdd=true`
       - `web_execution_test=true`
       - `exempt_patterns=["*.md","*.json","*.yml","*.yaml","*.txt","*.css"]`
       - `require_exemption_reason=true`
     - 키가 미설정인 기존 프로젝트도 에러 없이 동작해야 하며(미설정 fallback), 기존 review 플로우는 유지한다.
   - 우선순위:
     - `AUTO_MODE`: CLI `--auto` 플래그 > `config.auto_mode.review` > 기본값(false)
     - `max_iterations`: (`AUTO_MODE=true`일 때) `config.auto_mode.max_review_iterations` > `config.review.max_iterations` > 기본값(10)
   - 이후 문서의 "**`--auto` 모드**" 분기는 `AUTO_MODE=true`일 때 동일하게 적용.

### Step 2.5: Static Validation Gate (MANDATORY)

> 이 Step의 목적: Pass A 진입 전에 정적 실패를 선차단한다 / 핵심 출력물: `static_validation_gate_result`, `static-validation-report.md`

- 실행 위치:
  - Step 2 직후 즉시 실행한다.
  - Step 3(Pass A) 시작 전에 완료되어야 한다.
- 게이트 원칙:
  - 모든 하위 검증이 통과해야 `static_validation_gate_result=pass`.
  - `pass`가 아니면 Step 4(Pass B) 진입을 금지한다.
  - `static-validation-report.md`에 각 검증의 `Command/Expected/Actual/Exit Code`를 기록한다.

#### TS 타입체크 게이트

- 실행 조건:
  - Step 2의 `changed_files`에 `*.ts` 또는 `*.tsx`가 1개 이상 포함되고,
  - 대상 worktree에 `tsconfig*.json`이 1개 이상 존재할 때.
- 실행 명령:
  - `package.json.scripts.typecheck` 존재 시: `npm run typecheck`
  - 미존재 시 fallback: `npx tsc --noEmit`
- 실패 처리:
  - `pass_a_result = "fail"`
  - `failure_class = "implementation"`
  - `static_validation_gate_result = "fail"`
  - Step 3/4를 건너뛰고 Step 6(e) 경로로 진행한다.

#### 빌드 게이트

- 실행 조건:
  - `package.json.scripts.build`가 존재할 때.
- 실행 명령:
  - `npm run build`
- 실패 처리:
  - `pass_a_result = "fail"`
  - `failure_class = "implementation"`
  - `static_validation_gate_result = "fail"`
  - Step 3/4를 건너뛰고 Step 6(e) 경로로 진행한다.

#### spec 참조 파일 존재성 게이트

- 실행 조건:
  - Step 2-a의 `spec_reference_files.length > 0`.
- 실행 명령:
  - 각 경로에 대해 `test -e <path>` 실행.
- 실패 처리(미존재 파일 1개 이상):
  - `review.json.status = "gap_found"`
  - `review.json.gap_source = "ac_gap"`
  - `static_validation_gate_result = "gap_found"`
  - 누락 파일 목록을 근거로 갭 태스크 생성 규약을 적용하고 Step 6(c) 경로로 진행한다.
- 하위 호환:
  - `spec_reference_files`가 비어 있으면 이 게이트는 skip한다(비차단).

#### Step 3/4 연결 규칙 (호환성 보장)

- Step 3 진입 허용: `static_validation_gate_result == "pass"`
- Step 3 진입 차단: `static_validation_gate_result in {"fail", "gap_found"}`
- Step 4(Pass B) 최종 진입 허용: `pass_a_result == "pass"` AND `static_validation_gate_result == "pass"` AND `coverage_matrix_gate_result == pass` AND `full_backend_test_gate_result in {pass, pass_with_warning}`

### Step 3: Pass A — 인수 판정 (AC 충족성 검증)

> 이 Step의 목적: AC 충족 여부를 확정해 Pass B 진입 가능성을 결정한다 / 핵심 출력물: `pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`

#### Pass A 타입 분기 (if 1개, MANDATORY)

- `if strategy.review_mode == "fulltext"`:
  - 코드 중심 AC 해석 대신 문서 품질 AC 기준(정확성/완결성/독자적합성)으로 판정한다.
  - 근거는 문서 본문/구조/팩트 확인 결과를 `evidence-ledger.md`에 기록한다.
- `else` (`strategy.review_mode != "fulltext"`):
  - 기존 Pass A 절차를 그대로 적용한다. (변경 금지)

#### evidence-ledger.md 생성 프로토콜 (Pass A 내부, MANDATORY)

- 목적: Pass A에서 수행한 AC/PAC 검증의 실제 실행 증거(명령/기대/실제/exit code)를 구조화해 선언형 완료를 방지한다.
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
- Spec AC 기록 규칙:
  - `[automatable]` AC: `Test:` 명령 실행 직후 반드시 append한다.
    - `Command`: 실행한 명령 원문
    - `Expected`: AC의 Then/Test에서 도출한 기대 결과
    - `Actual`: stdout/stderr 요약 또는 관찰 결과
    - `Exit Code`: 실행 종료 코드(정수)
  - `[manual]` AC: 명령 실행 없이 append한다.
    - `Command`: `manual-judgement`
    - `Expected`: AC의 Then 문장
    - `Actual`: PM 판정 근거 텍스트(무엇을 확인했고 왜 PASS/FAIL인지)
    - `Exit Code`: `N/A`
- Plan AC(PAC) 기록 규칙:
  - `source_plan`이 있고 `plan.ids.json`이 존재하면 PAC별 검증 결과를 동일 형식으로 append한다.
  - PAC 항목에 실행 가능한 `Test:` 명령이 있으면 실행하고 `Command/Expected/Actual/Exit Code`를 기록한다.
  - 실행 명령이 없는 PAC는 `manual-judgement`로 기록하고 PM 판정 근거를 `Actual`에 남긴다.
  - `source_plan` 또는 `plan.ids.json`이 없으면 PAC 섹션은 skip한다 (하위 호환).
- append 타이밍:
  - 각 AC/PAC의 PASS/FAIL/SKIP 판정 직후 즉시 append한다 (배치 저장 금지).
  - PASS/FAIL 여부와 무관하게 실행/판정이 있었으면 반드시 기록한다.
- 호환성 보장(변경 금지):
  - 기존 Pass A 판정 로직(`pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`)은 변경하지 않는다.
  - `evidence-ledger.md` 생성은 기존 흐름에 추가되는 부가 산출물이며 `pass-a-result.md`를 대체하지 않는다.

#### test_enforcement 게이트 (Pass A 내부, MANDATORY)

- 목적: `test_enforcement.enabled=true`일 때 소스 코드 변경에 테스트 AC가 누락되면 자동으로 `"테스트 미작성"` gap을 생성한다.
- 소스 코드 변경 판정:
  - Step 2의 변경 파일 목록 중 `test_enforcement.exempt_patterns`에 매칭되지 않는 파일이 1개라도 있으면 `source_code_changed=true`.
  - 변경 파일이 모두 `exempt_patterns`에 매칭되면 테스트 면제 적용 (`reason: "비코드 수정(exempt_patterns 매칭)"`).
  - `require_exemption_reason=true`이면 면제 사유를 `ac-results.md` 또는 `review-report.md`에 반드시 기록한다.
- 테스트 프레임워크 판정:
  - Step 2 탐색에서 test runner 감지 결과를 재사용한다 (`jest|vitest|mocha|pytest` 등).
  - test runner 미감지면 테스트 면제 적용 (`reason: "테스트 프레임워크 미존재"`; `no test framework`).
  - 면제는 워크플로우를 차단하지 않는다.
- 테스트 AC 존재 판정(면제 아님 + `source_code_changed=true`일 때):
  - 아래 중 하나라도 만족하면 테스트 AC가 존재한다고 본다.
    - `ac_type == browser-test`
    - `ac_test_type`이 `[unit-test]`, `[integration]`, `[api-test]`, `[e2e-browser]`, `[regression-test]`
    - AC `Test:`에 테스트 실행 명령이 명시됨 (`test`, `vitest`, `jest`, `pytest`, `playwright` 등)
  - 모두 미충족이면 Pass A에서 즉시 gap 생성:
    - `pass_a_result = fail`
    - `failure_class = implementation`
    - `failed_ac_ids`에 `AC-TEST-ENFORCEMENT` 추가
    - `evidence`에 `"gap: 테스트 미작성 (test_enforcement)"`를 기록
  - 이 규칙은 기존 MUST/SHOULD 판정 전에 선행 적용한다.
- 하위 호환:
  - `test_enforcement.enabled=false`이면 본 게이트를 건너뛰고 기존 Pass A 동작을 그대로 유지한다.
  - `test_enforcement` 키 자체가 없는 프로젝트는 위 fallback 기본값으로 해석하며, 파싱 실패 시 경고 후 기존 동작으로 graceful fallback한다.

#### browser-test AC 실행 분기 (Pass A 내부, MANDATORY)

- 대상: Step 2에서 `ac_type == browser-test`로 파싱된 Spec AC.
- 저장 경로(요청 단위):
  - 디렉토리: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/`
  - 결과 JSON: `results.json`
  - 스크린샷: `screenshots/*.webp`
- 실행 순서:
  1. `browser-tests/BT-{RV-NNN}/screenshots` 디렉토리를 생성한다.
     ```bash
     mkdir -p {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/screenshots
     ```
  1.5. 실행 모드를 결정한다.
     - `config.resolved.json.review.roles.browser_tester.agent`가 존재하면 `execution_mode = delegated`.
       - `delegate_agent = review.roles.browser_tester.agent`
       - `delegate_tier = review.roles.browser_tester.tier || providers[delegate_agent].default_tier`
     - 키가 없거나 값이 비어 있으면 `execution_mode = pm_direct`로 간주하고 기존 PM 직접 실행 절차를 그대로 유지한다 (하위 호환).
  2. `execution_mode == delegated`이면 browser-test AC 실행을 서브에이전트에 위임한다.
     - 에이전트 유형별 dispatch는 본 문서의 `에이전트 유형별 dispatch 패턴`을 그대로 사용한다 (codex/gemini/claude 공통 규칙 재사용).
     - 위임 프롬프트는 파일로 저장 후 전달한다:
       - `Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/browser-tester-prompt.md`
     - 프롬프트에는 아래 내용을 포함한다.
       - 대상 AC 목록(`ac_type == browser-test`)
       - 본 섹션의 도구 감지/사전 검증/실행/스크린샷 저장 규칙
       - 결과 반환 스키마(`results[].ac_id/status/reason/screenshot/precheck_screenshot`)
     - PM은 에이전트 반환 결과를 수신해 `{...}/browser-tests/BT-{RV-NNN}/results.json`에 기록한다.
     - 실패 fallback:
       - 서브에이전트 실행 실패/타임아웃/결과 파싱 실패 시 해당 AC를 `FAIL` 또는 `SKIP(agent_failed)`로 기록하고 다음 AC로 진행한다.
       - 워크플로우는 중단하지 않는다.
  3. `execution_mode == pm_direct`이면 기존 PM 직접 실행 절차를 따른다.
  3.1. 도구 가용성을 아래 우선순위로 감지한다.
     - 1순위: Playwright CLI 스킬 사용 가능 여부 (`Skill(skill: "playwright-cli", ...)` 호출 가능한지)
     - 2순위: Claude in Chrome MCP 도구 사용 가능 여부 (`mcp__claude-in-chrome__computer` 도구가 로드 가능한지)
     - 감지 결과를 `tool` 변수에 기록: `"playwright"` | `"claude-in-chrome"` | `"unavailable"`
  3.2. 사전 검증 프로토콜 (MANDATORY): `tool != "unavailable"`일 때, 실제 AC 인터랙션 전에 아래 3단계를 선행한다.
     - Step 1. 열린 탭 나열 + 대상 탭 식별:
       - Claude in Chrome: `mcp__claude-in-chrome__tabs_context_mcp`(`tabs_context_mcp`)를 호출해 열린 브라우저 탭을 나열하고, AC 실행 대상 탭(`TARGET_TAB_ID`)을 식별한다.
       - Playwright: 대상 `TEST_URL`로 직접 navigate하여 페이지 컨텍스트를 확보한다 (탭 나열 불필요 — Playwright가 자체 브라우저 인스턴스를 관리).
     - Step 2. 대상 페이지 스크린샷 촬영:
       기존 스크린샷 캡처 패턴과 동일한 도구를 사용해 현재 페이지 상태를 캡처한다.
       - `{PRECHECK_SCREENSHOT_PATH}` = `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/screenshots/precheck-{AC-ID}.webp`
       - Playwright: `Skill(skill: "playwright-cli", args: "screenshot --url {TEST_URL} --output {PRECHECK_SCREENSHOT_PATH}")`
       - Claude in Chrome: `mcp__claude-in-chrome__computer(action: "screenshot", tabId: {TARGET_TAB_ID})` → 결과를 `{PRECHECK_SCREENSHOT_PATH}`에 저장
       - 저장 성공 시 `results[].precheck_screenshot` = `"screenshots/precheck-{AC-ID}.webp"` 기록. 실패 시 `null`.
     - Step 3. 주요 선택자 DOM 존재 확인:
       실제 인터랙션에 필요한 주요 선택자를 확인한다.
       - Claude in Chrome: `mcp__claude-in-chrome__find`
       - Playwright: selector 확인(`locator`/`waitForSelector`)으로 동등 검증
     - 게이트 조건:
       위 3단계를 모두 PASS한 경우에만 아래 3.3(AC 실행)으로 진행한다.
     - 실패 처리:
       3단계 중 하나라도 실패하면 사전 검증 프로토콜을 1회 재시도한다. 재시도 후에도 실패하면 해당 AC를 `FAIL`로 처리하고 실제 인터랙션을 진행하지 않는다.
  3.3. 가용 도구가 있으면 각 browser-test AC를 실제 브라우저에서 실행하고 PASS/FAIL을 판정한다.
     - AC의 `Given/When/Then/Test` 문장을 그대로 실행 시나리오 입력으로 사용한다.
     - **스크린샷 캡처/저장 (MANDATORY — 생략 금지)**:
       각 AC 실행 직후 반드시 스크린샷을 캡처하고 파일로 저장한다.

       **Playwright 사용 시:**
       ```
       Skill(skill: "playwright-cli", args: "screenshot --url {TEST_URL} --output {SCREENSHOT_PATH}")
       ```
       - `{SCREENSHOT_PATH}` = `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/screenshots/{AC-ID}.webp`
       - Playwright가 직접 WebP로 저장하지 못하면 PNG로 캡처 후 변환:
         ```bash
         # PNG → WebP 변환 (cwebp 사용 가능 시)
         cwebp -q 80 {AC-ID}.png -o {AC-ID}.webp 2>/dev/null && rm {AC-ID}.png
         # cwebp 미설치 시 PNG 그대로 유지 (파일명만 .png로 기록)
         ```

       **Claude in Chrome 사용 시:**
       1. `ToolSearch(query: "select:mcp__claude-in-chrome__computer")` 로 도구 로드
       2. 테스트 페이지 탐색 후 `mcp__claude-in-chrome__computer(action: "screenshot", tabId: {TAB_ID})` 실행
       3. 반환된 스크린샷 이미지를 파일로 저장:
          ```bash
          # screenshot 결과에서 이미지 ID 추출 후 GIF creator 또는 직접 저장
          # base64 이미지 데이터가 반환되면:
          python3 -c "
          import base64, sys
          data = base64.b64decode(sys.argv[1])
          with open(sys.argv[2], 'wb') as f:
              f.write(data)
          " "{BASE64_DATA}" "{SCREENSHOT_PATH}"
          ```
          - `{SCREENSHOT_PATH}` = `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/browser-tests/BT-{RV-NNN}/screenshots/{AC-ID}.webp`
          - Chrome screenshot이 JPEG로 반환되면 `.jpg` 확장자로 저장 (WebP 강제 변환 불필요)

     - **저장 후 검증 (MANDATORY)**:
       ```bash
       ls -la {SCREENSHOT_PATH}
       ```
       - 파일 존재 + 크기 > 0 → 저장 성공. `results[].screenshot` = `"screenshots/{AC-ID}.webp"` 기록.
       - 파일 미존재 또는 크기 0 → 저장 실패. 아래 fallback 적용.

     - **저장 실패 fallback**:
       - `results[].screenshot` = `null` 로 기록.
       - 경고 출력: `"[WARN] {AC-ID} 스크린샷 저장 실패 — screenshot=null로 기록"`
       - 워크플로우는 중단하지 않고 다음 AC로 진행한다.

  3.4. 가용 도구가 없으면 워크플로우를 중단하지 않고 해당 AC를 `SKIP(tool_unavailable)`으로 기록한다.
     - 이 경우 MUST AC라도 `pass_a_failed`로 강등하지 않는다.
     - 사용자 보고에는 "브라우저 도구 미가용으로 browser-test AC를 SKIP"을 명시한다.
     - `results[].screenshot` = `null`, `results[].reason` = `"tool_unavailable"` 기록.
- `results.json` 최소 스키마:
  ```json
  {
    "id": "BT-RV-NNN",
    "rv_id": "RV-NNN",
    "created_at": "<ISO8601>",
    "tool": "playwright | claude-in-chrome | unavailable",
    "summary": { "pass": 0, "fail": 0, "skip": 0 },
    "results": [
      {
        "ac_id": "AC-001",
        "status": "PASS | FAIL | SKIP",
        "reason": "tool_unavailable | assertion_failed | ...",
        "screenshot": "screenshots/AC-001.webp",
        "precheck_screenshot": "screenshots/precheck-AC-001.webp"
      }
    ]
  }
  ```
- browser-test AC 실행 결과는 `ac-results.md` 근거란에도 반영한다.

자세한 절차: `templates/protocols/pass-a-protocol.md` 참조

#### 테스트 유형 보조 태그 실행 분기 (Pass A 내부, 선택적)

> 이 분기는 `ac_test_type`이 설정된 AC에만 적용된다. `ac_test_type == null`인 AC는 기존 동작을 따른다.

#### [impact-check] AC DEFERRED 분기 (Pass A 내부, MANDATORY)

- 대상: Step 2에서 `[impact-check]` 보조 태그가 파싱된 Spec AC.
- 처리 규칙:
  - Pass A에서는 PASS/FAIL을 확정하지 않고 `DEFERRED`로 기록한다.
  - `ac-results.md` 근거란에는 `DEFERRED (→ Pass B impact_reviewer)`로 명시한다.
  - `DEFERRED` 항목은 MUST/SHOULD 카운트 및 `pass_a_failed` 판정에서 제외한다.
  - Pass A의 `failed_ac_ids`/`failure_class`/`evidence` 집계에도 포함하지 않는다.
- 하위호환: `[impact-check]` AC가 0건이면 이 분기를 graceful skip하고 기존 Pass A 동작을 그대로 유지한다.

#### [regression-test] AC 실행 분기 (Pass A 내부, MANDATORY)

- 대상: Step 2에서 `[regression-test]` 보조 태그가 파싱된 Spec AC.
- 실행 규칙:
  - AC `Test:` 필드에 명시된 회귀 테스트 명령어를 실행한다.
  - 명령어 성공(exit code 0)이면 PASS, 실패(exit code != 0 또는 assertion 실패)면 FAIL.
  - 회귀 테스트는 "수정 대상 파일/함수 + 1단계 연관 모듈(static import/caller)"의 기존 동작 보존 확인 목적임을 근거에 명시한다.
- 실패 처리(강제):
  - `[regression-test]` AC가 1건이라도 FAIL이면 해당 review iteration을 `pass_a_failed`로 처리한다.
  - 이 규칙은 일반 SHOULD 경고 정책보다 우선한다(즉, 회귀 테스트 실패는 iteration FAIL).
  - 실패 근거는 `ac-results.md`와 `pass-a-result.md`에 반드시 남긴다.
- 하위호환: `[regression-test]` AC가 0건이면 이 분기를 graceful skip하고 기존 Pass A 동작을 그대로 유지한다.

- **[build-check]**: AC의 `Test:` 필드에 명시된 빌드 명령어를 실행한다. exit code 0이면 PASS, 아니면 FAIL.
- **[lint-check]**: AC의 `Test:` 필드에 명시된 린트 명령어를 실행한다. 위반 0건이면 PASS.
- **[unit-test]**: AC의 `Test:` 필드에 명시된 테스트 명령어를 실행한다. 전체 PASS이면 PASS.
  - **커버리지 검증 (선택적)**: `source_plan`이 존재하고 plan.md `## 테스트 전략` 섹션에 `목표 커버리지`가 설정되어 있으면:
    - 테스트 명령어에 `--coverage` 플래그를 추가하여 실행한다.
    - 변경된 파일의 line coverage가 목표 이상인지 확인한다.
    - 미달 시 FAIL 판정 + "커버리지 {실제}% < 목표 {목표}%" 보고.
    - 커버리지 도구가 미설치이면 graceful skip (커버리지 검증만 skip, 테스트 자체는 실행).
- **[integration]** / **[api-test]**: AC의 `Test:` 필드에 명시된 테스트 명령어를 실행한다.
- **[e2e-browser]**: 기존 `browser-test AC 실행 분기`를 그대로 재사용한다. 별도 구현 없음.
- **[visual]**: 비주얼 비교 도구를 감지하고 AC의 `Test:` 필드 명령어를 실행한다.
- **[performance]**: 벤치마크 도구를 감지하고 AC의 `Test:` 필드 명령어를 실행한다.
- **[regression-test]**: 위 `[regression-test] AC 실행 분기`를 따른다 (실패 시 iteration FAIL 강제).

**공통 규칙**:
- 모든 보조 태그 실행은 AC의 `Test:` 필드에 명시된 명령어를 기반으로 한다.
- 도구 미설치 시: `SKIP(tool_unavailable)` 기록 + "[SKIP] {태그}: 도구 미설치 ({도구명})" 로그 출력.
- 실행 결과는 `ac-results.md` 근거란에 반영한다.
- 실행/판정 직후 `evidence-ledger.md`에도 `Command/Expected/Actual/Exit Code`를 append한다.

---

### Step 3.4: Spec↔Diff Coverage Matrix Gate (MANDATORY)

> 이 Step의 목적: Pass A 직후 AC-ID/PAC-ID 기준의 Spec↔Diff 양방향 커버리지를 기계적으로 검증해 Pass B 진입 누락을 차단한다 / 핵심 출력물: `coverage_matrix_gate_result`, `coverage-matrix.json`, `coverage-matrix.md`

- 실행 위치:
  - Step 3(Pass A) 완료 직후 실행한다.
  - Step 3.5(Full Backend Test Gate) 진입 전에 완료되어야 한다.
- 진입 조건:
  - `pass_a_result == pass`이고 `static_validation_gate_result == "pass"`일 때만 실행한다.
  - `pass_a_result == fail`이면 본 Step을 skip하고 기존 Step 6(e) 경로를 그대로 따른다.
- 산출물 경로:
  - JSON: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/coverage-matrix.json`
  - MD: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/coverage-matrix.md`

#### coverage-matrix.json 스키마 (MANDATORY)

```json
{
  "spec_to_diff": [
    {
      "id": "AC-001 | PAC-4",
      "kind": "spec_ac | plan_ac",
      "grade": "MUST | SHOULD",
      "ac_type": "automatable | manual | browser-test",
      "mapped_diff_refs": ["src/module/file.ts#L10"],
      "is_mapped": true,
      "unmapped_reason": ""
    }
  ],
  "diff_to_spec": [
    {
      "diff_ref": "src/module/file.ts#L10",
      "mapped_ids": ["AC-001", "PAC-4"],
      "is_mapped": true,
      "unmapped_reason": ""
    }
  ],
  "summary": {
    "spec_total": 0,
    "spec_mapped_count": 0,
    "spec_unmapped_count": 0,
    "must_total": 0,
    "must_mapped_count": 0,
    "must_unmapped_count": 0,
    "diff_total": 0,
    "diff_mapped_count": 0,
    "diff_unmapped_count": 0
  }
}
```

- `spec_to_diff[]`:
  - Step 2에서 파싱된 Spec AC + Plan AC(PAC)를 각각 1행으로 기록한다.
  - 각 ID가 어떤 변경(diff ref)로 충족되는지 양방향 추적 가능해야 한다.
- `diff_to_spec[]`:
  - Step 2의 `changed_files`(필요 시 파일 내 핵심 hunks 포함)를 기준으로 각 변경이 어떤 AC/PAC와 연결되는지 기록한다.
  - 어떤 AC/PAC에도 매핑되지 않은 변경은 `is_mapped=false`로 남기고 `unmapped_reason`을 기록한다.
- `summary`:
  - `must_unmapped_count`는 `grade=MUST`인 AC/PAC 중 `is_mapped=false` 개수다.

#### coverage-matrix.md 생성 규칙 (MANDATORY)

- 사람 검토용 요약 리포트를 같은 RV 폴더에 생성한다.
- 최소 포함 항목:
  - `Spec -> Diff` 표 (ID, grade, ac_type, mapped_diff_refs, unmapped_reason)
  - `Diff -> Spec` 표 (diff_ref, mapped_ids, unmapped_reason)
  - 요약 블록 (`must_unmapped_count`, `spec_unmapped_count`, `diff_unmapped_count`)

#### Hard Gate (MANDATORY)

- `summary.must_unmapped_count == 0`일 때만 `coverage_matrix_gate_result = pass`로 처리한다.
- `summary.must_unmapped_count > 0`이면:
  - `coverage_matrix_gate_result = gap_found`
  - `review.json.status = "gap_found"`
  - `review.json.gap_source = "ac_gap"`
  - unmapped MUST AC/PAC별 갭 태스크를 기존 Step 6(c) 생성 규약(`generated_by: "review"`)으로 자동 생성한다.
  - Step 3.5/Step 4 진입을 차단하고 Step 6(c)/(d) 경로로 진행한다.
- 하위 호환:
  - SHOULD-only unmapped는 경고로 기록하되 hard blocking 사유로 사용하지 않는다.
  - 기존 Pass A 판정 필드(`pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`)는 변경하지 않는다.

---

### Step 3.5: Full Backend Test Gate (MANDATORY)

> 이 Step의 목적: Pass A 완료 후 Pass B 진입 전에 외부 프로젝트 worktree의 **백엔드 전체 테스트**를 강제 실행한다 / 핵심 출력물: `full_backend_test_gate_result`, `full-backend-test-report.md`, 보강-재테스트 이력

- 진입 조건:
  - `pass_a_result == pass`이고 `coverage_matrix_gate_result == pass`일 때만 실행한다.
  - `pass_a_result == fail`이면 본 Step을 skip하고 기존 Step 6(e) 경로를 그대로 따른다.
  - `coverage_matrix_gate_result == gap_found`이면 본 Step을 skip하고 Step 6(c)/(d) 경로를 따른다.
- 차단 규칙:
  - 전체 테스트가 100% PASS(또는 "테스트 없음" 사용자 확인)되기 전에는 **Step 4(Pass B) 진입 금지**.
- 범위 제한:
  - Node 기반 백엔드 테스트만 대상.
  - 프론트엔드/E2E 테스트(`playwright`, `cypress`, `selenium`, `puppeteer` 등)는 본 게이트 판정 대상에서 제외한다.
- 기존 흐름 호환성:
  - 기존 Pass A/Pass B/Step 5 구조는 유지한다.
  - 게이트 실패 시 신규 분기를 만들지 않고 Step 6(c)/(d)의 기존 갭 처리 경로를 재사용한다(`gap_source: "ac_gap"` 유지).

#### package.json `scripts.test` 자동 탐지 (MANDATORY)

1. 대상 worktree 루트의 `package.json`을 확인한다.
2. `scripts.test`를 자동 탐지한다.
   - 최소 실행 기준(동등 명령 허용):
     ```bash
     grep -q '"test"' package.json && npm test
     ```
3. `scripts.test`가 아래 npm init 기본값과 논리적으로 동일하면 `"테스트 없음"`으로 판단한다.
   - 기준 문자열(공백/따옴표 차이는 normalize 후 비교):
     - `echo "Error: no test specified" && exit 1`
4. `scripts.test`가 없거나 빈 문자열이어도 `"테스트 없음"`으로 동일 처리한다.

#### "테스트 없음" 분기 (MANDATORY)

- `"테스트 없음"`으로 판정되면 `full-backend-test-report.md`에 `status: NO_TESTS_DETECTED`를 기록한다.
- 사용자에게 아래를 반드시 확인한다.
  - 안내: "백엔드 전체 테스트 스크립트가 없어 자동 검증을 수행하지 못했습니다."
  - 질문: "현재 상태로 Pass B/머지 진행을 허용할지"
- `AUTO_MODE=true`여도 `AskUserQuestion`을 생략하지 않는다.
- 사용자 선택:
  - 허용: `full_backend_test_gate_result = pass_with_warning`으로 처리하고 Step 4로 진행.
  - 비허용: `full_backend_test_gate_result = fail`로 처리하고 Step 6(c)/(d) 경로로 이동.

#### 실행/실패 분석 프로토콜 (MANDATORY)

1. 전체 백엔드 테스트 실행:
   - 기본 명령: `npm test`
   - 실행 로그 저장: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/full-backend-test.log`
2. 실패 테스트가 1개 이상이면 각 실패 항목에 대해 `explore` 기반 원인 분석을 수행한다.
   - 예시:
     ```bash
     omx explore --prompt "실패 테스트 {TEST_NAME}의 원인(변경 파일, 호출 경로, 부수효과)을 추적"
     ```
3. 각 실패 항목을 아래 3중 문맥과 비교해 의도성을 판정한다.
   - `intent`: request/plan의 JTBD 의도
   - `plan`: `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`
   - `spec`: 현재 태스크 `spec.md`의 §1/§2/§3 및 Intent Trace
4. 판정 규칙:
   - `INTENTIONAL`: 실패가 plan/spec에 명시된 의도적 동작 변경과 일치
   - `UNINTENTIONAL`: 명시되지 않은 회귀/부수효과
   - `UNCERTAIN`: 증거 불충분. 기본값은 `UNINTENTIONAL`로 처리하고 리포트에 불확실성 표시

#### 의도/비의도 분기 처리 (MANDATORY)

- `INTENTIONAL` 실패:
  - 테스트 기대값/fixture/assertion을 새 동작에 맞게 수정하는 태스크를 자동 디스패치한다.
  - 원칙: 소스 동작 변경 없이 테스트 정합성 회복을 우선한다.
- `UNINTENTIONAL` 실패:
  - 소스 코드 + 테스트 보강 태스크를 자동 디스패치한다.
  - 원칙: 회귀 원인 제거와 재발 방지 테스트 추가를 한 번에 수행한다.
- 공통:
  - 생성 태스크는 기존 review 갭 태스크 생성 규약(`generated_by: "review"`)을 재사용한다.
  - 태스크 완료 후 전체 백엔드 테스트를 즉시 재실행한다.

#### 보강-재테스트 루프 (최대 10회, MANDATORY)

- 루프 카운터: `full_backend_test_retry_count` (현재 RV 기준, 1부터 시작).
- 반복 규칙:
  1. 테스트 실행
  2. 실패 시 explore 분석 + 의도 판정
  3. 분기별 태스크 자동 디스패치
  4. 보강 완료 후 전체 재테스트
- 종료 규칙:
  - 10회 이내 100% PASS: `full_backend_test_gate_result = pass` → Step 4 진입 허용
  - 10회 반복 후에도 FAIL: `full_backend_test_gate_result = limit_reached`로 기록하고 사용자 에스컬레이션
  - 11회째 자동 시도는 금지한다(즉시 에스컬레이션)

#### 결과 리포트 + `evidence-ledger.md` 연계 (MANDATORY)

- 리포트 파일:
  - `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV-NNN}/full-backend-test-report.md`
- 리포트 포맷:
  ```markdown
  # Full Backend Test Report — RV-NNN

  - status: PASS | PASS_WITH_WARNING | FAIL | LIMIT_REACHED | NO_TESTS_DETECTED
  - attempts: N/10
  - command: npm test
  - summary: total=<N>, passed=<N>, failed=<N>, skipped=<N>

  ## Failed Tests
  | Test | Intent Verdict | Classification | Root Cause (explore) | Action |
  |------|----------------|----------------|----------------------|--------|
  | <name> | INTENTIONAL \| UNINTENTIONAL \| UNCERTAIN | test-only \| source+test | <요약> | <dispatch task id> |

  ## Escalation
  - escalated: true|false
  - reason: <10회 초과 / 사용자 선택 / 없음>
  ```
- `evidence-ledger.md` 연계:
  - 각 테스트 실행 직후 `Spec AC 검증 증거` 표에 아래 형식으로 append한다.
    - `ID`: `AC-FULL-BACKEND-TEST-GATE`
    - `Type`: `automatable`
    - `Command`: `npm test`
    - `Expected`: `전체 백엔드 테스트 100% PASS`
    - `Actual`: `pass/fail 카운트 + 주요 실패 테스트명`
    - `Exit Code`: 실제 종료 코드

#### Step 4/5 연결 규칙 (호환성 보장)

- Step 4 진입 허용 조건:
  - `coverage_matrix_gate_result == pass`
  - `full_backend_test_gate_result in {pass, pass_with_warning}`
- Step 4 진입 차단 조건:
  - `coverage_matrix_gate_result == gap_found`
  - `full_backend_test_gate_result in {fail, limit_reached}`
  - 이 경우 Pass B를 생략하고 Step 6(c)/(d) 기존 경로로 진행한다.
- Step 5 취합 시 `full-backend-test-report.md`가 존재하면 `review-report.md`에 요약을 포함한다.

---

### Step 4: Pass B — 코드/문서 품질 검증

> 이 Step의 목적: Pass A 통과 산출물을 기반으로 코드/설계/UI/의도 충실도/영향 범위/적대적 관점 갭을 찾는다 / 핵심 출력물: `ac-results.md`, `review-code.md`, `review-arch.md`, `review-ui.md`, `review-intent-fidelity.md`, `review-impact.md`, `review-adversarial.md`

#### Pass B 타입 분기 (if 1개, MANDATORY)

- `if strategy.review_mode == "fulltext"`:
  - 코드 리뷰 프롬프트 대신 문서 구조/품질 리뷰 프롬프트를 사용한다.
  - 검토 기준은 정확성, 완결성, 독자적합성, 구조/가독성으로 고정한다.
  - 입력은 `git diff`가 아니라 문서 전문(full text)이며, 신규 문서(diff 없음)도 동일하게 전문 리뷰를 수행한다.
  - 결과 산출 경로는 기존과 동일하게 유지한다 (`review-code.md` 재사용).
- `else` (`strategy.review_mode != "fulltext"`):
  - 기존 Pass B 절차를 그대로 적용한다. (변경 금지)

##### strategy.review_mode=="fulltext" Pass B 전문 리뷰 규칙 (MANDATORY)

1. 입력 데이터
   - 리뷰 대상 문서는 `spec §2 변경 범위`에 명시된 파일 기준으로 식별한다.
   - 각 문서 파일은 `Read`로 원문 전체를 로드해 프롬프트에 전달한다 (요약본/부분 diff 사용 금지).
2. 체크리스트 (모든 항목 필수)
   - 정확성(소스 대비): claim이 소스/근거와 일치하는지, 과장/추정 서술이 없는지 확인
   - 완결성(TOC 대비): plan/spec의 TOC 항목이 누락 없이 반영됐는지 확인
   - 독자적합성(plan 대비): plan의 목적/독자/결과물 조건에 맞는 설명 깊이와 톤인지 확인
   - 구조(헤딩 체계): H1/H2/H3 계층, 섹션 순서, 문단 흐름이 일관적인지 확인
3. 산출 형식
   - `review-code.md`에 위 4개 축별 `PASS|FAIL`과 근거를 표 형태로 기록한다.
   - FAIL 항목은 반드시 수정 권고(어떤 섹션을 어떻게 고칠지)를 포함한다.

Pass B는 Claude(인컨텍스트)와 background 에이전트 6개(기존 5개 + adversarial_reviewer)를 동시 시작합니다.

```
Claude (인컨텍스트):   spec §3 AC 체크리스트 순차 검증  ─┐
code-reviewer (bg):   구현 레벨 리뷰                  ─┤─→ Step 5에서 PM 취합 → review-report.md
arch-reviewer (bg):   설계/계획 레벨 리뷰              ─┤
ui-reviewer (bg):     UI 설계 검토 (조건부)            ─┤
intent-fidelity (bg): 원본 의도 대비 구현 일치 검증     ─┤
impact-reviewer (bg): 영향 범위(회귀 영향) 분석         ─┤
adversarial-reviewer (bg): 공격 표면 기반 적대적 리뷰   ─┘
```

#### Claude 인컨텍스트: AC 검증

- 각 AC 항목별로 관련 코드/설정 파일 Read.
- PASS / FAIL / UNKNOWN 판정 후 근거 기록.
- **Plan AC(PAC-N 또는 레거시 PLAN-AC-N)가 있으면 Spec AC와 별도 섹션으로 검증**한다.
  - Plan AC는 구현 상세보다 **관찰 가능한 결과/동작** 기준으로 판정한다 (예: "X 버튼 클릭 시 Y 결과 표시").
  - Plan AC 미충족은 MUST 등급 실패로 처리하고, spec AC 실패와 동일하게 Pass A 실패 트리거 대상이 된다.
- 결과를 `reviews/RV-NNN/ac-results.md`에 저장.
  ```markdown
  # AC 검증 결과 — RV-NNN

  ## Spec AC
  | AC | 등급 | 판정 | 근거 |
  |----|------|------|------|
  | AC-1 | MUST | ✅ PASS | ... |
  | AC-2 | SHOULD | ❌ FAIL | ... |

  ## Plan AC (PLN-NNN)
  | AC | 판정 | 근거 |
  |----|------|------|
  | PAC-1 | ✅ PASS | ... |
  | PAC-2 | ❌ FAIL | ... |
  ```
  Plan AC 섹션이 없으면 (source_plan 미존재 시) 생략한다.

#### Background 에이전트 dispatch

background 에이전트는 `run_in_background: true` 옵션으로 dispatch합니다 (approve SKILL.md Step 4d 완료 감지 패턴 동일 적용).

| 역할 키 | 검토 관점 | config 키 | 모델 resolve |
|---------|-----------|-----------|-------------|
| `code_reviewer` | 누락 로직, 버그, 엣지케이스, 테스트 누락 + **테스트 패턴 준수 검증**: spec에 주입된 유형별 원칙(2-3줄)을 기준으로 작성된 테스트 코드의 패턴 준수 여부 점검. 미준수 시 [MAJOR] 등급 이슈로 보고. | `review.roles.code_reviewer.agent` | `providers[agent][review.roles.code_reviewer.tier \|\| default_tier]`로 resolve |
| `arch_reviewer` | spec 의도 vs 구현 방향 차이, 통합 일관성 + Scope Audit(필수): `SCOPE_CREEP`(spec.md에 없는 구현), `OMISSION`(spec.md에는 있으나 구현 누락) 점검. plan.md가 있는 경우 상위 목표·방향 대비 구현 적합성도 반드시 확인. 불필요한 파일 변경(범위 외 수정) 여부 점검. 미발견 시에도 `"확인 완료 — 해당 없음"` 명시 | `review.roles.arch_reviewer.agent` | `providers[agent][review.roles.arch_reviewer.tier \|\| default_tier]`로 resolve |
| `ui_reviewer` | Stitch 시안 vs 실제 UI, UX 흐름 일관성 | `review.roles.ui_reviewer.agent` | `providers[agent][review.roles.ui_reviewer.tier \|\| default_tier]`로 resolve |
| `intent_fidelity` | 원본 의도(plan 요청 + docs) 대비 구현 일치 검증. spec §3.2 Intent Trace의 각 항목을 구현 증거와 대조. Missing/Partial/Verified 분류. 기본 blocking 모드에서 MUST 항목 Partial/Missing은 pass/fail에 반영, SHOULD는 warning으로만 추적 | `review.roles.intent_fidelity.agent` | `providers[agent][review.roles.intent_fidelity.tier \|\| default_tier]`로 resolve |
| `impact_reviewer` | `git diff --name-only` 기준 변경 파일 식별 후 영향 범위를 회귀 관점으로 검토. `review.roles.impact_reviewer.enhanced_analysis=true`이면 각 변경 파일의 정적 `import`/`require`를 **2단계 역추적**(변경 파일 → 직접 의존자 → 간접 의존자)하고, 역추적된 의존 파일 소스를 직접 Read하여 변경 내용과 대조해 기능 깨짐 여부를 판단한다. `enhanced_analysis=false`이면 기존 **1단계 역추적 + [IMPACT] 태그 체계**만 유지한다. 영향 이슈는 Impact 전용 rubric(공개 API/라우트=CRITICAL, 공유 컴포넌트/유틸리티=MAJOR, 내부 모듈=MINOR)으로 태깅. 추가로 `[impact-check]` AC가 있으면 Given/When/Then 조건의 PASS/FAIL verdict를 AC별로 전담 판정한다. | `review.roles.impact_reviewer.agent` | `providers[agent][review.roles.impact_reviewer.tier \|\| default_tier]`로 resolve |
| `adversarial_reviewer` | 보안/데이터 무결성/동시성/롤백 안전/null·timeout/버전 스큐/관측성 등 attack surface 관점으로 적대적 리뷰를 수행한다. finding에는 `attack_surface`와 `confidence(0~1)`를 포함하며, Step 5에서 confidence→severity 매핑을 적용해 통합한다. | `review.roles.adversarial_reviewer.agent` | `providers[agent][review.roles.adversarial_reviewer.tier \|\| default_tier]`로 resolve |

### 테스트 패턴 준수 검증 (code_reviewer 추가 관점)

spec.md에 유형별 원칙이 주입된 AC가 있는 경우:
1. 해당 AC의 보조 태그([unit-test], [api-test] 등)와 주입된 원칙(2-3줄)을 확인한다.
2. 구현된 테스트 코드가 해당 원칙을 따르는지 검증한다.
3. 미준수 항목은 [MAJOR] 등급으로 보고한다. 예:
   - "[MAJOR] AC-003 [unit-test]: AAA 패턴 미준수 — setup과 assertion이 혼재"
   - "[MAJOR] AC-005 [api-test]: schema 검증 누락"
4. 보조 태그가 없는 AC는 이 검증을 skip한다.

각 리뷰어(code_reviewer, arch_reviewer, ui_reviewer, impact_reviewer, adversarial_reviewer)는 발견한 이슈에 반드시 `[CRITICAL]`, `[MAJOR]`, `[MINOR]` 등급을 태깅해야 한다 (`templates/review-request.md`의 등급 판별 가이드 및 보안 오버라이드 규칙 적용).
adversarial_reviewer는 등급 태깅과 별개로 finding별 `confidence`를 필수로 포함하며, Step 5에서 confidence 기준 재매핑 결과를 최종 severity로 사용한다.
intent_fidelity는 등급 대신 `Verified/Partial/Missing` + `INTENT-GAP` 카운트를 출력한다.

arch_reviewer dispatch 시 `templates/review-request.md`의 `{{PERSPECTIVE}}`에는 위 Scope Audit 지시(`SCOPE_CREEP`, `OMISSION`, 미발견 시 `"확인 완료 — 해당 없음"` 명시)를 반드시 포함해 전달한다.

각 에이전트 프롬프트에 출력 파일 경로를 명시하여 전달합니다:
- code_reviewer → `reviews/RV-NNN/review-code.md`
- arch_reviewer → `reviews/RV-NNN/review-arch.md`
- ui_reviewer → `reviews/RV-NNN/review-ui.md`
- intent_fidelity → `reviews/RV-NNN/review-intent-fidelity.md`
- impact_reviewer → `reviews/RV-NNN/review-impact.md`
- adversarial_reviewer → `reviews/RV-NNN/review-adversarial.md`

- `{{SPEC_PATH}}`: 해당 태스크의 `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/tasks/{NN}/spec.md` 절대 경로
- `{{PLAN_PATH}}`: `request.json.source_plan` 존재 시 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`, 미존재 시 `"N/A"`
- `{{REFERENCE_CONTEXT}}`: Step 2에서 생성한 `[REFERENCE_CONTEXT]` 블록 (`references: none` 포함). code/arch/ui/intent_fidelity/impact/adversarial 모든 리뷰어 프롬프트에 동일 주입.
- `{{SPEC_REFERENCE_CONTEXT}}`: Step 2-a에서 생성한 spec 직접 참조 파일 컨텍스트 블록(`spec_reference_context_block`). code/arch/ui/intent_fidelity/impact/adversarial 모든 리뷰어 프롬프트에 동일 주입한다.
- `if strategy.review_mode == "fulltext"`:
  - 프롬프트 본문에 문서 전문(full text)을 직접 포함하고, diff 요약은 참고 정보로만 사용한다.
  - `code_reviewer`의 검토 포커스를 문서 품질(정확성/완결성/독자적합성/구조) 체크리스트로 고정한다.

#### impact_reviewer dispatch 입력 규칙

- `review.roles.impact_reviewer.enabled != true`이면 auto-skip하고 취합 시 `"Impact 리뷰 skip (비활성화)"`를 표시한다.
- 변경 파일 목록(`git diff --name-only {BASE_BRANCH}...HEAD`)이 비어있으면 auto-skip하고 취합 시 `"Impact 리뷰 skip (변경 파일 없음)"`를 표시한다.
- `review.roles.impact_reviewer.enhanced_analysis` 기본값은 `true`다.
- 실행 시 `templates/review-request.md`의 `{{PERSPECTIVE}}`에는 아래 지시를 반드시 포함한다.
  - `enhanced_analysis=true`:
    - `"git diff --name-only 기준 변경 파일 식별 → 각 파일의 정적 import/require를 2단계 역추적(변경 파일 → 직접 의존자 → 간접 의존자) → 역추적된 의존 파일 소스를 Read로 직접 확인하고 변경 내용과 대조해 기능 깨짐 여부 판단"`
    - `"기능 유지"는 코드 무변경이 아니라 기능 정상 동작을 의미하며, 함께 수정이 필요한 파일을 식별`
    - `review-impact.md`에 `확인한 파일 목록`, `판단 근거`, `함께 수정 필요 파일(수정 방향 포함)`을 기록
  - `enhanced_analysis=false`:
    - `"git diff --name-only 기준 변경 파일 식별 → 각 파일의 정적 import/require를 1단계 역추적하여 의존하는 외부 모듈 식별 → 영향 받을 수 있는 기능/페이지/화면 보고"`
    - `기존 [IMPACT] 태그 체계를 그대로 유지`
  - `동적 import/런타임 의존성 추적 제외`
  - `영향 이슈 등급 rubric: 공개 API/라우트 영향=[CRITICAL], 공유 컴포넌트/유틸리티 영향=[MAJOR], 내부 모듈 영향=[MINOR]`
  - `[impact-check]` AC가 있으면 각 AC의 Given/When/Then 충족 여부를 PASS/FAIL/SKIP로 판정하고 `review-impact.md`에 `AC ID | Grade | Verdict | Evidence` 표로 기록
- dispatch는 기존 background 리뷰어와 동일하게 `run_in_background: true`로 병렬 실행한다.

#### adversarial_reviewer dispatch 입력 규칙

- `review.roles.adversarial_reviewer.enabled != true`이면 auto-skip하고 취합 시 `"Adversarial 리뷰 skip (비활성화)"`를 표시한다.
- 프롬프트 템플릿은 `templates/adversarial-review-prompt.md`를 사용한다.
  - 템플릿 Read 실패(FILE_NOT_FOUND 포함) 시 비차단으로 skip하고 취합 시 `[ADVERSARIAL: SKIPPED — prompt template missing]`를 기록한다.
- dispatch는 기존 background 리뷰어와 동일한 `run_in_background: true` 패턴으로 실행한다.
- timeout/에이전트 에러가 발생해도 워크플로우를 중단하지 않는다. Step 5에서 `[ADVERSARIAL: SKIPPED — {timeout|agent_error}]`로 표시하고 기존 역할 취합을 계속 진행한다.

#### [impact-check] AC 전담 판정 규칙 (Pass B, impact_reviewer)

- `[impact-check]` AC가 1개 이상이면 impact_reviewer가 해당 AC의 Given/When/Then 조건을 전담 판정한다.
- 판정 결과는 `reviews/RV-NNN/review-impact.md`에 AC별 verdict로 기록한다.
- `[impact-check]` AC 중 `[MUST]` 등급이 `FAIL`이면 해당 review iteration을 실패로 간주하고 Step 6에서 `gap_found` 분기로 처리한다.
- `review.roles.impact_reviewer.enabled != true`이고 `[impact-check]` AC가 존재하면 해당 AC verdict를 `SKIP`으로 기록하고 경고를 출력한다:
  - `"[WARN] impact-check AC SKIP (impact_reviewer 비활성화): {AC-ID}"`
  - 이 경우는 비차단으로 처리한다 (하위 호환).
- `[impact-check]` AC가 0건이면 기존 impact_reviewer 동작(영향 범위 분석만 수행)을 그대로 유지한다 (graceful skip).

#### impact_reviewer 결과 처리 규칙 (Pass B 공통)

- `review-impact.md`의 이슈 태깅(`[CRITICAL]`, `[MAJOR]`, `[MINOR]`)을 파싱해 반영한다.
- impact_reviewer에서 `[CRITICAL]` 또는 `[MAJOR]` 이슈가 1건이라도 보고되면 해당 review iteration을 `FAIL(gap_found)`로 처리하고 Step 6 `(c)` 경로로 진행한다.
- impact_reviewer 이슈로 `gap_found`가 트리거된 경우, 생성되는 수정 태스크 description에는 `review-impact.md`의 `함께 수정 필요 파일` 목록과 각 파일의 수정 방향을 반드시 포함한다.
- impact_reviewer에서 `[MINOR]`만 보고되면 warning으로 기록만 하고, 해당 사유만으로는 `gap_found`를 트리거하지 않는다.
- 위 규칙은 `[impact-check]` AC 존재 여부와 무관하게 적용한다.

#### intent_fidelity dispatch 입력 규칙

- `intent_fidelity.enabled != true`이면 skip.
- `spec.md`에 `## 3.2 Intent Trace`가 없으면 auto-skip하고 취합 시 `"Intent Fidelity 리뷰 skip (Intent Trace 없음)"`를 표시한다.
- 실행 시 아래 컨텍스트를 함께 전달한다.
  - `spec.md` 원문
  - 구현 diff (`git diff <base>..HEAD`)
  - plan 원본 요청 (`plan.md`의 `## 요청 (Refined)` + `## Intent (JTBD)`)
  - spec `§3.2 Intent Trace` 원문
  - docs 컨텍스트 (`Intent Trace` 근거 출처 및 `intent_snapshot`에서 식별된 관련 docs)
- 출력 파일은 반드시 `reviews/RV-NNN/review-intent-fidelity.md`로 저장한다.
- 리포트 형식은 아래 템플릿을 따른다.
  ```markdown
  # Intent Fidelity 리포트 — RV-NNN

  ## 검증 요약
  - ✅ Verified: N개
  - ⚠️ Partial: N개
  - ❌ Missing: N개
  - ℹ️ INTENT-GAP (근거 없는 AC): N개

  ## 상세

  | AC-ID | 의도 근거 | 구현 증거 | 판정 | 비고 |
  |-------|-----------|-----------|------|------|
  | AC-001 | {의도 문장} | {코드/테스트 위치} | Verified/Partial/Missing | {차이점} |
  ```

#### 프롬프트 파일 사전 저장 (MANDATORY)

> ⚠️ **파이프 방식 금지**: `echo "$PROMPT" | codex exec ... "$(cat)"` 패턴을 사용하면
> shell command substitution이 파이프 연결 전에 평가되어 프롬프트가 빈 문자열로 전달됩니다.
> 반드시 아래 파일 저장 → 파일에서 읽기 방식을 사용하세요.

dispatch 전 각 리뷰어 프롬프트를 반드시 파일로 먼저 저장한다:
```
Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/{role}-prompt.md
```
이 경로를 `{PROMPT_FILE}`로 참조한다. 저장 완료 확인 후 dispatch한다.

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

**ui_reviewer 스킵 조건**: `request.json.stitch_screens` 배열이 비어있고 `frontend/` 디렉토리 변경 파일이 없으면 auto-skip. 취합 시 "UI 리뷰 skip (변경 없음)" 표시.
**impact_reviewer 스킵 조건**: `review.roles.impact_reviewer.enabled=false` 또는 변경 파일 목록 비어있음이면 auto-skip. 취합 시 각각 "Impact 리뷰 skip (비활성화)" 또는 "Impact 리뷰 skip (변경 파일 없음)" 표시.
**adversarial_reviewer 스킵 조건**: `review.roles.adversarial_reviewer.enabled=false`이면 auto-skip. 취합 시 "Adversarial 리뷰 skip (비활성화)" 표시.
**intent_fidelity 스킵 조건**: `intent_fidelity.enabled=false` 또는 `## 3.2 Intent Trace` 미존재 시 auto-skip. 취합 시 각각 "Intent Fidelity 리뷰 skip (비활성화)" 또는 "Intent Fidelity 리뷰 skip (Intent Trace 없음)" 표시.
- `impact_reviewer` 비활성화 상태에서 `[impact-check]` AC가 존재하면 `review-impact.md` 또는 취합 로그에 해당 AC별 `SKIP` 경고를 남긴다 (비차단, 하위 호환).

### Step 5: 완료 대기 및 취합

> 이 Step의 목적: Pass B 산출물을 수집·요약해 리뷰 결과를 단일 리포트로 정리한다 / 핵심 출력물: `review-report.md`

1. **완료 폴링**: background 에이전트 6개(또는 skip된 에이전트 제외) 완료 대기. approve SKILL.md Step 4d 완료 감지 패턴 동일 적용.
   - 에이전트 실패 시: 해당 역할 리뷰 "에이전트 실패" 표시 후 나머지 취합 계속 진행.
   - fallback (FILE_NOT_FOUND 처리): 각 `review-*.md` 파일이 FILE_NOT_FOUND이면 해당 background Agent 반환값(`TaskOutput`)에서 전체 텍스트를 추출한다.
     - 추출 텍스트가 빈 문자열이 아니고 `# ` 또는 `## ` 마크다운 헤더를 1개 이상 포함하면 유효한 리뷰 결과로 간주하고 PM이 해당 `review-*.md` 경로에 Write한다.
     - 추출 텍스트가 비어있거나 헤더가 없으면 해당 역할을 "에이전트 실패"로 표시하고 나머지 취합을 계속 진행한다.
2. **취합 파일**: `ac-results.md` + `review-code.md` + `review-arch.md` + `review-ui.md` + `review-intent-fidelity.md` + `review-impact.md` + `review-adversarial.md` + `coverage-matrix.json` + `coverage-matrix.md` + `full-backend-test-report.md`(선택, Step 3.5 실행 시 생성).
3. **review-report.md 작성**: `reviews/RV-NNN/review-report.md`
   ```markdown
   # 리뷰 리포트 — RV-NNN (REQ-NNN 반복 N)

   ## Spec AC 검증 결과
   - ✅ 충족 AC N개
   - ❌ 미충족/갭 N개
     - AC-X: <설명>

   ## Plan AC 검증 결과 (PLN-NNN)
   <!-- source_plan 없으면 이 섹션 생략 -->
   - ✅ 충족 PAC N개
   - ❌ 미충족 PAC N개
     - PAC-X: <설명>

   ## Spec↔Diff Coverage Matrix 결과
   - MUST unmapped: N건 (hard gate 기준: 0이어야 Pass B 허용)
   - Spec unmapped: N건 / Diff unmapped: N건
   - 상세: `coverage-matrix.md`, `coverage-matrix.json`

   ## Full Backend Test Gate 결과
   - 상태: PASS | PASS_WITH_WARNING | FAIL | LIMIT_REACHED | NO_TESTS_DETECTED
   - 시도 횟수: N/10
   - 테스트 요약: total/passed/failed/skipped
   - 실패 테스트 목록 + 의도 판정(INTENTIONAL/UNINTENTIONAL/UNCERTAIN)
   - 상세: `full-backend-test-report.md` (없으면 "Step 3.5 skip")

   ## 교차 매트릭스 (파일 × attack_surface) — finding 3개+ 시
   - 조건 미충족 시: `finding < 3 (matrix skip)`
   - 셀 표기: `F-NN [합의|단독 발견|상충]`
   - sources: `[role1, role2, ...]`

   ## 코드 리뷰 주요 발견 사항
   <review-code.md 핵심 항목>

   ## 아키텍처 리뷰 주요 발견 사항
   <review-arch.md 핵심 항목>

   ## UI 리뷰 주요 발견 사항
   <review-ui.md 핵심 항목 또는 "UI 리뷰 skip (변경 없음)">

   ## Intent Fidelity 검증 결과
   - 모드: blocking(기본) | advisory
   - advisory 모드면 `(advisory — pass/fail 미반영)` 라벨 표기
   - ✅ Verified N개 / ⚠️ Partial N개 / ❌ Missing N개 / ℹ️ INTENT-GAP N개
   - SHOULD 경고 로그: `warnings.log` 기록 여부 + 누적 횟수
   - 상세: `review-intent-fidelity.md` 또는 skip 사유

   ## 영향 범위 분석 결과
   - 상세: `review-impact.md` 또는 skip 사유
   - 영향 없음 시: `영향 범위 분석 완료 — 해당 없음`
   - 비활성화 skip 시: `Impact 리뷰 skip (비활성화)`
   - 에이전트 실패 시: `에이전트 실패`

   ## Adversarial 리뷰 결과
   - `[ADVERSARIAL: SKIPPED — {사유}]` 또는 finding 요약
   - 상세: `review-adversarial.md` 또는 skip 사유
   ```

4. **adversarial finding 통합 (MANDATORY)**:
   - `review-adversarial.md`의 각 finding에서 `confidence` 값을 읽어 severity를 아래 기준으로 재매핑한다.
     - `confidence >= 0.8` → `CRITICAL`
     - `0.5 <= confidence <= 0.79` → `MAJOR`
     - `0.2 <= confidence <= 0.49` → `MINOR`
     - `confidence < 0.2` → `DROP` (report 본문/집계에서 제외)
   - adversarial finding은 `F-NN` 식별자를 부여해 report에 기록한다.

5. **교차 검증 승격 + sources 병기 (MANDATORY)**:
   - `review.cross_validation.enabled == true`이면, Pass B 리뷰어(code/arch/ui/impact/adversarial) 중 `max(2, review.cross_validation.min_reviewers)`명 이상이 동일 파일·라인 근접(`line_proximity`) 영역을 지적할 때 severity를 1단계 승격한다.
   - 승격 시 finding에 `sources: [역할1, 역할2, ...]`를 병기하고 `source: "cross_validation"` 메모를 남긴다.
   - 교차 확인 라벨 규칙:
     - `합의`: 동일 영역을 2개 이상 역할이 지적
     - `단독 발견`: 1개 역할만 지적
     - `상충`: 동일 영역에 상반된 verdict/주장이 공존

6. **교차 매트릭스 포맷 (MANDATORY)**:
   - 최종 finding(드롭 제외) 개수가 3개 이상이면 report 상단에 `파일 × attack_surface` 격자를 생성한다.
   - 행은 파일 경로, 열은 attack_surface(보안/데이터 무결성/동시성/롤백 안전/null·timeout/버전 스큐/관측성)로 구성한다.
   - 각 셀에는 `F-NN`과 교차 확인 라벨(`합의|단독 발견|상충`)을 표시한다.

7. **adversarial non-blocking 처리 (MANDATORY)**:
   - timeout, 에이전트 에러, 프롬프트 템플릿 누락/Read 실패 시 adversarial만 skip 처리하고 기존 6개 역할 기준으로 report 생성/분기 로직을 계속 수행한다.
   - 이 경우 report에 반드시 `[ADVERSARIAL: SKIPPED — {사유}]` 섹션을 남긴다.
   - adversarial skip 단독 사유만으로 `gap_found`를 트리거하지 않는다.

### Step 6: 갭 처리 분기

> 이 Step의 목적: AC 갭/코드리뷰 이슈 상태에 따라 후속 경로를 확정한다 / 핵심 출력물: `review.json.status` 및 재실행/수락 분기 결정

AC 미충족(갭) 여부와 코드리뷰 이슈 여부에 따라 5개 분기로 처리합니다.

Pass B에서 `review-impact.md`를 통해 `[impact-check]` AC verdict가 보고된 경우:
- `[MUST] [impact-check]` AC 중 `FAIL`이 1건이라도 있으면 `review.json.status = "gap_found"`로 처리하고 `(c)` 분기로 진입한다.

> **Step 5 완료 시 공통 절차**: 분기 처리가 완료되면 `request.json.review_iterations` 배열에서 현재 회차 항목의 `status`를 `"in_progress"` → `"completed"`로 갱신합니다.

#### PM 판정 기계화 Boolean Gate (Step 6 선행, MANDATORY)

`PM_PASS = MUST_AUTOMATABLE_PASS AND EVIDENCE_COMPLETE AND NO_BLOCKING_EXCEPTION`

1. `MUST_AUTOMATABLE_PASS` 계산 규칙:
   - 대상: MUST 등급이면서 `ac_type == automatable`인 Spec AC/PAC만 포함한다.
   - 제외: `manual`/`browser-test` MUST AC는 자동 통과 계산에서 제외하고 별도 플래그로만 관리한다.
   - 판정 정규화:
     - `PASS` → pass
     - `FAIL` → fail
     - `TIMEOUT`/`timeout` → fail (강제)
     - `N/A`/`na` → `na_reason`이 비어 있지 않을 때만 유효, 비어 있으면 fail (강제)
   - MUST 대상 중 1건이라도 fail이면 `MUST_AUTOMATABLE_PASS=false`.
   - 별도 플래그(리포트/메타 기록):
     - `manual_must_flag`: MUST + manual AC 존재 여부/개수
     - `browser_test_must_flag`: MUST + browser-test AC 존재 여부/개수
2. `EVIDENCE_COMPLETE` 계산 규칙:
   - 아래 필수 증적 4종이 모두 존재하고 비어있지 않아야 true:
     - `reviews/RV-NNN/review.json`
     - `reviews/RV-NNN/evidence-ledger.md`
     - `reviews/RV-NNN/coverage-matrix.json`
     - `reviews/RV-NNN/coverage-matrix.md`
3. `NO_BLOCKING_EXCEPTION` 계산 규칙:
   - 아래 blocking 조건이 모두 없어야 true:
     - `pass_a_result == fail`
     - `static_validation_gate_result in {fail, gap_found}`
     - `coverage_matrix_gate_result == gap_found`
     - `full_backend_test_gate_result in {fail, limit_reached}`
     - blocking 모드 intent_fidelity 실패
4. 적용 규칙:
   - 기존 Step 6 분기 판정 결과가 `(a)`(pass 후보)일 때만 최종 확정 직전에 Boolean Gate를 평가한다.
   - `PM_PASS=true`면 `(a)`를 유지한다.
   - `PM_PASS=false`면 `(a)`를 취소하고 `(c)`와 동일 경로로 강등한다 (`review.json.status="gap_found"`, `gap_source="ac_gap"`).
   - 기존 `(b)/(c)/(d)/(e)`로 이미 확정된 경우에는 Boolean Gate가 분기를 덮어쓰지 않는다(하위 호환).

#### 커스텀 Loop 종료 조건 게이트 (Step 6 선행)

> 이 게이트는 기존 분기 판정을 대체하지 않는다. 기존 판정이 `(a)`(pass)로 확정되기 직전에만 AND로 추가 평가한다.

1. Step 6 루프 시작 시 1회, `request.json.source_plan` 기준으로 대상 plan 경로를 결정한다.
   - 경로: `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`
2. plan.md의 `## Loop 종료 조건` 섹션을 Read하여 `custom_loop_conditions`를 로드한다.
   - `source_plan` 미존재, plan 파일 미존재, 섹션 미존재, 섹션 본문 비어있음 중 하나라도 해당하면 `custom_loop_conditions=[]`로 간주하고 커스텀 게이트를 skip한다 (기존 로직 그대로 진행, 하위 호환).
3. Intent Fidelity 규칙을 포함한 기존 Step 6 분기 판정을 먼저 수행한다.
4. 기존 판정이 `(a)`가 아니면 커스텀 게이트를 평가하지 않고 기존 분기 결과를 그대로 따른다.
5. 기존 판정이 `(a)`이면 `custom_loop_conditions`의 각 조건을 AND로 평가한다.
   - `연속 무변경 수렴`: 이번 iteration의 gap/diff 목록과 직전 iteration 비교 시 새로운 gap/diff가 없어야 통과.
   - `고정 N회 반복`: `request.json.review_iterations.length >= N`일 때만 통과. `length < N`이면 미충족.
   - 그 외 커스텀 자연어 조건: PM이 현재 iteration 상태(`ac-results.md`, `review-report.md`, `review.json`) 기반으로 충족 여부를 판정한다.
6. 커스텀 조건 중 하나라도 미충족이면 `(a)`를 취소하고 `(c)`와 동일 경로로 처리한다.
   - `review.json.status = "gap_found"`
   - `request.json.review_summary.status = "gap_fixing"`
   - approve로 갭 목록 + 재실행 대상 태스크를 반환한다.
7. 모든 커스텀 조건이 충족되면 기존 `(a)` pass 경로를 그대로 진행한다.

#### Intent Fidelity 결과 반영 규칙 (Step 6 공통)

1. `review-intent-fidelity.md`가 존재하면 `Verified/Partial/Missing/INTENT-GAP` 카운트를 파싱한다.
2. 파싱 결과를 `request.json`의 현재 태스크에 기록한다.
   - 경로: `tasks[현재 태스크].self_check.intent_fidelity_result`
   - 스키마: `{ "verified": N, "partial": N, "missing": N, "intent_gaps": N, "report_path": "reviews/RV-NNN/review-intent-fidelity.md" }`
3. `intent_fidelity.mode` 기본값은 `"blocking"`이며, 명시적으로 `"advisory"`일 때만 완화 동작을 적용한다.
4. `intent_fidelity.mode == "advisory"`이면 리포트만 출력하고 기존 review pass/fail 판정에는 영향을 주지 않는다.
5. `intent_fidelity.mode == "blocking"`이면 기존 review 판정과 AND 조건으로 결합한다.
   - MUST AC(또는 MUST PAC에 매핑된 AC)에서 `Partial`/`Missing`이 1건이라도 있으면 `review.json.status = "gap_found"`로 처리하고 `(c)` 경로를 따른다.
   - SHOULD AC의 `Partial`/`Missing`은 warning으로만 처리하고 blocking 사유로는 사용하지 않는다.
6. SHOULD warning 로깅 (`intent_fidelity.should_warning_log == true`):
   - 경로: `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/warnings.log`
   - 포맷(한 줄 JSONL 권장): `timestamp`, `req_id`, `rv_id`, `ac_id`, `module`, `result(Partial|Missing)`, `reason`
   - `module`은 구현 증거 경로의 상위 모듈(예: `src/auth`, `skills/request`)로 추출하고, 추출 불가 시 `"unknown"` 사용
7. SHOULD 누적 관리 (`intent_fidelity.should_escalation_threshold`, 기본 3):
   - 동일 `module`에서 SHOULD warning 누적 횟수가 임계치 이상이면 `"MUST escalation review required"` 플래그를 review-report에 추가한다.
   - 이 플래그는 즉시 blocking하지 않으며, 다음 회차/후속 작업에서 MUST 격상 검토 대상으로 취급한다.

#### (a) 갭 없음 + 코드리뷰 이슈 없음 (+ blocking 모드면 intent_fidelity 통과)

- `review.json.status = "passed"`
- `request.json.review_summary = { "iteration": N, "status": "passed" }` 업데이트
- Phase 3 PASS 반환. approve가 Phase 5(mst:accept)를 호출 — review는 mst:accept를 직접 호출하지 않는다.

#### (b) 갭 없음 + 코드리뷰 이슈만 있음 (AC는 통과, 설계/품질 이슈)

코드리뷰 이슈를 등급별로 분류한 뒤 자동 처리 분기를 수행합니다.

##### (b) enabled 가드

`config.review.severity_auto_fix.enabled` 확인:
- `false`: 기존 (b) 동작으로 fallback
  - **`--auto` 모드**: 이슈를 report에만 기록하고 Phase 5 자동 진행. `review.json.status = "passed"`.
  - **일반 모드**: `AskUserQuestion` → 선택지:
    - `[이슈 무시하고 수락]`: Phase 5 진행. `review.json.status = "passed"`.
    - `[이슈를 태스크로 추가]`: **(c)와 동일 경로** (갭별 새 태스크 spec.md 자동 작성 + 재외주).
- `true`: 아래 등급별 분기 진행 (사전 처리 → b-1/b-2/b-3).

##### (b) 사전 처리: 이슈 파싱 및 등급 분류

1. **리뷰어 태깅 파싱**: `review-report.md`의 코드/아키텍처/UI/영향/adversarial 리뷰 발견 사항에서 `[CRITICAL]`, `[MAJOR]`, `[MINOR]` 접두사를 파싱하여 등급별 배열로 분리합니다.
   - 태깅 형식 예시: `[CRITICAL] SQL injection 취약점 발견`, `[MAJOR] 에러 핸들링 누락`, `[MINOR] 변수명 컨벤션 불일치`
   - **태깅 없는 이슈**: 리뷰어가 등급 접두사를 붙이지 않은 이슈는 **MAJOR로 기본 분류**합니다.
   - adversarial finding은 Step 5에서 confidence 매핑이 끝난 항목만 포함한다(`DROP` 제외).

2. **PM 재조정 (보안 오버라이드)**: `config.review.severity_auto_fix.security_override_keywords` 배열의 키워드와 각 이슈 내용을 매칭합니다.
   - 키워드가 이슈 텍스트에 포함되면 해당 이슈의 등급을 **무조건 CRITICAL로 승격**합니다 (원래 MAJOR/MINOR였더라도).
   - 키워드 매칭은 대소문자 무시(case-insensitive).
   - 예시 키워드: `인증`, `인가`, `인젝션`, `XSS`, `CSRF`, `SQL injection`, `권한 우회`, `authentication`, `authorization`, `injection`, `secret`, `token`

3. **Severity 역행 감지 (iteration 2+ MANDATORY)**:
   - 현재 회차가 iteration 2 이상이면 직전 회차 `reviews/RV-(N-1)/review.json`을 Read하여 `previous_severity_counts`를 현재 회차 `review.json`에 기록한다.
   - **동일 이슈 판정 기준(관찰 가능 기준)**:
     - 동일 파일 경로 + 라인 번호 차이 `<= 10` + 정규화된 설명 문자열이 동일하면 동일 이슈로 간주한다.
     - 정규화 예: 대소문자 무시, 연속 공백 제거, 공통 접두사(`[CRITICAL]` 등) 제거.
   - 동일 이슈가 직전 회차에도 보고되면 현재 회차의 해당 이슈 severity를 **자동 CRITICAL 승격**한다.
   - 승격 내역은 `review-report.md` 또는 `review_issues_summary` 부가 메모에 `source: "severity_regression_guard"`로 기록한다.

4. **Pass B 교차 검증 승격 (`review.cross_validation.enabled == true`)**:
   - 적용 조건: Pass B 리뷰어(code/arch/ui/impact/adversarial) 중 `max(2, review.cross_validation.min_reviewers)`명 이상이 같은 영역을 지적한 경우.
   - 같은 영역 판정(관찰 가능 기준): 동일 파일 경로 + 라인 번호 차이 `<= review.cross_validation.line_proximity` (기본 `10`줄).
   - 조건 충족 시 해당 영역 이슈 severity를 **+1 단계 승격**한다.
     - `MINOR -> MAJOR`
     - `MAJOR -> CRITICAL`
     - `CRITICAL -> CRITICAL` (상한 고정)
   - 승격 내역은 `review-report.md` 또는 `review_issues_summary` 부가 메모에 `source: "cross_validation"`로 기록하고 `sources: [역할1, 역할2, ...]`를 병기한다.

5. **등급별 카운트 산출**: 재조정 완료 후 `critical_count`, `major_count`, `minor_count`를 산출합니다.

6. **`review_issues_summary` 기록**: `review.json`과 `request.json`의 해당 review iteration에 등급별 카운트 및 자동 처리 내역을 기록합니다 (스키마는 하단 "review_issues_summary 스키마" 섹션 참조).

##### (b-1) CRITICAL 또는 MAJOR가 1건 이상 존재

- `critical_count + major_count > 0` 인 경우.
- **`--auto` 모드**:
  - CRITICAL/MAJOR 이슈에 대해 **(c)와 동일 경로** (갭별 새 태스크 spec.md 자동 작성 + 재외주). `gap_source: "code_review_issues"` 메타 기록.
  - MINOR 이슈는 `review_issues_summary.skipped` 배열에 기록하고 **무조건 스킵** (threshold 무시). `review-report.md`에만 기록.
- **일반 모드**: `AskUserQuestion` → 선택지:
  - `[CRITICAL/MAJOR N건 태스크로 추가]`: **(c)와 동일 경로** (갭별 새 태스크 spec.md 자동 작성 + 재외주). MINOR는 `config.review.severity_auto_fix.minor_skip_threshold` 검사 적용 (b-2/b-3 규칙 동일). `review.json.status = "gap_found"`. `gap_source: "code_review_issues"` 메타 기록.
  - `[전체 이슈 무시하고 수락]`: Phase 5 진행. `review.json.status = "passed"`.

##### (b-2) MINOR만 존재 + 개수 <= threshold (스킵+리포트)

- **MINOR-only high-pass 보호 가드 (MANDATORY)**:
  - 운영 단일 기준 위치: `workflow.auto_accept_guard` (기본값 정의: `templates/defaults/config.json`).
  - 단순 count 임계값만으로 `passed` 처리하지 않는다.
  - `review_issues_summary.auto_accept_guard` 메타를 항상 기록:
    - `skipped_minor_count`: 현재/누적 스킵된 MINOR 개수
    - `protection_flags_count`: 보호 규칙 플래그 개수
    - `blocked`: auto accept 차단 여부
    - `blocked_reasons`: 차단 사유 배열
  - 아래 조건 중 하나라도 참이면 `blocked=true`로 판단하고 **(c) 경로**로 전환한다:
    - `review_issues_summary.auto_accept_guard.skipped_minor_count > 0`
    - `review_issues_summary.auto_accept_guard.protection_flags_count > 0`
- `critical_count == 0 AND major_count == 0 AND minor_count > 0 AND minor_count <= config.review.severity_auto_fix.minor_skip_threshold AND review_issues_summary.auto_accept_guard.blocked == false` 인 경우에만 `passed`.
- MINOR 이슈를 `review-report.md`에 기록하고 `review_issues_summary.skipped` 배열에 기록.
- `review.json.status = "passed"`.
- `request.json.review_summary = { "iteration": N, "status": "passed" }` 업데이트.

##### (b-3) MINOR만 존재 + 개수 > threshold (자동 태스크 생성)

- `critical_count == 0 AND major_count == 0 AND minor_count > 0 AND minor_count > config.review.severity_auto_fix.minor_skip_threshold` 인 경우.
- **(c)와 동일 경로** (갭별 새 태스크 spec.md 자동 작성 + 재외주). `gap_source: "code_review_issues"` 메타 기록.
- `review.json.status = "gap_found"`.
- **참고**: `minor_skip_threshold`가 `0`이면 모든 MINOR도 자동 처리 대상.

##### (b) `--auto` 모드 동작 요약

`--auto` 플래그 실행 시 코드리뷰 이슈 등급별 동작:

| 등급 | 동작 |
|------|------|
| CRITICAL | 자동 태스크 생성 + 재외주 (c 경로) |
| MAJOR | 자동 태스크 생성 + 재외주 (c 경로) |
| MINOR | MINOR-only인 경우에도 `minor_skip_threshold` + `review_issues_summary.auto_accept_guard`를 함께 검사한다. 가드 차단 시 (c) 경로로 전환한다. |

- CRITICAL/MAJOR 없이 MINOR만 있는 경우: `minor_count <= config.review.severity_auto_fix.minor_skip_threshold` 이고 `auto_accept_guard.blocked == false`일 때만 `review.json.status = "passed"`.
- CRITICAL/MAJOR와 MINOR 혼재: CRITICAL/MAJOR만 태스크 생성, MINOR 스킵. `review.json.status = "gap_found"`.

#### (c) 갭 있음 + iteration ≤ max_iterations

1. 갭별 새 태스크 spec.md 자동 작성:
   - 경로: `tasks/NN+1/spec.md` (기존 최대 태스크 번호 +1)
   - `request.json.tasks` 항목 필드: `{ "id": "NN", "title": "<갭 설명>", "status": "pending", "agent": null, "spec": "tasks/NN/spec.md", "generated_by": "review" }`
   - impact_reviewer 이슈로 생성되는 태스크라면 description 본문에 `review-impact.md`의 `함께 수정 필요 파일` 목록과 수정 방향을 포함한다.
2. `request.json.tasks` 배열 업데이트 (신규 태스크 추가).
3. `request.json.review_summary = { "iteration": N, "status": "gap_fixing" }` 업데이트.
4. `review.json` 업데이트: `{ "status": "gap_found", "gaps_found": M, "tasks_created": ["NN", "NN+1", ...], "gap_source": "ac_gap | code_review_issues | intent_fidelity" }`.
5. approve 스킬에 갭 목록 + 새 태스크 ID 반환 → approve가 Phase 2 재실행 제어. — 텍스트만 출력하고 멈추지 않는다

#### (d) 갭 있음 + iteration > max_iterations

- **`--auto` 모드**: `review.json.status = "limit_reached"`, `review_summary.status = "limit_reached"` 기록 후 종료.
- **일반 모드**: `AskUserQuestion` → 선택지:
  - `[추가 반복 허용 (+1회)]`: `max_iterations` 임시 +1 후 (c) 경로 실행.
  - `[현재 상태로 수락]`: Phase 5 진행. `review.json.status = "passed"` (강제 수락).
  - `[중단]`: 워크플로우 중단.

#### (e) Pass A 실패 (MUST AC 실패 감지)

Step 3 AC 검증에서 MUST 등급 AC가 1개 이상 FAIL 판정된 경우 진입합니다.

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
  - AC-YY
failure_class: ac_unclear | interpretation | implementation
evidence:
  - ac_id: AC-XX
    type: log | screenshot | metric | manual
    ref: "실패 증거 경로 또는 설명"
    summary: "실패 내용 요약"
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `pass_a_result` | string | 항상 `"fail"` (Pass A 실패를 나타냄). |
| `failed_ac_ids` | string[] | FAIL 판정된 MUST 등급 AC ID 목록. |
| `failure_class` | string | 실패 원인 분류: `ac_unclear`(AC 기준 불명확) \| `interpretation`(해석 차이) \| `implementation`(구현 누락/오류). |
| `evidence` | array | 각 실패 AC의 증거 목록. 각 항목: `{ ac_id, type, ref, summary }`. |

approve는 이 파일에서 `failed_ac_ids`와 `failure_class`를 파싱하여 재외주 대상 태스크를 선별한다.


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
  "review_summary": {
    "iteration": 1,
    "status": "gap_fixing"
  },
  "plan_iterations": [
    {
      "iteration_no": 1,
      "trigger": "post_review",
      "started_at": "2026-03-01T00:10:00Z",
      "ended_at": "2026-03-01T00:12:00Z",
      "result": "passed"
    }
  ],
  "tasks": [
    {
      "id": "02",
      "self_check": {
        "intent_fidelity_result": {
          "verified": 3,
          "partial": 1,
          "missing": 0,
          "intent_gaps": 1,
          "report_path": "reviews/RV-001/review-intent-fidelity.md"
        }
      }
    }
  ]
}
```

### review_iterations 배열

각 회차 실행 결과를 순서대로 기록합니다.

| 필드 | 설명 |
|------|------|
| `rv_id` | RV 채번 (`RV-NNN`). `review_iterations.length + 1` 기반. |
| `created_at` | 회차 시작 시각 (ISO8601). |
| `gaps_found` | 발견된 갭 수. 0이면 갭 없음. |
| `tasks_created` | 갭으로 생성된 태스크 ID 배열. 갭 없으면 `[]`. |
| `status` | Step 1에서 `"in_progress"`로 초기화, Step 5 완료 후 `"completed"`로 갱신. 갭 여부는 `gaps_found > 0`으로 구분. |
| `previous_severity_counts` | (선택) 직전 iteration의 severity 카운트 스냅샷. 구조: `{ "critical": number, "major": number, "minor": number }` |
| `review_issues_summary` | (선택) 등급별 코드리뷰 이슈 요약. 이슈가 존재하면 `review.json.review_issues_summary`와 동일 구조로 기록. |

### plan_iterations 배열 (정의 전용)

`request.json.plan_iterations`는 `plan -a` 실행 시 사후 점검 반복 메트릭을 기록하는 필드다.  
`mst:review`는 이 필드를 **정의만 참조**하며 생성/갱신 로직을 수행하지 않는다(기록 책임은 `plan -a`).

| 필드 | 타입 | 설명 |
|------|------|------|
| `iteration_no` | number | plan 사후 점검 반복 번호(1부터 시작). |
| `trigger` | string | 반복 실행 트리거 (`post_review`, `manual_retry`, `auto_retry` 등). |
| `started_at` | string | 반복 시작 시각 (ISO8601). |
| `ended_at` | string | 반복 종료 시각 (ISO8601). |
| `result` | string | 반복 결과 (`passed`, `failed`, `needs_followup` 등). |

### tasks[].self_check.intent_fidelity_result

intent_fidelity 리뷰 결과를 현재 태스크 단위로 기록한다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `verified` | number | Intent Trace 대비 구현 증거가 충분한 항목 수 |
| `partial` | number | 의도 근거 대비 구현 증거가 불충분한 항목 수 |
| `missing` | number | 의도 근거 대비 구현 누락 항목 수 |
| `intent_gaps` | number | 의도 근거가 없는 AC(`[INTENT-GAP]`) 수 |
| `report_path` | string | intent-fidelity 리포트 경로 (`reviews/RV-NNN/review-intent-fidelity.md`) |

### review_summary 객체

현재 진행 중인 review 상태를 담습니다.

| 필드 | 설명 |
|------|------|
| `iteration` | 현재(마지막) 회차 번호. |
| `status` | 현재 상태: `reviewing` \| `gap_fixing` \| `passed` \| `limit_reached` \| `pass_a_failed` |

**status 규칙**:
- `reviewing`: Step 1~4 진행 중.
- `gap_fixing`: 갭 발견, 태스크 추가됨 (Phase 2 재실행 대기).
- `passed`: 갭 없음, 리뷰 통과.
- `limit_reached`: `--auto` 모드에서 `max_iterations` 초과 + 갭 있음.
- `pass_a_failed`: Pass A MUST AC 실패로 인해 재작업이 필요한 상태. approve가 이 상태를 수신하면 해당 태스크를 re-outsource 트리거.

### review.json

`reviews/RV-NNN/review.json` 구조:

```json
{
  "id": "RV-NNN",
  "req_id": "REQ-NNN",
  "iteration": N,
  "status": "passed | gap_found | reviewing | pass_a_failed",
  "created_at": "<ISO8601>",
  "previous_severity_counts": {
    "critical": 0,
    "major": 0,
    "minor": 0
  },
  "gaps_found": 0,
  "tasks_created": [],
  "gap_source": "ac_gap | code_review_issues | intent_fidelity | null",
  "review_issues_summary": {
    "critical": 0,
    "major": 0,
    "minor": 0,
    "auto_fixed": [],
    "skipped": []
  },
  "pm_gate": {
    "pm_pass": true,
    "must_automatable_pass": true,
    "evidence_complete": true,
    "no_blocking_exception": true,
    "manual_must_flag": {
      "count": 0
    },
    "browser_test_must_flag": {
      "count": 0
    }
  }
}
```

`pm_gate`는 Step 6 Boolean Gate 계산 결과를 저장하는 선택 필드다(하위 호환). 필드가 없으면 기존 리포트 파싱만으로도 동작해야 한다.

### previous_severity_counts 스키마

이전 iteration(`RV-(N-1)`)의 severity 카운트를 현재 회차 메타데이터로 보존합니다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `critical` | number | 직전 iteration의 CRITICAL 카운트. |
| `major` | number | 직전 iteration의 MAJOR 카운트. |
| `minor` | number | 직전 iteration의 MINOR 카운트. |

### review_issues_summary 스키마

Step 5(b) 등급별 분류 결과를 기록합니다. `review.json`과 `request.json`의 해당 `review_iterations` 항목 양쪽에 동일 구조로 기록됩니다.

```json
{
  "review_issues_summary": {
    "critical": 2,
    "major": 1,
    "minor": 3,
    "auto_fixed": [
      { "severity": "CRITICAL", "description": "SQL injection 취약점", "task_id": "05" },
      { "severity": "MAJOR", "description": "에러 핸들링 누락", "task_id": "06" }
    ],
    "skipped": [
      { "severity": "MINOR", "description": "변수명 컨벤션 불일치" },
      { "severity": "MINOR", "description": "주석 누락" }
    ],
    "auto_accept_guard": {
      "skipped_minor_count": 2,
      "protection_flags_count": 0,
      "blocked": true,
      "blocked_reasons": [
        "review_issues_summary.auto_accept_guard.skipped_minor_count > 0"
      ]
    }
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `critical` | number | CRITICAL 등급 이슈 수 (보안 오버라이드 승격 반영 후). |
| `major` | number | MAJOR 등급 이슈 수. |
| `minor` | number | MINOR 등급 이슈 수. |
| `auto_fixed` | array | 자동 태스크 생성되어 재외주된 이슈 목록. 각 항목: `{ "severity": string, "description": string, "task_id": string }`. |
| `skipped` | array | 스킵 처리된 이슈 목록 (threshold 이하 MINOR 또는 `--auto` 모드 MINOR). 각 항목: `{ "severity": string, "description": string }`. |
| `auto_accept_guard` | object | auto accept 허용/차단 메타. `{ "skipped_minor_count": number, "protection_flags_count": number, "blocked": boolean, "blocked_reasons": string[] }`. |

### gap_source 필드

`review.json`의 `gap_source`는 갭 발생 원인을 구분합니다.

| 값 | 의미 |
|------|------|
| `"ac_gap"` | AC 미충족으로 인한 갭 (Step 5 (c)/(d) 분기). |
| `"code_review_issues"` | 코드리뷰 이슈로 인한 갭 (Step 5 (b) 분기). |
| `"intent_fidelity"` | blocking 모드 intent-fidelity 실패로 인한 갭 (Step 6 공통 규칙). |
| `null` | 갭 없음 (`status: "passed"`일 때). |

### approve → review_issues_summary 데이터 전달 경로

approve SKILL.md Phase 3 결과 처리 시 최신 `reviews/RV-NNN/review.json`을 Read하여 `review_issues_summary`를 참조합니다. approve는 이 데이터를 통해 CRITICAL/MAJOR/MINOR 카운트 및 auto_fixed/skipped 내역을 확인하고, 등급별 후속 분기(재외주/PM 직접 수정/스킵)를 결정합니다.
