# REQ-813 T03 Evidence Ledger

- Request: REQ-813
- Task: T03
- Plan: PLN-640
- Objective: AGI-030 Sprint 10 DOD-011
- Checked at: 2026-05-05
- Integration HEAD: b4c0d0c4aae99db1cf0831db527d3a9d4f72d78a
- T02 follow-up commit: 2cf2b7f2645728fc38567ad0e8605a52b51110e5
- Overall status: PASS

## PAC-1 — Resume/checkpoint rehydrates from validated snapshot and ledger

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: DOD-011 targeted suite passes, including resume/checkpoint envelope fields for `mst_session_id`, `root_mst_id`, `workflow.next_skill`, `workflow.next_source`, and validated history head.
- Actual: PASS. `test_ac001_resume_checkpoint_uses_existing_snapshot_and_ledger_head` passed and the full DOD-011 targeted suite passed.
- Exit code: 0

## PAC-2 — Skill switch/child dispatch preserves parent session context

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: Child dispatch records keep the parent `MST_SESSION_ID`/`root_mst_id` and do not create fallback sessions.
- Actual: PASS. `test_ac002_skill_switch_child_dispatch_keeps_parent_session_and_root_without_new_session` passed.
- Exit code: 0

## PAC-3 — Context compaction prefers core rehydration over prompt summary

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: Conflicting prompt-summary identity is diagnostic only; state writes use `core_rehydration` identity and canonical ledger context.
- Actual: PASS. `test_ac003_compaction_rehydration_write_ignores_conflicting_prompt_summary` passed.
- Exit code: 0

## PAC-4 — Stop-hook continuation uses active workflow and ledger head evidence

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: Stop hook blocks with the active workflow next action and includes ledger head evidence instead of falling back to an unhandled approve decision.
- Actual: PASS. `test_ac004_stop_hook_continuation_uses_active_workflow_next_action_and_ledger_head_evidence` passed.
- Exit code: 0

## PAC-5 — Stale/mismatch/prompt-summary-only inputs fail closed without mutation

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: Stale handoff, history head mismatch, parent/child session mismatch, and prompt-summary-only recover inputs return structured non-success or inspect-only evidence and do not mutate canonical state/history.
- Actual: PASS. `test_ac005_stale_mismatch_and_prompt_summary_only_inputs_are_non_success_no_mutation` passed after the T02 follow-up narrowed lifecycle exceptions to the current process invocation-start path only.
- Exit code: 0

## PAC-6 — Legacy identity inputs are never canonical fallback sources

- Command: `PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py`
- Expected: Legacy-only or alias-conflicting identity (`sessionId`, `session_id`, `owner_session_id`, `MST_SNAPSHOT_SESSION_ID`, hook `session_id`, transcript UUID) never recovers successfully or creates fallback canonical sessions.
- Actual: PASS. `test_ac006_legacy_identity_inputs_are_never_success_or_fallback_sources` passed.
- Exit code: 0

## PAC-7 — DOD-003~DOD-006 and DOD-010 regressions remain green

- Commands:
  - `PYTHONPATH=$PWD python3 tests/test_dod003_state_snapshot_contract.py && ... && PYTHONPATH=$PWD python3 tests/test_dod006_recover_hook_no_fallback.py`
  - `PYTHONPATH=$PWD python3 scripts/tests/test_agile_cross_agi_isolation.py`
  - `PYTHONPATH=$PWD python3 tests/test_dod006_recover_skill_history.py`
- Expected: Existing canonical state, no-PPID, parent inheritance, history integrity, recover/resume/dispatch/hook, skill lifecycle, and cross-AGI isolation regressions pass.
- Actual: PASS. The full DOD-003~DOD-006 regression chain passed, including `test_recovered_context_skill_lifecycle_appends_to_existing_session_ledger`; DOD-010 cross-AGI isolation passed with `1 passed`.
- Exit code: 0

## PAC-8 — TypeScript, npm smoke, and diff sanity pass

- Commands:
  - `npm exec -- tsc --noEmit`
  - `npm test`
  - `git diff --check`
- Expected: TypeScript check, npm smoke test, and whitespace sanity all pass.
- Actual: PASS. `npm exec -- tsc --noEmit` completed with no output; `npm test` reported `pass 1 fail 0`; `git diff --check` completed with no output.
- Exit code: 0

## PAC-9 — Hook sync/plugin manifest and docs impact are verified

- Commands:
  - `python3 tests/test_sync_plugin_cache.py && python3 tests/test_plugin_manifest_hooks.py`
  - `git diff --name-only -- README.md docs skills || true`
  - `git diff -- README.md docs skills || true`
- Expected: Hook source/copy/cache sync and plugin manifest hook declarations pass; README/docs/skills changes are either evidenced or explicitly not required.
- Actual: PASS. Hook sync/plugin manifest checks reported `SUMMARY: passed=12 failed=0 total=12`, `PASS test_sync_plugin_cache_integration`, and `PASS test_plugin_manifest_hooks_file_exposes_expected_events`. README/docs/skills diff commands produced no output, so docs impact is not required.
- Exit code: 0

## Additional implementation evidence

- T02 follow-up fixed the T03 failure by allowing recovered-context state writes to accept the command-entry ledger head when the current process `mst.invocation_start` has already advanced the ledger.
- The same change keeps stale handoff fail-closed behavior by skipping stale invocation-start mutation and only allowing invocation end/error when the current invocation start exists in the ledger.
- Modified implementation files in T02 follow-up: `scripts/mst_cmds/state.py`, `scripts/mst_cmds/session.py`.
