from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds import agile, worktree


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATTERNS = (
    re.compile(r"git checkout -b \"\$REQ_BRANCH\""),
    re.compile(r"git checkout -b gran-maestro/REQ-NNN"),
    re.compile(r"git -C \{PROJECT_ROOT\} checkout"),
    re.compile(r"git -C \{PROJECT_ROOT\} merge --squash"),
    re.compile(r"git -C \{PROJECT_ROOT\} merge --no-ff"),
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _commit(repo: Path, path: str, content: str, message: str, cwd: Path | None = None) -> None:
    target_root = cwd or repo
    target = target_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    add = _git(target_root, "add", path)
    assert add.returncode == 0, add.stderr
    commit = _git(target_root, "commit", "-m", message)
    assert commit.returncode == 0, commit.stderr


@pytest.fixture
def sprint_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init").returncode == 0
    assert _git(repo, "config", "user.email", "tester@example.com").returncode == 0
    assert _git(repo, "config", "user.name", "Test User").returncode == 0
    _commit(repo, "app.txt", "base\n", "initial")
    assert _git(repo, "branch", "-M", "master").returncode == 0
    (repo / ".gran-maestro").mkdir()
    monkeypatch.setattr(_common, "BASE_DIR", repo / ".gran-maestro")
    return repo


def _current_branch(repo: Path) -> str:
    result = _git(repo, "branch", "--show-current")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_sprint_close_preserves_original_project_root_branch(sprint_repo: Path) -> None:
    assert _git(sprint_repo, "checkout", "-b", "feature/original").returncode == 0
    assert _git(sprint_repo, "checkout", "-b", "gran-maestro/AGI-026/sprint-1", "master").returncode == 0
    _commit(sprint_repo, "app.txt", "sprint\n", "sprint work")
    assert _git(sprint_repo, "checkout", "feature/original").returncode == 0

    before = _current_branch(sprint_repo)
    exit_code = agile.cmd_agile_sprint_close(
        argparse.Namespace(
            agi_id="AGI-026",
            sprint=1,
            base="master",
            branch="gran-maestro/AGI-026/sprint-1",
            worktree_path=None,
            dry_run=False,
            json=True,
            message=None,
        )
    )
    after = _current_branch(sprint_repo)

    assert exit_code == 0
    assert after == before, f"branch invariant violated: before={before} after={after} role=sprint-close"
    assert (sprint_repo / "app.txt").read_text(encoding="utf-8") == "base\n"
    assert _git(sprint_repo, "rev-parse", "master^0").returncode == 0


def test_dirty_root_preserved_by_sprint_close(sprint_repo: Path) -> None:
    assert _git(sprint_repo, "checkout", "-b", "feature/dirty-root").returncode == 0
    dirty_path = sprint_repo / "dirty.txt"
    dirty_path.write_text("dirty\n", encoding="utf-8")
    assert _git(sprint_repo, "checkout", "-b", "gran-maestro/AGI-026/sprint-2", "master").returncode == 0
    _commit(sprint_repo, "app.txt", "sprint 2\n", "sprint work 2")
    assert _git(sprint_repo, "checkout", "feature/dirty-root").returncode == 0

    before = _current_branch(sprint_repo)
    exit_code = agile.cmd_agile_sprint_close(
        argparse.Namespace(
            agi_id="AGI-026",
            sprint=2,
            base="master",
            branch="gran-maestro/AGI-026/sprint-2",
            worktree_path=None,
            dry_run=False,
            json=True,
            message=None,
        )
    )

    assert exit_code == 0
    assert _current_branch(sprint_repo) == before
    assert dirty_path.read_text(encoding="utf-8") == "dirty\n"
    status = _git(sprint_repo, "status", "--short").stdout
    assert "?? dirty.txt" in status


def test_forbidden_checkout_patterns_are_absent() -> None:
    paths = [
        *(ROOT / "skills").glob("*/SKILL.md"),
        *(ROOT / "scripts" / "mst_cmds").glob("*.py"),
    ]
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in FORBIDDEN_PATTERNS):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}:{line.strip()}")

    assert violations == []


def test_worktree_path_cli_is_deterministic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    gm_dir = tmp_path / "repo" / ".gran-maestro"
    gm_dir.mkdir(parents=True)
    monkeypatch.setattr(_common, "BASE_DIR", gm_dir)

    exit_code = worktree.cmd_worktree_path(
        argparse.Namespace(req="REQ-776", role="accept", agi="AGI-026")
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip().endswith(".gran-maestro/worktrees/AGI-026/REQ-776/accept")
