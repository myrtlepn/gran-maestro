# agent_assignments 커스터마이징 가이드

`agent_assignments`는 에이전트별 담당 도메인을 정의합니다. request 스킬이 태스크 설명에서 도메인을 추론할 때 이 설정을 참조합니다.

## 구조

```json
"agent_assignments": {
  "에이전트명": ["도메인1", "도메인2", ...]
}
```

## 기본값

| 에이전트 | 담당 도메인 |
|----------|-------------|
| `codex-dev` | backend, skill, test, infra, docs, config |
| `gemini-dev` | frontend, ui |

Codex-primary 기본값은 docs/config도 `codex-dev`로 보냅니다. Claude Code 중심 운영을 원하면 Claude 계열 preset을 적용해 `claude-dev`에 docs/config를 재배정할 수 있습니다.

## 커스터마이징 방법

### 도메인 재배정

에이전트 담당 도메인을 변경하려면 해당 도메인을 원하는 에이전트로 이동하세요:

```json
"agent_assignments": {
  "codex-dev": ["backend", "test", "infra"],
  "gemini-dev": ["frontend", "ui", "skill"]  // skill을 gemini로 이동
}
```

### 신규 도메인 추가

새 도메인을 추가할 때는 반드시 `templates/spec.md`의 Agent Assignment 주석에 추론 예시도 함께 추가하세요.
그렇지 않으면 LLM이 새 도메인으로 추론하지 못할 수 있습니다.

## 유효한 에이전트명

| 에이전트명 | 설명 |
|------------|------|
| `codex-dev` | Codex CLI 기반 (코드 구현, 테스트) |
| `claude-dev` | Claude managed delegation 기반 legacy/fallback 에이전트 |
| `gemini-dev` | Gemini CLI 기반 (프론트엔드, UI) |

> ⚠️ 목록에 없는 에이전트명(오타 포함)은 매칭 불가로 `workflow.default_agent`로 fallback됩니다. 의도한 에이전트가 사용되지 않을 수 있으므로 정확한 이름을 사용하세요.

## 신규 에이전트 추가 시 주의사항

`agent_assignments`에 새 에이전트명(예: `"my-agent"`)을 추가하면 `skills/approve/SKILL.md`의 CLI 실행 분기도 함께 업데이트해야 합니다. approve 스킬은 에이전트명별로 다른 CLI 명령어를 실행합니다.

## fallback

`agent_assignments`에 없는 도메인으로 추론되면 `workflow.default_agent` 값이 사용됩니다.
