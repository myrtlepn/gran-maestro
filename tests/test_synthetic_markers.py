"""AGI-013 합성 산출물 존재 검증 (DOD-011).

11개 합성 산출물 (README.md + 8 markers + index.md + 이 테스트 파일 자기 자신)이
모두 존재하는지 검증한다.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIR = PROJECT_ROOT / ".gran-maestro" / "synthetic"


def test_readme_exists_with_agi013_tag() -> None:
    readme = SYNTHETIC_DIR / "README.md"
    assert readme.exists(), f"missing {readme}"
    assert "AGI-013" in readme.read_text(encoding="utf-8")


def test_all_eight_markers_present() -> None:
    for i in range(1, 9):
        marker = SYNTHETIC_DIR / f"marker-{i:02d}.txt"
        assert marker.exists(), f"missing {marker}"
        content = marker.read_text(encoding="utf-8")
        assert f"AGI-013 sprint {i} marker" in content, f"tag missing in {marker}"


def test_index_lists_all_markers() -> None:
    index = SYNTHETIC_DIR / "index.md"
    assert index.exists(), f"missing {index}"
    content = index.read_text(encoding="utf-8")
    for i in range(1, 9):
        assert f"marker-{i:02d}.txt" in content, f"marker-{i:02d}.txt not in index"


def test_self_exists() -> None:
    assert Path(__file__).exists()
