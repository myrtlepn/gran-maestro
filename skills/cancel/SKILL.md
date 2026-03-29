---
name: cancel
description: "요청 또는 태스크를 취소하고 worktree를 정리합니다. 사용자가 '취소', '중단', '그만'을 말하거나 /mst:cancel을 호출할 때 사용."
user-invocable: true
argument-hint: "{REQ-ID} [--force]"
---

# maestro:cancel

진행 중인 요청/태스크를 취소하고 관련 리소스를 정리합니다.

## 실행 프로토콜

> **경로 규칙 (MANDATORY)**: 이 스킬의 모든 `.gran-maestro/` 경로는 **절대경로**로 사용합니다.
> 스킬 실행 시작 시 `PROJECT_ROOT`를 취득하고, 이후 모든 경로에 `{PROJECT_ROOT}/` 접두사를 붙입니다.
> ```bash
> PROJECT_ROOT=$(pwd)
> ```

1. REQ ID 파싱 → 활성 태스크 확인 → 취소 확인 프롬프트 (`--force` 아닌 경우)
2. 취소 처리: 에이전트/CLI 프로세스 종료 → `python3 {PLUGIN_ROOT}/scripts/mst.py worktree remove --path {worktree_path} [--force]` 실행 → 임시 브랜치 정리 → `status="cancelled"`
3. **Plan 상태 동기화**: `source_plan` 있으면 `python3 mst.py plan sync {source_plan}` 실행; 없으면 스킵
4. 모든 요청이 terminal 상태이고 `auto_deactivate:true`이면 Maestro 모드 자동 비활성화


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

## 옵션

- `--force`: 확인 없이 즉시 취소

## 예시

```
/mst:cancel REQ-001         # REQ-001 취소 (확인 요청)
/mst:cancel REQ-001 --force # REQ-001 즉시 취소
/mst:cancel REQ-002-01      # 특정 태스크만 취소
```

## 문제 해결

- "요청을 찾을 수 없음" → REQ ID 형식 확인; `/mst:list`로 목록 조회
- "프로세스 종료 실패" → 수동 확인; `--force`로 강제 취소
- "worktree 삭제 실패" → `.gran-maestro/worktrees/` 수동 정리; `git worktree list` 확인
