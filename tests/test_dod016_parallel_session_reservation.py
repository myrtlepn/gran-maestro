from __future__ import annotations

from scripts.mst_cmds import session


MST_SESSION_ID = "MST-AGI-038-20260515T084507000Z-dod016"
OTHER_SESSION_ID = "MST-AGI-038-20260515T084507000Z-other016"
SESSION_BRANCH = "gran-maestro/session/MST-AGI-038-20260515T084507000Z-dod016"
SESSION_ROOT = "/tmp/gran-maestro-session-dod016"
METADATA_PATH = "/tmp/gran-maestro-runtime/sessions/MST-AGI-038-20260515T084507000Z-dod016/session.json"
BASE_BRANCH = "master"
BASE_SHA = "1111111111111111111111111111111111111111"
CURRENT_SHA = "1111111111111111111111111111111111111111"
DRIFT_SHA = "2222222222222222222222222222222222222222"


def _require_session_api(name: str):
    value = getattr(session, name, None)
    assert callable(value), f"session.{name} contract helper is missing"
    return value


def _candidate(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "metadata_path": METADATA_PATH,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
    }
    payload.update(overrides)
    return payload


def _resolve(
    *,
    candidate: dict[str, object] | None = None,
    existing_reservations: list[dict[str, object]] | None = None,
    final_merge_context: dict[str, object] | None = None,
) -> dict[str, object]:
    resolver = _require_session_api("resolve_parallel_session_reservation_state")
    return resolver(
        candidate=candidate if candidate is not None else _candidate(),
        existing_reservations=existing_reservations or [],
        final_merge_context=final_merge_context or {},
    )


def test_required_parallel_reservation_policy_api_exists() -> None:
    _require_session_api("resolve_parallel_session_reservation_state")
    _require_session_api("session_reservation_idempotency_key")


def test_atomic_reservation_tuple_is_stable_and_complete() -> None:
    payload = _resolve()
    key_resolver = _require_session_api("session_reservation_idempotency_key")

    assert payload["ok"] is True
    assert payload["classification"] == "reservation_available"
    assert payload["reservation_policy"] == "atomic_reservation_available"
    assert payload["collision_policy"] == "none"
    assert payload["destructive_action_allowed"] is False
    assert payload["reservation"] == {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "metadata_path": METADATA_PATH,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "idempotency_key": key_resolver(candidate=_candidate()),
    }
    assert payload["reservation"]["idempotency_key"] == payload["idempotency_key"]


def test_collision_policy_reports_exact_conflicting_fields() -> None:
    collision = {
        "mst_session_id": MST_SESSION_ID,
        "session_branch": SESSION_BRANCH,
        "session_worktree_path": SESSION_ROOT,
        "metadata_path": METADATA_PATH,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
    }

    payload = _resolve(existing_reservations=[collision])

    assert payload["ok"] is False
    assert payload["classification"] == "reservation_collision"
    assert payload["reservation_policy"] == "collision_detected"
    assert payload["collision_policy"] == "retry_with_new_session_identity"
    assert payload["destructive_action_allowed"] is False
    assert payload["collisions"] == [
        {
            "index": 0,
            "fields": ["metadata_path", "mst_session_id", "session_branch", "session_worktree_path"],
            "policy": "retry_with_new_session_identity",
        }
    ]
    assert payload["action"] == "allocate_new_session_identity_or_resume_existing"


def test_final_merge_authorized_requires_owned_lock_and_matching_base_sha() -> None:
    payload = _resolve(
        final_merge_context={
            "requested": True,
            "lock": {
                "state": "held",
                "base_branch": BASE_BRANCH,
                "owner_mst_session_id": MST_SESSION_ID,
            },
            "current_base_sha": CURRENT_SHA,
        }
    )

    assert payload["ok"] is True
    assert payload["classification"] == "final_merge_authorized"
    assert payload["lock_policy"] == "owned_lock"
    assert payload["base_drift_policy"] == "clean"
    assert payload["final_merge_action"] == "authorize_final_merge"
    assert payload["unsafe_merge_blocked"] is False
    assert payload["destructive_action_allowed"] is False


def test_lock_policy_blocks_busy_stale_and_owner_mismatch_states() -> None:
    cases = [
        ({"state": "busy", "base_branch": BASE_BRANCH, "owner_mst_session_id": OTHER_SESSION_ID}, "lock_busy", "wait_for_base_merge_lock"),
        ({"state": "stale", "base_branch": BASE_BRANCH, "owner_mst_session_id": OTHER_SESSION_ID}, "stale_lock", "recover_or_repair_base_merge_lock"),
        ({"state": "held", "base_branch": BASE_BRANCH, "owner_mst_session_id": OTHER_SESSION_ID}, "lock_owner_mismatch", "wait_for_or_recover_base_merge_lock"),
    ]

    for lock, expected_policy, expected_action in cases:
        payload = _resolve(final_merge_context={"requested": True, "lock": lock, "current_base_sha": CURRENT_SHA})

        assert payload["ok"] is False
        assert payload["classification"] == "final_merge_blocked"
        assert payload["lock_policy"] == expected_policy
        assert payload["final_merge_action"] == expected_action
        assert payload["unsafe_merge_blocked"] is True
        assert payload["destructive_action_allowed"] is False


def test_base_drift_blocks_final_merge_without_mutation() -> None:
    payload = _resolve(
        final_merge_context={
            "requested": True,
            "lock": {
                "state": "held",
                "base_branch": BASE_BRANCH,
                "owner_mst_session_id": MST_SESSION_ID,
            },
            "current_base_sha": DRIFT_SHA,
        }
    )

    assert payload["ok"] is False
    assert payload["classification"] == "final_merge_blocked"
    assert payload["lock_policy"] == "owned_lock"
    assert payload["base_drift_policy"] == "base_sha_drift"
    assert payload["final_merge_action"] == "refresh_session_or_rebase_before_final_merge"
    assert payload["unsafe_merge_blocked"] is True
    assert payload["destructive_action_allowed"] is False
    assert payload["diagnostics"] == [
        {
            "code": "base_sha_drift",
            "reserved_base_sha": BASE_SHA,
            "current_base_sha": DRIFT_SHA,
            "safer_action": "refresh_session_or_rebase_before_final_merge",
        }
    ]


def test_legacy_identity_fields_are_diagnostic_only_not_lock_owners() -> None:
    payload = _resolve(
        candidate={
            "owner_session_id": MST_SESSION_ID,
            "session_id": MST_SESSION_ID,
            "owner_pid": 4242,
            "base_branch": BASE_BRANCH,
            "base_sha": BASE_SHA,
        },
        final_merge_context={
            "requested": True,
            "lock": {
                "state": "held",
                "base_branch": BASE_BRANCH,
                "owner_session_id": MST_SESSION_ID,
            },
            "current_base_sha": CURRENT_SHA,
        },
    )

    assert payload["ok"] is False
    assert payload["classification"] == "session_identity_required"
    assert payload["reservation_policy"] == "canonical_identity_required"
    assert payload["final_merge_action"] == "provide_canonical_mst_session_id"
    assert payload["reservation"] == {}
    assert payload["legacy_diagnostics"] == {
        "owner_session_id": MST_SESSION_ID,
        "owner_pid": 4242,
        "session_id": MST_SESSION_ID,
    }
    assert payload["destructive_action_allowed"] is False
