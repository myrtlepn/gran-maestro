from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PASS_COUNT_RE = re.compile(r"(\d+)\s+passed")


def test_regression_gate():
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-k", "queue or resume or resolve", "-v"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    output = f"{proc.stdout}\n{proc.stderr}"

    assert proc.returncode == 0, output

    match = PASS_COUNT_RE.search(output)
    assert match is not None, output
    passed_count = int(match.group(1))
    assert passed_count > 0, output
    print(f"REQ-743 regression gate passed_count={passed_count}")
