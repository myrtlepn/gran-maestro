from __future__ import annotations

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.mst_cmds import native_delegation as native_delegation_mod
from scripts.mst_cmds.current_work_handoff import (
    project_lifecycle_artifact_consumer_summary,
)
from scripts.mst_cmds.native_delegation import (
    LifecycleConflict,
    acknowledge_native_spawn,
    attach_native_attempt,
    cancel_native_attempt,
    claim_native_spawn,
    complete_native_attempt,
    recover_native_attempt,
    request_external_fallback,
    start_native_attempt,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
MST_SESSION_ID = "MST-REQ-939-20260712T000000000Z-session1"
PARENT_SESSION_ID = "MST-REQ-939-20260712T000001000Z-parent01"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _base_dir(tmp_path: Path) -> Path:
    base = tmp_path / "workspace" / ".gran-maestro"
    base.mkdir(parents=True)
    return base


def _write_pending_reconciliation_state(
    base: Path,
    *,
    task_id: str,
    phase: str,
    status: str,
    execution_transport: str = "native",
) -> dict:
    attempt_id = f"{task_id}-attempt"
    action = {
        "kind": "provider_reconcile",
        "action_id": f"provider-reconcile:{task_id}",
        "lookup_key": f"attempt:{attempt_id}",
        "provider": "codex",
        "provider_task_id": None,
        "attempt_id": attempt_id,
        "status": "pending",
        "completion_accepted": False,
    }
    state = {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "phase": phase,
        "status": status,
        "execution_transport": execution_transport,
        "provider_reconciliation_required": True,
        "reconciliation_action": action,
    }
    path = base / "run" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    return state


def _claim_token(base: Path, task_id: str, attempt_id: str, *, key: str | None = None) -> str:
    claim = claim_native_spawn(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=attempt_id,
        claimant_id=f"test-parent:{task_id}",
        idempotency_key=key or f"{task_id}:claim",
    )
    assert claim["spawn_allowed"] is True
    assert claim["claim_status"] == "claimed"
    assert claim["claim_token"]
    return str(claim["claim_token"])


def test_native_lifecycle_preserves_evidence_and_nullable_exit_code(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("implement the bounded change", encoding="utf-8")
    context = tmp_path / "context.json"
    context.write_text('{"request":"REQ-939"}', encoding="utf-8")
    output = tmp_path / "result.md"

    started = start_native_attempt(
        base_dir=base,
        task_id="REQ-939-T02",
        attempt_id="native-a1",
        idempotency_key="start-a1",
        host="codex",
        provider="codex",
        capability_status="available",
        route_reason="same_host_native_capable",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        context_files=[context],
        trace_path="REQ-939/T02/native-a1",
        output_path=output,
    )
    spawned = acknowledge_native_spawn(
        base_dir=base,
        task_id="REQ-939-T02",
        expected_attempt_id="native-a1",
        spawn_status="created_with_task_id",
        provider_task_id="codex-task-17",
        claim_token=_claim_token(base, "REQ-939-T02", "native-a1"),
        idempotency_key="ack-a1",
    )
    attached = attach_native_attempt(
        base_dir=base,
        task_id="REQ-939-T02",
        expected_attempt_id="native-a1",
        attach_status="attached",
        idempotency_key="attach-a1",
    )
    output.write_text("done", encoding="utf-8")
    completed = complete_native_attempt(
        base_dir=base,
        task_id="REQ-939-T02",
        expected_attempt_id="native-a1",
        completion_signal="completed",
        output_path=output,
        idempotency_key="finish-a1",
    )

    assert started["execution_transport"] == "native"
    assert started["pid"] is None
    assert started["exit_code"] is None
    assert started["spawn_allowed"] is False
    assert started["fallback_allowed"] is False
    assert started["prompt_hash"].startswith("sha256:")
    assert started["context_files_read"][0]["hash"].startswith("sha256:")
    assert spawned["provider_task_id"] == "codex-task-17"
    assert spawned["start_acknowledged"] is True
    assert attached["phase"] == "attached"
    assert completed["phase"] == "done"
    assert completed["status"] == "completed"
    assert completed["completion_signal"] == "completed"
    assert completed["exit_code"] is None
    assert completed["output_hash"].startswith("sha256:")
    assert json.loads((base / "run" / "REQ-939-T02.json").read_text(encoding="utf-8")) == completed
    history_path = base / "history" / "native-delegation.ndjson"
    assert history_path.is_file()
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()]
    assert history[-1]["route_reason"] == "same_host_native_capable"
    assert history[-1]["worktree_dir"] == str(base.parent.resolve())
    assert history[-1]["prompt_hash"].startswith("sha256:")
    assert history[-1]["context_files_read"][0]["hash"].startswith("sha256:")
    assert history[-1]["output_hash"].startswith("sha256:")


def test_native_start_inherits_canonical_session_identity_and_artifact_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    output = tmp_path / "session-result.md"
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    monkeypatch.setenv(
        "MST_CONTEXT_JSON",
        json.dumps({"mst_session_id": MST_SESSION_ID, "root_mst_id": "REQ-939"}),
    )

    state = start_native_attempt(
        base_dir=base,
        task_id="session-native",
        idempotency_key="session-start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
        parent_session_id=PARENT_SESSION_ID,
        output_path=output,
    )

    assert state["mst_session_id"] == MST_SESSION_ID
    assert state["root_mst_id"] == "REQ-939"
    assert state["parent_session_id"] == PARENT_SESSION_ID
    assert Path(state["running_log_path"]).is_file()
    assert Path(state["trace_path"]).is_file()
    assert state["output_path"] == str(output.resolve())
    assert state["output_baseline_exists"] is False
    assert state["output_baseline_hash"] is None
    assert state["output_baseline_version"] is None

    history = [
        json.loads(line)
        for line in (base / "history" / "native-delegation.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert history[-1]["mst_session_id"] == MST_SESSION_ID
    assert history[-1]["root_mst_id"] == "REQ-939"
    assert history[-1]["parent_session_id"] == PARENT_SESSION_ID
    assert history[-1]["running_log_path"] == state["running_log_path"]


def test_native_start_rejects_inherited_session_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    monkeypatch.setenv(
        "MST_CONTEXT_JSON",
        json.dumps(
            {
                "mst_session_id": "MST-REQ-939-20260712T000002000Z-other001",
                "root_mst_id": "REQ-939",
            }
        ),
    )

    with pytest.raises(LifecycleConflict, match="MST_SESSION_ID"):
        start_native_attempt(
            base_dir=base,
            task_id="session-mismatch",
            idempotency_key="session-start",
            host="codex",
            provider="codex",
            worktree_dir=base.parent,
            scope="analysis",
            read_only=True,
        )


def test_native_mutation_rejects_changed_inherited_session_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    state = start_native_attempt(
        base_dir=base,
        task_id="session-mutation-mismatch",
        idempotency_key="start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    monkeypatch.setenv(
        "MST_SESSION_ID", "MST-REQ-939-20260712T000002000Z-other001"
    )
    with pytest.raises(LifecycleConflict, match="MST_SESSION_ID"):
        acknowledge_native_spawn(
            base_dir=base,
            task_id="session-mutation-mismatch",
            expected_attempt_id=state["attempt_id"],
            spawn_status="accepted",
            idempotency_key="ack",
        )


def _started_native_with_expected_output(tmp_path: Path, task_id: str, *, preexisting: str | None = None):
    base = _base_dir(tmp_path)
    output = tmp_path / f"{task_id}.result"
    if preexisting is not None:
        output.write_text(preexisting, encoding="utf-8")
    state = start_native_attempt(
        base_dir=base,
        task_id=task_id,
        idempotency_key=f"{task_id}:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
        output_path=output,
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=state["attempt_id"],
        spawn_status="accepted",
        claim_token=_claim_token(base, task_id, str(state["attempt_id"])),
        idempotency_key=f"{task_id}:ack",
    )
    return base, output, state


def test_native_success_rejects_missing_expected_output(tmp_path: Path) -> None:
    base, output, state = _started_native_with_expected_output(tmp_path, "missing-output")
    completed = complete_native_attempt(
        base_dir=base,
        task_id="missing-output",
        expected_attempt_id=state["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="missing-output:complete",
    )
    assert completed["phase"] == "failed"
    assert completed["status"] == "missing_result"
    assert completed["failure_domain"] == "output_evidence"
    assert completed["fallback_allowed"] is False


def test_native_success_rejects_empty_new_output(tmp_path: Path) -> None:
    base, output, state = _started_native_with_expected_output(tmp_path, "empty-output")
    output.write_bytes(b"")
    completed = complete_native_attempt(
        base_dir=base,
        task_id="empty-output",
        expected_attempt_id=state["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="empty-output:complete",
    )
    assert completed["phase"] == "failed"
    assert completed["status"] == "empty_result"
    assert completed["failure_domain"] == "output_evidence"


def test_native_success_rejects_unchanged_output(tmp_path: Path) -> None:
    base, output, state = _started_native_with_expected_output(
        tmp_path, "unchanged-output", preexisting="stale"
    )
    completed = complete_native_attempt(
        base_dir=base,
        task_id="unchanged-output",
        expected_attempt_id=state["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="unchanged-output:complete",
    )
    assert completed["phase"] == "failed"
    assert completed["status"] == "unchanged_result"
    assert completed["failure_domain"] == "output_evidence"


def test_native_success_rejects_changed_preexisting_output(tmp_path: Path) -> None:
    base, output, state = _started_native_with_expected_output(
        tmp_path, "preexisting-output", preexisting="stale"
    )
    output.write_text("changed but not newly created", encoding="utf-8")
    completed = complete_native_attempt(
        base_dir=base,
        task_id="preexisting-output",
        expected_attempt_id=state["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="preexisting-output:complete",
    )
    assert completed["phase"] == "failed"
    assert completed["status"] == "preexisting_result"
    assert completed["failure_domain"] == "output_evidence"


def test_native_start_captures_output_created_during_worktree_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    output = tmp_path / "guard-race.result"
    original_guard = native_delegation_mod.validate_native_worktree

    def guard_with_racing_output(**kwargs):
        result = original_guard(**kwargs)
        output.write_text("appeared during guard", encoding="utf-8")
        return result

    monkeypatch.setattr(native_delegation_mod, "validate_native_worktree", guard_with_racing_output)
    started = start_native_attempt(
        base_dir=base,
        task_id="guard-race",
        idempotency_key="guard-race:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
        output_path=output,
    )
    assert started["output_baseline_exists"] is True
    assert started["output_baseline_hash"].startswith("sha256:")

    acknowledge_native_spawn(
        base_dir=base,
        task_id="guard-race",
        expected_attempt_id=started["attempt_id"],
        spawn_status="accepted",
        claim_token=_claim_token(base, "guard-race", str(started["attempt_id"])),
        idempotency_key="guard-race:ack",
    )
    completed = complete_native_attempt(
        base_dir=base,
        task_id="guard-race",
        expected_attempt_id=started["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="guard-race:complete",
    )
    assert completed["phase"] == "failed"
    assert completed["status"] == "unchanged_result"


def test_native_start_exact_replay_does_not_resample_output_baseline(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    output = tmp_path / "replay-baseline.result"
    kwargs = dict(
        base_dir=base,
        task_id="replay-baseline",
        idempotency_key="replay-baseline:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
        output_path=output,
    )
    first = start_native_attempt(**kwargs)
    output.write_text("created after persisted start", encoding="utf-8")
    replay = start_native_attempt(**kwargs)
    assert replay["attempt_id"] == first["attempt_id"]
    assert replay["output_baseline_exists"] is False
    assert replay["idempotency_keys"]["replay-baseline:start"]["fingerprint"] == first[
        "idempotency_keys"
    ]["replay-baseline:start"]["fingerprint"]


def test_native_start_guard_failure_creates_no_lifecycle_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    artifact_root = tmp_path / "must-not-exist"

    def reject_guard(**_kwargs):
        raise LifecycleConflict("guard rejected")

    monkeypatch.setattr(native_delegation_mod, "validate_native_worktree", reject_guard)
    with pytest.raises(LifecycleConflict, match="guard rejected"):
        start_native_attempt(
            base_dir=base,
            task_id="guard-no-artifacts",
            idempotency_key="guard-no-artifacts:start",
            host="codex",
            provider="codex",
            worktree_dir=base.parent,
            scope="analysis",
            read_only=True,
            running_log_path=artifact_root / "running.log",
            trace_path=artifact_root / "trace.ndjson",
            output_path=artifact_root / "result.md",
        )
    assert not artifact_root.exists()


def test_delegation_lifecycle_cli_emits_json_and_preserves_native_truth(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    workspace = base.parent
    prompt = tmp_path / "cli-prompt.md"
    prompt.write_text("inspect only", encoding="utf-8")

    capability = _run_mst(
        workspace,
        "delegation",
        "capability",
        "--host",
        "codex",
        "--provider",
        "codex",
        "--capability-status",
        "available",
        "--external-unavailable",
    )
    assert capability.returncode == 0, capability.stderr
    capability_payload = json.loads(capability.stdout)
    assert capability_payload["capability_status"] == "available"
    assert capability_payload["route"] == "native_candidate"

    started = _run_mst(
        workspace,
        "delegation",
        "start",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--idempotency-key",
        "cli-start",
        "--host",
        "codex",
        "--provider",
        "codex",
        "--worktree-dir",
        str(workspace),
        "--scope",
        "analysis",
        "--read-only",
        "--prompt-file",
        str(prompt),
    )
    assert started.returncode == 0, started.stderr
    started_payload = json.loads(started.stdout)
    assert started_payload["phase"] == "spawn_requested"
    assert started_payload["spawn_allowed"] is False

    claimed = _run_mst(
        workspace,
        "delegation",
        "claim-spawn",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--claimant-id",
        "cli-parent-1",
        "--idempotency-key",
        "cli-claim",
    )
    assert claimed.returncode == 0, claimed.stderr
    claim_payload = json.loads(claimed.stdout)
    assert claim_payload["spawn_allowed"] is True
    assert claim_payload["claim_status"] == "claimed"
    assert claim_payload["claim_token"] is None
    claim_token_file = Path(claim_payload["claim_token_file"])
    assert claim_token_file.is_file()
    assert claim_token_file.stat().st_mode & 0o077 == 0

    claim_replay = _run_mst(
        workspace,
        "delegation",
        "claim-spawn",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--claimant-id",
        "cli-parent-1",
        "--idempotency-key",
        "cli-claim",
    )
    assert claim_replay.returncode == 0, claim_replay.stderr
    replay_payload = json.loads(claim_replay.stdout)
    assert replay_payload["spawn_allowed"] is False
    assert replay_payload["claim_status"] == "claim_replay"
    assert replay_payload["claim_token"] is None
    assert replay_payload["claim_token_file"] is None

    acknowledged = _run_mst(
        workspace,
        "delegation",
        "acknowledge",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--spawn-status",
        "created_with_task_id",
        "--provider-task-id",
        "provider-cli-1",
        "--claim-token-file",
        str(claim_token_file),
        "--idempotency-key",
        "cli-ack",
    )
    assert acknowledged.returncode == 0, acknowledged.stderr
    assert json.loads(acknowledged.stdout)["provider_task_id"] == "provider-cli-1"
    assert not claim_token_file.exists()

    attached = _run_mst(
        workspace,
        "delegation",
        "attach",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--attach-status",
        "attached",
        "--idempotency-key",
        "cli-attach",
    )
    assert attached.returncode == 0, attached.stderr
    Path(started_payload["output_path"]).write_text("native CLI result", encoding="utf-8")

    completed = _run_mst(
        workspace,
        "delegation",
        "complete",
        "--task-id",
        "cli-native",
        "--attempt-id",
        "cli-native-a1",
        "--completion-signal",
        "completed",
        "--output-path",
        started_payload["output_path"],
        "--idempotency-key",
        "cli-complete",
    )
    assert completed.returncode == 0, completed.stderr
    final = json.loads(completed.stdout)
    assert final["status"] == "completed"
    assert final["completion_signal"] == "completed"
    assert final["exit_code"] is None


def test_delegation_cli_conflict_is_structured_json(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    proc = _run_mst(
        base.parent,
        "delegation",
        "attach",
        "--task-id",
        "missing-attempt",
        "--attempt-id",
        "missing-a1",
        "--attach-status",
        "attached",
        "--idempotency-key",
        "missing-attach",
    )

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert payload["error_type"] == "LifecycleConflict"


def test_delegation_external_run_cli_requires_expected_attempt_id(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    prompt = tmp_path / "external-cli-prompt.md"
    prompt.write_text("external", encoding="utf-8")
    proc = _run_mst(
        base.parent,
        "delegation",
        "external-run",
        "--task-id",
        "external-cli",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt),
        "--worktree-dir",
        str(base.parent),
        "--output-path",
        str(tmp_path / "external-cli.out"),
        "--idempotency-key",
        "external-cli:run",
    )
    assert proc.returncode == 2
    assert "--expected-attempt-id" in proc.stderr


def test_delegation_external_run_cli_rejects_unpersisted_attempt_before_spawn(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    prompt = tmp_path / "external-cli-prompt.md"
    prompt.write_text("external", encoding="utf-8")
    marker = tmp_path / "must-not-run"
    binary = tmp_path / "codex-stub"
    binary.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    binary.chmod(0o755)
    proc = _run_mst(
        base.parent,
        "delegation",
        "external-run",
        "--task-id",
        "external-cli-unpersisted",
        "--expected-attempt-id",
        "missing-attempt",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt),
        "--worktree-dir",
        str(base.parent),
        "--output-path",
        str(tmp_path / "external-cli.out"),
        "--idempotency-key",
        "external-cli:run",
        "--binary",
        str(binary),
        "--scope",
        "analysis",
        "--read-only",
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert "external lifecycle state not found" in payload["message"]
    assert not marker.exists()


@pytest.mark.parametrize("spawn_status", ["rejected", "outcome_unknown"])
def test_indeterminate_acknowledgement_reconciles_without_fallback(
    tmp_path: Path, spawn_status: str
) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-unknown",
        idempotency_key="start",
        host="claude",
        provider="claude",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )

    state = acknowledge_native_spawn(
        base_dir=base,
        task_id="task-unknown",
        expected_attempt_id=started["attempt_id"],
        spawn_status=spawn_status,
        claim_token=_claim_token(base, "task-unknown", str(started["attempt_id"])),
        idempotency_key="ack",
    )

    assert state["phase"] == "reconciling"
    assert state["fallback_allowed"] is False
    assert state["spawn_allowed"] is False
    with pytest.raises(LifecycleConflict, match="fallback"):
        request_external_fallback(
            base_dir=base,
            task_id="task-unknown",
            expected_attempt_id=started["attempt_id"],
            idempotency_key="fallback",
        )


def test_start_acknowledgement_without_task_id_still_blocks_duplicate_external(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-accepted",
        idempotency_key="start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    state = acknowledge_native_spawn(
        base_dir=base,
        task_id="task-accepted",
        expected_attempt_id=started["attempt_id"],
        spawn_status="accepted",
        claim_token=_claim_token(base, "task-accepted", str(started["attempt_id"])),
        idempotency_key="ack",
    )

    assert state["start_acknowledged"] is True
    assert state["fallback_allowed"] is False
    assert state["phase"] == "spawned"


def test_attach_failure_after_provider_task_creation_is_reconcile_first(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-attach-race",
        idempotency_key="start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="task-attach-race",
        expected_attempt_id=started["attempt_id"],
        spawn_status="created_with_task_id",
        provider_task_id="provider-42",
        claim_token=_claim_token(base, "task-attach-race", str(started["attempt_id"])),
        idempotency_key="ack",
    )

    state = attach_native_attempt(
        base_dir=base,
        task_id="task-attach-race",
        expected_attempt_id=started["attempt_id"],
        attach_status="failed",
        idempotency_key="attach",
    )

    assert state["phase"] == "reconciling"
    assert state["provider_task_id"] == "provider-42"
    assert state["fallback_allowed"] is False


def test_definitive_not_created_is_the_only_fallback_boundary(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-fallback",
        idempotency_key="start",
        host="claude",
        provider="claude",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    rejected = acknowledge_native_spawn(
        base_dir=base,
        task_id="task-fallback",
        expected_attempt_id=started["attempt_id"],
        spawn_status="definitive_not_created",
        claim_token=_claim_token(base, "task-fallback", str(started["attempt_id"])),
        idempotency_key="ack",
    )
    fallback = request_external_fallback(
        base_dir=base,
        task_id="task-fallback",
        expected_attempt_id=started["attempt_id"],
        idempotency_key="fallback",
    )

    assert rejected["fallback_allowed"] is True
    assert fallback["execution_transport"] == "external"
    assert fallback["fallback_from"] == rejected["attempt_id"]
    assert fallback["attempt_id"] != rejected["attempt_id"]
    assert len(fallback["attempts"]) == 2
    assert sum(bool(attempt["current_attempt"]) for attempt in fallback["attempts"]) == 1


def test_native_task_failure_is_terminal_and_never_transport_fallback(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-failed",
        idempotency_key="start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="task-failed",
        expected_attempt_id=started["attempt_id"],
        spawn_status="accepted",
        claim_token=_claim_token(base, "task-failed", str(started["attempt_id"])),
        idempotency_key="ack",
    )
    failed = complete_native_attempt(
        base_dir=base,
        task_id="task-failed",
        expected_attempt_id=started["attempt_id"],
        completion_signal="failed",
        failure_domain="task",
        idempotency_key="complete",
    )

    assert failed["phase"] == "failed"
    assert failed["status"] == "failed"
    assert failed["failure_domain"] == "task"
    assert failed["fallback_allowed"] is False
    with pytest.raises(LifecycleConflict, match="terminal lifecycle attempt cannot attach"):
        attach_native_attempt(
            base_dir=base,
            task_id="task-failed",
            expected_attempt_id=started["attempt_id"],
            attach_status="attached",
            idempotency_key="late-attach",
        )


def test_concurrent_start_is_idempotent_and_has_one_current_attempt(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)

    def start() -> dict:
        return start_native_attempt(
            base_dir=base,
            task_id="task-race",
            attempt_id="native-race",
            idempotency_key="same-key",
            host="codex",
            provider="codex",
            worktree_dir=base.parent,
            scope="analysis",
            read_only=True,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: start(), range(16)))

    assert {state["attempt_id"] for state in states} == {"native-race"}
    persisted = json.loads((base / "run" / "task-race.json").read_text(encoding="utf-8"))
    assert len(persisted["attempts"]) == 1
    assert persisted["attempts"][0]["current_attempt"] is True


def test_concurrent_manual_lifecycle_claim_allows_exactly_one_fake_host_spawn(
    tmp_path: Path,
) -> None:
    base = _base_dir(tmp_path)
    callers = 16
    barrier = threading.Barrier(callers)
    spawn_lock = threading.Lock()
    fake_host_spawn_count = 0

    def fake_host_spawn() -> str:
        nonlocal fake_host_spawn_count
        with spawn_lock:
            fake_host_spawn_count += 1
            return f"provider-task-{fake_host_spawn_count}"

    def parent_caller(index: int) -> dict:
        started = start_native_attempt(
            base_dir=base,
            task_id="manual-claim-race",
            attempt_id="manual-native-a1",
            idempotency_key="manual:start",
            host="codex",
            provider="codex",
            worktree_dir=base.parent,
            scope="analysis",
            read_only=True,
        )
        assert started["spawn_allowed"] is False
        barrier.wait()
        claim = claim_native_spawn(
            base_dir=base,
            task_id="manual-claim-race",
            expected_attempt_id="manual-native-a1",
            claimant_id=f"parent-{index}",
            idempotency_key=f"manual:claim:{index}",
        )
        if claim["spawn_allowed"]:
            provider_task_id = fake_host_spawn()
            acknowledge_native_spawn(
                base_dir=base,
                task_id="manual-claim-race",
                expected_attempt_id="manual-native-a1",
                spawn_status="created_with_task_id",
                provider_task_id=provider_task_id,
                claim_token=claim["claim_token"],
                idempotency_key="manual:ack",
            )
        return claim

    with ThreadPoolExecutor(max_workers=callers) as pool:
        claims = list(pool.map(parent_caller, range(callers)))

    assert sum(claim["spawn_allowed"] is True for claim in claims) == 1
    assert fake_host_spawn_count == 1
    assert sum(bool(claim.get("claim_token")) for claim in claims) == 1
    assert all(
        claim["next_action"]
        in {
            "spawn_then_acknowledge",
            "wait_for_claim_lease_then_recover",
            "reconcile_or_wait",
            "attach_or_wait",
        }
        for claim in claims
    )
    persisted = json.loads((base / "run" / "manual-claim-race.json").read_text(encoding="utf-8"))
    assert persisted["spawn_allowed"] is False
    assert persisted["spawn_claim_status"] == "consumed"
    assert persisted["spawn_claim_token_hash"] is None
    assert persisted["provider_task_id"] == "provider-task-1"


def test_spawn_claim_exact_replay_never_reissues_authority(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    kwargs = dict(
        base_dir=base,
        task_id="claim-replay",
        attempt_id="claim-replay-a1",
        idempotency_key="claim-replay:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    started = start_native_attempt(**kwargs)
    winner = claim_native_spawn(
        base_dir=base,
        task_id="claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="parent-a",
        idempotency_key="claim-replay:claim-a",
    )
    replay = claim_native_spawn(
        base_dir=base,
        task_id="claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="parent-a",
        idempotency_key="claim-replay:claim-a",
    )
    loser = claim_native_spawn(
        base_dir=base,
        task_id="claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="parent-b",
        idempotency_key="claim-replay:claim-b",
    )
    start_replay = start_native_attempt(**kwargs)

    with pytest.raises(LifecycleConflict, match="claim_spawn attempt CAS mismatch"):
        claim_native_spawn(
            base_dir=base,
            task_id="claim-replay",
            expected_attempt_id="stale-native-attempt",
            claimant_id="stale-parent",
            idempotency_key="claim-replay:stale",
        )

    assert winner["spawn_allowed"] is True
    assert winner["claim_token"]
    assert replay["spawn_allowed"] is False
    assert replay["claim_status"] == "claim_replay"
    assert replay["claim_token"] is None
    assert loser["spawn_allowed"] is False
    assert loser["claim_status"] == "already_claimed"
    assert loser["claim_token"] is None
    assert start_replay["spawn_allowed"] is False
    assert "claim_token" not in start_replay
    persisted_text = (base / "run" / "claim-replay.json").read_text(encoding="utf-8")
    assert winner["claim_token"] not in persisted_text


def test_spawn_claim_crash_recovery_reconciles_and_never_falls_back(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="claim-crash",
        idempotency_key="claim-crash:start",
        host="claude",
        provider="claude",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id="claim-crash",
        expected_attempt_id=started["attempt_id"],
        claimant_id="crashed-parent",
        idempotency_key="claim-crash:claim",
    )
    assert claim["spawn_allowed"] is True

    with pytest.raises(LifecycleConflict, match="claim is still active"):
        recover_native_attempt(
            base_dir=base,
            task_id="claim-crash",
            expected_attempt_id=started["attempt_id"],
            provider_state="unknown_after_claim",
            idempotency_key="claim-crash:premature-recover",
        )

    state_path = base / "run" / "claim-crash.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    persisted["spawn_claim_expires_at"] = "2000-01-01T00:00:00+00:00"
    state_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")

    recovered = recover_native_attempt(
        base_dir=base,
        task_id="claim-crash",
        expected_attempt_id=started["attempt_id"],
        provider_state="unknown_after_claim",
        idempotency_key="claim-crash:recover",
    )
    retry = claim_native_spawn(
        base_dir=base,
        task_id="claim-crash",
        expected_attempt_id=started["attempt_id"],
        claimant_id="replacement-parent",
        idempotency_key="claim-crash:replacement",
    )

    assert recovered["phase"] == "reconciling"
    assert recovered["fallback_allowed"] is False
    assert recovered["spawn_claim_status"] == "indeterminate"
    assert recovered["spawn_claim_token_hash"] is None
    assert retry["spawn_allowed"] is False
    assert retry["claim_status"] == "reconciling"
    with pytest.raises(LifecycleConflict, match="fallback"):
        request_external_fallback(
            base_dir=base,
            task_id="claim-crash",
            expected_attempt_id=started["attempt_id"],
            idempotency_key="claim-crash:fallback",
        )


def test_spawn_claim_loser_cannot_recover_or_cancel_before_winner_acknowledges(
    tmp_path: Path,
) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="claim-active-winner",
        idempotency_key="claim-active:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    winner = claim_native_spawn(
        base_dir=base,
        task_id="claim-active-winner",
        expected_attempt_id=started["attempt_id"],
        claimant_id="winner-parent",
        idempotency_key="claim-active:winner",
    )
    loser = claim_native_spawn(
        base_dir=base,
        task_id="claim-active-winner",
        expected_attempt_id=started["attempt_id"],
        claimant_id="loser-parent",
        idempotency_key="claim-active:loser",
    )
    assert loser["spawn_allowed"] is False
    assert loser["next_action"] == "wait_for_claim_lease_then_recover"

    with pytest.raises(LifecycleConflict, match="claim is still active"):
        recover_native_attempt(
            base_dir=base,
            task_id="claim-active-winner",
            expected_attempt_id=started["attempt_id"],
            provider_state="unknown",
            idempotency_key="claim-active:loser-recover",
        )
    with pytest.raises(LifecycleConflict, match="claim is still active"):
        cancel_native_attempt(
            base_dir=base,
            task_id="claim-active-winner",
            expected_attempt_id=started["attempt_id"],
            idempotency_key="claim-active:loser-cancel",
        )

    acknowledged = acknowledge_native_spawn(
        base_dir=base,
        task_id="claim-active-winner",
        expected_attempt_id=started["attempt_id"],
        spawn_status="created_with_task_id",
        provider_task_id="provider-winner-1",
        claim_token=winner["claim_token"],
        idempotency_key="claim-active:ack",
    )
    assert acknowledged["phase"] == "spawned"
    assert acknowledged["provider_task_id"] == "provider-winner-1"


def test_spawn_claim_rejects_token_mismatch_and_session_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base_dir(tmp_path)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    started = start_native_attempt(
        base_dir=base,
        task_id="claim-session",
        idempotency_key="claim-session:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id="claim-session",
        expected_attempt_id=started["attempt_id"],
        claimant_id="session-parent",
        idempotency_key="claim-session:claim",
    )
    with pytest.raises(LifecycleConflict, match="claim token mismatch"):
        acknowledge_native_spawn(
            base_dir=base,
            task_id="claim-session",
            expected_attempt_id=started["attempt_id"],
            spawn_status="accepted",
            claim_token="wrong-token",
            idempotency_key="claim-session:bad-ack",
        )

    monkeypatch.setenv("MST_SESSION_ID", "MST-REQ-939-20260712T000002000Z-other001")
    with pytest.raises(LifecycleConflict, match="MST_SESSION_ID"):
        claim_native_spawn(
            base_dir=base,
            task_id="claim-session",
            expected_attempt_id=started["attempt_id"],
            claimant_id="other-session-parent",
            idempotency_key="claim-session:other",
        )
    assert claim["claim_token"]


def test_spawn_claim_on_terminal_attempt_never_authorizes_spawn(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="claim-terminal",
        idempotency_key="claim-terminal:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    token = _claim_token(base, "claim-terminal", str(started["attempt_id"]))
    acknowledge_native_spawn(
        base_dir=base,
        task_id="claim-terminal",
        expected_attempt_id=started["attempt_id"],
        spawn_status="accepted",
        claim_token=token,
        idempotency_key="claim-terminal:ack",
    )
    complete_native_attempt(
        base_dir=base,
        task_id="claim-terminal",
        expected_attempt_id=started["attempt_id"],
        completion_signal="failed",
        failure_domain="task",
        idempotency_key="claim-terminal:complete",
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id="claim-terminal",
        expected_attempt_id=started["attempt_id"],
        claimant_id="late-parent",
        idempotency_key="claim-terminal:late",
    )
    assert claim["spawn_allowed"] is False
    assert claim["claim_token"] is None
    assert claim["claim_status"] == "terminal"
    assert claim["next_action"] == "stop"


def test_pidless_cancel_and_recover_reconcile_without_os_signal(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="task-cancel",
        idempotency_key="start",
        host="claude",
        provider="claude",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="task-cancel",
        expected_attempt_id=started["attempt_id"],
        spawn_status="accepted",
        claim_token=_claim_token(base, "task-cancel", str(started["attempt_id"])),
        idempotency_key="ack",
    )

    cancelled = cancel_native_attempt(
        base_dir=base,
        task_id="task-cancel",
        expected_attempt_id=started["attempt_id"],
        idempotency_key="cancel",
    )
    recovered = recover_native_attempt(
        base_dir=base,
        task_id="task-cancel",
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        parent_heartbeat="2026-07-11T00:00:00+00:00",
        idempotency_key="recover",
    )

    assert cancelled["pid"] is None
    assert cancelled["os_signal_attempted"] is False
    assert cancelled["cancel_status"] == "unconfirmed"
    assert recovered["phase"] == "reconciling"
    assert recovered["spawn_allowed"] is False
    assert recovered["fallback_allowed"] is False
    assert recovered["os_signal_attempted"] is False
    assert recovered["recovery_evidence"] == {
        "provider_state": "unknown",
        "provider_task_id": None,
        "parent_heartbeat": "2026-07-11T00:00:00+00:00",
        "caller_provider_state_claim": "running",
        "caller_claim_trusted": False,
    }
    action = recovered["reconciliation_action"]
    assert action["kind"] == "provider_reconcile"
    assert action["status"] == "pending"
    assert action["provider_task_id"] is None
    assert action["lookup_key"] == f"attempt:{started['attempt_id']}"
    assert action["completion_accepted"] is False
    assert native_delegation_mod.get_reconciliation_action(
        base_dir=base,
        task_id="task-cancel",
        expected_attempt_id=started["attempt_id"],
    ) == action
    action_cli = _run_mst(
        base.parent,
        "delegation",
        "reconcile-action",
        "--task-id",
        "task-cancel",
        "--attempt-id",
        str(started["attempt_id"]),
    )
    assert action_cli.returncode == 0, action_cli.stderr
    assert json.loads(action_cli.stdout) == action


def test_terminal_status_contract_is_the_safe_consumer_union() -> None:
    assert native_delegation_mod.TERMINAL_STATUSES == frozenset(
        {
            "completed",
            "fallback_completed",
            "failed",
            "empty_result",
            "missing_result",
            "unchanged_result",
            "preexisting_result",
            "missing_output_baseline",
            "cancelled",
            "canceled",
            "blocked",
        }
    )
    for status in ("reconciling", "cancel_requested", "running", "unknown"):
        assert native_delegation_mod.lifecycle_is_terminal(
            {"phase": "running", "status": status}
        ) is False
    assert native_delegation_mod.lifecycle_is_terminal(
        {"phase": " running ", "status": " COMPLETED "}
    ) is True


@pytest.mark.parametrize("status", sorted(native_delegation_mod.TERMINAL_STATUSES))
def test_status_terminal_native_spawn_claim_never_issues_authority(
    tmp_path: Path,
    status: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"terminal-claim-{status}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase="spawn_requested",
        status=status,
    )
    state_path = base / "run" / f"{task_id}.json"
    before = state_path.read_bytes()

    claim = claim_native_spawn(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=state["attempt_id"],
        claimant_id="terminal-claim-test",
        idempotency_key=f"{task_id}:claim",
    )

    assert claim["spawn_allowed"] is False
    assert claim["claim_status"] == "terminal"
    assert claim["claim_token"] is None
    assert claim["next_action"] == "stop"
    assert state_path.read_bytes() == before
    secret_dir = base / "run" / ".claim-secrets"
    assert not secret_dir.exists() or list(secret_dir.iterdir()) == []
    assert not (base / "history" / "native-delegation.ndjson").exists()


def test_status_terminal_native_spawn_claim_cli_creates_no_private_token(
    tmp_path: Path,
) -> None:
    base = _base_dir(tmp_path)
    state = _write_pending_reconciliation_state(
        base,
        task_id="terminal-claim-cli",
        phase="spawn_requested",
        status="completed",
    )
    state_path = base / "run" / "terminal-claim-cli.json"
    before = state_path.read_bytes()

    claimed = _run_mst(
        base.parent,
        "delegation",
        "claim-spawn",
        "--task-id",
        "terminal-claim-cli",
        "--attempt-id",
        str(state["attempt_id"]),
        "--claimant-id",
        "terminal-claim-cli-test",
        "--idempotency-key",
        "terminal-claim-cli:key",
    )

    assert claimed.returncode == 0, claimed.stderr
    payload = json.loads(claimed.stdout)
    assert payload["spawn_allowed"] is False
    assert payload["claim_status"] == "terminal"
    assert payload["next_action"] == "stop"
    assert payload["claim_token"] is None
    assert payload["claim_token_file"] is None
    assert state_path.read_bytes() == before
    secret_dir = base / "run" / ".claim-secrets"
    assert not secret_dir.exists() or list(secret_dir.iterdir()) == []
    assert not (base / "history" / "native-delegation.ndjson").exists()


def test_terminal_spawn_claim_preserves_exact_replay_before_new_key_guard(
    tmp_path: Path,
) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="terminal-claim-replay",
        idempotency_key="terminal-claim-replay:start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    first = claim_native_spawn(
        base_dir=base,
        task_id="terminal-claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="terminal-claim-replay-parent",
        idempotency_key="terminal-claim-replay:key",
    )
    assert first["spawn_allowed"] is True
    state_path = base / "run" / "terminal-claim-replay.json"
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    terminal["status"] = "completed"
    state_path.write_text(json.dumps(terminal) + "\n", encoding="utf-8")
    before = state_path.read_bytes()

    replay = claim_native_spawn(
        base_dir=base,
        task_id="terminal-claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="terminal-claim-replay-parent",
        idempotency_key="terminal-claim-replay:key",
    )
    assert replay["spawn_allowed"] is False
    assert replay["claim_status"] == "claim_replay"
    assert replay["claim_token"] is None

    guarded = claim_native_spawn(
        base_dir=base,
        task_id="terminal-claim-replay",
        expected_attempt_id=started["attempt_id"],
        claimant_id="terminal-claim-replay-parent",
        idempotency_key="terminal-claim-replay:new-key",
    )
    assert guarded["spawn_allowed"] is False
    assert guarded["claim_status"] == "terminal"
    assert guarded["next_action"] == "stop"
    assert state_path.read_bytes() == before


def test_native_spawn_claim_rejects_nonterminal_external_lane_without_authority(
    tmp_path: Path,
) -> None:
    base = _base_dir(tmp_path)
    state = _write_pending_reconciliation_state(
        base,
        task_id="external-lane-native-claim",
        phase="spawn_requested",
        status="spawn_requested",
        execution_transport="external",
    )
    state_path = base / "run" / "external-lane-native-claim.json"
    before = state_path.read_bytes()

    with pytest.raises(
        LifecycleConflict,
        match="native spawn claim requires native execution transport",
    ):
        claim_native_spawn(
            base_dir=base,
            task_id="external-lane-native-claim",
            expected_attempt_id=state["attempt_id"],
            claimant_id="wrong-lane-parent",
            idempotency_key="external-lane-native-claim:key",
        )
    assert state_path.read_bytes() == before
    assert not (base / "history" / "native-delegation.ndjson").exists()
    assert not (base / "run" / ".claim-secrets").exists()


@pytest.mark.parametrize(
    ("operation", "phase", "event"),
    (
        ("acknowledge", "spawn_requested", "acknowledge"),
        ("attach", "spawned", "attach"),
        ("heartbeat", "running", "heartbeat"),
        ("complete", "running", "complete"),
        ("fallback", "planned", "fallback"),
        ("cancel", "running", "cancel"),
        ("recover", "running", "recover"),
    ),
)
def test_native_mutation_entrypoints_reject_external_lane(
    tmp_path: Path,
    operation: str,
    phase: str,
    event: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"external-lane-native-{operation}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase=phase,
        status=phase,
        execution_transport="external",
    )
    state_path = base / "run" / f"{task_id}.json"
    before = state_path.read_bytes()

    if operation == "acknowledge":
        action = lambda: acknowledge_native_spawn(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            spawn_status="accepted",
            claim_token="wrong-lane-token",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "attach":
        action = lambda: attach_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            attach_status="attached",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "heartbeat":
        action = lambda: native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "complete":
        action = lambda: complete_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            completion_signal="failed",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "fallback":
        action = lambda: request_external_fallback(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "cancel":
        action = lambda: cancel_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )
    else:
        action = lambda: recover_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )

    with pytest.raises(
        LifecycleConflict,
        match=rf"{event} requires native execution transport, found 'external'",
    ):
        action()
    assert state_path.read_bytes() == before
    assert not (base / "history" / "native-delegation.ndjson").exists()


@pytest.mark.parametrize(
    ("operation", "phase", "event"),
    (
        ("prompt", "running", "external_prompt_delivered"),
        ("cancel", "running", "external_cancel_requested"),
        ("reconcile", "cancel_requested", "external_cancel_reconcile_blocked"),
        ("reap", "running", "external_provider_reap_unconfirmed"),
    ),
)
def test_external_mutation_entrypoints_reject_native_lane(
    tmp_path: Path,
    operation: str,
    phase: str,
    event: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"native-lane-external-{operation}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase=phase,
        status=phase,
        execution_transport="native",
    )
    state_path = base / "run" / f"{task_id}.json"
    before = state_path.read_bytes()

    if operation == "prompt":
        action = lambda: native_delegation_mod.record_external_prompt_delivery(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            claim_owner_pid=1,
            provider_pid=2,
            prompt_execution_hash="sha256:wrong-lane",
            prompt_transport="stdin_claimed_fd",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "cancel":
        action = lambda: native_delegation_mod.request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "reconcile":
        action = lambda: native_delegation_mod.mark_external_cancel_reconciling(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            reason="wrong-lane",
            idempotency_key=f"{task_id}:mutation",
        )
    else:
        action = lambda: native_delegation_mod.record_external_reap_unconfirmed(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            cancellation_requested=False,
            provider_reap_evidence={"status": "wrong-lane"},
            idempotency_key=f"{task_id}:mutation",
        )

    with pytest.raises(
        LifecycleConflict,
        match=rf"{event} requires external execution transport, found 'native'",
    ):
        action()
    assert state_path.read_bytes() == before
    assert not (base / "history" / "native-delegation.ndjson").exists()


@pytest.mark.parametrize("status", sorted(native_delegation_mod.TERMINAL_STATUSES))
def test_status_terminal_heartbeat_cannot_reclassify_or_be_reopened_by_cli(
    tmp_path: Path,
    status: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"terminal-heartbeat-{status}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase="running",
        status=status,
    )
    state_path = base / "run" / f"{task_id}.json"
    before = state_path.read_bytes()

    with pytest.raises(LifecycleConflict, match="terminal lifecycle attempt cannot heartbeat"):
        native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            provider_state="running",
            idempotency_key=f"{task_id}:direct",
        )
    assert state_path.read_bytes() == before

    heartbeat_cli = _run_mst(
        base.parent,
        "delegation",
        "heartbeat",
        "--task-id",
        task_id,
        "--attempt-id",
        str(state["attempt_id"]),
        "--provider-state",
        "running",
        "--idempotency-key",
        f"{task_id}:cli",
    )
    assert heartbeat_cli.returncode != 0
    assert "terminal lifecycle attempt cannot heartbeat" in (
        heartbeat_cli.stdout + heartbeat_cli.stderr
    )
    assert state_path.read_bytes() == before


@pytest.mark.parametrize(
    ("operation", "phase"),
    (
        ("acknowledge", "spawn_requested"),
        ("attach", "spawned"),
        ("cancel", "running"),
        ("recover", "running"),
        ("fallback", "planned"),
    ),
)
def test_status_terminal_representative_native_mutations_are_fail_closed(
    tmp_path: Path,
    operation: str,
    phase: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"terminal-mutation-{operation}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase=phase,
        status="completed",
    )
    state_path = base / "run" / f"{task_id}.json"
    before = state_path.read_bytes()

    if operation == "acknowledge":
        action = lambda: acknowledge_native_spawn(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            spawn_status="accepted",
            claim_token="must-not-be-consumed",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "attach":
        action = lambda: attach_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            attach_status="attached",
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "cancel":
        action = lambda: cancel_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )
    elif operation == "recover":
        action = lambda: recover_native_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )
    else:
        action = lambda: request_external_fallback(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
            idempotency_key=f"{task_id}:mutation",
        )

    with pytest.raises(
        LifecycleConflict,
        match=f"terminal lifecycle attempt cannot {operation}",
    ):
        action()
    assert state_path.read_bytes() == before


def test_terminal_mutation_exact_replay_is_returned_before_fail_closed_guard(
    tmp_path: Path,
) -> None:
    base, _output, started = _started_native_with_expected_output(
        tmp_path,
        "terminal-exact-replay",
    )
    heartbeat = native_delegation_mod.heartbeat_native_attempt(
        base_dir=base,
        task_id="terminal-exact-replay",
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        parent_heartbeat="2026-07-12T00:00:00+00:00",
        idempotency_key="terminal-exact-replay:heartbeat",
    )
    state_path = base / "run" / "terminal-exact-replay.json"
    heartbeat["status"] = "completed"
    state_path.write_text(json.dumps(heartbeat) + "\n", encoding="utf-8")

    replay = native_delegation_mod.heartbeat_native_attempt(
        base_dir=base,
        task_id="terminal-exact-replay",
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        parent_heartbeat="2026-07-12T00:00:00+00:00",
        idempotency_key="terminal-exact-replay:heartbeat",
    )
    assert replay["status"] == "completed"
    assert replay["idempotency_keys"] == heartbeat["idempotency_keys"]

    with pytest.raises(LifecycleConflict, match="conflicting replay"):
        native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id="terminal-exact-replay",
            expected_attempt_id=started["attempt_id"],
            provider_state="running",
            parent_heartbeat="2026-07-12T00:00:01+00:00",
            idempotency_key="terminal-exact-replay:heartbeat",
        )

    with pytest.raises(LifecycleConflict, match="terminal lifecycle attempt cannot heartbeat"):
        native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id="terminal-exact-replay",
            expected_attempt_id=started["attempt_id"],
            provider_state="running",
            parent_heartbeat="2026-07-12T00:00:00+00:00",
            idempotency_key="terminal-exact-replay:new-heartbeat",
        )


def test_transport_guard_preserves_exact_replay_before_lane_rejection(
    tmp_path: Path,
) -> None:
    base, _output, started = _started_native_with_expected_output(
        tmp_path,
        "transport-exact-replay",
    )
    heartbeat = native_delegation_mod.heartbeat_native_attempt(
        base_dir=base,
        task_id="transport-exact-replay",
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        parent_heartbeat="2026-07-12T00:00:00+00:00",
        idempotency_key="transport-exact-replay:heartbeat",
    )
    state_path = base / "run" / "transport-exact-replay.json"
    heartbeat["execution_transport"] = "external"
    state_path.write_text(json.dumps(heartbeat) + "\n", encoding="utf-8")

    replay = native_delegation_mod.heartbeat_native_attempt(
        base_dir=base,
        task_id="transport-exact-replay",
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        parent_heartbeat="2026-07-12T00:00:00+00:00",
        idempotency_key="transport-exact-replay:heartbeat",
    )
    assert replay["execution_transport"] == "external"
    assert replay["idempotency_keys"] == heartbeat["idempotency_keys"]

    with pytest.raises(LifecycleConflict, match="conflicting replay"):
        native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id="transport-exact-replay",
            expected_attempt_id=started["attempt_id"],
            provider_state="running",
            parent_heartbeat="2026-07-12T00:00:01+00:00",
            idempotency_key="transport-exact-replay:heartbeat",
        )

    with pytest.raises(
        LifecycleConflict,
        match="heartbeat requires native execution transport, found 'external'",
    ):
        native_delegation_mod.heartbeat_native_attempt(
            base_dir=base,
            task_id="transport-exact-replay",
            expected_attempt_id=started["attempt_id"],
            provider_state="running",
            parent_heartbeat="2026-07-12T00:00:00+00:00",
            idempotency_key="transport-exact-replay:new-heartbeat",
        )


@pytest.mark.parametrize("status", sorted(native_delegation_mod.TERMINAL_STATUSES))
def test_status_terminal_reconciliation_action_is_never_readable(
    tmp_path: Path,
    status: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"status-terminal-{status}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase="running",
        status=status,
    )

    assert native_delegation_mod.lifecycle_is_terminal(state) is True
    with pytest.raises(LifecycleConflict, match="no pending provider reconciliation action"):
        native_delegation_mod.get_reconciliation_action(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=state["attempt_id"],
        )


@pytest.mark.parametrize(
    "status",
    ("completed", "failed", "cancelled", "fallback_completed"),
)
def test_status_terminal_reconciliation_action_cli_is_fail_closed(
    tmp_path: Path,
    status: str,
) -> None:
    base = _base_dir(tmp_path)
    task_id = f"status-terminal-cli-{status}"
    state = _write_pending_reconciliation_state(
        base,
        task_id=task_id,
        phase="running",
        status=status,
    )

    action_cli = _run_mst(
        base.parent,
        "delegation",
        "reconcile-action",
        "--task-id",
        task_id,
        "--attempt-id",
        str(state["attempt_id"]),
    )
    assert action_cli.returncode != 0
    assert "no pending provider reconciliation action" in (
        action_cli.stdout + action_cli.stderr
    )


def test_native_recovery_completion_atomically_resolves_reconciliation(
    tmp_path: Path,
) -> None:
    base, output, started = _started_native_with_expected_output(
        tmp_path,
        "native-reconcile-terminal",
    )
    recovered = recover_native_attempt(
        base_dir=base,
        task_id="native-reconcile-terminal",
        expected_attempt_id=started["attempt_id"],
        provider_state="unknown",
        idempotency_key="native-reconcile-terminal:recover",
    )
    pending = recovered["reconciliation_action"]
    assert recovered["provider_reconciliation_required"] is True
    assert pending["status"] == "pending"

    output.write_text("conclusive native result\n", encoding="utf-8")
    terminal = complete_native_attempt(
        base_dir=base,
        task_id="native-reconcile-terminal",
        expected_attempt_id=started["attempt_id"],
        completion_signal="completed",
        output_path=output,
        idempotency_key="native-reconcile-terminal:complete",
    )

    assert terminal["phase"] == "done"
    assert terminal["status"] == "completed"
    assert terminal["provider_state"] == "completed"
    assert terminal["provider_reconciliation_required"] is False
    resolved = terminal["reconciliation_action"]
    assert resolved["action_id"] == pending["action_id"]
    assert resolved["status"] == "resolved"
    assert resolved["completion_accepted"] is True
    assert resolved["resolved_at"] == terminal["terminated_at"]
    assert resolved["result"]["provider_state"] == "completed"
    assert resolved["result"]["completion_signal"] == "completed"
    assert resolved["result"]["phase"] == "done"
    assert resolved["result"]["status"] == "completed"
    assert resolved["result"]["observed_at"] == terminal["terminated_at"]
    assert resolved["result"]["evidence_source"] == "terminal_lifecycle_state"

    with pytest.raises(LifecycleConflict, match="no pending provider reconciliation action"):
        native_delegation_mod.get_reconciliation_action(
            base_dir=base,
            task_id="native-reconcile-terminal",
            expected_attempt_id=started["attempt_id"],
        )
    action_cli = _run_mst(
        base.parent,
        "delegation",
        "reconcile-action",
        "--task-id",
        "native-reconcile-terminal",
        "--attempt-id",
        str(started["attempt_id"]),
    )
    assert action_cli.returncode != 0
    assert "no pending provider reconciliation action" in (
        action_cli.stdout + action_cli.stderr
    )

    listed = _run_mst(base.parent, "dispatch", "list", "--format", "json")
    assert listed.returncode == 0, listed.stderr
    row = next(
        item
        for item in json.loads(listed.stdout)
        if item["task_id"] == "native-reconcile-terminal"
    )
    assert row["phase"] == "done"
    assert row["status"] == "completed"
    assert row["reconciliation_required"] is False
    assert row["reconciliation_invariant_gap"] is False
    assert row["reconciliation_action"] == resolved

    consumer = project_lifecycle_artifact_consumer_summary(terminal)
    assert not {
        "terminal_reconciliation_required",
        "terminal_pending_reconciliation",
        "terminal_reconciliation_resolution_incomplete",
    }.intersection(gap["code"] for gap in consumer["gaps"])
    assert consumer["provider_reconciliation_required"] is False
    assert consumer["reconciliation_action"] == resolved
    history = [
        json.loads(line)
        for line in (base / "history" / "native-delegation.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert history[-1]["phase"] == "done"
    assert history[-1]["reconciliation_action"] == resolved


@pytest.mark.parametrize(
    ("completion_signal", "expected_phase", "expected_status", "provider_state"),
    (
        ("failed", "failed", "failed", "failed"),
        ("cancelled", "terminated", "cancelled", "cancelled"),
    ),
)
def test_native_recovery_non_success_terminal_also_resolves_reconciliation(
    tmp_path: Path,
    completion_signal: str,
    expected_phase: str,
    expected_status: str,
    provider_state: str,
) -> None:
    task_id = f"native-reconcile-{completion_signal}"
    base, output, started = _started_native_with_expected_output(
        tmp_path,
        task_id,
    )
    recovered = recover_native_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=started["attempt_id"],
        provider_state="running",
        idempotency_key=f"{task_id}:recover",
    )
    pending = recovered["reconciliation_action"]
    terminal = complete_native_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=started["attempt_id"],
        completion_signal=completion_signal,
        output_path=output,
        idempotency_key=f"{task_id}:complete",
    )

    assert terminal["phase"] == expected_phase
    assert terminal["status"] == expected_status
    assert terminal["provider_state"] == provider_state
    assert terminal["provider_reconciliation_required"] is False
    resolved = terminal["reconciliation_action"]
    assert resolved["action_id"] == pending["action_id"]
    assert resolved["status"] == "resolved"
    assert resolved["completion_accepted"] is True
    assert resolved["resolved_at"] == terminal["terminated_at"]
    assert resolved["result"]["provider_state"] == provider_state
    assert resolved["result"]["prior_provider_state"] is None
    assert resolved["result"]["completion_signal"] == completion_signal
    with pytest.raises(LifecycleConflict, match="no pending provider reconciliation action"):
        native_delegation_mod.get_reconciliation_action(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=started["attempt_id"],
        )


def test_fallback_exact_replay_precedes_attempt_cas_and_conflicts_are_rejected(tmp_path: Path) -> None:
    base = _base_dir(tmp_path)
    started = start_native_attempt(
        base_dir=base,
        task_id="fallback-replay",
        attempt_id="native-source",
        idempotency_key="start",
        host="codex",
        provider="codex",
        worktree_dir=base.parent,
        scope="analysis",
        read_only=True,
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="fallback-replay",
        expected_attempt_id=started["attempt_id"],
        spawn_status="definitive_not_created",
        claim_token=_claim_token(base, "fallback-replay", str(started["attempt_id"])),
        idempotency_key="ack",
    )
    first = request_external_fallback(
        base_dir=base,
        task_id="fallback-replay",
        expected_attempt_id="native-source",
        attempt_id="external-fixed",
        idempotency_key="fallback-key",
    )
    replay = request_external_fallback(
        base_dir=base,
        task_id="fallback-replay",
        expected_attempt_id="native-source",
        attempt_id="external-fixed",
        idempotency_key="fallback-key",
    )

    assert replay == first
    record = replay["idempotency_keys"]["fallback-key"]
    assert record["operation"] == "fallback"
    assert record["source_attempt_id"] == "native-source"
    assert record["result_attempt_id"] == "external-fixed"
    assert record["fingerprint"].startswith("sha256:")
    with pytest.raises(LifecycleConflict, match="conflicting replay"):
        request_external_fallback(
            base_dir=base,
            task_id="fallback-replay",
            expected_attempt_id="native-source",
            attempt_id="different-external",
            idempotency_key="fallback-key",
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_write_capable_native_attempt_requires_linked_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("seed", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    base = repo / ".gran-maestro"
    base.mkdir()

    with pytest.raises(LifecycleConflict, match="read-only exception"):
        start_native_attempt(
            base_dir=base,
            task_id="write-read-only-bypass",
            idempotency_key="start-read-only-bypass",
            host="codex",
            provider="codex",
            worktree_dir=repo,
            scope="implementation",
            read_only=True,
        )
    assert not (base / "run" / "artifacts" / "write-read-only-bypass").exists()
    assert not (base / "run" / "write-read-only-bypass.json").exists()

    with pytest.raises(LifecycleConflict, match="primary checkout"):
        start_native_attempt(
            base_dir=base,
            task_id="write-primary",
            idempotency_key="start-primary",
            host="codex",
            provider="codex",
            worktree_dir=repo,
            scope="implementation",
            read_only=False,
        )
    assert not (base / "run" / "artifacts" / "write-primary").exists()
    assert not (base / "run" / "write-primary.json").exists()

    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "feature/native", str(linked), "main")
    state = start_native_attempt(
        base_dir=base,
        task_id="write-linked",
        idempotency_key="start-linked",
        host="codex",
        provider="codex",
        worktree_dir=linked,
        scope="implementation",
        read_only=False,
    )
    assert state["worktree_dir"] == str(linked.resolve())
    assert state["worktree_guard"]["ok"] is True
