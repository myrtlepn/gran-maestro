import json
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


def _write_stub_binary(bin_dir: Path, name: str) -> Path:
    path = bin_dir / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_dispatch_preflight_fails_when_binary_missing(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = ""

    proc = _run_mst(
        workspace,
        "dispatch",
        "preflight",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        env=env,
    )

    assert proc.returncode != 0
    assert "codex" in proc.stderr.lower()


def test_dispatch_preflight_fails_when_model_cannot_resolve(tmp_path):
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    gm.mkdir(parents=True, exist_ok=True)

    (gm / "config.resolved.json").write_text(
        json.dumps(
            {
                "models": {
                    "providers": {
                        "codex": {
                            "default_tier": "premium",
                        }
                    }
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_stub_binary(bin_dir, "codex")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    proc = _run_mst(
        workspace,
        "dispatch",
        "preflight",
        "--provider",
        "codex",
        env=env,
    )

    assert proc.returncode != 0
    assert "model" in proc.stderr.lower()


def test_dispatch_preflight_warns_on_stdin_pipe_but_returns_zero(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_stub_binary(bin_dir, "codex")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

    proc = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "dispatch",
            "preflight",
            "--provider",
            "codex",
            "--model",
            "gpt-test",
        ],
        cwd=workspace,
        input="",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert "stdin" in proc.stderr.lower()


def test_dispatch_register_resolves_started_by_pid_from_session_anchor(tmp_path):
    workspace = tmp_path / "workspace"
    gm_tmp = workspace / ".gran-maestro" / "tmp"
    gm_tmp.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.pop("MST_STATE_PPID", None)

    anchor_proc = subprocess.Popen(["sleep", "30"])
    try:
        (gm_tmp / f"mst-session-anchor-{anchor_proc.pid}.pid").write_text(
            f"{anchor_proc.pid}\n",
            encoding="utf-8",
        )

        proc = _run_mst(
            workspace,
            "dispatch",
            "register",
            "--task-id",
            "dispatch-anchor",
            "--pid",
            str(os.getpid()),
            "--provider",
            "codex",
            "--model",
            "test-model",
            "--worktree-dir",
            str(workspace),
            env=env,
        )

        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["started_by_pid"] == anchor_proc.pid
    finally:
        if anchor_proc.poll() is None:
            anchor_proc.terminate()
            anchor_proc.wait(timeout=5)
