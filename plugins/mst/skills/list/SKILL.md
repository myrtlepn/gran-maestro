---
name: list
description: "사용자가 $mst:list 또는 /mst:list을 명시적으로 호출하거나 MST/Gran Maestro/Maestro의 list 기능 사용을 명시적으로 요청한 경우에만 실행합니다. 일반 요청에는 자동 활성화하지 않습니다."
user-invocable: true
argument-hint: "[--all | --active | --completed]"
---

# maestro:list

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

모든 Gran Maestro 요청과 태스크의 현황을 터미널에 표시합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

**스크립트 우선 실행**: `python3 {PLUGIN_ROOT}/scripts/mst.py request list --active` 실행. 성공(exit 0)이면 출력을 사용하되, 각 REQ의 `source_plan` 필드를 확인해 `"[from PLN-NNN]"` 태그를 보강한다. 실패 시 아래 fallback으로 진행.

**Fallback:** `requests/` 스캔 → 각 `request.json` 읽기 → 상태별 분류/포맷팅
- 출력 규칙:
  - `source_plan == "PLN-NNN"`이면 REQ 제목 줄에 `"[from PLN-NNN]"` 태그를 표시
  - `source_plan == null` 또는 필드 부재(레거시)면 태그를 표시하지 않음

## 출력 형식

```
Gran Maestro — 요청 현황
═══════════════════════════════════════

REQ-001  "사용자 인증 기능 추가" [from PLN-233]
  Phase: 2 (외주 실행)  |  Tasks: 3  |  진행: 1/3
  ├── 01: [codex] 실행 중 — JWT 미들웨어 구현
  ├── 02: [agy] 대기 — 로그인 UI 구현
  └── 03: [codex] 완료 — 유저 모델 테스트

REQ-002  "로그인 페이지 디자인"
  Phase: 1 (PM 분석)  |  blockedBy: REQ-001-02
  └── 스펙 작성 중...

═══════════════════════════════════════
활성: 2  |  완료: 0  |  전체: 2
```

## 옵션

- `--all`: 완료된 요청 포함 전체 목록
- `--active`: 활성 요청만 (기본값)
- `--completed`: 완료된 요청만

## 문제 해결

- `requests/` 디렉토리 없음 → `/mst:on` 또는 `/mst:request`로 활성화
- 빈 목록 → `--all`로 완료/취소 요청 포함 확인
