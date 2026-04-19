from __future__ import annotations

from pathlib import Path

from scripts.tests.test_agile_sprint_close import (
    AGI_ID,
    _branch_exists,
    _commit_file,
    _json_stdout,
    _run_git,
    _run_mst,
    _sprint_log,
)


def _sprint_branch(sprint: int) -> str:
    return f"gran-maestro/{AGI_ID}/sprint-{sprint}"


def _sprint_worktree(repo_root: Path, sprint: int) -> Path:
    return repo_root / ".gran-maestro" / "worktrees" / AGI_ID / f"sprint-{sprint}"


def _current_branch(repo_root: Path) -> str:
    result = _run_git(repo_root, "branch", "--show-current")
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    init = _run_git(repo_root, "init")
    assert init.returncode == 0, init.stderr or init.stdout
    email = _run_git(repo_root, "config", "user.email", "tester@example.com")
    assert email.returncode == 0, email.stderr or email.stdout
    name = _run_git(repo_root, "config", "user.name", "Test User")
    assert name.returncode == 0, name.stderr or name.stdout

    _commit_file(repo_root, "app.txt", "base\n", "initial commit")
    rename = _run_git(repo_root, "branch", "-M", "master")
    assert rename.returncode == 0, rename.stderr or rename.stdout
    (repo_root / ".gran-maestro").mkdir()
    return repo_root


def _create_sprint_worktree_and_squash(repo_root: Path, sprint: int) -> None:
    branch = _sprint_branch(sprint)
    worktree_path = _sprint_worktree(repo_root, sprint)

    add_worktree = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
        "master",
    )
    assert add_worktree.returncode == 0, add_worktree.stderr or add_worktree.stdout

    _commit_file(
        repo_root,
        f"sprints/sprint-{sprint}.txt",
        f"sprint {sprint}\n",
        f"sprint {sprint} work",
        cwd=worktree_path,
    )

    checkout = _run_git(repo_root, "checkout", "master")
    assert checkout.returncode == 0, checkout.stderr or checkout.stdout
    merge = _run_git(repo_root, "merge", "--squash", branch)
    assert merge.returncode == 0, merge.stderr or merge.stdout
    commit = _run_git(
        repo_root,
        "commit",
        "-m",
        f"[{AGI_ID} Sprint {sprint}] squash-merged: integration",
    )
    assert commit.returncode == 0, commit.stderr or commit.stdout


def _create_three_sprints(repo_root: Path) -> None:
    for sprint in (1, 2, 3):
        _create_sprint_worktree_and_squash(repo_root, sprint)


def _close_sprint(repo_root: Path, sprint: int):
    result = _run_mst(
        repo_root,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        str(sprint),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    return _json_stdout(result)


def _assert_all_sprints_removed(repo_root: Path) -> None:
    for sprint in (1, 2, 3):
        assert not _branch_exists(repo_root, _sprint_branch(sprint))
        assert not _sprint_worktree(repo_root, sprint).exists()


def test_end_to_end_three_sprints(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _create_three_sprints(repo_root)

    payloads = [_close_sprint(repo_root, sprint) for sprint in (1, 2, 3)]

    assert [payload["status"] for payload in payloads] == ["closed", "closed", "closed"]
    assert all(payload["branch_deleted"] is True for payload in payloads)
    assert all(payload["worktree_removed"] is True for payload in payloads)
    _assert_all_sprints_removed(repo_root)
    assert _current_branch(repo_root) == "master"
    log = _sprint_log(repo_root)
    assert [entry["sprint"] for entry in log] == [1, 2, 3]
    assert [entry["status"] for entry in log] == ["closed", "closed", "closed"]


def test_reentrant_after_close(tmp_path: Path) -> None:
    repo_root = _init_repo(tmp_path)
    _create_three_sprints(repo_root)
    for sprint in (1, 2, 3):
        _close_sprint(repo_root, sprint)

    result = _run_mst(
        repo_root,
        "agile",
        "sprint-close",
        AGI_ID,
        "--sprint",
        "1",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = _json_stdout(result)
    assert payload["status"] == "already_closed"
    assert payload["branch_deleted"] is False
    assert payload["worktree_removed"] is False
    _assert_all_sprints_removed(repo_root)
    assert _current_branch(repo_root) == "master"
    log = _sprint_log(repo_root)
    assert [entry["status"] for entry in log] == ["closed", "closed", "closed", "already_closed"]
    assert [entry["sprint"] for entry in log] == [1, 2, 3, 1]
