from __future__ import annotations

import os
import json
import stat
import subprocess
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.mst_cmds import native_delegation as native_delegation_mod
from scripts.mst_cmds.native_delegation import (
    ExternalAdapterUnavailable,
    LifecycleConflict,
    acknowledge_native_spawn,
    claim_native_spawn,
    execute_delegation_bridge,
    run_external_adapter,
    start_external_attempt,
    start_native_attempt,
)


MST_SESSION_ID = "MST-REQ-939-20260712T000000000Z-session1"


class FakeBridge:
    def __init__(
        self,
        *,
        capability: str = "available",
        spawn: dict | None = None,
        attach: str = "attached",
        result: dict | None = None,
    ) -> None:
        self.capability_value = capability
        self.spawn_value = spawn or {
            "spawn_status": "created_with_task_id",
            "provider_task_id": "provider-native-1",
        }
        self.attach_value = attach
        self.result_value = result or {"completion_signal": "completed", "output": "native result"}
        self.calls: list[tuple[str, str | None]] = []
        self.spawn_requests: list[dict] = []

    def capability(self, provider: str) -> str:
        self.calls.append(("capability", provider))
        return self.capability_value

    def spawn(self, request: dict) -> dict:
        self.calls.append(("spawn", request["task_id"]))
        self.spawn_requests.append(dict(request))
        return dict(self.spawn_value)

    def attach(self, provider_task_id: str | None) -> str:
        self.calls.append(("attach", provider_task_id))
        return self.attach_value

    def poll(self, provider_task_id: str | None) -> str:
        self.calls.append(("poll", provider_task_id))
        return "terminal"

    def result(self, provider_task_id: str | None) -> dict:
        self.calls.append(("result", provider_task_id))
        return dict(self.result_value)


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("delegate this task", encoding="utf-8")
    return workspace, base, prompt


def _stub_binary(tmp_path: Path, provider: str, marker: Path) -> Path:
    binary = tmp_path / provider
    binary.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {marker}\n"
        "printf 'external result'\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary


def test_fake_native_bridge_success_records_exact_lifecycle_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "native-output.md"
    bridge = FakeBridge()
    monkeypatch.setattr(
        native_delegation_mod.reasoning_effort_mod,
        "_codex_model_catalog",
        lambda: {"gpt-5.6-sol": {"efforts": ["ultra"], "default": "low"}},
    )

    state = execute_delegation_bridge(
        base_dir=base,
        task_id="native-success",
        host="codex",
        provider="codex",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        idempotency_key="wave-1",
        external_binary=None,
        model="gpt-5.6-sol",
        reasoning_effort="ultra",
        reasoning_effort_source="explicit",
    )

    assert bridge.calls == [
        ("capability", "codex"),
        ("spawn", "native-success"),
        ("attach", "provider-native-1"),
        ("poll", "provider-native-1"),
        ("result", "provider-native-1"),
    ]
    assert state["provider_task_id"] == "provider-native-1"
    assert state["execution_transport"] == "native"
    assert state["completion_signal"] == "completed"
    assert state["exit_code"] is None
    assert state["model"] == "gpt-5.6-sol"
    assert state["reasoning_effort"] == "ultra"
    assert state["reasoning_effort_source"] == "explicit"
    assert output.read_text(encoding="utf-8") == "native result"
    request = bridge.spawn_requests[0]
    assert request["attempt_id"]
    assert request["scope"] == "analysis"
    assert request["read_only"] is True
    assert request["worktree_dir"] == str(workspace.resolve())
    assert request["idempotency_key"].endswith(":host-spawn")
    assert request["model"] == "gpt-5.6-sol"
    assert request["reasoning_effort"] == "ultra"


def test_status_terminal_bridge_issues_no_resumed_host_authority(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "terminal-bridge-output.md"
    started = start_native_attempt(
        base_dir=base,
        task_id="terminal-bridge",
        idempotency_key="terminal-bridge:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )
    claim = claim_native_spawn(
        base_dir=base,
        task_id="terminal-bridge",
        expected_attempt_id=started["attempt_id"],
        claimant_id="terminal-bridge-parent",
        idempotency_key="terminal-bridge:claim",
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="terminal-bridge",
        expected_attempt_id=started["attempt_id"],
        spawn_status="created_with_task_id",
        provider_task_id="terminal-provider-task",
        claim_token=claim["claim_token"],
        idempotency_key="terminal-bridge:ack",
    )
    state_path = base / "run" / "terminal-bridge.json"
    terminal = json.loads(state_path.read_text(encoding="utf-8"))
    terminal["status"] = "completed"
    state_path.write_text(json.dumps(terminal) + "\n", encoding="utf-8")
    before = state_path.read_bytes()
    bridge = FakeBridge()

    result = execute_delegation_bridge(
        base_dir=base,
        task_id="terminal-bridge",
        host="codex",
        provider="codex",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        idempotency_key="terminal-bridge:resume",
        external_binary=None,
    )

    assert result["phase"] == "spawned"
    assert result["status"] == "completed"
    assert bridge.calls == []
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_capability_unavailable_executes_real_external_adapter(
    tmp_path: Path, provider: str
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / f"{provider}.args"
    binary = _stub_binary(tmp_path, provider, marker)
    bridge = FakeBridge(capability="unavailable")

    state = execute_delegation_bridge(
        base_dir=base,
        task_id=f"external-{provider}",
        host=provider,
        provider=provider,
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / f"{provider}.out",
        idempotency_key="wave-external",
        external_binary=binary,
        model="test-model",
    )

    assert Counter(call for call, _ in bridge.calls) == Counter({"capability": 1})
    assert marker.is_file()
    assert state["execution_transport"] == "external"
    assert state["status"] == "completed"
    assert state["exit_code"] == 0
    assert state["fallback_from"] is None
    with pytest.raises(
        LifecycleConflict,
        match="terminal lifecycle attempt cannot run external adapter",
    ):
        run_external_adapter(
            base_dir=base,
            task_id=f"external-{provider}",
            expected_attempt_id=state["attempt_id"],
            provider=provider,
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=tmp_path / f"{provider}.out",
            idempotency_key="different-external-run",
            binary=binary,
            model="test-model",
            scope="analysis",
            read_only=True,
        )


def test_accepted_native_task_failure_never_runs_external_duplicate(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "external-marker"
    binary = _stub_binary(tmp_path, "codex", marker)
    bridge = FakeBridge(result={"completion_signal": "failed", "output": "task failed"})

    state = execute_delegation_bridge(
        base_dir=base,
        task_id="native-task-failure",
        host="codex",
        provider="codex",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "failed.out",
        idempotency_key="wave-failed",
        external_binary=binary,
    )

    assert state["status"] == "failed"
    assert state["failure_domain"] == "task"
    assert not marker.exists()


def test_attach_race_reconciles_and_does_not_run_external_duplicate(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "external-marker"
    binary = _stub_binary(tmp_path, "claude", marker)
    bridge = FakeBridge(attach="failed")
    started = start_native_attempt(
        base_dir=base,
        task_id="native-attach-race",
        idempotency_key="interrupted-start",
        host="claude",
        provider="claude",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "race.out",
    )
    acknowledge_native_spawn(
        base_dir=base,
        task_id="native-attach-race",
        expected_attempt_id=started["attempt_id"],
        spawn_status="created_with_task_id",
        provider_task_id="provider-native-1",
        claim_token=claim_native_spawn(
            base_dir=base,
            task_id="native-attach-race",
            expected_attempt_id=started["attempt_id"],
            claimant_id="interrupted-parent",
            idempotency_key="interrupted-claim",
        )["claim_token"],
        idempotency_key="interrupted-ack",
    )

    state = execute_delegation_bridge(
        base_dir=base,
        task_id="native-attach-race",
        host="claude",
        provider="claude",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "race.out",
        idempotency_key="wave-race",
        external_binary=binary,
    )

    assert state["phase"] == "reconciling"
    assert state["fallback_allowed"] is False
    assert not marker.exists()
    assert Counter(call for call, _ in bridge.calls) == Counter({"attach": 1})


def test_external_adapter_missing_binary_is_structured_block(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "missing.out"
    started = start_external_attempt(
        base_dir=base,
        task_id="missing-cli",
        provider="claude",
        worktree_dir=workspace,
        idempotency_key="external-missing:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )

    with pytest.raises(ExternalAdapterUnavailable, match="missing_cli"):
        run_external_adapter(
            base_dir=base,
            task_id="missing-cli",
            expected_attempt_id=started["attempt_id"],
            provider="claude",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key="external-missing",
            binary=tmp_path / "does-not-exist",
            scope="analysis",
            read_only=True,
        )


def test_claude_external_adapter_uses_least_privilege_worktree_mode(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "claude-safe.args"
    binary = _stub_binary(tmp_path, "claude", marker)
    output = tmp_path / "claude-safe.out"
    started = start_external_attempt(
        base_dir=base,
        task_id="claude-safe",
        provider="claude",
        worktree_dir=workspace,
        idempotency_key="claude-safe:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="sonnet",
    )

    state = run_external_adapter(
        base_dir=base,
        task_id="claude-safe",
        expected_attempt_id=started["attempt_id"],
        provider="claude",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key="claude-safe-run",
        binary=binary,
        model="sonnet",
        scope="analysis",
        read_only=True,
    )

    argv = marker.read_text(encoding="utf-8")
    assert "--permission-mode" in argv
    assert "plan" in argv
    assert "acceptEdits" not in argv
    assert "--add-dir" in argv
    assert str(workspace.resolve()) in argv
    assert "dangerously-skip-permissions" not in argv
    assert state["status"] == "completed"


def test_write_capable_external_authorization_rejects_primary_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True)
    base = repo / ".gran-maestro"
    base.mkdir()
    prompt = tmp_path / "write-prompt.md"
    prompt.write_text("edit files", encoding="utf-8")
    binary = _stub_binary(tmp_path, "codex", tmp_path / "should-not-run")

    with pytest.raises(Exception, match="primary checkout"):
        start_external_attempt(
            base_dir=base,
            task_id="external-primary",
            provider="codex",
            worktree_dir=repo,
            idempotency_key="external-primary-prepare",
            route_reason="headless_host",
            prompt_file=prompt,
            output_path=tmp_path / "primary.out",
            scope="implementation",
            read_only=False,
        )
    assert not (tmp_path / "should-not-run").exists()


def test_external_adapter_releases_lifecycle_lock_while_provider_runs(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    started = tmp_path / "started"
    release = tmp_path / "release"
    binary = tmp_path / "codex"
    binary.write_text(
        "#!/bin/sh\n"
        f"touch {started}\n"
        f"while [ ! -f {release} ]; do sleep 0.05; done\n"
        "printf done\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    result: dict = {}
    output = tmp_path / "lock.out"
    prepared = start_external_attempt(
        base_dir=base,
        task_id="external-lock",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="external-lock:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )

    def run() -> None:
        result.update(
            run_external_adapter(
                base_dir=base,
                task_id="external-lock",
                expected_attempt_id=prepared["attempt_id"],
                provider="codex",
                prompt_file=prompt,
                worktree_dir=workspace,
                output_path=output,
                idempotency_key="external-lock-run",
                binary=binary,
                scope="analysis",
                read_only=True,
            )
        )

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 5
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert started.exists()

    # A competing lifecycle command must return promptly instead of waiting
    # for the provider process to exit.
    before = time.monotonic()
    from scripts.mst_cmds.native_delegation import _task_lock

    with _task_lock(base, "external-lock"):
        pass
    assert time.monotonic() - before < 0.5

    release.touch()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result["status"] == "completed"


def test_config_external_only_bridge_never_spawns_native(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    (base / "config.resolved.json").write_text(
        json.dumps(
            {
                "delegation": {
                    "transport_policy": "external-only",
                    "native": {"enabled": False, "scope": "all"},
                }
            }
        ),
        encoding="utf-8",
    )
    marker = tmp_path / "external-only.args"
    binary = _stub_binary(tmp_path, "codex", marker)
    bridge = FakeBridge(capability="available")

    state = execute_delegation_bridge(
        base_dir=base,
        task_id="external-only",
        host="codex",
        provider="codex",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "external-only.out",
        idempotency_key="external-only-wave",
        external_binary=binary,
    )

    assert not any(call == "spawn" for call, _ in bridge.calls)
    assert state["execution_transport"] == "external"
    assert state["route_decision"]["transport_policy"] == "external-only"
    assert state["route_fingerprint"].startswith("sha256:")


def test_unknown_capability_reconciles_without_spawn_or_fallback(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    bridge = FakeBridge(capability="unknown")

    state = execute_delegation_bridge(
        base_dir=base,
        task_id="unknown-capability",
        host="claude",
        provider="claude",
        bridge=bridge,
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "unknown.out",
        idempotency_key="unknown-wave",
        external_binary=None,
    )

    assert Counter(call for call, _ in bridge.calls) == Counter({"capability": 1})
    assert state["phase"] == "reconciling"
    assert state["spawn_allowed"] is False
    assert state["fallback_allowed"] is False


def test_external_write_worktree_lease_is_atomic_across_task_ids(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True)
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feature/external-lease", str(linked), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    base = repo / ".gran-maestro"
    base.mkdir()

    def claim(task_id: str) -> str:
        try:
            start_external_attempt(
                base_dir=base,
                task_id=task_id,
                provider="codex",
                worktree_dir=linked,
                idempotency_key=f"start-{task_id}",
                route_reason="external-only",
                scope="implementation",
                read_only=False,
            )
            return "started"
        except LifecycleConflict:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ["external-race-a", "external-race-b"]))
    assert sorted(outcomes) == ["blocked", "started"]


def test_external_state_never_persists_prompt_argv_or_raw_secret_stderr(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    secret = "sk-super-secret-token-123456"
    prompt.write_text(f"use credential {secret}", encoding="utf-8")
    stdin_marker = tmp_path / "stdin.txt"
    binary = tmp_path / "codex"
    binary.write_text(
        "#!/bin/sh\n"
        f"cat > {stdin_marker}\n"
        f"printf 'TOKEN={secret} password=hunter2' >&2\n"
        "printf done\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    output = tmp_path / "secret-safe.out"
    prepared = start_external_attempt(
        base_dir=base,
        task_id="secret-safe",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="secret-safe:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )

    state = run_external_adapter(
        base_dir=base,
        task_id="secret-safe",
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key="secret-run",
        binary=binary,
        scope="analysis",
        read_only=True,
    )

    persisted = json.dumps(state, ensure_ascii=False)
    assert secret not in persisted
    assert "hunter2" not in persisted
    assert "output_fd" not in persisted
    assert "external_command" not in state
    assert state["external_command_metadata"]["prompt_transport"] == "stdin_claimed_fd"
    assert "[REDACTED]" in state["stderr_evidence"]["redacted_tail"]
    assert len(state["stderr_evidence"]["redacted_tail"]) <= 2048
    assert stdin_marker.read_text(encoding="utf-8") == prompt.read_text(encoding="utf-8")


@pytest.mark.parametrize("swap", ["provider", "worktree", "prompt"])
def test_existing_external_attempt_rejects_persisted_binding_swap(
    tmp_path: Path, swap: str
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    other_prompt = tmp_path / "other-prompt.md"
    other_prompt.write_text("different prompt", encoding="utf-8")
    output = tmp_path / "bound.out"
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    started = start_external_attempt(
        base_dir=base,
        task_id=f"external-swap-{swap}",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="bound-model",
    )
    provider = "claude" if swap == "provider" else "codex"
    run_worktree = other_workspace if swap == "worktree" else workspace
    run_prompt = other_prompt if swap == "prompt" else prompt

    with pytest.raises(LifecycleConflict, match=swap):
        run_external_adapter(
            base_dir=base,
            task_id=f"external-swap-{swap}",
            expected_attempt_id=started["attempt_id"],
            provider=provider,
            prompt_file=run_prompt,
            worktree_dir=run_worktree,
            output_path=output,
            idempotency_key="execute",
            binary=binary,
            model="bound-model",
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()


def test_existing_external_attempt_requires_expected_attempt_cas(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "bound.out"
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    start_external_attempt(
        base_dir=base,
        task_id="external-cas",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="bound-model",
    )

    with pytest.raises(LifecycleConflict, match="expected_attempt_id"):
        run_external_adapter(
            base_dir=base,
            task_id="external-cas",
            expected_attempt_id="",
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key="execute",
            binary=binary,
            model="bound-model",
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()


def test_direct_external_execution_without_persisted_attempt_never_spawns(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    with pytest.raises(LifecycleConflict, match="external lifecycle state not found"):
        run_external_adapter(
            base_dir=base,
            task_id="external-direct-blocked",
            expected_attempt_id="unpersisted-attempt",
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=tmp_path / "direct.out",
            idempotency_key="direct:run",
            binary=binary,
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()
    assert not (base / "run" / "external-direct-blocked.json").exists()


def test_external_execution_rejects_native_current_attempt_before_spawn(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    native = start_native_attempt(
        base_dir=base,
        task_id="native-external-blocked",
        idempotency_key="native:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "native.out",
    )
    with pytest.raises(LifecycleConflict, match="native or non-external"):
        run_external_adapter(
            base_dir=base,
            task_id="native-external-blocked",
            expected_attempt_id=native["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=tmp_path / "native.out",
            idempotency_key="native:external-run",
            binary=binary,
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()


def test_external_execution_rejects_reconciling_authorization_before_spawn(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    output = tmp_path / "reconciling.out"
    external = start_external_attempt(
        base_dir=base,
        task_id="external-reconciling",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="reconciling:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )
    state_path = base / "run" / "external-reconciling.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    persisted["phase"] = "reconciling"
    persisted["status"] = "reconciling"
    state_path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(LifecycleConflict, match="phase 'reconciling'"):
        run_external_adapter(
            base_dir=base,
            task_id="external-reconciling",
            expected_attempt_id=external["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key="reconciling:run",
            binary=binary,
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()


def test_external_start_inherits_session_identity_and_artifact_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    monkeypatch.setenv("MST_SESSION_ID", MST_SESSION_ID)
    state = start_external_attempt(
        base_dir=base,
        task_id="external-session",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=tmp_path / "external-session.out",
        model="bound-model",
    )

    assert state["mst_session_id"] == MST_SESSION_ID
    assert state["root_mst_id"] == "REQ-939"
    assert state["parent_session_id"] == MST_SESSION_ID
    assert Path(state["running_log_path"]).is_file()
    assert Path(state["trace_path"]).is_file()
    assert state["output_path"] == str((tmp_path / "external-session.out").resolve())


def test_existing_external_attempt_rejects_prompt_hash_swap(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "bound.out"
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    started = start_external_attempt(
        base_dir=base,
        task_id="external-prompt-hash-swap",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="bound-model",
    )
    prompt.write_text("mutated after prepare", encoding="utf-8")
    with pytest.raises(LifecycleConflict, match="prompt hash"):
        run_external_adapter(
            base_dir=base,
            task_id="external-prompt-hash-swap",
            expected_attempt_id=started["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key="execute",
            binary=binary,
            model="bound-model",
            scope="analysis",
            read_only=True,
        )
    assert not marker.exists()


@pytest.mark.parametrize("swap", ["output", "model", "scope", "read_only"])
def test_existing_external_attempt_rejects_remaining_binding_swaps(
    tmp_path: Path, swap: str
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "bound.out"
    marker = tmp_path / "must-not-run"
    binary = _stub_binary(tmp_path, "codex", marker)
    started = start_external_attempt(
        base_dir=base,
        task_id=f"external-binding-{swap}",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
        model="bound-model",
    )

    with pytest.raises(LifecycleConflict, match=swap):
        run_external_adapter(
            base_dir=base,
            task_id=f"external-binding-{swap}",
            expected_attempt_id=started["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=(tmp_path / "swapped.out") if swap == "output" else output,
            idempotency_key="execute",
            binary=binary,
            model="swapped-model" if swap == "model" else "bound-model",
            scope="review" if swap == "scope" else "analysis",
            read_only=False if swap == "read_only" else True,
        )
    assert not marker.exists()


def test_public_external_adapter_empty_output_is_terminal_failure(tmp_path: Path) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "empty-public.out"
    binary = tmp_path / "codex-empty"
    binary.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id="external-empty-public",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="empty:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )

    state = run_external_adapter(
        base_dir=base,
        task_id="external-empty-public",
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key="empty:run",
        binary=binary,
        scope="analysis",
        read_only=True,
    )

    assert state["phase"] == "failed"
    assert state["status"] == "empty_result"
    assert state["exit_code"] == 0
    assert state["external_claim_id"]


def test_public_external_adapter_spawn_crash_consumes_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, base, prompt = _workspace(tmp_path)
    output = tmp_path / "spawn-crash.out"
    binary = tmp_path / "codex-spawn-crash"
    binary.write_text("#!/bin/sh\nprintf should-not-run\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    prepared = start_external_attempt(
        base_dir=base,
        task_id="external-spawn-crash",
        provider="codex",
        worktree_dir=workspace,
        idempotency_key="spawn-crash:prepare",
        route_reason="headless_host",
        scope="analysis",
        read_only=True,
        prompt_file=prompt,
        output_path=output,
    )

    def fail_popen(*_args, **_kwargs):
        raise OSError("synthetic crash before provider creation")

    monkeypatch.setattr(native_delegation_mod.subprocess, "Popen", fail_popen)
    state = run_external_adapter(
        base_dir=base,
        task_id="external-spawn-crash",
        expected_attempt_id=prepared["attempt_id"],
        provider="codex",
        prompt_file=prompt,
        worktree_dir=workspace,
        output_path=output,
        idempotency_key="spawn-crash:run",
        binary=binary,
        scope="analysis",
        read_only=True,
    )

    assert state["phase"] == "failed"
    assert state["external_claim_id"]
    assert state["exit_code"] == 127
    with pytest.raises(
        LifecycleConflict,
        match="terminal lifecycle attempt cannot run external adapter",
    ):
        run_external_adapter(
            base_dir=base,
            task_id="external-spawn-crash",
            expected_attempt_id=prepared["attempt_id"],
            provider="codex",
            prompt_file=prompt,
            worktree_dir=workspace,
            output_path=output,
            idempotency_key="spawn-crash:second-run",
            binary=binary,
            scope="analysis",
            read_only=True,
        )
