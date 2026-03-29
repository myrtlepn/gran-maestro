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

##### 1A.1 JTBD Q&A (5개, AskUserQuestion 순차 진행)

1. **Job Statement**: "어떤 상황에서 이 프로젝트를 진행하게 되었나요? (When I ...)"
2. **핵심 목표**: "이 프로젝트를 통해 무엇을 달성하고 싶으신가요? (I want to ...)"
3. **기대 결과**: "성공했을 때 얻게 되는 가치는 무엇인가요? (So I can ...)"
4. **성공 지표**: "완료를 어떻게 측정할 수 있을까요? (측정 가능한 지표)"
5. **완료 정의**: "프로젝트가 완료됐다고 판단하는 기준은 무엇인가요? (프로젝트 DoD)"

##### 1A.2 Epic 분해 + DoD 체크리스트 Q&A

1. JTBD 답변 기반으로 **Epic 2~5개** 초안을 제안하고 사용자 확인
2. 각 Epic에 대해 아래를 확정
   - `목표`: Epic이 달성해야 할 관찰 가능한 결과
   - `DoD 체크리스트`: Epic당 **3~7개**
3. Story 생성은 하지 않는다. 실행 단위 Story는 후속 Sprint 단계에서 JIT로 결정한다.

##### 1A.3 4중 가드레일 검증 (MANDATORY)

1. **How-free**: 구현 방법이 포함되면 거부하고 관찰 가능한 결과 문장으로 재질문
2. **5-7 rule**: Epic당 DoD 항목은 3~7개 유지, 8개 이상이면 Epic 분할 안내
3. **So-that 검증**: 각 DoD가 "X한다, so that 사용자는 Y할 수 있다"로 연결 가능한지 확인
4. **Sprint 간 동결**: 진행 중 Sprint의 체크리스트 변경 금지, 변경은 스티어링 체크포인트에서만 반영

##### 1A.4 objective.md 저장

`templates/objective.md` 포맷으로 아래 경로에 저장:

```
{PROJECT_ROOT}/.gran-maestro/agile/{AGI_ID}/objective/objective.md
```

저장 규칙:
- 섹션은 `JTBD 레이어` + `Epic 레이어 (목표 + DoD 체크리스트)`만 사용
- Story/Checklist 별도 레이어는 만들지 않음
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

##### 1B.2 누락/모호 항목 보완 Q&A

1. JTBD 누락 필드를 AskUserQuestion으로 보완
2. Epic 목표가 모호하면 "관찰 가능한 결과" 기준으로 재질문
3. Epic별 DoD 개수가 3개 미만이면 보강 질문, 7개 초과면 Epic 분할 질문
4. 4중 가드레일(How-free/5-7/So-that/동결) 재검증

##### 1B.3 objective.md 저장

- 1A.4와 동일한 경로/포맷/마커 규칙으로 저장
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

## DSC-047 운영 합의 반영 (MANDATORY)

1. Epic DoD 체크리스트가 완료 판정의 유일한 게이트다(LLM override 금지).
2. Sprint 완료 시 체크 갱신은 "제안"만 가능하며 `evidence_ref`를 반드시 포함한다.
3. 최종 approve/reject는 스티어링 체크포인트에서 사용자가 수행한다.

