import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "agile-plan" / "coverage"


def discover_cases() -> list[Path]:
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(
        [
            candidate
            for candidate in FIXTURE_ROOT.iterdir()
            if candidate.is_dir() and (candidate / "expected.json").is_file()
        ],
        key=lambda item: item.name,
    )


def run_coverage_check(original: Path, details_dir: Path) -> tuple[dict, int, str]:
    proc = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "agile",
            "coverage-check",
            str(original),
            "--details-dir",
            str(details_dir),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    return payload, proc.returncode, proc.stderr


@pytest.mark.parametrize("case_dir", discover_cases(), ids=lambda path: path.name)
def test_agile_coverage_fixture(case_dir: Path):
    original = case_dir / "original.md"
    details_dir = case_dir / "details"
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))

    assert original.is_file(), f"missing original.md: {case_dir}"
    assert details_dir.is_dir(), f"missing details/: {case_dir}"

    payload, exit_code, stderr = run_coverage_check(original, details_dir)

    if "coverage" in expected:
        assert payload["coverage"] == pytest.approx(expected["coverage"], abs=0.01)
    if "coverage_min" in expected:
        assert payload["coverage"] >= expected["coverage_min"]
    if "valid" in expected:
        assert payload["valid"] is expected["valid"]
        assert exit_code == (0 if expected["valid"] else 1)
    if "missing_sections" in expected:
        assert sorted(payload["missing_sections"]) == sorted(expected["missing_sections"])
    if "missing_sections_min_count" in expected:
        assert len(payload["missing_sections"]) >= expected["missing_sections_min_count"]
    if "missing_sections_max_count" in expected:
        assert len(payload["missing_sections"]) <= expected["missing_sections_max_count"]

    assert isinstance(payload.get("errors"), list)
    assert "Traceback" not in stderr
