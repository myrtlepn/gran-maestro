from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = REPO_ROOT / "scripts" / "playbooks" / "cukestill-sprint-cleanup.sh"
AGI = "AGI-999"
SPRINT_BRANCH = f"gran-maestro/{AGI}/sprint-5"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_playbook(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PLAYBOOK), "--repo", str(repo), "--agi", AGI, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_git_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr or result.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _assert_git_ok(_git(repo, "init"))
    _assert_git_ok(_git(repo, "config", "user.email", "tester@example.com"))
    _assert_git_ok(_git(repo, "config", "user.name", "Test User"))
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _assert_git_ok(_git(repo, "add", "README.md"))
    _assert_git_ok(_git(repo, "commit", "-m", "initial commit"))
    _assert_git_ok(_git(repo, "branch", "-M", "master"))
    return repo


def _create_matching_sprint(repo: Path) -> None:
    _assert_git_ok(_git(repo, "checkout", "-b", SPRINT_BRANCH, "master"))
    (repo / "feature.txt").write_text("sprint 5\n", encoding="utf-8")
    _assert_git_ok(_git(repo, "add", "feature.txt"))
    _assert_git_ok(_git(repo, "commit", "-m", "sprint 5 work"))
    _assert_git_ok(_git(repo, "checkout", "master"))
    _assert_git_ok(_git(repo, "merge", "--squash", SPRINT_BRANCH))
    _assert_git_ok(_git(repo, "commit", "-m", f"[{AGI} Sprint 5] squash-merged"))


def _branch_exists(repo: Path, branch: str = SPRINT_BRANCH) -> bool:
    result = _git(repo, "branch", "--list", branch)
    assert result.returncode == 0, result.stderr
    return bool(result.stdout.strip())


def _current_branch(repo: Path) -> str:
    result = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_dry_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_matching_sprint(repo)

    result = _run_playbook(repo, "--sprints", "5", "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["planned_deletes"] == [SPRINT_BRANCH]
    assert payload["deleted"] == []
    assert payload["skipped"] == []
    assert payload["dry_run"] is True
    assert _branch_exists(repo)
    assert list((repo / ".gran-maestro" / "agile" / AGI).glob("cleanup-playbook-*.log"))


def test_actual_cleanup(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_matching_sprint(repo)

    result = _run_playbook(repo, "--sprints", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["deleted"] == [SPRINT_BRANCH]
    assert payload["planned_deletes"] == []
    assert payload["skipped"] == []
    assert not _branch_exists(repo)
    assert _current_branch(repo) == "master"


def test_skip_on_tree_mismatch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_matching_sprint(repo)
    _assert_git_ok(_git(repo, "checkout", SPRINT_BRANCH))
    (repo / "feature.txt").write_text("sprint 5 changed after squash\n", encoding="utf-8")
    _assert_git_ok(_git(repo, "add", "feature.txt"))
    _assert_git_ok(_git(repo, "commit", "-m", "post squash branch change"))
    _assert_git_ok(_git(repo, "checkout", "master"))

    result = _run_playbook(repo, "--sprints", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["deleted"] == []
    assert payload["planned_deletes"] == []
    assert payload["skipped"] == [{"branch": SPRINT_BRANCH, "reason": "tree_mismatch"}]
    assert _branch_exists(repo)


def test_aborts_on_dirty_primary(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _create_matching_sprint(repo)
    _assert_git_ok(_git(repo, "checkout", SPRINT_BRANCH))
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    result = _run_playbook(repo, "--sprints", "5", "--json")

    assert result.returncode != 0
    assert "uncommitted changes in primary worktree" in result.stderr
    assert _branch_exists(repo)
    assert _current_branch(repo) == SPRINT_BRANCH
