from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

DOD002_UNIT_COVERAGE = {
    "session_identity": {
        "path": "tests/test_dod002_session_id_contract.py",
        "tests": [
            "test_env_and_payload_spellings_are_same_canonical_identity_contract",
            "test_session_resolve_json_alias_matches_structured_mst_session_id",
        ],
        "tokens": ["MST_SESSION_ID", "legacy_diagnostics"],
    },
    "id_generation_validation": {
        "path": "tests/test_dod002_entrypoint_generation_matrix.py",
        "tests": [
            "test_root_entrypoint_generation_allowed_with_explicit_root_context",
            "test_child_entrypoint_generation_forbidden_without_parent_env",
            "test_missing_context_mutation_generation_forbidden_without_legacy_fallback",
        ],
        "tokens": ["ENTRYPOINT_GENERATION_MATRIX", "UUID_V4_RE"],
    },
    "history_ledger": {
        "path": "scripts/tests/test_history_ledger_contract.py",
        "tests": [
            "test_normal_append_hash_chain_matches_heads_and_verify_state",
            "test_corrupt_partial_and_stale_lock_failure_evidence_block_without_hiding_damage",
        ],
        "tokens": ["history ledger mismatch", "verify_history"],
    },
    "policy": {
        "path": "tests/test_pre_tool_use_policy_contract.py",
        "tests": [
            "test_decision_tuple_matches_between_shell_wrapper_and_python_fast_path",
            "test_failure_modes_fail_closed_with_contract_evidence",
        ],
        "tokens": ["policy_block", "manifest_sha256_mismatch"],
    },
    "phase_gate": {
        "path": "tests/test_pre_tool_use_policy_contract.py",
        "tests": ["test_decision_tuple_matches_between_shell_wrapper_and_python_fast_path"],
        "tokens": ["_install_phase_gate_rule", "phase_gate_mutating_bash", "GM-PHASE-GATE"],
    },
    "boundary": {
        "path": "scripts/tests/test_boundary_integration.py",
        "tests": [
            "test_pre_tool_hook_blocks_missing_worktree_when_retry_not_possible",
            "test_pre_tool_hook_repairs_missing_worktree_when_retry_possible",
            "test_stop_boundary_log_then_detect_orphans_migrates_cleaned_meta",
        ],
        "tokens": ["boundary_violation", "boundary-guard.log"],
    },
    "stop_judge": {
        "path": "scripts/tests/test_stop_judge.py",
        "tests": [
            "test_evaluate_stop_judge_returns_structured_decision_and_wrapper_payload",
            "test_reduce_stop_judge_respects_priority_order",
            "test_invalid_stdin_returns_fail_open_fallback",
        ],
        "tokens": ["reduce_stop_judge_decision", "hook judge timeout"],
    },
    "prompt_context": {
        "path": "tests/test_dod004_prompt_correlation_contract.py",
        "tests": [
            "test_prompt_submitted_event_schema_uses_canonical_env_identity_and_confines_diagnostics",
            "test_prompt_writer_rejects_missing_canonical_identity_without_legacy_fallback",
            "test_prompt_timeline_correlation_uses_ledger_order_timestamp_and_head_relation_only",
        ],
        "tokens": ["prompt.submitted", "prompt_excerpt", "project_prompt_timeline"],
    },
}


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


def test_agi036_dod002_unit_coverage_inventory_has_all_required_feature_groups() -> None:
    assert set(DOD002_UNIT_COVERAGE) == {
        "session_identity",
        "id_generation_validation",
        "history_ledger",
        "policy",
        "phase_gate",
        "boundary",
        "stop_judge",
        "prompt_context",
    }


DOD002_GROUP_IDS = sorted(DOD002_UNIT_COVERAGE)


def test_agi036_dod002_feature_group_representative_tests_exist() -> None:
    missing: list[str] = []
    for group_id in DOD002_GROUP_IDS:
        expectation = DOD002_UNIT_COVERAGE[group_id]
        path = REPO_ROOT / expectation["path"]
        if not path.is_file():
            missing.append(f"{group_id}: missing file {expectation['path']}")
            continue
        tests = _test_functions(path)
        for test_name in expectation["tests"]:
            if test_name not in tests:
                missing.append(f"{group_id}: missing {test_name} in {expectation['path']}")

    assert not missing, "\n".join(missing)


def test_agi036_dod002_feature_group_contract_tokens_remain_anchored() -> None:
    missing: list[str] = []
    for group_id in DOD002_GROUP_IDS:
        expectation = DOD002_UNIT_COVERAGE[group_id]
        path = REPO_ROOT / expectation["path"]
        if not path.is_file():
            missing.append(f"{group_id}: missing file {expectation['path']}")
            continue
        text = path.read_text(encoding="utf-8")
        for token in expectation["tokens"]:
            if token not in text:
                missing.append(f"{group_id}: missing token {token!r} in {expectation['path']}")

    assert not missing, "\n".join(missing)
