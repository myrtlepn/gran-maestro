from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
AUDIT_JSON = REPO_ROOT / "hooks" / "canonical-hook-entrypoint-boundary.audit.json"
MATRIX_JSON = REPO_ROOT / "hooks" / "hook-event-contract-matrix.json"

EXPECTED_SOURCE_OF_TRUTH = {
    "plugin_manifest": ".claude-plugin/plugin.json",
    "hooks_registration": "hooks/hooks.json",
    "boundary_audit": "hooks/canonical-hook-entrypoint-boundary.audit.json",
}
EXPECTED_COMMAND_ROOT = "${CLAUDE_PLUGIN_ROOT}/hooks/"
EXPECTED_NEGATIVE_BOUNDARIES = {
    ".claude/hooks": "project_legacy_source_dev_helper",
    "$CLAUDE_PROJECT_DIR/.claude/hooks": "project_local_hook_registration",
    "settings.local.json": "project_local_settings_hook_registration",
    "~/.claude/settings.json": "user_global_environment_hooks",
}
REQUIRED_ROW_KEYS = {
    "event",
    "matcher",
    "hook_type",
    "command",
    "script",
    "source_of_truth",
    "command_root",
    "case_id",
    "coverage_scope",
    "applicability",
    "stdin_shape",
    "expected_decision",
    "expected_exit_code",
    "stdout_contract",
    "stderr_contract",
    "expected_diagnostics",
    "allowed_side_effects",
    "forbidden_side_effects",
    "contract_tests",
}
ALLOWED_EVENTS = {"SessionStart", "PreToolUse", "Stop", "UserPromptSubmit"}
ALLOWED_DECISIONS = {
    "approve",
    "block",
    "noop",
    "allow",
    "fail_open_approve",
    "fail_open_noop",
    "fail_closed_block",
    "not_applicable",
}
ALLOWED_STDIN_SHAPES = {"valid", "invalid_json", "empty", "missing_fields", "n/a"}
ALLOWED_COVERAGE_SCOPES = {
    "runtime_guaranteed",
    "direct_fixture_only",
    "negative_boundary",
}
ALLOWED_APPLICABILITY = {"applicable", "not_applicable"}
ALLOWED_STDOUT_MODES = {
    "empty",
    "single_line_json",
    "hook_specific_output_json",
    "block_payload_json",
}
ALLOWED_STDERR_MODES = {
    "silent",
    "diagnostics_only",
    "block_diagnostics",
    "optional_diagnostics",
}
ALLOWED_DIAGNOSTIC_MODES = {"required", "optional", "forbidden"}
COMMON_FAILURE_CASES = {
    "invalid_json",
    "empty_stdin",
    "missing_fields",
    "helper_failure",
    "helper_timeout",
    "partial_stdout",
    "session_mismatch",
    "history_mismatch",
    "policy_exception",
    "boundary_repair_failure",
    "timeout",
    "stdout_contamination",
}
REQUIRED_CASE_ASSERTIONS = {
    ("SessionStart", ""): {
        "runtime_registration": "noop",
        "normal_start": "noop",
        "missing_runtime_or_version_guard": "fail_open_noop",
        "maintenance_failure": "fail_open_noop",
    },
    ("PreToolUse", "Skill"): {
        "runtime_registration": "allow",
        "normal_allow": "allow",
        "policy_block": "fail_closed_block",
        "history_mismatch": "fail_closed_block",
        "boundary_repair_failure": "fail_closed_block",
    },
    ("PreToolUse", "ScheduleWakeup"): {
        "runtime_registration": "allow",
        "normal_allow": "allow",
        "policy_block": "fail_closed_block",
        "history_mismatch": "fail_closed_block",
        "boundary_repair_failure": "fail_closed_block",
    },
    ("Stop", ""): {
        "runtime_registration": "approve",
        "normal_approve": "approve",
        "normal_block": "block",
        "invalid_judge_stdout": "fail_open_approve",
        "duplicate_stdout_fence": "fail_open_approve",
        "process_cleanup": "fail_open_approve",
    },
    ("UserPromptSubmit", ""): {
        "runtime_registration": "noop",
        "inactive_noop": "noop",
        "active_context": "allow",
        "helper_invalid_json": "fail_open_noop",
        "wrong_hook_specific_output_shape": "fail_open_noop",
        "additional_context_wrong_type": "fail_open_noop",
    },
}
REQUIRED_CASE_TESTS = {
    ("SessionStart", "missing_runtime_or_version_guard"): {
        "tests/test_claude_code_version_guard.py",
    },
    ("PreToolUse", "policy_block"): {
        "tests/test_pre_tool_use_policy_contract.py",
    },
    ("PreToolUse", "runtime_registration"): {
        "tests/test_pre_tool_use_fast_schedule_wakeup.py",
    },
    ("Stop", "normal_approve"): {
        "tests/test_stop_hook_output_strict_schema.py",
        "scripts/tests/test_stop_judge.py",
    },
    ("Stop", "invalid_judge_stdout"): {
        "scripts/tests/test_stop_hook_wrapper.py",
    },
    ("Stop", "duplicate_stdout_fence"): {
        "tests/test_stop_hook_timeout_emit_fence.py",
    },
    ("UserPromptSubmit", "active_context"): {
        "tests/test_auto_chain_context_hook.py",
        "tests/test_auto_chain_context_schema.py",
    },
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hooks_runtime_tuples() -> set[tuple[str, str, str, str, str]]:
    payload = _load_json(HOOKS_JSON)
    tuples: set[tuple[str, str, str, str, str]] = set()
    for event, registrations in payload["hooks"].items():
        for registration in registrations:
            matcher = registration.get("matcher", "")
            for hook in registration.get("hooks", []):
                command = hook["command"]
                tuples.add((event, matcher, hook["type"], command, Path(command).name))
    return tuples


def _audit_runtime_tuples() -> set[tuple[str, str, str, str, str]]:
    payload = _load_json(AUDIT_JSON)
    tuples: set[tuple[str, str, str, str, str]] = set()
    for entry in payload["canonical_entrypoints"]:
        for matcher in entry["matchers"]:
            tuples.add(
                (
                    entry["event"],
                    matcher,
                    "command",
                    entry["command"],
                    entry["script"],
                )
            )
    return tuples


def _audit_entrypoints_by_script() -> dict[str, dict]:
    payload = _load_json(AUDIT_JSON)
    return {
        entry["script"]: entry
        for entry in payload["canonical_entrypoints"]
    }


def _matrix_payload() -> dict:
    return _load_json(MATRIX_JSON)


def _runtime_rows() -> list[dict]:
    return _matrix_payload()["runtime_rows"]


def _negative_boundary_rows() -> list[dict]:
    return _matrix_payload()["negative_boundary_rows"]


def _rows_by_tuple() -> dict[tuple[str, str], dict[str, dict]]:
    rows: dict[tuple[str, str], dict[str, dict]] = {}
    for row in _runtime_rows():
        key = (row["event"], row["matcher"])
        rows.setdefault(key, {})
        rows[key][row["case_id"]] = row
    return rows


def test_matrix_top_level_schema_and_sources() -> None:
    payload = _matrix_payload()
    plugin_payload = _load_json(PLUGIN_JSON)

    assert plugin_payload["hooks"] == "./hooks/hooks.json"
    assert payload["schema_version"] == 1
    assert payload["source_of_truth"] == EXPECTED_SOURCE_OF_TRUTH
    assert payload["command_root"] == EXPECTED_COMMAND_ROOT
    assert isinstance(payload["runtime_rows"], list) and payload["runtime_rows"]
    assert isinstance(payload["negative_boundary_rows"], list) and payload["negative_boundary_rows"]


def test_matrix_runtime_rows_lock_tuple_identity_and_drift() -> None:
    hooks_tuples = _hooks_runtime_tuples()
    audit_tuples = _audit_runtime_tuples()
    runtime_rows = _runtime_rows()

    identities = set()
    registration_tuples = set()

    for row in runtime_rows:
        assert set(row) == REQUIRED_ROW_KEYS
        assert row["event"] in ALLOWED_EVENTS
        assert row["hook_type"] == "command"
        assert row["command"].startswith(EXPECTED_COMMAND_ROOT)
        assert row["script"] == Path(row["command"]).name
        assert row["source_of_truth"] == EXPECTED_SOURCE_OF_TRUTH["hooks_registration"]
        assert row["command_root"] == EXPECTED_COMMAND_ROOT
        assert row["coverage_scope"] in ALLOWED_COVERAGE_SCOPES
        assert row["applicability"] in ALLOWED_APPLICABILITY
        assert row["stdin_shape"] in ALLOWED_STDIN_SHAPES
        assert row["expected_decision"] in ALLOWED_DECISIONS
        assert isinstance(row["expected_exit_code"], int) or row["expected_exit_code"] == "n/a"
        assert isinstance(row["allowed_side_effects"], list)
        assert isinstance(row["forbidden_side_effects"], list)
        assert isinstance(row["contract_tests"], list) and row["contract_tests"]
        assert all(isinstance(target, str) and target.strip() for target in row["contract_tests"])

        stdout_contract = row["stdout_contract"]
        assert set(stdout_contract) == {"mode", "required_keys", "forbidden_patterns"}
        assert stdout_contract["mode"] in ALLOWED_STDOUT_MODES
        assert isinstance(stdout_contract["required_keys"], list)
        assert isinstance(stdout_contract["forbidden_patterns"], list)

        stderr_contract = row["stderr_contract"]
        assert set(stderr_contract) == {"mode", "required_tokens", "forbidden_in_stdout"}
        assert stderr_contract["mode"] in ALLOWED_STDERR_MODES
        assert isinstance(stderr_contract["required_tokens"], list)
        assert isinstance(stderr_contract["forbidden_in_stdout"], list)

        expected_diagnostics = row["expected_diagnostics"]
        assert set(expected_diagnostics) == {"mode", "reason_tokens"}
        assert expected_diagnostics["mode"] in ALLOWED_DIAGNOSTIC_MODES
        assert isinstance(expected_diagnostics["reason_tokens"], list)

        identity = (
            row["event"],
            row["matcher"],
            row["hook_type"],
            row["command"],
            row["case_id"],
        )
        assert identity not in identities, f"duplicate runtime row identity: {identity}"
        identities.add(identity)

        if row["case_id"] == "runtime_registration":
            registration_tuples.add(
                (
                    row["event"],
                    row["matcher"],
                    row["hook_type"],
                    row["command"],
                    row["script"],
                )
            )

    assert registration_tuples == hooks_tuples == audit_tuples


def test_matrix_covers_common_failure_rows_for_every_runtime_tuple() -> None:
    rows_by_tuple = _rows_by_tuple()
    assert set(rows_by_tuple) == set(REQUIRED_CASE_ASSERTIONS)

    for tuple_key, case_rows in rows_by_tuple.items():
        for case_id in COMMON_FAILURE_CASES:
            assert case_id in case_rows, f"missing {case_id} for {tuple_key}"
            assert case_rows[case_id]["applicability"] in ALLOWED_APPLICABILITY


def test_matrix_event_specific_contracts_link_to_existing_tests() -> None:
    rows_by_tuple = _rows_by_tuple()

    for tuple_key, expected_cases in REQUIRED_CASE_ASSERTIONS.items():
        case_rows = rows_by_tuple[tuple_key]
        for case_id, expected_decision in expected_cases.items():
            row = case_rows[case_id]
            assert row["expected_decision"] == expected_decision, (tuple_key, case_id)

    for (event, case_id), expected_tests in REQUIRED_CASE_TESTS.items():
        matching_rows = [
            row
            for row in _runtime_rows()
            if row["event"] == event and row["case_id"] == case_id
        ]
        assert matching_rows, (event, case_id)
        for row in matching_rows:
            assert expected_tests <= set(row["contract_tests"]), (event, case_id, row["matcher"])
            for target in row["contract_tests"]:
                assert (REPO_ROOT / target).exists(), target


def test_matrix_negative_boundaries_stay_non_canonical() -> None:
    audit_payload = _load_json(AUDIT_JSON)
    runtime_commands = {row["command"] for row in _runtime_rows()}

    boundaries = {row["path"]: row for row in _negative_boundary_rows()}
    assert set(boundaries) == set(EXPECTED_NEGATIVE_BOUNDARIES)

    audit_boundaries = {
        item["path"]: item["classification"]
        for item in audit_payload["canonical_runtime_boundary"]["non_canonical_runtimes"]
    }

    for path, classification in EXPECTED_NEGATIVE_BOUNDARIES.items():
        row = boundaries[path]
        assert row["coverage_scope"] == "negative_boundary"
        assert row["classification"] == classification
        assert row["canonical_mst_core_runtime"] is False
        assert row["allowed_only_as"] == "negative_boundary"
        assert isinstance(row["reason"], str) and row["reason"].strip()
        assert all(path not in command for command in runtime_commands)

    for path, classification in audit_boundaries.items():
        assert boundaries[path]["classification"] == classification


def test_retained_shell_wrappers_have_machine_readable_rationale_and_boundary_contract() -> None:
    hook_scripts = {path.name for path in (REPO_ROOT / "hooks").glob("*.sh")}
    entrypoints = _audit_entrypoints_by_script()
    runtime_scripts = {row["script"] for row in _runtime_rows() if row["case_id"] == "runtime_registration"}

    assert hook_scripts == runtime_scripts == set(entrypoints)

    for script in sorted(hook_scripts):
        entry = entrypoints[script]
        assert entry["shell_wrapper_retained"] is True
        assert isinstance(entry["wrapper_reason"], str) and len(entry["wrapper_reason"]) >= 40
        assert entry["command"] == f"{EXPECTED_COMMAND_ROOT}{script}"
        assert entry["adapter_allowed"], script
        assert entry["process_control_allowed"], script
        assert entry["domain_logic_to_move"], script
        assert entry["maintenance_to_extract"], script

        contract_kinds = {
            item["kind"]
            for item in entry["contract_tests"]
            if isinstance(item, dict) and isinstance(item.get("kind"), str)
        }
        assert "registration" in contract_kinds, script
        assert contract_kinds & {
            "wrapper_contract",
            "shell_contract",
            "hook_output_contract",
            "schema_contract",
            "policy_contract",
        }, script

        maintenance_ids = {
            item["id"]
            for item in entry["maintenance_to_extract"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        assert {"plugin_cache_sync", "migration_cleanup"} <= maintenance_ids
