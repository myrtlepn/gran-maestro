from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.worktree import cmd_worktree_remove


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _worktree_roots(repo_root: Path) -> list[Path]:
    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    assert result.returncode == 0, result.stderr

    roots: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line.split(" ", 1)[1]).resolve(strict=False))
    return roots


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


@pytest.fixture
def clean_worktree(master_repo: Path, tmp_path: Path) -> Path:
    worktree_path = tmp_path / "linked-worktree-A"
    add_worktree = _run_git(
        master_repo,
        "worktree",
        "add",
        "-b",
        "feature/remove-regression",
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr

    status = _run_git(worktree_path, "status", "--porcelain")
    assert status.returncode == 0, status.stderr
    assert status.stdout == ""
    assert worktree_path.resolve(strict=False) in _worktree_roots(master_repo)

    return worktree_path


def test_normal_remove_clean(master_repo: Path, clean_worktree: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(clean_worktree),
            force=False,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(clean_worktree.resolve())
    assert not clean_worktree.exists()
    assert clean_worktree.resolve(strict=False) not in _worktree_roots(master_repo)
