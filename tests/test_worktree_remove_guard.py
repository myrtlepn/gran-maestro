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


def _add_worktree(master_repo: Path, worktree_path: Path, branch: str) -> Path:
    add_worktree = _run_git(
        master_repo,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    return worktree_path


def test_child_worktree_blocks_remove(master_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    parent_worktree = _add_worktree(
        master_repo,
        tmp_path / "linked-worktree-parent",
        "feature/remove-parent",
    )
    child_worktree = _add_worktree(
        master_repo,
        parent_worktree / "child-worktree",
        "feature/remove-child",
    )

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(parent_worktree),
            force=False,
        )
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "child worktree" in captured.err
    assert "자식부터 정리하세요" in captured.err
    assert str(parent_worktree.resolve(strict=False)) in captured.err
    assert str(child_worktree.resolve(strict=False)) in captured.err
    assert parent_worktree.exists()
    assert parent_worktree.resolve(strict=False) in _worktree_roots(master_repo)
    assert child_worktree.resolve(strict=False) in _worktree_roots(master_repo)


def test_dirty_blocks_remove_without_force(master_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    worktree_path = _add_worktree(
        master_repo,
        tmp_path / "linked-worktree-dirty",
        "feature/remove-dirty",
    )
    (worktree_path / "untracked.txt").write_text("dirty\n")

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(worktree_path),
            force=False,
        )
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "uncommitted changes" in captured.err
    assert "--force" in captured.err
    assert str(worktree_path.resolve(strict=False)) in captured.err
    assert worktree_path.exists()
    assert worktree_path.resolve(strict=False) in _worktree_roots(master_repo)


def test_dirty_force_warns_then_removes(master_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    worktree_path = _add_worktree(
        master_repo,
        tmp_path / "linked-worktree-force-dirty",
        "feature/remove-force-dirty",
    )
    (worktree_path / "untracked.txt").write_text("dirty\n")

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_remove(
        argparse.Namespace(
            path=str(worktree_path),
            force=True,
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert "uncommitted changes" in captured.err
    assert "data loss" in captured.err
    assert captured.out.strip() == str(worktree_path.resolve(strict=False))
    assert not worktree_path.exists()
    assert worktree_path.resolve(strict=False) not in _worktree_roots(master_repo)
