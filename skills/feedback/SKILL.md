---
name: feedback
description: "Gran Maestro 워크플로우 내에서 수동 피드백을 제공합니다 (Phase 4). 사용자가 진행 중인 요청에 대해 '피드백'을 말하거나 /mst:feedback을 호출할 때 사용. 일반적인 코드 수정 요청이나 워크플로우 외부의 '수정해줘', '변경해줘'에는 사용하지 않음."
user-invocable: true
argument-hint: "{REQ-ID} {피드백 내용}"
---

# maestro:feedback

사용자가 직접 피드백을 제공하여 Phase 4(피드백 루프)를 트리거합니다.

## 필수 입력 스키마

mst:feedback 실행 시 아래 정보를 반드시 제공해야 합니다:

- `failure_class`: `ac_unclear | interpretation | implementation` 중 하나 (필수)
  - `ac_unclear`: AC/spec 자체가 모호하거나 불완전한 경우
  - `interpretation`: 구현 의도와 실제 결과가 불일치한 경우
  - `implementation`: 올바른 의도로 구현했으나 실행 오류가 발생한 경우
- `evidence`: AC-ID 매핑 배열 (최소 1개 필수). 각 항목은 아래 필드를 포함해야 함:
  - `ac_id`: 관련 AC ID (예: `AC-01`). `spec.md`의 AC-ID와 일치해야 함. 불일치 시 경고를 표시하고 PM이 확인하도록 안내함 (차단은 아님). `ac_id`가 누락된 경우 경고를 표시하며 차단 여부는 PM이 판단함.
  - `type`: `log | screenshot | metric | manual`
  - `ref`: 증거 경로 또는 설명
  - `summary`: 실패 내용 요약
- `next_action`: 재작업 지시 내용 (구현 방법을 지시하지 않고, 어느 AC/기준을 복구해야 하는지만 명시)

**스키마 검증 규칙 (차단):**
- `failure_class`가 제공되지 않았거나 허용값(`ac_unclear | interpretation | implementation`) 외의 값이면 → 오류를 반환하고 피드백 저장 및 전파를 차단함
- `evidence` 배열이 비어 있거나 제공되지 않았으면 → "evidence가 없으면 판정 불가" 오류를 반환하고 차단함

## 실패 분류별 자동 라우팅

라우팅 기준: `templates/protocols/failure-routing.md` 참조

## 실행 프로토콜

<!-- @include _shared/path-rules.md -->
> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```
>
> `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.
<!-- @end-include -->

1. `$ARGUMENTS`에서 REQ ID + 피드백 내용 파싱
   > 이 Step의 목적: 피드백 대상 요청과 입력 본문을 식별한다 / 핵심 출력물: 유효한 `REQ-ID`와 원본 피드백 텍스트
2. Feedback Composer 활성화 → 구조화된 피드백 문서 변환 → `tasks/NN/feedback-RN.md` 저장
   > 이 Step의 목적: 자유 입력 피드백을 실행 가능한 포맷으로 정규화한다 / 핵심 출력물: `feedback-RN.md`
3. 실패 유형 분류 및 라우팅:
   > 이 Step의 목적: 실패 원인을 `failure_class`로 고정하고 후속 경로를 결정한다 / 핵심 출력물: `failure_class` 기반 라우팅 결정

   라우팅 기준: `templates/protocols/failure-routing.md` 참조
4. 피드백 라운드 카운터 증가; 최대 횟수(기본 5회) 초과 시 사용자 개입 요청
   > 이 Step의 목적: 반복 피드백 루프의 상한을 관리한다 / 핵심 출력물: 증가된 피드백 라운드 카운터와 초과 시 개입 신호

### 외주 재실행 프로토콜 (구현 오류 시)

**반드시 `/mst:codex` 또는 `/mst:gemini`를 통해 외주. Claude(PM) 직접 코드 수정 금지.**

1. spec.md에서 `Assigned Agent` 확인
2. 수정 프롬프트 구성: spec.md §3 수락 조건 + feedback-RN.md 수정 요청 + §5 테스트 명령
3. 외주 실행:
   - codex-dev → `Skill("mst:codex", "--dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
   - gemini-dev → `Skill("mst:gemini", "--dir {worktree_path} --files {worktree_path}/**/* --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
   - claude-dev → `Skill("mst:claude", "--prompt-file {prompt_path} --dir {worktree_path} --trace {REQ-ID}/{TASK-NUM}/phase4-fix-R{N}")`
4. **스크립트 우선**: `python3 {PLUGIN_ROOT}/scripts/mst.py request set-phase {REQ_ID} 2 phase2_execution`; 실패 시 fallback으로 `current_phase`=2, `status`=`phase2_execution` 직접 업데이트 → 완료 후 사전 검증 → Phase 3
5. **외주 재실행 완료 후 Phase 3 복귀**:
   - **자동 실행 경로**: approve 스킬이 활성 상태(approve 루프)인 경우, Phase 3(mst:review)은 approve 루프에서 자동으로 재트리거됨
   - **수동 실행 경로**: feedback이 독립 호출된 경우, 재작업 완료 후 `/mst:approve REQ-NNN`을 수동으로 호출해 Phase 3을 재시작해야 함


<!-- @include _shared/skill-execution-marker.md -->
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
<!-- @end-include -->

## 문제 해결

- "해당 요청을 찾을 수 없음" → REQ ID 형식 확인; `/mst:list`로 조회
- "최대 피드백 횟수 초과" → `/mst:settings workflow.max_feedback_rounds` 확인; 값 증가 또는 `/mst:request`로 스펙 재작성
- "활성 태스크 없음" → `/mst:inspect {REQ-ID}`로 Phase 2~3 여부 확인
