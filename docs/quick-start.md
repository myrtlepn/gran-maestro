[한국어](quick-start.md) | [English](quick-start.en.md)

[← README로 돌아가기](../README.md)

# Quick Start

## 0. 사전 요구사항

> **프로젝트 디렉토리에서 실행하세요.** Gran Maestro는 기존 프로젝트의 코드베이스를 분석하여 동작합니다. 프로젝트 루트에서 Claude Code 또는 Codex CLI plugin runtime을 실행한 뒤 플러그인을 사용하세요.

Gran Maestro의 기본값은 Codex-primary와 `same-host-native-first`입니다. Codex host → Codex provider 또는 Claude Code host → Claude provider 위임은 host의 native agent를 먼저 사용하므로, 같은 host 위임만을 위한 별도 provider CLI 설치는 필요하지 않습니다. 단, Codex plugin 자체를 실행하려면 Codex runtime이 필요합니다.

기존 `/mst:gemini`, `gemini`, `gemini-dev` 값은 한 릴리스 동안 deprecated alias로 동작하지만, 새 설정은 `/mst:agy`, `agy`, `agy-dev`를 사용하세요.

External lane을 사용할 계획이라면 해당 provider CLI만 선택적으로 설치하고 인증하세요.

```bash
# 선택: external Codex lane
npm install -g @openai/codex

# 선택: AGY provider는 항상 external lane
# Antigravity/AGY CLI를 설치한 뒤 확인하세요.
agy --version
```

### Native-first와 external lane

| 예시 | 기본 경로 | 추가 provider CLI |
|------|-----------|-------------------|
| Codex host → Codex provider | Codex collaboration native agent | 같은 host 위임만으로는 불필요 |
| Claude Code host → Claude provider | Claude Task/Agent | 같은 host 위임만으로는 불필요 |
| Codex host → Claude provider 또는 Claude Code host → Codex provider | managed external wrapper | 대상 provider CLI 필요 |
| headless, `external-only`, native 비활성/scope 제외/capability unavailable | managed external wrapper | 대상 provider CLI 필요 |
| AGY provider | managed external wrapper | AGY CLI 필요 |

External route에서 대상 CLI를 찾지 못하면 `blocked`(`missing_cli`)로 fail-closed 처리합니다. Native spawn 뒤에는 host가 task 미생성을 확정한 경우에만 external fallback합니다. Spawn 승인/provider task ID 이후 attach 실패·timeout·결과 불명·취소 미확인은 `reconciling`으로 남기고, 새 native spawn과 external 중복 실행을 모두 차단합니다. Native task 자체의 실패도 다른 transport로 자동 재실행하지 않습니다.

기존 project-local `delegation.native_codex_subagents.enabled: false`는 opt-out으로 계속 읽고 canonical 설정으로 migration할 수 있습니다. 새 설정에서 external wrapper만 사용하려면 다음 canonical 키를 사용하세요.

```
/mst:settings delegation.transport_policy external-only
/mst:settings delegation.native.enabled false
```

### External CLI를 선택했다면 한 번 직접 실행하세요

External lane에 사용할 CLI는 설치 후 한 번 직접 실행해 인증을 완료하세요. Native same-host 경로만 사용한다면 이 단계는 건너뛸 수 있습니다.

```bash
codex   # external Codex lane을 사용할 때만
claude  # external Claude lane을 사용할 때만
agy     # AGY provider를 사용할 때
```

External wrapper는 별도 프록시 서버를 거치지 않으며 대상 CLI의 인증과 로컬 설정을 그대로 사용합니다. 프로젝트 루트의 `AGENTS.md`/`CODEX.md` 같은 Codex 지시 파일과 AGY/Claude CLI가 지원하는 프로젝트 설정도 해당 external 실행에 적용됩니다. 설치 후 `which codex`, `which claude`, `which agy` 중 사용할 CLI가 PATH에 등록됐는지 확인하세요.

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
