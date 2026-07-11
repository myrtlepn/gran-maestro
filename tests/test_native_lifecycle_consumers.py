from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds import state as state_cmds
from scripts.mst_cmds.current_work_handoff import (
    project_current_work_handoff,
    project_lifecycle_artifact_consumer_summary,
    project_lifecycle_artifacts_for_session,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-REQ-939-20260711T131345269Z-consumer1"
OTHER_SID = "MST-REQ-939-20260711T131345269Z-consumer2"
ROOT = "REQ-939"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MST_SESSION_ID"] = SID
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env.pop("MST_CONTEXT_JSON", None)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _artifact_paths(base: Path, task_id: str, *, output_exists: bool) -> dict[str, str]:
    artifact_dir = base / "run" / "artifacts" / task_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    running = artifact_dir / "running.log"
    trace = artifact_dir / "trace.ndjson"
    output = artifact_dir / "result.md"
    running.write_text("running\n", encoding="utf-8")
    trace.write_text('{"event":"consumer-test"}\n', encoding="utf-8")
    if output_exists:
        output.write_text("native result\n", encoding="utf-8")
    return {
        "running_log_path": str(running),
        "trace_path": str(trace),
        "output_path": str(output),
    }


def _state(base: Path, kind: str, *, session_id: str = SID, ordinal: int = 1) -> dict:
    task_id = f"REQ-939-{kind.upper()}"
    native_attempt_id = f"{task_id}-native-a1"
    timestamp = f"2026-07-11T13:00:0{ordinal}.000Z"
    current_attempt_id = native_attempt_id
    phase = "done"
    status = "completed"
    completion_signal: str | None = "completed"
    execution_transport = "native"
    exit_code: int | None = None
    reconciliation_action = None
    fallback_from = None
    fallback_to = None
    output_exists = kind in {
        "completed",
        "fallback",
        "native_resolved",
        "terminal_pending",
    }

    if kind == "failed":
        phase = "failed"
        status = "failed"
        completion_signal = "failed"
    elif kind == "orphan":
        phase = "reconciling"
        status = "reconciling"
        completion_signal = None
        reconciliation_action = {
            "kind": "provider_reconcile",
            "action_id": f"provider-reconcile:{task_id}",
            "lookup_key": f"provider-{kind}-1",
            "provider": "codex",
            "provider_task_id": f"provider-{kind}-1",
            "attempt_id": native_attempt_id,
            "status": "pending",
            "completion_accepted": False,
        }
    elif kind == "fallback":
        current_attempt_id = f"{task_id}-external-a2"
        execution_transport = "external"
        status = "fallback_completed"
        fallback_from = native_attempt_id
        exit_code = 0
    elif kind == "external_failed":
        phase = "failed"
        status = "failed"
        completion_signal = "process_exit"
        execution_transport = "external"
        exit_code = 3
    elif kind == "external_reconciling":
        phase = "reconciling"
        status = "reconciling"
        completion_signal = None
        execution_transport = "external"
        exit_code = None
        reconciliation_action = {
            "kind": "provider_reconcile",
            "action_id": f"provider-reconcile:{task_id}",
            "lookup_key": f"attempt:{native_attempt_id}",
            "provider": "codex",
            "provider_task_id": None,
            "attempt_id": native_attempt_id,
            "status": "pending",
            "completion_accepted": False,
            "reason_code": "termination_unconfirmed",
            "next_operation": "reconcile_external_provider_group",
            "required_result_fields": [
                "provider_state",
                "completion_signal",
                "group_observed_gone",
                "observed_at",
            ],
        }
    elif kind in {"native_resolved", "external_resolved"}:
        if kind == "external_resolved":
            phase = "terminated"
            status = "cancelled"
            completion_signal = "process_cancelled"
            execution_transport = "external"
            exit_code = 143
        reconciliation_action = {
            "kind": "provider_reconcile",
            "action_id": f"provider-reconcile:{task_id}",
            "lookup_key": f"attempt:{native_attempt_id}",
            "provider": "codex",
            "provider_task_id": None,
            "attempt_id": native_attempt_id,
            "status": "resolved",
            "completion_accepted": True,
            "requested_at": "2026-07-11T12:59:59.000Z",
            "resolved_at": timestamp,
            "result": {
                "provider_state": "cancelled" if kind == "external_resolved" else "completed",
                "prior_provider_state": "unknown",
                "completion_signal": completion_signal,
                "phase": phase,
                "status": status,
                "exit_code": exit_code,
                "group_observed_gone": True if kind == "external_resolved" else None,
                "observed_at": timestamp,
                "evidence_source": "terminal_lifecycle_state",
            },
        }
    elif kind == "terminal_pending":
        reconciliation_action = {
            "kind": "provider_reconcile",
            "action_id": f"provider-reconcile:{task_id}",
            "lookup_key": f"attempt:{native_attempt_id}",
            "provider": "codex",
            "provider_task_id": None,
            "attempt_id": native_attempt_id,
            "status": "pending",
            "completion_accepted": False,
        }

    paths = _artifact_paths(base, task_id, output_exists=output_exists)
    state = {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": ROOT,
        "parent_session_id": session_id,
        "task_id": task_id,
        "attempt_id": current_attempt_id,
        "current_attempt": True,
        "execution_transport": execution_transport,
        "external_control_surface": "host_bridge" if execution_transport == "native" else "provider_cli_adapter",
        "host": "codex",
        "provider": "codex",
        "provider_task_id": f"provider-{kind}-1" if kind != "fallback" else None,
        "route_reason": (
            "same_host_native_capable"
            if kind != "fallback"
            else "external_fallback_after_definitive_not_created"
        ),
        "phase": phase,
        "status": status,
        "completion_signal": completion_signal,
        "exit_code": exit_code,
        "fallback_from": fallback_from,
        "fallback_to": fallback_to,
        "provider_reconciliation_required": kind in {
            "orphan",
            "external_reconciling",
            "terminal_pending",
        },
        "reconciliation_action": reconciliation_action,
        "started_at": timestamp,
        "last_heartbeat": timestamp,
        "updated_at": timestamp,
        "terminated_at": timestamp if phase in {"done", "failed", "terminated"} else None,
        **paths,
    }
    if kind in {"external_failed", "external_reconciling", "external_resolved"}:
        state.update(
            {
                "external_claim_id": f"claim-{task_id}",
                "artifact_binding_version": 2,
            }
        )
    if kind == "external_failed":
        state["stderr_evidence"] = {
            "sha256": "sha256:" + "a" * 64,
            "byte_count": 23,
            "truncated": False,
            "redacted_tail": "provider failed",
        }
    attempts = []
    if kind == "fallback":
        attempts.append(
            {
                **state,
                "attempt_id": native_attempt_id,
                "current_attempt": False,
                "execution_transport": "native",
                "provider_task_id": None,
                "phase": "planned",
                "status": "definitive_not_created",
                "completion_signal": None,
                "exit_code": None,
                "fallback_from": None,
                "fallback_to": current_attempt_id,
            }
        )
    attempts.append({**state, "attempts": []})
    state["attempts"] = attempts
    return state


def _write_state(base: Path, state: dict) -> Path:
    path = base / "run" / f"{state['task_id']}.json"
    _write_json(path, state)
    return path


def _assert_retained(summary: dict, expected: dict) -> None:
    for field in (
        "provider_task_id",
        "execution_transport",
        "completion_signal",
        "exit_code",
        "provider_reconciliation_required",
        "reconciliation_action",
        "fallback_from",
        "fallback_to",
        "running_log_path",
        "trace_path",
        "output_path",
    ):
        assert summary[field] == expected[field], field
    assert summary["attempt_linkage"] == {
        "task_id": expected["task_id"],
        "attempt_id": expected["attempt_id"],
        "parent_session_id": SID,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
    }


def test_session_scoped_consumer_restores_completed_failed_orphan_and_fallback(tmp_path: Path) -> None:
    base = tmp_path / "workspace" / ".gran-maestro"
    expected = {}
    for ordinal, kind in enumerate(
        (
            "completed",
            "failed",
            "orphan",
            "fallback",
            "external_failed",
            "external_reconciling",
            "native_resolved",
            "external_resolved",
        ),
        start=1,
    ):
        state = _state(base, kind, ordinal=ordinal)
        _write_state(base, state)
        expected[state["task_id"]] = state
    _write_state(base, _state(base, "unrelated", session_id=OTHER_SID, ordinal=9))

    projected = project_lifecycle_artifacts_for_session(base, SID)
    by_task = {item["task_id"]: item for item in projected}
    assert set(by_task) == set(expected)
    for task_id, state in expected.items():
        _assert_retained(by_task[task_id], state)

    assert by_task["REQ-939-COMPLETED"]["consumer_status"] == "success"
    assert by_task["REQ-939-FAILED"]["consumer_status"] == "non_success"
    assert by_task["REQ-939-ORPHAN"]["consumer_status"] == "non_success"
    assert by_task["REQ-939-EXTERNAL_FAILED"]["consumer_status"] == "non_success"
    assert by_task["REQ-939-EXTERNAL_FAILED"]["gaps"] == []
    assert by_task["REQ-939-EXTERNAL_RECONCILING"]["consumer_status"] == "non_success"
    assert by_task["REQ-939-EXTERNAL_RECONCILING"]["reconciliation_action"]["status"] == "pending"
    assert by_task["REQ-939-NATIVE_RESOLVED"]["consumer_status"] == "success"
    assert by_task["REQ-939-NATIVE_RESOLVED"]["reconciliation_action"]["status"] == "resolved"
    assert by_task["REQ-939-EXTERNAL_RESOLVED"]["consumer_status"] == "non_success"
    assert by_task["REQ-939-EXTERNAL_RESOLVED"]["reconciliation_action"]["status"] == "resolved"
    fallback_attempts = {
        item["attempt_id"]: item for item in by_task["REQ-939-FALLBACK"]["attempts"]
    }
    assert fallback_attempts["REQ-939-FALLBACK-native-a1"]["fallback_to"] == "REQ-939-FALLBACK-external-a2"
    assert fallback_attempts["REQ-939-FALLBACK-external-a2"]["fallback_from"] == "REQ-939-FALLBACK-native-a1"


@pytest.mark.parametrize(
    ("kind", "continuation_state"),
    [
        ("completed", "parent_continuation_ready"),
        ("failed", "recovery_ready"),
        ("orphan", "recovery_ready"),
        ("fallback", "parent_continuation_ready"),
        ("external_failed", "recovery_ready"),
        ("external_reconciling", "recovery_ready"),
        ("native_resolved", "parent_continuation_ready"),
        ("external_resolved", "recovery_ready"),
    ],
)
def test_current_work_and_recover_resume_envelope_restore_session_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    continuation_state: str,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    state = _state(base, kind)
    _write_state(base, state)

    current_work = _run_mst(workspace, "current-work-handoff", "--session-id", SID)
    assert current_work.returncode == 0, current_work.stderr
    current_payload = json.loads(current_work.stdout)
    _assert_retained(current_payload["lifecycle_artifact_consumer"], state)
    assert current_payload["continuation_handoff"]["continuation_state"] == continuation_state

    monkeypatch.setattr(_common, "BASE_DIR", base)
    history_dir = base / "sessions" / SID
    history_dir.mkdir(parents=True, exist_ok=True)
    history_result = SimpleNamespace(
        rows=[],
        history_file=history_dir / "history.ndjson",
        tail_hash="a" * 64,
        tail_seq=1,
    )
    envelope = state_cmds._recover_rehydration_bundle(
        session_id=SID,
        root_mst_id=ROOT,
        snapshot={
            "status": "active",
            "currentSkill": "request",
            "currentStep": 2,
            "totalSteps": 5,
            "nextSkill": {"name": "mst:request", "source_id": ROOT},
        },
        root_payload={"status": "executing"},
        history_result=history_result,
        previous_history_head="0" * 64,
        recovery_fingerprint=f"recover:{ROOT}:consumer",
    )
    _assert_retained(envelope["lifecycle_artifact_consumer"], state)
    _assert_retained(envelope["current_work_handoff"]["lifecycle_artifact_consumer"], state)
    _assert_retained(
        envelope["next_execution"]["context"]["lifecycle_artifact_consumer"],
        state,
    )
    assert (
        envelope["current_work_handoff"]["continuation_handoff"]["continuation_state"]
        == continuation_state
    )


def test_terminal_pending_reconciliation_is_an_invariant_gap_and_cannot_continue(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    state = _state(base, "terminal_pending")
    _write_state(base, state)

    summary = project_lifecycle_artifact_consumer_summary(state)
    assert summary["consumer_status"] == "gap"
    assert {
        gap["code"] for gap in summary["gaps"]
    } == {
        "terminal_reconciliation_required",
        "terminal_pending_reconciliation",
    }

    current_work = _run_mst(workspace, "current-work-handoff", "--session-id", SID)
    assert current_work.returncode == 0, current_work.stderr
    current_payload = json.loads(current_work.stdout)
    assert current_payload["lifecycle_artifact_consumer"]["consumer_status"] == "gap"
    assert current_payload["continuation_handoff"]["completion_status"] == "unknown"
    assert current_payload["continuation_handoff"]["continuation_state"] == "no_completion_evidence"
    assert current_payload["continuation_handoff"]["consumable"] is False
    assert current_payload["continue"]["queued_action"] is None

    listed = _run_mst(workspace, "dispatch", "list", "--format", "json")
    assert listed.returncode == 0, listed.stderr
    row = next(
        item
        for item in json.loads(listed.stdout)
        if item["task_id"] == state["task_id"]
    )
    assert row["phase"] == "done"
    assert row["reconciliation_required"] is False
    assert row["reconciliation_invariant_gap"] is True
    assert row["reconciliation_action"]["status"] == "pending"

    explicit_completion = project_current_work_handoff(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "identity": {
                "env": {"MST_SESSION_ID": SID},
                "context": {"mst_session_id": SID},
            },
            "lifecycle_artifact_consumer": summary,
            "dispatch_completion": {
                "status": "completed",
                "task_id": state["task_id"],
                "parent_mst_session_id": SID,
                "next_action_idempotency_key": "must-not-run",
            },
            "next_action_source": {
                "action_type": "continue_skill",
                "label": "must not run",
                "idempotency_key": "must-not-run",
            },
        }
    )
    assert explicit_completion["continuation_handoff"]["completion_status"] == "unknown"
    assert explicit_completion["continuation_handoff"]["continuation_state"] == "no_completion_evidence"
    assert explicit_completion["continuation_handoff"]["consumable"] is False
    assert explicit_completion["continue"]["queued_action"] is None

    malformed_resolved = json.loads(json.dumps(state))
    malformed_resolved["provider_reconciliation_required"] = False
    malformed_resolved["reconciliation_action"].update(
        {
            "status": "resolved",
            "completion_accepted": True,
            "resolved_at": state["terminated_at"],
            "result": {},
        }
    )
    malformed_resolved["attempts"][-1]["provider_reconciliation_required"] = False
    malformed_resolved["attempts"][-1]["reconciliation_action"] = dict(
        malformed_resolved["reconciliation_action"]
    )
    incomplete = project_lifecycle_artifact_consumer_summary(malformed_resolved)
    assert incomplete["consumer_status"] == "gap"
    assert {
        gap["code"] for gap in incomplete["gaps"]
    } == {"terminal_reconciliation_resolution_incomplete"}


@pytest.mark.parametrize(
    "kind",
    ("completed", "external_failed", "native_resolved", "external_resolved"),
)
def test_request_history_and_inspect_and_session_inspect_restore_terminal_evidence(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    state = _state(base, kind)
    _write_state(base, state)
    _write_json(
        base / "requests" / ROOT / "request.json",
        {
            "id": ROOT,
            "title": "Native lifecycle consumer",
            "status": "completed",
            "current_phase": 5,
            "mst_session_id": SID,
        },
    )
    _write_json(
        base / "sessions" / SID / "session.json",
        {"schema_version": 1, "mst_session_id": SID, "root_mst_id": ROOT},
    )

    request_inspect = _run_mst(workspace, "request", "inspect", ROOT, "--json")
    assert request_inspect.returncode == 0, request_inspect.stderr
    request_payload = json.loads(request_inspect.stdout)
    _assert_retained(request_payload["native_lifecycle"]["latest"], state)

    request_history = _run_mst(workspace, "request", "history", "--format", "json")
    assert request_history.returncode == 0, request_history.stderr
    history_payload = json.loads(request_history.stdout)
    _assert_retained(history_payload["native_lifecycle"]["latest"], state)

    session_inspect = _run_mst(workspace, "session", "inspect", SID)
    assert session_inspect.returncode == 0, session_inspect.stderr
    session_payload = json.loads(session_inspect.stdout)
    _assert_retained(session_payload["native_lifecycle"]["latest"], state)
    if kind == "external_failed":
        for summary in (
            request_payload["native_lifecycle"]["latest"],
            history_payload["native_lifecycle"]["latest"],
            session_payload["native_lifecycle"]["latest"],
        ):
            assert summary["consumer_status"] == "non_success"
            assert summary["gaps"] == []
            assert summary["artifacts"]["stderr_evidence"]["byte_count"] == 23
    if kind in {"native_resolved", "external_resolved"}:
        for summary in (
            request_payload["native_lifecycle"]["latest"],
            history_payload["native_lifecycle"]["latest"],
            session_payload["native_lifecycle"]["latest"],
        ):
            assert summary["provider_reconciliation_required"] is False
            assert summary["reconciliation_action"]["status"] == "resolved"
            assert summary["reconciliation_action"]["completion_accepted"] is True


@pytest.mark.parametrize(
    "kind",
    ("completed", "external_failed", "native_resolved", "external_resolved"),
)
def test_terminal_history_fallback_remains_available_after_run_state_cleanup(
    tmp_path: Path,
    kind: str,
) -> None:
    base = tmp_path / "workspace" / ".gran-maestro"
    state = _state(base, kind)
    run_path = _write_state(base, state)
    history_path = base / "history" / "native-delegation.ndjson"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps({**state, "observed_at": state["updated_at"]}) + "\n", encoding="utf-8")
    run_path.unlink()

    projected = project_lifecycle_artifacts_for_session(base, SID, terminal_only=True)
    assert len(projected) == 1
    _assert_retained(projected[0], state)
    assert projected[0]["terminal"] is True
    assert projected[0]["source_path"] == str(history_path)
    assert projected[0]["consumer_status"] == (
        "success" if kind in {"completed", "native_resolved"} else "non_success"
    )
    if kind in {"native_resolved", "external_resolved"}:
        assert projected[0]["provider_reconciliation_required"] is False
        assert projected[0]["reconciliation_action"]["status"] == "resolved"
