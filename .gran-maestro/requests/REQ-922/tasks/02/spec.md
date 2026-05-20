# Implementation Spec

- Request ID: REQ-922
- Task ID: REQ-922-02
- Created: 2026-05-20T07:13:05.000Z
- Status: pending
- Assigned Agent: [config: codex-dev] → [도메인: evidence-generator-registry] → 최종: codex-dev
- Assigned Team: codex-dev 단독 실행
- Worktree: /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/REQ-922-02
- Complexity: Standard

## §0 Context Manifest

> 구현 시작 전 이 목록의 파일을 가장 먼저 Read하세요.
> 이 목록이 완전하지 않을 수 있으며, 에이전트는 자율 탐색을 유지해야 합니다.

- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.ids.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/01/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/discussion/req-arch-decision.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-919/evidence/dod-011-migration-work-package-breakdown.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-921/evidence/dod-012-docs-release-integration.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-921/evidence/dod-012-integration-validation.json
- /Users/brandev/mygit/gran-maestro/scripts/generate-dod-012-docs-release-integration.mjs
- /Users/brandev/mygit/gran-maestro/scripts/lib/codex-plugin-discovery-smoke.mjs
- /Users/brandev/mygit/gran-maestro/tests/smoke.test.mjs

## 1. 요약 (Summary)

DOD-013 request-level evidence generator와 persisted artifact를 추가하고, shared DOD evidence registry에 validator-linked DOD-013 entry를 연결한다. 산출물은 DOD-011/DOD-012 source evidence를 입력으로 single-source drift validation 결과를 machine-readable 형태로 기록해야 한다.

## 2. 범위 (Scope)

- 포함: `scripts/generate-dod-013-single-source-drift-validation.mjs`, DOD-013 evidence builder/assertion, `.gran-maestro/requests/REQ-922/evidence/dod-013-single-source-drift-validation.json`, shared registry DOD-013 entry, source evidence refs, 5-file version sync evidence, no-go boundary evidence
- 제외: docs 본문 보강, integration validation artifact 생성, objective status 전이, 실제 Codex install/load/cache refresh, user-home mutation, `.claude/hooks` 수정, symlink 생성, plugin cache mutation
- 시작점 힌트: `scripts/generate-dod-012-docs-release-integration.mjs`, `scripts/lib/codex-plugin-discovery-smoke.mjs`, `tests/smoke.test.mjs`

## 3. 수락 조건 (Acceptance Criteria)

#### T02-AC-001 [MUST] [automatable] [evidence]
Given: DOD-013 generator가 repository-local source와 source evidence를 읽음
When: `node scripts/generate-dod-013-single-source-drift-validation.mjs /tmp/dod-013-single-source-drift-validation-check.json`를 실행함
Then: JSON artifact가 생성되고 `assertDod013SingleSourceDriftValidation` helper를 통과해야 함
Test: `node scripts/generate-dod-013-single-source-drift-validation.mjs /tmp/dod-013-single-source-drift-validation-check.json && node --input-type=module -e "import { readFileSync } from 'node:fs'; import { assertDod013SingleSourceDriftValidation } from './scripts/lib/codex-plugin-discovery-smoke.mjs'; assertDod013SingleSourceDriftValidation(JSON.parse(readFileSync('/tmp/dod-013-single-source-drift-validation-check.json','utf8')));"`

#### T02-AC-002 [MUST] [automatable] [evidence]
Given: DOD-013 성공 지표는 Codex-only fork 0개와 generated drift 0건임
When: generator가 `codex_only_fork_scan`과 `generated_drift_summary`를 기록함
Then: `fork_count: 0`, `drift_count: 0`, `status: "pass"`가 기록되고 Codex-only source fork가 새로 생성되지 않아야 함
Test: `npm test`

#### T02-AC-003 [MUST] [automatable] [evidence]
Given: 5-file version sync가 release gate임
When: generator가 5개 version source를 읽음
Then: `.claude-plugin/plugin.json`, `package.json`, `.claude-plugin/marketplace.json`, `extension/manifest.json`, `extension/package.json`의 version 값이 동일하고 evidence에 파일별 version과 `status: "pass"`가 기록되어야 함
Test: `npm test`

#### T02-AC-004 [MUST] [automatable] [evidence]
Given: single-source 유지 검증은 canonical source path coverage가 필요함
When: generator가 `canonical_source_coverage`를 기록함
Then: Claude plugin canonical source와 Codex generated/projected assets 관계가 coverage entry로 표현되고 모든 required canonical source path가 `validation_status: "pass"`여야 함
Test: `npm test`

#### T02-AC-005 [MUST] [automatable] [regression-test]
Given: DOD-013은 DOD-011/DOD-012 산출물을 입력으로 사용함
When: shared DOD evidence registry linkage를 검사함
Then: DOD-013 entry가 request evidence path, generator script path, validator export name을 포함하고 DOD-009/DOD-010/DOD-011/DOD-012 entry regression이 없어야 함
Test: `npm test`

#### T02-AC-006 [MUST] [automatable] [boundary]
Given: 검증은 repository-local로 제한됨
When: persisted DOD-013 evidence를 검사함
Then: no-go boundary violation_count가 0이고 user-home, Codex config, external install/cache/reload, symlink, plugin cache, `.claude/hooks`, `objective.md`, Codex-only fork, release publish/push mutation이 모두 pass로 기록되어야 함
Test: `npm test`

## 3.1 아키텍처 영향도 검토

- Gate: open (`risk_signal_review_required`)
- 방향: DOD-012 generator/helper 패턴을 DOD-013용으로 확장하고 shared registry entry를 validator-linked 형태로 추가한다.
- 영향 surface: `scripts/lib/codex-plugin-discovery-smoke.mjs`, `scripts/generate-dod-013-single-source-drift-validation.mjs`, `.gran-maestro/requests/REQ-922/evidence/dod-013-single-source-drift-validation.json`, `tests/smoke.test.mjs`.
- 금지: actual Codex install/cache/reload, user-home mutation, symlink, plugin cache, `.claude/hooks`, `objective.md` direct edit, release publish/push.

## 3.2 Intent Trace

| AC-ID | 의도 근거 | 근거 출처 | 신뢰도 |
|-------|-----------|-----------|--------|
| T02-AC-001 | DOD-013 generator와 assertion helper 필요 | PLN-746 PAC-1 | High |
| T02-AC-002 | Codex-only fork 0 / generated drift 0 기록 필요 | PLN-746 PAC-1 | High |
| T02-AC-003 | 5-file version sync evidence 필요 | PLN-746 PAC-1, PAC-4 | High |
| T02-AC-004 | canonical source path coverage 필요 | PLN-746 PAC-1, PAC-2 | High |
| T02-AC-005 | shared DOD registry linkage 필요 | PLN-746 PAC-3, PAC-6 | High |
| T02-AC-006 | repository-local no-go boundary 필요 | PLN-746 PAC-2 | High |

## 3.3 PAC Mapping

| PAC ID | Grade | Mapped Spec AC IDs | Coverage |
|--------|-------|--------------------|----------|
| PAC-1 | MUST | T02-AC-001, T02-AC-002, T02-AC-003, T02-AC-004 | PARTIAL |
| PAC-2 | MUST | T02-AC-002, T02-AC-004, T02-AC-006 | PARTIAL |
| PAC-3 | MUST | T02-AC-005 | PARTIAL |
| PAC-4 | MUST | T02-AC-003 | PARTIAL |
| PAC-5 | MUST | T02-AC-005, T02-AC-006 | PARTIAL |
| PAC-6 | SHOULD | T02-AC-005 | PARTIAL |

## 3.4 Epic DoD Mapping

| DoD ID | DoD 설명 | Mapped Spec AC IDs | Coverage |
|--------|----------|--------------------|----------|
| DOD-013 | migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다 | T02-AC-001, T02-AC-002, T02-AC-003, T02-AC-004, T02-AC-005, T02-AC-006 | PARTIAL |
| DOD-012 | docs/release evidence linkage regression 보존 | T02-AC-005 | PRESERVED |
| DOD-011 | migration work package source evidence | T02-AC-005 | PRESERVED |
| DOD-009 | Claude plugin regression evidence | T02-AC-005 | PRESERVED |
| DOD-010 | blocker-free migration report | T02-AC-005 | PRESERVED |

## 3.5 Constraints

- 보안: 실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits 없이 repository-local fixtures/evidence로만 검증된다.
- 운영: `.claude/hooks`, `~/.codex`, `~/.agents`, `~/.claude`, user-global config, `objective.md`를 직접 수정하지 않는다.
- evidence: `.gran-maestro/requests/REQ-922/evidence/dod-013-single-source-drift-validation.json`는 git ignore 대상이므로 PM commit 시 `git add -f`가 필요할 수 있다.

## 4. 구현 컨텍스트 (Context)

- 따라야 할 패턴: DOD-012 generator CLI output path handling, `assertDod012DocsReleaseIntegration`, shared registry DOD-012 entry.
- source evidence: DOD-011 work package breakdown, DOD-012 docs/release integration, DOD-012 integration validation.
- 접근법 방향: generator는 repository-local file reads와 deterministic summary만 수행하고 외부 Codex command를 실행하지 않는다.

## 5. 의존성 (Dependencies)

- blockedBy: [REQ-922-01]
- blocks: [REQ-922-03, REQ-922-04]
- relatedTo: REQ-919, REQ-921, PLN-746, DOD-011, DOD-012, DOD-013

## 6. 테스트 계획 (Test Plan)

- `node scripts/generate-dod-013-single-source-drift-validation.mjs /tmp/dod-013-single-source-drift-validation-check.json`
- `node --input-type=module -e "import { readFileSync } from 'node:fs'; import { assertDod013SingleSourceDriftValidation } from './scripts/lib/codex-plugin-discovery-smoke.mjs'; assertDod013SingleSourceDriftValidation(JSON.parse(readFileSync('/tmp/dod-013-single-source-drift-validation-check.json','utf8')));"`
- `npm test`

## 7. Test Scenarios (Pre-Impl)

- Generator temp output is JSON parseable and assertion helper passes.
- Persisted DOD-013 artifact matches generator contract.
- Shared registry includes DOD-013 and keeps previous DOD entries validator-linked.
- No forbidden mutation criteria are recorded as violations.

## 8. 구현 메모

- 실제 Codex command, install, cache refresh, reload, symlink creation은 금지한다.
- Git commit은 PM이 처리하며 구현 에이전트는 commit하지 않는다.
