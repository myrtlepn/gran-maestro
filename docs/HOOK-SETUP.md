# Hook 설정 가이드

## PreToolUse Hook으로 config resolve 자동 실행

Claude Code의 PreToolUse hook을 사용하면 매 Skill 실행 전 자동으로 `config resolve`를 수행하여
항상 최신 merged config를 사용할 수 있습니다.

### 설정 방법

`~/.claude/settings.json` (또는 프로젝트의 `.claude/settings.json`)에 아래 항목을 추가합니다:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Skill",
        "command": "python3 ~/.claude/plugins/cache/gran-maestro/mst/0.44.1/scripts/mst.py config resolve"
      }
    ]
  }
}
```

> **경로 확인 방법**: 위 경로의 버전 부분(`0.44.1`)은 설치된 버전에 맞게 수정하세요.
> 정확한 경로는 아래 명령어로 확인할 수 있습니다:
> ```bash
> ls ~/.claude/plugins/cache/gran-maestro/mst/
> ```

### 동작 원리

1. Claude Code가 Skill 도구를 호출하기 전 hook이 트리거됩니다
2. `mst.py config resolve`가 실행되어 `templates/defaults/config.json`(디폴트)과 `.gran-maestro/config.json`(사용자 오버라이드)를 deep merge합니다
3. 결과가 `.gran-maestro/config.resolved.json`에 기록됩니다
4. 스킬은 항상 최신 resolved config를 참조합니다

### 참고

- 대시보드 서버 실행 중에는 서버가 자동으로 resolved.json을 관리하므로 hook이 불필요할 수 있습니다

## Boundary guard 로그

워크트리 경계 가드가 PreToolUse 또는 Stop hook에서 감지, 자동 재시도, 차단을 수행하면 `.gran-maestro/logs/boundary-guard.log`에 한 줄씩 append됩니다. 각 행은 `ISO_TS | hook_name | event_type | task_id | result | message` 형식이며, 예를 들어 `2026-04-19T00:00:00Z | mst-stop-hook.sh | blocked | REQ-681 | merge_conflict | boundary_violation:merge_conflict`처럼 어떤 hook이 어떤 요청을 어떤 결과로 처리했는지 추적할 수 있습니다.

---

## PostToolUse Hook으로 스킬 완료 후 자동 정리

스킬 실행 완료 후 자동으로 세션 아카이브를 수행합니다. AI 토큰을 소비하지 않고 shell 레벨에서 실행됩니다.

### 설정 방법

`~/.claude/settings.json`에 아래 항목을 추가합니다:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Skill",
        "command": "python3 ~/.claude/plugins/cache/gran-maestro/mst/0.44.1/scripts/mst.py hooks post-skill"
      }
    ]
  }
}
```

> **경로 확인 방법**: 위 경로의 버전 부분(`0.44.1`)은 설치된 버전에 맞게 수정하세요.
> 정확한 경로는 아래 명령어로 확인할 수 있습니다:
> ```bash
> ls ~/.claude/plugins/cache/gran-maestro/mst/
> ```

### 동작 원리

1. Skill 도구 실행 완료 후 hook이 트리거됩니다
2. `mst.py hooks post-skill`이 stdin으로 PostToolUse JSON을 수신합니다
   ```json
   {
     "tool_name": "Skill",
     "tool_input": {
       "skill": "mst:accept",
       "args": "..."
     }
   }
   ```
3. 스킬명 확인: `mst:accept`, `mst:ideation`, `mst:discussion`, `mst:debug`만 대상
4. `config.resolved.json`의 `archive.auto_archive_on_complete` 확인
5. `true`이면 `archive run-all` 실행 (모든 타입 정리)

### 대상 스킬

| 스킬 | 설명 | 아카이브 트리거 |
|------|------|---------------|
| `mst:accept` | 최종 수락 (Phase 5 완료) | O |
| `mst:ideation` | 3 AI 의견 수집 완료 | O |
| `mst:discussion` | AI 팀원 토론 완료 | O |
| `mst:debug` | 병렬 디버그 리포트 완료 | O |

### 참고

- 훅 오류는 Claude Code 실행에 영향 없음 (모든 예외 삼킴)
- `archive.auto_archive_on_complete=false`로 설정하면 훅이 실행되어도 정리하지 않음
