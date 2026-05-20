# Plan: AGI-039 Sprint 15 DOD-013 single-source drift validation

## Intent (JTBD)

| 필드 | 내용 |
|------|------|
| When I | Codex plugin migration docs/release integration까지 완료한 뒤 |
| I want to | migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지되는지 검증한다 |
| So I can | Claude Code plugin canonical source와 Codex generated/projected assets가 drift 없이 함께 release될 수 있다 |

## Objective 컨텍스트

- objective.md: `/Users/brandev/mygit/gran-maestro/.gran-maestro/agile/AGI-039/objective/objective.md`
- JTBD 요약: Gran Maestro의 Claude Code plugin 기능을 Codex plugin 모델로 손실 없이 이식하고, 필요한 요소를 모두 분해·점검해 한 번에 마이그레이션한다.
- 프로젝트 DoD:
  - DOD-011: migration work packages가 한 번에 실행 가능한 순서와 검증 기준으로 분해된다. Status: done.
  - DOD-012: Codex migration 관련 사용자 문서와 release checklist가 설치·업데이트·삭제·검증 절차를 포함한다. Status: done.
  - DOD-013: migration 결과가 Codex-only fork 없이 단일 Gran Maestro source에서 유지된다. Status: todo.
- 성공 지표: Codex-only fork 0개, generated drift 0건, 5-file version sync 유지, shared DOD registry linkage regression 0건.

## 문제 정의

DOD-011은 migration work package 순서를 고정했고, DOD-012는 docs/release gate를 사용자·maintainer 문서와 request-level evidence로 연결했다. 남은 DOD-013은 이 산출물들이 별도 Codex-only fork나 drift된 generated asset으로 분리되지 않고, 단일 Gran Maestro source에서 유지되는지 검증해야 한다.

## 범위 예산 (Appetite)

- 단일 Sprint/단일 REQ 범위에서 DOD-013 single-source drift validation을 완료한다.
- 변경 중심은 evidence generator/helper, smoke tests, release/docs boundary 보강, request-level validation artifact다.
- 실제 Codex install/load/cache refresh, user-home config mutation, plugin cache mutation은 수행하지 않는다.

## 제외 범위 (No-go Scope)

- 실제 사용자 홈 mutation 금지: `~/.codex/config.toml`, `~/.agents`, `~/.claude` 수정 없음.
- external Codex install/cache refresh/reload 실행 없음.
- symlink 생성 없음.
- plugin cache mutation 없음.
- `.claude/hooks` 직접 수정 없음.
- objective.md 직접 편집 없음.
- Codex-only fork 생성 없음.
- 릴리스 push, npm publish, GitHub release 생성 없음.

## 제약사항

- Claude plugin canonical source는 `.claude-plugin/plugin.json`, `skills/`, `agents/`, `hooks/`, `templates/defaults/`, package/version files를 유지한다.
- Codex migration 산출물은 generated/projected asset으로 검증하며 Codex-only source fork를 만들지 않는다.
- 버전은 `.claude-plugin/plugin.json`, `package.json`, `.claude-plugin/marketplace.json`, `extension/manifest.json`, `extension/package.json`의 5-file sync를 유지한다.
- DOD-013 검증은 repository-local fixture/evidence 중심으로 구성한다.

## 우선순위 (MoSCoW)

- Must
  - DOD-013 request-level evidence artifact가 Codex-only fork 0개, generated drift 0건, 5-file version sync 유지, canonical source path coverage를 machine-readable 형태로 기록한다.
  - 검증은 user-home/plugin-cache/external Codex install mutation 없이 repository-local로 제한된다.
  - shared DOD evidence registry가 DOD-013 entry를 validator-linked 형태로 보존한다.
  - release/docs boundary가 single-source 유지 원칙과 5-file version sync gate를 설명한다.
  - AGI-039 objective의 모든 DOD가 done으로 전이 가능해야 한다.
- Should
  - 기존 smoke suite와 DOD-009/DOD-010/DOD-011/DOD-012 registry linkage regression이 발생하지 않는다.
- Won't
  - 실제 Codex plugin install/load/cache refresh를 수행하지 않는다.
  - Codex-only fork를 생성하지 않는다.

## 의존성

- blockedBy: DOD-011, DOD-012 완료 evidence.
- relatedTo: REQ-919, REQ-921, PLN-743, PLN-745.
- blocks: AGI-039 objective completion.

## 결정사항

1. DOD-013 산출물은 DOD-011/DOD-012 source evidence를 입력으로 하여 single-source drift validation을 request-level evidence로 남긴다.
2. `scripts/lib/codex-plugin-discovery-smoke.mjs`의 shared DOD evidence registry에 DOD-013 entry를 추가한다.
3. DOD-013 evidence는 Codex-only fork scan, generated drift summary, 5-file version sync, canonical source coverage, no-go boundary를 포함해야 한다.
4. 문서 변경은 release/docs boundary 보강에 한정하고 새 문서 파일은 만들지 않는다.
5. Objective status 전이는 구현/검증/accept 이후 helper로만 수행하고 objective.md 직접 편집은 금지한다.

## 테스트 전략

- `npm test` smoke suite가 계속 통과해야 한다.
- DOD-013 generator temp output이 JSON parse 가능하고 assertion helper를 통과해야 한다.
- persisted DOD-013 request evidence artifact가 shared registry entry와 일치해야 한다.
- 5-file version sync 검증 명령이 pass해야 한다.
- forbidden mutation scan은 user-home mutation, external Codex install/cache/reload, symlink, plugin cache, `.claude/hooks`, objective direct edit 금지 항목을 검증해야 한다.

## Loop 종료 조건

- PAC-1~PAC-6이 request review에서 모두 PASS.
- full smoke test PASS.
- DOD-013 request-level evidence가 persisted artifact로 남음.
- Codex-only fork 0개, generated drift 0건, 5-file version sync 유지가 evidence에 기록됨.
- DOD-013이 helper로 done 전이되고 AGI-039 objective-check `all_done: true`가 됨.

## Objective Trace

| Objective Anchor | Plan Coverage | PAC |
|------------------|---------------|-----|
| DOD-013 | Codex-only fork 없이 단일 Gran Maestro source 유지 검증 | PAC-1, PAC-2, PAC-3, PAC-4, PAC-5 |
| DOD-012 | docs/release evidence linkage regression 보존 | PAC-3, PAC-6 |
| 성공 지표 generated drift 0 / blocker 0 | single-source evidence와 smoke validation | PAC-1, PAC-2, PAC-6 |

누락 ID 목록: 없음. `objective.ids.json`은 존재하지 않으므로 DOD/도메인 anchor 기준으로 추적한다.

## 인수 기준 초안

이 plan이 완료됐다는 것은:

- [MUST] [TIER-A] DOD-013 single-source evidence artifact가 Codex-only fork 0개, generated drift 0건, 5-file version sync 유지, canonical source path coverage를 machine-readable 형태로 기록한다.
- [MUST] [TIER-A] 검증은 Claude canonical source와 Codex generated/projected assets의 관계를 확인하되 Codex-only fork를 새로 만들거나 user-home/plugin-cache/external Codex install을 수정하지 않는다.
- [MUST] [TIER-A] shared DOD evidence registry가 DOD-013 entry를 DOD-009/DOD-010/DOD-011/DOD-012와 함께 validator-linked 형태로 보존한다.
- [MUST] [TIER-B] README/docs/RELEASE 또는 기존 문서가 single-source 유지 원칙과 5-file version sync gate를 DOD-013 release boundary로 설명한다.
- [MUST] [TIER-A] DOD-013 완료 후 AGI-039 objective의 모든 DOD가 done 상태가 되고 DOD-012 evidence linkage regression이 발생하지 않는다.
- [SHOULD] [IMPACT] [TIER-B] 기존 smoke suite와 DOD-009/DOD-010/DOD-011/DOD-012 registry linkage regression이 발생하지 않는다.

## 분리 실행

- 단일 REQ로 진행한다.
- REQ 내부 태스크 분해 권장:
  - T01: DOD-013 single-source drift failing-first tests/validator contract 추가.
  - T02: DOD-013 evidence generator/artifact와 shared registry linkage 추가.
  - T03: docs/release single-source boundary 보강과 integration validation evidence 생성.
  - T04: review/accept validation과 objective completion evidence 기록.

## 브라우저 테스트

- enabled: false
- reason: UI/브라우저 흐름이 아니라 CLI/plugin/runtime evidence와 release checklist 검증 산출물이다.
