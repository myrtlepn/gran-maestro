from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MST = [sys.executable, str(ROOT / "scripts/mst.py")]


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_mst(cwd: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        MST + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _init_master_repo(tmp_path: Path) -> Path:
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


def _make_git_wrapper(tmp_path: Path) -> tuple[dict[str, str], Path]:
    real_git = shutil.which("git")
    assert real_git is not None

    bin_dir = tmp_path / "instrumented-bin"
    log_path = tmp_path / "git-invocations.log"
    bin_dir.mkdir()
    log_path.write_text("", encoding="utf-8")

    _write_file(
        bin_dir / "git",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f"printf '%s\\t%s\\n' \"$PWD\" \"$*\" >> {shlex.quote(str(log_path))}",
                f"exec {shlex.quote(real_git)} \"$@\"",
                "",
            ]
        ),
        executable=True,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env, log_path


def _worktree_list(repo_root: Path) -> list[Path]:
    result = _run_git(repo_root, "worktree", "list", "--porcelain")
    assert result.returncode == 0, result.stderr
    worktrees: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            worktrees.append(Path(line.split(" ", 1)[1]).resolve(strict=False))
    return worktrees


def _git_worktree_add_cwds(log_path: Path) -> list[Path]:
    entries: list[Path] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        cwd, args = line.split("\t", 1)
        if args.startswith("worktree add "):
            entries.append(Path(cwd).resolve(strict=False))
    return entries


def _assert_support_files_copied(source_root: Path, target_root: Path) -> None:
    source_hooks = sorted((source_root / ".claude" / "hooks").glob("mst-*.sh"))
    copied_hooks = sorted((target_root / ".claude" / "hooks").glob("mst-*.sh"))

    assert [path.name for path in copied_hooks] == [path.name for path in source_hooks]
    for source_hook, copied_hook in zip(source_hooks, copied_hooks):
        assert copied_hook.read_text(encoding="utf-8") == source_hook.read_text(encoding="utf-8")
        assert copied_hook.stat().st_mode & 0o111

    copied_settings = target_root / ".claude" / "settings.local.json"
    assert copied_settings.is_file()
    assert json.loads(copied_settings.read_text(encoding="utf-8")) == json.loads(
        (source_root / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )


def test_worktree_create_cli_integration_sequence(tmp_path: Path) -> None:
    master_repo = _init_master_repo(tmp_path)
    existing_worktree = tmp_path / "linked-worktree-A"

    add_existing_worktree = _run_git(
        master_repo,
        "worktree",
        "add",
        "-b",
        "feature/existing-worktree",
        str(existing_worktree),
        "master",
    )
    assert add_existing_worktree.returncode == 0, add_existing_worktree.stderr
    (existing_worktree / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    assert not (existing_worktree / ".claude").exists()

    env, git_log_path = _make_git_wrapper(tmp_path)

    target_from_master = tmp_path / "created-from-master"
    created_from_master = _run_mst(
        master_repo,
        env,
        "worktree",
        "create",
        "--path",
        str(target_from_master),
        "--branch",
        "feature/from-master",
        "--base",
        "master",
    )
    assert created_from_master.returncode == 0, created_from_master.stderr
    assert created_from_master.stderr == ""
    assert created_from_master.stdout.strip() == str(target_from_master)
    assert (target_from_master / ".git").is_file()
    assert target_from_master.resolve(strict=False) in _worktree_list(master_repo)
    _assert_support_files_copied(master_repo, target_from_master)

    target_from_worktree = tmp_path / "created-from-linked-worktree"
    created_from_worktree = _run_mst(
        existing_worktree,
        env,
        "worktree",
        "create",
        "--path",
        str(target_from_worktree),
        "--branch",
        "feature/from-linked-worktree",
        "--base",
        "master",
    )
    assert created_from_worktree.returncode == 0, created_from_worktree.stderr
    assert created_from_worktree.stderr == ""
    assert created_from_worktree.stdout.strip() == str(target_from_worktree)
    assert (target_from_worktree / ".git").is_file()
    assert target_from_worktree.resolve(strict=False) in _worktree_list(master_repo)
    _assert_support_files_copied(master_repo, target_from_worktree)

    add_cwds = _git_worktree_add_cwds(git_log_path)
    assert add_cwds == [master_repo.resolve(strict=False), master_repo.resolve(strict=False)]

    nested_target = existing_worktree / "nested-worktree"
    nested_blocked = _run_mst(
        master_repo,
        env,
        "worktree",
        "create",
        "--path",
        str(nested_target),
        "--branch",
        "feature/nested-blocked",
        "--base",
        "master",
    )
    assert nested_blocked.returncode != 0
    assert "nested worktree path detected" in nested_blocked.stderr
    assert str(nested_target.resolve(strict=False)) in nested_blocked.stderr
    assert f"기존 worktree {existing_worktree.resolve(strict=False)}의 내부" in nested_blocked.stderr
    assert f"master({master_repo.resolve(strict=False)})" in nested_blocked.stderr
    assert not nested_target.exists()
    assert _git_worktree_add_cwds(git_log_path) == add_cwds

    symlink_target = tmp_path / "alias-to-nested"
    resolved_symlink_target = existing_worktree / "nested-via-symlink"
    symlink_target.symlink_to(resolved_symlink_target, target_is_directory=True)

    symlink_blocked = _run_mst(
        master_repo,
        env,
        "worktree",
        "create",
        "--path",
        str(symlink_target),
        "--branch",
        "feature/symlink-blocked",
        "--base",
        "master",
    )
    assert symlink_blocked.returncode != 0
    assert "nested worktree path detected" in symlink_blocked.stderr
    assert str(resolved_symlink_target.resolve(strict=False)) in symlink_blocked.stderr
    assert f"기존 worktree {existing_worktree.resolve(strict=False)}의 내부" in symlink_blocked.stderr
    assert f"master({master_repo.resolve(strict=False)})" in symlink_blocked.stderr
    assert not resolved_symlink_target.exists()
    assert _git_worktree_add_cwds(git_log_path) == add_cwds
