---
name: accept
description: "완료된 결과물을 최종 수락합니다 (Phase 3 → Phase 5). Worktree를 main에 머지하고 정리합니다. 사용자가 '수락', '머지', '최종 수락'을 말하거나 /mst:accept를 호출할 때 사용. 기본적으로 /mst:approve에서 자동 호출되며, workflow.auto_accept_result=false 시 수동 사용."
user-invocable: true
argument-hint: "[REQ-ID]"
---

# maestro:accept

Phase 3 리뷰를 통과한 결과물을 최종 수락하여 main 브랜치에 머지하고 정리합니다.

## 호출 방식

- **자동**: `auto_accept_result=true`(기본) 시 `/mst:approve`에서 Phase 3 PASS 후 자동 실행
- **수동**: `auto_accept_result=false` 시 `/mst:approve`가 Phase 3 PASS 후 멈추고 사용자가 명시적 호출

## Gate

### Entry

- 대상 REQ를 확정하고 Phase 3 리뷰 PASS 상태를 먼저 검증한다.
- 머지/정리 대상 브랜치와 worktree 식별이 완료된 상태에서만 수락 절차를 시작한다.
- `source_plan` 존재 여부를 확인해 Step 6 동기화 대상(plan.json)을 결정한다.

### Exit

- squash-merge 커밋 생성, 브랜치/워크트리 정리, Phase 5 완료 처리가 모두 끝나야 종료한다.
- `request.json`이 `done` 상태로 갱신되고 후속 의존 REQ 처리(해당 시)가 반영되어야 한다.
- `source_plan`이 있으면 Plan 상태 동기화 시도 결과(완료/스킵)를 남긴다.

### 금지 패턴

- 리뷰 PASS 확인 없이 머지/정리 단계부터 실행한다.
- squash-merge 후 `git branch -d`만 사용해 정리 실패를 방치한다.
- `source_plan`이 있는데도 Step 6 동기화 확인을 생략하고 완료 처리한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "테스트가 통과했으니 리뷰/상태 확인 없이 바로 머지해도 된다." | 확인 증거: 실행 로그에 리뷰 PASS 확인 결과와 대상 REQ-ID를 먼저 출력한다.
- 합리화 패턴: "일부 정리 실패는 무시하고 완료로 닫아도 된다." | 확인 증거: worktree/브랜치 정리 실행 결과를 항목별로 기록하고 실패 시 경고를 남긴다.
- 합리화 패턴: "수락만 끝나면 plan 동기화는 선택사항이다." | 확인 증거: Step 6에서 `source_plan` 조회 및 sync 실행(또는 skip 사유)을 명시한다.

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

### REQ ID 결정 (인자 없이 호출 시)

`requests/`의 모든 `request.json` 스캔 → `current_phase==3` + `phase3_review`/PASS 상태 필터링 → REQ 번호 오름차순 첫 번째 선택 (없으면 "대기 중 요청 없음" 알림)

### 최종 수락 실행 (Phase 3 → Phase 5)

1. **리뷰 PASS 확인**: PASS 아니면 사용자 알림 후 중단 (먼저 `/mst:feedback` 완료 필요)
2. **요약 리포트 생성**: 모든 태스크 완료 결과 → `summary.md` 작성
2.5. **Evidence Verification Gate (PAC 증거 검증)**:
   - 목적: `source_plan` 기반 PAC 검증 증거가 최신 review 산출물에 모두 첨부되었는지 확인한다.
   - 실행 순서:
     1. `request.json.source_plan` 확인.
        - 미존재 시: `"[INFO] Evidence gate skip (source_plan 없음)"` 출력 후 다음 단계 진행 (하위 호환).
     2. `source_plan`이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json` Read.
        - 파일 미존재 시: `"[INFO] Evidence gate skip (plan.ids.json 없음)"` 출력 후 다음 단계 진행 (하위 호환).
     3. `plan.ids.json`에서 PAC ID 목록(`PAC-N`)을 로드한다.
     3.5. **PAC 범위 필터링 (분리 실행 플랜 대응)**:
        - `request.json`의 모든 태스크에서 `covers_ac` 배열을 수집한다.
        - 해당 태스크의 `spec.md`의 `## 3.3 PAC Mapping`에서 `Coverage == "COVERED"`인 PAC ID만 추출하여 `in_scope_pacs`로 설정한다.
        - `in_scope_pacs`가 비어있으면 (하위 호환: PAC Mapping 미존재) `plan.ids.json`의 전체 PAC를 대상으로 한다.
        - `in_scope_pacs`가 있으면 해당 PAC만 검증 대상으로 한정한다 (OTHER_REQ PAC 제외).
     4. 최신 review iteration(`request.json.review_iterations`의 최신 `rv_id`)을 식별하고
        `{PROJECT_ROOT}/.gran-maestro/requests/{REQ_ID}/reviews/{RV_ID}/evidence-ledger.md`를 Read한다.
        - 파일 미존재 시: `"[INFO] Evidence gate skip (evidence-ledger.md 없음 — 레거시 review)"` 출력 후 다음 단계 진행 (하위 호환).
     5. PAC별 증거 존재 여부를 확인한다 (`in_scope_pacs` 범위 내에서만).
        - 기준: `evidence-ledger.md`에 해당 PAC ID 레코드가 존재해야 한다.
        - 누락 PAC가 1개 이상이면 accept를 **즉시 블로킹**하고 아래 메시지를 출력한 뒤 중단한다.
          - `증거 미첨부 PAC: {PAC-ID 목록}`
        - 누락이 없으면 다음 단계 진행.
2.6. **수락 전략 결정 (source_plan → plan.json.type → type-strategies.json 체인, MANDATORY)**:
   - `request.json.source_plan` 값이 있으면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`을 Read하고 `type` 필드를 확인한다.
   - `plan_type = plan.json.type` (`type` 누락 또는 Read 실패 시 `"code"` fallback)
   - `type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)` 시도
   - `strategy = type_strategies[plan_type] || type_strategies["code"]`
   - `type-strategies.json` Read 실패/파싱 실패/키 누락 시 `strategy = {"template":"templates/impl-request.md","worktree_policy":"required","review_mode":"code","accept_mode":"squash-merge"}`로 fallback해 기존 수락 경로를 유지한다.
3. **Worktree → REQ 브랜치 → master squash-merge** (기본: `strategy.accept_mode != "file-placement"`)
   - `if strategy.accept_mode == "file-placement"`:
     - squash-merge를 실행하지 않고 문서 파일을 대상 경로로 배치(복사/이동)한다.
     - 배치 대상 경로는 각 태스크 spec/doc-spec에 정의된 문서 산출 경로를 따른다.
     - 아래 3-1~3-3 git merge 절차는 건너뛴다.
   - `else` (`strategy.accept_mode != "file-placement"`):
     - 아래 3-1~3-3 기존 절차를 그대로 수행한다. (변경 금지)
   - approve 단계(Step 4a)에서 생성된 `gran-maestro/REQ-NNN` 브랜치를 사용합니다.
   - 단일 태스크 REQ도 동일한 플로우를 적용합니다.
   - **3-1. 각 태스크 worktree → REQ 브랜치 일반 머지 (태스크 커밋 이력 보존)**:
     ```bash
     # 각 태스크 브랜치를 REQ 브랜치에 머지 (커밋 이력 보존)
     git -C {PROJECT_ROOT} checkout gran-maestro/REQ-NNN
     git -C {PROJECT_ROOT} merge --no-ff gran-maestro/REQ-NNN-T01
     git -C {PROJECT_ROOT} merge --no-ff gran-maestro/REQ-NNN-T02
     # ... (태스크 수만큼 반복)
     ```
   - **3-2. REQ 브랜치 → master squash-merge (단일 커밋 생성)**:
     ```bash
     git -C {PROJECT_ROOT} checkout master
     git -C {PROJECT_ROOT} merge --squash gran-maestro/REQ-NNN
     ```
     [커밋 양식 감지]
     1. `git -C {PROJECT_ROOT} log --pretty=format:"%s" -10`을 실행해 최근 10개 커밋 subject를 수집한다.
     2. 수집된 subject에서 `[REQ-`로 시작하는 항목을 우선 분석 대상으로 사용하고, 없으면 전체 10개를 분석 대상으로 사용한다.
     3. 분석 대상에서 가장 빈번한 패턴을 추출한다.
        - 접두사 패턴: `[REQ-NNN]` 형태와 뒤따르는 설명 구조를 식별한다.
        - 언어 패턴: 한국어/영어 중 우세한 언어를 식별한다.
        - 부록 패턴: `(...)` 형태의 파일목록/부록 유무를 식별한다.
     4. `git log` 실행 실패, 커밋 히스토리 부재, 또는 분석 대상에서 일관된 패턴을 추출할 수 없는 경우 subject 폴백은 `[REQ-NNN] {REQ 제목}`으로 고정한다.
     5. 감지 결과로 `{DETECTED_SUBJECT}`를 만들고, 예를 들어 `[REQ-NNN] 한국어 설명 (파일목록)`이 우세하면 동일한 접두사/언어/괄호 부록 구조를 유지한다.
     ```bash
     git -C {PROJECT_ROOT} commit -m "{DETECTED_SUBJECT}

     태스크 요약:
     - T01: {태스크 1 제목}
     - T02: {태스크 2 제목}"
     ```
   - **3-3. REQ 브랜치 삭제** (squash merge 후 `-D` 강제 삭제):
     ```bash
     git -C {PROJECT_ROOT} branch -D gran-maestro/REQ-NNN
     ```
3.5. **Implementation Decision 기록 (비차단)**:
   - `source_plan`이 존재하면 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json`의 `linked_intent` 필드를 읽어 INTENT_ID 취득
   - INTENT_ID가 존재하면 해당 Intent 파일(`{PROJECT_ROOT}/.gran-maestro/intents/{INTENT_ID}.md`)의 `## Implementation Decision` 섹션 끝에 아래 형식으로 직접 Edit(append):
     - Edit 방법: old_string에 섹션의 기존 마지막 줄(또는 빈 줄 포함)을 포함하고, new_string에 기존 내용 + 새 항목을 추가
     ```
     [YYYY-MM-DD] [REQ-NNN] {spec §1 요약}
     ```
   - `linked_intent` 미존재 시 skip (비차단); 파일 Edit 실패 시 warn만 출력, 워크플로우 차단 금지

4. **정리**: 각 태스크의 worktree 및 임시 브랜치 정리
   > ⚠️ **squash merge 후 브랜치 삭제 규칙**: REQ 브랜치를 master에 squash merge하면 merge ancestor가
   > 생성되지 않으므로 `git branch -d`(soft delete)는 "not fully merged" 오류로 실패합니다.
   > 브랜치 삭제는 `git branch -D`를 사용하세요.
   - `strategy.accept_mode == "file-placement"`이면 worktree가 없을 수 있으므로 worktree 제거 단계는 "없으면 skip"으로 처리한다 (graceful skip, 비차단).
   - `git worktree remove --force "{worktree_path}" || true` — 태스크 worktree 제거 (이미 제거된 경우 오류 무시)
   - `git branch -D "gran-maestro/REQ-NNN-T01" || true` — 태스크 브랜치 강제 삭제 (`gran-maestro/REQ-NNN-T02` 등 반복)
   - `git branch -D "gran-maestro/REQ-NNN" || true` — REQ 브랜치 강제 삭제 (기본은 Step 3-3에서 처리, 정리 단계에서는 중복 방지 확인용)
   - 각 태스크를 **독립적으로** 실행 (`&&` 연결 금지 — 하나 실패 시 나머지 미실행됨)
   - 순서: worktree 제거 먼저, 브랜치 삭제 나중
4.5. **Pending Stitch 화면 재확인**:
   - `request.json`의 `stitch_screens` 배열에서 `status: "pending"` 항목 확인
   - 없으면 이 단계 스킵
   - 있으면: `mcp__stitch__list_screens(projectId)` 호출 (projectId는 `config.stitch.project_id`)
     - **`baseline_screen_ids` 있는 경우**:
       - 현재 screen IDs = `screens[].name`에서 마지막 `/` 이후 값 추출
       - 차집합 = 현재 screen IDs - pending 항목의 `baseline_screen_ids`
       - 차집합 비어있지 않으면: 첫 번째 ID로 `get_screen` 호출 → URL 확보 → 발견 처리
       - 차집합 비어있으면: 미발견 처리
     - **`baseline_screen_ids` 없는 경우** (구버전 pending 호환):
       - 타임스탬프 비교 불가 → 미발견 처리
     - **발견 시**: `get_screen`으로 URL 확보 →
       `stitch_screens`의 pending 항목을 아래 필드로 업데이트:
       `stitch_screen_id`, `url` (`https://stitch.withgoogle.com/projects/{project_id}`),
       `image_url` (`screenshot.downloadUrl` 또는 null), `status: "active"`
       → "[Stitch] 화면 확인 완료 — {screen title}" 출력
     - **미발견 시**: pending 유지 →
       "[Stitch] 화면 미확인 — /mst:stitch --list로 수동 확인 가능합니다." 출력

5. **Phase 5 완료 처리**: `stitch_screens`의 `active` 항목 → `archived`로 변경; **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 5 done`; 실패 시 fallback으로 `current_phase`=5, `status`=`done` 직접 업데이트; 완료 알림
> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제).

5.5. **후속 REQ 활성화 (Dependency Unblock)**:
  - `request.json`의 `dependencies.blocks` 배열 확인
  - 배열이 비어있으면 이 단계 스킵
  - 비어있지 않으면 각 후속 REQ-ID에 대해:
    a. `{PROJECT_ROOT}/.gran-maestro/requests/{BLOCKED-REQ-ID}/request.json` Read
    b. `status`가 `pending_dependency`인지 확인 (아니면 스킵)
    c. `dependencies.blockedBy` 배열에서 현재 완료된 REQ-ID를 제거
    d. `blockedBy` 배열이 비어지면:
       - `request.json`의 `status`를 `"phase1_analysis"`로 변경
       - 사용자에게 알림: `[활성화] {BLOCKED-REQ-ID} 의존성 해소 — Phase 1 분석 시작`
       - PM Conductor로 해당 REQ의 Phase 1 분석 즉시 실행 (spec.md 자동 작성)
       - Phase 1 분석 완료 (`status == "spec_ready"`) 후:
         * `workflow.auto_approve_on_unblock == true`이면:
           - 알림: `[자동 실행] {BLOCKED-REQ-ID} 의존성 해소 완료 → approve 자동 실행 중...`
           - `Skill(skill: "mst:approve", args: "{BLOCKED-REQ-ID}")` 호출
         * `false`이면: 기존과 동일하게 `/mst:approve {BLOCKED-REQ-ID}` 안내
    e. `blockedBy`가 아직 남아있으면 현재 REQ-ID만 제거하고 `pending_dependency` 유지
5.6. **DAG 자동 연쇄 실행 게이트 (수동 수락 경로 지원)**:
  - 목적: `workflow.auto_accept_result=false`로 `/mst:accept`를 수동 호출한 경로에서도 DAG 연쇄를 동일하게 보장
  - 실행 조건 (모두 충족 시에만 실행):
    1. `workflow.auto_accept_result == false`
    2. 현재 REQ의 `request.json.source_plan`이 `"PLN-NNN"` 형태로 존재
    3. 현재 REQ의 `request.json.dag_auto_chain == true`
    4. 현재 REQ 상태가 `done` 또는 `completed` 또는 `accepted`
  - 탐색/실행 규칙:
    - 매 반복마다 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json` Read 후 `linked_requests` 전체를 재평가한다 (`after=current` 방식 금지)
    - 후보 상태는 `pending_dependency`, `phase1_analysis`, `spec_ready`를 모두 포함한다
    - 완료/종료 상태(`done`, `completed`, `accepted`, `cancelled`)는 제외한다
    - 후보 REQ의 `dependencies.blockedBy`가 모두 해소된 경우에만 실행한다
    - 실행 호출 계약:
      - `Skill(skill: "mst:request", args: "--plan {source_plan} --resume {next_req.id} -a")`
      - `mst:request`는 기존 REQ 재개 모드로 동작해야 하며 신규 REQ를 생성하면 안 된다
  - 실패/종료 처리:
    - 다음 REQ 실행 후 상태가 `done`/`completed`/`accepted`가 아니면 즉시 중단
    - 중단 보고: `[DAG 연쇄 중단] {REQ-ID} 실패. 후속 REQ: {REQ-ID 목록}`
    - `linked_requests` 전체가 `done`/`completed`/`accepted`면 완료 보고:
      `[DAG 연쇄 완료] PLN-NNN의 모든 REQ가 완료되었습니다. ...`
6. **Plan 상태 동기화**:
   - `source_plan`(예: `PLN-NNN`) 있으면: `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json` Read → `linked_requests` 내 모든 REQ 상태 확인
   - 전체 `done`/`completed`/아카이브 시: **스크립트 우선** `python3 {PLUGIN_ROOT}/scripts/mst.py plan sync {source_plan}`; 실패 시 fallback으로 `plan.json`의 `status="completed"` + `completed_at` 직접 업데이트
   - 미완료 REQ 존재 시: 스킵; `source_plan` 없으면 스킵


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

## 예시

```
/mst:accept              # 최종 수락 대기 중인 첫 번째 요청 자동 선택
/mst:accept REQ-001      # 명시적으로 REQ-001 최종 수락
```

## 설정

`workflow.auto_accept_result` (기본: `true`): `true` → 자동 수락; `false` → 수동 호출 필요
```
/mst:settings workflow.auto_accept_result false
```

## 문제 해결

- "수락 요청 없음" → `/mst:inspect {REQ-ID}`로 Phase 3 PASS 상태 확인
- "리뷰 PASS 아님" → `/mst:feedback`으로 피드백 루프 먼저 완료
- "머지 충돌" → worktree에서 수동 충돌 해결 후 재실행
- "이미 완료됨" → `/mst:inspect {REQ-ID}` 확인
