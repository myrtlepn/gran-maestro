def _validate_context_identity(payload: dict, session_id: str) -> None:
    parsed = validate_mst_session_id(session_id)
    has_legacy_identity = any(
        isinstance(payload.get(key), str) and payload.get(key, "").strip()
        for key in ("session_id", "sessionId", "owner_session_id")
    )
    core = payload.get("core_rehydration")
    if isinstance(core, dict):
        has_legacy_identity = has_legacy_identity or any(
            isinstance(core.get(key), str) and core.get(key, "").strip()
            for key in ("session_id", "sessionId", "owner_session_id")
        )
    if has_legacy_identity:
        _common.raise_validation_failure(
            target="dispatch_envelope",
            field="legacy_identity",
            reason="legacy session identity is not a canonical source",
            code="legacy_identity_not_canonical_source",
        )

    if "schema_version" in payload and payload.get("schema_version") != 1:
        _common.raise_validation_failure(
            target="dispatch_envelope",
            field="schema_version",
            reason="dispatch context schema_version must be 1 when provided",
        )
    if not isinstance(payload.get("mst_session_id"), str) or not payload.get("mst_session_id", "").strip():
        _common.raise_validation_failure(
            target="dispatch_envelope",
            field="mst_session_id",
            reason="dispatch context mst_session_id is required",
        )
    if not isinstance(payload.get("root_mst_id"), str) or not payload.get("root_mst_id", "").strip():
        _common.raise_validation_failure(
            target="dispatch_envelope",
            field="root_mst_id",
            reason="dispatch context root_mst_id is required",
        )

    for candidate in _context_payload_session_candidates(payload):
        if validate_mst_session_id(candidate).mst_session_id != parsed.mst_session_id:
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="mst_session_id",
                reason="MST_SESSION_ID and structured mst_session_id mismatch",
            )

    for field, root_mst_id in _context_payload_root_candidates(payload):
        if validate_root_mst_id(root_mst_id) != parsed.root_mst_id:
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field=field,
                reason="MST_CONTEXT_JSON root_mst_id mismatch",
            )

    if isinstance(core, dict):
        core_schema_version = core.get("schema_version")
        if core_schema_version != 1:
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="core_rehydration.schema_version",
                reason="MST_CONTEXT_JSON core_rehydration schema_version must be 1",
            )
        if not isinstance(core.get("mst_session_id"), str) or not core.get("mst_session_id", "").strip():
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="core_rehydration.mst_session_id",
                reason="MST_CONTEXT_JSON core_rehydration mst_session_id is required",
            )
        core_root = core.get("root_mst_id")
        if not isinstance(core_root, str) or not core_root.strip():
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="core_rehydration.root_mst_id",
                reason="MST_CONTEXT_JSON core_rehydration root_mst_id is required",
            )
        if validate_root_mst_id(core_root.strip()) != parsed.root_mst_id:
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="core_rehydration.root_mst_id",
                reason="MST_CONTEXT_JSON core_rehydration root_mst_id mismatch",
            )
        if ("auto" in payload or "auto" in core) and payload.get("auto") != core.get("auto"):
            _common.raise_validation_failure(
                target="dispatch_envelope",
                field="auto",
                reason="dispatch context auto policy mismatch",
            )
def _normalized_child_context_payload(raw_context: str, session_id: str) -> dict:
    context_payload: dict = {}
    if raw_context:
        try:
            parsed = json.loads(raw_context)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MST_CONTEXT_JSON must be a JSON object: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("MST_CONTEXT_JSON must be a JSON object")
        _validate_context_identity(parsed, session_id)
        context_payload = dict(parsed)

    canonical_fields = _common.canonical_state_payload_fields(session_id)
    context_payload.setdefault("schema_version", canonical_fields["schema_version"])
    context_payload["mst_session_id"] = canonical_fields["mst_session_id"]
    context_payload.setdefault("root_mst_id", canonical_fields["root_mst_id"])

    core = context_payload.get("core_rehydration")
    if isinstance(core, dict):
        next_execution = core.get("next_execution")
        if isinstance(next_execution, dict):
            env = next_execution.get("env")
            if isinstance(env, dict):
                existing_env_sid = env.get("MST_SESSION_ID")
                if isinstance(existing_env_sid, str) and existing_env_sid.strip() and existing_env_sid.strip() != session_id:
                    raise ValueError("MST_SESSION_ID and recovered next_execution env mismatch")
                env["MST_SESSION_ID"] = session_id
            context = next_execution.get("context")
            if isinstance(context, dict):
                existing_context_sid = context.get("mst_session_id")
                if (
                    isinstance(existing_context_sid, str)
                    and existing_context_sid.strip()
                    and existing_context_sid.strip() != session_id
                ):
                    raise ValueError("MST_SESSION_ID and recovered next_execution context mismatch")
                context["mst_session_id"] = session_id

    return context_payload
def _session_id_from_stdin_or_env_payload() -> str | None:
    for env_name in ("MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW"):
        raw = os.environ.get(env_name, "")
        if raw:
            value = _session_id_from_payload(raw)
            if value:
                return value
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
        return _session_id_from_payload(sys.stdin.read())
    except Exception:
        return None
def _validate_session_id(value: str) -> str:
    return validate_mst_session_id(value).mst_session_id
def resolve_session_id_identity(
    *,
    allow_generate: bool = True,
    root_mst_id: str | None = None,
    started_at: datetime | None = None,
) -> dict:
    env_value = canonical_session_id_from_env()
    payload_value = _session_id_from_stdin_or_env_payload()
    if env_value and payload_value and env_value != payload_value:
        raise ValueError("MST_SESSION_ID and structured mst_session_id mismatch")

    if env_value:
        return {
            "mst_session_id": _validate_session_id(env_value),
            "source": "env:MST_SESSION_ID",
            "legacy_diagnostics": _common.legacy_session_diagnostics(),
        }

    if payload_value:
        return {
            "mst_session_id": _validate_session_id(payload_value),
            "source": "payload:mst_session_id",
            "legacy_diagnostics": _common.legacy_session_diagnostics(),
        }

    if not allow_generate:
        raise ValueError("missing MST_SESSION_ID")

    if not root_mst_id:
        raise ValueError("missing MST_SESSION_ID and root_mst_id for structured mst_session_id generation")

    generated = generate_mst_session_id(root_mst_id, started_at=started_at)
    return {
        "mst_session_id": generated,
        "source": "generated:root_mst_id",
        "legacy_diagnostics": _common.legacy_session_diagnostics(),
    }
def resolve_session_id_value(*, allow_generate: bool = True) -> str:
    identity = resolve_session_id_identity(allow_generate=allow_generate)
    env_value = identity["mst_session_id"]
    if env_value:
        return env_value
    raise RuntimeError("MST_SESSION_ID could not be resolved")
def ensure_session_id_in_env() -> str:
    session_id = resolve_session_id_value()
    if not session_id:
        raise RuntimeError("MST_SESSION_ID could not be resolved")
    os.environ["MST_SESSION_ID"] = session_id
    return session_id
def child_env_with_session_id() -> dict[str, str]:
    session_id = ensure_session_id_in_env()
    child_env = os.environ.copy()
    child_env["MST_SESSION_ID"] = session_id
    return child_env
def child_env_with_required_session_context() -> dict[str, str]:
    env_value = canonical_session_id_from_env()
    if not env_value:
        raise ValueError("missing MST_SESSION_ID")

    payload_value = _session_id_from_stdin_or_env_payload()
    if payload_value and env_value != payload_value:
        _common.raise_validation_failure(
            target="dispatch_envelope",
            field="mst_session_id",
            reason="MST_SESSION_ID and structured mst_session_id mismatch",
        )

    session_id = _validate_session_id(env_value)
    child_env = os.environ.copy()
    child_env["MST_SESSION_ID"] = session_id

    context_payload = _normalized_child_context_payload(
        child_env.get("MST_CONTEXT_JSON", "").strip(),
        session_id,
    )
    child_env["MST_CONTEXT_JSON"] = json.dumps(context_payload, ensure_ascii=False, separators=(",", ":"))
    return child_env
def cmd_session_resolve(args):
    try:
        started_at = _parse_started_at_arg(args.started_at) if args.started_at else None
        identity = resolve_session_id_identity(
            allow_generate=True,
            root_mst_id=args.root_mst_id,
            started_at=started_at,
        )
    except ValueError as exc:
        if args.json and _common.is_session_identity_non_success_error(exc):
            return _common.emit_session_identity_non_success(
                "session resolve",
                error=exc,
                invocation_class="external_invocation",
            )
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session_id = identity["mst_session_id"]
    if args.json:
        from scripts.mst_cmds import execution_flow

        diagnostic = execution_flow.resolve_canonical_mst_session_identity(
            {"mst_session_id": session_id} if identity.get("source") == "payload:mst_session_id" else {},
            {"MST_SESSION_ID": session_id} if identity.get("source") == "env:MST_SESSION_ID" else {},
            invocation_class="external_invocation",
        )
        if identity.get("source") == "generated:root_mst_id":
            diagnostic = execution_flow.resolve_canonical_mst_session_identity(
                {},
                {},
                invocation_class="normal_entry",
                allow_generate=True,
                root_mst_id=args.root_mst_id,
                started_at=started_at,
            )
        print(
            json.dumps(
                {
                    "mst_session_id": session_id,
                    "session_id": session_id,
                    "source": identity.get("source"),
                    "legacy_diagnostics": identity.get("legacy_diagnostics", {}),
                    "valid": diagnostic.get("valid", True),
                    "reason": diagnostic.get("reason", "canonical_identity_resolved"),
                    "action": diagnostic.get("action", "accept_canonical_identity"),
                    "source_precedence": diagnostic.get("source_precedence", _common.canonical_session_source_precedence()),
                    "observed_sources": diagnostic.get("observed_sources", {}),
                    "invocation_class": diagnostic.get("invocation_class", "external_invocation"),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(session_id)
    return 0
def _parse_json_object_argument(raw_value: str | None, *, argument: str) -> dict:
    text = str(raw_value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{argument} must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{argument} must be a JSON object")
    return payload
def cmd_session_merge_scope(args):
    try:
        project_root = (
            Path(args.project_root).expanduser().resolve(strict=False)
            if getattr(args, "project_root", None)
            else _common._project_root()
        )
        evidence = _parse_json_object_argument(getattr(args, "evidence_json", None), argument="--evidence-json")
        payload = resolve_session_merge_scope(
            project_root,
            caller=getattr(args, "caller", None),
            requested_target=getattr(args, "requested_target", None),
            mst_session_id=getattr(args, "mst_session_id", None),
            evidence=evidence,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(payload.get("merge_state") or "")
    return 0 if payload.get("ok") else 2
def _parse_started_at_arg(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("--started-at must not be empty")
    if _STARTED_AT_COMPACT_RE.fullmatch(text):
        return parse_mst_session_started_at_compact(text)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("--started-at must be ISO-8601 UTC or compact UTC milliseconds") from exc
    return parsed
def cmd_session_split_prompts(args):
    if not args.prompts_dir:
        print("Error: directory not found", file=sys.stderr)
        return 1

    prompts_dir = Path(args.prompts_dir)
    if not prompts_dir.exists():
        print("Error: directory not found", file=sys.stderr)
        return 1

    combined_path = prompts_dir / "combined-prompts.txt"
    if not combined_path.exists():
        print("Error: combined-prompts.txt not found", file=sys.stderr)
        return 1

    content = combined_path.read_text(encoding="utf-8")
    marker_re = re.compile(r"^===SPLIT: (.+)===$")
    generated = []
    target_name = None
    target_lines = []

    for raw_line in content.splitlines(keepends=True):
        m = marker_re.match(raw_line.strip())
        if m:
            if target_name is not None:
                out_path = prompts_dir / target_name
                out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
                generated.append(str(out_path))
                print(str(out_path))
            target_name = m.group(1)
            target_lines = []
            continue

        if target_name is not None:
            target_lines.append(raw_line)

    if target_name is not None:
        out_path = prompts_dir / target_name
        out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
        generated.append(str(out_path))
        print(str(out_path))

    return 0
def cmd_session_list(args):
    session_type = args.type
    type_map = {"ideation": ("ideation", "IDN"), "discussion": ("discussion", "DSC"), "debug": ("debug", "DBG")}
    types_to_scan = [type_map[session_type]] if session_type in type_map else list(type_map.values())

    for subdir, prefix in types_to_scan:
        sdir = _common.BASE_DIR / subdir
        if not sdir.exists():
            continue
        for sess in sorted(sdir.glob(f"{prefix}-*")):
            if not sess.is_dir():
                continue
            sj = load_json(sess / "session.json") or {}
            topic = (sj.get("topic") or sj.get("title") or "")[:50]
            print(f"{sess.name:<15} {subdir:<12} {topic}")
    return 0
def cmd_session_ensure_worktree(args):
    project_root = Path(args.project_root).expanduser().resolve(strict=False) if getattr(args, "project_root", None) else Path(_common.BASE_DIR).parent
    mst_session_id = args.mst_session_id or os.environ.get("MST_SESSION_ID", "").strip()
    if not mst_session_id:
        print("Error: missing MST_SESSION_ID for session ensure-worktree.", file=sys.stderr)
        return 1
    try:
        payload = ensure_session_worktree_contract(project_root, mst_session_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload.get("session_worktree_path") or "")
    return 0
def cmd_session_inspect(args):
    raw_session_id = str(args.session_id).strip()
    if raw_session_id.startswith("MST-"):
        try:
            parsed = validate_mst_session_id(raw_session_id)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        sess_path = session_metadata_path(_common.BASE_DIR, parsed.mst_session_id)
        if not sess_path.exists():
            print(f"Error: {parsed.mst_session_id} not found.", file=sys.stderr)
            return 1
        sj = load_json(sess_path)
        if sj:
            print(json.dumps(sj, ensure_ascii=False, indent=2))
        return 0

    sess_id = raw_session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix, "ideation")
    sess_path = _common.BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj:
        print(json.dumps(sj, ensure_ascii=False, indent=2))
    return 0
def cmd_session_complete(args):
    sess_id = args.session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix)
    if subdir is None:
        print(f"Error: Unknown session type '{prefix}'. Expected IDN/DSC/DBG.", file=sys.stderr)
        return 1
    sess_path = _common.BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj is None:
        print(f"Error: session.json not found for {sess_id}.", file=sys.stderr)
        return 1
    if sj.get("status") == "completed":
        print(f"{sess_id} is already completed.")
        return 0
    from scripts._state_manager import complete
    complete(_common.BASE_DIR, sess_id)
    print(f"Completed: {sess_id}")
    return 0
def _current_head_for_flow_view(base_dir: Path, mst_session_id: str, projection: dict) -> dict:
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    current = dict(source)
    head_path = session_history_head_path(base_dir, mst_session_id)
    current_head = _read_history_sidecar_head(head_path)
    if current_head:
        current["history_head"] = current_head
        current["cumulative_hash"] = current_head
    verify_path = session_history_verify_path(base_dir, mst_session_id)
    try:
        verify_raw = verify_path.read_text(encoding="utf-8").strip()
    except OSError:
        verify_raw = ""
    verify_parts = verify_raw.split("\t")
    if len(verify_parts) >= 3 and verify_parts[2].isdigit():
        seq = int(verify_parts[2])
        current["last_event_seq"] = seq
        current["event_count"] = seq
    return current
def cmd_session_flow(args):
    from scripts.mst_cmds import execution_flow

    parsed = validate_mst_session_id(args.mst_session_id)
    projection_path = Path(_common.BASE_DIR) / "sessions" / parsed.mst_session_id / "execution-flow.json"
    projection = load_json(projection_path)
    if not isinstance(projection, dict):
        print(f"Error: execution-flow projection not found: {projection_path}", file=sys.stderr)
        return 1

    current_head = _current_head_for_flow_view(Path(_common.BASE_DIR), parsed.mst_session_id, projection)
    result = execution_flow.render_cli_flow_view(projection, current_head)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(result.get("text") or "")
    return 0 if result.get("status") in {"ok", "stale"} else 2
def register(subparsers):
    sub = subparsers
    sess = sub.add_parser("session")
    sess_sub = sess.add_subparsers(dest="subcommand")

    sess_list = sess_sub.add_parser("list")
    sess_list.add_argument("--type", choices=["ideation", "discussion", "debug"])

    sess_ensure_worktree = sess_sub.add_parser("ensure-worktree")
    sess_ensure_worktree.add_argument("--mst-session-id", dest="mst_session_id")
    sess_ensure_worktree.add_argument("--project-root")
    sess_ensure_worktree.add_argument("--json", action="store_true")

    sess_inspect = sess_sub.add_parser("inspect")
    sess_inspect.add_argument("session_id")

    sess_complete = sess_sub.add_parser("complete")
    sess_complete.add_argument("session_id")

    sess_flow = sess_sub.add_parser("flow")
    sess_flow.add_argument("mst_session_id")
    sess_flow.add_argument("--json", action="store_true")

    sess_merge_scope = sess_sub.add_parser("merge-scope")
    sess_merge_scope.add_argument("--caller", required=True)
    sess_merge_scope.add_argument("--requested-target", dest="requested_target", default="auto")
    sess_merge_scope.add_argument("--mst-session-id", dest="mst_session_id")
    sess_merge_scope.add_argument("--project-root")
    sess_merge_scope.add_argument("--evidence-json")
    sess_merge_scope.add_argument("--json", action="store_true")

    sess_resolve = sess_sub.add_parser("resolve")
    sess_resolve.add_argument("--json", action="store_true")
    sess_resolve.add_argument("--root-mst-id", help="explicit root MST artifact id for new structured session issuance")
    sess_resolve.add_argument("--started-at", help="UTC start time for deterministic structured session issuance")

    sess_split = sess_sub.add_parser("split-prompts", help="combined-prompts.txt를 개별 프롬프트 파일로 분리")
    sess_split.add_argument("--dir", dest="prompts_dir", required=False, help="prompts 디렉토리 경로")
