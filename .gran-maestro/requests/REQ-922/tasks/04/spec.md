# Implementation Spec

- Request ID: REQ-922
- Task ID: REQ-922-04
- Created: 2026-05-20T07:13:05.000Z
- Status: pending
- Assigned Agent: [config: codex-dev] → [도메인: integration-validation-objective-evidence] → 최종: codex-dev
- Assigned Team: codex-dev 단독 실행
- Worktree: /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/REQ-922-04
- Complexity: Standard

## §0 Context Manifest

> 구현 시작 전 이 목록의 파일을 가장 먼저 Read하세요.
> 이 목록이 완전하지 않을 수 있으며, 에이전트는 자율 탐색을 유지해야 합니다.

- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/plans/PLN-746/plan.ids.json
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/01/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/02/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/tasks/03/spec.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/discussion/req-arch-decision.md
- /Users/brandev/mygit/gran-maestro/.gran-maestro/requests/REQ-922/evidence/dod-013-single-source-drift-validation.json
- /Users/brandev/mygit/gran-maestro/scripts/generate-dod-013-single-source-drift-validation.mjs
- /Users/brandev/mygit/gran-maestro/scripts/lib/codex-plugin-discovery-smoke.mjs
- /Users/brandev/mygit/gran-maestro/tests/smoke.test.mjs

## 1. 요약 (Summary)

REQ-922의 통합 검증 evidence를 기록하고, DOD-013 accept 이후 objective completion을 helper로 전이할 수 있도록 request-level validation 결과를 정리한다. 이 태스크는 objective.md를 직접 수정하지 않고, 최종 accept 단계에서 PM이 helper를 사용해 DOD-013을 done으로 전이할 근거를 남긴다.

## 2. 범위 (Scope)

- 포함: DOD-013 integration validation artifact, temp generator validation result, persisted artifact cross-check, shared registry cross-check, 5-file version sync validation result, no-go boundary validation result, PAC summary, objective completion readiness evidence
- 제외: objective.md 직접 수정, actual objective transition helper 실행, git commit, release push/npm publish/GitHub release, actual Codex install/load/cache refresh, user-home mutation, `.claude/hooks` 수정
- 시작점 힌트: `.gran-maestro/requests/REQ-922/evidence/dod-013-single-source-drift-validation.json`, `scripts/generate-dod-013-single-source-drift-validation.mjs`, `tests/smoke.test.mjs`

## 3. 수락 조건 (Acceptance Criteria)

#### T04-AC-001 [MUST] [automatable] [validation]
Given: DOD-013 generator와 persisted artifact가 준비됨
When: integration validation artifact를 생성함
Then: `.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json`가 `request_id: "REQ-922"`, `dod_id: "DOD-013"`, `status: "pass"`, temp generator validation, persisted artifact validation, shared registry validation, 5-file version sync validation, no-go boundary validation을 기록해야 함
Test: `node -e "const fs=require('fs'); const p='.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json'; const data=JSON.parse(fs.readFileSync(p,'utf8')); if(data.status!=='pass'||data.request_id!=='REQ-922'||data.dod_id!=='DOD-013') throw new Error('invalid DOD-013 integration validation');"`

#### T04-AC-002 [MUST] [automatable] [validation]
Given: full smoke suite가 DOD-013 contract를 포함함
When: `npm test`를 실행함
Then: 기존 smoke suite와 DOD-009/DOD-010/DOD-011/DOD-012/DOD-013 registry linkage tests가 모두 PASS해야 함
Test: `npm test`

#### T04-AC-003 [MUST] [automatable] [validation]
Given: DOD-013 request evidence는 shared registry와 일치해야 함
When: integration validation이 persisted DOD-013 artifact와 registry entry를 교차 검증함
Then: generator script path, request evidence path, validator export name, request id, DOD id가 일치해야 함
Test: `npm test`

#### T04-AC-004 [MUST] [automatable] [boundary]
Given: no-go boundary가 DOD-013 핵심 제약임
When: integration validation artifact를 검사함
Then: user-home mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits, objective direct edit, Codex-only fork creation, release publish/push violation count가 0이어야 함
Test: `node -e "const fs=require('fs'); const data=JSON.parse(fs.readFileSync('.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json','utf8')); if(data.no_go_boundary?.violation_count!==0) throw new Error('no-go violation');"`

#### T04-AC-005 [MUST] [automatable] [objective-readiness]
Given: DOD-013 완료 후 AGI-039 objective의 모든 DOD가 done으로 전이 가능해야 함
When: integration validation artifact가 objective completion readiness를 기록함
Then: DOD-013은 `ready_for_transition: true`, objective transition method는 helper-only, direct objective edit는 false로 기록되어야 함
Test: `node -e "const fs=require('fs'); const data=JSON.parse(fs.readFileSync('.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json','utf8')); if(data.objective_completion_readiness?.ready_for_transition!==true || data.objective_completion_readiness?.objective_md_direct_edit!==false) throw new Error('objective readiness invalid');"`

#### T04-AC-006 [SHOULD] [automatable] [impact]
Given: DOD-013은 DOD-012 evidence linkage 위에 쌓임
When: integration validation이 regression summary를 기록함
Then: DOD-012 evidence linkage regression count가 0이고 DOD-009/DOD-010/DOD-011/DOD-012 registry entries가 pass로 보존되어야 함
Test: `npm test`

## 3.1 아키텍처 영향도 검토

- Gate: open (`risk_signal_review_required`)
- 방향: DOD-013 implementation evidence와 final validation result를 분리하고, objective transition은 accept 단계에서 helper-only로 수행할 준비 상태만 기록한다.
- 영향 surface: `.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json`, `tests/smoke.test.mjs`, `scripts/lib/codex-plugin-discovery-smoke.mjs`, request metadata.
- 금지: objective.md direct edit, actual Codex install/cache/reload, user-home mutation, symlink, plugin cache, `.claude/hooks`, release publish/push.

## 3.2 Intent Trace

| AC-ID | 의도 근거 | 근거 출처 | 신뢰도 |
|-------|-----------|-----------|--------|
| T04-AC-001 | integration validation artifact 필요 | PLN-746 PAC-1, PAC-5 | High |
| T04-AC-002 | full smoke suite PASS 필요 | PLN-746 PAC-6 | High |
| T04-AC-003 | registry와 persisted artifact 일치 필요 | PLN-746 PAC-3 | High |
| T04-AC-004 | no-go boundary violation 0 필요 | PLN-746 PAC-2 | High |
| T04-AC-005 | objective all_done 전이 준비 필요 | PLN-746 PAC-5 | High |
| T04-AC-006 | DOD-012 linkage regression 0 필요 | PLN-746 PAC-5, PAC-6 | High |

## 3.3 PAC Mapping

| PAC ID | Grade | Mapped Spec AC IDs | Coverage |
|--------|-------|--------------------|----------|
| PAC-1 | MUST | T04-AC-001, T04-AC-003 | PARTIAL |
| PAC-2 | MUST | T04-AC-004 | PARTIAL |
| PAC-3 | MUST | T04-AC-003, T04-AC-006 | PARTIAL |
| PAC-4 | MUST | T04-AC-001 | PARTIAL |
| PAC-5 | MUST | T04-AC-001, T04-AC-005, T04-AC-006 | FULL |
| PAC-6 | SHOULD | T04-AC-002, T04-AC-006 | FULL |

## 3.4 Epic DoD Mapping

| DoD ID | DoD 설명 | Mapped Spec AC IDs | Coverage |
|--------|----------|--------------------|----------|
| DOD-013 | migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다 | T04-AC-001, T04-AC-002, T04-AC-003, T04-AC-004, T04-AC-005 | PARTIAL |
| DOD-012 | docs/release evidence linkage regression 보존 | T04-AC-006 | PRESERVED |
| DOD-011 | migration work package source evidence | T04-AC-006 | PRESERVED |
| DOD-009 | Claude plugin regression evidence | T04-AC-006 | PRESERVED |
| DOD-010 | blocker-free migration report | T04-AC-006 | PRESERVED |

## 3.5 Constraints

- 보안: 실제 사용자 홈 mutation, `~/.codex/config.toml` mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation, `.claude/hooks` direct edits 없이 repository-local fixtures/evidence로만 검증된다.
- 운영: `.claude/hooks`, `~/.codex`, `~/.agents`, `~/.claude`, user-global config, `objective.md`를 직접 수정하지 않는다.
- 전이: objective status transition은 implementation/review/accept 후 PM이 `mst.py agile objective-transition` helper로만 수행한다.
- evidence: `.gran-maestro/requests/REQ-922/evidence/dod-013-integration-validation.json`는 git ignore 대상이므로 PM commit 시 `git add -f`가 필요할 수 있다.

## 4. 구현 컨텍스트 (Context)

- DOD-013 single-source evidence artifact는 T02에서 생성된다.
- 이 태스크는 final review/accept가 사용할 machine-readable validation summary를 남긴다.
- `objective_completion_readiness`는 helper-only 전이 준비를 기록하지만 objective.md를 직접 변경하지 않는다.

## 5. 의존성 (Dependencies)

- blockedBy: [REQ-922-01, REQ-922-02, REQ-922-03]
- blocks: []
- relatedTo: REQ-919, REQ-921, PLN-746, DOD-011, DOD-012, DOD-013, AGI-039

## 6. 테스트 계획 (Test Plan)

- `npm test`
- `node scripts/generate-dod-013-single-source-drift-validation.mjs /tmp/dod-013-single-source-drift-validation-check.json`
- persisted DOD-013 evidence JSON parse/assertion
- persisted DOD-013 integration validation JSON parse/assertion
- 5-file version sync validation command

## 7. Test Scenarios (Pre-Impl)

- DOD-013 integration validation artifact exists and records status pass.
- Full smoke suite passes with previous DOD registry regression preserved.
- No-go boundary violation count is 0.
- Objective readiness records helper-only transition and no direct objective edit.

## 8. 구현 메모

- 이 태스크는 objective transition을 실행하지 않는다. accept 단계에서 PM이 최종 validation 이후 helper를 실행한다.
- Git commit은 PM이 처리하며 구현 에이전트는 commit하지 않는다.
