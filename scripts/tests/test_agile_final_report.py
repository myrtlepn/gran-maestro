from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.agile import cmd_agile_finalize


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-689"


def _run_git(repo_root: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST), *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str) -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    add = _run_git(repo_root, "add", relative_path)
    assert add.returncode == 0, add.stderr
    commit = _run_git(repo_root, "commit", "-m", message)
    assert commit.returncode == 0, commit.stderr


@pytest.fixture
def final_report_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    _commit_file(repo_root, "app.txt", "base\n", "initial commit")
    rename = _run_git(repo_root, "branch", "-M", "master")
    assert rename.returncode == 0, rename.stderr

    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "session.json",
        {"id": AGI_ID, "status": "active", "current_sprint": 1},
    )
    return repo_root


def _write_request(repo_root: Path, req_id: str, status: str) -> None:
    _write_json(
        repo_root / ".gran-maestro" / "requests" / req_id / "request.json",
        {"id": req_id, "title": req_id, "status": status, "current_phase": 4},
    )


def _write_sprint_result(repo_root: Path, sprint: int, req_id: str) -> None:
    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "sprints" / f"S{sprint:02d}" / "result.json",
        {"sprint_id": f"S{sprint:02d}", "req_id": req_id, "status": "done"},
    )


def _final_report(repo_root: Path) -> Path:
    return repo_root / ".gran-maestro" / "agile" / AGI_ID / "final-report.md"


def test_agile_finalize_writes_ok_final_report(final_report_repo: Path) -> None:
    _write_request(final_report_repo, "REQ-801", "accepted")
    _write_sprint_result(final_report_repo, 0, "REQ-801")

    result = _run_mst(final_report_repo, "agile", "finalize", AGI_ID, "--json")

    assert result.returncode == 0, result.stderr
    report = _final_report(final_report_repo)
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "# AGI-689 Finalization Report" in content
    assert "- status: ok" in content
    assert "- skipped_reqs: [\"REQ-801\"]" in content
    assert "## Worktree Cleanup" in content
    assert "- removed_worktrees: 0" in content


def test_agile_finalize_writes_pending_accept_final_report(final_report_repo: Path) -> None:
    _write_request(final_report_repo, "REQ-802", "executing")
    _write_sprint_result(final_report_repo, 0, "REQ-802")

    result = _run_mst(final_report_repo, "agile", "finalize", AGI_ID, "--json")

    assert result.returncode == 2
    content = _final_report(final_report_repo).read_text(encoding="utf-8")
    assert "- status: pending_accept" in content
    assert "- pending_accept_reqs: [\"REQ-802\"]" in content


def test_agile_finalize_writes_failed_orphan_final_report(monkeypatch, tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".gran-maestro" / "agile" / AGI_ID).mkdir(parents=True)
    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "session.json",
        {"id": AGI_ID, "status": "active"},
    )
    monkeypatch.setattr(_common, "BASE_DIR", repo_root / ".gran-maestro")
    monkeypatch.chdir(repo_root)

    def fake_run(command, *, cwd):
        if command[:4] == [sys.executable, str(_common._mst_script_path()), "worktree", "detect-orphans"]:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=json.dumps({"cleaned": [], "failed": ["REQ-803-T01"], "orphans": []}),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="usage: unsupported --agi")

    monkeypatch.setattr("scripts.mst_cmds.agile._run_finalize_mst_command", fake_run)

    exit_code = cmd_agile_finalize(argparse.Namespace(agi_id=AGI_ID, json=True))
    capsys.readouterr()

    assert exit_code == 1
    content = _final_report(repo_root).read_text(encoding="utf-8")
    assert "- status: failed" in content
    assert "## Orphan Cleanup" in content
    assert "- failed: [\"REQ-803-T01\"]" in content
