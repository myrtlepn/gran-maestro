"""DOD-008 + DOD-009 회귀 테스트 — `mst.py on cleanup` 서브커맨드.

scripts/mst_cmds/on.py가 정규식 매칭으로 mst hook 4종 settings 항목을 제거하고,
.claude/hooks/ 사본 4종 + 부수 파일을 atomic하게 삭제하며, 사용자 정의 hook은
보존하고, lock 파일로 동시 실행을 차단함을 검증한다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MST_CLI = [sys.executable, str(REPO_ROOT / "scripts" / "mst.py")]


def _run_cleanup(cwd: Path, *extra_args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    cmd = MST_CLI + ["on", "cleanup", "--json", *extra_args]
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env.setdefault("MST_PROJECT_ROOT", str(cwd))
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=full_env,
        timeout=15,
    )


def _setup_registered_project(tmp_path: Path, settings_hooks: dict, hook_files: list) -> Path:
    """플러그인 소스 저장소가 아닌 등록 프로젝트 시뮬레이션.

    .claude-plugin/plugin.json 또는 hooks/hooks.json이 없는 일반 프로젝트.
    """
    project = tmp_path / "registered"
    project.mkdir()
    (project / ".gran-maestro").mkdir()

    settings_dir = project / ".claude"
    settings_dir.mkdir()
    settings = {"permissions": {"allow": ["Read"]}}
    if settings_hooks is not None:
        settings["hooks"] = settings_hooks
    settings_path = settings_dir / "settings.local.json"
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    hooks_dir = settings_dir / "hooks"
    hooks_dir.mkdir()
    for name in hook_files:
        (hooks_dir / name).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    return project


def test_pattern_matches_claude_project_dir_variant(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-session-init.sh"}
                    ],
                }
            ]
        },
        hook_files=["mst-session-init.sh"],
    )
    proc = _run_cleanup(project)
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert any("mst-session-init" in r for r in payload["settings"]["removed"])

    settings = json.loads((project / ".claude" / "settings.local.json").read_text())
    assert "hooks" not in settings or not settings.get("hooks", {}).get("SessionStart")


def test_pattern_matches_git_rev_parse_variant(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
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
            ]
        },
        hook_files=["mst-stop-hook.sh"],
    )
    proc = _run_cleanup(project)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert len(payload["settings"]["removed"]) == 1


def test_user_custom_hook_preserved(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-session-init.sh"},
                        {"type": "command", "command": "/usr/local/bin/my-custom-hook.sh"},
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "/home/user/scripts/my-prompt-hook.sh"}
                    ],
                }
            ],
        },
        hook_files=["mst-session-init.sh"],
    )
    proc = _run_cleanup(project)
    assert proc.returncode == 0

    settings = json.loads((project / ".claude" / "settings.local.json").read_text())
    hooks = settings.get("hooks", {})

    sess_cmds = [h["command"] for entry in hooks.get("SessionStart", []) for h in entry["hooks"]]
    assert "/usr/local/bin/my-custom-hook.sh" in sess_cmds
    assert not any("mst-session-init" in c for c in sess_cmds)

    upr_cmds = [h["command"] for entry in hooks.get("UserPromptSubmit", []) for h in entry["hooks"]]
    assert "/home/user/scripts/my-prompt-hook.sh" in upr_cmds


def test_mst_files_removed(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=[
            "mst-stop-hook.sh",
            "mst-session-init.sh",
            "mst-pre-tool-use.sh",
            "mst-auto-chain-context.sh",
            ".mst-hook-version",
        ],
    )
    proc = _run_cleanup(project)
    assert proc.returncode == 0

    hooks_dir = project / ".claude" / "hooks"
    for name in ["mst-stop-hook.sh", "mst-session-init.sh", "mst-pre-tool-use.sh", "mst-auto-chain-context.sh", ".mst-hook-version"]:
        assert not (hooks_dir / name).exists() or not hooks_dir.exists(), f"{name} still present"


def test_user_files_in_hooks_dir_preserved(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    proc = _run_cleanup(project)
    assert proc.returncode == 0

    hooks_dir = project / ".claude" / "hooks"
    assert hooks_dir.exists()
    assert (hooks_dir / "my-user-hook.sh").exists()
    assert not (hooks_dir / "mst-stop-hook.sh").exists()


def test_lock_blocks_concurrent_run(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh"],
    )
    lock_path = project / ".gran-maestro" / "tmp" / "cleanup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()))
    # Set lock mtime to now (fresh)
    os.utime(str(lock_path), None)

    proc = _run_cleanup(project)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "skipped"
    assert "lock" in payload.get("reason", "")

    # mst-stop-hook.sh should still exist (cleanup was skipped)
    assert (project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()


def test_stale_lock_invalidated(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh"],
    )
    lock_path = project / ".gran-maestro" / "tmp" / "cleanup.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("99999")
    # Set lock mtime to 120 seconds ago (stale)
    old = time.time() - 120
    os.utime(str(lock_path), (old, old))

    proc = _run_cleanup(project)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok", f"expected ok after stale lock invalidation, got {payload}"


def test_dry_run_no_changes(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"}
                    ],
                }
            ]
        },
        hook_files=["mst-stop-hook.sh"],
    )
    proc = _run_cleanup(project, "--dry-run")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "dry_run"
    # Files should NOT be deleted in dry-run
    assert (project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
    settings = json.loads((project / ".claude" / "settings.local.json").read_text())
    assert "Stop" in settings.get("hooks", {})


def test_plugin_source_repo_skipped(tmp_path):
    """gran-maestro 자체 플러그인 소스 저장소는 cleanup 대상에서 제외된다."""
    plugin_repo = tmp_path / "plugin_src"
    plugin_repo.mkdir()
    (plugin_repo / ".gran-maestro").mkdir()
    (plugin_repo / ".claude-plugin").mkdir()
    (plugin_repo / ".claude-plugin" / "plugin.json").write_text('{"version": "0.0.0"}', encoding="utf-8")
    (plugin_repo / "hooks").mkdir()
    (plugin_repo / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")
    (plugin_repo / ".claude" / "hooks").mkdir(parents=True)
    (plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    proc = _run_cleanup(plugin_repo)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "skipped"
    assert "plugin source repo" in payload["reason"]
    # mst-stop-hook.sh should still exist
    assert (plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
