# Implementation Spec

- Request ID: REQ-922
- Task ID: REQ-922-03
- Created: 2026-05-20T07:13:05.000Z
- Status: pending
- Assigned Agent: [config: codex-dev] → [도메인: docs-release-boundary] → 최종: codex-dev
- Assigned Team: codex-dev 단독 실행
- Worktree: /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/REQ-922-03
- Complexity: Standard

## §0 Context Manifest

> 구현 시작 전 이 목록의 파일을 가장 먼저 Read하세요.
> 이 목록이 완전하지 않을 수 있으며, 에이전트는 자율 탐색을 유지해야 합니다.

- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.ids.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/01/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/02/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/discussion/req-arch-decision.md
- /Users/brandev/mygit/gran-maestro/docs/RELEASE.md
- /Users/brandev/mygit/gran-maestro/README.md
- /Users/brandev/mygit/gran-maestro/README.en.md
- /Users/brandev/mygit/gran-maestro/scripts/lib/codex-plugin-discovery-smoke.mjs
- /Users/brandev/mygit/gran-maestro/tests/smoke.test.mjs

## 1. 요약 (Summary)

기존 README/docs/RELEASE boundary에 DOD-013 single-source 유지 원칙과 5-file version sync gate를 명시한다. 새 문서 파일은 만들지 않고, DOD-012 docs/release gate 위에 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다는 release boundary를 보강한다.

## 2. 범위 (Scope)

- 포함: README/README.en 또는 docs/RELEASE 등 기존 문서의 DOD-013 single-source 유지 원칙, Codex generated/projected asset boundary, 5-file version sync gate, repository-local validation command 안내 보강
- 포함: docs coverage 또는 evidence assertion이 DOD-013 docs/release boundary를 확인하도록 필요한 최소 smoke/helper 보강
- 제외: 새 문서 파일 생성, 실제 release push/npm publish/GitHub release, actual Codex install/load/cache refresh, user-home mutation, `.claude/hooks` 수정, objective status 전이
- 시작점 힌트: `docs/RELEASE.md`, `README.md`, `README.en.md`, `scripts/lib/codex-plugin-discovery-smoke.mjs`, `tests/smoke.test.mjs`

## 3. 수락 조건 (Acceptance Criteria)

#### T03-AC-001 [MUST] [automatable] [docs]
Given: DOD-013 release boundary는 single-source 유지 원칙을 설명해야 함
When: 문서와 smoke assertion이 release/docs boundary를 검사함
Then: 기존 README/docs/RELEASE 중 하나 이상이 Claude plugin canonical source와 Codex generated/projected assets의 관계를 설명하고 Codex-only fork를 만들지 않는다는 원칙을 명시해야 함
Test: `npm test`

#### T03-AC-002 [MUST] [automatable] [docs]
Given: 5-file version sync는 DOD-013 release gate임
When: 문서와 evidence assertion이 release checklist를 검사함
Then: `.claude-plugin/plugin.json`, `package.json`, `.claude-plugin/marketplace.json`, `extension/manifest.json`, `extension/package.json` 5-file version sync gate가 DOD-013 single-source validation과 함께 설명되어야 함
Test: `npm test`

#### T03-AC-003 [MUST] [automatable] [boundary]
Given: 검증은 repository-local로 제한됨
When: docs/release boundary를 검사함
Then: 실제 Codex install/cache refresh/reload, user-home mutation, plugin cache mutation, symlink creation, `.claude/hooks` direct edit 없이 generator와 `npm test`로 검증한다는 boundary가 유지되어야 함
Test: `npm test`

#### T03-AC-004 [MUST] [automatable] [regression-test]
Given: DOD-012 docs/release integration evidence가 이미 accepted 됨
When: DOD-013 docs boundary가 추가됨
Then: DOD-012 docs coverage matrix와 shared registry linkage regression이 없어야 함
Test: `npm test`

#### T03-AC-005 [SHOULD] [automatable] [impact]
Given: DOD-013은 DOD-012 docs/release gate의 후속 검증임
When: release checklist를 읽음
Then: DOD-012 evidence와 DOD-013 single-source evidence를 함께 확인하는 maintainer 흐름이 기존 문서 안에서 이해 가능해야 함
Test: `npm test`

## 3.1 아키텍처 영향도 검토

- Gate: open (`risk_signal_review_required`)
- 방향: 새 문서를 만들지 않고 기존 release/docs boundary에 DOD-013 single-source 유지 원칙을 최소 보강한다.
- 영향 surface: `README.md`, `README.en.md`, `docs/RELEASE.md`, 필요 시 `scripts/lib/codex-plugin-discovery-smoke.mjs`, `tests/smoke.test.mjs`.
- 금지: actual release push/npm publish/GitHub release, user-home mutation, Codex install/cache/reload, `.claude/hooks`, `objective.md` direct edit.

## 3.2 Intent Trace

| AC-ID | 의도 근거 | 근거 출처 | 신뢰도 |
|-------|-----------|-----------|--------|
| T03-AC-001 | single-source 유지 원칙 문서화 필요 | PLN-746 PAC-4 | High |
| T03-AC-002 | 5-file version sync gate 문서화 필요 | PLN-746 PAC-4 | High |
| T03-AC-003 | repository-local no-go boundary 유지 | PLN-746 PAC-2 | High |
| T03-AC-004 | DOD-012 linkage regression 방지 | PLN-746 PAC-5, PAC-6 | High |
| T03-AC-005 | maintainer release flow 이해 가능성 | PLN-746 PAC-4, PAC-6 | Medium |

## 3.3 PAC Mapping

| PAC ID | Grade | Mapped Spec AC IDs | Coverage |
|--------|-------|--------------------|----------|
| PAC-1 | MUST | T03-AC-002 | PARTIAL |
| PAC-2 | MUST | T03-AC-001, T03-AC-003 | PARTIAL |
| PAC-3 | MUST | T03-AC-004 | PARTIAL |
| PAC-4 | MUST | T03-AC-001, T03-AC-002, T03-AC-005 | FULL |
| PAC-5 | MUST | T03-AC-004 | PARTIAL |
| PAC-6 | SHOULD | T03-AC-004, T03-AC-005 | PARTIAL |

## 3.4 Epic DoD Mapping

| DoD ID | DoD 설명 | Mapped Spec AC IDs | Coverage |
|--------|----------|--------------------|----------|
| DOD-013 | migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다 | T03-AC-001, T03-AC-002, T03-AC-003, T03-AC-005 | PARTIAL |
| DOD-012 | docs/release evidence linkage regression 보존 | T03-AC-004 | PRESERVED |

## 3.5 Constraints

- 보안: 실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits 없이 repository-local fixtures/evidence로만 검증된다.
- 운영: `.claude/hooks`, `~/.codex`, `~/.agents`, `~/.claude`, user-global config, `objective.md`를 직접 수정하지 않는다.
- 문서: 새 문서 파일은 만들지 않고 기존 README/docs/RELEASE boundary만 보강한다.

## 4. 구현 컨텍스트 (Context)

- DOD-012가 이미 install/update/uninstall/validation boundary를 추가했으므로 중복 설명을 늘리지 말고 DOD-013 single-source 유지와 5-file sync gate 중심으로 보강한다.
- docs assertion이 필요하면 기존 DOD-012 docs coverage assertion 패턴과 충돌하지 않게 추가한다.

## 5. 의존성 (Dependencies)

- blockedBy: [REQ-922-01, REQ-922-02]
- blocks: [REQ-922-04]
- relatedTo: REQ-921, PLN-746, DOD-012, DOD-013

## 6. 테스트 계획 (Test Plan)

- `npm test`
- DOD-013 evidence assertion에서 docs/release boundary status 확인
- DOD-012 docs coverage and registry regression 확인

## 7. Test Scenarios (Pre-Impl)

- README/docs/RELEASE contains single-source boundary and Codex-only fork prohibition.
- RELEASE mentions DOD-013 single-source evidence and 5-file version sync gate.
- Existing DOD-012 docs/release smoke tests remain PASS.

## 8. 구현 메모

- 문서 본문에 불필요한 설치 명령을 추가하지 않는다.
- 실제 Codex environment mutation을 암시하는 자동 실행 문구를 쓰지 않는다.
- Git commit은 PM이 처리하며 구현 에이전트는 commit하지 않는다.
