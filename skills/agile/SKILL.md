---
name: agile
description: "프로젝트 목표를 제공하면 JTBD+Epic(DoD 체크리스트) 기반 자율 실행을 수행합니다. Step 1은 agile-plan 서브스킬로 objective.md를 준비하고 Sprint 0 → Sprint N 루프 → 스티어링 체크포인트를 반복합니다."
user-invocable: true
argument-hint: "{프로젝트 목표(JTBD+Epic(DoD 체크리스트) 기반) 또는 --resume AGI-NNN | --doc 파일경로 | --steering-every N}"
---

# maestro:agile

**목적**: 프로젝트 목표를 받아 JTBD+Epic(DoD 체크리스트) 기반 objective 흐름을 `agile-plan`으로 초기화하고, 스프린트 단위 자율 실행 루프를 진행합니다.

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
  - `[MST skill=agile step=0/4 return_to=null]`
  - `[MST skill=plan step=returned return_to=agile/2]`


## Gate

### Entry

- `/mst:agile` 호출 시 Step 0~1 전체 프로토콜을 실행 대상으로 잠근다.
- 시작 전에 Write/Edit 허용 경로가 `AGI-*` 산출물 경로인지 확인한다.
- `--resume AGI-NNN`이 있으면 기존 세션 재개 경로로 분기한다.

### Exit

- Step 1에서 `agile-plan` 서브스킬 반환 마커 확인 후 Step 2로 진입한다.
- Step 2/3 루프는 `objective_mode`(`epic|story`)에 따라 분기 실행한다.

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
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 절대경로입니다.


---

### Step 0: 세션 초기화

`[MST skill=agile step=0/4 return_to=null]`

#### 0.1 인자 파싱

args 전체 토큰에서 아래 플래그를 감지한다:

| 플래그 | 설명 | 예시 |
|--------|------|------|
| `--resume AGI-NNN` | 기존 세션 재개 | `--resume AGI-001` |
| `--doc 파일경로` | 기존 문서 지정 (파싱 모드) | `--doc docs/goals.md` |
| `--steering-every N` | 스티어링 체크포인트 간격 (기본값: 3) | `--steering-every 5` |

- `--steering-every` 미지정 시: `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`의 `agile.steering_every` 값을 사용한다. config에도 없으면 기본값 `3`.

#### 0.2 분기: --resume 있는 경우

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile status AGI-NNN --json` 실행
2. session.json 로드 성공 시: `AGI_ID`, `CURRENT_SPRINT`, `STEERING_EVERY`, `OBJECTIVE_MODE`를 메모리에 보관
   - `OBJECTIVE_MODE` 필드가 없거나 비정상이면 `story`로 간주한다(하위 호환).
3. 세션 상태 출력: `[재개] AGI-{NNN} — 스프린트 {N} 상태: {status} (mode: {OBJECTIVE_MODE})`
4. Step 1 건너뜀 → 스프린트 루프(REQ-480)로 진행
5. session.json 로드 실패 또는 AGI-NNN 미존재 시:
   - 에러 메시지 출력: `[오류] AGI-{NNN} 세션을 찾을 수 없습니다.`
   - 복구 안내: `.gran-maestro/agile/` 디렉토리 확인 방법 안내 후 중단

#### 0.3 분기: 신규 세션 (--resume 없는 경우)

1. 신규 세션 생성과 objective 초기화는 Step 1의 `agile-plan` 서브스킬에서 수행한다.
2. Step 1 호출을 위해 사용자 입력 목표(`PROJECT_GOAL`)와 선택 플래그(`DOC_PATH`, `STEERING_EVERY`)를 메모리에 보관한다.
3. `[신규 세션 준비] agile-plan 위임 예정 (steering-every: {STEERING_EVERY})` 출력
4. Step 1로 진행

---

### Step 1: Objective 준비 (agile-plan 서브스킬 위임)

`[MST skill=agile step=1/4 return_to=null]`

신규 세션(`--resume` 없음)은 Step 1 전체를 아래 1줄 호출로 수행한다:

```text
Skill(skill: "mst:agile-plan", args: "{PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} --steering-every {STEERING_EVERY} --return-to agile/1")
```

규칙:
- `--doc` 입력이 있으면 `DOC_FLAG_IF_ANY`에 `--doc {DOC_PATH}`를 포함하여 그대로 전달한다.
- `--doc` 입력이 없으면 `{PROJECT_GOAL_OR_DOC}`에 사용자 목표 문장을 전달한다.
- 서브스킬 종료 마커 `[MST skill=agile-plan step=returned return_to=agile/1]` 확인 후 stop-hook re-feed로 Step 2에 자동 진입한다.

---

### Step 2: 스프린트 루프

`[MST skill=agile step=2/4 return_to=null]`

#### 2.0 상태 복원 + objective_mode 분기

세션 초기화(Step 0) 또는 Step 1 복귀 결과로 `CURRENT_SPRINT`, `STEERING_EVERY`, `OBJECTIVE_MODE`를 복원한다.

- `--resume AGI-NNN` 진입:
  - session.json에서 `current_sprint`를 복원하고, `objective_mode`를 확인한다.
  - `objective_mode=epic`이면 Epic 기반 루프(2.2-E), `objective_mode=story`이면 기존 Story 기반 루프(2.2-S)로 분기한다.
  - `objective_mode` 필드가 없거나 비정상이면 `story`로 간주한다(하위 호환).
  - session.json 손상 또는 `current_sprint` 필드 누락 시:
    - `[오류] AGI-{AGI_ID} session.json 손상 — current_sprint 값을 읽을 수 없습니다.` 출력
    - 복구 안내: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/session.json`을 직접 점검하거나 삭제 후 신규 세션으로 재시작
    - 실행 중단
- 신규 세션(Step 1에서 복귀):
  - `agile-plan` 생성 결과의 `AGI_ID`를 사용한다.
  - `CURRENT_SPRINT=0`, `OBJECTIVE_MODE=epic`으로 시작한다.

분기:
- `CURRENT_SPRINT == 0` 또는 Sprint 0 미완료 → **2.1 (Sprint 0)** 으로 진행
- `CURRENT_SPRINT >= 1` 및 Sprint 0 완료 + `OBJECTIVE_MODE=epic` → **2.2-E (Epic 루프)** 로 진행
- `CURRENT_SPRINT >= 1` 및 Sprint 0 완료 + `OBJECTIVE_MODE=story` → **2.2-S (기존 Story 루프)** 로 진행

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

#### 2.2 Sprint N 자율 루프 (objective_mode 분기)

**목표**: `objective_mode`에 따라 Sprint 실행 단위를 결정한다.
- `epic` 모드: Epic 미완료 DoD 기반 JIT Story 1개를 매 Sprint 도출
- `story` 모드: 기존 Story 선택 로직 유지 (하위 호환)

##### 2.2.1 공통 루프 게이트

반복 시작 전 매번 수행:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json
```

- `all_done: true` → 루프 종료 (2.3 최종 보고서로 이동)
- `all_done: false` → 스티어링 체크포인트 확인 후 모드별 루프로 진행

**스티어링 체크포인트 확인**: `CURRENT_SPRINT > 0` 이고 `CURRENT_SPRINT % STEERING_EVERY == 0` 이면 **Step 3(스티어링 체크포인트)** 로 분기하고, 완료 후 루프를 계속 진행.

##### 2.2-E Epic 기반 루프 (OBJECTIVE_MODE=epic)

**목표**: Epic의 미완료 required DoD 항목을 Sprint마다 JIT Story 1개로 전환하여 점진 완료한다.

###### 2.2-E.1 JIT Story 도출 (Sprint 시작)

직전 result + Epic 현재 상태를 사용해 이번 Sprint의 Story 1개를 도출한다.

| 계층 | 내용 | 출처 |
|------|------|------|
| **고정층** | objective.md의 JTBD + Epic DoD 전체 맥락 | `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md` |
| **활성층** | 현재 Epic + 미완료 required DoD 항목 | `objective-check --json`의 `incomplete` + objective 파싱 |
| **변화층** | 직전 Sprint 결과 요약 | `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md` |

도출 규칙:
1. `objective-check` 결과의 `incomplete`(DoD ID 목록)에서 이번 Sprint 대상 DoD 묶음을 선택한다.
2. 변화층(result.md)에서 직전 실패/미완료 원인을 반영한다.
3. 위 두 입력으로 이번 Sprint의 Story 1개를 즉시 도출하고 `JIT_STORY_ID`, `JIT_STORY_DESC`를 선언한다.
4. 출력: `[Sprint {CURRENT_SPRINT}] JIT Story 도출: {JIT_STORY_ID} — {JIT_STORY_DESC}`

###### 2.2-E.2 plan -a 호출 (컨텍스트 3계층 유지)

```text
Skill(skill: "mst:plan", args: "-a {JIT_STORY_DESC}
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 현재 Epic: {EPIC_ID} | 미완료 DoD: {INCOMPLETE_DOD_LIST} | 이번 JIT Story: {JIT_STORY_ID}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md")
```

서브스킬 종료 마커 확인: `[MST skill=plan step=returned return_to=agile/2]`

###### 2.2-E.3 Sprint 결과 기록 + DoD 갱신 제안 기록

plan -a 실행 완료 후 아래 순서로 처리한다:

1. 스프린트 결과 기록:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{JIT_STORY_ID}" \
  --completed "{JIT_STORY_ID_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --json
```
2. DoD 체크리스트 갱신 "제안" 생성(확정 아님):
   - Sprint result 기반으로 제안 목록을 만든다: `{dod_id, suggested_status, evidence_ref, reason}`
   - `evidence_ref`에는 근거 파일 절대경로를 반드시 포함한다 (`result.md`, 테스트 로그, diff 요약 등).
3. 제안 기록 (`objective-transition` 사용, 확정은 Step 3):
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status proposed_done --json
```
4. session.json 업데이트:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```
5. 반복: `CURRENT_SPRINT = CURRENT_SPRINT + 1` 설정 후 루프 상단(2.2.1)으로 복귀

##### 2.2-S Story 기반 루프 (OBJECTIVE_MODE=story, 하위 호환)

**목표**: 기존 Story 기반 Sprint 로직을 유지한다.

###### 2.2-S.1 작업(Story) 선택

`objective-check` 출력에서 아래 기준으로 story를 선택한다:

1. **deps 필터**: 모든 `deps` story가 `status=done`인 story만 후보
2. **priority 정렬**: `high → medium → low` 순서 (`mst.py agile objective-check` 활용)
3. 첫 번째 후보 story를 `SELECTED_STORY`로 선정
4. 후보가 없는 경우 (모든 후보가 blocked 또는 deps 미해소):
   - `[경고] 선택 가능한 story가 없습니다. blocked story를 확인하세요.` 출력
   - 루프 중단 후 사용자 안내

선정된 story 정보 출력:

```text
[Sprint {CURRENT_SPRINT}] 선택된 story: {STORY_ID} — {story 제목} (priority: {priority})
```

###### 2.2-S.2 컨텍스트 전달 3계층 구성 (DSC-044)

plan -a 호출 전 3계층 컨텍스트를 구성한다:

| 계층 | 내용 | 출처 |
|------|------|------|
| **고정층** | objective.md의 JTBD(목표·제약·성공 지표·DoD) 요약 | 파일 경로 참조: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md` |
| **활성층** | 이번 스프린트 대상 story + AC + 선행/후행 deps story 목록 | `objective-check` 결과 |
| **변화층** | 직전 1~2 스프린트 결과 요약 (완료 항목, 실패 원인) | 파일 경로 참조: `sprints/S{N-1}/result.md`, `sprints/S{N-2}/result.md` |

**규칙**:
- 전체 히스토리 전달 금지 — 변화층은 직전 1~2 스프린트만 참조
- 원문은 파일 경로로 참조 (인라인 삽입 금지)

###### 2.2-S.3 plan -a 호출

```text
Skill(skill: "mst:plan", args: "-a {STORY_DESCRIPTION}
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 대상: {STORY_ID} — {STORY_TITLE} | deps: {DEPS_LIST} | AC: {AC_LIST}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md")
```

서브스킬 종료 마커 확인: `[MST skill=plan step=returned return_to=agile/2]`

###### 2.2-S.4 결과 기록

1. 스프린트 결과 기록:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{STORY_ID}" \
  --completed "{STORY_ID_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --json
```
2. story 상태 업데이트:
   - 성공 시: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {STORY_ID} --status done`
   - 실패 시: `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {STORY_ID} --status blocked`
3. session.json 업데이트:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```
4. 반복: `CURRENT_SPRINT = CURRENT_SPRINT + 1` 설정 후 루프 상단(2.2.1)으로 반복

---

#### 2.3 루프 종료 및 최종 보고서

**종료 조건**: `mst.py agile objective-check {AGI_ID} --json` 결과에서 `all_done: true` 반환.
- `OBJECTIVE_MODE=epic`: 모든 Epic의 required DoD 항목이 `done|completed`이면 `all_done=true`
- `OBJECTIVE_MODE=story`: 기존 Story 완료 집계 기준 유지

최종 보고서를 출력한다:

```
========================================
[완료] AGI-{AGI_ID} 자율 스프린트 루프 종료
========================================

총 스프린트 수: {TOTAL_SPRINTS}
완료된 항목 수: {DONE_ITEMS} / {TOTAL_ITEMS} (mode: {OBJECTIVE_MODE})
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

### Step 3: 스티어링 체크포인트

`[MST skill=agile step=3/4 return_to=null]`

**목표**: 정기 또는 비상 트리거 시 현재 진행 상황과 DoD 제안을 사용자에게 보고하고, approve/reject 및 objective 변경 여부를 반영한 뒤 루프를 계속 진행한다.

#### 3.1 트리거 조건

| 유형 | 조건 |
|------|------|
| **정기** | `CURRENT_SPRINT > 0` AND `CURRENT_SPRINT % STEERING_EVERY == 0` |
| **비상** | 안전장치 섹션의 비상 스티어링 트리거 조건 충족 시 즉시 진입 |

`steering_every` 값은 session.json에서 로드하며 기본값은 3이다.

모드 분기:
- `OBJECTIVE_MODE=epic`이면 3.2/3.3 DoD 제안 보고 및 approve/reject 절차를 수행한다.
- `OBJECTIVE_MODE=story`이면 기존 Story 기반 스티어링 보고/방향 수정 절차를 유지하고 3.3 DoD 제안 단계는 생략한다.

#### 3.2 진행 보고서 출력

아래 형식으로 **진행 보고서**를 출력한다:

```
========================================
[스티어링 체크포인트] AGI-{AGI_ID} — Sprint {CURRENT_SPRINT}
========================================

목표 진행률
- metric 달성률: {METRICS_PROGRESS} (성공 지표 기준)
- Epic burnup: {EPIC_DONE}/{EPIC_TOTAL} 완료 ({DOD_DONE}/{DOD_TOTAL} DoD)

최근 {STEERING_EVERY} 스프린트 요약
| 스프린트 | 계획 | 완료 | 미완료 | 블로커 |
|----------|------|------|--------|--------|
| S{N}     | ...  | ...  | ...    | ...    |

DoD 체크 갱신 제안 (pending)
| DOD-ID | 제안 상태 | evidence_ref | 근거 요약 |
|--------|-----------|--------------|-----------|
| DOD-... | proposed_done | .../sprints/S{N}/result.md | ... |

리스크 Top3
1. {RISK_1} — 영향도: {high|medium|low}
2. {RISK_2} — 영향도: {high|medium|low}
3. {RISK_3} — 영향도: {high|medium|low}

다음 추천 경로
- 추천: {RECOMMENDED_PATH}
- 근거: {RATIONALE}
- 대안: {ALTERNATIVE_PATH}
========================================
```

#### 3.3 DoD 제안 approve/reject (MANDATORY)

진행 보고서 출력 후 `AskUserQuestion`으로 사용자에게 확인:

> "DoD 제안 목록을 승인/반려해주세요. (예: approve DOD-001,DOD-002 / reject DOD-003)"

처리 규칙:
- **approve된 DOD**:
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status done --json`
  - authoritative 상태를 `done`으로 확정
- **reject된 DOD**:
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status todo --json`
  - reject 사유 + `evidence_ref`를 Sprint 메모에 기록
  - 다음 Sprint의 2.2-E.1 JIT Story 도출 시 `REJECTED_DOD_QUEUE`를 활성층 우선 입력으로 반영

#### 3.4 방향 수정 (Objective 변경)

진행 방향 수정이 필요하면 아래 순서로 처리한다:

1. 버전 스냅샷 저장:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-snapshot {AGI_ID} \
  --reason "{사용자 입력 요약}" --json
```

2. objective 재계획 서브스킬 재호출:

```text
Skill(skill: "mst:agile-plan", args: "--resume {AGI_ID}")
```

3. 재계획 결과 반영 후 2.2 루프로 복귀

#### 3.5 변경 후 정합성 정책

objective 변경 시 영향 범위에 따라 아래 정합성 정책을 적용한다:

| 레벨 | 조건 | 처리 방식 |
|------|------|-----------|
| **Level A** (경미) | 용어 정정, 성공 지표 소폭 조정 | 완료 스프린트 유지, 루프 계속 |
| **Level B** (중간) | Epic DoD 범위 조정, 우선순위 재조정 | 영향받는 DoD만 부분 재검증 후 루프 계속 |
| **Level C** (중대) | JTBD 목표 변경, Epic 추가/삭제 | 영향 Epic 재계산, 필요 시 부분 롤백 task 생성 |

**원칙**: 완료 기록 삭제 금지. 변경된 항목은 `superseded` 또는 `revalidated` 상태로 보존한다.

레벨 결정 후 `AskUserQuestion`으로 처리 방식 확인하고 루프로 복귀.

---

## 안전장치

### 카운터 유지 (MANDATORY)

아래 카운터는 기존 임계치/의미를 그대로 유지한다:

- `consecutive_failures`: 동일 작업 단위 연속 실패 횟수
- `drift_count`: 목표와 무관한 변경 누적 횟수
- `no_diff_count`: 실행 후 diff 없음 누적 횟수

### 4단계 복구 전략

작업 실패 발생 시 아래 레벨 순서로 복구를 시도한다. Level N 실패 시 Level N+1로 에스컬레이션.

| 레벨 | 이름 | 조건 | 처리 |
|------|------|------|------|
| **Level 0** | 자동 재시도 | transient failure (네트워크, 타임아웃 등 일시적 오류) | 동일 작업 1회 자동 재시도 |
| **Level 1** | 작업 분해 | scope 과대 (story/JIT story 범위가 너무 큼) | plan -a에 더 작은 단위로 분해 요청 후 재시도 |
| **Level 2** | 스킵 + blocked | 외부 의존성 미해소 | 현재 작업 단위를 `blocked` 상태로 마킹하고 다음 단위로 이동 |
| **Level 3** | 비상 스티어링 | Level 0~2로 해결 불가 또는 자동 중단 트리거 발동 | 사용자 개입 요청 → Step 3 강제 진입 |

복구 절차:
1. 실패 감지 → 실패 유형 분류 (transient / scope / external / unknown)
2. 해당 Level 복구 시도
3. 복구 성공 시: 결과 기록 후 루프 재진입
4. 복구 실패 시: 다음 Level로 에스컬레이션

### Drift 감지

**정의**: 스프린트 결과물이 objective.md의 목표 항목과 **관련성**이 없는 경우.

**감지 시점**: 매 스프린트 완료(2.2-E.3 또는 2.2-S.4 결과 기록) 직후 수행.

> **Agile config fallback (MANDATORY)**: drift_threshold, drift_count_trigger, no_diff_count_trigger는 `config.resolved.json`의 `agile.{key}` 값을 우선 사용하고, 없으면 기본값(80, 2, 2)을 사용한다.

**감지 절차**:

1. 스프린트에서 변경된 파일 목록 추출 (`git diff --name-only`)
2. objective.md의 활성 Epic/Story/DoD 항목과 변경 파일의 관련성 및 **정합성** 확인
   - 관련 없는 변경이 80% 이상인 경우: **drift 경고**
3. drift 감지 시 아래 메시지 출력:
   ```
   [drift 감지] Sprint {N}
   - 변경 파일: {파일 목록}
   - 목표 단위: {WORK_ITEM_ID} — {WORK_ITEM_TITLE}
   - 관련성: 관련|무관
   - 판정: 정상|경고|비상
   ```
4. **연속 2회 이상** drift 경고 발생 시: 비상 스티어링 트리거 → Step 3 즉시 진입

### 자동 중단 트리거

아래 조건 중 하나 이상 충족 시 루프를 즉시 중단하고 비상 스티어링을 실행한다:

| 조건 | 기준 |
|------|------|
| **연속 실패** | 동일 작업 단위에 대해 **연속 2회 실패** (`consecutive_failures`) |
| **누적 실패율** | 전체 스프린트 중 실패율 **50%** 이상 (최소 4 스프린트 이후 적용) |
| **무의미 루프** | **diff 없음** **2회 연속** (plan 실행 후 변경 파일 없음, `no_diff_count`) |
| **비용 cap** | 누적 **비용**/토큰 사용량이 session.json의 `cost_cap` 값 초과 |

자동 중단 발생 시:

```
[자동 중단] AGI-{AGI_ID} — 중단 조건 충족: {REASON}
현재까지 결과: {DONE_ITEMS}/{TOTAL_ITEMS} 항목 완료
재개하려면: /mst:agile --resume {AGI_ID}
```

`python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status paused --json` 실행 후 종료.

### 비상 스티어링 트리거

정기 체크포인트 외에 아래 조건에서 **Step 3을 즉시 강제 트리거**한다:

| 트리거 조건 | 설명 |
|-------------|------|
| 연속 실패 2회 (자동 중단 이전) | 자동 중단 직전 사용자 개입 기회 제공 (`consecutive_failures`) |
| blocked story 누적 50% 이상 | 절반 이상의 story가 blocked 상태 |
| drift 감지 연속 2회 | 변경 파일과 objective 관련성 80% 미달 연속 (`drift_count`) |
| Level 3 복구 에스컬레이션 도달 | 4단계 복구 최상위 레벨 도달 |

비상 스티어링 진입 시:
1. `[비상 스티어링] 조건: {TRIGGER_REASON}` 출력 후 Step 3으로 진입
2. Step 3.2 진행 보고서 즉시 출력
3. `AskUserQuestion`으로 사용자 개입 요청:
   ```
   [비상 스티어링] 자동 진행이 중단되었습니다. 트리거: {TRIGGER_REASON}

   선택:
   1) 계속 진행 (해당 story blocked 처리 후 다음 story)
   2) objective 수정 (Step 3.4 방향 전환)
   3) 완전 중단
   ```
4. 사용자 응답에 따라 분기:
   - **계속 진행**: 해당 story `blocked` 처리 후 다음 story로 진행
   - **objective 수정**: Step 3.4 수행 후 루프 재진입
   - **완전 중단**: session을 `paused` 상태로 저장 후 종료

---

## 상태 전이 규칙 (CRITICAL)

### 유효 상태 전이

| 엔티티 | 유효 전이 |
|--------|----------|
| DoD (epic 모드) | `todo → proposed_done → done`, `proposed_done → todo`(reject) |
| Story | `todo → in_progress → done`, `todo → blocked → in_progress → done` |
| Session | `active → paused → completed`, `active → completed` |

**LLM은 objective.md를 절대 직접 편집하지 않습니다.**

모든 상태 변경은 아래 mst.py 스크립트 명령어로만 수행합니다:

| 작업 | 명령어 |
|------|--------|
| DoD/Story 상태 변경 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID_OR_STORY_ID} --status {todo\|proposed_done\|in_progress\|done\|blocked}` |
| 완료 여부 전체 확인 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json` |
| 세션 상태 업데이트 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status {active\|paused\|completed}` |
| 스프린트 결과 기록 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} ...` |

**이유**: LLM의 YAML/Markdown 파싱 오류 누적을 방지하고 상태 파일의 무결성을 보장한다. (DSC-044 critic 합의)

---

## Anti-Rationalization Checklist

- 합리화 패턴: "간단한 목표니 Step 1 절차를 생략해도 된다." | 확인 증거: Step 1에서 `Skill(skill: "mst:agile-plan", ...)` 호출 로그와 반환 마커가 존재.
- 합리화 패턴: "objective.md가 이미 있으니 직접 편집해도 된다." | 확인 증거: 상태 변경 시 항상 `mst.py agile objective-transition` 실행 로그 존재.
- 합리화 패턴: "Step 0 없이 바로 생성으로 진행해도 된다." | 확인 증거: `mst.py agile status`(resume) 또는 `mst:agile-plan`(신규) 실행 로그가 Step 0~1 흐름에 존재.
