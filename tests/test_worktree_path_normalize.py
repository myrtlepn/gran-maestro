from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds.worktree import _find_nested_worktree_root, _normalize_target_path



def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def existing_worktree(tmp_path: Path) -> Path:
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

    worktree_path = repo_root / "external-wt" / "A"
    add_worktree = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        "feature/existing-worktree",
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    return worktree_path



def test_normalize_target_path_resolves_symlink(existing_worktree: Path, tmp_path: Path) -> None:
    symlink_target = tmp_path / "alias-to-nested"
    symlink_target.symlink_to(existing_worktree / "nested-wt", target_is_directory=True)

    normalized_root = _normalize_target_path(existing_worktree)
    nested_root = _find_nested_worktree_root(symlink_target, [existing_worktree])

    assert nested_root == normalized_root



def test_normalize_target_path_ignores_trailing_slash(existing_worktree: Path) -> None:
    nested_target = Path(f"{existing_worktree}/nested-wt/")

    normalized_root = _normalize_target_path(f"{existing_worktree}/")
    nested_root = _find_nested_worktree_root(nested_target, [f"{existing_worktree}/"])

    assert nested_root == normalized_root



def test_normalize_target_path_matches_relative_path(existing_worktree: Path, monkeypatch) -> None:
    monkeypatch.chdir(existing_worktree.parent.parent)

    normalized_root = _normalize_target_path(existing_worktree)
    nested_root = _find_nested_worktree_root(Path("external-wt/A/nested-wt"), [existing_worktree])

    assert nested_root == normalized_root
