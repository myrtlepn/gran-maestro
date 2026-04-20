from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.agile import cmd_agile_finalize


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-688"


def _run_git(repo_root: Path, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
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


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str, *, cwd: Optional[Path] = None) -> None:
    target_root = cwd or repo_root
    target = target_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    add = _run_git(repo_root, "add", relative_path, cwd=target_root)
    assert add.returncode == 0, add.stderr
    commit = _run_git(repo_root, "commit", "-m", message, cwd=target_root)
    assert commit.returncode == 0, commit.stderr


def _payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


@pytest.fixture
def finalize_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    _commit_file(repo_root, "app.txt", "base\n", "initial commit")
    rename = _run_git(repo_root, "branch", "-M", "master")
    assert rename.returncode == 0, rename.stderr

    (repo_root / ".gran-maestro").mkdir()
    _write_json(
        repo_root / ".gran-maestro" / "agile" / AGI_ID / "session.json",
        {"id": AGI_ID, "status": "active", "current_sprint": 3},
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


def _events(repo_root: Path) -> list[dict]:
    events_path = repo_root / ".gran-maestro" / "agile" / AGI_ID / "events.ndjson"
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_agile_finalize_all_done(finalize_repo: Path) -> None:
    req_ids = ["REQ-701", "REQ-702", "REQ-703"]
    for index, req_id in enumerate(req_ids):
        _write_request(finalize_repo, req_id, ["accepted", "done", "completed"][index])
        _write_sprint_result(finalize_repo, index, req_id)

    result = _run_mst(finalize_repo, "agile", "finalize", AGI_ID, "--json")

    assert result.returncode == 0, result.stderr
    payload = _payload(result)
    assert payload["agi_id"] == AGI_ID
    assert payload["accepted_reqs"] == []
    assert payload["skipped_reqs"] == req_ids
    assert payload["pending_accept_reqs"] == []
    assert payload["removed_worktrees"] == []
    assert payload["orphan_cleanup"]["failed"] == []
    assert payload["boundary_ok"] is None
    assert _events(finalize_repo)[-1]["event"] == "agile.finalize.ok"


def test_agile_finalize_pending_accept(finalize_repo: Path) -> None:
    _write_request(finalize_repo, "REQ-704", "executing")
    _write_sprint_result(finalize_repo, 0, "REQ-704")

    result = _run_mst(finalize_repo, "agile", "finalize", AGI_ID, "--json")

    assert result.returncode == 2
    payload = _payload(result)
    assert payload["accepted_reqs"] == []
    assert payload["pending_accept_reqs"] == ["REQ-704"]
    assert "[finalize] pending accept: REQ-704" in result.stderr
    assert payload["orphan_cleanup"]["failed"] == []
    assert "agile.finalize.pending_accept" in [event["event"] for event in _events(finalize_repo)]


def test_agile_finalize_worktree_cleanup_idempotent(finalize_repo: Path) -> None:
    _write_request(finalize_repo, "REQ-705", "accepted")
    _write_sprint_result(finalize_repo, 1, "REQ-705")
    worktree_path = finalize_repo / ".gran-maestro" / "worktrees" / AGI_ID / "sprint-01"
    add_worktree = _run_git(
        finalize_repo,
        "worktree",
        "add",
        "-b",
        f"gran-maestro/{AGI_ID}/sprint-01",
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    _commit_file(finalize_repo, "app.txt", "sprint\n", "sprint work", cwd=worktree_path)

    first = _run_mst(finalize_repo, "agile", "finalize", AGI_ID, "--json")
    second = _run_mst(finalize_repo, "agile", "finalize", AGI_ID, "--json")

    assert first.returncode == 0, first.stderr
    first_payload = _payload(first)
    assert first_payload["removed_worktrees"] == [str(worktree_path.resolve(strict=False))]
    assert not worktree_path.exists()
    assert second.returncode == 0, second.stderr
    assert _payload(second)["removed_worktrees"] == []


def test_agile_finalize_orphan_cleanup_payload(monkeypatch, tmp_path: Path, capsys) -> None:
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
                0,
                stdout=json.dumps({"cleaned": ["REQ-706-T01"], "failed": [], "orphans": []}),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="usage: unsupported --agi")

    monkeypatch.setattr("scripts.mst_cmds.agile._run_finalize_mst_command", fake_run)

    exit_code = cmd_agile_finalize(argparse.Namespace(agi_id=AGI_ID, json=True))
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["orphan_cleanup"]["cleaned"] == ["REQ-706-T01"]
    assert payload["orphan_cleanup"]["failed"] == []


def test_agile_finalize_orphan_cleanup_failed_is_nonzero(monkeypatch, tmp_path: Path, capsys) -> None:
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
                stdout=json.dumps({"cleaned": [], "failed": ["REQ-707-T01"], "orphans": []}),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="usage: unsupported --agi")

    monkeypatch.setattr("scripts.mst_cmds.agile._run_finalize_mst_command", fake_run)

    exit_code = cmd_agile_finalize(argparse.Namespace(agi_id=AGI_ID, json=True))
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["orphan_cleanup"]["failed"] == ["REQ-707-T01"]


def test_agile_finalize_subparser_registered(finalize_repo: Path) -> None:
    help_result = _run_mst(finalize_repo, "agile", "finalize", "--help")
    missing_arg = _run_mst(finalize_repo, "agile", "finalize")

    assert help_result.returncode == 0, help_result.stderr
    assert "agi_id" in help_result.stdout
    assert missing_arg.returncode != 0
    assert "usage:" in missing_arg.stderr
