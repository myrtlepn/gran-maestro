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
    "malformed_settings",
    "missing_hooks_registry",
    "parse_error",
    "permission_denied",
    "unknown_environment",
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


@pytest.mark.parametrize("row", SCENARIO_MATRIX_ROWS, ids=[row["id"] for row in SCENARIO_MATRIX_ROWS])
def test_boundary_scenario_matrix_rows_lock_expected_actions_and_hook_layers(tmp_path, request, row):
    project, env, source_repo = _setup_boundary_matrix_scenario(tmp_path, row["setup"])
    payload = _run_cleanup_dry_run_json(project, env=env, source_repo=source_repo)

    _assert_boundary_axes_visible(request.node.nodeid, row["axes"], row["scenario"])

    assert set(row["allowed_hook_layers"]).issubset(DOD002_CLASSIFICATIONS), (
        f"{row['scenario']} uses unsupported hook layer vocabulary: {row['allowed_hook_layers']}"
    )
    assert set(_collect_classifications(payload)) == set(row["allowed_hook_layers"]), (
        f"{row['scenario']} must converge to {row['allowed_hook_layers']}"
    )
    assert payload["environment"]["project_kind"] == row["project_kind"], row["scenario"]
    assert payload["environment"]["cleanup_scope"] == row["expected_cleanup_scope"], row["scenario"]
    assert payload["environment"]["user_global_present"] is row["expected_user_global_present"], row["scenario"]
    assert payload["status"] == row["expected_status"], (
        f"{row['scenario']} expected_action={row['expected_action']}"
    )
    assert payload.get("reason") == row["expected_reason"], row["scenario"]
    assert payload["rollback_available"] is row["expected_rollback_available"], row["scenario"]
    assert tuple(payload["settings"]["removed"]) == row["expected_settings_removed"], row["scenario"]
    assert tuple(sorted(Path(path).name for path in payload["files"]["targets"])) == row["expected_target_files"], (
        f"{row['scenario']} should only target MST legacy files"
    )
    assert tuple(payload["post_check_required"]) == row["expected_post_check_required"], row["scenario"]

    user_global_text = json.dumps(payload["user_global"], ensure_ascii=False)
    if row["expected_user_global_hook"]:
        assert "check-version.sh" in user_global_text, row["scenario"]
    else:
        assert "check-version.sh" not in user_global_text, row["scenario"]


def test_boundary_scenario_matrix_allowed_hook_layers_use_locked_vocabulary():
    matrix_layers = {
        layer
        for row in SCENARIO_MATRIX_ROWS
        for layer in row["allowed_hook_layers"]
    }

    assert matrix_layers == DOD002_CLASSIFICATIONS


@pytest.mark.parametrize("row", EDGE_MATRIX_ROWS, ids=[row["id"] for row in EDGE_MATRIX_ROWS])
def test_boundary_edge_matrix_rows_lock_status_reason_rollback_and_post_check(tmp_path, request, row):
    payload = _execute_boundary_edge_case(tmp_path, row["setup"])

    _assert_boundary_axes_visible(request.node.nodeid, row["axes"], row["scenario"])

    if row["setup"] == "repeated_cleanup_apply":
        first = payload["first"]
        second = payload["second"]

        for label, item, expected_status, expected_rollback, expected_mutation, expected_removed, expected_deleted in (
            (
                "first",
                first,
                row["first_expected_status"],
                row["first_expected_rollback_available"],
                row["first_expected_mutation"],
                row["first_expected_settings_removed"],
                row["first_expected_deleted_files"],
            ),
            (
                "second",
                second,
                row["second_expected_status"],
                row["second_expected_rollback_available"],
                row["second_expected_mutation"],
                row["second_expected_settings_removed"],
                row["second_expected_deleted_files"],
            ),
        ):
            assert item["status"] == expected_status, f"{row['scenario']} {label}"
            assert item.get("reason") == row["expected_reason"], f"{row['scenario']} {label}"
            assert item["rollback_available"] is expected_rollback, f"{row['scenario']} {label}"
            assert item["mutation"] == expected_mutation, f"{row['scenario']} {label}"
            assert tuple(item["settings"]["removed"]) == expected_removed, f"{row['scenario']} {label}"
            assert tuple(sorted(Path(path).name for path in item["files"]["deleted"])) == expected_deleted, (
                f"{row['scenario']} {label}"
            )
            assert row["expected_diag_codes"].issubset(_diagnostic_codes(item)), f"{row['scenario']} {label}"
            checks = item.get("post_check", {}).get("checks")
            assert isinstance(checks, dict), f"{row['scenario']} {label} missing post_check.checks"
            assert set(row["expected_post_check_keys"]).issubset(checks), f"{row['scenario']} {label}"
        return

    assert payload["status"] == row["expected_status"], row["scenario"]
    assert payload.get("reason") == row["expected_reason"], row["scenario"]
    assert payload["rollback_available"] is row["expected_rollback_available"], row["scenario"]
    assert payload["mutation"] == row["expected_mutation"], row["scenario"]
    assert row["expected_diag_codes"].issubset(_diagnostic_codes(payload)), row["scenario"]

    if row["destructive_mutation_allowed"]:
        expected_deleted = row.get("expected_deleted_files", ())
        assert tuple(sorted(Path(path).name for path in payload["files"]["deleted"])) == expected_deleted, (
            f"{row['scenario']} deleted files"
        )
    else:
        assert payload["files"].get("deleted", []) == [], f"{row['scenario']} must not delete files"
        assert payload["files"].get("targets", []) == [], f"{row['scenario']} must not stage file deletion targets"
        assert payload["settings"]["removed"] == [], f"{row['scenario']} must not remove settings hooks"

    checks = payload.get("post_check", {}).get("checks")
    if row["allow_post_check_omission"]:
        assert checks is None or set(row["expected_post_check_keys"]).issubset(checks), row["scenario"]
    else:
        assert isinstance(checks, dict), f"{row['scenario']} missing post_check.checks"
        assert set(row["expected_post_check_keys"]).issubset(checks), row["scenario"]

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
    payload = _run_cleanup_apply_json(project)
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
    payload = _run_cleanup_apply_json(project)
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
    payload = _run_cleanup_apply_json(project)
    assert payload["status"] == "ok"

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
    payload = _run_cleanup_apply_json(project)
    assert payload["status"] == "ok"

    hooks_dir = project / ".claude" / "hooks"
    for name in ["mst-stop-hook.sh", "mst-session-init.sh", "mst-pre-tool-use.sh", "mst-auto-chain-context.sh", ".mst-hook-version"]:
        assert not (hooks_dir / name).exists() or not hooks_dir.exists(), f"{name} still present"


def test_user_files_in_hooks_dir_preserved(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    payload = _run_cleanup_apply_json(project)
    assert payload["status"] == "ok"

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

    payload = _run_cleanup_apply_json(project)
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


def test_environment_contract_reports_priority_fields_for_normal_source_worktree_and_non_mst(tmp_path):
    normal = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=[])
    source = _setup_plugin_source_repo(tmp_path)
    worktree = tmp_path / ".gran-maestro" / "worktrees" / "REQ-1-T01"
    worktree.mkdir(parents=True)
    (worktree / ".gran-maestro").mkdir()
    (worktree / ".claude").mkdir()
    (worktree / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
    non_mst = tmp_path / "plain"
    non_mst.mkdir()

    cases = [
        (normal, "normal_project", False, False, "active"),
        (source, "source_repo", True, False, "source_repo"),
        (worktree, "worktree", False, True, "worktree"),
        (non_mst, "non_mst", False, False, "inactive"),
    ]

    for project, project_kind, is_source_repo, is_worktree, mst_mode in cases:
        payload = _run_cleanup_dry_run_json(project)
        environment = payload["environment"]
        assert environment["project_kind"] == project_kind
        assert environment["is_source_repo"] is is_source_repo
        assert environment["is_worktree"] is is_worktree
        assert environment["mst_mode"] == mst_mode
        assert isinstance(environment["user_global_present"], bool)
        assert environment["unknown_environment_reasons"] == []


def test_environment_unknown_priority_blocks_symlink_and_claude_project_dir_mismatch(tmp_path):
    real_project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=["mst-stop-hook.sh"])
    symlink_project = tmp_path / "linked-project"
    symlink_project.symlink_to(real_project, target_is_directory=True)
    payload = _run_cleanup_dry_run_json(symlink_project)

    assert payload["environment"]["project_kind"] == "unknown"
    assert "symlink_project_root" in payload["environment"]["unknown_environment_reasons"]
    assert payload["status"] in {"blocked", "diagnostic", "skipped"}
    assert payload["rollback_available"] is False
    assert payload["post_check_required"]

    payload = _run_cleanup_dry_run_json(
        real_project,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path / "other-project")},
    )

    assert payload["environment"]["project_kind"] == "unknown"
    assert "claude_project_dir_mismatch" in payload["environment"]["unknown_environment_reasons"]
    assert payload["status"] in {"blocked", "diagnostic", "skipped"}
    assert (real_project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()


def test_dry_run_json_schema_candidate_hash_rollback_and_preserved_hooks(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)

    payload = _run_cleanup_dry_run_json(project)

    assert payload["schema_version"] == DOD010_SCHEMA_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", payload["dry_run_id"])
    assert payload["dry_run"] is True
    assert payload["project_root"] == str(project)
    assert payload["created_at"].endswith("Z")
    assert payload["settings"]["removed"]
    assert payload["files"]["targets"]
    assert payload["preserved_user_hooks"]
    assert payload["candidate_set"]
    assert re.fullmatch(r"[0-9a-f]{64}", payload["candidate_hash"])
    assert payload["rollback"]["available"] is True
    assert payload["rollback"]["backup_path"]
    assert payload["rollback"]["inverse_operations"]
    assert payload["rollback_available"] is True
    assert payload["post_check_required"]
    assert isinstance(payload["skipped"], list)
    assert isinstance(payload["blocked"], list)


def test_dry_run_json_reports_reinjection_boundary_without_creating_canonical_runtime(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_dry_run_json(project)

    legacy_boundary = _boundary_item(payload, "legacy_project_local_hook_reinjection")
    assert legacy_boundary["status"] == "PASS"
    assert legacy_boundary["result"] == "reinjection-absent"
    assert legacy_boundary["settings_candidate_count"] == 1
    assert legacy_boundary["file_candidate_count"] == 1
    assert "create_.claude_hooks_copy" in legacy_boundary["prohibited_actions"]
    assert "reinsert_settings_local_hooks_as_canonical_runtime" in legacy_boundary["prohibited_actions"]
    assert payload["project_legacy"]["settings"]["candidates"]
    assert payload["project_legacy"]["files"]["candidates"]
    assert payload["settings"]["removed"] == ["$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"]
    assert Path(payload["files"]["targets"][0]).name == "mst-stop-hook.sh"
    assert _read_bytes_by_path(watched_paths) == before

    settings = _read_project_settings(project)
    assert _commands_for(settings, "Stop") == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        "/usr/local/bin/my-custom-stop-hook.sh",
    ]


def test_human_dry_run_summary_is_derived_from_json_candidate_fields(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    json_payload = _run_cleanup_dry_run_json(project)
    proc = _run_cleanup_human(project, "--dry-run")

    assert proc.returncode == 0
    summary = proc.stdout
    assert json_payload["settings"]["removed"][0] in summary
    assert json_payload["files"]["targets"][0] in summary
    assert json_payload["rollback"]["backup_path"] in summary
    for candidate in json_payload["candidate_set"]:
        value = candidate.get("command") or candidate.get("path")
        if value:
            assert value in summary
    assert "hooks/hooks.json" not in summary


def test_human_dry_run_reports_diagnostic_boundary_pass_skip_items(tmp_path):
    project = _setup_dod002_inventory_project(tmp_path)
    home = tmp_path / "home"
    _write_user_global_settings(home)

    proc = _run_cleanup_human(project, "--dry-run", env={"HOME": str(home)})

    assert proc.returncode == 0
    summary = proc.stdout
    assert "PASS legacy_project_local_hook_reinjection" in summary
    assert "PASS canonical_plugin_registration" in summary
    assert "PASS user_global_hook_preservation" in summary


def test_non_mst_dry_run_reports_post_check_fail_open_evidence(tmp_path):
    project = tmp_path / "plain"
    project.mkdir()
    home = tmp_path / "home"
    _write_user_global_settings(home)

    payload = _run_cleanup_dry_run_json(project, env={"HOME": str(home)})
    checks = _post_check_checks(payload)

    assert payload["status"] == "skipped"
    assert payload["reason"] == "non-MST project fail-open"
    assert payload["post_check"]["passed"] is True
    assert checks["stale_cleanup_candidates_absent"] is True
    assert checks["non_mst_user_global_fail_open"] is True
    assert checks["plugin_core_canonical_command"] is True
    assert checks["user_custom_preserved"] is True


def test_apply_blocks_without_dry_run_artifact_when_candidates_exist(tmp_path):
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
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    before_settings = (project / ".claude" / "settings.local.json").read_bytes()

    payload = _run_cleanup_apply_without_dry_run_json(project)
    settings = _read_project_settings(project)

    assert payload["status"] == "blocked"
    assert payload["reason"] == "dry_run_artifact_unavailable"
    assert "dry_run_artifact_missing" in _diagnostic_codes(payload)
    assert (project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
    assert _commands_for(settings, "Stop") == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        "/usr/local/bin/my-custom-stop-hook.sh",
    ]
    assert (project / ".claude" / "settings.local.json").read_bytes() == before_settings
    diagnostics = _diagnostics_with_code(payload, "dry_run_artifact_missing")
    assert diagnostics
    assert diagnostics[0]["result"] == "preserved-state"



def test_apply_blocks_when_candidate_set_drifts_after_dry_run_and_preserves_custom(tmp_path):
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
        },
        hook_files=["mst-stop-hook.sh", "mst-session-init.sh", "my-user-hook.sh"],
    )
    dry_run = _run_cleanup_dry_run_json(project)
    assert dry_run["candidate_hash"]

    (project / ".claude" / "hooks" / "mst-session-init.sh").unlink()
    before_settings = (project / ".claude" / "settings.local.json").read_bytes()
    before_custom = (project / ".claude" / "hooks" / "my-user-hook.sh").read_bytes()

    payload = _run_cleanup_apply_json(project, dry_run_payload=dry_run)
    settings = _read_project_settings(project)

    assert payload["status"] in {"blocked", "diagnostic"}
    assert payload["reason"] == "dry_run_candidate_mismatch"
    assert "candidate_hash_mismatch" in _diagnostic_codes(payload)
    assert (project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
    assert _commands_for(settings, "Stop") == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
        "/usr/local/bin/my-custom-stop-hook.sh",
    ]
    assert (project / ".claude" / "settings.local.json").read_bytes() == before_settings
    assert (project / ".claude" / "hooks" / "my-user-hook.sh").read_bytes() == before_custom
    diagnostics = _diagnostics_with_code(payload, "candidate_hash_mismatch")
    assert diagnostics
    assert diagnostics[0]["result"] == "preserved-state"


def test_source_repo_default_skip_excludes_plugin_core_hooks_from_candidates(tmp_path):
    plugin_repo = _setup_plugin_source_repo(tmp_path)

    payload = _run_cleanup_dry_run_json(plugin_repo)
    payload_text = json.dumps(
        {
            "settings": payload["settings"],
            "files": payload["files"],
            "candidate_set": payload["candidate_set"],
            "rollback": payload["rollback"],
        },
        ensure_ascii=False,
    )

    assert payload["status"] == "skipped"
    assert payload["environment"]["project_kind"] == "source_repo"
    assert payload["settings"]["removed"] == []
    assert payload["files"]["targets"] == []
    assert "hooks/hooks.json" not in payload_text
    assert str(plugin_repo / "hooks" / "mst-stop-hook.sh") not in payload_text
    source_boundary = _boundary_item(payload, "legacy_project_local_hook_reinjection")
    assert source_boundary["status"] == "SKIP"
    assert source_boundary["result"] == "diagnostic-only"
    assert _boundary_item(payload, "canonical_plugin_registration")["status"] == "PASS"


def test_cleanup_apply_preserves_custom_command_in_mixed_matcher_and_reports_inventory(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "Stop": [
                {
                    "matcher": "shell",
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

    payload = _run_cleanup_apply_json(project)

    settings = _read_project_settings(project)
    stop_commands = _commands_for(settings, "Stop", "shell")
    assert stop_commands == ["/usr/local/bin/my-custom-stop-hook.sh"]
    assert _commands_for(settings, "UserPromptSubmit") == ["/home/user/scripts/my-prompt-hook.sh"]

    assert payload["status"] == "ok"
    assert payload["mutation"] == {"dry_run": False, "mutated": True}
    assert DOD002_TOP_LEVEL_FIELDS.issubset(payload)


def test_cleanup_mixed_settings_removes_legacy_only_and_preserves_local_config(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "PreToolUse": [
                {
                    "matcher": "Skill",
                    "hooks": [
                        {"type": "command", "command": "$(git rev-parse --show-toplevel)/.claude/hooks/mst-pre-tool-use.sh"},
                        {"type": "command", "command": "/opt/local/pre-tool-user-hook.sh"},
                    ],
                }
            ],
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
        hook_files=["mst-stop-hook.sh", "mst-pre-tool-use.sh", "my-user-hook.sh"],
    )
    settings_path = project / ".claude" / "settings.local.json"
    mixed_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    mixed_settings.update(
        {
            "env": {"GRAN_MAESTRO_TEST": "keep"},
            "statusLine": {"type": "command", "command": "/usr/local/bin/status-line.sh"},
            "permissions": {
                "allow": ["Read", "Bash(git status:*)"],
                "deny": ["Bash(rm -rf:*)"],
            },
        }
    )
    settings_path.write_text(json.dumps(mixed_settings, indent=2) + "\n", encoding="utf-8")

    payload = _run_cleanup_apply_json(project)
    settings = _read_project_settings(project)

    assert payload["status"] == "ok"
    assert sorted(payload["settings"]["removed"]) == [
        "$(git rev-parse --show-toplevel)/.claude/hooks/mst-pre-tool-use.sh",
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh",
    ]
    assert settings["env"] == mixed_settings["env"]
    assert settings["permissions"] == mixed_settings["permissions"]
    assert settings["statusLine"] == mixed_settings["statusLine"]
    assert _commands_for(settings, "PreToolUse", "Skill") == [
        "/opt/local/pre-tool-user-hook.sh"
    ]
    assert _commands_for(settings, "Stop") == ["/usr/local/bin/my-custom-stop-hook.sh"]
    assert _commands_for(settings, "UserPromptSubmit") == [
        "/home/user/scripts/my-prompt-hook.sh"
    ]

    serialized_settings = json.dumps(settings, sort_keys=True)
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/" not in serialized_settings
    assert "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-" not in serialized_settings
    assert "$(git rev-parse --show-toplevel)/.claude/hooks/mst-" not in serialized_settings


def test_cleanup_files_only_known_legacy_removed_and_preserved_user_mst_like_files(tmp_path):
    known_legacy = [
        "mst-stop-hook.sh",
        "mst-session-init.sh",
        "mst-pre-tool-use.sh",
        "mst-auto-chain-context.sh",
    ]
    preserved_files = [
        "mst-user-custom.sh",
        "mst-stop-hook.local.sh",
        "my-user-hook.sh",
    ]
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=known_legacy + preserved_files,
    )

    payload = _run_cleanup_apply_json(project)

    hooks_dir = project / ".claude" / "hooks"
    assert all(not (hooks_dir / name).exists() for name in known_legacy)
    assert all((hooks_dir / name).exists() for name in preserved_files)
    deleted_basenames = {Path(path).name for path in payload["files"]["deleted"]}
    assert deleted_basenames == set(known_legacy)


def test_cleanup_apply_is_idempotent_no_op_on_second_run(tmp_path):
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
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )

    first_payload = _run_cleanup_apply_json(project)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    after_first = _read_bytes_by_path(watched_paths)

    second_payload = _run_cleanup_apply_json(project)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] in {"ok", "no_op"}
    assert second_payload["settings"]["removed"] == []
    assert second_payload["files"]["deleted"] == []
    assert second_payload["mutation"] == {"dry_run": False, "mutated": False}
    assert _read_bytes_by_path(watched_paths) == after_first


def test_cleanup_no_op_preserves_existing_empty_hooks_dir(tmp_path):
    project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=[])
    hooks_dir = project / ".claude" / "hooks"
    assert hooks_dir.exists()

    payload = _run_cleanup_apply_json(project)

    assert payload["status"] == "ok"
    assert payload["settings"]["removed"] == []
    assert payload["files"]["deleted"] == []
    assert payload["mutation"] == {"dry_run": False, "mutated": False}
    assert hooks_dir.exists()


def test_cleanup_malformed_settings_failure_reported_without_destructive_mutation(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    settings_path = project / ".claude" / "settings.local.json"
    settings_path.write_text('{"hooks": ', encoding="utf-8")
    watched_paths = [
        settings_path,
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    proc = _run_cleanup(project)
    payload = json.loads(proc.stdout)

    assert proc.returncode in {0, 1}
    assert payload["status"] in {"skipped", "error", "failed", "diagnostic"}
    assert {"malformed_settings", "parse_error"}.intersection(_diagnostic_codes(payload))
    assert any(
        diagnostic.get("result") == "safe-skip"
        for diagnostic in payload.get("diagnostics", [])
        if diagnostic.get("code") in {"malformed_settings", "parse_error"}
    )
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_read_only_settings_failure_reports_safe_skip_without_destructive_mutation(tmp_path):
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
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    settings_path = project / ".claude" / "settings.local.json"
    watched_paths = [
        settings_path,
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)
    settings_path.chmod(0o444)
    try:
        payload = _run_cleanup_dry_run_json(project)
    finally:
        settings_path.chmod(0o644)

    assert payload["status"] == "diagnostic"
    assert payload["settings"]["removed"] == []
    assert payload["files"]["targets"] == []
    diagnostics = _diagnostics_with_code(payload, "permission_denied")
    assert diagnostics
    assert any(diagnostic.get("result") == "safe-skip" for diagnostic in diagnostics)
    assert _boundary_item(payload, "legacy_project_local_hook_reinjection")["status"] == "DIAGNOSTIC"
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_unexpected_hooks_schema_failure_reported_without_destructive_mutation(tmp_path):
    project = _setup_registered_project(tmp_path, settings_hooks={}, hook_files=["my-user-hook.sh"])
    settings_path = project / ".claude" / "settings.local.json"
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "/usr/local/bin/my-custom-stop-hook.sh"}
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    watched_paths = [
        settings_path,
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    proc = _run_cleanup(project)
    payload = json.loads(proc.stdout)

    assert proc.returncode in {0, 1}
    assert payload["status"] in {"skipped", "error", "failed", "diagnostic"}
    assert "diagnostics" in payload
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_settings_write_failure_reports_reason_without_file_deletion(tmp_path):
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
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )
    claude_dir = project / ".claude"
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)
    dry_run = _run_cleanup_dry_run_json(project)
    claude_dir.chmod(0o555)
    try:
        proc = _run_cleanup(project, "--dry-run-id", dry_run["dry_run_id"])
    finally:
        claude_dir.chmod(0o755)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["status"] == "error"
    assert payload["reason"] == "settings.local.json write failed"
    assert payload["settings"]["failed"]
    assert payload["files"]["deleted"] == []
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_file_delete_failure_reports_reason_and_rolls_back_settings(tmp_path):
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
    hooks_dir = project / ".claude" / "hooks"
    watched_paths = [
        project / ".claude" / "settings.local.json",
        hooks_dir / "mst-stop-hook.sh",
        hooks_dir / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)
    dry_run = _run_cleanup_dry_run_json(project)
    hooks_dir.chmod(0o555)
    try:
        proc = _run_cleanup(project, "--dry-run-id", dry_run["dry_run_id"])
    finally:
        hooks_dir.chmod(0o755)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["status"] == "rollback"
    assert payload["reason"] == "file deletion failed; settings rollback attempted"
    assert payload["settings"]["rolled_back"] is True
    assert payload["files"]["failed"]
    assert _boundary_item(payload, "canonical_plugin_registration")["status"] == "PASS"
    assert _boundary_item(payload, "legacy_project_local_hook_reinjection")["result"] == "reinjection-absent"
    checks = _post_check_checks(payload)
    assert checks["rollback_restored_pre_mutation_state"] is True
    assert checks["stale_cleanup_reinjection_absent"] is True
    diagnostics = _diagnostics_with_code(payload, "file_deletion_failed")
    assert diagnostics
    assert diagnostics[0]["result"] == "preserved-state"
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_file_delete_failure_restores_files_after_partial_move(tmp_path, monkeypatch):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh", "mst-session-init.sh", "my-user-hook.sh"],
    )
    hooks_dir = project / ".claude" / "hooks"
    targets = [
        str(hooks_dir / "mst-stop-hook.sh"),
        str(hooks_dir / "mst-session-init.sh"),
    ]
    watched_paths = [Path(target) for target in targets] + [hooks_dir / "my-user-hook.sh"]
    before = _read_bytes_by_path(watched_paths)
    real_replace = on.os.replace
    move_count = 0

    def fail_second_move(src, dst):
        nonlocal move_count
        if str(src) in targets:
            move_count += 1
            if move_count == 2:
                raise OSError("simulated delete preparation failure")
        return real_replace(src, dst)

    monkeypatch.setattr(on.os, "replace", fail_second_move)

    deleted, failed = on._apply_file_deletions(targets)

    assert deleted == []
    assert failed
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_file_delete_failure_restores_files_after_quarantine_unlink_error(tmp_path, monkeypatch):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={},
        hook_files=["mst-stop-hook.sh", "mst-session-init.sh", "my-user-hook.sh"],
    )
    hooks_dir = project / ".claude" / "hooks"
    targets = [
        str(hooks_dir / "mst-stop-hook.sh"),
        str(hooks_dir / "mst-session-init.sh"),
    ]
    watched_paths = [Path(target) for target in targets] + [hooks_dir / "my-user-hook.sh"]
    before = _read_bytes_by_path(watched_paths)
    real_unlink = Path.unlink

    def fail_quarantine_unlink(self, *args, **kwargs):
        if ".mst-cleanup." in str(self):
            raise OSError("simulated final delete failure")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_quarantine_unlink)

    deleted, failed = on._apply_file_deletions(targets)

    assert deleted == []
    assert failed
    assert _read_bytes_by_path(watched_paths) == before


def test_cleanup_settings_rollback_failure_reports_error(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setenv("MST_PROJECT_ROOT", str(project))
    real_replace = on.os.replace

    def fake_file_deletions(targets):
        def fail_restore_replace(src, dst):
            if str(dst).endswith("settings.local.json"):
                raise OSError("simulated settings rollback failure")
            return real_replace(src, dst)

        monkeypatch.setattr(on.os, "replace", fail_restore_replace)
        return [], [(str(project / ".claude" / "hooks" / "mst-stop-hook.sh"), "simulated delete failure")]

    monkeypatch.setattr(on, "_apply_file_deletions", fake_file_deletions)
    _run_cleanup_dry_run_json(project)
    args = type("Args", (), {"dry_run": False, "source_repo": False, "dry_run_id": None, "dry_run_artifact": None, "json": True, "silent": False})()

    rc = on.cmd_on_cleanup(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "error"
    assert payload["reason"] == "file deletion failed; settings rollback failed"
    assert payload["settings"]["rolled_back"] is False
    assert "rollback_error" in payload["settings"]
    assert payload["mutation"] == {"dry_run": False, "mutated": False}


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
    (project / ".claude-plugin").mkdir()

    payload = _run_cleanup_dry_run_json(project)

    assert "unknown_environment" in _diagnostic_codes(payload)
    assert payload["environment"]["project_kind"] == "unknown"


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
    plugin_repo = _setup_plugin_source_repo(tmp_path)
    watched_paths = [
        plugin_repo / ".claude" / "settings.local.json",
        plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh",
        plugin_repo / "hooks" / "hooks.json",
        plugin_repo / "hooks" / "mst-stop-hook.sh",
        plugin_repo / ".claude-plugin" / "plugin.json",
    ]
    before = _read_bytes_by_path(watched_paths)

    dry_run = _run_cleanup(plugin_repo, "--dry-run")
    apply = _run_cleanup(plugin_repo)

    assert dry_run.returncode == 0
    assert apply.returncode == 0
    dry_run_payload = json.loads(dry_run.stdout)
    apply_payload = json.loads(apply.stdout)
    for payload, dry_run_value in ((dry_run_payload, True), (apply_payload, False)):
        assert payload["status"] == "skipped"
        assert "plugin source repo" in payload["reason"]
        assert payload["mutation"] == {"dry_run": dry_run_value, "mutated": False}
    assert _read_bytes_by_path(watched_paths) == before


def test_source_repo_cleanup_opt_in_dry_run_previews_legacy_only(tmp_path):
    plugin_repo = _setup_plugin_source_repo(tmp_path)

    proc = _run_cleanup(plugin_repo, "--dry-run", "--source-repo")

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "dry_run"
    assert payload["environment"]["kind"] == "source-dev"
    assert payload["environment"]["source_repo"] is True
    assert payload["environment"]["cleanup_scope"] == "source-repo-opt-in"
    assert payload["mutation"] == {"dry_run": True, "mutated": False}
    assert any("mst-stop-hook.sh" in command for command in payload["settings"]["removed"])
    assert {Path(path).name for path in payload["files"]["targets"]} == {
        "mst-stop-hook.sh",
        "mst-session-init.sh",
    }
    payload_text = json.dumps({"settings": payload["settings"], "files": payload["files"]}, ensure_ascii=False)
    assert "hooks/hooks.json" not in payload_text
    assert ".claude-plugin/plugin.json" not in payload_text
    assert "my-user-hook.sh" not in payload_text


def test_source_repo_cleanup_opt_in_apply_preserves_plugin_source_and_user_custom(tmp_path):
    plugin_repo = _setup_plugin_source_repo(tmp_path)
    preserved_paths = [
        plugin_repo / ".claude" / "hooks" / "my-user-hook.sh",
        plugin_repo / "hooks" / "hooks.json",
        plugin_repo / "hooks" / "mst-stop-hook.sh",
        plugin_repo / ".claude-plugin" / "plugin.json",
    ]
    before_preserved = _read_bytes_by_path(preserved_paths)

    payload = _run_cleanup_apply_json(plugin_repo)

    assert payload["status"] == "skipped"
    opt_in_dry_run = _run_cleanup_dry_run_json(plugin_repo, source_repo=True)
    opt_in_payload = json.loads(_run_cleanup(plugin_repo, "--source-repo", "--dry-run-id", opt_in_dry_run["dry_run_id"]).stdout)
    assert opt_in_payload["status"] == "ok"
    assert opt_in_payload["environment"]["cleanup_scope"] == "source-repo-opt-in"
    assert opt_in_payload["mutation"] == {"dry_run": False, "mutated": True}
    settings = _read_project_settings(plugin_repo)
    assert _commands_for(settings, "Stop") == ["/usr/local/bin/my-custom-stop-hook.sh"]
    assert not (plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
    assert not (plugin_repo / ".claude" / "hooks" / "mst-session-init.sh").exists()
    assert _read_bytes_by_path(preserved_paths) == before_preserved


def test_source_repo_cleanup_opt_in_apply_is_idempotent(tmp_path):
    plugin_repo = _setup_plugin_source_repo(tmp_path)
    preserved_paths = [
        plugin_repo / ".claude" / "settings.local.json",
        plugin_repo / ".claude" / "hooks" / "my-user-hook.sh",
        plugin_repo / "hooks" / "hooks.json",
        plugin_repo / "hooks" / "mst-stop-hook.sh",
        plugin_repo / ".claude-plugin" / "plugin.json",
    ]

    first_dry_run = _run_cleanup_dry_run_json(plugin_repo, source_repo=True)
    first_payload = json.loads(_run_cleanup(plugin_repo, "--source-repo", "--dry-run-id", first_dry_run["dry_run_id"]).stdout)
    after_first = _read_bytes_by_path(preserved_paths)
    second_dry_run = _run_cleanup_dry_run_json(plugin_repo, source_repo=True)
    second_payload = json.loads(_run_cleanup(plugin_repo, "--source-repo", "--dry-run-id", second_dry_run["dry_run_id"]).stdout)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] in {"ok", "no_op"}
    assert second_payload["settings"]["removed"] == []
    assert second_payload["files"]["deleted"] == []
    assert second_payload["mutation"] == {"dry_run": False, "mutated": False}
    assert _read_bytes_by_path(preserved_paths) == after_first


def test_source_repo_cleanup_opt_in_file_failure_rolls_back_without_canonical_deletion(tmp_path, monkeypatch, capsys):
    plugin_repo = _setup_plugin_source_repo(tmp_path)
    monkeypatch.setenv("MST_PROJECT_ROOT", str(plugin_repo))
    watched_paths = [
        plugin_repo / ".claude" / "settings.local.json",
        plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh",
        plugin_repo / ".claude" / "hooks" / "mst-session-init.sh",
        plugin_repo / ".claude" / "hooks" / "my-user-hook.sh",
        plugin_repo / "hooks" / "hooks.json",
        plugin_repo / "hooks" / "mst-stop-hook.sh",
        plugin_repo / ".claude-plugin" / "plugin.json",
    ]
    before = _read_bytes_by_path(watched_paths)

    _run_cleanup_dry_run_json(plugin_repo, source_repo=True)
    monkeypatch.setattr(
        on,
        "_apply_file_deletions",
        lambda targets: ([], [(str(plugin_repo / ".claude" / "hooks" / "mst-stop-hook.sh"), "simulated delete failure")]),
    )
    args = type("Args", (), {"dry_run": False, "source_repo": True, "dry_run_id": None, "dry_run_artifact": None, "json": True, "silent": False})()

    rc = on.cmd_on_cleanup(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "rollback"
    assert payload["reason"] == "file deletion failed; settings rollback attempted"
    assert payload["settings"]["rolled_back"] is True
    assert payload["files"]["failed"]
    assert payload["environment"]["cleanup_scope"] == "source-repo-opt-in"
    assert _read_bytes_by_path(watched_paths) == before
