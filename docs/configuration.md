# 설정 관리 (Configuration Reference)

[← README](../README.md)

`.gran-maestro/config.json`으로 모든 동작을 제어합니다.
`/mst:request` 또는 `/mst:on` 첫 실행 시 기본 설정으로 자동 생성됩니다.

```
/mst:settings                                    # 전체 설정 표시
/mst:settings workflow.max_feedback_rounds        # 특정 설정 조회
/mst:settings workflow.max_feedback_rounds 3      # 설정 변경
```

대시보드의 **Settings** 탭에서도 웹 UI로 변경할 수 있습니다.

## Codex migration config boundary

Gran Maestro 설정의 source of truth는 프로젝트 내부 `.gran-maestro/config.json`과 template defaults입니다. Codex plugin migration 문서·릴리스 검증은 repository-local fixture/evidence만 사용하며 실제 사용자 소유 설정을 변경하지 않습니다.

- 수정 가능 범위: repository-local `.gran-maestro/config.json`, `templates/defaults/config.json`, generated evidence.
- 사용자 소유 범위: `~/.codex/config.toml`, `~/.agents`, `~/.claude`, user-global config는 설치자가 직접 관리합니다.
- DOD-012 검증: `node scripts/generate-dod-012-docs-release-integration.mjs <output>`와 `npm test`로 coverage를 확인하며 user-home mutation, external Codex install/cache refresh/reload, symlink creation, plugin cache mutation을 수행하지 않습니다.
- DOD-013 single-source drift validation은 follow-up/supporting boundary로만 기록하며 DOD-012에서 완료로 승격하지 않습니다.

---

## 목차

- [auto_mode](#auto_mode)
- [workflow](#workflow)
- [server](#server)
- [concurrency](#concurrency)
- [timeouts](#timeouts)
- [hook](#hook)
- [worktree](#worktree)
- [retry](#retry)
- [delegation / agile.dispatch](#delegation--agiledispatch)
- [history / archive](#history--archive)
- [discussion / ideation](#discussion--ideation)
- [collaborative_debug](#collaborative_debug)
- [debug.agents](#debugagents)
- [explore.agents](#exploreagents)
- [models](#models)
- [prereview](#prereview)
- [code_review](#code_review)
- [stitch](#stitch)
- [plan_review](#plan_review)
- [review](#review)
- [phase1_exploration](#phase1_exploration)
- [notifications / realtime / debug / cleanup](#notifications--realtime--debug--cleanup)
- [예시 설정 조합](#예시-설정-조합)

---

## auto_mode

`-a` / `--auto` 플래그를 CLI 없이 상시 활성화하는 설정입니다. CLI 플래그가 항상 config 설정보다 우선합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `auto_mode.plan` | `false` | `/mst:plan` 자율 실행 모드 상시 활성화 |
| `auto_mode.request` | `false` | `/mst:request` 자동 승인 모드 상시 활성화 |
| `auto_mode.confidence_threshold` | `0.8` | plan 자율 모드에서 자율 결정 임계값 (0~1). 이 값 미만이면 `mst:discussion` 자동 호출 |

### auto_mode.plan

`true`이면 `/mst:plan` 실행 시 `AskUserQuestion` 없이 PM이 모든 미결 항목을 자율 결정합니다.
- 확신 점수가 `confidence_threshold` 미만인 항목은 `mst:discussion`을 자동 실행해 결론을 도출합니다
- 모든 결정 근거는 `plans/PLN-NNN/auto-decisions.md`에 기록됩니다
- plan.md 저장 후 `/mst:request -a`를 자동 호출합니다

### auto_mode.request

`true`이면 `/mst:request` 실행 시 스펙 작성 후 사용자 승인 없이 즉시 `/mst:approve --auto`를 호출합니다.
- Spec Pre-review Pass를 건너뜁니다
- `request.json`에 `auto_approve: true`로 기록됩니다

> 두 값을 모두 `true`로 설정하면 `/mst:plan` 한 번으로 plan → spec → 구현 → 리뷰 → 수락까지 전 과정이 무인 실행됩니다. 자세한 내용은 [스킬 레퍼런스 — 자율 실행 모드](skills-reference.md#자율-실행-모드--a----auto)를 참고하세요.

---

## workflow

워크플로우 전체 흐름을 제어하는 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `workflow.max_feedback_rounds` | `5` | 최대 피드백 반복 횟수 (Phase 4) |
| `workflow.auto_approve_spec` | `false` | 스펙 자동 승인 여부 |
| `workflow.auto_accept_result` | `true` | Phase 3 리뷰 PASS 후 자동 수락 |
| `workflow.default_agent` | `codex-dev` | 기본 실행 에이전트 |
| `workflow.spec_prereview` | `true` | Spec Pre-review 활성화 여부 |
| `workflow.spec_prereview_max_iterations` | `3` | Pre-review 최대 반복 횟수 |
| `workflow.spec_prereview_escalation_trigger` | `"major"` | Pre-review 에스컬레이션 기준 (`critical` / `major` / `minor`) |
| `workflow.spec_prereview_minor_escalation_threshold` | `3` | MINOR 이슈 임계값 에스컬레이션 (3이면 MINOR 3건 이상 시 에스컬레이션) |
| `workflow.auto_approve_on_unblock` | `false` | 의존성 해소 시 자동 approve 실행 여부 |

---

## server

대시보드 서버 접근 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `server.port` | `3847` | 대시보드 포트 |
| `server.host` | `127.0.0.1` | 대시보드 호스트 |

---

## concurrency

병렬 실행 수준을 제어하는 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `concurrency.max_parallel_tasks` | `5` | 최대 병렬 태스크 수 |
| `concurrency.max_parallel_reviews` | `3` | 최대 병렬 리뷰 수 |
| `concurrency.batch_max_parallel_reqs` | `1` | 배치 approve 시 최대 병렬 REQ 수 |
| `concurrency.queue_strategy` | `fifo` | 큐 전략 |

---

## timeouts

각 단계별 타임아웃(ms) 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `timeouts.cli_default_ms` | `300000` | CLI 기본 타임아웃 (5분) |
| `timeouts.cli_large_task_ms` | `1800000` | 대규모 태스크 타임아웃 (30분) |
| `timeouts.pre_check_ms` | `120000` | 사전 검증 타임아웃 (2분) |
| `timeouts.merge_ms` | `60000` | Merge 타임아웃 (1분) |
| `timeouts.dashboard_health_check_ms` | `10000` | 대시보드 헬스체크 (10초) |

---

## hook

Claude hook 판정 경로의 보호 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `hook.judge_timeout_ms` | `500` | stop hook 판정 전체 hard timeout(ms). 초과 시 fail-open으로 `{"decision":"allow"}`를 반환하고 `flow-detail.ndjson`에 `judge_timeout` 이벤트를 기록합니다. |

---

## worktree

Git worktree 생성 및 관리 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `worktree.root_directory` | `.gran-maestro/worktrees` | worktree 루트 경로 |
| `worktree.max_active` | `10` | 최대 활성 worktree 수 |
| `worktree.base_branch` | `main` | worktree 기준 브랜치 |
| `worktree.protected_branches` | `["main","master","release/*"]` | REQ 시작을 막을 보호 브랜치 목록. glob 패턴 허용 |
| `worktree.stale_timeout_hours` | `24` | stale 판정 시간 |
| `worktree.auto_cleanup_on_cancel` | `true` | 취소 시 자동 정리 |

---

## retry

실패 시 재시도 동작을 제어하는 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `retry.max_cli_retries` | `2` | CLI 최대 재시도 횟수 |
| `retry.max_fallback_depth` | `1` | 최대 fallback 깊이 |
| `retry.backoff_base_ms` | `1000` | 재시도 백오프 기준 (ms) |

---

## delegation / agile.dispatch

Host와 provider를 분리하고 중앙 route planner가 `native_candidate`, `external`, `blocked` 중 하나를 선택합니다. `host=auto`이면 `/mst:on`과 `mst.py host context`가 Codex 또는 Claude Code 런타임을 감지합니다. 기본 `same-host-native-first` 정책에서는 Codex/Codex와 Claude/Claude 조합이 host native agent를 우선하므로, 같은 host 위임만을 위한 별도 provider CLI가 필요하지 않습니다.

호환성: 기존 `gemini`, `gemini-dev`, `gemini-reviewer` 설정 키와 세션 값은 한 릴리스 동안 AGY alias로 읽습니다. 새 config는 `agy`, `agy-dev`, `agy-reviewer`를 사용하세요.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `delegation.host` | `"auto"` | 위임 명령 선택 기준 host (`auto` / `codex` / `claude` / `headless`) |
| `delegation.default_provider` | `"codex"` | Assigned Agent가 모호할 때 사용할 기본 provider |
| `delegation.provider_priority` | `["codex","agy","claude"]` | provider 선택 우선순위/추천 순서. 활성 attempt의 transport fail-closed 규칙을 덮어쓰지 않음 |
| `delegation.transport_policy` | `"same-host-native-first"` | `same-host-native-first` 또는 native를 건너뛰는 `external-only` |
| `delegation.native.enabled` | `true` | same-host native candidate 허용 여부 |
| `delegation.native.scope` | `"all"` | native 허용 scope (`all`, `review-and-exploration-only`, `review-only`, `exploration-only`, `implementation-only`, `none`) |
| `delegation.orca.enabled` | `false` | 이미 external로 결정된 provider CLI runner를 exact MST worktree의 로컬 Orca background terminal에서 시작할지 여부 |
| `agile.dispatch.provider` | `"codex"` | Sprint dispatch provider (`codex` / `agy` / `claude`) |

### Route 선택과 CLI 요구사항

| 조건 | Route | 동작 |
|------|-------|------|
| Codex host → Codex provider 또는 Claude host → Claude provider이고 policy/scope가 허용됨 | `native_candidate` | host capability handshake 뒤 Codex collaboration 또는 Claude Task/Agent 사용 |
| Cross-provider, headless, `external-only`, `native.enabled=false`, scope 제외, capability unavailable | `external` | 기존 provider managed wrapper 사용. 대상 provider CLI 필요 |
| External 조건인데 대상 provider CLI도 없음 | `blocked` | `missing_cli` structured non-success와 exit code 2. 실행/fallback을 꾸며내지 않음 |

`capability_status=unknown`인 same-host route는 곧바로 external로 내리지 않고 native capability handshake를 요구합니다. Native spawn이 `definitive_not_created`로 확정된 경우에만 같은 provider의 external wrapper fallback을 허용합니다. Spawn 승인 또는 provider task ID 이후 attach 실패·timeout·결과 불명·취소 미확인은 `reconciling`으로 남기고 새 native spawn과 external 중복 실행을 모두 차단합니다. Native task 자체의 실패도 terminal failure이며 transport fallback 사유가 아닙니다.

`delegation.orca.enabled=true`이면 이미 `external`로 결정된 Codex, Claude, AGY 보호 runner만 Orca launch surface로 시작합니다. Orca는 native candidate를 external로 바꾸지 않으며 model/effort binding과 provider 기능 범위도 바꾸지 않습니다. Orca는 provider나 lifecycle owner가 아니며 Run/Task/Dispatch API도 사용하지 않습니다. MST가 만든 absolute worktree만 `path:<absolute-worktree>`로 preflight/선택하고, V1은 ready 상태인 local runtime만 지원합니다. Preflight가 terminal create 호출 전에 확정적으로 실패하면 direct external로 실행하지만, create 호출 이후 응답 유실이나 handle 불명은 fallback하지 않고 exact worktree와 `MST/<task>/<attempt>` title로 reconcile합니다. 성공 attempt는 terminal 내부 runner가 output·history와 cleanup-ready evidence를 먼저 저장한 뒤, terminal 밖의 launch controller가 tab을 닫습니다. 실패·취소·unknown terminal과 terminal 내부 worker의 실행 전 실패·provider 회수 불명은 controller 대기를 끝내고 진단을 위해 보존합니다. `ORCA_CLI_COMMAND`의 wrapper 인자는 정상 응답뿐 아니라 timeout·structured error에도 redaction하고 provider 환경에도 전달하지 않습니다. 구조화된 MST context binding은 canonical fallback과 공개 호환 CLI를 포함한 모든 진입점의 provider-spawn 경계에서 inherited 환경보다 우선해 적용하며, provider output과 runtime log를 저장하기 전에 raw/JSON-escaped exact context 값을 redaction합니다. Terminal 출력은 진단용이며 MST output hash와 lifecycle state가 완료의 기준입니다.

Route planner는 transport를 실행하지 않고 JSON 결정만 반환합니다.

```bash
python3 scripts/mst.py delegation route --host codex --provider codex --capability-status available --pretty
python3 scripts/mst.py delegation route --host claude --provider codex --capability-status unavailable --pretty
```

`delegation start/claim-spawn/acknowledge/attach/heartbeat/complete/fallback/cancel/recover/external-run`은 host bridge가 native/external lifecycle evidence를 기록할 때 사용하는 관리용 CLI입니다. `start`는 native spawn 권한을 주지 않으며, 원자적 `claim-spawn`의 단일 승자가 받은 private one-shot token file로만 host spawn 결과를 `acknowledge`할 수 있습니다. raw token은 JSON/argv에 노출되지 않습니다. `external-run`은 중앙 route가 미리 저장한 external attempt와 필수 `--expected-attempt-id`가 있어야 하며, 자체적으로 새 external attempt를 만들지 않습니다. `dispatch build`가 만든 보호 wrapper는 direct launch에서 `dispatch run-external`, Orca launch에서 terminal 내부의 동일한 `dispatch run-external` 단일 감독자만 호출합니다. 감독자는 authorization을 소비한 뒤 side effect가 없는 anonymous exec gate의 PID·PGID·start identity를 CAS로 attach하고, 같은 task lock에서 취소보다 먼저 exec release가 확정된 경우에만 실제 provider를 시작합니다. 이어 claim 시점에 캡처한 정확한 prompt byte 전달, provider process group의 bounded TERM→KILL 회수, fresh single-link inode로 claim해 계속 보유한 non-following output descriptor를 통한 결과 게시와 terminal 내부 completion evidence 저장을 한 경계에서 수행합니다. Orca tab 종료는 그 evidence를 확인한 terminal 외부 controller가 담당합니다. prompt snapshot은 감사용이며 provider 입력으로 다시 열지 않고, output pathname도 provider 실행 뒤 쓰기 위해 다시 열지 않습니다. prompt/snapshot/running/trace/output 상호 alias와 MST state·lock·history reserved path alias는 provider spawn 전에 실패합니다. 분리형 `claim-external`/`heartbeat-external`/`finalize-external` CLI는 `central_runner_required`로 차단됩니다. 자동 authorization을 사용하는 호환 호출도 canonical `MST_SESSION_ID`가 없으면 command 생성 단계에서 실패합니다. `blocked`나 `reconciling` 상태에서 사용자가 별도 wrapper를 직접 재실행하면 중복 side effect가 생길 수 있으므로, provider 상태를 reconcile한 뒤 기존 attempt를 이어가야 합니다.

### Canonical 설정과 legacy opt-out migration

새 프로젝트의 canonical 설정은 다음과 같습니다.

```json
{
  "delegation": {
    "host": "auto",
    "transport_policy": "same-host-native-first",
    "native": {
      "enabled": true,
      "scope": "all"
    },
    "orca": {
      "enabled": false
    }
  }
}
```

Native 위임을 명시적으로 끄고 기존 wrapper만 사용하려면 `transport_policy: "external-only"`와 `native.enabled: false`를 함께 설정하세요. 이 opt-out에서는 대상 provider CLI가 없으면 route가 `blocked`됩니다.

기존 project-local `delegation.native_codex_subagents`는 한 릴리스 동안 migration/read alias로 지원합니다. 예전 `enabled: false`는 `transport_policy: "external-only"`와 `native.enabled: false`로, legacy `scope`는 `native.scope`로 보존됩니다. `transport_policy` 또는 `native.enabled`를 명시한 canonical 값과 legacy 값이 충돌하면 canonical 값이 우선하고 warning을 출력합니다.

```bash
python3 scripts/mst.py config migrate --apply
```

Migration은 legacy key를 canonical 구조로 치환하며 두 번 실행해도 결과가 바뀌지 않습니다. 새 config에는 `native_codex_subagents`를 추가하지 마세요.

---

## history / archive

요청 이력 보존 및 세션 아카이브 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `history.retention_days` | `30` | 이력 보존 기간 (일) |
| `history.auto_archive` | `true` | 자동 아카이브 |
| `archive.max_active_sessions` | `200` | 최대 활성 세션 수 |
| `archive.archive_retention_days` | `90` | 아카이브 보존 기간 (일). purge 기준 기본값 |
| `archive.auto_archive_on_create` | `true` | 세션 생성 시 초과분 자동 아카이브 |
| `archive.auto_archive_on_complete` | `true` | 완료 시 자동 아카이브 |
| `archive.archive_directory` | `.gran-maestro/archive` | 아카이브 저장 경로 |

---

## discussion / ideation

토론 및 아이디에이션 라운드 제어 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `discussion.agents.codex` | `{ count: 2, tier: "premium" }` | Discussion Codex 에이전트 (0=제외) |
| `discussion.agents.agy` | `{ count: 0, tier: "premium" }` | Discussion AGY 에이전트 (0=제외) |
| `discussion.agents.claude` | `{ count: 0, tier: "economy" }` | Discussion Claude 에이전트 (0=제외) |
| `discussion.response_char_limit` | `2000` | Discussion 응답 글자 제한 |
| `discussion.critique_char_limit` | `2000` | Discussion Critic 글자 제한 |
| `discussion.default_max_rounds` | `5` | 기본 최대 라운드 수 |
| `discussion.max_rounds_upper_limit` | `10` | 최대 라운드 상한 |
| `ideation.agents.codex` | `{ count: 2, tier: "premium" }` | Ideation Codex 에이전트 (0=제외) |
| `ideation.agents.agy` | `{ count: 0, tier: "premium" }` | Ideation AGY 에이전트 (0=제외) |
| `ideation.agents.claude` | `{ count: 0, tier: "economy" }` | Ideation Claude 에이전트 (0=제외) |
| `ideation.opinion_char_limit` | `2000` | Ideation 의견 글자 제한 |
| `ideation.critique_char_limit` | `2000` | Ideation Critic 글자 제한 |

에이전트 풀 공통 규칙:
- 각 에이전트는 `{ count, tier }` 객체로 지정합니다
- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## collaborative_debug

협업 디버그 모드 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `collaborative_debug.finding_char_limit` | `3000` | 조사 결과 글자 제한 |
| `collaborative_debug.merge_wait_ms` | `60000` | 에이전트 합류 대기 시간 (60초) |
| `collaborative_debug.auto_trigger_from_request` | `true` | `/mst:request`에서 디버그 의도 시 자동 트리거 |

---

## debug.agents

디버그 조사에 참여하는 에이전트 풀 설정입니다. 각 에이전트는 `{ count, tier }` 객체로 지정합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `debug.agents.codex` | `{ count: 2, tier: "premium" }` | Debug 조사 Codex 에이전트 (0=제외) |
| `debug.agents.agy` | `{ count: 0, tier: "premium" }` | Debug 조사 AGY 에이전트 (0=제외) |
| `debug.agents.claude` | `{ count: 0, tier: "economy" }` | Debug 조사 Claude 에이전트 (0=제외) |

참여자 규칙:
- 총합: 1명 이상 6명 이하
- 누락 시 기본값: `codex: 2`, `agy: 0`, `claude: 0`
- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## explore.agents

코드베이스 탐색(`/mst:explore`)에 참여하는 에이전트 풀 설정입니다. 각 에이전트는 `{ count, tier }` 객체로 지정합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `explore.agents.codex` | `{ count: 2, tier: "premium" }` | Explore Codex 에이전트 (0=제외) |
| `explore.agents.agy` | `{ count: 0, tier: "premium" }` | Explore AGY 에이전트 (0=제외) |
| `explore.agents.claude` | `{ count: 0, tier: "economy" }` | Explore Claude 에이전트 (0=제외) |

- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## models

각 역할별로 사용할 모델을 지정하는 설정입니다. `providers`와 `roles` 두 하위 섹션으로 구성됩니다.

### models.providers

프로바이더별 모델 티어(premium/economy)를 정의합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `models.providers.codex.premium` | `"gpt-5.6-luna"` | Codex premium 모델 |
| `models.providers.codex.economy` | `"codex-mini"` | Codex economy 모델 |
| `models.providers.codex.default_tier` | `"premium"` | Codex 기본 티어 |
| `models.providers.codex.premium_reasoning_effort` | 미설정 | Codex premium 모델의 기본 추론 난이도 |
| `models.providers.codex.economy_reasoning_effort` | 미설정 | Codex economy 모델의 기본 추론 난이도 |
| `models.providers.codex.default_reasoning_effort` | `"inherit"` | tier별 설정이 없을 때 사용하는 Codex 추론 난이도 |
| `models.providers.agy.premium` | `"agy-default"` | AGY premium 모델 |
| `models.providers.agy.economy` | `"agy-default"` | AGY economy 모델 |
| `models.providers.agy.default_tier` | `"premium"` | AGY 기본 티어 |
| `models.providers.agy.premium_reasoning_effort` | 미설정 | AGY premium 모델의 기본 추론 난이도 |
| `models.providers.agy.economy_reasoning_effort` | 미설정 | AGY economy 모델의 기본 추론 난이도 |
| `models.providers.agy.default_reasoning_effort` | `"inherit"` | tier별 설정이 없을 때 사용하는 AGY 추론 난이도 |
| `models.providers.claude.premium` | `"opus"` | Claude premium 모델 |
| `models.providers.claude.economy` | `"sonnet"` | Claude economy 모델 |
| `models.providers.claude.default_tier` | `"economy"` | Claude 기본 티어 |
| `models.providers.claude.premium_reasoning_effort` | 미설정 | Claude premium 모델의 기본 추론 난이도 |
| `models.providers.claude.economy_reasoning_effort` | 미설정 | Claude economy 모델의 기본 추론 난이도 |
| `models.providers.claude.default_reasoning_effort` | `"inherit"` | tier별 설정이 없을 때 사용하는 Claude 추론 난이도 |

### models.roles

각 역할(role)에 사용할 프로바이더와 티어를 지정합니다. 배열로 지정하면 다중 에이전트를 순서대로 배치합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `models.roles.pm_conductor` | `{ provider: "codex", tier: "premium" }` | PM 지휘자 (Phase 1, 3) |
| `models.roles.architect` | `{ provider: "codex", tier: "premium" }` | 아키텍트 (Design Wing) |
| `models.roles.developer` | `[codex/premium, agy/premium]` | 개발자 (배열 — 다중 에이전트) |
| `models.roles.developer_claude` | `{ provider: "claude", tier: "premium", enabled: false }` | Claude legacy/fallback 개발자 |
| `models.roles.reviewer` | `[codex/premium, agy/premium]` | 리뷰어 (배열 — 다중 에이전트) |

### 모델 Resolve 규칙

역할에서 `tier`를 지정하면, 해당 프로바이더의 `providers` 정의에서 실제 모델명을 resolve합니다.

예: `{ provider: "codex", tier: "premium" }` → `providers.codex.premium` → `"gpt-5.6-luna"`

`tier`를 생략하면 해당 프로바이더의 `default_tier`가 적용됩니다.

각 agent/role 객체의 `reasoning_effort`는 `default | inherit | low | medium | high | xhigh | max | ultra`를 사용합니다. `default`는 먼저 선택된 model tier의 `<tier>_reasoning_effort`를 따르고, 해당 키가 없으면 provider의 `default_reasoning_effort`를 fallback으로 사용합니다. `inherit`은 native host 또는 CLI 기본값을 사용합니다. concrete 값은 호출별 값이 tier/provider 기본값보다 우선하며, 현재 provider/model이 지원하지 않는 값은 실행 전에 차단됩니다. 동일한 resolved 값이 native, direct external, Orca external에 적용됩니다.

`premium_reasoning_effort`와 `economy_reasoning_effort`는 선택 사항입니다. 예전 설정처럼 `default_reasoning_effort`만 지정해도 동작하며, tier별 키에 `inherit`을 명시하면 해당 tier는 host/CLI 기본값을 사용합니다.

> **용어 주의: model tier vs preset tier**
>
> - **model tier** (`premium` / `economy`): `models.providers`에서 프로바이더별 모델 등급을 구분하는 체계입니다.
> - **preset tier** (`performance` / `efficient` / `budget`): 예시 설정 조합(preset)에서 전체 시스템 성능 수준을 표현하는 별개의 체계입니다.
>
> 두 tier는 서로 독립적이며 혼동하지 않도록 주의하세요.

### 설정 예시

```json
"models": {
  "providers": {
    "codex": {
      "premium": "gpt-5.6-luna",
      "economy": "codex-mini",
      "default_tier": "premium",
      "premium_reasoning_effort": "xhigh",
      "economy_reasoning_effort": "max",
      "default_reasoning_effort": "inherit"
    },
    "agy": {
      "premium": "agy-default",
      "economy": "agy-default",
      "default_tier": "premium"
    },
    "claude": {
      "premium": "opus",
      "economy": "sonnet",
      "default_tier": "economy"
    }
  },
  "roles": {
    "pm_conductor": { "provider": "claude", "tier": "premium" },
    "architect": { "provider": "claude", "tier": "premium" },
    "developer": [
      { "provider": "codex", "tier": "premium" },
      { "provider": "agy", "tier": "premium" }
    ],
    "developer_claude": { "provider": "claude", "tier": "premium" },
    "reviewer": [
      { "provider": "codex", "tier": "premium" },
      { "provider": "agy", "tier": "premium" }
    ]
  }
}
```

---

## prereview

Spec Pre-review Pass에서 사용하는 에이전트 풀 설정입니다.
`request` 스킬의 Step h-2에서 Pre-review 에이전트를 dispatch할 때 참조됩니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `prereview.agents.codex` | `{ count: 2, tier: "premium" }` | Pre-review Codex 에이전트 (0=제외) |
| `prereview.agents.agy` | `{ count: 0 }` | Pre-review AGY 에이전트 (0=제외) |
| `prereview.agents.claude` | `{ count: 0, tier: "economy" }` | Pre-review Claude 에이전트 (0=제외) |

기본값은 `templates/defaults/config.json` 기준입니다.

- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## code_review

Phase 3에서 추가 독립 리뷰어를 배치하는 설정입니다.
기존 Review Squad(Phase 3 기본 리뷰)와 별도로, `pm-conductor.md`에서 추가적인 독립 리뷰 에이전트를 dispatch하는 데 사용됩니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `code_review.enabled` | `true` | 추가 독립 리뷰어 활성화 여부 |
| `code_review.agents` | `1` | 추가 리뷰어 수 (agent_roster에서 순서대로 선택) |
| `code_review.agent_roster` | `["codex", "agy"]` | 리뷰어 후보 에이전트 목록 |
| `code_review.parallel` | `true` | 기존 Phase 3 패스와 동시 실행 여부 |

---

## stitch

Google Stitch MCP 연동 설정입니다. UI 화면 시안 생성·관리에 사용됩니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `stitch.enabled` | `true` | Stitch 연동 전체 활성화 여부 |
| `stitch.auto_detect` | `true` | UI 관련 요청 자동 감지 여부 |
| `stitch.auto_trigger` | `false` | 새 화면 추가 감지 시 자동 실행 여부 |
| `stitch.project_id` | `null` | Stitch 프로젝트 ID (글로벌 fallback) |
| `stitch.failure_policy` | `"skip"` | Stitch 호출 실패 시 정책 |
| `stitch.ui_keywords.whitelist` | `["화면", "페이지", ...]` | UI 관련 키워드 화이트리스트 |
| `stitch.ui_keywords.blacklist` | `["API", "DB", ...]` | 비-UI 키워드 블랙리스트 |

---

## plan_review

Plan Review Pass 설정입니다. `/mst:plan` Step 3.8에서 플랜 사전 리뷰를 수행할 때 참조됩니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `plan_review.enabled` | `true` | Plan Review Pass 활성화 여부 |
| `plan_review.parallel` | `true` | 리뷰 에이전트 병렬 실행 여부 |
| `plan_review.max_iterations` | `2` | 리뷰-수정 반복 최대 횟수 |
| `plan_review.escalation_trigger` | `"major"` | 에스컬레이션 기준 (`critical` / `major` / `minor`) |
| `plan_review.minor_escalation_threshold` | `3` | MINOR 이슈 임계값 에스컬레이션 |
| `plan_review.roles.architect.enabled` | `true` | 아키텍트 리뷰어 활성화 |
| `plan_review.roles.architect.agent` | `"codex"` | 아키텍트 리뷰어 에이전트 |
| `plan_review.roles.architect.tier` | `"premium"` | 아키텍트 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `plan_review.roles.devils_advocate.enabled` | `true` | 악마의 대변인 리뷰어 활성화 |
| `plan_review.roles.devils_advocate.agent` | `"agy"` | 악마의 대변인 리뷰어 에이전트 |
| `plan_review.roles.devils_advocate.tier` | `"premium"` | 악마의 대변인 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `plan_review.roles.completeness.enabled` | `true` | 완전성 검토 리뷰어 활성화 |
| `plan_review.roles.completeness.agent` | `"codex"` | 완전성 검토 리뷰어 에이전트 |
| `plan_review.roles.completeness.tier` | `"premium"` | 완전성 검토 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `plan_review.roles.ux_reviewer.enabled` | `true` | UX 리뷰어 활성화 |
| `plan_review.roles.ux_reviewer.agent` | `"agy"` | UX 리뷰어 에이전트 |
| `plan_review.roles.ux_reviewer.tier` | `"premium"` | UX 리뷰어 모델 티어 (`models.providers`에서 resolve) |

---

## review

구현 리뷰(`/mst:review`) 설정입니다. Phase 3에서 AC 검증 + 병렬 코드/아키텍처/UI 리뷰를 수행합니다.

### 기본 키 (templates/defaults/config.json 기준)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `review.auto_review` | `true` | Phase 3에서 mst:review 자동 호출 여부 |
| `review.max_iterations` | `3` | 리뷰-갭수정 반복 최대 횟수 |
| `review.roles.code_reviewer.agent` | `"codex"` | 코드 리뷰어 에이전트 |
| `review.roles.code_reviewer.tier` | `"premium"` | 코드 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `review.roles.arch_reviewer.agent` | `"agy"` | 아키텍처 리뷰어 에이전트 |
| `review.roles.arch_reviewer.tier` | `"premium"` | 아키텍처 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `review.roles.ui_reviewer.agent` | `"agy"` | UI 리뷰어 에이전트 |
| `review.roles.ui_reviewer.tier` | `"premium"` | UI 리뷰어 모델 티어 (`models.providers`에서 resolve) |

### severity_auto_fix 키

아래 키는 `templates/defaults/config.json`의 `review.severity_auto_fix` 기본 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `review.severity_auto_fix.enabled` | `true` | 심각도 기반 자동 수정 활성화 |
| `review.severity_auto_fix.minor_skip_threshold` | `3` | MINOR 이슈 스킵 임계값 |
| `review.severity_auto_fix.pm_direct_fix_enabled` | `true` | PM 직접 수정 활성화 |
| `review.severity_auto_fix.pm_direct_fix_max_files` | `1` | PM 직접 수정 최대 파일 수 |
| `review.severity_auto_fix.pm_direct_fix_max_diff_lines` | `20` | PM 직접 수정 최대 diff 라인 수 |
| `review.severity_auto_fix.security_override_keywords` | `["인증", "인가", ...]` | 보안 오버라이드 키워드 목록 |

---

## phase1_exploration

Phase 1 코드베이스 탐색에 참여하는 에이전트 역할 설정입니다.
`/mst:request` Step 4.c에서 PM이 `config.phase1_exploration.roles`를 읽어 enabled=true인 역할만 background dispatch합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `phase1_exploration.roles.symbol_tracing.agent` | `"codex"` | 정밀 심볼 추적 에이전트 |
| `phase1_exploration.roles.symbol_tracing.enabled` | `true` | 심볼 추적 역할 활성화 여부 |
| `phase1_exploration.roles.symbol_tracing.tier` | `"premium"` | 심볼 추적에 사용할 모델 티어 (`models.providers`에서 resolve) |
| `phase1_exploration.roles.broad_scan.agent` | `"agy"` | 광역 탐색 에이전트 |
| `phase1_exploration.roles.broad_scan.enabled` | `true` | 광역 탐색 역할 활성화 여부 |
| `phase1_exploration.roles.broad_scan.tier` | `"premium"` | 광역 탐색에 사용할 모델 티어 (`models.providers`에서 resolve) |

---

## notifications / realtime / debug / cleanup

알림, 실시간 업데이트, 디버그 로깅, 세션 정리 설정입니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `notifications.terminal` | `true` | 터미널 알림 |
| `notifications.dashboard` | `true` | 대시보드 알림 |
| `realtime.protocol` | `sse` | 실시간 프로토콜 (SSE) |
| `realtime.debounce_ms` | `100` | 이벤트 디바운스 (ms) |
| `debug.enabled` | `false` | 디버그 모드 |
| `debug.log_level` | `info` | 로그 레벨 |
| `debug.log_prompts` | `false` | 프롬프트 로깅 |
| `cleanup.ideation_keep_count` | `10` | Ideation 세션 유지 수 |
| `cleanup.discussion_keep_count` | `10` | Discussion 세션 유지 수 |
| `cleanup.debug_keep_count` | `10` | Debug 세션 유지 수 |
| `cleanup.plan_keep_count` | `10` | Plan 세션 유지 수 |
| `cleanup.request_keep_count` | `10` | Request 세션 유지 수 |
| `cleanup.old_request_threshold_hours` | `24` | 오래된 요청 판단 기준 (시간) |

---

## 예시 설정 조합

아래는 대표적인 사용 시나리오별 권장 설정 조합입니다.
`.gran-maestro/config.json`에 해당 값을 적용하거나 `/mst:settings <key> <value>` 명령어로 개별 변경할 수 있습니다.

### 예시 1: 병렬 실행 최적화

많은 태스크를 동시에 처리해야 하는 팀 환경에서 처리량을 극대화하는 설정입니다.
리소스가 충분한 머신에서 사용하는 것을 권장합니다.

```json
{
  "concurrency": {
    "max_parallel_tasks": 10,
    "max_parallel_reviews": 6,
    "queue_strategy": "fifo"
  },
  "worktree": {
    "max_active": 20,
    "stale_timeout_hours": 48,
    "auto_cleanup_on_cancel": true
  },
  "timeouts": {
    "cli_default_ms": 600000,
    "cli_large_task_ms": 3600000
  },
  "archive": {
    "max_active_sessions": 50,
    "auto_archive_on_create": true,
    "auto_archive_on_complete": true
  }
}
```

### 예시 2: 비용 절감 모드

API 호출 비용을 최소화하기 위해 참여 에이전트 수와 토론 라운드를 제한하는 설정입니다.
소규모 프로젝트나 개인 개발 환경에 적합합니다.

```json
{
  "debug": {
    "agents": {
      "codex": 1,
      "agy": 0,
      "claude": 0
    }
  },
  "discussion": {
    "response_char_limit": 1000,
    "critique_char_limit": 1000,
    "default_max_rounds": 2,
    "max_rounds_upper_limit": 3
  },
  "ideation": {
    "opinion_char_limit": 1000,
    "critique_char_limit": 1000
  },
  "workflow": {
    "max_feedback_rounds": 2,
    "auto_accept_result": true
  },
  "concurrency": {
    "max_parallel_tasks": 3,
    "max_parallel_reviews": 2
  }
}
```

### 예시 3: 오프라인 / 자동 승인 모드

인터랙션 없이 완전 자동으로 워크플로우를 실행하는 설정입니다.
CI/CD 파이프라인이나 야간 배치 작업에 적합합니다.

```json
{
  "workflow": {
    "auto_approve_spec": true,
    "auto_accept_result": true,
    "max_feedback_rounds": 1,
    "default_agent": "codex-dev"
  },
  "notifications": {
    "terminal": false,
    "dashboard": true
  },
  "debug": {
    "enabled": false,
    "log_level": "warn",
    "log_prompts": false
  },
  "collaborative_debug": {
    "auto_trigger_from_request": false
  },
  "retry": {
    "max_cli_retries": 3,
    "max_fallback_depth": 2,
    "backoff_base_ms": 2000
  }
}
```
