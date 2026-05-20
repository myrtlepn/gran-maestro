# Release Checklist

버전을 올리고 푸시할 때 따르는 단계별 체크리스트입니다.

## 1. 버전 결정

- patch (0.2.0 → 0.2.1): 버그 수정, 매니페스트 수정
- minor (0.2.0 → 0.3.0): 새 기능, 새 에이전트/스킬 추가
- major (0.2.0 → 1.0.0): 호환성 깨지는 변경

## 2. 버전 동기화 (5파일)

아래 5개 파일의 버전을 동일하게 업데이트합니다:

```
.claude-plugin/plugin.json       → "version": "X.Y.Z"
package.json                     → "version": "X.Y.Z"
.claude-plugin/marketplace.json  → plugins[0].version: "X.Y.Z"
extension/manifest.json          → "version": "X.Y.Z"
extension/package.json           → "version": "X.Y.Z"
```

## 3. 매니페스트 정합성 확인

### Codex migration docs/release gate (DOD-012)

Codex plugin migration을 포함한 릴리스는 Claude Code plugin canonical release와 Codex generated asset 검증을 분리해서 확인합니다.

- generated Codex assets: `.codex-plugin/`, `.agents/plugins/`, `skills/`, `agents/`, `hooks/hooks.json`가 repository-local 산출물로 존재하는지 확인합니다.
- repository-local validation: 실제 Codex install/cache refresh/reload 없이 아래 명령을 실행합니다.
  ```bash
  node scripts/generate-dod-012-docs-release-integration.mjs /tmp/dod-012-docs-release-integration-check.json
  npm test
  ```
- DOD evidence linkage: `.gran-maestro/requests/REQ-921/evidence/dod-012-docs-release-integration.json`가 shared DOD registry의 DOD-012 entry와 일치하고 DOD-011 source evidence를 참조해야 합니다.
- no-go boundary: user-home mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edit, `objective.md` direct edit가 없어야 합니다.
- 5-file version sync: 기존 5파일 버전 동기화 gate를 Codex docs/release gate와 함께 확인합니다.
- DOD-013 follow-up boundary: single-source drift validation은 supporting/follow-up only로 남기고 done/accepted/completed로 승격하지 않습니다.

### agents 배열 검증

`plugin.json`의 `agents` 배열이 `agents/` 디렉토리의 모든 `.md` 파일과 일치하는지 확인합니다.

```bash
# agents/ 디렉토리 실제 파일
ls agents/*.md

# plugin.json에 선언된 agents
cat .claude-plugin/plugin.json | grep "agents/"
```

누락된 파일이 있으면 `agents` 배열에 추가합니다.

### skills 디렉토리 확인

`skills/`는 디렉토리 경로로 자동 탐색되므로 별도 매니페스트 수정 불필요.
새 스킬 추가 시 `skills/<name>/SKILL.md` 파일만 생성하면 됩니다.

### Hook 변경 체크리스트

Hook 관련 변경이 포함된 릴리스에서는 아래 항목을 함께 확인합니다:

- plugin manifest `.claude-plugin/plugin.json`의 `"hooks": "./hooks/hooks.json"` reference와 `hooks/hooks.json` 등록이 변경 의도와 일치하는지 확인합니다.
- source hooks인 프로젝트 루트 `hooks/` 원본 파일이 최종 source of truth이며, plugin core canonical runtime command가 `${CLAUDE_PLUGIN_ROOT}/hooks/...`를 가리키는지 확인합니다.
- plugin cache packaging에 source hooks와 `hooks/hooks.json`이 포함되어 캐시 버전에 반영되는지 확인합니다.
- docs/tests consistency를 위해 hook boundary 문서와 문서 테스트를 함께 갱신합니다.
- 검증 evidence는 아래 순서대로 no-injection/manifest, cleanup, hooks sync/plugin cache, worktree, global hook 축을 분리해 기록하고, skip/fail은 해당 축의 사유로 남깁니다.
- hook 변경 후 아래 검증을 실행합니다:
  ```bash
  python3 -m pytest tests/test_mst_on_no_hook_injection.py tests/test_plugin_manifest_hooks.py  # no-injection / manifest
  python3 -m pytest tests/test_mst_on_cleanup.py                                             # cleanup
  bash tests/hooks/test_sync_plugin_cache.sh                                                  # hooks sync / plugin cache
  python3 -m pytest tests/test_worktree_create_regression.py                                  # worktree
  python3 -m pytest tests/test_global_user_hooks_safety.py                                    # global hook / user-global
  ```

## 4. 빌드 검증 (src/ 변경 시)

```bash
npx tsc --noEmit
```

`npx tsc --noEmit`은 Node/core 호환 TypeScript 검증입니다. Deno dashboard/server 영역(`src/server.ts`, `src/config.ts`, `src/routes/`, `src/flow-watcher.ts` 등)을 변경한 경우 별도로 실행합니다:

```bash
deno check --no-config src/server.ts
```

## 5. 커밋 & 푸시

```bash
git add .claude-plugin/plugin.json package.json .claude-plugin/marketplace.json extension/manifest.json extension/package.json
# + 변경된 파일들
git commit -m "Release vX.Y.Z — <변경 요약>"
git push
```

## 6. 캐시 갱신 (로컬 테스트 시)

플러그인 캐시가 자동 갱신되지 않을 경우:

```bash
# 캐시 위치
~/.claude/plugins/cache/gran-maestro/gran-maestro/<version>/

# 수동 갱신: 캐시 삭제 후 플러그인 재로드
rm -rf ~/.claude/plugins/cache/gran-maestro/
# Claude Code에서 /plugin 실행으로 재로드
```
