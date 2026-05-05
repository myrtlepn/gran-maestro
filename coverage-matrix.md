# REQ-821 Final Coverage Matrix

- Request: REQ-821
- Task: T03 final validation and evidence
- Plan: PLN-648
- Objective: AGI-030
- Sprint: S17
- DoD: DOD-008
- Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-821/t03`
- Branch: `gran-maestro/master/AGI-030/REQ-821-T03`
- Head under validation: `f7c0fd34081542e92f7fa6a01c835ba7bed3ec69`
- Checked at: `2026-05-05T19:37:39Z`
- Overall status: PASS

## DOD-008 Source-Of-Truth Policy

Canonical identity remains `MST_SESSION_ID` / `mst_session_id`. `owner_pid` is process lock liveness diagnostic-only evidence for stale/history/result lock diagnostics. It is not a canonical identity source, fallback, alias, migration source, recover target, continuation policy key, or lock takeover trigger.

Stale lock diagnostic behavior is read-only: diagnostics may report `lock_path`, `owner_pid`, `owner_status`, stale reason, and next action, but they must not create or mutate `.gran-maestro/state/{owner_pid}`, `.gran-maestro/sessions/{owner_pid}`, canonical `history.head`, policy mirror heads, recover artifacts, or lock owner files.

## PAC Coverage

| PAC | Grade | AC | Status | Evidence |
| --- | --- | --- | --- | --- |
| PAC-1 | MUST | AC-009, AC-013 | PASS | DOD-008 targeted suite and DOD-007 regression passed; owner_pid is asserted as diagnostic-only, not a canonical identity source/fallback/alias/migration/takeover trigger. |
| PAC-2 | MUST | AC-009, AC-011, AC-013 | PASS | Targeted test asserts no legacy identity artifacts or policy heads are created; DOD-006/009/011 regressions preserve canonical mst_session_id flow. |
| PAC-3 | MUST | AC-009, AC-011, AC-013 | PASS | Targeted test fixture combines owner_pid, session_id, and owner_session_id while preserving canonical mst_session_id and rejecting legacy artifact creation. |
| PAC-4 | MUST | AC-009, AC-010, AC-013 | PASS | Targeted stale candidate test hashes history.head, policy mirror head, and owner.json before/after; hashes are unchanged. |
| PAC-5 | MUST | AC-009, AC-010, AC-013 | PASS | Evidence and tests separate lock_path/process-liveness diagnostics from canonical mst_session_id identity; owner_pid is not promoted into identity payload. |
| PAC-6 | MUST | AC-009, AC-011, AC-013 | PASS | Recover and docs contract tests pass and require diagnostic-only wording for owner_pid. |
| PAC-7 | MUST | AC-009, AC-011, AC-013 | PASS | Hook source assertions pass for hooks/lib/pre_tool_use_fast.py and hooks/mst-pre-tool-use.sh: owner_pid/process lock owner metadata is not a session selector. |
| PAC-8 | MUST | AC-009, AC-013 | PASS | Targeted regression asserts .gran-maestro/state/{owner_pid}, .gran-maestro/sessions/{owner_pid}, and legacy session paths do not exist after diagnosis. |
| PAC-9 | MUST | AC-009, AC-010, AC-013 | PASS | Targeted regression preserves canonical history.head, mirror head, and lock owner file while stale diagnostic remains read-only. |
| PAC-10 | MUST | AC-011, AC-012 | PASS | Exact spec-listed DOD-011~DOD-014 wrapper regression commands, available DOD-015~DOD-017 suites, npm test, npx tsc --noEmit, and git diff --check passed. |
| PAC-11 | MUST | AC-013 | PASS | coverage-matrix.json, coverage-matrix.md, evidence-ledger.md, and verification-report.md were refreshed for REQ-821 / PLN-648 / AGI-030 / DOD-008. |

## AC Coverage

| AC | Status | Evidence |
| --- | --- | --- |
| AC-009 | PASS | DOD-008 targeted suite passed: 4 PASS lines covering owner_pid diagnostic-only, no legacy identity paths, read-only stale lock preservation, recover docs, and hook boundary assertions. |
| AC-010 | PASS | tests/test_agile_stale_lock_diagnostics.py passed and preserves live/missing/inconclusive/unknown/stale/scope-mismatch/ledger-mismatch diagnostic categories without artifact mutation. |
| AC-011 | PASS | DOD-006, DOD-007, DOD-009, exact spec-listed DOD-011~DOD-014 wrapper suites, and DOD-015~DOD-017 regressions passed. The DOD-011~DOD-014 wrappers delegate to the current regression files while preserving the approved spec command surface. |
| AC-012 | PASS | npm test, npx tsc --noEmit, and git diff --check passed. |
| AC-013 | PASS | Final evidence artifacts record REQ-821, PLN-648, AGI-030, DOD-008, PAC-1..PAC-11, command evidence, owner_pid diagnostic-only, read-only lock diagnostic, no identity fallback, and no-core provenance. |

## Command Summary

| ID | AC/PAC | Command | Status | Exit | Actual summary |
| --- | --- | --- | --- | --- | --- |
| CMD-001 | AC-009, PAC-1~PAC-9 | `python3 tests/test_dod008_owner_pid_diagnostic_only_contract.py` | PASS | 0 | 4 PASS lines: legacy identity artifact non-creation, read-only stale candidate/head preservation, recover docs diagnostic-only, hook source no owner_pid session selector. |
| CMD-002 | AC-010, PAC-4, PAC-5, PAC-9 | `python3 tests/test_agile_stale_lock_diagnostics.py` | PASS | 0 | stale lock diagnostics regression passed across live/missing/inconclusive/unknown/stale/scope/ledger branches. |
| CMD-003 | AC-011, PAC-6 | `python3 tests/test_dod006_recover_contract_docs.py` | PASS | 0 | recover/resume contract docs passed. |
| CMD-004 | AC-011, PAC-1, PAC-3 | `python3 tests/test_dod007_owner_pid_diagnostic_only.py` | PASS | 0 | owner_pid diagnostic-only regression passed. |
| CMD-005 | AC-011, PAC-2, PAC-3 | `python3 tests/test_dod007_contract_docs.py` | PASS | 0 | canonical identity boundary docs passed. |
| CMD-006 | AC-011, PAC-2, PAC-3 | `python3 tests/test_dod009_contract_docs.py` | PASS | 0 | session identity glossary and canonical state/history/recover terms passed. |
| CMD-007 | AC-011, PAC-10 | `python3 tests/test_dod011_continuation_contract.py` | PASS | 0 | Exact spec-listed DOD-011 wrapper passed and delegates to tests/test_dod011_rehydration_contract.py; 6 PASS lines preserve continuation/rehydration and legacy identity non-fallback coverage. |
| CMD-008 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod011_rehydration_contract.py` | PASS | 0 | 6 PASS lines for resume checkpoint, child dispatch, compaction rehydration, stop hook continuation, stale mismatch, and legacy identity non-fallback. |
| CMD-009 | AC-011, PAC-10 | `python3 tests/test_dod012_auto_true_continuation_contract.py` | PASS | 0 | Exact spec-listed DOD-012 wrapper passed and delegates to tests/test_dod012_auto_continuation_contract.py; 7 PASS lines preserve auto continuation policy and retry circuit scoping coverage. |
| CMD-010 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod012_auto_continuation_contract.py` | PASS | 0 | 7 PASS lines for auto continuation policy, recoverable issue continuation, blocker/security guards, action classification, and retry circuit scoping. |
| CMD-011 | AC-011, PAC-10 | `python3 tests/test_dod013_state_contract_validation.py` | PASS | 0 | Exact spec-listed DOD-013 wrapper passed and delegates to tests/test_dod013_state_contract_validator.py; 6 PASS lines preserve state/history/recover/dispatch validation coverage. |
| CMD-012 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod013_state_contract_validator.py` | PASS | 0 | 6 PASS lines for snapshot/history/recover/dispatch contracts and failure shape/partial write state inconsistency. |
| CMD-013 | AC-011, PAC-10 | `python3 tests/test_dod014_history_snapshot_consistency.py` | PASS | 0 | Exact spec-listed DOD-014 wrapper passed and delegates to tests/test_dod014_ledger_projection_contract.py; 8 PASS lines preserve ledger/snapshot projection consistency coverage. |
| CMD-014 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod014_ledger_projection_contract.py` | PASS | 0 | 8 PASS lines for snapshot projection, ledger head mismatch, replay mismatch, state inconsistency, recursive guard, circuit breaker, hook enforcement, and recover mismatch. |
| CMD-015 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod015_external_control_surface_contract.py` | PASS | 0 | 5 PASS lines including child dispatch, heartbeat policy preservation, context mismatch, core rehydration order, and no Claude Code core modification. |
| CMD-016 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod016_transition_graph_contract.py` | PASS | 0 | 6 PASS lines for transition graph artifact/schema/validator/on_reject/hook boundary/generated view drift. |
| CMD-017 | AC-011, PAC-10 | `PYTHONPATH="$PWD" python3 tests/test_dod017_execution_flow_projection_contract.py` | PASS | 0 | 20 PASS lines for execution-flow projection, provenance, stale read-only behavior, hot path, handoff, graph separation, and no-core. |
| CMD-018 | AC-012, PAC-10 | `npm test` | PASS | 0 | node --test tests/smoke.test.mjs: 1 pass, 0 fail. |
| CMD-019 | AC-012, PAC-10 | `npx tsc --noEmit` | PASS | 0 | No TypeScript errors; exit 0. |
| CMD-020 | AC-012, PAC-10 | `git diff --check` | PASS | 0 | No whitespace errors before evidence refresh; final gate rerun after evidence write is recorded separately. |

## Owner PID Diagnostic-Only Evidence

- `tests/test_dod008_owner_pid_diagnostic_only_contract.py` uses canonical session `MST-AGI-030-20260506T010203456Z-dod008` and legacy/process fields `owner_pid`, `session_id`, and `owner_session_id` in the same stale lock fixture.
- The targeted test asserts no owner_pid-derived or legacy-derived identity paths are created under `.gran-maestro/state/`, `.gran-maestro/sessions/`, or policy `ledger-heads/`.
- The stale candidate test hashes `history.head`, policy mirror head, and `history.lock/owner.json` before and after diagnosis; hashes remain unchanged.
- Recover docs and hook source assertions preserve diagnostic-only wording and forbid owner_pid/process lock owner metadata as a session selector.

## No Identity Fallback / No-Core Provenance

No identity fallback evidence: canonical `mst_session_id` wins over owner_pid, owner_session_id, hook `session_id`, snapshot `sessionId`, and other process/legacy values. No-core evidence: validation changed root evidence artifacts, the DOD-008 targeted regression, and DOD-011~DOD-014 wrapper regression files; no path under `src/claude-code-core/`, `packages/claude-code-core/`, or `vendor/claude-code/` is modified. DOD-015 and DOD-017 no-core tests passed.

## Spec-listed Wrapper Evidence

The exact spec-listed DOD-011~DOD-014 commands are present as wrapper regression files and passed. They delegate to the current equivalent regression suites: `test_dod011_rehydration_contract.py`, `test_dod012_auto_continuation_contract.py`, `test_dod013_state_contract_validator.py`, and `test_dod014_ledger_projection_contract.py`.
