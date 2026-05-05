# REQ-815 T03 Coverage Matrix

- Request: REQ-815
- Task: T03
- Plan: PLN-642
- Objective: AGI-030 / DOD-012
- Cynefin domain: complicated
- Integration worktree: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03`
- Validated implementation baseline: `08fe874544c8b103ed38ca94ae8f7993b3a6714f`
- Authoritative validation path: `/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03`
- Non-authoritative stale-root probe: `/Users/brandev/mygit/gran-maestro` at `2a48c8f2cc5c531a3101d536446f1d9886c4d5bf` lacked the T01/T02 DOD-012 test before integration and is not used for T03 status.
- Overall status: PASS.
- MUST PAC unmapped count: 0
- SHOULD PAC unmapped count: 0

| PAC | Grade | AC | Coverage | Evidence | Status |
|-----|-------|----|----------|----------|--------|
| PAC-1 | MUST | AC-015 | COVERED | `tests/test_dod012_auto_continuation_contract.py::test_auto_continuation_policy_persists_through_recover_bundle` verifies `mst_session_id`, `root_mst_id`, `auto=true`, `continuation.mode=continue_unless_critical`, `next_action`, and `critical_blocker=null` in recover output. | PASS in worktree |
| PAC-2 | MUST | AC-015 | COVERED | `test_recoverable_issue_records_continue_transition_and_next_action_execution_evidence` verifies recoverable hook output records `continue.*` and next-action execution evidence. | PASS in worktree |
| PAC-3 | MUST | AC-015 | COVERED | `test_user_wait_guard_redirects_without_critical_evidence` covers AskUserQuestion, confirmation wait, self-paced stop, and stop-hook preventContinuation attempts without terminal user-wait. | PASS in worktree |
| PAC-4 | MUST | AC-015 | COVERED | `test_blocker_evidence_is_structured_before_user_wait_is_allowed` verifies structured `critical_blocker` fields: `type`, `evidence`, `attempted_recovery`, `next_safe_action`, `mst_session_id`, and `history_head`. | PASS in worktree |
| PAC-5 | MUST | AC-015 | COVERED | `test_security_boundary_records_confirmation_required_and_does_not_start_original_action` verifies destructive/shared-state action is not started and records `terminal.security_confirmation_required` or equivalent blocker. | PASS in worktree |
| PAC-6 | MUST | AC-015 | COVERED | `test_action_classification_precedes_blocker_declaration_from_prose` verifies queued action/tool envelope classification, classifier failure kind, safe alternatives, and no assistant-prose-only blocker. | PASS in worktree |
| PAC-7 | MUST | AC-015 | COVERED | `test_retry_circuit_key_is_session_action_error_scoped_and_resets_on_progress` verifies circuit key scope is `mst_session_id + normalized_action + normalized_error` and resets after `action.completed`. | PASS in worktree |
| PAC-8 | MUST | AC-015, AC-016, AC-017, AC-018 | COVERED | Authoritative T03 worktree commands passed: DOD-012, DOD-011, DOD-006, `npm test`, `npm exec -- tsc --noEmit`, `git diff --check`, and `coverage-matrix.json` JSON validation. | PASS |
| PAC-9 | SHOULD | AC-020 | COVERED | `git diff --name-only HEAD -- README.md docs skills` produced no output in T03 worktree; no docs/skills change was made in T03, so docs/skills impact is not required. | PASS |
| PAC-10 | SHOULD | AC-019 | COVERED | `git diff --name-only HEAD -- hooks .claude/hooks` produced no output for T03 evidence changes; hook sync was also checked for T02-modified source/copy/cache files with `cmp=0`. | PASS |

## Commands Executed

Authoritative §5 commands run in the T03 worktree:

```bash
PYTHONPATH=/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 python3 /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03/tests/test_dod012_auto_continuation_contract.py
PYTHONPATH=/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 python3 /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03/tests/test_dod011_rehydration_contract.py
PYTHONPATH=/Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 python3 /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03/tests/test_dod006_recover_skill_history.py
npm --prefix /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 test
npm --prefix /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 exec -- tsc --noEmit
git -C /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03 diff --check
python3 -m json.tool /Users/brandev/mygit/gran-maestro/.gran-maestro/worktrees/AGI-030/REQ-815/t03/coverage-matrix.json
```

T03 worktree validation commands:

```bash
PYTHONPATH=$PWD python3 tests/test_dod012_auto_continuation_contract.py
PYTHONPATH=$PWD python3 tests/test_dod011_rehydration_contract.py
PYTHONPATH=$PWD python3 tests/test_dod006_recover_skill_history.py
npm test
npm exec -- tsc --noEmit
git diff --check
git diff --name-only HEAD -- hooks .claude/hooks README.md docs skills
cmp -s hooks/mst-stop-hook.sh .claude/hooks/mst-stop-hook.sh
cmp -s hooks/mst-stop-hook.sh "$HOME/.claude/plugins/cache/gran-maestro/mst/0.59.8/hooks/mst-stop-hook.sh"
cmp -s hooks/mst-stop-hook.sh "$HOME/.claude/plugins/cache/gran-maestro/mst/0.59.8/.claude/hooks/mst-stop-hook.sh"
```
