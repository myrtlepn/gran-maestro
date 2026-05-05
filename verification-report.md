# REQ-820 Final Verification Report

Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-820/integration`
Branch: `gran-maestro/master/AGI-030/REQ-820`
Head under validation: `03671a7bf3da433f939509842013c964a6d0a149`
Date: `2026-05-05T18:43:55Z`

## Verdict

REQ-820 / PLN-647 / AGI-030 DOD-017 final evidence is PASS with one diagnostic-only caveat: active plugin cache copies of `hooks/lib/pre_tool_use_fast.py` remain mismatched and the project copy path is missing. Synchronization is not claimed.

Primary gates passed:

- DOD-017 targeted regression: PASS, 20 tests.
- DOD-011 through DOD-016 regressions: PASS.
- `npm test`: PASS, 1 smoke test.
- `npx tsc --noEmit`: PASS.
- `git diff --check`: PASS.
- Evidence JSON and sentinel grep gates: PASS.
- No Claude Code core source modification: PASS.

## DOD-017 Scope And DOD-016 Boundary

DOD-017 records actual per-session execution-flow from the verified history ledger. The projection, D2 view, dashboard/CLI views, and compaction handoff summary are generated or derived artifacts.

DOD-016 remains the canonical possible-transition graph and the transition authority. DOD-017 projection evidence cannot authorize a transition that the DOD-016 graph/validator rejects.

## Changed Files Provenance

Final integration evidence intentionally replaces stale evidence at the repository root:

```text
coverage-matrix.json
coverage-matrix.md
evidence-ledger.md
verification-report.md
```

No Claude Code core path is changed:

```text
src/claude-code-core/
packages/claude-code-core/
vendor/claude-code/
```

`git diff --name-only master...HEAD` on the integration branch lists the expected DOD-017 implementation, dashboard flow-view, hook, test, and evidence surfaces while excluding Claude Code core prefixes. The final evidence changes are the four evidence artifacts above plus the narrow DOD-015 guard allowlist alignment commit for DOD-017 flow-view surfaces.

## Validation Summary

| Area | Command | Result |
| --- | --- | --- |
| DOD-017 targeted regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod017_execution_flow_projection_contract.py"` | PASS, 20 tests |
| DOD-011 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod011_rehydration_contract.py"` | PASS, 6 tests |
| DOD-012 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod012_auto_continuation_contract.py"` | PASS, 7 tests |
| DOD-013 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod013_state_contract_validator.py"` | PASS, 6 tests |
| DOD-014 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod014_ledger_projection_contract.py"` | PASS, 7 tests |
| DOD-015 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod015_external_control_surface_contract.py"` | PASS, 10 tests |
| DOD-016 regression | `PYTHONPATH="$PWD" python3 "$PWD/tests/test_dod016_transition_graph_contract.py"` | PASS, 6 tests |
| Project smoke | `npm test` | PASS, 1 smoke test |
| TypeScript | `npx tsc --noEmit` | PASS |
| Whitespace | `git diff --check` | PASS |
| JSON evidence | `python3 -m json.tool "$PWD/coverage-matrix.json"` | PASS |
| Evidence sentinel grep | `grep -R "PAC-17\|DOD-017\|history_head\|no-hot-path-full-projection" ...` | PASS |
| Changed-file provenance | `git diff --name-only gran-maestro/master/AGI-030/REQ-820...HEAD` | PASS, no code/core paths before evidence commit |
| Generated artifact scan | `find "$PWD" -path '*/execution-flow.*' -type f` | PASS, no persistent artifacts |

## Source Ledger Evidence

DOD-017 source ledger head/hash fixture:

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

The DOD-017 suite verifies this head before replay, projection generation, projection consumption, handoff generation, and handoff consumption.

## Generated Projection Evidence

Generated contract paths:

```text
.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.json
.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.d2
```

Generated provenance includes:

```text
projection_kind=dod017.execution-flow
projection_schema_version=1
projection_hash=a229d846e8ad10eff76e1b24f9e3e5978aa5eb86d94fc3f0babfe8e42b455da8
source_kind=verified_history_ledger
source_hash=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
history_head=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
```

The integration worktree has no persistent `execution-flow.*` files; the generated paths are contract/test-session paths.

## Handoff Evidence

The compaction handoff includes:

```text
current_node=terminal.completed:14
last_transition=terminal.completed
next_action={"skill":"mst:approve","source_id":"REQ-820"}
history_head=f341e57a5d808c7c437102c2c68d62cec3257bf5011a2e155edf2c93dc42c470
flow_view.execution_flow_json=.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.json
flow_view.execution_flow_d2=.gran-maestro/sessions/MST-AGI-030-20260506T010203000Z-dod017aa/execution-flow.d2
```

`context.compacted` and `context.rehydrated` evidence remain in the same `mst_session_id` ledger. Rehydration consumes verified execution-flow handoff before the LLM prompt summary.

## Hot-Path Evidence

The hook hot path is covered by `no-hot-path-full-projection` evidence. It uses cursor/cache/minimal head evidence and avoids:

```text
hot_path_full_ledger_replay=false
hot_path_execution_flow_projection=false
hot_path_d2_rendering=false
hot_path_dashboard_rendering=false
```

If cursor/cache state is stale or missing, the route is inspect-only/state inconsistency, not full replay recovery.

## Stale Behavior

Stale projection or handoff source evidence fails closed:

- stale projection is read-only and regenerate-required;
- stale projection cannot drive validator judgement, next action, auto-write, or handoff consumption;
- stale handoff blocks auto-write and next-action execution;
- stale route is `guard.inspect_only_verification`.

## DOD-016 Graph Identity Impact

Canonical graph identity:

```text
source_graph_path=templates/state-machine/mst-transition-graph.json
generated_graph_view=dashboard/mst-transition-graph.json
graph_id=mst-transition-graph
graph_version=2026-05-05.dod016-contract
graph_hash=8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79
```

The DOD-016 graph/view remains the possible-transition source after DOD-017. DOD-017 actual execution-flow projection is separate and display/derived only.

## No-Core Provenance

DOD-017 and DOD-015 no-core tests passed. Final evidence changes are limited to root evidence artifacts plus a narrow DOD-015 allowlist alignment for DOD-017 flow-view surfaces. No path under `src/claude-code-core/`, `packages/claude-code-core/`, or `vendor/claude-code/` is modified.

## Remaining Risks / Diagnostics

Current diagnostic-only hook cache truth:

```text
hooks/lib/pre_tool_use_fast.py source_sha256=df25c404c8068e889f988568a2585dc16b197df21ad1da8dcd99f4e56d3d8984
.claude/hooks/lib/pre_tool_use_fast.py MISSING
~/.claude/plugins/cache/gran-maestro/mst/0.59.6/hooks/lib/pre_tool_use_fast.py sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52 MISMATCH
~/.claude/plugins/cache/gran-maestro/mst/0.59.8/hooks/lib/pre_tool_use_fast.py sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52 MISMATCH
```

No unresolved validation blocker remains for T07 evidence.
