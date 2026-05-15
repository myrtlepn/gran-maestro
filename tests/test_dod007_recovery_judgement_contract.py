from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

import pytest

from scripts.mst_cmds import cleanup


MST_SESSION_ID = "MST-AGI-038-20260515T032931Z-abc12345"
SESSION_BRANCH = "gran-maestro/main/AGI-038/session"
LEGACY_OWNER_SESSION_ID = "MST-LEGACY-OWNER-ONLY-20260515"
SUPPORTED_PRIMARY_ACTIONS = {
    "resume_session",
    "cleanup_child",
    "manual_conflict_resolution",
    "blocked_destructive",
    "diagnostic_only",
}


@dataclass(frozen=True)
class SessionWorktreeFixture:
    path: str = "/tmp/mst-session-worktree"
    metadata_mst_session_id: str | None = MST_SESSION_ID
    state: str = "active"
    session_branch: str = SESSION_BRANCH
    original_base_ref: str = "main"
    current_base_ref: str = "main"
    ownership: str = "owned"
    scan_fresh: bool = True


@dataclass(frozen=True)
class ChildFixture:
    child_id: str
    metadata_mst_session_id: str | None = MST_SESSION_ID
    state: str = "clean"
    merge_status: str = "merged_to_session"
    ownership: str = "owned"
    scan_fresh: bool = True
    seen_in_freeze_snapshot: bool = True


@dataclass(frozen=True)
class BranchCollisionFixture:
    branch_name: str
    ownership: str
    target_ref: str
    same_name_as_session_output: bool = True


@dataclass(frozen=True)
class MergeStateFixture:
    original_base_ref: str = "main"
    current_base_ref: str = "main"
    session_branch: str = SESSION_BRANCH
    child_merge_statuses: list[str] = field(default_factory=lambda: ["merged_to_session"])
    final_policy_state: str = "eligible"
    merge_uncertainty: bool = False
    branch_collisions: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class CleanupStageEvidenceFixture:
    evidence_state: str = "known"
    completed_destructive_stages: list[str] = field(default_factory=list)
    next_idempotent_stage: str | None = None
    stage_status: dict[str, str] = field(
        default_factory=lambda: {
            "freeze": "succeeded",
            "inspect_child_worktrees": "succeeded",
            "child_merge_or_block": "succeeded",
        }
    )
    decision_generated_at: str = "2026-05-15T03:29:31Z"
    child_scan_fresh: bool = True
    child_scan_generation: str = "scan-001"


@dataclass(frozen=True)
class CallerContextFixture:
    caller: str = "session_recovery"
    request_scope: str = "session"
    read_only: bool = False


@dataclass(frozen=True)
class LegacyDiagnosticsFixture:
    owner_session_id: str = LEGACY_OWNER_SESSION_ID
    owner_pid: int = 4242
    owner_ppid: int = 31337
    hook_session_id: str = "claude-hook-session"


def _require_cleanup_api(name: str):
    value = getattr(cleanup, name, None)
    assert callable(value), f"cleanup.{name} contract helper is missing"
    return value


def _session_worktree(**overrides) -> dict[str, object]:
    return asdict(SessionWorktreeFixture(**overrides))


def _child(child_id: str, **overrides) -> dict[str, object]:
    return asdict(ChildFixture(child_id=child_id, **overrides))


def _branch_collision(branch_name: str, **overrides) -> dict[str, object]:
    return asdict(BranchCollisionFixture(branch_name=branch_name, **overrides))


def _merge_state(**overrides) -> dict[str, object]:
    return asdict(MergeStateFixture(**overrides))


def _cleanup_stage_evidence(**overrides) -> dict[str, object]:
    return asdict(CleanupStageEvidenceFixture(**overrides))


def _caller_context(**overrides) -> dict[str, object]:
    return asdict(CallerContextFixture(**overrides))


def _legacy_diagnostics(**overrides) -> dict[str, object]:
    return asdict(LegacyDiagnosticsFixture(**overrides))


def _decision_input(**overrides) -> dict[str, object]:
    payload = {
        "mst_session_id": MST_SESSION_ID,
        "session_worktree": _session_worktree(),
        "children": [_child("REQ-872-T01")],
        "merge_state": _merge_state(),
        "cleanup_stage_evidence": _cleanup_stage_evidence(),
        "caller_context": _caller_context(),
        "legacy_diagnostics": _legacy_diagnostics(),
    }
    payload.update(overrides)
    return copy.deepcopy(payload)


def _resolve_recovery_judgement_state(**kwargs):
    resolver = _require_cleanup_api("resolve_recovery_judgement_state")
    return resolver(**kwargs)


def _affected_resource_kinds(payload: dict[str, object]) -> list[str]:
    resources = payload.get("affected_resources") or []
    return [str(resource.get("kind")) for resource in resources if isinstance(resource, dict)]


def _branch_collision_by_name(payload: dict[str, object], branch_name: str) -> dict[str, object]:
    collisions = payload["merge_state"]["branch_collisions"]
    for collision in collisions:
        if collision.get("branch_name") == branch_name:
            return collision
    raise AssertionError(f"missing branch collision for {branch_name}")


def test_required_recovery_judgement_contract_api_exists() -> None:
    _require_cleanup_api("resolve_recovery_judgement_state")


def test_single_decision_payload_includes_integrated_recovery_fields() -> None:
    payload = _resolve_recovery_judgement_state(**_decision_input())

    for key in (
        "mst_session_id",
        "session_worktree",
        "children",
        "merge_state",
        "cleanup_stage_evidence",
        "primary_action",
        "reason",
        "affected_resources",
    ):
        assert key in payload

    assert payload["mst_session_id"] == MST_SESSION_ID
    assert payload["session_worktree"]["path"] == "/tmp/mst-session-worktree"
    assert payload["children"][0]["child_id"] == "REQ-872-T01"
    assert payload["merge_state"]["session_branch"] == SESSION_BRANCH
    assert payload["primary_action"] == "resume_session"
    assert payload["reason"] == "resume_ready"
    assert {
        "mst_session_id",
        "session_worktree",
        "child_worktree",
        "merge_state",
        "cleanup_stage_evidence",
    }.issubset(set(_affected_resource_kinds(payload)))


def test_decision_precedence_prefers_canonical_identity_before_all_other_blockers() -> None:
    payload = _resolve_recovery_judgement_state(
        **_decision_input(
            session_worktree=_session_worktree(metadata_mst_session_id="MST-OTHER-SESSION"),
            children=[
                _child(
                    "REQ-872-T01",
                    metadata_mst_session_id="MST-OTHER-SESSION",
                    state="dirty",
                    ownership="ownership_ambiguous",
                    scan_fresh=False,
                )
            ],
            merge_state=_merge_state(
                current_base_ref="release/2026.05",
                final_policy_state="uncertain",
                merge_uncertainty=True,
            ),
            cleanup_stage_evidence=_cleanup_stage_evidence(
                evidence_state="unknown",
                child_scan_fresh=False,
            ),
        )
    )

    assert payload["primary_action"] == "blocked_destructive"
    assert payload["reason"] == "canonical_identity_mismatch"
    assert _affected_resource_kinds(payload)[0] == "mst_session_id"


@pytest.mark.parametrize(
    ("case_name", "decision_input", "expected_action", "expected_reason"),
    [
        (
            "resume",
            _decision_input(),
            "resume_session",
            "resume_ready",
        ),
        (
            "cleanup_child",
            _decision_input(
                children=[_child("dirty-child", state="dirty", merge_status="pending")],
                merge_state=_merge_state(final_policy_state="child_cleanup_required"),
            ),
            "cleanup_child",
            "child_dirty",
        ),
        (
            "manual_conflict",
            _decision_input(
                merge_state=_merge_state(
                    current_base_ref="release/2026.05",
                    final_policy_state="manual_conflict_resolution_required",
                    merge_uncertainty=True,
                )
            ),
            "manual_conflict_resolution",
            "base_branch_drift",
        ),
        (
            "blocked_destructive",
            _decision_input(
                cleanup_stage_evidence=_cleanup_stage_evidence(evidence_state="unknown")
            ),
            "blocked_destructive",
            "cleanup_evidence_unknown",
        ),
        (
            "diagnostic_only",
            _decision_input(
                caller_context=_caller_context(
                    caller="dashboard_diagnostic",
                    request_scope="diagnostic",
                    read_only=True,
                )
            ),
            "diagnostic_only",
            "read_only_probe",
        ),
    ],
)
def test_primary_action_vocabulary_returns_exactly_one_supported_action(
    case_name: str,
    decision_input: dict[str, object],
    expected_action: str,
    expected_reason: str,
) -> None:
    payload = _resolve_recovery_judgement_state(**decision_input)

    assert payload["primary_action"] == expected_action, case_name
    assert payload["primary_action"] in SUPPORTED_PRIMARY_ACTIONS, case_name
    assert payload["reason"] == expected_reason, case_name
    assert isinstance(payload["affected_resources"], list), case_name


@pytest.mark.parametrize(
    ("case_name", "decision_input", "expected_reason"),
    [
        (
            "missing",
            _decision_input(
                mst_session_id=None,
                session_worktree=_session_worktree(metadata_mst_session_id=None),
                children=[_child("REQ-872-T01", metadata_mst_session_id=None)],
            ),
            "missing_canonical_identity",
        ),
        (
            "invalid",
            _decision_input(
                mst_session_id="broken-session-id",
                session_worktree=_session_worktree(metadata_mst_session_id="broken-session-id"),
                children=[_child("REQ-872-T01", metadata_mst_session_id="broken-session-id")],
            ),
            "invalid_canonical_identity",
        ),
        (
            "mismatch",
            _decision_input(
                session_worktree=_session_worktree(metadata_mst_session_id="MST-OTHER-SESSION"),
                children=[_child("REQ-872-T01", metadata_mst_session_id="MST-THIRD-SESSION")],
            ),
            "canonical_identity_mismatch",
        ),
    ],
)
def test_canonical_identity_mismatch_does_not_fallback_to_legacy_fields(
    case_name: str,
    decision_input: dict[str, object],
    expected_reason: str,
) -> None:
    payload = _resolve_recovery_judgement_state(**decision_input)

    assert payload["primary_action"] == "blocked_destructive", case_name
    assert payload["reason"] == expected_reason, case_name
    assert payload["mst_session_id"] != LEGACY_OWNER_SESSION_ID, case_name
    assert _affected_resource_kinds(payload)[0] == "mst_session_id", case_name


@pytest.mark.parametrize(
    ("case_name", "child", "cleanup_stage_evidence", "expected_action", "expected_reason"),
    [
        (
            "dirty",
            _child("child-dirty", state="dirty", merge_status="pending"),
            _cleanup_stage_evidence(),
            "cleanup_child",
            "child_dirty",
        ),
        (
            "conflicted",
            _child("child-conflicted", state="conflicted", merge_status="conflicted"),
            _cleanup_stage_evidence(),
            "manual_conflict_resolution",
            "child_conflicted",
        ),
        (
            "orphaned",
            _child("child-orphaned", state="orphaned", ownership="unknown"),
            _cleanup_stage_evidence(),
            "blocked_destructive",
            "orphan_child",
        ),
        (
            "late_arriving_child",
            _child("child-late", state="late_arriving_child", seen_in_freeze_snapshot=False),
            _cleanup_stage_evidence(),
            "blocked_destructive",
            "late_arriving_child",
        ),
        (
            "ownership_ambiguous",
            _child("child-ambiguous", ownership="ownership_ambiguous"),
            _cleanup_stage_evidence(),
            "blocked_destructive",
            "child_ownership_ambiguous",
        ),
        (
            "stale_scan",
            _child("child-stale", scan_fresh=False),
            _cleanup_stage_evidence(child_scan_fresh=False),
            "blocked_destructive",
            "stale_child_scan",
        ),
    ],
)
def test_child_blockers_preserve_work_and_block_destructive_cleanup(
    case_name: str,
    child: dict[str, object],
    cleanup_stage_evidence: dict[str, object],
    expected_action: str,
    expected_reason: str,
) -> None:
    payload = _resolve_recovery_judgement_state(
        **_decision_input(
            children=[child],
            cleanup_stage_evidence=cleanup_stage_evidence,
            merge_state=_merge_state(final_policy_state="blocked_by_child"),
        )
    )

    assert payload["primary_action"] == expected_action, case_name
    assert payload["reason"] == expected_reason, case_name
    assert payload["primary_action"] != "resume_session", case_name
    assert "child_worktree" in _affected_resource_kinds(payload), case_name


def test_interrupted_cleanup_evidence_returns_idempotent_next_stage_or_blocks_unknown() -> None:
    resumed = _resolve_recovery_judgement_state(
        **_decision_input(
            cleanup_stage_evidence=_cleanup_stage_evidence(
                completed_destructive_stages=["child_remove", "session_remove"],
                next_idempotent_stage="branch_or_archive",
                stage_status={
                    "child_remove": "succeeded",
                    "session_remove": "succeeded",
                    "branch_or_archive": "pending",
                },
            ),
            merge_state=_merge_state(final_policy_state="cancelled"),
        )
    )

    assert resumed["primary_action"] == "resume_session"
    assert resumed["reason"] == "resume_from_cleanup_stage"
    assert resumed["cleanup_stage_evidence"]["evidence_state"] == "known"
    assert resumed["completed_destructive_stages"] == ["child_remove", "session_remove"]
    assert resumed["next_idempotent_stage"] == "branch_or_archive"

    blocked = _resolve_recovery_judgement_state(
        **_decision_input(
            cleanup_stage_evidence=_cleanup_stage_evidence(
                evidence_state="unknown",
                completed_destructive_stages=["child_remove"],
                next_idempotent_stage=None,
                stage_status={"child_remove": "unknown"},
            )
        )
    )

    assert blocked["primary_action"] == "blocked_destructive"
    assert blocked["reason"] == "cleanup_evidence_unknown"
    assert blocked["cleanup_stage_evidence"]["evidence_state"] == "unknown"


def test_base_branch_and_collision_evidence_blocks_silent_original_base_merge() -> None:
    payload = _resolve_recovery_judgement_state(
        **_decision_input(
            merge_state=_merge_state(
                original_base_ref="main",
                current_base_ref="release/2026.05",
                child_merge_statuses=["merged_to_session", "conflicted"],
                final_policy_state="manual_conflict_resolution_required",
                merge_uncertainty=True,
                branch_collisions=[
                    _branch_collision(
                        "gran-maestro/main/AGI-038/session-output",
                        ownership="same_name_ambiguous",
                        target_ref="refs/heads/gran-maestro/main/AGI-038/session-output",
                    )
                ],
            )
        )
    )

    assert payload["primary_action"] == "manual_conflict_resolution"
    assert payload["reason"] == "base_branch_drift"
    assert payload["merge_state"]["original_base_ref"] == "main"
    assert payload["merge_state"]["current_base_ref"] == "release/2026.05"
    assert payload["merge_state"]["session_branch"] == SESSION_BRANCH
    assert payload["merge_state"]["child_merge_statuses"] == ["merged_to_session", "conflicted"]
    assert payload["merge_state"]["final_policy_state"] == "manual_conflict_resolution_required"


def test_branch_collision_ownership_never_allows_ambiguous_or_external_recovery_merge() -> None:
    payload = _resolve_recovery_judgement_state(
        **_decision_input(
            merge_state=_merge_state(
                final_policy_state="collision_review_required",
                branch_collisions=[
                    _branch_collision(
                        "gran-maestro/main/AGI-038/owned-output",
                        ownership="same_name_owned",
                        target_ref="refs/heads/gran-maestro/main/AGI-038/owned-output",
                    ),
                    _branch_collision(
                        "gran-maestro/main/AGI-038/ambiguous-output",
                        ownership="same_name_ambiguous",
                        target_ref="refs/heads/gran-maestro/main/AGI-038/ambiguous-output",
                    ),
                    _branch_collision(
                        "external/output",
                        ownership="same_name_external",
                        target_ref="refs/heads/external/output",
                    ),
                ]
            )
        )
    )

    ambiguous = _branch_collision_by_name(payload, "gran-maestro/main/AGI-038/ambiguous-output")
    external = _branch_collision_by_name(payload, "external/output")

    assert ambiguous["ownership"] == "same_name_ambiguous"
    assert ambiguous["recovery_allows"] == {"delete": False, "overwrite": False, "merge": False}
    assert external["ownership"] == "same_name_external"
    assert external["recovery_allows"] == {"delete": False, "overwrite": False, "merge": False}


def test_request_child_accept_scope_blocks_session_cleanup_and_original_base_repair() -> None:
    payload = _resolve_recovery_judgement_state(
        **_decision_input(
            caller_context=_caller_context(
                caller="request_child_accept",
                request_scope="child_accept",
            ),
            merge_state=_merge_state(
                current_base_ref="release/2026.05",
                final_policy_state="final_merge_retry_requested",
                merge_uncertainty=True,
            ),
        )
    )

    assert payload["primary_action"] == "diagnostic_only"
    assert payload["reason"] == "request_child_accept_scope"
    assert payload["primary_action"] in SUPPORTED_PRIMARY_ACTIONS
    assert {"session_worktree", "merge_state"}.issubset(set(_affected_resource_kinds(payload)))
