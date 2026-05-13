def load_verified_history_source(project_root: str | Path, policy_home: str | Path, mst_session_id: str) -> dict[str, Any]:
    from scripts.mst_cmds import hook

    try:
        history = hook._load_validated_history(
            project_root=Path(project_root),
            policy_home=Path(policy_home),
            raw_session_id=mst_session_id,
        )
    except hook.HistoryValidationError as exc:
        return _failure(
            exc.code,
            diagnostics=[_diagnostic(exc.code, field="history", reason=exc.message)],
            current_head_evidence=exc.details,
            trusted_projection_payload=None,
        )

    source = {
        "ledger_path": str(history.history_file),
        "mst_session_id": history.session_id,
        "last_event_id": _row_event(history.rows[-1]).get("event_id") or history.tail_hash,
        "last_event_seq": history.tail_seq,
        "cumulative_hash": history.tail_hash,
        "event_count": history.tail_seq,
        "ledger_schema_version": 1,
        "history_head": history.tail_hash,
    }
    return {
        "schema_version": 1,
        "mst_session_id": history.session_id,
        "root_mst_id": history.root_mst_id,
        "ledger_path": str(history.history_file),
        "verified": True,
        "source": source,
        "rows": history.rows,
    }
