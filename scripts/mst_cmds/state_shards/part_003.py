def _validate_context_rehydration_head_for_write(session_id: str) -> Optional[dict]:
    refs = _context_core_history_refs()
    if not refs:
        return None
    snapshot = _load_snapshot_for_session(_skill_state_base_dir(), session_id)
    snapshot_refs = _snapshot_history_refs(snapshot) if isinstance(snapshot, dict) else set()
    if refs & snapshot_refs:
        return None
    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return history_error
    assert history_result is not None
    if history_result.tail_hash not in refs and not _history_tail_is_current_invocation_after_refs(history_result, refs):
        return _recover_non_success(
            "stale_history_head",
            "core rehydration history reference does not match validated ledger head",
            session_id=session_id,
            root_mst_id=history_result.root_mst_id,
            details={
                "expected_history_head": history_result.tail_hash,
                "core_rehydration_history_refs": sorted(refs),
                "attempted_recovery": "validated ledger head before automatic state write",
                "next_safe_action": "inspect-only state/history consistency verification",
                "write_allowed": False,
                "mismatch_subject": "core_rehydration.history",
            },
        )
    return None
def _transition_depth_limit() -> int:
    raw = os.environ.get("MST_TRANSITION_DEPTH_LIMIT", "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 8
    return parsed if parsed > 0 else 8
def _continuation_chain_guard_for_write(session_id: str) -> Optional[dict]:
    contexts: list[dict] = []
    snapshot = _load_snapshot_for_session(_skill_state_base_dir(), session_id)
    if isinstance(snapshot, dict) and isinstance(snapshot.get("continuation"), dict):
        contexts.append(snapshot["continuation"])
    env_context = _json_object_env("MST_CONTEXT_JSON")
    core = env_context.get("core_rehydration")
    if isinstance(core, dict) and isinstance(core.get("continuation"), dict):
        contexts.append(core["continuation"])
    if not contexts:
        return None

    limit = _transition_depth_limit()
    selected: dict | None = None
    selected_depth = 0
    for continuation in contexts:
        raw_depth = continuation.get("transition_depth")
        try:
            depth = int(raw_depth)
        except (TypeError, ValueError):
            continue
        if depth > selected_depth:
            selected_depth = depth
            selected = continuation

    if selected is None or selected_depth <= limit:
        return None

    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return history_error
    root_mst_id = history_result.root_mst_id if history_result is not None else None
    return _recover_non_success(
        "recursive_transition_depth_exceeded",
        "recursive recover/compact/continuation depth exceeded safe automatic write limit",
        session_id=session_id,
        root_mst_id=root_mst_id,
        details={
            "transition_source": selected.get("transition_source") or "unknown",
            "transition_depth": selected_depth,
            "transition_depth_limit": limit,
            "chain_id": selected.get("chain_id") or "",
            "write_allowed": False,
            "next_safe_action": "inspect-only state/history consistency verification",
            "attempted_recovery": "downgraded automatic write after recursive transition guard",
            "mismatch_subject": "recursive_transition_guard",
        },
    )
def _previous_enter_duration_ms(flow_path: Path, session_id: str, skill: str) -> Optional[float]:
    try:
        if not flow_path.exists():
            return None
        previous_at = None
        for raw_line in flow_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("session_id") == session_id
                and entry.get("skill") == skill
                and entry.get("event_type") == "enter"
            ):
                previous_at = _parse_flow_timestamp(entry.get("timestamp"))
        if previous_at is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - previous_at).total_seconds() * 1000)
    except Exception:
        return None
def _resolve_owner_session_id(ppid: int) -> Optional[str]:
    if not _common.BASE_DIR:
        return None
    bridge_path = _common.BASE_DIR / "tmp" / f"claude-session-{ppid}.id"
    try:
        raw_value = bridge_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not raw_value:
        return None
    try:
        session_id = uuid.UUID(raw_value)
    except ValueError:
        return None
    canonical = str(session_id)
    if session_id.variant != uuid.RFC_4122 or session_id.version != 4 or canonical != raw_value:
        return None
    return canonical
def _owner_resolution_source(present: bool, value: object = None, valid: bool = False, error: str | None = None) -> dict:
    source = {"present": present, "valid": valid, "value": value}
    if error:
        source["error"] = error
    return source
def _valid_canonical_owner_session_id(raw_value: str) -> tuple[Optional[str], Optional[str]]:
    try:
        from scripts.mst_cmds.session import validate_mst_session_id

        return validate_mst_session_id(raw_value).mst_session_id, None
    except ValueError as exc:
        return None, str(exc)
def _valid_bridge_owner_session_id(raw_value: str) -> tuple[Optional[str], Optional[str]]:
    if not raw_value:
        return None, "empty_bridge_uuid"
    try:
        session_id = uuid.UUID(raw_value)
    except ValueError:
        return None, "invalid_bridge_uuid"
    canonical = str(session_id)
    if session_id.variant != uuid.RFC_4122 or session_id.version != 4 or canonical != raw_value:
        return None, "invalid_bridge_uuid"
    return canonical, None
def _owner_invocation_class() -> str:
    if os.environ.get("MST_SESSION_ID") is not None:
        return "workflow_with_canonical_env"
    if os.environ.get("MST_HOOK_STDIN_RAW", "").strip():
        return "workflow_with_hook_stdin"
    if os.environ.get("MST_STATE_PPID", "").strip():
        return "workflow_with_owner_ppid"
    return "external_invocation"
def _owner_bridge_path(ppid: int) -> Optional[Path]:
    if not _common.BASE_DIR:
        return None
    return _common.BASE_DIR / "tmp" / f"claude-session-{ppid}.id"
def _other_owner_bridge_paths(ppid: int) -> list[str]:
    if not _common.BASE_DIR:
        return []
    tmp_dir = _common.BASE_DIR / "tmp"
    if not tmp_dir.is_dir():
        return []
    current_name = f"claude-session-{ppid}.id"
    return sorted(path.name for path in tmp_dir.glob("claude-session-*.id") if path.name != current_name)
def _resolve_owner_session_context(ppid: int) -> tuple[Optional[str], dict]:
    observed_sources: dict[str, dict] = {}
    invocation_class = _owner_invocation_class()

    raw_env = os.environ.get("MST_SESSION_ID")
    env_present = raw_env is not None
    env_value = raw_env.strip() if raw_env is not None else None
    if env_present:
        if env_value:
            canonical, canonical_error = _valid_canonical_owner_session_id(env_value)
        else:
            canonical, canonical_error = None, "empty_canonical_mst_session_id"
        observed_sources["env:MST_SESSION_ID"] = _owner_resolution_source(
            True,
            env_value,
            bool(canonical),
            canonical_error,
        )
    else:
        canonical = None
        canonical_error = None
        observed_sources["env:MST_SESSION_ID"] = _owner_resolution_source(False)

    bridge_path = _owner_bridge_path(ppid)
    bridge_raw = None
    bridge_owner = None
    bridge_error = None
    if bridge_path is None:
        bridge_error = "bridge_base_dir_missing"
        observed_sources["bridge:claude_session"] = _owner_resolution_source(False, error=bridge_error)
    else:
        try:
            bridge_raw = bridge_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            other_paths = _other_owner_bridge_paths(ppid)
            bridge_error = "owner_ppid_changed" if other_paths else "bridge_missing"
            observed_sources["bridge:claude_session"] = _owner_resolution_source(False, error=bridge_error)
            if other_paths:
                observed_sources["bridge:other_owner_ppids"] = {
                    "present": True,
                    "valid": False,
                    "value": other_paths,
                }
        except Exception as exc:
            bridge_error = "bridge_read_failure"
            observed_sources["bridge:claude_session"] = _owner_resolution_source(
                True,
                None,
                False,
                f"{bridge_error}:{exc.__class__.__name__}",
            )
        else:
            bridge_owner, bridge_error = _valid_bridge_owner_session_id(bridge_raw)
            observed_sources["bridge:claude_session"] = _owner_resolution_source(
                True,
                bridge_raw,
                bool(bridge_owner),
                bridge_error,
            )

    if env_present and not canonical:
        return None, {
            "reason": "invalid_canonical_identity",
            "action": "emit_diagnostic_no_mutation",
            "invocation_class": invocation_class,
            "observed_sources": observed_sources,
            "owner_session_id": None,
        }
    if canonical:
        return canonical, {
            "reason": "canonical_identity_converged",
            "action": "converged_owner_session_id",
            "invocation_class": invocation_class,
            "observed_sources": observed_sources,
            "owner_session_id": canonical,
        }
    if bridge_owner:
        return bridge_owner, {
            "reason": "bridge_owner_resolved",
            "action": "use_verified_owner_bridge",
            "invocation_class": invocation_class,
            "observed_sources": observed_sources,
            "owner_session_id": bridge_owner,
        }

    reason = bridge_error or "bridge_missing"
    return None, {
        "reason": reason,
        "action": "record_owner_resolution_diagnostic",
        "invocation_class": invocation_class,
        "observed_sources": observed_sources,
        "owner_session_id": None,
    }
def _owner_resolution_for_write(owner_resolution: Optional[dict], session_id: Optional[str]) -> dict:
    if isinstance(owner_resolution, dict):
        return dict(owner_resolution)
    return {
        "reason": "owner_metadata_provided",
        "action": "record_owner_metadata",
        "invocation_class": "direct_owner_metadata_write",
        "observed_sources": {},
        "owner_session_id": session_id,
    }
def _inject_owner_metadata_to_json(
    json_path: Path,
    ppid: int,
    session_id: Optional[str],
    owner_resolution: Optional[dict] = None,
) -> None:
    """Write owner metadata while preserving non-null existing owner fields."""
    data = _common.load_json(json_path)
    if not isinstance(data, dict):
        return
    should_write = False
    if "owner_ppid" not in data:
        data["owner_ppid"] = ppid
        should_write = True
    existing_owner = data.get("owner_session_id")
    if "owner_session_id" not in data or (existing_owner is None and session_id is not None):
        data["owner_session_id"] = session_id
        should_write = True
        if existing_owner is None and session_id is not None and isinstance(data.get("owner_resolution"), dict):
            repaired_resolution = _owner_resolution_for_write(owner_resolution, session_id)
            repaired_resolution["reason"] = "repaired_from_canonical_identity"
            repaired_resolution["action"] = "converged_owner_session_id"
            data["owner_resolution"] = repaired_resolution
            should_write = True
    if "owner_resolution" not in data and owner_resolution is not None:
        data["owner_resolution"] = _owner_resolution_for_write(owner_resolution, session_id)
        should_write = True
    if not should_write:
        return
    tmp_path = json_path.with_name(f"{json_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, json_path)
def _inject_owner_metadata_if_missing(args) -> bool:
    ppid = _resolve_owner_ppid()
    session_id, owner_resolution = _resolve_owner_session_context(ppid)
    injected = False

    req_id = (getattr(args, "req", "") or "").strip()
    if req_id.startswith("REQ-") and _common.BASE_DIR:
        req_json = _common.BASE_DIR / "requests" / req_id / "request.json"
        if req_json.exists():
            try:
                before = _common.load_json(req_json)
                _inject_owner_metadata_to_json(req_json, ppid, session_id, owner_resolution)
                after = _common.load_json(req_json)
                injected = injected or before != after
            except Exception as exc:
                print(f"[mst] warning: failed to inject owner metadata into {req_json}: {exc}", file=sys.stderr)

    next_source = (getattr(args, "next_source", "") or "").strip()
    source_skill = (getattr(args, "source_skill", "") or "").strip()
    if next_source.startswith("PLN-") and source_skill == "mst:plan" and _common.BASE_DIR:
        plan_json = _common.BASE_DIR / "plans" / next_source / "plan.json"
        if plan_json.exists():
            try:
                before = _common.load_json(plan_json)
                _inject_owner_metadata_to_json(plan_json, ppid, session_id, owner_resolution)
                after = _common.load_json(plan_json)
                injected = injected or before != after
            except Exception as exc:
                print(f"[mst] warning: failed to inject owner metadata into {plan_json}: {exc}", file=sys.stderr)

    return injected
def _state_migration_base_dir() -> Path:
    env_base = os.environ.get("MST_BASE_DIR", "").strip()
    if env_base:
        return Path(env_base)
    if _common.BASE_DIR:
        return _common.BASE_DIR.parent
    return Path.cwd()
def _collect_migration_targets(base_dir: Path) -> list[dict]:
    """Collect legacy PPID state directories and owner_ppid-only metadata files."""
    targets = []
    gm_dir = _common.base_dir_from_project(base_dir)
    state_dir = _common.state_dir(gm_dir)
    if state_dir.is_dir():
        for child in state_dir.iterdir():
            if not child.is_dir() or not child.name.isdigit():
                continue
            snapshot = child / "snapshot.json"
            if not snapshot.is_file():
                continue
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            targets.append({
                "type": "rename_dir",
                "path": str(child),
                "ppid": int(child.name),
                "owner_session_id": data.get("owner_session_id"),
            })

    patterns = [
        ".gran-maestro/agile/AGI-*/objective/objective.json",
        ".gran-maestro/requests/REQ-*/request.json",
        ".gran-maestro/plans/PLN-*/plan.json",
    ]
    for pattern in patterns:
        for json_path in base_dir.glob(pattern):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and "owner_ppid" in data and "owner_session_id" not in data:
                targets.append({"type": "owner_field", "path": str(json_path), "data": data})
    return targets
def _create_backup(base_dir: Path, targets: list, backup_dir: Optional[Path] = None) -> Path:
    if backup_dir is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = _common.backups_dir(_common.base_dir_from_project(base_dir)) / f"state-migrate-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        src = Path(target["path"])
        if not src.exists():
            continue
        dst = backup_dir / src.relative_to(base_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    return backup_dir
def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in itertools.count(1):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
def _migrate_ppid_dir(ppid_dir: Path, owner_session_id: Optional[str], base_dir: Path) -> Tuple[Path, Path]:
    ppid = ppid_dir.name
    state_dir = _common.state_dir(_common.base_dir_from_project(base_dir))
    target_name = owner_session_id if isinstance(owner_session_id, str) and owner_session_id.strip() else f"legacy-{ppid}"
    target_dir = state_dir / target_name
    if target_dir.exists() and target_dir != ppid_dir:
        target_dir = _next_available_path(state_dir / f"legacy-{ppid}")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    ppid_dir.rename(target_dir)
    return ppid_dir, target_dir
def _migrate_owner_field(json_path: Path, ppid_to_session_map: dict) -> Tuple[dict, dict]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}, {}
    ppid = data.get("owner_ppid")
    before = {"owner_ppid": ppid}
    data.pop("owner_ppid", None)
    session_id = ppid_to_session_map.get(ppid)
    if session_id is None:
        try:
            session_id = ppid_to_session_map.get(int(ppid))
        except (TypeError, ValueError):
            session_id = None
    if session_id:
        data["owner_session_id"] = session_id
        after = {"owner_session_id": session_id}
    else:
        data["legacy_owner_ppid"] = ppid
        after = {"legacy_owner_ppid": ppid}
    _atomic_json_write(json_path, data)
    return before, after
def _apply_migration(base_dir: Path, targets: list, log_path: Path, dry_run: bool = False) -> int:
    """Apply PPID to session_id migration and write a user-observable log."""
    log_lines = []
    ppid_to_session = {}

    for target in targets:
        if target.get("type") != "rename_dir":
            continue
        ppid = target.get("ppid")
        owner_session_id = target.get("owner_session_id")
        if owner_session_id:
            ppid_to_session[ppid] = owner_session_id
        src = Path(target["path"])
        target_name = owner_session_id if owner_session_id else f"legacy-{ppid}"
        state_dir = _common.state_dir(_common.base_dir_from_project(base_dir))
        dst = state_dir / target_name
        if dst.exists() and dst != src:
            dst = _next_available_path(state_dir / f"legacy-{ppid}")
        if not dry_run:
            _, dst = _migrate_ppid_dir(src, owner_session_id, base_dir)
        log_lines.append(f"rename_dir: {src} -> {dst}")

    for target in targets:
        if target.get("type") != "owner_field":
            continue
        json_path = Path(target["path"])
        data = target.get("data") if isinstance(target.get("data"), dict) else {}
        ppid = data.get("owner_ppid")
        session_id = ppid_to_session.get(ppid)
        if session_id is None:
            try:
                session_id = ppid_to_session.get(int(ppid))
            except (TypeError, ValueError):
                session_id = None
        before = {"owner_ppid": ppid}
        after = {"owner_session_id": session_id} if session_id else {"legacy_owner_ppid": ppid}
        if not dry_run:
            before, after = _migrate_owner_field(json_path, ppid_to_session)
        log_lines.append(
            "owner_field: "
            f"{json_path} "
            f"{json.dumps(before, ensure_ascii=False)} -> {json.dumps(after, ensure_ascii=False)}"
        )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    return len(log_lines)
def _run_dry_run(base_dir: Path) -> int:
    targets = _collect_migration_targets(base_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gm_dir = _common.base_dir_from_project(base_dir)
    backup_path = _common.backups_dir(gm_dir) / f"state-migrate-{timestamp}"
    out_targets = []
    ppid_to_session = {
        target["ppid"]: target.get("owner_session_id")
        for target in targets
        if target["type"] == "rename_dir" and target.get("owner_session_id")
    }

    for target in targets:
        if target["type"] == "rename_dir":
            session_id = target.get("owner_session_id")
            state_dir = _common.state_dir(gm_dir)
            if session_id:
                to_path = str(state_dir / session_id)
            else:
                to_path = str(state_dir / f"legacy-{target['ppid']}")
            out_targets.append({
                "type": "rename_dir",
                "from": target["path"],
                "to": to_path,
            })
        elif target["type"] == "owner_field":
            data = target.get("data") or {}
            ppid = data.get("owner_ppid")
            session_id = ppid_to_session.get(ppid)
            if session_id is None:
                try:
                    session_id = ppid_to_session.get(int(ppid))
                except (TypeError, ValueError):
                    session_id = None
            field = "owner_session_id" if session_id else "legacy_owner_ppid"
            out_targets.append({
                "type": "json_field",
                "path": target["path"],
                "from": "owner_ppid",
                "to": field,
            })

    print(json.dumps(
        {"targets": out_targets, "backup_path": str(backup_path)},
        ensure_ascii=False,
        indent=2,
    ))
    return 0
def _run_rollback(base_dir: Path) -> int:
    gm_dir = _common.base_dir_from_project(base_dir)
    backups_dir = _common.backups_dir(gm_dir)
    if not backups_dir.is_dir():
        print("error: no backup directory found", file=sys.stderr)
        return 1

    candidates = sorted(
        [
            path
            for path in backups_dir.iterdir()
            if path.is_dir() and path.name.startswith("state-migrate-")
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    if not candidates:
        print("error: no state-migrate-* backup found", file=sys.stderr)
        return 1

    latest = candidates[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = _common.logs_dir(gm_dir) / f"state-migrate-rollback-{timestamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines = []

    for src in latest.rglob("*"):
        if src.is_file():
            rel = src.relative_to(latest)
            dst = base_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log_lines.append(f"restore: {dst}")

    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")
    print(f"rolled back from {latest}; log={log_path}")
    return 0
def _run_verify(base_dir: Path) -> int:
    gm_dir = _common.base_dir_from_project(base_dir)
    state_dir = _common.state_dir(gm_dir)
    issues = []
    if state_dir.is_dir():
        for child in state_dir.iterdir():
            if child.is_dir() and child.name.isdigit():
                issues.append(f"numeric_ppid_dir_remains: {child}")

    for pattern in [
        ".gran-maestro/agile/AGI-*/objective/objective.json",
        ".gran-maestro/requests/REQ-*/request.json",
        ".gran-maestro/plans/PLN-*/plan.json",
    ]:
        for json_path in base_dir.glob(pattern):
            try:
                text = json_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if (
                '"owner_ppid"' in text
                and '"owner_session_id"' not in text
                and '"legacy_owner_ppid"' not in text
            ):
                issues.append(f"owner_ppid_remains: {json_path}")

    backups_dir = _common.backups_dir(gm_dir)
    backup_present = backups_dir.is_dir() and any(
        path.is_dir() and path.name.startswith("state-migrate-") for path in backups_dir.iterdir()
    )
    status = "PASS" if not issues else "FAIL"
    print(json.dumps(
        {"status": status, "issues": issues, "backup_present": backup_present},
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if status == "PASS" else 1
def _run_migrate_default(base_dir: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    gm_dir = _common.base_dir_from_project(base_dir)
    log_path = _common.logs_dir(gm_dir) / f"state-migrate-{timestamp}.log"
    backup_dir = _common.backups_dir(gm_dir) / f"state-migrate-{timestamp}"
    lock_path = gm_dir / "tmp" / "mst-state-migrate.lock"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    targets = _collect_migration_targets(base_dir)
    if not targets:
        log_path.write_text("[no changes]\n", encoding="utf-8")
        print("no_changes: legacy PPID state 없음")
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)
    _create_backup(base_dir, targets, backup_dir)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        _common._lock_exclusive_with_timeout(lock_file, timeout_sec=5)
        try:
            changes = _apply_migration(base_dir, targets, log_path, dry_run=False)
        finally:
            _common._unlock(lock_file)

    print(f"migrated: {changes} item(s); backup={backup_dir}; log={log_path}")
    return 0
def migrate(args: argparse.Namespace) -> int:
    """state migrate: PPID -> session_id migration entry point."""
    base_dir = _state_migration_base_dir()
    if args.dry_run:
        return _run_dry_run(base_dir)
    if args.rollback:
        return _run_rollback(base_dir)
    if args.verify:
        return _run_verify(base_dir)
    return _run_migrate_default(base_dir)
def _ensure_workflow_session_id(args) -> tuple[str, dict | None]:
    root_mst_id = str(getattr(args, "root_mst_id", "") or "").strip()
    try:
        return _common.require_mst_session_id_for_mutation("workflow state write"), None
    except ValueError as exc:
        if not root_mst_id or not _common.is_missing_canonical_session_error(exc):
            raise

    from scripts.mst_cmds import session as session_mod

    created = session_mod.ensure_root_session_artifacts(
        _common.BASE_DIR,
        root_mst_id,
        root_payload={"id": root_mst_id, "status": "active"},
    )
    session_id = str(created["mst_session_id"])
    os.environ["MST_SESSION_ID"] = session_id
    os.environ.setdefault(
        "MST_CONTEXT_JSON",
        json.dumps(_common.canonical_state_payload_fields(session_id), ensure_ascii=False, separators=(",", ":")),
    )
    return session_id, {
        "created_new_session": bool(created.get("created_new_session", True)),
        "root_artifact_created": bool(created.get("root_artifact_created", True)),
        "root_mst_id": root_mst_id,
        "session_metadata_path": str(created["session_metadata_path"]),
        "root_artifact_path": str(created["root_artifact_path"]),
    }


def cmd_state_set_workflow(args):
    state_base_dir = _skill_state_base_dir()
    now = _workflow_state_timestamp()

    try:
        try:
            session_id, session_creation = _ensure_workflow_session_id(args)
        except ValueError as exc:
            if _common.is_session_identity_non_success_error(exc):
                if not bool(getattr(args, "active", False)):
                    print(json.dumps({
                        "status": "partial",
                        "code": "inactive_workflow_without_canonical_state",
                        "message": str(exc),
                        "mutation_performed": False,
                        "workflow_state_written": False,
                        "created_new_session": False,
                    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    return 0
                owner_injected = _inject_owner_metadata_if_missing(args)
                if owner_injected:
                    print(json.dumps({
                        "status": "partial",
                        "code": "owner_metadata_injected_without_workflow_state",
                        "message": str(exc),
                        "mutation_performed": True,
                        "workflow_state_written": False,
                        "created_new_session": False,
                    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    return 0
                return _common.emit_session_identity_non_success(
                    "workflow state write",
                    error=exc,
                    invocation_class="state_set_workflow",
                )
            raise

        state_path = _workflow_state_file(state_base_dir)
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            payload = _workflow_state_default_payload(now)
        else:
            valid_workflow, workflow_error = _validate_existing_workflow_payload(payload, session_id)
            if not valid_workflow:
                print(f"Error: workflow {workflow_error}", file=sys.stderr)
                return 1

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            next_action = {}

        was_active = payload.get("workflow_active") is True
        payload["workflow_active"] = bool(args.active)
        payload["current_skill"] = args.skill if args.active else ""
        payload["active_req"] = args.req if args.active else ""
        payload["iteration"] = payload.get("iteration") if isinstance(payload.get("iteration"), int) else 0
        payload["agile_loop_active"] = (
            payload.get("agile_loop_active")
            if isinstance(payload.get("agile_loop_active"), bool)
            else False
        )
        payload["steering_disabled"] = (
            payload.get("steering_disabled")
            if isinstance(payload.get("steering_disabled"), bool)
            else False
        )
        block_count = payload.get("block_count")
        payload["block_count"] = (
            block_count
            if isinstance(block_count, int) and not isinstance(block_count, bool)
            else 0
        )
        payload["last_block_reason"] = (
            payload.get("last_block_reason")
            if isinstance(payload.get("last_block_reason"), str)
            else ""
        )
        payload["awaiting_user_input"] = (
            payload.get("awaiting_user_input")
            if isinstance(payload.get("awaiting_user_input"), bool)
            else False
        )
        payload["question_id"] = (
            payload.get("question_id")
            if isinstance(payload.get("question_id"), str)
            else ""
        )
        payload["expected_question_hash"] = (
            payload.get("expected_question_hash")
            if isinstance(payload.get("expected_question_hash"), str)
            else ""
        )
        if not isinstance(payload.get("user_input"), dict):
            payload["user_input"] = {}

        if args.agile_loop_active is not None:
            payload["agile_loop_active"] = bool(args.agile_loop_active)
            if not payload["agile_loop_active"]:
                payload["block_count"] = 0
        if args.steering_disabled is not None:
            payload["steering_disabled"] = bool(args.steering_disabled)
        if args.awaiting_user_input is not None:
            payload["awaiting_user_input"] = bool(args.awaiting_user_input)
            if payload["awaiting_user_input"]:
                payload["question_id"] = args.question_id or payload["question_id"]
                payload["expected_question_hash"] = args.expected_question_hash or payload["expected_question_hash"]
                payload["user_input"] = {
                    **payload["user_input"],
                    "awaiting": True,
                    "question_id": payload["question_id"],
                    "expected_question_hash": payload["expected_question_hash"],
                    "resume_skill": args.resume_skill or payload["user_input"].get("resume_skill", ""),
                    "resume_args": args.resume_args or payload["user_input"].get("resume_args", ""),
                    "updated_at": now,
                }
            else:
                payload["question_id"] = ""
                payload["expected_question_hash"] = ""
                payload["user_input"] = {
                    **payload["user_input"],
                    "awaiting": False,
                    "updated_at": now,
                }
        elif not args.active:
            payload["awaiting_user_input"] = False
            payload["question_id"] = ""
            payload["expected_question_hash"] = ""
            payload["user_input"] = {
                **payload["user_input"],
                "awaiting": False,
                "updated_at": now,
            }

        payload["updated_at"] = now

        if args.active or (was_active and not args.active):
            payload["last_active_at"] = now

        if args.active:
            expected_skill = args.next_skill or ""
            source_id = args.next_source or ""
            source_skill = args.source_skill or args.skill or ""
            auto_mode = bool(args.auto)
            next_action.update(
                {
                    "skill": expected_skill,
                    "source": source_id,
                    "auto": auto_mode,
                    "expected_skill": expected_skill,
                    "source_skill": source_skill,
                    "source_id": source_id,
                    "auto_mode": auto_mode,
                }
            )
        else:
            next_action.update(
                {
                    "skill": "",
                    "source": "",
                    "auto": False,
                    "expected_skill": "",
                    "source_skill": "",
                    "source_id": "",
                    "auto_mode": False,
                }
            )

        payload["next_action"] = next_action
        payload.update(_common.canonical_state_payload_fields(session_id))
        if session_creation:
            payload["session_creation"] = session_creation
        else:
            payload.pop("session_creation", None)
        diagnostics = _common.legacy_session_diagnostics()
        if diagnostics:
            payload["legacy_diagnostics"] = diagnostics
        else:
            payload.pop("legacy_diagnostics", None)
        if bool(args.active):
            _inject_owner_metadata_if_missing(args)
        _workflow_state_atomic_write(state_path, payload)

        if bool(getattr(args, "enqueue", False)) and payload.get("next_action"):
            na = payload.get("next_action", {})
            if isinstance(na, dict) and na.get("expected_skill"):
                auto_flag = bool(na.get("auto_mode", na.get("auto", False)))
                args_base = str(na.get("args", "") or "").strip()
                queue_args = args_base
                if auto_flag:
                    args_tokens = args_base.split()
                    if "-a" not in args_tokens and "--auto" not in args_tokens:
                        queue_args = f"{args_base} -a".strip()
                try:
                    queue_enqueue(
                        {
                            "skill": str(na.get("expected_skill", "")),
                            "args": queue_args,
                            "source_skill": str(na.get("source_skill", "")),
                            "source_id": str(na.get("source_id", "")),
                            "resource_id": str(na.get("source_id", "")),
                            "auto": auto_flag,
                        }
                    )
                except Exception as queue_exc:
                    print(f"[mst] warning: failed to enqueue next_action: {queue_exc}", file=sys.stderr)

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[mst] error: failed to update workflow state: {exc}", file=sys.stderr)
        return 1

    return 0
def cmd_state_set(args):
    from scripts._skill_state import set_snapshot
    from scripts._flow_logger import append_skill_event, flow_log_path, safe_session_id

    state_base_dir = _skill_state_base_dir()
    project_root = state_base_dir.parent
    try:
        session_id = _snapshot_session_id()
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state set")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        try:
            payload = json.loads(validation_error)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return _emit_validation_payload(payload)
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    context_head_error = _validate_context_rehydration_head_for_write(session_id)
    if context_head_error is not None:
        return _emit_recover_non_success(context_head_error)
    transition_guard_error = _continuation_chain_guard_for_write(session_id)
    if transition_guard_error is not None:
        return _emit_recover_non_success(transition_guard_error)
    resource_id = _current_flow_resource_id()
    try:
        if args.step == 0:
            _append_skill_history_event(
                state_base_dir,
                session_id,
                event_type="skill.enter",
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                resource_id=resource_id,
            )
        _append_skill_history_event(
            state_base_dir,
            session_id,
            event_type="skill.step",
            skill=args.skill,
            step=args.step,
            total_steps=args.total,
            resource_id=resource_id,
        )
        if args.step == args.total:
            _append_skill_history_event(
                state_base_dir,
                session_id,
                event_type="skill.exit",
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                resource_id=resource_id,
                status="committed",
            )
    except Exception as exc:
        print(f"Error: failed to append skill history: {exc}", file=sys.stderr)
        return 1
    data = set_snapshot(
        state_base_dir,
        skill=args.skill,
        step=args.step,
        total=args.total,
        return_to=args.return_to,
        session_id=session_id,
    )
    if args.step == args.total:
        data["status"] = "committed"
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
    current_history_head = _history_head_for_session(state_base_dir, session_id)
    if current_history_head:
        history = dict(data.get("history")) if isinstance(data.get("history"), dict) else {}
        if history.get("head_hash") != current_history_head or history.get("last_event_id") != current_history_head:
            history["head_hash"] = current_history_head
            history["last_event_id"] = current_history_head
            data["history"] = history
            data = _write_canonical_snapshot_payload(state_base_dir, session_id, data, history_head_override=current_history_head)
    try:
        parent_skill, parent_step = _parse_return_to_parent(args.return_to)
        flow_path = flow_log_path(project_root, rotate=True)
        log_session_id = safe_session_id(session_id)
        duration_ms = _previous_enter_duration_ms(flow_path, log_session_id, args.skill)
        extras = {"resource_id": resource_id} if resource_id else None
        append_skill_event(
            project_root,
            session_id,
            skill=args.skill,
            step=args.step,
            total_steps=args.total,
            event_type="enter",
            parent_skill=parent_skill,
            parent_step=parent_step,
            duration_ms=duration_ms,
            extras=extras,
            rotate=True,
        )
        if args.step == args.total:
            append_skill_event(
                project_root,
                session_id,
                skill=args.skill,
                step=args.step,
                total_steps=args.total,
                event_type="commit",
                parent_skill=parent_skill,
                parent_step=parent_step,
                duration_ms=0,
                extras=extras,
                rotate=True,
            )
    except Exception as exc:
        print(f"[flow-logger] append failed: {exc}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0
def cmd_state_get(args):
    from scripts._skill_state import load_snapshot

    try:
        session_id = _common.require_mst_session_id_for_mutation("state snapshot read")
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state get")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = load_snapshot(_skill_state_base_dir(), session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    contract_failure = _state_snapshot_contract_failure(data, session_id)
    if contract_failure is not None:
        return _emit_validation_payload(contract_failure)
    validation_error = _common.canonical_state_payload_error(data, session_id)
    if validation_error is not None:
        return _common.emit_validation_failure(
            target="state_snapshot",
            field="mst_session_id" if "mst_session_id" in validation_error else "state_snapshot",
            reason=f"snapshot {validation_error}",
        )
    try:
        _append_state_history_event(
            _common.BASE_DIR,
            session_id,
            snapshot=data,
            command="state get",
        )
    except Exception as exc:
        print(f"[state] warning: failed to append state evidence ({exc})", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0
def cmd_state_clear(args):
    from scripts._skill_state import clear_snapshot

    try:
        session_id = _snapshot_session_id()
    except ValueError as exc:
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("state clear")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(_skill_state_base_dir(), session_id)
    if not valid_snapshot:
        try:
            payload = json.loads(validation_error)
        except (TypeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            return _emit_validation_payload(payload)
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    clear_snapshot(_skill_state_base_dir(), session_id=session_id)
    print("스냅샷 초기화 완료")
    return 0
