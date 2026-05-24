def cmd_on_cleanup(args) -> int:
    project_root = _project_root()
    lock_path = _common.tmp_dir(project_root) / "cleanup.lock"
    payload: dict = {"project_root": str(project_root)}
    source_repo_opt_in = bool(getattr(args, "source_repo", False))

    if args.dry_run:
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=True,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        environment = inventory.get("environment", {})
        if environment.get("source_repo") and not source_repo_opt_in:
            payload["status"] = "skipped"
            payload["reason"] = "plugin source repo (out of cleanup scope)"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        elif _diagnostics_block_mutation(project_root, inventory):
            _annotate_diagnostics(inventory.get("diagnostics", []), result="safe-skip", status="diagnostic")
            payload["status"] = "diagnostic"
            payload["reason"] = "cleanup environment cannot be safely mutated"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        elif environment.get("project_kind") == "non_mst":
            payload["status"] = "skipped"
            payload["reason"] = "non-MST project fail-open"
            payload["settings"] = {
                "path": str(project_root / ".claude" / "settings.local.json"),
                "exists": (project_root / ".claude" / "settings.local.json").exists(),
                "removed": [],
            }
            payload["files"] = {"targets": []}
        else:
            payload["status"] = "dry_run"
            payload["settings"] = _plan_settings_changes(project_root)
            payload["files"] = {"targets": _plan_file_deletions(project_root)}
        payload.update(inventory)
        payload["status"] = payload.get("status")
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=payload.get("settings", {}).get("removed", []),
            file_targets=payload.get("files", {}).get("targets", []),
            dry_run=True,
        )
        if payload.get("status") == "dry_run":
            try:
                _write_dry_run_artifact(project_root, payload)
            except OSError as exc:
                payload.setdefault("diagnostics", []).append(
                    _diagnostic(DIAGNOSTIC_PERMISSION_DENIED, str(exc), _cleanup_artifact_path(project_root))
                )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    if _is_plugin_source_repo(project_root) and not source_repo_opt_in:
        inventory = _build_cleanup_inventory(project_root, dry_run=False, mutated=False)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        payload["settings"] = {
            "path": str(project_root / ".claude" / "settings.local.json"),
            "exists": (project_root / ".claude" / "settings.local.json").exists(),
            "removed": [],
        }
        payload["files"] = {"targets": [], "deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "plugin source repo (out of cleanup scope)"
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=[],
            file_targets=[],
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    if not _acquire_lock(lock_path):
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=False,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        payload["settings"] = {"removed": []}
        payload["files"] = {"deleted": []}
        payload.update(inventory)
        payload["status"] = "skipped"
        payload["reason"] = "another cleanup in progress (lock held)"
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=[],
            file_targets=[],
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0

    try:
        inventory = _build_cleanup_inventory(
            project_root,
            dry_run=False,
            mutated=False,
            source_repo_opt_in=source_repo_opt_in,
        )
        if _diagnostics_block_mutation(project_root, inventory):
            _annotate_diagnostics(inventory.get("diagnostics", []), result="safe-skip", status="diagnostic")
            payload.update(inventory)
            payload["status"] = "diagnostic"
            payload["reason"] = "cleanup environment cannot be safely mutated"
            payload["settings"] = {"removed": []}
            payload["files"] = {"targets": [], "deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=[],
                file_targets=[],
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
            _emit(args, payload)
            return 0

        planned_settings = _plan_settings_changes(project_root).get("removed", [])
        planned_files = _plan_file_deletions(project_root)
        current_candidates = _candidate_set(planned_settings, planned_files, project_root)
        current_candidate_hash = _candidate_hash(current_candidates)
        artifact_diagnostics: List[dict] = []
        artifact = _read_dry_run_artifact(project_root, args, artifact_diagnostics)
        if artifact is None and current_candidates:
            artifact_diagnostics.append(
                _diagnostic("dry_run_artifact_missing", "dry-run artifact not found", project_root)
            )
        mismatches = _validate_dry_run_artifact(
            project_root,
            args,
            artifact,
            current_candidates,
            current_candidate_hash,
        )
        if artifact_diagnostics or mismatches:
            for mismatch in mismatches:
                artifact_diagnostics.append(
                    _diagnostic(
                        mismatch,
                        f"dry-run artifact validation failed: {mismatch}",
                        project_root,
                        result="preserved-state",
                        status="blocked",
                    )
                )
            _annotate_diagnostics(artifact_diagnostics, result="preserved-state", status="blocked")
            inventory["diagnostics"].extend(artifact_diagnostics)
            payload.update(inventory)
            payload["status"] = "blocked"
            payload["reason"] = "dry_run_candidate_mismatch" if mismatches else "dry_run_artifact_unavailable"
            payload["settings"] = {"removed": []}
            payload["files"] = {"targets": planned_files, "deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=planned_settings,
                file_targets=planned_files,
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
            _emit(args, payload)
            return 0

        settings_path = project_root / ".claude" / "settings.local.json"
        backup_text: Optional[str] = None
        if settings_path.exists():
            try:
                backup_text = settings_path.read_text(encoding="utf-8")
            except OSError:
                payload.update(inventory)
                payload["status"] = "diagnostic"
                payload["reason"] = "settings.local.json cannot be read"
                payload["settings"] = {"removed": []}
                payload["files"] = {"targets": planned_files, "deleted": []}
                _enrich_cleanup_payload(
                    payload,
                    project_root=project_root,
                    inventory=inventory,
                    settings_removed=[],
                    file_targets=[],
                    dry_run=False,
                )
                payload["post_check"] = _post_check_with_context(
                    project_root,
                    environment=inventory.get("environment", {}),
                    expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                    expected_candidate_set=payload.get("candidate_set"),
                )
                _emit(args, payload)
                return 0

        ok_settings, removed = _apply_settings(settings_path, backup_text)
        if not ok_settings:
            payload.update(inventory)
            payload["status"] = "error"
            payload["reason"] = "settings.local.json write failed"
            payload["settings"] = {"removed": [], "failed": removed}
            payload["files"] = {"deleted": []}
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=[],
                file_targets=[],
                dry_run=False,
            )
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
            )
            _emit(args, payload)
            return 1

        targets = planned_files
        deleted, failed = _apply_file_deletions(targets)

        if failed:
            mutated = bool(removed or deleted)
            # rollback settings
            settings_rolled_back = backup_text is None
            settings_rollback_error = None
            if backup_text is not None:
                try:
                    tmp_fd, tmp_path = tempfile.mkstemp(
                        prefix=".settings.local.json.",
                        suffix=".restore",
                        dir=str(settings_path.parent),
                    )
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        f.write(backup_text)
                    os.replace(tmp_path, settings_path)
                    settings_rolled_back = True
                except OSError as exc:
                    settings_rollback_error = str(exc)
            inventory["mutation"]["mutated"] = mutated and settings_rolled_back
            payload.update(inventory)
            payload["status"] = "rollback" if settings_rolled_back else "error"
            payload["reason"] = (
                "file deletion failed; settings rollback attempted"
                if settings_rolled_back
                else "file deletion failed; settings rollback failed"
            )
            payload["settings"] = {"removed": removed, "rolled_back": settings_rolled_back}
            if settings_rollback_error is not None:
                payload["settings"]["rollback_error"] = settings_rollback_error
            payload["files"] = {"deleted": deleted, "failed": failed}
            payload.setdefault("diagnostics", []).append(
                _diagnostic(
                    "file_deletion_failed",
                    "file deletion failed; restored pre-mutation state where possible",
                    Path(failed[0][0]),
                    result="preserved-state",
                    status="rollback" if settings_rolled_back else "error",
                )
            )
            _enrich_cleanup_payload(
                payload,
                project_root=project_root,
                inventory=inventory,
                settings_removed=removed,
                file_targets=targets,
                dry_run=False,
            )
            rollback = payload.get("rollback")
            if isinstance(rollback, dict):
                failed_path, failed_reason = failed[0]
                rollback["failed_operation"] = {
                    "type": "file_delete",
                    "path": failed_path,
                    "reason": failed_reason,
                }
            payload["post_check"] = _post_check_with_context(
                project_root,
                environment=inventory.get("environment", {}),
                expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
                expected_candidate_set=payload.get("candidate_set"),
                allow_expected_candidates=True,
            )
            _emit(args, payload)
            return 1

        # cleanup empty .claude/hooks dir (선택)
        hooks_dir = project_root / ".claude" / "hooks"
        try:
            if deleted and hooks_dir.exists() and not any(hooks_dir.iterdir()):
                hooks_dir.rmdir()
        except OSError:
            pass

        mutated = bool(removed or deleted)
        inventory["mutation"]["mutated"] = mutated
        payload.update(inventory)
        payload["status"] = "ok"
        payload["settings"] = {"removed": removed}
        payload["files"] = {"deleted": deleted}
        _enrich_cleanup_payload(
            payload,
            project_root=project_root,
            inventory=inventory,
            settings_removed=removed,
            file_targets=targets,
            dry_run=False,
        )
        payload["post_check"] = _post_check_with_context(
            project_root,
            environment=inventory.get("environment", {}),
            expected_preserved_user_hooks=payload.get("preserved_user_hooks"),
            expected_candidate_set=payload.get("candidate_set"),
        )
        _emit(args, payload)
        return 0
    finally:
        _release_lock(lock_path)
def register(subparsers) -> None:
    on_parser = subparsers.add_parser("on", help="/mst:on 보조 명령")
    on_sub = on_parser.add_subparsers(dest="subcommand")

    cleanup = on_sub.add_parser("cleanup", help="기존 mst hook 사본·settings 항목 정리")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--source-repo", action="store_true", help="플러그인 소스 저장소 legacy hook cleanup을 명시적으로 허용")
    cleanup.add_argument("--dry-run-id", help="직전 dry-run artifact id와 일치할 때만 apply 허용")
    cleanup.add_argument("--dry-run-artifact", help="검증할 cleanup dry-run JSON artifact 경로")
    cleanup.add_argument("--silent", action="store_true")
    cleanup.add_argument("--json", action="store_true")
