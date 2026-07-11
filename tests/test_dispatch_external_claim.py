from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.mst_cmds import native_delegation as native_delegation_mod
from scripts.mst_cmds.current_work_handoff import (
    project_lifecycle_artifact_consumer_summary,
    project_lifecycle_artifacts_for_session,
)
from scripts.mst_cmds.native_delegation import (
    acknowledge_native_spawn,
    claim_native_spawn,
    request_external_cancel,
    request_external_fallback,
    run_external_adapter,
    start_external_attempt,
    start_native_attempt,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "MST-REQ-939-20260712T010203004Z-extclaim"
MODEL = "gpt-external-claim-test"


def _write_provider_stub(bin_dir: Path, spawn_log: Path, *, delay: float = 0.1) -> None:
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        f"printf 'spawn\\n' >> {spawn_log}\n"
        "cat >/dev/null\n"
        f"sleep {delay}\n"
        "printf 'external provider result\\n'\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env={**os.environ, "MST_SESSION_ID": SESSION_ID},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _build_external_command(workspace: Path, state: dict) -> str:
    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(state["prompt_file"]),
        "--task-id",
        str(state["task_id"]),
        "--worktree-dir",
        str(state["worktree_dir"]),
        "--log-file",
        str(state["running_log_path"]),
        "--model",
        str(state["model"]),
        "--expected-attempt-id",
        str(state["attempt_id"]),
    )
    assert built.returncode == 0, built.stderr
    return built.stdout.strip()


def _execute_wrapper(workspace: Path, command: str, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
            "MST_DISPATCH_HEARTBEAT_INTERVAL": "10",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for external lifecycle evidence")


def _update_state_file(path: Path, **updates) -> dict:
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(updates)
    path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    return state


def _assert_external_reconciliation_action(
    state: dict,
    *,
    next_operation: str,
) -> dict:
    action = state.get("reconciliation_action")
    assert isinstance(action, dict)
    assert action["kind"] == "provider_reconcile"
    assert action["status"] == "pending"
    assert action["completion_accepted"] is False
    assert action["attempt_id"] == state["attempt_id"]
    assert action["provider"] == state["provider"]
    assert action["next_operation"] == next_operation
    assert action["action_id"].startswith("provider-reconcile:")
    assert "group_observed_gone" in action["required_result_fields"]
    return action


def _assert_resolved_reconciliation_action(state: dict, pending: dict) -> dict:
    action = state.get("reconciliation_action")
    assert isinstance(action, dict)
    assert action["action_id"] == pending["action_id"]
    assert action["status"] == "resolved"
    assert action["completion_accepted"] is True
    assert action["resolved_at"] == state["terminated_at"]
    assert action["result"]["phase"] == state["phase"]
    assert action["result"]["status"] == state["status"]
    assert action["result"]["completion_signal"] == state["completion_signal"]
    assert action["result"]["observed_at"] == state["terminated_at"]
    assert action["result"]["evidence_source"] == "terminal_lifecycle_state"
    return action


def test_status_terminal_external_claim_and_run_issue_no_authority(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("terminal external authority", encoding="utf-8")
    output = workspace / "result.md"
    output.write_text("preserve baseline", encoding="utf-8")
    task_id = "REQ-939-terminal-external-claim"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    state_path = base / "run" / f"{task_id}.json"
    terminal = _update_state_file(state_path, status="completed")
    before = state_path.read_bytes()
    snapshot = Path(str(prepared["prompt_snapshot_path"]))
    assert not snapshot.exists()
    private_resources: dict = {}

    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="terminal lifecycle attempt cannot issue external claim authority",
    ):
        native_delegation_mod.claim_external_attempt(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=terminal["attempt_id"],
            provider="codex",
            worktree_dir=workspace,
            prompt_file=prompt,
            prompt_snapshot_path=prepared["prompt_snapshot_path"],
            model=MODEL,
            scope="analysis",
            read_only=True,
            running_log_path=prepared["running_log_path"],
            trace_path=prepared["trace_path"],
            output_path=output,
            pid=os.getpid(),
            pid_start_time="terminal-claim-owner",
            started_by_pid=os.getppid(),
            idempotency_key=f"{task_id}:claim",
            mst_session_id=SESSION_ID,
            _private_resources=private_resources,
        )
    assert private_resources == {}
    assert state_path.read_bytes() == before
    assert output.read_text(encoding="utf-8") == "preserve baseline"
    assert not snapshot.exists()

    marker = workspace / "provider-spawned"
    provider = tmp_path / "codex"
    provider.write_text(
        f"#!/bin/sh\ntouch {marker}\nprintf unexpected\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="terminal lifecycle attempt cannot run external adapter",
    ):
        run_external_adapter(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=terminal["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()
    assert state_path.read_bytes() == before


def test_claimed_external_attempt_rejects_native_heartbeat_and_completion_cli(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("external lane ownership", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-external-lane-ownership"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    private_resources: dict = {}
    claimed = native_delegation_mod.claim_external_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        worktree_dir=workspace,
        prompt_file=prompt,
        prompt_snapshot_path=prepared["prompt_snapshot_path"],
        model=MODEL,
        scope="analysis",
        read_only=True,
        running_log_path=prepared["running_log_path"],
        trace_path=prepared["trace_path"],
        output_path=output,
        pid=os.getpid(),
        pid_start_time="external-lane-owner",
        started_by_pid=os.getppid(),
        idempotency_key=f"{task_id}:claim",
        mst_session_id=SESSION_ID,
        _private_resources=private_resources,
    )
    state_path = base / "run" / f"{task_id}.json"
    history_path = base / "history" / "native-delegation.ndjson"
    before_state = state_path.read_bytes()
    before_history = history_path.read_bytes()
    try:
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="heartbeat requires native execution transport, found 'external'",
        ):
            native_delegation_mod.heartbeat_native_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=claimed["attempt_id"],
                idempotency_key=f"{task_id}:native-heartbeat",
            )
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="complete requires native execution transport, found 'external'",
        ):
            native_delegation_mod.complete_native_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=claimed["attempt_id"],
                completion_signal="failed",
                idempotency_key=f"{task_id}:native-complete",
            )

        heartbeat_cli = _run_mst(
            workspace,
            "delegation",
            "heartbeat",
            "--task-id",
            task_id,
            "--attempt-id",
            str(claimed["attempt_id"]),
            "--idempotency-key",
            f"{task_id}:native-heartbeat-cli",
        )
        assert heartbeat_cli.returncode != 0
        assert "heartbeat requires native execution transport, found 'external'" in (
            heartbeat_cli.stdout + heartbeat_cli.stderr
        )
        complete_cli = _run_mst(
            workspace,
            "delegation",
            "complete",
            "--task-id",
            task_id,
            "--attempt-id",
            str(claimed["attempt_id"]),
            "--completion-signal",
            "failed",
            "--idempotency-key",
            f"{task_id}:native-complete-cli",
        )
        assert complete_cli.returncode != 0
        assert "complete requires native execution transport, found 'external'" in (
            complete_cli.stdout + complete_cli.stderr
        )
        assert state_path.read_bytes() == before_state
        assert history_path.read_bytes() == before_history
    finally:
        output_fd = private_resources.get("output_fd")
        if isinstance(output_fd, int):
            os.close(output_fd)


def test_live_external_provider_finalizes_after_wrong_lane_native_calls_fail(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("live external lane ownership", encoding="utf-8")
    output = workspace / "result.md"
    marker = workspace / "provider-side-effect"
    task_id = "REQ-939-live-external-lane"
    provider = tmp_path / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        "sleep 0.8\n"
        f"printf provider-ran > {marker}\n"
        "printf 'live external result\\n'\n"
        "printf 'live external stderr\\n' >&2\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    state_path = base / "run" / f"{task_id}.json"
    history_path = base / "history" / "native-delegation.ndjson"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_external_adapter,
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
        _wait_for(
            lambda: json.loads(state_path.read_text(encoding="utf-8")).get(
                "provider_exec_release_status"
            )
            == "released"
        )
        running = json.loads(state_path.read_text(encoding="utf-8"))
        before_state = state_path.read_bytes()
        before_history = history_path.read_bytes()
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="heartbeat requires native execution transport, found 'external'",
        ):
            native_delegation_mod.heartbeat_native_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=running["attempt_id"],
                idempotency_key=f"{task_id}:wrong-heartbeat",
            )
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="complete requires native execution transport, found 'external'",
        ):
            native_delegation_mod.complete_native_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=running["attempt_id"],
                completion_signal="failed",
                idempotency_key=f"{task_id}:wrong-complete",
            )
        assert state_path.read_bytes() == before_state
        assert history_path.read_bytes() == before_history
        terminal = future.result(timeout=10)

    assert marker.read_text(encoding="utf-8") == "provider-ran"
    assert terminal["execution_transport"] == "external"
    assert terminal["phase"] == "done"
    assert terminal["status"] == "completed"
    assert terminal["exit_code"] == 0
    assert terminal["completion_signal"] == "process_exit"
    assert terminal["provider_reap_evidence"]["group_observed_gone"] is True
    assert terminal["stderr_evidence"]["byte_count"] > 0
    assert terminal["output_publish"]["status"] == "published"
    assert output.read_text(encoding="utf-8") == "live external result\n"
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
    ]
    assert history[-1]["event_type"] == "delegation.external_finalize"
    assert history[-1]["phase"] == "done"
    assert history[-1]["execution_transport"] == "external"


def test_status_terminal_external_runtime_boundaries_issue_no_new_authority(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("terminal external runtime", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-terminal-external-runtime"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    private_resources: dict = {}
    owner_pid = os.getpid()
    provider_pid = 999_999_923
    claimed = native_delegation_mod.claim_external_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        worktree_dir=workspace,
        prompt_file=prompt,
        prompt_snapshot_path=prepared["prompt_snapshot_path"],
        model=MODEL,
        scope="analysis",
        read_only=True,
        running_log_path=prepared["running_log_path"],
        trace_path=prepared["trace_path"],
        output_path=output,
        pid=owner_pid,
        pid_start_time="terminal-runtime-owner",
        started_by_pid=os.getppid(),
        idempotency_key=f"{task_id}:claim",
        mst_session_id=SESSION_ID,
        _private_resources=private_resources,
    )
    state_path = base / "run" / f"{task_id}.json"
    try:
        terminal = _update_state_file(state_path, status="completed")
        before = state_path.read_bytes()
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot external heartbeat",
        ):
            native_delegation_mod.heartbeat_external_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=terminal["attempt_id"],
                pid=owner_pid,
            )
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot attach external provider authority",
        ):
            native_delegation_mod.attach_external_provider_process(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=terminal["attempt_id"],
                claim_owner_pid=owner_pid,
                provider_pid=provider_pid,
                provider_pgid=provider_pid,
                provider_pid_start_time="terminal-provider-start",
                prompt_execution_hash=prepared["prompt_hash"],
                idempotency_key=f"{task_id}:terminal-attach",
            )
        assert state_path.read_bytes() == before

        _update_state_file(state_path, status="running")
        attached = native_delegation_mod.attach_external_provider_process(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=terminal["attempt_id"],
            claim_owner_pid=owner_pid,
            provider_pid=provider_pid,
            provider_pgid=provider_pid,
            provider_pid_start_time="terminal-provider-start",
            prompt_execution_hash=prepared["prompt_hash"],
            idempotency_key=f"{task_id}:attach",
        )
        terminal = _update_state_file(state_path, status="completed")
        before = state_path.read_bytes()
        replay = native_delegation_mod.attach_external_provider_process(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=terminal["attempt_id"],
            claim_owner_pid=owner_pid,
            provider_pid=provider_pid,
            provider_pgid=provider_pid,
            provider_pid_start_time="terminal-provider-start",
            prompt_execution_hash=prepared["prompt_hash"],
            idempotency_key=f"{task_id}:attach-replay",
        )
        assert replay["provider_pid"] == attached["provider_pid"]
        assert replay["status"] == "completed"
        assert state_path.read_bytes() == before

        gate_read_fd, gate_write_fd = os.pipe()
        try:
            with pytest.raises(
                native_delegation_mod.LifecycleConflict,
                match="terminal lifecycle attempt cannot release external provider exec authority",
            ):
                native_delegation_mod.release_external_provider_exec(
                    base_dir=base,
                    task_id=task_id,
                    expected_attempt_id=terminal["attempt_id"],
                    claim_owner_pid=owner_pid,
                    provider_pid=provider_pid,
                    provider_pgid=provider_pid,
                    provider_pid_start_time="terminal-provider-start",
                    gate_write_fd=gate_write_fd,
                    idempotency_key=f"{task_id}:release",
                )
        finally:
            os.close(gate_write_fd)
        assert os.read(gate_read_fd, 1) == b""
        os.close(gate_read_fd)
        assert state_path.read_bytes() == before

        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot external_prompt_delivered",
        ):
            native_delegation_mod.record_external_prompt_delivery(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=terminal["attempt_id"],
                claim_owner_pid=owner_pid,
                provider_pid=provider_pid,
                prompt_execution_hash=prepared["prompt_hash"],
                prompt_transport="stdin_claimed_fd",
                idempotency_key=f"{task_id}:prompt",
            )
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot external_cancel_requested",
        ):
            request_external_cancel(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=terminal["attempt_id"],
                signal_name="TERM",
                idempotency_key=f"{task_id}:cancel",
            )
        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot finalize external attempt",
        ):
            native_delegation_mod.finalize_external_attempt(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=terminal["attempt_id"],
                pid=owner_pid,
                exit_code=0,
                completion_signal="process_exit",
                running_log_path=terminal["running_log_path"],
                trace_path=terminal["trace_path"],
                output_path=output,
                output_bytes=b"must not publish",
                idempotency_key=f"{task_id}:finalize",
            )
        assert output.read_bytes() == b""
        assert state_path.read_bytes() == before
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted.get("provider_exec_authorized_at") is None
        assert persisted.get("provider_exec_released_at") is None
    finally:
        output_fd = private_resources.get("output_fd")
        if isinstance(output_fd, int):
            os.close(output_fd)


def test_external_gate_revalidates_terminal_state_immediately_before_popen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("provider-gate terminal race", encoding="utf-8")
    output = workspace / "result.md"
    marker = workspace / "provider-spawned"
    task_id = "REQ-939-terminal-pre-provider-gate"
    provider = tmp_path / "codex"
    provider.write_text(
        f"#!/bin/sh\ntouch {marker}\nprintf unexpected\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    state_path = base / "run" / f"{task_id}.json"
    original_temporary_file = native_delegation_mod.tempfile.TemporaryFile
    staging_started = False

    def terminalizing_temporary_file(*args, **kwargs):
        nonlocal staging_started
        stage = original_temporary_file(*args, **kwargs)
        if staging_started:
            return stage
        staging_started = True
        _update_state_file(state_path, status="completed")

        def forbidden_popen(*_args, **_kwargs):
            raise AssertionError("anonymous provider gate must not spawn for terminal state")

        monkeypatch.setattr(native_delegation_mod.subprocess, "Popen", forbidden_popen)
        return stage

    monkeypatch.setattr(
        native_delegation_mod.tempfile,
        "TemporaryFile",
        terminalizing_temporary_file,
    )
    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="terminal lifecycle attempt cannot spawn external provider gate",
    ):
        run_external_adapter(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
    assert staging_started is True
    assert not marker.exists()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["phase"] == "running"
    assert persisted["status"] == "completed"
    assert persisted.get("provider_pid") is None


def test_protected_external_claim_is_single_use_under_two_runner_barrier(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("single provider spawn", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    state = start_external_attempt(
        base_dir=base,
        task_id="REQ-939-two-runner",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="two-runner:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    assert "dispatch run-external" in command
    assert "dispatch claim-external" not in command
    assert "dispatch register" not in command

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log, delay=0.2)
    barrier = threading.Barrier(3)

    def runner() -> subprocess.CompletedProcess[str]:
        barrier.wait(timeout=5)
        return _execute_wrapper(workspace, command, bin_dir)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(runner) for _ in range(2)]
        barrier.wait(timeout=5)
        results = [future.result(timeout=30) for future in futures]

    assert sorted(result.returncode for result in results) == [0, 2]
    assert spawn_log.read_text(encoding="utf-8").splitlines() == ["spawn"]
    persisted = json.loads((base / "run" / "REQ-939-two-runner.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "done"
    assert persisted["status"] == "completed"
    assert persisted["completion_signal"] == "process_exit"
    assert persisted["exit_code"] == 0
    assert persisted["running_log_path"] == str(running.resolve())
    assert persisted["trace_path"] == str(trace.resolve())
    assert persisted["output_path"] == str(output.resolve())
    assert persisted["artifact_binding_version"] == 2
    assert persisted["prompt_execution"]["status"] == "verified"
    assert persisted["output_publish"]["status"] == "published"
    assert persisted["output_publish"]["descriptor_bound"] is True
    assert persisted["provider_pgid"] == persisted["provider_pid"]
    assert persisted["provider_exec_release_status"] == "released"
    assert persisted["provider_exec_released_at"]
    assert persisted["provider_reap_evidence"]["group_observed_gone"] is True

    replay = _execute_wrapper(workspace, command, bin_dir)
    assert replay.returncode == 0
    assert spawn_log.read_text(encoding="utf-8").splitlines() == ["spawn"]
    after_replay = json.loads((base / "run" / "REQ-939-two-runner.json").read_text(encoding="utf-8"))
    assert after_replay["phase"] == "done"
    assert after_replay["external_claim_id"] == persisted["external_claim_id"]


def test_central_runner_uses_claimed_prompt_bytes_when_audit_snapshot_changes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    original_prompt = "authorized prompt bytes\n"
    prompt.write_text(original_prompt, encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-prompt-lease"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    assert "dispatch run-external" in command
    assert "codex exec" not in command
    assert ".snapshot.md" not in command

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    received = tmp_path / "received-prompt"
    started = tmp_path / "provider-started"
    release = tmp_path / "release-provider"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        f"cat > {received}\n"
        f"touch {started}\n"
        f"while [ ! -f {release} ]; do sleep 0.02; done\n"
        "printf 'stable result\\n'\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = base / "run" / f"{task_id}.json"
    _wait_for(started.exists)
    claimed = json.loads(state_path.read_text(encoding="utf-8"))
    snapshot = Path(claimed["prompt_snapshot_path"])
    replacement = snapshot.with_name("replacement.snapshot")
    replacement.write_text("changed audit snapshot", encoding="utf-8")
    os.replace(replacement, snapshot)
    release.touch()
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    assert received.read_text(encoding="utf-8") == original_prompt
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    assert terminal["phase"] == "done"
    assert terminal["prompt_execution"]["status"] == "verified"
    assert terminal["prompt_execution"]["transport"] == "stdin_claimed_fd"
    assert terminal["prompt_snapshot_audit"]["status"] == "drifted_or_missing"


def test_split_external_claim_cli_is_blocked_before_authorization_consumption(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("central runner only", encoding="utf-8")
    task_id = "REQ-939-split-claim-blocked"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    blocked = _run_mst(
        workspace,
        "dispatch",
        "claim-external",
        "--provider",
        "codex",
        "--prompt-file",
        str(state["prompt_file"]),
        "--prompt-snapshot-path",
        str(state["prompt_snapshot_path"]),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--expected-attempt-id",
        str(state["attempt_id"]),
        "--model",
        MODEL,
        "--scope",
        "analysis",
        "--read-only",
        "true",
        "--running-log-path",
        str(state["running_log_path"]),
        "--trace-path",
        str(state["trace_path"]),
        "--output-path",
        str(state["output_path"]),
        "--pid",
        str(os.getpid()),
        "--idempotency-key",
        f"{task_id}:split",
    )
    assert blocked.returncode == 2
    assert json.loads(blocked.stderr)["status"] == "central_runner_required"
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "planned"
    assert persisted.get("external_claim_id") is None


def test_nonregular_output_is_rejected_before_claim_or_provider_spawn(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("reject fifo output", encoding="utf-8")
    output = workspace / "result.fifo"
    os.mkfifo(output)
    task_id = "REQ-939-fifo-output"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    started = time.monotonic()
    result = _execute_wrapper(workspace, command, bin_dir)
    assert time.monotonic() - started < 3
    assert result.returncode == 2
    assert "regular file" in result.stderr
    assert not spawn_log.exists()
    assert stat.S_ISFIFO(os.stat(output, follow_symlinks=False).st_mode)
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "planned"
    assert persisted.get("external_claim_id") is None


def test_nonregular_running_log_is_rejected_without_blocking_authorization(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("reject fifo running log", encoding="utf-8")
    running = workspace / "running.fifo"
    os.mkfifo(running)
    task_id = "REQ-939-fifo-running-log"

    started = time.monotonic()
    with pytest.raises(native_delegation_mod.LifecycleConflict, match="safely writable|regular file"):
        start_external_attempt(
            base_dir=base,
            task_id=task_id,
            provider="codex",
            worktree_dir=workspace,
            idempotency_key=f"{task_id}:authorize",
            route_reason="headless_host",
            scope="analysis",
            read_only=True,
            prompt_file=prompt,
            running_log_path=running,
            model=MODEL,
            mst_session_id=SESSION_ID,
        )

    assert time.monotonic() - started < 2
    assert stat.S_ISFIFO(os.stat(running, follow_symlinks=False).st_mode)
    assert not (base / "run" / f"{task_id}.json").exists()


def test_hardlinked_output_is_rejected_without_truncating_link_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("reject hard-linked output", encoding="utf-8")
    victim = workspace / "sensitive.txt"
    victim.write_text("KEEP-ME", encoding="utf-8")
    output = workspace / "result.md"
    os.link(victim, output)
    task_id = "REQ-939-hardlink-output"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)

    result = _execute_wrapper(workspace, command, bin_dir)

    assert result.returncode == 2
    assert "hard link" in result.stderr or "hard-linked" in result.stderr
    assert not spawn_log.exists()
    assert victim.read_text(encoding="utf-8") == "KEEP-ME"
    assert output.read_text(encoding="utf-8") == "KEEP-ME"
    assert os.stat(victim).st_nlink == 2
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "planned"
    assert persisted.get("external_claim_id") is None


def test_output_aliasing_prompt_is_rejected_without_mutating_authorized_prompt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    authorized_prompt = "AUTHORIZED-PROMPT"
    prompt.write_text(authorized_prompt, encoding="utf-8")
    task_id = "REQ-939-output-prompt-alias"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=prompt,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)

    result = _execute_wrapper(workspace, command, bin_dir)

    assert result.returncode == 2
    assert "must be distinct" in result.stderr
    assert not spawn_log.exists()
    assert prompt.read_text(encoding="utf-8") == authorized_prompt
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "planned"
    assert persisted.get("external_claim_id") is None


def test_writable_artifact_cannot_alias_mst_control_plane_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("preserve control plane", encoding="utf-8")
    task_id = "REQ-939-control-plane-alias"
    state_path = base / "run" / f"{task_id}.json"

    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="reserved MST control-plane storage",
    ):
        start_external_attempt(
            base_dir=base,
            task_id=task_id,
            provider="codex",
            worktree_dir=workspace,
            idempotency_key=f"{task_id}:authorize",
            route_reason="headless_host",
            scope="analysis",
            read_only=True,
            prompt_file=prompt,
            running_log_path=state_path,
            model=MODEL,
            mst_session_id=SESSION_ID,
        )

    assert not state_path.exists()
    assert prompt.read_text(encoding="utf-8") == "preserve control plane"


@pytest.mark.parametrize(
    "relative_control_path",
    (
        Path("requests/REQ-939/request.json"),
        Path("agile/AGI-939/session.json"),
        Path("agile/AGI-939/events.ndjson"),
    ),
)
def test_request_and_agile_control_files_cannot_be_provider_artifacts(
    tmp_path: Path,
    relative_control_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("preserve workflow control", encoding="utf-8")
    control_path = base / relative_control_path
    control_path.parent.mkdir(parents=True)
    control_path.write_text("CONTROL", encoding="utf-8")
    task_id = "REQ-939-protected-" + control_path.stem.replace(".", "-")

    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="reserved MST control-plane storage",
    ):
        start_external_attempt(
            base_dir=base,
            task_id=task_id,
            provider="codex",
            worktree_dir=workspace,
            idempotency_key=f"{task_id}:authorize",
            route_reason="headless_host",
            scope="analysis",
            read_only=True,
            prompt_file=prompt,
            output_path=control_path,
            model=MODEL,
            mst_session_id=SESSION_ID,
        )

    assert control_path.read_text(encoding="utf-8") == "CONTROL"
    assert not (base / "run" / f"{task_id}.json").exists()


def test_git_control_path_cannot_be_provider_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("preserve git control", encoding="utf-8")
    git_marker = workspace / ".git"
    git_marker.write_text("gitdir: /protected/gitdir\n", encoding="utf-8")
    task_id = "REQ-939-protected-git-marker"

    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="reserved MST control-plane storage",
    ):
        start_external_attempt(
            base_dir=base,
            task_id=task_id,
            provider="codex",
            worktree_dir=workspace,
            idempotency_key=f"{task_id}:authorize",
            route_reason="headless_host",
            scope="analysis",
            read_only=True,
            prompt_file=prompt,
            output_path=git_marker,
            model=MODEL,
            mst_session_id=SESSION_ID,
        )

    assert git_marker.read_text(encoding="utf-8") == "gitdir: /protected/gitdir\n"
    assert not (base / "run" / f"{task_id}.json").exists()


@pytest.mark.parametrize(
    "relative_task_dir",
    (
        Path("requests/REQ-939/tasks/01"),
        Path("agile/AGI-939/sprints/S01"),
    ),
)
def test_workflow_owned_request_and_agile_artifact_roots_remain_supported(
    tmp_path: Path,
    relative_task_dir: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("compatible workflow artifacts", encoding="utf-8")
    task_id = "REQ-939-compatible-" + relative_task_dir.parts[0]
    task_dir = base / relative_task_dir

    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=task_dir / "running.log",
        trace_path=task_dir / "trace.ndjson",
        output_path=task_dir / "result.md",
        model=MODEL,
        mst_session_id=SESSION_ID,
    )

    assert state["phase"] == "planned"
    assert state["running_log_path"] == str((task_dir / "running.log").resolve())
    assert state["trace_path"] == str((task_dir / "trace.ndjson").resolve())
    assert state["output_path"] == str((task_dir / "result.md").resolve())


def test_oversized_prompt_nonreader_times_out_without_blocking_or_output_publish(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_bytes(b"x" * (2 * 1024 * 1024))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    provider = bin_dir / "codex"
    provider.write_text("#!/bin/sh\nsleep 10\nprintf 'late output\\n'\n", encoding="utf-8")
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)

    generated_task = "REQ-939-large-prompt-generated"
    generated_output = workspace / "generated-result.md"
    generated = start_external_attempt(
        base_dir=base,
        task_id=generated_task,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{generated_task}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=generated_output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, generated)
    started = time.monotonic()
    executed = subprocess.run(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
            "MST_EXTERNAL_RUN_TIMEOUT": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=6,
    )
    assert time.monotonic() - started < 5
    assert executed.returncode == 124, executed.stderr
    generated_state = json.loads(
        (base / "run" / f"{generated_task}.json").read_text(encoding="utf-8")
    )
    assert generated_state["completion_signal"] == "process_timeout"
    assert generated_state["provider_reap_evidence"]["group_observed_gone"] is True
    assert generated_state["output_publish"]["status"] == "not_published_non_success"
    assert generated_output.read_bytes() == b""

    direct_task = "REQ-939-large-prompt-direct"
    direct_output = workspace / "direct-result.md"
    direct = start_external_attempt(
        base_dir=base,
        task_id=direct_task,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{direct_task}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=direct_output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    started = time.monotonic()
    direct_state = run_external_adapter(
        base_dir=base,
        task_id=direct_task,
        expected_attempt_id=direct["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=direct_output,
        idempotency_key=f"{direct_task}:run",
        binary=provider,
        model=MODEL,
        timeout=1,
        scope="analysis",
        read_only=True,
    )
    assert time.monotonic() - started < 5
    assert direct_state["completion_signal"] == "process_timeout"
    assert direct_state["provider_reap_evidence"]["group_observed_gone"] is True
    assert direct_state["output_publish"]["status"] == "not_published_non_success"
    assert direct_output.read_bytes() == b""


def test_unconfirmed_provider_group_stays_nonterminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("stay nonterminal", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-unconfirmed-reap"
    provider = tmp_path / "codex"
    provider.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    monkeypatch.setattr(native_delegation_mod, "_process_group_alive", lambda _pgid: True)
    monkeypatch.setattr(
        native_delegation_mod,
        "_terminate_external_provider_group",
        lambda **_kwargs: {
            "status": "termination_unconfirmed",
            "term_sent": True,
            "kill_sent": True,
            "group_observed_gone": False,
        },
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_external_adapter,
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
        state_path = base / "run" / f"{task_id}.json"
        _wait_for(
            lambda: bool(
                json.loads(state_path.read_text(encoding="utf-8")).get("provider_pgid")
            )
        )
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        state = future.result(timeout=10)

    assert state["phase"] == "cancel_requested"
    assert state["status"] == "cancel_requested"
    assert state["completion_signal"] is None
    assert state.get("terminated_at") is None
    assert state["provider_reap_evidence"]["group_observed_gone"] is False
    _assert_external_reconciliation_action(
        state,
        next_operation="reconcile_external_provider_group",
    )
    assert "output_publish" not in state


def test_cancel_committed_after_gate_attach_prevents_provider_exec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("cancel before provider exec", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-cancel-before-provider-exec"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    provider = bin_dir / "codex"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    attached = threading.Event()
    allow_attach_return = threading.Event()
    original_attach = native_delegation_mod.attach_external_provider_process

    def barrier_attach(**kwargs):
        state = original_attach(**kwargs)
        attached.set()
        assert allow_attach_return.wait(timeout=5)
        return state

    monkeypatch.setattr(native_delegation_mod, "attach_external_provider_process", barrier_attach)
    monkeypatch.setenv("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "0.1")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_external_adapter,
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
        assert attached.wait(timeout=5)
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        allow_attach_return.set()
        state = future.result(timeout=10)

    assert not spawn_log.exists()
    assert state["phase"] == "terminated"
    assert state["status"] == "cancelled"
    assert state["completion_signal"] == "process_cancelled"
    assert state["provider_reap_evidence"]["group_observed_gone"] is True
    assert state["output_publish"]["status"] == "cancelled_not_published"
    assert output.read_bytes() == b""


def test_exec_gate_ignores_python_startup_hooks_before_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("isolated gate startup", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-isolated-exec-gate"
    startup_marker = tmp_path / "sitecustomize-side-effect"
    python_path = tmp_path / "python-path"
    python_path.mkdir()
    (python_path / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(startup_marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    provider = bin_dir / "codex"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    attached = threading.Event()
    allow_attach_return = threading.Event()
    original_attach = native_delegation_mod.attach_external_provider_process

    def barrier_attach(**kwargs):
        state = original_attach(**kwargs)
        attached.set()
        assert allow_attach_return.wait(timeout=5)
        return state

    monkeypatch.setattr(native_delegation_mod, "attach_external_provider_process", barrier_attach)
    provider_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(python_path),
    }

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_external_adapter,
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            env=provider_env,
            scope="analysis",
            read_only=True,
        )
        assert attached.wait(timeout=5)
        assert not startup_marker.exists()
        assert not spawn_log.exists()
        allow_attach_return.set()
        state = future.result(timeout=10)

    assert state["phase"] == "done"
    assert state["provider_exec_release_status"] == "released"
    assert not startup_marker.exists()
    assert spawn_log.read_text(encoding="utf-8").splitlines() == ["spawn"]


def test_cancel_committed_after_claim_prevents_even_gate_spawn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("cancel immediately after claim", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-cancel-after-claim"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    provider = bin_dir / "codex"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    claimed = threading.Event()
    allow_claim_return = threading.Event()
    original_claim = native_delegation_mod.claim_external_attempt

    def barrier_claim(**kwargs):
        state = original_claim(**kwargs)
        claimed.set()
        assert allow_claim_return.wait(timeout=5)
        return state

    monkeypatch.setattr(native_delegation_mod, "claim_external_attempt", barrier_claim)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_external_adapter,
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key=f"{task_id}:run",
            binary=provider,
            model=MODEL,
            scope="analysis",
            read_only=True,
        )
        assert claimed.wait(timeout=5)
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=prepared["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        allow_claim_return.set()
        state = future.result(timeout=10)

    assert not spawn_log.exists()
    assert state["phase"] == "terminated"
    assert state["status"] == "cancelled"
    assert state["completion_signal"] == "process_cancelled"
    assert state.get("provider_pid") is None
    assert state["provider_reap_evidence"]["status"] == "cancelled_before_provider_spawn"
    assert state["provider_reap_evidence"]["group_observed_gone"] is True
    assert state["output_publish"]["status"] == "cancelled_not_published"


def test_runner_loss_before_provider_attachment_stays_reconciling(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("runner loss before attach", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-runner-loss-before-attach"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    private_resources: dict = {}
    fake_dead_runner_pid = 999_999_937
    claimed = native_delegation_mod.claim_external_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        worktree_dir=workspace,
        prompt_file=prompt,
        prompt_snapshot_path=prepared["prompt_snapshot_path"],
        model=MODEL,
        scope="analysis",
        read_only=True,
        running_log_path=prepared["running_log_path"],
        trace_path=prepared["trace_path"],
        output_path=output,
        pid=fake_dead_runner_pid,
        pid_start_time="forced-dead-runner",
        started_by_pid=os.getpid(),
        idempotency_key=f"{task_id}:claim",
        mst_session_id=SESSION_ID,
        _private_resources=private_resources,
    )
    try:
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        reconciled = native_delegation_mod.reconcile_external_cancel_after_runner_loss(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            idempotency_key=f"{task_id}:reconcile",
        )
    finally:
        output_fd = private_resources.get("output_fd")
        if isinstance(output_fd, int):
            os.close(output_fd)

    assert reconciled["phase"] == "reconciling"
    assert reconciled["status"] == "reconciling"
    assert reconciled["completion_signal"] is None
    assert reconciled.get("terminated_at") is None
    assert reconciled["provider_reap_evidence"]["status"] == "runner_lost_before_provider_attach"
    assert reconciled["provider_reap_evidence"]["group_observed_gone"] is False
    action = _assert_external_reconciliation_action(
        reconciled,
        next_operation="reconcile_external_provider_group",
    )
    assert native_delegation_mod.get_reconciliation_action(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=claimed["attempt_id"],
    ) == action
    action_cli = _run_mst(
        workspace,
        "delegation",
        "reconcile-action",
        "--task-id",
        task_id,
        "--attempt-id",
        claimed["attempt_id"],
    )
    assert action_cli.returncode == 0, action_cli.stderr
    assert json.loads(action_cli.stdout) == action
    listed = _run_mst(workspace, "dispatch", "list", "--format", "json")
    assert listed.returncode == 0, listed.stderr
    row = next(item for item in json.loads(listed.stdout) if item["task_id"] == task_id)
    assert row["reconciliation_required"] is True
    assert row["reconciliation_action"] == action
    consumer = project_lifecycle_artifact_consumer_summary(reconciled)
    assert consumer["consumer_status"] == "non_success"
    assert consumer["gaps"] == []
    assert consumer["reconciliation_action"] == action
    assert consumer["current_attempt"]["reconciliation_action"] == action
    assert "output_publish" not in reconciled


def test_external_cancel_reconciliation_terminalizes_with_resolved_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("settle external reconciliation", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-external-reconcile-terminal"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    private_resources: dict = {}
    fake_dead_runner_pid = 999_999_931
    fake_gone_provider_pid = 999_999_929
    claimed = native_delegation_mod.claim_external_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        worktree_dir=workspace,
        prompt_file=prompt,
        prompt_snapshot_path=prepared["prompt_snapshot_path"],
        model=MODEL,
        scope="analysis",
        read_only=True,
        running_log_path=prepared["running_log_path"],
        trace_path=prepared["trace_path"],
        output_path=output,
        pid=fake_dead_runner_pid,
        pid_start_time="forced-dead-runner",
        started_by_pid=os.getpid(),
        idempotency_key=f"{task_id}:claim",
        mst_session_id=SESSION_ID,
        _private_resources=private_resources,
    )
    try:
        native_delegation_mod.attach_external_provider_process(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            claim_owner_pid=fake_dead_runner_pid,
            provider_pid=fake_gone_provider_pid,
            provider_pgid=fake_gone_provider_pid,
            provider_pid_start_time="forced-gone-provider",
            prompt_execution_hash=prepared["prompt_hash"],
            idempotency_key=f"{task_id}:attach-provider",
        )
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        reconciling = native_delegation_mod.record_external_reap_unconfirmed(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            cancellation_requested=True,
            provider_reap_evidence={
                "status": "termination_unconfirmed",
                "term_sent": True,
                "kill_sent": True,
                "group_observed_gone": False,
                "wrapper_crashed": True,
            },
            idempotency_key=f"{task_id}:unconfirmed",
        )
        pending = _assert_external_reconciliation_action(
            reconciling,
            next_operation="reconcile_external_provider_group",
        )
        monkeypatch.setattr(native_delegation_mod, "_pid_alive", lambda _pid: False)
        monkeypatch.setattr(
            native_delegation_mod,
            "_process_group_alive",
            lambda _pgid: False,
        )
        terminal = native_delegation_mod.reconcile_external_cancel_after_runner_loss(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            idempotency_key=f"{task_id}:reconcile",
        )
    finally:
        output_fd = private_resources.get("output_fd")
        if isinstance(output_fd, int):
            os.close(output_fd)

    assert terminal["phase"] == "terminated"
    assert terminal["status"] == "cancelled"
    assert terminal["provider_state"] == "cancelled"
    assert terminal["provider_reconciliation_required"] is False
    assert terminal["provider_reap_evidence"]["group_observed_gone"] is True
    resolved = _assert_resolved_reconciliation_action(terminal, pending)
    assert resolved["result"]["provider_state"] == "cancelled"
    assert resolved["result"]["group_observed_gone"] is True

    with pytest.raises(
        native_delegation_mod.LifecycleConflict,
        match="no pending provider reconciliation action",
    ):
        native_delegation_mod.get_reconciliation_action(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
        )
    action_cli = _run_mst(
        workspace,
        "delegation",
        "reconcile-action",
        "--task-id",
        task_id,
        "--attempt-id",
        str(claimed["attempt_id"]),
    )
    assert action_cli.returncode != 0
    assert "no pending provider reconciliation action" in (
        action_cli.stdout + action_cli.stderr
    )

    listed = _run_mst(workspace, "dispatch", "list", "--format", "json")
    assert listed.returncode == 0, listed.stderr
    row = next(item for item in json.loads(listed.stdout) if item["task_id"] == task_id)
    assert row["phase"] == "terminated"
    assert row["status"] == "cancelled"
    assert row["reconciliation_required"] is False
    assert row["reconciliation_invariant_gap"] is False
    assert row["reconciliation_action"] == resolved

    consumer = project_lifecycle_artifact_consumer_summary(terminal)
    assert consumer["consumer_status"] == "non_success"
    assert consumer["gaps"] == []
    assert consumer["provider_reconciliation_required"] is False
    assert consumer["reconciliation_action"] == resolved
    history = [
        json.loads(line)
        for line in (base / "history" / "native-delegation.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert history[-1]["phase"] == "terminated"
    assert history[-1]["reconciliation_action"] == resolved


def test_runner_loss_revalidates_terminal_state_before_provider_group_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("runner loss authority race", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-runner-loss-terminal-race"
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    private_resources: dict = {}
    owner_pid = 999_999_919
    provider_pid = 999_999_917
    claimed = native_delegation_mod.claim_external_attempt(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        worktree_dir=workspace,
        prompt_file=prompt,
        prompt_snapshot_path=prepared["prompt_snapshot_path"],
        model=MODEL,
        scope="analysis",
        read_only=True,
        running_log_path=prepared["running_log_path"],
        trace_path=prepared["trace_path"],
        output_path=output,
        pid=owner_pid,
        pid_start_time="dead-owner",
        started_by_pid=os.getpid(),
        idempotency_key=f"{task_id}:claim",
        mst_session_id=SESSION_ID,
        _private_resources=private_resources,
    )
    state_path = base / "run" / f"{task_id}.json"
    try:
        native_delegation_mod.attach_external_provider_process(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            claim_owner_pid=owner_pid,
            provider_pid=provider_pid,
            provider_pgid=provider_pid,
            provider_pid_start_time="provider-start",
            prompt_execution_hash=prepared["prompt_hash"],
            idempotency_key=f"{task_id}:attach",
        )
        request_external_cancel(
            base_dir=base,
            task_id=task_id,
            expected_attempt_id=claimed["attempt_id"],
            signal_name="TERM",
            idempotency_key=f"{task_id}:cancel",
        )
        monkeypatch.setattr(native_delegation_mod, "_pid_alive", lambda _pid: False)
        monkeypatch.setattr(
            native_delegation_mod,
            "_process_group_alive",
            lambda _pgid: True,
        )
        terminate_called = False

        def terminalize_during_identity_check(**_kwargs):
            _update_state_file(state_path, status="completed")
            return True, "provider_identity_match"

        def forbidden_terminate(**_kwargs):
            nonlocal terminate_called
            terminate_called = True
            return {"group_observed_gone": True}

        monkeypatch.setattr(
            native_delegation_mod,
            "_provider_identity_matches",
            terminalize_during_identity_check,
        )
        monkeypatch.setattr(
            native_delegation_mod,
            "_terminate_external_provider_group",
            forbidden_terminate,
        )

        with pytest.raises(
            native_delegation_mod.LifecycleConflict,
            match="terminal lifecycle attempt cannot terminate external provider group",
        ):
            native_delegation_mod.reconcile_external_cancel_after_runner_loss(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=claimed["attempt_id"],
                idempotency_key=f"{task_id}:reconcile",
            )
        assert terminate_called is False
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["phase"] == "cancel_requested"
        assert persisted["status"] == "completed"
        assert persisted.get("provider_reap_evidence") is None
    finally:
        output_fd = private_resources.get("output_fd")
        if isinstance(output_fd, int):
            os.close(output_fd)


def test_attach_failure_with_unconfirmed_group_stays_nonterminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("forced attach failure", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-attach-failure-unconfirmed"
    provider = tmp_path / "codex"
    provider.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )

    def fail_attach(**_kwargs):
        raise native_delegation_mod.LifecycleConflict("forced provider attach failure")

    monkeypatch.setenv("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "0.1")
    monkeypatch.setattr(native_delegation_mod, "attach_external_provider_process", fail_attach)
    monkeypatch.setattr(native_delegation_mod, "_process_group_alive", lambda _pgid: True)
    monkeypatch.setattr(
        native_delegation_mod,
        "_terminate_external_provider_group",
        lambda **_kwargs: {
            "status": "termination_unconfirmed",
            "term_sent": True,
            "kill_sent": True,
            "group_observed_gone": False,
        },
    )

    state = run_external_adapter(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key=f"{task_id}:run",
        binary=provider,
        model=MODEL,
        scope="analysis",
        read_only=True,
    )

    assert state["phase"] == "reconciling"
    assert state["status"] == "reconciling"
    assert state["completion_signal"] is None
    assert state.get("terminated_at") is None
    assert state["provider_reap_evidence"]["group_observed_gone"] is False
    assert state["provider_reap_evidence"]["status"] == "termination_unconfirmed"
    _assert_external_reconciliation_action(
        state,
        next_operation="reconcile_external_provider_group",
    )
    assert "output_publish" not in state


def test_signal_permission_error_returns_bounded_nonterminal_reconciliation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("bounded signal failure", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-signal-permission-error"
    provider = tmp_path / "codex"
    provider.write_text("#!/bin/sh\ncat >/dev/null\nsleep 10\n", encoding="utf-8")
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    original_killpg = os.killpg

    def deny_signal(_pgid: int, _signal: int) -> None:
        raise PermissionError("forced signal denial")

    monkeypatch.setenv("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "0.1")
    monkeypatch.setattr(native_delegation_mod.os, "killpg", deny_signal)
    state_path = base / "run" / f"{task_id}.json"
    provider_pgid = 0
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                run_external_adapter,
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=prepared["attempt_id"],
                provider="codex",
                prompt_file=prompt,
                worktree_dir=workspace,
                output_path=output,
                idempotency_key=f"{task_id}:run",
                binary=provider,
                model=MODEL,
                scope="analysis",
                read_only=True,
            )
            _wait_for(
                lambda: json.loads(state_path.read_text(encoding="utf-8")).get(
                    "provider_exec_release_status"
                )
                == "released"
            )
            request_external_cancel(
                base_dir=base,
                task_id=task_id,
                expected_attempt_id=prepared["attempt_id"],
                signal_name="TERM",
                idempotency_key=f"{task_id}:cancel",
            )
            state = future.result(timeout=5)
            provider_pgid = int(state["provider_pgid"])
    finally:
        monkeypatch.setattr(native_delegation_mod.os, "killpg", original_killpg)
        if provider_pgid > 0:
            try:
                original_killpg(provider_pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert state["phase"] == "cancel_requested"
    assert state["status"] == "cancel_requested"
    assert state["completion_signal"] is None
    assert state["provider_reap_evidence"]["group_observed_gone"] is False
    assert "forced signal denial" in str(state["provider_reap_evidence"]["term_error"])
    assert "forced signal denial" in str(state["provider_reap_evidence"]["kill_error"])
    _assert_external_reconciliation_action(
        state,
        next_operation="reconcile_external_provider_group",
    )
    assert "output_publish" not in state


def test_missing_provider_start_identity_reaps_group_before_terminal_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("missing provider start identity", encoding="utf-8")
    output = workspace / "result.md"
    late_side_effect = workspace / "late-side-effect"
    task_id = "REQ-939-missing-provider-start"
    provider = tmp_path / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        f"(sleep 0.8; printf late > {late_side_effect}) &\n"
        "wait\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    monkeypatch.setenv("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "0.1")
    monkeypatch.setattr(native_delegation_mod, "_external_process_start_time", lambda _pid: "")

    state = run_external_adapter(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key=f"{task_id}:run",
        binary=provider,
        model=MODEL,
        scope="analysis",
        read_only=True,
    )

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["completion_signal"] == "process_exit"
    assert state["provider_pid_start_time"] in {None, ""}
    assert state["provider_reap_evidence"]["group_observed_gone"] is True
    assert "start identity is unavailable" in state["provider_reap_evidence"]["provider_attach_error"]
    assert state["output_publish"]["status"] == "not_published_non_success"
    time.sleep(1.0)
    assert not late_side_effect.exists()


def test_central_runner_rejects_output_identity_change_before_atomic_publish(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("publish safely", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-output-identity"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "provider-started"
    release = tmp_path / "release-provider"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        f"touch {started}\n"
        f"while [ ! -f {release} ]; do sleep 0.02; done\n"
        "printf 'provider output\\n'\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = base / "run" / f"{task_id}.json"
    _wait_for(started.exists)
    _wait_for(output.exists)
    replacement = output.with_name("replacement-output")
    replacement.write_text("untrusted replacement", encoding="utf-8")
    os.replace(replacement, output)
    release.touch()
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 3, f"stdout={stdout}\nstderr={stderr}"
    assert output.read_text(encoding="utf-8") == "untrusted replacement"
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    assert terminal["phase"] == "failed"
    assert terminal["failure_domain"] == "external_output_io"
    assert terminal["output_publish"]["status"] == "failed"
    assert "identity changed" in terminal["output_publish"]["error"]


def test_fifo_swap_after_claim_fails_promptly_without_output_publish(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("reject post-claim fifo", encoding="utf-8")
    output = workspace / "result.md"
    task_id = "REQ-939-post-claim-fifo"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "provider-started"
    release = tmp_path / "release-provider"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        "cat >/dev/null\n"
        f"touch {started}\n"
        f"while [ ! -f {release} ]; do sleep 0.02; done\n"
        "printf 'provider output\n'\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for(started.exists)
    _wait_for(output.exists)
    output.unlink()
    os.mkfifo(output)
    release.touch()

    started_wait = time.monotonic()
    stdout, stderr = proc.communicate(timeout=5)
    assert time.monotonic() - started_wait < 3
    assert proc.returncode == 3, f"stdout={stdout}\nstderr={stderr}"
    assert stat.S_ISFIFO(os.stat(output, follow_symlinks=False).st_mode)
    terminal = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert terminal["phase"] == "failed"
    assert terminal["failure_domain"] == "external_output_io"
    assert terminal["output_publish"]["status"] == "failed"
    assert "regular file" in terminal["output_publish"]["error"]


def test_native_definitive_noncreation_fallback_completes_current_work_consumer(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("fallback execution", encoding="utf-8")
    running = workspace / "fallback-running.log"
    trace = workspace / "fallback-trace.ndjson"
    output = workspace / "fallback-result.md"
    task_id = "REQ-939-fallback-consumer"
    native = start_native_attempt(
        base_dir=base,
        task_id=task_id,
        idempotency_key=f"{task_id}:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=str(native["attempt_id"]),
        claimant_id="fallback-test-parent",
        idempotency_key=f"{task_id}:native-claim",
    )
    acknowledged = acknowledge_native_spawn(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=str(native["attempt_id"]),
        spawn_status="definitive_not_created",
        provider_task_id=None,
        claim_token=str(claim["claim_token"]),
        idempotency_key=f"{task_id}:ack",
    )
    fallback = request_external_fallback(
        base_dir=base,
        task_id=task_id,
        expected_attempt_id=str(acknowledged["attempt_id"]),
        idempotency_key=f"{task_id}:fallback",
    )
    command = _build_external_command(workspace, fallback)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "fallback-provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    executed = _execute_wrapper(workspace, command, bin_dir)
    assert executed.returncode == 0, executed.stderr
    assert spawn_log.read_text(encoding="utf-8").splitlines() == ["spawn"]

    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "done"
    assert persisted["status"] == "fallback_completed"
    assert persisted["completion_signal"] == "process_exit"
    assert persisted["exit_code"] == 0
    assert persisted["fallback_from"] == native["attempt_id"]
    attempts = {item["attempt_id"]: item for item in persisted["attempts"]}
    assert attempts[native["attempt_id"]]["fallback_to"] == fallback["attempt_id"]
    assert attempts[fallback["attempt_id"]]["fallback_from"] == native["attempt_id"]
    assert "external provider result" in output.read_text(encoding="utf-8")
    assert "external provider result" in running.read_text(encoding="utf-8")

    consumer = project_lifecycle_artifact_consumer_summary(persisted)
    assert consumer["consumer_status"] == "success"
    assert consumer["lifecycle_status"] == "fallback_completed"
    assert consumer["completion_signal"] == "process_exit"
    assert consumer["exit_code"] == 0
    assert consumer["artifacts"]["output"]["path"] == str(output.resolve())


def test_documented_fresh_authorize_then_build_executes_bound_external_lane(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("documented external lane", encoding="utf-8")
    running = workspace / "documented-running.log"
    trace = workspace / "documented-trace.ndjson"
    output = workspace / "documented-result.md"
    task_id = "REQ-939-documented-authorize"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "documented-provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "MST_HOST": "headless",
        "MST_SESSION_ID": SESSION_ID,
    }
    authorized = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "dispatch",
            "authorize-external",
            "--provider",
            "codex",
            "--task-id",
            task_id,
            "--prompt-file",
            str(prompt),
            "--worktree-dir",
            str(workspace),
            "--running-log-path",
            str(running),
            "--trace-path",
            str(trace),
            "--output-path",
            str(output),
            "--model",
            MODEL,
            "--scope",
            "analysis",
            "--idempotency-key",
            f"{task_id}:authorize",
            "--read-only",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert authorized.returncode == 0, authorized.stderr
    state = json.loads(authorized.stdout)
    assert state["running_log_path"] == str(running.resolve())
    assert state["trace_path"] == str(trace.resolve())
    assert state["output_path"] == str(output.resolve())
    assert state["model"] == MODEL

    command = _build_external_command(workspace, state)
    executed = _execute_wrapper(workspace, command, bin_dir)
    assert executed.returncode == 0, executed.stderr
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["completion_signal"] == "process_exit"
    assert persisted["exit_code"] == 0
    assert spawn_log.read_text(encoding="utf-8").splitlines() == ["spawn"]


def test_prompt_mutation_after_claim_cannot_change_provider_stdin(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("AUTHORIZED_PROMPT", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-prompt-snapshot"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "provider-started"
    received = tmp_path / "provider-stdin.txt"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        f"touch {started}\n"
        "sleep 0.3\n"
        f"cat > {received}\n"
        "printf 'snapshot-result\\n'\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)

    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
            "MST_DISPATCH_HEARTBEAT_INTERVAL": "10",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for(started.exists)
    persisted_running = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted_running["external_claim_id"]
    prompt.write_text("MUTATED_AFTER_ATOMIC_CLAIM", encoding="utf-8")
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    assert received.read_text(encoding="utf-8") == "AUTHORIZED_PROMPT"
    terminal = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert terminal["prompt_snapshot_hash"] == state["prompt_hash"]
    assert terminal["status"] == "completed"


def test_unwritable_stale_output_blocks_before_provider_spawn(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("blocked stale output", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    output.write_text("STALE_PREEXISTING", encoding="utf-8")
    output.chmod(0o400)
    task_id = "REQ-939-stale-output"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    spawn_log = tmp_path / "provider-spawns.log"
    _write_provider_stub(bin_dir, spawn_log)
    executed = _execute_wrapper(workspace, command, bin_dir)
    output.chmod(0o600)

    assert executed.returncode == 2
    assert not spawn_log.exists()
    assert output.read_text(encoding="utf-8") == "STALE_PREEXISTING"
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "planned"
    assert not persisted.get("external_claim_id")


def test_empty_provider_output_is_lifecycle_failure_and_nonzero_wrapper(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("empty result", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-empty-output"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    provider = bin_dir / "codex"
    provider.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n", encoding="utf-8")
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    executed = _execute_wrapper(workspace, command, bin_dir)

    assert executed.returncode == 3
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "failed"
    assert persisted["status"] == "empty_result"
    assert persisted["exit_code"] == 0
    assert persisted["output_freshness"]["status"] == "missing_empty_or_unchanged"


def test_external_cli_failure_projects_structured_stderr_as_non_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("external failure consumer", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-external-failure-consumer"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\ncat >/dev/null\nprintf 'provider failed\\n' >&2\nexit 3\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)

    executed = _execute_wrapper(workspace, command, bin_dir)

    assert executed.returncode == 3
    persisted = json.loads((base / "run" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert persisted["phase"] == "failed"
    assert persisted["status"] == "failed"
    assert persisted["exit_code"] == 3
    assert persisted.get("stderr_log_path") is None
    assert persisted["stderr_evidence"]["byte_count"] > 0
    consumer = project_lifecycle_artifact_consumer_summary(persisted)
    assert consumer["consumer_status"] == "non_success"
    assert consumer["gaps"] == []
    assert consumer["artifacts"]["stderr_log"]["path"] == ""
    assert consumer["artifacts"]["stderr_evidence"]["sha256"] == persisted["stderr_evidence"]["sha256"]
    assert running.read_text(encoding="utf-8").endswith("provider failed\n")
    assert str(running) in consumer["failure"]["evidence_paths"]
    (base / "run" / f"{task_id}.json").unlink()
    history_consumer = next(
        item
        for item in project_lifecycle_artifacts_for_session(
            base,
            SESSION_ID,
            terminal_only=True,
        )
        if item["task_id"] == task_id
    )
    assert history_consumer["consumer_status"] == "non_success"
    assert history_consumer["gaps"] == []
    assert history_consumer["artifacts"]["stderr_evidence"]["byte_count"] > 0


def test_dispatch_kill_forwards_to_provider_group_before_terminal_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("cancel provider group", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-provider-group-cancel"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "provider-started"
    forbidden = tmp_path / "late-side-effect"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        "trap '' TERM INT\n"
        f"touch {started}\n"
        f"(sleep 1; touch {forbidden}) &\n"
        "wait\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "MST_SESSION_ID": SESSION_ID,
        "MST_DISPATCH_HEARTBEAT_INTERVAL": "10",
        "MST_EXTERNAL_CANCEL_GRACE_SECONDS": "0.1",
    }
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = base / "run" / f"{task_id}.json"
    _wait_for(started.exists)
    _wait_for(lambda: json.loads(state_path.read_text(encoding="utf-8")).get("phase") == "running")
    killed = _run_mst(workspace, "dispatch", "kill", "--task-id", task_id, "--signal", "TERM")
    assert killed.returncode == 0, killed.stderr
    kill_result = json.loads(killed.stdout)
    assert kill_result["cancel_requested"] == 1
    assert kill_result["blocked"] == 0
    stdout, stderr = proc.communicate(timeout=10)
    assert proc.returncode == 143, f"stdout={stdout}\nstderr={stderr}"
    time.sleep(1.2)
    assert not forbidden.exists()
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    assert terminal["phase"] == "terminated"
    assert terminal["status"] == "cancelled"
    assert terminal["completion_signal"] == "process_cancelled"
    assert terminal["provider_pgid"] == terminal["provider_pid"]
    assert terminal["provider_reap_evidence"]["group_observed_gone"] is True
    assert terminal["provider_reap_evidence"]["kill_sent"] is True


def test_dispatch_kill_recovers_provider_group_after_central_runner_crash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MST_EXTERNAL_CANCEL_GRACE_SECONDS", "0.1")
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = workspace / "prompt.md"
    prompt.write_text("recover orphaned provider", encoding="utf-8")
    running = workspace / "running.log"
    trace = workspace / "trace.ndjson"
    output = workspace / "result.md"
    task_id = "REQ-939-runner-crash"
    state = start_external_attempt(
        base_dir=base,
        task_id=task_id,
        provider="codex",
        worktree_dir=workspace,
        idempotency_key=f"{task_id}:authorize",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        running_log_path=running,
        trace_path=trace,
        output_path=output,
        model=MODEL,
        mst_session_id=SESSION_ID,
    )
    command = _build_external_command(workspace, state)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "provider-started"
    forbidden = tmp_path / "late-side-effect"
    provider = bin_dir / "codex"
    provider.write_text(
        "#!/bin/sh\n"
        "trap '' TERM INT\n"
        "cat >/dev/null\n"
        f"touch {started}\n"
        f"(sleep 0.6; touch {forbidden}) &\n"
        "wait\n",
        encoding="utf-8",
    )
    provider.chmod(provider.stat().st_mode | stat.S_IEXEC)
    proc = subprocess.Popen(
        ["bash", "-c", command],
        cwd=workspace,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = base / "run" / f"{task_id}.json"
    _wait_for(started.exists)
    _wait_for(
        lambda: bool(
            json.loads(state_path.read_text(encoding="utf-8")).get("provider_pgid")
        )
    )
    running_state = json.loads(state_path.read_text(encoding="utf-8"))
    os.kill(int(running_state["pid"]), signal.SIGKILL)
    proc.communicate(timeout=10)

    killed = _run_mst(workspace, "dispatch", "kill", "--task-id", task_id, "--signal", "TERM")
    assert killed.returncode == 0, killed.stderr
    kill_result = json.loads(killed.stdout)
    assert kill_result["cancel_requested"] == 1
    assert kill_result["terminated"] == 1
    time.sleep(0.8)
    assert not forbidden.exists()
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    assert terminal["phase"] == "terminated"
    assert terminal["status"] == "cancelled"
    assert terminal["provider_reap_evidence"]["wrapper_crashed"] is True
    assert terminal["provider_reap_evidence"]["group_observed_gone"] is True
    assert terminal["provider_reap_evidence"]["reaped_by_supervisor"] is False
