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
