from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
AUDIT_JSON = REPO_ROOT / "hooks" / "canonical-hook-entrypoint-boundary.audit.json"

EXPECTED_COMMANDS = {
    "SessionStart": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh",
    "PreToolUse": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh",
    "Stop": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
    "UserPromptSubmit": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh",
}
EXPECTED_MATCHERS = {
    "SessionStart": [""],
    "PreToolUse": ["Skill", "ScheduleWakeup"],
    "Stop": [""],
    "UserPromptSubmit": [""],
}
REQUIRED_MAINTENANCE_IDS = {
    "plugin_cache_sync",
    "gardening_auto_archive",
    "run_marker_gc",
    "migration_cleanup",
}
DIRECT_WRAPPER_CONTRACT_KINDS = {"wrapper_contract", "shell_contract"}
REQUIRED_NON_CANONICAL_BOUNDARIES = {
    ".claude/hooks": "project_legacy_source_dev_helper",
    "~/.claude/settings.json": "user_global_environment_hooks",
}
REQUIRED_MAINTENANCE_FIELDS = {
    "classification": "maintenance_runtime",
    "current_event": "SessionStart",
    "target_boundary": "extract_from_hook_hot_path",
    "follow_up_dod": "DOD-016",
    "follow_up_marker": "maintenance_hot_path_extraction_follow_up",
}
REQUIRED_FIELDS = (
    "adapter_allowed",
    "process_control_allowed",
    "domain_logic_to_move",
    "maintenance_to_extract",
    "contract_tests",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_by_event() -> dict[str, dict]:
    payload = _load_json(AUDIT_JSON)
    entries = payload["canonical_entrypoints"]
    return {entry["event"]: entry for entry in entries}


def test_audit_sources_point_to_canonical_manifest_and_hooks_json() -> None:
    plugin_payload = _load_json(PLUGIN_JSON)
    audit_payload = _load_json(AUDIT_JSON)

    assert plugin_payload["hooks"] == "./hooks/hooks.json"
    assert audit_payload["source_of_truth"] == {
        "plugin_manifest": ".claude-plugin/plugin.json",
        "hooks_registration": "hooks/hooks.json",
    }

    canonical_boundary = audit_payload["canonical_runtime_boundary"]
    assert canonical_boundary["plugin_core_canonical_runtime"] == {
        "plugin_manifest": ".claude-plugin/plugin.json",
        "hooks_registration": "hooks/hooks.json",
        "command_root": "${CLAUDE_PLUGIN_ROOT}/hooks/",
    }


def test_audit_marks_legacy_and_user_global_hooks_non_canonical() -> None:
    audit_payload = _load_json(AUDIT_JSON)
    boundaries = audit_payload["canonical_runtime_boundary"]["non_canonical_runtimes"]

    by_path = {item["path"]: item for item in boundaries}
    assert set(by_path) == set(REQUIRED_NON_CANONICAL_BOUNDARIES)

    for path, classification in REQUIRED_NON_CANONICAL_BOUNDARIES.items():
        boundary = by_path[path]
        assert boundary["classification"] == classification
        assert boundary["canonical_mst_core_runtime"] is False
        assert isinstance(boundary["reason"], str) and boundary["reason"].strip()


def test_audit_event_inventory_matches_hooks_json() -> None:
    hooks_payload = _load_json(HOOKS_JSON)
    entries = _entry_by_event()

    assert set(entries) == set(EXPECTED_COMMANDS) == set(hooks_payload["hooks"])


def test_audit_locks_matchers_commands_and_script_names() -> None:
    hooks_payload = _load_json(HOOKS_JSON)
    entries = _entry_by_event()

    for event, expected_command in EXPECTED_COMMANDS.items():
        entry = entries[event]
        assert entry["command"] == expected_command
        assert entry["script"] == Path(expected_command).name
        assert entry["matchers"] == EXPECTED_MATCHERS[event]
        assert entry["command"].startswith("${CLAUDE_PLUGIN_ROOT}/hooks/")
        assert ".claude/hooks" not in entry["command"]

        registrations = hooks_payload["hooks"][event]
        actual_matchers = [item.get("matcher", "") for item in registrations]
        assert actual_matchers == EXPECTED_MATCHERS[event]

        actual_commands = [
            hook.get("command", "")
            for item in registrations
            for hook in item.get("hooks", [])
        ]
        assert actual_commands == [expected_command] * len(EXPECTED_MATCHERS[event])


def test_audit_distinguishes_allowed_vs_to_move_fields_for_all_events() -> None:
    entries = _entry_by_event()

    for event, entry in entries.items():
        assert entry["shell_wrapper_retained"] is True, event
        assert isinstance(entry["wrapper_reason"], str) and entry["wrapper_reason"].strip(), event

        for field in REQUIRED_FIELDS:
            value = entry[field]
            assert isinstance(value, list) and value, f"{event} {field} must be non-empty"


def test_audit_contract_test_targets_exist() -> None:
    entries = _entry_by_event()

    for event, entry in entries.items():
        for contract in entry["contract_tests"]:
            assert set(contract) == {"kind", "target"}, (event, contract)
            assert isinstance(contract["kind"], str) and contract["kind"].strip(), (event, contract)
            target = REPO_ROOT / contract["target"]
            assert target.exists(), f"{event} contract target missing: {contract['target']}"


def test_retained_shell_wrappers_have_direct_wrapper_or_shell_contract() -> None:
    entries = _entry_by_event()

    for event, entry in entries.items():
        if entry["shell_wrapper_retained"] is True:
            contract_kinds = {contract["kind"] for contract in entry["contract_tests"]}
            assert contract_kinds & DIRECT_WRAPPER_CONTRACT_KINDS, event


def test_audit_maintenance_catalog_tracks_required_hot_path_candidates() -> None:
    payload = _load_json(AUDIT_JSON)
    entries = _entry_by_event()

    catalog = payload["maintenance_catalog"]
    assert isinstance(catalog, list) and catalog

    catalog_ids = {item["id"] for item in catalog}
    assert catalog_ids == REQUIRED_MAINTENANCE_IDS

    for item in catalog:
        for field, expected_value in REQUIRED_MAINTENANCE_FIELDS.items():
            assert item[field] == expected_value, item["id"]

    session_start_ids = {item["id"] for item in entries["SessionStart"]["maintenance_to_extract"]}
    assert REQUIRED_MAINTENANCE_IDS <= session_start_ids

    for event in ("PreToolUse", "Stop", "UserPromptSubmit"):
        event_items = entries[event]["maintenance_to_extract"]
        event_ids = {item["id"] for item in event_items}
        assert REQUIRED_MAINTENANCE_IDS <= event_ids
        assert all(
            item["status"] == "must_not_run_in_event_hot_path" for item in event_items
        ), f"{event} must classify maintenance outside its hot path"


def main() -> int:
    test_audit_sources_point_to_canonical_manifest_and_hooks_json()
    print("PASS test_audit_sources_point_to_canonical_manifest_and_hooks_json")
    test_audit_marks_legacy_and_user_global_hooks_non_canonical()
    print("PASS test_audit_marks_legacy_and_user_global_hooks_non_canonical")
    test_audit_event_inventory_matches_hooks_json()
    print("PASS test_audit_event_inventory_matches_hooks_json")
    test_audit_locks_matchers_commands_and_script_names()
    print("PASS test_audit_locks_matchers_commands_and_script_names")
    test_audit_distinguishes_allowed_vs_to_move_fields_for_all_events()
    print("PASS test_audit_distinguishes_allowed_vs_to_move_fields_for_all_events")
    test_audit_contract_test_targets_exist()
    print("PASS test_audit_contract_test_targets_exist")
    test_retained_shell_wrappers_have_direct_wrapper_or_shell_contract()
    print("PASS test_retained_shell_wrappers_have_direct_wrapper_or_shell_contract")
    test_audit_maintenance_catalog_tracks_required_hot_path_candidates()
    print("PASS test_audit_maintenance_catalog_tracks_required_hot_path_candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
