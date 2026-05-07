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
DOD002_TOP_LEVEL_FIELDS = {
    "mutation",
    "environment",
    "plugin_core",
    "project_legacy",
    "user_global",
    "user_custom",
    "duplicate_risks",
    "diagnostics",
}
DOD002_CLASSIFICATIONS = {
    "plugin_core",
    "project_legacy",
    "user_global",
    "user_custom",
}
DOD002_DIAGNOSTIC_CODES = {
    "malformed_settings",
    "missing_hooks_registry",
    "parse_error",
    "permission_denied",
    "unknown_environment",
}


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


def _run_cleanup_dry_run_json(cwd: Path, env: Optional[dict] = None) -> dict:
    proc = _run_cleanup(cwd, "--dry-run", env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    return json.loads(proc.stdout)


def _setup_dod002_inventory_project(tmp_path: Path) -> Path:
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"},
                        {"type": "command", "command": "/usr/local/bin/my-custom-stop-hook.sh"},
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
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    hooks_dir = project / ".claude" / "hooks"
    (hooks_dir / "mst-stop-hook.sh").write_text("#!/bin/bash\necho legacy-stop\n", encoding="utf-8")
    (hooks_dir / "my-user-hook.sh").write_text("#!/bin/bash\necho custom\n", encoding="utf-8")
    return project


def _read_bytes_by_path(paths: list[Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _collect_classifications(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        classification = value.get("classification")
        if isinstance(classification, str):
            found.add(classification)
        for child in value.values():
            found.update(_collect_classifications(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_classifications(child))
    return found


def _diagnostic_codes(payload: dict) -> set[str]:
    codes: set[str] = set()
    for diagnostic in payload.get("diagnostics", []):
        if not isinstance(diagnostic, dict):
            continue
        for key in ("code", "reason", "reason_code"):
            value = diagnostic.get(key)
            if isinstance(value, str):
                codes.add(value)
    return codes


def _write_user_global_settings(home: Path) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [
                                {"type": "command", "command": "~/.claude/scripts/check-version.sh"}
                            ],
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
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


def test_inventory_dry_run_json_exposes_dod002_top_level_contract(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    home = tmp_path / "home"
    _write_user_global_settings(home)

    payload = _run_cleanup_dry_run_json(project, env={"HOME": str(home)})

    assert DOD002_TOP_LEVEL_FIELDS.issubset(payload), (
        f"missing DOD-002 inventory fields: {DOD002_TOP_LEVEL_FIELDS - set(payload)}"
    )
    assert payload["mutation"]["dry_run"] is True
    assert payload["mutation"]["mutated"] is False


def test_inventory_classification_enum_is_exactly_reusable_and_limited(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    home = tmp_path / "home"
    _write_user_global_settings(home)

    payload = _run_cleanup_dry_run_json(project, env={"HOME": str(home)})

    classifications = _collect_classifications(payload)
    assert classifications == DOD002_CLASSIFICATIONS


def test_dry_run_no_mutation_byte_for_byte_for_settings_and_hooks(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_dry_run_json(project)

    assert payload["mutation"]["dry_run"] is True
    assert payload["mutation"]["mutated"] is False
    assert _read_bytes_by_path(watched_paths) == before


def test_custom_hook_inventory_reports_preserved_not_cleanup_candidate(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)

    payload = _run_cleanup_dry_run_json(project)

    user_custom_text = json.dumps(payload["user_custom"], ensure_ascii=False)
    assert "/usr/local/bin/my-custom-stop-hook.sh" in user_custom_text
    assert "/home/user/scripts/my-prompt-hook.sh" in user_custom_text
    assert "my-user-hook.sh" in user_custom_text
    assert "preserved" in user_custom_text

    project_legacy_text = json.dumps(payload["project_legacy"], ensure_ascii=False)
    assert "/usr/local/bin/my-custom-stop-hook.sh" not in project_legacy_text
    assert "/home/user/scripts/my-prompt-hook.sh" not in project_legacy_text
    assert "my-user-hook.sh" not in project_legacy_text


def test_duplicate_risk_observable_for_plugin_core_and_project_legacy_same_event(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)

    payload = _run_cleanup_dry_run_json(project)

    duplicate_risks = payload["duplicate_risks"]
    assert duplicate_risks, "expected duplicate risk when plugin core and project legacy Stop hooks coexist"
    duplicate_text = json.dumps(duplicate_risks, ensure_ascii=False)
    assert "Stop" in duplicate_text
    assert "plugin_core" in duplicate_text
    assert "project_legacy" in duplicate_text
    assert "reason" in duplicate_text


def test_diagnostic_malformed_settings_reports_stable_reason_codes(tmp_path):
    project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=[])
    settings_path = project / ".claude" / "settings.local.json"
    settings_path.write_text('{"hooks": ', encoding="utf-8")
    before = settings_path.read_bytes()

    payload = _run_cleanup_dry_run_json(project)

    assert {"malformed_settings", "parse_error"}.issubset(_diagnostic_codes(payload))
    assert settings_path.read_bytes() == before


def test_diagnostic_missing_hooks_registry_reports_stable_reason_code(tmp_path):
    project = tmp_path / "plugin_like_without_registry"
    project.mkdir()
    (project / ".gran-maestro").mkdir()
    (project / ".claude-plugin").mkdir()
    (project / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"hooks": "./hooks/hooks.json"}) + "\n",
        encoding="utf-8",
    )
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")

    payload = _run_cleanup_dry_run_json(project)

    assert "missing_hooks_registry" in _diagnostic_codes(payload)


def test_diagnostic_permission_denied_reports_stable_reason_code(tmp_path):
    project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=[])
    settings_path = project / ".claude" / "settings.local.json"
    before = settings_path.read_bytes()
    settings_path.chmod(0)
    try:
        payload = _run_cleanup_dry_run_json(project)
    finally:
        settings_path.chmod(0o644)

    assert "permission_denied" in _diagnostic_codes(payload)
    assert settings_path.read_bytes() == before


def test_diagnostic_unknown_environment_reports_stable_reason_code(tmp_path):
    project = tmp_path / "unknown"
    project.mkdir()

    payload = _run_cleanup_dry_run_json(project)

    assert "unknown_environment" in _diagnostic_codes(payload)


def test_diagnostic_reason_code_enum_is_locked() -> None:
    assert DOD002_DIAGNOSTIC_CODES == {
        "malformed_settings",
        "missing_hooks_registry",
        "parse_error",
        "permission_denied",
        "unknown_environment",
    }


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
