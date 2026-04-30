"""Tests for AD-009: ``mst.py archive purge`` retention enforcement."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _init_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    gm.mkdir(parents=True, exist_ok=True)
    return workspace, gm


def _make_tar(gm: Path, type_subdir: str, name: str, *, age_days: int) -> Path:
    archived = gm / type_subdir / "archived"
    archived.mkdir(parents=True, exist_ok=True)
    path = archived / name
    path.write_bytes(b"fake-tar-payload")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp()
    os.utime(path, (cutoff, cutoff))
    return path


def _run_purge(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "archive", "purge", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_purge_deletes_only_files_older_than_threshold(tmp_path: Path) -> None:
    workspace, gm = _init_workspace(tmp_path)
    old = _make_tar(gm, "requests", "requests-REQ-001-old.tar.gz", age_days=120)
    fresh = _make_tar(gm, "requests", "requests-REQ-002-fresh.tar.gz", age_days=10)

    result = _run_purge(workspace, "--max-age-days", "30")

    assert result.returncode == 0, result.stderr
    assert not old.exists(), "old archive should be deleted"
    assert fresh.exists(), "fresh archive must remain"
    assert "Purged 1 archive" in result.stdout


def test_purge_dry_run_keeps_files(tmp_path: Path) -> None:
    workspace, gm = _init_workspace(tmp_path)
    old = _make_tar(gm, "requests", "requests-REQ-100-old.tar.gz", age_days=180)

    result = _run_purge(workspace, "--max-age-days", "30", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert old.exists(), "dry-run must keep the file"
    assert "[dry-run] would delete 1" in result.stdout
    assert "requests-REQ-100-old.tar.gz" in result.stdout


def test_purge_handles_multiple_type_dirs(tmp_path: Path) -> None:
    workspace, gm = _init_workspace(tmp_path)
    old_req = _make_tar(gm, "requests", "requests-old.tar.gz", age_days=200)
    old_pln = _make_tar(gm, "plans", "plans-old.tar.gz", age_days=200)
    fresh_dbg = _make_tar(gm, "debug", "debug-fresh.tar.gz", age_days=5)

    result = _run_purge(workspace, "--max-age-days", "30")

    assert result.returncode == 0, result.stderr
    assert not old_req.exists()
    assert not old_pln.exists()
    assert fresh_dbg.exists()
    assert "Purged 2 archive" in result.stdout


def test_purge_default_when_config_null_uses_90_days(tmp_path: Path) -> None:
    """AD-009: ``archive_retention_days: null`` must resolve to the safe 90-day
    default rather than infinite retention.
    """
    workspace, gm = _init_workspace(tmp_path)
    # Config explicitly null at top level.
    (gm / "config.json").write_text(
        json.dumps({"archive_retention_days": None}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    older_than_90 = _make_tar(gm, "requests", "requests-old.tar.gz", age_days=120)
    inside_90 = _make_tar(gm, "requests", "requests-recent.tar.gz", age_days=30)

    result = _run_purge(workspace)  # no CLI override

    assert result.returncode == 0, result.stderr
    assert not older_than_90.exists(), "120-day-old archive must be purged under 90d default"
    assert inside_90.exists(), "30-day-old archive must remain under 90d default"


def test_purge_cli_overrides_config(tmp_path: Path) -> None:
    workspace, gm = _init_workspace(tmp_path)
    (gm / "config.json").write_text(
        json.dumps({"archive": {"retention_days": 365}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    over_30 = _make_tar(gm, "requests", "requests-31.tar.gz", age_days=31)

    result = _run_purge(workspace, "--max-age-days", "30")

    assert result.returncode == 0, result.stderr
    assert not over_30.exists(), "CLI override (30d) must take precedence over config (365d)"


def test_purge_empty_workspace(tmp_path: Path) -> None:
    workspace, gm = _init_workspace(tmp_path)

    result = _run_purge(workspace, "--max-age-days", "30")

    assert result.returncode == 0
    assert "Purged 0 archive" in result.stdout
