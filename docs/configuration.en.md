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
| `discussion.agents.codex` | `{ count: 1, tier: "premium" }` | Discussion Codex agent (0 to exclude) |
| `discussion.agents.gemini` | `{ count: 1, tier: "premium" }` | Discussion Gemini agent (0 to exclude) |
| `discussion.agents.claude` | `{ count: 1, tier: "economy" }` | Discussion Claude agent (0 to exclude) |
| `discussion.response_char_limit` | `2000` | Discussion response character limit |
| `discussion.critique_char_limit` | `2000` | Discussion critique character limit |
| `discussion.default_max_rounds` | `5` | default max number of rounds |
| `discussion.max_rounds_upper_limit` | `10` | maximum rounds upper limit |
| `ideation.agents.codex` | `{ count: 1, tier: "premium" }` | Ideation Codex agent (0 to exclude) |
| `ideation.agents.gemini` | `{ count: 1, tier: "premium" }` | Ideation Gemini agent (0 to exclude) |
| `ideation.agents.claude` | `{ count: 1, tier: "economy" }` | Ideation Claude agent (0 to exclude) |
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
| `debug.agents.codex` | `{ count: 1, tier: "premium" }` | Debug Codex agent (0 to exclude) |
| `debug.agents.gemini` | `{ count: 1, tier: "premium" }` | Debug Gemini agent (0 to exclude) |
| `debug.agents.claude` | `{ count: 0 }` | Debug Claude agent (0 to exclude) |

Participation rules:
- total: 1 to 6
- defaults when omitted: `codex: 1`, `gemini: 1`, `claude: 0`
- When `tier` is omitted, the provider's `models.providers.<provider>.default_tier` is used
- Backward compatible: integer values (`"codex": 1`) are also accepted and interpreted as `{ count: 1 }`

---

## explore.agents

Agent pool for codebase exploration (`/mst:explore`). Each agent is specified as a `{ count, tier }` object.

| Key | Default | Description |
|----|--------|------|
| `explore.agents.codex` | `{ count: 1, tier: "premium" }` | Explore Codex agent (0 to exclude) |
| `explore.agents.gemini` | `{ count: 1, tier: "premium" }` | Explore Gemini agent (0 to exclude) |
| `explore.agents.claude` | `{ count: 0 }` | Explore Claude agent (0 to exclude) |

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
| `models.providers.gemini.premium` | `"gemini-3.1-pro-preview"` | Gemini premium model |
| `models.providers.gemini.economy` | `"gemini-2.5-flash"` | Gemini economy model |
| `models.providers.gemini.default_tier` | `"premium"` | Gemini default tier |
| `models.providers.claude.premium` | `"opus"` | Claude premium model |
| `models.providers.claude.economy` | `"sonnet"` | Claude economy model |
| `models.providers.claude.default_tier` | `"economy"` | Claude default tier |

### models.roles

Specifies the provider and tier for each role. Use an array to assign multiple agents in order.

| Key | Default | Description |
|----|--------|------|
| `models.roles.pm_conductor` | `{ provider: "claude", tier: "premium" }` | PM conductor (Phase 1, 3) |
| `models.roles.architect` | `{ provider: "claude", tier: "premium" }` | architect (Design Wing) |
| `models.roles.developer` | `[codex/premium, gemini/premium]` | developer (array — multiple agents) |
| `models.roles.developer_claude` | `{ provider: "claude", tier: "premium" }` | Claude developer |
| `models.roles.reviewer` | `[codex/premium, gemini/premium]` | reviewer (array — multiple agents) |

### Model resolve rules

When a role specifies a `tier`, the actual model name is resolved from the provider's `providers` definition.

Example: `{ provider: "codex", tier: "premium" }` → `providers.codex.premium` → `"gpt-5.3-codex"`

If `tier` is omitted, the provider's `default_tier` is used.

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

Agent pool for Spec Pre-review Pass.
Referenced when dispatching Pre-review agents in the `request` skill's Step h-2.

| Key | Default | Description |
|----|--------|------|
| `prereview.agents.codex` | `{ count: 1, tier: "premium" }` | Pre-review Codex agent (0 to exclude) |
| `prereview.agents.gemini` | `{ count: 0 }` | Pre-review Gemini agent (0 to exclude) |
| `prereview.agents.claude` | `{ count: 1, tier: "economy" }` | Pre-review Claude agent (0 to exclude) |

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
| `plan_review.roles.devils_advocate.agent` | `"gemini"` | devil's advocate reviewer agent |
| `plan_review.roles.devils_advocate.tier` | `"premium"` | devil's advocate reviewer model tier (resolved from `models.providers`) |
| `plan_review.roles.completeness.enabled` | `true` | enable completeness reviewer |
| `plan_review.roles.completeness.agent` | `"codex"` | completeness reviewer agent |
| `plan_review.roles.completeness.tier` | `"premium"` | completeness reviewer model tier (resolved from `models.providers`) |
| `plan_review.roles.ux_reviewer.enabled` | `true` | enable UX reviewer |
| `plan_review.roles.ux_reviewer.agent` | `"gemini"` | UX reviewer agent |
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
| `review.roles.arch_reviewer.agent` | `"gemini"` | architecture reviewer agent |
| `review.roles.arch_reviewer.tier` | `"premium"` | architecture reviewer model tier (resolved from `models.providers`) |
| `review.roles.ui_reviewer.agent` | `"gemini"` | UI reviewer agent |
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
| `phase1_exploration.roles.broad_scan.agent` | `"gemini"` | broad scan agent |
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
