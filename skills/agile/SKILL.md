---
name: agile
description: "프로젝트 목표를 제공하면 애자일 마스터가 스프린트 단위로 작업을 분해하여 자율 실행합니다. 목적 문서(objective.md) 생성/검토 → Sprint 0 → Sprint N 루프 → 스티어링 체크포인트."
user-invocable: true
argument-hint: "{프로젝트 목표 또는 --resume AGI-NNN | --doc 파일경로 | --steering-every N}"
---

# maestro:agile

**목적**: 프로젝트 목표를 받아 JTBD+Epic/Story+Checklist 구조의 목적 문서를 생성/검토하고, 스프린트 단위 자율 실행 루프를 진행합니다.

핵심 우회 금지 규칙은 아래 Gate/체크리스트 섹션을 따른다.

## ⚠️ 실행 제약 (CRITICAL — 항상 준수)

이 스킬 실행 중 **Write/Edit 도구를 사용할 수 있는 경로는 아래만 해당**합니다:

- `{PROJECT_ROOT}/.gran-maestro/agile/AGI-*/objective/objective.md` (신규 생성 시 Step 1에서만)

**그 외 모든 경로(스킬 파일, 소스 코드, 설정 파일, objective.md 직접 수정 등)에 대한 Write/Edit 사용은 절대 금지입니다.**

- **objective.md 상태 전이(status 변경, checklist 체크 등)는 반드시 `mst.py agile objective-transition` / `mst.py agile objective-check`를 통해서만 수행한다.** LLM이 objective.md를 직접 편집하는 것은 엄격히 금지된다.
- 스프린트 루프에서 plan 생성은 반드시 `Skill(skill: "mst:plan", args: "-a ...")` 서브스킬 호출로 수행한다.

허용 경로 외 수정 요청 시: 즉시 중단 → mst.py 스크립트 사용 안내 출력


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
  - `[MST skill=agile step=0/3 return_to=null]`
  - `[MST skill=plan step=returned return_to=agile/2]`


## Gate

### Entry

- `/mst:agile` 호출 시 Step 0~1 전체 프로토콜을 실행 대상으로 잠근다.
- 시작 전에 Write/Edit 허용 경로가 `AGI-*` 산출물 경로인지 확인한다.
- `--resume AGI-NNN`이 있으면 기존 세션 재개 경로로 분기한다.

### Exit

- Step 1 완료(objective.md 확정) 후 스프린트 루프(REQ-480)로 진입한다.
- 스프린트 루프는 REQ-480에서 구현 예정이며, 이 스킬은 현재 Step 0~1까지만 구현한다.

### 금지 패턴

- LLM이 objective.md를 직접 Write/Edit로 수정하는 행위.
- `mst.py agile objective-transition` / `objective-check` 우회.
- Step 0(세션 초기화) 없이 바로 objective 생성으로 진입.


## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```


---

### Step 0: 세션 초기화

`[MST skill=agile step=0/3 return_to=null]`

#### 0.1 인자 파싱

args 전체 토큰에서 아래 플래그를 감지한다:

| 플래그 | 설명 | 예시 |
|--------|------|------|
| `--resume AGI-NNN` | 기존 세션 재개 | `--resume AGI-001` |
| `--doc 파일경로` | 기존 문서 지정 (파싱 모드) | `--doc docs/goals.md` |
| `--steering-every N` | 스티어링 체크포인트 간격 (기본값: 3) | `--steering-every 5` |

- `--steering-every` 미지정 시: `STEERING_EVERY=3` 기본값 설정

#### 0.2 분기: --resume 있는 경우

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile status AGI-NNN --json` 실행
2. session.json 로드 성공 시: `AGI_ID`, `CURRENT_SPRINT`, `STEERING_EVERY`를 메모리에 보관
3. 세션 상태 출력: `[재개] AGI-{NNN} — 스프린트 {N} 상태: {status}`
4. Step 1 건너뜀 → 스프린트 루프(REQ-480)로 진행 *(현재: 재개 안내 출력 후 종료)*
5. session.json 로드 실패 또는 AGI-NNN 미존재 시:
   - 에러 메시지 출력: `[오류] AGI-{NNN} 세션을 찾을 수 없습니다.`
   - 복구 안내: `.gran-maestro/agile/` 디렉토리 확인 방법 안내 후 중단

#### 0.3 분기: 신규 세션 (--resume 없는 경우)

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile init --steering-every {STEERING_EVERY} --json` 실행
2. 출력에서 `agi_id` 파싱하여 `AGI_ID`에 저장
3. `[신규 세션] AGI-{NNN} 생성됨 (steering-every: {STEERING_EVERY})` 출력
4. Step 1으로 진행

---

### Step 1: Objective 문서 생성/검토

`[MST skill=agile step=1/3 return_to=null]`

#### 분기 결정

`--doc 파일경로`가 있으면 **1B (기존 문서 파싱 모드)**, 없으면 **1A (Q&A 생성 모드)**로 진행한다.

---

#### Step 1A: Q&A로 Objective 신규 생성 (--doc 없는 경우)

**목표**: 대화형 Q&A로 JTBD+Epic/Story+Checklist 3계층 구조의 objective.md를 생성한다.

##### 1A.1 JTBD 레이어 Q&A

아래 질문을 순서대로 진행한다. 각 질문은 `AskUserQuestion`으로 하나씩 진행한다:

1. **Job Statement**: "어떤 상황에서 이 프로젝트를 진행하게 되었나요? (When I ... )"
2. **핵심 목표**: "이 프로젝트를 통해 무엇을 달성하고 싶으신가요? (I want to ... )"
3. **기대 결과**: "성공했을 때 얻게 되는 가치는 무엇인가요? (So I can ... )"
4. **성공 지표**: "완료를 어떻게 측정할 수 있을까요? (측정 가능한 지표)"
5. **완료 정의(DoD)**: "모든 작업이 완료됐다고 판단하는 구체적인 기준은 무엇인가요?"

##### 1A.2 Epic/Story 레이어 Q&A

JTBD 답변을 기반으로 Epic 후보를 제안하고 확인:

1. 수집된 JTBD를 기반으로 **Epic 2~5개** 초안 생성 및 제안
2. 사용자 피드백으로 Epic 확정
3. 각 Epic에 대해 **Story 2~5개** 초안 생성 및 제안
4. 각 Story의 우선순위(priority: high/medium/low)와 의존성(deps) 확인

##### 1A.3 Checklist 레이어 Q&A

1. 테스트 요건: "각 Story 완료 전 필요한 테스트가 있나요? (예: 단위 테스트, E2E 테스트)"
2. 문서화 요건: "완료 시 작성해야 할 문서가 있나요?"
3. 리뷰 요건: "완료 전 리뷰가 필요한 항목이 있나요?"

##### 1A.4 Objective.md 생성

Q&A 결과를 `templates/objective.md` 형식으로 구조화하여 아래 경로에 저장:

```
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
```

> ⚠️ 신규 생성 시에만 Write 허용. 이후 모든 수정은 `mst.py agile objective-transition` / `objective-check` 사용.

저장 완료 후:
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 생성된 objective.md 요약 출력
- Step 2(스프린트 루프 — REQ-480)로 진입 *(현재: 생성 완료 안내 후 종료)*

---

#### Step 1B: 기존 문서 파싱 및 검토 (--doc 있는 경우)

**목표**: 기존 문서를 파싱하여 JTBD/Epic/Story/Checklist로 정규화하고, 누락/모호 항목에 대해 Q&A로 보완한다.

##### 1B.1 기존 문서 파싱

1. `Read({PROJECT_ROOT}/{--doc 경로})` 실행 (절대경로로 변환)
2. 아래 구조로 파싱 시도:
   - **JTBD 레이어**: "When I", "I want to", "So I can", DoD, 성공 지표 추출
   - **Epic 레이어**: 제목/섹션/그룹 추출 → Epic 후보 식별
   - **Story 레이어**: Epic 하위 항목 추출 → Story 후보 식별
   - **Checklist 레이어**: 체크리스트/완료 기준/테스트/리뷰 항목 추출
3. 파싱 결과를 `PARSED_CONTEXT`에 저장

##### 1B.2 정규화 및 모호성 제거 Q&A

파싱 결과를 기반으로 누락/모호 항목에 대해 추가 Q&A 진행:

1. **JTBD 누락 항목**: 파싱되지 않은 JTBD 필드에 대해 각각 질문
   - 예: "파싱된 문서에서 'So I can' 항목을 찾을 수 없었습니다. 이 프로젝트를 통해 얻게 되는 가치는 무엇인가요?"
2. **모호한 Epic/Story**: 범위가 불명확하거나 완료 기준이 없는 항목 확인
   - 예: "{Epic명}의 완료 기준이 명시되지 않았습니다. 어떤 상태가 되면 완료로 볼 수 있나요?"
3. **누락된 Story 필드**: priority, deps, sprint_target이 없는 Story에 대해 확인
4. **Checklist 누락**: 테스트/문서/리뷰 게이트가 없는 Story에 대해 확인

파싱 후 Q&A가 불필요한 경우(모든 필드 충족): "기존 문서가 완전합니다. 확인 후 스프린트 루프로 진행할까요?" 확인 요청

##### 1B.3 정규화된 Objective.md 저장

파싱 + Q&A 보완 결과를 `templates/objective.md` 형식으로 정규화하여 저장:

```
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
```

> ⚠️ 신규 생성 시에만 Write 허용. 이후 모든 수정은 `mst.py agile objective-transition` / `objective-check` 사용.

저장 완료 후:
- `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status active --objective-version 1 --json` 실행
- 정규화 요약 출력 (원본 대비 변경/추가된 항목 목록)
- Step 2(스프린트 루프 — REQ-480)로 진입 *(현재: 검토 완료 안내 후 종료)*

---

### Step 2: 스프린트 루프

`[MST skill=agile step=2/3 return_to=null]`

#### 2.0 재개 분기 결정

세션 초기화(Step 0)에서 전달된 `CURRENT_SPRINT` 값으로 진입 경로를 결정한다.

- `--resume AGI-NNN`으로 진입한 경우: 세션 초기화에서 session.json을 로드하여 `CURRENT_SPRINT`가 이미 설정되어 있어야 한다.
  - session.json 손상 또는 `current_sprint` 필드 누락 시:
    - `[오류] AGI-{AGI_ID} session.json 손상 — current_sprint 값을 읽을 수 없습니다.` 출력
    - 복구 안내: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/session.json`을 직접 점검하거나 삭제 후 신규 세션으로 재시작
    - 실행 중단
  - 정상 로드 시: `[재개] AGI-{AGI_ID} — 스프린트 {CURRENT_SPRINT}부터 재시작` 출력
- 신규 세션(Step 1에서 진입): `CURRENT_SPRINT=0` 으로 시작

분기:
- `CURRENT_SPRINT == 0` 또는 Sprint 0 미완료 → **2.1 (Sprint 0)** 으로 진행
- `CURRENT_SPRINT >= 1` 및 Sprint 0 완료 → **2.2 (Sprint N 루프)** 로 직접 진행

---

#### 2.1 Sprint 0: 테스트 환경 구축

**목표**: 프로젝트의 테스트 러너/프레임워크를 감지하고, smoke test 1개 이상이 통과한 것을 확인한 후 Sprint 1로 진입한다.

##### 2.1.1 테스트 러너 감지

아래 파일을 순서대로 확인하여 테스트 러너를 감지한다:

1. `package.json` — `scripts.test` 필드 확인 (jest, vitest, mocha 등)
2. `Makefile` — `test` 타깃 확인
3. `pyproject.toml` / `setup.cfg` / `pytest.ini` — pytest 감지
4. `Cargo.toml` — `cargo test` (Rust)
5. `go.mod` — `go test ./...` (Go)
6. `.github/workflows/` — CI 설정에서 테스트 명령어 추출

감지 결과를 `TEST_RUNNER` 변수에 저장하고 출력:

```
[Sprint 0] 테스트 러너 감지: {TEST_RUNNER}
```

##### 2.1.2 테스트 환경 미존재 시

테스트 러너 감지 실패 시:

1. `[Sprint 0] 테스트 환경 없음 — 기본 환경 구축 시작` 출력
2. 아래 서브스킬 호출로 기본 테스트 환경 자동 구축:

```
Skill(skill: "mst:plan", args: "-a 프로젝트에 최소한의 smoke test 1개를 포함한 테스트 환경을 구축한다. 테스트 러너를 선택하고 설정 파일을 작성하며, 항상 통과하는 smoke test 1개를 작성한다.")
```

3. 완료 후 2.1.1로 재시도 (최대 1회). 재시도 실패 시 사용자 안내 후 중단.

##### 2.1.3 Smoke Test 실행 및 Sprint 1 진입 조건

1. 감지된 `TEST_RUNNER`로 smoke test 실행하여 **최소 1개 테스트 통과** 확인
2. 통과 시:
   - `[Sprint 0] smoke test 통과 — Sprint 1 진입 조건 충족` 출력
   - `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --current-sprint 1 --json` 실행
   - `CURRENT_SPRINT=1` 설정 후 Sprint N 루프(2.2)로 진입
3. 실패 시:
   - `[Sprint 0] smoke test 실패 — 원인 분석 후 수동 확인 필요` 출력 + 실패 로그 요약
   - `AskUserQuestion`으로 사용자에게 확인 요청 후 재시도 또는 중단

---

#### 2.2 Sprint N 자율 루프

**목표**: objective.md의 모든 story가 완료될 때까지 스프린트를 반복한다.

##### 2.2.1 루프 진입 조건 확인

반복 시작 전 매번 수행:

```
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json
```

- `all_done: true` → 루프 종료 (2.3 최종 보고서로 이동)
- `all_done: false` → 다음 story 선택 (2.2.2)

> ⚠️ 스티어링 체크포인트는 REQ-481에서 구현됩니다.

##### 2.2.2 작업(Story) 선택

`objective-check` 출력에서 아래 기준으로 story를 선택한다:

1. **deps 필터**: 모든 `deps` story가 `status=done`인 story만 후보
2. **priority 정렬**: `high → medium → low` 순서 (`mst.py agile objective-check` 활용)
3. 첫 번째 후보 story를 `SELECTED_STORY`로 선정
4. 후보가 없는 경우 (모든 후보가 blocked 또는 deps 미해소):
   - `[경고] 선택 가능한 story가 없습니다. blocked story를 확인하세요.` 출력
   - 루프 중단 후 사용자 안내

선정된 story 정보 출력:

```
[Sprint {CURRENT_SPRINT}] 선택된 story: {STORY_ID} — {story 제목} (priority: {priority})
```

##### 2.2.3 컨텍스트 전달 3계층 구성 (DSC-044)

plan -a 호출 전 3계층 컨텍스트를 구성한다:

| 계층 | 내용 | 출처 |
|------|------|------|
| **고정층** | objective.md의 JTBD(목표·제약·성공 지표·DoD) 요약 | 파일 경로 참조: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md` |
| **활성층** | 이번 스프린트 대상 story + AC + 선행/후행 deps story 목록 | `objective-check` 결과 |
| **변화층** | 직전 1~2 스프린트 결과 요약 (완료 항목, 실패 원인) | 파일 경로 참조: `sprints/S{N-1}/result.md`, `sprints/S{N-2}/result.md` |

**규칙**:
- 전체 히스토리 전달 금지 — 변화층은 직전 1~2 스프린트만 참조
- 원문은 파일 경로로 참조 (인라인 삽입 금지)

##### 2.2.4 plan -a 호출

구성한 3계층 컨텍스트를 포함하여 plan을 자율 실행한다:

```
Skill(skill: "mst:plan", args: "-a {STORY_DESCRIPTION}
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 대상: {STORY_ID} — {STORY_TITLE} | deps: {DEPS_LIST} | AC: {AC_LIST}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md")
```

서브스킬 종료 마커 확인: `[MST skill=plan step=returned return_to=agile/2]`

##### 2.2.5 결과 기록

plan -a 실행 완료 후 아래 순서로 처리한다:

**① 스프린트 결과 기록** (`agile result`):

```
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{STORY_ID}" \
  --completed "{STORY_ID_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --json
```

**② story 상태 업데이트**:
- 성공 시: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {STORY_ID} --status done`
- 실패 시: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {STORY_ID} --status blocked`

**③ session.json 업데이트**:

```
python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```

**④ 반복**: `CURRENT_SPRINT = CURRENT_SPRINT + 1` 설정 후 루프 상단(2.2.1)으로 반복

---

#### 2.3 루프 종료 및 최종 보고서

**종료 조건**: `mst.py agile objective-check {AGI_ID} --json` 결과에서 `all_done: true` 반환.

최종 보고서를 출력한다:

```
========================================
[완료] AGI-{AGI_ID} 자율 스프린트 루프 종료
========================================

총 스프린트 수: {TOTAL_SPRINTS}
완료된 story 수: {DONE_STORIES} / {TOTAL_STORIES}
생성된 PLN 목록: {PLN_IDS}
생성된 REQ 목록: {REQ_IDS}

스프린트 결과 요약:
- 성공: {SUCCESS_COUNT}회
- 실패: {FAIL_COUNT}회

결과 디렉토리: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/
목표 달성 여부: {JTBD_SUCCESS_SUMMARY}
========================================
```

`python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status completed --json` 실행 후 종료.

---

## 상태 전이 규칙 (CRITICAL)

**LLM은 objective.md를 절대 직접 편집하지 않습니다.**

모든 상태 변경은 아래 mst.py 스크립트 명령어로만 수행합니다:

| 작업 | 명령어 |
|------|--------|
| Story 상태 변경 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {story_id} --status {todo\|in_progress\|done\|blocked}` |
| 완료 여부 전체 확인 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json` |
| 세션 상태 업데이트 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status {active\|paused\|completed}` |
| 스프린트 결과 기록 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} ...` |

**이유**: LLM의 YAML/Markdown 파싱 오류 누적을 방지하고 상태 파일의 무결성을 보장한다. (DSC-044 critic 합의)

---

## Anti-Rationalization Checklist

- 합리화 패턴: "간단한 목표니 JTBD Q&A를 생략해도 된다." | 확인 증거: JTBD 5개 필드(When I / I want to / So I can / 성공 지표 / DoD) 모두 수집됨을 Step 1 종료 시 출력.
- 합리화 패턴: "objective.md가 이미 있으니 직접 편집해도 된다." | 확인 증거: 상태 변경 시 항상 `mst.py agile objective-transition` 실행 로그 존재.
- 합리화 패턴: "Step 0 없이 바로 Q&A로 진행해도 된다." | 확인 증거: `mst.py agile init` 또는 `mst.py agile status` 실행 로그가 Step 0에서 존재.
