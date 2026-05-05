# REQ-820 Final Coverage Matrix

- Request: REQ-820
- Task: T07 final evidence and regression gate
- Plan: PLN-647
- Objective: AGI-030
- DoD: DOD-017
- Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-820/integration`
- Branch: `gran-maestro/master/AGI-030/REQ-820`
- Head under validation: `03671a7bf3da433f939509842013c964a6d0a149`
- Checked at: `2026-05-05T18:43:55Z`
- Overall status: PASS with active plugin cache diagnostic recorded.

## Source-Of-Truth Policy

The authoritative DOD-017 actual execution-flow source is the verified history ledger for the same `mst_session_id`. Generated `execution-flow.json`, `execution-flow.d2`, dashboard/CLI flow views, compaction handoff summaries, snapshot/cache data, and prompt summaries are derived or auxiliary. They do not authorize transition decisions by themselves.

Transition authority remains the DOD-016 possible-transition graph plus verified ledger/snapshot validation. DOD-017 projections are display and handoff artifacts derived from the verified ledger.

## Execution-Flow Provenance

| Field | Evidence |
| --- | --- |
| Source ledger fixture | `tests/test_dod017_execution_flow_projection_contract.py::_source_head` |
| `ledger_path` | `.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/history.ndjson` |
| `mst_session_id` | `MST-AGI-030-20260506T010203000Z-dod017aa` |
| Last event | `evt-014`, seq `14` |
| Cumulative hash / `history_head` | `f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470` |
| Event count / schema | `14`, ledger schema version `1` |
| Projection kind | `dod017.execution-flow` |
| Projection schema | `1` |
| Projection hash fixture | `a229d846e8ad10eff76e1b24f9e3e5978aa5eb86d94fc3f0babfe8e42b455da8` |
| Generated paths from contract | `.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.json`, `.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.d2` |
| Persistent projection artifacts in integration worktree | None found by `find "$PWD" -path '*/execution-flow.*' -type f` |

The DOD-017 tests prove the projection generator writes `execution-flow.json` and `execution-flow.d2` only after ledger verify/head/hash validation. The generated payload carries source ledger path, `history_head`, source hash, projection schema version, projection hash, and `projection_created_at`.

## PAC Coverage

| PAC | Grade | AC | Status | Evidence |
| --- | --- | --- | --- | --- |
| PAC-1 | MUST | AC-031 | PASS | Same `mst_session_id` ledger replay recognizes `skill.enter`, `skill.step`, `skill.exit`, `skill.recover`, `continue.*`, `guard.*`, `terminal.*`, `context.compacted`, `context.rehydrated`, `action.*`, and `blocker.*`. |
| PAC-2 | MUST | AC-031, AC-034 | PASS | Verified history ledger is source-of-truth; generated JSON/D2/dashboard/CLI/handoff/snapshot/cache/prompt summary are derived or auxiliary. |
| PAC-3 | MUST | AC-031, AC-034 | PASS | Source head evidence records `ledger_path`, `mst_session_id`, last event id/seq, cumulative hash, event count, ledger schema version, and `history_head`. |
| PAC-4 | MUST | AC-031, AC-034 | PASS | Projection JSON/D2 generation passes only after verified source validation and includes generated provenance. |
| PAC-5 | MUST | AC-031, AC-034 | PASS | Stale projection source is fail-closed: read-only/regenerate-required and denied for validator, next-action, auto-write, and handoff consumption. |
| PAC-6 | MUST | AC-031, AC-036 | PASS | DOD-016 possible graph and DOD-017 actual execution-flow remain separate; transition authority is DOD-016 graph plus verified ledger/snapshot validation. |
| PAC-7 | MUST | AC-031, AC-034 | PASS | Dashboard, CLI, and D2 views expose provenance, coverage, stale, drift, and regenerate status as generated views. |
| PAC-8 | MUST | AC-031, AC-034 | PASS | Compaction handoff includes current node, last transition, next action, blocker status, `history_head`, and flow paths; rehydration consumes it before LLM prompt summary. |
| PAC-9 | MUST | AC-031 | PASS | `context.compacted` and `context.rehydrated` evidence remains in the same session ledger; stale handoff blocks auto write and next action. |
| PAC-10 | MUST | AC-031 | PASS | Hook hot path uses cursor/cache/minimal head evidence and avoids full replay, full projection, D2 rendering, and dashboard rendering. |
| PAC-11 | MUST | AC-031 | PASS | Cursor/cache miss or stale hot-path state routes to inspect-only/state inconsistency without full replay. |
| PAC-12 | MUST | AC-031 | PASS | Full DOD-017 targeted suite passed with 20 tests, including no-hot-path-full-projection. |
| PAC-13 | MUST | AC-031, AC-036 | PASS | Graph/projection separation tests prove projection cannot authorize DOD-016-forbidden transitions. |
| PAC-14 | MUST | AC-032, AC-033 | PASS | DOD-011 through DOD-016 regressions, `npm test`, `npx tsc --noEmit`, and `git diff --check` passed. |
| PAC-15 | MUST | AC-035 | PASS | No Claude Code core source path is changed. |
| PAC-16 | SHOULD | AC-036 | PASS | DOD-016 graph identity remains canonical: `mst-transition-graph`, version `2026-05-05.dod016-contract`, hash `8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79`. |
| PAC-17 | MUST | AC-034, AC-035, AC-036 | PASS | These evidence artifacts record PAC/AC coverage, commands, source ledger head/hash, generated provenance, stale behavior, handoff, hot path, and no-core provenance. |

## AC Coverage

| AC | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| AC-031 | Full DOD-017 targeted regression passes. | PASS | `tests/test_dod017_execution_flow_projection_contract.py` exited 0 with 20 PASS lines. |
| AC-032 | DOD-011 through DOD-016 regressions pass. | PASS | Six prior DoD regression suites exited 0. |
| AC-033 | `npm test`, `npx tsc --noEmit`, and `git diff --check` pass. | PASS | Project smoke, TypeScript, and whitespace gates passed. |
| AC-034 | Evidence artifacts cover all PAC/AC items. | PASS | `coverage-matrix.json`, this matrix, `evidence-ledger.md`, and `verification-report.md` cover PAC-1 through PAC-17 and AC-031 through AC-036. |
| AC-035 | Claude Code core remains untouched. | PASS | No changed path under `src/claude-code-core/`, `packages/claude-code-core/`, or `vendor/claude-code/`; DOD-017 no-core test passed. |
| AC-036 | DOD-016 graph identity impact remains explicit. | PASS | DOD-016 graph artifact/view/hash remain canonical possible-transition graph evidence after DOD-017. |

## Command Summary

| Command | Result |
| --- | --- |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod017_execution_flow_projection_contract.py"` | PASS, 20 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod011_rehydration_contract.py"` | PASS, 6 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod012_auto_continuation_contract.py"` | PASS, 7 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod013_state_contract_validator.py"` | PASS, 6 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod014_ledger_projection_contract.py"` | PASS, 7 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod015_external_control_surface_contract.py"` | PASS, 10 tests |
| `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod016_transition_graph_contract.py"` | PASS, 6 tests |
| `npm test` | PASS, 1 smoke test |
| `npx tsc --noEmit` | PASS |
| `git diff --check` | PASS |
| `python3 -m json.tool "$PWD/coverage-matrix.json"` | PASS |
| `grep -R "PAC-17\|DOD-017\|history_head\|no-hot-path-full-projection" ...` | PASS |
| `git diff --name-only gran-maestro/master/AGI-030/REQ-820...HEAD` | PASS, no code/core paths before T07 evidence commit |
| `find "$PWD" -path '*/execution-flow.*' -type f` | PASS, no persistent projection artifacts in worktree |

## DOD-016 Graph Identity Impact

DOD-016 remains the canonical possible-transition graph source. DOD-017 actual execution-flow projection is separate and cannot authorize transitions. The canonical graph source is `templates/state-machine/mst-transition-graph.json`; generated graph view is `dashboard/mst-transition-graph.json`; graph id/version/hash are:

```text
graph_id=mst-transition-graph
graph_version=2026-05-05.dod016-contract
graph_hash=8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79
```

## No-Core Provenance

T07 evidence changes are limited to root evidence files:

```text
coverage-matrix.json
coverage-matrix.md
evidence-ledger.md
verification-report.md
```

Forbidden core prefixes are `src/claude-code-core/`, `packages/claude-code-core/`, and `vendor/claude-code/`. No changed path uses those prefixes.

## Diagnostic-Only Cache Caveat

`hooks/lib/pre_tool_use_fast.py` source sha256 is `df25c404c8068e889f988568a2585dc16b197df21ad1da8dcd99f4e56d3d8984`. The project copy `.claude/hooks/lib/pre_tool_use_fast.py` is missing. Active cache copies under `~/.claude/plugins/cache/gran-maestro/mst/0.59.6` and `0.59.8` have sha256 `79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52`, so synchronization is not claimed.
