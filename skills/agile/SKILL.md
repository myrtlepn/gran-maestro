---
name: agile
description: "프로젝트 목표를 제공하면 JTBD+프로젝트 DoD 기반 자율 실행을 수행합니다. Step 1은 agile-plan 서브스킬로 objective.md를 준비하고 Sprint 0 → Sprint N(프로젝트 건강 우선) 루프 → 스티어링 체크포인트를 반복합니다."
user-invocable: true
argument-hint: "{프로젝트 목표(JTBD+프로젝트 DoD 기반) 또는 --resume AGI-NNN | --doc 파일경로 | --steering-every N}"
---

# maestro:agile

**목적**: 프로젝트 목표를 받아 JTBD+프로젝트 DoD 기반 objective 흐름을 `agile-plan`으로 초기화하고, 프로젝트 건강 우선 스프린트 루프를 진행합니다.

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
- Step 2/3 루프는 단일 스프린트 모델로 반복 실행한다.

### 금지 패턴

- LLM이 objective.md를 직접 Write/Edit로 수정하는 행위.
- `mst.py agile objective-transition` / `objective-check` 우회.
- Step 0(세션 초기화) 없이 바로 objective 생성으로 진입.
- 스프린트 횟수/완료 시점을 예측·확정·암시하는 표현을 objective/plan 입력/중간 보고/스티어링 보고에 기재하는 행위.
- objective.md에 "예상 스프린트", "N회 스프린트", "X주 내 완료" 등 필드/문장을 추가하는 행위.
- `plan -a` 입력, 중간 보고, 스티어링 보고에서 잔여 스프린트 수/완료 예정 스프린트 표현을 전달·기재하는 행위.
- 캘린더 단위로 변환한 기간 추정(예: "4~8주 소요")을 기재하는 행위.
- 과거 실적을 현재 프로젝트의 완료 시점/스프린트 횟수 예측 근거로 인용하는 행위.
- 스프린트 진행 중/스프린트 완료 직후 `"계속 진행하시겠습니까?"`, `"계속할까요?"` 등 스프린트 간 확인 질문을 `AskUserQuestion`으로 삽입하는 행위.
- 루프가 남아 있는데 `"마무리"`, `"별도 세션"`, `"나머지는"` 등 루프 종료/이관을 암시하는 표현을 중간 보고/스티어링 보고/자유 텍스트에 기재하는 행위.
- 허용 표현: DoD 진행률(%), 완료/미완료 항목 수, 스티어링 방향 추천, 종료 후 총 스프린트 수 사후 집계.

### AskUserQuestion 허용 지점 (Whitelist)

- 허용 지점 1: Step 3.3 DoD 제안 approve/reject 확인
  - 필수 마커: `[스티어링 체크포인트]`
- 허용 지점 2: Step 3 비상 스티어링 강제 진입 후 사용자 개입 요청
  - 필수 마커: `[비상 스티어링]`
- 허용 지점 3: Step 2.1 Sprint 0 smoke test 실패 후 재시도/중단 확인
  - 필수 마커: `[Sprint 0]`
- 허용 지점 4: Step 2.2.5 소스 검증 3회 실패 초과 시 사용자 에스컬레이션
  - 필수 마커: `[자동 중단]`
- 허용 지점 5: Step 3.5 변경 후 정합성 정책 레벨 확인
  - 필수 마커: `[스티어링 체크포인트]`

동기화 규칙:
- 위 허용 지점/마커 목록을 변경하면 `hooks/mst-stop-hook.sh`의 agile AskUserQuestion 화이트리스트를 같은 PR에서 동시에 갱신한다.
- stop hook 화이트리스트에 없는 마커가 포함된 AskUserQuestion은 스프린트 루프에서 허용되지 않는다.

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
2. session.json 로드 성공 시: `AGI_ID`, `CURRENT_SPRINT`, `STEERING_EVERY`를 메모리에 보관
3. 아래 workflow state를 활성화한다 (non-blocking):
```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --auto true \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```
4. 세션 상태 출력: `[재개] AGI-{NNN} — 스프린트 {N} 상태: {status}`
5. Step 1 건너뜀 → 스프린트 루프(2.2)로 진행
6. session.json 로드 실패 또는 AGI-NNN 미존재 시:
  - 에러 메시지 출력: `[오류] AGI-{NNN} 세션을 찾을 수 없습니다.`
  - 복구 안내: `.gran-maestro/agile/` 디렉토리 확인 방법 안내 후 중단

#### 0.3 분기: 신규 세션 (--resume 없는 경우)

1. 신규 세션 생성과 objective 초기화는 Step 1의 `agile-plan` 서브스킬에서 수행한다.
2. Step 1 호출을 위해 사용자 입력 목표(`PROJECT_GOAL`)와 선택 플래그(`DOC_PATH`, `STEERING_EVERY`)를 메모리에 보관한다.
3. `[신규 세션 준비] agile-plan 위임 예정 (steering-every: {STEERING_EVERY})` 출력
```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --auto true \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```
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

#### 2.0 상태 복원

세션 초기화(Step 0) 또는 Step 1 복귀 결과로 `CURRENT_SPRINT`, `STEERING_EVERY`를 복원한다.

- `--resume AGI-NNN` 진입:
  - session.json에서 `current_sprint`를 복원한다.
  - session.json 손상 또는 `current_sprint` 필드 누락 시:
    - `[오류] AGI-{AGI_ID} session.json 손상 — current_sprint 값을 읽을 수 없습니다.` 출력
    - 복구 안내: `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/session.json`을 직접 점검하거나 삭제 후 신규 세션으로 재시작
    - 실행 중단
- 신규 세션(Step 1에서 복귀):
  - `agile-plan` 생성 결과의 `AGI_ID`를 사용한다.
  - `CURRENT_SPRINT=0`으로 시작한다.

분기:
- `CURRENT_SPRINT == 0` 또는 Sprint 0 미완료 → **2.1 (Sprint 0)** 으로 진행
- `CURRENT_SPRINT >= 1` 및 Sprint 0 완료 → **2.2 (Sprint N 루프)** 로 진행

---

#### 2.1 Sprint 0: 테스트 환경 구축

**목표**: 프로젝트의 테스트 러너/프레임워크를 감지하고, smoke test 1개 이상이 통과한 것을 확인한 후 Sprint 1로 진입한다.

##### 2.1.0 Sprint 0 시작 기록 (MANDATORY)

Sprint 0 진입 즉시 `in_progress` 상태의 result를 기록하여 대시보드 타임라인에 표시한다:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint 0 \
  --status in_progress \
  --summary "테스트 환경 구축 중" \
  --json
```

##### 2.1.1 테스트 러너 감지

아래 파일을 순서대로 확인하여 테스트 러너를 감지한다:

1. `package.json` — `scripts.test` 필드 확인 (jest, vitest, mocha 등)
2. `Makefile` — `test` 타깃 확인
3. `pyproject.toml` / `setup.cfg` / `pytest.ini` — pytest 감지
4. `Cargo.toml` — `cargo test` (Rust)
5. `go.mod` — `go test ./...` (Go)
6. `.github/workflows/` — CI 설정에서 테스트 명령어 추출

감지 결과를 `TEST_RUNNER` 변수에 저장하고 출력:

```text
[Sprint 0] 테스트 러너 감지: {TEST_RUNNER}
```

##### 2.1.2 테스트 환경 미존재 시

테스트 러너 감지 실패 시:

1. `[Sprint 0] 테스트 환경 없음 — 기본 환경 구축 시작` 출력
2. 아래 서브스킬 호출로 기본 테스트 환경 자동 구축:

```text
Skill(skill: "mst:plan", args: "-a 프로젝트에 최소한의 smoke test 1개를 포함한 테스트 환경을 구축한다. 테스트 러너를 선택하고 설정 파일을 작성하며, 항상 통과하는 smoke test 1개를 작성한다.")
```

3. 완료 후 2.1.1로 재시도 (최대 1회). 재시도 실패 시 사용자 안내 후 중단.

##### 2.1.3 Smoke Test 실행 및 Sprint 1 진입 조건

1. 감지된 `TEST_RUNNER`로 smoke test 실행하여 **최소 1개 테스트 통과** 확인
2. 통과 시:
  - `[Sprint 0] smoke test 통과 — Sprint 1 진입 조건 충족` 출력
  - Sprint 0 결과 기록 (완료):
    ```bash
    python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
      --sprint 0 \
      --status done \
      --planned "테스트 환경 구축" \
      --completed "테스트 환경 구축" \
      --pln {PLN_ID_IF_EXISTS} \
      --req {REQ_ID_IF_EXISTS} \
      --summary "smoke test 통과" \
      --json
    ```
    - `PLN_ID_IF_EXISTS` / `REQ_ID_IF_EXISTS`: Sprint 0에서 `mst:plan`을 호출하여 PLN/REQ가 생성된 경우에만 전달. 테스트 환경이 이미 존재하여 plan 호출 없이 통과한 경우 `--pln`/`--req` 인자를 생략한다.
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --current-sprint 1 --json` 실행
  - `CURRENT_SPRINT=1` 설정 후 Sprint N 루프(2.2)로 진입
3. 실패 시:
  - `[Sprint 0] smoke test 실패 — 원인 분석 후 수동 확인 필요` 출력 + 실패 로그 요약
  - `AskUserQuestion`으로 사용자에게 확인 요청 후 재시도 또는 중단

---

#### 2.2 Sprint N 루프 (프로젝트 건강 우선)

**목표**: 매 Sprint 시작 시 프로젝트 건강을 먼저 점검하고, 문제를 우선 해결한 뒤 프로젝트 DoD를 MoSCoW+의존성 기반으로 진행한다.

스프린트 시작 시 아래 체크포인트 마커를 반드시 출력한다:
`[LOOP {CURRENT_SPRINT}] DOD 진행: {done}/{total} | 잔여: {remaining}`

반복 시작 전 매번 공통 게이트를 아래 순서로 수행한다:

```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active true \
  --active true \
  --skill mst:agile \
  --auto true \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```

##### 2.2.0.5 Accept Preflight 검증 (이전 Sprint REQ 완료 확인)

`state set-workflow` 직후, `objective-check` 호출 전에 직전 Sprint REQ의 accept 완료 여부를 선검증한다.

1. `CURRENT_SPRINT == 1`이면 Sprint 0은 smoke test이므로 preflight를 skip하고 objective-check로 진행한다.
2. `CURRENT_SPRINT > 1`이면 직전 Sprint 결과에서 REQ ID를 추출한다.
```bash
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT-1}/result.json)
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT-1}/result.md)
```
- 결과에서 `REQ-<숫자>` 패턴이 없으면(예: 건강 이슈 수정 Sprint) preflight를 skip하고 objective-check로 진행한다.
3. `Read({PROJECT_ROOT}/.gran-maestro/requests/{PREV_REQ_ID}/request.json)` 후 `status`를 확인한다.
- `status`가 `done`, `completed`, `accepted` 중 하나이면 정상 완료로 간주하고 preflight를 skip한다.
- 그 외(`phase2_execution`, `phase3_review`, `spec_ready` 등)는 미완료로 간주한다.
4. 미완료로 판정되면 브랜치 존재 여부를 교차 검증한다.
```bash
git show-ref --verify --quiet refs/heads/gran-maestro/{PREV_REQ_ID}
```
- 브랜치가 존재하면 accept 미실행으로 확정한다.
5. accept를 선행 실행한다.
```text
Skill(skill: "mst:accept", args: "{PREV_REQ_ID}")
```
6. accept 실행 결과를 확인한다.
- 성공 조건:
  - `request.json.status`가 `done`, `completed`, `accepted` 중 하나
  - `refs/heads/gran-maestro/{PREV_REQ_ID}` 및 `refs/heads/gran-maestro/{PREV_REQ_ID}-T*`가 정리됨
- 실패 조건:
  - 위 성공 조건을 만족하지 못하면 `[비상 스티어링]` 마커로 사용자 개입을 요청하고 Sprint 진행을 중단한다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json
```

- `all_done: true`이면 루프를 종료하고 2.3으로 이동한다.
- `all_done: false`이면 Sprint를 계속 진행한다.
- `CURRENT_SPRINT > 0` 이고 `CURRENT_SPRINT % STEERING_EVERY == 0`이면 Step 3(스티어링 체크포인트) 수행 후 이 루프로 복귀한다.

##### 2.2.1 프로젝트 건강 점검 (Sprint 시작 시 MANDATORY)

Sprint 시작 즉시 `in_progress` 결과를 기록한 뒤 건강 점검을 수행한다.

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status in_progress \
  --summary "프로젝트 건강 점검 중" \
  --json
```

점검 항목:
1. 테스트 실행 (`npm test` 등 프로젝트 표준 명령)
2. 빌드/타입체크 확인
3. known issues 조회
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues list {AGI_ID} --status open --json
```
4. 직전 Sprint 회고의 미해결 항목(`failed`, `limitations`) 확인
```bash
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md)
```

판정:
- 실패 테스트/빌드, open known issues, 미해결 회고 항목 중 하나라도 있으면 `HEALTH_ISSUE_FOUND=true`로 두고 **수정 작업을 DoD 진행보다 우선**한다.
- 모두 정상인 경우 `HEALTH_ISSUE_FOUND=false`로 두고 2.2.2로 진행한다.

##### 2.2.2 DoD 항목 선택 (MoSCoW + 의존성 기반)

`HEALTH_ISSUE_FOUND=false`일 때만 DoD 선택을 수행한다.

선택 규칙:
1. objective.md의 프로젝트 DoD에서 미완료 항목 조회 (`objective-check --json`)
2. MoSCoW `must` 우선, 없으면 `should`, 그다음 `could`
3. 의존성이 충족된 항목만 후보(`deps`가 모두 `done`)
4. 직전 회고 `direction`을 반영하여 우선순위 미세 조정

결정:
- 건강 이슈가 있으면 `SELECTED_WORK_ITEM={FIX_TARGET}`으로 확정한다.
- 건강 이슈가 없으면 `SELECTED_WORK_ITEM={SELECTED_DOD}`로 확정한다.
- 의존성 미충족으로 선택 불가하면 의존성 해소 작업을 생성하고 `SELECTED_WORK_ITEM={FIX_TARGET}`으로 전환한다.

##### 2.2.3 plan -a 호출 (3계층 컨텍스트)

`mst:plan -a` 호출 시 아래 컨텍스트를 반드시 전달한다.

- `[고정층]`: objective.md 전체 (JTBD + 프로젝트 DoD + 제약 + 설계 결정 + NFR + 리스크)
- `[활성층]`: 현재 선택된 미완료 DoD 항목
- `[변화층]`: 직전 Sprint 결과
- `[회고층]`: 직전 retrospective
- `[이슈층]`: open known issues
- `[제약층]`: 프로젝트 DoD + 성공 지표

```text
Skill(skill: "mst:plan", args: "-a {SELECTED_WORK_ITEM}
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 현재 대상: {SELECTED_WORK_ITEM} | 미완료 DoD: {INCOMPLETE_DOD_LIST}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md
[회고층] 직전 회고: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md
[이슈층] open known issues: {OPEN_ISSUE_LIST}
[제약층] 프로젝트 DoD: {PROJECT_DOD_LIST_LITERAL} | 성공 지표: {SUCCESS_METRICS_LITERAL}")
```

규칙:
- `plan -a` 입력에 완료 시점/잔여 횟수 예측 문구를 포함하지 않는다.
- 스프린트 목표는 작업 항목 명사가 아니라 **관찰 가능한 결과/동작**으로 작성한다.
  - 예: `"설정 탭 추가"` 대신 `"설정 페이지에서 포트 변경 후 저장 시 서버 재시작 없이 반영됨"` 형태로 작성한다.
- 컨텍스트가 비어 있으면 `"N/A"`로 채워 graceful fallback 한다.

##### 2.2.4 Sprint 결과 기록 + DoD 갱신 제안

Sprint 실행 결과를 기록하고, 이번 Sprint에서 완료 근거가 확보된 DoD에 대해 갱신 제안을 남긴다.

1. Sprint 결과 기록:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{SELECTED_WORK_ITEM}" \
  --completed "{COMPLETED_ITEM_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --sprint-goals '{SPRINT_GOALS_JSON_IF_AVAILABLE}' \
  --json
```
  - `--sprint-goals`는 **optional**이다. sprint_goals를 구성할 수 없는 경우 인자를 생략하고 기존 방식으로 기록한다.
  - `SPRINT_GOALS_JSON_IF_AVAILABLE` 구조:
    ```json
    [
      {
        "goal": "목표 텍스트",
        "status": "achieved|not_achieved|partial",
        "change_summary": "체감 변화 설명",
        "evidence": {
          "screenshots": ["path"],
          "test_results": {
            "passed": 0,
            "failed": 0,
            "summary": "text"
          },
          "diff": {
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "commits": ["hash"]
          }
        }
      }
    ]
    ```
  - `evidence` 및 하위 필드(`screenshots`, `test_results`, `diff`)는 모두 선택적으로 포함한다. 수집 가능한 데이터만 채운다.
2. 회고 기록:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile retrospective {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --succeeded "{SUCCEEDED_ITEMS}" \
  --failed '{"item":"{ITEM_ID}","cause":"{CAUSE}","attempt":"{ATTEMPT}"}' \
  --velocity-planned {VELOCITY_PLANNED} \
  --velocity-completed {VELOCITY_COMPLETED} \
  --limitations "{LIMITATIONS}" \
  --lessons "{LESSONS_LEARNED}" \
  --direction "{NEXT_DIRECTION}" \
  --json
```
3. known issue 자동 해소 체크:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues list {AGI_ID} --status open --json
python3 {PLUGIN_ROOT}/scripts/mst.py agile known-issues resolve {AGI_ID} --issue-id {KI_ID} --json
```
4. DoD 갱신 제안 생성:
  - `{dod_id, suggested_status, evidence_ref, reason}` 형태로 구성
  - `evidence_ref`는 `result.md`, 테스트/빌드 로그, `source-verify.md` 경로를 포함한다.
  - authoritative 상태 확정(`done`)은 Step 3 승인 절차(3.3)에서만 수행한다.

##### 2.2.5 외부 에이전트 소스 검증 (Sprint 완료 후 MANDATORY)

Sprint 완료 직후 `explore`(또는 동등한 코드베이스 탐색)를 실행해 소스를 검증한다.

기본 호출:
```text
Skill(skill: "mst:explore", args: "-a [Source Verification]
AGI: {AGI_ID} / Sprint: {CURRENT_SPRINT}
검증 대상:
1) 이번 Sprint 변경 파일 + 영향 범위
2) 변경 내용이 SELECTED_WORK_ITEM과 일치하는지
3) 테스트/빌드 결과와 코드 변경 정합성
4) 누락된 회귀 위험/사이드이펙트
출력 형식:
- findings: [{severity: CRITICAL|MAJOR|MINOR, title, evidence_ref, fix_hint}]
- verdict: pass|fail")
```

fallback: `mst:explore` 사용 불가 시 `mst:codex` 또는 `mst:claude`를 동일 템플릿으로 호출한다.

검증 루프:
1. 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT}/source-verify.md`에 기록한다.
2. `verdict=fail` 또는 `CRITICAL|MAJOR` 발견 시:
  - 검증 실패로 간주한다.
  - 자동 수정 태스크를 생성해 즉시 보완 작업을 수행한다.
  - 보완 후 테스트/빌드를 재실행하고 다시 소스 검증을 수행한다.
3. 최대 재시도는 **3회**다. 3회 초과 시 `AskUserQuestion`으로 사용자 에스컬레이션 후 지시를 따른다.
4. `pass` 또는 `MINOR`만 남으면:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```
5. `CONTINUATION GUARD`:
  - 위 update 호출 직후 `CURRENT_SPRINT = CURRENT_SPRINT + 1`로 갱신한다.
  - 즉시 다음 DoD의 구현을 시작하라: 루프 상단으로 복귀해 다음 Sprint를 연속 실행한다.

---

#### 2.3 루프 종료 및 최종 보고서

**종료 조건**: `mst.py agile objective-check {AGI_ID} --json` 결과에서 `all_done: true` 반환.

최종 보고서를 출력한다:

```text
========================================
[완료] AGI-{AGI_ID} 자율 스프린트 루프 종료
========================================

총 스프린트 수: {TOTAL_SPRINTS}
완료된 DoD 수: {DONE_DOD} / {TOTAL_DOD}
생성된 PLN 목록: {PLN_IDS}
생성된 REQ 목록: {REQ_IDS}

스프린트 결과 요약:
- 성공: {SUCCESS_COUNT}회
- 실패: {FAIL_COUNT}회

결과 디렉토리: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/
목표 달성 여부: {JTBD_SUCCESS_SUMMARY}
========================================
```

```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active false \
  --active false \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
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

#### 3.2 진행 보고서 출력

아래 형식으로 **진행 보고서**를 출력한다:

```text
========================================
[스티어링 체크포인트] AGI-{AGI_ID} — Sprint {CURRENT_SPRINT}
========================================

목표 진행률
- metric 달성률: {METRICS_PROGRESS} (성공 지표 기준)
- 프로젝트 DoD 진행률: {DOD_DONE}/{DOD_TOTAL} 완료

최근 {STEERING_EVERY} 스프린트 요약
| 스프린트 | 계획 | 완료 | 미완료 | 블로커 |
|----------|------|------|--------|--------|
| S{N}     | ...  | ...  | ...    | ...    |

회고 요약 (최근 {STEERING_EVERY} 스프린트)
- lessons learned: {RETRO_LESSONS_SUMMARY}
- limitations 추이: {RETRO_LIMITATIONS_TREND}
- known issues: open {KNOWN_ISSUES_OPEN_COUNT} / resolved {KNOWN_ISSUES_RESOLVED_COUNT}

소스 검증 요약
- pass: {VERIFY_PASS_COUNT}
- fail: {VERIFY_FAIL_COUNT}
- 주요 이슈: {VERIFY_TOP_FINDINGS}

DoD 체크 갱신 제안 (pending)
| DOD-ID | 제안 상태 | evidence_ref | 근거 요약 |
|--------|-----------|--------------|-----------|
| DOD-... | proposed_done | .../sprints/S{N}/source-verify.md | ... |

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
- **approve된 DoD**:
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status done --json`
  - authoritative 상태를 `done`으로 확정
- **reject된 DoD**:
  - `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status todo --json`
  - reject 사유 + `evidence_ref`를 Sprint 메모에 기록
  - 다음 Sprint의 2.2.1 문제 우선 해결 대상으로 큐잉

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
| **Level B** (중간) | DoD 범위 조정, 우선순위 재조정 | 영향받는 DoD만 부분 재검증 후 루프 계속 |
| **Level C** (중대) | JTBD 목표 변경, DoD 대규모 재정의 | 영향 DoD 재계산, 필요 시 부분 롤백 task 생성 |

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
| **Level 1** | 작업 분해 | scope 과대 (DoD 작업 범위가 너무 큼) | plan -a에 더 작은 단위로 분해 요청 후 재시도 |
| **Level 2** | 스킵 + blocked | 외부 의존성 미해소 | 현재 작업 단위를 `blocked` 상태로 마킹하고 다음 단위로 이동 |
| **Level 3** | 비상 스티어링 | Level 0~2로 해결 불가 또는 자동 중단 트리거 발동 | 사용자 개입 요청 → Step 3 강제 진입 |

복구 절차:
1. 실패 감지 → 실패 유형 분류 (transient / scope / external / unknown)
2. 해당 Level 복구 시도
3. 복구 성공 시: 결과 기록 후 루프 재진입
4. 복구 실패 시: 다음 Level로 에스컬레이션

### Drift 감지

**정의**: 스프린트 결과물이 objective.md의 활성 DoD 항목과 **관련성**이 없는 경우.

**감지 시점**: 매 스프린트 완료(2.2.5 소스 검증 통과 직후) 수행.

> **Agile config fallback (MANDATORY)**: drift_threshold, drift_count_trigger, no_diff_count_trigger는 `config.resolved.json`의 `agile.{key}` 값을 우선 사용하고, 없으면 기본값(80, 2, 2)을 사용한다.

**감지 절차**:

1. 스프린트에서 변경된 파일 목록 추출 (`git diff --name-only`)
2. objective.md의 활성 DoD 항목과 변경 파일의 관련성 확인
  - 관련 없는 변경이 80% 이상인 경우: **drift 경고**
3. **형태 정합성 검증** (관련성 체크 직후, MANDATORY):
  - objective.md의 프로젝트 DoD 항목에서 이번 작업의 기대 산출물 유형(`DELIVERABLE_SHAPE_EXPECTED`)을 추출한다.
  - 변경된 파일의 구조/형태(`DELIVERABLE_SHAPE_OBSERVED`)가 기대 유형과 부합하는지 LLM 판단으로 검증한다.
  - 미부합 시 drift 경고 태그에 `[형태 불일치]`를 추가한다.
  - 프로젝트 DoD 또는 산출물 유형 정보가 없으면 형태 정합성 검증은 skip하고 관련성 판정만으로 계속 진행한다 (graceful fallback).
4. drift 감지 시 아래 메시지 출력:
```text
[drift 감지] Sprint {N}
- 변경 파일: {파일 목록}
- 목표 단위: {WORK_ITEM_ID} — {WORK_ITEM_TITLE}
- 관련성: 관련|무관
- 형태 정합성: 부합|미부합|정보부족
- 태그: [형태 불일치]|(없음)
- 판정: 정상|경고|비상
```
5. **연속 2회 이상** drift 경고 발생 시: 비상 스티어링 트리거 → Step 3 즉시 진입

### 자동 중단 트리거

아래 조건 중 하나 이상 충족 시 루프를 즉시 중단하고 비상 스티어링을 실행한다:

| 조건 | 기준 |
|------|------|
| **연속 실패** | 동일 작업 단위에 대해 **연속 2회 실패** (`consecutive_failures`) |
| **누적 실패율** | 전체 스프린트 중 실패율 **50%** 이상 (최소 4 스프린트 이후 적용) |
| **무의미 루프** | **diff 없음** **2회 연속** (plan 실행 후 변경 파일 없음, `no_diff_count`) |
| **비용 cap** | 누적 **비용**/토큰 사용량이 session.json의 `cost_cap` 값 초과 |

자동 중단 발생 시:

```text
[자동 중단] AGI-{AGI_ID} — 중단 조건 충족: {REASON}
현재까지 결과: {DONE_ITEMS}/{TOTAL_ITEMS} 항목 완료
재개하려면: /mst:agile --resume {AGI_ID}
```

```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --agile-loop-active false \
  --active false \
|| echo "[mst:agile] warning: failed to update workflow state" >&2
```

`python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status paused --json` 실행 후 종료.

### 비상 스티어링 트리거

정기 체크포인트 외에 아래 조건에서 **Step 3을 즉시 강제 트리거**한다:

| 트리거 조건 | 설명 |
|-------------|------|
| 연속 실패 2회 (자동 중단 이전) | 자동 중단 직전 사용자 개입 기회 제공 (`consecutive_failures`) |
| blocked DoD 누적 50% 이상 | 절반 이상의 DoD가 blocked 상태 |
| drift 감지 연속 2회 | 변경 파일과 objective 관련성 80% 미달 연속 (`drift_count`) |
| Level 3 복구 에스컬레이션 도달 | 4단계 복구 최상위 레벨 도달 |

비상 스티어링 진입 시:
1. `[비상 스티어링] 조건: {TRIGGER_REASON}` 출력 후 Step 3으로 진입
2. Step 3.2 진행 보고서 즉시 출력
3. `AskUserQuestion`으로 사용자 개입 요청:
```text
[비상 스티어링] 자동 진행이 중단되었습니다. 트리거: {TRIGGER_REASON}

선택:
1) 계속 진행 (해당 DoD blocked 처리 후 다음 DoD)
2) objective 수정 (Step 3.4 방향 전환)
3) 완전 중단
```
4. 사용자 응답에 따라 분기:
  - **계속 진행**: 해당 DoD `blocked` 처리 후 다음 DoD로 진행
  - **objective 수정**: Step 3.4 수행 후 루프 재진입
  - **완전 중단**: session을 `paused` 상태로 저장 후 종료

---

## 상태 전이 규칙 (CRITICAL)

### 유효 상태 전이

| 엔티티 | 유효 전이 |
|--------|----------|
| DoD | `todo → proposed_done → done`, `proposed_done → todo`(reject), `todo → blocked → todo|proposed_done` |
| Session | `active → paused → completed`, `active → completed` |

**LLM은 objective.md를 절대 직접 편집하지 않습니다.**

모든 상태 변경은 아래 mst.py 스크립트 명령어로만 수행합니다:

| 작업 | 명령어 |
|------|--------|
| DoD 상태 변경 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} --story {DOD_ID} --status {todo\|proposed_done\|in_progress\|done\|blocked}` |
| 완료 여부 전체 확인 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-check {AGI_ID} --json` |
| 세션 상태 업데이트 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} --status {active\|paused\|completed}` |
| 스프린트 결과 기록 | `python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} --sprint {N} ...` |

**이유**: LLM의 YAML/Markdown 파싱 오류 누적을 방지하고 상태 파일의 무결성을 보장한다. (DSC-044 critic 합의)

---

## Anti-Rationalization Checklist

- 합리화 패턴: "간단한 목표니 Step 1 절차를 생략해도 된다." | 확인 증거: Step 1에서 `Skill(skill: "mst:agile-plan", ...)` 호출 로그와 반환 마커가 존재.
- 합리화 패턴: "objective.md가 이미 있으니 직접 편집해도 된다." | 확인 증거: 상태 변경 시 항상 `mst.py agile objective-transition` 실행 로그 존재.
- 합리화 패턴: "Step 0 없이 바로 생성으로 진행해도 된다." | 확인 증거: `mst.py agile status`(resume) 또는 `mst:agile-plan`(신규) 실행 로그가 Step 0~1 흐름에 존재.
- 합리화 패턴: "대략 N 스프린트면 되니 계획/보고에 넣어도 된다." | 확인 증거: objective.md, plan 입력, 중간/스티어링 보고 산출물 전체에서 스프린트 횟수 예측 문구 0건.
- 합리화 패턴: "횟수가 아니라 규모/기간 추정이므로 허용된다." | 확인 증거: 캘린더 변환/반복 횟수 암시 표현이 산출물 전체에서 0건.
