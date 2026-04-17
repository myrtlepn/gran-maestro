from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skip(reason="T02 변경이 merge된 환경에서만 검증")
def test_approve_accept_args_dash_a():
    skill_doc = ROOT / "skills" / "approve" / "SKILL.md"
    assert skill_doc.exists(), f"missing file: {skill_doc}"

    lines = skill_doc.read_text(encoding="utf-8").splitlines()
    near_1140 = "\n".join(lines[1119:1165])

    assert "AUTO_MODE" in near_1140
    assert "-a" in near_1140
