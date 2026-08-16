# Changelog

모든 주요 변경사항을 이 파일에 기록합니다. [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식을 따릅니다.

---

## [Unreleased]

---

## [0.65.0] — 2026-08-16

### 새 기능

- **MST 호출별 추론 난이도 설정**: Codex·AGY·Claude provider 기본값과 각 agent/role 호출에 `default`, `inherit` 또는 provider/model이 지원하는 구체적인 추론 난이도를 지정할 수 있습니다.
- **모델 capability 기반 Settings UI**: 일반 워크플로우 설정과 고급 설정에서 추론 난이도를 편집하며, 현재 선택한 모델이 실제 지원하는 값만 표시합니다.

### 개선

- **실행 transport 간 동일한 binding 보장**: model과 reasoning effort를 native, direct external, Orca external 실행 전체에서 하나의 lifecycle binding으로 보존합니다.
- **지원하지 않는 조합의 사전 차단**: provider 실행 전에 capability를 검증해 지원하지 않는 추론 난이도가 다른 transport나 기본값으로 조용히 우회되지 않도록 했습니다.
- **Orca 책임 경계 명확화**: Orca는 이미 external로 판정된 호출의 launch surface만 변경하며 native route나 provider/model 기능 범위를 변경하지 않습니다.

---

## [0.64.0] — 2026-07-13

### 새 기능

- **Same-host native-first 위임**: Codex→Codex와 Claude Code→Claude 작업은 host native agent를 우선 사용해, 같은 host 위임만을 위한 별도 provider CLI 없이 실행할 수 있습니다.
- **위임 lifecycle·복구 추적**: native/external/blocked route와 attempt ownership, fallback, reconciliation evidence를 일관되게 기록해 중복 실행을 방지합니다.

### 개선

- **안전한 external fallback**: native task 미생성이 확정된 경우에만 external로 전환하고, attach 실패·timeout·취소 미확인 상태는 `reconciling`으로 유지하며 대상 CLI가 없으면 structured `blocked`로 종료합니다.
- **위임 대시보드 가시성 강화**: 실행 transport, attempt, provider task, fallback, reconciliation, 완료·exit 상태를 Dispatch 화면에서 확인할 수 있습니다.
- **설정 migration·opt-out 지원**: 기존 `delegation.native_codex_subagents`를 canonical 설정으로 이관하고 `external-only`와 native scope 제어를 제공합니다.

---

## [0.63.1] — 2026-06-26

### 버그 수정

- **Codex skill invocation projection 수정**: Codex plugin 설치 후 `/mst:agile`, `/mst:agile-plan` 같은 skill 호출 경로가 projection에서도 올바르게 동작하도록 보강했습니다.
- **Gemini legacy alias 호환 보강**: 기존 `gemini` provider 설정을 AGY 경로로 정규화할 때 사용자 설정 모델을 보존하고, AGY CLI가 없을 때 structured preflight evidence를 출력하도록 수정했습니다.

---

## [0.63.0] — 2026-06-14

### 새 기능

- **Host-aware User Input Boundary 추가**: AskUserQuestion을 사용할 수 없는 Codex/headless 환경에서도 질문을 `question prepare` payload로 구조화하고, 사용자에게 질문이 막힌 것처럼 보이지 않도록 pending 상태와 fallback 안내를 기록합니다.

### 개선

- **질문 컨텍스트 분리**: 여러 스킬이 공통 User Input Boundary include를 참조하도록 정리해, 질문 계약을 매번 긴 스킬 본문에 중복 주입하지 않고 필요한 컨텍스트만 전달합니다.
- **상태·hook guard 진단 보강**: workflow state에 질문 pending 정보를 기록하고 PreToolUse/transition graph 테스트로 headless 질문 경계를 검증할 수 있게 했습니다.
- **Codex projection 검증 강화**: 새 question CLI, payload schema, 회귀 테스트가 source와 projection 양쪽에 반영되도록 local install smoke 경로를 맞췄습니다.

---

## [0.62.0] — 2026-06-04

### 새 기능

- **AGY provider 전환**: Gemini CLI 종료 예정에 맞춰 canonical provider/skill/agent를 `agy`, `/mst:agy`, `agy-dev`로 전환했습니다. 기존 `/mst:gemini`, `gemini`, `gemini-dev` 설정과 세션 값은 한 릴리스 동안 deprecated alias로 읽고 AGY 경로로 정규화합니다.
- **Agile 실행 게이트 보강**: agile sidecar schema, source mapping, coverage check, integration review context를 추가해 objective 기반 실행이 누락된 도메인·DoD·통합 검증을 더 명확히 추적합니다.

### 개선

- **worktree accept/cleanup lifecycle 정렬**: workflow 문서, transition graph, accept/approve 스킬, CLI evidence가 `worktree 생성 → worktree 작업 → 의도 변경 커밋 → accept/merge target 반영 → cleanup 정리` 순서와 일치하도록 정리했습니다.
- **linked worktree 지원 파일 처리 개선**: linked worktree 환경에서 필요한 보조 파일과 dispatch guard가 더 안정적으로 동작하도록 source/projection 파일을 맞췄습니다.
- **plan/agile-plan 다음 명령 안내 보강**: planning 세션 종료 시 사용자가 바로 이어갈 수 있는 다음 명령을 더 일관되게 출력합니다.

### 버그 수정

- **cleanup 단계 merge 오해 차단**: cleanup이 commit, merge, ref update를 수행하지 않도록 회귀 테스트와 상태 전이 계약을 보강했습니다.
- **accept target 반영 누락 방지**: request/session accept 이후 정해진 대상 브랜치 반영 evidence가 없으면 Phase 5 cleanup으로 넘어가지 않도록 검증을 추가했습니다.
- **Phase 2 readiness 검증 강화**: task status만으로 Phase 3에 진입하지 않고 commit hash, branch, worktree evidence를 확인하도록 수정했습니다.
- **Agile session 검증 회귀 수정**: agile 세션의 검증 상태가 누락되거나 잘못 판정되는 흐름을 보강했습니다.

---

## [0.61.0] — 2026-05-25

### 새 기능

- **사용자 기준 브랜치 기반 worktree 수락 경계 강화**: MST workflow가 `master` 고정값 대신 workflow 시작 시점의 사용자 기준 브랜치와 SHA를 original base evidence로 보존합니다. MST 임시 브랜치(`gran-maestro/**`)는 original base로 인정하지 않으며, 최종 반영은 session branch에서 원본 checkout으로 `ff-only` 검증을 통과한 경우에만 수행합니다.
- **Codex delegated run worktree guard 추가**: `mst.py run --require-worktree --worktree-dir ...` 경로에서 primary checkout과 git에 등록되지 않은 경로를 subprocess 실행 전에 차단합니다. Codex/approve 스킬의 dispatch 예시도 새 guard 옵션을 사용하도록 맞췄습니다.

### 개선

- **Codex plugin migration 문서·릴리스 검증 통합**: README, Quick Start, configuration, hook setup, skills reference, release checklist가 Codex plugin 설치·업데이트·삭제·검증 절차와 repository-local validation boundary를 함께 안내합니다. DOD-012 evidence와 smoke validation으로 사용자 홈 설정, Codex cache, `.claude/hooks`를 건드리지 않고 릴리스 준비 상태를 확인할 수 있습니다.
- **한국어 차단/진단 메시지 정리**: MST 임시 브랜치, protected branch, Codex worktree guard 차단 메시지가 “사용자 기준 브랜치”와 worktree 경계 용어를 일관되게 안내하도록 회귀 테스트를 보강했습니다.

### 버그 수정

- **accept 단계의 `master` fallback 제거**: child/request accept 문서의 `CONFIG_BASE_BRANCH:-master` fallback을 제거하고, `request.json.detected_base` 또는 명시된 `config.worktree.base_branch`가 없으면 중단하도록 안내합니다. 원본 `PROJECT_ROOT`에서 destructive git 명령이 재유입되지 않도록 snapshot/static 테스트도 갱신했습니다.

---

## [0.59.8] — 2026-04-30

### 버그 수정

- **agile/mst 자율 루프에서 ScheduleWakeup 자가 페이싱 차단** (REQ-757, PLN-583): mst chain·agile loop 자율 모드 진행 중에 모델이 `ScheduleWakeup`으로 수십 분짜리 자가 지연을 도입해 작업이 정지되던 문제를 차단합니다. PreToolUse hook이 workflow_active=true 상태에서의 ScheduleWakeup을 즉시 차단하고 다음 액션 emit을 강제합니다. 정상적인 `/loop` dynamic mode 사용자는 영향받지 않으며, 의도적 호출이 필요한 경우 `MST_ALLOW_SCHEDULE_WAKEUP=1` 환경 변수로 우회할 수 있습니다.
- **선조작 후호출 우회 차단**: workflow_state를 false로 미리 바꾼 뒤 ScheduleWakeup을 호출하는 우회 시나리오에 대비해 active→inactive 전환 직후 30초 grace period 동안 계속 차단을 유지합니다.
- **텍스트 자가 일시정지 패턴 보강**: stop hook의 SELF_PAUSE_RE에 "wakeup", "사이클 후", "N분 후 재개" 등 7개 패턴을 추가하여 텍스트 우회까지 함께 차단합니다.

---

## [0.60.0] — 2026-04-29

### 새 기능

- **`/mst:on cleanup` 자동 마이그레이션** (AGI-019, DOD-007/008/009/010~016): hooks.json 자체 등록(${CLAUDE_PLUGIN_ROOT}) 메커니즘 도입에 맞춰 `/mst:on`이 더 이상 hook 파일을 프로젝트로 복사하거나 `settings.local.json`의 hooks 블록을 수정하지 않도록 재설계했습니다. 등록된 기존 프로젝트는 SessionStart 시 hook 버전 mismatch가 감지되면 자동으로 `mst.py on cleanup`이 실행되어 stale mst hook 사본·settings 항목이 안전하게 정리됩니다 (사용자 정의 hook은 정규식 패턴 매칭으로 100% 보존).
- **5종 안전 가드**: 자동 마이그레이션 트리거에 G1 동시성 lock(120s stale), G2 fail-open(timeout 30s + return 0), G3 anti-loop(실패 marker TTL 600s), G4 환경 detection(`MST_DISABLE_AUTO_MIGRATE=1` / `timeout` 명령 부재 시 skip), 재귀 가드(`MST_AUTO_MIGRATE_IN_PROGRESS=1`)를 적용했습니다.
- **마이그레이션 가시성**: `.gran-maestro/migration.log`에 ISO timestamp로 모든 마이그레이션 시도/성공/실패/skip 사유를 기록하며 50KB rotation cap을 적용합니다. 사용자 레벨 `~/.claude/settings.json`에 mst hook 항목이 남아 있으면 충돌 detection으로 안내합니다 (자동 제거는 사용자 책임).
- **명시적 cleanup 명령**: `python3 scripts/mst.py on cleanup [--dry-run] [--silent] [--json]`으로 수동 정리 가능. `.claude-plugin/plugin.json` + `hooks/hooks.json` 동시 존재 시 plugin source repo로 식별하여 자동 skip하는 가드 포함.

### 개선

- **stop hook strict schema 재확보** (KI-003, DOD-005): fd34058 머지로 회귀했던 stop hook stdout 출력에서 `details_anchor` 키를 제거하고 stderr `[stop-hook] anchor=<value>` 분리 패턴을 복원했습니다. `emit_block_json` 빈 reason fallback (`"stop blocked (reason unspecified)"`) + source-time 테스트 하네스 호환을 위한 source-guard도 함께 추가했습니다. session-init hook의 Claude Code version guard 블록도 함께 복원되었습니다.
- **회귀 차단 자동화 강화**: 4개 hook 등록·portability(비-git/subdir/symlink) + /mst:on cleanup migrator 패턴 매칭·atomic·lock + 자동 마이그레이션 가드 시나리오를 합쳐 회귀 테스트 91건이 신규로 추가되었습니다 (master 전체 683 passed/0 failed).

---

## [0.59.6] — 2026-04-25

### 개선

- 스킬 본문 boilerplate 제거 (DOD-009, PLN-553, REQ-724): 40개 SKILL.md에서 `## 스킬 실행 마커 (MANDATORY)` 섹션과 `@include _shared/skill-execution-marker.md`, `@include _shared/hooks-sync.md` 블록을 일괄 제거했습니다. `skills/_shared/` 원본은 유지하면서 스킬 실행 컨텍스트의 중복 boilerplate 토큰 부담을 줄였습니다.

---

## [0.59.5] — 2026-04-23

### 버그 수정

- Stop hook의 `decision: allow` schema 위반으로 발생하던 "Hook JSON output validation failed" 경고를 제거했습니다. Claude Code 세션 종료 시 더 이상 경고가 출력되지 않습니다.

---

## [0.59.4] — 2026-04-21

### 새 기능
- **Agile 종료 자동화**: `agile finalize` CLI가 추가되어 Sprint 전체 완료 시 `final-report.md`를 자동 생성하고, 프로젝트 DoD 달성 여부를 검증하는 Finalization Gate가 신설되었습니다. `update` 커맨드에 완료 가드도 추가되었습니다. (REQ-687, REQ-688)
- **Sprint 종료 자동화**: `sprint-close` CLI가 신설되어 Sprint 종료 시 hijack 가드·cukestill 정리까지 일괄 처리합니다. (REQ-685)
- **worktree detect-orphans 옵션**: `--scope`·`--prefix` 옵션으로 orphan 탐지 범위를 세밀하게 지정할 수 있습니다. (REQ-689)

### 개선
- **archive 기본 보존량 상향**: `archive.max_active_sessions` 기본값이 20 → 200으로 상향되어, 활성 세션이 자주 누적되는 실사용 패턴에서 과도한 아카이브를 줄입니다.
- **AUTO_MODE 자발적 중단 방지 강화**: `/mst:agile` Step 3에서 자율 루프가 컨텍스트 길이 등을 이유로 스스로 중단하지 않도록 가드를 강화했습니다. (REQ-686)

---

## [0.59.3] — 2026-04-19

### 개선
- `/mst:agile -a` 자율 스프린트 루프가 Step 3 스티어링 체크포인트 이후에도 중단 없이 다음 Sprint로 자동 복귀합니다. 기존 체크포인트 직후 "새 세션에서 --resume으로 재개 권장" 문구로 자발 종료되던 문제를 해결했습니다.

---

## [0.59.2] — 2026-04-19

### 개선

- `mst:stitch` CLI(`stitch-sdk.mjs`)가 `generate --save-dir <dir> --screen-name <slug>` 옵션을 받아 html/image/meta 3파일을 atomic하게 저장합니다. 스킬을 우회해 CLI를 직접 쓰더라도 산출물이 디스크에 남습니다.
- `list-screens`가 Stitch SDK의 빈 응답을 받았을 때 MCP `list_screens` fallback을 자동 시도합니다. canvas에만 존재하는 화면이 누락되는 문제가 줄어듭니다.
- `@google/stitch-sdk`가 설치되어 있지 않으면 CLI가 `install_required:true` JSON과 exit code 2를 반환하고, `mst:stitch` 스킬이 설치 동의 AskUserQuestion으로 안내합니다.
- `mst:stitch` 스킬 상단에 Bash 직접 orchestration 금지 Gate와 Anti-Rationalization Checklist를 추가했습니다.

---

## [0.59.1] — 2026-04-19

### 새 기능
- `agile-plan`에서 비-UI 프로젝트도 objective 저장 전에 사용자 동선, 시스템 지도, 누락 확인 형태로 완성된 모습을 미리 검증하고 정제할 수 있습니다. (REQ-683)

---

## [0.59.0] — 2026-04-19

### 새 기능
- **적대적 검토 게이트(Adversarial Review Gate)**: `/mst:plan`·`/mst:agile-plan`의 D3 Gate 직전과 `/mst:request`의 질문 생성 직전에, 독립 에이전트가 plan/objective를 적대적으로 검토해 사용자가 **놓친 엣지케이스·빠진 흐름·페르소나/NFR/통합 gap**을 찾아 DoD/AC에 보강합니다. 5종 perspective(edge/flow/persona/nfr/integration) 중 edge/flow/integration이 기본 on, persona/nfr은 기본 off. 대시보드 Settings 탭 "적대적 검토" 섹션에서 전체/perspective별 on/off와 max_rounds, auto_apply_severity_threshold, agent provider/tier를 편집할 수 있습니다. config로는 `agile.adversarial_review.enabled=false`로 끌 수 있습니다. (REQ-667)
- **MST HUD 스킬 호출 체인 표시**: statusline HUD에서 실행 중 스킬 체인(예: plan → request → approve)을 가시화합니다. (REQ-668)

### 개선
- **worktree remove 정리 안전화**: remove 절차 중 비정상 상태에 대한 방어가 강화되어 정리 실패로 인한 상태 오염이 줄어듭니다. (REQ-666)
- **worktree 중첩 생성 차단 가드**: 이미 worktree인 경로 안에 추가 worktree 생성 시도를 사전에 차단합니다. (REQ-665)
- **스킬 프롬프트 압축**: 상위 5개 스킬의 SKILL.md 크기를 평균 30% 이상 축소하고, 공통 블록을 include 메커니즘으로 재사용하도록 재구성했습니다. 컨텍스트 소비가 감소합니다. (REQ-664, REQ-662)
- **mst-session-init에 session_id 브리지 writer**: 세션 식별자가 여러 훅·스킬 간에 일관되게 전달되도록 session-init에서 writer를 보강했습니다. (REQ-663)
- **config get CLI 복수 키 지원**: `mst.py config get KEY1 KEY2 ...` 로 한 번에 여러 키를 조회하고, 스킬에서 `config.resolved.json` 전체 Read를 제거해 IO를 줄였습니다. (REQ-660)
- **statusline fallback 판정 보강**: authoritative 판정 경로를 명확히 하고 stop-hook과 계약을 정렬했습니다. (REQ-658)

### 버그 수정
- **Ultrareview 관련 3종 수정**: session-init fallback, gardening cascade, stop-hook의 unquoted `find` 경로에서 발생하던 이슈를 수정했습니다. (REQ-661)

---

## [0.58.4] — 2026-04-18

### 개선
- `/mst:plan` Step 2.1/2.3/2.6에 "추론 가능 시 질문 생략" 규칙 추가. PM이 직전 대화 컨텍스트에서 값을 추론 가능한 항목은 `AskUserQuestion`을 생략하고 plan.md 초안에 `(PM 추론)` 표기로 기입하며, 추론 불가 항목만 질문합니다. 기존 Q&A 흐름을 이미 답한 내용으로 리프레이즈해 다시 묻지 않도록 단순화합니다.
- Step 4에 `(PM 추론)` 항목에 대한 "수정 필요" 지시 시 같은 턴 재제시 규칙 명시.

---

## [0.58.3] — 2026-04-15

### 버그 수정
- **agile→accept 복귀 시 Sprint 자동 재개 복원**: accept 단계에서 stop-hook이 조기 종료되며 다음 Sprint가 이어지지 않던 문제를 수정했습니다.
- **AUTO_MODE 스프린트 간 자발 정지 방지**: agile AUTO_MODE에서 스프린트 사이에 LLM이 자발적으로 멈추던 현상을 stop-hook 패턴 확장과 진입 시 hook 검증으로 차단했습니다.

### 개선
- **plan/agile-plan/request/agile 진입 시 hooks 자동 동기화**: 해당 스킬 진입 시 `hooks/` 원본이 프로젝트로 자동 복사되어 수동 동기화 없이 최신 hook이 적용됩니다.
- Agile Sprint 실행이 dashboard에서 실시간으로 추적됩니다. dispatch 모드에서는 `mst.py run` wrapper 경유로 register/heartbeat가 자동 기록되고, inline 모드에서도 경량 추적 마커가 작성되어 Sprint 진행 상태를 실시간으로 확인할 수 있습니다.

---

## [0.58.2] — 2026-04-12

### 버그 수정
- **Windows 호환성 복원**: `fcntl`(Unix 전용 모듈) 사용으로 인해 Windows에서 `mst.py`가 완전히 동작 불가했던 문제를 수정했습니다. 파일 잠금을 platform-aware 방식(`fcntl`/`msvcrt`)으로 교체하고, 서브커맨드 35개 파일의 불필요한 `import fcntl`을 제거했습니다.

---

## [0.58.1] — 2026-04-12

### 새 기능
- **Sprint dispatch prompt 템플릿**: 7-layer context 구조로 외부 에이전트에 전달할 dispatch prompt를 체계적으로 생성하는 템플릿을 추가했습니다.

---

## [0.58.0] — 2026-04-12

### 새 기능
- **LLM 스티어링 게이트**: `mst:agile` 실행 중 LLM이 규칙을 우회하려는 자기합리화를 감지하면 즉시 정지시키는 런타임 게이트를 추가했습니다 (DOD-004/006).
- **Synthetic marker 테스트 인프라**: `tests/test_synthetic_markers.py`로 마커 기반 agile 실행 검증을 자동화했습니다.

### 개선
- **Wire 승격 + 하이브리드 fallback**: 테스트 PASS 기반으로 wire를 승격하고, 실패 시 하위호환 fallback 경로를 제공합니다 (DOD-002/003/005).
- **grep 패턴 확장**: `_regex_for()`에 `__init__.py` 패키지 매칭 및 `register()` call-site 패턴을 추가해 탐색 정확도를 높였습니다.
- **Reference 스킬 재설계**: 원문 중심으로 content.md 및 가이드를 전면 재작성했습니다.
- **Stop-audit 감사 로그**: sentinel 프로토콜 + 허용 정지 사유 enum 매칭 로직으로 감사 인프라를 구축했습니다.

### 버그 수정
- `/mst:settings` 실행 후 `/mst:on`이 `config.resolved.json`을 갱신하지 않던 문제를 수정했습니다.

---

## [0.57.6] — 2026-04-11

### 새 기능
- **Agile Sprint dispatch 모드 (`--dispatch codex|claude|inline`)**: `/mst:agile` Sprint loop가 Step 2.2.3에서 sub-plan 전체 체인(plan→request→approve→accept)을 부모 세션 inline 컨텍스트에서 실행할지, 아니면 신규 worktree의 외부 CLI 격리 컨텍스트(`mst:codex` / `mst:claude`)에서 실행할지 선택할 수 있습니다. 기본값은 `inline`으로 기존 동작을 유지하며, 대형 agile 프로젝트에서 컨텍스트 압박이 누적될 때 `--dispatch codex` 플래그로 각 sub-plan을 깨끗한 격리 실행으로 전환할 수 있습니다. dispatch 결과는 `sprints/S{N:02d}/dispatch-result.json`에 기록되어 Step 2.2.0.7 통합 검증에 자동 연계됩니다.

### 개선
- **agile 기본 전략 명시**: `templates/defaults/config.json`에 `agile.dispatch.default_mode` 기본값 `"inline"`을 추가해 Sprint dispatch 모드 전역 기본값을 config에서 관리할 수 있게 했습니다. 기존 Sprint loop 동작은 완전히 호환됩니다.

---

## [0.57.5] — 2026-04-11

### 새 기능
- **Agile Sub-plan 격리 실행 가이드**: `mst:codex`와 `mst:claude` 스킬에 agile Sprint loop에서 sub-plan 전체 체인(plan→request→approve→accept)을 깨끗한 격리 컨텍스트로 수동 실행하는 사용 예시 섹션을 추가했습니다. 컨텍스트 압박이 심한 대형 agile 프로젝트에서 안전 장치로 활용할 수 있습니다.

### 개선
- **우회 금지 규칙 전역화**: `mst:agile`, `mst:plan`, `mst:request` 3개 스킬에 "컨텍스트 압박을 이유로 sub-plan chain을 우회하여 직접 codex dispatch + master 커밋으로 전환하는 관행"을 금지하는 규칙과 Anti-Rationalization 항목을 동일 문구로 추가했습니다. 이 플러그인이 다른 프로젝트에 재사용될 때도 동일 원칙이 유지됩니다.

---

## [0.57.4] — 2026-04-11

> **Accept 정리 로직 및 agile 플로우 개선 (PLN-445~447 / REQ-602~604)**

### 개선

- **스티어링 설정 Q&A 이동**: `/mst:agile` 실행 시 스티어링 체크포인트 관련 Q&A를 `agile-plan` 서브스킬에서 `agile` Step 1.5로 이동했습니다. 이제 objective.md 준비 단계와 실행 스텝이 더 명확하게 분리되어 있으며, 스티어링 설정이 필요한 시점에 정확히 문의됩니다.
- **Frontend useDispatchStream 회귀 테스트**: `frontend/`의 `useDispatchStream` 훅에 대한 단위 테스트를 추가했습니다. Dashboard Dispatch 패널의 SSE 스트림 구독/해제 동작이 향후 회귀되지 않도록 검증합니다.

### 버그 수정

- **accept 종료 시 workflow 상태 정리**: `/mst:accept` 스킬 종료 시 `workflow_active=false` 상태 정리 호출을 추가했습니다. 기존에는 수락 완료 후에도 일부 경로에서 workflow_active 플래그가 남아있어 다음 요청 시작 시 상태가 혼동될 수 있던 문제를 해결합니다.

---

## [0.57.3] — 2026-04-09

> **대시보드 Dispatch 패널 라이브 동작 복구 (PLN-444 / REQ-601)**

REQ-598에서 도입된 Dashboard SSE Dispatch 패널이 production 환경에서 항상 빈 상태로만 표시되던 버그를 수정합니다.

### 버그 수정

- **DispatchPanel 라이브 데이터 복구**: `src/routes/dispatch.ts`의 `runDir` 경로가 `${baseDir}/.gran-maestro/run`으로 잘못 조합되어 있어, 실제 `.gran-maestro/run/*.json` 상태파일이 존재해도 `collectDispatchSnapshot`이 항상 빈 배열을 반환하던 문제를 수정했습니다. `resolveBaseDir`는 이미 `.gran-maestro` 접미 경로를 반환하므로 다른 라우트(`overview.ts` 등)와 동일하게 `${baseDir}/run`으로 교정했습니다. 이제 Overview 화면의 Dispatch Runs 패널이 `task_id`/`provider`/`phase`/`heartbeat_age_sec`을 실제 외부 CLI 실행 상태에 따라 1초 주기로 갱신하며 표시합니다.
- **dispatch.test.ts production 규약 반영**: 동일한 잘못된 경로 규약을 따르고 있어 위 버그를 검출하지 못하던 단위 테스트를 production `resolveBaseDir` 규약(baseDir 자체가 `.gran-maestro` 디렉토리 역할)과 일치시켰습니다. TDD red→green 사이클로 회귀 방지를 검증했습니다.

---

## [0.57.2] — 2026-04-08

> **mst-loop 재진입 경로 복구 + 문서 정합성 정리 (PLN-440 / REQ-593)**

0.57.1에서 커밋된 `ralph-loop → mst-loop` 리네이밍 이후, `scripts/mst-loop.sh`가 호출하는 `/mst:resume` 스킬과 스크립트 자체가 플러그인 캐시로 아직 배포되지 않아 mst-loop 재진입이 실질적으로 동작하지 않던 문제를 해결합니다.

### 버그 수정

- **mst-loop 재진입 경로 복구**: 버전 bump를 통해 `skills/resume/` 스킬과 `scripts/mst-loop.sh`를 플러그인 캐시에 배포합니다. 이 버전 이후 `/mst:on` 재실행 또는 Claude Code 재시작으로 플러그인 캐시가 `0.57.2`로 갱신되면, `/mst:resume` 슬래시 커맨드가 사용자 호출 가능 목록에 노출되고 `bash scripts/mst-loop.sh`가 정상 동작합니다.

### 개선

- **`skills/recover/SKILL.md` description 분리**: "queue(pending.ndjson) 기반 단일 pop 재진입은 `/mst:resume`을 사용" 취지 안내를 추가했습니다. "재개/이어서/계속해줘" 사용자 자연어가 `/mst:recover`와 `/mst:resume` 사이에서 혼동되지 않도록 경로를 명시합니다.
- **stale `ralph` 문서 참조 정리**: `skills/ideation/SKILL.md`의 AUTO-CONTINUE 원칙 설명 문구를 `ralph/ultrawork` → `mst-loop/ultrawork`로 교체했습니다. `skills/on/SKILL.md`의 차단 스킬 목록 `/ralph` 엔트리는 구 오토파일럿/루프 계열 차단 목적으로 유지하되, 현재 mst-loop 재진입 경로 안내 주석을 추가했습니다.

### 주의사항

이 버전의 `mst:resume` 스킬과 `mst-loop.sh`를 사용하려면 bump 후 반드시 `/mst:on`을 재실행하거나 Claude Code를 재시작하여 플러그인 캐시를 `0.57.2`로 갱신해야 합니다.

---

## [0.57.1] — 2026-04-08

> **PLN-435 Phase 1 ~ 6 전면 구축 — agile 스프린트 Sprint Review Gate + Objective Surface Coverage drift + recall Level 2/3 + Done DoD unlock 경로**

> slide-craft 패턴(DoD done 22/22인데 실 산출물 미검증)을 evidence/drift/recall 3단 방어로 구조적으로 차단합니다. 전체 7개 REQ(REQ-586~592) 릴리스.

### 새 기능

- **Sprint Review Gate (Step 2.2.5)**: 매 스프린트 마지막에 `mst.py agile evidence-check`로 모든 done DoD의 evidence(artifact_paths 실재성 + verify_cmd 실행 가능성 + Goodhart 린터로 `true`/`exit 0`/`echo` 거부)를 검증합니다. 3-tier 결과(PASS/WARN/FAIL), `required_globs` 프로젝트 타입별 계약 산출물 검사(0건 시 hard fail), `--accept-evidence-gap REASON` bypass(sprint-log 영구 기록)를 지원합니다. `agile.evidence_gate.enabled=false` 기본값으로 하위 호환.
- **Objective Surface Coverage drift-check**: `mst.py agile drift-check`가 `objective.md`의 JTBD + 프로젝트 DoD surface를 lexical 매칭으로 추출해 Coverage 점수를 계산하고, `agile-state.json` append-only ledger에 누적합니다. `drift_score < threshold`(기본 0.7)가 2회 연속이면 `escalate_flag=true`로 자동 에스컬레이션 신호를 발생시킵니다. `agile.drift.enabled=false` 기본값.
- **agile recall Level 2 patch 모드**: `mst.py agile recall`로 evidence fail / drift escalate 발생 시 agile-plan을 patch 모드로 재호출합니다. DoD CRUD + objective 문구 정밀화 + 통합 sprint 삽입을 지원합니다. Cooldown 적응 공식 `clamp(1,4,⌈N*0.10⌉)`, cap `clamp(3,6,⌈N/10⌉)`, `--bypass-cooldown` (evidence hard fail fingerprint 1회, 동일 fingerprint 중복 거부), patch budget `min(3, done*20%)` 상한, rollback token 선저장(`.gran-maestro/agile/snapshots/<ts>.json`), Level 2 scope guard(objective 본질 변경 감지 시 Level 3 유도).
- **agile recall Level 3 사용자 명시 승인 + audit trail**: `agile recall --level 3 --approval-ticket <id>`는 objective JTBD 재정의까지 허용하지만 `--approval-ticket` 없으면 AUTO_MODE에서도 실행을 차단합니다. `objective.md` frontmatter에 `version`/`last_event_id`/`semantic_hash` 필드를 추가하고, `.gran-maestro/objective/history/<ts>_L3_<reason>.json`에 append-only 로그(before_hash/after_hash/diff/affected_dods/drift_evidence)를 기록합니다. Level 3 cooldown은 Level 2의 2배.
- **agile classify-change 자동 분류기**: `mst.py agile classify-change <manifest>`가 heuristic 기반으로 변경을 Level 2/3 후보로 자동 분류하고 confidence 점수를 반환합니다. 혼합 manifest는 Level 2, JTBD 핵심 단어 변경은 Level 3.
- **Done DoD unlock explicit reason 경로**: `mst.py agile unlock --dod <id> --category <cat> --reason "<text>" --evidence <path>`로 done DoD를 재수정 가능 상태로 전환합니다. 카테고리 4종(`upstream_evidence_changed`/`integration_regression`/`new_dependency_dod`/`objective_precision_fix`)별 증빙 필드 강제, reason 20~500자 + 금칙어(`lgtm`/`ok`/`fix`) 거부, `unlock_history[]` append-only, 의존 DoD는 즉시 강등 없이 `revalidation_required` 표식만 부여합니다. `mst.py agile revalidate-done <id>`로 표식을 해제합니다.
- **evidence 파서 + validator + 1A.10 evidence 필드별 강제 시점 표**: REQ-579 source-mapping 파서를 확장해 `details/*.md` frontmatter에 evidence 필드(`plan.artifact_paths`/`entrypoint_path`, `runtime.integration_smoke_id`/`verify_cmd`/`expected_signal`)를 read/write 지원합니다. `mst.py agile detail validate-evidence <file>` CLI, `entrypoint: none + reason` 예외 태그, Goodhart 린터, legacy graceful 로드(warn-only) 구현. `skills/agile-plan/SKILL.md` 1A.10 섹션에 필드별 plan-time/sprint-runtime/sprint-end 강제 시점 표 추가.
- **Dashboard Settings agile 섹션 확장**: `agile.evidence_gate` / `agile.drift` / `agile.recall` / `agile.unlock` 4개 섹션이 Settings 탭에서 직접 토글/편집 가능하게 되었습니다.

### 개선

- **`templates/defaults/config.json` agile 섹션 정리**: REQ-586~591에서 부분적으로 추가된 설정 키를 spec 기준으로 정렬하고 누락된 기본값을 보강했습니다. 전부 `enabled=false` 기본값이므로 기존 프로젝트는 변경 없이 그대로 동작합니다.

### 버그 수정

- **`_resolve_required_globs_config` 빈 배열 fallback**: `templates/defaults/config.json`이 `required_globs: []`를 주입하면 REQ-587의 프로젝트 타입 기본값 fallback이 발동하지 않아 `test_required_globs_fallback`이 회귀하는 문제를 수정했습니다. 이제 빈 배열과 missing 모두 fallback 대상입니다.

### 호환성 / 마이그레이션

- 모든 신규 agile 기능은 `enabled=false` 기본값이므로 기존 프로젝트는 자동 활성화되지 않습니다. 사용하려면 `/mst:settings agile.evidence_gate.enabled true`와 같이 명시적으로 토글하세요.
- 기존 `details/*.md`는 evidence 필드 없이도 graceful 로드(stderr에 "evidence fields not defined (legacy format)" warning만)되어 무수정 호환됩니다.

---

## [0.57.0] — 2026-04-08

> **agile 스킬 통합 결여 해결 — "Sprint가 사용자에게 전달할 수 있는 변화"를 단위로 삼는 재프레이밍**
>
> slide-craft 사례(Sprint 추적상 DoD done 22/22인데 실제 플러그인 미동작)처럼 "격리된 단위 헬퍼만 만들고 통합 없이 done 처리되는" 패턴을 구조적으로 차단합니다.

### 새 기능

- **Sprint 종류 자기선언 + 지연 승격**: 모든 Sprint는 `user_observable`(사용자가 이제 볼/할 수 있는 변화 포함) 또는 `foundational`(기반 작업, 사용자 관찰 불가) 중 하나로 자기선언합니다. `foundational` Sprint에 포함된 DoD는 `proposed_done`으로 대기하고, 첫 번째 후속 `user_observable` Sprint 완료 시 `--deferred-promote`로 일괄 `done` 승격됩니다. `foundational` 연속 한도는 2(Sprint 0 제외).
- **누적 통합 리뷰 (2.2.0.7)**: Sprint 시작 시 직전 3 Sprint의 변경 파일을 `modify / wire / new-island` 3분류로 판정합니다. `new_island` 비율이 `agile.new_island_threshold`(기본 0.20)를 초과하면 이번 Sprint를 강제로 "통합(wire) 작업"으로 전환하여 새 DoD 진행보다 기존 산출물 통합을 우선합니다.
- **기획-구현 정합성 점검 (2.2.0.8)**: 누적 통합 리뷰 직후 PM이 3축(DoD-변경 매핑/DoD 현실 가능성/기획 노후화)으로 판정합니다. `objective_stale` 판정 시 비상 스티어링 강제 진입으로 `objective.md` 재계획을 요구합니다.
- **plan -a `[누적층]` 컨텍스트**: `mst:plan -a` 호출 시 직전 K Sprint의 통합 컨텍스트 파일(`integration-context.md`)을 **필수 Read 대상**으로 전달합니다. plan은 이 파일을 기반으로 "이전 산출물 위에 쌓을지 / 고칠지 / 엮을지"를 결정합니다.
- **스티어링 보고서 통합 건강 지표**: 정기 스티어링 체크포인트에서 직전 K Sprint 분류 비율, 연속 user_observable/foundational Sprint 수, `proposed_done` 대기 DoD 수, alignment 판정 분포, Escape Hatch override 횟수를 한 섹션으로 표시합니다.
- **결정론 헬퍼 2종**: `mst.py agile integration-review`(3분류 + verdict + integration-context.md 자동 생성) / `mst.py agile alignment-package`(objective + 누적 결과 경로 JSON 패키지). 각 헬퍼는 git 상태만으로 결정론적 출력을 보장하여 pytest 회귀 11건으로 전수 검증됩니다.

### 개선

- **PM Escape Hatch**: `integration-review`가 false positive를 낼 수 있는 환경(동적 import/매크로 기반 언어 등)을 고려해, PM이 `auto-decisions.md` 또는 `retrospective.md`에 명시적 사유를 기록한 경우에만 verdict 무시를 허용합니다. 사유 없는 무시와 연속 2회 이상 override는 금지 패턴으로 명시됩니다.
- **agile-plan 1A.7 가드레일 5중 확장**: DoD 작성 시 "이 DoD가 어떤 Sprint에서 사용자 관찰 가능하게 만들어질 것인가?" 사고 프롬프트를 추가합니다 (비차단, quality-gate-log 메타데이터 권장).
- **config agile 키 4개 추가**: `integration_review_depth=3`, `new_island_threshold=0.20`, `foundational_streak_max=2`, `integration_wire_streak_max=3`.

### 호환성 / 마이그레이션

- 진행 중인 AGI 세션은 **자동 마이그레이션되지 않습니다.** 기존 `done` 상태 DoD는 그대로 유지되며 강등되지 않습니다.
- 새 룰(Sprint 자기선언, 통합 부채 게이트, alignment check)을 적용하려면 **새 AGI 세션을 시작**하세요. 기존 세션을 그대로 진행하면 기존 룰로 계속 동작합니다.
- `agile objective-transition`, `agile result` 등 기존 명령의 신규 인자(`--sprint-kind`, `--deferred-promote`)는 모두 선택적이며, 미지정 시 기존 동작을 그대로 유지합니다 (하위 호환).

---

## [0.56.2] — 2026-04-05

### 새 기능

- **return_to 스킬 복귀 가드**: 서브 스킬 완료 후 `return_to=` 마커를 감지하여 부모 스킬로 자동 복귀, 불필요한 정지 차단
- **Agile 루프 무동작 계속 가드**: 스프린트 루프 활성 상태에서 다음 액션이 없을 때 자동으로 계속 진행

### 개선

- **스프린트 상세 UI 강화**: phase badge, goals 달성률, summary/outcome 표시 추가 + sprint_goals 미존재 시 planned/completed/summary/outcome/generated 카드 형태 fallback
- **스프린트 목록 카드**: planned/completed 수량, goals 달성률, summary 미리보기 표시
- **STEERING_DISABLED 정지 차단**: `steering_disabled=true` 시 AUTO_MODE 무관하게 스프린트 간 정지 완전 차단
- **Agile -a 모드 정지 제거**: 자동 모드에서 스프린트 간 불필요한 정지를 유발하는 금지 패턴 3종 + 우회 패턴 3종 추가
- **위임 기능 권한/모니터링**: stdin null 처리, Codex sandbox 분기, config delegation, 실행 모니터링 개선
- **accept 후 정지 금지 강화**: accept 반환 후 어떤 사유로든 정지를 절대 금지하는 가드레일 추가

---

## [0.56.1] — 2026-04-04

### 새 기능

- **Agile 대시보드 deep link**: `/agile/AGI-NNN/objective` URL로 직접 접속하면 해당 세션과 objective 탭이 자동 선택됨
- **설계 의도 검증 루프**: approve Step 5.7에 검증 에이전트 디스패치 + 보완 루프 + 모드 분기 삽입
- **검증 에이전트 프롬프트 템플릿**: approve Step 5.7 설계 의도 검증용 표준 프롬프트 추가
- **Adversarial Multi-Perspective 코드 리뷰**: Pass B에 adversarial_reviewer 역할 추가, 7개 attack surface 프롬프트, confidence→severity 매핑

### 개선

- **Agile 스티어링 체크포인트**: 정기/비상 스티어링 AskUserQuestion 추가 + off-by-one 조건식 수정 + 금지 패턴 강화
- **Preset agent_assignments 교체**: deep_merge 후 replace 후처리로 미포함 provider 잔류 방지
- **Sprint Detail 간결화**: PROVE/Retro Collapsible 접힘 + phase 배지 + 현재 Sprint 강조
- **Preset 에이전트 정합성**: 12개 preset에 workflow.default_agent + agent_assignments 추가
- **Sprint 중 디자인 수정**: AI 자율/사용자 요청/review 발견 3가지 경로 지원
- **Overview DoD 우선순위 그룹**: MoSCoW 그룹 정렬 + Sprint 귀속 + 마크다운 렌더링

---

## [0.56.0] — 2026-04-02

### 새 기능

- **Agile 자율 실행 엔진**: `/mst:agile` + `/mst:agile-plan` 스킬 신설 — JTBD 기반 objective 문서 생성, Sprint 0→N 자율 루프, 프로젝트 건강 우선 모델, 스티어링 체크포인트
- **Agile 대시보드**: 타임라인 흐름도, 스프린트 세부 패널(3컬럼), Objective 실시간 편집기, Result 탭(WHY/WHAT/HOW PROVE 구조), 회고 렌더링, 코멘트 기능
- **Sprint 비교 기능**: Result 탭 비교 토글 + 좌우 분할 뷰로 스프린트 간 성과 비교
- **Sprint 회고(Retrospective)**: 독립 에이전트 검토 + 보완 스프린트 + known issue 추적 + 교훈(lessons_learned) 전달
- **노션형 마크다운 에디터**: Milkdown 통합으로 Objective 문서 WYSIWYG 편집
- **plan-doc 문서 실행 파이프라인**: doc-request 템플릿(reference/decision/ops/auto) + 문서 유형 6개 확장 + 검증 루프
- **Plan type dispatcher**: 4개 스킬(plan/plan-doc/agile-plan/doc-request) 타입별 자동 분기

### 개선

- **Agile 스프린트 루프 안정화**: 3계층 방어(금지 패턴 + hook 화이트리스트 + CONTINUATION GUARD)로 임의 중단 차단
- **Review 검증 체계화**: Static Validation Gate + 커버리지 매트릭스 + PM 판정 기계화 + Full Backend Test Gate
- **DoD 품질 게이트**: IEEE 830 + IREB + ODI 기반 DoD 검증 + DoR 준비도 체크
- **Result 탭 재설계**: 도메인별 계층 탐색 + 테스트 4단 구조(의도/전략/흐름/결과) + 시각 자료 인라인 렌더링
- **Hook 시스템 단순화**: mst-loop 스타일 단일 re-feed stop hook으로 교체
- **agile-plan 대화 문서화**: 재귀 탐색 루프 재설계(갯수 제한 제거 + 수렴 판정) + 상세 보존 원칙
- **Windows 호환성**: SIGTERM OS 분기, 경로 구분자 정규식, 대시보드 Windows 명령어 지원
- **Agile Comments 패널**: 접기/펼치기 토글 버튼 + localStorage 상태 유지
- **스토리 목록 가시성**: ID + anchorText 동시 렌더링 + 시각적 강조

### 버그 수정

- **DoD 항목 텍스트 동일 표시**: contentText 순방향 추출 + 프론트 우선 표시로 수정
- **Stitch HTML 미리보기**: downloadUrl JSON 서빙/저장 버그 수정
- **Worktree hooks 복사 누락**: worktree 생성 시 .claude/hooks/ 자동 복사
- **Sprint 클릭 미갱신**: sprint_id 병합 순서 + objective 경로 + 스프린트 자동 선택 복구
- **Hook format 버그**: mst-stop-hook.sh format 오류 + updated_at 테스트 추가

---

## [0.55.4] — 2026-03-23

### 새 기능

- **plan UI 감지 확장**: 기존 화면이 대규모로 수정될 때도 Stitch 시안 확인을 자동 트리거

### 개선

- **HUD transcript JSONL 전환**: statusline transcript를 JSONL 파싱 기반으로 전환하여 안정성 향상
- **HUD continuation-guard 교차 검증**: transcript 단일 소스 전환 및 push/pop 콜스택 제거로 guard 로직 단순화

### 버그 수정

- **Stitch HTML 미리보기 fetch 오류**: download URL 대신 실제 HTML을 fetch하도록 수정

---

## [0.55.3] — 2026-03-22

### 새 기능

- **PAC-Evidence Ledger**: review Pass A에서 AC/PAC 검증 증거를 evidence-ledger.md로 자동 수집, accept 시 증거 존재 여부 검증 게이트 추가
- **4-Phase 의미 게이트**: plan/request/review/accept 스킬에 Gate + Anti-Rationalization Checklist 표준화
- **Risk-tiered TDD**: plan/request 스킬에 TIER-A/TIER-B 태깅 메커니즘 도입
- **4-Phase 디버깅 템플릿**: debug 에이전트 프롬프트에 구조화 보고 양식 주입 + 3회 실패 시 architect 승격

### 개선

- **mst:claude CLI 전환**: claude 서브에이전트 실행 방식을 Agent에서 Bash(claude CLI) 기반으로 전환
- **자율 모드 판단 교정**: AUTO_MODE 판단 패턴 프레이밍 교정 + Cynefin 자동 분류 보조
- **Stale 마커 구조적 해결**: session-init hook에 plan.json next_action 정리 로직 추가
- **HUD 이모지 제거**: statusline 출력에서 불필요한 이모지 제거

### 버그 수정

- **HUD 스킬 depth 표시 오류**: skill 필드 sanitization (쓰기+읽기 양쪽 방어)
- **review SKILL 중복 섹션 정리**: evidence-ledger 프로토콜 중복 제거

---

## [0.55.2] — 2026-03-22

### 개선

- **approve → accept 인라인 배치**: review PASS 후 accept 호출을 approve 스킬 내에서 직접 실행하여 워크플로우 단축
- **런타임 마커 경로 격리**: /tmp 마커를 .gran-maestro/tmp/로 이동하여 크로스 프로젝트 오염 방지
- **explore 스킬 상세화**: explore SKILL.md를 debug 수준으로 상세 기술하여 탐색 품질 향상
- **Reference 상세 보기 탭 분리**: metadata/content 탭으로 분리하여 가독성 개선
- **plan 프로토콜 우회 금지 규칙**: /mst:plan 호출 시 주제 성격과 무관하게 전체 프로토콜 실행을 강제하는 규칙 추가

### 버그 수정

- **stop hook debug_log 호출 순서**: 함수 정의 전 호출되던 오류 수정

---

## [0.55.1] — 2026-03-22

### 개선

- **Reference 대시보드 content 조회**: Reference 상세 보기에서 content.md 내용이 표시되도록 수정
- **대시보드 서버 권한 확장**: Deno --allow-run에 node, tar 추가로 디자인 refresh/아카이브 권한 오류 해소
- **plan 테스트 전략 기본값 변경**: plan_qa_presets.test_strategy 기본값을 ask에서 apply-80으로 변경

---

## [0.55.0] — 2026-03-22

### 새 기능

- **Reference 시스템**: 외부 참조 자료의 저장·신선도 체크·스킬 자동 참조 인프라 신설 + 대시보드 UI 및 Settings 연동
- **plan-doc 문서 전용 플래닝**: 소스 조사→구조화→팩트체크 반복 루프 기반 문서 작성 스킬 추가
- **Stitch MCP→SDK 전환**: @google/stitch-sdk 래퍼 기반으로 디자인 생성 파이프라인 전면 교체
- **사용자 정의 Loop 종료 조건**: plan Step 2.45에서 수집한 커스텀 게이트를 review에서 검증하는 체계
- **review browser-test 사전 검증**: 탭 나열·스크린샷·선택자 확인 3단계 게이트로 브라우저 테스트 안정성 향상
- **review impact_reviewer**: Pass B에 영향 범위 분석 절차 추가 — 2단계 역추적 + 소스 읽기 + 기능 유지 판단
- **review browser_tester 위임**: 저렴한 에이전트에 browser-test AC를 위임하는 config 기반 분기
- **Stop hook next_action 체크**: plan→request 워크플로우 강제 시스템으로 스킬 체인 이탈 방지
- **Stitch 인증 가이드 흐름**: 인증 실패 시 우회 대신 API Key 설정을 안내하는 구조화된 흐름
- **디자인탭 시안별 편집/대체시안/새로고침**: Refresh API + Alt 설정 UI + 탭 비교 기능
- **디자인탭 스크린 고유번호(SCR-NNN)**: 넘버링 + Copy 버튼으로 디자인 관리 편의성 향상
- **HTML 미리보기 전체화면**: DesignView Dialog 기반 전체화면 모달 추가
- **Hook 원본 디렉토리 체계**: hooks/ 원본 + .claude/hooks/ 복사본 구조로 Hook 관리 일원화

### 개선

- **plan 자율모드 가드레일**: -a 모드에서 직접 구현 전환 금지 + 실행 제약 보강
- **테스트 방법론 통합**: plan 테스트 의도 질문 + request 테스트 전략 게이트 + spec 보조 태그
- **Shell hook continuation 개선**: stop_hook_active 파싱 + 구체적 block 메시지 + PENDING_FILE next_step
- **user-profile.json**: 13개 스킬 + pm-conductor AskUserQuestion 용어 수준 적응
- **Settings Workflow Pipeline**: 독립 스크롤바 + models.roles 인라인 편집 + Review Iterations 표시
- **대시보드 Designs 탭**: DESIGN.md 접이식 패널 + plan/request에서 자동 참조
- **Codex native review 통합**: config use_native_review 필드로 옵셔널 코드리뷰 연동
- **README 전체 현행화**: Quick Start 보강 + plan 중심 end-to-end 자동화 반영
- **Trace 문서 경량화**: Bash 자동 생성 + TRACE_SAVED 메시지 제거
- **explore 백그라운드 완료 대기 의무화**: 부분 결과로 종합 시작하는 문제 방지

### 버그 수정

- **아카이브 시스템**: 타입별 max_active_sessions 기본값 변경 + 버그 수정
- **hook 경로 CWD 독립 처리**: 누락 hook 참조 제거
- **PLUGIN_ROOT 경로 규칙**: SKILL.md 상대경로 에러 방지

---

## [0.54.4] — 2026-03-19

### 새 기능

- **의도→계획→개발→검증 하네스 강화**: AC 트레이스 + Intent Blocking + 역방향 시뮬레이션으로 의도 문서 기반 검증 체계 강화
- **서브스킬 returnTo continuation guard**: 서브스킬 완료 후 부모 스킬로 자동 복귀 메시지 출력으로 대화 중단 방지

### 개선

- **서브스킬 세션 격리**: pending_continuation 플래그 + PPID 기반 세션 격리로 서브스킬 반환 안정성 향상
- **대시보드 백업 버튼 보강**: 에러 피드백/로딩 상태 추가 + double-click guard + 서버 보강
- **plan 선택지 장단점 규칙 확대**: 모든 다중 선택지 AskUserQuestion에 장단점·추천 필수 규칙 적용

---

## [0.54.3] — 2026-03-18

### 새 기능

- **Q&A 컨텍스트 캡처 시스템**: AskUserQuestion hook으로 질문/답변 자동 캡처 + 선호 패턴 요약 + SKILL.md MANDATORY Read 연동

### 개선

- **트레이스 상태 안정성**: TRACE_DONE→TRACE_SAVED 리네임 + 부모 프레임 TTL touch로 종료 오인 방지

---

## [0.54.2] — 2026-03-16

### 새 기능

- **브라우저 UI 테스트 워크플로우**: UI 변경 시 plan/request/review 스킬에서 브라우저 테스트 자동 연계 + 대시보드 탭 추가
- **브라우저 테스트 스크린샷 캡처**: Playwright/Chrome별 캡처·저장·검증·fallback 절차 구체화

### 개선

- **AskUserQuestion 품질 개선**: 빈 선택지 금지, API 제약 반영(옵션 최대 4개), markdown 상세 설명 2유형 체계 도입
- **콜스택 Hook 시스템 보강**: Pop 스킬명 검증, jq→python3 전환, TTL 좀비 제거, 디버그 로깅, 깊이 상한 추가
- **콜스택 세션 안전성**: 세션 시작 시 스택+카운터 자동 초기화로 강제 중단 시 스택 오염 방지
- **DONE 멈춤 근본 해결**: PreToolUse/PostToolUse push/pop + Stop hook depth 판단 + CONTINUATION GUARD 간소화

---

## [0.54.1] — 2026-03-15

### 개선

- **워크플로우 info 노드 편집**: ReadonlyFieldCard에 타입별 편집 컴포넌트 적용 (boolean→Switch, number→Input, string→Select/Input)
- **서브스킬 반환 후 멈춤 방지**: CONTINUATION GUARD를 request/accept/recover/picks/debug/plan 스킬에 일괄 추가 + Stop hook 범용 안전망
- **Intent 스킬 DB 단일화**: md 파일 이중 저장 제거, `_sync_markdown_record`/`template` 삭제, rebuild FTS 전환

---

## [0.54.0] — 2026-03-15

### Breaking Changes

- `mst:start` 스킬 제거 — `/mst:start` 호출 불가, `/mst:request` 사용 필요
- `collaborative_debug.auto_trigger_from_start` → `auto_trigger_from_request` 키 리네임 (구 키 런타임 호환 없음)

### 새 기능

- **Intent 시스템**: 기능 의도(Intent) 저장소 도입 — SQLite 기반 CRUD, 검색, 연관 탐색 지원 (`mst:intent`)
- **Intent 통합**: plan/request/review/accept 스킬에서 Intent 자동 참조 및 대조 검증
- **대시보드 Intent 관리 UI**: 목록/검색/CRUD/연관 탐색 화면 추가
- **대시보드 Overview 개선**: Hero KPI + 활성 목록 + Quick Actions → Next Steps + Project Pulse 교체
- **mst:gardening 스킬**: stale plan/spec/intent 자동 스캔 리포트
- **mst:plan 강화**: INVEST 방법론 적용, 보조 선택지(ideation/discussion/explore) 필수화, 저오버헤드 방법론 4종 반영
- **plan → request 전환 개선**: DAG 자동 연쇄 실행 지원
- **설정 UI**: Agent 중심 재구성, 워크플로우 동작 제어 탭 분리, 모델 공급자 프리미엄/이코노미 인라인 편집
- **설정 Find & Replace**: 배열 필드 검색/교체 지원
- **Picks 탭 개선**: All 필터 전체 표시, 기본 필터 pending, 캡처 취소 기능 추가
- **Stitch 스킬**: 대시보드 디자인 링크 출력 추가 (멀티스타일/사용자보고/Redesign 통합)

### 개선

- approve Step 5 self-check 결과를 request.json에 기록
- approve 에이전트 친화적 에러 메시지 포맷터
- spec.md §0 Context Manifest 섹션 추가
- accept squash-merge 커밋 메시지 양식 자동 감지
- A-lite 파일 체크포인트 + mst:recover Step 수준 확장
- 스킬 실행 단일 마커 통합 + 서브스킬 반환 프로토콜 통일
- plan 스킬 CONTINUATION GUARD 강화 — 서브스킬 반환 후 즉시 재실행 규칙 명확화
- 리뷰 프롬프트에 spec/plan 참조 추가 + background reviewer 파이프 방식 버그 수정
- 설정 역할 테이블 Enabled ON/OFF 배지 토글 기능
- 설정 워크플로우 탭 배열 필드 TagInput(칩) UI 전환
- Settings readonly Input 시각적 표시 강화
- Settings/Intents 헤더 버튼 아이콘화 + 툴팁 전환
- pending_dependency 자동 해제 훅 — done 전환 시 자동 호출

### 버그 수정

- Extension 즉시모드 클립보드 메모 잘림 버그 수정
- Intents API cwd 경로 버그 수정 (500 에러 해소)
- 리뷰 에이전트 샌드박스 파일 저장 실패 해결
- wait-files / merge 타임아웃 10분으로 증가 (안정성 개선)
- mst.py P0 스크립트화: config get + capture mark-consumed subcommand 추가

---

## [0.53.2] — 2026-03-11

### 버그 수정

- `mst:stitch`: HTML 미리보기 연결 결함 수정 — SKILL.md, designs.ts, DesignView 반영

---

## [0.53.1] — 2026-03-10

### 버그 수정

- `mst:approve`: gemini-dev 외주 호출 시 `--approval-mode yolo` 누락으로 background 실행 중 hung 상태 발생하던 문제 수정
- `mst:approve`: gemini-dev 호출에 `--model` resolve 코드 추가 — codex-dev 패턴과 일관성 확보
- `mst:dashboard`: DesignView HTML 미리보기 버튼이 표시되지 않던 문제 수정

---

## [0.53.0] — 2026-03-10

### 개선

- `mst:approve` + `mst:review`: Phase 3 PASS 후 `[TRACE_DONE]` 신호를 종료 신호로 오인해 `mst:accept` 미호출로 불쑥 종료되던 문제 수정
  - `approve/SKILL.md`: `Skill(mst:review)` 반환 직후 "즉시 결과 처리로 진행" reminder 추가
  - `review/SKILL.md`: Phase 3 PASS 분기에서 "review는 mst:accept를 직접 호출하지 않는다" 명시
- `mst:request` Step 1d-arch 아키텍처 논의 게이트 신설 (`mst:request Step 1d-arch`)
- `mst:approve` `base_branch` 설정 마법사 및 안내 추가
- `mst:approve`/`mst:request` AUTO_MODE 전환 프로세스 및 지원 패턴 개선
- auto 모드 매뉴얼 문서 추가 (plan / request / approve)

---

## [0.52.0] — 2026-03-10

### 개선

- `mst:request`에 **Step 1.8 구현 세부 Q&A Pass** 추가: Step 1g 이후 Step h-0 이전에 7개 카테고리(에러/실패처리, 엣지케이스, 데이터 변경, 호환성, 성능, 테스트 범위, 배포 전략)를 `AskUserQuestion`으로 순차 확인
- Step 1.8에서 각 질문에 `"해당 없음"` 선택지를 포함하고, 모호한 답변은 최대 3회 재질문 후 PM이 가장 안전한 선택으로 자동 결정하도록 규칙화
- `AUTO_APPROVE=true`일 때 Step 1.8을 완전 skip하도록 분기 추가
- Spec Pre-review 에스컬레이션 모드를 `AUTO_APPROVE` 기준으로 변경: `AUTO_APPROVE=false`면 항상 사용자에게 `AskUserQuestion`으로 처리 방식 확인, `AUTO_APPROVE=true`면 `pm-self` 자동 반영 유지

---

## [0.51.1] — 2026-03-09

### 개선

- `mst:plan`이 태스크 분해를 다루지 않도록 범위 명확화 — plan은 REQ 단위 분리까지만 고민하고, 태스크 분해는 `mst:request`가 코드베이스 탐색 후 독자적으로 결정
- `templates/plan.md`에서 `## 태스크 분해` 섹션 제거
- `mst:request`가 plan.md의 태스크 분해 섹션을 명시적으로 무시하도록 수정

---

## [0.51.0] — 2026-03-09

### 새 기능

- **OMX Autopilot 통합**: `config.json`에 `omx` 섹션 추가 및 `approve` 스킬에 `$autopilot` 조건부 삽입으로 oh-my-codex 자율 실행 지원
- **Plan-Review 관점 강화**: `intent_validator`에 Ontologist 관점(핵심 개념 정의 확인), `scope_critic`에 Brownfield 충돌 리스크 관점 추가

### 개선

- **plan/request 역할 분리**: `plan` 스킬은 스펙 정제, `request` 스킬은 실행 착수로 역할을 명확히 분리하고 `spec.md` 경량화
- **오실레이션 탐지 가이드**: `plan` 스킬에 3.8.3 반복 진동(오실레이션) 감지 및 PM 판단 가이드 삽입
- **Scope Audit 관점 추가**: `review` 스킬 `arch_reviewer`에 SCOPE_CREEP/OMISSION 감지를 위한 Scope Audit 관점 강제 추가
- **스키마 안전성·태스크 매핑·SKILL.md 복잡도 개선**: REQ-312 후속 우려사항 3종 해소
- **Squash 머지 브랜치 전략**: PR 머지 시 Squash 머지를 기본으로 도입해 히스토리 가독성 향상

### 버그 수정

- **premium tier 직접 전달 버그**: `request` SKILL.md 모델 resolve 로직에서 premium tier가 올바르게 전달되지 않던 문제 수정

---

## [0.50.0] — 2026-03-08

### 새 기능

- **Pass A/B 2패스 리뷰 구조**: `review` → `approve` → `feedback` 스킬 전반에 걸쳐 Pass A(MUST AC 검증)와 Pass B(코드·아키텍처·UI 품질) 이중 검증 체계 도입. `pass-a-result.md` 스키마로 결과 공유
- **자율 실행 모드 (`-a` / `--auto` 플래그)**: 사용자 개입 없이 approve 루프를 끝까지 자동 실행하는 AUTO_MODE 지원
- **에이전트 배정 도메인 추론**: 파일 타입 표 대신 `agent_assignments` 도메인 추론 방식으로 에이전트 자동 배정. `config.json`에 기본값 추가
- **`request set-phase` 커맨드**: CLI에서 요청의 Phase를 직접 전환하는 서브커맨드 추가
- **설정 UI Dropdown**: 설정 항목에 선택값 제한(Select/Dropdown) 위젯 지원 추가
- **대시보드 Settings Accordion**: 설정 UI를 아코디언 패널로 재구성, 전체 프로젝트 일괄 적용 버튼 추가

### 개선

- **스킬 AC 형식 강화**: `spec.md` 인수 기준(AC)에 Lite/Standard/High-Risk 분기 및 Test Scenarios 섹션 추가. `plan.md`에 AC 초안 섹션 추가
- **`failure_class` 기반 자동 라우팅**: `feedback` 스킬에서 실패 유형(`failure_class` + `evidence`)을 기반으로 설계 재검토 vs. 재구현 분기 자동화
- **`pass_a_failed` 처리 단일화**: approve 루프 내 Pass A 실패 태스크 선별 및 재진입 로직 통일
- **Stitch·Recover 스킬 UX**: 항상 `AskUserQuestion` 옵션을 제공하도록 개선
- **Gemini CLI `--dir` 옵션**: 워크트리 디렉토리 전환 지원으로 멀티-리포 환경 호환성 향상
- **README What's New**: Extension Pick→Plan 흐름 신규 섹션 추가

### 버그 수정

- **Custom 배지 미표시**: `count=0` 에이전트 설정 시 tier 기본값 누락으로 Custom 배지가 표시되지 않던 문제 수정
- **Stitch HTML 미추출**: 비동기 응답 시 HTML이 추출되지 않던 버그 수정

---

## [0.49.1] — 2026-03-06

### 개선

- **프리셋 모델 기본값 업데이트**: Codex·Gemini 프리셋의 기본 모델 티어를 economy로 변경하여 비용 효율 개선

---

## [0.49.0] — 2026-03-06

### 새 기능

- **config migrate 마법사**: `config migrate` 서브커맨드로 구 포맷(숫자) 에이전트 설정을 신 포맷(`{count, tier}` 객체)으로 자동 변환, dry-run 미리보기 지원
- **config resolve 구 포맷 경고**: `config resolve` 실행 시 구 포맷이 감지되면 마이그레이션 안내 메시지 표시

### 개선

- **모델 설정 체계 통일**: providers+roles 분리형 구조로 모델 설정 일원화, 스킬 10개 문서 마이그레이션
- **외주 에이전트 워크플로우 안정화**: 에이전트 완료 후 approve 워크플로우가 중단되지 않도록 dispatch 통일
- **설정 마법사 Diff Preview**: 프리셋 적용 전 변경사항 미리보기 단계 추가
- **README 리뉴얼**: `/mst:plan` 중심 스토리텔링으로 사용 가이드 재구성
- **MIT 라이선스 전환**

---

## [0.48.2] — 2026-03-06

### 버그 수정

- **스크린샷 미리보기 누락 수정**: captureVisibleTab 실패 원인을 해결하여 스크린샷 미리보기가 정상 표시되도록 수정

---

## [0.48.1] — 2026-03-06

### 버그 수정

- **Pick Element 더블클릭 문제 해결**: 요소 선택 시 더블클릭으로 인한 팝업 중복 표시 문제를 수정하고 팝업 자동 닫기 처리

---

## [0.48.0] — 2026-03-05

### 새 기능

- **캡처 스크린샷 저장**: 캡처한 UI 요소의 스크린샷을 로컬에 저장하는 기능 추가
- **Stitch 멀티 스타일 디자인 뷰**: DesignView에서 스타일별 그룹 갤러리로 디자인 결과를 확인 가능
- **Stitch HTML iframe 렌더링**: 디자인 결과를 이미지 외에 HTML iframe으로도 렌더링 지원
- **Inspector 엘리먼트 정보 라벨**: 하이라이트 시 태그명·클래스 등 엘리먼트 정보를 라벨로 표시
- **멀티 스타일 × 멀티 화면 그룹핑**: 스킬·백엔드·프론트엔드에서 복수 스타일과 복수 화면을 그룹화하여 관리
- **캡처 cancelled 상태**: 캡처 스키마 전 스택에 cancelled 상태 추가로 라이프사이클 완성
- **LifecycleTimeline 리디자인**: 모던 미니멀 스타일로 타임라인 컴포넌트 전면 재설계

### 개선

- **Picks 대시보드 링크**: picks 스킬 출력에 CAP ID와 프로젝트 링크 포함
- **캡처 목록 기본 필터**: consumed/done/archived 상태를 기본 필터에서 제외하여 가독성 향상
- **Settings 프리셋 마법사 모달 재설계**: 프리셋 선택 UX를 마법사 형태로 개선
- **Pick Element UX 개선**: 싱글클릭 선택, 자동 포커스, Enter 캡처 등 직관적 조작

---

## [0.47.6] — 2026-03-05

### 새 기능

- **Codex CLI 모델 설정**: Codex 실행 시 사용할 모델을 config에서 지정 가능 (`models.codex.default`)
- **Settings 프리셋 시스템**: `/mst:settings preset` 명령으로 12종 내장 프리셋 적용·조회·관리 지원
- **대시보드 Settings 프리셋 UI**: Settings 탭에서 프리셋을 시각적으로 선택·적용 가능

### 개선

- **Picks 탭 네비게이션 우선순위**: Picks 탭이 대시보드 탭 바에서 맨 앞으로 이동, 단축키 순서 재배치
- **Pick Element 키보드 간섭 해소**: Pick Element 후 패널 입력 시 웹페이지 단축키가 간섭하지 않도록 억제

---

## [0.47.5] — 2026-03-05

### 개선

- **Extension 버전 동기화**: 플러그인 캐시와 프로젝트 소스 간 Extension 버전 불일치 해소를 위한 패치 버전업

---

## [0.47.4] — 2026-03-05

### 개선

- **인증/토큰 시스템 전면 제거**: Dashboard 서버의 불필요한 인증 레이어를 제거하여 연결 단순화
- **Inspect 모드 키보드 단축키 억제**: Inspect 모드 활성 시 웹페이지의 키보드 단축키가 간섭하지 않도록 일시 억제
- **Inspect 모드 1회성 Pick Element UX**: Inspect 모드를 토글 방식에서 1회성 요소 선택 방식으로 전환하여 직관성 향상
- **ensure-copy content hash 비교**: Extension 복사 시 content hash 비교를 적용하여 불필요한 복사 방지
- **bump.py 크롬 익스텐션 버전 동기화**: 버전 bump 시 Extension 버전도 자동으로 동기화 (5파일 일괄 관리)

---

## [0.47.3] — 2026-03-04

### 개선

- **Extension 아이콘 업데이트**: Chrome Extension 아이콘 이미지 갱신

---

## [0.47.2] — 2026-03-04

### 개선

- **Extension Capture API projectId 경로 포함**: 캡처 API 경로에 projectId를 포함하여 프로젝트별 캡처 정확도 향상
- **Extension 프로젝트 드롭다운 안정성 강화**: race condition 추가 수정 및 auto-refresh 기능 추가

---

## [0.47.1] — 2026-03-04

### 버그 수정

- **Chrome Extension 프로젝트 드롭다운 race condition 수정**: 프로젝트 목록 로딩 중 드롭다운 선택 시 발생하던 경쟁 상태 해결

---

## [0.47.0] — 2026-03-04

### 새 기능

- **Inspect 모드 Enter 키 선택**: 키보드 Enter로 요소 선택 가능 + mousemove 잠금으로 정밀 선택 지원
- **HTML 스마트 트리밍**: 캡처된 HTML의 불필요한 부분을 자동으로 제거하여 컨텍스트 효율 개선

### 개선

- **bump 스크립트 빌드 통합**: 버전업 시 Extension/Frontend 자동 빌드 + 실패 시 중단 안전장치 추가

---

## [0.46.1] — 2026-03-04

### 새 기능

- **Chrome Extension (UI Picker)**: MV3 기반 캡처/메모/태깅/즉시모드/오버레이 Chrome Extension 구현
- **Extension 설치 스킬**: `/mst:setup-extension` 스킬로 Load Unpacked 방식 설치 안내 자동화
- **Picks 스킬**: `/mst:picks`로 captures 큐에서 자연어 항목 선택 및 plan 연동
- **캡처 REST API**: POST/GET/PATCH captures 엔드포인트 + SSE 실시간 스트림 + Origin/토큰 인증
- **Picks 탭 UI**: 대시보드에 Picks 뷰 추가 및 StatusBadge 캡처 상태 색상 표시
- **Lifecycle Timeline**: 대시보드에 라이프사이클 타임라인 통합 및 PicksView 상세 패널 연동
- **서버 /api/health 엔드포인트**: Extension healthCheck body 검증 강화
- **Stitch 모델 선택 설정**: config에 Stitch 모델 설정 추가 및 `--redesign` 옵션 신설

### 개선

- **CLI 셸 exit code 전파**: 8개 스킬, 26개 위치에서 exit code 올바르게 캡처 및 전파
- **스킬 절대경로 컨벤션**: worktree-manager 및 23개 스킬 파일에 절대경로 컨벤션 도입
- **Codex/Gemini provider 간소화**: Claude 래퍼 제거, Bash 직접 호출로 변경
- **카운터 동기화 보정**: 매 호출마다 max(counter, disk) 보정으로 ID 충돌 방지
- **캡처 TTL 자동 아카이브**: 만료된 캡처 자동 정리
- **plan/spec 캡처 참조 템플릿**: `[CAP-NNN]` 컨텍스트 주입 체이닝 지원
- **Extension Graceful Degradation**: 서버 미연결 시 안정적 동작 + Overlay ID 통합

### 버그 수정

- **Extension 팝업 UI 버그 수정**: 팝업 UX 개선 (B1, B2, U1, U2)
- **Extension sendMessage 에러 처리**: Promise 기반 `.catch()`로 비동기 에러 올바르게 처리

---

## [0.46.0] — 2026-03-02

### 새 기능

- **CLI config resolve 명령어**: `config resolve <key>` 명령으로 최종 병합된 설정값 조회 지원
- **Hook 설정**: CLI 훅 구성 및 스킬 경로 변경 지원

### 버그 수정

- **WorkflowView 태스크 선택 수정**: 태스크 클릭 시 selectedTask가 갱신되지 않던 버그 수정

---

## [0.45.0] — 2026-03-02

### 새 기능

- **대시보드 SPA 라우팅**: React Router 기반 클라이언트 사이드 라우팅 도입으로 페이지 새로고침 없이 뷰 전환 가능
- **대시보드 신규 뷰 3종**: Overview(전체 현황), Archives(아카이브 관리), AgentPerformance(에이전트 성과 분석) 뷰 추가
- **아카이브 API**: GET /archives, POST /archives/:id/restore 엔드포인트로 아카이브 조회 및 복원 지원
- **통합 통계 API**: GET /stats, /stats/agents 엔드포인트로 전체 통계 및 에이전트별 성과 데이터 제공
- **워크트리 현황 API**: GET /worktrees 엔드포인트로 활성 워크트리 현황 조회 지원
- **SSE 이벤트 확장**: design_update/explore_update 패턴 추가 및 태스크 duration 필드 지원
- **Explore 에이전트 설정**: config에 explore 에이전트 구성 섹션 추가
- **리뷰 자동 수정 설정**: severity_auto_fix 설정으로 MINOR 이슈 자동 수정 정책 및 보안 키워드 오버라이드 지원

### 개선

- **공통 ListFilter 컴포넌트**: 5개 목록 뷰에 일관된 필터링 UI 적용
- **IdeationView 개선**: Explore 에이전트별 결과 탭 분리 및 React #310 적용
- **SettingsView 개선**: 배열 편집 UI, SETTING_DESCRIPTIONS 18키 보완, Modified/Custom 배지, Reset/Delete 버튼
- **DocumentsView 개선**: 트리 확장 및 파일 검색 기능 추가
- **NotificationPanel 개선**: 알림→세션 네비게이션, Sheet 자동 닫기
- **Header 상태 인디케이터**: mode.json 상태를 헤더에 실시간 표시
- **DebugView 개선**: Plan 링크, dependencies 표시, duration 정보 추가
- **백엔드 deepMerge**: 설정 API에 deepMerge 유틸 적용으로 부분 업데이트 지원

### 버그 수정

- **Path Traversal 취약점 수정**: Deno.realPath + baseDir 접두사 검증으로 경로 탐색 공격 방어
- **SettingsView lastSseEvent 버그 수정**: SSE 이벤트 상태 관리 오류 해결

---

## [0.44.1] — 2026-03-02

### 개선

- **Stitch 디자인 → 구현 전달 파이프라인**: Stitch에서 생성된 HTML/CSS 코드가 구현 에이전트에게 자동 전달되도록 개선 (spec.md §10에 html_file 절대경로 포함, impl-request에 읽기 지시 추가, IMPL_CONTEXT 자동 삽입)

## [0.44.0] — 2026-03-02

### 새 기능

- **MINOR 임계값 에스컬레이션**: 리뷰에서 MINOR 이슈가 설정된 임계값 이상 발견되면 자동으로 사용자에게 에스컬레이션하여 승인/거부 선택 제공
- **AskUserQuestion 장단점 포맷**: 선택지 제시 시 장단점 3줄형 포맷 가이드라인 추가로 사용자의 정보 기반 의사결정 지원

### 개선

- **리뷰 등급별 분기 처리**: 리뷰어 프롬프트에 등급 태깅, 체크리스트, 보안 오버라이드 적용하여 리뷰 품질 향상
- **approve MINOR 처리 개선**: PM이 MINOR 이슈를 직접 수정하는 분기 추가 및 FAIL 처리 보완
- **review SKILL.md enabled 가드**: 리뷰 비활성화 시 스킵 로직 추가 및 스키마·보안 키워드 동기화
- **README 및 매뉴얼 문서 갱신**: 7개 한글 문서 점검 및 갱신

---

## [0.43.1] — 2026-03-02

### 새 기능

- **Stitch 디자인 HTML 코드 자동 저장**: `output_components`에 포함된 HTML/CSS/React 코드를 `screen-NNN.html` 파일로 자동 저장
  - plan 디자인 시안 섹션에 구현 코드 경로 표시
  - `design.json` screens에 `html_file` 필드 추가

### 개선

- **prereview 반복 루프**: request 스킬에서 스펙 사전 검토를 반복 실행하여 CRITICAL/MAJOR 이슈 자동 수정
- **plan escalation_trigger 기반 변경**: plan 스킬 Step 3.8.5에서 escalation 조건을 config 기반으로 처리
- **Gemini --sandbox 옵션 제거**: gemini/discussion/plan/approve 스킬에서 불필요한 --sandbox 플래그 정리
- **대시보드 설정 찾아 바꾸기**: JSON value bulk replace 기능 추가
- **대시보드 Plan/Traces 탭 연동**: PlanDiagramTab 교차 링크 + Phase 2 실행 정보 표시
- **approve retry_count 기록**: approve 스킬에서 재시도 횟수를 메타데이터에 기록
- **discussion/ideation combined+split 패턴**: 병렬 Write 대신 combined+split 패턴으로 세션 파일 생성 안정화
- **아카이브 자동화**: accept 스킬 완료 시 `mst.py archive run-all` 자동 호출 + 대시보드 정리 버튼 추가

---

## [0.43.0] — 2026-03-02

### 새 기능

- **Phase 1 탐색 에이전트 role 기반 config 설정**: `config.json`의 `phase1_exploration.roles`로 탐색 에이전트를 교체하거나 비활성화 가능
  - `symbol_tracing` (기본: codex) / `broad_scan` (기본: gemini) 역할별 agent·enabled·model 설정
  - `enabled: false` 시 해당 에이전트 dispatch 생략; Claude 직접 탐색은 항상 활성

### 개선

- **Phase 1 3-way 병렬 탐색**: PM Conductor(Claude)가 codex/gemini와 동시에 직접 Read/Glob/Grep 탐색 수행
  - 총 소요 = `max(codex_time, gemini_time, claude_direct_time)` — 추가 지연 없음
- **Phase 1 탐색 명세 명확화**: pm-conductor.md + SKILL.md에서 하드코딩 제거, config 기반 role dispatch로 통일

---

## [0.42.0] — 2026-03-01

### 새 기능

- **mst:review 스킬**: 구현 완성도를 반복 검토하는 신규 스킬 추가 (`/mst:review REQ-NNN`)
  - spec AC 체크리스트 검증(Claude 인컨텍스트) + 코드/아키텍처/UI 리뷰어 병렬 실행
  - 갭 발견 시 태스크 자동 생성 → Phase 2 재실행 → max_iterations 도달까지 반복
  - `--auto` 플래그로 무인 실행 지원

### 개선

- **approve Phase 3 리뷰 루프**: `review.auto_review: true` 시 Phase 3에서 mst:review 자동 호출
  - passed → Phase 5 직행 / gap_found → 신규 태스크 Phase 2 재실행 / limit_reached → 사용자 선택
- **대시보드 REQ 카드 리뷰 뱃지**: 리뷰 진행 상태를 뱃지로 표시 (🔍 N회차 리뷰 중 / 🔄 갭 수정 중 / ⚠️ 리뷰 한계 도달)
- **config.json `review` 섹션 추가**: `auto_review` (기본 true), `max_iterations` (기본 3), 역할별 에이전트 설정
- **plan 리뷰 루프 (REQ-230)**: plan 확정 전 AI 팀 검토 단계 추가 (Step 3.8)
- **Pre-review 에이전트 설정**: `prereview` config 섹션으로 에이전트별 참여 수 제어 가능

---

## [0.41.4] — 2026-03-01

### 버그 수정

- **WorkflowView Details 탭 스크롤 영역 레이아웃 버그 수정** — Details 탭 내 스크롤 영역 레이아웃이 올바르게 동작하지 않던 문제 수정 (REQ-226)

### 개선

- **알림 시스템 완료 이벤트 전용 전환** — 종모양 알림을 완료 이벤트 전용으로 전환하고 토스트 알림 제거 (REQ-223)

---

## [0.41.3] — 2026-03-01

### 버그 수정

- **WorkflowView 태스크 패널 스크롤 수정** — 태스크 상세 패널에 `min-h-0` 추가, 내용 오버플로우 시 스크롤이 제대로 동작하지 않던 문제 수정

---

## [0.41.2] — 2026-03-01

### 버그 수정

- **PlansView Design 탭 섹션 누락 수정** — Plans 목록 뷰에서 Design 탭 섹션이 표시되지 않던 문제 수정 (REQ-225)
- **EXP 세션 카드 내용 중복 표시 수정** — Explore 세션 카드에서 동일 내용이 중복으로 표시되던 문제 수정

---

## [0.41.1] — 2026-03-01

### 버그 수정

- **Plan Design 탭 이미지 잘림 수정** — `object-cover max-h-80` → `max-w-[85%] block mx-auto` 로 변경, Plan 탭 이미지 잘림 해결 (REQ-224)

---

## [0.41.0] — 2026-03-01

### 새 기능

- **CompletionAlarm** — 요청 완료 시 SSE `completion_alert` 이벤트 방출 + 프론트엔드 토스트 알림 컴포넌트 추가 (REQ-221)
- **Design 탭 신설** — 대시보드에 Stitch 디자인 화면을 전용 탭으로 표시, `DesignView` 컴포넌트 + `/api/designs` 라우트 + 백엔드 DES 타입 지원 (REQ-218)
- **Stitch DES-NNN 세션 프로토콜** — PLN 세션 의존 제거, Stitch 스킬이 독립 DES 세션 ID로 동작 (REQ-218)

### 개선

- **에이전트 선택 규칙 확정형 전환** — 금지/허용/우선 방식을 IF-THEN 플로우로 재정의하여 에이전트 선택 일관성 향상 (REQ-219)
- **Stitch multi_style_batch 안정성** — 재진입 감지 로직 추가 + stale_at 기준 15분으로 수정 (REQ-220)
- **Stitch 폴링 한도 확대** — 최대 폴링 횟수 10회 → 20회 (총 최대 10분 대기)
- **Design 탭 이미지 표시 수정** — `object-cover max-h-80` → `max-w-[85%] block mx-auto` 로 변경, 이미지 잘림 해결 (REQ-222)

---

## [0.40.2] — 2026-02-28

### 개선

- Plans 뷰에서 Diagram 탭 제거

---

## [0.40.1] — 2026-02-28

### 개선

- **Stitch 폴링 신뢰성 향상** — count 비교 → screen ID set 차집합 비교로 전환, 폴링 윈도우 3분 → 5분 연장 (REQ-216)
- **mst:accept pending Stitch 자동 재확인** — accept 시 pending 상태 stitch_screens를 자동으로 재확인하여 active 갱신 (REQ-216)
- **Plans 다이어그램 뷰** — 대시보드에 Plans 간 의존 관계를 시각화하는 Diagram 탭 추가 (REQ-215)
- **mst:stitch 멀티 스타일 생성** — `--multi` 플래그로 여러 스타일 방향 화면을 한 번에 생성, plan Step 4.5에서 자동 제안 (REQ-217)
- **sync-local 스크립트** — 로컬 플러그인 캐시 동기화 스크립트 추가 (REQ-214)

## [0.40.0] — 2026-02-28

### 새 기능

- **mst:stitch 비동기 생성 처리** — 화면 생성 요청을 비동기로 처리하여 타임아웃 없이 안정적으로 동작 (REQ-206)
- **Ideation 탭 통합** — Explore 탭을 Ideation 탭으로 통합하여 브레인스토밍·탐색 기능 일원화 (REQ-209)

### 개선

- **에이전트 배정 로직 강화** — config 주입 방식 개선 및 spec 작성 과정 표현 강화 (REQ-213)
- **cleanup 스킬 plans 지원** — plans 정리 포함, requests 최소 유지 갯수 적용 (REQ-208)
- **버전 bump 시 커밋 자동 포함** — 버전업 워크플로우에서 미커밋 변경사항 자동 반영 (REQ-210)
- **UI 감지 방식 개선** — LLM 의미 판단 기반으로 UI 변경 여부를 더 정확하게 감지 (REQ-205)
- **mst:plan Step 4 디자인 시안** — Stitch 디자인 시안 보기 옵션 추가, `templates/plan.md` 디자인 시안 섹션 템플릿 반영 (REQ-205)
- **PM 커밋 통일 + self-check 출력 의무화** — 커밋 형식 일관성 강화 및 자체 검증 단계 출력 필수화 (REQ-203)

### 버그 수정

- **PlansView design.md 갱신 버그 수정** — refresh 및 SSE 이벤트가 design.md에 미반영되던 문제 수정 (REQ-212)
- **Explore 세션 상태 변경 실패 수정** — EXP-* 타입 처리 누락으로 상태 전환 실패하던 문제 수정 (REQ-211)
- **Stitch 링크 404 버그 수정** — URL 형식·이미지 필드명·터미널 출력·만료 경고 개선 (REQ-207)
- **pm-conductor default_agent 오할당** — 잘못된 에이전트가 기본값으로 지정되던 문제 수정 (REQ-204)

---

## [0.39.0] — 2026-02-28

### 새 기능

- **bump.py 버전업 스크립트** — 3파일 버전 자동 동기화 + 직전 버전 이후 git log 출력 (REQ-201)

### 개선

- **frontend useAuth** — token 저장 로직 추가, AppContext projectId 폴백 처리, URL 정리 (REQ-200, REQ-202)
- **projects.ts 경로 정규화** — `.gran-maestro` 서브디렉토리 자동 감지 및 path 중복 체크 (REQ-200, REQ-202)
- **plans.ts 타입 오류 수정** — registry 정리 포함 (REQ-202)
- **accept SKILL.md** — `git branch -D` 강제 삭제 명세 보강 (REQ-199)

---

## [0.36.0] — 2026-02-27

### 새 기능

- **대시보드 PlansView** — Overview / Design 2탭 분리, `design.md` 렌더링 지원 (REQ-167)
- **pending_dependency 자동 활성화** — `accept` Step 5.5 추가, `approve` 필터 개선, `mst.py` plan sync 연동 (REQ-168)
- **mst:stitch PLN 컨텍스트 감지** — 활성 PLN 세션 자동 감지 후 `design.md` 생성 (REQ-165)
- **AGENTS.md + 공통 템플릿** — 분기 규칙 및 실행 원칙 명확화, 에이전트 초기 컨텍스트 표준화 (REQ-165)
- **Stitch MCP 직접 호출 방지** — `mst:stitch` 스킬 경유 강제, 일관된 PLN 연동 보장 (REQ-166)
- **Codex 위임 확대** — agent 배정 기준 명확화, 호출 일관성 개선, Step 5b 검토 강화 (REQ-171)

### 개선

- **mst:debug 리팩토링** — 개별 에이전트 취합 방식에서 PM 중앙 취합 방식으로 전환 (REQ-162)
- **SKILL.md 프롬프트 압축** — Phase 1: 설명 문장 압축 + 예시 섹션 축소 (27개 스킬), Phase 2: 오류 처리 희귀 케이스 정리 (REQ-163, REQ-164)
- **OMX 가이드 문서 추가** — `docs/omx-guide.md`: oh-my-codex 설치, AGENTS.md 커스터마이징, 트리거 레퍼런스 (REQ-170)
- **README Stitch 사용자 가이드 추가** — 요청 유형별 동작 표, PLN 연동 사례 정리 (REQ-169)

### 버그 수정

- **mst:stitch pending 즉시 삭제 버그** — `stale_at(5분)` 유지 방식으로 교체, 조기 삭제 방지 (REQ-161)

---

## [0.35.4] — 2026-02-26

### 개선

- **mst:stitch 타임아웃 복구 메커니즘** — 생성 도중 타임아웃 시 pending 상태 보존 및 재시도 가이드 (REQ-159)

### 버그 수정

- **대시보드 탭 미표시 문제 수정** — DBG-021: 특정 조건에서 탭이 렌더링되지 않던 문제 해결 (REQ-160)

---

## [0.35.3] — 2026-02-26

### 새 기능

- **mst:setup-omx 스킬 추가** — Codex CLI 프로젝트에 oh-my-codex 설치·초기화·gitignore 등록·AGENTS.md 주입을 4단계로 자동화 (REQ-158)

---

## [0.35.2] — 2026-02-26

### 개선

- **Spec Pre-review Pass** — 구현 에이전트가 스펙 승인 전 사전 Q&A를 수행해 모호성 제거 (REQ-156)
- **mst:request 설명 문구 개선** — 스펙 작성 의도 및 approve 분리 흐름 명확화 (REQ-157)

---

## [0.35.1] — 2026-02-25

### 새 기능

- **mst:explore 스킬 추가** — 에이전트들이 코드베이스를 백그라운드로 자율 탐색해 원하는 정보를 찾아오는 스킬 (REQ-155)

### 변경

- **mst:start → mst:request 이름 변경** — 스킬 이름을 의도에 맞게 변경, `mst:start`는 deprecated 래퍼로 유지 (REQ-154)

### 문서

- `docs/best-practices.md` 설명 문구 간소화
