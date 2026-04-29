from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MST_PY = REPO_ROOT / "scripts" / "mst.py"


def _clean_env(home: Path, policy_home: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_"))
    }
    env["HOME"] = str(home)
    env["MST_POLICY_HOME"] = str(policy_home)
    return env


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    policy_home = tmp_path / "policy"
    (project_root / ".gran-maestro").mkdir(parents=True)
    home.mkdir()
    policy_home.mkdir()
    return project_root, home, policy_home


def _allowlist_path(policy_home: Path) -> Path:
    return policy_home / "allowlist.json"


def _run_plain(
    project_root: Path,
    home: Path,
    policy_home: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _clean_env(home, policy_home)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(MST_PY), *args],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_tty(
    project_root: Path,
    home: Path,
    policy_home: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _clean_env(home, policy_home)
    if env_extra:
        env.update(env_extra)
    master_fd, slave_fd = pty.openpty()
    try:
        return subprocess.run(
            [sys.executable, str(MST_PY), *args],
            cwd=project_root,
            env=env,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def _run_tty_home_only(project_root: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CLAUDE_CODE_", "CLAUDECODE_", "CLAUDE_API_")) and key != "MST_POLICY_HOME"
    }
    env["HOME"] = str(home)
    master_fd, slave_fd = pty.openpty()
    try:
        return subprocess.run(
            [sys.executable, str(MST_PY), *args],
            cwd=project_root,
            env=env,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def _write_allowlist(policy_home: Path, entries: list[dict]) -> None:
    path = _allowlist_path(policy_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "entries": entries}, indent=2) + "\n", encoding="utf-8")


def test_add_allowlist_requires_tty_and_writes_expiring_entry(tmp_path: Path) -> None:
    project_root, home, policy_home = _make_project(tmp_path)
    start = datetime.now(timezone.utc)

    result = _run_tty(project_root, home, policy_home, "hook", "allow", "Bash", "--args-pattern", "*npm test*", "--expires", "30")

    assert result.returncode == 0, result.stderr
    assert "Added: alw_" in result.stdout
    data = json.loads(_allowlist_path(policy_home).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["id"].startswith("alw_")
    assert entry["tool"] == "Bash"
    assert entry["args_pattern"] == "*npm test*"
    assert entry["added_by_tty"] is True
    expires_at = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
    assert start + timedelta(minutes=29) <= expires_at <= start + timedelta(minutes=31)


def test_add_allowlist_defaults_to_sandbox_home_policy_dir(tmp_path: Path) -> None:
    project_root, home, _policy_home = _make_project(tmp_path)

    result = _run_tty_home_only(project_root, home, "hook", "allow", "Bash")

    assert result.returncode == 0, result.stderr
    path = home / ".claude" / "gran-maestro-policy" / "allowlist.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["entries"][0]["tool"] == "Bash"


def test_add_allowlist_blocks_llm_non_tty_without_writing(tmp_path: Path) -> None:
    project_root, home, policy_home = _make_project(tmp_path)

    result = _run_plain(
        project_root,
        home,
        policy_home,
        "hook",
        "allow",
        "Bash",
        env_extra={"CLAUDE_CODE_SESSION_ID": "llm-session"},
    )

    assert result.returncode != 0
    assert "TTY provenance required" in result.stderr
    assert not _allowlist_path(policy_home).exists()


def test_list_prints_active_and_expired_entries(tmp_path: Path) -> None:
    project_root, home, policy_home = _make_project(tmp_path)
    _write_allowlist(
        policy_home,
        [
            {"id": "alw_one", "tool": "Bash", "args_pattern": "*npm test*", "expires_at": None, "created_at": "2026-04-29T00:00:00Z"},
            {"id": "alw_two", "tool": "Write", "args_pattern": "*.md", "expires_at": "2099-01-01T00:00:00Z", "created_at": "2026-04-29T00:00:00Z"},
            {"id": "alw_old", "tool": "Bash", "args_pattern": "*", "expires_at": "2000-01-01T00:00:00Z", "created_at": "2026-04-29T00:00:00Z"},
        ],
    )

    result = _run_plain(project_root, home, policy_home, "hook", "allow", "--list")

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines[0] == "ID | Tool | Args Pattern | Expires | Status"
    assert len(lines) == 4
    assert any("alw_one | Bash | *npm test* | never | active" in line for line in lines)
    assert any("alw_old | Bash | * | 2000-01-01T00:00:00Z | expired" in line for line in lines)


def test_remove_deletes_matching_entry(tmp_path: Path) -> None:
    project_root, home, policy_home = _make_project(tmp_path)
    _write_allowlist(
        policy_home,
        [
            {"id": "alw_keep", "tool": "Bash", "args_pattern": "*", "expires_at": None, "created_at": "2026-04-29T00:00:00Z"},
            {"id": "alw_drop", "tool": "Write", "args_pattern": "*", "expires_at": None, "created_at": "2026-04-29T00:00:00Z"},
        ],
    )

    result = _run_plain(project_root, home, policy_home, "hook", "allow", "--remove", "alw_drop")

    assert result.returncode == 0, result.stderr
    assert "Removed: alw_drop" in result.stdout
    data = json.loads(_allowlist_path(policy_home).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in data["entries"]] == ["alw_keep"]
