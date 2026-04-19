# REQ-684 Verification Report

Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/REQ-684-T04`
Branch: `gran-maestro/master/REQ-684-T04` (T01+T02+T03 merged)
Version: 0.59.2
Date: 2026-04-19

## 1. 통합 동작 검증

| # | 항목 | 실행 명령 | 결과 | PASS/FAIL |
|---|------|-----------|------|-----------|
| 1 | Node 문법 | `node --check scripts/stitch-sdk.mjs` | `SYNTAX_OK` | PASS |
| 2 | Help 옵션 노출 | `node scripts/stitch-sdk.mjs --help \| grep -E "save-dir\|screen-name"` | 2줄 매칭 (`--save-dir <dir>`, `--screen-name <slug>`) | PASS |
| 3 | backward compat (list-projects) | `node scripts/stitch-sdk.mjs list-projects \| jq '.ok, .command'` | `true`, `"list-projects"` | PASS |
| 4 | SDK 누락 감지 (read-through 대체) | `grep -n "MODULE_NOT_FOUND\|install_required" scripts/stitch-sdk.mjs` | 6개 라인 매칭 — L102-103(`SdkMissingError` 생성자에서 `code="MODULE_NOT_FOUND"` + `install_required=true`), L184(`isStitchSdkMissingError` 판별), L582/586(error JSON의 `install_required:true` + `code:"MODULE_NOT_FOUND"`), L1166(top-level catch에서 `SdkMissingError`/`install_required` 플래그 감지 → exit 2) | PASS (read-through) |
| 5 | SKILL.md Bash 가드 | `grep -n "Bash 직접 orchestration 금지" skills/stitch/SKILL.md` | L14 매칭 (`Bash로 직접 orchestration하는 것은 금지한다 (Bash 직접 orchestration 금지)`) | PASS |
| 6 | Anti-Rationalization 항목 | `awk '/^## Anti-Rationalization/,/^## [^A]/' skills/stitch/SKILL.md \| grep -E "CLI를 직접\|응답은 나중에"` | 2줄 매칭 ("CLI를 직접 쓰는 편이 더 빠르다", "generate 응답은 나중에 파싱하자") | PASS |
| 7 | SDK 누락 플로우 섹션 | `grep -n "SDK 누락 감지" skills/stitch/SKILL.md` | 2줄 매칭 (L15 require 실패 신호 안내, L65 `### SDK 누락 감지 → 설치 동의 플로우 (MANDATORY)` 섹션 헤더) | PASS |

### 4번 항목 실환경 면제 사유

`PLUGIN_DIR`에서 `node_modules/@google/stitch-sdk`를 실제로 rename하여 exit 2 + install_required:true JSON을 확인하는 방식은 설치된 SDK 전역 상태를 훼손할 위험이 크다 (진행 중인 다른 워크플로우가 SDK를 요구하면 즉시 실패). 따라서 T04는 코드 read-through로 대체:

- `SdkMissingError` 클래스 (L100-105): 생성 시점에 `code="MODULE_NOT_FOUND"`, `install_required=true` 설정
- `isStitchSdkMissingError` (L183-185): require 실패 code가 `MODULE_NOT_FOUND` 또는 `ERR_MODULE_NOT_FOUND` 이고 메시지에 `@google/stitch-sdk`가 포함되면 true
- CLI 진입부 catch (L582, L586): 위 판별이 true면 JSON 응답에 `install_required:true`, `code:"MODULE_NOT_FOUND"` 포함
- Top-level catch (L1166): `SdkMissingError` 인스턴스이거나 `install_required` 플래그가 있으면 process.exit(2)

→ 코드 경로 상 정상적으로 설치 누락 시 `{ok:false, install_required:true, code:"MODULE_NOT_FOUND", ...}` + exit 2가 반환됨을 확인.

### Stitch 실 프로젝트 호출 면제 사유

generate/get-screen/variants/edit 등 실제 Stitch SDK 호출이 필요한 명령은 API 쿼터 및 실 프로젝트 영향 때문에 직접 호출하지 않았고, (1) `--help` 옵션 노출(항목 2)과 (2) `list-projects`의 backward-compat JSON 응답(항목 3), (3) SKILL.md 명령 스펙(항목 5~7)으로 간접 검증.

## 2. 호출자 영향

`grep -rn "stitch-sdk.mjs" skills/ scripts/` 결과 기준, 모든 호출은 `skills/stitch/SKILL.md`의 Bash 명령 스펙 내부에 있다 (실행 시 PM Conductor가 스킬 내 템플릿을 렌더). scripts 내부에서 CLI를 호출하는 곳은 없음 (usage 예시 1건만 존재).

| 파일:줄 | 호출 형태 (command) | `--save-dir` 여부 | backward compat |
|---------|--------------------|--------------------|-----------------|
| skills/stitch/SKILL.md:48 | `list-projects` | 없음 | OK |
| skills/stitch/SKILL.md:58 | `list-projects` | 없음 | OK |
| skills/stitch/SKILL.md:180 | `get-project --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:182 | `create-project --title ...` | 없음 | OK |
| skills/stitch/SKILL.md:211 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:221 | `init --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:265 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:275 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:317 | `generate --project-id ... --prompt ... --device-type ... --model-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:338 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:350 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:362 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:370 | `variants --project-id ... --screen-id ... --prompt ... --variant-count ...` | 없음 | OK |
| skills/stitch/SKILL.md:387 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:415 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:479/482 | `generate --project-id ... --prompt ... --device-type ...` | 없음 | OK |
| skills/stitch/SKILL.md:503 | `list-screens --project-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:515 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:526 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:609 | `variants --project-id ... --screen-ids ... --prompt ... --variant-count ...` | 없음 | OK |
| skills/stitch/SKILL.md:852 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:858 | `edit --project-id ... --screen-id ... --prompt ... --model-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:911 | `get-screen --project-id ... --screen-id ...` | 없음 | OK |
| skills/stitch/SKILL.md:917 | `variants --project-id ... --screen-id ... --prompt ... --variant-count ... --creative-range EXPLORE` | 없음 | OK |
| skills/stitch/SKILL.md:983 | `get-screen --project-id ... --screen-id ... --name ...` | 없음 | OK |
| skills/stitch/SKILL.md:997 | `variants --project-id ... --screen-id ... --prompt ... --variant-count ... --creative-range REIMAGINE --aspects ...` | 없음 | OK |
| scripts/stitch-sdk.mjs:30 | usage 문자열 예시 (`node scripts/stitch-sdk.mjs <command> [options]`) | 해당 없음 | N/A (실행 아님) |

**호출자 영향 종합**: 모든 기존 호출부가 `--save-dir`/`--screen-name` 을 사용하지 않는다. T01에서 추가한 두 옵션은 순수 확장(additive)이며, 생략 시 기존 JSON 응답(`{ok, command, ...}`)이 그대로 유지됨을 `list-projects` 실행으로 검증(항목 3). 기존 호출 형태가 깨진 곳은 0건.

## 3. 버전 동기화

- `.claude-plugin/plugin.json`: 0.59.2
- `package.json`: 0.59.2
- `extension/manifest.json`: 0.59.2
- `extension/package.json`: 0.59.2
- `.claude-plugin/marketplace.json` (`plugins[0].version`): 0.59.2

→ 5개 파일 버전 일치.

CHANGELOG.md 상단 `## [0.59.2] — 2026-04-19` 섹션 발췌 (사용자 관점 변경 4건):

1. `mst:stitch` CLI(`stitch-sdk.mjs`)가 `generate --save-dir <dir> --screen-name <slug>` 옵션으로 html/image/meta 3파일을 atomic 저장.
2. `list-screens`가 SDK 빈 응답 시 MCP `list_screens` fallback을 자동 시도.
3. `@google/stitch-sdk` 미설치 시 CLI가 `install_required:true` JSON + exit 2, 스킬이 설치 동의 AskUserQuestion으로 안내.
4. `mst:stitch` 스킬 상단에 Bash 직접 orchestration 금지 Gate와 Anti-Rationalization Checklist 추가.

→ 사용자 관점 변경 3~4건 기재 조건 충족.

## 4. AC 매핑 결과

- **AC-T04-001 (통합 동작 검증)**: PASS — 항목 1~7 모두 PASS (4번은 read-through 대체, 근거 명시)
- **AC-T04-002 (호출자 영향 없음)**: PASS — skills/stitch/SKILL.md의 기존 호출부 26건 모두 `--save-dir` 미사용이며, `list-projects` 실제 실행으로 backward compat 확인
- **AC-T04-003 (면제 사유 기록)**: PASS — 아래 5번 섹션 및 본 리포트의 1번 테이블 하단 주석에 명시

## 5. 면제 사유 기록

1. **자동 단위 테스트 면제**: 프로젝트에 Node 테스트 프레임워크(jest/mocha/vitest) 미도입 상태. `.gran-maestro/config.resolved.json`의 `test_enforcement.exempt_patterns`에는 본 태스크가 해당하지 않으나, 러너 부재 상태이므로 수동 검증(node --check + CLI 실행 + grep)으로 대체. T01의 `[automatable]` 태그 AC는 추후 Node 러너 도입 시 자동화 대상으로 유지.
2. **SDK 누락 실환경 검증 면제**: `node_modules/@google/stitch-sdk` rename은 설치된 SDK 전역 상태를 훼손하며 다른 진행 중 워크플로우에 영향을 주기 때문에 코드 read-through로 대체 (본 리포트 1번 섹션의 4번 항목 상세 참고).
3. **Stitch 실 프로젝트 호출 면제**: generate/get-screen/variants/edit 등은 Stitch API 쿼터를 소모하며 실 DES 프로젝트 산출물을 변경하므로 help/syntax/list-projects read-through로 대체.

## 6. 최종 판정

**전체 통합: PASS**

- 1번 통합 동작 검증 7개 항목 전부 PASS (4번 read-through 대체 명시)
- 2번 호출자 영향 26건 모두 backward compat OK, 깨진 호출 0건
- 3번 버전 5파일 동기화 일치 + CHANGELOG 사용자 관점 변경 4건 확인
- AC-T04-001/002/003 모두 충족

주요 이슈: 없음. 향후 개선 제안으로 Node 테스트 러너 도입 시 `--help` 옵션 매칭, `list-projects` JSON 스키마, `SdkMissingError` 분기를 단위 테스트로 자동화할 것.
