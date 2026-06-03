from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass

from scripts.mst_cmds import worktree


MST_SESSION_ID = "MST-AGI-038-20260515T082215000Z-dod014"
SESSION_BRANCH = "gran-maestro/session/AGI-038-dod014"


@dataclass(frozen=True)
class ChildMergeFixture:
    child_id: str
    req_id: str = "REQ-879"
    task_id: str = "01"
    child_branch: str = "gran-maestro/session/AGI-038-dod014/REQ-879-01"
    ready_at: str = "2026-05-15T08:22:15Z"
    priority: int = 100
    state: str = "ready"
    merge_outcome: str | None = None
    cleanup_outcome: str | None = None


def _require_worktree_api(name: str):
    value = getattr(worktree, name, None)
    assert callable(value), f"worktree.{name} contract helper is missing"
    return value


def _child(child_id: str, **overrides: object) -> dict[str, object]:
    data = asdict(ChildMergeFixture(child_id=child_id))
    data.update(overrides)
    if "child_branch" not in overrides:
        data["child_branch"] = f"gran-maestro/session/AGI-038-dod014/{data['req_id']}-{data['task_id']}-{child_id}"
    return data


def _event(child: dict[str, object], *, status: str = "succeeded", stage: str = "child_merge_or_block") -> dict[str, object]:
    resolver = _require_worktree_api("child_merge_idempotency_key")
    return {
        "stage": stage,
        "status": status,
        "child_id": child["child_id"],
        "idempotency_key": resolver(
            mst_session_id=MST_SESSION_ID,
            req_id=str(child["req_id"]),
            task_id=str(child["task_id"]),
            child_id=str(child["child_id"]),
            child_branch=str(child["child_branch"]),
            target_branch=SESSION_BRANCH,
        ),
    }


def _resolve(children: list[dict[str, object]], *, durable_events: list[dict[str, object]] | None = None) -> dict[str, object]:
    resolver = _require_worktree_api("resolve_child_merge_queue_state")
    return resolver(
        mst_session_id=MST_SESSION_ID,
        session_branch=SESSION_BRANCH,
        children=children,
        durable_events=durable_events or [],
    )


def test_required_child_merge_contract_api_exists() -> None:
    _require_worktree_api("resolve_child_merge_queue_state")
    _require_worktree_api("child_merge_idempotency_key")
    _require_worktree_api("cmd_worktree_child_merge_queue")


def test_child_merge_queue_cli_exposes_ordering_and_blockers(capsys) -> None:
    ready = _child("ready", req_id="REQ-879", task_id="02", priority=20)
    late = _child("late", req_id="REQ-879", task_id="01", priority=10, state="late_arriving_child")

    exit_code = worktree.cmd_worktree_child_merge_queue(
        argparse.Namespace(
            mst_session_id=MST_SESSION_ID,
            session_branch=SESSION_BRANCH,
            children_json=json.dumps([ready, late]),
            durable_events_json="[]",
            json=True,
        )
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["merge_queue_state"] == "blocked"
    assert payload["session_final_merge_blocked"] is True
    assert [entry["child_id"] for entry in payload["queue"]] == ["late", "ready"]
    assert payload["queue"][0]["merge_state"] == "late_arriving_child"
    assert payload["queue"][1]["idempotency_key"]
    assert payload["blockers"] == [
        {
            "child_id": "late",
            "state": "late_arriving_child",
            "reason": "reconcile_child_before_final_merge",
        }
    ]


def test_ordering_is_deterministic_by_priority_ready_time_request_task_and_child_identity() -> None:
    first = _child("b", req_id="REQ-879", task_id="02", priority=20, ready_at="2026-05-15T08:22:15Z")
    second = _child("a", req_id="REQ-879", task_id="01", priority=20, ready_at="2026-05-15T08:22:15Z")
    third = _child("c", req_id="REQ-880", task_id="01", priority=40, ready_at="2026-05-15T08:20:00Z")

    payload = _resolve([first, third, second])

    assert payload["ok"] is True
    assert payload["merge_queue_state"] == "ready"
    assert payload["session_final_merge_blocked"] is True
    assert [entry["child_id"] for entry in payload["queue"]] == ["a", "b", "c"]
    assert [entry["queue_position"] for entry in payload["queue"]] == [1, 2, 3]
    assert payload["serialization"] == "deterministic_queue"


def test_strategy_targets_parent_session_branch_only() -> None:
    child = _child("strategy")

    payload = _resolve([child])
    entry = payload["queue"][0]

    assert entry["merge_strategy"] == {
        "name": "no_ff_child_to_session",
        "target_branch": SESSION_BRANCH,
        "child_branch": child["child_branch"],
        "child_to_session": True,
        "session_to_original": False,
    }
    assert entry["merge_target"] == SESSION_BRANCH
    assert entry["session_to_original"] is False
    assert payload["target_branch"] == SESSION_BRANCH


def test_commit_identity_metadata_preserves_request_task_child_and_session_linkage() -> None:
    child = _child("identity", req_id="REQ-879", task_id="07")

    payload = _resolve([child])
    metadata = payload["queue"][0]["commit_metadata"]

    assert metadata["mst_session_id"] == MST_SESSION_ID
    assert metadata["req_id"] == "REQ-879"
    assert metadata["task_id"] == "07"
    assert metadata["child_id"] == "identity"
    assert metadata["child_branch"] == child["child_branch"]
    assert metadata["target_branch"] == SESSION_BRANCH
    assert re.search(r"REQ-879.*T07.*identity", metadata["message"])


def test_idempotency_key_blocks_already_merged_replay() -> None:
    child = _child("already-merged")

    payload = _resolve([child], durable_events=[_event(child)])
    entry = payload["queue"][0]

    assert entry["merge_state"] == "already_merged"
    assert entry["merge_required"] is False
    assert entry["idempotency_key"] == payload["idempotency_keys"][0]
    assert payload["ok"] is True
    assert payload["merge_queue_state"] == "idempotent_replay"


def test_duplicate_idempotency_key_allows_only_one_merge_required_entry() -> None:
    original = _child("dup", req_id="REQ-879", task_id="01")
    duplicate = dict(original)

    payload = _resolve([duplicate, original])

    merge_required = [entry for entry in payload["queue"] if entry["merge_required"]]
    duplicates = [entry for entry in payload["queue"] if entry["merge_state"] == "duplicate_child"]

    assert len(merge_required) == 1
    assert len(duplicates) == 1
    assert duplicates[0]["duplicate_of"] == merge_required[0]["idempotency_key"]
    assert payload["diagnostics"] == [
        {
            "code": "duplicate_child_merge",
            "child_id": "dup",
            "idempotency_key": merge_required[0]["idempotency_key"],
        }
    ]


def test_conflict_and_partial_merge_evidence_block_session_final_merge() -> None:
    conflict = _child("conflict", state="conflicted", merge_outcome="conflict")
    partial = _child("partial", state="partial", merge_outcome="partial")

    payload = _resolve([partial, conflict])

    assert payload["ok"] is False
    assert payload["merge_queue_state"] == "blocked"
    assert payload["session_final_merge_blocked"] is True
    assert payload["blockers"] == [
        {"child_id": "conflict", "state": "child_conflict", "reason": "resolve_child_conflict"},
        {"child_id": "partial", "state": "partial_merge", "reason": "resume_or_reconcile_partial_merge"},
    ]
    assert {entry["merge_state"] for entry in payload["queue"]} == {"child_conflict", "partial_merge"}


def test_cleanup_failure_and_late_arriving_child_block_with_retry_actions() -> None:
    cleanup_failed = _child("cleanup", state="merged", merge_outcome="merged", cleanup_outcome="remove_failed")
    late = _child("late", state="late_arriving_child")

    payload = _resolve([late, cleanup_failed], durable_events=[_event(cleanup_failed)])

    assert payload["ok"] is False
    assert payload["merge_queue_state"] == "blocked"
    assert payload["session_final_merge_blocked"] is True
    assert payload["blockers"] == [
        {
            "child_id": "cleanup",
            "state": "merged_to_session_cleanup_failed",
            "reason": "retry_child_cleanup",
        },
        {
            "child_id": "late",
            "state": "late_arriving_child",
            "reason": "reconcile_child_before_final_merge",
        },
    ]
    cleanup_entry = next(entry for entry in payload["queue"] if entry["child_id"] == "cleanup")
    late_entry = next(entry for entry in payload["queue"] if entry["child_id"] == "late")
    assert cleanup_entry["merge_required"] is False
    assert cleanup_entry["next_action"] == "retry_child_cleanup"
    assert late_entry["next_action"] == "reconcile_child_before_final_merge"
