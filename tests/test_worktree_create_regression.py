from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.mst_cmds import _common
from scripts.mst_cmds.worktree import cmd_worktree_create


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    _write_file(repo_root / ".claude" / "hooks" / ".mst-hook-version", "0.0.0\n")
    _write_file(
        repo_root / ".claude" / "hooks" / "my-user-hook.sh",
        "#!/usr/bin/env bash\necho custom\n",
        executable=True,
    )
    _write_file(
        repo_root / ".claude" / "settings.local.json",
        json.dumps(
            {
                "permissions": {"allow": ["Bash(git status:*)"]},
                "env": {"CUSTOM_ENV": "1"},
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-session-init.sh",
                                },
                                {"type": "command", "command": "/usr/local/bin/my-custom-start-hook.sh"},
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.claude/hooks/mst-stop-hook.sh",
                                }
                            ],
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [
                                {"type": "command", "command": "/usr/local/bin/my-custom-prompt-hook.sh"}
                            ],
                        }
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    return repo_root


def _create_worktree(tmp_path: Path, master_repo: Path, monkeypatch, branch: str = "feature/worktree-regression") -> tuple[int, Path]:
    target_path = tmp_path / branch.replace("/", "-")

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    exit_code = cmd_worktree_create(
        argparse.Namespace(
            path=str(target_path),
            branch=branch,
            base="master",
        )
    )
    return exit_code, target_path


def test_normal_create_from_master(tmp_path: Path, master_repo: Path, monkeypatch, capsys) -> None:
    exit_code, target_path = _create_worktree(tmp_path, master_repo, monkeypatch)
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(target_path)
    assert (target_path / ".git").is_file()

    copied_hooks_dir = target_path / ".claude" / "hooks"
    assert not (copied_hooks_dir / "mst-session-init.sh").exists()
    assert not (copied_hooks_dir / "mst-stop-hook.sh").exists()
    assert not (copied_hooks_dir / ".mst-hook-version").exists()

    copied_custom_hook = copied_hooks_dir / "my-user-hook.sh"
    assert copied_custom_hook.is_file()
    assert copied_custom_hook.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho custom\n"
    assert copied_custom_hook.stat().st_mode & 0o111

    copied_settings = target_path / ".claude" / "settings.local.json"
    assert copied_settings.is_file()
    settings = json.loads(copied_settings.read_text(encoding="utf-8"))
    assert settings["permissions"] == {"allow": ["Bash(git status:*)"]}
    assert settings["env"] == {"CUSTOM_ENV": "1"}

    session_commands = [
        hook["command"]
        for entry in settings["hooks"]["SessionStart"]
        for hook in entry["hooks"]
    ]
    assert session_commands == ["/usr/local/bin/my-custom-start-hook.sh"]
    assert settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "/usr/local/bin/my-custom-prompt-hook.sh"
    assert "Stop" not in settings["hooks"]
    assert "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-session-init.sh" not in json.dumps(settings)
    assert "mst-stop-hook.sh" not in json.dumps(settings)


def test_worktree_create_succeeds_without_source_hooks(tmp_path: Path, master_repo: Path, monkeypatch, capsys) -> None:
    for path in (master_repo / ".claude" / "hooks").iterdir():
        path.unlink()
    (master_repo / ".claude" / "hooks").rmdir()

    exit_code, target_path = _create_worktree(tmp_path, master_repo, monkeypatch, branch="feature/no-hooks")
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert captured.out.strip() == str(target_path)
    assert (target_path / ".git").is_file()
    assert (master_repo / ".gran-maestro" / "worktrees" / "feature-no-hooks.meta.json").is_file()
    assert (target_path / ".claude" / "settings.local.json").is_file()
    assert not (target_path / ".claude" / "hooks").exists()


def test_worktree_create_succeeds_without_mst_hook_scripts(tmp_path: Path, master_repo: Path, monkeypatch, capsys) -> None:
    for path in (master_repo / ".claude" / "hooks").glob("mst-*.sh"):
        path.unlink()
    (master_repo / ".claude" / "hooks" / ".mst-hook-version").unlink()

    exit_code, target_path = _create_worktree(tmp_path, master_repo, monkeypatch, branch="feature/no-mst-hooks")
    captured = capsys.readouterr()

    assert exit_code == 0, captured.err
    assert captured.err == ""
    assert (target_path / ".git").is_file()
    assert (target_path / ".claude" / "hooks" / "my-user-hook.sh").is_file()
    assert not list((target_path / ".claude" / "hooks").glob("mst-*.sh"))


def test_worktree_create_from_worktree_sources_master_settings(
    master_repo: Path,
    monkeypatch,
    capsys,
) -> None:
    first_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-900-T01"
    second_path = master_repo / ".gran-maestro" / "worktrees" / "REQ-900-T02"

    monkeypatch.setattr(_common, "BASE_DIR", master_repo / ".gran-maestro")
    monkeypatch.chdir(master_repo)

    first_exit = cmd_worktree_create(
        argparse.Namespace(
            path=str(first_path),
            branch="feature/source-settings-first",
            base="master",
        )
    )
    first_captured = capsys.readouterr()
    assert first_exit == 0, first_captured.err

    master_settings = json.loads((master_repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    master_settings["env"]["CUSTOM_ENV"] = "master-updated"
    master_settings["permissions"] = {"allow": ["Bash(git log:*)"]}
    (master_repo / ".claude" / "settings.local.json").write_text(
        json.dumps(master_settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(first_path)
    second_exit = cmd_worktree_create(
        argparse.Namespace(
            path=str(second_path),
            branch="feature/source-settings-second",
            base="master",
        )
    )
    second_captured = capsys.readouterr()

    assert second_exit == 0, second_captured.err
    copied_settings = json.loads((second_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert copied_settings["env"]["CUSTOM_ENV"] == "master-updated"
    assert copied_settings["permissions"] == {"allow": ["Bash(git log:*)"]}


def test_typescript_worktree_manager_does_not_bulk_copy_project_hooks() -> None:
    source = (REPO_ROOT / "src" / "core" / "worktree-manager.ts").read_text(encoding="utf-8")

    assert "isMstOwnedWorktreeHookFile" in source
    assert "if (!entry.isFile || isMstOwnedWorktreeHookFile(entry.name)) continue;" in source
    assert "await Deno.mkdir(targetHooksDir, { recursive: true });\n\n        for await" not in source
    assert "filterWorktreeSettings" in source
    assert "settings.local.json" in source
