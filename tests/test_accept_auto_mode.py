import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skip(reason="T02 변경이 merge된 환경에서만 검증")
def test_accept_step_0_1_doc_exists():
    skill_doc = ROOT / "skills" / "accept" / "SKILL.md"
    assert skill_doc.exists(), f"missing file: {skill_doc}"

    proc = subprocess.run(
        ["grep", "-n", "Step 0.1", str(skill_doc)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
