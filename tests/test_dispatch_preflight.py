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
