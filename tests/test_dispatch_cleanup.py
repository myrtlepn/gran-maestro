import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro" / "run").mkdir(parents=True)
    (workspace / ".gran-maestro" / "archive").mkdir(parents=True)
    return workspace


def _run_mst(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _write_marker(workspace: Path, task_id: str, **overrides) -> Path:
    payload = {
        "task_id": task_id,
        "pid": os.getpid(),
        "started_by_pid": os.getpid(),
        "phase": "running",
        "provider": "codex",
        "model": "test-model",
        "worktree_dir": str(workspace),
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)

    path = workspace / ".gran-maestro" / "run" / f"{task_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _archive_path(workspace: Path, task_id: str) -> Path:
    matches = sorted((workspace / ".gran-maestro" / "archive" / "run").glob(f"*/{task_id}.json"))
    assert len(matches) == 1, f"expected one archived marker for {task_id}, got {matches}"
    return matches[0]


def _summary_line(stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "expected stdout to contain a summary line"
    return lines[-1]


def test_legacy_marker_archived(tmp_path):
    workspace = _workspace(tmp_path)
    marker = _write_marker(workspace, "legacy-marker")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload.pop("started_by_pid")
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    proc = _run_mst(workspace, "dispatch", "cleanup", "--legacy")

    assert proc.returncode == 0, proc.stderr
    archived = _archive_path(workspace, "legacy-marker")
    assert archived.exists()
    assert not marker.exists()


def test_stale_done_archived(tmp_path):
    workspace = _workspace(tmp_path)
    marker = _write_marker(
        workspace,
        "stale-done",
        phase="done",
        last_heartbeat=_iso_days_ago(10),
    )

    proc = _run_mst(workspace, "dispatch", "cleanup", "--legacy")

    assert proc.returncode == 0, proc.stderr
    archived = _archive_path(workspace, "stale-done")
    assert archived.exists()
    assert not marker.exists()


def test_normal_marker_preserved(tmp_path):
    workspace = _workspace(tmp_path)
    marker = _write_marker(
        workspace,
        "normal-running",
        phase="running",
        pid=os.getpid(),
        started_by_pid=os.getpid(),
    )
    before = marker.read_text(encoding="utf-8")
    before_mtime = marker.stat().st_mtime_ns

    proc = _run_mst(workspace, "dispatch", "cleanup", "--legacy")

    assert proc.returncode == 0, proc.stderr
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == before
    assert marker.stat().st_mtime_ns == before_mtime
    assert not list((workspace / ".gran-maestro" / "archive" / "run").glob("*/normal-running.json"))


def test_dry_run_no_archive(tmp_path):
    workspace = _workspace(tmp_path)
    legacy = _write_marker(workspace, "dry-legacy")
    legacy_payload = json.loads(legacy.read_text(encoding="utf-8"))
    legacy_payload.pop("started_by_pid")
    legacy.write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    stale_done = _write_marker(
        workspace,
        "dry-stale-done",
        phase="done",
        last_heartbeat=_iso_days_ago(10),
    )
    preserved = _write_marker(workspace, "dry-preserved", phase="running")

    proc = _run_mst(workspace, "dispatch", "cleanup", "--legacy", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert legacy.exists()
    assert stale_done.exists()
    assert preserved.exists()
    assert not list((workspace / ".gran-maestro" / "archive" / "run").glob("*/*.json"))
    assert "[dry-run] would archive:" in proc.stdout
    assert "dry-legacy.json" in proc.stdout
    assert "dry-stale-done.json" in proc.stdout
    assert "dry-preserved.json" not in proc.stdout


def test_summary_output(tmp_path):
    workspace = _workspace(tmp_path)
    legacy = _write_marker(workspace, "summary-legacy")
    legacy_payload = json.loads(legacy.read_text(encoding="utf-8"))
    legacy_payload.pop("started_by_pid")
    legacy.write_text(json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_marker(
        workspace,
        "summary-stale-done",
        phase="done",
        last_heartbeat=_iso_days_ago(10),
    )
    _write_marker(workspace, "summary-preserved", phase="running")

    proc = _run_mst(workspace, "dispatch", "cleanup", "--legacy")

    assert proc.returncode == 0, proc.stderr
    assert re.fullmatch(
        r"SUMMARY: archived=2 legacy=1 stale_done=1 preserved=1",
        _summary_line(proc.stdout),
    )


def test_regression():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dispatch_preflight.py",
            "tests/test_run_integration.py",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
