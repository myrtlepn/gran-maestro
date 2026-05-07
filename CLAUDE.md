# Gran Maestro — Project Instructions

> 플러그인 세계관 및 스킬 레퍼런스: [docs/CLAUDE.md](docs/CLAUDE.md)
> 릴리스 체크리스트: [docs/RELEASE.md](docs/RELEASE.md)

## Hook 책임 경계 및 수정 규칙 (CRITICAL)

MST hook runtime은 3계층으로 구분합니다:

1. **Plugin core canonical runtime**: `.claude-plugin/plugin.json`의 `"hooks": "./hooks/hooks.json"`와 `hooks/hooks.json`의 `${CLAUDE_PLUGIN_ROOT}/hooks/...` command가 일반 프로젝트의 유일한 canonical MST core hook 등록 경로입니다.
2. **Project legacy / source repo 개발 보조**: `.claude/hooks/mst-*.sh` 또는 `$CLAUDE_PROJECT_DIR/.claude/hooks/...`에 남아 있는 사본은 일반 프로젝트 canonical runtime이 아닙니다. 이 저장소에서 source 개발·레거시 호환·cleanup/doctor 진단 대상으로만 취급합니다.
3. **User-global environment hooks**: `~/.claude/settings.json`의 `maestro-guard.sh`, `log-prompt.sh`, `check-version.sh` 등은 사용자 전역 환경 hook 계층이며 MST core SessionStart/Stop hook이 아닙니다.

`.claude/hooks/` 파일은 **직접 수정 금지**. `/mst:on`은 일반 프로젝트에 `.claude/hooks` 사본이나 `settings.local.json` hooks block을 canonical runtime으로 주입하면 안 됩니다.

이 플러그인의 MST core hook을 수정하려면 최종 source of truth는 `/Users/brandev/mygit/gran-maestro/hooks/` 하위 파일입니다.

Hook 수정이 필요할 때는 반드시 아래 순서를 따릅니다:

1. **`hooks/` 원본 수정**: 프로젝트 루트의 `hooks/` 디렉토리 파일을 수정
2. **canonical 등록 확인**: `.claude-plugin/plugin.json`의 `"hooks": "./hooks/hooks.json"`와 `hooks/hooks.json`의 `${CLAUDE_PLUGIN_ROOT}/hooks/...` command가 변경 의도와 일치하는지 확인
3. **source repo 보조 사본 동기화가 필요한 경우에만 복사**: 이 저장소의 legacy/source-dev 진단을 위해 필요한 경우 `cp hooks/*.sh .claude/hooks/` 실행. 일반 프로젝트 `/mst:on` 동작으로 해석하지 않습니다.
4. **플러그인 캐시에 복사**: 릴리스/검증 목적상 필요한 버전에 `cp hooks/*.sh ~/.claude/plugins/cache/gran-maestro/mst/{버전}/hooks/` 및 legacy 보조가 필요한 경우에만 `cp hooks/*.sh ~/.claude/plugins/cache/gran-maestro/mst/{버전}/.claude/hooks/`
5. **커밋**: `hooks/`와 실제로 동기화한 보조 사본 변경사항을 함께 커밋

```
hooks/                    ← 플러그인 소유 원본 및 canonical command 대상 (수정 대상)
hooks/hooks.json          ← plugin core canonical hook registration
.claude/hooks/            ← source repo legacy/source-dev 보조 사본 (일반 프로젝트 canonical runtime 아님)
~/.claude/settings.json   ← user-global environment hook 계층 (MST core hook 아님)
```

## 프로젝트 구조

```
.claude-plugin/
  plugin.json        # 플러그인 매니페스트 (버전, agents, skills)
  marketplace.json   # 마켓플레이스 메타데이터 (버전)
package.json         # npm 패키지 (버전)
agents/              # 커스텀 에이전트 정의 (.md)
skills/              # 스킬 디렉토리 (자동 탐색)
src/                 # TypeScript 소스
docs/                # 문서
```

## 버전 관리 (5파일 동기화 필수)

버전은 아래 5개 파일에서 **반드시 동일하게** 유지해야 합니다:

| 파일 | 필드 |
|------|------|
| `.claude-plugin/plugin.json` | `version` |
| `package.json` | `version` |
| `.claude-plugin/marketplace.json` | `plugins[0].version` |
| `extension/manifest.json` | `version` |
| `extension/package.json` | `version` |

## 버전업 요청 처리

### 전체 버전업 (CHANGELOG 포함, 기본)

사용자가 버전업을 요청하면 다음 순서로 처리합니다:

1. **미커밋 변경사항 확인**: `git status`로 커밋되지 않은 변경사항이 있으면 먼저 커밋
2. **버전 결정**: 변경 범위에 따라 적절한 버전을 선택 (patch: 버그 수정/소규모 변경, minor: 기능 추가/개선, major: 호환성 깨지는 변경)
3. **bump 스크립트 실행**: `python3 scripts/bump.py <patch|minor|major>`
   - 5파일 버전 자동 수정 + 직전 버전 이후 git log 출력
4. **CHANGELOG.md 업데이트**: 스크립트가 출력한 git log를 참고하여 `CHANGELOG.md` 상단에 새 버전 섹션 추가
   - `## [X.Y.Z] — YYYY-MM-DD` 헤더
   - `### 새 기능` / `### 개선` / `### 버그 수정` 섹션 (해당 항목만 포함)
   - 각 항목은 **사용자 관점**에서 체감할 수 있는 변화를 서술 (내부 리팩토링 제외)
5. **버전업 커밋**: `Bump version to X.Y.Z` 메시지로 커밋 (CHANGELOG.md 변경 포함)
6. **푸시**: `git push origin master`

### 버전 bump만 (푸시 없이)

사용자가 "bump만", "버전만 올려", "푸시 없이" 등으로 요청하면:

1. **미커밋 변경사항 확인**: 위와 동일
2. **bump 스크립트 실행**: `python3 scripts/bump.py <patch|minor|major>`
3. **CHANGELOG.md 업데이트**: 위와 동일
4. **버전업 커밋**: `Bump version to X.Y.Z` 메시지로 커밋 (CHANGELOG.md 변경 포함)

## 기능 변경 시 필수 고려사항

기능이 추가·변경·삭제되면, 요청받은 내용 외에 아래 항목의 수정 필요 여부를 반드시 검토합니다:

1. **대시보드 변경점**: 대시보드 UI에 표시되는 데이터·화면·동작이 영향받는지 확인, 해당 시 `frontend/` 수정 및 빌드
2. **config 변경**: `config.json`/`config.resolved.json`에 키 추가·변경·삭제가 필요한지 확인
   - config 키가 변경되면 대시보드 Settings의 해당 탭 UI도 반드시 동기화
   - 기본값이 필요한 경우 `templates/defaults/config.json`도 함께 수정
3. **상태머신 영향**: `mst.py`, `scripts/mst_cmds/`, `scripts/_skill_state.py`, `hooks/`, `skills/`의 continuation/auto/resume/stop/session/history/snapshot 동작이 바뀌면 소스만 수정하지 말고 상태머신 계약도 함께 갱신합니다.
   - 가능한 state/transition/guard/evidence/on_reject가 바뀌면 machine-readable transition graph(YAML/JSON)와 D2/dashboard generated view 갱신 필요 여부를 확인합니다.
   - `auto=true`, Stop hook, PreToolUse, context compaction, skill 종료, resume/recover, `MST_SESSION_ID` 전파 규칙이 바뀌면 AGI-030 objective/details의 state-history-recovery 계약과 관련 테스트를 함께 맞춥니다.
   - 정상 경로에서는 full state를 LLM prompt에 매번 주입하지 않고 hook/validator가 로컬에서 상태머신 계약 이탈만 검사하며, 이탈 시에만 structured continuation block을 전달한다는 원칙을 유지합니다.
4. **README 업데이트**: 사용자 대면 기능이 변경된 경우 `README.md`의 관련 섹션 수정

## 커밋 & 푸시 체크리스트

커밋/푸시 요청 시 아래를 반드시 확인합니다:

1. **버전 동기화**: 5개 파일의 버전이 일치하는지 확인
2. **agents 배열**: `plugin.json`의 `agents`가 `agents/` 디렉토리 내 모든 `.md` 파일을 나열하는지 확인
3. **신규 파일 누락**: 새로 추가된 agent/skill 파일이 매니페스트에 반영되었는지 확인
4. **TypeScript (core)**: `npx tsc --noEmit`으로 Node/core 호환 TypeScript 타입 오류 없는지 확인 (src/ 변경 시)
5. **TypeScript (dashboard)**: Deno dashboard/server 영역(`src/server.ts`, `src/config.ts`, `src/routes/`, `src/flow-watcher.ts` 등) 변경 시 `deno check --no-config src/server.ts`로 별도 검증
6. **대시보드 빌드**: `frontend/` 변경 시 `frontend/` 디렉토리에서 `npm run build`로 빌드 후 `dist/`(프로젝트 루트)를 함께 커밋

## plugin.json 규칙

- `skills`: 디렉토리 경로 허용 (`"./skills/"`)
- `agents`: **파일 경로 배열만 허용** (디렉토리 경로 불가)
  ```json
  "agents": [
    "./agents/pm-conductor.md",
    "./agents/architect.md"
  ]
  ```

## 커밋 메시지 컨벤션

```
<요약> (<버전>)

<상세 설명 (선택)>

```
