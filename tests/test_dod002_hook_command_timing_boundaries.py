from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = (
    REPO_ROOT
    / ".gran-maestro"
    / "requests"
    / "REQ-899"
    / "evidence"
    / "dod-002-hook-command-boundary-evidence.json"
)
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"

EXPECTED_BOUNDARY_IDS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse:Skill",
    "PreToolUse:ScheduleWakeup",
    "CommandMutation",
    "Stop",
]
REQUIRED_COMMAND_IDS = {
    "mst_cli_invocation",
    "state_set",
    "state_set_workflow",
}
UNSUPPORTED_COMPLETION_COMMAND_IDS = {
    "agile_objective_transition",
}
ALLOWED_SEVERITIES = {"info", "low", "medium", "high", "critical"}
ALLOWED_GAP_KINDS = {"cross_reference", "follow_up"}
REQUIRED_BOUNDARY_FIELDS = {
    "boundary_id",
    "order",
    "event",
    "trigger",
    "input",
    "output",
    "allowed_side_effects",
    "forbidden_side_effects",
    "failure_policy",
    "evidence_ref",
}
REQUIRED_COMMAND_GUARD_FIELDS = {
    "mst_session_id",
    "history_head_before",
    "history_head_after",
    "idempotency_key",
    "guard_result",
}


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), path
    return payload


def _stdout_json(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, stdout
    payload = json.loads(lines[-1])
    assert isinstance(payload, dict), stdout
    return payload


def _artifact() -> dict:
    return _load_json(ARTIFACT)


def _assert_local_evidence_refs_exist(value) -> None:
    if isinstance(value, dict):
        refs = value.get("evidence_ref")
        if refs is not None:
            assert isinstance(refs, list) and refs
            for ref in refs:
                assert isinstance(ref, str) and ref.strip()
                assert not Path(ref).is_absolute(), ref
                assert (REPO_ROOT / ref).exists(), ref
        for child in value.values():
            _assert_local_evidence_refs_exist(child)
    elif isinstance(value, list):
        for child in value:
            _assert_local_evidence_refs_exist(child)


def test_dod002_artifact_has_required_schema_and_paths() -> None:
    payload = _artifact()

    assert ARTIFACT.is_file(), ARTIFACT
    assert {
        "artifact_id",
        "request_id",
        "task_id",
        "agi_id",
        "plan_id",
        "dod_id",
        "status",
        "format_version",
        "generated_at",
        "request_evidence_path",
        "hook_manifest_ref",
        "plugin_hook_pointer",
        "checked_boundaries",
        "checked_commands",
        "gaps",
        "severity",
        "evidence_ref",
        "recommended_action",
    } <= payload.keys()
    assert payload["request_id"] == "REQ-899"
    assert payload["task_id"] == "01"
    assert payload["agi_id"] == "AGI-041"
    assert payload["plan_id"] == "PLN-726"
    assert payload["dod_id"] == "DOD-002"
    assert payload["request_evidence_path"] == (
        ".gran-maestro/requests/REQ-899/evidence/dod-002-hook-command-boundary-evidence.json"
    )
    assert payload["hook_manifest_ref"] == "hooks/hooks.json"
    assert payload["plugin_hook_pointer"] == ".claude-plugin/plugin.json::hooks"
    assert payload["severity"] in ALLOWED_SEVERITIES
    assert isinstance(payload["recommended_action"], str) and payload["recommended_action"].strip()
    _assert_local_evidence_refs_exist(payload)


def test_dod002_boundaries_follow_canonical_manifest_order() -> None:
    payload = _artifact()
    plugin_payload = _load_json(PLUGIN_JSON)
    hooks_payload = _load_json(HOOKS_JSON)
    boundaries = payload["checked_boundaries"]

    assert plugin_payload["hooks"] == "./hooks/hooks.json"
    assert [entry["boundary_id"] for entry in boundaries] == EXPECTED_BOUNDARY_IDS
    assert "SubagentStop" not in hooks_payload["hooks"]

    hook_entries = {entry["boundary_id"]: entry for entry in boundaries if entry["boundary_id"] != "CommandMutation"}
    expected_commands = {
        "SessionStart": ("SessionStart", "", "${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh"),
        "UserPromptSubmit": ("UserPromptSubmit", "", "${CLAUDE_PLUGIN_ROOT}/hooks/mst-auto-chain-context.sh"),
        "PreToolUse:Skill": ("PreToolUse", "Skill", "${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh"),
        "PreToolUse:ScheduleWakeup": (
            "PreToolUse",
            "ScheduleWakeup",
            "${CLAUDE_PLUGIN_ROOT}/hooks/mst-pre-tool-use.sh",
        ),
        "Stop": ("Stop", "", "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"),
    }

    for entry in boundaries:
        assert REQUIRED_BOUNDARY_FIELDS <= entry.keys()
        assert isinstance(entry["allowed_side_effects"], list) and entry["allowed_side_effects"]
        assert isinstance(entry["forbidden_side_effects"], list) and entry["forbidden_side_effects"]
        if "command" in entry:
            assert ".claude/hooks" not in str(entry["command"])
        assert isinstance(entry["evidence_ref"], list) and entry["evidence_ref"]

    for boundary_id, (event, matcher, command) in expected_commands.items():
        entry = hook_entries[boundary_id]
        assert entry["event"] == event
        assert entry.get("matcher", "") == matcher
        assert entry["command"] == command

        registrations = hooks_payload["hooks"][event]
        matched = [
            hook.get("command", "")
            for registration in registrations
            if registration.get("matcher", "") == matcher
            for hook in registration.get("hooks", [])
        ]
        assert matched == [command]

    command_boundary = payload["checked_boundaries"][4]
    assert command_boundary["event"] == "CommandMutation"
    assert command_boundary["entrypoint"] == "scripts/mst.py"
    assert "PreToolUse matcher outside" in command_boundary["trigger"]


def test_dod002_command_contracts_cover_cli_mutation_and_guard_evidence() -> None:
    payload = _artifact()
    commands = payload["checked_commands"]
    by_id = {entry["command_id"]: entry for entry in commands}

    assert REQUIRED_COMMAND_IDS <= set(by_id)
    assert set(by_id).isdisjoint(UNSUPPORTED_COMPLETION_COMMAND_IDS)

    for entry in commands:
        assert Path(REPO_ROOT / entry["source_path"]).is_file(), entry["source_path"]
        assert isinstance(entry["command_patterns"], list) and entry["command_patterns"]
        assert isinstance(entry["evidence_ref"], list) and entry["evidence_ref"]
        invocation = entry["invocation_events"]
        assert invocation["required"] == [
            "mst.invocation_start",
            "mst.invocation_end",
            "mst.invocation_error",
        ]
        assert {"mst_session_id", "idempotency_key"} <= set(invocation["required_fields"])
        guard = entry["guard_evidence"]
        if entry["command_id"] in REQUIRED_COMMAND_IDS:
            assert REQUIRED_COMMAND_GUARD_FIELDS <= set(guard["required_fields"])
            assert guard["on_identity_mismatch"] in {"structured_reject", "inspect_only"}
            assert guard["on_history_head_mismatch"] in {"structured_reject", "inspect_only"}


def test_dod002_subagent_exclusion_and_cross_dod_gaps_remain_non_completion_only() -> None:
    payload = _artifact()
    subagent = payload["subagent_boundary"]
    gaps = payload["gaps"]

    assert subagent["registered_in_hooks_manifest"] is False
    assert subagent["registered_in_plugin_pointer"] is False
    assert subagent["parent_direct_mutation_allowed"] is False
    assert isinstance(subagent["parent_reconciliation_paths"], list)
    assert {"Skill", "Stop", "command"} <= set(subagent["parent_reconciliation_paths"])

    unsupported_titles = {
        "agile objective-transition command guard coverage is not completion evidence",
    }
    seen_unsupported_follow_up = set()

    for gap in gaps:
        assert gap["kind"] in ALLOWED_GAP_KINDS
        assert gap["related_dod"] in {"DOD-002", "DOD-004", "DOD-005"}
        assert gap["severity"] in ALLOWED_SEVERITIES
        assert isinstance(gap["recommended_action"], str) and gap["recommended_action"].strip()
        if gap["title"] in unsupported_titles:
            assert gap["kind"] == "follow_up"
            assert gap["related_dod"] == "DOD-002"
            seen_unsupported_follow_up.add(gap["title"])

    assert seen_unsupported_follow_up == unsupported_titles


def test_missing_canonical_session_rejects_state_mutation_without_snapshot_write() -> None:
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        (workspace / ".gran-maestro").mkdir()
        home = workspace / "home"
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["MST_CLAUDE_HOME"] = str(home)
        env["MST_POLICY_HOME"] = str(workspace / ".gran-maestro" / "policy")
        env["MST_FLOW_DISABLE_ATEXIT"] = "1"
        env.pop("MST_SESSION_ID", None)
        env.pop("MST_CONTEXT_JSON", None)

        result = subprocess.run(
            [
                sys.executable,
                str(MST_SCRIPT),
                "state",
                "set",
                "--skill",
                "mst:test",
                "--step",
                "0",
                "--total",
                "1",
                "--return-to",
                "mst:plan/step-1",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        assert result.returncode == 1, result.stdout + result.stderr
        payload = _stdout_json(result.stdout)
        assert payload["code"] == "missing_canonical_mst_session_id"
        assert payload["mutation_performed"] is False
        assert payload["created_new_session"] is False
        assert payload["canonical_mst_session_id"] is None
        assert not list((workspace / ".gran-maestro" / "state").glob("**/snapshot.json"))


def test_canonical_cli_invocation_appends_start_and_end_history_events() -> None:
    session_id = "MST-AGI-041-20260520T010203000Z-dod002aa"
    root_mst_id = "AGI-041"

    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        session_dir = workspace / ".gran-maestro" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mst_session_id": session_id,
                    "root_mst_id": root_mst_id,
                }
            )
            + "\n",
            encoding="utf-8",
        )

        home = workspace / "home"
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["MST_CLAUDE_HOME"] = str(home)
        env["MST_POLICY_HOME"] = str(workspace / ".gran-maestro" / "policy")
        env["MST_FLOW_DISABLE_ATEXIT"] = "1"
        env["MST_SESSION_ID"] = session_id
        env["MST_CONTEXT_JSON"] = json.dumps(
            {
                "schema_version": 1,
                "mst_session_id": session_id,
                "root_mst_id": root_mst_id,
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                str(MST_SCRIPT),
                "history",
                "head",
                "--session",
                session_id,
                "--json",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        history_rows = [
            json.loads(line)
            for line in (session_dir / "history.ndjson").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        invocation_events = [
            row["event"]
            for row in history_rows
            if str(row.get("event", {}).get("event_type", "")).startswith("mst.invocation_")
        ]
        assert {event["event_type"] for event in invocation_events} >= {
            "mst.invocation_start",
            "mst.invocation_end",
        }
        for event in invocation_events:
            assert event["mst_session_id"] == session_id
            assert event["root_mst_id"] == root_mst_id
            assert isinstance(event["idempotency_key"], str) and event["idempotency_key"].strip()
