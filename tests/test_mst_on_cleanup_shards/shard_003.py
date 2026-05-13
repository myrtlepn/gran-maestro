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
def test_duplicate_canonical_registration_diagnostic_dedupes_plugin_core_output(tmp_path):
    project = _setup_duplicate_canonical_plugin_source_repo(tmp_path)

    payload = _run_cleanup_dry_run_json(project, source_repo=True)

    stop_commands = [
        hook["command"]
        for hook in payload["plugin_core"]["hooks"]
        if hook.get("event") == "Stop"
    ]
    assert stop_commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/mst-stop-hook.sh"]
    diagnostics = _diagnostics_with_code(payload, "duplicate_canonical_registration")
    assert diagnostics
    assert diagnostics[0]["result"] in {"diagnostic", "safe-skip"}
    assert diagnostics[0]["status"] == "diagnostic"
    duplicate_sources = diagnostics[0].get("duplicate_sources")
    assert isinstance(duplicate_sources, list) and len(duplicate_sources) >= 2
    assert any("hooks/hooks.json" in source for source in duplicate_sources)
def test_duplicate_legacy_registration_diagnostic_dedupes_candidate_output(tmp_path):
    project = _setup_registered_project(
        tmp_path,
        settings_hooks={
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"},
                        {"type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"},
                        {"type": "command", "command": "/usr/local/bin/my-custom-stop-hook.sh"},
                    ],
                }
            ]
        },
        hook_files=["mst-stop-hook.sh", "my-user-hook.sh"],
    )

    payload = _run_cleanup_dry_run_json(project)

    assert payload["settings"]["removed"] == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/mst-stop-hook.sh"
    ]
    diagnostics = _diagnostics_with_code(payload, "duplicate_legacy_registration")
    assert diagnostics
    assert diagnostics[0]["status"] == "diagnostic"
    assert diagnostics[0]["result"] == "safe-skip"
    duplicate_sources = diagnostics[0].get("duplicate_sources")
    assert isinstance(duplicate_sources, list) and len(duplicate_sources) == 2
    assert all("settings.local.json" in source for source in duplicate_sources)
def test_unknown_hook_command_preserved_with_manual_review_diagnostic(tmp_path):
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
            "PreToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict",
                        }
                    ],
                }
            ],
        },
        hook_files=["mst-stop-hook.sh", "project-unknown-hook.sh", "my-user-hook.sh"],
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
    assert settings["env"] == mixed_settings["env"]
    assert settings["permissions"] == mixed_settings["permissions"]
    assert settings["statusLine"] == mixed_settings["statusLine"]
    assert _commands_for(settings, "Stop") == ["/usr/local/bin/my-custom-stop-hook.sh"]
    assert _commands_for(settings, "PreToolUse", "Write") == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict"
    ]
    assert (project / ".claude" / "hooks" / "project-unknown-hook.sh").exists()
    diagnostics = _diagnostics_with_code(payload, "unknown_hook_command")
    assert diagnostics
    assert diagnostics[0]["status"] == "diagnostic"
    assert diagnostics[0]["result"] == "safe-skip"
    assert diagnostics[0]["reason"] == "manual-review"
    assert diagnostics[0]["command"] == "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict"
def test_mixed_unknown_user_global_cleanup_flow_preserves_local_and_global_boundaries(tmp_path):
    home = tmp_path / "home-mixed"
    user_settings_path = _write_mixed_user_global_settings(home)
    before_user_bytes = user_settings_path.read_bytes()
    before_user_membership = _settings_commands_by_event(json.loads(before_user_bytes))

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
            "PreToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict",
                        }
                    ],
                }
            ],
        },
        hook_files=["mst-stop-hook.sh", "project-unknown-hook.sh", "my-user-hook.sh"],
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

    env = {"HOME": str(home)}
    dry_proc = _run_cleanup(project, "--dry-run", env=env)
    assert dry_proc.returncode == 0, f"stderr: {dry_proc.stderr}\nstdout: {dry_proc.stdout}"
    dry_payload = json.loads(dry_proc.stdout)

    apply_proc = _run_cleanup(project, "--dry-run-id", dry_payload["dry_run_id"], env=env)
    assert apply_proc.returncode == 0, f"stderr: {apply_proc.stderr}\nstdout: {apply_proc.stdout}"
    apply_payload = json.loads(apply_proc.stdout)

    after_user_bytes = user_settings_path.read_bytes()
    after_user_membership = _settings_commands_by_event(json.loads(after_user_bytes))
    assert after_user_bytes == before_user_bytes
    assert after_user_membership == before_user_membership

    settings = _read_project_settings(project)
    assert settings["env"] == mixed_settings["env"]
    assert settings["permissions"] == mixed_settings["permissions"]
    assert settings["statusLine"] == mixed_settings["statusLine"]
    assert _commands_for(settings, "Stop") == ["/usr/local/bin/my-custom-stop-hook.sh"]
    assert _commands_for(settings, "PreToolUse", "Write") == [
        "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict"
    ]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/" not in settings_path.read_text(encoding="utf-8")
    assert not (project / ".claude" / "hooks" / "mst-stop-hook.sh").exists()
    assert (project / ".claude" / "hooks" / "project-unknown-hook.sh").exists()

    dry_unknown = _diagnostics_with_code(dry_payload, "unknown_hook_command")
    apply_unknown = _diagnostics_with_code(apply_payload, "unknown_hook_command")
    assert dry_unknown and apply_unknown
    for diagnostic in (dry_unknown[0], apply_unknown[0]):
        assert diagnostic["status"] == "diagnostic"
        assert diagnostic["result"] == "safe-skip"
        assert diagnostic["reason"] == "manual-review"
        assert diagnostic["command"] == "$CLAUDE_PROJECT_DIR/.claude/hooks/project-unknown-hook.sh --mode strict"

    assert _boundary_item(dry_payload, "legacy_project_local_hook_reinjection")["result"] == "reinjection-absent"
    assert _boundary_item(apply_payload, "legacy_project_local_hook_reinjection")["result"] == "reinjection-absent"
    assert _boundary_item(dry_payload, "user_global_hook_preservation")["result"] == "preserved-state"
    assert _boundary_item(apply_payload, "user_global_hook_preservation")["result"] == "preserved-state"
    assert dry_payload["plugin_core"]["status"] == "canonical"
    assert apply_payload["plugin_core"]["status"] == "canonical"
    assert all(hook["classification"] == "user_global" for hook in dry_payload["user_global"]["hooks"])
    assert all(hook["classification"] == "user_global" for hook in apply_payload["user_global"]["hooks"])
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
def test_cleanup_missing_manifest_failure_preserves_state_without_reinjection(tmp_path):
    project, env = _setup_missing_manifest_cleanup_fixture(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_dry_run_json(project, env=env)

    assert payload["status"] == "diagnostic"
    assert "missing_plugin_manifest" in _diagnostic_codes(payload)
    assert payload["settings"]["removed"] == []
    assert payload["files"]["targets"] == []
    assert _boundary_item(payload, "legacy_project_local_hook_reinjection")["status"] == "DIAGNOSTIC"
    assert _read_bytes_by_path(watched_paths) == before
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/" not in watched_paths[0].read_text(encoding="utf-8")
def test_cleanup_broken_canonical_registration_failure_preserves_state_without_reinjection(tmp_path):
    project, env = _setup_broken_canonical_cleanup_fixture(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / "hooks" / "hooks.json",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_dry_run_json(project, env=env, source_repo=True)

    assert payload["status"] == "diagnostic"
    assert "broken_canonical_registration" in _diagnostic_codes(payload)
    assert payload["settings"]["removed"] == []
    assert payload["files"]["targets"] == []
    assert _boundary_item(payload, "canonical_plugin_registration")["status"] == "DIAGNOSTIC"
    assert _read_bytes_by_path(watched_paths) == before
def test_cleanup_stale_cache_failure_preserves_state_without_reinjection(tmp_path):
    project, env, cache_root = _setup_stale_cache_cleanup_fixture(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
        cache_root / "0.57.6" / ".claude-plugin" / "plugin.json",
        cache_root / "0.57.6" / "hooks" / "hooks.json",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_apply_without_dry_run_json(project, env=env)

    assert payload["status"] in {"blocked", "diagnostic"}
    assert "stale_plugin_cache" in _diagnostic_codes(payload)
    assert payload["settings"]["removed"] == []
    assert payload["files"]["deleted"] == []
    assert _read_bytes_by_path(watched_paths) == before
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/" not in watched_paths[0].read_text(encoding="utf-8")
def test_cleanup_cache_sync_failure_preserves_state_without_reinjection(tmp_path):
    project, env, cache_root = _setup_cache_sync_failure_cleanup_fixture(tmp_path)
    watched_paths = [
        project / ".claude" / "settings.local.json",
        project / ".claude" / "hooks" / "mst-stop-hook.sh",
        project / ".claude" / "hooks" / "my-user-hook.sh",
        cache_root / _plugin_version() / ".claude-plugin" / "plugin.json",
        cache_root / _plugin_version() / "hooks" / "mst-stop-hook.sh",
    ]
    before = _read_bytes_by_path(watched_paths)

    payload = _run_cleanup_apply_without_dry_run_json(project, env=env)

    assert payload["status"] in {"blocked", "diagnostic"}
    assert "cache_sync_failure" in _diagnostic_codes(payload)
    assert payload["settings"]["removed"] == []
    assert payload["files"]["deleted"] == []
    assert _read_bytes_by_path(watched_paths) == before
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/" not in watched_paths[0].read_text(encoding="utf-8")
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
