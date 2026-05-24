def cmd_hook_repair(args: argparse.Namespace) -> int:
    try:
        require_user_tty()
        if args.session:
            return _repair_session(args)
        if args.manifest:
            return _repair_manifest(args)
        print("one of --session or --manifest is required", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
def cmd_hook_log(args: argparse.Namespace) -> int:
    sessions_dir = _common.BASE_DIR / "sessions"
    if args.session:
        try:
            result = _load_validated_history(
                project_root=_project_root(),
                policy_home=_policy_home(),
                raw_session_id=args.session,
            )
        except HistoryValidationError as exc:
            _emit_history_error(exc, json_mode=bool(args.json))
            return 2
        rows = result.rows
    else:
        rows = []
        if sessions_dir.is_dir():
            for session_dir in sorted(path for path in sessions_dir.iterdir() if path.is_dir()):
                try:
                    result = _load_validated_history(
                        project_root=_project_root(),
                        policy_home=_policy_home(),
                        raw_session_id=session_dir.name,
                    )
                except HistoryValidationError:
                    continue
                rows.extend(result.rows)

    if args.type:
        rows = [row for row in rows if _event_type(row) == args.type]
    rows.sort(key=_event_timestamp)

    limit = max(0, int(args.limit))
    if limit:
        rows = rows[-limit:]
    else:
        rows = []

    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        _print_hook_log_table(rows)
    return 0
def cmd_history_log(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    rows = sorted(result.projections, key=lambda row: row["seq"])
    limit = max(0, int(args.limit))
    if limit:
        rows = rows[-limit:]
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        _print_history_log_table(rows)
    return 0
def cmd_history_verify(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    payload = _history_summary(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"ok session={result.session_id} seq={result.tail_seq} head={result.tail_hash}")
    return 0
def cmd_history_head(args: argparse.Namespace) -> int:
    try:
        result = _load_validated_history(
            project_root=_project_root(),
            policy_home=_policy_home(),
            raw_session_id=args.session,
        )
    except HistoryValidationError as exc:
        _emit_history_error(exc, json_mode=bool(args.json))
        return 2

    payload = {
        "status": "ok",
        "mst_session_id": result.session_id,
        "root_mst_id": result.root_mst_id,
        "head": {"event_hash": result.tail_hash, "seq": result.tail_seq},
        "local_head": str(result.local_head),
        "mirror_head": str(result.mirror_head),
        "verify_state": str(result.verify_state),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(result.tail_hash)
    return 0
def cmd_hook_allow(args: argparse.Namespace) -> int:
    if not (args.list or args.remove):
        try:
            require_user_tty()
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 2

    allowlist_path = _allowlist_path()
    data = _load_allowlist(allowlist_path)

    if args.list:
        _print_allowlist(data)
        return 0

    if args.remove:
        before = len(data["entries"])
        data["entries"] = [entry for entry in data["entries"] if entry.get("id") != args.remove]
        if len(data["entries"]) == before:
            print(f"Not found: {args.remove}", file=sys.stderr)
            return 1
        _save_allowlist(allowlist_path, data)
        print(f"Removed: {args.remove}")
        return 0

    if not args.tool:
        print("--tool required for add", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    expires_at = _format_utc(now + timedelta(minutes=args.expires)) if args.expires is not None else None
    entry = {
        "id": f"alw_{secrets.token_hex(4)}",
        "tool": args.tool,
        "args_pattern": args.args_pattern or "*",
        "expires_at": expires_at,
        "added_by_tty": True,
        "created_at": _format_utc(now),
    }
    data.setdefault("entries", []).append(entry)
    _save_allowlist(allowlist_path, data)
    print(f"Added: {entry['id']}")
    return 0
def cmd_hook_stop(args: argparse.Namespace) -> int:
    if getattr(args, "stop_subcommand", None) == "judge":
        return stop_judge.cmd_hook_stop_judge(args)
    print("hook stop requires a subcommand", file=sys.stderr)
    return 2
def register(subparsers):
    hook = subparsers.add_parser("hook")
    hook_sub = hook.add_subparsers(dest="subcommand")
    repair = hook_sub.add_parser("repair")
    mode = repair.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session")
    mode.add_argument("--manifest", action="store_true")
    repair.add_argument("--truncate-to", type=int)
    repair.add_argument("--yes", action="store_true")
    repair.set_defaults(func=cmd_hook_repair)

    log = hook_sub.add_parser(
        "log",
        description=(
            "Show hook event rows as a backward-compatible subset of canonical history. "
            "DOD-005 source of truth is mst.py history log --session MST_SESSION_ID: "
            "the single mst_session_id ledger under .gran-maestro/sessions/{mst_session_id}/history.*. "
            "This command must not use PPID, Claude hook session_id, or global/default ledger fallback."
        ),
    )
    log.add_argument("--session", help="Optional mst_session_id; when provided, read only that validated session ledger.")
    log.add_argument("--type", help="Filter by hook event type.")
    log.add_argument("--limit", type=int, default=50, help="Maximum rows to print; defaults to 50.")
    log.add_argument("--json", action="store_true", help="Emit NDJSON rows.")
    log.set_defaults(func=cmd_hook_log)

    history = subparsers.add_parser(
        "history",
        description=(
            "Inspect the DOD-005 single history ledger keyed only by mst_session_id. "
            "Queries validate append-only seq/prev_hash/event_hash rows, local history.head, "
            "policy mirror head, and history.verify for the same session key; split-ledger "
            "violations and legacy fallback inputs fail closed."
        ),
    )
    history_sub = history.add_subparsers(dest="subcommand")

    history_log = history_sub.add_parser(
        "log",
        description=(
            "Read event rows from one .gran-maestro/sessions/{mst_session_id}/history.ndjson ledger. "
            "Every returned row is read-time validated for schema_version, mst_session_id, root_mst_id, "
            "event_type, created_at, seq, prev_hash, event_hash, and idempotency_key. "
            "No PPID, Claude hook session_id, owner_session_id, global hook ledger, or default history fallback is used."
        ),
    )
    history_log.add_argument("--session", required=True, help="Structured mst_session_id that selects the single canonical ledger.")
    history_log.add_argument("--limit", type=int, default=0, help="Maximum rows to print; 0 prints all validated rows.")
    history_log.add_argument("--json", action="store_true", help="Emit validated projection rows as NDJSON.")
    history_log.set_defaults(func=cmd_history_log)

    history_verify = history_sub.add_parser(
        "verify",
        description=(
            "Verify append-only head state for one mst_session_id ledger. "
            "The command compares the ledger tail seq/hash with local history.head, active policy mirror head, "
            "and history.verify for the same session key, returning structured non-success for missing, stale, mismatch, "
            "corrupt, or split-ledger violation states instead of repairing or falling back."
        ),
    )
    history_verify.add_argument("--session", required=True, help="Structured mst_session_id whose ledger head/verify state is checked.")
    history_verify.add_argument("--json", action="store_true", help="Emit the verification summary or error as JSON.")
    history_verify.set_defaults(func=cmd_history_verify)

    history_head = history_sub.add_parser(
        "head",
        description=(
            "Show the append-only head for one mst_session_id ledger after validating history.ndjson, "
            "local history.head, active policy mirror head, and history.verify. "
            "The head is session-key scoped and never resolved through legacy process/session fallback."
        ),
    )
    history_head.add_argument("--session", required=True, help="Structured mst_session_id whose canonical ledger head is shown.")
    history_head.add_argument("--json", action="store_true", help="Emit the head summary or error as JSON.")
    history_head.set_defaults(func=cmd_history_head)

    allow = hook_sub.add_parser("allow")
    allow.add_argument("tool", nargs="?")
    allow.add_argument("--args-pattern")
    allow.add_argument("--expires", type=int)
    allow.add_argument("--list", action="store_true")
    allow.add_argument("--remove")
    allow.set_defaults(func=cmd_hook_allow)

    stop = hook_sub.add_parser("stop")
    stop_sub = stop.add_subparsers(dest="stop_subcommand")
    judge = stop_sub.add_parser("judge")
    judge.add_argument("--stdin-file", required=True, help="Path to the captured Stop hook stdin payload JSON.")
    judge.add_argument(
        "--hook-timeout-ms",
        type=int,
        default=stop_judge.DEFAULT_HOOK_TIMEOUT_MS,
        help="Timeout budget passed by the shell wrapper for fail-safe diagnostics.",
    )
    judge.set_defaults(func=cmd_hook_stop)
