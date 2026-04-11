import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"

SKILL_FILES = [
    REPO_ROOT / "skills" / "plan" / "SKILL.md",
    REPO_ROOT / "skills" / "request" / "SKILL.md",
    REPO_ROOT / "skills" / "approve" / "SKILL.md",
    REPO_ROOT / "skills" / "review" / "SKILL.md",
    REPO_ROOT / "skills" / "agile-plan" / "SKILL.md",
    REPO_ROOT / "skills" / "plan-doc" / "SKILL.md",
]


def _run_mst(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reference_add_help_mentions_raw_excerpt_keywords():
    proc = _run_mst("reference", "add", "--help")

    assert proc.returncode == 0
    output = f"{proc.stdout}\n{proc.stderr}"

    for keyword in ("raw 발췌", "인용", "표", "코드"):
        assert keyword in output


def test_reference_protocol_removed_core_summary_placeholder_and_requires_raw_excerpt():
    for path in SKILL_FILES:
        content = path.read_text(encoding="utf-8")

        assert "{핵심 요약}" not in content, f"legacy placeholder found in {path}"
        assert (
            "raw 발췌" in content or "원문 발췌" in content
        ), f"raw excerpt guidance missing in {path}"


def test_plan_skill_has_quote_table_code_examples_with_source_context():
    content = (REPO_ROOT / "skills" / "plan" / "SKILL.md").read_text(encoding="utf-8")

    assert "> 인용" in content
    assert "| 열 |" in content
    assert "```" in content

    for keyword in ("출처", "URL", "날짜"):
        assert keyword in content


def test_plan_skill_contains_ref_quality_checklist_keywords():
    content = (REPO_ROOT / "skills" / "plan" / "SKILL.md").read_text(encoding="utf-8")

    for keyword in ("Findings", "Quotes", "Data", "Context"):
        assert keyword in content
