---
name: agile-plan
description: "프로젝트 목표 + 설계 문서(objective.md)를 JTBD 기반 Q&A로 생성하고, 실행 전 검토 가능한 플래닝 세션을 초기화합니다."
user-invocable: true
argument-hint: "{프로젝트 목표 | --doc 파일경로} [--steering-every N] [--return-to parent/step]"
---

# maestro:agile-plan

**목적**: `/mst:agile-plan`으로 JTBD + 프로젝트 DoD 중심의 objective.md를 생성한다. 이 스킬은 플래닝 전용이며 Story 생성/실행은 담당하지 않는다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/objective.md` (신규 생성)
- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/details/*.md` (신규 생성)
- `{PROJECT_ROOT}/.gran-maestro/state/default/snapshot.json` (`mst.py state set`으로 기록되는 상태 파일)

그 외 모든 경로에 대한 Write/Edit 사용은 금지합니다.

- objective 상태 변경은 직접 편집이 아니라 `mst.py` 명령을 통해 수행한다.
- 프로젝트 DoD 체크리스트는 완료 판정의 유일한 게이트로 다룬다(DSC-047).

## 스킬 실행 마커 (MANDATORY)

- 모든 응답의 첫 줄 또는 각 Step 시작 줄에 아래 마커를 출력한다.
- 기본 마커 포맷: `[MST skill={name} step={N}/{M} return_to={parent_skill/step | null}]`
- 필드 규칙:
  - `skill`: 현재 실행 중인 스킬 이름
  - `step`: 현재 단계(`N/M`) 또는 서브스킬 종료 시 `returned`
  - `return_to`: 최상위 스킬이면 `null`, 서브스킬이면 `{parent_skill}/{step_number}`
- 서브스킬 종료 마커: `[MST skill={subskill} step=returned return_to={parent/step}]`

## Gate

### Entry

- Step 0에서 반드시 `mst.py agile init`으로 AGI 세션을 먼저 생성한다.
- `--doc` 미지정 시 1A(Q&A 생성 모드), 지정 시 1B(문서 파싱 모드)로 분기한다.
- Story/작업 실행 루프로 진입하지 않는다. 이 스킬은 objective 생성까지만 수행한다.

### Exit

- `templates/objective.md` 포맷으로 objective.md 저장 완료
- `mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 완료
- `mst.py state set --skill agile-plan --step 3 --total 3 [--return-to ...]` 기록 완료
- `--return-to`가 있으면 stop-hook continuation guard로 상위 스킬 복귀(re-feed), 없으면 독립 실행을 종료하고 `--resume` 안내

### 금지 패턴

- Story 레이어/Checklist 별도 실행 레이어를 objective에 생성하는 행위
- DoD 항목에 구현 방법(API 엔드포인트, 함수명, 파일명, 기술 스택)을 강제하는 행위
- Step 0 없이 objective 생성을 시작하는 행위
- 스프린트 횟수/완료 시점을 예측·확정·암시하는 표현을 objective/질문/보고에 기재하는 행위
- objective.md에 "예상 스프린트", "N회 스프린트", "X주 내 완료" 등 필드/문장을 추가하는 행위
- 캘린더 단위로 변환한 기간 추정(예: "4~8주 소요")을 기재하는 행위
- 과거 실적을 현재 프로젝트의 완료 시점/스프린트 횟수 예측 근거로 인용하는 행위

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: `.gran-maestro/` 경로는 절대경로로 사용한다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
> `{PLUGIN_ROOT}`는 이 스킬의 Base directory에서 `skills/agile-plan/`을 제거한 절대경로다.

---

### Step 0: 세션 초기화

`[MST skill=agile-plan step=0/3 return_to={RETURN_TO_OR_NULL}]`

#### 0.1 인자 파싱

| 플래그 | 설명 | 예시 |
|--------|------|------|
| `--doc 파일경로` | 기존 문서 파싱 모드 | `--doc docs/spec.md` |
| `--steering-every N` | 스티어링 간격(기본값 3) | `--steering-every 5` |
| `--return-to parent/step` | 서브스킬 복귀 지점 | `--return-to agile/1` |

- `--steering-every` 미지정 시 `STEERING_EVERY=3`
- `--return-to` 미지정 시 독립 실행으로 간주 (`return_to=null`)
- `EMERGENCY_STEERING_ENABLED` 기본값은 `true`로 둔다.
- `STEERING_DISABLED` 기본값은 `false`로 둔다.

#### 0.15 스티어링 설정 Q&A (MANDATORY)

1. 아래 형태로 **AskUserQuestion 1회 호출**에서 `questions` 배열 2개 탭을 동시에 제시한다.
   - 탭 1: 정기 스티어링 간격/비활성화
   - 탭 2: 비상 스티어링 활성화/비활성화
2. 질문 정의(예시 포맷):
   - `questions`:
     - `id`: `regular_steering`
       - `header`: `정기 스티어링`
       - `question`: `정기 스티어링 체크포인트를 어떤 주기로 운영할까요?`
       - `options`:
         - `label`: `3 스프린트마다 (기본값)`
           - `description`: |
               - 기본 추천 주기입니다.
               - Sprint 3/6/9 완료 직후 Step 3 체크포인트가 자동 실행됩니다.
               - 탐색/구현 사이 균형을 유지하면서 drift 누적 전에 방향을 교정할 수 있습니다.
         - `label`: `5 스프린트마다`
           - `description`: |
               - 보고 빈도를 낮추고 긴 실행 구간을 확보합니다.
               - Sprint 5/10/15 완료 직후 Step 3 체크포인트가 실행됩니다.
               - 대규모 구현 구간에서 컨텍스트 전환 비용을 줄이고 싶을 때 적합합니다.
         - `label`: `비활성화 (정기 스티어링 없이 진행)`
           - `description`: |
               - 정기 체크포인트를 완전히 끄고 스프린트 루프를 연속 실행합니다.
               - Step 3 정기 진입 조건은 skip되며, 필요한 경우 비상 스티어링만 사용합니다.
               - 이 선택은 프롬프트 레벨에서 `STEERING_EVERY=0`으로 해석됩니다.
     - `id`: `emergency_steering`
       - `header`: `비상 스티어링`
       - `question`: `이상 징후 발생 시 비상 스티어링 자동 개입을 사용할까요?`
       - `options`:
         - `label`: `활성화 (연속실패/drift/blocked 등 이상 시 자동 개입)`
           - `description`: |
               - 연속 실패, drift 누적, blocked 비율 급증 같은 위험 신호를 감지합니다.
               - 위험 신호 발생 시 Step 3 비상 스티어링을 즉시 강제 실행합니다.
               - 장기 루프 정체를 줄이고, 조기 개입으로 손실을 제한하는 기본 권장 설정입니다.
         - `label`: `비활성화 (모든 스티어링 비활성화)`
           - `description`: |
               - 비상 트리거 기반 Step 3 강제 진입을 사용하지 않습니다.
               - 정기 스티어링도 비활성화했다면 스티어링 자체가 완전히 꺼진 상태로 동작합니다.
               - 사용자는 자동 개입 없이 연속 스프린트 실행만 원할 때 선택합니다.
3. 응답 매핑 규칙:
   - 정기 스티어링 응답이 `3 스프린트마다 (기본값)`이면 `STEERING_EVERY=3`, `STEERING_DISABLED=false`
   - 정기 스티어링 응답이 `5 스프린트마다`이면 `STEERING_EVERY=5`, `STEERING_DISABLED=false`
   - 정기 스티어링 응답이 `비활성화 (정기 스티어링 없이 진행)`이면 `STEERING_EVERY=0`, `STEERING_DISABLED=true`
   - 비상 스티어링 응답이 `활성화 ...`이면 `EMERGENCY_STEERING_ENABLED=true`
   - 비상 스티어링 응답이 `비활성화 ...`이면 `EMERGENCY_STEERING_ENABLED=false`
4. 기본값 연계 규칙(하위 호환):
   - `--steering-every N`이 지정되면 정기 스티어링 탭 기본 선택값을 `N`에 맞춰 preselect 한다.
   - CLI 미지정 시 기본 선택은 `3 스프린트마다 (기본값)`으로 둔다.

#### 0.2 agile init 호출

1. `STEERING_EVERY == 0`이면 `INIT_STEERING_EVERY=3`으로 둔다. (`mst.py` 호출값은 유효 범위를 유지하고, 정기 비활성화는 프롬프트 레벨 변수 `STEERING_DISABLED=true`로 해석)
2. `STEERING_EVERY > 0`이면 `INIT_STEERING_EVERY={STEERING_EVERY}`로 둔다.
3. `python3 {PLUGIN_ROOT}/scripts/mst.py agile init --steering-every {INIT_STEERING_EVERY} --json` 실행
4. 출력에서 `agi_id`를 파싱해 `AGI_ID`에 저장
5. `[신규 세션] AGI-{NNN} 생성됨 (steering-every: {STEERING_EVERY}, emergency-steering: {EMERGENCY_STEERING_ENABLED})` 출력
6. Step 1로 진행

### Step 0.5: 의도 분류 게이트

- PM은 요청 텍스트를 읽고 아래 질문을 내부 판단한다.
  - "이 요청이 새 프로젝트 objective를 정의하려는 의도인가?"
- confidence(0.0~1.0)를 산정한다.
- 기본 경로는 objective 생성이다. confidence가 낮을 때만 확인 질문을 수행한다.

#### 0.5.1 confidence >= 0.8 (직행)

1. `[의도 확인: objective 생성으로 진행]` 한 줄 통지를 출력한다.
2. Step 1A로 직행한다.
3. 요청 원문을 Step 1A JTBD Q&A의 초기 컨텍스트로 전달한다.

#### 0.5.2 confidence < 0.8 (1회 확인 질문)

1. AskUserQuestion으로 아래 확인 질문을 **1회만** 제시한다.
   - question: `이 요청을 objective 생성으로 진행할까요?`
   - options:
     - `objective 생성으로 진행`
     - `다른 의도 설명`
2. 사용자 응답이 `objective 생성으로 진행`이면 Step 1A로 진행한다.
3. Step 1A 진행 시 요청 원문 + Step 0.5 확인 대화 내용을 JTBD Q&A 초기 컨텍스트로 함께 전달한다.
4. 사용자 응답이 `다른 의도 설명`이면 적합한 스킬을 안내하고 종료한다.

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
   - `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`에서 `reference.auto_search` 확인
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
   - 표/텍스트 요약만으로는 저장이 완료되지 않는다 — `Bash` 도구 호출이 확인 증거다.
   - WebSearch N건 실행 → `mst.py reference add` 최소 N회 호출 (1:1 대응 원칙).
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{핵심 요약}"`

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
   - `CRITICAL` 또는 `MAJOR` 존재 시, 저장 전에 보완 질의 후 재검토
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

##### 1A.10 objective.md + details/*.md 저장

###### evidence 필드별 강제 시점 표

| 필드 | plan-time | sprint-runtime | sprint-end |
|------|-----------|----------------|------------|
| `artifact_paths` | 필수 (자동 채움) | - | 파일 실존 검증 |
| `entrypoint_path` | 필수 (`entrypoint: none` + `reason` 예외 허용) | - | grep 실매칭 검증 |
| `integration_smoke_id` | 예약 필수 (ID + user flow + 성공의도) | 선택 보강 | tests/ 실존 경로 강제 |
| `verify_cmd` | 골격 필수 (비대화식 실행 정의) | 실제 명령 확정 | 실행 + 신호 매칭, `true`/`exit 0`/`echo` 단독 거부 |
| `expected_signal` | TBD 허용 | TBD 해소 | 정규식/문자열 매칭 |

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
  - 각 `details/{domain}.md` 파일의 **첫 줄**에는 반드시 `<!-- source-mapping: original=<원본경로> sections=[<H1/H2 헤더 목록>] -->` 메타데이터를 작성한다.
  - detail 파일 저장 직후 `python3 {PLUGIN_ROOT}/scripts/mst.py agile detail validate-mapping {details_file_path}` 명령으로 source-mapping 메타데이터를 검증한다.
  - 모든 details 파일 저장 직후, `python3 {PLUGIN_ROOT}/scripts/mst.py agile coverage-check {원본문서경로} --details-dir {details_dir}` 명령으로 원본 ↔ details 집합 매칭률을 검증한다. 매칭률이 임계 미만이면 저장을 **실패**로 처리하고, 누락된 원본 슬러그 목록을 사용자에게 보고한 뒤 details 보강 후 재실행한다.
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
  - `<!-- dod:DOD-NNN status:todo priority:must -->`
- `priority` 값은 MoSCoW 결과를 반영해 `must|should|could|wont` 중 하나를 사용한다.
- 전략 검토/Confidence Matrix 결과를 objective.md 섹션으로 남기지 않는다.

##### 1A.10.5 details D3 역방향 시뮬레이션 (MANDATORY)

Step 1A.10 저장 직후, 각 detail 파일에 대해 독립적으로 D3 검증을 수행한다.

1. `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`에서 `d3.objective_detail_threshold`를 조회한다.
2. 값이 없으면 기본값 `0.1`을 사용한다.
3. `objective/details/*.md` 각 파일마다 독립 에이전트로 D3 역방향 시뮬레이션을 실행한다.
4. 판정은 기존 plan D3 Gate(`mst:plan` Step 3.9) 패턴을 따르되, 임계치는 `objective_detail_threshold`를 사용한다.
5. 모호도 점수가 임계치를 초과하면(명료도 90% 미만) 보완 요구를 생성하고 수정 후 재검증한다.

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

objective 저장 후 반드시 상태 스냅샷을 기록한다:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py state set \
  --skill agile-plan \
  --step 3 \
  --total 3 \
  [--return-to {RETURN_TO}]
```

#### 2.2 서브스킬 호출(return_to 존재) 처리

- `--return-to`가 있으면 아래 종료 마커 출력 후 즉시 종료:
  - `[MST skill=agile-plan step=returned return_to={RETURN_TO}]`
- stop-hook continuation guard가 `return_to`를 감지하여 상위 스킬 re-feed를 강제한다.

#### 2.3 독립 실행(return_to 없음) 처리

- objective 생성 결과를 안내하고 종료한다.
- 사용자가 objective를 수동 검토/수정한 뒤 아래로 실행을 연결하도록 안내한다:
  - `/mst:agile --resume {AGI_ID}`

---

## Anti-Rationalization Checklist

- 합리화 패턴: "대략 N 스프린트면 되니 계획/보고에 넣어도 된다." | 확인 증거: objective.md, plan 입력, 중간/스티어링 보고 산출물 전체에서 스프린트 횟수 예측 문구 0건.
- 합리화 패턴: "횟수가 아니라 규모/기간 추정이므로 허용된다." | 확인 증거: 캘린더 변환/반복 횟수 암시 표현이 산출물 전체에서 0건.

---

## DSC-047 운영 합의 반영 (MANDATORY)

1. 프로젝트 DoD 체크리스트가 완료 판정의 유일한 게이트다(LLM override 금지).
2. Sprint 완료 시 체크 갱신은 "제안"만 가능하며 `evidence_ref`를 반드시 포함한다.
3. 최종 approve/reject는 스티어링 체크포인트에서 사용자가 수행한다.
