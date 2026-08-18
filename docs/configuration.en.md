# Configuration Management (Configuration Reference)

[한국어](configuration.md) | [English](configuration.en.md)

` .gran-maestro/config.json` controls all behavior.
It is generated with defaults on first run of `/mst:request` or `/mst:on`.

```
/mst:settings                                    # show all settings
/mst:settings workflow.max_feedback_rounds        # show a specific setting
/mst:settings workflow.max_feedback_rounds 3      # change a setting
```

You can also edit it through the dashboard **Settings** tab with a web UI.

---

## Table of contents

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
- [collaborative_debug](#collaborative-debug)
- [debug.agents](#debugagents)
- [explore.agents](#exploreagents)
- [models](#models)
- [prereview](#prereview)
- [plan_review](#plan_review)
- [review](#review)
- [phase1_exploration](#phase1_exploration)
- [notifications / realtime / debug / cleanup](#notifications--realtime--debug--cleanup)
- [Example setting presets](#example-setting-presets)

---

## workflow

Controls the overall workflow behavior.

| Key | Default | Description |
|----|--------|------|
| `workflow.max_feedback_rounds` | `5` | maximum number of feedback loops in Phase 4 |
| `workflow.auto_approve_spec` | `false` | auto-approve spec |
| `workflow.auto_accept_result` | `true` | auto accept after Phase 3 review PASS |
| `workflow.default_agent` | `codex-dev` | default execution agent |

---

## server

Settings for dashboard server access.

| Key | Default | Description |
|----|--------|------|
| `server.port` | `3847` | dashboard port |
| `server.host` | `127.0.0.1` | dashboard host |

---

## concurrency

Controls parallelism level.

| Key | Default | Description |
|----|--------|------|
| `concurrency.max_parallel_tasks` | `5` | maximum number of parallel tasks |
| `concurrency.max_parallel_reviews` | `3` | maximum number of parallel reviews |
| `concurrency.queue_strategy` | `fifo` | queue strategy |

---

## timeouts

Timeout settings for each stage (ms).

| Key | Default | Description |
|----|--------|------|
| `timeouts.cli_default_ms` | `300000` | default CLI timeout (5 min) |
| `timeouts.cli_large_task_ms` | `1800000` | large task timeout (30 min) |
| `timeouts.pre_check_ms` | `120000` | pre-check timeout (2 min) |
| `timeouts.merge_ms` | `60000` | merge timeout (1 min) |
| `timeouts.dashboard_health_check_ms` | `10000` | dashboard health check (10 sec) |

---

## hook

Protective settings for Claude hook judgment paths.

| Key | Default | Description |
|----|--------|------|
| `hook.judge_timeout_ms` | `500` | Hard timeout for the full stop hook judgment path (ms). When exceeded, the hook fails open with `{"decision":"allow"}` and appends a `judge_timeout` event to `flow-detail.ndjson`. |

---

## worktree

Settings for Git worktree creation and management.

| Key | Default | Description |
|----|--------|------|
| `worktree.root_directory` | `.gran-maestro/worktrees` | root path for worktrees |
| `worktree.max_active` | `10` | maximum active worktrees |
| `worktree.base_branch` | `main` | base branch |
| `worktree.protected_branches` | `["main","master","release/*"]` | protected branches that block starting REQs; glob patterns are allowed |
| `worktree.stale_timeout_hours` | `24` | stale threshold (hours) |
| `worktree.auto_cleanup_on_cancel` | `true` | auto cleanup on cancel |

---

## retry

Controls retry behavior on failure.

| Key | Default | Description |
|----|--------|------|
| `retry.max_cli_retries` | `2` | maximum number of CLI retries |
| `retry.max_fallback_depth` | `1` | maximum fallback depth |
| `retry.backoff_base_ms` | `1000` | base backoff time (ms) |

---

## delegation / agile.dispatch

Separates runtime host from execution provider, then uses a central route planner to select `native_candidate`, `external`, or `blocked`. With `host=auto`, `/mst:on` and `mst.py host context` detect Codex or Claude Code. Under the default `same-host-native-first` policy, Codex/Codex and Claude/Claude use host-native agents first, so no separate provider CLI is required solely for same-host delegation.

Compatibility: existing `gemini`, `gemini-dev`, and `gemini-reviewer` config keys/session values are read as AGY aliases for one release. New config should use `agy`, `agy-dev`, and `agy-reviewer`.

| Key | Default | Description |
|----|--------|------|
| `delegation.host` | `"auto"` | host used to choose delegation commands (`auto` / `codex` / `claude` / `headless`) |
| `delegation.default_provider` | `"codex"` | default provider when the assigned agent is ambiguous |
| `delegation.provider_priority` | `["codex","agy","claude"]` | provider selection/recommendation order; does not override fail-closed transport rules for an active attempt |
| `delegation.transport_policy` | `"same-host-native-first"` | `same-host-native-first` or `external-only`, which skips native routing |
| `delegation.native.enabled` | `true` | whether same-host native candidates are allowed |
| `delegation.native.scope` | `"all"` | native scope (`all`, `review-and-exploration-only`, `review-only`, `exploration-only`, `implementation-only`, `none`) |
| `delegation.orca.enabled` | `false` | launch an already-external provider CLI runner in a local Orca background terminal bound to the exact MST worktree |
| `agile.dispatch.provider` | `"codex"` | Sprint dispatch provider (`codex` / `agy` / `claude`) |

### Route selection and CLI requirements

| Condition | Route | Behavior |
|-----------|-------|----------|
| Codex host → Codex provider or Claude host → Claude provider with policy/scope enabled | `native_candidate` | use Codex collaboration or Claude Task/Agent after the host capability handshake |
| Cross-provider, headless, `external-only`, `native.enabled=false`, excluded scope, or unavailable capability | `external` | use the existing provider managed wrapper; target provider CLI required |
| External condition and target provider CLI is also missing | `blocked` | `missing_cli` structured non-success with exit code 2; no pretend execution/fallback |

For a same-host route with `capability_status=unknown`, the planner requires a native capability handshake instead of immediately selecting external. Same-provider external-wrapper fallback is allowed only when native spawn is confirmed as `definitive_not_created`. After spawn acknowledgement or a provider task ID, attach failure, timeout, an unknown result, or unconfirmed cancellation keeps the attempt in `reconciling` and blocks both a new native spawn and duplicate external execution. A native task failure is terminal and is not a transport-fallback reason.

When `delegation.orca.enabled=true`, only Codex, Claude, and AGY calls already resolved to `external` launch the existing protected runner through Orca. Orca never changes a native candidate into an external route and does not change model/effort bindings or provider capabilities. Orca is neither a provider nor the lifecycle owner, and MST does not use Orca Run/Task/Dispatch APIs. Only the absolute MST-created worktree is preflighted and selected as `path:<absolute-worktree>`; V1 supports ready local runtimes only. A definitive failure before terminal create falls back to direct external execution. Once create is invoked, lost responses or unknown handles never fall back: recovery reconciles by exact worktree and deterministic `MST/<task>/<attempt>` title. On success, the in-terminal runner persists output, history, and cleanup-ready evidence before the out-of-terminal launch controller closes the tab. Failed, cancelled, and unknown attempts, in-terminal pre-run failures, and ambiguous provider reap states release the controller wait and preserve their terminals for diagnostics. Wrapper arguments from `ORCA_CLI_COMMAND` are redacted from normal responses, timeouts, and structured errors and are not forwarded into the provider environment. The structured MST context binding overrides inherited environment state at the provider-spawn boundary for every entrypoint, including canonical fallback and the public compatibility CLI; raw and JSON-escaped exact values are then redacted before provider output or runtime logs are persisted. Terminal output is diagnostic, while MST output hashes and lifecycle state remain authoritative.

The route planner returns only a JSON decision; it does not execute either transport.

```bash
python3 scripts/mst.py delegation route --host codex --provider codex --capability-status available --pretty
python3 scripts/mst.py delegation route --host claude --provider codex --capability-status unavailable --pretty
```

`delegation start/claim-spawn/acknowledge/attach/heartbeat/complete/fallback/cancel/recover/external-run` are management commands used by the host bridge to record native/external lifecycle evidence. `start` does not grant native spawn authority: only the single winner of the atomic `claim-spawn` call may acknowledge the host result through its private one-shot token file. The raw token is not exposed in JSON or argv. `external-run` requires a centrally persisted external attempt and the matching `--expected-attempt-id`; it never creates a new external attempt by itself. Protected wrappers produced by `dispatch build` invoke only the single `dispatch run-external` supervisor, either directly or inside the Orca terminal. After consuming authorization, that supervisor starts a side-effect-free anonymous exec gate, CAS-attaches its PID, PGID, and start identity, and releases the actual provider only when exec authorization linearizes before cancellation under the same task lock. It then delivers the exact prompt bytes captured at claim time, performs bounded TERM-to-KILL provider-group cleanup, publishes output through a non-following descriptor retained from a fresh single-link claim inode, and persists in-terminal completion evidence in one ownership boundary. Orca tab closure is performed by the out-of-terminal controller after it observes that durable evidence. The prompt snapshot is audit-only and is never reopened as provider input, and the output pathname is not reopened for writing after provider execution. Prompt/snapshot/running/trace/output aliases and aliases into reserved MST state, lock, or history paths fail before provider spawn. Split `claim-external`/`heartbeat-external`/`finalize-external` CLI calls fail with `central_runner_required`. Compatibility calls that use automatic authorization fail during command construction when no canonical `MST_SESSION_ID` exists. Manually starting another wrapper while an attempt is `blocked` or `reconciling` can duplicate side effects; reconcile provider state and continue the existing attempt instead.

### Canonical configuration and legacy opt-out migration

New projects use this canonical configuration:

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

To explicitly disable native delegation and use only the existing wrapper, set both `transport_policy: "external-only"` and `native.enabled: false`. Under this opt-out, the route is `blocked` if the target provider CLI is absent.

Existing project-local `delegation.native_codex_subagents` remains supported for one release as a migration/read alias. Legacy `enabled: false` is preserved as `transport_policy: "external-only"` plus `native.enabled: false`, and legacy `scope` becomes `native.scope`. If legacy values conflict with explicit canonical `transport_policy` or `native.enabled` values, the canonical values win and a warning is emitted.

```bash
python3 scripts/mst.py config migrate --apply
```

Migration replaces the legacy key with the canonical structure and is idempotent. Do not add `native_codex_subagents` to new configuration.

---

## history / archive

Settings for request history retention and session archive.

| Key | Default | Description |
|----|--------|------|
| `history.retention_days` | `30` | history retention period (days) |
| `history.auto_archive` | `true` | auto archive |
| `archive.max_active_sessions` | `200` | maximum active sessions |
| `archive.archive_retention_days` | `90` | archive retention period in days; default purge threshold |
| `archive.auto_archive_on_create` | `true` | auto-archive when sessions exceed limits at creation |
| `archive.auto_archive_on_complete` | `true` | auto-archive on completion |
| `archive.archive_directory` | `.gran-maestro/archive` | archive path |

---

## discussion / ideation

Controls discussion and ideation rounds.

| Key | Default | Description |
|----|--------|------|
| `discussion.agents.codex` | `{ count: 2, tier: "premium" }` | Discussion Codex agent (0 to exclude) |
| `discussion.agents.agy` | `{ count: 0, tier: "premium" }` | Discussion AGY agent (0 to exclude) |
| `discussion.agents.claude` | `{ count: 0, tier: "economy" }` | Discussion Claude agent (0 to exclude) |
| `discussion.response_char_limit` | `2000` | Discussion response character limit |
| `discussion.critique_char_limit` | `2000` | Discussion critique character limit |
| `discussion.default_max_rounds` | `5` | default max number of rounds |
| `discussion.max_rounds_upper_limit` | `10` | maximum rounds upper limit |
| `ideation.agents.codex` | `{ count: 2, tier: "premium" }` | Ideation Codex agent (0 to exclude) |
| `ideation.agents.agy` | `{ count: 0, tier: "premium" }` | Ideation AGY agent (0 to exclude) |
| `ideation.agents.claude` | `{ count: 0, tier: "economy" }` | Ideation Claude agent (0 to exclude) |
| `ideation.opinion_char_limit` | `2000` | Ideation opinion character limit |
| `ideation.critique_char_limit` | `2000` | Ideation critique character limit |

Agent pool common rules:
- Each agent is specified as a `{ count, tier }` object
- When `tier` is omitted, the provider's `models.providers.<provider>.default_tier` is used
- Backward compatible: integer values (`"codex": 1`) are also accepted and interpreted as `{ count: 1 }`

---

## collaborative_debug

Settings for collaborative debug mode.

| Key | Default | Description |
|----|--------|------|
| `collaborative_debug.finding_char_limit` | `3000` | debug finding character limit |
| `collaborative_debug.merge_wait_ms` | `60000` | agent join wait time (60 sec) |
| `collaborative_debug.auto_trigger_from_request` | `true` | auto trigger debug when intent is detected in `/mst:request` |

---

## debug.agents

Agent pool for debug investigation. Each agent is specified as a `{ count, tier }` object.

| Key | Default | Description |
|----|--------|------|
| `debug.agents.codex` | `{ count: 2, tier: "premium" }` | Debug Codex agent (0 to exclude) |
| `debug.agents.agy` | `{ count: 0, tier: "premium" }` | Debug AGY agent (0 to exclude) |
| `debug.agents.claude` | `{ count: 0, tier: "economy" }` | Debug Claude agent (0 to exclude) |

Participation rules:
- total: 1 to 6
- defaults when omitted: `codex: 1`, `agy: 1`, `claude: 0`
- When `tier` is omitted, the provider's `models.providers.<provider>.default_tier` is used
- Backward compatible: integer values (`"codex": 1`) are also accepted and interpreted as `{ count: 1 }`

---

## explore.agents

Agent pool for codebase exploration (`/mst:explore`). Each agent is specified as a `{ count, tier }` object.

| Key | Default | Description |
|----|--------|------|
| `explore.agents.codex` | `{ count: 2, tier: "premium" }` | Explore Codex agent (0 to exclude) |
| `explore.agents.agy` | `{ count: 0, tier: "premium" }` | Explore AGY agent (0 to exclude) |
| `explore.agents.claude` | `{ count: 0, tier: "economy" }` | Explore Claude agent (0 to exclude) |

- When `tier` is omitted, the provider's `models.providers.<provider>.default_tier` is used
- Backward compatible: integer values (`"codex": 1`) are also accepted and interpreted as `{ count: 1 }`

---

## models

Configures models for each role. Composed of two sub-sections: `providers` and `roles`.

### models.providers

Defines model tiers (premium/economy) per provider.

| Key | Default | Description |
|----|--------|------|
| `models.providers.codex.premium` | `"gpt-5.3-codex"` | Codex premium model |
| `models.providers.codex.economy` | `"codex-mini"` | Codex economy model |
| `models.providers.codex.default_tier` | `"premium"` | Codex default tier |
| `models.providers.codex.premium_reasoning_effort` | unset | Default reasoning effort for the Codex premium model |
| `models.providers.codex.economy_reasoning_effort` | unset | Default reasoning effort for the Codex economy model |
| `models.providers.codex.default_reasoning_effort` | `"inherit"` | Codex reasoning fallback when no tier setting exists |
| `models.providers.agy.premium` | `"agy-default"` | AGY premium model |
| `models.providers.agy.economy` | `"agy-default"` | AGY economy model |
| `models.providers.agy.default_tier` | `"premium"` | AGY default tier |
| `models.providers.agy.premium_reasoning_effort` | unset | Default reasoning effort for the AGY premium model |
| `models.providers.agy.economy_reasoning_effort` | unset | Default reasoning effort for the AGY economy model |
| `models.providers.agy.default_reasoning_effort` | `"inherit"` | AGY reasoning fallback when no tier setting exists |
| `models.providers.claude.premium` | `"opus"` | Claude premium model |
| `models.providers.claude.economy` | `"sonnet"` | Claude economy model |
| `models.providers.claude.default_tier` | `"economy"` | Claude default tier |
| `models.providers.claude.premium_reasoning_effort` | unset | Default reasoning effort for the Claude premium model |
| `models.providers.claude.economy_reasoning_effort` | unset | Default reasoning effort for the Claude economy model |
| `models.providers.claude.default_reasoning_effort` | `"inherit"` | Claude reasoning fallback when no tier setting exists |

### models.roles

Specifies the provider and tier for each role. Use an array to assign multiple agents in order.

| Key | Default | Description |
|----|--------|------|
| `models.roles.pm_conductor` | `{ provider: "codex", tier: "premium" }` | PM conductor (Phase 1, 3) |
| `models.roles.architect` | `{ provider: "codex", tier: "premium" }` | architect (Design Wing) |
| `models.roles.developer` | `[codex/premium, agy/premium]` | developer (array — multiple agents) |
| `models.roles.developer_claude` | `{ provider: "claude", tier: "premium", enabled: false }` | Claude legacy/fallback developer |
| `models.roles.reviewer` | `[codex/premium, agy/premium]` | reviewer (array — multiple agents) |

### Model resolve rules

When a role specifies a `tier`, the actual model name is resolved from the provider's `providers` definition.

Example: `{ provider: "codex", tier: "premium" }` → `providers.codex.premium` → `"gpt-5.3-codex"`

If `tier` is omitted, the provider's `default_tier` is used.

Each agent or role object accepts `reasoning_effort` with `default | inherit | low | medium | high | xhigh | max | ultra`. `default` first uses the selected model tier's `<tier>_reasoning_effort`, then falls back to the provider's `default_reasoning_effort` when the tier key is absent. `inherit` leaves the native host or CLI default unchanged. A concrete per-call value overrides the tier/provider default, and unsupported provider/model combinations fail before launch. The same resolved binding is used for native, direct external, and Orca external execution.

`premium_reasoning_effort` and `economy_reasoning_effort` are optional. Existing configurations that only define `default_reasoning_effort` continue to work; setting a tier key to `inherit` explicitly uses the host/CLI default for that tier.

> **Terminology note: model tier vs preset tier**
>
> - **model tier** (`premium` / `economy`): Differentiates model grades per provider in `models.providers`.
> - **preset tier** (`performance` / `efficient` / `budget`): A separate system used in example setting presets to express overall system performance levels.
>
> These two tier systems are independent and should not be confused.

### Example config

```json
"models": {
  "providers": {
    "codex": {
      "premium": "gpt-5.3-codex",
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

Agent pool for Spec Pre-review Pass.
Referenced when dispatching Pre-review agents in the `request` skill's Step h-2.

| Key | Default | Description |
|----|--------|------|
| `prereview.agents.codex` | `{ count: 2, tier: "premium" }` | Pre-review Codex agent (0 to exclude) |
| `prereview.agents.agy` | `{ count: 0 }` | Pre-review AGY agent (0 to exclude) |
| `prereview.agents.claude` | `{ count: 0, tier: "economy" }` | Pre-review Claude agent (0 to exclude) |

Defaults are based on `templates/defaults/config.json`.

- When `tier` is omitted, the provider's `models.providers.<provider>.default_tier` is used
- Backward compatible: integer values (`"codex": 1`) are also accepted and interpreted as `{ count: 1 }`

---

## plan_review

Settings for the Plan Review Pass.
Referenced in `/mst:plan` Step 3.8 when running pre-review on the execution plan.

| Key | Default | Description |
|----|--------|------|
| `plan_review.enabled` | `true` | enable/disable Plan Review Pass |
| `plan_review.parallel` | `true` | run review agents in parallel |
| `plan_review.max_iterations` | `2` | maximum review-fix iterations |
| `plan_review.escalation_trigger` | `"major"` | escalation trigger (`critical` / `major` / `minor`) |
| `plan_review.minor_escalation_threshold` | `3` | escalate when MINOR issue count reaches threshold |
| `plan_review.roles.architect.enabled` | `true` | enable architect reviewer |
| `plan_review.roles.architect.agent` | `"codex"` | architect reviewer agent |
| `plan_review.roles.architect.tier` | `"premium"` | architect reviewer model tier (resolved from `models.providers`) |
| `plan_review.roles.devils_advocate.enabled` | `true` | enable devil's advocate reviewer |
| `plan_review.roles.devils_advocate.agent` | `"agy"` | devil's advocate reviewer agent |
| `plan_review.roles.devils_advocate.tier` | `"premium"` | devil's advocate reviewer model tier (resolved from `models.providers`) |
| `plan_review.roles.completeness.enabled` | `true` | enable completeness reviewer |
| `plan_review.roles.completeness.agent` | `"codex"` | completeness reviewer agent |
| `plan_review.roles.completeness.tier` | `"premium"` | completeness reviewer model tier (resolved from `models.providers`) |
| `plan_review.roles.ux_reviewer.enabled` | `true` | enable UX reviewer |
| `plan_review.roles.ux_reviewer.agent` | `"agy"` | UX reviewer agent |
| `plan_review.roles.ux_reviewer.tier` | `"premium"` | UX reviewer model tier (resolved from `models.providers`) |

---

## review

Settings for implementation review (`/mst:review`).
Used in Phase 3 for AC verification and parallel code/architecture/UI reviews.

| Key | Default | Description |
|----|--------|------|
| `review.auto_review` | `true` | auto-invoke `mst:review` in Phase 3 |
| `review.max_iterations` | `3` | maximum review-fix iterations |
| `review.roles.code_reviewer.agent` | `"codex"` | code reviewer agent |
| `review.roles.code_reviewer.tier` | `"premium"` | code reviewer model tier (resolved from `models.providers`) |
| `review.roles.arch_reviewer.agent` | `"agy"` | architecture reviewer agent |
| `review.roles.arch_reviewer.tier` | `"premium"` | architecture reviewer model tier (resolved from `models.providers`) |
| `review.roles.ui_reviewer.agent` | `"agy"` | UI reviewer agent |
| `review.roles.ui_reviewer.tier` | `"premium"` | UI reviewer model tier (resolved from `models.providers`) |
| `review.severity_auto_fix.enabled` | `true` | enable severity-based auto-fix |
| `review.severity_auto_fix.minor_skip_threshold` | `3` | MINOR issue skip threshold |
| `review.severity_auto_fix.pm_direct_fix_enabled` | `true` | enable PM direct fix |
| `review.severity_auto_fix.pm_direct_fix_max_files` | `1` | max files for PM direct fix |
| `review.severity_auto_fix.pm_direct_fix_max_diff_lines` | `20` | max diff lines for PM direct fix |
| `review.severity_auto_fix.security_override_keywords` | `["authentication", "authorization", ...]` | security override keyword list |

---

## phase1_exploration

Agent role settings for Phase 1 codebase exploration.
In `/mst:request` Step 4.c, the PM reads `config.phase1_exploration.roles` and dispatches only roles with `enabled: true` in the background.

| Key | Default | Description |
|----|--------|------|
| `phase1_exploration.roles.symbol_tracing.agent` | `"codex"` | precise symbol tracing agent |
| `phase1_exploration.roles.symbol_tracing.enabled` | `true` | enable symbol tracing role |
| `phase1_exploration.roles.symbol_tracing.tier` | `"premium"` | model tier for symbol tracing (resolved from `models.providers`) |
| `phase1_exploration.roles.broad_scan.agent` | `"agy"` | broad scan agent |
| `phase1_exploration.roles.broad_scan.enabled` | `true` | enable broad scan role |
| `phase1_exploration.roles.broad_scan.tier` | `"premium"` | model tier for broad scan (resolved from `models.providers`) |

---

## notifications / realtime / debug / cleanup

Settings for notifications, realtime updates, debug logging, and session cleanup.

| Key | Default | Description |
|----|--------|------|
| `notifications.terminal` | `true` | terminal notifications |
| `notifications.dashboard` | `true` | dashboard notifications |
| `realtime.protocol` | `sse` | realtime protocol (SSE) |
| `realtime.debounce_ms` | `100` | event debounce (ms) |
| `debug.enabled` | `false` | debug mode |
| `debug.log_level` | `info` | log level |
| `debug.log_prompts` | `false` | prompt logging |
| `cleanup.ideation_keep_count` | `10` | number of ideation sessions kept |
| `cleanup.discussion_keep_count` | `10` | number of discussion sessions kept |
| `cleanup.debug_keep_count` | `10` | number of debug sessions kept |
| `cleanup.old_request_threshold_hours` | `24` | threshold to classify old requests (hours) |

---

## Example setting presets

The following are recommended presets by usage pattern.
Apply these in `.gran-maestro/config.json` or change individually with `/mst:settings <key> <value>`.

### Example 1: parallel execution optimized

Maximize throughput for handling many tasks in team settings.
Recommended only on machines with sufficient resources.

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

### Example 2: cost-saving mode

Limit agent count and discussion rounds to minimize API cost.
Suitable for small projects or personal development.

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

### Example 3: offline / auto-accept mode

Run workflows fully automatically without interaction.
Suitable for CI/CD pipelines or nightly batch jobs.

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
