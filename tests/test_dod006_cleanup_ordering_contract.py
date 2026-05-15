from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.mst_cmds import cleanup


REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPT_SKILL = REPO_ROOT / "skills" / "accept" / "SKILL.md"


CANONICAL_STAGES = [
    "freeze",
    "inspect_child_worktrees",
    "child_merge_or_block",
    "child_remove",
    "inspect_session",
    "final_merge_or_block",
    "session_remove",
    "branch_or_archive",
]

WORKTREE_REMOVAL_STAGES = ["child_remove", "session_remove"]
BLOCKING_CHILD_STATES = (
    "active",
    "dirty",
    "conflicted",
    "orphaned",
    "late_arriving_child",
    "unclassified",
)


@dataclass(frozen=True)
class ChildFixture:
    child_id: str
    state: str = "clean"
    merge_outcome: str | None = "merged"
    remove_path_succeeded: bool | None = True
    in_freeze_snapshot: bool = True


@dataclass(frozen=True)
class OwnershipFixture:
    worktree_id: str
    mst_session_id: str | None
    owned_path: str | None
    registered_parent_session_id: str | None
    legacy_owner_session_id: str | None = None


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), f"cleanup.{name} contract helper is missing"
    return value


def _child(
    child_id: str,
    *,
    state: str = "clean",
    merge_outcome: str | None = "merged",
    remove_path_succeeded: bool | None = True,
    in_freeze_snapshot: bool = True,
) -> dict[str, object]:
    return asdict(
        ChildFixture(
            child_id=child_id,
            state=state,
            merge_outcome=merge_outcome,
            remove_path_succeeded=remove_path_succeeded,
            in_freeze_snapshot=in_freeze_snapshot,
        )
    )


def _ownership(
    worktree_id: str,
    *,
    mst_session_id: str | None,
    owned_path: str | None,
    registered_parent_session_id: str | None,
    legacy_owner_session_id: str | None = None,
) -> dict[str, object]:
    return asdict(
        OwnershipFixture(
            worktree_id=worktree_id,
            mst_session_id=mst_session_id,
            owned_path=owned_path,
            registered_parent_session_id=registered_parent_session_id,
            legacy_owner_session_id=legacy_owner_session_id,
        )
    )


def _resolve_cleanup_ordering_state(**kwargs):
    resolver = _require_cleanup_api("resolve_cleanup_ordering_state")
    return resolver(**kwargs)


def _classify_cleanup_worktree_ownership(**kwargs):
    classifier = _require_cleanup_api("classify_cleanup_worktree_ownership")
    return classifier(**kwargs)


def test_accept_skill_cleanup_vocabulary() -> None:
    accept_skill = ACCEPT_SKILL.read_text(encoding="utf-8")

    for token in (
        "child-first/session-last cleanup lifecycle vocabulary",
        "`freeze`",
        "`child inspection` (`inspect_child_worktrees`)",
        "`child removal` (`child_remove`)",
        "`session inspection` (`inspect_session`)",
        "`final merge/cancel policy` (`final_merge_or_block`)",
        "`session removal` (`session_remove`)",
        "`branch/archive` (`branch_or_archive`)",
        "worktree removal은 child removal과 session removal에서만 수행한다",
    ):
        assert token in accept_skill


def test_accept_skill_cleanup_scope_separation() -> None:
    accept_skill = ACCEPT_SKILL.read_text(encoding="utf-8")

    for token in (
        "`request child accept`는 child/session merge와 child cleanup evidence까지만 담당한다.",
        "session final cleanup/removal",
        "original base cleanup authority는 주장하지 않는다",
        "session-level accept 또는 `terminal_success`만 session inspection 이후 final merge/cancel policy를 결정할 수 있다",
    ):
        assert token in accept_skill


def test_required_cleanup_ordering_contract_api_exists() -> None:
    _require_cleanup_api("resolve_cleanup_ordering_state")
    _require_cleanup_api("classify_cleanup_worktree_ownership")


def test_ordered_lifecycle_enforces_canonical_stage_order_and_prerequisites() -> None:
    payload = _resolve_cleanup_ordering_state(
        requested_stage="freeze",
        completed_stages=[],
        children=[],
        durable_events=[],
        final_merge_policy=None,
        freeze_snapshot_child_ids=[],
    )

    assert payload["stage_order"] == CANONICAL_STAGES
    assert payload["worktree_removal_stages"] == WORKTREE_REMOVAL_STAGES

    blocked = _resolve_cleanup_ordering_state(
        requested_stage="final_merge_or_block",
        completed_stages=["freeze"],
        children=[],
        durable_events=[],
        final_merge_policy="merged",
        freeze_snapshot_child_ids=[],
    )

    assert blocked["allowed_transition"] is False
    assert blocked["next_stage"] == "inspect_child_worktrees"
    assert any(
        item == {
            "code": "missing_prerequisite",
            "requested_stage": "final_merge_or_block",
            "missing_stage": "inspect_child_worktrees",
        }
        for item in blocked["diagnostics"]
    )


def test_child_collection_barrier_names_every_blocking_child_state() -> None:
    completed_stages = [
        "freeze",
        "inspect_child_worktrees",
        "child_merge_or_block",
        "child_remove",
        "inspect_session",
        "final_merge_or_block",
    ]

    for child_state in BLOCKING_CHILD_STATES:
        payload = _resolve_cleanup_ordering_state(
            requested_stage="session_remove",
            completed_stages=completed_stages,
            children=[_child("child-blocker", state=child_state)],
            durable_events=[],
            final_merge_policy="merged",
            freeze_snapshot_child_ids=["child-blocker"],
        )

        assert payload["session_remove_allowed"] is False
        assert payload["allowed_transition"] is False
        assert payload["next_stage"] == "inspect_child_worktrees"
        assert payload["blockers"] == [
            {
                "child_id": "child-blocker",
                "state": child_state,
                "reason": "child_collection_barrier",
            }
        ]
        assert any(
            item["code"] == "child_collection_barrier" and item["state"] == child_state
            for item in payload["diagnostics"]
        )


def test_child_remove_before_branch_delete_requires_durable_remove_evidence() -> None:
    payload = _resolve_cleanup_ordering_state(
        requested_stage="branch_or_archive",
        completed_stages=CANONICAL_STAGES[:-1],
        children=[
            _child(
                "child-without-remove-evidence",
                merge_outcome="blocked",
                remove_path_succeeded=False,
            )
        ],
        durable_events=[
            {
                "stage": "child_merge_or_block",
                "child_id": "child-without-remove-evidence",
                "status": "succeeded",
            }
        ],
        final_merge_policy="cancelled",
        freeze_snapshot_child_ids=["child-without-remove-evidence"],
    )

    assert payload["allowed_transition"] is False
    assert payload["next_stage"] == "child_remove"
    assert any(
        item == {
            "code": "child_remove_evidence_missing",
            "child_id": "child-without-remove-evidence",
            "route": "retry_or_reconcile",
        }
        for item in payload["diagnostics"]
    )


def test_session_remove_last_blocks_until_child_outcomes_and_final_policy_resolve() -> None:
    blocked = _resolve_cleanup_ordering_state(
        requested_stage="session_remove",
        completed_stages=[
            "freeze",
            "inspect_child_worktrees",
            "child_merge_or_block",
            "child_remove",
            "inspect_session",
        ],
        children=[_child("child-ready")],
        durable_events=[],
        final_merge_policy=None,
        freeze_snapshot_child_ids=["child-ready"],
    )

    assert blocked["session_remove_allowed"] is False
    assert blocked["allowed_transition"] is False
    assert blocked["next_stage"] == "final_merge_or_block"
    assert any(
        item == {
            "code": "final_merge_policy_unresolved",
            "requested_stage": "session_remove",
        }
        for item in blocked["diagnostics"]
    )

    allowed = _resolve_cleanup_ordering_state(
        requested_stage="session_remove",
        completed_stages=CANONICAL_STAGES[:-2],
        children=[_child("child-ready")],
        durable_events=[],
        final_merge_policy="merged",
        freeze_snapshot_child_ids=["child-ready"],
    )

    assert allowed["allowed_transition"] is True
    assert allowed["session_remove_allowed"] is True
    assert allowed["next_stage"] == "session_remove"
    assert allowed["stage_order"] == CANONICAL_STAGES
    assert allowed["worktree_removal_stages"] == WORKTREE_REMOVAL_STAGES
    assert allowed["stage_order"].index("child_remove") < allowed["stage_order"].index("session_remove")
    assert allowed["stage_order"].index("session_remove") < allowed["stage_order"].index("branch_or_archive")


def test_interrupted_resume_idempotent_skips_successful_destructive_stages() -> None:
    payload = _resolve_cleanup_ordering_state(
        requested_stage="inspect_session",
        completed_stages=[
            "freeze",
            "inspect_child_worktrees",
            "child_merge_or_block",
        ],
        children=[_child("child-1", remove_path_succeeded=None)],
        durable_events=[
            {
                "stage": "child_remove",
                "child_id": "child-1",
                "status": "succeeded",
                "evidence": "worktree-path-removed",
            }
        ],
        final_merge_policy="merged",
        freeze_snapshot_child_ids=["child-1"],
    )

    assert payload["allowed_transition"] is True
    assert payload["next_stage"] == "inspect_session"
    assert payload["already_satisfied"] == ["child_remove"]
    assert payload["stage_status"]["child_remove"] == "already_satisfied"
    assert payload["stage_order"].index(payload["next_stage"]) > payload["stage_order"].index("child_remove")


def test_late_arriving_child_after_freeze_is_classified_and_blocks_session_remove() -> None:
    payload = _resolve_cleanup_ordering_state(
        requested_stage="session_remove",
        completed_stages=CANONICAL_STAGES[:-2],
        children=[
            _child("child-known"),
            _child("child-late", state="clean", in_freeze_snapshot=False),
        ],
        durable_events=[],
        final_merge_policy="merged",
        freeze_snapshot_child_ids=["child-known"],
    )

    assert payload["session_remove_allowed"] is False
    assert payload["allowed_transition"] is False
    assert any(
        item["child_id"] == "child-late" and item["state"] == "late_arriving_child"
        for item in payload["classified_children"]
    )
    assert any(
        item == {
            "child_id": "child-late",
            "state": "late_arriving_child",
            "reason": "child_collection_barrier",
        }
        for item in payload["blockers"]
    )


def test_ownership_ambiguity_routes_to_blocked_recovery_without_fallback() -> None:
    cases = [
        (
            "legacy",
            _ownership(
                "legacy-child",
                mst_session_id=None,
                owned_path=None,
                registered_parent_session_id=None,
                legacy_owner_session_id="legacy-only",
            ),
        ),
        (
            "external",
            _ownership(
                "external-child",
                mst_session_id="MST-OTHER-SESSION",
                owned_path=None,
                registered_parent_session_id=None,
            ),
        ),
        (
            "ownership_ambiguous",
            _ownership(
                "ambiguous-child",
                mst_session_id="MST-SESSION-001",
                owned_path=None,
                registered_parent_session_id=None,
            ),
        ),
    ]

    for expected_classification, worktree in cases:
        payload = _classify_cleanup_worktree_ownership(
            worktree=worktree,
            session_id="MST-SESSION-001",
        )

        assert payload["classification"] == expected_classification
        assert payload["cleanup_allowed"] is False
        assert payload["fallback_used"] is False
        assert payload["diagnostic"] == "blocked_recovery"
        assert payload["ownership_proof"]["same_session_lineage"] is (
            worktree["mst_session_id"] == "MST-SESSION-001"
        )
        assert payload["ownership_proof"]["owned_path"] is False
        assert payload["ownership_proof"]["registered_relation"] is False
