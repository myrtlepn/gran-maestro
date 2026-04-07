import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _load_mst_module():
    spec = importlib.util.spec_from_file_location("mst_module", MST_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MST_MODULE = _load_mst_module()


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_details(details_dir: Path, filename: str, sections: list[str]) -> Path:
    details_dir.mkdir(parents=True, exist_ok=True)
    quoted = ", ".join(f'"{section}"' for section in sections)
    details_path = details_dir / filename
    details_path.write_text(
        f"<!-- source-mapping: original=objective.md sections=[{quoted}] -->\n# Detail\n",
        encoding="utf-8",
    )
    return details_path


def test_extract_h12_slugs_normalization_and_dedupe():
    markdown = "\n".join(
        [
            "# 소개",
            "## 기능 A!",
            "## 기능\tA!",
            "### 제외됨",
            "## API / Auth",
            "#   mixed   Case  제목 ",
        ]
    )

    slugs = MST_MODULE.extract_h12_slugs(markdown)

    assert slugs == ["소개", "기능-a", "api-auth", "mixed-case-제목"]


def test_compute_coverage_reports_missing_sorted():
    coverage = MST_MODULE.compute_coverage(
        ["b", "a", "c"],
        {"a"},
    )

    assert coverage["total_sections"] == 3
    assert coverage["matched_sections"] == 1
    assert coverage["missing_sections"] == ["b", "c"]
    assert coverage["coverage"] == 1 / 3


def test_coverage_pass_threshold(tmp_path):
    workspace = _make_workspace(tmp_path)
    original = tmp_path / "original.md"
    details_dir = tmp_path / "details"

    original.write_text(
        "\n".join(
            [
                "# 소개",
                "## 목표",
                "## 범위",
                "# 구현",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_details(details_dir, "d1.md", ["소개", "목표"])
    _write_details(details_dir, "d2.md", ["범위", "구현"])

    proc = _run_mst(
        workspace,
        "agile",
        "coverage-check",
        str(original),
        "--details-dir",
        str(details_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["original"] == str(original)
    assert payload["details_dir"] == str(details_dir)
    assert payload["total_sections"] == 4
    assert payload["matched_sections"] == 4
    assert payload["missing_sections"] == []
    assert payload["coverage"] == 1.0
    assert payload["threshold"] == 0.85
    assert payload["valid"] is True
    assert payload["errors"] == []


def test_coverage_fail_threshold(tmp_path):
    workspace = _make_workspace(tmp_path)
    original = tmp_path / "original.md"
    details_dir = tmp_path / "details"

    original.write_text(
        "\n".join(
            [
                "# one",
                "## two",
                "## three",
                "## four",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_details(details_dir, "d1.md", ["one", "two"])

    proc = _run_mst(
        workspace,
        "agile",
        "coverage-check",
        str(original),
        "--details-dir",
        str(details_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["total_sections"] == 4
    assert payload["matched_sections"] == 2
    assert payload["missing_sections"] == ["four", "three"]
    assert payload["coverage"] == 0.5
    assert payload["threshold"] == 0.85
    assert payload["valid"] is False
    assert "[coverage-check] FAIL" in proc.stderr
    assert "[coverage-check] missing: four" in proc.stderr
    assert "[coverage-check] missing: three" in proc.stderr


def test_coverage_threshold_override(tmp_path):
    workspace = _make_workspace(tmp_path)
    original = tmp_path / "original.md"
    details_dir = tmp_path / "details"

    original.write_text(
        "\n".join(
            [
                "# one",
                "## two",
                "## three",
                "## four",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_details(details_dir, "d1.md", ["one", "two"])

    proc = _run_mst(
        workspace,
        "agile",
        "coverage-check",
        str(original),
        "--details-dir",
        str(details_dir),
        "--threshold",
        "0.4",
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert payload["coverage"] == 0.5
    assert payload["threshold"] == 0.4
    assert payload["valid"] is True


def test_coverage_original_missing(tmp_path):
    workspace = _make_workspace(tmp_path)
    original = tmp_path / "missing.md"
    details_dir = tmp_path / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    proc = _run_mst(
        workspace,
        "agile",
        "coverage-check",
        str(original),
        "--details-dir",
        str(details_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["valid"] is False
    assert payload["errors"] == [f"original not found: {original}"]
    assert "Traceback" not in proc.stderr


def test_coverage_details_dir_missing(tmp_path):
    workspace = _make_workspace(tmp_path)
    original = tmp_path / "original.md"
    details_dir = tmp_path / "missing-details"

    original.write_text("# intro\n", encoding="utf-8")

    proc = _run_mst(
        workspace,
        "agile",
        "coverage-check",
        str(original),
        "--details-dir",
        str(details_dir),
        "--json",
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["valid"] is False
    assert payload["errors"] == [f"details dir not found: {details_dir}"]
    assert "Traceback" not in proc.stderr
