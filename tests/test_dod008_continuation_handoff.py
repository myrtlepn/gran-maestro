from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"

SID = "MST-AGI-040-20260520T031335000Z-req91702"
OTHER_SID = "MST-AGI-040-20260520T031336000Z-req91799"
TASK_ID = "REQ-917-02"
HOOK_UUID = "11111111-2222-4333-8444-555555555555"
OWNER_SESSION_ID = "legacy-owner-session"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _queue_path(workspace: Path) -> Path:
    return workspace / ".gran-maestro" / "pending.ndjson"


def _run_mst(workspace: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    for key in (
        "MST_SESSION_ID",
        "MST_CONTEXT_JSON",
        "MST_HOOK_STDIN_RAW",
        "MST_STATE_PPID",
        "MST_SNAPSHOT_SESSION_ID",
        "CLAUDE_SESSION_ID",
    ):
        merged_env.pop(key, None)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _read_queue(workspace: Path) -> list[dict]:
    path = _queue_path(workspace)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_queue(workspace: Path, entries: list[dict]) -> None:
    path = _queue_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


def _queue_entry(
    workspace: Path,
    *,
    skill: str = "mst:request",
    args: str = "--plan PLN-741 -a",
    status: str = "queued",
    idempotency_key: str | None = None,
    mst_session_id: str | None = None,
    queue_session_id: str | None = None,
    next_action_idempotency_key: str | None = None,
    completion_evidence_path: str | None = None,
    failure_metadata_path: str | None = None,
    headless_terminal_status: str = "done",
    headless_terminal_reason: str | None = None,
    headless_next_action: dict | None = None,
    legacy_fields: dict | None = None,
) -> dict:
    entry_id = uuid.uuid4().hex
    if idempotency_key is None:
        idempotency_key = f"dod008:{skill}:{args}"
    if mst_session_id:
        default_session_id = mst_session_id
    else:
        default_session_id = queue_session_id or ""
    if completion_evidence_path is None:
        completion_evidence_path = str(
            workspace / ".gran-maestro" / "queue" / "completion" / f"{entry_id}.json"
        )
    if failure_metadata_path is None:
        failure_metadata_path = str(
            workspace / ".gran-maestro" / "queue" / "failures" / f"{entry_id}.json"
        )
    entry = {
        "id": uuid.uuid4().hex,
        "entry_id": entry_id,
        "skill": skill,
        "args": args,
        "source_skill": "mst:plan",
        "source_id": "PLN-741",
        "resource_id": "AGI-040",
        "auto": True,
        "status": status,
        "created_at": "2026-05-20T03:00:00+00:00",
        "consumed_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
        "idempotency_key": idempotency_key,
        "mst_session_id": mst_session_id,
        "queue_session_id": queue_session_id,
        "canonical_session_id": default_session_id or None,
        "completion_evidence_path": completion_evidence_path,
        "next_action_idempotency_key": next_action_idempotency_key or f"next:{idempotency_key}",
        "failure_metadata_path": failure_metadata_path,
        "headless_terminal_status": headless_terminal_status,
        "headless_terminal_reason": headless_terminal_reason,
        "headless_next_action": headless_next_action,
    }
    if legacy_fields:
        entry.update(legacy_fields)
    if status in {"done", "failed", "empty_result", "blocked", "consumed"}:
        entry["completed_at"] = "2026-05-20T03:01:00+00:00"
    return entry


def _current_work_module():
    module = importlib.import_module("scripts.mst_cmds.current_work_handoff")
    assert hasattr(module, "project_current_work_handoff")
    assert hasattr(module, "resolve_continuation_guard")
    return module


def _dod008_module():
    module = importlib.import_module("scripts.mst_cmds.dod008_evidence")
    assert hasattr(module, "project_dod008_evidence")
    return module


def _identity_context(*, env_sid: str | None = SID, structured_sid: str | None = SID) -> dict[str, Any]:
    env: dict[str, Any] = {"MST_STATE_PPID": "4242"}
    if env_sid is not None:
        env["MST_SESSION_ID"] = env_sid

    context: dict[str, Any] = {
        "session_id": HOOK_UUID,
        "owner_session_id": OWNER_SESSION_ID,
        "owner_pid": "4242",
        "transcript_path": f"/tmp/{HOOK_UUID}.jsonl",
    }
    if structured_sid is not None:
        context["mst_session_id"] = structured_sid

    return {
        "env": env,
        "context": context,
        "legacy_diagnostics": {
            "hook_session_id": HOOK_UUID,
            "owner_session_id": OWNER_SESSION_ID,
            "owner_pid": "4242",
        },
    }


def _dispatch_completion(
    status: str = "completed",
    *,
    next_action_key: str | None = None,
    evidence_path: str | None = None,
    parent_session_id: str = SID,
    task_id: str = TASK_ID,
) -> dict[str, Any]:
    return {
        "parent_mst_session_id": parent_session_id,
        "task_id": task_id,
        "status": status,
        "completion_evidence_path": evidence_path or f".gran-maestro/run/{task_id}/completion.json",
        "next_action_idempotency_key": next_action_key or f"{SID}:next_action:{task_id}",
        "completed_at": "2026-05-20T03:13:35Z",
    }


def _base_fixture(**overrides: Any) -> dict[str, Any]:
    completion = _dispatch_completion()
    next_action_key = completion["next_action_idempotency_key"]
    fixture: dict[str, Any] = {
        "schema_version": 1,
        "fixture_id": "req917_parent_child_handoff",
        "mst_session_id": SID,
        "canonical_mst_session_id": SID,
        "generated_at": "2026-05-20T03:13:35Z",
        "source_history_head": "a" * 64,
        "current_history_head": "a" * 64,
        "current_verified_head": "a" * 64,
        "verified_history_head": "a" * 64,
        "history_head_evidence_path": f".gran-maestro/sessions/{SID}/history.head",
        "identity": _identity_context(),
        "active_workflow": {
            "skill": "mst:request",
            "source_id": "REQ-917",
            "auto": True,
            "status": "active",
            "evidence_path": ".gran-maestro/requests/REQ-917/request.json",
        },
        "task_sources": [
            {
                "kind": "request_task",
                "id": TASK_ID,
                "title": "Validate parent-child continuation handoff",
                "status": "active",
                "owner": "codex-dev",
                "phase": "phase2_execution",
                "source": "spec.md",
                "evidence_path": ".gran-maestro/requests/REQ-917/tasks/02/spec.md",
            }
        ],
        "next_action_source": {
            "action_type": "continue_skill",
            "label": "Resume parent request flow",
            "target": TASK_ID,
            "command_hint": "/mst:request REQ-917 -a",
            "reason": "child completion prepared parent continuation handoff",
            "confidence": 1.0,
            "evidence_path": ".gran-maestro/requests/REQ-917/request.json",
            "idempotency_key": next_action_key,
        },
        "dispatch_completion": completion,
        "consumed_idempotency_keys": [],
        "blocker_sources": [],
        "history_ledger": {
            "ledger_path": f".gran-maestro/sessions/{SID}/history.ndjson",
            "rows": [
                {
                    "seq": 1,
                    "prev_hash": "0" * 64,
                    "event_hash": "b" * 64,
                    "event": {
                        "schema_version": 1,
                        "mst_session_id": SID,
                        "root_mst_id": "AGI-040",
                        "event_type": "skill.step",
                        "type": "skill.step",
                        "idempotency_key": f"{SID}:skill.step:{TASK_ID}",
                        "created_at": "2026-05-20T03:13:34Z",
                    },
                }
            ],
            "verified_ledger_head": "b" * 64,
            "sidecar_head": "b" * 64,
            "mirror_head": "b" * 64,
            "policy_mirror_head": "b" * 64,
            "verify_head": "b" * 64,
            "evidence_path": f".gran-maestro/sessions/{SID}/history.verify",
        },
    }
    fixture.update(overrides)
    return fixture


def _project_current_work_handoff(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _current_work_module()
    return module.project_current_work_handoff(copy.deepcopy(fixture))


def _resolve_guard(fixture: dict[str, Any], *, hook_event: str) -> dict[str, Any]:
    module = _current_work_module()
    return module.resolve_continuation_guard(copy.deepcopy(fixture), hook_event=hook_event)


def _project_dod008_evidence(fixture: dict[str, Any]) -> dict[str, Any]:
    module = _dod008_module()
    return module.project_dod008_evidence(copy.deepcopy(fixture))


def _hook_command(hook_event: str) -> str:
    manifest = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = manifest["hooks"][hook_event][0]["hooks"]
    assert len(hooks) == 1
    return hooks[0]["command"]


def test_headless_queue_drain_preserves_session_identity_and_evidence_once(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    session_id = "MST-AGI-040-20260520T030000000Z-dod008h1"
    entry = _queue_entry(
        workspace,
        mst_session_id=session_id,
        idempotency_key="dod008:headless:once",
        next_action_idempotency_key="next:dod008:headless:once",
    )
    _write_queue(workspace, [entry])

    peek = _run_mst(workspace, "queue", "peek", "--json")
    assert peek.returncode == 0, peek.stderr
    assert json.loads(peek.stdout)["status"] == "queued"

    drained = _run_mst(workspace, "queue", "drain-headless", "--json")

    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    assert payload["status"] == "drained"
    assert payload["action"]["status"] == "done"
    assert payload["action"]["canonical_session_id"] == session_id
    assert payload["action"]["next_action_idempotency_key"] == "next:dod008:headless:once"

    persisted = _read_queue(workspace)
    assert len(persisted) == 1
    assert persisted[0]["status"] == "done"
    assert persisted[0]["mst_session_id"] == session_id
    assert persisted[0]["canonical_session_id"] == session_id

    evidence = json.loads(Path(entry["completion_evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == "done"
    assert evidence["mst_session_id"] == session_id
    assert evidence["canonical_session_id"] == session_id
    assert evidence["next_action_idempotency_key"] == "next:dod008:headless:once"

    second = _run_mst(workspace, "queue", "drain-headless", "--json")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == {"status": "empty", "reason": "queue_empty"}


@pytest.mark.parametrize("terminal_status", ["done", "failed"])
def test_headless_queue_idempotency_consumes_duplicate_terminal_entries(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    workspace = _workspace(tmp_path)
    terminal = _queue_entry(
        workspace,
        status=terminal_status,
        idempotency_key=f"dod008:duplicate:{terminal_status}",
        headless_terminal_status=terminal_status,
        headless_terminal_reason=f"existing-{terminal_status}",
        mst_session_id="MST-AGI-040-20260520T030500000Z-dod008dup",
    )
    duplicate = _queue_entry(
        workspace,
        status="queued",
        idempotency_key=f"dod008:duplicate:{terminal_status}",
        headless_terminal_status="done",
        mst_session_id="MST-AGI-040-20260520T030500000Z-dod008dup",
    )
    _write_queue(workspace, [terminal, duplicate])

    drained = _run_mst(workspace, "queue", "drain-headless", "--json")

    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    assert payload["status"] == "duplicate"
    assert payload["action"]["status"] == "consumed"
    assert payload["action"]["duplicate_of_entry_id"] == terminal["entry_id"]
    assert payload["action"]["duplicate_of_status"] == terminal_status

    persisted = _read_queue(workspace)
    assert persisted[0]["status"] == terminal_status
    assert persisted[1]["status"] == "consumed"
    assert persisted[1]["result"] == "duplicate_terminal_idempotency_key"
    assert persisted[1]["duplicate_of_entry_id"] == terminal["entry_id"]
    assert persisted[1]["duplicate_of_status"] == terminal_status
    assert not Path(duplicate["completion_evidence_path"]).exists()


def test_headless_queue_session_identity_uses_explicit_queue_identity_not_legacy(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    queue_session_id = "QUEUE-AGI-040-DOD008-EXPLICIT"
    entry = _queue_entry(
        workspace,
        mst_session_id=None,
        queue_session_id=queue_session_id,
        idempotency_key="dod008:session_identity:explicit",
        legacy_fields={
            "owner_session_id": "legacy-owner-session",
            "owner_ppid": 424242,
            "session_id": "legacy-hook-session",
            "sessionId": "legacy-alias",
        },
    )
    _write_queue(workspace, [entry])

    drained = _run_mst(workspace, "queue", "drain-headless", "--json")

    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    assert payload["action"]["canonical_session_id"] == queue_session_id
    assert payload["action"]["queue_session_id"] == queue_session_id
    assert payload["action"]["mst_session_id"] is None
    assert payload["action"]["legacy_diagnostics"] == {
        "owner_ppid": 424242,
        "owner_session_id": "legacy-owner-session",
        "sessionId": "legacy-alias",
        "session_id": "legacy-hook-session",
    }

    evidence = json.loads(Path(entry["completion_evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["canonical_session_id"] == queue_session_id
    assert evidence["queue_session_id"] == queue_session_id
    assert evidence["mst_session_id"] is None
    assert evidence["legacy_diagnostics"]["owner_session_id"] == "legacy-owner-session"


@pytest.mark.parametrize(
    ("terminal_status", "reason"),
    [
        ("failed", "headless execution failed"),
        ("empty_result", "headless execution returned no result"),
        ("blocked", "manual review required"),
    ],
)
def test_headless_queue_failure_metadata_is_structured(
    tmp_path: Path,
    terminal_status: str,
    reason: str,
) -> None:
    workspace = _workspace(tmp_path)
    entry = _queue_entry(
        workspace,
        idempotency_key=f"dod008:{terminal_status}:failure",
        mst_session_id="MST-AGI-040-20260520T031000000Z-dod008f1",
        headless_terminal_status=terminal_status,
        headless_terminal_reason=reason,
        headless_next_action={
            "action": "resume_parent_session_workflow",
            "reason": "structured_headless_failure",
        },
    )
    _write_queue(workspace, [entry])

    drained = _run_mst(workspace, "queue", "drain-headless", "--json")

    assert drained.returncode == 0, drained.stderr
    payload = json.loads(drained.stdout)
    assert payload["status"] == "drained"
    assert payload["action"]["status"] == terminal_status
    assert payload["action"]["failure_metadata_path"] == entry["failure_metadata_path"]

    persisted = _read_queue(workspace)
    assert persisted[0]["status"] == terminal_status
    assert persisted[0]["error"] == reason

    evidence = json.loads(Path(entry["completion_evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["terminal_status"] == terminal_status
    assert evidence["reason"] == reason
    assert evidence["next_action"]["action"] == "resume_parent_session_workflow"

    failure = json.loads(Path(entry["failure_metadata_path"]).read_text(encoding="utf-8"))
    assert failure["terminal_status"] == terminal_status
    assert failure["reason"] == reason
    assert failure["next_action"]["action"] == "resume_parent_session_workflow"
    assert failure["next_action_idempotency_key"] == entry["next_action_idempotency_key"]


def test_parent_child_handoff_completed_preserves_evidence_path_and_next_action_idempotency_key() -> None:
    payload = _project_current_work_handoff(_base_fixture())

    handoff = payload["continuation_handoff"]
    assert handoff["completion_status"] == "completed"
    assert handoff["continuation_state"] == "parent_continuation_ready"
    assert handoff["parent_mst_session_id"] == SID
    assert handoff["task_id"] == TASK_ID
    assert handoff["completion_evidence_path"] == f".gran-maestro/run/{TASK_ID}/completion.json"
    assert handoff["next_action_idempotency_key"] == f"{SID}:next_action:{TASK_ID}"
    assert handoff["consumable"] is True
    assert handoff["duplicate_prevented"] is False
    assert f".gran-maestro/run/{TASK_ID}/completion.json" in payload["evidence_paths"]
    assert payload["continue"]["queued_action"]["action_type"] == "continue_skill"
    assert payload["continue"]["idempotency_key"] == f"{SID}:next_action:{TASK_ID}"

    shared = _project_dod008_evidence(_base_fixture())
    continuation = shared["continuation_guard"]
    assert continuation["status"] == "pass"
    assert continuation["code"] == "parent_continuation_ready"
    assert continuation["evidence_path"] == f".gran-maestro/run/{TASK_ID}/completion.json"


def test_parent_child_handoff_failure_empty_result_and_blocked_are_recovery_ready() -> None:
    cases = {
        "failed": "dispatch_failed",
        "empty_result": "dispatch_empty_result",
        "blocked": "dispatch_blocked",
    }

    for completion_status, expected_code in cases.items():
        payload = _project_current_work_handoff(
            _base_fixture(
                dispatch_completion=_dispatch_completion(completion_status),
                next_action_source={
                    "action_type": "resolve_blocker",
                    "label": "Inspect child completion evidence",
                    "target": TASK_ID,
                    "command_hint": "/mst:recover AGI-040",
                    "reason": f"{completion_status} child completion requires bounded recovery inspection",
                    "confidence": 0.8,
                    "evidence_path": f".gran-maestro/run/{TASK_ID}/completion.json",
                    "idempotency_key": f"{SID}:next_action:{TASK_ID}",
                },
            )
        )

        handoff = payload["continuation_handoff"]
        assert handoff["completion_status"] == completion_status
        assert handoff["continuation_state"] == "recovery_ready"
        assert handoff["result_class"] == "non_success"
        assert handoff["status_code"] == expected_code
        assert handoff["consumable"] is True
        assert payload["continue"]["queued_action"]["action_type"] == "resolve_blocker"


def test_parent_child_handoff_idempotency_key_is_consumed_only_once() -> None:
    fixture = _base_fixture(consumed_idempotency_keys=[f"{SID}:next_action:{TASK_ID}"])

    payload = _project_current_work_handoff(fixture)
    handoff = payload["continuation_handoff"]
    assert handoff["continuation_state"] == "already_consumed"
    assert handoff["consumption_status"] == "already_consumed"
    assert handoff["consumable"] is False
    assert handoff["duplicate_prevented"] is True
    assert payload["continue"]["queued_action"] is None

    shared = _project_dod008_evidence(fixture)
    continuation = shared["continuation_guard"]
    assert continuation["status"] == "pass"
    assert continuation["code"] == "continuation_already_consumed"


def test_session_identity_prefers_canonical_mst_session_id_and_keeps_legacy_only_values_diagnostic() -> None:
    payload = _project_current_work_handoff(
        _base_fixture(
            identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID),
            dispatch_completion=_dispatch_completion(parent_session_id=SID),
        )
    )

    assert payload["mst_session_id"] == SID
    assert payload["canonical_mst_session_id"] == SID
    assert payload["lookup_key"] == SID
    assert payload["continuation_handoff"]["parent_mst_session_id"] == SID
    assert payload["legacy_diagnostics"]["hook_session_id"] == HOOK_UUID
    assert payload["legacy_diagnostics"]["owner_session_id"] == OWNER_SESSION_ID
    assert payload["projection_freshness"]["status"] == "identity_mismatch"

    shared = _project_dod008_evidence(
        _base_fixture(
            identity=_identity_context(env_sid=SID, structured_sid=OTHER_SID),
            dispatch_completion=_dispatch_completion(parent_session_id=SID),
        )
    )
    assert shared["identity_boundary"]["code"] == "canonical_mst_session_id_mismatch"
    assert shared["continuation_guard"]["parent_mst_session_id"] == SID


def test_stop_continuation_guard_uses_canonical_hook_source_and_blocks_duplicate_execution() -> None:
    assert _hook_command("Stop") == "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"

    first = _resolve_guard(_base_fixture(), hook_event="Stop")
    assert first["hook_event"] == "Stop"
    assert first["hook_source"] == "hooks/mst-stop-hook.sh"
    assert first["decision"] == "parent_continuation_ready"
    assert first["execution_allowed"] is True
    assert first["consumed_idempotency_key"] == f"{SID}:next_action:{TASK_ID}"

    second = _resolve_guard(
        _base_fixture(consumed_idempotency_keys=[f"{SID}:next_action:{TASK_ID}"]),
        hook_event="Stop",
    )
    assert second["decision"] == "already_consumed"
    assert second["execution_allowed"] is False
    assert second["duplicate_prevented"] is True


def test_session_start_continuation_guard_uses_canonical_hook_source_for_recovery_ready() -> None:
    assert _hook_command("SessionStart") == "${CLAUDE_PLUGIN_ROOT}/hooks/mst-session-init.sh"

    payload = _resolve_guard(
        _base_fixture(
            dispatch_completion=_dispatch_completion("blocked"),
            next_action_source={
                "action_type": "resolve_blocker",
                "label": "Inspect blocked child completion",
                "target": TASK_ID,
                "command_hint": "/mst:recover AGI-040",
                "reason": "blocked child completion requires recovery",
                "confidence": 0.9,
                "evidence_path": f".gran-maestro/run/{TASK_ID}/completion.json",
                "idempotency_key": f"{SID}:next_action:{TASK_ID}",
            },
        ),
        hook_event="SessionStart",
    )

    assert payload["hook_event"] == "SessionStart"
    assert payload["hook_source"] == "hooks/mst-session-init.sh"
    assert payload["decision"] == "recovery_ready"
    assert payload["execution_allowed"] is True
    assert payload["next_action"]["action_type"] == "resolve_blocker"
