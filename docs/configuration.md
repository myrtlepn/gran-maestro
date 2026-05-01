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
| `discussion.agents.codex` | `{ count: 1, tier: "premium" }` | Discussion Codex 에이전트 (0=제외) |
| `discussion.agents.gemini` | `{ count: 1, tier: "premium" }` | Discussion Gemini 에이전트 (0=제외) |
| `discussion.agents.claude` | `{ count: 1, tier: "economy" }` | Discussion Claude 에이전트 (0=제외) |
| `discussion.response_char_limit` | `2000` | Discussion 응답 글자 제한 |
| `discussion.critique_char_limit` | `2000` | Discussion Critic 글자 제한 |
| `discussion.default_max_rounds` | `5` | 기본 최대 라운드 수 |
| `discussion.max_rounds_upper_limit` | `10` | 최대 라운드 상한 |
| `ideation.agents.codex` | `{ count: 1, tier: "premium" }` | Ideation Codex 에이전트 (0=제외) |
| `ideation.agents.gemini` | `{ count: 1, tier: "premium" }` | Ideation Gemini 에이전트 (0=제외) |
| `ideation.agents.claude` | `{ count: 1, tier: "economy" }` | Ideation Claude 에이전트 (0=제외) |
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
| `debug.agents.codex` | `{ count: 1, tier: "premium" }` | Debug 조사 Codex 에이전트 (0=제외) |
| `debug.agents.gemini` | `{ count: 1, tier: "premium" }` | Debug 조사 Gemini 에이전트 (0=제외) |
| `debug.agents.claude` | `{ count: 0 }` | Debug 조사 Claude 에이전트 (0=제외) |

참여자 규칙:
- 총합: 1명 이상 6명 이하
- 누락 시 기본값: `codex: 1`, `gemini: 1`, `claude: 0`
- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## explore.agents

코드베이스 탐색(`/mst:explore`)에 참여하는 에이전트 풀 설정입니다. 각 에이전트는 `{ count, tier }` 객체로 지정합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `explore.agents.codex` | `{ count: 1, tier: "premium" }` | Explore Codex 에이전트 (0=제외) |
| `explore.agents.gemini` | `{ count: 1, tier: "premium" }` | Explore Gemini 에이전트 (0=제외) |
| `explore.agents.claude` | `{ count: 0 }` | Explore Claude 에이전트 (0=제외) |

- `tier` 생략 시 해당 프로바이더의 `models.providers.<provider>.default_tier` 적용
- 하위 호환: 정수값(`"codex": 1`)도 허용되며, `{ count: 1 }`으로 해석됩니다

---

## models

각 역할별로 사용할 모델을 지정하는 설정입니다. `providers`와 `roles` 두 하위 섹션으로 구성됩니다.

### models.providers

프로바이더별 모델 티어(premium/economy)를 정의합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `models.providers.codex.premium` | `"gpt-5.3-codex"` | Codex premium 모델 |
| `models.providers.codex.economy` | `"codex-mini"` | Codex economy 모델 |
| `models.providers.codex.default_tier` | `"premium"` | Codex 기본 티어 |
| `models.providers.gemini.premium` | `"gemini-3.1-pro-preview"` | Gemini premium 모델 |
| `models.providers.gemini.economy` | `"gemini-2.5-flash"` | Gemini economy 모델 |
| `models.providers.gemini.default_tier` | `"premium"` | Gemini 기본 티어 |
| `models.providers.claude.premium` | `"opus"` | Claude premium 모델 |
| `models.providers.claude.economy` | `"sonnet"` | Claude economy 모델 |
| `models.providers.claude.default_tier` | `"economy"` | Claude 기본 티어 |

### models.roles

각 역할(role)에 사용할 프로바이더와 티어를 지정합니다. 배열로 지정하면 다중 에이전트를 순서대로 배치합니다.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `models.roles.pm_conductor` | `{ provider: "claude", tier: "premium" }` | PM 지휘자 (Phase 1, 3) |
| `models.roles.architect` | `{ provider: "claude", tier: "premium" }` | 아키텍트 (Design Wing) |
| `models.roles.developer` | `[codex/premium, gemini/premium]` | 개발자 (배열 — 다중 에이전트) |
| `models.roles.developer_claude` | `{ provider: "claude", tier: "premium" }` | Claude 개발자 |
| `models.roles.reviewer` | `[codex/premium, gemini/premium]` | 리뷰어 (배열 — 다중 에이전트) |

### 모델 Resolve 규칙

역할에서 `tier`를 지정하면, 해당 프로바이더의 `providers` 정의에서 실제 모델명을 resolve합니다.

예: `{ provider: "codex", tier: "premium" }` → `providers.codex.premium` → `"gpt-5.3-codex"`

`tier`를 생략하면 해당 프로바이더의 `default_tier`가 적용됩니다.

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
      "premium": "gpt-5.3-codex",
      "economy": "codex-mini",
      "default_tier": "premium"
    },
    "gemini": {
      "premium": "gemini-3.1-pro-preview",
      "economy": "gemini-2.5-flash",
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
      { "provider": "gemini", "tier": "premium" }
    ],
    "developer_claude": { "provider": "claude", "tier": "premium" },
    "reviewer": [
      { "provider": "codex", "tier": "premium" },
      { "provider": "gemini", "tier": "premium" }
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
| `prereview.agents.codex` | `{ count: 1, tier: "premium" }` | Pre-review Codex 에이전트 (0=제외) |
| `prereview.agents.gemini` | `{ count: 0 }` | Pre-review Gemini 에이전트 (0=제외) |
| `prereview.agents.claude` | `{ count: 1, tier: "economy" }` | Pre-review Claude 에이전트 (0=제외) |

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
| `code_review.agent_roster` | `["codex", "gemini"]` | 리뷰어 후보 에이전트 목록 |
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
| `plan_review.roles.devils_advocate.agent` | `"gemini"` | 악마의 대변인 리뷰어 에이전트 |
| `plan_review.roles.devils_advocate.tier` | `"premium"` | 악마의 대변인 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `plan_review.roles.completeness.enabled` | `true` | 완전성 검토 리뷰어 활성화 |
| `plan_review.roles.completeness.agent` | `"codex"` | 완전성 검토 리뷰어 에이전트 |
| `plan_review.roles.completeness.tier` | `"premium"` | 완전성 검토 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `plan_review.roles.ux_reviewer.enabled` | `true` | UX 리뷰어 활성화 |
| `plan_review.roles.ux_reviewer.agent` | `"gemini"` | UX 리뷰어 에이전트 |
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
| `review.roles.arch_reviewer.agent` | `"gemini"` | 아키텍처 리뷰어 에이전트 |
| `review.roles.arch_reviewer.tier` | `"premium"` | 아키텍처 리뷰어 모델 티어 (`models.providers`에서 resolve) |
| `review.roles.ui_reviewer.agent` | `"gemini"` | UI 리뷰어 에이전트 |
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
| `phase1_exploration.roles.broad_scan.agent` | `"gemini"` | 광역 탐색 에이전트 |
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
      "gemini": 0,
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
