from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


SID = "MST-AGI-031-20260507T030405000Z-dod004aa"
OTHER_SID = "MST-AGI-031-20260507T030406000Z-dod004bb"
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session-dod004"
TRANSCRIPT_STEM = "66666666-7777-4888-9999-aaaaaaaaaaaa"
TRANSCRIPT_PATH = f"/tmp/{TRANSCRIPT_STEM}.jsonl"
OWNER_PID = "737373"
OWNER_PPID = "747474"
SNAPSHOT_ALIAS = "legacy-snapshot-alias-dod004"
HEAD_BEFORE = "a" * 64
HEAD_AFTER_PROMPT = "b" * 64
HEAD_AFTER_TOOL = "c" * 64
HEAD_AFTER_POLICY = "d" * 64
ZERO_HASH = "0" * 64
RAW_PROMPT_TAIL_SENTINEL = "RAW_PROMPT_TAIL_SENTINEL_MUST_NOT_LEAK_DOD004"
RAW_TRANSCRIPT_SENTINEL = "RAW_TRANSCRIPT_SENTINEL_MUST_NOT_LEAK_DOD004"
RAW_HISTORY_SENTINEL = "RAW_HISTORY_SENTINEL_MUST_NOT_LEAK_DOD004"
SOURCE = "UserPromptSubmit"


FORBIDDEN_RESPONSE_KEYS = {
    "raw_prompt",
    "raw_prompt_text",
    "prompt",
    "prompt_text",
    "full_prompt",
    "full_prompt_text",
    "raw_transcript",
    "transcript",
    "transcript_text",
    "raw_transcript_content",
    "raw_history",
    "raw_history_rows",
    "history_rows",
    "ledger_rows",
    "full_history",
    "full_history_events",
    "full_history_payload",
    "full_history_event_payload",
    "llm_summary",
    "semantic_summary",
    "prompt_summary",
}

DIAGNOSTIC_ONLY_VALUES = {
    HOOK_UUID,
    OWNER_SESSION_ID,
    TRANSCRIPT_STEM,
    OWNER_PID,
    OWNER_PPID,
    SNAPSHOT_ALIAS,
}

REQUIRED_EVENT_FIELDS = {
    "event_type",
    "type",
    "created_at",
    "mst_session_id",
    "prompt_digest",
    "prompt_size_bytes",
    "prompt_excerpt",
    "transcript_path",
    "history_head_before",
    "idempotency_key",
    "source",
}

PROMPT_WRITER_STATUS = {
    "ok",
    "not_seen",
    "write_failed",
    "schema_invalid",
    "identity_mismatch",
    "unknown",
}

CORRELATION_BASIS = {"ledger_order", "timestamp", "head_relation"}


def _prompt_module() -> object:
    try:
        return importlib.import_module("scripts.mst_cmds.prompt_correlation")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "DOD-004 prompt correlation module is missing: "
            "expected scripts.mst_cmds.prompt_correlation"
        ) from exc


def _build_prompt_submitted_event(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _prompt_module()
    fn = getattr(module, "build_prompt_submitted_event", None)
    assert callable(fn), (
        "scripts.mst_cmds.prompt_correlation.build_prompt_submitted_event "
        "must be callable"
    )
    payload = fn(fixture)
    assert isinstance(payload, dict), "prompt.submitted event builder must return a JSON object"
    return payload


def _append_prompt_submitted(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _prompt_module()
    fn = getattr(module, "append_prompt_submitted", None)
    assert callable(fn), (
        "scripts.mst_cmds.prompt_correlation.append_prompt_submitted "
        "must be callable"
    )
    payload = fn(fixture)
    assert isinstance(payload, dict), "prompt append result must return a JSON object"
    return payload


def _project_prompt_timeline(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _prompt_module()
    fn = getattr(module, "project_prompt_timeline", None)
    assert callable(fn), (
        "scripts.mst_cmds.prompt_correlation.project_prompt_timeline "
        "must be callable"
    )
    payload = fn(fixture)
    assert isinstance(payload, dict), "prompt timeline projection must return a JSON object"
    return payload


def _project_writer_coverage(fixture: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module("scripts.mst_cmds.writer_coverage")
    fn = getattr(module, "project_writer_coverage", None)
    assert callable(fn), "scripts.mst_cmds.writer_coverage.project_writer_coverage must be callable"
    payload = fn(fixture)
    assert isinstance(payload, dict)
    return payload


def _identity_context(*, env_sid: str | None = SID, structured_sid: str | None = SID) -> dict[str, Any]:
    env: dict[str, Any] = {
        "MST_STATE_PPID": OWNER_PID,
        "MST_SNAPSHOT_SESSION_ID": SNAPSHOT_ALIAS,
    }
    if env_sid is not None:
        env["MST_SESSION_ID"] = env_sid
    context: dict[str, Any] = {
        "session_id": HOOK_UUID,
        "owner_session_id": OWNER_SESSION_ID,
        "owner_pid": OWNER_PID,
        "pid": OWNER_PID,
        "ppid": OWNER_PPID,
        "transcript_path": TRANSCRIPT_PATH,
    }
    if structured_sid is not None:
        context["mst_session_id"] = structured_sid
    return {
        "env": env,
        "context": context,
        "legacy_diagnostics": {
            "hook_session_id": HOOK_UUID,
            "owner_session_id": OWNER_SESSION_ID,
            "owner_pid": OWNER_PID,
            "owner_ppid": OWNER_PPID,
            "snapshot_session_id": SNAPSHOT_ALIAS,
            "hook_transcript_stem": TRANSCRIPT_STEM,
        },
    }


def _prompt_text() -> str:
    return (
        "DOD-004 prompt correlation regression fixture. "
        "Keep only a bounded excerpt in event and debug payloads. "
        + ("repeat-block " * 40)
        + RAW_PROMPT_TAIL_SENTINEL
    )


def _digest(prompt_text: str) -> str:
    return "sha256:" + hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def _idempotency_key(*, sid: str = SID, digest: str, head: str | None = HEAD_BEFORE) -> str:
    head_value = head if head is not None else "null"
    return f"{sid}:prompt.submitted:{digest}:head={head_value}:source={SOURCE}"


def _base_fixture(**overrides: Any) -> dict[str, Any]:
    prompt_text = overrides.pop("prompt_text", _prompt_text())
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "created_at": "2026-05-07T03:04:05.000Z",
        "identity": _identity_context(),
        "prompt_text": prompt_text,
        "transcript_path": TRANSCRIPT_PATH,
        "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        "history_head_before": HEAD_BEFORE,
        "source": SOURCE,
        "excerpt_max_chars": 240,
        "raw_history_rows": [
            {
                "seq": 1,
                "event_hash": HEAD_BEFORE,
                "prev_hash": ZERO_HASH,
                "event": {"event_type": "skill.step", "payload": RAW_HISTORY_SENTINEL},
            }
        ],
    }
    fixture.update(overrides)
    return fixture


def _walk_json(value: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _assert_no_forbidden_payload_leak(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert RAW_PROMPT_TAIL_SENTINEL not in encoded
    assert RAW_TRANSCRIPT_SENTINEL not in encoded
    assert RAW_HISTORY_SENTINEL not in encoded

    forbidden_hits: list[str] = []
    for path, value in _walk_json(payload):
        if isinstance(value, dict):
            for key in value:
                if key in FORBIDDEN_RESPONSE_KEYS:
                    forbidden_hits.append(f"{path}.{key}")
    assert not forbidden_hits, "forbidden raw or summary payload keys leaked: " + ", ".join(forbidden_hits)


def _assert_diagnostic_values_not_used_as_canonical_material(payload: dict[str, Any]) -> None:
    for field in (
        "mst_session_id",
        "canonical_mst_session_id",
        "lookup_key",
        "partition_key",
        "repair_source",
        "migration_source",
        "idempotency_source",
    ):
        value = payload.get(field)
        if value is not None:
            assert value not in DIAGNOSTIC_ONLY_VALUES, f"{field} used diagnostic-only identity {value!r}"

    key = str(payload.get("idempotency_key") or "")
    assert key, "idempotency_key is required"
    for value in DIAGNOSTIC_ONLY_VALUES:
        assert value not in key, f"idempotency_key used diagnostic-only material {value!r}"


def _assert_prompt_event_contract(event: dict[str, Any], *, prompt_text: str, head: str | None = HEAD_BEFORE) -> None:
    expected_digest = _digest(prompt_text)

    assert REQUIRED_EVENT_FIELDS <= event.keys(), f"missing event fields: {REQUIRED_EVENT_FIELDS - event.keys()}"
    assert event["event_type"] == "prompt.submitted"
    assert event["type"] == "prompt.submitted"
    assert event["mst_session_id"] == SID
    assert event["prompt_digest"] == expected_digest
    assert event["prompt_size_bytes"] == len(prompt_text.encode("utf-8"))
    assert event["transcript_path"] == TRANSCRIPT_PATH
    assert event["history_head_before"] == head
    assert event["idempotency_key"] == _idempotency_key(digest=expected_digest, head=head)
    assert event["source"] == SOURCE
    assert isinstance(event["created_at"], str) and event["created_at"].strip()

    excerpt = event["prompt_excerpt"]
    assert isinstance(excerpt, dict), "prompt_excerpt must be bounded metadata object"
    assert isinstance(excerpt.get("text"), str)
    assert isinstance(excerpt.get("max_chars"), int)
    assert excerpt["max_chars"] <= 240
    assert len(excerpt["text"]) <= excerpt["max_chars"]
    assert excerpt.get("truncated") is True
    assert isinstance(excerpt.get("omitted_bytes"), int) and excerpt["omitted_bytes"] > 0

    _assert_no_forbidden_payload_leak(event)
    _assert_diagnostic_values_not_used_as_canonical_material(event)


def _writer_matrix() -> list[dict[str, Any]]:
    return [
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
            "expected_events": ["hook.UserPromptSubmit.start", "hook.UserPromptSubmit.complete"],
            "required_when": "UserPromptSubmit hook lifecycle diagnostics are enabled",
            "identity_classification": "canonical selector + diagnostics",
            "delivery_type": "process_exit_nonzero_json_emit",
            "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
        },
    ]


def _coverage_fixture(*events: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "source_history_head": HEAD_BEFORE,
        "generated_at": "2026-05-07T03:04:06.000Z",
        "identity": _identity_context(),
        "writer_matrix": _writer_matrix(),
        "observed_events": list(events),
    }


def _event(
    event_type: str,
    *,
    writer_id: str,
    mst_session_id: str = SID,
    source_head: str = HEAD_BEFORE,
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
        "created_at": "2026-05-07T03:04:06.000Z",
        "write_status": write_status,
        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
    }
    if include_event_type:
        event["event_type"] = event_type
    if reason:
        event["reason"] = reason
    return event


def _writers_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    writers = payload.get("writers")
    assert isinstance(writers, list)
    return {str(row["writer_id"]): row for row in writers if isinstance(row, dict) and "writer_id" in row}


def _prompt_event_for_timeline() -> dict[str, Any]:
    prompt_text = _prompt_text()
    return {
        "schema_version": 1,
        "event_type": "prompt.submitted",
        "type": "prompt.submitted",
        "created_at": "2026-05-07T03:04:05.000Z",
        "mst_session_id": SID,
        "prompt_digest": _digest(prompt_text),
        "prompt_size_bytes": len(prompt_text.encode("utf-8")),
        "prompt_excerpt": {
            "text": prompt_text[:80],
            "max_chars": 80,
            "truncated": True,
            "omitted_bytes": len(prompt_text.encode("utf-8")) - len(prompt_text[:80].encode("utf-8")),
        },
        "transcript_path": TRANSCRIPT_PATH,
        "history_head_before": HEAD_BEFORE,
        "idempotency_key": _idempotency_key(digest=_digest(prompt_text), head=HEAD_BEFORE),
        "source": SOURCE,
    }


def _history_row(seq: int, prev_hash: str, event_hash: str, event: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "seq": seq,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "timestamp": event.get("created_at", f"2026-05-07T03:04:{seq:02d}.000Z"),
        "event_type": event["event_type"],
        "mst_session_id": event.get("mst_session_id", SID),
        "event": event,
    }


def test_prompt_submitted_event_schema_uses_canonical_env_identity_and_confines_diagnostics() -> None:
    prompt_text = _prompt_text()
    event = _build_prompt_submitted_event(_base_fixture(prompt_text=prompt_text))

    _assert_prompt_event_contract(event, prompt_text=prompt_text)
    assert event.get("canonical_mst_session_id", SID) == SID
    assert event.get("lookup_key", SID) in {SID, f"prompt:{SID}"}
    assert event.get("partition_key", SID) in {SID, f"prompt:{SID}"}


def test_prompt_submitted_event_allows_structured_mst_session_id_when_env_is_absent() -> None:
    prompt_text = _prompt_text()
    event = _build_prompt_submitted_event(
        _base_fixture(
            prompt_text=prompt_text,
            identity=_identity_context(env_sid=None, structured_sid=SID),
        )
    )

    _assert_prompt_event_contract(event, prompt_text=prompt_text)


def test_prompt_writer_rejects_missing_canonical_identity_without_legacy_fallback() -> None:
    result = _append_prompt_submitted(
        _base_fixture(identity=_identity_context(env_sid=None, structured_sid=None))
    )

    assert result["status"] == "error"
    assert result["code"] == "missing_canonical_mst_session_id"
    assert result.get("mutation_performed") is False
    assert result.get("appended") is False
    assert result.get("event") is None
    assert isinstance(result.get("legacy_diagnostics"), dict)
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    assert HOOK_UUID in encoded
    assert TRANSCRIPT_STEM in encoded
    assert f"/sessions/{HOOK_UUID}/" not in encoded
    assert f"/sessions/{TRANSCRIPT_STEM}/" not in encoded
    _assert_no_forbidden_payload_leak(result)


def test_prompt_writer_reports_canonical_diagnostic_mismatch_without_mutation() -> None:
    result = _append_prompt_submitted(
        _base_fixture(identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID))
    )

    assert result["status"] == "error"
    assert result["code"] in {"mst_session_id_mismatch", "identity_mismatch"}
    assert result.get("mutation_performed") is False
    assert result.get("appended") is False
    assert result.get("event") is None
    _assert_no_forbidden_payload_leak(result)


def test_prompt_digest_size_and_bounded_excerpt_are_derived_from_original_prompt_bytes() -> None:
    prompt_text = _prompt_text()
    event = _build_prompt_submitted_event(_base_fixture(prompt_text=prompt_text))

    assert event["prompt_digest"] == _digest(prompt_text)
    assert event["prompt_size_bytes"] == len(prompt_text.encode("utf-8"))
    excerpt = event["prompt_excerpt"]
    assert excerpt["text"] == prompt_text[: excerpt["max_chars"]]
    assert RAW_PROMPT_TAIL_SENTINEL not in excerpt["text"]
    _assert_prompt_event_contract(event, prompt_text=prompt_text)


def test_transcript_path_is_preserved_without_raw_transcript_or_full_prompt_payload() -> None:
    prompt_text = _prompt_text()
    event = _build_prompt_submitted_event(_base_fixture(prompt_text=prompt_text))

    assert event["transcript_path"] == TRANSCRIPT_PATH
    assert Path(event["transcript_path"]).name == f"{TRANSCRIPT_STEM}.jsonl"
    _assert_no_forbidden_payload_leak(event)
    _assert_diagnostic_values_not_used_as_canonical_material(event)


def test_history_head_before_null_and_non_null_idempotency_keys_are_deterministic() -> None:
    prompt_text = _prompt_text()
    digest = _digest(prompt_text)

    with_head = _build_prompt_submitted_event(_base_fixture(prompt_text=prompt_text, history_head_before=HEAD_BEFORE))
    without_head = _build_prompt_submitted_event(
        _base_fixture(prompt_text=prompt_text, history_head_before=None, raw_history_rows=[])
    )
    invalid_head = _build_prompt_submitted_event(
        _base_fixture(prompt_text=prompt_text, history_head_before="not-a-validated-ledger-head")
    )

    assert with_head["history_head_before"] == HEAD_BEFORE
    assert with_head["idempotency_key"] == _idempotency_key(digest=digest, head=HEAD_BEFORE)
    assert without_head["history_head_before"] is None
    assert without_head["idempotency_key"] == _idempotency_key(digest=digest, head=None)
    assert invalid_head["history_head_before"] is None
    assert invalid_head["idempotency_key"] == _idempotency_key(digest=digest, head=None)
    for value in DIAGNOSTIC_ONLY_VALUES:
        assert value not in with_head["idempotency_key"]
        assert value not in without_head["idempotency_key"]


def test_duplicate_retry_is_idempotent_and_does_not_append_duplicate_semantic_event() -> None:
    fixture = _base_fixture()
    first = _append_prompt_submitted(fixture)
    retry = _append_prompt_submitted({**fixture, "history_rows": first.get("history_rows", [])})

    assert first["status"] == "ok"
    assert first["appended"] is True
    assert first["duplicate"] is False
    assert retry["status"] == "ok"
    assert retry["appended"] is False
    assert retry["duplicate"] is True
    assert retry["event"]["idempotency_key"] == first["event"]["idempotency_key"]
    assert retry.get("history_head_after") == first.get("history_head_after")


def test_lifecycle_only_prompt_submit_is_not_prompt_writer_success() -> None:
    payload = _project_writer_coverage(
        _coverage_fixture(
            _event("hook.UserPromptSubmit.start", writer_id="hook_lifecycle_ledger"),
            _event("hook.UserPromptSubmit.complete", writer_id="hook_lifecycle_ledger"),
        )
    )
    writers = _writers_by_id(payload)

    assert writers["hook_lifecycle_ledger"]["status"] == "ok"
    assert writers["prompt_writer"]["expected"] is True
    assert writers["prompt_writer"]["observed"] is False
    assert writers["prompt_writer"]["status"] == "not_seen"
    assert writers["prompt_writer"]["status"] != writers["hook_lifecycle_ledger"]["status"]


def test_prompt_writer_failure_schema_invalid_and_identity_mismatch_statuses_are_structured() -> None:
    cases = {
        "write_failed": _event(
            "prompt.submitted",
            writer_id="prompt_writer",
            write_status="error",
            reason="semantic prompt append failed",
        ),
        "schema_invalid": _event(
            "prompt.submitted",
            writer_id="prompt_writer",
            include_event_type=False,
            schema_version=0,
            reason="event_type is required",
        ),
        "identity_mismatch": _event("prompt.submitted", writer_id="prompt_writer", mst_session_id=OTHER_SID),
    }

    for expected_status, event in cases.items():
        payload = _project_writer_coverage(_coverage_fixture(event))
        writer = _writers_by_id(payload)["prompt_writer"]
        assert writer["status"] == expected_status
        assert writer["status"] in PROMPT_WRITER_STATUS
        assert isinstance(writer["reason"], str) and writer["reason"].strip()
        assert isinstance(writer["evidence_path"], str) and writer["evidence_path"].strip()


def test_append_failure_is_non_success_without_repair_or_synthetic_prompt_event() -> None:
    result = _append_prompt_submitted(_base_fixture(simulate_append_failure=True))

    assert result["status"] == "error"
    assert result["code"] == "write_failed"
    assert result.get("appended") is False
    assert result.get("mutation_performed") is False
    assert result.get("repair_performed") is not True
    assert result.get("synthetic_replacement_event_created") is not True
    assert result.get("event", {}).get("event_type") != "prompt.submitted.synthetic"
    _assert_no_forbidden_payload_leak(result)


def test_prompt_timeline_correlation_uses_ledger_order_timestamp_and_head_relation_only() -> None:
    prompt_event = _prompt_event_for_timeline()
    rows = [
        _history_row(
            1,
            ZERO_HASH,
            HEAD_BEFORE,
            {
                "event_type": "skill.step",
                "created_at": "2026-05-07T03:04:04.000Z",
                "mst_session_id": SID,
                "idempotency_key": f"{SID}:skill.step:fixture",
            },
        ),
        _history_row(2, HEAD_BEFORE, HEAD_AFTER_PROMPT, prompt_event),
        _history_row(
            3,
            HEAD_AFTER_PROMPT,
            HEAD_AFTER_TOOL,
            {
                "event_type": "tool_call",
                "created_at": "2026-05-07T03:04:06.000Z",
                "mst_session_id": SID,
                "tool": "Bash",
                "args_sha256": "sha256:" + "e" * 64,
                "payload": RAW_HISTORY_SENTINEL,
                "idempotency_key": f"{SID}:tool_call:fixture",
            },
        ),
        _history_row(
            4,
            HEAD_AFTER_TOOL,
            HEAD_AFTER_POLICY,
            {
                "event_type": "policy_block",
                "created_at": "2026-05-07T03:04:07.000Z",
                "mst_session_id": SID,
                "policy": "core",
                "idempotency_key": f"{SID}:policy_block:fixture",
            },
        ),
    ]
    payload = _project_prompt_timeline(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "generated_at": "2026-05-07T03:04:08.000Z",
            "source_history_head": HEAD_AFTER_POLICY,
            "current_history_head": HEAD_AFTER_POLICY,
            "identity": _identity_context(),
            "history_rows": rows,
            "writer_coverage": {
                "writers": [
                    {
                        "writer_id": "prompt_writer",
                        "expected": True,
                        "observed": True,
                        "status": "ok",
                        "evidence_path": f".gran-maestro/sessions/{SID}/history.ndjson",
                    }
                ]
            },
            "raw_transcript": RAW_TRANSCRIPT_SENTINEL,
        }
    )

    assert payload["schema_version"] == 1
    assert payload["mst_session_id"] == SID
    assert set(payload["correlation_basis"]) == CORRELATION_BASIS
    assert payload["projection_freshness"]["status"] == "fresh"
    assert payload["source_head"] == HEAD_AFTER_POLICY
    assert isinstance(payload["evidence_paths"], list) and payload["evidence_paths"]

    anchors = payload["prompt_anchors"]
    assert isinstance(anchors, dict)
    assert anchors["max_items"] <= 20
    assert anchors["total"] == 1
    assert anchors["truncated"] is False
    anchor = anchors["items"][0]
    assert anchor["event_type"] == "prompt.submitted"
    assert anchor["prompt_digest"] == prompt_event["prompt_digest"]
    assert anchor["prompt_size_bytes"] == prompt_event["prompt_size_bytes"]
    assert anchor["transcript_path"] == TRANSCRIPT_PATH
    assert anchor["history_head_before"] == HEAD_BEFORE
    assert anchor["idempotency_key"] == prompt_event["idempotency_key"]
    assert anchor["source"] == SOURCE

    following = anchor["following_events"]
    assert following["max_items"] <= 50
    assert following["total"] == 2
    assert following["items"][0]["event_type"] == "tool_call"
    assert following["items"][0]["seq"] > anchor["seq"]
    assert following["items"][0]["prev_hash"] == HEAD_AFTER_PROMPT
    assert anchor["first_semantic_event"]["event_type"] == "tool_call"
    assert payload["policy_block_indicators"]["count"] == 1
    assert payload["core_block_indicators"]["count"] == 0
    assert payload.get("correlation_summary_source") != "llm"
    _assert_no_forbidden_payload_leak(payload)


def test_prompt_timeline_projection_rebounds_prompt_excerpt() -> None:
    prompt_event = _prompt_event_for_timeline()
    prompt_event["prompt_excerpt"] = {
        "text": "x" * 400 + RAW_PROMPT_TAIL_SENTINEL,
        "max_chars": 9999,
        "truncated": False,
        "omitted_bytes": 0,
    }
    rows = [_history_row(1, ZERO_HASH, HEAD_AFTER_PROMPT, prompt_event)]

    payload = _project_prompt_timeline(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "identity": _identity_context(),
            "history_rows": rows,
        }
    )

    excerpt = payload["prompt_anchors"]["items"][0]["prompt_excerpt"]
    assert excerpt["max_chars"] <= 240
    assert len(excerpt["text"]) <= 240
    assert RAW_PROMPT_TAIL_SENTINEL not in excerpt["text"]


def test_debug_route_exposes_bounded_read_only_prompt_timeline_projection() -> None:
    route_source = Path("src/routes/debug.ts").read_text(encoding="utf-8")

    assert 'projectDebugApi.get("/debug/prompt-timeline"' in route_source
    assert "projectPromptTimeline" in route_source
    assert "sanitizePromptTimelinePayload" in route_source
    assert '"history" + "_rows"' in route_source
    assert route_source.index('projectDebugApi.get("/debug/prompt-timeline"') < route_source.index(
        'projectDebugApi.get("/debug/:debugId"'
    )
    assert "raw_prompt" not in route_source
    assert "raw_transcript" not in route_source
    assert "Deno.writeTextFile" not in route_source
