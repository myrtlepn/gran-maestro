---
name: approve
description: "스펙을 승인하고 실행을 시작합니다. 사용자가 '승인', '진행해', 'OK 진행'을 말하거나 /mst:approve를 호출할 때 사용. Gran Maestro 워크플로우 내에서만 의미 있으며, 일반적인 확인 응답에는 사용하지 않음."
user-invocable: true
argument-hint: "[-a|--auto] [REQ-ID...] [--stop-on-fail | --continue] [--parallel] [--priority <level>]"
---

# maestro:approve

PM이 작성한 구현 스펙을 승인하고 Phase 2 실행을 시작합니다. 단건/배치 승인 모두 지원. Phase 3 PASS 후 최종 수락은 `workflow.auto_accept_result` 설정에 따라 자동 실행.

## Gate

### Entry

- 승인 대상 REQ와 의존성 검증 결과를 확정한 뒤에만 단건/배치 실행 루프로 진입한다.
- Phase 2 이후 단계는 NON-STOP 규칙(중간 멈춤 금지)을 적용 대상으로 잠근다.

### Exit

- Phase 3 결과 처리와 최종 수락(또는 수동 수락 안내)까지 완료되어야 approve를 종료할 수 있다.
- DAG 자동 연쇄가 활성화된 경우, 실행 가능한 후속 REQ가 더 이상 없거나 사용자 명시적 취소가 있을 때만 연쇄 루프를 종료한다.

### 금지 패턴

- "컨텍스트가 길어졌다", "대화가 길어졌다", "토큰을 많이 썼다"를 이유로 approve 실행을 임의 중단한다.
- 서브스킬 반환 메시지(`[TRACE_SAVED]` 등)를 종료 신호로 오해해 다음 Step 호출 없이 멈춘다.
- DAG 연쇄 중 실행 가능한 다음 REQ가 존재하는데도 임의 판단으로 체인을 종료한다.

## Anti-Rationalization Checklist

- 합리화 패턴: "컨텍스트가 길어졌으므로 멈춘다." | 확인 증거: 컨텍스트 길이/대화 길이/토큰 소비량과 무관하게 `NEXT_ACTION` 출력 직후 다음 Step 도구 호출을 실행한다.
- 합리화 패턴: "대화가 길어졌으니 다음 REQ는 다음 턴에 하자." | 확인 증거: 실행 가능한 다음 REQ가 있으면 같은 실행 흐름에서 `mst:request --resume ... -a`를 즉시 호출한다.
- 합리화 패턴: "토큰 절약을 위해 DAG 자동 연쇄를 여기서 끝내자." | 확인 증거: 연쇄 루프는 사용자 명시적 취소 또는 실행 가능한 후보 부재 시에만 종료한다.

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

approve 외주 브리프 작성 시 외부 의존성 판단 최신화를 위해 아래 공통 프로토콜을 적용한다.

0. **자동 트리거 게이트**:
   - `config.resolved.json`의 `reference.auto_search == true`일 때만 자동 WebSearch 허용.
   - 미설정 기본값: `cache_ttl_days=2`, `cutoff_threshold_months=0.5`, `max_searches_per_step=5`, `llm_auto_trigger=true`, `auto_fact_check=true`.
1. **키워드 감지**:
   - 태스크 spec(`§1/§2/§3`), 이전 피드백, plan 요약, IMPL_CONTEXT 초안에서 외부 의존성 키워드(라이브러리/API/프레임워크/버전/프로토콜)를 감지한다.
   - `reference.llm_auto_trigger == true`이면 키워드 매칭과 별도로 PM이 "인터넷에 최신 정보가 있을 법한 내용"이라고 판단할 때 자율적으로 WebSearch를 트리거한다.
   - `reference.llm_auto_trigger == false`이면 기존 키워드 매칭 기반 동작만 유지한다.
2. **3단계 신선도 체크**:
   - (a) `.gran-maestro/references/` 캐시 존재 확인
   - (b) TTL(`cache_ttl_days`) 기준 `fresh/stale` 판정
   - (c) cutoff 괴리(`cutoff_threshold_months`) 기준 `expired` 판정
3. **WebSearch 트리거**:
   - 캐시 없음 또는 `stale/expired` 항목만 검색 대상으로 선정.
   - 자동 검색은 `reference.auto_search == true`일 때만 수행.
   - `reference.auto_fact_check == true`이면 검색 결과의 핵심 claim을 1회성 교차 WebSearch로 경량 검증한다.
   - `reference.auto_fact_check == false`이면 기존 동작(검색 결과를 그대로 다음 단계로 전달)을 유지한다.
4. **REF 저장 (MANDATORY — WebSearch 실행 시 Bash 호출 필수)**:
   - WebSearch를 1건이라도 실행했으면, 각 검색 결과마다 반드시 `Bash`로 `mst.py reference add`를 호출해야 한다.
   - 표/텍스트 요약만으로는 저장이 완료되지 않는다 — `Bash` 도구 호출이 확인 증거다.
   - WebSearch N건 실행 → `mst.py reference add` 최소 N회 호출 (1:1 대응 원칙).
   - 저장 명령: `python3 {PLUGIN_ROOT}/scripts/mst.py reference add --topic "{topic}" --url "{url}" --summary "{summary}" --content "{핵심 요약}"`
5. **프롬프트 주입**:
   - outsource brief의 `{{IMPL_CONTEXT}}`에 아래 `[REFERENCE_CONTEXT]` 블록을 반드시 포함한다.
     ```text
     [REFERENCE_CONTEXT]
     current_date: {YYYY-MM-DD}
     model_cutoff: {cutoff_date_or_unknown}
     references:
     - REF-001 (fresh|stale|expired) {topic} | {url}
     [/REFERENCE_CONTEXT]
     ```
   - 참조가 없으면 `references: none`으로 명시한다.


### REQ ID 결정 (인자 파싱)

`$ARGUMENTS`를 파싱하여 승인 대상 REQ 리스트를 결정합니다. 아래 규칙을 위에서 아래로 순서대로 적용합니다.

#### 1. 명시적 단건 인자

`$ARGUMENTS`가 단일 REQ 패턴(`REQ-NNN`)이면 **단건 승인 프로토콜**을 직접 실행합니다. 배치 로직 미통과.

```
/mst:approve REQ-003   → [REQ-003] 단건
```

#### 2. 명시적 다건 인자

`$ARGUMENTS`에 공백 구분 REQ 패턴이 2개 이상이면 **토글 UI 없이** 직접 배치 실행합니다.

```
/mst:approve REQ-001 REQ-003 REQ-005   → [REQ-001, REQ-003, REQ-005]
```

#### 3. 콤마 구분 및 범위 지정

콤마(`,`)나 범위(`..`) 포함 인자를 파싱합니다.

```
/mst:approve REQ-001,REQ-003,REQ-005     → [REQ-001, REQ-003, REQ-005]
/mst:approve REQ-001..005                 → [REQ-001, REQ-002, REQ-003, REQ-004, REQ-005]
/mst:approve REQ-001..003,REQ-007        → [REQ-001, REQ-002, REQ-003, REQ-007]
```

범위 지정 시 **승인 가능 상태인 REQ만** 결과 리스트에 포함. 승인 불가 REQ는 무시.

#### 4. `--priority` 필터링

`--priority <level>` 플래그가 있으면 해당 우선순위의 승인 가능 REQ만 필터링합니다.

```
/mst:approve --priority high   → 승인 가능 REQ 중 priority == "high"인 것만
```

`request.json`의 `priority` 필드 기준. 필드 없는 REQ는 `normal`로 취급. `--priority`와 REQ 패턴/범위를 조합 가능.

#### 5. 인자 없이 호출 — 조건부 분기

`$ARGUMENTS`에 REQ 패턴이 없고 플래그만 있거나 완전히 비어 있는 경우:

**스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request filter --phase 1 --format json` 실행 후 `status`가 `phase1_analysis` 또는 `pending_dependency`가 아닌 것 필터링. 실패 시 fallback.

**Fallback:**
1. `{PROJECT_ROOT}/.gran-maestro/requests/` 디렉토리의 모든 `request.json` 스캔
2. 승인 가능 상태 필터링: `current_phase == 1` 이고 `status`가 `phase1_analysis` 또는 `pending_dependency`가 아닌 것 (PM 분석 완료 상태), 또는 `status`가 `phase2_spec_review`인 것
3. `--priority` 필터 있으면 추가 적용
4. REQ 번호 오름차순 정렬
5. 결과에 따라 분기:

| 승인 대기 REQ 수 | 환경 | 동작 |
|-----------------|------|------|
| 0개 | — | "승인 대기 중인 요청이 없습니다" 메시지 후 종료 |
| 1개 | — | **기존 단건 동작 그대로** (스펙 요약 → 승인 → Phase 2) |
| 2개+ | 대화형 (TTY) | **토글 선택 UI 진입** (아래 참조) |
| 2개+ | 비대화형 | **기존 동작 유지** (첫 번째 REQ 자동 선택, 단건 실행) |

#### 토글 선택 UI

승인 대기 REQ가 2개 이상이고 대화형(TTY) 환경일 때 대기 수에 따라 분기:

##### 2~4개인 경우 (기존 multiSelect UI)

`AskUserQuestion`의 `multiSelect` 옵션 사용:
- 각 옵션의 배지 생성:
  - `dependencies.blockedBy` 배열 → `[←REQ-MMM]` 형식 (선행 필요)
  - `dependencies.blocks` 배열 → `[→REQ-PPP]` 형식 (후행 대기)
  - 복합 예시: `[←REQ-MMM →REQ-PPP]`
  - 배지 없으면 생략
- `label: "REQ-NNN — {title}  [←REQ-MMM →REQ-PPP]"` (배지 있을 때)
- `description: "Phase 1 완료, 태스크 N개 | 선행: REQ-MMM | 후행: REQ-PPP"` (의존성 있을 때)
- **기본값: 전체 선택**
- 선택 후 확인 → 배치 실행. 0개 선택 시 "선택된 요청이 없습니다" 후 종료

##### 5개 이상인 경우 (전체선택 / 직접 입력 UI)

1. **목록 텍스트 출력**:
   ```
   승인 대기 중인 요청 ({N}개):
     REQ-NNN — {title}  [←REQ-MMM →REQ-PPP]  [태스크 M개]
     ...
   ```
   배지 생성 규칙 (multiSelect UI와 동일):
   - `dependencies.blockedBy` → `[←REQ-MMM]` (선행 필요)
   - `dependencies.blocks` → `[→REQ-PPP]` (후행 대기)
   - 복합: `[←MMM →PPP]` 형식으로 하나의 배지로 합산
   - 없으면 배지 생략
   예시:
   ```
     REQ-010 — DB 스키마 설계     [→REQ-011]  [태스크 2개]
     REQ-011 — API 구현           [←REQ-010 →REQ-012]  [태스크 3개]
     REQ-012 — UI 연동            [←REQ-011]  [태스크 1개]
   ```
2. **1차 AskUserQuestion** (`multiSelect: false`):
   - "전체선택" → 전체 REQ 배치 실행
   - "직접 입력" → REQ ID 직접 입력
3. **"전체선택"**: 전체 대기 REQ 배치 실행.
4. **"직접 입력"**:
   a. 목록 재출력 (참조용)
   b. **2차 AskUserQuestion**: "전체선택으로 변경" 또는 자유 입력 (`REQ-001,REQ-003` 또는 `REQ-001..005`)
   c. 빈 입력 또는 0건 → "선택된 요청이 없습니다" 후 종료
   d. 입력값을 "콤마 구분 및 범위 지정" 파싱 로직으로 처리 → 배치 실행

---

### 단건 승인 프로토콜

**AUTO_MODE 초기화** (단건 프로토콜 진입 즉시):
`AUTO_MODE = ($ARGUMENTS에 --auto 또는 -a 포함) OR (request.json.auto_approve == true)`
이후 모든 Step에서 이 변수를 사용한다.

`AUTO_MODE=true`이면 단건 프로토콜 진입 직후 workflow state를 기록한다 (non-blocking):

```bash
MST_STATE_PPID="${PPID}" python3 {PLUGIN_ROOT}/scripts/mst.py state set-workflow \
  --active true \
  --skill mst:approve \
  --req "{REQ-ID}" \
  --next-skill mst:accept \
  --next-source "{REQ-ID}" \
  --source-skill mst:approve \
  --auto true \
|| echo "[mst:approve] warning: failed to update workflow state" >&2
```

- `AUTO_MODE=false`에서는 이 호출을 실행하지 않는다.

**세션 중 자율 모드 전환**: `AskUserQuestion` 대기 중 사용자가 다음 패턴을 입력하면 즉시 `AUTO_MODE=true`로 전환합니다:
- 자연어 예시: "auto로 해줘", "자율 모드로", "-a로", "지금부터 자동으로", "이제 auto로"
- 전환 즉시 `[자율 모드 전환] 이제부터 -a 모드로 진행합니다.` 출력 후 현재 Step부터 AUTO_MODE=true 적용하여 재개

REQ 리스트가 1건이거나, 명시적 단건 인자 호출 시 이 프로토콜을 실행합니다.

1. `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/` 하위 spec.md 확인
   - **spec.md 없으면**: Phase 1 미완료. 사용자에게 알리고 PM Conductor 분석 재실행
2. 스펙 요약을 사용자에게 표시
2.3. **체인 자동 실행 제안** (조건: `dependencies.blocks` 비어있지 않음 AND `workflow.auto_approve_on_unblock == false`):
  - 조건 미충족 시 이 단계 skip, Step 2.5로 진행
  - `AUTO_MODE=true` 또는 `request.json.auto_approve=true`이면 AskUserQuestion 없이 기본값("아니오, 각 단계마다 수동 approve") 적용 후 즉시 Step 2.5로 진행 (현재 요청만 진행, 설정 변경 없음) (* auto_approve_on_unblock=false 전제, config 변경 없음)
  - 조건 충족 시 blocks 체인 시각화:
    ```
    이 REQ가 완료되면 아래 REQ들이 순서대로 실행 가능해집니다:
      REQ-NNN — {title} (대기 중)
      REQ-MMM — {title} (대기 중)  ← REQ-NNN 완료 후
    ```
    (blocks 배열의 직접 후속 REQ만 표시; 재귀 조회는 1단계만)
  - AskUserQuestion:
    - "예, 자동으로 연결 실행" → `config.json`의 `workflow.auto_approve_on_unblock`을 `true`로 업데이트
      알림: "✓ 이후 모든 체인에서 의존성 해소 시 자동 approve가 실행됩니다. (`/mst:settings workflow.auto_approve_on_unblock false`로 되돌릴 수 있습니다)"
    - "아니오, 각 단계마다 수동 approve" → 현재 요청만 진행, 설정 변경 없음
2.7. **Pre-Impl Preflight 검사 (구현 착수 전 필수)**

구현을 시작하기 전 아래 검사를 수행한다:

1. spec.md Read — 실패 시 "spec.md 읽기 실패 (경로: {spec_path}) — 워크트리 구조 확인 필요" 오류 반환 후 착수 차단.
2. spec.md 내 `"Test Scenarios (Pre-Impl)"` 문자열 **포함 검사(contains)** — `"## Test Scenarios (Pre-Impl)"` (번호 없음) 또는 `"## N.N Test Scenarios (Pre-Impl)"` (번호 있음) 모두 허용.
3. 각 automatable AC에 대해 `Test:` 항목(실행 명령 또는 확인 방법) 기입 여부 확인

**통과 조건**: 섹션 존재 + 모든 automatable AC에 Test 항목 기입
**실패 시**: 구현 착수 중단 → "Pre-Impl Test Scenarios 미작성" 오류 반환
  - failure_class: ac_unclear
  - PM에 반환: spec.md의 Test Scenarios 섹션 보완 요청

**예외**: manual AC만 있는 spec은 Test Scenarios 섹션이 비어있어도 통과 허용

preflight 검사가 통과된 경우에만 아래 Step 3(worktree 생성 및 구현 착수)로 진행.

**base_branch 안내 (비차단, preflight 통과 이후 실행)**:
- config.resolved.json에서 `worktree.base_branch` 값 읽기
  - 파일 읽기 실패 또는 키 부재 시: 경고를 **silent suppress** — 출력 없이 Step 3 진행
- `worktree.base_branch` 값이 정확히 `"main"` (대소문자 구분, exact match)인 경우에만 아래 안내 출력:

  ⚠️  base_branch가 "main"으로 설정되어 있습니다.
      모든 워크트리가 main 브랜치 기준으로 분기됩니다.
      다른 브랜치로 변경하려면:
        • /mst:on 을 다시 실행하거나
        • 대시보드 Settings → 설정 마법사 → Git 단계에서 변경하세요.

- 값이 `"main"` 이 아닌 경우: 출력 없이 진행
- 이 안내는 실행을 **절대 차단하지 않음** — 출력 후 즉시 Step 3으로 진행
- **배치 승인 모드**: 각 REQ의 preflight 통과 시마다 1회씩 출력 (base_branch는 전역 설정이나, 배치 내 첫 REQ 처리 시에만 1회 출력하도록 PM이 추적하는 것을 권장)

3. 승인 실행:
   - **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 2 phase2_execution`; 실패 시 fallback으로 `request.json`의 `current_phase`=2, `status`=`phase2_execution` 직접 업데이트
   - `strategy.worktree_policy == "skip"`이면 worktree 생성을 스킵하고 `{PROJECT_ROOT}`에서 직접 작업, 그렇지 않으면 각 태스크에 대해 git worktree 생성
   - **Phase 2 (외주 실행) 프로토콜** 실행

---

### 실행 전 의존성 검증

REQ 리스트가 2건 이상일 때, 배치 실행 루프 진입 전 선택된 REQ 집합의 의존성 위반을 검사합니다.

```pseudo
violations = []
for req_id in selected:
  req = read_request_json(req_id)
  for dep in req.dependencies.blockedBy:
    if dep not in selected:
      violations.append({ req: req_id, missing_prereq: dep })

if violations:
  출력: "⚠️ 의존성 위반 감지:"
  for v in violations:
    출력: "  - {v.req}은 {v.missing_prereq}이 먼저 완료되어야 하나 선택 목록에 없음"

  AskUserQuestion:
    - "누락된 선행 REQ 추가하여 전체 체인 실행"  → 누락 REQ를 selected에 추가 후 재진행
    - "후행 REQ 제외하고 선택된 것만 실행"      → violations의 후행 REQ를 selected에서 제거 후 재진행
    - "취소"                                   → 종료
```

위반이 없거나 사용자 선택 후 재진행 시, 아래 배치 실행 루프로 진입합니다.

---

### 배치 실행 루프

REQ 리스트가 2건 이상일 때 실행합니다.

#### 실행 모드 결정

| 플래그 | 동작 |
|--------|------|
| (기본, 플래그 없음) | **순차 실행** — 각 REQ의 전체 라이프사이클(Phase 2 → 3 → 5) 완료 후 다음 REQ |
| `--parallel` | **병렬 실행** — `concurrency.batch_max_parallel_reqs`만큼 REQ를 동시 실행 |

#### 순차 모드

의존성 토폴로지 정렬을 수행하여 Wave 단위로 실행합니다. 의존성이 없는 REQ는 단일 Wave로 묶입니다.

**topological_sort_into_waves 알고리즘:**
```pseudo
def topological_sort_into_waves(req_ids):
  # 선택된 REQ 집합 내에서만 의존성 해소
  in_degree = {r: 0 for r in req_ids}
  for r in req_ids:
    for dep in read_request_json(r).dependencies.blockedBy:
      if dep in req_ids:       # 선택 집합 내 의존성만 고려
        in_degree[r] += 1

  waves = []
  remaining = set(req_ids)
  while remaining:
    wave = [r for r in remaining if in_degree[r] == 0]
    if not wave:               # 사이클 감지
      경고: "의존성 사이클 감지, 남은 REQ는 독립 실행"
      wave = list(remaining)
    waves.append(sorted(wave))
    for r in wave:
      remaining.remove(r)
      for s in remaining:
        if r in read_request_json(s).dependencies.blockedBy:
          in_degree[s] -= 1
  return waves
```

**Wave 캐스케이드 실행:**
```pseudo
# 토폴로지 정렬로 Wave 그룹핑
waves = topological_sort_into_waves(req_list)
# Wave 예시: [[REQ-010, REQ-015], [REQ-011], [REQ-012]]
# (REQ-010, REQ-015는 독립, REQ-011은 REQ-010 완료 후, REQ-012는 REQ-011 완료 후)
# 의존성 없는 REQ만 있으면: [[REQ-001, REQ-002, REQ-003]] (단일 Wave)

출력: "실행 계획:"
for i, wave in enumerate(waves):
  출력: "  Wave {i+1}: {wave} (순차 실행)"

all_results = []
outer: for wave_num, wave in enumerate(waves):
  출력: "── Wave {wave_num+1}/{len(waves)} 시작 ──"
  wave_results = []
  for req_id in wave:
    result = 단건 승인 프로토콜 실행(req_id, AUTO_MODE=현재 AUTO_MODE 값)
    # AUTO_MODE: 배치 루프 진입 시점의 AUTO_MODE 값($ARGUMENTS --auto 포함 여부)을 단건 컨텍스트로 전달
    wave_results.append(result)
    if result == FAILED:
      오류 처리 규칙 적용 (§ 배치 오류 처리)
      if 중단 결정:
        # 현재 Wave 및 남은 모든 Wave를 skipped로 마킹
        남은 REQ (현재 Wave 미실행 + 이후 Wave 전체) → skipped
        break outer
  all_results.extend(wave_results)

  # 실패한 Wave가 있으면 후행 Wave들의 dependent REQ를 자동 Skip (실패 전파)
  failed_in_wave = [r.req_id for r in wave_results if r.status == FAILED]
  if failed_in_wave:
    이후 Wave에서 failed REQ를 blockedBy로 가진 REQ들 → 자동 Skip 마킹
    출력: "의존 REQ N개를 Skip합니다" 알림

최종 요약 출력(all_results)
```

#### 병렬 모드 (`--parallel`)

`--parallel` 플래그 사용 시에도 Wave 경계는 준수합니다. Wave 내 REQ들은 병렬 실행하고, Wave 간에는 순차 유지(선행 Wave 완료 후 후행 Wave 시작).

`config.concurrency.batch_max_parallel_reqs` 값으로 동시 실행 REQ 수를 결정합니다.

```pseudo
max_concurrent = config.concurrency.batch_max_parallel_reqs  # 기본 1
slot_guard = min(max_concurrent × avg_tasks_per_req, config.worktree.max_active)

queue = req_list.copy()
running = {}
results = []

while queue 또는 running:
  # 슬롯 여유가 있으면 큐에서 꺼내 실행
  while len(running) < max_concurrent and queue:
    req_id = queue.pop(0)

    # 의존성 체크: blockedBy에 failed REQ가 있으면 자동 Skip
    if has_failed_dependency(req_id, results):
      results.append({req_id, status: "skipped", reason: "의존 REQ 실패"})
      continue

    출력: "[진행] {req_id} — 승인 시작..."
    task = 비동기로 단건 승인 프로토콜 실행(req_id)  # run_in_background
    running[req_id] = task

  # 완료 감지 (폴링)
  for req_id, task in running:
    if task.completed:
      results.append(task.result)
      running.remove(req_id)
      출력: "[완료] {req_id} — {status}"

  sleep(backoff)

최종 요약 출력(results)
```

> **슬롯 관리**: Phase 2 내부에서 태스크 병렬 실행(Wave)이 발생. 전역 동시 태스크 수는 `min(batch_max_parallel_reqs × max_tasks_per_req, worktree.max_active)`로 제한.

#### 진행 피드백 형식

순차: `[1/3] REQ-013 "JWT 미들웨어" — 승인 중... → 실행 중... → 완료`

병렬: `[병렬 2/3] REQ-013 시작 | REQ-014 시작`

최종 요약:
```
═══ 배치 승인 완료 ═══
성공: 2  |  실패: 1  |  건너뜀: 0
REQ-015: Phase 2 사전검증 실패 (tsc error) → /mst:approve REQ-015 로 재시도
```

---

### 배치 오류 처리

#### 환경별 기본 동작

| 환경 | 기본 동작 | 세부 |
|------|-----------|------|
| **대화형 (TTY)** | **Prompt** | Continue / Skip / Retry / Abort 4지선다 제시. 기본 커서 위치: Continue |
| **비대화형 (CI)** | **Continue** | 실패 REQ는 `failed` 마킹 후 나머지 계속 진행. 최종 exit code: 실패 1건 이상이면 non-zero |

#### 의존성 기반 예외

`dependencies.blockedBy` 관계가 있는 그룹에서 선행 REQ 실패 시:
- 후속 REQ **자동 Skip** (환경 불문)
- "의존 REQ N개를 Skip합니다" 알림
- `blockedBy` 미기재 시: **독립 REQ로 취급**

#### 행동 수정자 오버라이드

`--stop-on-fail`/`--continue` 플래그가 환경 기본값을 오버라이드:
- `--stop-on-fail`: 첫 실패 시 즉시 중단 (의존성 Skip은 유지)
- `--continue`: 실패 무시 후 계속 (의존성 Skip은 유지)

#### 실패 REQ 상태 마킹

실패한 REQ의 `status`를 `failed`로 마킹. 재진입: `/mst:approve REQ-NNN` 단건 호출 또는 다음 배치 시 토글 UI 재선택.

---

### Phase 2 외주 실행 프로토콜

#### OMX 플래그 취득 (Phase 2 진입 시 1회)

OMX_AUTOPILOT = (config.omx.enabled == true && config.omx.autopilot == true)
               → config.omx 키 미존재 시 false로 처리 (fallback)

이 값을 Step 4c / Fix / Escalation에서 참조한다.

Phase 2에서 Claude(PM)는 **절대 코드를 직접 작성하지 않습니다**. 모든 구현은 `/mst:codex` 또는 `/mst:gemini`로 외주합니다.

#### 실행 전략 결정 (Phase 2 진입 시 1회, MANDATORY)

`request.json.source_plan -> plan.json.type -> type-strategies.json` 체인으로 실행 전략을 결정한다.

```pseudo
source_plan = request.json.source_plan
plan_type = "code"
if source_plan exists:
  plan = Read({PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json)
  plan_type = plan.type if plan.type exists else "code"

type_strategies = Read({PLUGIN_ROOT}/templates/defaults/type-strategies.json)
strategy = type_strategies[plan_type] || type_strategies["code"]

if Read/parse/key lookup failed:
  strategy = {
    "template": "templates/impl-request.md",
    "worktree_policy": "required",
    "review_mode": "code",
    "accept_mode": "squash-merge"
  }  # 하위 호환
```

- `plan.json` Read 실패, `type` 누락, type-strategies Read 실패/키 누락은 모두 code 전략 fallback으로 처리해 기존 코드 경로를 유지한다.
- `strategy.worktree_policy == "skip"`이면 DocExecutor 전략(문서 초안 생성 → 구조 검증 → 팩트체크)을 사용한다.

#### Step 1: 전체 태스크 스펙 일괄 검증 (외주 전 필수)

#### Step 2.7: Preflight — spec.md Read 검증

각 태스크의 spec.md를 Read하기 전 경로 유효성을 확인합니다:
- spec.md Read 실패 시: `"spec.md 읽기 실패 (경로: {spec_path}) — 워크트리 구조 확인 필요"` 오류를 반환하고 해당 태스크의 구현 착수를 차단합니다.
- Read 성공 후 아래 일괄 검증을 진행합니다.

모든 태스크의 spec.md를 일괄 검증합니다. 다음 항목이 명확한지 확인, 부족하면 보완:
- **수락 조건** (§3): AC가 pass/fail로 측정 가능한지
- **테스트 계획** (§5): 실행 명령어와 항목이 구체적인지
- **변경 범위** (§2): 수정 파일 목록 명시 여부

**Ideation 자동 트리거 (LLM 판단)**: 아래 상황 감지 시 `/mst:ideation` 호출하여 스펙 보완:
- 접근 방식 타당성 불확실 또는 대안이 더 나을 가능성
- 수락 조건 모호로 외주 에이전트 구현이 어려운 경우
- 아키텍처/보안/성능 설계 근거 부족
명백한 구현은 스킵.

#### Step 2: 의존성 분석 및 실행 계획 수립

1. 각 태스크의 `spec.md §7`에서 `blockedBy` 배열 읽기
2. 태스크 분류:
   - **독립 태스크**: `blockedBy` 비어있음 → 즉시 실행
   - **의존 태스크**: `blockedBy` 있음 → 선행 완료 후 실행
   - **단일 태스크**: 1개뿐 → 기존 순차 실행
3. 실행 계획 사용자 표시

```
Wave 1: {독립 태스크 목록} (병렬 실행)
Wave 2: {Wave 1 완료 후 실행 가능한 태스크} (병렬 실행)
Wave 3: {...}
```

#### Step 3: 실행 에이전트 결정

spec.md 헤더의 `Assigned Agent` 필드를 읽어 에이전트를 결정합니다. `agents.json`의 capabilities 기준:

| 태스크 유형 | 에이전트 | capabilities |
|------------|---------|-------------|
| 백엔드, 리팩토링, 테스트 | `codex-dev` → `/mst:codex` | code, refactor, test |
| **신규 `.ts` 파일 생성, 단순 리팩토링·보일러플레이트, 독립 테스트 작성, 소규모 `.ts` 인라인 수정** | **`codex-dev` → `/mst:codex`** | **code, refactor, test** |
| **프론트엔드, 문서, 대용량 컨텍스트** | **`gemini-dev` → `/mst:gemini`** | **frontend, docs, large-context** |
| **`.md` 문서, `.json`/`.env` config, `*.config.ts`, 기존 `.ts` 인라인 수정(신규 `.ts` 생성 없음)** | **`claude-dev` → `/mst:claude`** | **code, docs, config, small-inline** |

> **경계 케이스 기본값**: 태스크 유형이 모호한 경우 → `config.resolved.json`의 `workflow.default_agent` 값 사용 (`claude-dev` 하드코딩 금지).
> **CLI guard**: Phase 2 진입 전 Codex CLI 설치 확인 필요. `codex-dev` 배정 시 `codex` 명령어 사용 가능 여부를 사전 확인할 것.

`claude`와 `claude-dev`는 동일하게 처리됩니다 (하위 호환).

spec.md의 `Assigned Agent` 필드를 읽어 에이전트를 결정합니다: (1) `최종:` 패턴이 있으면 `최종:` 이후 값을 에이전트명으로 사용합니다. (2) `최종:` 패턴이 없으면 필드 값 전체를 에이전트명으로 사용합니다. (3) 필드가 없거나 값이 비어있으면 `config.resolved.json`의 `workflow.default_agent`를 fallback으로 사용합니다.

**`Assigned Agent: claude`/`claude-dev`인 경우**: Step 4 외주 디스패치를 통해 `/mst:claude` 서브에이전트에게 위임. PM은 직접 구현하지 않습니다.

#### Step 4: 병렬 디스패치 실행

**REQ 브랜치 생성 (태스크 수와 무관한 공통 선행 단계)**:

```bash
# master 기반으로 REQ 중간 브랜치 생성 (이미 존재하면 skip)
git show-ref --verify --quiet refs/heads/gran-maestro/REQ-NNN \
  || git checkout -b gran-maestro/REQ-NNN {config.worktree.base_branch}
```

이 브랜치는 모든 태스크 커밋의 집합점이 되며, accept 단계에서 master에 squash-merge된다.
단일 태스크 REQ에서도 반드시 이 단계를 실행해야 accept의 3단계 플로우가 정상 작동한다.

**태스크가 1개인 경우**: 기존 순차 실행과 동일 처리.

**실행 타입 분기 (if 1개, MANDATORY)**:
- `if strategy.worktree_policy == "skip"`:
  - 4a worktree 생성 단계는 스킵하고 `{PROJECT_ROOT}`에서 직접 작업한다.
  - 4b 브리프는 `templates/doc-request.md` 템플릿을 사용한다.
  - 4c 외주 지시는 코드 구현 대신 문서 작성 흐름(문서 초안 생성 → 구조 검증 → 팩트체크)으로 작성한다.
- `else` (`strategy.worktree_policy != "skip"`):
  - 아래 4a~4c 기존 절차를 그대로 수행한다. (변경 금지)

**태스크가 2개 이상이고 독립 태스크가 존재하는 경우 (`strategy.worktree_policy != "skip"`)**:

##### 4a. Worktree 일괄 생성

독립 태스크들의 git worktree를 미리 생성합니다.

태스크 worktree는 위에서 생성한 REQ 중간 브랜치를 기준으로 생성한다:

```bash
python3 {PLUGIN_ROOT}/scripts/mst.py worktree create --path {worktree_path} --branch gran-maestro/REQ-NNN-T01 --base gran-maestro/REQ-NNN
```

##### 4b. Outsource Brief 파일 작성

독립 태스크들의 브리프 파일을 **하나의 메시지에서 동시에 Write** 호출합니다.

```
Write -> {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-impl.md
```

브리프는 `templates/impl-request.md` 템플릿 사용. (`strategy.worktree_policy != "skip"` 경로)
- `{{IMPL_CONTEXT}}`: PM 작성 — 3~5줄 자유 형식 (무엇을, 왜, 어떻게 + 주의사항)
  - Step 4b 시작 시 `Reference Lookup Protocol`을 먼저 실행하고, 생성된 `[REFERENCE_CONTEXT]` 블록을 `{{IMPL_CONTEXT}}` 끝에 주입한다.
  - `reference.auto_search != true`이면 자동 WebSearch 없이 기존 REF 캐시 조회 결과만 주입한다.
  - `request.json`에 `linked_designs`가 존재하고 비어있지 않으면, `{{IMPL_CONTEXT}}` 끝에 다음 문구를 자동 추가:
    `"spec.md §10의 Stitch HTML 파일을 참조하되 기술 스택에 맞게 구현하세요."`
- `{{SPEC_PATH}}`, `{{WORKTREE_PATH}}`, `{{REQ_ID}}`, `{{TASK_ID}}`: 자동 주입
- `{{PLAN_PATH}}`: `request.json.source_plan` 존재 시 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`, 미존재 시 `"N/A"`
- `{{PREV_FEEDBACK_PATH}}`: 첫 실행 시 "N/A", 재실행 시 feedback 파일 경로

##### 4c. 독립 태스크 동시 실행

`run_in_background: true` 기반 Bash 실행 사용. (`Skill` 호출은 직렬이므로 병렬 실행 시 CLI 직접 호출 필요)

{task_dir} = {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{TASK-NUM}/

> ⚠️ **gemini-dev Bash 강제 (MANDATORY)**: gemini-dev는 단건/병렬 무관하게 **항상** `Bash(run_in_background: true)`로 실행한다.
> claude-dev 단건의 `Skill()` 패턴을 gemini-dev에 유추 적용하는 것은 금지 — `Skill(mst:gemini)` 전환 불가.
> trace는 `running.log`로 대체된다 (codex-dev와 동일 패턴).

```bash
# codex-dev인 경우 (OMX_AUTOPILOT=true 시 \$autopilot 프리픽스 삽입)
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex");
  command: 'set -o pipefail; codex exec --full-auto -m "$MODEL" -C {worktree_path} "\$autopilot $(cat {prompt_file})" < /dev/null 2>&1 | tee {task_dir}/running.log',   # OMX_AUTOPILOT=true
  # 또는:
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex");
  command: 'set -o pipefail; codex exec --full-auto -m "$MODEL" -C {worktree_path} "$(cat {prompt_file})" < /dev/null 2>&1 | tee {task_dir}/running.log',              # OMX_AUTOPILOT=false
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)
# \$autopilot: bash에서 \로 이스케이프하여 $autopilot 리터럴 문자열로 Codex/OMX에 전달
# SKILL.md는 pseudo-code이므로 조건 분기를 주석 + 두 command 예시로 표현

# gemini-dev인 경우
Bash(
  MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model gemini default 2>/dev/null);
  command: 'set -o pipefail && cd {worktree_path} && gemini -p "$(cat {prompt_file})"${MODEL:+ --model "$MODEL"} --approval-mode yolo --sandbox=false < /dev/null 2>&1 | tee {task_dir}/running.log',
  run_in_background: true,
  timeout: {config.timeouts.cli_large_task_ms}
)

# claude-dev (또는 claude)인 경우
# Wave 내 claude-dev 태스크 수 판단
if (wave_claude_task_count > 1):
  # 병렬 실행 — 기존 경로 유지 (Skill은 직렬이므로 Task 직접 호출 필수)
  Task(
    subagent_type: "general-purpose",
    prompt: {prompt_file 내용},
    run_in_background: true
  )
else:
  # 단건 실행 — Skill(mst:claude) 전환으로 trace 자동 생성 + worktree 격리
  Skill(skill: "mst:claude", args: "--trace {REQ-ID}/{TASK-NUM}/phase2-impl")
```

각 실행의 `task_id`를 `request.json`에 영구 저장:

```json
{ "background_task_ids": [{ "task_id": "{bg_task_id}", "task_num": "01", "agent": "codex-dev", "status": "running" }] }
```

> **세션 간 추적**: task_id를 기록하여 세션 전환 후에도 추적 가능. 필요 시 `TaskStop(task_id)`로 취소.

> ⚠️ **CONTINUATION GUARD**: 서브스킬 반환 후 즉시 다음 Step 진행 (hook이 자동 강제). approve는 Phase 5 완료 시에만 종료.

##### 4d. 완료 감지 루프

모든 병렬 태스크가 완료될 때까지 폴링합니다.

```pseudo
backoff = 2초
max_backoff = 30초

while (실행 중인 태스크가 있음):
  for task_id in running_tasks:
    result = TaskOutput(task_id, block: false, timeout: 5000)
    if result.status == 'completed':
      remove task_id from running_tasks
      if result.exit_code == 0:
        Step 5로 이동(사전 검증)
      else:
        mark task status = failed
        Step 4e 실패 전파 규칙 적용
        Fallback 규칙 적용(필요 시 재실행)
      해당 태스크가 선행인 후속태스크가 있으면 4e로 이동

  if running_tasks 남아있음:
    sleep(backoff)
    backoff = min(backoff * 2, max_backoff)
```

##### 4e. 의존 태스크 디스패치 (선형 의존 체인)

선행 태스크 완료 시 blockedBy 해소:
1. 후속 태스크의 `blockedBy`에서 완료 태스크 제거
2. `blockedBy` 비면 4c에 추가해 병렬 실행
3. 실패 전파: 선행 `failed`이면 후속 태스크를 `cancelled`로 전이, 즉시 사용자 알림

#### Step 5: 사전 검증 (각 완료된 태스크별)

> ⚠️ **NON-STOP EXECUTION RULE (CRITICAL)**:
> Step 5 ~ Step 6 ~ Phase 3 ~ 최종 수락까지 **중간 멈춤 없이 연속 실행**한다.
> "진행합니다", "다음 단계로 이동합니다" 등의 **텍스트만 출력하고 멈추는 것은 절대 금지**.
> 텍스트를 출력했으면 **반드시 해당 단계의 도구 호출(Bash/Edit/Skill 등)을 즉시 실행**한다.
> **서브스킬 반환 직후 강제 패턴**: 서브스킬(mst:claude, mst:codex, mst:gemini, mst:review 등)이 반환되면,
> 반환 텍스트(`[TRACE_SAVED]` 등)와 무관하게 **즉시** `NEXT_ACTION: <다음 Step 설명>` 패턴을 출력하고
> 해당 Step의 도구 호출을 실행한다. 서브스킬 반환은 종료가 아니라 **다음 단계 전환 신호**다.
> 서브스킬 반환 직후 `NEXT_ACTION` 없이 응답 종료하는 패턴을 금지한다.
> 컨텍스트 길이/대화 길이/토큰 소비량을 이유로 한 자발적 중단을 금지한다.
> Claude Code는 자동 대화 압축으로 실제 한계를 관리하므로, LLM이 이를 근거로 중단 여부를 직접 판단하지 않는다.
> 이 규칙은 이 approve 스킬의 모든 후속 Step에 적용된다.

각 태스크 완료 즉시 사전 검증 실행:
1. spec §5의 테스트 명령어 실행 (`test_output` 캡처 + exit code 확보)
2. spec §5의 타입 체크 명령어 실행 (`tsc_output` 캡처 + exit code 확보)
3. PASS/FAIL 분기 전에 `self_check` 객체를 생성하고 `request.json`의 현재 태스크(`tasks[].id == 현재 TASK_ID`)에 기록
   ```pseudo
   self_check = {
     tsc: (tsc_exit_code == 0 ? "PASS" : "FAIL"),
     test: (test_exit_code == 0 ? "PASS" : "FAIL"),
     ran_at: now_in_iso8601_utc(),
     tsc_output: tsc_output,
     test_output: test_output,
     retry_round: (request_json.pre_check_retries or 0)
   }

   try:
     req = Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/request.json)
     task = find(req.tasks, id == {TASK_ID})
     if task exists:
       task.self_check = self_check
       Write(request.json, req)
     else:
       warn("[non-blocking] self_check 저장 대상 task를 찾지 못함: {TASK_ID}")
   except err:
     warn("[non-blocking] self_check 저장 실패: {err}")
   ```
   - `self_check`가 기존 request.json에 없어도 새 필드로 추가 기록하며, 미존재 상태와 완전 하위 호환되어야 한다.
   - 저장 실패는 **non-blocking**: 경고만 출력하고 반드시 다음 분기로 진행한다.
4. 결과 분기:
   - **PASS**: `status` → `review` → **즉시 Step 5.5 실행** (PM 커밋) — 텍스트만 출력하고 멈추지 않는다
   - **FAIL**: `status` → `pre_check_failed` → **즉시 Step 5b 실행** (재외주) — 텍스트만 출력하고 멈추지 않는다

#### Step 5.5: PM 커밋 (사전검증 PASS 시)

Step 5 PASS 후 PM이 직접 커밋합니다 (외주 에이전트의 `index.lock` 문제 방지).

0. 이중 커밋 방지 체크:
   ```bash
   STATUS=$(git -C {worktree_path} status --porcelain)
   if [ -z "$STATUS" ]; then
     echo "[Step 5.5 skip] worktree가 이미 커밋된 상태 (clean). 이중 커밋 방지."
   fi
   ```
   clean이면 커밋 없이 `status` → `committed` 전환 후 Step 5.7 진행.

1. 전체 변경 스테이징 (worktree 격리로 인해 -A 사용 안전):
   ```bash
   git -C {worktree_path} add -A
   ```

2. staged 파일 중 `frontend/` 변경 자동 감지 후 빌드:
   ```bash
   FRONTEND_CHANGED=$(git -C {worktree_path} diff --cached --name-only | grep "^frontend/" | head -1)
   if [ -n "$FRONTEND_CHANGED" ]; then
     echo "frontend/ 변경 감지됨 → 빌드 실행 중..."
     cd {worktree_path}/frontend && npm install --prefer-offline && npm run build
     git -C {worktree_path} add dist/
   fi
   ```

3. PM이 커밋:
   ```bash
   git -C {worktree_path} commit -m "[{REQ_ID}/{TASK_ID}] {spec §1 요약}

   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
   ```

4. 커밋 hash/message 저장:
   ```bash
   COMMIT_HASH=$(git -C {worktree_path} log -1 --format="%H")
   COMMIT_MSG=$(git -C {worktree_path} log -1 --format="%s")
   python3 {PLUGIN_ROOT}/scripts/mst.py task set-commit {REQ_ID}-T{TASK_ID_PAD} "$COMMIT_HASH" "$COMMIT_MSG"
   ```
   - 실패 시 경고만 출력하고 워크플로우는 계속 진행.

5. 해당 태스크 `status`를 `committed`로 변경 → Step 5.7 진행. `background_task_ids` 항목 status → `"completed"` 업데이트

#### Step 5.7: 설계 의도 검증 루프 (PM 커밋 이후, Phase 3 이전)

> 이 Step은 Step 5 ~ Step 6 사이의 **NON-STOP EXECUTION RULE 적용 범위 내부**다.
> 검증 에이전트 반환 후 텍스트만 출력하고 멈추지 말고, 즉시 판정/보완/재검증 또는 Step 6 전환을 수행한다.

Step 5.5 완료 직후 아래 순서로 실행한다.

설계 문서 `.gran-maestro/agile/AGI-009/objective/details/verification-loop-design.md`의 §1~§8은 이 Step에 아래처럼 매핑된다.
- §1 전체 흐름: `5.7-0`, `5.7-2`, `5.7-3`, `5.7-5`
- §2 검증 에이전트 프롬프트 설계: `5.7-1`, `5.7-2(a)`, `5.7-2(b)`
- §3 보완 태스크 디스패치: `5.7-2(c)`
- §4 수렴 조건: `5.7-3`
- §5 모드 분기(auto/user): `5.7-2(c)` 3번
- §6 config 설정: `5.7-0` (`intent_verification.enabled`, `max_iterations`)
- §7 파일 저장 경로: `5.7-2(b)`, `5.7-4`
- §8 NON-STOP 규칙 적용: Step 5.7 헤더/`5.7-5`

##### 5.7-0. 진입 게이트 (source_plan Guard + 하위호환)

```pseudo
req = Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/request.json)
source_plan = req.source_plan
intent_cfg = Read({PROJECT_ROOT}/.gran-maestro/config.resolved.json).intent_verification or {}
intent_enabled = intent_cfg.enabled if boolean else true
max_iterations = intent_cfg.max_iterations if positive_integer else 5
all_committed = every(req.tasks[].status in ["committed", "done"])

if all_committed == false:
  # 아직 다른 태스크 커밋이 남았으면 검증 루프를 실행하지 않고 기존 흐름 유지
  goto Step 6

if source_plan is null or source_plan is empty:
  echo "[Step 5.7 skip] source_plan 없음 (--plan 없는 REQ) → Step 6 진행"
  goto Step 6

if intent_enabled == false:
  echo "[Step 5.7 skip] intent_verification.enabled=false → Step 6 진행"
  goto Step 6
```

- `--plan` 없는 REQ는 Step 5.7 **전체 skip**하며 기존 흐름(Step 5.5 → Step 6)을 유지한다.

##### 5.7-1. 비교 대상 초기화 (AD/PAC/구조 명세)

1. plan 파일 Read:
   - `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.md`
   - `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.ids.json`
2. `plan.md`에서 `## Architecture Decisions` 및 구조 명세 관련 섹션을 추출한다.
3. `plan.ids.json`에서 PAC 목록(`id`, `grade`, 설명)을 추출한다.
4. 검증 결과 저장 디렉토리 준비:
   - `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/intent-verification/`

##### 5.7-2. 반복 루프 (iteration = 1..max_iterations, 기본 5)

각 iteration마다 아래 (a)~(d)를 순서대로 실행한다.

###### (a) 검증 에이전트 디스패치

1. 템플릿 Read: `{PROJECT_ROOT}/templates/intent-verification.md`
2. 변수 치환(문자열 치환, MANDATORY):
   - `{REQ_ID}` → 현재 REQ ID
   - `{PLN_ID}` → `source_plan`
   - `{ITERATION}` → 현재 iteration 번호
   - `{WORKTREE_PATH}` → `request.json.worktree`
   - `{AD_LIST}` → plan.md AD 목록 추출 결과
   - `{PAC_LIST}` → plan.ids.json PAC 목록 추출 결과
   - `{STRUCTURE_SPEC}` → plan.md 구조 명세 추출 결과
3. 치환된 프롬프트 저장:
   - `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/intent-verification/prompt-iteration-{iteration}.md`
4. 기존 Step 5b 재외주 패턴과 동일한 실행 전략/재시도 정책으로 검증 에이전트를 디스패치한다.
   - 입력: 치환 완료 프롬프트 + `--dir {worktree_path}`
   - 출력: 설계 의도 비교 리포트(markdown, 템플릿의 `## 요약` 표 + `## 항목별 판정` + `## 보완 필요 항목` 구조 유지)

###### (b) 리포트 저장 + PM 판정

1. 리포트를 아래 경로에 즉시 저장한다 (MANDATORY):
   - `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/intent-verification/iteration-{iteration}.md`
2. 리포트의 항목별 판정을 집계한다:
   - 반영됨 / 부분반영 / 미반영
   - 반영됨: plan 결정/조건이 코드에서 관찰 가능한 형태로 구현됨
   - 부분반영: 의도는 맞지만 일부만 구현되었거나 세부 누락이 있음
   - 미반영: plan 결정/조건이 코드에 없거나 상충 구현이 존재함
3. `부분반영 + 미반영 == 0`이면 수렴으로 간주하고 루프 종료:
   - `echo "[Step 5.7 converged] 미반영 항목 0건 → Step 6 진행"`

###### (c) 보완 태스크 디스패치 (미반영 항목 존재 시)

1. `보완 필요 항목` 목록을 기반으로 단일 보완 태스크를 생성한다.
2. 보완 태스크는 기존 구현 태스크와 동일한 에이전트 배정/외주 브리프 패턴을 재사용한다.
3. 모드 분기:
   - `AUTO_MODE=true` (auto): PM 자율 판단으로 즉시 보완 디스패치
   - `AUTO_MODE=false` (user): AskUserQuestion으로 미반영 목록 제시
     - `"보완하고 재검증"`: 보완 디스패치 후 계속
     - `"남은 항목 무시하고 진행"`: 루프 종료 후 Step 6 진행
4. 보완 완료 후 PM 커밋은 **Step 5.5와 동일한 절차**(add/build-if-needed/commit/hash 저장)로 수행한다.

###### (d) 재검증 재진입

- 보완 커밋 완료 즉시 `iteration += 1` 후 Step 5.7-2 (a)로 재진입한다.
- `iteration > max_iterations`이면 루프를 종료한다.

##### 5.7-3. 종료 조건

- 수렴: `부분반영 + 미반영 == 0` → 즉시 Step 6 진행
- 한도 도달: `iteration > max_iterations` → 잔여 미반영이 있어도 Step 6 진행
- 에이전트 실행 실패: 기존 outsource 재시도 패턴(`retry.max_cli_retries`) 적용

##### 5.7-4. 최종 요약 저장 (권장)

루프 종료 시 아래 파일에 요약을 저장한다.

- `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/intent-verification/summary.md`
- 포함 항목: 총 iteration 수, 수렴 여부, 잔여 미반영 항목 목록

##### 5.7-5. Step 6 연결

- Step 5.7 종료 직후 **즉시** `Step 6: Phase 3 전환`으로 진행한다.
- "Step 6으로 이동합니다" 같은 텍스트만 출력하고 멈추는 동작은 금지한다.

#### Step 5b: 사전검증 실패 재외주 (Pre-check Failure Re-outsourcing)

Step 5 FAIL 시, PM이 직접 코드를 수정하지 않고 외주 에이전트에게 에러 컨텍스트와 함께 재요청합니다. 최대 재시도 소진 후 PM 직접 개입.

**실행 타입 분기 (if 1개, MANDATORY)**:
- `if strategy.worktree_policy == "skip"`:
  - Step 5 FAIL을 문서 검증 실패(특히 팩트체크 실패)로 해석하고, 아래 DocExecutor 재실행 루프를 우선 적용한다.
  - 최대 재시도는 고정 `2회`이며, 루프는 `팩트체크 실패 → 소스 재확인 프롬프트 생성 → 재작성` 순서를 따른다.

##### 5b-doc-1. 팩트체크 실패 항목 수집

- 직전 문서 검증 결과에서 실패 claim 목록(`failed_claims`)과 근거 부족 항목(`unverified_claims`)을 추출한다.
- 각 항목에 대해 "현재 서술 / 실패 사유 / 필요한 근거(source)"를 정리한다.

##### 5b-doc-2. 소스 재확인 프롬프트 생성

`Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-doc-fix-R{N}.md`

포함 내용:
- spec.md §3 수락 조건 (문서 품질 관련 AC 포함)
- 실패/미검증 claim 목록 + 실패 사유
- `§0 Context Manifest` 및 문서 소스 목록 재확인 지시
- "실패 claim이 포함된 섹션만 재작성 후 구조 검증 + 팩트체크를 다시 실행" 지시

##### 5b-doc-3. DocExecutor 재실행 (동일 태스크 경로)

- 동일 에이전트로 재외주를 실행한다. (`strategy.worktree_policy=="skip"` 경로이므로 `{PROJECT_ROOT}` 기준 실행)
- `request.json`에 `doc_factcheck_retries`(없으면 0)를 +1 저장한다.
- 재작성 완료 후 즉시 문서 검증(구조 검증 + 팩트체크)을 다시 실행하고 Step 5로 복귀한다.

##### 5b-doc-4. 재시도 한도 도달 시 PM 직접 개입

- `doc_factcheck_retries >= 2`이면 루프를 종료한다.
- PM이 소스 원문을 재확인해 문서를 직접 보정한 뒤, 문서 검증(구조 검증 + 팩트체크)만 재실행한다.

- `else` (`strategy.worktree_policy != "skip"`):
  - 아래 `5b-1 ~ 5b-5` 기존 코드 경로를 **그대로** 수행한다. (변경 금지)

##### 5b-1. 에러 출력 캡처

- tsc 에러: 전체 stderr/stdout 캡처
- 테스트 실패: 실패 목록 + 에러 메시지 캡처
- 에러 출력 3000자 초과 시 앞 500자 + 뒤 2500자로 트리밍

##### 5b-2. 에러 출력 포맷터 적용 (Agent-Friendly)

- 5b-1의 트리밍된 에러 출력(`TRIMMED_ERROR_OUTPUT`)에 아래 포맷터 적용:
  - `python3 {PLUGIN_ROOT}/scripts/format-precheck-errors.py`
- tsc 패턴 변환:
  - 입력: `파일경로(줄,열): error TSNNNN: 메시지`
  - 출력: `파일경로:줄 — TSNNNN — 메시지`
- 테스트 실패도 가능한 경우 동일한 구조(`대상:라인 — TEST_FAIL — 메시지`)로 변환
- **Fail-safe (필수)**:
  - 파싱 결과가 0건이거나 스크립트 실행 중 예외 발생 시 `TRIMMED_ERROR_OUTPUT`을 그대로 사용 (passthrough)
  - 이 단계의 최종 출력 변수명을 `FORMATTED_ERROR_OUTPUT`으로 사용

##### 5b-2.5. 재시도 카운터 확인

- `pre_check_retries` 필드 확인 (없으면 0)
- `config.retry.max_cli_retries` (기본 2) 미만 → 5b-3 (재외주)
- 이상 → 5b-5 (PM 직접 개입)

##### 5b-3. 에러 수정 프롬프트 생성

outsource-brief 템플릿의 `<error_context>` 섹션을 활용하여 수정 프롬프트 구성:

`Write → {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-R{N}.md`

포함 내용: spec.md §3 수락 조건, **포맷된 에러 출력(`FORMATTED_ERROR_OUTPUT`)**, "에러 수정 후 검증 명령어 실행 확인" 지침, spec §5 테스트/타입체크 명령어
- 템플릿 변수 매핑: `<error_context>`의 `{ERROR_OUTPUT}`에 `FORMATTED_ERROR_OUTPUT` 바인딩

##### 5b-4. 동일 worktree에서 재외주 실행

동일 에이전트, 동일 worktree에서 재실행:

```pseudo
# OMX_AUTOPILOT=true: $autopilot 프리픽스를 별도 파일에 기록 후 경로 전달 (파일-쓰기 방식)
# OMX_AUTOPILOT=false: 원본 프롬프트 파일 경로를 직접 전달 (인라인 이스케이프 불필요)
# 두 방식은 의도적으로 공존하며, 각각의 메커니즘이 독립적으로 동작함
if OMX_AUTOPILOT:
  fix_content = Read({PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-R{N}.md)
  fix_omx_path = {PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/tasks/{NN}/prompts/phase2-fix-omx-R{N}.md
  Write(fix_omx_path, "$autopilot\n\n" + fix_content)
  # 재시도 시 N이 달라지므로 파일명 달라짐 (덮어쓰기 발생하지 않음)
  Skill(skill: "mst:codex", args: "--prompt-file {fix_omx_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-fix-R{N}")
else:
  Skill(skill: "mst:codex", args: "--prompt-file {fix_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase2-fix-R{N}")
```

- `pre_check_retries` +1 증가
- `request.json`의 `tasks` 배열에서 현재 태스크 항목 찾기 (id 매칭):
  - 해당 항목의 `retry_count` 값 읽기 (없으면 0으로 취급)
  - `retry_count` = (현재 값) + 1 로 업데이트
- `request.json` 저장 (`pre_check_retries` + `retry_count` 동시 반영)
- Step 5 복귀 시 `self_check.retry_round`는 증가된 `pre_check_retries` 값을 사용한다.
- `status` → `executing`
- 재외주 완료 후 **즉시 Step 5 복귀** — 텍스트만 출력하고 멈추지 않는다

##### 5b-4.5. Codex Fallback 추가 시도 (5b-5 이전)

`max_cli_retries` 소진 후, PM 직접 개입 전 Codex 에스컬레이션 1회 시도:

1. **에러 유형 분류**: 에러 출력에서 컴파일/타입 오류 여부 판단
   - 환경·의존성 이슈(패키지 설치 실패, 네트워크 오류 등)이면 → 즉시 5b-5로 이동

2. **`codex_fallback_retries` 확인**: `request.json`의 `codex_fallback_retries` 값 읽기
   - `codex_fallback_retries >= 1`이면 → 즉시 5b-5로 이동 (최대 1회 한도)

3. **stash 후 Codex 에스컬레이션 실행**:
   ```bash
   git -C {worktree_path} stash
   ```
   에스컬레이션 프롬프트 준비 (`phase2-fix-R{N}.md` 기반에 `## 에스컬레이션 힌트` 섹션 추가):
   - 에러 패턴 요약
   - 영향 파일 목록
   - 전면 재작성 권장 여부
   ```bash
   # OMX_AUTOPILOT=true
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex");
   set -o pipefail; codex exec --full-auto -m "$MODEL" -C {worktree_path} "\$autopilot $(cat {escalation_prompt_path})" < /dev/null 2>&1 | tee {task_dir}/running-fallback.log
   # OMX_AUTOPILOT=false (현행 유지)
   MODEL=$(python3 {PLUGIN_ROOT}/scripts/mst.py resolve-model codex default 2>/dev/null || echo "gpt-5.3-codex");
   set -o pipefail; codex exec --full-auto -m "$MODEL" -C {worktree_path} "$(cat {escalation_prompt_path})" < /dev/null 2>&1 | tee {task_dir}/running-fallback.log
   ```

4. **결과 처리**:
   - **성공 시**: `codex_fallback_retries = 1`로 `request.json` 업데이트 → Step 5 재진입
   - **실패 시**: `git -C {worktree_path} stash pop` → 5b-5(PM 직접 개입)로 이동

##### 5b-5. PM 직접 개입 (재외주 소진 시)

재외주 횟수가 `config.retry.max_cli_retries`에 도달한 경우:

0. **실행 중 백그라운드 태스크 취소**: `background_task_ids`에서 `status: "running"` 항목을 `TaskStop(task_id)`로 취소 → `"cancelled"` 업데이트. 고아 태스크 방지.
1. PM이 에러 출력 분석 후 직접 코드 수정
2. 사전검증(Step 5) 재실행
3. PASS → `status: review` / 여전히 FAIL → 사용자 개입 요청

#### Step 6: Phase 3 전환

> 이 Step의 목적: Phase 2 완료 태스크를 Phase 3 리뷰 루프로 연결하고 결과별 후속 액션을 확정한다 / 핵심 출력물: `current_phase=3`, review 결과별 재실행/수락 분기

태스크 상태 순서: `pending → executing → pre_check → committed → done`

모든 태스크가 `committed` 상태에 도달하면 **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 3 phase3_review`; 실패 시 fallback으로 `current_phase`=3, `status`=`phase3_review` 직접 업데이트 → Phase 3 (PM 리뷰) 진입

### Phase 3 리뷰 루프 (auto_review 활성화 시)

모든 태스크가 `committed` 상태에 도달하고 `current_phase`가 3으로 전환된 후:

1. `review.auto_review` 설정 확인 (`{PROJECT_ROOT}/.gran-maestro/config.resolved.json` 읽기):
   - `AUTO_MODE`는 단건 프로토콜 진입 시 단일 초기화된 값을 그대로 사용한다 (이중 판단 금지).
   - `false` (기본): 아래 태스크 상태 검증 후 최종 수락 실행 (mst:review 미호출):
     1. `request.json.tasks` 전체 확인: 모든 태스크가 `committed` 이상 상태인지 검증
        - 태스크 상태 순서: `pending → executing → pre_check → committed → done`
        - `committed` 미만 태스크 존재 시: "태스크 {TASK_ID}가 아직 committed 상태가 아닙니다" 경고 후 대기
     2. 검증 통과 시 `workflow.auto_accept_result` 설정에 따라 즉시 실행:
        - **`true` (기본)**: `Skill(skill: "mst:accept", args: "{REQ_ID}")` 호출 → accept 완료 후 DAG 연쇄 실행 판단 (아래 "passed 분기 내 DAG 연쇄" 규칙과 동일)
        - **`false`**: Phase 3 리뷰 PASS로 간주하고 멈추고, 사용자에게 `/mst:accept {REQ_ID}`를 수동으로 호출하라고 안내
   - `true` 또는 `AUTO_MODE=true`이면 mst:review 호출 진행

#### Step 6.3: 이전 Iteration 결정 로그 복구 (iteration 2+)

> 이 Step의 목적: compaction으로 이전 맥락이 유실되었을 때 파일에서 결정 이력을 복구한다.

1. `iteration_num` = `request.json.review_iterations.length + 1` (다음 iteration 번호)
2. `iteration_num >= 2`인 경우:
   - `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/iteration-decisions/iteration-{iteration_num - 1}.md` Read
   - 파일이 없으면 skip (iteration 1이거나 이전 저장 실패)
   - 파일이 있으면 내용을 컨텍스트로 보관하여 이후 review 결과 판단 시 참조
3. `iteration_num < 2`인 경우: skip

2. mst:review 호출:
   ```
   AUTO_MODE=true  -> Skill(skill: "mst:review", args: "{REQ_ID} --auto")
   AUTO_MODE=false -> Skill(skill: "mst:review", args: "{REQ_ID}")
   ```
   (`AUTO_MODE=true`에서는 `review.auto_review=false`이더라도 항상 호출)
   > ⚠️ **반환 후 즉시 3번으로 진행** — `[TRACE_SAVED]` 텍스트 포함 여부 무관. approve는 Phase 5(mst:accept) 완료 시에만 종료.

#### Step 6.5: PM Iteration 결정 로그 저장 (Compaction 대비)

> 이 Step의 목적: compaction으로 이전 iteration 판단이 유실되어도 파일에서 복구할 수 있도록 매 iteration 끝에 결정 로그를 저장한다.

mst:review 반환 후, review 결과 처리(3번) 진입 전에 실행:

1. `iteration_num` = `request.json.review_iterations.length` (현재 iteration 번호)
2. `{PROJECT_ROOT}/.gran-maestro/requests/{REQ-ID}/iteration-decisions/` 디렉토리 생성 (없으면)
3. 아래 내용으로 `iteration-{iteration_num}.md` Write:

   ```markdown
   # Iteration {iteration_num} 결정 로그

   ## AC 상태
   {각 AC에 대해: AC-NNN: PASS/FAIL + 판단 근거 1줄}

   ## 핵심 판단
   {리뷰에서 발견된 주요 이슈에 대한 PM의 severity 동의/이의 + 결정 이유}

   ## 다음 iteration 방향
   {다음 iteration에서 집중할 AC 목록 + 추가 태스크 방향}
   ```

- Write 실패 시 warn만 출력하고 워크플로우를 차단하지 않는다 (graceful).

3. review 결과 처리:

   **review_issues_summary 로드**: 최신 `reviews/RV-NNN/review.json`을 Read → `review_issues_summary` 파싱 (critical/major/minor 카운트 + auto_fixed/skipped 배열)

   - **`status: "passed"`**: `review_summary.status → "passed"` → `workflow.auto_accept_result` 설정에 따라 즉시 실행:
     - **`true` (기본)**: 아래와 같이 accept 스킬을 명시적으로 호출:
       ```
       Skill(skill: "mst:accept", args: "{REQ_ID}")
       ```
       > ⚠️ **MANDATORY**: in-context 실행 시 Plan 상태 동기화가 생략되는 것을 방지하기 위해
       > 반드시 Skill 도구를 통해 mst:accept를 호출해야 합니다.
       accept 완료 후 아래 **DAG 자동 연쇄 실행**을 즉시 판단한다.
     - **`false`**: Phase 3 리뷰 PASS 후 멈추고, 사용자에게 `/mst:accept {REQ_ID}`를 수동으로 호출하라고 안내. 설정 변경: `/mst:settings workflow.auto_accept_result false`

     **DAG 자동 연쇄 실행** (accept 완료 직후, `auto_accept_result == true`인 경우에만 실행):

     아래 조건을 모두 충족하면 같은 plan의 후속 REQ를 자동 연쇄 실행한다.
     (`auto_accept_result == false`인 경우의 DAG 연쇄 규칙은 `mst:accept`(Step 5.6)에서 실행)

     **실행 조건**:
     1. 현재 REQ의 `request.json`에서 `source_plan`이 `"PLN-NNN"` 형태로 존재
     2. 현재 REQ의 `request.json`에서 `dag_auto_chain == true`
     3. 현재 REQ 상태가 `done` 또는 `completed` 또는 `accepted`

     하나라도 불충족이면 DAG 연쇄 실행 단계는 skip하고 기존 approve 종료 동작을 유지한다.

     **다음 REQ 탐색 규칙**:
     1. 매 반복마다 `{PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json` Read 후 `linked_requests` 전체를 plan 정의 순서대로 재평가
     2. 후보 필터:
        - 현재 REQ 및 이미 연쇄 완료(`chain_results`)된 REQ는 제외
        - 완료/종료 상태(`done`, `completed`, `accepted`, `cancelled`)는 제외
        - 실행 가능 상태(`pending_dependency`, `phase1_analysis`, `spec_ready`)만 후보로 인정
     3. `blockedBy` 해소 판정:
        - 후보 REQ의 `dependencies.blockedBy` 내 각 선행 REQ 상태를 확인
        - 모든 선행 REQ가 `done`/`completed`/`accepted`이면 "실행 가능"으로 판단
     4. 실행 가능한 첫 번째 후보를 "다음 REQ"로 선택

     **자동 연쇄 실행 루프**:
     > **컨텍스트 길이 기반 중단 금지 (MANDATORY)**:
     > 아래 루프는 컨텍스트 길이/대화 길이/토큰 소비량을 이유로 중단하지 않는다.
     > Claude Code의 자동 대화 압축이 실제 한계를 관리하므로 LLM이 자체 한계 판단으로 종료 결정을 내리지 않는다.
     > **유일한 예외는 사용자의 명시적 취소 지시**다.

     ```pseudo
     chain_results = [{ req_id: CURRENT_REQ_ID, status: "completed" }]

     while true:
       plan = Read({PROJECT_ROOT}/.gran-maestro/plans/{source_plan}/plan.json)
       next_req = first runnable req from plan.linked_requests (full scan each loop)
       if not next_req:
         break

       출력: "[DAG 연쇄] 다음 실행: {next_req.id} ({next_req.title})"
       Skill(skill: "mst:request", args: "--plan {source_plan} --resume {next_req.id} -a")

       refreshed = Read({PROJECT_ROOT}/.gran-maestro/requests/{next_req.id}/request.json)
       if refreshed.status in ["done", "completed", "accepted"]:
         chain_results.append({ req_id: next_req.id, status: "completed" })
         continue

       pending_tail = remaining non-terminal req ids in same plan
       출력: "[DAG 연쇄 중단] {next_req.id} 실패. 후속 REQ: {pending_tail.join(', ')}"
       종료

     if all linked_requests are done/completed/accepted:
       출력: "[DAG 연쇄 완료] {source_plan}의 모든 REQ가 완료되었습니다. ..."
     else:
       출력: "[DAG 연쇄 종료] 실행 가능한 다음 REQ가 없어 종료했습니다."
     ```
   - **`status: "gap_found"`**:
     `review_issues_summary`를 참조하여 이슈 등급별 분기:

     **a. CRITICAL 이슈 존재 시**: CRITICAL은 PM 직접 수정 불가, 항상 재외주. 아래 기존 재외주 경로로 진행.

     **a-2. MINOR 이슈**: `review_issues_summary.skipped`에 기록된 대로 스킵 처리, 재외주 대상에 포함하지 않음. 리포트에만 기록.

     **b. MAJOR 이슈 — PM 직접 수정 분기**:

     > **CRITICAL은 PM 직접 수정 불가, 항상 재외주**

     MAJOR 이슈 중 아래 **모든 조건**을 충족하면 PM이 worktree에서 직접 수정:

     1. **등급 조건**: MAJOR만 (CRITICAL 이슈가 동시에 존재하면 해당 CRITICAL은 반드시 재외주)
     2. **설정 조건**: `config.review.severity_auto_fix.pm_direct_fix_enabled == true`
     3. **파일 수 조건**: 변경 대상 파일 수 <= `config.review.severity_auto_fix.pm_direct_fix_max_files`
     4. **diff 크기 조건**: 예상 diff 줄 수 <= `config.review.severity_auto_fix.pm_direct_fix_max_diff_lines`
     5. **고위험 패턴 배제**: 변경 대상이 아래에 해당하지 않아야 함:
        - API 스펙 (OpenAPI/Swagger 정의)
        - DB 스키마 / 마이그레이션 파일
        - 권한(auth) 로직 / 보안 코드
        - 공통 유틸 (shared/common 모듈)

     **PM 직접 수정 조건 미충족 시** → 기존 재외주 경로(아래 c.)로 전환.

     **PM 직접 수정 절차**:

     MAJOR 이슈가 여러 개인 경우, 조건을 충족하는 이슈만 PM이 직접 수정하고 나머지는 재외주.

     1. PM이 review에서 지적된 MAJOR 이슈를 분석하고 해당 worktree에서 직접 코드 수정
     2. **검증 게이트** (PASS 필수):
        - spec §5 테스트 명령어 실행 → PASS 필수
        - spec §5 타입 체크 명령어 실행 → PASS 필수
        - **게이트 PASS**: Step 5.5와 동일한 커밋 절차 적용 (add → commit → hash 저장)
        - **게이트 FAIL**: 수정 롤백 (`git -C {worktree_path} checkout -- .`) → 해당 MAJOR 이슈에 대한 태스크를 `request.json.tasks`에 신규 생성 (`generated_by: "review"`, `status: "pending"`) → 재외주 경로(아래 c.)로 진입
     3. **메타데이터 기록**: `review-report.md`에 아래 항목 기록:
        - `pm_direct_fix: true`
        - 수정된 파일 목록
        - 수정 내용 요약 (어떤 MAJOR 이슈를 어떻게 수정했는지)

     **c. MAJOR 조건 미충족 또는 재외주 경로**:
     > ⚠️ **AUTO_MODE=true일 때 재외주는 무정지 실행**: 진행 상황 요약·AskUserQuestion 없이 즉시 아래 절차를 실행한다 — 텍스트만 출력하고 멈추지 않는다.
     1. `request.json.tasks`에서 `generated_by: "review"` + `status: "pending"` 태스크만 선별
     2. **Step 4a 포함** 재실행: 신규 태스크 worktree 생성 후 4b~4e 실행
     3. 재실행 완료 후 `current_phase → 3` 재전환 → 이 루프 반복
   - **`status: "pass_a_failed"`**:
     > 이 Step의 목적: Pass A 실패 AC 기준으로 재외주 대상을 정확히 선별한다 / 핵심 출력물: 스키마 검증된 `pass-a-result.md` 기반 재외주 태스크 목록
     > ⚠️ CRITICAL: `pass-a-result.md` 스키마 필수 필드가 하나라도 누락되면 재외주 선별을 즉시 중단하고 review 재실행을 요구한다.

     | 조건 | 동작 | 다음 단계 |
     |---|---|---|
     | `pass-a-result.md` 스키마 검증 실패 (필수 필드 누락) | `"스키마 불일치"` 출력 + `/mst:review {REQ_ID}` 재실행 안내 | 재외주 선별 중단 |
     | 스키마 검증 통과 + `covers_ac` 필드 존재(비어있지 않음) 태스크 있음 | `failed_ac_ids ∩ covers_ac` 교집합 기준으로 재외주 대상 선별 | 선별 태스크로 재외주 절차 진행 |
     | 스키마 검증 통과 + 모든 `committed` 태스크의 `covers_ac`가 없거나 빈 배열(`[]`) | 하위 호환 fallback으로 모든 `committed` 태스크를 재외주 대상으로 선별 | 재외주 절차 진행 |
     | 스키마 검증 통과 + `covers_ac` 필드는 있으나 교집합 없음 (비어있지 않은 필드 기준) | fallback 없이 빈 선별 결과 유지 | 재외주 대상 없음 상태로 분기 종료 |
     | 스키마 검증 통과 + 일부 태스크만 `covers_ac` 존재 (혼합 상태) | `covers_ac` 비어있지 않은 태스크는 교집합 기준 선별, 나머지(`covers_ac` 없거나 빈 배열)는 fallback 대상 포함 | 선별 태스크로 재외주 절차 진행 |

     재외주 태스크 선별 방법:
     1. `reviews/RV-NNN/pass-a-result.md`를 Read하여 `failed_ac_ids` 목록을 파싱한다.
     2. 파싱 직후 `templates/schemas/pass-a-result.md` 기준으로 필수 필드(`pass_a_result`, `failed_ac_ids`, `failure_class`, `evidence`) 존재 여부를 검증한다.
        - 하나라도 누락되면 `"스키마 불일치"` 오류를 출력하고, "`/mst:review {REQ_ID}`를 재실행해 pass-a-result.md를 스키마에 맞게 다시 생성하세요" 안내 후 재외주 선별을 중단한다.
     3. `request.json.tasks`의 `committed` 상태 태스크 중 `covers_ac` 필드가 있고 비어있지 않은 태스크를 대상으로,
        `failed_ac_ids ∩ tasks[i].covers_ac` 교집합이 1개 이상인 태스크를 재외주 대상으로 선정한다.
     4. fallback 조건(하위 호환): `covers_ac` 필드가 없거나 빈 배열(`[]`)인 `committed` 태스크에 대해서는
        fallback으로 재외주 대상에 포함한다.
        (`covers_ac` 필드가 비어있지 않은데 교집합이 없는 경우에는 fallback하지 않는다.)

     재외주 절차:
     > ⚠️ **AUTO_MODE=true일 때 재외주는 무정지 실행**: 진행 상황 요약·AskUserQuestion 없이 즉시 아래 절차를 실행한다 — 텍스트만 출력하고 멈추지 않는다.
     1. 선별된 태스크에 대해 `request.json.tasks`에 신규 태스크 항목 생성 (`generated_by: "review"`, `status: "pending"`)
     2. **Step 4a 포함** 재실행: 신규 태스크 worktree 생성 후 4b~4e 실행
     3. 재외주 완료 후 → `current_phase`를 3으로 재전환 → `mst:review` 재호출 (이 루프 반복)
        (gap_found 분기와 동일 구조)
   - **`status: "limit_reached"`**:
     - 일반 모드: AskUserQuestion → [추가 반복 허용 (+1회)] / [현재 상태로 수락] / [중단]
       - 추가 반복: review 재호출
       - 현재 수락: `workflow.auto_accept_result` 설정에 따라 즉시 실행 (위 `status: "passed"` 분기의 accept 호출 + DAG 연쇄 규칙과 동일)
       - 중단: `request.json.status → "cancelled"`
     - `--auto` 모드: `review_summary.status = "limit_reached"` 기록 후 `workflow.auto_accept_result` 설정에 따라 즉시 실행 (위 `status: "passed"` 분기의 accept 호출 + DAG 연쇄 규칙과 동일)

단, `--auto` 플래그 맥락: approve가 `--auto`로 실행된 경우 review 호출 시 컨텍스트로 전달됨.

#### Fallback 규칙

- 최대 깊이: 1단계 (codex → gemini, gemini → codex)
- 동일 에이전트 재시도: 최대 2회
- fallback 에이전트 재시도: 최대 2회
- 모두 실패 시: 사용자 개입 요청


## 스킬 실행 마커 (MANDATORY)

- 모든 응답의 첫 줄 또는 각 Step 시작 줄에 아래 마커를 출력한다.
- 기본 마커 포맷: `[MST skill={name} step={N}/{M} return_to={parent_skill/step | null}]`
- 필드 규칙:
  - `skill`: 현재 실행 중인 스킬 이름
  - `step`: 현재 단계(`N/M`)
  - `return_to`: 최상위 스킬이면 `null`, 서브스킬이면 `{parent_skill}/{step_number}`
- C/D 분리 마커 규칙을 추가로 사용하지 않는다. 반드시 단일 MST 마커만 사용한다.
- 서브스킬 반환 시: `step=returned` 마커에 의존하지 않는다. 서브스킬 호출(Skill 도구) 반환 자체가 전환 신호이며, 즉시 `NEXT_ACTION: <다음 Step>` 패턴을 출력하고 다음 도구 호출을 실행한다.
- 예시:
  - `[MST skill={name} step=1/3 return_to=null]`
  - 서브스킬 반환 직후: `NEXT_ACTION: Step 5 사전 검증` → 즉시 Bash/Read 등 도구 호출

## 예시

```
# 단건 승인
/mst:approve REQ-001

# 인자 없이 (대기 1건이면 단건, 2건+이면 토글 UI)
/mst:approve

# 명시적 다건 (토글 UI 스킵)
/mst:approve REQ-001 REQ-003 REQ-005

# 콤마 구분
/mst:approve REQ-001,REQ-003,REQ-005

# 범위 지정
/mst:approve REQ-001..005

# 우선순위 필터링
/mst:approve --priority high

# 배치 + 병렬 실행
/mst:approve --parallel

# 배치 + 실패 시 즉시 중단
/mst:approve --stop-on-fail

# 조합: 범위 + 병렬 + 실패 시 계속
/mst:approve REQ-010..020 --parallel --continue
```

## 문제 해결

- "승인할 스펙이 없음" → 해당 요청이 Phase 1(PM 분석) 완료 상태인지 확인. `/mst:inspect {REQ-ID}`로 상태 조회
- "이미 승인됨" → 해당 요청이 이미 Phase 2 이후에 있음. `/mst:inspect {REQ-ID}`로 현재 Phase 확인
- 최종 수락이 필요한 경우 → Phase 3 리뷰 PASS 후 `/mst:accept`를 수동 호출하거나, `workflow.auto_accept_result`를 `true`로 설정
- 배치 실패 재시도 → `/mst:approve REQ-NNN`으로 실패한 REQ만 단건 재승인
