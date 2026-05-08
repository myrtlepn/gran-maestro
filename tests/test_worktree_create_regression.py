from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
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
        json.dumps(
            {
                "permissions": {"allow": ["Bash(git status:*)"]},
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"},
                                {"type": "command", "command": "/usr/local/bin/custom-stop.sh"},
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    return repo_root


def test_normal_create_from_master(tmp_path: Path, master_repo: Path, monkeypatch, capsys) -> None:
    target_path = tmp_path / "linked-worktree"

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(target_path),
            branch="feature/worktree-regression",
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(target_path)
    assert (target_path / ".git").is_file()

    copied_hooks = sorted((target_path / ".claude" / "hooks").glob("mst-*.sh"))

    assert copied_hooks == []

    copied_settings = target_path / ".claude" / "settings.local.json"
    assert copied_settings.is_file()
    copied_payload = json.loads(copied_settings.read_text(encoding="utf-8"))
    assert copied_payload["permissions"] == {"allow": ["Bash(git status:*)"]}
    stop_hooks = copied_payload["hooks"]["Stop"][0]["hooks"]
    assert stop_hooks == [{"type": "command", "command": "/usr/local/bin/custom-stop.sh"}]


def test_create_succeeds_without_source_hooks_dir(tmp_path: Path, master_repo: Path, monkeypatch, capsys) -> None:
    shutil_target = master_repo / ".claude" / "hooks"
    for hook_path in sorted(shutil_target.glob("*")):
        hook_path.unlink()
    shutil_target.rmdir()
    target_path = tmp_path / "linked-worktree-no-hooks"

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(target_path),
            branch="feature/worktree-no-hooks",
            base="master",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert (target_path / ".git").is_file()
    assert not (target_path / ".claude" / "hooks").exists()
    assert (target_path / ".claude" / "settings.local.json").is_file()


def test_typescript_worktree_manager_does_not_bulk_copy_project_hooks() -> None:
    manager_source = Path("src/core/worktree-manager.ts").read_text(encoding="utf-8")

    assert ".claude/hooks" not in manager_source
    assert "Deno.readDir(sourceHooksDir)" not in manager_source
    assert "copyFile(sourcePath, targetPath)" not in manager_source
