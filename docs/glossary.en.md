[한국어](glossary.md) | [English](glossary.en.md)

# Gran Maestro Glossary

This document defines the official terminology used by the Gran Maestro plugin.
Consistent term usage reduces communication ambiguity.

## Core Terms

| Official term | Description | Forbidden alternatives |
|----------|------|----------------|
| **Gran Maestro** | Plugin name | Maestro (can be ambiguous when used alone) |
| **PM Conductor** | AI leader that directs the team in Phase 1/3 | PM, Claude, Claude Code |
| **Analysis Squad** | Team analyzing the codebase in Phase 1 | analysis team, Team |
| **Design Wing** | Group of agents writing design documents in Phase 1 | design team |
| **Review Squad** | Team validating code in Phase 3 | review team, Team |
| **Outsource Brief** | Prompt document delivered to CLI agents in Phase 2 | external spec, prompt |
| **Feedback Composer** | Agent that converts review outcomes into implementation tasks in Phase 4 | — |

## Phase Terms

| Term | Description |
|------|------|
| **Phase 1: PM analysis** | requirement analysis, spec writing, task splitting, user approval |
| **Phase 2: outsourced execution** | work done in worktrees by `/mst:codex` / `/mst:agy` |
| **Phase 3: PM review** | verify results, map against acceptance criteria, PASS/FAIL judgment |
| **Phase 4: feedback loop** | classify failure type, write feedback docs, return to Phase 2 or 1 |
| **Phase 5: accept / complete** | rebase + squash merge, worktree cleanup, notification |

## ID System

| Pattern | Description | Example |
|------|------|-----------|
| `REQ-NNN` | original user request | REQ-001 |
| `REQ-NNN-NN` | task split by PM | REQ-001-02 |
| `REQ-NNN-NN-RN` | feedback revision | REQ-001-02-R1 |

## Task Status (FSM)

| Status | Description | Phase |
|------|------|-------|
| `pending` | Created in Phase 1, waiting for execution | 1 |
| `queued` | entered execution queue (parallel slot waiting) | 2 |
| `executing` | CLI execution in progress | 2 |
| `pre_check` | pre-check (typecheck/test) | 2 |
| `pre_check_failed` | pre-check failed | 2 |
| `review` | PM review in progress | 3 |
| `feedback` | feedback written, waiting for re-run | 4 |
| `merging` | rebase + merge in progress | 5 |
| `merge_conflict` | conflict occurred, waiting for resolution | 5 |
| `done` | completed (merged) | 5 |
| `failed` | failed due to system error | — |
| `cancelled` | cancelled by user | — |

## Agent Types

| Type | agents.json key | Provider | Phase |
|------|---------------|----------|-------|
| execution agent | `codex-dev`, `agy-dev` | `/mst:codex` / `/mst:agy` | 2 |
| review agent | `codex-reviewer`, `agy-reviewer` | `/mst:codex` / `/mst:agy` | 3 |
| analysis agent | `architect`, `schema-designer`, `ui-designer` | Claude Code | 1 |

## Modes

| Mode | Description |
|------|------|
| **Maestro mode** | Gran Maestro active. Claude Code acts only as PM |
| **Batch mode** | Multiple REQ IDs are approved and executed in parallel |
