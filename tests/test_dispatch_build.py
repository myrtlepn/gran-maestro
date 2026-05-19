import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SESSION_ID = "MST-REQ-000-20260519T000000000Z-test0000"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_stub_cli(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


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


def test_dispatch_build_gemini_includes_required_fragments(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    prompt_file = workspace / "prompt-gemini.md"
    prompt_file.write_text("hello gemini", encoding="utf-8")
    log_file = workspace / "gemini.log"

    proc = _run_mst(
        workspace,
        "dispatch",
        "build",
        "--provider",
        "gemini",
        "--prompt-file",
        str(prompt_file),
        "--task-id",
        "task-gemini",
        "--worktree-dir",
        str(workspace),
        "--log-file",
        str(log_file),
        "--model",
        "gemini-test-model",
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()

    assert "gemini -p" in command
    assert f"$(cat {prompt_file})" in command
    assert "--model gemini-test-model" in command
    assert str(log_file) in command
    assert "dispatch register" in command
    assert "dispatch heartbeat --task-id task-gemini --log-file" in command
    assert "dispatch heartbeat --task-id task-gemini --log-file" in command and "--final" in command
    assert "MST_DISPATCH_HEARTBEAT_INTERVAL" in command
    assert "2>&1 | tee" in command
    assert "EXIT_CODE:" in command
    assert "< /dev/null" in command
    assert "export MST_SESSION_ID" in command
    assert "MST_CONTEXT_JSON" in command
    assert "session resolve" not in command


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
