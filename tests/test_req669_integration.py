from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.mst_cmds.branch_strategy import (
    current_branch,
    is_protected_branch,
    make_req_branch_name,
    slugify_base_branch,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
DEFAULT_PROTECTED_BRANCHES = ["main", "master", "release/*"]


@dataclass(frozen=True)
class ApproveResult:
    allowed: bool
    base_branch: str
    req_branch: str | None
    message: str


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo_root: Path, *args: str) -> str:
    result = _run_git(repo_root, *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _write(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_sandbox_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "sandbox-repo"
    repo_root.mkdir()

    assert _run_git(repo_root, "init").returncode == 0
    assert _run_git(repo_root, "config", "user.email", "tester@example.com").returncode == 0
    assert _run_git(repo_root, "config", "user.name", "Test User").returncode == 0

    _write(repo_root, "README.md", "# sandbox\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial commit")
    _git(repo_root, "branch", "-M", "main")
    _git(repo_root, "branch", "master", "main")

    (repo_root / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    return repo_root


def _branch_exists(repo_root: Path, branch: str) -> bool:
    result = _run_git(repo_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return result.returncode == 0


def _branches(repo_root: Path) -> set[str]:
    output = _git(repo_root, "branch", "--format=%(refname:short)")
    return {line.strip() for line in output.splitlines() if line.strip()}


def _approve_in_sandbox(
    repo_root: Path,
    req_id: str,
    protected_branches: list[str],
) -> ApproveResult:
    base_branch = current_branch(repo_root)
    if is_protected_branch(base_branch, protected_branches):
        return ApproveResult(
            allowed=False,
            base_branch=base_branch,
            req_branch=None,
            message=f"{base_branch} is protected; checkout a feature branch before approve",
        )

    req_branch = make_req_branch_name(req_id, base_branch)
    _git(repo_root, "checkout", "-b", req_branch, base_branch)
    return ApproveResult(
        allowed=True,
        base_branch=base_branch,
        req_branch=req_branch,
        message=f"created {req_branch}",
    )


def _accept_in_sandbox(repo_root: Path, req_id: str, approval: ApproveResult) -> None:
    assert approval.allowed
    assert approval.req_branch is not None
    _git(repo_root, "checkout", approval.base_branch)
    _git(repo_root, "merge", "--squash", approval.req_branch)
    _git(repo_root, "commit", "-m", f"[{req_id}] integration squash")


def _run_mst(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def test_feature_branch_approve_accept_squashes_to_detected_base(tmp_path: Path) -> None:
    repo_root = _init_sandbox_repo(tmp_path)
    _git(repo_root, "checkout", "-b", "feature/demo-epic", "main")

    feature_base_sha = _git(repo_root, "rev-parse", "feature/demo-epic")
    master_before_sha = _git(repo_root, "rev-parse", "master")

    assert current_branch(repo_root) == "feature/demo-epic"
    assert slugify_base_branch("feature/demo-epic") == "feature-demo-epic"
    assert make_req_branch_name("REQ-701", "feature/demo-epic") == (
        "gran-maestro/feature-demo-epic/REQ-701"
    )
    assert not is_protected_branch(current_branch(repo_root), DEFAULT_PROTECTED_BRANCHES)

    approval = _approve_in_sandbox(repo_root, "REQ-701", DEFAULT_PROTECTED_BRANCHES)
    assert approval.allowed
    assert approval.base_branch == "feature/demo-epic"
    assert approval.req_branch == "gran-maestro/feature-demo-epic/REQ-701"
    assert current_branch(repo_root) == approval.req_branch

    _write(repo_root, "implementation.txt", "done\n")
    _git(repo_root, "add", "implementation.txt")
    _git(repo_root, "commit", "-m", "implement REQ-701")

    _accept_in_sandbox(repo_root, "REQ-701", approval)

    assert current_branch(repo_root) == "feature/demo-epic"
    assert _git(repo_root, "rev-list", "--count", f"{feature_base_sha}..feature/demo-epic") == "1"
    assert _git(repo_root, "log", "-1", "--pretty=%s") == "[REQ-701] integration squash"
    assert _git(repo_root, "rev-parse", "master") == master_before_sha


def test_protected_branch_helper_blocks_main_and_release_without_creating_req_branch(
    tmp_path: Path,
) -> None:
    repo_root = _init_sandbox_repo(tmp_path)
    _git(repo_root, "checkout", "-b", "release/v1.2", "main")

    scenarios = [
        ("main", "REQ-702", "gran-maestro/main/REQ-702"),
        ("release/v1.2", "REQ-703", "gran-maestro/release-v1.2/REQ-703"),
    ]

    for branch, req_id, forbidden_req_branch in scenarios:
        _git(repo_root, "checkout", branch)
        assert is_protected_branch(current_branch(repo_root), DEFAULT_PROTECTED_BRANCHES)

        approval = _approve_in_sandbox(repo_root, req_id, DEFAULT_PROTECTED_BRANCHES)

        assert not approval.allowed
        assert approval.req_branch is None
        assert "protected" in approval.message
        assert not _branch_exists(repo_root, forbidden_req_branch)


def test_config_resolve_populates_protected_branches_for_legacy_base_only_config(
    tmp_path: Path,
) -> None:
    repo_root = _init_sandbox_repo(tmp_path)
    config_path = repo_root / ".gran-maestro" / "config.json"
    config_path.write_text(
        json.dumps({"worktree": {"base_branch": "main"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    resolved = _run_mst(repo_root, "config", "resolve")

    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    resolved_config = json.loads(
        (repo_root / ".gran-maestro" / "config.resolved.json").read_text(encoding="utf-8")
    )
    assert resolved_config["worktree"]["base_branch"] == "main"
    assert resolved_config["worktree"]["protected_branches"] == DEFAULT_PROTECTED_BRANCHES

    _git(repo_root, "checkout", "-b", "feature/legacy-base", "main")
    approval = _approve_in_sandbox(
        repo_root,
        "REQ-704",
        resolved_config["worktree"]["protected_branches"],
    )

    assert approval.allowed
    assert approval.req_branch == "gran-maestro/feature-legacy-base/REQ-704"
    assert _branch_exists(repo_root, "gran-maestro/feature-legacy-base/REQ-704")


def test_req_branch_names_are_unique_across_base_slugs_and_legacy_flat_branch(
    tmp_path: Path,
) -> None:
    repo_root = _init_sandbox_repo(tmp_path)
    _git(repo_root, "branch", "gran-maestro/REQ-705", "main")

    main_approval = _approve_in_sandbox(repo_root, "REQ-705", protected_branches=[])
    assert main_approval.allowed
    assert main_approval.req_branch == "gran-maestro/main/REQ-705"

    _git(repo_root, "checkout", "main")
    _git(repo_root, "checkout", "-b", "feature/x", "main")
    feature_approval = _approve_in_sandbox(repo_root, "REQ-706", protected_branches=[])

    assert feature_approval.allowed
    assert feature_approval.req_branch == "gran-maestro/feature-x/REQ-706"
    assert {
        "gran-maestro/REQ-705",
        "gran-maestro/main/REQ-705",
        "gran-maestro/feature-x/REQ-706",
    }.issubset(_branches(repo_root))


def test_default_config_declares_protected_branch_defaults() -> None:
    defaults = json.loads(
        (REPO_ROOT / "templates" / "defaults" / "config.json").read_text(encoding="utf-8")
    )

    assert defaults["worktree"]["protected_branches"] == DEFAULT_PROTECTED_BRANCHES


def test_frontend_settings_spec_is_reRunnable_when_present() -> None:
    settings_spec = REPO_ROOT / "frontend" / "e2e" / "settings.spec.ts"
    if not settings_spec.exists():
        pytest.skip("frontend/e2e/settings.spec.ts is absent in this worktree")

    frontend_dir = REPO_ROOT / "frontend"
    if not (frontend_dir / "node_modules" / "@playwright" / "test").exists():
        pytest.skip("frontend/@playwright/test is not installed — run `npm install` in frontend/")

    result = subprocess.run(
        ["npx", "playwright", "test", "e2e/settings.spec.ts"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
