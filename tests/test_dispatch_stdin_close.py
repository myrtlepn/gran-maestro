from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SKILL_FILES = [
    "skills/ideation/SKILL.md",
    "skills/discussion/SKILL.md",
    "skills/debug/SKILL.md",
    "skills/explore/SKILL.md",
    "skills/review/SKILL.md",
    "skills/request/SKILL.md",
    "skills/plan/SKILL.md",
    "skills/plan-doc/SKILL.md",
    "skills/approve/SKILL.md",
    "skills/codex/SKILL.md",
    "skills/claude/SKILL.md",
]


def test_background_dispatch_commands_close_stdin():
    missing: list[str] = []

    for rel_path in SKILL_FILES:
        path = REPO_ROOT / rel_path
        content = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if "codex exec" not in line and "agy --print" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            is_command_line = (
                "command:" in line
                or stripped.startswith("MODEL=")
                or stripped.startswith("codex exec ")
                or stripped.startswith("agy --print ")
                or "&& codex exec " in line
                or "&& agy --print " in line
            )
            if not is_command_line:
                continue
            if "< /dev/null" in line:
                continue
            missing.append(f"{rel_path}:{line_no}")

    assert not missing, "stdin close (< /dev/null) missing in:\n" + "\n".join(missing)
