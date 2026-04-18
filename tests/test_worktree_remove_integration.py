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


def _remove_worktree(worktree_path: Path, *, force: bool) -> int:
    return cmd_worktree_remove(
        argparse.Namespace(
            path=str(worktree_path),
            force=force,
        )
    )


def test_parent_child_dirty_remove_sequence(master_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    parent_worktree = _add_worktree(
        master_repo,
        tmp_path / "linked-worktree-A",
        "feature/remove-integration-parent",
    )
    child_worktree = _add_worktree(
        master_repo,
        parent_worktree / "child",
        "feature/remove-integration-child",
    )
    (child_worktree / "untracked.txt").write_text("dirty\n")

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    parent_blocked = _remove_worktree(parent_worktree, force=False)
    parent_blocked_output = capsys.readouterr()

    assert parent_blocked != 0
    assert "child worktree" in parent_blocked_output.err
    assert "자식부터 정리하세요" in parent_blocked_output.err
    assert str(parent_worktree.resolve(strict=False)) in parent_blocked_output.err
    assert str(child_worktree.resolve(strict=False)) in parent_blocked_output.err
    assert parent_worktree.exists()
    assert child_worktree.exists()
    assert parent_worktree.resolve(strict=False) in _worktree_roots(master_repo)
    assert child_worktree.resolve(strict=False) in _worktree_roots(master_repo)

    child_dirty_blocked = _remove_worktree(child_worktree, force=False)
    child_dirty_blocked_output = capsys.readouterr()

    assert child_dirty_blocked != 0
    assert "uncommitted changes" in child_dirty_blocked_output.err
    assert "--force" in child_dirty_blocked_output.err
    assert str(child_worktree.resolve(strict=False)) in child_dirty_blocked_output.err
    assert child_worktree.exists()
    assert child_worktree.resolve(strict=False) in _worktree_roots(master_repo)

    child_forced = _remove_worktree(child_worktree, force=True)
    child_forced_output = capsys.readouterr()

    assert child_forced == 0, child_forced_output.err
    assert "uncommitted changes" in child_forced_output.err
    assert "data loss" in child_forced_output.err
    assert child_forced_output.out.strip() == str(child_worktree.resolve(strict=False))
    assert not child_worktree.exists()
    assert child_worktree.resolve(strict=False) not in _worktree_roots(master_repo)
    assert parent_worktree.resolve(strict=False) in _worktree_roots(master_repo)

    parent_removed = _remove_worktree(parent_worktree, force=False)
    parent_removed_output = capsys.readouterr()

    assert parent_removed == 0, parent_removed_output.err
    assert parent_removed_output.err == ""
    assert parent_removed_output.out.strip() == str(parent_worktree.resolve(strict=False))
    assert not parent_worktree.exists()
    assert parent_worktree.resolve(strict=False) not in _worktree_roots(master_repo)
