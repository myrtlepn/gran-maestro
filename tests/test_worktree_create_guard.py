from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common, worktree
from scripts.mst_cmds.worktree import cmd_worktree_create



def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )



def _write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


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
    _write_file(
        repo_root / ".claude" / "hooks" / "mst-session-init.sh",
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _write_file(
        repo_root / ".claude" / "hooks" / "mst-stop-hook.sh",
        "#!/usr/bin/env bash\nexit 0\n",
        executable=True,
    )
    _write_file(
        repo_root / ".claude" / "settings.local.json",
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"]}}, ensure_ascii=False, indent=2),
    )

    return repo_root


@pytest.fixture
def existing_worktree(master_repo: Path) -> Path:
    worktree_path = master_repo / "external-wt" / "A"
    add_worktree = _run_git(
        master_repo,
        "worktree",
        "add",
        "-b",
        "feature/existing-worktree",
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    (worktree_path / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return worktree_path



def test_nested_target_blocked(existing_worktree: Path, master_repo: Path, monkeypatch, capsys) -> None:
    nested_target = existing_worktree / "nested-wt"

    monkeypatch.setattr(_common, "BASE_DIR", existing_worktree / ".gran-maestro")
    monkeypatch.chdir(existing_worktree)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(nested_target),
            branch="feature/nested-worktree",
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "nested worktree path detected" in captured.err
    assert str(nested_target) in captured.err
    assert f"기존 worktree {existing_worktree}의 내부" in captured.err
    assert f"master({master_repo})" in captured.err
    assert not nested_target.exists()



def test_master_cwd_forced_from_worktree(
    existing_worktree: Path,
    master_repo: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    target_path = tmp_path / "outside-worktree"
    add_invocations: list[str | None] = []
    real_run = subprocess.run

    def traced_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if cmd[:3] == ["git", "worktree", "add"]:
            add_invocations.append(kwargs.get("cwd"))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(worktree.subprocess, "run", traced_run)
    monkeypatch.setattr(_common, "BASE_DIR", existing_worktree / ".gran-maestro")
    monkeypatch.chdir(existing_worktree)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(target_path),
            branch="feature/from-linked-worktree",
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(target_path)
    assert target_path.exists()
    assert add_invocations == [str(master_repo)]
