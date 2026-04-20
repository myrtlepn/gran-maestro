[한국어](skills-reference.md) | [English](skills-reference.en.md)

# Gran Maestro Skill Reference

This is the full reference for 27 skills provided by the Gran Maestro plugin.
Each skill is invoked with the `/mst:{name}` form.

---

## Table of contents

- [Category overview](#category-overview)
- [Orchestration](#orchestration)
  - [/mst:request](#mstrequest)
  - [/mst:plan](#mstplan)
  - [/mst:approve](#mstapprove)
  - [/mst:accept](#mstaccept)
  - [/mst:feedback](#mstfeedback)
  - [/mst:cancel](#mstcancel)
  - [/mst:recover](#mstrecover)
  - [/mst:priority](#mstpriority)
- [Monitoring](#monitoring)
  - [/mst:list](#mstlist)
  - [/mst:inspect](#mstinspect)
  - [/mst:history](#msthistory)
  - [/mst:dashboard](#mstdashboard)
- [Analysis tools](#analysis-tools)
  - [/mst:ideation](#mstideation)
  - [/mst:discussion](#mstdiscussion)
  - [/mst:debug](#mstdebug)
- [Direct CLI execution](#direct-cli-execution)
  - [/mst:codex](#mstcodex)
  - [/mst:gemini](#mstgemini)
  - [/mst:claude](#mstclaude)
- [Design tools](#design-tools)
  - [/mst:stitch](#mststitch)
  - [/mst:ui-designer](#mstuidesigner)
  - [/mst:schema-designer](#mstschemadesigner)
  - [/mst:feedback-composer](#mstfeedback-composer)
- [Management](#management)
  - [/mst:settings](#mstsettings)
  - [/mst:on](#mston)
  - [/mst:off](#mstoff)
  - [/mst:cleanup](#mstcleanup)
  - [/mst:archive](#mstarchive)
- [English natural language triggers](#english-natural-language-triggers)

---

## Category overview

| Category | Skill count | Description |
|---------|---------|------|
| Orchestration | 8 | core flow control: start, approve, feedback, cancel, recover |
| Monitoring | 4 | request/task status viewing and dashboard |
| Analysis tools | 3 | ideation, discussion, debug — can be used independently of workflow mode |
| Direct CLI calls | 3 | dispatching Codex/Gemini/Claude sub-agents directly |
| Design tools | 4 | UI, DB, feedback design specialist agents |
| Management | 5 | mode transition, settings, session cleanup |

---

## Orchestration

The core skill group that controls Gran Maestro workflow (Phase 1 → 2 → 3 → 5).

---

### /mst:request

**One-line description**: enter PM analysis workflow and start a new request.

**Arguments**: `[--auto|-a] {request content}`

#### Purpose

Entry point for requests entering the PM (Claude) analysis phase of Gran Maestro workflow. If Maestro mode is inactive, it auto-initializes (bootstraps).

#### When to use

- when requesting code work such as new feature implementation, refactoring, or bug fixes
- when you want PM to analyze the request and write a spec
- when you want to run immediately with `--auto` flag without Q&A

#### Examples

```
/mst:request 로그인 화면에 구글 소셜 로그인 버튼을 추가해줘
/mst:request --auto JWT 토큰 만료 시간을 30분으로 변경
```

---

### /mst:plan

**One-line description**: clarify unresolved items with Q&A and write an executable plan.

**Arguments**: `{planning topic}`

#### Purpose

Before implementation, it refines unresolved requirements through conversation with the user. It clarifies scope and constraints, then stores the result in `.gran-maestro/plans/PLN-NNN/plan.md`. After plan creation, it proceeds to `/mst:request`.

#### When to use

- when requests are complex or include multiple unresolved decisions
- when preparing multiple requests to approve in batch with `/mst:approve`
- when you want to define scope and priorities before implementation
- when you want to refine implementation scope based on debug results (`/mst:debug`)

#### Examples

```
/mst:plan 알림 시스템 전체 리팩터링
/mst:plan 결제 모듈 추가 — Stripe 연동 범위 논의
/mst:plan --from-debug DBG-012   # connect to debug session
```

#### Best practice

For independent planning of multiple features:
```
/mst:plan feature A
/mst:plan feature B
/mst:plan feature C
/mst:approve PLN-001 PLN-002 PLN-003   # batch approve then parallel execution
```

---

### /mst:approve

**One-line description**: approve PM-written implementation spec and start Phase 2 execution.

**Arguments**: `[REQ-ID...] [--stop-on-fail | --continue] [--parallel] [--priority <level>]`

#### Purpose

Reviews spec written by PM and approves to start actual implementation (Phase 2). Supports single and batch approval. After Phase 3 review PASS, final acceptance (`/mst:accept`) runs by default automatically.

#### When to use

- when PM completes spec and asks to proceed
- when approving multiple REQ in one batch

#### Examples

```
/mst:approve                          # auto-select first pending REQ
/mst:approve REQ-007                  # single approval
/mst:approve REQ-007 REQ-008 REQ-009  # multi-batch approval
/mst:approve --parallel               # parallel execution
/mst:approve REQ-007 --stop-on-fail   # stop on failure
```

---

### /mst:accept

**One-line description**: final accept review-passed outputs and merge to main branch (Phase 3 → Phase 5).

**Arguments**: `[REQ-ID]`

#### Purpose

Merges Phase 3 PASS worktrees into main branch and cleans up. Called automatically from `/mst:approve` by default. If `workflow.auto_accept_result=false`, call manually.

#### When to use

- when final acceptance is controlled manually with `workflow.auto_accept_result=false`
- when you want to merge and finalize after explicit review

#### Examples

```
/mst:accept           # auto-select first REQ waiting for acceptance
/mst:accept REQ-007   # accept specific REQ
```

---

### /mst:feedback

**One-line description**: provide manual feedback on an in-progress request in Gran Maestro workflow (Phase 4).

**Arguments**: `{REQ-ID} {feedback}`

#### Purpose

Passes direct user observations or additional requirements outside automated review. Feedback is structured by Feedback Composer and triggers a fix loop in Phase 4.

#### When to use

- when user notices issues missed by auto-review
- when you need additional changes after result inspection

#### Examples

```
/mst:feedback REQ-007 버튼 클릭 시 로딩 스피너가 표시되지 않음
/mst:feedback REQ-007 모바일 뷰에서 레이아웃이 깨집니다
```

---

### /mst:cancel

**One-line description**: cancel in-progress requests/tasks and clean up related resources.

**Arguments**: `{REQ-ID} [--force]`

#### Purpose

Terminates running agent/CLI processes and cleans up worktree and temporary branches.

#### When to use

- to stop a wrongly started request
- when requirement changed and current work becomes unnecessary

#### Examples

```
/mst:cancel REQ-007          # cancel with confirmation
/mst:cancel REQ-007 --force  # force cancel without confirmation
```

---

### /mst:recover

**One-line description**: recover incomplete requests after Claude Code session ends and resume from last phase.

**Arguments**: `[{REQ-ID}] [{TASK-ID}]`

#### Purpose

Scans recoverable tasks from file-based state and resumes interrupted workflows automatically.

#### When to use

- when continuing work interrupted after Claude Code session ends
- when recovering only a specific request or task

#### Examples

```
/mst:recover                      # auto-search and resume recoverable requests
/mst:recover REQ-007              # recover specific REQ
/mst:recover REQ-007 02           # recover specific task
```

---

### /mst:priority

**One-line description**: change task priority and execution order.

**Arguments**: `{TASK-ID} --before {TASK-ID}`

#### Purpose

Overrides execution order determined by PM. Updates `request.json` `execution_order` and warns on dependency conflicts.

#### When to use

- when you want one task to run first
- when you want to override full task execution order

#### Examples

```
/mst:priority REQ-001-02 --before REQ-001-01   # run 02 before 01
/mst:priority REQ-001-03 --after REQ-001-01    # run 03 after 01
/mst:priority REQ-001 --reorder 03,01,02       # specify full order
```

---

## Monitoring

A monitoring group for viewing status of in-progress or completed requests/tasks.

---

### /mst:list

**One-line description**: show a summary list of all requests and tasks in terminal.

**Arguments**: `[--all | --active | --completed]`

#### Purpose

Classifies and outputs all requests under `.gran-maestro/requests/` by status. Runs Python script `mst.py` first and falls back to file scan on failure.

#### When to use

- when you quickly need to know number of active requests
- when needing detailed status lookup for a request use `/mst:inspect`

#### Examples

```
/mst:list             # active request list
/mst:list --all       # all requests including completed
/mst:list --completed # completed requests only
```

---

### /mst:inspect

**One-line description**: show detailed status for a specific request.

**Arguments**: `{REQ-ID}`

#### Purpose

Displays detailed information for a specific REQ including Phase progression, task-level statuses, agent activity, and feedback iteration history.

#### When to use

- when you want to know which Phase a request is in
- when tracing task execution results or error causes

#### Examples

```
/mst:inspect REQ-007
```

---

### /mst:history

**One-line description**: query completed request history.

**Arguments**: `[{REQ-ID}] [--limit {N}]`

#### Purpose

Displays history of requests with `status: completed` or `status: cancelled`, with request summary, elapsed time, agent usage, and number of feedback rounds.

#### When to use

- when reviewing past completed work
- when checking overall flow for a specific REQ

#### Examples

```
/mst:history               # completed history list (recent first)
/mst:history REQ-007       # detailed history for specific REQ
/mst:history --limit 10    # latest 10 items
```

---

### /mst:dashboard

**One-line description**: start Gran Maestro local dashboard server and open in browser.

**Arguments**: `[--port {port}] [--stop] [--restart]`

#### Purpose

Provides workflow graph, agent stream, and document browser in a web UI. Operates as one hub managing multiple projects in one server instance. Requires Deno runtime.

#### When to use

- when you want visual workflow monitoring instead of terminal-only output
- when you want to view status of multiple projects from one screen

#### Examples

```
/mst:dashboard              # start server and open browser
/mst:dashboard --port 8080  # specify port
/mst:dashboard --stop       # stop server
/mst:dashboard --restart    # restart server
```

---

## Analysis tools

AI collaboration analysis tools that can be used independently of Maestro mode state.

---

### /mst:ideation

**One-line description**: collect AI team opinions in parallel; PM synthesizes.

**Arguments**: `{topic} [--focus {architecture|ux|performance|security|cost}]`

#### Purpose

A brainstorming skill where multiple AI agents (Codex, Gemini, etc.) collect ideas in one parallel round and PM (Claude) synthesizes them. The goal is to explore multiple perspectives, not necessarily to reach consensus.

#### When to use

- when multi-angle opinions are needed before implementation
- when quick collection of technical viewpoints is needed
- when idea exploration is the goal rather than immediate consensus

#### Examples

```
/mst:ideation 실시간 알림 시스템 아키텍처 선택 (WebSocket vs SSE vs Polling)
/mst:ideation 모바일 앱 네비게이션 패턴 --focus ux
/mst:ideation 데이터베이스 샤딩 전략 --focus performance
```

---

### /mst:discussion

**One-line description**: AI team members repeatedly discuss until consensus is reached.

**Arguments**: `{subject or IDN-NNN} [--max-rounds {N}] [--focus {domain}]`

#### Purpose

PM acts as moderator, identifies divergence points, and guides convergence by passing counterpoints between AI members. If ideation is one-round divergence, discussion aims for convergence through N rounds.

#### Difference from ideation

| Item | /mst:ideation | /mst:discussion |
|------|--------------|----------------|
| Goal | collect perspectives (divergence) | reach consensus (convergence) |
| Rounds | 1 | N repeated |
| Stop condition | PM synthesis complete | participant consensus or max rounds |

#### When to use

- when you want to deepen and converge previous ideation results
- when technical choice requires team-level agreement

#### Examples

```
/mst:discussion IDN-003                           # continue from existing ideation
/mst:discussion REST vs GraphQL API design decision --max-rounds 3
/mst:discussion microservice decomposition threshold agreement --focus architecture
```

---

### /mst:debug

**One-line description**: multiple AIs investigate bugs in parallel and produce a consolidated debug report.

**Arguments**: `{bug/issue description} [--focus {filePattern}]`

#### Purpose

Configured AI team members investigate bugs independently in parallel while PM (Claude) also participates; all results are merged into a consolidated debug report (`debug-report.md`). The report includes root cause, prioritized fix suggestions (P0~P2), and list of impacted files. After creation, continue naturally with `/mst:plan --from-debug DBG-NNN`.

#### When to use

- when bug root cause is unclear
- when investigating complex issues across multiple files
- when you need exact cause analysis before fixing

#### Examples

```
/mst:debug 로그인 후 대시보드가 빈 화면을 표시함
/mst:debug API 응답이 간헐적으로 500 에러를 반환 --focus src/api/
/mst:debug 빌드 후 테스트 전체가 실패함
```

---

## Direct CLI execution

Skills for directly dispatching external AI CLI tools and Claude sub-agents. Can be used regardless of Maestro mode.

---

### /mst:codex

**One-line description**: call Codex CLI to execute coding work.

**Arguments**: `{prompt} [--prompt-file {path}] [--dir {path}] [--json] [--trace {REQ/TASK/label}]`

#### Purpose

Single entry point for Codex CLI calls. Every Codex call inside and outside Gran Maestro workflow goes through this skill.

#### When to use

- when you want to execute Codex CLI directly
- when PM dispatches implementation tasks to Codex within workflow
- when you need to pass a long prompt via `--prompt-file`

#### Examples

```
/mst:codex "Implement JWT validation logic in src/auth.ts"
/mst:codex --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
/mst:codex "Write tests" --trace REQ-007/01/tests
```

---

### /mst:gemini

**One-line description**: call Gemini CLI for large-context jobs.

**Arguments**: `{prompt} [--prompt-file {path}] [--dir {path}] [--files {pattern}] [--trace {REQ/TASK/label}]`

#### Purpose

Single entry point for Gemini CLI calls. Suitable for large-context tasks such as full frontend analysis or documentation-heavy work.

#### When to use

- when analyzing full frontend codebase
- when large-context tasks (e.g., documenting 27 skills) need Gemini
- when passing multiple files through `--files` context

#### Examples

```
/mst:gemini "Analyze this codebase architecture"
/mst:gemini --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
```

---

### /mst:claude

**One-line description**: call Claude sub-agent for code work.

**Arguments**: `{prompt} [--prompt-file {path}] [--dir {path}] [--trace {REQ/TASK/label}]`

#### Purpose

Maintains the PM Conductor principle "I conduct, I don't code" by spawning a separate Claude sub-agent process and separating implementation tasks. Useful when Codex/Gemini are unavailable or when tasks require Claude file tools (Read/Write/Edit/Bash/Glob/Grep).

#### When to use

- when implementing tasks via Claude sub-agent in environments without Codex/Gemini CLI
- when dispatching `claude-dev` tasks inside Gran Maestro workflow
- when read/write/edit-style tasks should be executed by sub-agent

#### Examples

```
/mst:claude "Modify src/components/LoginForm.tsx to add Google login button"
/mst:claude --prompt-file .gran-maestro/requests/REQ-007/tasks/01/spec.md --dir .gran-maestro/worktrees/REQ-007-01
/mst:claude "Fix type errors" --trace REQ-007/01/typefix
```

---

## Design tools

Design Wing specialist agent skills executed by PM Conductor with argument substitution.

---

### /mst:stitch

**One-line description**: generate UI mockups and drafts via Google Stitch MCP.

**Arguments**: `[--auto] [--variants] [--req REQ-NNN] {screen description}`

#### Purpose

Uses Stitch MCP tools to generate UI screen drafts and returns Stitch project URLs and images. It captures existing screen context to maintain layout consistency and avoid duplicated work.

#### When to use

- when generating mockups or mockup drafts ("design a screen", "make a mockup")
- when you want to confirm UI before implementing a new route/page
- when you want to explore whole redesign directions with multiple variants

#### Precondition

`config.stitch.enabled: true` must be enabled.

#### Trigger routing

| Trigger | Processing |
|--------|-------------|
| "draw a screen", "design with Stitch", "make mockup" | create immediately |
| adding a new route file + navigation exposure expected | create after user confirmation |
| "full redesign", "redesign" | suggest 2-3 variants after confirmation |
| only existing component style adjustments | no Stitch intervention |

#### Examples

```
/mst:stitch 로그인 화면 — 이메일/비밀번호 입력 폼 + 구글 로그인 버튼
/mst:stitch --variants 대시보드 메인 화면 전체 리디자인
/mst:stitch --req REQ-007 알림 설정 패널
```

---

### /mst:ui-designer

**One-line description**: Design Wing agent for screen structure, component structure, interaction flow, and design system.

**Arguments**: PM Conductor substitutes variables and executes `/mst:codex`

#### Purpose

Creates UI spec documents. Defines component tree and props/state flow, user journeys (happy/error/edge), design system tokens (color/spacing/typography), and responsive breakpoints. Does not generate implementation code.

#### When to use

- when PM wants a separate UI design step before frontend implementation
- when documenting component hierarchy and state flow in advance

---

### /mst:schema-designer

**One-line description**: Design Wing agent that designs DB schema, data models, ERD, and migration plans.

**Arguments**: PM Conductor substitutes variables and executes `/mst:codex`

#### Purpose

Generates data model design docs including entity-relationship diagrams, field types/constraints/defaults, migration strategy preserving data integrity, and index design aligned with query patterns. No implementation code.

#### When to use

- when performing design steps before implementing a request involving data model changes
- when you want ERD and migration strategy finalized in documentation first

---

### /mst:feedback-composer

**One-line description**: agent that writes precise feedback docs an outsourced agent can implement in one pass.

**Arguments**: PM Conductor substitutes variables and executes `/mst:codex`

#### Purpose

Consolidates multiple review outputs into a clear feedback doc. Includes file:line references, issue details, and fix strategy, and provides priorities `CRITICAL > HIGH > MEDIUM > LOW` and categories `implementation_error | spec_insufficient`.

#### When to use

- when PM auto-calls this after Phase 3 review FAIL and needs actionable fix instructions
- when compiling multiple reviewer findings into one executable document

---

## Management

A skill group handling Maestro mode switching, settings, and session cleanup.

---

### /mst:settings

**One-line description**: query or update Gran Maestro settings.

**Arguments**: `[{key} [{value}]]`

#### Purpose

Manages `.gran-maestro/config.json`. Without args, displays full settings; with key only, displays that value; with key and value updates it.

#### When to use

- when checking or changing workflow settings (auto-accept, parallel execution, etc.)
- when enabling/disabling Stitch integration is needed

#### Examples

```
/mst:settings                                    # show all settings
/mst:settings workflow.auto_accept_result        # show specific value
/mst:settings workflow.auto_accept_result false  # change setting
/mst:settings stitch.enabled true               # enable Stitch integration
```

---

### /mst:on

**One-line description**: activate Gran Maestro mode.

**Arguments**: none

#### Purpose

Activates Maestro orchestration skills and updates `.gran-maestro/mode.json` to `active: true`. Calling `/mst:request` includes bootstrap, so separate `/mst:on` is often unnecessary.

#### When to use

- when you want to explicitly enable Maestro mode
- when you want to activate and verify mode state manually

#### Examples

```
/mst:on
```

---

### /mst:off

**One-line description**: deactivate Gran Maestro mode.

**Arguments**: `[--force]`

#### Purpose

Updates `.gran-maestro/mode.json` to `active: false`. Displays warnings if active requests exist. With `--force`, active requests are marked `paused`.

#### When to use

- when you want to temporarily pause Maestro workflow
- when switching to another work mode

#### Examples

```
/mst:off           # deactivate immediately if no active requests
/mst:off --force   # force deactivate and mark active requests as paused
```

---

### /mst:cleanup

**One-line description**: batch cleanup ideation, discussion, and requests sessions.

**Arguments**: `[--run] [--dry-run]`

#### Purpose

Cleans all session types in one command. Ideation and discussion keep only recent N items and archive excess; completed requests auto-archive and old active requests are cleaned with user confirmation. Works regardless of Maestro mode state.

#### Difference from /mst:archive

| Item | /mst:cleanup | /mst:archive |
|------|-------------|-------------|
| Purpose | clean all at once | fine-grained per type |
| Flow | 3-step auto + interactive | manual targeted |
| Restore | not supported | supported (`--restore`) |
| Scope | batch ideation + discussion + requests | individual by `--type` |

#### When to use

- when many sessions accumulate and you need one-time cleanup
- when quick all-in cleanup is required

#### Examples

```
/mst:cleanup --dry-run  # preview cleanup targets
/mst:cleanup --run      # execute cleanup
```

---

### /mst:archive

**One-line description**: manage session archives by type in a granular way.

**Arguments**: `[--run [--type {ideation|discussion|requests}]] [--restore {ID}] [--purge [--before {YYYY-MM-DD}]] [--list]`

#### Purpose

Archives session directories under each type's `archived/` using tar.gz. Keeps up to `max_active_sessions` (default 200), archives excess entries, and supports restore (`--restore`) or permanent purge (`--purge`).

#### When to use

- when selectively archiving only one session type (ideation/discussion/requests)
- when restoring an archived session is needed
- when permanently deleting old archives

#### Examples

```
/mst:archive --list                              # view archive status
/mst:archive --run --type ideation               # archive only ideation
/mst:archive --restore IDN-003                   # restore specific session
/mst:archive --purge --before 2025-01-01         # delete archives before 2025
```

---

## English natural language triggers

Gran Maestro detects intent from Korean utterances and executes the matching skill automatically. The following are major trigger keywords and corresponding skills.

### Orchestration triggers

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "implement", "build", "develop", "add", "create" | `/mst:request` |
| "make a plan", "write plan", "refine", "define scope" | `/mst:plan` |
| "approve", "start", "ok", "proceed", "run" | `/mst:approve` |
| "accept", "merge", "final accept", "combine" | `/mst:accept` |
| "feedback", "request fix", "this is wrong", "fix again" (within workflow) | `/mst:feedback` |
| "cancel", "stop", "pause", "halt" | `/mst:cancel` |
| "recover", "resume", "continue" | `/mst:recover` |
| "change priority", "change order", "run first", "before" | `/mst:priority` |

### Monitoring triggers

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "status", "show status", "list", "what is happening" | `/mst:list` |
| "detailed status", "show details", "REQ-NNN status" | `/mst:inspect` |
| "history", "past", "completed request", "previous work" | `/mst:history` |
| "dashboard", "open dashboard", "monitor", "visualize" | `/mst:dashboard` |

### Analysis tool triggers

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "idea", "brainstorm", "gather opinions", "collect perspectives" | `/mst:ideation` |
| "discussion", "consensus", "debate", "deep discussion" | `/mst:discussion` |
| "bug", "error", "fault", "not working", "analyze" | `/mst:debug` |

### Design tool triggers

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "design screen", "make mockup", "draw with Stitch", "UI draft", "plan page" | `/mst:stitch` |

### Direct CLI trigger

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "run codex", "use codex", "work with codex" | `/mst:codex` |
| "run gemini", "use gemini", "analyze with gemini", "large analysis" | `/mst:gemini` |
| "run claud", "use claud", "claude sub-agent", "sub-agent" | `/mst:claude` |

### Management triggers

| Natural language keywords / patterns | auto-triggered skill |
|--------------------------|--------------|
| "settings", "change settings", "environment", "config" | `/mst:settings` |
| "enable maestro", "start maestro", "turn on conductor mode" | `/mst:on` |
| "disable maestro", "turn off maestro", "deactivate maesto" | `/mst:off` |
| "cleanup", "clean up", "clear", "remove all sessions" | `/mst:cleanup` |
| "archive", "archive session", "compress storage" | `/mst:archive` |

---

*This document is generated by scanning the `skills/` directory of the Gran Maestro plugin. Keep it updated whenever skills are added or changed.*
