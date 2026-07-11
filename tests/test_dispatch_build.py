from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.mst_cmds.native_delegation import (
    acknowledge_native_spawn,
    claim_native_spawn,
    request_external_fallback,
    start_external_attempt,
    start_native_attempt,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "MST-REQ-000-20260519T000000000Z-test0000"
DIRECT_CLI_TOKENS = ("claude -p",)
CLAUDE_PRINT_MODE_TOKEN = DIRECT_CLI_TOKENS[0]


def _persist_external_authorization(
    workspace: Path,
    *,
    task_id: str,
    provider: str,
    prompt_file: Path,
    worktree_dir: Path,
    running_log_path: Path,
    model: str | None,
    write_capable: bool = False,
) -> dict:
    return start_external_attempt(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        provider=provider,
        worktree_dir=worktree_dir,
        idempotency_key=f"{task_id}:test-external-authorization",
        route_reason="test_headless_external",
        scope="implementation" if write_capable else "analysis",
        read_only=not write_capable,
        prompt_file=prompt_file,
        running_log_path=running_log_path,
        model=model,
        mst_session_id=SESSION_ID,
    )


def _run_mst(
    workspace: Path,
    *args: str,
    env: dict[str, str] | None = None,
    authorize_external: bool = True,
) -> subprocess.CompletedProcess:
    command_args = list(args)
    if authorize_external and command_args[:2] == ["dispatch", "build"]:
        provider = command_args[command_args.index("--provider") + 1]
        if provider in {"codex", "claude"} and "--expected-attempt-id" not in command_args:
            task_id = command_args[command_args.index("--task-id") + 1]
            prompt_file = Path(command_args[command_args.index("--prompt-file") + 1])
            worktree_dir = Path(command_args[command_args.index("--worktree-dir") + 1])
            running_log_path = Path(command_args[command_args.index("--log-file") + 1])
            model = (
                command_args[command_args.index("--model") + 1]
                if "--model" in command_args
                else None
            )
            write_capable = "--require-worktree" in command_args
            state = _persist_external_authorization(
                workspace,
                task_id=task_id,
                provider=provider,
                prompt_file=prompt_file,
                worktree_dir=worktree_dir,
                running_log_path=running_log_path,
                model=model,
                write_capable=write_capable,
            )
            command_args.extend(["--expected-attempt-id", str(state["attempt_id"])])
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *command_args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _write_stub_cli(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _init_workspace_repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "tester@example.com")
    _git(workspace, "config", "user.name", "Test User")
    _git(workspace, "commit", "--allow-empty", "-m", "initial commit")
    _git(workspace, "branch", "-M", "main")
    return workspace


def test_dispatch_build_codex_includes_required_fragments(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-codex",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()

    assert "dispatch run-external" in command
    assert "codex exec" not in command
    assert "$(cat" not in command
    assert ".snapshot.md" not in command
    assert str(prompt_file) not in command
    assert str(log_file) not in command
    assert "dispatch claim-external" not in command
    assert "dispatch register" not in command
    assert "dispatch heartbeat-external" not in command
    assert "dispatch finalize-external" not in command
    assert "mst_forward_provider" not in command
    assert "PROVIDER_PID=$!" not in command
    assert "export MST_SESSION_ID" in command
    assert "MST_CONTEXT_JSON" in command
    assert "session resolve" not in command


def test_dispatch_build_claude_uses_safe_external_fallback_wrapper(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt-claude.md"
    prompt_file.write_text("hello claude", encoding="utf-8")
    log_file = workspace / "claude.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "claude",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-claude",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "sonnet-test",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "dispatch run-external" in command
    assert CLAUDE_PRINT_MODE_TOKEN not in command
    assert "--permission-mode" not in command
    assert "dangerously-skip-permissions" not in command
    assert "dispatch claim-external" not in command
    assert "dispatch register" not in command
    assert "--provider claude" not in command
    assert "dispatch heartbeat-external" not in command
    assert "dispatch finalize-external" not in command
    assert "$(cat" not in command
    assert ".snapshot.md" not in command


def test_dispatch_build_claude_executes_provider_stub_with_lifecycle_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "claude.argv"
    _write_stub_cli(
        bin_dir,
        "claude",
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {argv_file}\n"
        "printf 'claude external result\\n'\n",
    )
    prompt_file = workspace / "prompt-claude.md"
    prompt_file.write_text("hello claude", encoding="utf-8")
    log_file = workspace / "claude.log"
    task_id = "task-claude-exec"

    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "claude",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "sonnet-test",
    )
    assert built.returncode == 0, built.stderr

    executed = subprocess.run(
        ["bash", "-c", built.stdout.strip()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
    )

    assert executed.returncode == 0, executed.stderr
    argv = argv_file.read_text(encoding="utf-8")
    assert "plan" in argv
    assert "hello claude" not in argv
    assert "dangerously-skip-permissions" not in argv
    state = json.loads(
        (workspace / ".gran-maestro" / "run" / f"{task_id}.json").read_text(encoding="utf-8")
    )
    assert state["provider"] == "claude"
    assert state["exit_code"] == 0
    assert state["status"] == "completed"
    assert "claude external result" in log_file.read_text(encoding="utf-8")


def test_dispatch_build_rejects_route_bypass_without_persisted_authorization(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("same-host route must not be bypassed", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-route-bypass",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(workspace / "route-bypass.log"),
        "--model",
        "gpt-test-codex",
        "--expected-attempt-id",
        "missing-attempt",
        authorize_external=False,
    )

    assert proc.returncode == 2
    assert "persisted external authorization not found" in proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("mismatch", ["provider", "worktree", "prompt"])
def test_dispatch_build_rejects_persisted_authorization_binding_mismatch(tmp_path, mismatch):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("authorized prompt", encoding="utf-8")
    task_id = f"task-{mismatch}-mismatch"
    state = _persist_external_authorization(
        workspace,
        task_id=task_id,
        provider="codex",
        prompt_file=prompt_file,
        worktree_dir=workspace,
        running_log_path=workspace / f"{mismatch}.log",
        model="test-model",
    )

    provider = "claude" if mismatch == "provider" else "codex"
    worktree_dir = workspace
    if mismatch == "worktree":
        worktree_dir = workspace / "other-worktree"
        worktree_dir.mkdir()
    if mismatch == "prompt":
        prompt_file.write_text("mutated after authorization", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        provider,
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(worktree_dir),
        "--log-file",
        str(workspace / f"{mismatch}.log"),
        "--model",
        "test-model",
        "--expected-attempt-id",
        str(state["attempt_id"]),
        authorize_external=False,
    )

    assert proc.returncode == 2
    assert f"authorization {mismatch}" in proc.stderr
    assert "mismatch" in proc.stderr
    assert proc.stdout == ""


def test_dispatch_build_rejects_native_current_attempt(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("native task", encoding="utf-8")
    task_id = "task-native-current"
    state = start_native_attempt(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        idempotency_key=f"{task_id}:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt_file,
    )

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(workspace / "native.log"),
        "--expected-attempt-id",
        str(state["attempt_id"]),
        authorize_external=False,
    )

    assert proc.returncode == 2
    assert "native current attempt" in proc.stderr


def test_dispatch_build_rejects_reconciling_attempt(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("reconciling task", encoding="utf-8")
    task_id = "task-reconciling"
    state = start_native_attempt(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        idempotency_key=f"{task_id}:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        capability_status="unknown",
        prompt_file=prompt_file,
    )

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(workspace / "reconciling.log"),
        "--expected-attempt-id",
        str(state["attempt_id"]),
        authorize_external=False,
    )

    assert proc.returncode == 2
    assert "reconciling; external execution is forbidden" in proc.stderr


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_dispatch_build_protected_provider_prompt_is_process_list_safe(tmp_path, provider):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / f"{provider}.argv"
    stdin_file = tmp_path / f"{provider}.stdin"
    ps_file = tmp_path / f"{provider}.ps"
    _write_stub_cli(
        bin_dir,
        provider,
        "#!/bin/sh\n"
        f"/bin/ps -o command= -p $$ > {ps_file}\n"
        f"printf '%s\\n' \"$@\" > {argv_file}\n"
        f"cat > {stdin_file}\n"
        f"printf '{provider} result\\n'\n",
    )
    secret = f"PROCESS_LIST_SECRET_{provider.upper()}_73f2"
    prompt_file = workspace / f"{provider}-prompt.md"
    prompt_file.write_text(secret, encoding="utf-8")
    task_id = f"task-{provider}-process-list"

    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        provider,
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(workspace / f"{provider}.log"),
        "--model",
        "safe-model",
    )
    assert built.returncode == 0, built.stderr
    command = built.stdout.strip()
    assert secret not in command
    assert "$(cat" not in command

    executed = subprocess.run(
        ["bash", "-c", command],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
    )

    assert executed.returncode == 0, executed.stderr
    assert stdin_file.read_text(encoding="utf-8") == secret
    assert secret not in argv_file.read_text(encoding="utf-8")
    assert secret not in ps_file.read_text(encoding="utf-8")


@pytest.mark.parametrize(("host", "provider"), [("headless", "codex"), ("codex", "claude")])
def test_dispatch_authorize_external_supports_headless_and_cross_provider(tmp_path, host, provider):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(bin_dir, provider, "#!/bin/sh\nexit 0\n")
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("explicit external lane", encoding="utf-8")
    task_id = f"task-{host}-{provider}-authorized"
    running_log = workspace / "authorized.log"
    trace_path = workspace / "authorized-trace.ndjson"
    output_path = workspace / "authorized-result.md"
    env = {
        **os.environ,
        "MST_HOST": host,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    authorized = _run_mst(
        workspace,
        "dispatch",
        "authorize-external",
        "--provider",
        provider,
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--running-log-path",
        str(running_log),
        "--trace-path",
        str(trace_path),
        "--output-path",
        str(output_path),
        "--model",
        "authorized-model",
        "--idempotency-key",
        f"{task_id}:authorize",
        "--scope",
        "analysis",
        "--read-only",
        env=env,
    )

    assert authorized.returncode == 0, authorized.stderr
    state = json.loads(authorized.stdout)
    assert state["execution_transport"] == "external"
    assert state["route_decision"]["route"] == "external"
    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        provider,
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(running_log),
        "--model",
        "authorized-model",
        "--expected-attempt-id",
        str(state["attempt_id"]),
        authorize_external=False,
        env=env,
    )
    assert built.returncode == 0, built.stderr


def test_dispatch_build_legacy_headless_surface_auto_authorizes_atomic_claim(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(bin_dir, "codex", "#!/bin/sh\ncat >/dev/null\nprintf 'ok\\n'\n")
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("legacy compatibility lane", encoding="utf-8")
    log_file = workspace / "legacy.log"
    task_id = "task-legacy-auto-authorized"
    env = {
        **os.environ,
        "MST_HOST": "headless",
        "MST_SESSION_ID": SESSION_ID,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    built = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "legacy-model",
        authorize_external=False,
        env=env,
    )

    assert built.returncode == 0, built.stderr
    assert "dispatch run-external" in built.stdout
    assert "dispatch claim-external" not in built.stdout
    assert "dispatch register" not in built.stdout
    persisted = json.loads(
        (workspace / ".gran-maestro" / "run" / f"{task_id}.json").read_text(encoding="utf-8")
    )
    assert persisted["phase"] == "planned"
    assert persisted["execution_transport"] == "external"
    assert persisted["mst_session_id"] == SESSION_ID

    executed = subprocess.run(
        ["bash", "-c", built.stdout.strip()],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr
    terminal = json.loads(
        (workspace / ".gran-maestro" / "run" / f"{task_id}.json").read_text(encoding="utf-8")
    )
    assert terminal["phase"] == "done"
    assert terminal["completion_signal"] == "process_exit"


def test_dispatch_authorize_external_rejects_same_host_native_route(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(bin_dir, "codex", "#!/bin/sh\nexit 0\n")
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("must stay native", encoding="utf-8")
    task_id = "task-same-host-route"

    proc = _run_mst(
        workspace,
        "dispatch",
        "authorize-external",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--idempotency-key",
        f"{task_id}:authorize",
        "--scope",
        "analysis",
        "--capability-status",
        "available",
        "--read-only",
        env={
            **os.environ,
            "MST_HOST": "codex",
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        },
    )

    assert proc.returncode == 2
    assert "central delegation route does not authorize external dispatch" in proc.stderr
    assert not (workspace / ".gran-maestro" / "run" / f"{task_id}.json").exists()


def test_dispatch_build_accepts_linked_fallback_attempt_and_preserves_lineage(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("fallback prompt", encoding="utf-8")
    task_id = "task-definitive-fallback"
    running_log = workspace / "fallback.log"
    trace_path = workspace / "fallback-trace.ndjson"
    output_path = workspace / "fallback-result.md"
    native = start_native_attempt(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        idempotency_key=f"{task_id}:start",
        host="codex",
        provider="codex",
        worktree_dir=workspace,
        scope="analysis",
        read_only=True,
        prompt_file=prompt_file,
        running_log_path=running_log,
        trace_path=trace_path,
        output_path=output_path,
        model="fallback-model",
        mst_session_id=SESSION_ID,
    )
    acknowledged = acknowledge_native_spawn(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        expected_attempt_id=str(native["attempt_id"]),
        spawn_status="definitive_not_created",
        provider_task_id=None,
        claim_token=claim_native_spawn(
            base_dir=workspace / ".gran-maestro",
            task_id=task_id,
            expected_attempt_id=str(native["attempt_id"]),
            claimant_id="dispatch-fallback-parent",
            idempotency_key=f"{task_id}:claim",
        )["claim_token"],
        idempotency_key=f"{task_id}:ack",
    )
    fallback = request_external_fallback(
        base_dir=workspace / ".gran-maestro",
        task_id=task_id,
        expected_attempt_id=str(acknowledged["attempt_id"]),
        idempotency_key=f"{task_id}:fallback",
    )

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(running_log),
        "--model",
        "fallback-model",
        "--expected-attempt-id",
        str(fallback["attempt_id"]),
        authorize_external=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert f"--expected-attempt-id {fallback['attempt_id']}" in proc.stdout
    assert fallback["fallback_from"] == native["attempt_id"]


def test_dispatch_build_require_worktree_rejects_primary_checkout(tmp_path):
    workspace = _init_workspace_repo(tmp_path)
    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-primary-blocked",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
        "--require-worktree",
        authorize_external=False,
    )

    assert proc.returncode == 2
    assert "worktree guard failed" in proc.stderr
    assert "원본 primary checkout은 dispatch 작업 디렉토리로 사용할 수 없습니다" in proc.stderr
    assert proc.stdout == ""


def test_dispatch_build_require_worktree_allows_registered_linked_worktree(tmp_path):
    workspace = _init_workspace_repo(tmp_path)
    linked_worktree = tmp_path / "linked-worktree"
    _git(workspace, "worktree", "add", "-b", "feature/dispatch-linked", str(linked_worktree), "main")
    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-linked-ok",
        "--worktree-dir",
        str(linked_worktree),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
        "--require-worktree",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "dispatch validate-worktree" in command
    assert f"--worktree-dir {linked_worktree}" in command
    assert "dispatch run-external" in command
    assert f"-C {linked_worktree}" not in command


def test_dispatch_validate_worktree_rejects_primary_checkout(tmp_path):
    workspace = _init_workspace_repo(tmp_path)

    proc = _run_mst(
        workspace,
        "dispatch",
        "validate-worktree",
        "--worktree-dir",
        str(workspace),
        "--json",
    )

    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["reason"] == "primary_checkout"


def test_dispatch_build_agy_includes_required_fragments(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-agy.md"
    prompt_file.write_text("hello agy", encoding="utf-8")
    log_file = workspace / "agy.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "agy",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-agy",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "agy-test-model",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()

    assert "agy --print" in command
    assert f"$(cat {prompt_file})" in command
    assert "--dangerously-skip-permissions" in command
    assert f"--add-dir {workspace}" in command
    agy_segment = command.split("agy --print", 1)[1].split("< /dev/null", 1)[0]
    assert "--model agy-test-model" not in agy_segment
    assert "gemini" + " -p" not in command
    assert "--approval-mode" not in command
    assert "--sandbox=false" not in command
    assert str(log_file) in command
    assert "dispatch register" in command
    assert "dispatch heartbeat --task-id task-agy --log-file" in command
    assert "dispatch heartbeat --task-id task-agy --log-file" in command and "--final" in command
    assert "MST_DISPATCH_HEARTBEAT_INTERVAL" in command
    assert "2>&1 | tee" in command
    assert "EXIT_CODE:" in command
    assert "< /dev/null" in command
    assert "export MST_SESSION_ID" in command
    assert "MST_CONTEXT_JSON" in command
    assert "session resolve" not in command


def test_dispatch_build_legacy_gemini_alias_uses_agy(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-legacy.md"
    prompt_file.write_text("hello legacy provider", encoding="utf-8")
    log_file = workspace / "legacy.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "gemini",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-legacy",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "legacy-model",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "agy --print" in command
    assert "--dangerously-skip-permissions" in command
    agy_segment = command.split("agy --print", 1)[1].split("< /dev/null", 1)[0]
    assert "--model legacy-model" not in agy_segment
    assert "PROVIDER_DEPRECATION:gemini->agy" in command


def test_dispatch_build_legacy_gemini_alias_preserves_configured_default_model(tmp_path):
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    gm.mkdir(parents=True, exist_ok=True)
    (gm / "config.resolved.json").write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "gemini": {
                            "default_tier": "premium",
                            "premium": "legacy-custom-model",
                        }
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    prompt_file = workspace / "prompt-legacy-config.md"
    prompt_file.write_text("hello legacy configured provider", encoding="utf-8")
    log_file = workspace / "legacy-config.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "gemini",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-legacy-config",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "agy --print" in command
    assert "dispatch register --task-id task-legacy-config" in command
    assert "--provider agy --model legacy-custom-model" in command
    assert "agy-default" not in command
    assert "PROVIDER_DEPRECATION:gemini->agy" in command


def test_dispatch_build_executes_monitor_heartbeat_for_prompt_output(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(
        bin_dir,
        "codex",
        "#!/bin/sh\n"
        "printf 'Do you want to continue? [y/N]\\n'\n"
        "sleep 0.3\n"
        "exit 0\n",
    )

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"
    task_id = "task-monitor"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
    )

    assert proc.returncode == 0, proc.stderr
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "MST_DISPATCH_HEARTBEAT_INTERVAL": "0.1",
        "MST_SESSION_ID": SESSION_ID,
    }
    executed = subprocess.run(
        ["bash", "-c", proc.stdout.strip()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert executed.returncode == 0, executed.stderr
    state_file = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    events = state.get("delegate_io_attention_events") or []
    assert any(event.get("signal") == "stdin_prompt_suspected" for event in events)
    assert state.get("phase") == "done"



def test_dispatch_build_claude_is_supported_only_through_safe_wrapper(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-claude.md"
    prompt_file.write_text("hello claude", encoding="utf-8")
    log_file = workspace / "claude.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "claude",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-claude",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "claude-test-model",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout
    assert "dispatch run-external" in command
    assert CLAUDE_PRINT_MODE_TOKEN not in command
    assert "--permission-mode" not in command
    assert "dangerously-skip-permissions" not in command
    assert "dispatch claim-external" not in command
    assert "dispatch register" not in command
    assert "dispatch heartbeat-external" not in command
    assert "dispatch finalize-external" not in command


def test_dispatch_build_command_propagates_session_env_when_executed(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-env",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    prefix = re.split(
        r"; MST_SESSION_ID=\"\$MST_SESSION_ID\" python3 .*? dispatch run-external ",
        command,
        maxsplit=1,
    )[0]
    check = subprocess.run(
        ["bash", "-c", prefix + '; printf "%s\\n" "$MST_SESSION_ID"'],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MST_SESSION_ID": SESSION_ID},
    )

    assert check.returncode == 0, check.stderr
    assert check.stdout.strip().splitlines()[-1] == SESSION_ID


def test_dispatch_build_emits_context_envelope_with_canonical_next_execution(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"
    session_id = "MST-AGI-040-20260519T150147980Z-6fdzl4qx"
    raw_context = json.dumps(
        {
            "mst_session_id": session_id,
            "root_mst_id": "AGI-040",
            "schema_version": 1,
        },
        separators=(",", ":"),
    )

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-json",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
        env={
            **os.environ,
            "MST_SESSION_ID": session_id,
            "MST_CONTEXT_JSON": raw_context,
        },
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)

    assert payload["mst_session_id"] == session_id
    assert payload["root_mst_id"] == "AGI-040"
    assert payload["task_id"] == "task-json"
    assert payload["created_new_session"] is False
    assert payload["prompt_summary_used_as_source"] is False
    assert payload["next_execution"]["env"]["MST_SESSION_ID"] == session_id
    assert payload["next_execution"]["context"] == {
        "mst_session_id": session_id,
        "root_mst_id": "AGI-040",
    }
    assert payload["next_execution"]["env"]["MST_CONTEXT_JSON"] == raw_context
    assert "$(cat" not in payload["command"]
    assert ".snapshot.md" not in payload["command"]
    assert "dispatch run-external" in payload["command"]
    assert "dispatch claim-external" not in payload["command"]
    assert "dispatch register" not in payload["command"]
    assert str(log_file) not in payload["command"]


def test_dispatch_build_nonzero_exit_records_failure_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(
        bin_dir,
        "codex",
        "#!/bin/sh\n"
        "echo 'codex stderr' >&2\n"
        "exit 7\n",
    )

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex.log"
    task_id = "task-failure"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
    )

    assert proc.returncode == 0, proc.stderr
    executed = subprocess.run(
        ["bash", "-c", proc.stdout.strip()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
    )

    assert executed.returncode == 7
    state_file = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    running_log = log_file.read_text(encoding="utf-8")

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["exit_code"] == 7
    assert state["completion_signal"] == "process_exit"
    assert state["failure_domain"] == "external_cli"
    assert "last_heartbeat" in state
    assert "codex stderr" in running_log
    assert state["stderr_evidence"]["byte_count"] > 0
    assert state["provider_reap_evidence"]["group_observed_gone"] is True


def test_dispatch_build_timeout_output_records_failure_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub_cli(
        bin_dir,
        "codex",
        "#!/bin/sh\n"
        "echo 'deadline exceeded while waiting'\n"
        "exit 124\n",
    )

    prompt_file = workspace / "prompt-codex.md"
    prompt_file.write_text("hello codex", encoding="utf-8")
    log_file = workspace / "codex-timeout.log"
    task_id = "task-timeout"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "codex",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gpt-test-codex",
    )

    assert proc.returncode == 0, proc.stderr
    executed = subprocess.run(
        ["bash", "-c", proc.stdout.strip()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
    )

    assert executed.returncode == 124
    state_file = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    running_log = log_file.read_text(encoding="utf-8")

    assert state["phase"] == "failed"
    assert state["status"] == "failed"
    assert state["exit_code"] == 124
    assert state["completion_signal"] == "process_timeout"
    assert state["failure_domain"] == "external_timeout"
    assert "deadline exceeded" in running_log
    assert state["provider_reap_evidence"]["group_observed_gone"] is True


@pytest.mark.parametrize(
    ("failure_kind", "stub_output", "exit_code"),
    [
        ("rate_limit", "429 rate limit exceeded\n", 1),
        ("timeout", "deadline exceeded while waiting\n", 124),
        ("empty_result", "", 0),
        ("nonzero_exit", "provider exited unexpectedly\n", 9),
    ],
)
def test_dispatch_build_gemini_execution_records_failure_evidence_and_fallback(
    tmp_path,
    failure_kind: str,
    stub_output: str,
    exit_code: int,
):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub_lines = ["#!/bin/sh"]
    if stub_output:
        stub_lines.append(f"printf '%s' {stub_output!r}")
    stub_lines.append(f"exit {exit_code}")
    _write_stub_cli(bin_dir, "agy", "\n".join(stub_lines) + "\n")

    prompt_file = workspace / "prompt-gemini.md"
    prompt_file.write_text("hello gemini", encoding="utf-8")
    log_file = workspace / f"gemini-{failure_kind}.log"
    task_id = f"task-gemini-{failure_kind}"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "gemini",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        task_id,
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gemini-test-model",
    )

    assert proc.returncode == 0, proc.stderr
    executed = subprocess.run(
        ["bash", "-c", proc.stdout.strip()],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "MST_SESSION_ID": SESSION_ID,
        },
    )

    assert executed.returncode == exit_code
    state_file = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    running_log = log_file.read_text(encoding="utf-8")

    assert state["phase"] == "done"
    assert state["exit_code"] == exit_code
    assert state["failure_kind"] == failure_kind
    assert state["fallback_condition"] == "codex_fallback_required"
    assert f"PROVIDER_FAILURE_KIND:{failure_kind}" in running_log
    assert "PROVIDER_CODEX_FALLBACK_CONDITION:codex_fallback_required" in running_log
    assert f"PROVIDER_EVIDENCE_ID:{task_id}:agy-failure" in running_log
    assert f"failure_kind={failure_kind}" in running_log
    assert "fallback=codex_fallback_required" in running_log
