---
name: intent
description: "기능 의도(Intent) 문서를 자연어로 빠르게 생성/조회/수정/삭제합니다. 사용자가 'intent', '의도 저장', '의도 조회'를 말하거나 /mst:intent를 호출할 때 사용."
user-invocable: true
argument-hint: "{add|get|list|update|delete|search|lookup|related|rebuild ...}"
---

# maestro:intent

기능 의도(INTENT) 레지스트리를 관리합니다.

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

> **스크립트 우선 실행**: `python3 {PLUGIN_ROOT}/scripts/mst.py intent ...` 를 그대로 호출합니다.

### Step 1. Smart Landing (`/mst:intent`만 호출)

1. `python3 {PLUGIN_ROOT}/scripts/mst.py intent list --json` 실행
2. intent 개수에 따라 분기

- **0개인 경우**
  - 아래 메시지를 그대로 안내
    - `아직 저장된 intent가 없습니다.`
    - `예시: /mst:intent add 로그인 기능 - 사용자가 접근할 때 인증이 필요`
    - `예시: /mst:intent add 결제 기능 - 구매 완료 시 결제 처리가 필요해서 안전한 거래 보장`
- **1개 이상인 경우**
  - 최근 5개를 요약해서 보여주고 아래 액션 제시
    - `무엇을 하시겠어요? add / search / get INTENT-NNN / list`

### Step 2. 자연어 `add` 파싱

입력 예시:
- `/mst:intent add 로그인 기능 - 사용자가 접근할 때 인증 필요`
- `/mst:intent add 결제 기능 - 구매 완료 시 결제 처리가 필요해서 안전한 거래 보장`

파싱 규칙:
1. `add` 뒤의 자연어를 `feature`, `situation`, `motivation`, `goal`로 분해
2. 하이픈(`-`)은 구분자이지만 기능명 자체에도 포함될 수 있으므로 문맥 기준으로 분리
3. `motivation`이 비어 있으면 `goal` 값을 그대로 사용
4. 저장 전 반드시 1줄 확인 출력
   - `이렇게 저장할게요: feature=X, situation=Y, motivation=Z, goal=W`
5. 확인 후 실행
   - `python3 {PLUGIN_ROOT}/scripts/mst.py intent add --feature "X" --situation "Y" --motivation "Z" --goal "W"`

### Step 3. 파싱 실패 fallback

필드 분리가 불가능하면 아래 힌트를 출력하고 재입력을 유도한다.

- `파싱에 실패했습니다. 아래 포맷으로 다시 시도해주세요: add 기능 | 상황 | 동기 | 목표`

### Step 4. 관리 명령

- 추가: `python3 {PLUGIN_ROOT}/scripts/mst.py intent add --feature "기능명" --situation "..." --goal "..." [--motivation "..."] [--req REQ-NNN] [--plan PLN-NNN]`
- 조회: `python3 {PLUGIN_ROOT}/scripts/mst.py intent get INTENT-001`
- 목록: `python3 {PLUGIN_ROOT}/scripts/mst.py intent list [--req REQ-001] [--plan PLN-001]`
- 수정: `python3 {PLUGIN_ROOT}/scripts/mst.py intent update INTENT-001 [--feature "..."] [--situation "..."] [--motivation "..."] [--goal "..."] [--req REQ-001] [--plan PLN-001]`
- 삭제: `python3 {PLUGIN_ROOT}/scripts/mst.py intent delete INTENT-001`
- 검색: `python3 {PLUGIN_ROOT}/scripts/mst.py intent search "키워드"`
- 파일 역조회: `python3 {PLUGIN_ROOT}/scripts/mst.py intent lookup --files src/foo.py`
- 연관 탐색: `python3 {PLUGIN_ROOT}/scripts/mst.py intent related INTENT-001 --depth 2 --json`
- DB 재구성: `python3 {PLUGIN_ROOT}/scripts/mst.py intent rebuild`

## 문제 해결

- `No module named 'yaml'` 오류: `pip install pyyaml`
- `Intent not found`: `/mst:intent list`로 ID 확인 후 재시도
- 검색 결과 없음: `intent rebuild` 실행 후 다시 조회
