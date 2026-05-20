def cmd_dispatch_register(args):
    try:
        child_env = _dispatch_required_session_context()
    except ValueError as exc:
        if isinstance(exc, _common.ContractValidationError):
            return _emit_dispatch_validation_failure(exc)
        validation_result = _emit_dispatch_value_error(exc)
        if validation_result is not None:
            return validation_result
        if _common.is_missing_canonical_session_error(exc):
            if (
                not os.environ.get("MST_CONTEXT_JSON", "").strip()
                and not os.environ.get("MST_HOOK_STDIN_RAW", "").strip()
            ):
                started_by_pid = resolve_started_by_pid()
                if started_by_pid > 0:
                    print(
                        json.dumps(
                            {
                                "status": "skipped",
                                "reason": "missing_canonical_mst_session_id",
                                "created_new_session": False,
                                "prompt_summary_used_as_source": False,
                                "task_id": str(args.task_id).strip(),
                                "started_by_pid": started_by_pid,
                            },
                            ensure_ascii=False,
                        )
                    )
                    return 0
            return _common.emit_session_identity_non_success("dispatch register")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    now = _now_iso()
    task_id = str(args.task_id).strip()
    marker_pid = int(args.pid)
    state_path = _dispatch_state_path(task_id)
    existing_payload = load_json(state_path)
    if isinstance(existing_payload, dict):
        payload_error = _dispatch_payload_error(existing_payload, session_id)
        if payload_error is not None:
            return _emit_dispatch_payload_mismatch(payload_error)
    canonical_fields = _canonical_dispatch_fields(session_id)
    payload = {
        **canonical_fields,
        **_continuation_policy_from_context(child_env.get("MST_CONTEXT_JSON", "")),
        "task_id": task_id,
        "child_artifact_id": task_id,
        "external_control_surface": "dispatch",
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
        "pid": marker_pid,
        "pid_start_time": _process_start_time(marker_pid) or f"pid:{marker_pid}:started_at:{now}",
        "started_at": now,
        "phase": "running",
        "provider": str(args.provider).strip().lower(),
        "skill": str(getattr(args, "skill", "")).strip(),
        "model": str(args.model).strip(),
        "worktree_dir": str(args.worktree_dir),
        "last_heartbeat": now,
    }
    payload["next_execution"] = _dispatch_context_envelope(
        session_id=session_id,
        task_id=task_id,
        raw_context=child_env.get("MST_CONTEXT_JSON", ""),
    )["next_execution"]
    if getattr(args, "started_by_pid", None) is not None:
        try:
            payload["started_by_pid"] = int(args.started_by_pid)
        except (TypeError, ValueError):
            print(
                f"[dispatch] warning: invalid started_by_pid skipped: {args.started_by_pid}",
                file=sys.stderr,
            )
    else:
        payload["started_by_pid"] = resolve_started_by_pid()
    try:
        cleanup_mod.write_active_flow_marker_for_pid(
            project_root=_common.BASE_DIR.parent,
            session_id=session_id,
            pid=marker_pid,
            mode="single-shot",
            extra={
                "entrypoint": "dispatch",
                "task_id": task_id,
                **canonical_fields,
                "provider": payload["provider"],
                "worktree_dir": payload["worktree_dir"],
            },
        )
    except Exception as exc:
        print(f"[dispatch] warning: failed to write active-flow marker ({exc})", file=sys.stderr)
    save_json(state_path, payload)
    _append_dispatch_history_event(session_id, payload, "dispatch.register")
    print(json.dumps(payload, ensure_ascii=False))
    return 0
def cmd_dispatch_heartbeat(args):
    try:
        child_env = _dispatch_required_session_context()
    except ValueError as exc:
        if isinstance(exc, _common.ContractValidationError):
            return _emit_dispatch_validation_failure(exc)
        validation_result = _emit_dispatch_value_error(exc)
        if validation_result is not None:
            return validation_result
        if _common.is_missing_canonical_session_error(exc):
            return _common.emit_session_identity_non_success("dispatch heartbeat")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    task_id = str(args.task_id).strip()
    now = _now_iso()
    state_path = _dispatch_state_path(task_id)
    payload = load_json(state_path)
    if not isinstance(payload, dict):
        payload = {"task_id": task_id}
    payload_error = _dispatch_payload_error(payload, session_id)
    if payload_error is not None:
        return _emit_dispatch_payload_mismatch(payload_error)

    payload.update(_canonical_dispatch_fields(session_id))
    payload.update(_continuation_policy_from_context(child_env.get("MST_CONTEXT_JSON", "")))
    payload["task_id"] = task_id
    payload["child_artifact_id"] = task_id
    payload["external_control_surface"] = "dispatch"
    payload["created_new_session"] = False
    payload["prompt_summary_used_as_source"] = False
    payload["next_execution"] = _dispatch_context_envelope(
        session_id=session_id,
        task_id=task_id,
        raw_context=child_env.get("MST_CONTEXT_JSON", ""),
    )["next_execution"]
    payload["last_heartbeat"] = now
    if args.phase:
        payload["phase"] = str(args.phase).strip()

    if args.final:
        payload["phase"] = "done"
        payload["terminated_at"] = now
        if args.exit_code is not None:
            payload["exit_code"] = int(args.exit_code)

    log_file = getattr(args, "log_file", None)
    if log_file and not args.final:
        try:
            monitor_result = evaluate_delegate_io_attention(
                payload,
                {"combined": Path(str(log_file))},
                process_identity={
                    "pid": payload.get("pid"),
                    "pid_start_time": str(payload.get("pid_start_time") or ""),
                    "pid_alive": _pid_is_alive(int(payload.get("pid") or 0)),
                },
            )
            payload = monitor_result["state"]
        except Exception:
            pass

    try:
        save_json(state_path, payload)
    except Exception as exc:
        print(f"[dispatch] warning: failed to write heartbeat state ({exc})", file=sys.stderr)
        return 0

    _append_dispatch_history_event(session_id, payload, "dispatch.heartbeat")
    print(json.dumps(payload, ensure_ascii=False))
    return 0
def cmd_dispatch_list(args):
    stale_threshold = _dispatch_stale_threshold(args)
    rows = _collect_dispatch_rows(stale_threshold)

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("No dispatch entries found.")
        return 0

    print(f"{'TASK_ID':<32} {'STATUS':<10} {'AGE(s)':<8} {'PID':<8} {'PROVIDER':<8} {'PHASE'}")
    for row in rows:
        print(
            f"{str(row.get('task_id', '')):<32} "
            f"{str(row.get('status', '')):<10} "
            f"{str(row.get('age_sec', '')):<8} "
            f"{str(row.get('pid', '')):<8} "
            f"{str(row.get('provider', '')):<8} "
            f"{str(row.get('phase', ''))}"
        )
    return 0
def _signal_from_name(raw_signal: str) -> int:
    normalized = str(raw_signal or "TERM").strip().upper()
    if normalized == "KILL":
        return signal.SIGKILL
    return signal.SIGTERM
def cmd_dispatch_kill(args):
    stale_threshold = _dispatch_stale_threshold(args)
    signal_name = str(args.signal).strip().upper()
    signal_value = _signal_from_name(signal_name)

    rows: list[dict]
    if args.stale:
        rows = [row for row in _collect_dispatch_rows(stale_threshold) if row.get("status") == "stale"]
    else:
        state_path = _dispatch_state_path(str(args.task_id).strip())
        row = _build_status_row(state_path, stale_threshold, datetime.now(timezone.utc))
        rows = [row] if row is not None else []

    terminated = 0
    for row in rows:
        task_id = str(row.get("task_id", ""))
        pid = row.get("pid")
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            print(f"[dispatch] warning: invalid pid for task '{task_id}'", file=sys.stderr)
            continue

        try:
            os.kill(pid_int, signal_value)
            terminated += 1
        except ProcessLookupError:
            print(f"[dispatch] warning: pid not found for task '{task_id}' ({pid_int})", file=sys.stderr)
        except Exception as exc:
            print(f"[dispatch] warning: failed to signal task '{task_id}' ({exc})", file=sys.stderr)
            continue

        state_path = _dispatch_state_path(task_id)
        payload = load_json(state_path)
        if not isinstance(payload, dict):
            payload = {"task_id": task_id}
        payload["phase"] = "terminated"
        payload["signal"] = signal_name
        payload["terminated_at"] = _now_iso()
        payload["last_heartbeat"] = payload.get("terminated_at")
        try:
            save_json(state_path, payload)
        except Exception as exc:
            print(f"[dispatch] warning: failed to update state for task '{task_id}' ({exc})", file=sys.stderr)

    print(json.dumps({"terminated": terminated}, ensure_ascii=False))
    return 0
def _dispatch_run_dir_no_create() -> Path:
    return _common.run_dir_no_create()
def _cleanup_archive_dir(now: datetime) -> Path:
    base_dir = _common.BASE_DIR if _common.BASE_DIR is not None else _common.cwd_base_dir()
    return base_dir / "archive" / "run" / f"{now.year:04d}-{now.month:02d}"
def _has_valid_started_by_pid(payload: dict) -> bool:
    if "started_by_pid" not in payload:
        return False
    try:
        int(payload.get("started_by_pid"))
    except (TypeError, ValueError):
        return False
    return True
def _cleanup_marker_reason(payload: dict, archive_after_seconds: int, now: datetime, include_legacy: bool) -> str | None:
    if include_legacy and not _has_valid_started_by_pid(payload):
        return "legacy"

    phase = str(payload.get("phase", "")).strip().lower()
    if phase != "done":
        return None

    heartbeat = _parse_utc_datetime(payload.get("last_heartbeat"))
    if heartbeat is None:
        return None

    age_seconds = max(0, int((now - heartbeat).total_seconds()))
    if age_seconds > archive_after_seconds:
        return "stale_done"
    return None
def _dispatch_cleanup_markers(args) -> dict:
    run_directory = _dispatch_run_dir_no_create()
    if not run_directory.is_dir():
        print("SUMMARY: archived=0 legacy=0 stale_done=0 preserved=0")
        return {"status": "ok", "archived": 0, "legacy": 0, "stale_done": 0, "preserved": 0}

    now = datetime.now(timezone.utc)
    archive_after_seconds = max(0, int(args.archive_after_days)) * 86400
    include_legacy = bool(getattr(args, "legacy", False))
    dry_run = bool(getattr(args, "dry_run", False))
    archived = 0
    legacy = 0
    stale_done = 0
    preserved = 0

    for path in sorted(run_directory.glob("*.json")):
        if not path.is_file():
            continue

        payload = load_json(path)
        if not isinstance(payload, dict):
            preserved += 1
            print(f"[dispatch] debug: failed to parse cleanup marker preserved: {path}", file=sys.stderr)
            continue

        reason = _cleanup_marker_reason(payload, archive_after_seconds, now, include_legacy)
        if reason is None:
            preserved += 1
            continue

        if dry_run:
            print(f"[dry-run] would archive: {path} (reason: {reason})")
            archived += 1
            if reason == "legacy":
                legacy += 1
            else:
                stale_done += 1
            continue

        archive_dir = _cleanup_archive_dir(now)
        target = archive_dir / path.name
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except Exception as exc:
            preserved += 1
            print(f"[dispatch] warning: failed to archive marker '{path}' ({exc})", file=sys.stderr)
            continue

        archived += 1
        if reason == "legacy":
            legacy += 1
        else:
            stale_done += 1

    print(f"SUMMARY: archived={archived} legacy={legacy} stale_done={stale_done} preserved={preserved}")
    return {
        "status": "ok",
        "archived": archived,
        "legacy": legacy,
        "stale_done": stale_done,
        "preserved": preserved,
    }
def cmd_dispatch_cleanup(args):
    session_id = os.environ.get("MST_SESSION_ID", "").strip() or "dispatch-cleanup"
    result = cleanup_mod.run_cleanup_with_lock_report(
        project_root=_common.BASE_DIR.parent,
        entrypoint="stale-marker",
        session_id=session_id,
        timeout_seconds=5.0,
        cleanup_fn=lambda _context: _dispatch_cleanup_markers(args),
    )
    if result.get("status") == "skipped":
        print(f"SUMMARY: archived=0 legacy=0 stale_done=0 preserved=0")
        print(f"[dispatch] cleanup skipped: {result.get('reason', 'unknown')}", file=sys.stderr)
    return 0
def register(subparsers):
    sub = subparsers
    dispatch = sub.add_parser("dispatch")
    dispatch_sub = dispatch.add_subparsers(dest="subcommand")

    build = dispatch_sub.add_parser("build")
    build.add_argument("--provider", choices=["codex", "gemini", "claude"], required=True)
    build.add_argument("--prompt-file", required=True)
    build.add_argument("--task-id", required=True)
    build.add_argument("--worktree-dir", required=True)
    build.add_argument("--log-file", required=True)
    build.add_argument("--model")

    preflight = dispatch_sub.add_parser("preflight")
    preflight.add_argument("--provider", choices=["codex", "gemini", "claude"], required=True)
    preflight.add_argument("--model")

    register_cmd = dispatch_sub.add_parser("register")
    register_cmd.add_argument("--task-id", required=True)
    register_cmd.add_argument("--pid", required=True)
    register_cmd.add_argument("--provider", required=True)
    register_cmd.add_argument("--skill", default="")
    register_cmd.add_argument("--model", required=True)
    register_cmd.add_argument("--worktree-dir", required=True)
    register_cmd.add_argument("--started-by-pid")

    heartbeat = dispatch_sub.add_parser("heartbeat")
    heartbeat.add_argument("--task-id", required=True)
    heartbeat.add_argument("--phase")
    heartbeat.add_argument("--final", action="store_true")
    heartbeat.add_argument("--exit-code")
    heartbeat.add_argument("--log-file")

    list_cmd = dispatch_sub.add_parser("list")
    list_cmd.add_argument("--format", choices=["json", "table"], default="table")
    list_cmd.add_argument("--stale-threshold")

    kill = dispatch_sub.add_parser("kill")
    group = kill.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-id")
    group.add_argument("--stale", action="store_true")
    kill.add_argument("--signal", choices=["TERM", "KILL"], default="TERM")
    kill.add_argument("--stale-threshold")

    cleanup = dispatch_sub.add_parser("cleanup")
    cleanup.add_argument("--legacy", action="store_true")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--archive-after-days", type=int, default=7)
    cleanup.set_defaults(func=cmd_dispatch_cleanup)
