import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"

SKILLS = ["review", "plan", "approve", "agile", "request"]

BEFORE = {
    "review":  {"lines": 1579, "mandatory": 40, "steps": 19, "gate": 3},
    "plan":    {"lines": 1462, "mandatory": 23, "steps": 24, "gate": 3},
    "approve": {"lines": 1366, "mandatory": 13, "steps": 36, "gate": 3},
    "agile":   {"lines": 1290, "mandatory": 30, "steps": 26, "gate": 3},
    "request": {"lines": 1134, "mandatory": 31, "steps":  4, "gate": 3},
}


def count_lines(skill: str) -> int:
    return len((SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8").splitlines())


def count_mandatory(skill: str) -> int:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    return text.count("MANDATORY")


def count_steps(skill: str) -> int:
    import re
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    return sum(
        1 for line in text.splitlines()
        if re.match(r"^### Step|^#### Step|^##### ", line)
    )


def count_gate(skill: str) -> int:
    import re
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    return sum(
        1 for line in text.splitlines()
        if re.match(r"^### (Entry|Exit|금지 패턴)", line)
    )


def test_each_skill_20_percent_reduction():
    for skill in SKILLS:
        lines = count_lines(skill)
        threshold = int(BEFORE[skill]["lines"] * 0.8)
        assert lines <= threshold, f"{skill}: {lines} > {threshold}"


def test_total_line_reduction():
    total = sum(count_lines(s) for s in SKILLS)
    assert total <= 4782, f"Total {total} > 4782"


def test_mandatory_preserved():
    for skill in SKILLS:
        count = count_mandatory(skill)
        assert count >= BEFORE[skill]["mandatory"], \
            f"{skill}: MANDATORY {count} < {BEFORE[skill]['mandatory']}"


def test_step_headers_preserved():
    for skill in SKILLS:
        count = count_steps(skill)
        assert count >= BEFORE[skill]["steps"], \
            f"{skill}: Steps {count} < {BEFORE[skill]['steps']}"


def test_gate_sections_preserved():
    for skill in SKILLS:
        count = count_gate(skill)
        assert count >= BEFORE[skill]["gate"], \
            f"{skill}: Gate {count} < {BEFORE[skill]['gate']}"
