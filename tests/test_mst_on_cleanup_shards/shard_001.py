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
from scripts.mst_cmds import on
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
    "broken_canonical_registration",
    "cache_sync_failure",
    "malformed_settings",
    "missing_hooks_registry",
    "missing_plugin_manifest",
    "parse_error",
    "permission_denied",
    "stale_plugin_cache",
    "unknown_environment",
    "duplicate_registration",
    "duplicate_canonical_registration",
    "duplicate_legacy_registration",
    "unknown_hook_command",
}
DOD010_SCHEMA_VERSION = "mst.on.cleanup.v1"
DOD010_POST_CHECK_BASE_CHECKS = {
    "stale_cleanup_candidates_absent",
    "plugin_core_canonical_command",
    "user_custom_preserved",
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
def _run_cleanup_dry_run_json(cwd: Path, env: Optional[dict] = None, source_repo: bool = False) -> dict:
    extra_args = ["--dry-run"]
    if source_repo:
        extra_args.append("--source-repo")
    proc = _run_cleanup(cwd, *extra_args, env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    return json.loads(proc.stdout)
def _run_cleanup_apply_json(cwd: Path, env: Optional[dict] = None, dry_run_payload: Optional[dict] = None) -> dict:
    dry_run = dry_run_payload or _run_cleanup_dry_run_json(cwd, env=env)
    proc = _run_cleanup(cwd, "--dry-run-id", dry_run["dry_run_id"], env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    return json.loads(proc.stdout)
def _run_cleanup_apply_without_dry_run_json(cwd: Path, env: Optional[dict] = None) -> dict:
    proc = _run_cleanup(cwd, env=env)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    return json.loads(proc.stdout)
def _run_cleanup_human(cwd: Path, *extra_args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    cmd = MST_CLI + ["on", "cleanup", *extra_args]
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
def _read_project_settings(project: Path) -> dict:
    return json.loads((project / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
def _commands_for(settings: dict, event: str, matcher: str = "") -> list[str]:
    commands: list[str] = []
    for entry in settings.get("hooks", {}).get(event, []):
        if entry.get("matcher", "") != matcher:
            continue
        for hook in entry.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str):
                commands.append(command)
    return commands
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
def _post_check_checks(payload: dict) -> dict:
    post_check = payload.get("post_check")
    assert isinstance(post_check, dict), f"post_check missing from payload: {payload}"
    checks = post_check.get("checks")
    assert isinstance(checks, dict), f"post_check.checks missing from payload: {payload}"
    return checks
def _boundary_item(payload: dict, item_id: str) -> dict:
    boundary = payload.get("migration_boundary")
    assert isinstance(boundary, dict), f"migration_boundary missing from payload: {payload}"
    for item in boundary.get("items", []):
        if item.get("id") == item_id:
            return item
    raise AssertionError(f"missing migration boundary item {item_id!r}: {boundary}")
def _diagnostics_with_code(payload: dict, code: str) -> list[dict]:
    return [
        diagnostic
        for diagnostic in payload.get("diagnostics", [])
        if isinstance(diagnostic, dict)
        and code in {diagnostic.get("code"), diagnostic.get("reason"), diagnostic.get("reason_code")}
    ]
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
def _write_mixed_user_global_settings(home: Path) -> Path:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "mcp__plugin_oh-my-claudecode_x__ask_codex",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/scripts/maestro-guard.sh",
                                }
                            ],
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/scripts/log-prompt.sh",
                                },
                                {
                                    "type": "command",
                                    "command": "~/.claude/scripts/check-version.sh",
                                },
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "~/.claude/hooks/mst-stop-hook.sh --global-wrapper",
                                }
                            ],
                        }
                    ],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return settings_path
def _settings_commands_by_event(settings: dict) -> dict[tuple[str, str], list[str]]:
    commands: dict[tuple[str, str], list[str]] = {}
    for event, entries in settings.get("hooks", {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher", "")
            hooks = entry.get("hooks", [])
            if not isinstance(hooks, list):
                continue
            commands[(event, matcher if isinstance(matcher, str) else "")] = [
                hook.get("command")
                for hook in hooks
                if isinstance(hook, dict) and isinstance(hook.get("command"), str)
            ]
    return commands
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
def _setup_plugin_source_repo(tmp_path: Path) -> Path:
    project = tmp_path / "plugin_src"
    project.mkdir()
    (project / ".gran-maestro").mkdir()

    plugin_dir = project / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"version": "0.0.0", "hooks": "./hooks/hooks.json"}, indent=2) + "\n",
        encoding="utf-8",
    )

    canonical_hooks_dir = project / "hooks"
    canonical_hooks_dir.mkdir()
    (canonical_hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
                                }
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
    (canonical_hooks_dir / "mst-stop-hook.sh").write_text("#!/bin/bash\necho canonical\n", encoding="utf-8")

    claude_dir = project / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
                                },
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/my-custom-stop-hook.sh",
                                },
                            ],
                        }
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    legacy_hooks_dir = claude_dir / "hooks"
    legacy_hooks_dir.mkdir()
    (legacy_hooks_dir / "mst-stop-hook.sh").write_text("#!/bin/bash\necho legacy-stop\n", encoding="utf-8")
    (legacy_hooks_dir / "mst-session-init.sh").write_text("#!/bin/bash\necho legacy-session\n", encoding="utf-8")
    (legacy_hooks_dir / "my-user-hook.sh").write_text("#!/bin/bash\necho custom\n", encoding="utf-8")
    return project
def _plugin_version() -> str:
    return json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
def _setup_missing_manifest_cleanup_fixture(tmp_path: Path) -> tuple[Path, dict]:
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
            ]
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    (project / ".claude-plugin").mkdir()
    env = _matrix_home_env(tmp_path, include_user_global=False)
    return project, env
def _setup_broken_canonical_cleanup_fixture(tmp_path: Path) -> tuple[Path, dict]:
    project = _setup_plugin_source_repo(tmp_path)
    hooks_payload = json.loads((project / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hooks_payload["hooks"]["Stop"][0]["hooks"][0]["command"] = (
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"
    )
    (project / "hooks" / "hooks.json").write_text(
        json.dumps(hooks_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    env = _matrix_home_env(tmp_path, include_user_global=False)
    return project, env
def _write_cache_install(cache_dir: Path, *, version: str, canonical: bool = True, include_registry: bool = True) -> Path:
    install_root = cache_dir / version
    (install_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (install_root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "mst", "version": version, "hooks": "./hooks/hooks.json"}, indent=2) + "\n",
        encoding="utf-8",
    )
    hooks_dir = install_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    if include_registry:
        command = (
            "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"
            if canonical
            else "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"
        )
        (hooks_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "matcher": "",
                                "hooks": [{"type": "command", "command": command}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    (hooks_dir / "mst-stop-hook.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return install_root
def _setup_stale_cache_cleanup_fixture(tmp_path: Path) -> tuple[Path, dict, Path]:
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
            ]
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    home = tmp_path / "home-stale-cache"
    cache_root = home / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst"
    _write_cache_install(cache_root, version="0.57.6")
    env = {"HOME": str(home)}
    return project, env, cache_root
def _setup_cache_sync_failure_cleanup_fixture(tmp_path: Path) -> tuple[Path, dict, Path]:
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
            ]
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    home = tmp_path / "home-cache-sync-failure"
    cache_root = home / ".claude" / "plugins" / "cache" / "gran-maestro" / "mst"
    _write_cache_install(cache_root, version=_plugin_version(), include_registry=False)
    env = {"HOME": str(home)}
    return project, env, cache_root
def _setup_duplicate_canonical_plugin_source_repo(tmp_path: Path) -> Path:
    project = _setup_plugin_source_repo(tmp_path)
    registry_path = project / "hooks" / "hooks.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["hooks"]["Stop"][0]["hooks"].append(
        {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh",
        }
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return project
MATRIX_ALLOWED_HOOK_LAYERS = tuple(sorted(DOD002_CLASSIFICATIONS))
MATRIX_BASE_POST_CHECK_KEYS = (
    "stale_cleanup_candidates_absent",
    "plugin_core_canonical_command",
    "user_custom_preserved",
)
SCENARIO_MATRIX_ROWS = [
    {
        "id": "matrix-source-default-source",
        "scenario": "source repo default skip",
        "axes": ("source",),
        "setup": "source_default",
        "project_kind": "source_repo",
        "expected_action": "skip",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "skipped",
        "expected_reason": "plugin source repo (out of cleanup scope)",
        "expected_cleanup_scope": "skipped",
        "expected_rollback_available": False,
        "expected_settings_removed": (),
        "expected_target_files": (),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS + ("source_repo_default_skip_or_opt_in",),
        "expected_user_global_present": False,
        "expected_user_global_hook": False,
    },
    {
        "id": "matrix-source-opt-in-source",
        "scenario": "source repo opt-in legacy-only cleanup",
        "axes": ("source",),
        "setup": "source_opt_in",
        "project_kind": "source_repo",
        "expected_action": "mutate_legacy_source_only",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "dry_run",
        "expected_reason": None,
        "expected_cleanup_scope": "source-repo-opt-in",
        "expected_rollback_available": True,
        "expected_settings_removed": (
            "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        ),
        "expected_target_files": ("mst-session-init.sh", "mst-stop-hook.sh"),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS + ("source_repo_default_skip_or_opt_in",),
        "expected_user_global_present": False,
        "expected_user_global_hook": False,
    },
    {
        "id": "matrix-normal-project-normal",
        "scenario": "normal MST project cleanup",
        "axes": ("normal",),
        "setup": "normal",
        "project_kind": "normal_project",
        "expected_action": "mutate_mst_legacy_only",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "dry_run",
        "expected_reason": None,
        "expected_cleanup_scope": "project",
        "expected_rollback_available": True,
        "expected_settings_removed": (
            "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        ),
        "expected_target_files": ("mst-stop-hook.sh",),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS,
        "expected_user_global_present": False,
        "expected_user_global_hook": False,
    },
    {
        "id": "matrix-worktree-sync-worktree",
        "scenario": "worktree no legacy propagation",
        "axes": ("worktree", "sync"),
        "setup": "worktree",
        "project_kind": "worktree",
        "expected_action": "skip_legacy_propagation",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "dry_run",
        "expected_reason": None,
        "expected_cleanup_scope": "project",
        "expected_rollback_available": False,
        "expected_settings_removed": (),
        "expected_target_files": (),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS + ("worktree_no_legacy_propagation",),
        "expected_user_global_present": False,
        "expected_user_global_hook": False,
    },
    {
        "id": "matrix-non_mst-non_mst",
        "scenario": "non-MST fail-open skip",
        "axes": ("non_mst",),
        "setup": "non_mst",
        "project_kind": "non_mst",
        "expected_action": "fail_open_skip",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "skipped",
        "expected_reason": "non-MST project fail-open",
        "expected_cleanup_scope": "project",
        "expected_rollback_available": False,
        "expected_settings_removed": (),
        "expected_target_files": (),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS + ("non_mst_user_global_fail_open",),
        "expected_user_global_present": False,
        "expected_user_global_hook": False,
    },
    {
        "id": "matrix-global-non_mst-global",
        "scenario": "user-global read-only fail-open",
        "axes": ("global", "non_mst"),
        "setup": "global",
        "project_kind": "non_mst",
        "expected_action": "read_only_fail_open",
        "allowed_hook_layers": MATRIX_ALLOWED_HOOK_LAYERS,
        "expected_status": "skipped",
        "expected_reason": "non-MST project fail-open",
        "expected_cleanup_scope": "project",
        "expected_rollback_available": False,
        "expected_settings_removed": (),
        "expected_target_files": (),
        "expected_post_check_required": MATRIX_BASE_POST_CHECK_KEYS + ("non_mst_user_global_fail_open",),
        "expected_user_global_present": True,
        "expected_user_global_hook": True,
    },
]
EDGE_MATRIX_ROWS = [
    {
        "id": "edge-partial-source-sync",
        "scenario": "partial checkout missing hooks registry",
        "axes": ("source", "sync"),
        "setup": "partial_missing_registry",
        "destructive_mutation_allowed": False,
        "expected_status": "diagnostic",
        "expected_reason": "cleanup environment cannot be safely mutated",
        "expected_rollback_available": False,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": {"missing_hooks_registry", "unknown_environment"},
        "expected_mutation": {"dry_run": True, "mutated": False},
    },
    {
        "id": "edge-permission-normal",
        "scenario": "settings permission denied",
        "axes": ("permission", "normal"),
        "setup": "permission_denied",
        "destructive_mutation_allowed": False,
        "expected_status": "diagnostic",
        "expected_reason": "cleanup environment cannot be safely mutated",
        "expected_rollback_available": False,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": {"permission_denied"},
        "expected_mutation": {"dry_run": True, "mutated": False},
    },
    {
        "id": "edge-lock-normal-fresh-lock",
        "scenario": "fresh cleanup lock skip",
        "axes": ("lock", "normal"),
        "setup": "fresh_lock",
        "destructive_mutation_allowed": False,
        "expected_status": "skipped",
        "expected_reason": "another cleanup in progress (lock held)",
        "expected_rollback_available": False,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": set(),
        "expected_mutation": {"dry_run": False, "mutated": False},
    },
    {
        "id": "edge-lock-normal-stale-lock",
        "scenario": "stale cleanup lock invalidated",
        "axes": ("lock", "normal"),
        "setup": "stale_lock",
        "destructive_mutation_allowed": True,
        "expected_status": "ok",
        "expected_reason": None,
        "expected_rollback_available": True,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": set(),
        "expected_mutation": {"dry_run": False, "mutated": True},
        "expected_deleted_files": ("mst-stop-hook.sh",),
    },
    {
        "id": "edge-malformed-normal",
        "scenario": "malformed settings fail-open diagnostic",
        "axes": ("normal",),
        "setup": "malformed_settings",
        "destructive_mutation_allowed": False,
        "expected_status": "diagnostic",
        "expected_reason": "cleanup environment cannot be safely mutated",
        "expected_rollback_available": False,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": {"malformed_settings", "parse_error"},
        "expected_mutation": {"dry_run": False, "mutated": False},
    },
    {
        "id": "edge-repeated-normal-repeated",
        "scenario": "repeated cleanup apply stays idempotent",
        "axes": ("repeated", "normal"),
        "setup": "repeated_cleanup_apply",
        "destructive_mutation_allowed": True,
        "first_expected_status": "ok",
        "second_expected_status": "ok",
        "expected_reason": None,
        "first_expected_rollback_available": True,
        "second_expected_rollback_available": False,
        "expected_post_check_keys": MATRIX_BASE_POST_CHECK_KEYS,
        "allow_post_check_omission": False,
        "expected_diag_codes": set(),
        "first_expected_mutation": {"dry_run": False, "mutated": True},
        "second_expected_mutation": {"dry_run": False, "mutated": False},
        "first_expected_settings_removed": (
            "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        ),
        "second_expected_settings_removed": (),
        "first_expected_deleted_files": ("mst-stop-hook.sh",),
        "second_expected_deleted_files": (),
    },
]
def _matrix_home_env(tmp_path: Path, *, include_user_global: bool) -> dict:
    home = tmp_path / ("home-global" if include_user_global else "home-empty")
    home.mkdir(parents=True, exist_ok=True)
    if include_user_global:
        _write_user_global_settings(home)
    return {"HOME": str(home)}
def _setup_boundary_matrix_scenario(tmp_path: Path, setup: str) -> tuple[Path, dict, bool]:
    if setup == "normal":
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
                ]
            },
            hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
        )
        return project, _matrix_home_env(tmp_path, include_user_global=False), False

    if setup == "source_default":
        return (
            _setup_plugin_source_repo(tmp_path),
            _matrix_home_env(tmp_path, include_user_global=False),
            False,
        )

    if setup == "source_opt_in":
        return (
            _setup_plugin_source_repo(tmp_path),
            _matrix_home_env(tmp_path, include_user_global=False),
            True,
        )

    if setup == "worktree":
        project = tmp_path / ".gran-maestro" / "worktrees" / "REQ-853-T01"
        project.mkdir(parents=True)
        (project / ".gran-maestro").mkdir()
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
        return project, _matrix_home_env(tmp_path, include_user_global=False), False

    if setup == "non_mst":
        project = tmp_path / "plain"
        project.mkdir()
        return project, _matrix_home_env(tmp_path, include_user_global=False), False

    if setup == "global":
        project = tmp_path / "plain"
        project.mkdir()
        return project, _matrix_home_env(tmp_path, include_user_global=True), False

    raise AssertionError(f"unsupported scenario setup: {setup}")
def _execute_boundary_edge_case(tmp_path: Path, setup: str):
    env = _matrix_home_env(tmp_path, include_user_global=False)

    if setup == "partial_missing_registry":
        project = tmp_path / "partial-checkout"
        project.mkdir()
        (project / ".gran-maestro").mkdir()
        (project / ".claude-plugin").mkdir()
        (project / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"hooks": "./hooks/hooks.json"}) + "\n",
            encoding="utf-8",
        )
        (project / ".claude").mkdir()
        (project / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
        return _run_cleanup_dry_run_json(project, env=env)

    if setup == "permission_denied":
        project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=[])
        settings_path = project / ".claude" / "settings.local.json"
        settings_path.chmod(0)
        try:
            return _run_cleanup_dry_run_json(project, env=env)
        finally:
            settings_path.chmod(0o644)

    if setup == "fresh_lock":
        project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=["mst-stop-hook.sh"])
        lock_path = project / ".gran-maestro" / "tmp" / "cleanup.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("123", encoding="utf-8")
        os.utime(str(lock_path), None)
        proc = _run_cleanup(project, env=env)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    if setup == "stale_lock":
        project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=["mst-stop-hook.sh"])
        lock_path = project / ".gran-maestro" / "tmp" / "cleanup.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("123", encoding="utf-8")
        old = time.time() - 120
        os.utime(str(lock_path), (old, old))
        return _run_cleanup_apply_json(project, env=env)

    if setup == "malformed_settings":
        project = _setup_registered_project(
            tmp_path,
            settings_hooks={},
            hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
        )
        settings_path = project / ".claude" / "settings.local.json"
        settings_path.write_text('{"hooks": ', encoding="utf-8")
        proc = _run_cleanup(project, env=env)
        assert proc.returncode in {0, 1}, proc.stderr
        return json.loads(proc.stdout)

    if setup == "repeated_cleanup_apply":
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
                ]
            },
            hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
        )
        return {
            "first": _run_cleanup_apply_json(project, env=env),
            "second": _run_cleanup_apply_json(project, env=env),
        }

    raise AssertionError(f"unsupported edge setup: {setup}")
def _assert_boundary_axes_visible(nodeid: str, axes: tuple[str, ...], context: str) -> None:
    for axis in axes:
        assert axis in nodeid, f"{context}: missing axis {axis!r} in node id {nodeid}"
