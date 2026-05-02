from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _run_scan(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), "gardening", "scan", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gardening_scan_json_reports_migrate_archive_counts_read_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    worktrees_dir = gm / "worktrees"
    candidate = worktrees_dir / "REQ-801-candidate.meta.json"
    invalid = worktrees_dir / "REQ-801-invalid.meta.json"
    _write_json(candidate, {"taskId": "REQ-801-candidate", "state": "cleaned"})
    _write(invalid, "{not json")
    before = candidate.read_text(encoding="utf-8")

    result = _run_scan(workspace, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    report = payload["worktree_migrate_archive"]
    assert report["ok"] is True
    assert report["candidate_count"] == 1
    assert report["skipped_count"] == 1
    assert report["clean"] is False
    assert report["recommended_commands"] == [
        "mst.py worktree migrate-archive --dry-run",
        "mst.py worktree migrate-archive --apply",
        "mst.py worktree migrate-archive --delete --apply",
    ]
    assert candidate.read_text(encoding="utf-8") == before
    assert not (worktrees_dir / ".archive").exists()


def test_gardening_scan_text_reports_clean_zero_candidate_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    _write_json(
        gm / "worktrees" / "REQ-801-ok.meta.json",
        {"taskId": "REQ-801-ok", "session_id": "session-ok"},
    )

    result = _run_scan(workspace)

    assert result.returncode == 0, result.stderr
    assert "stale meta lineage=unknown candidates=0 skipped=1" in result.stdout
    assert "clean: lineage=unknown candidate 없음" in result.stdout


def test_gardening_scan_json_reports_clean_zero_candidate_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    gm = workspace / ".gran-maestro"
    _write_json(
        gm / "worktrees" / "REQ-801-ok.meta.json",
        {"taskId": "REQ-801-ok", "session_id": "session-ok"},
    )

    result = _run_scan(workspace, "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)["worktree_migrate_archive"]
    assert report["candidate_count"] == 0
    assert report["clean"] is True
