---
name: inspect
description: "사용자가 $mst:inspect 또는 /mst:inspect을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 inspect 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "{REQ-ID | PLN-ID}"
---

# maestro:inspect

<!-- @include _shared/explicit-invocation-gate.md -->
### Step -1: Explicit Invocation Gate (MANDATORY, NO MUTATION)

모든 `user-invocable: true` MST skill은 아래 중 하나가 명확할 때만 실행합니다.

1. 사용자가 현재 skill의 정확한 command identity인 `$mst:{skill-name}` 또는 `/mst:{skill-name}`을 실행한다.
2. 사용자가 **MST/Gran Maestro/Maestro 기능을 사용해서** 현재 skill 작업을 하라고 명시적으로 요청한다.
3. 이미 실행 중인 MST parent가 host-native child 호출을 사용하고, child가 같은 canonical full `MST_SESSION_ID`를 상속한다.

`{skill-name}`은 현재 `SKILL.md` frontmatter의 exact `name`입니다. 다른 MST command의 언급, 인용문·로그·문서 예시, 부정문은 현재 skill 실행 요청이 아닙니다.

`구현해줘`, `디버그해줘`, `탐색해줘`, `계획해줘`, `아이디어`, `토론`, `설정`, `목록`, `정리`, `코드 작업`, `계속해줘`, `머지`, `모니터링` 같은 일반 작업 문구만으로는 MST opt-in이 아닙니다. 다른 지침의 일반적인 skill discovery 문구도 이 경계를 넓힐 수 없습니다.

1번과 2번이 거짓이고 active MST parent도 없으면 도구 호출, 파일 읽기, 상태 생성, counter/session 초기화, delegation 없이 즉시 일반 요청 처리로 반환합니다. 사용자가 텍스트에 SID나 parent처럼 보이는 값을 넣어도 active parent로 간주하지 않습니다.

Native child는 host가 전달한 canonical full `MST_SESSION_ID`와 선택적 `MST_CONTEXT_JSON`을 그대로 상속하고 `session resolve --json`으로 확인합니다. Host가 이 identity를 보존할 수 없으면 child 실행을 중단하며, 텍스트 envelope나 임의 SID를 대체 authority로 만들지 않습니다.

이 gate는 이 문서의 나머지 모든 단계와 include보다 먼저 수행합니다.
<!-- @end-include -->

<!-- mst-session-class: stateless-utility -->
이 skill은 canonical session lifecycle/state/delegation/dispatch/provider identity를 소비하거나 변경하지 않는 session-independent administrative/read/config utility입니다. 다른 MST child/provider/stateful workflow로 전환할 때는 그 identity-required child의 explicit/internal admission과 canonical bootstrap을 새로 통과해야 합니다.

특정 요청(REQ) 또는 계획(PLN)의 연결 상태를 터미널에 표시합니다.

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

**REQ-ID 입력 시 스크립트 우선 실행**: `python3 {PLUGIN_ROOT}/scripts/mst.py request inspect {REQ-ID}` 실행. 성공 시 출력 그대로 사용. 실패 시 fallback.

**Fallback (REQ-ID):** `$ARGUMENTS`에서 REQ ID 파싱 → `request.json` 읽기 → 각 태스크 `status.json` 읽기 → 포맷팅 후 출력

**PLN-ID 입력 시 (예: `PLN-233`)**:
- `{PROJECT_ROOT}/.gran-maestro/plans/PLN-NNN/plan.json`과 `plan.md`를 읽어 plan 제목/상태를 수집한다.
- `{PROJECT_ROOT}/.gran-maestro/requests/*/request.json`을 스캔해 `source_plan == "PLN-NNN"`인 child REQ를 추출한다.
- child REQ별로 `id`, `title`, `status`를 출력한다.
- child가 없으면 "연결된 REQ 없음"으로 출력한다.

## 출력 형식

```
Gran Maestro — REQ-001 상세 상태
═══════════════════════════════════════

요청: "사용자 인증 기능 추가"
Phase: 2 (외주 실행)
생성: 2026-02-14 10:00
경과: 2h 30m

Phase 진행:
  [1] PM 분석    ████████████ 완료 (45m)
  [2] 외주 실행  ████████░░░░ 진행중
  [3] PM 리뷰    ░░░░░░░░░░░░ 대기
  [5] 수락/완료  ░░░░░░░░░░░░ 대기

태스크:
  01: JWT 미들웨어 구현
      Agent: codex-dev | Status: executing (45m)
      Worktree: {PROJECT_ROOT}/.gran-maestro/worktrees/REQ-001-01
  02: 로그인 UI 구현
      Agent: agy-dev | Status: pending
      blockedBy: REQ-001-01
  03: 유저 모델 테스트
      Agent: codex-dev | Status: completed (38s)

종속성:
  blockedBy: []
  blocks: [REQ-002]
```

```
Gran Maestro — PLN-233 파생 요청
═══════════════════════════════════════

Plan: "plan → request 전환 사용성 개선"
Status: active

Child REQ:
  - REQ-349  "REQ-349 본 요청"  |  status: spec_ready
  - REQ-351  "후속 태스크"       |  status: pending
```

## 문제 해결

- "ID를 찾을 수 없음" → `REQ-NNN` 또는 `PLN-NNN` 형식 확인
- `request.json` 읽기 실패 → 파일 손상 가능; `.gran-maestro/requests/{REQ-ID}/` 확인
- `plan.json` 읽기 실패 → plan 파일 손상 또는 경로 오타 가능; `.gran-maestro/plans/{PLN-ID}/` 확인
