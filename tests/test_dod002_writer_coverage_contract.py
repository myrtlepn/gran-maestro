from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SID = "MST-AGI-031-20260507T010203000Z-dod002aa"
OTHER_SID = "MST-AGI-031-20260507T010204000Z-dod002bb"
SOURCE_HEAD = "a" * 64
STALE_HEAD = "b" * 64
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod002"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
OWNER_PID = "818181"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK"

ALLOWED_STATUS = {
    "ok",
    "not_applicable",
    "not_seen",
    "stale",
    "identity_mismatch",
    "write_failed",
    "schema_invalid",
    "unknown",
}

REQUIRED_ROW_FIELDS = {
    "writer_id",
    "expected",
    "observed",
    "status",
    "last_event_type",
    "last_success_at",
    "last_error_at",
    "last_source_head",
    "reason",
    "evidence_path",
}

EXPECTED_STATUSES = {
    "cli_invocation": "ok",
    "state_writer": "not_seen",
    "dispatch_writer": "stale",
    "bash_history_writer": "identity_mismatch",
    "policy_writer": "write_failed",
    "stop_continuation_writer": "schema_invalid",
    "prompt_writer": "not_seen",
    "hook_lifecycle_ledger": "unknown",
}

DIAGNOSTIC_ONLY_VALUES = {
    HOOK_UUID,
    OWNER_SESSION_ID,
    TRANSCRIPT_STEM,
    OWNER_PID,
}


def _writer_coverage_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.writer_coverage")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-002 writer coverage projection module is missing: "
            "expected scripts.mst_cmds.writer_coverage"
        ) from exc


def _project_writer_coverage(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _writer_coverage_module()
    fn = getattr(module, "project_writer_coverage", None)
    assert callable(fn), "scripts.mst_cmds.writer_coverage.project_writer_coverage must be callable"
    payload = fn(fixture)
    assert isinstance(payload, dict), "writer coverage projection must return a JSON object payload"
    return payload


def _event(
    writer_id: str,
    event_type: str,
    *,
    mst_session_id: str = SID,
    source_head: str = SOURCE_HEAD,
    write_status: str = "success",
    schema_version: int = 1,
    include_event_type: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema_version": schema_version,
        "writer_id": writer_id,
        "mst_session_id": mst_session_id,
        "source_history_head": source_head,
        "created_at": f"2026-05-07T01:02:{len(writer_id) % 60:02d}.000Z",
        "write_status": write_status,
        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
    }
    if include_event_type:
        event["event_type"] = event_type
    if reason is not None:
        event["reason"] = reason
    return event


def _writer_matrix() -> list[dict[str, Any]]:
    return [
        {
            "writer_id": "cli_invocation",
            "surface": "CLI invocation writer",
            "expected": True,
            "expected_events": ["mst.invocation_start", "mst.invocation_end", "mst.invocation_error"],
            "required_when": "MST CLI command executes in canonical session",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "return_payload",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        {
            "writer_id": "state_writer",
            "surface": "state writer",
            "expected": True,
            "expected_events": ["skill.enter", "skill.step", "skill.exit"],
            "required_when": "workflow state or skill lifecycle mutates",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "return_payload",
            "evidence_path": f".gran-maestro/state/{SID}/snapshot.json",
        },
        {
            "writer_id": "dispatch_writer",
            "surface": "dispatch writer",
            "expected": True,
            "expected_events": ["dispatch.register", "dispatch.heartbeat"],
            "required_when": "dispatch task is registered or heartbeat is written",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "return_payload",
            "evidence_path": ".gran-maestro/run/dispatch-fixture.json",
        },
        {
            "writer_id": "bash_history_writer",
            "surface": "bash history writer",
            "expected": True,
            "expected_events": ["tool_call"],
            "required_when": "hooks append history or tool call diagnostics",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "process_exit_nonzero_json_emit",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        {
            "writer_id": "policy_writer",
            "surface": "policy writer",
            "expected": True,
            "expected_events": ["policy_block", "confirm_requested", "core_block", "override_granted"],
            "required_when": "policy or confirmation decisions occur",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "return_payload",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        {
            "writer_id": "stop_continuation_writer",
            "surface": "stop/continuation writer",
            "expected": True,
            "expected_events": ["continue.*", "terminal.*", "action.*", "guard.*", "context.*"],
            "required_when": "stop hook, recovery, resume, or continuation flow runs",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "process_exit_nonzero_json_emit",
            "evidence_path": f".gran-maestro/sessions/{SID}/execution-flow.json",
        },
        {
            "writer_id": "prompt_writer",
            "surface": "prompt writer",
            "expected": True,
            "expected_events": ["prompt.submitted"],
            "required_when": "UserPromptSubmit event is available",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "return_payload",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
        {
            "writer_id": "hook_lifecycle_ledger",
            "surface": "hook lifecycle ledger",
            "expected": True,
            "expected_events": ["hook.Stop.start", "hook.Stop.complete"],
            "required_when": "hook lifecycle diagnostics are enabled",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "process_exit_nonzero_json_emit",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
    ]


def _coverage_contract_fixture() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "source_history_head": SOURCE_HEAD,
        "generated_at": "2026-05-07T01:03:00.000Z",
        "identity": {
            "env": {"MST_SESSION_ID": SID, "MST_STATE_PPID": OWNER_PID},
            "context": {
                "mst_session_id": SID,
                "session_id": HOOK_UUID,
                "owner_session_id": OWNER_SESSION_ID,
                "transcript_path": f"/tmp/{TRANSCRIPT_STEM}.jsonl",
            },
            "legacy_diagnostics": {
                "hook_session_id": HOOK_UUID,
                "owner_session_id": OWNER_SESSION_ID,
                "owner_pid": OWNER_PID,
                "hook_transcript_stem": TRANSCRIPT_STEM,
            },
        },
        "writer_matrix": _writer_matrix(),
        "observed_events": [
            _event("cli_invocation", "mst.invocation_end"),
            _event("dispatch_writer", "dispatch.heartbeat", source_head=STALE_HEAD),
            _event("bash_history_writer", "tool_call", mst_session_id=OTHER_SID),
            _event(
                "policy_writer",
                "policy_block",
                write_status="error",
                reason="policy writer append failed",
            ),
            _event(
                "stop_continuation_writer",
                "continue.queued_action",
                schema_version=0,
                include_event_type=False,
                reason="event_type is required",
            ),
            _event(
                "hook_lifecycle_ledger",
                "hook.Stop.start",
                write_status="unknown",
                reason="hook lifecycle start observed without terminal completion",
            ),
        ],
        "raw_history_rows": [
            {
                "seq": index,
                "event": {"event_type": "tool_call", "args": RAW_HISTORY_SENTINEL},
            }
            for index in range(1, 40)
        ],
    }


def _writers_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    writers = payload.get("writers")
    assert isinstance(writers, list), "projection payload must expose writers as a list"
    result: dict[str, dict[str, Any]] = {}
    for row in writers:
        assert isinstance(row, dict), f"writer row must be an object: {row!r}"
        writer_id = row.get("writer_id")
        assert isinstance(writer_id, str) and writer_id.strip(), f"writer_id is required: {row!r}"
        result[writer_id] = row
    return result


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _assert_diagnostics_confined(payload: dict[str, Any]) -> None:
    violations: list[str] = []
    for path, value in _walk_json(payload):
        if value not in DIAGNOSTIC_ONLY_VALUES:
            continue
        if ".legacy_diagnostics" in path or ".diagnostics" in path:
            continue
        violations.append(f"{path} leaked diagnostic-only identity {value!r}")
    assert not violations, "\n".join(violations)


def test_writer_coverage_uses_only_canonical_mst_session_identity_and_confines_diagnostics() -> None:
    payload = _project_writer_coverage(_coverage_contract_fixture())

    assert payload["mst_session_id"] == SID
    assert payload["canonical_mst_session_id"] == SID
    assert payload.get("lookup_key", SID) in {SID, f"writer_coverage:{SID}"}
    assert payload.get("partition_key", SID) in {SID, f"writer_coverage:{SID}"}
    assert isinstance(payload.get("legacy_diagnostics"), dict)
    assert payload["legacy_diagnostics"]["hook_session_id"] == HOOK_UUID
    assert payload["legacy_diagnostics"]["owner_session_id"] == OWNER_SESSION_ID
    assert payload["legacy_diagnostics"]["owner_pid"] == OWNER_PID
    assert payload["legacy_diagnostics"]["hook_transcript_stem"] == TRANSCRIPT_STEM
    _assert_diagnostics_confined(payload)


def test_writer_coverage_rows_have_required_fields_and_allowed_status_enum() -> None:
    payload = _project_writer_coverage(_coverage_contract_fixture())
    writers = _writers_by_id(payload)

    assert set(writers) == set(EXPECTED_STATUSES)
    for writer_id, row in writers.items():
        assert REQUIRED_ROW_FIELDS <= row.keys(), f"{writer_id} missing fields: {REQUIRED_ROW_FIELDS - row.keys()}"
        assert isinstance(row["expected"], bool), f"{writer_id}.expected must be boolean"
        assert isinstance(row["observed"], bool), f"{writer_id}.observed must be boolean"
        assert row["status"] in ALLOWED_STATUS, f"{writer_id} emitted invalid status {row['status']!r}"
        assert row["status"] == EXPECTED_STATUSES[writer_id]


def test_writer_coverage_distinguishes_each_missing_log_status_with_reason_and_evidence_path() -> None:
    payload = _project_writer_coverage(_coverage_contract_fixture())
    writers = _writers_by_id(payload)

    for writer_id, expected_status in EXPECTED_STATUSES.items():
        row = writers[writer_id]
        assert row["status"] == expected_status
        if expected_status == "ok":
            assert row["last_success_at"], "ok writer must expose last_success_at"
            assert row["last_error_at"] is None
            continue

        assert isinstance(row["reason"], str) and row["reason"].strip(), f"{writer_id} reason is required"
        assert isinstance(row["evidence_path"], str) and row["evidence_path"].strip(), (
            f"{writer_id} evidence_path is required"
        )

    assert writers["dispatch_writer"]["last_source_head"] == STALE_HEAD
    assert writers["policy_writer"]["last_error_at"], "write_failed writer must expose last_error_at"
    assert writers["stop_continuation_writer"]["last_event_type"] is None


def test_writer_coverage_keeps_not_applicable_separate_from_expected_but_unobserved() -> None:
    payload = _project_writer_coverage(_coverage_contract_fixture())
    writers = _writers_by_id(payload)

    state = writers["state_writer"]
    prompt = writers["prompt_writer"]

    assert state["expected"] is True
    assert state["observed"] is False
    assert state["status"] == "not_seen"

    assert prompt["expected"] is True
    assert prompt["observed"] is False
    assert prompt["status"] == "not_seen"
    assert "matching event" in prompt["reason"].lower()


def test_writer_coverage_payload_is_bounded_and_excludes_raw_history_full_payload() -> None:
    payload = _project_writer_coverage(_coverage_contract_fixture())
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    assert RAW_HISTORY_SENTINEL not in encoded
    assert "raw_history_rows" not in payload
    assert "history_rows" not in payload
    assert "observed_events" not in payload
    assert "raw_history" not in payload
    assert len(encoded) < 12000

    assert payload["source_history_head"] == SOURCE_HEAD
    assert isinstance(payload["generated_at"], str) and payload["generated_at"].strip()
    summary = payload.get("summary")
    assert isinstance(summary, dict), "bounded payload must include summary counts"
    assert summary["total"] == len(EXPECTED_STATUSES)
    assert summary["ok"] == 1
    assert summary["not_applicable"] == 0
    assert summary["non_ok"] == len(EXPECTED_STATUSES) - 1


def test_debug_route_exposes_read_only_bounded_writer_coverage_projection() -> None:
    route_source = Path("src/routes/debug.ts").read_text(encoding="utf-8")

    assert 'projectDebugApi.get("/debug/writer-coverage"' in route_source
    assert 'projectDebugApi.get("/debug/:debugId"' in route_source
    assert route_source.index('projectDebugApi.get("/debug/writer-coverage"') < route_source.index(
        'projectDebugApi.get("/debug/:debugId"'
    )
    assert "projectWriterCoverage" in route_source
    assert "sanitizeWriterCoveragePayload" in route_source
    assert "raw_history_rows" not in route_source
    assert "history_rows" not in route_source
    assert "readJsonFile" in route_source
    assert "writeJsonFile" not in route_source
    assert "Deno.writeTextFile" not in route_source
