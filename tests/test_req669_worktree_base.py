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
    assert worktree.req_branch_name("REQ-779", "feature/branch-rules", "AGI-026") == (
        "gran-maestro/feature-branch-rules/AGI-026/REQ-779"
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
    assert worktree.task_branch_name("REQ-779", "T01", "feature/x", "AGI-026") == (
        "gran-maestro/feature-x/AGI-026/REQ-779-T01"
    )


def test_role_branch_names_are_deterministic() -> None:
    assert worktree.role_branch_name("REQ-069", "integration", "feature/x") == (
        "gran-maestro/feature-x/REQ-069"
    )
    assert worktree.role_branch_name("REQ-069", "accept", "feature/x") == (
        "gran-maestro/feature-x/REQ-069-accept"
    )
    assert worktree.role_branch_name("REQ-779", "integration", "feature/x", "AGI-026") == (
        "gran-maestro/feature-x/AGI-026/REQ-779"
    )
    assert worktree.role_branch_name("REQ-779", "accept", "feature/x", "AGI-026") == (
        "gran-maestro/feature-x/AGI-026/REQ-779-accept"
    )
    assert worktree.role_branch_name("REQ-779", "review-RV-001", "feature/x", "AGI-026") == (
        "gran-maestro/feature-x/AGI-026/REQ-779-review-RV-001"
    )


def test_role_worktree_paths_are_deterministic() -> None:
    project_root = Path("/repo")
    assert worktree.role_worktree_path(project_root, "REQ-069", "integration") == (
        project_root / ".gran-maestro" / "worktrees" / "REQ-069" / "integration"
    )
    assert worktree.role_worktree_path(project_root, "REQ-069", "accept", "AGI-026") == (
        project_root / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-069" / "accept"
    )
    assert worktree.role_worktree_path(project_root, "REQ-069", "review-RV-001", "AGI-026") == (
        project_root / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-069" / "review" / "RV-001"
    )


def test_ac007_detected_base_persisted_on_success(repo: Path) -> None:
    assert _run_git(repo, "checkout", "-b", "feature/x").returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))

    assert exit_code == 0
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert request_data.get("detected_base") == "feature/x"


@pytest.mark.parametrize(
    "branch",
    [
        "gran-maestro/session/MST-AGI-038-20260515T010203004Z-abc12345",
        "gran-maestro/feature-x/REQ-069",
        "gran-maestro/feature-x/REQ-069-T01",
        "gran-maestro/feature-x/REQ-069-accept",
    ],
)
def test_rejects_mst_temporary_branches_without_mutating_request(repo: Path, capsys, branch: str) -> None:
    assert _run_git(repo, "checkout", "-b", branch).returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "MST 임시 브랜치" in captured.err
    assert "사용자 기준 브랜치" in captured.err
    assert "master" not in captured.err
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert "detected_base" not in request_data


def test_detached_head_is_rejected_without_detected_base_mutation(repo: Path, capsys) -> None:
    assert _run_git(repo, "checkout", "--detach").returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "detached HEAD" in captured.err
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert "detected_base" not in request_data


def test_unborn_branch_is_rejected_without_detected_base_mutation(tmp_path: Path, monkeypatch, capsys) -> None:
    repo_root = tmp_path / "repo-unborn"
    repo_root.mkdir()

    assert _run_git(repo_root, "init").returncode == 0
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0

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

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.err
    request_data = json.loads((request_dir / "request.json").read_text(encoding="utf-8"))
    assert "detected_base" not in request_data


@pytest.mark.parametrize("branch", ["gran-maestro-feature", "feature/gran-maestro"])
def test_gran_maestro_like_user_branches_are_not_false_positives(repo: Path, capsys, branch: str) -> None:
    assert _run_git(repo, "checkout", "-b", branch).returncode == 0

    exit_code = worktree.cmd_worktree_resolve_base(argparse.Namespace(req="REQ-069", json=False))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.out.strip() == branch
    request_data = json.loads(
        (repo / ".gran-maestro" / "requests" / "REQ-069" / "request.json").read_text(encoding="utf-8")
    )
    assert request_data["detected_base"] == branch


def test_branch_name_cli_accepts_agi_namespace(capsys) -> None:
    exit_code = worktree.cmd_worktree_branch_name(
        argparse.Namespace(req="REQ-779", base="feature/x", task=None, role="integration", agi="AGI-026")
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == "gran-maestro/feature-x/AGI-026/REQ-779"


def test_collision_reusable_existing_worktree(repo: Path) -> None:
    path = repo / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-779" / "integration"
    branch = "gran-maestro/main/AGI-026/REQ-779"
    assert _run_git(repo, "worktree", "add", "-b", branch, str(path), "main").returncode == 0

    assert worktree.classify_worktree_collision(repo, path, branch) == "reusable_existing_worktree"


def test_collision_stale_orphan_cleanup_required(repo: Path) -> None:
    path = repo / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-779" / "accept"
    branch = "gran-maestro/main/AGI-026/REQ-779-accept"
    assert _run_git(repo, "branch", branch, "main").returncode == 0

    assert worktree.classify_worktree_collision(repo, path, branch) == "stale_orphan_cleanup_required"


def test_collision_dirty_worktree_manual_conflict(repo: Path) -> None:
    path = repo / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-779" / "integration"
    branch = "gran-maestro/main/AGI-026/REQ-779"
    assert _run_git(repo, "worktree", "add", "-b", branch, str(path), "main").returncode == 0
    (path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    assert worktree.classify_worktree_collision(repo, path, branch) == "dirty_worktree_manual_conflict"


def test_collision_fatal_conflict(repo: Path) -> None:
    path = repo / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-779" / "integration"
    path.mkdir(parents=True)

    assert worktree.classify_worktree_collision(repo, path, "gran-maestro/main/AGI-026/REQ-779") == "fatal_conflict"


def test_collision_classifier_does_not_generate_suffix(repo: Path) -> None:
    path = repo / ".gran-maestro" / "worktrees" / "AGI-026" / "REQ-779" / "accept"
    branch = "gran-maestro/main/AGI-026/REQ-779-accept"
    assert _run_git(repo, "branch", branch, "main").returncode == 0

    classification = worktree.classify_worktree_collision(repo, path, branch)

    assert classification == "stale_orphan_cleanup_required"
    assert "-1" not in classification
    assert "uuid" not in classification
    assert "timestamp" not in classification
    assert "random" not in classification
