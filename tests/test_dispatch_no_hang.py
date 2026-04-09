import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _run_mst(workspace: Path, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_blocking_codex_stub(bin_dir: Path) -> None:
    codex = bin_dir / "codex"
    codex.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdin.read(1)\n"
        "print('stub-codex-ok')\n",
        encoding="utf-8",
    )
    codex.chmod(codex.stat().st_mode | stat.S_IEXEC)


def test_dispatch_built_command_does_not_hang_with_inherited_pipe_stdin(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_blocking_codex_stub(bin_dir)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("no-hang test", encoding="utf-8")

    for index in range(5):
        log_file = workspace / f"dispatch-{index}.log"
        task_id = f"task-no-hang-{index}"
        build = _run_mst(
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
            "gpt-test",
            env=env,
        )
        assert build.returncode == 0, build.stderr
        command = build.stdout.strip()
        assert command

        read_fd, write_fd = os.pipe()
        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                ["bash", "-c", command],
                cwd=workspace,
                env=env,
                stdin=read_fd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            os.close(read_fd)
            read_fd = -1

            stdout, stderr = proc.communicate(timeout=5)
            assert proc.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            os.close(write_fd)
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)

        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "EXIT_CODE:0" in content
