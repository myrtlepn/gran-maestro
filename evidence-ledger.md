# REQ-819 Final Evidence Ledger

- Request: REQ-819
- Task: T06 final evidence and regression gate
- Plan: PLN-646
- Objective: AGI-030 / DOD-016
- Worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-819/integration`
- Branch: `gran-maestro/master/AGI-030/REQ-819`
- Head: `3e19e8b6c79b0d1a202b9a00a3b902d137d3bb6b`
- Checked at: 2026-05-05T16:44:19Z

## Command Evidence

| ID | AC/PAC | Command | Expected | Actual summary | Exit | Status |
| --- | --- | --- | --- | --- | --- | --- |
| CMD-001 | AC-030, PAC-1~PAC-9, PAC-11 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod016_transition_graph_contract.py"` | DOD-016 graph contract suite passes. | 6 PASS lines: graph artifact, schema fail-closed, transition envelope, reject-loop, hook on_reject, generated view/no-DOD017. | 0 | PASS |
| CMD-002 | AC-031, PAC-10 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod011_rehydration_contract.py"` | DOD-011 remains green. | 6 PASS lines. | 0 | PASS |
| CMD-003 | AC-031, PAC-10 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod012_auto_continuation_contract.py"` | DOD-012 remains green. | 7 PASS lines. | 0 | PASS |
| CMD-004 | AC-031, PAC-10 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod013_state_contract_validator.py"` | DOD-013 remains green. | 6 PASS lines. | 0 | PASS |
| CMD-005 | AC-031, PAC-10 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod014_ledger_projection_contract.py"` | DOD-014 remains green. | 7 PASS lines. | 0 | PASS |
| CMD-006 | AC-031, AC-037, PAC-10, PAC-12 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod015_external_control_surface_contract.py"` | DOD-015 remains green. | Initial run failed only in `test_no_claude_code_core_source_modification`: stale DOD-015 allowlist rejected expected `dashboard/mst-transition-graph.json`. | 1 | FAIL_OBSERVED |
| CMD-007 | AC-031, AC-037, PAC-10, PAC-12 | `PYTHONPATH="$WT" python3 "$WT/tests/test_dod015_external_control_surface_contract.py"` | DOD-015 remains green after integration evidence fix. | 10 PASS lines after test allows exactly `dashboard/mst-transition-graph.json` as generated DOD-016 view. | 0 | PASS |
| CMD-008 | AC-032, PAC-10 | `npm test` | Project smoke tests pass. | `node --test tests/smoke.test.mjs`: 1 test, 0 failures. | 0 | PASS |
| CMD-009 | AC-032, PAC-10 | `npx tsc --noEmit` | TypeScript check passes. | No stdout/stderr; exit 0. | 0 | PASS |
| CMD-010 | AC-032, PAC-10 | `git diff --check` | No whitespace errors. | No output; exit 0. | 0 | PASS |
| CMD-011 | AC-033, PAC-13 | `bash "$WT/tests/hooks/test_hook_copy_sync.sh"` | Hook source/project/cache sync test passes. | `PASS: DOD-002 hook source, project copy, and plugin cache copies are synchronized`. | 0 | PASS |
| CMD-012 | AC-033, PAC-13 | `PYTHONPATH="$WT" python3 "$WT/tests/test_sync_plugin_cache.py"` | Plugin cache integration test passes. | 12 subtests passed; summary `passed=12 failed=0 total=12`. | 0 | PASS |
| CMD-013 | AC-035, PAC-11, PAC-13 | `find "$WT" -path '*/execution-flow.*' -type f` | No DOD-017 execution-flow artifacts exist. | No output. | 0 | PASS |
| CMD-014 | AC-035, PAC-13 | `git diff --name-only master...HEAD` | Changed-file provenance excludes Claude Code core. | Listed DOD-016 graph/view, hook lib, transition graph script, and tests; no core path. | 0 | PASS |
| CMD-015 | AC-034, PAC-7, PAC-13 | `validate_graph_consumer_identities` matching/mismatch Python snippet | Matching consumers pass and mismatch fails closed. | Matching accepted=true/status=ok/consumer_count=3; deliberate hash mismatch returned validation_failed, fail_closed=true, `graph_consumer_hash_mismatch`. | 0 | PASS |
| CMD-016 | AC-033, PAC-13 | Hook source/project sha256 diagnostic Python snippet | Record exact hook project copy status. | Shell hooks match; `.claude/hooks/lib/pre_tool_use_fast.py` does not exist; source sha256 recorded. | 0 | DIAGNOSTIC_RECORDED |
| CMD-017 | AC-033, PAC-13 | Active cache `pre_tool_use_fast.py` sha256 diagnostic Python snippet | Record active plugin cache status. | Cache copies at `0.59.6` and `0.59.8` exist but do not match source sha256. | 0 | DIAGNOSTIC_RECORDED |
| CMD-018 | AC-034, AC-036, PAC-13 | `python3 -m json.tool "$WT/coverage-matrix.json"` | Coverage matrix is valid JSON. | JSON parsed successfully. | 0 | PASS |
| CMD-019 | AC-034, PAC-7, PAC-13 | `grep -R "graph_hash\|graph_version\|DOD-016" "$WT/coverage-matrix.json" "$WT/evidence-ledger.md" "$WT/verification-report.md"` | Graph identity and DOD-016 evidence strings are present. | Sentinel strings present. | 0 | PASS |
| CMD-020 | AC-036, AC-037, PAC-1, PAC-13 | `grep -R "PAC-1\|PAC-13\|AC-001\|AC-036\|AC-037" "$WT/coverage-matrix.md" "$WT/evidence-ledger.md" "$WT/verification-report.md"` | PAC/AC coverage sentinel strings are present. | Sentinel strings present. | 0 | PASS |

`$WT` above is `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-819/integration`. The full exact commands are mirrored in `coverage-matrix.json`.

## Graph Identity Evidence

Canonical graph source:

```text
templates/state-machine/mst-transition-graph.json
graph_id=mst-transition-graph
graph_version=2026-05-05.dod016-contract
graph_hash=8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79
```

Generated view:

```text
dashboard/mst-transition-graph.json
kind=mst-transition-graph-view
source_graph_path=templates/state-machine/mst-transition-graph.json
source_graph.id=mst-transition-graph
source_graph.version=2026-05-05.dod016-contract
source_graph.hash=8bfe2272e05f4ddd8113f64d02778edf0eab7189ff0b480bf6a916a407a25e79
covered_states=active, blocked, cancelled, completed, failed, inspecting
covered_transitions=continue.queued_action, continue.rehydrate_retry, guard.inspect_only_verification, terminal.completed, terminal.repeat_failure_limit, terminal.security_confirmation_required, terminal.state_inconsistency
```

Consumer identity status:

- Matching consumers: `transition_validator`, `pre_tool_use_fast_hook`, `generated_graph_view`.
- Matching result: `accepted=true`, `status=ok`, `consumer_count=3`.
- Mismatch result: deliberate `graph_hash` mismatch returned `accepted=false`, `status=validation_failed`, `fail_closed=true`, `graph_consumer_hash_mismatch`.

## Hook Sync Evidence

Shell hook source/project copies:

```text
mst-pre-tool-use.sh: source/project sha256 match
mst-stop-hook.sh: source/project sha256 match
mst-session-init.sh: source/project sha256 match
mst-auto-chain-context.sh: source/project sha256 match
```

Required sync tests:

```text
tests/hooks/test_hook_copy_sync.sh: PASS
tests/test_sync_plugin_cache.py: PASS, passed=12 failed=0 total=12
```

`hooks/lib/pre_tool_use_fast.py` exact diagnostic:

```text
source=/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-819/integration/hooks/lib/pre_tool_use_fast.py
source_sha256=624693b838912f88ef6fd231d6081b124d7f158f7a7b1fd12ce619352ffd8af4
project copy path does not exist: /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-819/integration/.claude/hooks/lib/pre_tool_use_fast.py
/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.59.6/hooks/lib/pre_tool_use_fast.py: mismatch sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52
/Users/brandev/.claude/plugins/cache/gran-maestro/mst/0.59.8/hooks/lib/pre_tool_use_fast.py: mismatch sha256=79d42fd07088f82431f529f9a2ebce57f1106853f4624af1719992f7112f4d52
```

## No-Core And No-DOD017 Evidence

`git diff --name-only master...HEAD` returned:

```text
dashboard/mst-transition-graph.json
hooks/lib/pre_tool_use_fast.py
scripts/mst_cmds/transition_graph.py
templates/state-machine/mst-transition-graph.json
tests/test_dod015_external_control_surface_contract.py
tests/test_dod016_transition_graph_contract.py
```

No changed path is under `src/claude-code-core/`, `packages/claude-code-core/`, or `vendor/claude-code/`. The DOD-015 regression guard was updated to allow only `dashboard/mst-transition-graph.json`, not a broad dashboard surface.

The required DOD-017 scan:

```text
find "$WT" -path '*/execution-flow.*' -type f
```

returned no output.

## PAC Evidence Summary

- PAC-1 through PAC-8: covered by canonical graph, validator, hook boundary, hot path, consumer identity, and generated view evidence.
- PAC-9: covered by DOD-016 targeted regression.
- PAC-10: covered by DOD-011 through DOD-015 regressions plus `npm test`, `npx tsc --noEmit`, and `git diff --check`.
- PAC-11: covered by changed-file scan and empty `execution-flow.*` find scan.
- PAC-12: covered by DOD-015 impact check.
- PAC-13: covered by this ledger, `coverage-matrix.json`, `coverage-matrix.md`, and `verification-report.md`.

## AC-030 Through AC-037

| AC | Result | Evidence |
| --- | --- | --- |
| AC-030 | PASS | DOD-016 targeted regression passed. |
| AC-031 | PASS | DOD-011 through DOD-015 regressions passed; initial DOD-015 stale allowlist failure was fixed and rerun. |
| AC-032 | PASS | `npm test`, `npx tsc --noEmit`, and `git diff --check` passed. |
| AC-033 | PASS_WITH_DIAGNOSTIC | Required hook/cache tests passed; `hooks/lib/pre_tool_use_fast.py` project copy missing and active cache mismatch diagnostics recorded. |
| AC-034 | PASS | Graph id/version/hash and consumer sync evidence recorded. |
| AC-035 | PASS | No core source path and no `execution-flow.*` artifacts. |
| AC-036 | PASS | PAC-1 through PAC-13 and AC-001 through AC-037 represented. |
| AC-037 | PASS | DOD-015 impact suite passed. |
