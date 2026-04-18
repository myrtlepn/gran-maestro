---
name: list
description: "모든 요청 및 태스크의 현황 목록을 표시합니다. 사용자가 '현황', '상태 보여줘', '목록'을 말하거나 /mst:list를 호출할 때 사용. 특정 요청의 상세 상태는 /mst:inspect를 사용."
user-invocable: true
argument-hint: "[--all | --active | --completed]"
---

# maestro:list

모든 Gran Maestro 요청과 태스크의 현황을 터미널에 표시합니다.

## 실행 프로토콜

> **`{PLUGIN_ROOT}` 경로 규칙**: `{PLUGIN_ROOT}`는 이 스킬의 "Base directory"에서 `skills/{스킬명}/`을 제거한 **절대경로**입니다. 상대경로(`.claude/...`)는 절대 사용하지 않습니다.

**스크립트 우선 실행**: `python3 {PLUGIN_ROOT}/scripts/mst.py request list --active` 실행. 성공(exit 0)이면 출력을 사용하되, 각 REQ의 `source_plan` 필드를 확인해 `"[from PLN-NNN]"` 태그를 보강한다. 실패 시 아래 fallback으로 진행.

**Fallback:** `requests/` 스캔 → 각 `request.json` 읽기 → 상태별 분류/포맷팅
- 출력 규칙:
  - `source_plan == "PLN-NNN"`이면 REQ 제목 줄에 `"[from PLN-NNN]"` 태그를 표시
  - `source_plan == null` 또는 필드 부재(레거시)면 태그를 표시하지 않음


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

## 출력 형식

```
Gran Maestro — 요청 현황
═══════════════════════════════════════

REQ-001  "사용자 인증 기능 추가" [from PLN-233]
  Phase: 2 (외주 실행)  |  Tasks: 3  |  진행: 1/3
  ├── 01: [codex] 실행 중 — JWT 미들웨어 구현
  ├── 02: [gemini] 대기 — 로그인 UI 구현
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
