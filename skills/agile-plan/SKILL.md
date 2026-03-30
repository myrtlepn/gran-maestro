---
name: agile-plan
description: "프로젝트 목표 또는 기존 문서를 기반으로 JTBD + Epic DoD 체크리스트 objective.md를 생성하고, 실행 전 검토 가능한 플래닝 세션을 초기화합니다."
user-invocable: true
argument-hint: "{프로젝트 목표 | --doc 파일경로} [--steering-every N] [--return-to parent/step]"
---

# maestro:agile-plan

**목적**: `/mst:agile-plan`으로 JTBD + Epic(목표/DoD 체크리스트) 수준의 objective.md를 생성한다. 이 스킬은 플래닝 전용이며 Story 생성/실행은 담당하지 않는다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/objective.md` (신규 생성)
- `{PROJECT_ROOT}/.gran-maestro/state/default/snapshot.json` (`mst.py state set`으로 기록되는 상태 파일)

그 외 모든 경로에 대한 Write/Edit 사용은 금지합니다.

- objective 상태 변경은 직접 편집이 아니라 `mst.py` 명령을 통해 수행한다.
- DoD 체크리스트는 Epic 완료 판정의 유일한 게이트로 다룬다(DSC-047).

## 스킬 실행 마커 (MANDATORY)

- 모든 응답의 첫 줄 또는 각 Step 시작 줄에 아래 마커를 출력한다.
- 기본 마커 포맷: `[MST skill={name} step={N}/{M} return_to={parent_skill/step | null}]`
- 필드 규칙:
  - `skill`: 현재 실행 중인 스킬 이름
  - `step`: 현재 단계(`N/M`) 또는 서브스킬 종료 시 `returned`
  - `return_to`: 최상위 스킬이면 `null`, 서브스킬이면 `{parent_skill}/{step_number}`
- 서브스킬 종료 마커: `[MST skill={subskill} step=returned return_to={parent/step}]`
- 예시:
  - `[MST skill=agile-plan step=0/3 return_to=null]`
  - `[MST skill=agile-plan step=returned return_to=agile/1]`

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

- Story 레이어/Checklist 레이어를 objective에 생성하는 행위
- DoD 항목에 구현 방법(API 엔드포인트, 함수명, 파일명, 기술 스택)을 강제하는 행위
- Step 0 없이 objective 생성을 시작하는 행위
- 스프린트 횟수/완료 시점을 예측·확정·암시하는 표현을 objective/질문/보고에 기재하는 행위
- objective.md에 "예상 스프린트", "N회 스프린트", "X주 내 완료" 등 필드/문장을 추가하는 행위
- 캘린더 단위로 변환한 기간 추정(예: "4~8주 소요")을 기재하는 행위
- 과거 실적을 현재 프로젝트의 완료 시점/스프린트 횟수 예측 근거로 인용하는 행위
- 허용 표현: DoD 진행률(%), 완료/미완료 항목 수, Epic 간 상대적 복잡도 비교, 스티어링 방향 추천, 종료 후 총 스프린트 수 사후 집계

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

#### 0.2 agile init 호출

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile init --steering-every {STEERING_EVERY} --json` 실행
2. 출력에서 `agi_id`를 파싱해 `AGI_ID`에 저장
3. `[신규 세션] AGI-{NNN} 생성됨 (steering-every: {STEERING_EVERY})` 출력
4. Step 1로 진행

---

### Step 1: Objective 생성/정규화

`[MST skill=agile-plan step=1/3 return_to={RETURN_TO_OR_NULL}]`

`--doc`가 있으면 **1B**, 없으면 **1A**를 수행한다.

---

#### Step 1A: JTBD + Epic DoD Q&A 생성 모드

**목표**: JTBD 5개 질문과 Epic DoD Q&A로 objective.md를 생성한다.

##### 1A.1 JTBD Q&A (5개, 자연어 대화 순차 진행)

1. **Job Statement**: "어떤 상황에서 이 프로젝트를 진행하게 되었나요? (When I ...)"
2. **핵심 목표**: "이 프로젝트를 통해 무엇을 달성하고 싶으신가요? (I want to ...)"
3. **기대 결과**: "성공했을 때 얻게 되는 가치는 무엇인가요? (So I can ...)"
4. **성공 지표**: "완료를 어떻게 측정할 수 있을까요? (측정 가능한 지표)"
5. **완료 정의**: "프로젝트가 완료됐다고 판단하는 기준은 무엇인가요? (프로젝트 DoD)"

##### 1A.2 Agile config 로드 + 추천 범위/수렴 파라미터 초기화

1. `config.resolved.json`의 `agile` 섹션에서 아래 키를 우선 로드한다. 없으면 괄호의 기본값을 사용한다.
   - `epic_count_min`(2), `epic_count_max`(5)
   - `dod_per_epic_min`(3), `dod_per_epic_max`(7)
   - `convergence_threshold_abs`(0.12), `convergence_threshold_trend`(0.18)
   - `soft_limit_small`(8), `soft_limit_large`(12), `soft_limit_epic_threshold`(10)
   - `round_history_max_summary_lines`(50)
2. `epic_count_min/max`, `dod_per_epic_min/max`는 **하드 제한이 아니라 추천 범위**로만 사용한다.
3. Epic 수가 `soft_limit_epic_threshold` 이상이면 `soft_limit_rounds=soft_limit_large`, 미만이면 `soft_limit_rounds=soft_limit_small`로 설정한다.

##### 1A.3 초기 Epic 초안 생성 (라운드 0)

1. JTBD 답변 기반으로 Epic 초안을 제안하고 사용자 확인을 받는다.
2. 각 Epic은 아래를 갖춘다.
   - `목표`: Epic이 달성해야 할 관찰 가능한 결과
   - `DoD 체크리스트`: Epic별 완료 판단 기준
   - `ODI 구조`: `Direction` + `Measure` + `Object` + `Context` + `Target`
   - `Detail (optional)`: 외부 참조만으로 불충분할 때만 사용
3. DoD 작성 시 ODI 가이드를 적용한다.
   - 방향: 최소화/최대화/유지 등 개선 방향
   - 측정: 관찰/측정 가능한 지표
   - 대상: 측정 대상 엔티티
   - 맥락: 측정이 이루어지는 상황/조건
   - 목표값: 수치 목표 또는 기대 결과
   - detail(선택): 외부 링크 없이 이해가 어려울 때만 보충 설명
   - 예시
     - 나쁜 예: "사용자 경험이 좋아야 한다"
     - 좋은 예: "[최소화] 설정 변경 후 저장까지의 [클릭 횟수]를 [설정 화면에서] [3회 이내로]"
4. Story 생성은 하지 않는다. 실행 단위 Story는 후속 Sprint 단계에서 JIT로 결정한다.

##### 1A.4 재귀 탐색 루프 (MANDATORY)

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
   - 감지된 변경사항은 해당 라운드 컨텍스트에 반영한다.
   - 변경 미감지 또는 대시보드 미접속 시 텍스트 폴백으로 계속 진행한다.
3. 피드백 수집은 AskUserQuestion이 아닌 자연어 대화로 처리한다.
4. 각 라운드 종료 시 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/round-history.md`에 라운드 요약을 append한다.
   - 포함 항목: 라운드 번호, `delta` 값, 주요 변경사항 3줄, 미해결 쟁점
   - 총 요약 라인이 `round_history_max_summary_lines`를 초과하면 오래된 라운드를 1줄로 축약(히스토리 압축)한다.

##### 1A.5 수렴 판정 알고리즘 (4축 delta + 2중 게이트)

각 라운드 종료 시 직전 라운드 대비 delta를 측정한다.

1. 4축 delta 구성요소
   - `N_t`: Epic/DoD 추가·삭제 건수 정규화 값
   - `E_t`: Epic 목표/DoD 본문 수정 건수 정규화 값
   - `S_t`: 구조 변경 이벤트(순서 재배치, split/merge, 의존성 변경) 정규화 값
   - `P_t`: 상태 변경/미해결 코멘트 영향도 정규화 값
2. 라운드 delta 계산
   - `D_t = (N_t + E_t + S_t + P_t) / 4`
3. 추세 계산(최근 3라운드)
   - `EMA3_t = alpha * D_t + (1 - alpha) * EMA3_(t-1)` (`alpha=0.5`, 초기값=`D_1`)
4. 종료 권장 2중 게이트 + 보조 조건
   - 절대 조건: `D_t <= convergence_threshold_abs`
   - 추세 조건: `EMA3_t <= convergence_threshold_trend`
   - 보조 조건: 미해결 코멘트 `<= 1`
5. 3개 조건을 모두 만족하면 PM이 아래 문구로 종료를 권장한다.
   - `[수렴 감지] N라운드 연속 변경량이 임계값 이하입니다. 현재 상태로 확정할까요?`
6. 사용자가 "계속"을 선택하면 루프를 유지한다.
7. 루프 종료는 사용자의 명시적 종료 선언으로만 확정한다.

##### 1A.6 soft limit 결정 체크포인트 (MANDATORY)

1. `round == soft_limit_rounds`에 도달하면 아래 문구를 출력한다.
   - `[라운드 한도 도달] {N}회 라운드를 진행했습니다.`
2. 현재까지 합의된 사항 요약과 미해결 쟁점 목록을 제시한다.
3. 사용자에게 명시적 선택을 받는다.
   - 종료: 현재 상태 확정 후 저장 단계로 진행
   - 연장: "무엇이 더 나아져야 하는가"를 텍스트로 받고 다음 라운드 진행
4. 동일 쟁점이 3회 반복되면 정체로 판단해 에스컬레이션 질문을 수행한다.

##### 1A.7 DoD 품질 게이트 (MANDATORY)

각 라운드 반영 직후(또는 최종 저장 직전) 9개 통합 품질 기준으로 DoD를 판정한다.

1. PM이 각 DoD 항목을 아래 기준으로 자동 판정(pass/fail)한다.

| # | 기준명 | 출처 | PM 판정 질문 |
|---|--------|------|-------------|
| 1 | 정확성 (Correctness) | IEEE 830 | 이 DoD가 프로젝트 목표(JTBD)와 일치하는가? |
| 2 | 비모호성 (Unambiguity) | IEEE+IREB | 해석 분기 없이 단 하나의 의미만 가지는가? |
| 3 | 완전성 (Completeness) | IEEE+IREB | 정상/에러/경계 조건이 모두 정의되었는가? |
| 4 | 일관성 (Consistency) | IEEE 830 | 다른 DoD/Epic 항목과 모순되지 않는가? |
| 5 | 검증가능성 (Verifiability) | IEEE+IREB | 관찰/측정으로 완료 여부를 판정할 수 있는가? |
| 6 | 필요성 (Necessity) | IREB | 이 DoD 없이는 Epic 목표 달성이 불가능한가? |
| 7 | 이해가능성 (Understandability) | IREB | 비기술 이해관계자도 의미를 이해할 수 있는가? |
| 8 | 중요도 순위 (Ranked) | IEEE 830 | 우선순위(필수/선택)가 부여되었는가? |
| 9 | ODI 구조 (Outcome Format) | ODI | 방향+측정+대상+맥락+목표값이 포함되었는가? |

2. pass/fail 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/quality-gate-log.md`에 **DoD별 1행 요약 표**로 기록한다.
3. 요약 표 컬럼은 반드시 아래 5개를 사용한다: `DoD ID`, `pass/total`, `결과`, `실패 기준 수`, `타임스탬프`
4. `결과=fail`인 DoD만 `<details>` 블록으로 상세를 추가한다.
   - 상세 표 컬럼: `기준명`, `미충족 사유`
   - `결과=pass`인 DoD는 상세를 만들지 않는다.
5. 미충족 항목만 추려서 사용자에게 보완 질문을 요청한다.
   - 보완 질문은 자연어 대화로 진행한다(AskUserQuestion 사용 금지).
6. 사용자 답변을 DoD에 반영한 뒤 같은 9개 기준으로 재검증한다.
7. 모든 DoD가 9개 기준 전체 pass일 때만 다음 라운드 또는 저장 단계로 진행한다.

##### 1A.8 4중 가드레일 검증 (MANDATORY)

1. **How-free**: 구현 방법이 포함되면 거부하고 관찰 가능한 결과 문장으로 재질문
2. **추천 범위 가이드**: Epic/DoD 수량은 `epic_count_min/max`, `dod_per_epic_min/max` 추천 범위를 안내하되 차단하지 않는다. 추천 범위 초과 시 분할/통합을 권장한다.
3. **So-that 검증**: 각 DoD가 "X한다, so that 사용자는 Y할 수 있다"로 연결 가능한지 확인
4. **Sprint 간 동결**: 진행 중 Sprint의 체크리스트 변경 금지, 변경은 스티어링 체크포인트에서만 반영

##### 1A.9 DoR 준비도 게이트 (MANDATORY)

최종 저장(1A.10) 전에 아래 5개 체크리스트를 모두 확인한다.

1. `Epic 목표 정의`: 모든 Epic에 관찰 가능한 목표가 명시됨
2. `DoD 수량 권장`: Epic/DoD 수량이 config 추천 범위를 벗어나면 리스크를 안내하고 사용자의 최종 확인을 받음
3. `DoD 품질 게이트 통과`: 9개 기준 전체 pass
4. `JTBD 완전성`: 5개 필드(Job/목표/결과/지표/완료정의) 누락 없음
5. `측정 가능 성공 지표`: 1개 이상의 정량적 성공 지표 존재

##### 1A.10 objective.md 저장

`templates/objective.md` 포맷으로 아래 경로에 저장:

```
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
```

저장 규칙:
- 섹션은 최소 `진행 상태 요약` + `JTBD 레이어` + `Epic 의존성 / 순서` + `Epic 레이어`를 포함
- Story/Checklist 별도 레이어는 만들지 않음
- 각 DoD는 다중행 구조(`Direction/Measure/Object/Context/Target`)를 사용
- `Detail (optional)`은 필요한 DoD에만 추가
- objective.md의 마커 무결성을 절대 보장한다. 아래 마커를 변경/삭제하지 않는다.
- 모든 DoD 항목에 아래 마커를 포함
  - `<!-- epic:EPIC-NNN dod:DOD-NNN status:todo -->`

저장 후:
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 생성 요약 출력

---

#### Step 1B: --doc 문서 파싱 모드

**목표**: 기존 문서를 JTBD/Epic DoD 구조로 정규화하고 누락 항목을 Q&A로 보완한다.

##### 1B.1 문서 파싱

1. `Read({PROJECT_ROOT}/{--doc 경로})` 실행 (절대경로 변환)
2. 아래를 추출해 `PARSED_CONTEXT`에 저장
   - JTBD: When I / I want to / So I can / 성공 지표 / 완료 정의
   - Epic: 제목/섹션/그룹 기반 Epic 후보
   - DoD: Epic 하위 체크리스트/완료 기준 항목
3. Story/구현 상세는 objective 산출물에 반영하지 않고 Epic DoD로만 정규화한다.

##### 1B.2 문서 기반 초기 정규화 (라운드 0)

1. `PARSED_CONTEXT` 기반으로 JTBD/Epic/DoD 초안을 생성한다.
2. 누락/모호 항목은 자연어 대화로 보완한다(AskUserQuestion 사용 금지).
3. Epic 목표가 모호하면 "관찰 가능한 결과" 기준으로 재질문한다.
4. DoD 보완 시 Step 1A.3의 ODI 구조를 동일하게 적용한다.

##### 1B.3 재귀 탐색 루프 적용 (MANDATORY)

`--doc` 모드도 Step 1A의 재귀 루프를 동일하게 적용한다.

1. 루프 구조: `WHILE (사용자 종료 선언 전)`을 그대로 적용한다.
2. 라운드 절차: 요약 -> PM 개선안 -> 사용자 피드백(자연어 대화) -> 반영 -> 수렴 체크
3. 수렴 판정: 4축 `delta` + `EMA3` + 미해결 코멘트 보조조건을 동일 기준으로 적용한다.
   - `convergence_threshold_abs`, `convergence_threshold_trend`를 동일 참조
4. soft limit/정체 감지/결정 체크포인트를 동일 기준으로 적용한다.
5. 대시보드 URL 안내/변경 감지/텍스트 폴백을 동일하게 적용한다.
6. 라운드 히스토리 파일(`round-history.md`) append + 히스토리 압축을 동일하게 적용한다.
7. DoD 품질 게이트(9개 기준), 4중 가드레일, DoR 준비도 게이트를 각 라운드 반영 후와 최종 저장 전에 동일 적용한다.

##### 1B.4 objective.md 저장

- 1A.10과 동일한 경로/포맷/마커 규칙으로 저장
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 정규화 요약 출력(추가/수정된 JTBD/Epic/DoD)

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
- 상위 스킬 예시 호출:
  - `Skill(skill: "mst:agile-plan", args: "{프로젝트 목표} --return-to agile/1")`

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

1. Epic DoD 체크리스트가 완료 판정의 유일한 게이트다(LLM override 금지).
2. Sprint 완료 시 체크 갱신은 "제안"만 가능하며 `evidence_ref`를 반드시 포함한다.
3. 최종 approve/reject는 스티어링 체크포인트에서 사용자가 수행한다.
