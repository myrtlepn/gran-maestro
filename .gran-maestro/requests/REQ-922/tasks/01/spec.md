# Implementation Spec

- Request ID: REQ-922
- Task ID: REQ-922-01
- Created: 2026-05-20T07:13:05.000Z
- Status: pending
- Assigned Agent: [config: codex-dev] → [도메인: single-source-validator-contract] → 최종: codex-dev
- Assigned Team: codex-dev 단독 실행
- Worktree: /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/REQ-922-01
- Complexity: Standard

## §0 Context Manifest

> 구현 시작 전 이 목록의 파일을 가장 먼저 Read하세요.
> 이 목록이 완전하지 않을 수 있으며, 에이전트는 자율 탐색을 유지해야 합니다.

- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.ids.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/discussion/req-arch-decision.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/agile/AGI-039/objective/details/migration-execution-breakdown.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-919/evidence/dod-011-migration-work-package-breakdown.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-921/evidence/dod-012-docs-release-integration.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-921/evidence/dod-012-integration-validation.json
- /Users/brandev/mygit/gran-maestro/scripts/lib/codex-plugin-discovery-smoke.mjs
- /Users/brandev/mygit/gran-maestro/tests/smoke.test.mjs

## 1. 요약 (Summary)

DOD-013 single-source drift validation이 evidence artifact 없이 완료 처리되지 않도록, smoke surface와 assertion helper contract를 먼저 고정한다. 이 contract는 Codex-only fork 0개, generated drift 0건, 5-file version sync 유지, canonical source path coverage, DOD-012 linkage regression 보존을 검증해야 한다.

## 2. 범위 (Scope)

- 포함: DOD-013 evidence schema assertion, Codex-only fork scan assertion, generated drift summary assertion, 5-file version sync assertion, canonical source path coverage assertion, no-go boundary assertion, shared registry DOD-009/DOD-010/DOD-011/DOD-012/DOD-013 linkage assertion
- 제외: persisted DOD-013 artifact 생성, docs 본문 보강, objective status 전이, 실제 Codex install/load/cache refresh, user-home mutation, `.claude/hooks` 수정, symlink 생성, plugin cache mutation
- 시작점 힌트: `tests/smoke.test.mjs`, `scripts/lib/codex-plugin-discovery-smoke.mjs`

## 3. 수락 조건 (Acceptance Criteria)

#### T01-AC-001 [MUST] [automatable] [tdd-required] [regression-test]
Given: DOD-013 request-level evidence artifact가 생성될 예정임
When: smoke test가 DOD-013 evidence를 검증함
Then: evidence는 `request_id: "REQ-922"`, `agi_id: "AGI-039"`, `sprint: 15`, `dod_id: "DOD-013"`, `status: "pass"`, `codex_only_fork_scan`, `generated_drift_summary`, `five_file_version_sync`, `canonical_source_coverage`, `source_evidence_refs`, `shared_registry_linkage`, `no_go_boundary`를 포함해야 함
Test: `npm test`

#### T01-AC-002 [MUST] [automatable] [tdd-required] [regression-test]
Given: DOD-013 성공 지표는 Codex-only fork 0개와 generated drift 0건임
When: assertion helper가 single-source evidence를 검사함
Then: `codex_only_fork_scan.fork_count`는 `0`, `generated_drift_summary.drift_count`는 `0`, 각 세부 entry는 repository-local generated/projected asset과 Claude canonical source 관계를 기록해야 함
Test: `npm test`

#### T01-AC-003 [MUST] [automatable] [tdd-required] [regression-test]
Given: 버전은 5파일 sync를 유지해야 함
When: assertion helper가 `five_file_version_sync`를 검사함
Then: `.claude-plugin/plugin.json`, `package.json`, `.claude-plugin/marketplace.json`, `extension/manifest.json`, `extension/package.json`의 version 값이 모두 동일하고 evidence에 파일별 version이 기록되어야 함
Test: `npm test`

#### T01-AC-004 [MUST] [automatable] [tdd-required] [regression-test]
Given: Codex 산출물은 Codex-only source fork가 아니라 Claude canonical source에서 projected/generated되어야 함
When: assertion helper가 `canonical_source_coverage`를 검사함
Then: `.claude-plugin/plugin.json`, `skills/`, `agents/`, `hooks/`, `templates/defaults/`, package/version files 같은 canonical source path가 coverage entry로 존재하고 각 entry가 Codex generated/projected asset과 연결되어야 함
Test: `npm test`

#### T01-AC-005 [MUST] [automatable] [tdd-required] [regression-test]
Given: DOD-013은 DOD-011/DOD-012 산출물 위에 쌓여야 함
When: smoke test가 shared DOD registry를 검사함
Then: DOD-009, DOD-010, DOD-011, DOD-012 linkage regression 없이 DOD-013 entry가 validator-linked 형태로 보존되어야 함
Test: `npm test`

#### T01-AC-006 [MUST] [automatable] [tdd-required] [regression-test]
Given: 검증은 repository-local fixture/evidence로 제한됨
When: assertion helper가 `no_go_boundary`를 검사함
Then: 실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits, `objective.md` direct edit, Codex-only fork creation, release push/publish/GitHub release 없이 검증되어야 함
Test: `npm test`

## 3.1 아키텍처 영향도 검토

- Gate: open (`risk_signal_review_required`)
- 방향: DOD-013 single-source evidence contract를 smoke surface에 먼저 고정하고 후속 태스크가 generator/artifact/docs evidence를 통과시키게 한다.
- 영향 surface: `tests/smoke.test.mjs`, `scripts/lib/codex-plugin-discovery-smoke.mjs`, future DOD-013 request evidence artifact.
- 금지: user-home mutation, Codex external install/cache/reload, symlink, plugin cache, `.claude/hooks`, `objective.md` direct edit, Codex-only fork 생성.

## 3.2 Intent Trace

| AC-ID | 의도 근거 | 근거 출처 | 신뢰도 |
|-------|-----------|-----------|--------|
| T01-AC-001 | DOD-013 evidence artifact가 machine-readable이어야 함 | PLN-746 PAC-1 | High |
| T01-AC-002 | Codex-only fork 0, generated drift 0 성공 지표 | PLN-746 PAC-1, objective success metrics | High |
| T01-AC-003 | 5-file version sync gate 유지 | PLN-746 PAC-1, PAC-4 | High |
| T01-AC-004 | 단일 Gran Maestro source coverage 필요 | PLN-746 PAC-1, PAC-2 | High |
| T01-AC-005 | shared DOD registry linkage regression 방지 | PLN-746 PAC-3, PAC-6 | High |
| T01-AC-006 | repository-local no-go boundary 유지 | PLN-746 PAC-2 | High |

## 3.3 PAC Mapping

| PAC ID | Grade | Mapped Spec AC IDs | Coverage |
|--------|-------|--------------------|----------|
| PAC-1 | MUST | T01-AC-001, T01-AC-002, T01-AC-003, T01-AC-004 | PARTIAL |
| PAC-2 | MUST | T01-AC-002, T01-AC-004, T01-AC-006 | PARTIAL |
| PAC-3 | MUST | T01-AC-005 | PARTIAL |
| PAC-4 | MUST | T01-AC-003 | PARTIAL |
| PAC-5 | MUST | T01-AC-005, T01-AC-006 | PARTIAL |
| PAC-6 | SHOULD | T01-AC-005 | PARTIAL |

## 3.4 Epic DoD Mapping

| DoD ID | DoD 설명 | Mapped Spec AC IDs | Coverage |
|--------|----------|--------------------|----------|
| DOD-013 | migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다 | T01-AC-001, T01-AC-002, T01-AC-003, T01-AC-004, T01-AC-005, T01-AC-006 | PARTIAL |
| DOD-012 | docs/release evidence linkage regression 보존 | T01-AC-005 | PRESERVED |
| DOD-011 | migration work package source evidence | T01-AC-005 | PRESERVED |
| DOD-009 | Claude plugin regression evidence | T01-AC-005 | PRESERVED |
| DOD-010 | blocker-free migration report | T01-AC-005 | PRESERVED |

## 3.5 Constraints

- 보안: 실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits 없이 repository-local fixtures/evidence로만 검증된다.
- 운영: `.claude/hooks`, `~/.codex`, `~/.agents`, `~/.claude`, user-global config, `objective.md`를 직접 수정하지 않는다.
- 범위: 이 태스크는 failing-first validator contract 고정만 수행하며 persisted artifact refresh와 objective transition은 후속 태스크에서 수행한다.

## 4. 구현 컨텍스트 (Context)

- 따라야 할 패턴: DOD-011/DOD-012 request evidence builder/assertion, DOD-009~DOD-012 shared registry linkage tests.
- 알아야 할 제약: DOD-013 helper는 실제 Codex install/cache/reload를 실행하지 않고 repository-local source/evidence만 검사해야 한다.
- 접근법 방향: smoke test와 helper assertion을 추가해 missing DOD-013 artifact/registry entry가 실패하도록 만든다.

## 5. 의존성 (Dependencies)

- blockedBy: []
- blocks: [REQ-922-02, REQ-922-03, REQ-922-04]
- relatedTo: REQ-919, REQ-921, PLN-746, DOD-011, DOD-012, DOD-013

## 6. 테스트 계획 (Test Plan)

- `npm test`
- DOD-013 helper export 확인
- persisted artifact가 아직 없을 때 failing-first test가 의미 있게 실패하는지 확인

## 7. Test Scenarios (Pre-Impl)

- Run: `npm test`
- Expected before 후속 구현: DOD-013 persisted artifact/registry entry 미존재를 지적하는 실패가 발생할 수 있음
- Expected after 전체 REQ 완료: DOD-009/DOD-010/DOD-011/DOD-012/DOD-013 registry linkage와 DOD-013 evidence assertions가 모두 PASS

## 8. 구현 메모

- 새 문서 파일을 만들지 않는다.
- `.gran-maestro` evidence artifact는 필요 시 git ignore 때문에 `git add -f` 대상임을 후속 태스크에 전달한다.
- Git commit은 PM이 처리하며 구현 에이전트는 commit하지 않는다.
