from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds import worktree


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    assert _run_git(repo_root, "init").returncode == 0
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0
    assert _run_git(repo_root, "commit", "--allow-empty", "-m", "initial").returncode == 0
    assert _run_git(repo_root, "branch", "-M", "main").returncode == 0

    gm_dir = repo_root / ".gran-maestro"
    request_dir = gm_dir / "requests" / "REQ-069"
    request_dir.mkdir(parents=True)
    (request_dir / "request.json").write_text(
        json.dumps({"id": "REQ-069"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (gm_dir / "config.resolved.json").write_text(
        json.dumps(
            {"worktree": {"protected_branches": ["main", "master", "release/*"]}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(_common, "BASE_DIR", gm_dir)
    monkeypatch.chdir(repo_root)
    return repo_root


def test_ac001_resolve_base_detects_head_and_saves_request(repo: Path, capsys) -> None:
    assert _run_git(repo, "checkout", "-b", "feature/branch-rules").returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.out.strip() == "feature/branch-rules"
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert request_data["detected_base"] == "feature/branch-rules"


def test_ac002_main_protected_blocks_without_branch_side_effect(repo: Path, capsys) -> None:
    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "다른 브랜치로 이동" in captured.err
    branches = _run_git(repo, "branch", "--format=%(refname:short)").stdout.splitlines()
    assert "gran-maestro/main/REQ-069" not in branches
    assert "gran-maestro/REQ-069" not in branches


def test_ac003_release_glob_is_protected(repo: Path, capsys) -> None:
    assert _run_git(repo, "checkout", "-b", "release/v1.2").returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "release/*" in captured.err


def test_ac004_req_branch_name_uses_base_slug() -> None:
    assert worktree.req_branch_name("REQ-NNN", "feature/branch-rules") == (
        "gran-maestro/feature-branch-rules/REQ-NNN"
    )


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("user/bran/experiment", "user-bran-experiment"),
        ("feature/x", "feature-x"),
        ("main", "main"),
    ],
)
def test_ac005_base_slug_replaces_only_slashes(base: str, expected: str) -> None:
    assert worktree.base_slug(base) == expected


def test_ac006_task_worktree_branch_and_base_names() -> None:
    assert worktree.req_branch_name("REQ-069", "feature/x") == "gran-maestro/feature-x/REQ-069"
    assert worktree.task_branch_name("REQ-069", "T01", "feature/x") == (
        "gran-maestro/feature-x/REQ-069-T01"
    )


def test_ac007_detected_base_persisted_on_success(repo: Path) -> None:
    assert _run_git(repo, "checkout", "-b", "feature/x").returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))

    assert exit_code == 0
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert request_data.get("detected_base") == "feature/x"
