def _duplicate_risks(plugin_core: dict, project_legacy: dict) -> List[dict]:
    plugin_events = {
        item.get("event")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and item.get("event")
    }
    legacy_events = {
        item.get("event")
        for group in (
            project_legacy.get("settings", {}).get("candidates", []),
            project_legacy.get("files", {}).get("candidates", []),
        )
        for item in group
        if isinstance(item, dict) and item.get("event")
    }
    risks: List[dict] = []
    for event in sorted(plugin_events & legacy_events):
        risks.append(
            {
                "event": event,
                "sources": [CLASS_PLUGIN_CORE, CLASS_PROJECT_LEGACY],
                "classifications": [CLASS_PLUGIN_CORE, CLASS_PROJECT_LEGACY],
                "reason": "plugin_core_and_project_legacy_hooks_coexist",
            }
        )
    return risks
def _mark_source_dev_project_legacy(project_legacy: dict) -> None:
    for group in (
        project_legacy.get("settings", {}).get("candidates", []),
        project_legacy.get("files", {}).get("candidates", []),
    ):
        for item in group:
            if isinstance(item, dict):
                item["status"] = "skipped"
                item["reason"] = "source_dev_diagnostic_only"
def _build_cleanup_inventory(
    project_root: Path,
    *,
    dry_run: bool,
    mutated: bool,
    source_repo_opt_in: bool = False,
) -> dict:
    diagnostics: List[dict] = []
    environment = _classify_environment(project_root, diagnostics, source_repo_opt_in=source_repo_opt_in)
    plugin_core = _plugin_core_inventory(project_root, diagnostics)
    project_legacy, user_custom = _project_legacy_and_custom_inventory(project_root, diagnostics)
    user_global = _user_global_inventory(diagnostics)
    _plugin_cache_inventory_diagnostics(diagnostics)
    if environment.get("source_repo") and not source_repo_opt_in:
        _mark_source_dev_project_legacy(project_legacy)

    return {
        "mutation": {"dry_run": dry_run, "mutated": mutated},
        "environment": environment,
        "plugin_core": plugin_core,
        "project_legacy": project_legacy,
        "user_global": user_global,
        "user_custom": user_custom,
        "duplicate_risks": _duplicate_risks(plugin_core, project_legacy),
        "diagnostics": diagnostics,
    }
def _settings_diagnostics_block_mutation(project_root: Path, diagnostics: List[dict]) -> bool:
    settings_path = str(project_root / ".claude" / "settings.local.json")
    blocking_codes = {
        DIAGNOSTIC_MALFORMED_SETTINGS,
        DIAGNOSTIC_PARSE_ERROR,
        DIAGNOSTIC_PERMISSION_DENIED,
    }
    for diagnostic in diagnostics:
        if diagnostic.get("path") != settings_path:
            continue
        if diagnostic.get("code") in blocking_codes:
            return True
    return False
def _diagnostics_block_mutation(project_root: Path, inventory: dict) -> bool:
    environment = inventory.get("environment", {})
    if environment.get("project_kind") == "unknown" or environment.get("unknown_environment_reasons"):
        return True
    diagnostics = inventory.get("diagnostics", [])
    blocking_codes = {
        DIAGNOSTIC_BROKEN_CANONICAL_REGISTRATION,
        DIAGNOSTIC_CACHE_SYNC_FAILURE,
        DIAGNOSTIC_MISSING_PLUGIN_MANIFEST,
        DIAGNOSTIC_STALE_PLUGIN_CACHE,
    }
    if any(isinstance(item, dict) and item.get("code") in blocking_codes for item in diagnostics):
        return True
    return _settings_diagnostics_block_mutation(project_root, diagnostics)
def _candidate_set(settings_removed: List[str], file_targets: List[str], project_root: Path) -> List[dict]:
    settings_path = project_root / ".claude" / "settings.local.json"
    candidates: List[dict] = []
    for command in sorted(settings_removed):
        candidates.append(
            {
                "type": "settings_hook",
                "path": str(settings_path),
                "command": command,
            }
        )
    for target in sorted(file_targets):
        target_path = Path(target)
        candidates.append(
            {
                "type": "hook_file",
                "path": str(target_path),
                "name": target_path.name,
            }
        )
    return candidates
def _candidate_hash(candidate_set: List[dict]) -> str:
    encoded = json.dumps(candidate_set, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
def _created_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
def _cleanup_artifact_path(project_root: Path) -> Optional[Path]:
    base_dir = project_root / ".gran-maestro"
    if not base_dir.exists():
        return None
    return _common.tmp_dir(project_root) / CLEANUP_DRY_RUN_ARTIFACT
def _rollback_plan(project_root: Path, candidate_set: List[dict]) -> dict:
    backup_path = _common.tmp_dir(project_root) / "mst-on-cleanup-rollback.json"
    inverse_operations: List[dict] = []
    restore_targets: List[str] = []
    for candidate in candidate_set:
        candidate_path = candidate.get("path")
        if isinstance(candidate_path, str) and candidate_path not in restore_targets:
            restore_targets.append(candidate_path)
        if candidate.get("type") == "settings_hook":
            inverse_operations.append(
                {
                    "type": "restore_settings_hook",
                    "path": candidate_path,
                    "command": candidate.get("command"),
                }
            )
        elif candidate.get("type") == "hook_file":
            inverse_operations.append(
                {
                    "type": "restore_hook_file",
                    "path": candidate_path,
                }
            )
    return {
        "available": bool(candidate_set),
        "backup_path": str(backup_path),
        "restore_targets": restore_targets,
        "inverse_operations": inverse_operations,
    }
def _post_check_required(environment: dict) -> List[str]:
    checks = [
        "stale_cleanup_candidates_absent",
        "plugin_core_canonical_command",
        "user_custom_preserved",
    ]
    project_kind = environment.get("project_kind")
    if project_kind == "source_repo":
        checks.append("source_repo_default_skip_or_opt_in")
    if project_kind == "worktree":
        checks.append("worktree_no_legacy_propagation")
    if project_kind == "non_mst" or environment.get("user_global_present"):
        checks.append("non_mst_user_global_fail_open")
    return checks
def _preserved_user_hooks(user_custom: dict) -> List[dict]:
    preserved: List[dict] = []
    for item in user_custom.get("settings", []):
        if isinstance(item, dict):
            preserved.append(
                {
                    "type": "settings_hook",
                    "event": item.get("event"),
                    "matcher": item.get("matcher", ""),
                    "command": item.get("command"),
                    "reason": item.get("reason", "user_custom_settings_hook"),
                }
            )
    for item in user_custom.get("files", []):
        if isinstance(item, dict):
            preserved.append(
                {
                    "type": "hook_file",
                    "path": item.get("path"),
                    "name": item.get("name"),
                    "reason": item.get("reason", "user_custom_hook_file"),
                }
            )
    return preserved
def _status_items(diagnostics: List[dict], status: str) -> List[dict]:
    return [
        {
            "status": status,
            "reason": item.get("reason") or item.get("reason_code") or item.get("code"),
            "reason_code": item.get("reason_code") or item.get("code"),
            "result": item.get("result") or item.get("outcome"),
            "outcome": item.get("outcome") or item.get("result"),
            "message": item.get("message", ""),
            "path": item.get("path"),
        }
        for item in diagnostics
    ]
def _migration_boundary_items(inventory: dict) -> List[dict]:
    environment = inventory.get("environment", {})
    plugin_core = inventory.get("plugin_core", {})
    project_legacy = inventory.get("project_legacy", {})
    user_global = inventory.get("user_global", {})
    diagnostics = inventory.get("diagnostics", [])

    settings_candidates = project_legacy.get("settings", {}).get("candidates", [])
    file_candidates = project_legacy.get("files", {}).get("candidates", [])
    legacy_candidate_count = len(settings_candidates) + len(file_candidates)
    source_default_skip = bool(environment.get("source_repo")) and environment.get("cleanup_scope") == "skipped"
    blocked = _diagnostics_block_mutation(Path(environment.get("project_root", "")), inventory)

    if source_default_skip:
        legacy_status = "SKIP"
        legacy_result = "diagnostic-only"
        legacy_message = "source-dev project-local hooks remain diagnostic-only unless --source-repo is used"
    elif blocked:
        legacy_status = "DIAGNOSTIC"
        legacy_result = "safe-skip"
        legacy_message = "legacy project-local hook cleanup is blocked and pre-mutation state is preserved"
    else:
        legacy_status = "PASS"
        legacy_result = "reinjection-absent"
        legacy_message = "legacy project-local hooks are candidates only; canonical runtime is not reinserted"

    plugin_commands = [
        item.get("command")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]
    canonical = plugin_core.get("status") in {"canonical", "empty"} and all(
        _is_canonical_plugin_command(command)
        for command in plugin_commands
    )
    if canonical:
        plugin_status = "PASS"
        plugin_message = "canonical plugin registration is preserved"
    else:
        plugin_status = "DIAGNOSTIC"
        plugin_message = "canonical plugin registration needs inspection"

    user_settings = user_global.get("settings", {})
    user_settings_path = user_settings.get("path")
    user_global_diag = any(
        isinstance(item, dict) and item.get("path") == user_settings_path
        for item in diagnostics
    )
    if user_global_diag:
        user_status = "DIAGNOSTIC"
        user_result = "safe-skip"
        user_message = "user-global hook settings could not be fully inspected and were not mutated"
    elif user_settings.get("exists"):
        user_status = "PASS"
        user_result = "preserved-state"
        user_message = "user-global hook settings are observed and preserved"
    else:
        user_status = "SKIP"
        user_result = "absent"
        user_message = "user-global hook settings are absent"

    return [
        {
            "id": "legacy_project_local_hook_reinjection",
            "status": legacy_status,
            "result": legacy_result,
            "message": legacy_message,
            "classification": CLASS_PROJECT_LEGACY,
            "candidate_count": legacy_candidate_count,
            "settings_candidate_count": len(settings_candidates),
            "file_candidate_count": len(file_candidates),
            "prohibited_actions": [
                "create_.claude_hooks_copy",
                "reinsert_settings_local_hooks_as_canonical_runtime",
            ],
            "evidence": {
                "cleanup_scope": environment.get("cleanup_scope"),
                "project_kind": environment.get("project_kind"),
            },
        },
        {
            "id": "canonical_plugin_registration",
            "status": plugin_status,
            "result": "preserved-state" if canonical else "diagnostic",
            "message": plugin_message,
            "classification": CLASS_PLUGIN_CORE,
            "manifest": plugin_core.get("manifest"),
            "registry": plugin_core.get("registry"),
            "canonical_command_count": len(
                [command for command in plugin_commands if _is_canonical_plugin_command(command)]
            ),
            "command_prefix": "${CLAUDE_PLUGIN_ROOT}/hooks/",
        },
        {
            "id": "user_global_hook_preservation",
            "status": user_status,
            "result": user_result,
            "message": user_message,
            "classification": CLASS_USER_GLOBAL,
            "settings_path": user_settings_path,
            "hook_count": len(user_global.get("hooks", [])),
        },
    ]
def _migration_boundary(inventory: dict) -> dict:
    items = _migration_boundary_items(inventory)
    summary = {"PASS": 0, "SKIP": 0, "DIAGNOSTIC": 0}
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
    return {
        "schema_version": "mst.on.cleanup.boundary.v1",
        "items": items,
        "summary": summary,
    }
def _enrich_cleanup_payload(
    payload: dict,
    *,
    project_root: Path,
    inventory: dict,
    settings_removed: List[str],
    file_targets: List[str],
    dry_run: bool,
) -> None:
    candidates = _candidate_set(settings_removed, file_targets, project_root)
    candidate_hash = _candidate_hash(candidates)
    created_at = _created_at()
    dry_run_id = hashlib.sha256(
        json.dumps(
            {
                "schema_version": CLEANUP_SCHEMA_VERSION,
                "project_root": str(project_root),
                "created_at": created_at,
                "candidate_hash": candidate_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    environment = inventory.get("environment", {})
    rollback = _rollback_plan(project_root, candidates)
    diagnostics = inventory.get("diagnostics", [])
    blocked = _status_items(diagnostics, "blocked") if diagnostics else []
    skipped = []
    if environment.get("project_kind") in {"source_repo", "non_mst", "worktree"} and not candidates:
        skipped.append(
            {
                "status": "skipped",
                "reason": environment.get("reason"),
                "reason_code": environment.get("project_kind"),
            }
        )

    payload.update(
        {
            "schema_version": CLEANUP_SCHEMA_VERSION,
            "dry_run_id": dry_run_id,
            "dry_run": dry_run,
            "created_at": created_at,
            "candidate_set": candidates,
            "candidate_hash": candidate_hash,
            "preserved_user_hooks": _preserved_user_hooks(inventory.get("user_custom", {})),
            "skipped": skipped,
            "blocked": blocked,
            "rollback": rollback,
            "rollback_available": rollback["available"],
            "post_check_required": _post_check_required(environment),
            "migration_boundary": _migration_boundary(inventory),
        }
    )
def _write_dry_run_artifact(project_root: Path, payload: dict) -> None:
    artifact_path = _cleanup_artifact_path(project_root)
    if artifact_path is None:
        return
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def _read_dry_run_artifact(project_root: Path, args: argparse.Namespace, diagnostics: List[dict]) -> Optional[dict]:
    explicit_path = getattr(args, "dry_run_artifact", None)
    artifact_path = Path(explicit_path).expanduser() if explicit_path else _cleanup_artifact_path(project_root)
    if artifact_path is None or not artifact_path.exists():
        if explicit_path or getattr(args, "dry_run_id", None):
            diagnostics.append(_diagnostic("dry_run_artifact_missing", "dry-run artifact not found", artifact_path))
        return None
    artifact = _read_json_diagnostic(artifact_path, diagnostics)
    return artifact if isinstance(artifact, dict) else None
def _validate_dry_run_artifact(
    project_root: Path,
    args: argparse.Namespace,
    artifact: Optional[dict],
    current_candidate_set: List[dict],
    current_candidate_hash: str,
) -> List[str]:
    if artifact is None:
        return []

    mismatches: List[str] = []
    if artifact.get("schema_version") != CLEANUP_SCHEMA_VERSION:
        mismatches.append("schema_version_mismatch")
    if artifact.get("project_root") != str(project_root):
        mismatches.append("project_root_mismatch")
    expected_dry_run_id = getattr(args, "dry_run_id", None)
    if expected_dry_run_id and artifact.get("dry_run_id") != expected_dry_run_id:
        mismatches.append("dry_run_id_mismatch")
    if artifact.get("candidate_set") != current_candidate_set:
        mismatches.append("candidate_set_mismatch")
    if artifact.get("candidate_hash") != current_candidate_hash:
        mismatches.append("candidate_hash_mismatch")
    for required in ("dry_run_id", "candidate_set", "candidate_hash"):
        if required not in artifact:
            mismatches.append(f"{required}_missing")
    return sorted(set(mismatches))
def _post_check(project_root: Path, environment: dict) -> dict:
    return _post_check_with_context(
        project_root,
        environment=environment,
        expected_preserved_user_hooks=None,
        expected_candidate_set=None,
    )
def _post_check_with_context(
    project_root: Path,
    *,
    environment: dict,
    expected_preserved_user_hooks: Optional[List[dict]],
    expected_candidate_set: Optional[List[dict]],
    allow_expected_candidates: bool = False,
) -> dict:
    inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
    settings_removed = _plan_settings_changes(project_root).get("removed", [])
    file_targets = _plan_file_deletions(project_root)
    current_candidate_set = _candidate_set(settings_removed, file_targets, project_root)
    current_preserved = _preserved_user_hooks(inventory.get("user_custom", {}))
    plugin_core = inventory.get("plugin_core", {})
    plugin_core_commands = [
        item.get("command")
        for item in plugin_core.get("hooks", [])
        if isinstance(item, dict) and isinstance(item.get("command"), str)
    ]
    plugin_core_canonical = all(
        _is_canonical_plugin_command(command)
        for command in plugin_core_commands
    )
    user_custom_preserved = (
        current_preserved == expected_preserved_user_hooks
        if expected_preserved_user_hooks is not None
        else True
    )

    if not current_candidate_set:
        candidate_state = "absent"
    elif expected_candidate_set is not None and current_candidate_set == expected_candidate_set:
        candidate_state = "restored"
    else:
        candidate_state = "present"

    expected_candidates_restored = allow_expected_candidates and candidate_state == "restored"
    checks = {
        "stale_cleanup_candidates_absent": not current_candidate_set,
        "unexpected_cleanup_candidates_absent": not current_candidate_set or expected_candidates_restored,
        "plugin_core_canonical_command": plugin_core_canonical,
        "user_custom_preserved": user_custom_preserved,
    }
    if allow_expected_candidates:
        checks["rollback_restored_pre_mutation_state"] = expected_candidates_restored
        checks["stale_cleanup_reinjection_absent"] = expected_candidates_restored

    project_kind = environment.get("project_kind")
    if project_kind == "source_repo":
        checks["source_repo_default_skip_or_opt_in"] = all(
            not str(item.get("path", "")).startswith(str(project_root / "hooks"))
            and "hooks/hooks.json" not in str(item.get("path", ""))
            for item in current_candidate_set
        )
    if project_kind == "worktree":
        checks["worktree_no_legacy_propagation"] = not current_candidate_set
    if project_kind == "non_mst" or environment.get("user_global_present"):
        checks["non_mst_user_global_fail_open"] = True

    required_checks = dict(checks)
    if expected_candidates_restored:
        required_checks["stale_cleanup_candidates_absent"] = True

    return {
        "passed": all(required_checks.values()),
        "checks": checks,
        "candidate_state": candidate_state,
        "evidence": {
            "remaining_settings_removed": settings_removed,
            "remaining_file_targets": file_targets,
            "current_candidate_set": current_candidate_set,
            "plugin_core_commands": plugin_core_commands,
            "preserved_user_hooks": current_preserved,
        },
    }
def _apply_settings(settings_path: Path, original_text: Optional[str]) -> Tuple[bool, List[str]]:
    """settings.local.json hooks 정리 적용. atomic via tempfile + os.replace."""
    if original_text is None:
        return True, []
    try:
        original = json.loads(original_text)
    except json.JSONDecodeError:
        return True, []
    if not isinstance(original, dict):
        return True, []
    hooks = original.get("hooks", {})
    project_root = settings_path.parent.parent
    new_hooks, removed = _filter_hooks_block(hooks, project_root)
    if not removed:
        return True, []
    new_settings = dict(original)
    if new_hooks:
        new_settings["hooks"] = new_hooks
    else:
        new_settings.pop("hooks", None)
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".settings.local.json.", suffix=".tmp", dir=str(settings_path.parent)
        )
    except OSError:
        return False, removed
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(new_settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, settings_path)
        return True, removed
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False, removed
def _apply_file_deletions(targets: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    existing = [Path(target) for target in targets if Path(target).exists()]
    if not existing:
        return [], []

    backups: Dict[Path, Tuple[bytes, int]] = {}
    for target in existing:
        try:
            stat_result = target.stat()
            backups[target] = (target.read_bytes(), stat_result.st_mode)
        except OSError as exc:
            return [], [(str(target), str(exc))]

    try:
        quarantine_dir = Path(tempfile.mkdtemp(prefix=".mst-cleanup.", dir=str(existing[0].parent)))
    except OSError as exc:
        return [], [(str(target), str(exc)) for target in existing]

    moved: List[Tuple[Path, Path]] = []
    failed: List[Tuple[str, str]] = []
    for index, target in enumerate(existing):
        quarantine_path = quarantine_dir / f"{index}-{target.name}"
        try:
            os.replace(target, quarantine_path)
            moved.append((target, quarantine_path))
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed.append((str(target), str(exc)))
            break

    def restore_targets() -> None:
        for target, quarantine_path in reversed(moved):
            try:
                if quarantine_path.exists():
                    os.replace(quarantine_path, target)
            except OSError as exc:
                failed.append((str(target), f"restore failed: {exc}"))
        for target, (content, mode) in backups.items():
            if target.exists():
                continue
            try:
                target.write_bytes(content)
                target.chmod(mode & 0o777)
            except OSError as exc:
                failed.append((str(target), f"restore failed: {exc}"))

    if failed:
        restore_targets()
        try:
            quarantine_dir.rmdir()
        except OSError:
            pass
        return [], failed

    deleted: List[str] = []
    for target, quarantine_path in moved:
        try:
            quarantine_path.unlink()
            deleted.append(str(target))
        except OSError as exc:
            failed.append((str(target), str(exc)))
            break

    if failed:
        restore_targets()
        try:
            quarantine_dir.rmdir()
        except OSError:
            pass
        return [], failed

    try:
        quarantine_dir.rmdir()
    except OSError:
        pass
    return deleted, []
def _emit(args: argparse.Namespace, payload: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if getattr(args, "silent", False):
        return
    if payload.get("status") == "skipped":
        print(f"[mst:on cleanup] skipped: {payload.get('reason', '')}")
        return
    if payload.get("status") == "dry_run":
        print("[mst:on cleanup] dry-run preview:")
        for cmd in payload.get("settings", {}).get("removed", []):
            print(f"  remove settings hook: {cmd}")
        for f in payload.get("files", {}).get("targets", []):
            print(f"  remove file: {f}")
        for item in payload.get("preserved_user_hooks", []):
            value = item.get("command") or item.get("path")
            if value:
                print(f"  preserve user hook: {value}")
        for item in payload.get("skipped", []):
            print(f"  skipped: {item.get('reason', '')}")
        for item in payload.get("blocked", []):
            print(f"  blocked: {item.get('reason_code') or item.get('reason', '')}")
        boundary = payload.get("migration_boundary", {})
        for item in boundary.get("items", []):
            print(f"  {item.get('status')} {item.get('id')}: {item.get('message', '')}")
        rollback = payload.get("rollback", {})
        if rollback:
            print(f"  rollback available: {str(rollback.get('available')).lower()}")
            if rollback.get("backup_path"):
                print(f"  rollback backup: {rollback.get('backup_path')}")
        for check in payload.get("post_check_required", []):
            print(f"  post-check required: {check}")
        return
    if payload.get("status") in {"blocked", "diagnostic"}:
        print(f"[mst:on cleanup] {payload.get('status')}: {payload.get('reason', '')}")
        return
    if payload.get("status") == "ok":
        print(
            f"[mst:on cleanup] removed {len(payload.get('settings', {}).get('removed', []))} settings hooks, "
            f"{len(payload.get('files', {}).get('deleted', []))} files."
        )
    if payload.get("status") == "rollback":
        print("[mst:on cleanup] rollback applied due to partial failure", file=sys.stderr)
    if payload.get("status") == "error":
        print(f"[mst:on cleanup] error: {payload.get('reason', '')}", file=sys.stderr)
def _is_plugin_source_repo(project_root: Path) -> bool:
    """gran-maestro 플러그인 소스 저장소 식별 가드.

    .claude-plugin/plugin.json + hooks/hooks.json이 모두 존재하면 플러그인
    소스 저장소로 판정하여 cleanup 대상에서 제외한다 (No-go scope).
    """
    return (
        (project_root / ".claude-plugin" / "plugin.json").exists()
        and (project_root / "hooks" / "hooks.json").exists()
    )
