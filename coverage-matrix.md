# REQ-813 T03 Coverage Matrix

- Request: REQ-813
- Task: T03
- Plan: PLN-640
- Overall status: PASS
- MUST PAC unmapped count: 0
- SHOULD PAC unmapped count: 0

| PAC | Coverage | Evidence | Status |
|-----|----------|----------|--------|
| PAC-1 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac001_resume_checkpoint_uses_existing_snapshot_and_ledger_head` | PASS |
| PAC-2 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac002_skill_switch_child_dispatch_keeps_parent_session_and_root_without_new_session` | PASS |
| PAC-3 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac003_compaction_rehydration_write_ignores_conflicting_prompt_summary` | PASS |
| PAC-4 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac004_stop_hook_continuation_uses_active_workflow_next_action_and_ledger_head_evidence` | PASS |
| PAC-5 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac005_stale_mismatch_and_prompt_summary_only_inputs_are_non_success_no_mutation` | PASS |
| PAC-6 | COVERED | `tests/test_dod011_rehydration_contract.py::test_ac006_legacy_identity_inputs_are_never_success_or_fallback_sources` | PASS |
| PAC-7 | COVERED | DOD-003~DOD-006 full regression chain and `scripts/tests/test_agile_cross_agi_isolation.py` | PASS |
| PAC-8 | COVERED | `npm exec -- tsc --noEmit`, `npm test`, `git diff --check` | PASS |
| PAC-9 | COVERED | `tests/test_sync_plugin_cache.py`, `tests/test_plugin_manifest_hooks.py`, README/docs/skills diff impact check | PASS |

## Commands executed

```bash
PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py
PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_resume_context.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_dispatch_context.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_hook_no_fallback.py
PYTHONPATH=$PWD python3 tests/test_dod003_state_snapshot_contract.py && PYTHONPATH=$PWD python3 tests/test_dod003_state_no_ppid_contract.py && PYTHONPATH=$PWD python3 tests/test_dod003_legacy_diagnostic_only.py && PYTHONPATH=$PWD python3 tests/test_dod004_parent_session_inheritance.py && PYTHONPATH=$PWD python3 tests/test_dod004_subprocess_session_inheritance.py && PYTHONPATH=$PWD python3 tests/test_dod004_hook_parent_session_boundary.py && PYTHONPATH=$PWD python3 tests/test_dod005_history_cli.py && PYTHONPATH=$PWD python3 tests/test_dod005_history_integrity.py && PYTHONPATH=$PWD python3 tests/test_dod005_history_no_fallback.py && PYTHONPATH=$PWD python3 tests/test_dod005_hook_no_fallback.py && PYTHONPATH=$PWD python3 tests/test_dod005_invocation_history.py && PYTHONPATH=$PWD python3 tests/test_dod005_skill_lifecycle_history.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_resume_context.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_no_fallback.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_idempotency.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_dispatch_context.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_skill_history.py && PYTHONPATH=$PWD python3 tests/test_dod006_recover_hook_no_fallback.py
PYTHONPATH=$PWD python3 scripts/tests/test_agile_cross_agi_isolation.py
npm exec -- tsc --noEmit
npm test
git diff --check
python3 tests/test_sync_plugin_cache.py && python3 tests/test_plugin_manifest_hooks.py
git diff --name-only -- README.md docs skills || true
git diff -- README.md docs skills || true
```
