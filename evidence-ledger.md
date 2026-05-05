# REQ-820 Final Evidence Ledger

- Request: REQ-820
- Task: T07 final evidence and regression gate
- Plan: PLN-647
- Objective: AGI-030
- DoD: DOD-017
- Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-820/integration`
- Branch: `gran-maestro/master/AGI-030/REQ-820`
- Head under validation: `03671a7bf3da433f939509842013c964a6d0a149`
- Checked at: `2026-05-05T18:43:55Z`

## Command Evidence

| ID | AC/PAC | Command | Expected | Actual summary | Exit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| CMD-001 | AC-031, PAC-1~PAC-13 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod017_execution_flow_projection_contract.py"` | DOD-017 targeted regression passes. | 20 PASS lines: replay/source head, derived-only policy, projection JSON/D2/hash, stale projection, dashboard/CLI, graph separation, hot path, handoff, no-core. | 0 | PASS |
| CMD-002 | AC-032, PAC-14 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod011_rehydration_contract.py"` | DOD-011 remains green. | 6 PASS lines. | 0 | PASS |
| CMD-003 | AC-032, PAC-14 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod012_auto_continuation_contract.py"` | DOD-012 remains green. | 7 PASS lines. | 0 | PASS |
| CMD-004 | AC-032, PAC-14 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod013_state_contract_validator.py"` | DOD-013 remains green. | 6 PASS lines. | 0 | PASS |
| CMD-005 | AC-032, PAC-14 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod014_ledger_projection_contract.py"` | DOD-014 remains green. | 7 PASS lines. | 0 | PASS |
| CMD-006 | AC-032, PAC-14 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod015_external_control_surface_contract.py"` | DOD-015 remains green. | 10 PASS lines. | 0 | PASS |
| CMD-007 | AC-032, AC-036, PAC-14, PAC-16 | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod016_transition_graph_contract.py"` | DOD-016 remains green. | 6 PASS lines including generated graph view drift and DOD-016 graph identity impact coverage. | 0 | PASS |
| CMD-008 | AC-033, PAC-14 | `npm test` | Project smoke tests pass. | `node --test tests/smoke.test.mjs`: 1 test, 0 failures. | 0 | PASS |
| CMD-009 | AC-033, PAC-14 | `npx tsc --noEmit` | TypeScript check passes. | No output. | 0 | PASS |
| CMD-010 | AC-033, PAC-14 | `git diff --check` | No whitespace errors. | No output. | 0 | PASS |
| CMD-011 | AC-034, PAC-17 | `python3 -m json.tool "$PWD/coverage-matrix.json"` | Matrix JSON parses. | JSON parsed successfully. | 0 | PASS |
| CMD-012 | AC-034, PAC-17 | `grep -R "PAC-17\|DOD-017\|history_head\|no-hot-path-full-projection" "$PWD/coverage-matrix.md" "$PWD/evidence-ledger.md" "$PWD/verification-report.md"` | Required DOD-017 evidence sentinel strings exist. | Sentinel strings present. | 0 | PASS |
| CMD-013 | AC-035, PAC-15 | `git diff --name-only gran-maestro/master/AGI-030/REQ-820...HEAD` | Changed-file provenance excludes Claude Code core. | No output before evidence commit because T07 starts at integration head; evidence file changes are recorded separately below. | 0 | PASS |
| CMD-014 | AC-034, PAC-4, PAC-7 | `find "$PWD" -path '*/execution-flow.*' -type f` | Persistent execution-flow artifacts are intentional only. | No persistent `execution-flow.*` artifacts found in the T07 worktree. | 0 | PASS |
| CMD-015 | AC-035, diagnostic | Hook cache diagnostic Python snippet | Record current `hooks/lib/pre_tool_use_fast.py` project/cache truth. | Project copy missing; cache copies at `0.59.6` and `0.59.8` mismatch source sha256. | 0 | DIAGNOSTIC_RECORDED |

## Source Ledger Head/Hash Evidence

DOD-017 source ledger evidence is validated by `tests/test_dod017_execution_flow_projection_contract.py` and represented by the test fixture source head:

```text
ledger_path=.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/history.ndjson
mst_session_id=MST-AGI-030-20260506T010203000Z-dod017aa
last_event_id=evt-014
last_event_seq=14
cumulative_hash=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
event_count=14
ledger_schema_version=1
history_head=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
```

`test_source_ledger_head_requires_minimum_evidence`, `test_ledger_replay_accepts_required_event_families`, and `test_projection_generation_requires_verified_ledger_source` prove that projection generation and consumption revalidate this head/hash evidence and fail closed on missing or mismatched source evidence.

## Generated Artifact Provenance Evidence

Generated projection contract paths:

```text
.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.json
.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.d2
```

Generated projection provenance:

```text
projection_kind=dod017.execution-flow
projection_schema_version=1
projection_hash=a229d846e8ad10eff76e1b24f9e3e5978aa5eb86d94fc3f0babfe8e42b455da8
source_kind=verified_history_ledger
source_hash=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
history_head=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
```

`find "$PWD" -path '*/execution-flow.*' -type f` returned no persistent projection files in the T07 worktree. The contract-generated paths above are produced in test temp/session contexts only.

## Stale Fail-Closed Evidence

- `test_stale_projection_rejects_decision_consumption`: stale `history_head` or source hash rejects validator judgement, next-action decision, auto-write, and handoff consumption.
- `test_cli_flow_view_marks_stale_projection_read_only`: stale projections remain display/read-only with regenerate-required status.
- `test_stale_handoff_blocks_auto_write_and_next_action`: stale handoff returns `stale_handoff`, `auto_write_allowed=false`, `next_action_execution_allowed=false`, and `guard.inspect_only_verification`.
- `test_hook_cache_miss_routes_to_inspect_only_without_replay`: hook cursor/cache miss or stale state routes to inspect-only without full replay.

## Compaction Handoff Evidence

Compaction handoff contains the required cursor and provenance fields:

```text
current_node=terminal.completed:14
last_transition=terminal.completed
next_action={"skill":"mst:approve","source_id":"REQ-820"}
history_head=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
flow_view.execution_flow_json=.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.json
flow_view.execution_flow_d2=.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.d2
```

`test_rehydration_context_prefers_verified_handoff_over_llm_summary` proves rehydration order is `core_rehydration`, `execution_flow_handoff`, then `prompt_summary`; prompt summary is diagnostic only. `test_context_compaction_and_rehydration_events_share_session_ledger` proves `context.compacted` and `context.rehydrated` evidence stays in the same `mst_session_id` ledger.

## Hook Hot-Path No-Full-Projection Evidence

DOD-017 hook evidence includes the sentinel `no-hot-path-full-projection`.

`test_hook_hot_path_never_full_replays_or_renders` and `test_hook_hot_path_uses_cursor_cache_for_current_flow_state` prove:

```text
hot_path_full_ledger_replay=false
hot_path_execution_flow_projection=false
hot_path_d2_rendering=false
hot_path_dashboard_rendering=false
```

The hot path uses fresh cursor/cache and minimal current head evidence to recover `current_node`, `last_transition`, and `next_action`.

## Graph/Projection Separation Evidence

DOD-016 graph identity remains:

```text
source_graph_path=templates/state-machine/mst-transition-graph.json
generated_graph_view=dashboard/mst-transition-graph.json
graph_id=mst-transition-graph
graph_version=2026-05-05.dod016-contract
graph_hash=8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79
```

`test_graph_and_execution_flow_views_are_separate_artifacts` labels the DOD-016 artifact as possible-transition graph and DOD-017 as actual execution-flow. `test_projection_never_authorizes_forbidden_graph_transition` proves projection evidence cannot override graph rejection.

## No-Core Evidence

T07 evidence artifacts changed:

```text
coverage-matrix.json
coverage-matrix.md
evidence-ledger.md
verification-report.md
```

Forbidden core prefixes:

```text
src/claude-code-core/
packages/claude-code-core/
vendor/claude-code/
```

No changed path uses those prefixes. DOD-017 `test_compaction_handoff_does_not_modify_claude_code_core` and DOD-015 `test_no_claude_code_core_source_modification` passed.

## Diagnostic-Only Hook Cache Evidence

Current check for `hooks/lib/pre_tool_use_fast.py`:

```text
source_sha256=df25c404c8068e889f988568a2585dc16b197df21ad1da8dcd99f4e56d3d8984
project_copy=.claude/hooks/lib/pre_tool_use_fast.py MISSING
/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.59.6/hooks/lib/pre_tool_use_fast.py sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52 MISMATCH
/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.59.8/hooks/lib/pre_tool_use_fast.py sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52 MISMATCH
```

This is recorded as a diagnostic only. Synchronization is not claimed.

## PAC Evidence Summary

| PAC | Status | Evidence |
| --- | --- | --- |
| PAC-1 | PASS | Same-session ledger replay records all required actual execution-flow event families. |
| PAC-2 | PASS | Verified history ledger is authoritative; generated projections/views/handoff/snapshot/cache/prompt summary are derived or auxiliary. |
| PAC-3 | PASS | Source head/hash evidence includes required fields and `history_head`. |
| PAC-4 | PASS | Projection JSON/D2 generation requires verified source and records provenance. |
| PAC-5 | PASS | Stale projection/handoff fails closed and is read-only or inspect-only. |
| PAC-6 | PASS | DOD-016 possible graph and DOD-017 actual projection remain separate. |
| PAC-7 | PASS | Dashboard/CLI/D2 generated views expose provenance and stale/drift/regenerate status. |
| PAC-8 | PASS | Compaction handoff carries cursor/provenance and is consumed before prompt summary. |
| PAC-9 | PASS | Compaction/rehydration events and handoff evidence remain in the same session ledger. |
| PAC-10 | PASS | Hook hot path avoids full replay/projection/D2/dashboard rendering. |
| PAC-11 | PASS | Hot-path cache miss/stale state routes inspect-only without replay. |
| PAC-12 | PASS | Full DOD-017 targeted suite passed. |
| PAC-13 | PASS | Graph/projection separation tests preserve DOD-016 authority. |
| PAC-14 | PASS | DOD-011 through DOD-016 plus npm/tsc/diff gates passed. |
| PAC-15 | PASS | No Claude Code core source modification. |
| PAC-16 | PASS | DOD-016 graph identity remains canonical possible-transition graph source. |
| PAC-17 | PASS | Final evidence records PAC/AC coverage, commands, source head/hash, generated provenance, stale behavior, handoff, hot path, and no-core. |

## AC-031 Through AC-036

| AC | Result | Evidence |
| --- | --- | --- |
| AC-031 | PASS | DOD-017 targeted regression passed. |
| AC-032 | PASS | DOD-011 through DOD-016 regressions passed. |
| AC-033 | PASS | `npm test`, `npx tsc --noEmit`, and `git diff --check` passed. |
| AC-034 | PASS | Evidence artifacts cover all PAC/AC items and required provenance categories. |
| AC-035 | PASS | No Claude Code core source modification. |
| AC-036 | PASS | DOD-016 graph identity impact remains explicit and canonical. |
