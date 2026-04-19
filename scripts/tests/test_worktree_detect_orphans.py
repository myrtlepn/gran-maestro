from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.worktree import cmd_worktree_detect_orphans


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _worktree_roots(repo_root: Path) -> set[Path]:
    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    assert result.returncode == 0, result.stderr
    return {
        Path(line.split(" ", 1)[1]).resolve(strict=False)
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    }


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = _run_git(repo_root, "branch", "--list", branch)
    assert result.returncode == 0, result.stderr
    return bool(result.stdout.strip())


@pytest.fixture
def master_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "master-repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr

    config_email = _run_git(repo_root, "config", "user.email", "tester@example.com")
    assert config_email.returncode == 0, config_email.stderr

    config_name = _run_git(repo_root, "config", "user.name", "Test User")
    assert config_name.returncode == 0, config_name.stderr

    initial_commit = _run_git(repo_root, "commit", "--allow-empty", "-m", "initial commit")
    assert initial_commit.returncode == 0, initial_commit.stderr

    rename_branch = _run_git(repo_root, "branch", "-M", "master")
    assert rename_branch.returncode == 0, rename_branch.stderr

    (repo_root / ".gran-maestro" / "worktrees").mkdir(parents=True, exist_ok=True)
    return repo_root


def _run_detect_orphans(*, clean: bool, as_json: bool) -> int:
    return cmd_worktree_detect_orphans(
        argparse.Namespace(
            clean=clean,
            json=as_json,
        )
    )


def test_detect_orphans_cleans_cleaned_meta_with_lingering_worktree(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T01"
    branch = "gran-maestro/main/REQ-681-T01"
    worktree_path = tmp_path / task_id
    add_worktree = _run_git(master_repo, "worktree", "add", "-b", branch, str(worktree_path), "master")
    assert add_worktree.returncode == 0, add_worktree.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == [task_id]
    assert payload["orphans"][0]["taskId"] == task_id
    assert payload["orphans"][0]["worktree_listed"] is True
    assert payload["orphans"][0]["branch_exists"] is True
    assert not meta_path.exists()
    assert not worktree_path.exists()
    assert worktree_path.resolve(strict=False) not in _worktree_roots(master_repo)
    assert not _branch_exists(master_repo, branch)


def test_detect_orphans_ignores_cleaned_meta_without_artifacts(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T02"
    branch = "gran-maestro/main/REQ-681-T02"
    worktree_path = tmp_path / task_id
    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == []
    assert payload["orphans"] == []
    assert meta_path.exists()


def test_detect_orphans_cleans_branch_only_orphan(
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    task_id = "REQ-681-T03"
    branch = "gran-maestro/main/REQ-681-T03"
    worktree_path = tmp_path / task_id
    create_branch = _run_git(master_repo, "branch", branch, "master")
    assert create_branch.returncode == 0, create_branch.stderr

    meta_path = master_repo / ".gran-maestro" / "worktrees" / f"{task_id}.meta.json"
    _write_json(
        meta_path,
        {
            "taskId": task_id,
            "path": str(worktree_path),
            "branch": branch,
            "state": "cleaned",
        },
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = _run_detect_orphans(clean=True, as_json=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0, captured.err
    assert payload["cleaned"] == [task_id]
    assert payload["orphans"][0]["worktree_listed"] is False
    assert payload["orphans"][0]["branch_exists"] is True
    assert payload["orphans"][0]["path_exists"] is False
    assert not meta_path.exists()
    assert not _branch_exists(master_repo, branch)
