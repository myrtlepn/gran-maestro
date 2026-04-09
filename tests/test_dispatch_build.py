import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


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
    assert "dispatch heartbeat --task-id task-codex --final" in command
    assert "2>&1 | tee" in command
    assert "EXIT_CODE:" in command
    assert "< /dev/null" in command


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
    assert "dispatch heartbeat --task-id task-gemini --final" in command
    assert "2>&1 | tee" in command
    assert "EXIT_CODE:" in command
    assert "< /dev/null" in command


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
