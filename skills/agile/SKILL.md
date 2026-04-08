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
- `AUTO_MODE=true`이거나 `STEERING_DISABLED=true(STEERING_EVERY=0)`인 스프린트 루프에서 텍스트 출력으로 `"계속할까요?"`, `"진행할까요?"`, `"멈추고"` 등 질문을 생성하는 행위.
- `"컨텍스트가 길어지고 있으므로"`, `"요약하고 계속"`, `"정리하고 계속"`, `"컨텍스트를 줄이기 위해"` 등 컨텍스트 길이/요약/정리를 사유로 스프린트 간 정지하는 행위.
- `AUTO_MODE=true`이거나 `STEERING_DISABLED=true(STEERING_EVERY=0)`에서 스프린트 완료 후 `"다음 Sprint로 진행합니다"`라고 선언한 뒤 확인 질문을 삽입하는 행위.
- 스프린트 루프 중 어떤 자체 판단 사유(컨텍스트 길이, 세션 정리, 토큰 절약 등)로든 자발적으로 정지하는 행위.
- 루프가 남아 있는데 `"마무리"`, `"별도 세션"`, `"나머지는"` 등 루프 종료/이관을 암시하는 표현을 중간 보고/스티어링 보고/자유 텍스트에 기재하는 행위.
- 정기 스티어링 해당 Sprint에서 Step 3을 건너뛰고 Step 2를 계속 진행하는 행위.
- 정기 스티어링 미해당 Sprint에서 자의적으로 `"계속할까요?"`, `"멈출까요?"` 질문을 삽입하는 행위.
- 2.2.0.7 누적 통합 리뷰의 `verdict.force_wire_recommended=true`를 **사유 기록 없이** 무시하는 행위 (Escape Hatch는 반드시 `auto-decisions.md` 또는 `retrospective.md`에 사유를 남길 때만 허용).
- 2.2.0.7 Escape Hatch를 동일 세션에서 **연속 2회 이상** 사용하는 행위 (통합 부채 누적 위장).
- 2.2.4 Sprint 종류 자기선언을 누락(`sprint_kind` 미지정)하거나 `foundational`로 선언하면서 `--foundational-reason`을 생략하는 행위.
- `foundational` Sprint를 `config.agile.foundational_streak_max` 초과로 연속 선언하는 행위 (Sprint 0 제외).
- `foundational` Sprint에서 DoD를 곧바로 `done`으로 승격하는 행위 (반드시 `proposed_done`으로만 기록하고, 후속 `user_observable` Sprint에서 `--deferred-promote`로만 승격).
- 2.2.0.8 alignment 판정 `objective_stale`에서 비상 스티어링 진입 없이 Sprint를 계속 진행하는 행위.
- 허용 표현: DoD 진행률(%), 완료/미완료 항목 수, 스티어링 방향 추천, 종료 후 총 스프린트 수 사후 집계, `proposed_done` 대기 DoD 수, 분류별 변경 파일 비율, alignment 판정 분포.

### AskUserQuestion 허용 지점 (Whitelist)

- 허용 지점 1: Step 3.3 DoD 제안 approve/reject 확인
  - 필수 마커: `[스티어링 체크포인트]`
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 PM이 증거 기반으로 approve/reject를 자율 판단한다.
- 허용 지점 2: Step 3 비상 스티어링 강제 진입 후 사용자 개입 요청
  - 필수 마커: `[비상 스티어링]`
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 PM이 계속 진행/방향 수정/중단을 자율 판단한다.
- 허용 지점 3: Step 2.1 Sprint 0 smoke test 실패 후 재시도/중단 확인
  - 필수 마커: `[Sprint 0]`
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 PM이 재시도/중단을 자율 판단한다.
- 허용 지점 4: Step 2.2.6 소스 검증 3회 실패 초과 시 사용자 에스컬레이션
  - 필수 마커: `[자동 중단]`
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 자동 중단 절차로 즉시 전환한다.
- 허용 지점 5: Step 3.5 변경 후 정합성 정책 레벨 확인
  - 필수 마커: `[스티어링 체크포인트]`
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 PM이 정합성 정책 레벨을 자율 판단한다.

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
| `-a`, `--auto` | 자율 모드 활성화 | `-a`, `--auto` |
| `--resume AGI-NNN` | 기존 세션 재개 | `--resume AGI-001` |
| `--doc 파일경로` | 기존 문서 지정 (파싱 모드) | `--doc docs/goals.md` |
| `--steering-every N` | 스티어링 체크포인트 간격 (기본값: 3) | `--steering-every 5` |

- `-a` 또는 `--auto`가 args 어디에든 포함되면 `AUTO_MODE=true`, 없으면 `AUTO_MODE=false`.
- `AUTO_MODE=false`인 경우 config fallback을 적용한다:
  1. `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`에서 `auto_mode.agile` 확인
  2. 키가 없으면 `Read(templates/defaults/config.json)`에서 `auto_mode.agile` 확인
  3. `auto_mode.agile == true`면 `AUTO_MODE=true`, 아니면 `false`
- 우선순위: CLI 플래그(`-a`/`--auto`)가 config보다 우선한다.
- `--steering-every` 미지정 시: `Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json)`의 `agile.steering_every` 값을 사용한다. config에도 없으면 기본값 `3`.
- `STEERING_DISABLED`는 `STEERING_EVERY == 0`이면 `true`, 아니면 `false`로 계산한다.

#### 0.2 분기: --resume 있는 경우

1. `python3 {PLUGIN_ROOT}/scripts/mst.py agile status AGI-NNN --json` 실행
2. session.json 로드 성공 시: `AGI_ID`, `CURRENT_SPRINT`, `STEERING_EVERY`를 메모리에 보관
3. 아래 workflow state를 활성화한다 (non-blocking):
```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:agile \
  --auto {AUTO_MODE} \
  --steering-disabled {STEERING_DISABLED} \
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
  --auto {AUTO_MODE} \
  --steering-disabled {STEERING_DISABLED} \
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
- `STEERING_DISABLED`는 기본값 `false`로 두고, `STEERING_EVERY == 0`이면 즉시 `true`로 해석한다.
- `EMERGENCY_STEERING_ENABLED`는 기본값 `true`로 두고, 세션/복귀 컨텍스트에 명시값이 있으면 해당 값을 우선한다.

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
  - `AUTO_MODE=true`이면 AskUserQuestion 없이 PM이 자율 판단으로 1회 재시도 후, 재실패 시 자동 중단 절차로 전환한다.
  - `AUTO_MODE=false`이면 `AskUserQuestion`으로 사용자에게 확인 요청 후 재시도 또는 중단한다.

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
  --auto {AUTO_MODE} \
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
6. `[CRITICAL][NO-SELF-MOTIVATED-PAUSE]` accept 반환 후 어떤 사유(컨텍스트 정리, 요약, 확인 질문, 토큰 절약 등)로든 정지를 **절대 금지**하고 즉시 아래 결과 확인 + objective-check를 실행한다. accept 실행 결과를 확인한다.
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
- 정기 스티어링은 `STEERING_DISABLED=true` 또는 `STEERING_EVERY == 0`이면 skip한다.
- `[CRITICAL][NO-AD-HOC-PAUSE]` 정기 스티어링 미해당 Sprint에서는 `"계속할까요?"`/`"멈출까요?"` 질문 없이 즉시 Step 2.2.1로 진행한다.
- `STEERING_EVERY > 0` 이고 `CURRENT_SPRINT > 0` 이고 `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0`이면 `[MANDATORY][STEERING-DUE]` Step 3(스티어링 체크포인트)를 수행 후 이 루프로 복귀한다.

##### 2.2.0.7 누적 통합 리뷰 (MANDATORY)

**목적**: 이번 Sprint가 "이전 산출물 위에 쌓는가, 아니면 옆에 격리된 단위 헬퍼를 또 만드는가"를 결정론 헬퍼로 선검증한다. slide-craft 재발(Sprint 추적상 DoD done 22/22인데 플러그인 미동작) 패턴을 선제 차단한다.

`CURRENT_SPRINT <= 1`이면 직전 Sprint 윈도우가 비어 있으므로 본 단계를 skip하고 2.2.0.8로 진행한다.

1. 결정론 헬퍼 호출:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile integration-review {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --depth 3 \
  --json
```

  - `--depth`는 `config.agile.integration_review_depth`(기본 3)를 사용한다. 인자 생략 시 헬퍼가 자동으로 config fallback을 적용한다.
  - `--threshold`도 생략 시 `config.agile.new_island_threshold`(기본 0.20)를 사용한다.

2. 헬퍼 출력 JSON에서 아래 필드를 확인한다.
   - `files.total / modify / wire / new_island`
   - `ratios.new_island`
   - `verdict.exceeded` (= `ratios.new_island > threshold`)
   - `verdict.force_wire_recommended`
   - `wire_streak.current / max / exceeded`
3. 헬퍼는 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/integration-context.md`를 자동 생성한다. 이 파일은 (1) 분류별 변경 파일 트리, (2) entrypoint 상태, (3) wire 파일별 통합 지점 참조, (4) 직전 K Sprint의 `user_observable_change` 요약을 포함하며, 2.2.3 plan -a 호출 시 `[누적층]` 컨텍스트에서 **반드시 Read 강제 대상**으로 전달한다.
4. 분기:
   - `verdict.exceeded=false`이면 일반 경로 — 2.2.0.8로 진행
   - `verdict.exceeded=true`이면 **강제 wire 전환**:
     - `SELECTED_WORK_ITEM`을 새 DoD 진행 대신 "이번 Sprint는 직전 누적 new-island(`new_island_files` 목록)를 기존 진입점과 통합하는 작업"으로 재지정한다.
     - 2.2.2 DoD 선택은 이 Sprint에서 skip하고, `selection_reason`에 `integration-review forced wire`를 기록한다.
     - `wire_streak.exceeded=true`(연속 `agile.integration_wire_streak_max`=3회 wire)이면 비상 스티어링(Step 3)으로 즉시 강제 진입한다 — 근본적으로 DoD 설계가 잘못됐을 가능성.

5. **PM Escape Hatch**: PM이 구조적 판단으로 verdict를 무시해야 하는 경우(예: 프로젝트 특성상 grep 휴리스틱이 false positive를 낸 경우, 동적 import/매크로 기반 언어 등) 아래 조건을 모두 만족할 때만 허용:
   - `AUTO_MODE=true`: `auto-decisions.md`에 `[integration-review override] reason: {...}` 행을 반드시 기록
   - `AUTO_MODE=false`: 다음 `retrospective.md`에 `integration_review_override` 섹션으로 사유 기록
   - Escape Hatch 사용 시 `verdict.force_wire_recommended`를 무시하고 기존 DoD 진행을 허용하되, 동일 세션에서 **연속 2회 이상 override 금지** (드리프트 누적 방지)
   - 사유 없이 무시하는 것은 금지 패턴(`### 금지 패턴` 참조)

##### 2.2.0.8 기획-구현 정합성 점검 (MANDATORY)

**목적**: 2.2.0.7가 "코드 통합 부채"를 잡는다면, 본 단계는 "**기획(objective.md) ↔ 구현(누적 변경)**의 정합성"을 점검한다. slide-craft 재발의 또 다른 축인 "DoD가 코드의 현실과 어긋나는 기획 노후화"를 감지한다.

`CURRENT_SPRINT <= 1`이면 직전 데이터가 없으므로 본 단계를 skip하고 2.2.1로 진행한다.

1. alignment 데이터 패키지 조회:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile alignment-package {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --depth 3 \
  --json
```

  - 반환: `{objective_dods[], integration_context_path, recent_results[], recent_retrospectives[]}`
  - objective.md가 없으면 `warning: "objective file missing"` 포함 → 본 단계를 graceful skip하고 2.2.1로 진행한다.

2. 패키지의 `integration_context_path`와 `recent_results`/`recent_retrospectives`를 Read한 뒤, PM이 3축으로 정합성을 판정한다:
   - **A. DoD-변경 매핑 충실도**: 직전 K Sprint의 변경 내용이 objective.md의 어떤 DoD를 충족시키는가? 상당수 변경이 어떤 DoD에도 매핑되지 않으면 `drift_warning` 후보
   - **B. DoD 현실 가능성**: objective.md의 DoD가 현재 코드 상태에서 "관찰 가능"하게 만들어지고 있는가? DoD가 "사용자가 X 화면에서 Y를 본다"인데 변경 파일에 X 화면이 없으면 `drift_warning` 후보
   - **C. 기획 노후화**: objective.md의 DoD/제약/우선순위가 현재 코드 현실과 모순되는가? 코드가 기획 가정 구조를 이미 떠났는데 objective.md가 안 갱신됐으면 `objective_stale` 후보

3. 판정 결과를 `{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/alignment-check.md`에 기록한다.

   ```markdown
   # Alignment Check — S{CURRENT_SPRINT}

   ## 판정: aligned | drift_warning | objective_stale

   ## A. DoD-변경 매핑 충실도
   (매핑된 DoD 목록 + 매핑되지 않은 변경 파일)

   ## B. DoD 현실 가능성
   (각 DoD별 "관찰 가능한가" 판단)

   ## C. 기획 노후화
   (기획이 현실을 반영하는가 + 노후화 증거)
   ```

4. 분기:
   - `aligned` — 일반 경로, 2.2.1로 진행
   - `drift_warning` — `drift_count += 1` (기존 Drift 감지 카운터와 공유). 경고 출력 + 2.2.1 진행. 단, `drift_count >= agile.drift_count_trigger`이면 기존 Drift 감지 규칙대로 비상 스티어링 진입
   - `objective_stale` — **비상 스티어링 강제 진입**(Step 3). 기획 자체가 코드와 어긋나므로 `mst:agile-plan --resume`으로 objective 재계획이 필요할 가능성 높음. 진행 보고서에 `alignment: objective_stale` 마커 포함

5. `AUTO_MODE=true`에서는 PM이 3축 판정과 분기를 자율적으로 수행하고, 판정 근거를 `alignment-check.md`에 기록한 뒤 해당 분기로 진행한다.

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
4. 직전 Sprint 회고의 미해결 항목(`failed`, `limitations`) 및 교훈(`lessons_learned`) 확인
```bash
Read({PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md)
```
  - `lessons_learned` 값을 `PREVIOUS_LESSONS` 변수에 저장한다. 이 값은 2.2.3 plan 컨텍스트 및 result 기록 시 사용한다.

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
- 의존성 미충족으로 선택 불가하면 아래 분기를 적용한다.
  - `AUTO_MODE=true`: AskUserQuestion 없이 의존성 해소 작업을 자동 생성하고 즉시 진행한다. `SELECTED_WORK_ITEM={FIX_TARGET}`으로 전환한다.
  - `AUTO_MODE=false`: 기존 동작을 유지한다. 의존성 해소 작업을 생성하고 `SELECTED_WORK_ITEM={FIX_TARGET}`으로 전환한다.

##### 2.2.3 plan -a 호출 (N계층 컨텍스트)

`mst:plan -a` 호출 시 아래 컨텍스트를 반드시 전달한다.

- `[고정층]`: objective.md 전체 (JTBD + 프로젝트 DoD + 제약 + 설계 결정 + NFR + 리스크)
- `[활성층]`: 현재 선택된 미완료 DoD 항목
- `[변화층]`: 직전 Sprint 결과
- `[회고층]`: 직전 retrospective
- `[이슈층]`: open known issues
- `[누적층]`: 직전 K Sprint의 누적 통합 컨텍스트 (2.2.0.7에서 생성한 `integration-context.md`). plan -a는 이 파일을 반드시 Read하여 "이전 산출물 위에 쌓을지 / 고칠지"를 판단한다.
- `[제약층]`: 프로젝트 DoD + 성공 지표

```text
Skill(skill: "mst:plan", args: "-a {SELECTED_WORK_ITEM}
[고정층] 목적 파일: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
[활성층] 현재 대상: {SELECTED_WORK_ITEM} | 미완료 DoD: {INCOMPLETE_DOD_LIST}
[변화층] 직전 결과: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/result.md
[회고층] 직전 회고: {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{N-1}/retrospective.md | 직전 교훈: {PREVIOUS_LESSONS}
[이슈층] open known issues: {OPEN_ISSUE_LIST}
[누적층] 통합 컨텍스트 파일(MANDATORY Read): {PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/sprints/S{CURRENT_SPRINT:02d}/integration-context.md — 직전 K Sprint 분류(modify/wire/new-island), entrypoint 상태, wire 파일별 통합 지점, user_observable_change 요약을 확인하고 이번 Sprint가 어디에 쌓을지 결정한다
[제약층] 프로젝트 DoD: {PROJECT_DOD_LIST_LITERAL} | 성공 지표: {SUCCESS_METRICS_LITERAL}")
```

규칙:
- `plan -a` 입력에 완료 시점/잔여 횟수 예측 문구를 포함하지 않는다.
- 스프린트 목표는 작업 항목 명사가 아니라 **관찰 가능한 결과/동작**으로 작성한다.
  - 예: `"설정 탭 추가"` 대신 `"설정 페이지에서 포트 변경 후 저장 시 서버 재시작 없이 반영됨"` 형태로 작성한다.
- 컨텍스트가 비어 있으면 `"N/A"`로 채워 graceful fallback 한다.

##### [추가 섹션] Sprint 중 디자인 수정 경로 (Step 번호 유지 전용)

아래 경로는 기존 Step `2.2.1~2.2.6`를 대체하지 않고, sprint 진행 중 필요한 경우에만 추가로 적용한다.

**경로 1: AI 자율 판단 (AUTO_MODE)**
- 트리거: `2.2.3`의 `mst:plan -a` 컨텍스트 작성/실행 중, 기존 디자인 baseline과 새 요구사항의 불일치가 감지된 경우 (plan 스킬 Step 4의 UI 감지 키워드/의미 판단 포함).
- 실행 방법:
  1. `mst:plan`의 UI 감지 흐름으로 디자인 수정 필요성을 확정한다.
  2. 확정되면 `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {plan 주제}")`를 재호출한다.
  3. Stitch 결과를 현재 sprint plan 컨텍스트에 반영한 뒤 루프를 계속 진행한다.

**경로 2: 사용자 명시 요청**
- 트리거: sprint 중 사용자가 `"디자인 수정해줘"`, `"화면 추가해줘"` 등 디자인 변경을 직접 요청한 경우.
- 실행 방법:
  1. 요청을 plan 스킬의 UI 감지 흐름으로 전달하거나, 즉시 `Skill(skill: "mst:stitch", args: "{요청 맥락}")`를 호출한다.
  2. 생성된 디자인 결과를 sprint 기준선에 반영하고 필요 시 `2.2.3`을 재실행한다.

**경로 3: review 발견**
- 트리거: 구현 후 review에서 디자인과 구현의 괴리가 감지된 경우.
- 실행 방법:
  1. review 결과를 기준으로 `디자인 수정 필요` / `구현 수정 필요`를 분기한다.
  2. 디자인 수정이 필요하면 plan 스킬 UI 감지 흐름으로 재진입 후 `Skill(skill: "mst:stitch", args: "--pln PLN-NNN --multi {보정 주제}")`를 호출한다.
  3. 구현 수정만 필요하면 기존 sprint 수정 루프로 처리하고 디자인 baseline은 유지한다.

###### objective.md 디자인 컨텍스트 baseline 업데이트 규칙 (MANDATORY)

디자인이 실제로 수정된 경우(경로 1~3) 아래를 반드시 적용한다.
1. objective.md `## 디자인 컨텍스트`의 `상태`를 `updated`로 변경한다.
2. `### 변경 이력`에 변경 시점(Sprint N/날짜), 변경 내용, 변경 사유를 기록한다.
3. DES-NNN이 새로 생성/교체되었으면 화면 목록과 텍스트 와이어프레임을 최신 기준으로 갱신한다.
4. objective 갱신 시 direct edit 금지 규칙을 유지하고, 기존 `mst.py` 기반 objective 갱신 절차를 따른다.

##### 2.2.4 Sprint 결과 기록 + Sprint 종류 자기선언 + DoD 갱신 제안

Sprint 실행 결과를 기록하고, 이번 Sprint에서 완료 근거가 확보된 DoD에 대해 갱신 제안을 남긴다.

**Sprint 종류 자기선언 (MANDATORY — 재프레이밍 핵심)**:

이 Sprint는 시작 시점 또는 결과 기록 시점에 **반드시 종류를 자기선언**한다:

- `user_observable` (기본값): 사용자가 이 Sprint 전에는 할 수 없었던 것을 이제는 할/볼 수 있게 됨. 진입점(CLI 명령, SKILL 호출, UI 클릭 경로, 생성된 산출물 등) 중 최소 1개가 추가/변경되어 관찰 가능. `--user-observable-change` 필드로 "사용자가 이제 무엇을 볼/할 수 있는가"를 자유 텍스트로 기록한다.
- `foundational` (예외): 사용자 관찰이 불가능한 기반 작업(테스트 인프라, 빌드 파이프라인, 내부 스키마 정의, 타입 선언 등). `--foundational-reason` 필드로 "왜 사용자 관찰 불가한지 + 어느 후속 Sprint에서 사용자 관찰 가능해질 예정인지"를 기록한다.

**연속 한도 (MANDATORY)**: `foundational` Sprint는 `config.agile.foundational_streak_max`(기본 2) 이상 연속 선언할 수 없다. 한도 도달 후 다음 Sprint가 또 `foundational`을 시도하면 비상 스티어링(Step 3) 강제 진입. Sprint 0(테스트 환경 구축)은 이 카운트에 포함하지 않는다.

**지연 승격 (MANDATORY)**: `foundational` Sprint에 포함된 DoD는 `proposed_done` 상태로만 기록한다(=아직 `done` 승격 불가). 첫 번째 후속 `user_observable` Sprint가 완료되는 시점에 `agile objective-transition --deferred-promote --sprint {N}` 호출로 누적된 `proposed_done` DoD를 **일괄 `done`으로 승격**한다.

1. Sprint 결과 기록:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile result {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --status done|failed \
  --planned "{SELECTED_WORK_ITEM}" \
  --completed "{COMPLETED_ITEM_IF_DONE}" \
  --pln {PLN_ID} \
  --req {REQ_ID} \
  --sprint-kind {user_observable|foundational} \
  --user-observable-change "{사용자가 이제 할/볼 수 있는 것}" \
  --foundational-reason "{foundational 사유 + 후속 계획}" \
  --sprint-goals '{SPRINT_GOALS_JSON_IF_AVAILABLE}' \
  --previous-lessons "{PREVIOUS_LESSONS}" \
  --json
```
  - `--sprint-kind` 생략 시 기본값 `user_observable`.
  - `--sprint-kind user_observable`인 경우 `--user-observable-change`를 반드시 지정한다. 비어 있으면 경보 출력.
  - `--sprint-kind foundational`인 경우 `--foundational-reason`을 반드시 지정한다.
  - 동일 Sprint에서 한 필드만 지정하고 다른 필드는 생략한다 (두 종류는 상호 배타).

1.5. `user_observable` Sprint 완료 시 지연 승격 호출:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile objective-transition {AGI_ID} \
  --story {SELECTED_DOD_OR_PLACEHOLDER} \
  --status done \
  --deferred-promote \
  --sprint {CURRENT_SPRINT} \
  --json
```
  - 이 호출은 이번 Sprint가 실제로 기여한 DoD를 `done`으로 승격하면서, 동시에 `--sprint {CURRENT_SPRINT}` 이전의 foundational Sprint 체인에 포함된 모든 `proposed_done` DoD를 역추적하여 일괄 `done`으로 승격한다.
  - 직전 `foundational` Sprint가 없으면 `--deferred-promote`는 단일 DoD 전이와 동일하게 동작한다 (graceful).
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

##### Step 2.2.5 Sprint Review Gate (Step 2.2.4 직후 MANDATORY)

Sprint 결과/회고 기록 직후, objective details evidence를 스프린트 게이트로 검증한다.

기본 호출:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile evidence-check \
  --agi-id {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --json
```

판정 규칙 (3-tier):
- `PASS`: evidence 충족, 위반 0건. 즉시 Step 2.2.6으로 진행.
- `WARN`: 차단하지 않음(예: `TBD`, gate disabled 경고). 경고를 Sprint 메모에 남기고 Step 2.2.6으로 진행.
- `FAIL`: 스프린트 진행 차단. 위반(artifact 미존재, `required_globs` 미충족 등)을 수정한 뒤 `evidence-check`를 재실행한다.

Objective Surface Coverage drift-check (MANDATORY):
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile drift-check \
  --agi-id {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --json
```

drift-check 판정:
- `PASS`: objective surface coverage가 threshold 이상. Step 2.2.6으로 진행.
- `WARN`: coverage가 threshold 미만. 스프린트 메모에 `covered_surface`/`uncovered_surface`를 기록하고 계속 진행.
- `ESCALATE`: WARN이 `warn_streak_limit` 이상 연속되면 `escalate_flag=true`. 비상 스티어링 트리거로 간주하고 Step 3 진입 또는 recall 정책(사용 가능 시)을 실행한다.

drift-check config:
- `config.agile.drift.enabled`가 `false`면 drift-check는 skip WARN으로 처리하고 차단하지 않는다.
- `config.agile.drift.threshold` 기본값 `0.7`
- `config.agile.drift.warn_streak_limit` 기본값 `2`

recall 트리거 조건 (Step 2.2.5 내부, Level 2 patch만):
- `evidence-check == FAIL`이면 아래를 실행한다.
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile recall \
  --agi-id {AGI_ID} \
  --level 2 \
  --reason fail \
  --trigger evidence \
  --json
```
- `drift-check` 결과에서 `ESCALATE`면 아래를 실행한다.
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile recall \
  --agi-id {AGI_ID} \
  --level 2 \
  --reason drift \
  --trigger drift-warn-streak \
  --json
```
- `config.agile.recall.enabled=false`면 recall은 skip + warn으로 처리하고 기존 스프린트 워크플로우를 유지한다.
- cooldown bypass는 evidence hard fail에서만 허용한다 (`--bypass-cooldown --fingerprint <hard-fail-id>`). drift 트리거에는 bypass를 사용하지 않는다.

`required_globs` 규칙:
- 프로젝트 타입별 `required_globs`는 `config.agile.evidence_gate.required_globs`에서 읽는다.
- 어떤 패턴이든 매치가 0건이면 **hard fail**로 처리한다 (slide-craft 패턴 차단).
- 기본 fallback은 플러그인 타입의 `skills/*/SKILL.md`다.

예외 bypass (긴급 시에만):
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile evidence-check \
  --agi-id {AGI_ID} \
  --sprint {CURRENT_SPRINT} \
  --accept-evidence-gap "{REASON}" \
  --json
```
- `REASON`은 필수다.
- bypass 사용 시 `.gran-maestro/agile/sprint-log.json`에 사유가 영구 기록된다.

##### 2.2.6 외부 에이전트 소스 검증 (Sprint 완료 후 MANDATORY)

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
  - `AUTO_MODE=true`이면 AskUserQuestion을 skip하고 `[자동 중단]` 절차로 즉시 전환한다.
  - `AUTO_MODE=false`이면 기존대로 AskUserQuestion 에스컬레이션을 수행한다.
4. `pass` 또는 `MINOR`만 남으면:
```bash
python3 {PLUGIN_ROOT}/scripts/mst.py agile update {AGI_ID} \
  --current-sprint {CURRENT_SPRINT + 1} \
  --json
```
5. `CONTINUATION GUARD`:
  - 위 update 호출 직후 `CURRENT_SPRINT = CURRENT_SPRINT + 1`로 갱신한다.
  - `[CRITICAL][STEERING-CHECK-ON-INCREMENTED-SPRINT]` 증가된 `CURRENT_SPRINT` 기준으로 스티어링 해당 여부를 **반드시 즉시 판정**한다.
  - `STEERING_DISABLED=true` 또는 `STEERING_EVERY == 0`이면 정기 스티어링을 skip하고 Step 2.2.1로 즉시 진행한다.
  - `STEERING_EVERY > 0`이고 `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0`이면 `[MANDATORY][STEERING-DUE]` Step 3를 실행한 뒤 루프 상단으로 복귀한다.
  - 위 조건에 해당하지 않으면 `[CRITICAL][NO-AD-HOC-PAUSE]` 어떤 확인 질문도 삽입하지 말고 Step 2.2.1로 즉시 진행한다.
  - `[CRITICAL][NO-SELF-MOTIVATED-PAUSE]` 스티어링 체크포인트 또는 비상 스티어링 트리거에 해당하지 않는 한, 어떤 사유(컨텍스트 길이, 요약 필요, 세션 정리, 토큰 절약 등)로든 스프린트 간 정지를 절대 금지하고 Step 2.2.1로 즉시 진행한다.

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
| **정기** | `STEERING_DISABLED != true` AND `STEERING_EVERY > 0` AND `CURRENT_SPRINT > 0` AND `(CURRENT_SPRINT - 1) % STEERING_EVERY == 0` |
| **비상** | 안전장치 섹션의 비상 스티어링 트리거 조건 충족 시 즉시 진입 |

`steering_every` 값은 session.json에서 로드하며 기본값은 3이다.
`STEERING_EVERY == 0` 또는 `STEERING_DISABLED == true`이면 정기 스티어링은 비활성화 상태로 간주한다.

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

통합 건강 (integration-review + alignment-check)
- 직전 {STEERING_EVERY} Sprint 분류: modify {MODIFY_COUNT} / wire {WIRE_COUNT} / new-island {NEW_ISLAND_COUNT}
- 누적 new-island 비율: {NEW_ISLAND_RATIO:.2%} (임계: {NEW_ISLAND_THRESHOLD:.2%})
- 연속 user_observable Sprint: {USER_OBSERVABLE_STREAK} / 연속 foundational: {FOUNDATIONAL_STREAK} (한도 {FOUNDATIONAL_STREAK_MAX})
- proposed_done 대기 DoD: {DEFERRED_DOD_COUNT}건 (다음 user_observable Sprint 완료 시 일괄 승격 예정)
- alignment 판정: aligned {ALIGNED_COUNT} / drift_warning {DRIFT_WARNING_COUNT} / objective_stale {OBJECTIVE_STALE_COUNT}
- Escape Hatch override: {ESCAPE_OVERRIDE_COUNT}건 {ESCAPE_REASONS}

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

진행 보고서 출력 후 아래 분기를 적용한다.

- `AUTO_MODE=true`:
  - AskUserQuestion을 호출하지 않는다.
  - PM이 `evidence_ref`, 테스트/빌드 결과, `source-verify.md`를 근거로 DoD별 approve/reject를 자율 판단한다.
  - 판단 결과를 `[스티어링 체크포인트] AUTO_MODE 자율 판단` 로그로 기록한 뒤 즉시 상태 전이를 수행한다.
- `AUTO_MODE=false`:
  - `AskUserQuestion`으로 사용자에게 확인한다.

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

레벨 결정 후 아래 분기를 적용하고 루프로 복귀한다.
- `AUTO_MODE=true`: AskUserQuestion을 skip하고 PM이 정합성 정책 레벨(Level A/B/C)을 자율 판단해 적용한다.
- `AUTO_MODE=false`: `AskUserQuestion`으로 처리 방식 확인 후 적용한다.

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

**감지 시점**: 매 스프린트 완료(2.2.6 소스 검증 통과 직후) 수행.

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
- `EMERGENCY_STEERING_ENABLED == false`이면 본 섹션 전체를 skip하고 비상 스티어링 강제 진입을 수행하지 않는다.

| 트리거 조건 | 설명 |
|-------------|------|
| 연속 실패 2회 (자동 중단 이전) | 자동 중단 직전 사용자 개입 기회 제공 (`consecutive_failures`) |
| blocked DoD 누적 50% 이상 | 절반 이상의 DoD가 blocked 상태 |
| drift 감지 연속 2회 | 변경 파일과 objective 관련성 80% 미달 연속 (`drift_count`) |
| Level 3 복구 에스컬레이션 도달 | 4단계 복구 최상위 레벨 도달 |

비상 스티어링 진입 시:
1. `[비상 스티어링] 조건: {TRIGGER_REASON}` 출력 후 Step 3으로 진입
2. Step 3.2 진행 보고서 즉시 출력
3. 사용자 개입 분기:
```text
[비상 스티어링] 자동 진행이 중단되었습니다. 트리거: {TRIGGER_REASON}

선택:
1) 계속 진행 (해당 DoD blocked 처리 후 다음 DoD)
2) objective 수정 (Step 3.4 방향 전환)
3) 완전 중단
```
   - `AUTO_MODE=true`: AskUserQuestion을 skip하고 PM이 위 1~3 중 하나를 자율 판단해 즉시 실행한다.
   - `AUTO_MODE=false`: `AskUserQuestion`으로 사용자 개입을 요청한다.
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
- 합리화 패턴: "이번 스프린트는 바쁘니 스티어링 해당이어도 Step 3을 건너뛰자." | 확인 증거: 스티어링 해당 시점마다 `[MANDATORY][STEERING-DUE]` 로그와 Step 3 실행 기록이 존재.
- 합리화 패턴: "스티어링 미해당이지만 한 번 더 계속 여부를 묻자." | 확인 증거: 미해당 스프린트 로그에서 `"계속할까요?"`, `"멈출까요?"` 질문이 0건이고 Step 2.2.1로 즉시 진행한다.
