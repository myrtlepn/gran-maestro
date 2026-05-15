from __future__ import annotations

from scripts.mst_cmds import session


MST_SESSION_ID = "MST-AGI-038-20260515T083212000Z-dod015"
SESSION_ROOT = "/tmp/gran-maestro-session-dod015"
ORIGINAL_ROOT = "/tmp/gran-maestro-original-dod015"
CHILD_ROOT = "/tmp/gran-maestro-session-dod015/.gran-maestro/worktrees/REQ-880/t01"
SESSION_BRANCH = "gran-maestro/session/MST-AGI-038-20260515T083212000Z-dod015"


def _require_session_api(name: str):
    value = getattr(session, name, None)
    assert callable(value), f"session.{name} contract helper is missing"
    return value


def _metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mst_session_id": MST_SESSION_ID,
        "state": "active",
        "session_worktree_path": SESSION_ROOT,
        "session_branch": SESSION_BRANCH,
        "base_branch": "master",
        "base_sha": "1111111111111111111111111111111111111111",
    }
    payload.update(overrides)
    return payload


def _resolve(
    *,
    git_status: dict[str, object] | None = None,
    entry_context: dict[str, object] | None = None,
    session_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    resolver = _require_session_api("resolve_session_start_policy_state")
    return resolver(
        git_status=git_status or {},
        entry_context=entry_context or {"entry_type": "start", "cwd": ORIGINAL_ROOT},
        session_metadata=session_metadata,
    )


def test_required_session_start_policy_api_exists() -> None:
    _require_session_api("resolve_session_start_policy_state")


def test_dirty_base_policy_blocks_dirty_staged_untracked_and_conflicted_inputs() -> None:
    cases = [
        ({"dirty": True}, "dirty_worktree"),
        ({"staged": True}, "staged_changes"),
        ({"untracked": True}, "untracked_files"),
        ({"conflicted": True}, "conflicted_index"),
    ]

    for git_status, expected_policy in cases:
        payload = _resolve(git_status=git_status)

        assert payload["ok"] is False
        assert payload["classification"] == "blocked_dirty_base"
        assert payload["dirty_base_policy"] == expected_policy
        assert payload["action"] == "clean_or_stash_before_session_start"
        assert payload["unsafe_merge_blocked"] is True
        assert payload["destructive_action_allowed"] is False


def test_ignored_only_status_is_clean_for_top_level_session_start() -> None:
    payload = _resolve(git_status={"ignored": True})

    assert payload["ok"] is True
    assert payload["classification"] == "top_level_session_start"
    assert payload["dirty_base_policy"] == "clean"
    assert payload["resume_action"] == "create_new_session"
    assert payload["nested_session_action"] == "none"
    assert payload["unsafe_merge_blocked"] is False
    assert payload["destructive_action_allowed"] is False


def test_resume_existing_session_metadata_returns_resume_action() -> None:
    payload = _resolve(
        entry_context={"entry_type": "resume", "cwd": SESSION_ROOT, "worktree_exists": True},
        session_metadata=_metadata(),
    )

    assert payload["ok"] is True
    assert payload["classification"] == "resume_existing_session"
    assert payload["resume_action"] == "resume_existing_session"
    assert payload["target_project_root"] == SESSION_ROOT
    assert payload["canonical_session"]["mst_session_id"] == MST_SESSION_ID
    assert payload["destructive_action_allowed"] is False


def test_recover_or_repair_actions_do_not_grant_destructive_authority() -> None:
    missing_path = _resolve(
        entry_context={"entry_type": "resume", "cwd": ORIGINAL_ROOT, "worktree_exists": False},
        session_metadata=_metadata(session_worktree_path=""),
    )
    recover = _resolve(
        entry_context={"entry_type": "recover", "cwd": ORIGINAL_ROOT, "recover_dry_run": True, "worktree_exists": False},
        session_metadata=_metadata(state="blocked"),
    )

    assert missing_path["ok"] is False
    assert missing_path["classification"] == "repair_session_metadata"
    assert missing_path["resume_action"] == "repair_session_metadata"
    assert missing_path["reason"] == "missing_session_worktree_path"
    assert missing_path["destructive_action_allowed"] is False

    assert recover["ok"] is False
    assert recover["classification"] == "recover_dry_run"
    assert recover["resume_action"] == "recover_dry_run"
    assert recover["action"] == "report_recovery_plan_without_mutation"
    assert recover["destructive_action_allowed"] is False


def test_nested_session_inherits_parent_or_creates_child_worktree_by_intent() -> None:
    inherit = _resolve(
        entry_context={"entry_type": "nested", "cwd": SESSION_ROOT, "nested_intent": "inherit"},
        session_metadata=_metadata(),
    )
    child = _resolve(
        entry_context={"entry_type": "nested", "cwd": CHILD_ROOT, "nested_intent": "child_worktree"},
        session_metadata=_metadata(),
    )

    assert inherit["ok"] is True
    assert inherit["classification"] == "nested_session_entry"
    assert inherit["nested_session_action"] == "inherit_parent_session"
    assert inherit["target_project_root"] == SESSION_ROOT

    assert child["ok"] is True
    assert child["classification"] == "nested_session_entry"
    assert child["nested_session_action"] == "create_child_worktree"
    assert child["target_project_root"] == CHILD_ROOT
    assert child["parent_session"]["mst_session_id"] == MST_SESSION_ID


def test_nested_top_level_entry_is_blocked_without_destructive_authority() -> None:
    payload = _resolve(
        entry_context={"entry_type": "nested", "cwd": SESSION_ROOT, "nested_intent": "top_level"},
        session_metadata=_metadata(),
    )

    assert payload["ok"] is False
    assert payload["classification"] == "blocked_nested_top_level"
    assert payload["nested_session_action"] == "block_top_level_session"
    assert payload["action"] == "inherit_parent_session_or_create_child_worktree"
    assert payload["unsafe_merge_blocked"] is True
    assert payload["destructive_action_allowed"] is False


def test_legacy_identity_fields_are_diagnostic_only_not_resume_sources() -> None:
    payload = _resolve(
        entry_context={"entry_type": "resume", "cwd": ORIGINAL_ROOT},
        session_metadata={
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
            "owner_pid": 4242,
        },
    )

    assert payload["ok"] is False
    assert payload["classification"] == "session_identity_required"
    assert payload["resume_action"] == "provide_canonical_mst_session_id"
    assert payload["canonical_session"] == {}
    assert payload["legacy_diagnostics"] == {
        "owner_session_id": MST_SESSION_ID,
        "owner_pid": 4242,
        "session_id": MST_SESSION_ID,
        "sessionId": MST_SESSION_ID,
    }
    assert payload["destructive_action_allowed"] is False
