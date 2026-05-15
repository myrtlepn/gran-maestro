from __future__ import annotations

from pathlib import Path

from scripts.mst_cmds._common import resolve_canonical_runtime_root_state


MST_SESSION_ID = "MST-AGI-038-20260515T073102Z-dod012"
REQ_ID = "REQ-877"
ORIGINAL_ROOT = "/tmp/gran-maestro-original"
SESSION_ROOT = "/tmp/gran-maestro-session"
CHILD_ROOT = "/tmp/gran-maestro-child-req-877-t01"
CANONICAL_RUNTIME_ROOT = f"{ORIGINAL_ROOT}/.gran-maestro"
SESSION_LOCAL_RUNTIME_ROOT = f"{SESSION_ROOT}/.gran-maestro"
CHILD_LOCAL_RUNTIME_ROOT = f"{CHILD_ROOT}/.gran-maestro"


def _normalized(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _resolve(context: dict[str, object], *, mst_session_id: str | None = MST_SESSION_ID, req_id: str | None = REQ_ID) -> dict[str, object]:
    return resolve_canonical_runtime_root_state(context, mst_session_id=mst_session_id, req_id=req_id)


def _canonical_context(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "canonical_runtime_root": CANONICAL_RUNTIME_ROOT,
        "current_session": {
            "mst_session_id": MST_SESSION_ID,
            "session_worktree_path": SESSION_ROOT,
            "canonical_runtime_root": CANONICAL_RUNTIME_ROOT,
        },
        "child_metadata": {
            "taskId": "REQ-877-T01",
            "path": CHILD_ROOT,
            "parent_mst_session_id": MST_SESSION_ID,
            "canonical_runtime_root": CANONICAL_RUNTIME_ROOT,
        },
    }
    payload.update(overrides)
    return payload


def test_canonical_runtime_root_pointer_is_consistent_across_original_session_and_child_contexts() -> None:
    contexts = [
        _canonical_context(current_root=ORIGINAL_ROOT),
        _canonical_context(current_root=SESSION_ROOT),
        _canonical_context(current_root=CHILD_ROOT),
    ]

    payloads = [_resolve(context) for context in contexts]

    assert {payload["classification"] for payload in payloads} == {"canonical_runtime_root"}
    assert {payload["allowed"] for payload in payloads} == {True}
    assert {payload["canonical_runtime_root"] for payload in payloads} == {_normalized(CANONICAL_RUNTIME_ROOT)}
    assert {payload["reason"] for payload in payloads} == {"explicit_runtime_root_pointer"}
    assert all(payload["destructive_action_allowed"] is False for payload in payloads)


def test_metadata_paths_are_derived_from_canonical_runtime_root_not_cwd() -> None:
    payload = _resolve(
        _canonical_context(
            current_cwd=CHILD_ROOT,
            local_runtime_root=CHILD_LOCAL_RUNTIME_ROOT,
        )
    )

    root = _normalized(CANONICAL_RUNTIME_ROOT)
    paths = payload["metadata_paths"]

    assert payload["classification"] == "canonical_runtime_root"
    assert payload["canonical_runtime_root"] == root
    assert paths["runtime_root"] == root
    assert paths["sessions_dir"] == f"{root}/sessions"
    assert paths["session_dir"] == f"{root}/sessions/{MST_SESSION_ID}"
    assert paths["session_history"] == f"{root}/sessions/{MST_SESSION_ID}/history.jsonl"
    assert paths["execution_flow"] == f"{root}/sessions/{MST_SESSION_ID}/execution-flow.json"
    assert paths["state_dir"] == f"{root}/state"
    assert paths["state_session_dir"] == f"{root}/state/{MST_SESSION_ID}"
    assert paths["state_snapshot"] == f"{root}/state/{MST_SESSION_ID}/snapshot.json"
    assert paths["flow_detail"] == f"{root}/state/{MST_SESSION_ID}/flow-detail.ndjson"
    assert paths["lifecycle_events"] == f"{root}/sessions/{MST_SESSION_ID}/lifecycle.ndjson"
    assert paths["requests_dir"] == f"{root}/requests"
    assert paths["request_dir"] == f"{root}/requests/{REQ_ID}"
    assert paths["request_json"] == f"{root}/requests/{REQ_ID}/request.json"
    assert paths["worktrees_dir"] == f"{root}/worktrees"
    assert CHILD_LOCAL_RUNTIME_ROOT not in paths.values()


def test_split_root_pointer_mismatch_blocks_without_silent_local_selection() -> None:
    payload = _resolve(
        _canonical_context(
            child_metadata={
                "taskId": "REQ-877-T01",
                "path": CHILD_ROOT,
                "parent_mst_session_id": MST_SESSION_ID,
                "canonical_runtime_root": CHILD_LOCAL_RUNTIME_ROOT,
            },
            local_runtime_root=CHILD_LOCAL_RUNTIME_ROOT,
        )
    )

    assert payload["classification"] == "split_runtime_root_blocked"
    assert payload["allowed"] is False
    assert payload["canonical_runtime_root"] is None
    assert payload["metadata_paths"] == {}
    assert payload["reason"] == "runtime_root_pointer_mismatch"
    assert sorted(source["normalized"] for source in payload["diagnostics"]["pointer_sources"]) == sorted([
        _normalized(CANONICAL_RUNTIME_ROOT),
        _normalized(CANONICAL_RUNTIME_ROOT),
        _normalized(CHILD_LOCAL_RUNTIME_ROOT),
    ])
    assert payload["destructive_action_allowed"] is False


def test_split_root_local_gran_maestro_without_trusted_pointer_is_blocked() -> None:
    payload = _resolve(
        {
            "current_cwd": CHILD_ROOT,
            "has_local_gran_maestro": True,
            "current_session": {"mst_session_id": MST_SESSION_ID},
        }
    )

    assert payload["classification"] == "split_runtime_root_blocked"
    assert payload["allowed"] is False
    assert payload["canonical_runtime_root"] is None
    assert payload["metadata_paths"] == {}
    assert payload["reason"] == "missing_trusted_runtime_root_pointer"
    assert payload["diagnostics"]["local_runtime_roots"] == [
        {"source": "current_cwd/.gran-maestro", "normalized": _normalized(CHILD_LOCAL_RUNTIME_ROOT)}
    ]
    assert payload["destructive_action_allowed"] is False


def test_missing_pointer_blocks_when_no_runtime_root_evidence_exists() -> None:
    payload = _resolve({"current_session": {"mst_session_id": MST_SESSION_ID}})

    assert payload["classification"] == "missing_runtime_root"
    assert payload["allowed"] is False
    assert payload["canonical_runtime_root"] is None
    assert payload["metadata_paths"] == {}
    assert payload["reason"] == "missing_canonical_runtime_root_pointer"
    assert payload["destructive_action_allowed"] is False


def test_trusted_original_root_fallback_derives_paths_when_no_split_root_exists() -> None:
    payload = _resolve(
        {
            "trusted_original_project_root": ORIGINAL_ROOT,
            "current_session": {"mst_session_id": MST_SESSION_ID},
            "request": {"id": REQ_ID},
        }
    )

    root = _normalized(CANONICAL_RUNTIME_ROOT)
    assert payload["classification"] == "trusted_original_root"
    assert payload["allowed"] is True
    assert payload["canonical_runtime_root"] == root
    assert payload["metadata_paths"]["state_snapshot"] == f"{root}/state/{MST_SESSION_ID}/snapshot.json"
    assert payload["metadata_paths"]["request_json"] == f"{root}/requests/{REQ_ID}/request.json"
    assert payload["reason"] == "trusted_original_runtime_root_fallback"
    assert payload["destructive_action_allowed"] is False


def test_trusted_original_root_fallback_blocks_conflicting_local_root() -> None:
    payload = _resolve(
        {
            "trusted_original_project_root": ORIGINAL_ROOT,
            "current_cwd": SESSION_ROOT,
            "local_runtime_root": SESSION_LOCAL_RUNTIME_ROOT,
            "current_session": {"mst_session_id": MST_SESSION_ID},
        }
    )

    assert payload["classification"] == "split_runtime_root_blocked"
    assert payload["allowed"] is False
    assert payload["canonical_runtime_root"] is None
    assert payload["reason"] == "local_runtime_root_conflicts_with_trusted_original"
    assert payload["diagnostics"]["trusted_original_runtime_root"] == _normalized(CANONICAL_RUNTIME_ROOT)
    assert payload["diagnostics"]["conflicting_local_runtime_roots"] == [
        {"source": "local_runtime_root", "normalized": _normalized(SESSION_LOCAL_RUNTIME_ROOT)}
    ]


def test_diagnostic_only_legacy_fields_do_not_become_canonical_runtime_root_fallback() -> None:
    payload = _resolve(
        {
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
            "MST_STATE_PPID": "4242",
            "current_session": {
                "owner_session_id": MST_SESSION_ID,
                "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
            },
            "child_metadata": {
                "path": CHILD_ROOT,
                "owner_session_id": MST_SESSION_ID,
                "hook_session_id": "claude-hook-session",
                "transcript_uuid": "123e4567-e89b-12d3-a456-426614174000",
            },
        },
        mst_session_id=None,
        req_id=None,
    )

    assert payload["classification"] == "missing_runtime_root"
    assert payload["allowed"] is False
    assert payload["canonical_runtime_root"] is None
    assert payload["metadata_paths"] == {}
    assert payload["reason"] == "missing_canonical_runtime_root_pointer"
    assert payload["legacy_diagnostics"] == {
        "context": {
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
            "MST_STATE_PPID": "4242",
        },
        "current_session": {
            "owner_session_id": MST_SESSION_ID,
            "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
        },
        "child_metadata": {
            "owner_session_id": MST_SESSION_ID,
            "hook_session_id": "claude-hook-session",
            "transcript_uuid": "123e4567-e89b-12d3-a456-426614174000",
        },
    }
    assert payload["destructive_action_allowed"] is False
