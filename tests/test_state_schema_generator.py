from __future__ import annotations

import hashlib
import importlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCRIPT = REPO_ROOT / "scripts" / "build_state_schema.py"
GENERATED_MODULE = REPO_ROOT / "scripts" / "_state_schema.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generator_deterministic() -> None:
    run_kwargs = {
        "cwd": REPO_ROOT,
        "capture_output": True,
        "text": True,
        "check": False,
    }

    first = subprocess.run([sys.executable, str(GENERATOR_SCRIPT)], **run_kwargs)
    assert first.returncode == 0, first.stderr
    first_hash = _sha256(GENERATED_MODULE)

    second = subprocess.run([sys.executable, str(GENERATOR_SCRIPT)], **run_kwargs)
    assert second.returncode == 0, second.stderr
    second_hash = _sha256(GENERATED_MODULE)

    assert first_hash == second_hash


def test_generator_extracts_all_exports() -> None:
    from scripts import _state_schema as generated

    generated = importlib.reload(generated)

    required_names = (
        "TASK_STATUSES",
        "TERMINAL",
        "TRANSITIONS",
        "RECOVERY_ACTIONS",
    )
    for name in required_names:
        assert hasattr(generated, name)
        assert getattr(generated, name)
