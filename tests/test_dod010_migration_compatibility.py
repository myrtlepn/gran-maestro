from __future__ import annotations

from scripts.mst_cmds.worktree import resolve_migration_compatibility_state


MST_SESSION_ID = "MST-AGI-038-20260515T073102Z-dod010"
SESSION_BRANCH = "gran-maestro/master/AGI-038/session"
SESSION_WORKTREE_PATH = "/tmp/gran-maestro-session"
BASE_BRANCH = "master"
BASE_SHA = "1111111111111111111111111111111111111111"
LEGACY_BASE_SHA = "2222222222222222222222222222222222222222"


def _current_session(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_WORKTREE_PATH,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
    }
    payload.update(overrides)
    return payload


def _resolve(metadata: dict[str, object], *, current_session: dict[str, object] | None = None, request: dict[str, object] | None = None) -> dict[str, object]:
    return resolve_migration_compatibility_state(metadata, current_session or _current_session(), request=request)


def test_canonical_child_passthrough_preserves_parent_evidence() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T01",
            "parent_mst_session_id": MST_SESSION_ID,
            "parent_session_branch": SESSION_BRANCH,
            "parent_session_worktree_path": SESSION_WORKTREE_PATH,
            "base_branch": SESSION_BRANCH,
            "base_sha": BASE_SHA,
            "owner_session_id": "legacy-owner-diagnostic",
        }
    )

    assert payload["classification"] == "canonical_child"
    assert payload["migration_required"] is False
    assert payload["migration_allowed"] is False
    assert payload["canonical_patch"] == {}
    assert payload["destructive_action_allowed"] is False
    assert payload["canonical_parent_evidence"] == {
        "parent_mst_session_id": MST_SESSION_ID,
        "parent_session_branch": SESSION_BRANCH,
        "parent_session_worktree_path": SESSION_WORKTREE_PATH,
    }
    assert payload["legacy_diagnostics"]["metadata"] == {"owner_session_id": "legacy-owner-diagnostic"}


def test_safe_reparent_uses_matching_worktree_base_evidence() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T01",
            "base_branch": BASE_BRANCH,
            "base_sha": BASE_SHA,
            "owner_session_id": "legacy-owner-diagnostic",
            "session_id": "legacy-hook-session",
            "owner_pid": 4242,
        }
    )

    assert payload["classification"] == "reparent_to_session"
    assert payload["migration_required"] is True
    assert payload["migration_allowed"] is True
    assert payload["reason"] == "base_match"
    assert payload["canonical_patch"] == {
        "parent_mst_session_id": MST_SESSION_ID,
        "parent_session_branch": SESSION_BRANCH,
        "original_base_branch": BASE_BRANCH,
        "original_base_sha": BASE_SHA,
        "parent_session_worktree_path": SESSION_WORKTREE_PATH,
    }
    assert "owner_session_id" not in payload["canonical_patch"]
    assert "session_id" not in payload["canonical_patch"]
    assert payload["legacy_diagnostics"]["metadata"] == {
        "owner_session_id": "legacy-owner-diagnostic",
        "owner_pid": 4242,
        "session_id": "legacy-hook-session",
    }
    assert payload["destructive_action_allowed"] is False


def test_reparent_can_use_request_base_evidence_without_legacy_owner_fallback() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T02",
            "owner_session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
        },
        request={
            "id": "REQ-875",
            "original_base_branch": BASE_BRANCH,
            "original_base_sha": BASE_SHA,
            "owner_session_id": "request-legacy-owner",
        },
    )

    assert payload["classification"] == "reparent_to_session"
    assert payload["migration_allowed"] is True
    assert payload["canonical_patch"]["parent_mst_session_id"] == MST_SESSION_ID
    assert payload["canonical_patch"]["parent_session_branch"] == SESSION_BRANCH
    assert payload["legacy_diagnostics"]["metadata"] == {
        "owner_session_id": MST_SESSION_ID,
        "sessionId": MST_SESSION_ID,
    }
    assert payload["legacy_diagnostics"]["request"] == {"owner_session_id": "request-legacy-owner"}
    assert "owner_session_id" not in payload["canonical_patch"]
    assert "sessionId" not in payload["canonical_patch"]
    assert payload["base_evidence"]["source"] == "request"


def test_base_mismatch_blocks_migration_with_structured_reason() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T03",
            "base_branch": BASE_BRANCH,
            "base_sha": LEGACY_BASE_SHA,
            "owner_session_id": "legacy-owner-diagnostic",
        }
    )

    assert payload["classification"] == "blocked_migration"
    assert payload["migration_required"] is True
    assert payload["migration_allowed"] is False
    assert payload["reason"] == "base_mismatch"
    assert payload["canonical_patch"] == {}
    assert payload["base_evidence"] == {
        "source": "metadata",
        "branch_field": "base_branch",
        "sha_field": "base_sha",
        "base_branch": BASE_BRANCH,
        "base_sha": LEGACY_BASE_SHA,
    }
    assert payload["destructive_action_allowed"] is False


def test_diagnostic_only_legacy_fields_do_not_become_canonical_fallback() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T04",
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
            "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
            "owner_pid": 4242,
            "owner_ppid": 31337,
            "hook_session_id": "claude-hook-session",
            "transcript_uuid": "123e4567-e89b-12d3-a456-426614174000",
        }
    )

    assert payload["classification"] == "legacy_or_external"
    assert payload["migration_required"] is True
    assert payload["migration_allowed"] is False
    assert payload["reason"] == "insufficient_base_evidence"
    assert payload["canonical_patch"] == {}
    assert payload["legacy_diagnostics"]["metadata"] == {
        "owner_session_id": MST_SESSION_ID,
        "owner_pid": 4242,
        "owner_ppid": 31337,
        "session_id": MST_SESSION_ID,
        "sessionId": MST_SESSION_ID,
        "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
        "hook_session_id": "claude-hook-session",
        "transcript_uuid": "123e4567-e89b-12d3-a456-426614174000",
    }
    assert payload["destructive_action_allowed"] is False


def test_parent_session_mismatch_blocks_canonical_repair() -> None:
    payload = _resolve(
        {
            "taskId": "REQ-875-T05",
            "parent_mst_session_id": "MST-AGI-038-20260515T073102Z-other",
            "parent_session_branch": SESSION_BRANCH,
            "base_branch": BASE_BRANCH,
            "base_sha": BASE_SHA,
        }
    )

    assert payload["classification"] == "blocked_migration"
    assert payload["migration_allowed"] is False
    assert payload["migration_required"] is True
    assert payload["reason"] == "parent_session_mismatch"
    assert payload["canonical_patch"] == {}
    assert payload["destructive_action_allowed"] is False
