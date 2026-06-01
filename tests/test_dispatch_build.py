from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "MST-REQ-000-20260519T000000000Z-test0000"


def _run_mst(
    workspace: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
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

    assert "codex exec --full-auto -m gpt-test-codex" in command
    assert f"$(cat {prompt_file})" in command
    assert f"-C {workspace}" in command
    assert str(log_file) in command
    assert "dispatch register" in command
    assert "dispatch heartbeat --task-id task-codex --log-file" in command
    assert "dispatch heartbeat --task-id task-codex --log-file" in command and "--final" in command
    assert "MST_DISPATCH_HEARTBEAT_INTERVAL" in command
    assert "2>&1 | tee" in command
    assert "EXIT_CODE:" in command
    assert "< /dev/null" in command
    assert "export MST_SESSION_ID" in command
    assert "MST_CONTEXT_JSON" in command
    assert "session resolve" not in command


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
    assert f"-C {linked_worktree}" in command


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



def test_dispatch_build_claude_not_supported(tmp_path):
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

    assert proc.returncode != 0
    assert "claude" in (proc.stderr + proc.stdout).lower()


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
    prefix = re.split(r"; MST_SESSION_ID=\"\$MST_SESSION_ID\" python3 .* dispatch register ", command, maxsplit=1)[0]
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
    assert f"$(cat {prompt_file})" in payload["command"]
    assert "dispatch register" in payload["command"]
    assert str(log_file) in payload["command"]


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

    assert state["phase"] == "done"
    assert state["exit_code"] == 7
    assert state["failure_kind"] == "nonzero_exit"
    assert state["fallback_condition"] == "none"
    assert "last_heartbeat" in state
    assert "codex stderr" in running_log
    assert "failure_kind=nonzero_exit" in running_log
    assert "EXIT_CODE:7" in running_log


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

    assert state["phase"] == "done"
    assert state["exit_code"] == 124
    assert state["failure_kind"] == "timeout"
    assert "failure_kind=timeout" in running_log


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
