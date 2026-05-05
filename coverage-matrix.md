# REQ-819 Final Coverage Matrix

- Request: REQ-819
- Task: T06 final evidence and regression gate
- Plan: PLN-646
- Objective: AGI-030 / DOD-016
- Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-819/integration`
- Branch: `gran-maestro/master/AGI-030/REQ-819`
- Head: `3e19e8b6c79b0d1a202b9a00a3b902d137d3bb6b`
- Checked at: 2026-05-05T16:44:19Z
- Overall status: Final integration pass with active cache diagnostic recorded for `hooks/lib/pre_tool_use_fast.py`

## Graph Identity

| Field | Value |
| --- | --- |
| Source graph path | `templates/state-machine/mst-transition-graph.json` |
| graph_id | `mst-transition-graph` |
| graph_version | `2026-05-05.dod016-contract` |
| graph_hash | `8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79` |
| Generated view | `dashboard/mst-transition-graph.json` |
| Generated view identity | source graph id/version/hash match canonical graph; 6 states and 7 transition IDs covered |
| Consumer sync | `transition_validator`, `pre_tool_use_fast_hook`, and `generated_graph_view` matched canonical identity |
| Mismatch guard | deliberate `graph_hash=000...000` consumer failed closed with `graph_consumer_hash_mismatch` |

## PAC Coverage

| PAC | Grade | AC | Evidence | Status |
| --- | --- | --- | --- | --- |
| PAC-1 | MUST | AC-001, AC-007, AC-016, AC-020, AC-030, AC-036 | Canonical graph defines schema, states, transitions, guard/evidence/on_reject, `auto_allowed`, and `write_allowed`. | PASS |
| PAC-2 | MUST | AC-002, AC-008, AC-009, AC-011, AC-012, AC-015, AC-022, AC-026, AC-030, AC-036 | DOD-016 regression covers fail-closed schema, invariant, hash skew, generated view drift, and missing/corrupt graph cases. | PASS |
| PAC-3 | MUST | AC-003, AC-013, AC-014, AC-015, AC-016, AC-018, AC-019, AC-020, AC-030, AC-036 | Transition validator and hook boundaries use explicit transition envelopes and structured accept/reject results. | PASS |
| PAC-4 | MUST | AC-004, AC-017, AC-030, AC-036 | Repeated on_reject loop is bounded and does not convert to completed success. | PASS |
| PAC-5 | MUST | AC-005, AC-018, AC-019, AC-020, AC-030, AC-036 | Stop/PreToolUse boundary attempts produce graph-based on_reject continuation blocks. | PASS |
| PAC-6 | MUST | AC-005, AC-021, AC-030, AC-036 | Normal hook pass avoids full state prompt injection, full graph validation, D2 rendering, and full ledger replay. | PASS |
| PAC-7 | MUST | AC-010, AC-011, AC-014, AC-015, AC-020, AC-022, AC-027, AC-034, AC-036 | Graph consumer identity sync passes for matching consumers and fails closed for a deliberate hash mismatch. | PASS |
| PAC-8 | MUST | AC-006, AC-009, AC-024, AC-025, AC-026, AC-030, AC-036 | Generated dashboard view is derived from canonical graph and records source path/version/hash and coverage. | PASS |
| PAC-9 | MUST | AC-001 through AC-022, AC-024 through AC-030 | DOD-016 targeted regression passed graph schema, transition validation, hook on_reject, reject-loop, graph skew, generated view drift, and no-DOD017 checks. | PASS |
| PAC-10 | MUST | AC-029, AC-031, AC-032 | DOD-011 through DOD-015, `npm test`, `npx tsc --noEmit`, and `git diff --check` passed. | PASS |
| PAC-11 | MUST | AC-006, AC-028, AC-035, AC-036 | No `execution-flow.*` files found; DOD-016 changed files introduce transition graph artifacts only. | PASS |
| PAC-12 | SHOULD | AC-023, AC-037 | DOD-015 external control surface behavior remains green after graph integration. | PASS |
| PAC-13 | MUST | AC-033, AC-034, AC-035, AC-036 | Evidence artifacts record PAC/AC coverage, commands, graph sync, hook sync diagnostics, no-core, and DOD-017 no-go scope. | PASS |

## AC Coverage

| AC | Task | PAC | Evidence | Status |
| --- | --- | --- | --- | --- |
| AC-001 | T01 | PAC-1, PAC-9 | `test_graph_artifact_defines_machine_readable_contract` PASS. | PASS |
| AC-002 | T01 | PAC-2, PAC-9 | `test_graph_schema_invariants_fail_closed` PASS. | PASS |
| AC-003 | T01 | PAC-3, PAC-9 | `test_transition_validator_requires_explicit_envelope` PASS. | PASS |
| AC-004 | T01 | PAC-4, PAC-9 | `test_repeated_on_reject_loop_is_bounded` PASS. | PASS |
| AC-005 | T01 | PAC-5, PAC-6, PAC-9 | `test_hook_boundary_uses_graph_on_reject_continuation` PASS. | PASS |
| AC-006 | T01 | PAC-8, PAC-9, PAC-11 | Generated graph view drift and no-DOD017 fixture PASS. | PASS |
| AC-007 | T02 | PAC-1, PAC-9 | Canonical graph artifact fields present in JSON. | PASS |
| AC-008 | T02 | PAC-2, PAC-9 | Schema validator reports fail-closed diagnostics. | PASS |
| AC-009 | T02 | PAC-2, PAC-8, PAC-9 | Semantic invariants cover reachability, references, and generated view coverage. | PASS |
| AC-010 | T02 | PAC-7, PAC-9 | Stable graph identity recorded across consumers. | PASS |
| AC-011 | T02 | PAC-2, PAC-7, PAC-9 | Missing/corrupt/hash-skew graph fails closed. | PASS |
| AC-012 | T02 | PAC-2, PAC-9 | Legacy unknown transitions are not silently migrated. | PASS |
| AC-013 | T03 | PAC-3, PAC-9 | Explicit transition envelope validation covered. | PASS |
| AC-014 | T03 | PAC-3, PAC-7, PAC-9 | Accepted transition result includes graph identity and guard/evidence result. | PASS |
| AC-015 | T03 | PAC-2, PAC-3, PAC-7, PAC-9 | Rejected transition result includes structured diagnostic and on_reject. | PASS |
| AC-016 | T03 | PAC-1, PAC-3, PAC-9 | `auto_allowed` and `write_allowed` semantics covered. | PASS |
| AC-017 | T03 | PAC-4, PAC-9 | Reject-loop idempotency and terminal blocker covered. | PASS |
| AC-018 | T04 | PAC-3, PAC-5, PAC-9 | Stop boundary terminal attempts map to graph transitions. | PASS |
| AC-019 | T04 | PAC-3, PAC-5, PAC-9 | PreToolUse user-wait/self-paced stop attempts covered. | PASS |
| AC-020 | T04 | PAC-1, PAC-3, PAC-5, PAC-7, PAC-9 | Hook reject uses graph on_reject continuation block. | PASS |
| AC-021 | T04 | PAC-6, PAC-9 | Hook hot path excludes full validation/render/replay. | PASS |
| AC-022 | T04 | PAC-2, PAC-7, PAC-9 | Hook graph hash or snapshot skew fails closed. | PASS |
| AC-023 | T04 | PAC-12 | DOD-015 suite remains green after graph integration. | PASS |
| AC-024 | T05 | PAC-8, PAC-9 | Generated graph view contains source provenance. | PASS |
| AC-025 | T05 | PAC-8, PAC-9 | Dashboard graph view is derived from canonical graph. | PASS |
| AC-026 | T05 | PAC-2, PAC-8, PAC-9 | Generated graph view drift is detected. | PASS |
| AC-027 | T05 | PAC-7, PAC-9 | Graph consumers report same hash or fail closed. | PASS |
| AC-028 | T05 | PAC-9, PAC-11 | Required `find` scan returned no `execution-flow.*` artifacts. | PASS |
| AC-029 | T05 | PAC-9, PAC-10 | No T06 frontend/Deno files changed; `npm test` and `npx tsc --noEmit` passed. | PASS |
| AC-030 | T06 | PAC-1, PAC-2, PAC-3, PAC-4, PAC-5, PAC-6, PAC-8, PAC-9 | DOD-016 targeted regression passed. | PASS |
| AC-031 | T06 | PAC-10 | DOD-011 through DOD-015 regression commands passed. | PASS |
| AC-032 | T06 | PAC-10 | `npm test`, `npx tsc --noEmit`, and `git diff --check` passed. | PASS |
| AC-033 | T06 | PAC-13 | Required hook sync tests passed; `pre_tool_use_fast.py` project copy missing and active cache mismatch diagnostics recorded. | PASS_WITH_DIAGNOSTIC |
| AC-034 | T06 | PAC-7, PAC-13 | Graph hash/version evidence and consumer sync recorded. | PASS |
| AC-035 | T06 | PAC-11, PAC-13 | Changed-file and `execution-flow.*` scans prove no core and no DOD-017 artifacts. | PASS |
| AC-036 | T06 | PAC-1 through PAC-8, PAC-11, PAC-13 | PAC-1 through PAC-13 and AC-001 through AC-037 are represented. | PASS |
| AC-037 | T06 | PAC-12 | DOD-015 impact check passed; auto=true continuation, same-session ledger, and no-core provenance remain observable. | PASS |

## Command Results

| Command | Result |
| --- | --- |
| DOD-016 targeted regression | PASS, 6 tests |
| DOD-011 regression | PASS, 6 tests |
| DOD-012 regression | PASS, 7 tests |
| DOD-013 regression | PASS, 6 tests |
| DOD-014 regression | PASS, 7 tests |
| DOD-015 regression | Initial fail on dashboard graph allowlist, then PASS after narrow test fix |
| `npm test` | PASS, 1 smoke test |
| `npx tsc --noEmit` | PASS |
| `git diff --check` | PASS |
| `tests/hooks/test_hook_copy_sync.sh` | PASS |
| `tests/test_sync_plugin_cache.py` | PASS, 12 subtests |
| `find ... -path '*/execution-flow.*' -type f` | PASS, no output |
| Graph consumer identity demonstration | PASS, matching consumers accepted and deliberate mismatch failed closed |

## Hook Sync

Shell hook source/project copies are synchronized for `mst-pre-tool-use.sh`, `mst-stop-hook.sh`, `mst-session-init.sh`, and `mst-auto-chain-context.sh`.

`hooks/lib/pre_tool_use_fast.py` is explicitly diagnostic-only for project/cache copy status:

- Source sha256: `624693b838912f88ef6fd231d6081b124d7f158f7a7b1fd12ce619352ffd8af4`
- Project copy diagnostic: `.claude/hooks/lib/pre_tool_use_fast.py` does not exist.
- Active cache diagnostic: `~/.claude/plugins/cache/gran-maestro/mst/0.59.6/hooks/lib/pre_tool_use_fast.py` and `0.59.8/hooks/lib/pre_tool_use_fast.py` exist but have sha256 `79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52`, which does not match source.

## No-Core And No-DOD017

`git diff --name-only master...HEAD` returned the expected DOD-016 provenance:

```text
dashboard/mst-transition-graph.json
hooks/lib/pre_tool_use_fast.py
scripts/mst_cmds/transition_graph.py
templates/state-machine/mst-transition-graph.json
tests/test_dod015_external_control_surface_contract.py
tests/test_dod016_transition_graph_contract.py
```

No Claude Code core source path is present. The required `find` scan returned no `execution-flow.*` files.
