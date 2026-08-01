from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "sync-codex-plugin-projection.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("mst_projection_sync", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_projection_drift_reports_missing_extra_and_changed_files(tmp_path: Path) -> None:
    module = _load_sync_module()
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    expected.mkdir()
    actual.mkdir()
    (expected / "same.txt").write_text("same", encoding="utf-8")
    (actual / "same.txt").write_text("same", encoding="utf-8")
    (expected / "changed.txt").write_text("expected", encoding="utf-8")
    (actual / "changed.txt").write_text("actual", encoding="utf-8")
    (expected / "missing.txt").write_text("missing", encoding="utf-8")
    (actual / "extra.txt").write_text("extra", encoding="utf-8")

    assert module.projection_drift(expected, actual) == [
        "changed.txt",
        "extra.txt",
        "missing.txt",
    ]


def test_projection_check_is_read_only_when_projection_matches() -> None:
    before = _tree_snapshot(REPO_ROOT / "plugins" / "mst")

    result = subprocess.run(
        ["python3", str(SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    after = _tree_snapshot(REPO_ROOT / "plugins" / "mst")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "projection check passed" in result.stdout
    assert after == before
