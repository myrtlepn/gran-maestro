from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MST = REPO_ROOT / "scripts" / "mst.py"
AGI_ID = "AGI-999"
SPRINT = 5
SPRINT_BRANCH = "gran-maestro/AGI-999/sprint-5-test"


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


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit_file(repo_root: Path, relative_path: str, content: str, message: str, *, cwd: Optional[Path] = None) -> None:
    target_root = cwd or repo_root
    _write_file(target_root / relative_path, content)
    add = _run_git(repo_root, "add", relative_path, cwd=target_root)
    assert add.returncode == 0, add.stderr
    commit = _run_git(repo_root, "commit", "-m", message, cwd=target_root)
    assert commit.returncode == 0, commit.stderr


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = _run_git(repo_root, "branch", "--list", branch)
    assert result.returncode == 0, result.stderr
    return bool(result.stdout.strip())


def _sprint_log(repo_root: Path) -> list[dict]:
    path = repo_root / ".gran-maestro" / "agile" / AGI_ID / "sprint-log.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sprint_repo(tmp_path: Path) -> Path:
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
    return repo_root


def _create_sprint_branch(repo_root: Path, content: str = "sprint 5\n") -> None:
    checkout = _run_git(repo_root, "checkout", "-b", SPRINT_BRANCH, "master")
    assert checkout.returncode == 0, checkout.stderr
    _commit_file(repo_root, "app.txt", content, "sprint work")
    back = _run_git(repo_root, "checkout", "master")
    assert back.returncode == 0, back.stderr


def _squash_sprint_to_master(repo_root: Path, branch: str = SPRINT_BRANCH) -> str:
    checkout = _run_git(repo_root, "checkout", "master")
    assert checkout.returncode == 0, checkout.stderr
    merge = _run_git(repo_root, "merge", "--squash", branch)
    assert merge.returncode == 0, merge.stderr
    commit = _run_git(
        repo_root,
        "commit",
        "-m",
        f"[{AGI_ID} Sprint {SPRINT}] squash-merged: test",
    )
    assert commit.returncode == 0, commit.stderr
    sha = _run_git(repo_root, "rev-parse", "HEAD")
    assert sha.returncode == 0, sha.stderr
    return sha.stdout.strip()


def test_closes_sprint_with_branch_only(sprint_repo: Path) -> None:
    _create_sprint_branch(sprint_repo)
    squash_sha = _squash_sprint_to_master(sprint_repo)

    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["status"] == "closed"
    assert payload["branch_deleted"] is True
    assert payload["worktree_removed"] is False
    assert payload["squash_commit_sha"] == squash_sha
    assert not _branch_exists(sprint_repo, SPRINT_BRANCH)


def test_idempotent_rerun(sprint_repo: Path) -> None:
    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["status"] == "already_closed"
    assert payload["branch_deleted"] is False
    assert payload["worktree_removed"] is False


def test_aborts_on_tree_mismatch(sprint_repo: Path) -> None:
    _create_sprint_branch(sprint_repo, "sprint before squash\n")
    _squash_sprint_to_master(sprint_repo)
    checkout = _run_git(sprint_repo, "checkout", SPRINT_BRANCH)
    assert checkout.returncode == 0, checkout.stderr
    _commit_file(sprint_repo, "app.txt", "sprint after squash\n", "late sprint work")
    back = _run_git(sprint_repo, "checkout", "master")
    assert back.returncode == 0, back.stderr

    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--json",
    )

    assert result.returncode != 0
    assert "tree mismatch" in result.stderr
    assert _branch_exists(sprint_repo, SPRINT_BRANCH)
    assert _sprint_log(sprint_repo)[-1]["status"] == "aborted_tree_mismatch"


def test_removes_worktree_and_branch(sprint_repo: Path) -> None:
    worktree_path = sprint_repo / ".gran-maestro" / "worktrees" / AGI_ID / f"sprint-{SPRINT}"
    add_worktree = _run_git(
        sprint_repo,
        "worktree",
        "add",
        "-b",
        SPRINT_BRANCH,
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    _commit_file(sprint_repo, "app.txt", "sprint worktree\n", "sprint worktree work", cwd=worktree_path)
    _squash_sprint_to_master(sprint_repo)

    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["status"] == "closed"
    assert payload["branch_deleted"] is True
    assert payload["worktree_removed"] is True
    worktrees = _run_git(sprint_repo, "worktree", "list")
    assert worktrees.returncode == 0, worktrees.stderr
    assert str(worktree_path) not in worktrees.stdout
    assert not _branch_exists(sprint_repo, SPRINT_BRANCH)
    branch = _run_git(sprint_repo, "branch", "--show-current")
    assert branch.stdout.strip() == "master"


def test_dry_run(sprint_repo: Path) -> None:
    worktree_path = sprint_repo / ".gran-maestro" / "worktrees" / AGI_ID / f"sprint-{SPRINT}"
    add_worktree = _run_git(
        sprint_repo,
        "worktree",
        "add",
        "-b",
        SPRINT_BRANCH,
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr
    _commit_file(sprint_repo, "app.txt", "dry run sprint\n", "dry run sprint work", cwd=worktree_path)
    _squash_sprint_to_master(sprint_repo)

    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--dry-run",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["dry_run"] is True
    assert payload["status"] == "dry_run"
    assert any("remove worktree" in action for action in payload["actions"])
    assert any("delete branch" in action for action in payload["actions"])
    assert _branch_exists(sprint_repo, SPRINT_BRANCH)
    assert worktree_path.exists()
    assert not (sprint_repo / ".gran-maestro" / "agile" / AGI_ID / "sprint-log.json").exists()


def test_performs_squash_merge(sprint_repo: Path) -> None:
    _create_sprint_branch(sprint_repo, "needs squash\n")

    result = _run_mst(
        sprint_repo,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(SPRINT),
        "--base",
        "master",
        "--branch",
        SPRINT_BRANCH,
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["status"] == "closed"
    assert payload["branch_deleted"] is True
    assert payload["squash_commit_sha"]
    assert not _branch_exists(sprint_repo, SPRINT_BRANCH)
    log = _run_git(sprint_repo, "log", "-1", "--format=%s")
    assert log.stdout.strip() == f"[{AGI_ID} Sprint {SPRINT}] squash-merged: (자동 생성)"
    assert (sprint_repo / "app.txt").read_text(encoding="utf-8") == "needs squash\n"
