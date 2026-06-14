def cmd_state_recover(args):
    from scripts._skill_state import (
        load_snapshot,
        recover_agile_snapshot_from_durable_state,
    )
    from scripts.mst_cmds import session as session_mod

    strict_rehydration = getattr(args, "command", "") == "recover"
    try:
        agi_id = _normalize_agi_id_for_recover(args.agi_id)
    except ValueError as exc:
        return _emit_recover_non_success(_recover_non_success("invalid_root_mst_id", str(exc)))

    session_id, source_error = _read_canonical_recover_session_id()
    if source_error is not None:
        return _emit_recover_non_success(source_error)
    assert session_id is not None
    legacy_conflict = _structured_legacy_alias_conflict(session_id)
    if legacy_conflict is not None:
        return _emit_recover_non_success(legacy_conflict)

    try:
        parsed = session_mod.validate_mst_session_metadata_consistency(
            _common.BASE_DIR,
            session_id,
            require_root_metadata=True,
            require_session_metadata=True,
        )
    except ValueError as exc:
        message = str(exc)
        if "root mst_session_id metadata mismatch" in message:
            root_payload = _load_json_object(_agile_session_path(agi_id))
            payload_session_id = root_payload.get("mst_session_id") if isinstance(root_payload, dict) else None
            if isinstance(payload_session_id, str) and payload_session_id.strip():
                message = f"mst_session_id mismatch: env={session_id} payload={payload_session_id.strip()}"
        if not strict_rehydration and "mst_session_id mismatch" not in message:
            message = f"mst_session_id mismatch: {message}"
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                message,
                session_id=session_id,
            )
        )
    if parsed.root_mst_id != agi_id:
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                f"recover root mismatch: arg={agi_id} session={parsed.root_mst_id}",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )

    session_path = _agile_session_path(agi_id)
    session_payload = _load_json_object(session_path)
    if session_payload is None:
        return _emit_recover_non_success(
            _recover_non_success(
                "missing_root_metadata",
                f"durable root session not found: {session_path}",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )
    payload_session_id = session_payload.get("mst_session_id")
    if not isinstance(payload_session_id, str) or not payload_session_id.strip():
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                "missing mst_session_id in durable session",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )
    if payload_session_id.strip() != session_id:
        return _emit_recover_non_success(
            _recover_non_success(
                "state_history_linkage_mismatch",
                f"mst_session_id mismatch: env={session_id} payload={payload_session_id.strip()}",
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )

    previous_owner = session_payload.get("owner_session_id")
    previous_owner = previous_owner.strip() if isinstance(previous_owner, str) and previous_owner.strip() else None
    if previous_owner and previous_owner != session_id:
        print(
            f"[cross-session recover] diagnostic: owner_session_id ignored: "
            f"previous={previous_owner} current={session_id}",
            file=sys.stderr,
        )

    state_base_dir = _skill_state_base_dir()
    history_result, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    if history_error is not None:
        return _emit_recover_non_success(history_error)
    assert history_result is not None

    existing = load_snapshot(state_base_dir, session_id=session_id)
    if existing is None:
        existing = recover_agile_snapshot_from_durable_state(
            state_base_dir,
            agi_id,
            session_id=session_id,
        )
        if existing is not None:
            _update_snapshot_history_head(
                state_base_dir,
                session_id,
                existing,
                history_result.tail_hash,
                history_result.tail_hash,
            )
            existing = load_snapshot(state_base_dir, session_id=session_id)
    else:
        snapshot_error = _validate_recover_snapshot(existing, session_id, parsed.root_mst_id, history_result)
        if snapshot_error is not None and (strict_rehydration or snapshot_error.get("code") != "missing_history_linkage"):
            return _emit_recover_non_success(snapshot_error)
    context_contract_error = _recover_context_contract_failure(
        session_id=session_id,
        root_mst_id=parsed.root_mst_id,
        history_result=history_result,
        snapshot=existing,
    )
    if context_contract_error is not None:
        return _emit_recover_non_success(context_contract_error)

    if previous_owner and previous_owner != session_id and getattr(args, "takeover", False):
        def _mutate_owner(payload: dict) -> dict:
            payload["owner_session_id"] = session_id
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            return payload

        try:
            _check_takeover_storm(agi_id)
            _with_locked_json_update(session_path, _mutate_owner)
        except TakeoverStormError as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_blocked", str(exc), session_id=session_id, root_mst_id=parsed.root_mst_id)
            )
        except TimeoutError as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_failed", str(exc), session_id=session_id, root_mst_id=parsed.root_mst_id)
            )
        except Exception as exc:
            return _emit_recover_non_success(
                _recover_non_success("recover_takeover_failed", f"failed to takeover owner: {exc}", session_id=session_id, root_mst_id=parsed.root_mst_id)
            )

    _append_cross_session_recover_event(
        session_id,
        agi_id,
        previous_owner,
        takeover=bool(getattr(args, "takeover", False)),
    )

    previous_history_head = history_result.tail_hash
    recovery_fingerprint = _recovery_fingerprint(agi_id, session_id)
    try:
        _append_recover_history_event(
            _common.BASE_DIR,
            session_id,
            agi_id,
            recovery_fingerprint,
            previous_history_head=previous_history_head,
            snapshot=existing,
        )
        _append_context_rehydrated_history_event(
            _common.BASE_DIR,
            session_id,
            recovery_fingerprint,
            previous_history_head=previous_history_head,
            snapshot=existing,
        )
        updated_history, history_error = _load_recover_history(_common.BASE_DIR, session_id)
    except Exception as exc:
        return _emit_recover_non_success(
            _recover_non_success(
                "recover_history_append_failed",
                str(exc),
                session_id=session_id,
                root_mst_id=parsed.root_mst_id,
            )
        )
    if history_error is not None:
        return _emit_recover_non_success(history_error)
    assert updated_history is not None

    _update_snapshot_history_head(state_base_dir, session_id, existing, previous_history_head, updated_history.tail_hash)
    envelope = _recover_rehydration_bundle(
        session_id=session_id,
        root_mst_id=parsed.root_mst_id,
        snapshot=existing,
        root_payload=session_payload,
        history_result=updated_history,
        previous_history_head=previous_history_head,
        recovery_fingerprint=recovery_fingerprint,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "core_rehydration": envelope,
                "context_delivery_order": envelope.get("context_delivery_order"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
def cmd_state_mark_paused(args):
    from scripts._skill_state import mark_paused

    session_id, error = _require_args_session_matches_env(args.session_id)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    state_base_dir = _skill_state_base_dir()
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    data = mark_paused(state_base_dir, session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0
def cmd_state_resume_paused(args):
    from scripts._skill_state import resume_paused

    session_id, error = _require_args_session_matches_env(args.session_id)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    state_base_dir = _skill_state_base_dir()
    valid_snapshot, validation_error = _validate_existing_snapshot_for_write(state_base_dir, session_id)
    if not valid_snapshot:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 1
    data = resume_paused(state_base_dir, session_id=session_id)
    if data is None:
        print("스냅샷 없음")
        return 0
    data = _write_canonical_snapshot_payload(state_base_dir, session_id, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0
def cmd_state_paused_count(args):
    from scripts._skill_state import paused_count

    print(paused_count(_skill_state_base_dir(), session_id=args.session_id))
    return 0
def register(subparsers):
    sub = subparsers
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="subcommand")

    state_set = state_sub.add_parser("set")
    state_set.add_argument("--skill", required=True)
    state_set.add_argument("--step", type=int, required=True)
    state_set.add_argument("--total", type=int, required=True)
    state_set.add_argument("--return-to", dest="return_to")

    state_set_workflow = state_sub.add_parser("set-workflow")
    state_set_workflow.add_argument("--active", type=_parse_bool_arg, required=True)
    state_set_workflow.add_argument("--skill", default="")
    state_set_workflow.add_argument("--req", default="")
    state_set_workflow.add_argument("--next-skill", dest="next_skill", default="")
    state_set_workflow.add_argument("--next-source", dest="next_source", default="")
    state_set_workflow.add_argument("--source-skill", dest="source_skill", default="")
    state_set_workflow.add_argument("--auto", type=_parse_bool_arg, default=False)
    state_set_workflow.add_argument("--enqueue", type=_parse_bool_arg, default=False)
    state_set_workflow.add_argument("--agile-loop-active", dest="agile_loop_active", type=_parse_bool_arg)
    state_set_workflow.add_argument("--steering-disabled", dest="steering_disabled", type=_parse_bool_arg)
    state_set_workflow.add_argument("--awaiting-user-input", dest="awaiting_user_input", type=_parse_bool_arg)
    state_set_workflow.add_argument("--question-id", dest="question_id", default="")
    state_set_workflow.add_argument("--expected-question-hash", dest="expected_question_hash", default="")
    state_set_workflow.add_argument("--resume-skill", dest="resume_skill", default="")
    state_set_workflow.add_argument("--resume-args", dest="resume_args", default="")
    state_set_workflow.add_argument("--root-mst-id", dest="root_mst_id", default="")

    state_sub.add_parser("get")
    state_sub.add_parser("clear")

    state_migrate = state_sub.add_parser("migrate")
    mode_group = state_migrate.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true")
    mode_group.add_argument("--verify", action="store_true")
    mode_group.add_argument("--rollback", action="store_true")
    state_migrate.set_defaults(func=migrate)

    state_recover = state_sub.add_parser("recover")
    state_recover.add_argument("agi_id")
    state_recover.add_argument("--takeover", action="store_true")

    state_mark_paused = state_sub.add_parser("mark-paused")
    state_mark_paused.add_argument("--session-id", required=True)

    state_resume_paused = state_sub.add_parser("resume-paused")
    state_resume_paused.add_argument("--session-id", required=True)

    state_paused_count = state_sub.add_parser("paused-count")
    state_paused_count.add_argument("--session-id", required=True)
    register_state_validate(state_sub)

    recover = sub.add_parser("recover")
    recover.add_argument("agi_id")
    recover.add_argument("--takeover", action="store_true")
