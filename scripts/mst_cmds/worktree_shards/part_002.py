def _iter_cleaned_meta_entries(project_root: Path) -> list[dict]:
    entries: list[dict] = []
    worktrees_dir = _common.BASE_DIR / "worktrees"
    if not worktrees_dir.is_dir():
        return entries

    migrated_at_dt = datetime.now(timezone.utc).replace(microsecond=0)
    migrated_at = migrated_at_dt.isoformat().replace("+00:00", "Z")
    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data = _common.load_json(meta_path)
        if not isinstance(meta_data, dict):
            print(f"Warning: failed to read worktree meta {meta_path}", file=sys.stderr)
            continue
        if meta_data.get("state") != "cleaned":
            continue

        task_id = _coerce_nonempty_str(meta_data.get("taskId")) or meta_path.name.removesuffix(".meta.json")
        worktree_path = _meta_worktree_path(meta_data, project_root)
        entries.append(
            {
                "taskId": task_id,
                "path": str(worktree_path) if worktree_path else None,
                "branch": _coerce_nonempty_str(meta_data.get("branch")),
                "meta_path": str(meta_path.resolve(strict=False)),
                "legacy_cleaned_meta": True,
                "legacy_meta_data": meta_data,
                "legacy_migrated_at": migrated_at,
            }
        )
    return entries
def _normalize_meta_relative_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    relative_path = raw_path.replace("\\", "/")
    while relative_path.startswith("./"):
        relative_path = relative_path[2:]
    base_name = _common.BASE_DIR.name if _common.BASE_DIR else ".gran-maestro"
    for prefix in (f"{base_name}/", ".gran-maestro/"):
        if relative_path.startswith(prefix):
            return relative_path[len(prefix):]
    return relative_path
def _meta_relative_path(meta_data: dict, project_root: Path) -> str | None:
    worktree_path = _meta_worktree_path(meta_data, project_root)
    if worktree_path:
        for base_path in (_common.BASE_DIR, project_root):
            if base_path is None:
                continue
            try:
                return worktree_path.relative_to(base_path.resolve(strict=False)).as_posix()
            except ValueError:
                continue
    return _normalize_meta_relative_path(_coerce_nonempty_str(meta_data.get("path")))
def _normalize_scope_prefix(prefix: str | None) -> str | None:
    normalized = _normalize_meta_relative_path(_coerce_nonempty_str(prefix))
    if not normalized:
        return None
    return normalized
def _iter_scoped_meta_entries(
    project_root: Path,
    scope: str | None = None,
    prefix: str | None = None,
) -> list[dict]:
    entries: list[dict] = []
    scope_value = _coerce_nonempty_str(scope)
    prefix_value = _normalize_scope_prefix(prefix)
    if not scope_value and not prefix_value:
        return entries

    worktrees_dir = _common.BASE_DIR / "worktrees"
    if not worktrees_dir.is_dir():
        return entries

    for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
        meta_data = _common.load_json(meta_path)
        if not isinstance(meta_data, dict):
            print(f"Warning: failed to read worktree meta {meta_path}", file=sys.stderr)
            continue

        relative_path = _meta_relative_path(meta_data, project_root)
        scope_matches = bool(
            scope_value
            and (
                _coerce_nonempty_str(meta_data.get("agi_id")) == scope_value
                or (relative_path or "").startswith(f"worktrees/{scope_value}/sprint-")
            )
        )
        prefix_matches = bool(prefix_value and (relative_path or "").startswith(prefix_value))
        if not (scope_matches or prefix_matches):
            continue

        task_id = _coerce_nonempty_str(meta_data.get("taskId")) or meta_path.name.removesuffix(".meta.json")
        worktree_path = _meta_worktree_path(meta_data, project_root)
        entries.append(
            {
                "taskId": task_id,
                "path": str(worktree_path) if worktree_path else None,
                "branch": _coerce_nonempty_str(meta_data.get("branch")),
                "meta_path": str(meta_path.resolve(strict=False)),
            }
        )
    return entries
def _iter_scope_fs_orphan_entries(project_root: Path, scope: str | None, known_paths: set[Path]) -> list[dict]:
    scope_value = _coerce_nonempty_str(scope)
    if not scope_value:
        return []

    scope_dir = _common.BASE_DIR / "worktrees" / scope_value
    if not scope_dir.is_dir():
        return []

    entries: list[dict] = []
    for sprint_dir in sorted(scope_dir.glob("sprint-*")):
        if not sprint_dir.is_dir():
            continue
        worktree_path = sprint_dir.resolve(strict=False)
        if worktree_path in known_paths:
            continue
        entries.append(
            {
                "taskId": f"<fs-orphan:{sprint_dir.name}>",
                "path": str(worktree_path),
                "branch": None,
                "meta_path": None,
            }
        )
    return entries
def _detect_orphans_from_entries(project_root: Path, entries: list[dict]) -> list[dict]:
    worktree_roots = set(_list_worktree_roots(project_root))
    orphans: list[dict] = []

    for entry in entries:
        worktree_path = Path(entry["path"]) if entry.get("path") else None
        worktree_listed = worktree_path in worktree_roots if worktree_path else False
        path_exists = worktree_path.exists() if worktree_path else False
        branch_exists = _git_branch_exists(project_root, entry.get("branch"))

        if not (worktree_listed or branch_exists or path_exists):
            continue

        orphans.append(
            {
                **entry,
                "worktree_listed": worktree_listed,
                "branch_exists": branch_exists,
                "path_exists": path_exists,
            }
        )
    return orphans
def _detect_cleaned_orphans(project_root: Path) -> list[dict]:
    return _detect_orphans_from_entries(project_root, _iter_cleaned_meta_entries(project_root))
def _detect_scoped_orphans(
    project_root: Path,
    scope: str | None = None,
    prefix: str | None = None,
) -> list[dict]:
    entries = _iter_scoped_meta_entries(project_root, scope=scope, prefix=prefix)
    known_paths = {
        Path(entry["path"]).resolve(strict=False)
        for entry in entries
        if entry.get("path")
    }
    entries.extend(_iter_scope_fs_orphan_entries(project_root, scope, known_paths))
    return _detect_orphans_from_entries(project_root, entries)
def _run_orphan_cleanup_command(project_root: Path, command: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode == 0:
        return True, (result.stdout.strip() or result.stderr.strip())
    return False, (result.stderr.strip() or result.stdout.strip() or f"{' '.join(command)} failed")
def _clean_detected_orphan(project_root: Path, orphan: dict) -> tuple[bool, list[dict]]:
    steps: list[dict] = []
    worktree_path = orphan.get("path")
    branch = orphan.get("branch")

    if worktree_path and (orphan.get("worktree_listed") or orphan.get("path_exists")):
        remove_cmd = [
            sys.executable,
            str(_common._mst_script_path()),
            "worktree",
            "remove",
            "--path",
            worktree_path,
            "--force",
        ]
        ok, message = _run_orphan_cleanup_command(project_root, remove_cmd)
        steps.append({"command": " ".join(remove_cmd), "ok": ok, "message": message})
        if not ok:
            return False, steps

    if branch and orphan.get("branch_exists"):
        branch_cmd = ["git", "branch", "-D", branch]
        ok, message = _run_orphan_cleanup_command(project_root, branch_cmd)
        steps.append({"command": " ".join(branch_cmd), "ok": ok, "message": message})
        if not ok:
            return False, steps

    raw_meta_path = orphan.get("meta_path")
    if raw_meta_path:
        meta_path = Path(str(raw_meta_path))
        if orphan.get("legacy_cleaned_meta"):
            migrated_item = _migrate_legacy_cleaned_meta_file(
                project_root,
                meta_path,
                orphan.get("legacy_meta_data") if isinstance(orphan.get("legacy_meta_data"), dict) else {},
                migrated_at_dt=_parse_archive_datetime(orphan.get("legacy_migrated_at"))
                or datetime.now(timezone.utc).replace(microsecond=0),
            )
            if migrated_item is not None:
                steps.append(
                    {
                        "command": f"migrate meta {meta_path}",
                        "ok": True,
                        "message": migrated_item["target"],
                    }
                )
            return True, steps
        try:
            meta_path.unlink(missing_ok=True)
            steps.append({"command": f"remove meta {meta_path}", "ok": True, "message": str(meta_path)})
        except OSError as exc:
            steps.append({"command": f"remove meta {meta_path}", "ok": False, "message": str(exc)})
            return False, steps

    return True, steps
def _print_detect_orphans_payload(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    orphans = payload.get("orphans") or []
    if not orphans:
        print("[recover-orphan] cleaned meta orphan: none")
        return

    for orphan in orphans:
        reasons = [
            key
            for key in ("worktree_listed", "branch_exists", "path_exists")
            if orphan.get(key)
        ]
        print(
            "[recover-orphan] detected "
            f"taskId={orphan.get('taskId')} path={orphan.get('path')} "
            f"branch={orphan.get('branch')} reasons={','.join(reasons)}"
        )
        cleanup = orphan.get("cleanup")
        if cleanup:
            status = "cleaned" if cleanup.get("ok") else "failed"
            print(f"[recover-orphan] {status} taskId={orphan.get('taskId')}")
def cmd_worktree_archive_retention(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    default_days, default_count = _load_worktree_archive_retention_defaults()
    retention_days = _normalize_retention_value(getattr(args, "days", None))
    retention_count = _normalize_retention_value(getattr(args, "count", None))
    if retention_days is None and not getattr(args, "no_days", False):
        retention_days = default_days
    if retention_count is None and not getattr(args, "no_count", False):
        retention_count = default_count

    payload = prune_worktree_meta_archive(
        project_root,
        retention_days=retention_days,
        retention_count=retention_count,
        apply=bool(getattr(args, "apply", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        mode = "apply" if getattr(args, "apply", False) else "dry-run"
        print(
            f"[worktree-archive-retention] mode={mode} "
            f"days={retention_days} count={retention_count} "
            f"delete={len(payload['deleted'])} keep={len(payload['kept'])}"
        )
        for item in payload["deleted"]:
            print(f"delete session={item['session_token']} files={len(item['files'])}")
    return 0
def cmd_worktree_migrate_cleaned_meta(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    payload = migrate_legacy_cleaned_worktree_meta(project_root)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"[worktree-migrate-cleaned-meta] migrated={len(payload['migrated'])} skipped={len(payload['skipped'])}")
        for item in payload["migrated"]:
            print(f"migrated {item['source']} -> {item['target']}")
    return 0
def cmd_worktree_migrate_archive(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)
    apply = bool(getattr(args, "apply", False))
    delete = bool(getattr(args, "delete", False))
    payload = migrate_lineage_unknown_worktree_meta(project_root, apply=apply, delete=delete)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        mode = "apply" if apply else "dry-run"
        print(
            f"[worktree-migrate-archive] mode={mode} delete={delete} "
            f"candidates={payload['candidate_count']} migrated={payload['migrated_count']} "
            f"deleted={payload['deleted_count']} skipped={payload['skipped_count']}"
        )
        for item in payload["candidates"]:
            print(f"candidate lineage={item['lineage']} {item['source']} -> {item['target']}")
        for item in payload["migrated"]:
            print(f"migrated lineage={item['lineage']} {item['source']} -> {item['target']}")
        for item in payload["deleted"]:
            print(f"deleted lineage={item['lineage']} {item['target']}")
    return 0
def cmd_worktree_detect_orphans(args):
    project_root = _normalize_target_path(Path(_common.BASE_DIR).parent)

    scope = _coerce_nonempty_str(getattr(args, "scope", None))
    prefix = _coerce_nonempty_str(getattr(args, "prefix", None))

    try:
        if scope or prefix:
            orphans = _detect_scoped_orphans(project_root, scope=scope, prefix=prefix)
        else:
            orphans = _detect_cleaned_orphans(project_root)
            if not orphans:
                migrate_legacy_cleaned_worktree_meta(project_root)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "clean", False):
        for orphan in orphans:
            ok, steps = _clean_detected_orphan(project_root, orphan)
            orphan["cleanup"] = {"ok": ok, "steps": steps}

    cleaned = [
        orphan["taskId"]
        for orphan in orphans
        if orphan.get("cleanup", {}).get("ok") is True
    ]
    failed = [
        orphan["taskId"]
        for orphan in orphans
        if orphan.get("cleanup", {}).get("ok") is False
    ]
    payload = {
        "orphans": orphans,
        "cleaned": cleaned,
        "failed": failed,
    }
    _print_detect_orphans_payload(payload, getattr(args, "json", False))
    return 1 if failed else 0
def _read_git_worktree_branch(project_root: Path, worktree_path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        return None
    return _coerce_nonempty_str(result.stdout)
def _worktree_is_dirty(project_root: Path, worktree_path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    return result.returncode == 0 and bool(result.stdout.strip())
def _find_worktree_root(project_root: Path, worktree_path: Path) -> Path | None:
    try:
        for root in _list_worktree_roots(project_root):
            if _normalize_target_path(root) == _normalize_target_path(worktree_path):
                return root
    except RuntimeError:
        return None
    return None
def classify_worktree_collision(project_root: Path, worktree_path: Path, branch: str) -> str:
    normalized_path = _normalize_target_path(worktree_path)
    path_exists = normalized_path.exists()
    listed_root = _find_worktree_root(project_root, normalized_path)
    branch_exists = _git_branch_exists(project_root, branch)

    if listed_root is not None:
        current_branch = _read_git_worktree_branch(project_root, normalized_path)
        if _worktree_is_dirty(project_root, normalized_path):
            return "dirty_worktree_manual_conflict"
        if current_branch == branch and branch_exists:
            return "reusable_existing_worktree"
        return "stale_orphan_cleanup_required"

    if path_exists and not (normalized_path / ".git").exists():
        return "fatal_conflict"
    if path_exists or branch_exists:
        return "stale_orphan_cleanup_required"
    return "no_collision"
def cmd_worktree_classify_collision(args):
    branch = str(getattr(args, "branch", "") or "").strip()
    if not branch:
        print("Error: --branch is required", file=sys.stderr)
        return 1
    project_root = _resolve_master_project_root()
    classification = classify_worktree_collision(project_root, Path(args.path), branch)
    payload = {"classification": classification, "path": str(_normalize_target_path(args.path)), "branch": branch}
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(classification)
    return 0 if classification in {"no_collision", "reusable_existing_worktree"} else 2
def cmd_worktree_resolve_base(args):
    as_json = bool(getattr(args, "json", False))
    req_id = getattr(args, "req", None)
    if as_json:
        parent_session, session_error = _resolve_parent_session_context()
        if session_error is not None:
            _print_session_child_non_success(session_error, True)
            return 2
        detected_base = parent_session["session_branch"]
        if req_id:
            try:
                _persist_detected_base(req_id, detected_base, parent_session=parent_session)
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
        _print_resolve_base_payload(detected_base, req_id, True, parent_session=parent_session)
        return 0

    try:
        detected_base = current_head_branch()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    protected_patterns = _load_protected_branches()
    matched_pattern = matching_protected_pattern(detected_base, protected_patterns)
    if matched_pattern is not None:
        print(
            "Error: 현재 브랜치가 보호 브랜치입니다. "
            f"base={detected_base!r}, matched={matched_pattern!r}. "
            "다른 브랜치로 이동한 뒤 /mst:approve를 다시 실행하세요.",
            file=sys.stderr,
        )
        return 2

    if req_id:
        try:
            _persist_detected_base(req_id, detected_base)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    _print_resolve_base_payload(detected_base, req_id, False)
    return 0
def cmd_worktree_is_protected(args):
    branch = getattr(args, "branch", None)
    if not branch:
        try:
            branch = current_head_branch()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    protected_patterns = _load_protected_branches()
    matched_pattern = matching_protected_pattern(branch, protected_patterns)
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "branch": branch,
                    "protected": matched_pattern is not None,
                    "matched_pattern": matched_pattern,
                },
                ensure_ascii=False,
            )
        )
    elif matched_pattern is not None:
        print(matched_pattern)

    return 0 if matched_pattern is not None else 1
def cmd_worktree_slug(args):
    print(base_slug(args.base))
    return 0
def cmd_worktree_branch_name(args):
    agi_id = getattr(args, "agi", None)
    role = getattr(args, "role", None)
    if role:
        print(role_branch_name(args.req, role, args.base, agi_id))
    elif getattr(args, "task", None):
        print(task_branch_name(args.req, args.task, args.base, agi_id))
    else:
        print(req_branch_name(args.req, args.base, agi_id))
    return 0
def cmd_worktree_path(args):
    print(role_worktree_path(_project_root(), args.req, args.role, getattr(args, "agi", None)))
    return 0
def _boundary_payload(
    ok: bool,
    violation: str | None,
    retry_possible: bool,
    detected_base: str | None,
    reason: str,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> dict:
    return {
        "ok": ok,
        "violation": violation,
        "retry_possible": retry_possible,
        "detected_base": detected_base,
        "reason": reason,
        "owner_ppid": owner_ppid,
        "current_ppid": current_ppid,
    }
def _print_boundary_payload(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))
def _coerce_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
def _coerce_nonempty_str(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
def _load_boundary_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "JSON root is not an object"
    return data, None
def _boundary_request_path(req_id: str) -> Path:
    return _common.requests_dir() / req_id / "request.json"
def _boundary_meta_path(req_id: str, task_id: str) -> Path:
    return _common.BASE_DIR / "worktrees" / f"{req_id}-{task_id}.meta.json"
def _boundary_task_ids(request_data: dict, requested_task_id: str | None) -> list[str]:
    if requested_task_id:
        return [requested_task_id]

    task_ids: list[str] = []
    tasks = request_data.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict):
                task_id = _coerce_nonempty_str(task.get("id"))
                if task_id:
                    task_ids.append(task_id)
    return task_ids
def _all_tasks_have_phase2_ready_terminal_status(request_data: dict) -> bool:
    tasks = request_data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    for task in tasks:
        if not isinstance(task, dict):
            return False
        status = str(task.get("status", "")).strip().lower()
        if status not in _common.PHASE2_READY_TASK_STATUSES:
            return False
    return True
def _all_task_metas_missing(req_id: str, task_ids: list[str]) -> bool:
    if not task_ids:
        return False

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if meta_path.exists():
            return False
    return True
def _boundary_retry_possible(violation: str | None, detected_base: str | None, state: str | None) -> bool:
    if violation == "worktree_missing":
        return detected_base is not None
    if violation == "not_cleaned":
        return state in {"cleaning", "pre_merge", "clean_failed"}
    return False
def _phase_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
def _boundary_ok_payload(
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
    reason: str = "boundary ok",
) -> dict:
    return _boundary_payload(True, None, False, detected_base, reason, owner_ppid, current_ppid)
def _check_entry_boundary(
    req_id: str,
    request_data: dict,
    task_ids: list[str],
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> tuple[dict, int]:
    current_phase = _phase_int(request_data.get("current_phase"))
    if current_phase is None or current_phase < 2:
        return _boundary_ok_payload(
            detected_base,
            owner_ppid,
            current_ppid,
            "entry boundary not active before phase 2",
        ), 0

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if not meta_path.exists():
            violation = "worktree_missing"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, None),
                detected_base,
                f"worktree meta missing: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

        meta_data, error = _load_boundary_json(meta_path)
        if error:
            print(f"Warning: failed to read worktree meta {meta_path}: {error}", file=sys.stderr)
            return _boundary_payload(
                False,
                None,
                False,
                detected_base,
                f"failed to read worktree meta: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 3
        if meta_data.get("state") == "conflict":
            violation = "merge_conflict"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, "conflict"),
                detected_base,
                f"worktree meta is in conflict state: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

    return _boundary_ok_payload(detected_base, owner_ppid, current_ppid), 0
def _check_exit_boundary(
    req_id: str,
    request_data: dict,
    task_ids: list[str],
    detected_base: str | None,
    owner_ppid: int | None,
    current_ppid: int | None,
) -> tuple[dict, int]:
    status = str(request_data.get("status", "")).strip().lower()
    if status != "done":
        violation = "not_cleaned"
        return _boundary_payload(
            False,
            violation,
            _boundary_retry_possible(violation, detected_base, None),
            detected_base,
            f"request status is not done: {status or '<empty>'}",
            owner_ppid,
            current_ppid,
        ), 0

    if _all_tasks_have_phase2_ready_terminal_status(request_data) and _all_task_metas_missing(req_id, task_ids):
        return _boundary_payload(
            True,
            None,
            False,
            detected_base,
            "legacy_no_meta: all tasks in phase2 ready terminal status and no meta files (legacy CLI path)",
            owner_ppid,
            current_ppid,
        ), 0

    for task_id in task_ids:
        meta_path = _boundary_meta_path(req_id, task_id)
        if not meta_path.exists():
            violation = "worktree_missing"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, None),
                detected_base,
                f"worktree meta missing: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0

        meta_data, error = _load_boundary_json(meta_path)
        if error:
            print(f"Warning: failed to read worktree meta {meta_path}: {error}", file=sys.stderr)
            return _boundary_payload(
                False,
                None,
                False,
                detected_base,
                f"failed to read worktree meta: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 3

        state = _coerce_nonempty_str(meta_data.get("state"))
        if state == "conflict":
            violation = "merge_conflict"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, state),
                detected_base,
                f"worktree meta is in conflict state: {meta_path}",
                owner_ppid,
                current_ppid,
            ), 0
        if state != "cleaned":
            violation = "not_cleaned"
            return _boundary_payload(
                False,
                violation,
                _boundary_retry_possible(violation, detected_base, state),
                detected_base,
                f"worktree meta state is not cleaned: {meta_path} state={state or '<missing>'}",
                owner_ppid,
                current_ppid,
            ), 0

    return _boundary_ok_payload(detected_base, owner_ppid, current_ppid), 0
def cmd_worktree_check_boundary(args):
    req_id = _coerce_nonempty_str(args.req)
    current_ppid = getattr(args, "ppid", None)
    if not req_id:
        print("Warning: --req is required", file=sys.stderr)
        return 2

    request_path = _boundary_request_path(req_id)
    if not request_path.exists():
        payload = _boundary_payload(
            False,
            "unknown_req",
            False,
            None,
            f"request.json not found: {request_path}",
            None,
            current_ppid,
        )
        _print_boundary_payload(payload)
        return 0

    request_data, error = _load_boundary_json(request_path)
    if error:
        print(f"Warning: failed to read request.json {request_path}: {error}", file=sys.stderr)
        payload = _boundary_payload(
            False,
            None,
            False,
            None,
            f"failed to read request.json: {request_path}",
            None,
            current_ppid,
        )
        _print_boundary_payload(payload)
        return 3

    detected_base = _coerce_nonempty_str(request_data.get("detected_base"))
    owner_ppid = _coerce_int(request_data.get("owner_ppid"))
    if current_ppid is not None and owner_ppid is not None and current_ppid != owner_ppid:
        print(
            f"[boundary] diagnostic: owner_ppid ignored: owner_ppid={owner_ppid} current_ppid={current_ppid}",
            file=sys.stderr,
        )

    task_ids = _boundary_task_ids(request_data, getattr(args, "task_id", None))
    if not task_ids:
        payload = _boundary_ok_payload(
            detected_base,
            owner_ppid,
            current_ppid,
            "no task ids available for boundary check",
        )
        _print_boundary_payload(payload)
        return 0

    if args.phase == "entry":
        payload, exit_code = _check_entry_boundary(
            req_id,
            request_data,
            task_ids,
            detected_base,
            owner_ppid,
            current_ppid,
        )
    else:
        payload, exit_code = _check_exit_boundary(
            req_id,
            request_data,
            task_ids,
            detected_base,
            owner_ppid,
            current_ppid,
        )
    _print_boundary_payload(payload)
    return exit_code
def _register_worktree_dispatch(subcommand: str, fn) -> None:
    package = sys.modules.get("scripts.mst_cmds")
    dispatch = getattr(package, "DISPATCH", None)
    if isinstance(dispatch, dict):
        dispatch[("worktree", subcommand)] = fn
