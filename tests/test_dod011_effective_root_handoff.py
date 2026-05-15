from __future__ import annotations

from pathlib import Path

from scripts.mst_cmds.worktree import resolve_effective_root_handoff_state


MST_SESSION_ID = "MST-AGI-038-20260515T073102Z-dod011"
SESSION_BRANCH = "gran-maestro/master/AGI-038/session"
ORIGINAL_ROOT = "/tmp/gran-maestro-original"
SESSION_ROOT = "/tmp/gran-maestro-session"
CHILD_ROOT = "/tmp/gran-maestro-child-req-876-t01"
CANONICAL_RUNTIME_ROOT = "/tmp/gran-maestro-original/.gran-maestro"


def _normalized(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _current_session(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "parent_project_root": ORIGINAL_ROOT,
        "base_branch": "master",
        "base_sha": "1111111111111111111111111111111111111111",
        "canonical_runtime_root": CANONICAL_RUNTIME_ROOT,
    }
    payload.update(overrides)
    return payload


def _child_metadata(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "taskId": "REQ-876-T01",
        "path": CHILD_ROOT,
        "branch": "gran-maestro/master/AGI-038/REQ-876-T01",
        "base_branch": SESSION_BRANCH,
        "base_sha": "2222222222222222222222222222222222222222",
        "parent_mst_session_id": MST_SESSION_ID,
        "parent_session_branch": SESSION_BRANCH,
        "parent_session_worktree_path": SESSION_ROOT,
        "canonical_runtime_root": CANONICAL_RUNTIME_ROOT,
    }
    payload.update(overrides)
    return payload


def _resolve(
    current_root: str,
    *,
    current_session: dict[str, object] | None = None,
    child_metadata: dict[str, object] | None = None,
    original_project_root: str | None = ORIGINAL_ROOT,
    boundary: str = "skill",
    write_intent: bool = True,
) -> dict[str, object]:
    return resolve_effective_root_handoff_state(
        current_root,
        current_session or _current_session(),
        child_metadata=child_metadata,
        original_project_root=original_project_root,
        boundary=boundary,
        write_intent=write_intent,
    )


def test_session_root_allowed_for_skill_boundary() -> None:
    payload = _resolve(SESSION_ROOT, boundary="plan")

    assert payload["classification"] == "session_root"
    assert payload["action"] == "session_root_allowed"
    assert payload["allowed"] is True
    assert payload["effective_project_root"] == _normalized(SESSION_ROOT)
    assert payload["target_project_root"] == _normalized(SESSION_ROOT)
    assert payload["canonical_session"]["mst_session_id"] == MST_SESSION_ID
    assert payload["canonical_session"]["session_worktree_path"] == SESSION_ROOT
    assert payload["canonical_session"]["canonical_runtime_root"] == CANONICAL_RUNTIME_ROOT
    assert payload["destructive_action_allowed"] is False


def test_parent_checkout_requires_session_reentry_for_write_boundary() -> None:
    payload = _resolve(ORIGINAL_ROOT, boundary="request", write_intent=True)

    assert payload["classification"] == "original_checkout"
    assert payload["action"] == "session_reentry_required"
    assert payload["allowed"] is False
    assert payload["reason"] == "parent_checkout_not_effective_root"
    assert payload["effective_project_root"] == _normalized(ORIGINAL_ROOT)
    assert payload["target_project_root"] == _normalized(SESSION_ROOT)
    assert payload["canonical_session"]["mst_session_id"] == MST_SESSION_ID
    assert payload["write_intent"] is True
    assert payload["destructive_action_allowed"] is False


def test_parent_checkout_read_boundary_is_still_not_write_allowed() -> None:
    payload = _resolve(ORIGINAL_ROOT, boundary="dashboard", write_intent=False)

    assert payload["classification"] == "original_checkout"
    assert payload["action"] == "session_reentry_recommended"
    assert payload["allowed"] is False
    assert payload["target_project_root"] == _normalized(SESSION_ROOT)
    assert payload["write_intent"] is False


def test_parent_checkout_from_session_metadata_requires_reentry_without_explicit_original_root() -> None:
    payload = _resolve(ORIGINAL_ROOT, original_project_root=None, boundary="hook", write_intent=True)

    assert payload["classification"] == "original_checkout"
    assert payload["action"] == "session_reentry_required"
    assert payload["allowed"] is False
    assert payload["target_project_root"] == _normalized(SESSION_ROOT)


def test_child_root_allowed_with_parent_session_evidence() -> None:
    child = _child_metadata(owner_session_id="legacy-owner-diagnostic")
    payload = _resolve(CHILD_ROOT, child_metadata=child, boundary="task")

    assert payload["classification"] == "child_root"
    assert payload["action"] == "child_root_allowed"
    assert payload["allowed"] is True
    assert payload["effective_project_root"] == _normalized(CHILD_ROOT)
    assert payload["target_project_root"] == _normalized(CHILD_ROOT)
    assert payload["child_evidence"]["parent_mst_session_id"] == MST_SESSION_ID
    assert payload["child_evidence"]["parent_session_branch"] == SESSION_BRANCH
    assert payload["legacy_diagnostics"]["child"] == {"owner_session_id": "legacy-owner-diagnostic"}
    assert payload["destructive_action_allowed"] is False


def test_child_root_parent_session_mismatch_blocks_handoff() -> None:
    payload = _resolve(
        CHILD_ROOT,
        child_metadata=_child_metadata(parent_mst_session_id="MST-AGI-038-20260515T073102Z-other"),
        boundary="task",
    )

    assert payload["classification"] == "child_root"
    assert payload["action"] == "child_parent_session_mismatch"
    assert payload["allowed"] is False
    assert payload["reason"] == "child_parent_session_mismatch"
    assert payload["target_project_root"] == _normalized(SESSION_ROOT)
    assert payload["destructive_action_allowed"] is False


def test_missing_session_metadata_blocks_handoff() -> None:
    payload = resolve_effective_root_handoff_state(
        ORIGINAL_ROOT,
        {"mst_session_id": MST_SESSION_ID},
        original_project_root=ORIGINAL_ROOT,
        boundary="approve",
        write_intent=True,
    )

    assert payload["classification"] == "unknown_root"
    assert payload["action"] == "session_metadata_required"
    assert payload["allowed"] is False
    assert payload["reason"] == "missing_session_worktree_path"
    assert payload["target_project_root"] is None
    assert payload["destructive_action_allowed"] is False


def test_diagnostic_only_legacy_fields_do_not_become_canonical_fallback() -> None:
    payload = resolve_effective_root_handoff_state(
        ORIGINAL_ROOT,
        {
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "sessionId": MST_SESSION_ID,
            "owner_pid": 4242,
            "owner_ppid": 31337,
        },
        child_metadata={
            "path": CHILD_ROOT,
            "owner_session_id": MST_SESSION_ID,
            "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
        },
        original_project_root=ORIGINAL_ROOT,
        boundary="skill",
        write_intent=True,
    )

    assert payload["classification"] == "unknown_root"
    assert payload["action"] == "session_identity_required"
    assert payload["allowed"] is False
    assert payload["canonical_session"] == {}
    assert payload["legacy_diagnostics"]["session"] == {
        "owner_session_id": MST_SESSION_ID,
        "owner_pid": 4242,
        "owner_ppid": 31337,
        "session_id": MST_SESSION_ID,
        "sessionId": MST_SESSION_ID,
    }
    assert payload["legacy_diagnostics"]["child"] == {
        "owner_session_id": MST_SESSION_ID,
        "MST_SNAPSHOT_SESSION_ID": MST_SESSION_ID,
    }
    assert payload["destructive_action_allowed"] is False
