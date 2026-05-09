from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.mst_cmds import session as session_cmds
from scripts.mst_cmds import stop_judge


SESSION_ID = "MST-AGI-034-20260509T000000000Z-stopj001"
OTHER_SESSION_ID = "MST-AGI-034-20260509T000000000Z-stopj002"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict) -> Path:
    return _write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    return root


def _canonical_state_payload(session_id: str, **extra: object) -> dict:
    parsed = session_cmds.validate_mst_session_id(session_id)
    payload = {
        "schema_version": 1,
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
    }
    payload.update(extra)
    return payload


def _stdin_file(project_root: Path, payload: object, *, raw: bool = False) -> Path:
    path = project_root / "stop-stdin.json"
    if raw:
        path.write_text(str(payload), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _state_file(project_root: Path, session_id: str, payload: dict) -> Path:
    return _write_json(project_root / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json", payload)


def test_evaluate_stop_judge_returns_structured_decision_and_wrapper_payload(tmp_path: Path) -> None:
    project_root = _project_root(tmp_path)
    _state_file(project_root, SESSION_ID, _canonical_state_payload(SESSION_ID, workflow_active=False))
    stdin_file = _stdin_file(project_root, {"mst_session_id": SESSION_ID, "stop_hook_active": False})

    decision = stop_judge.evaluate_stop_judge(
        project_root=project_root,
        stdin_file=stdin_file,
        hook_timeout_ms=5000,
    )

    assert set(decision) >= {"decision", "reason", "diagnostics", "side_effects"}
    assert decision["decision"] == "approve"
    assert isinstance(decision["diagnostics"], dict)
    assert isinstance(decision["side_effects"], list)

    wrapper_payload = stop_judge.format_stop_judge_wrapper_payload(decision)
    assert wrapper_payload == {"decision": "approve", "reason": decision["reason"]}


@pytest.mark.parametrize(
    ("signals", "expected_decision", "expected_reason"),
    [
        (
            {
                "canonical_mismatch": True,
                "return_to": "mst:plan/step-2",
                "snapshot_in_progress": True,
            },
            "block",
            "canonical mst_session_id mismatch",
        ),
        (
            {
                "return_to": "mst:plan/step-2",
                "snapshot_in_progress": True,
                "queued_next_action": {"skill": "mst:request"},
            },
            "block",
            "return_to=mst:plan/step-2",
        ),
        (
            {
                "snapshot_in_progress": True,
                "queued_next_action": {"skill": "mst:request"},
                "workflow_active": True,
            },
            "block",
            "snapshot progress incomplete",
        ),
        (
            {
                "queued_next_action": {"skill": "mst:request", "source_id": "PLN-678"},
                "agile_loop_active": True,
                "workflow_active": True,
            },
            "block",
            "queued next_action present",
        ),
        (
            {
                "agile_loop_active": True,
                "workflow_active": True,
                "boundary_repair_required": True,
            },
            "block",
            "agile loop active",
        ),
        (
            {
                "workflow_active": True,
                "boundary_repair_required": True,
            },
            "block",
            "Workflow active, continue current skill",
        ),
        (
            {
                "boundary_repair_required": True,
            },
            "block",
            "boundary repair required",
        ),
        (
            {},
            "approve",
            "approved",
        ),
    ],
)
def test_reduce_stop_judge_respects_priority_order(
    signals: dict[str, object],
    expected_decision: str,
    expected_reason: str,
) -> None:
    decision = stop_judge.reduce_stop_judge_decision(
        {
            "signals": signals,
            "diagnostics": {"canonical_mst_session_id": SESSION_ID},
            "side_effects": [],
            "hook_timeout_ms": 5000,
        }
    )

    assert decision["decision"] == expected_decision
    assert expected_reason in decision["reason"]


def test_missing_canonical_session_keeps_fail_open_semantics_and_does_not_promote_legacy_ids(
    tmp_path: Path,
) -> None:
    project_root = _project_root(tmp_path)
    stdin_file = _stdin_file(
        project_root,
        {
            "session_id": "legacy-session-123",
            "owner_session_id": "owner-session-456",
            "owner_ppid": 97511,
            "stop_hook_active": False,
        },
    )

    decision = stop_judge.evaluate_stop_judge(
        project_root=project_root,
        stdin_file=stdin_file,
        hook_timeout_ms=5000,
    )

    assert decision["decision"] == "approve"
    assert "no canonical mst_session_id" in decision["reason"]
    assert decision["diagnostics"]["canonical_mst_session_id"] is None
    assert decision["diagnostics"]["legacy_identity_present"] is True


def test_true_canonical_mismatch_blocks(tmp_path: Path) -> None:
    project_root = _project_root(tmp_path)
    _state_file(
        project_root,
        SESSION_ID,
        _canonical_state_payload(OTHER_SESSION_ID, workflow_active=False),
    )
    stdin_file = _stdin_file(project_root, {"mst_session_id": SESSION_ID, "stop_hook_active": False})

    decision = stop_judge.evaluate_stop_judge(
        project_root=project_root,
        stdin_file=stdin_file,
        hook_timeout_ms=5000,
    )

    assert decision["decision"] == "block"
    assert "canonical mst_session_id mismatch" in decision["reason"]


def test_corrupted_mandatory_state_blocks(tmp_path: Path) -> None:
    project_root = _project_root(tmp_path)
    _state_file(
        project_root,
        SESSION_ID,
        {"mst_session_id": SESSION_ID, "workflow_active": True},
    )
    stdin_file = _stdin_file(project_root, {"mst_session_id": SESSION_ID, "stop_hook_active": False})

    decision = stop_judge.evaluate_stop_judge(
        project_root=project_root,
        stdin_file=stdin_file,
        hook_timeout_ms=5000,
    )

    assert decision["decision"] == "block"
    assert "corrupted mandatory state" in decision["reason"]


def test_invalid_stdin_returns_fail_open_fallback(tmp_path: Path) -> None:
    project_root = _project_root(tmp_path)
    stdin_file = _stdin_file(project_root, "{not-json", raw=True)

    decision = stop_judge.evaluate_stop_judge(
        project_root=project_root,
        stdin_file=stdin_file,
        hook_timeout_ms=5000,
    )

    assert decision["decision"] == "approve"
    assert "invalid stop hook stdin" in decision["reason"]
    assert decision["diagnostics"]["failsafe"] == "invalid_stdin"


@pytest.mark.parametrize(
    ("failsafe", "expected_reason"),
    [
        ("judge_timeout", "hook judge timeout (>5000ms) fail-open"),
        ("startup_failure", "hook judge startup failure fail-open"),
    ],
)
def test_reduce_stop_judge_documents_timeout_and_startup_fallbacks(
    failsafe: str,
    expected_reason: str,
) -> None:
    decision = stop_judge.reduce_stop_judge_decision(
        {
            "failsafe": failsafe,
            "signals": {},
            "diagnostics": {},
            "side_effects": [],
            "hook_timeout_ms": 5000,
        }
    )

    assert decision["decision"] == "approve"
    assert decision["reason"] == expected_reason
    assert decision["diagnostics"]["failsafe"] == failsafe


def test_apply_stop_judge_side_effects_uses_precomputed_side_effects_only(tmp_path: Path) -> None:
    project_root = _project_root(tmp_path)
    decision = {
        "decision": "block",
        "reason": "queued next_action present",
        "diagnostics": {"source": "test"},
        "side_effects": [
            {"kind": "persist_block_state", "session_id": SESSION_ID},
            {"kind": "append_audit", "event": "core_block"},
        ],
    }

    applied = stop_judge.apply_stop_judge_side_effects(project_root=project_root, decision=decision)

    assert applied == decision["side_effects"]
