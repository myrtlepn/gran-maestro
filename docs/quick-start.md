[한국어](quick-start.md) | [English](quick-start.en.md)

[← README로 돌아가기](../README.md)

# Quick Start

## 0. 사전 요구사항

> **프로젝트 디렉토리에서 실행하세요.** Gran Maestro는 기존 프로젝트의 코드베이스를 분석하여 동작합니다. 프로젝트 루트에서 Claude Code 또는 Codex CLI plugin runtime을 실행한 뒤 플러그인을 사용하세요.

Gran Maestro의 기본값은 Codex-primary입니다. Codex CLI는 필수이고, AGY CLI는 프론트엔드/UI 또는 대용량 컨텍스트 보조 provider를 사용할 때 설치하면 됩니다.

기존 `/mst:gemini`, `gemini`, `gemini-dev` 값은 한 릴리스 동안 deprecated alias로 동작하지만, 새 설정은 `/mst:agy`, `agy`, `agy-dev`를 사용하세요.

```bash
# Codex CLI
npm install -g @openai/codex

# AGY CLI
# Antigravity/AGY CLI를 설치한 뒤 agy --version이 동작하는지 확인하세요.
agy --version
```

**Gran Maestro는 각 CLI를 직접 호출합니다.** 별도 서버를 경유하거나 API를 중간에서 가로채지 않으며, 여러분이 직접 터미널에서 실행하는 것과 완전히 동일하게 동작합니다. 인증 정보와 데이터는 각 CLI와 해당 서비스 사이에서만 오가므로 Gran Maestro를 신뢰할 필요 없이 Codex/AGY를 신뢰하는 것으로 충분합니다.

### 각 CLI 설정이 그대로 적용됩니다

Gran Maestro는 CLI의 기능을 그대로 활용하기 때문에, 각 에이전트에 맞게 설정한 내용이 Gran Maestro 실행 중에도 동일하게 적용됩니다.

- **Codex**: 프로젝트 루트의 `AGENTS.md`, `CODEX.md` 등 에이전트 지시 파일이 Codex 호출 시 그대로 반영됩니다.
- **AGY**: AGY/Antigravity CLI가 지원하는 프로젝트 지시 파일과 로컬 설정이 AGY 호출 시 그대로 반영됩니다.

각 CLI의 개성(모델 설정, 시스템 프롬프트, 금지 동작 등)을 잘 조율해 두면 Gran Maestro 내에서도 동일한 품질과 일관성이 유지됩니다.

### 설치 후 반드시 한 번 직접 실행하세요

설치 후 **각 CLI를 직접 한 번 실행해 보세요.** 첫 실행 시 인증 플로우(로그인, API 키 등록 등)가 대화형으로 진행되며, 이 과정을 완료하지 않으면 Gran Maestro가 내부에서 CLI를 비대화형으로 호출할 때 인증 오류가 발생합니다.

```bash
codex   # 첫 실행 — 인증 플로우 완료
agy  # 첫 실행 — AGY 인증 플로우 완료
```

인증 방법:

- Codex: 첫 실행 시 대화형 로그인 또는 `OPENAI_API_KEY` 환경변수 설정
- AGY: 사용 중인 AGY CLI가 요구하는 로그인 또는 API 키 설정

> **Tip.** 설치 후 `which codex`, `which agy` 명령으로 PATH에 정상 등록되었는지도 확인하세요.

## 1. 설치

Claude Code에서 (v1.0.33 이상 필요):

```bash
# Step 1: 마켓플레이스 등록
/plugin marketplace add myrtlepn/gran-maestro

# Step 2: 플러그인 설치
/plugin install mst@gran-maestro
```

또는 `/plugin` 명령으로 UI를 열어 **Discover** 탭에서 직접 설치할 수도 있습니다.

### 업데이트

```bash
/plugin marketplace update gran-maestro
```

### 삭제

```bash
/plugin uninstall mst@gran-maestro
```

### Claude/Codex plugin 설치·업데이트·삭제·검증

Claude Code와 Codex는 같은 git 저장소를 marketplace source로 사용합니다. Claude Code는 skills/agents/hooks를 등록하고, Codex는 같은 skill source를 hookless plugin surface로 등록해 동일한 plan → request → approve → review → accept 흐름을 제공합니다. 기본 위임 설정은 Codex-primary이며, Claude provider는 Claude 계열 preset 또는 `claude-dev` 배정으로 opt-in합니다. 실제 사용자 환경은 각 CLI에서 명시적으로 관리합니다.

1. **설치 준비**: `.claude-plugin/`, `.codex-plugin/`, `.agents/plugins/`, root `marketplace.json`, `plugins/mst`, `skills/`, `agents/`, `hooks/hooks.json` 같은 repository-local 산출물을 검토합니다.
2. **설치**: Claude Code와 Codex CLI에서 같은 git source를 로드합니다.
   ```bash
   /plugin marketplace add myrtlepn/gran-maestro
   /plugin install mst@gran-maestro

   codex plugin marketplace add myrtlepn/gran-maestro
   codex plugin add mst@gran-maestro
   ```
   Gran Maestro 검증은 사용자 환경의 Claude/Codex install/cache refresh/reload를 자동 실행하지 않습니다.
3. **업데이트**: 릴리스 전 `npm test`와 아래 DOD-012 generator를 실행해 docs/release coverage를 확인한 뒤 사용자 환경 업데이트는 별도로 수행합니다.
4. **삭제**: 사용자 소유 plugin 등록과 캐시를 사용자가 직접 제거합니다. repository validation은 uninstall/cache 삭제 명령을 자동 실행하지 않습니다.
5. **검증**:
   ```bash
   node scripts/claude-plugin-local-install-smoke.mjs
   node scripts/codex-plugin-local-install-smoke.mjs
   node scripts/codex-plugin-git-source-readiness.mjs
   node scripts/generate-dod-012-docs-release-integration.mjs /tmp/dod-012-docs-release-integration-check.json
   npm test
   ```
   git source publish 이후에는 `node scripts/claude-plugin-local-install-smoke.mjs --source myrtlepn/gran-maestro`와 `node scripts/codex-plugin-local-install-smoke.mjs --source myrtlepn/gran-maestro`로 같은 설치 경로를 검증합니다.

DOD-012 검증 중에는 `~/.codex/config.toml`, `~/.agents`, `~/.claude`, plugin cache, symlink, `.claude/hooks`, `objective.md`를 수정하지 않습니다.

## Stitch MCP 설정 (선택)

`/mst:stitch`로 UI 목업을 생성하려면 Claude Code에 Stitch MCP를 먼저 추가해야 합니다.

Stitch는 Google의 UI 설계 도구입니다. `/mcp add` 명령 또는 Claude Code MCP 설정을 통해 추가한 뒤, Gran Maestro에서 활성화합니다:

```
/mst:settings stitch.enabled true
```

> **Tip.** Gran Maestro 기본값은 `stitch.enabled: true`입니다. Stitch MCP만 추가하면 별도 설정 없이 바로 사용할 수 있습니다.

## 2. 시작 — 워크플로우 체인

Gran Maestro의 핵심은 **plan → request → approve → review → accept** 체인입니다.

### 골든 패스: request → list → approve

가장 빠른 경로입니다. 요청을 바로 구현 스펙으로 변환하고 실행합니다.

```
/mst:request "JWT 기반 사용자 인증 기능을 추가해줘"
/mst:list                        # 요청 현황 확인
/mst:approve REQ-001             # 스펙 승인 → Codex/AGY가 구현 시작
```

### plan 분기: 요구사항이 모호할 때

요구사항이 복잡하거나 결정이 필요한 경우, `/mst:plan`으로 먼저 정제합니다.

```
/mst:plan "로그인 화면 개선해줘"   # Q&A로 요구사항 정제 → plan.md 생성
/mst:request                     # plan을 구현 스펙으로 변환
/mst:approve REQ-001             # 승인 → 구현 시작
```

> **Tip.** plan은 여러 개를 먼저 만들고 `/mst:approve PLN-001 PLN-002`로 일괄 승인할 수 있습니다.

### review → accept: 구현 완료 후

구현이 끝나면 리뷰하고 머지합니다.

```
/mst:review REQ-001              # AC 기준 다중 AI 검증
/mst:accept REQ-001              # 머지 + worktree 정리
```

> **Tip.** `/mst:approve -a`로 자율 모드를 사용하면 review → accept까지 자동으로 진행됩니다.

> **Tip.** 세션이 끊겼다면 `/mst:recover`로 미완료 요청을 이어서 진행할 수 있습니다.

## 3. 대시보드

```
/mst:dashboard
```

브라우저에서 실시간 대시보드를 열어 다음을 확인할 수 있습니다:

- **현황 모니터링** — 모든 요청·태스크의 Phase별 진행 상태
- **인라인 편집** — plan, spec, 피드백을 대시보드에서 직접 수정
- **실시간 추적** — 에이전트 실행 로그와 결과를 라이브로 확인

## 4. 주요 명령어 요약

| 명령어 | 설명 |
|--------|------|
| `/mst:plan` | Q&A로 요구사항을 정제하여 실행 가능한 플랜 생성 |
| `/mst:request` | 플랜 또는 직접 입력을 구현 스펙으로 변환 |
| `/mst:approve` | 스펙 승인 후 Codex/AGY 개발팀에 자동 전달 |
| `/mst:review` | AC 기준 다중 AI 검증 리뷰 |
| `/mst:dashboard` | 대시보드 서버 시작 및 브라우저 열기 |
| `/mst:recover` | 세션 종료 후 미완료 요청 복구 |

> 전체 스킬 목록은 [스킬 레퍼런스](skills-reference.md)를 참조하세요.

## 5. 트러블슈팅

**인증 실패 (`Authentication error`)** — Codex/AGY CLI를 직접 한 번 실행하여 인증 플로우를 완료하세요. `codex` 또는 `agy` 명령으로 대화형 로그인을 먼저 마쳐야 합니다.

**CLI를 찾을 수 없음 (`command not found`)** — `which codex`, `which agy`로 PATH에 등록되었는지 확인하세요. 글로벌 설치가 안 되어 있다면 `npm install -g @openai/codex @google/agy-cli`를 실행합니다.

**플러그인 미로드 (`plugin not found`)** — Claude Code 버전이 v1.0.33 이상인지 확인하세요. `/plugin marketplace add myrtlepn/gran-maestro` 후 `/plugin install mst@gran-maestro`를 다시 실행합니다.

## 6. 다음 단계

- [설정 관리](configuration.md) — config.json 전체 옵션 레퍼런스
- [베스트 프랙티스](best-practices.md) — 효율적인 워크플로우 패턴
- [스킬 레퍼런스](skills-reference.md) — 35개 이상 스킬 상세 사용법
- [대시보드](dashboard.md) — 허브 구조, 뷰, API 엔드포인트
- [Chrome Extension 설치](extension-setup.md) — 브라우저 캡처 확장 설치 가이드
