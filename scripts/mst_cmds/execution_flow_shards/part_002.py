def validate_compaction_handoff_consumption(
    handoff: dict[str, Any],
    current_head: dict[str, Any],
) -> dict[str, Any]:
    current = validate_source_ledger_head(current_head)
    if current.get("status") != "ok":
        payload = dict(current)
        payload.update(
            {
                "write_allowed": False,
                "auto_write_allowed": False,
                "next_action_execution_allowed": False,
                "trusted_handoff_payload": None,
            }
        )
        return payload
    if not isinstance(handoff, dict):
        return _failure(
            "handoff_invalid",
            diagnostics=[_diagnostic("handoff_invalid", field="handoff", reason="handoff must be a JSON object")],
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            trusted_handoff_payload=None,
        )

    required = [
        "mst_session_id",
        "root_mst_id",
        "history_head",
        "current_node",
        "last_transition",
        "next_action",
        "flow_view",
    ]
    missing = [field for field in required if handoff.get(field) in (None, "", {})]
    flow_view = _handoff_flow_view(handoff)
    for field in ("execution_flow_json", "execution_flow_d2"):
        if flow_view.get(field) in (None, ""):
            missing.append(f"flow_view.{field}")
    if missing:
        return _failure(
            "handoff_required_field_missing",
            diagnostics=[
                _diagnostic(
                    "handoff_required_field_missing",
                    field=field,
                    reason="handoff is missing required cursor/provenance field",
                )
                for field in missing
            ],
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            trusted_handoff_payload=None,
        )

    mismatches = []
    comparisons = {
        "mst_session_id": current_head.get("mst_session_id"),
        "history_head": current_head.get("history_head"),
    }
    for field, expected in comparisons.items():
        if handoff.get(field) != expected:
            mismatches.append(
                _diagnostic(
                    "stale_handoff",
                    field=field,
                    reason="compaction handoff provenance does not match current verified ledger head",
                    expected=expected,
                    actual=handoff.get(field),
                )
            )
    if mismatches:
        return _failure(
            "stale_handoff",
            diagnostics=mismatches,
            status="stale",
            stale=True,
            read_only=True,
            regenerate_required=True,
            source_history_head=handoff.get("history_head"),
            current_history_head=current_head.get("history_head"),
            write_allowed=False,
            auto_write_allowed=False,
            next_action_execution_allowed=False,
            on_stale_transition="guard.inspect_only_verification",
            next_safe_action="inspect-only state/history consistency verification",
            mismatch_subject="compaction_handoff.history_head",
            trusted_handoff_payload=None,
        )

    critical_blocker = handoff.get("critical_blocker")
    blocker_present = isinstance(critical_blocker, dict) and bool(critical_blocker)
    return _ok(
        stale=False,
        read_only=False,
        regenerate_required=False,
        source_history_head=handoff.get("history_head"),
        current_history_head=current_head.get("history_head"),
        write_allowed=not blocker_present,
        auto_write_allowed=not blocker_present and bool(handoff.get("auto")),
        next_action_execution_allowed=not blocker_present,
        trusted_handoff_payload=_handoff_cursor_payload(handoff),
        prompt_summary_used_as_source=False,
    )
def assemble_rehydration_continuation_context(
    core_rehydration: dict[str, Any],
    verified_handoff: dict[str, Any],
    prompt_summary: dict[str, Any] | None,
    current_head: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_compaction_handoff_consumption(verified_handoff, current_head)
    if validation.get("status") != "ok":
        payload = dict(validation)
        payload["context_delivery_order"] = ["core_rehydration", "execution_flow_handoff", "prompt_summary"]
        payload["write_allowed"] = False
        payload["next_action_execution_allowed"] = False
        return payload

    handoff = validation["trusted_handoff_payload"]
    core = dict(core_rehydration) if isinstance(core_rehydration, dict) else {}
    budgeted_context = {
        "execution_flow_handoff": handoff,
        "prompt_summary": prompt_summary if isinstance(prompt_summary, dict) else {},
        "omissions": [
            "full execution-flow nodes omitted; use flow_view.execution_flow_json for details",
            "full execution-flow D2 omitted; use flow_view.execution_flow_d2 for details",
        ],
    }
    return _ok(
        schema_version=1,
        core_rehydration=core,
        budgeted_context=budgeted_context,
        context_delivery_order=["core_rehydration", "execution_flow_handoff", "prompt_summary"],
        source_precedence=[
            "verified_history_ledger",
            "verified_execution_flow_handoff",
            "prompt_summary_diagnostic_only",
        ],
        prompt_summary_used_as_source=False,
        write_allowed=validation.get("write_allowed") is True,
        auto_write_allowed=validation.get("auto_write_allowed") is True,
        next_action_execution_allowed=validation.get("next_action_execution_allowed") is True,
        continuation={
            "mode": "continue_unless_critical",
            "next_action": handoff.get("next_action"),
            "last_transition": handoff.get("rehydration_transition") or "continue.rehydrate_retry",
            "critical_blocker": handoff.get("critical_blocker"),
        },
    )
def _append_ledger_row(rows: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any]:
    prev_hash = rows[-1].get("event_hash") if rows else ZERO_HASH
    seq = len(rows) + 1
    event_hash = _event_hash(str(prev_hash), event)
    row = {
        "schema_version": 1,
        "seq": seq,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "mst_session_id": event.get("mst_session_id"),
        "root_mst_id": event.get("root_mst_id"),
        "event_type": event.get("event_type"),
        "created_at": event.get("created_at"),
        "idempotency_key": event.get("idempotency_key"),
        "event": event,
    }
    rows.append(row)
    return row
def append_context_handoff_evidence_events(
    ledger: dict[str, Any],
    handoff: dict[str, Any],
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return _failure("ledger_invalid", diagnostics=[_diagnostic("ledger_invalid", field="ledger", reason="ledger must be a JSON object")])
    if ledger.get("verified") is not True:
        return _failure(
            "ledger_not_verified",
            diagnostics=[_diagnostic("ledger_not_verified", field="verified", reason="history ledger must be verified before context event append")],
        )
    source = _source_from_ledger(ledger)
    head_result = validate_source_ledger_head(source)
    if head_result.get("status") != "ok":
        return head_result
    consumption = validate_compaction_handoff_consumption(handoff, source)
    if consumption.get("status") != "ok":
        return consumption

    session_id = str(source["mst_session_id"])
    root_mst_id = str(ledger.get("root_mst_id") or handoff.get("root_mst_id") or "")
    timestamp = created_at or _iso_utc_now()
    updated = dict(ledger)
    rows = [dict(row) for row in _ledger_rows(ledger)]
    handoff_payload = consumption["trusted_handoff_payload"]
    compacted_event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(f"{session_id}:context.compacted:{source['history_head']}".encode("utf-8")).hexdigest()[:24],
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "event_type": "context.compacted",
        "type": "context.compacted",
        "created_at": timestamp,
        "idempotency_key": f"{session_id}:context.compacted:{source['history_head']}",
        "history_head": source["history_head"],
        "execution_flow_handoff": handoff_payload,
        "handoff_generation_evidence": {
            "source": "verified_execution_flow_projection",
            "history_head": source["history_head"],
            "flow_view": handoff_payload.get("flow_view"),
        },
    }
    compacted_row = _append_ledger_row(rows, compacted_event)
    rehydrated_event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(f"{session_id}:context.rehydrated:{compacted_row['event_hash']}".encode("utf-8")).hexdigest()[:24],
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "event_type": "context.rehydrated",
        "type": "context.rehydrated",
        "created_at": timestamp,
        "idempotency_key": f"{session_id}:context.rehydrated:{compacted_row['event_hash']}",
        "history_head": compacted_row["event_hash"],
        "execution_flow_handoff": handoff_payload,
        "handoff_consumption_evidence": {
            "source": "verified_execution_flow_handoff",
            "handoff_history_head": handoff_payload.get("history_head"),
            "prompt_summary_used_as_source": False,
        },
        "prompt_summary_used_as_source": False,
        "rehydration_transition": handoff_payload.get("rehydration_transition") or "continue.rehydrate_retry",
        "next_action": handoff_payload.get("next_action"),
    }
    rehydrated_row = _append_ledger_row(rows, rehydrated_event)
    new_source = dict(source)
    new_source.update(
        {
            "last_event_id": rehydrated_event["event_id"],
            "last_event_seq": len(rows),
            "cumulative_hash": rehydrated_row["event_hash"],
            "event_count": len(rows),
            "history_head": rehydrated_row["event_hash"],
        }
    )
    updated["source"] = new_source
    updated["rows"] = rows
    updated["verified"] = True
    return _ok(
        ledger=updated,
        mst_session_id=session_id,
        root_mst_id=root_mst_id,
        same_session_ledger=True,
        history_head=rehydrated_row["event_hash"],
        event_append_evidence={
            "compacted": "context.compacted",
            "rehydrated": "context.rehydrated",
            "handoff_generated": True,
            "handoff_consumed": True,
        },
    )
def validate_gran_maestro_owned_handoff_scope(changed_paths: Iterable[str]) -> dict[str, Any]:
    allowed_prefixes = (
        "scripts/",
        "hooks/",
        "skills/",
        "dashboard/",
        "tests/",
        "docs/",
        "frontend/",
        "templates/",
        "src/",
        ".gran-maestro/",
    )
    forbidden: list[str] = []
    for raw_path in changed_paths:
        path = str(raw_path)
        normalized = path.replace("\\", "/")
        if "/claude-code/" in normalized or normalized.startswith("claude-code/"):
            forbidden.append(path)
            continue
        relative = normalized.lstrip("/")
        if relative.startswith(allowed_prefixes):
            continue
        parts = normalized.split("/gran-maestro/", 1)
        if len(parts) == 2 and parts[1].startswith(allowed_prefixes):
            continue
    if forbidden:
        return _failure(
            "claude_code_core_scope_violation",
            diagnostics=[
                _diagnostic(
                    "claude_code_core_scope_violation",
                    field="changed_paths",
                    reason="DOD-017 handoff wiring must not modify Claude Code core source",
                    path=path,
                )
                for path in forbidden
            ],
            claude_code_core_modified=True,
            allowed_surface="gran_maestro_owned",
            changed_paths=list(changed_paths),
        )
    return _ok(
        claude_code_core_modified=False,
        allowed_surface="gran_maestro_owned",
        changed_paths=list(changed_paths),
    )
def _coverage_summary(projection: dict[str, Any]) -> dict[str, Any]:
    coverage = projection.get("coverage") if isinstance(projection.get("coverage"), dict) else {}
    recognized = coverage.get("recognized_event_families")
    missing = coverage.get("missing_event_families")
    required = coverage.get("required_event_families")
    nodes = projection.get("nodes") if isinstance(projection.get("nodes"), list) else []
    edges = projection.get("edges") if isinstance(projection.get("edges"), list) else []
    return {
        "recognized_event_families": list(recognized) if isinstance(recognized, list) else [],
        "missing_event_families": list(missing) if isinstance(missing, list) else [],
        "required_event_families": list(required) if isinstance(required, list) else sorted(REQUIRED_EVENT_FAMILIES),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
def _projection_display_status(projection: dict[str, Any], current_head: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validation = validate_projection_consumption(projection, current_head, consumers=DECISION_CONSUMERS)
    stale = validation.get("stale") is True
    status = {
        "stale": stale,
        "drift": stale,
        "regenerate_required": validation.get("regenerate_required") is True,
        "read_only": validation.get("read_only") is True,
        "source_history_head": validation.get("source_history_head"),
        "current_history_head": validation.get("current_history_head"),
        "on_stale_transition": validation.get("on_stale_transition"),
    }
    return validation, status
def build_dashboard_flow_view(projection: dict[str, Any], current_head: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    validation, projection_status = _projection_display_status(projection, current_head)
    coverage = _coverage_summary(projection)
    status = "ok" if validation.get("status") in {"ok", "stale"} else validation.get("status", "validation_failed")
    return {
        "status": status,
        "accepted": validation.get("status") in {"ok", "stale"},
        "fail_closed": validation.get("status") not in {"ok", "stale"},
        "view_kind": "dod017.execution-flow.dashboard-view",
        "schema_version": 1,
        "projection_kind": projection.get("projection_kind") or PROJECTION_KIND,
        "mst_session_id": projection.get("mst_session_id"),
        "root_mst_id": projection.get("root_mst_id"),
        "source": {
            "source_kind": source.get("source_kind") or SOURCE_KIND,
            "ledger_path": source.get("ledger_path"),
            "history_head": source.get("history_head"),
            "source_hash": source.get("source_hash") or source.get("cumulative_hash"),
            "projection_schema_version": projection.get("projection_schema_version"),
            "projection_hash": projection.get("projection_hash"),
            "projection_created_at": projection.get("projection_created_at") or source.get("projection_created_at"),
        },
        "projection_status": projection_status,
        "coverage": coverage,
        "current_node": projection.get("current_node"),
        "last_transition": projection.get("last_transition"),
        "next_action": projection.get("next_action"),
        "blocker": projection.get("blocker"),
        "views": projection.get("views") if isinstance(projection.get("views"), dict) else {},
        "display_only": True,
        "derived_artifact": True,
        "next_action_authority": False,
        "transition_authority": "dod016_transition_graph",
        "decision_sources": [SOURCE_KIND, "dod016_transition_graph"],
        "consumer_permissions": validation.get("consumer_permissions", {}),
        "diagnostics": validation.get("diagnostics", []),
    }
def render_cli_flow_view(projection: dict[str, Any], current_head: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )
    validation, projection_status = _projection_display_status(projection, current_head)
    source = projection.get("source") if isinstance(projection.get("source"), dict) else {}
    stale = projection_status["stale"]
    state = "stale/read-only/regenerate-required" if stale else "fresh/display-only"
    text = "\n".join(
        [
            "DOD-017 actual execution-flow (display-only)",
            f"session: {projection.get('mst_session_id')}",
            f"source ledger: {source.get('ledger_path')}",
            f"projection history_head: {source.get('history_head')}",
            f"current history_head: {current_head.get('history_head') if isinstance(current_head, dict) else None}",
            f"projection_hash: {projection.get('projection_hash')}",
            f"status: {state}",
            f"read-only: {str(projection_status['read_only']).lower()}",
            f"regenerate-required: {str(projection_status['regenerate_required']).lower()}",
            "authority: DOD-016 transition graph + verified ledger only; this projection is not next-action authority",
        ]
    )
    payload = dict(validation)
    payload.update(
        {
            "view_kind": "dod017.execution-flow.cli-view",
            "display_only": True,
            "derived_artifact": True,
            "mst_session_id": projection.get("mst_session_id"),
            "root_mst_id": projection.get("root_mst_id"),
            "next_action_authority": False,
            "transition_authority": "dod016_transition_graph",
            "read_only": projection_status["read_only"],
            "regenerate_required": projection_status["regenerate_required"],
            "stale": projection_status["stale"],
            "drift": projection_status["drift"],
            "text": text,
        }
    )
    return payload
def separate_graph_and_execution_flow_views(
    graph_view: dict[str, Any],
    execution_flow_projection: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(graph_view, dict):
        return _failure(
            "graph_view_invalid",
            diagnostics=[_diagnostic("graph_view_invalid", field="graph_view", reason="graph view must be a JSON object")],
        )
    if not isinstance(execution_flow_projection, dict):
        return _failure(
            "projection_invalid",
            diagnostics=[_diagnostic("projection_invalid", field="projection", reason="projection must be a JSON object")],
        )

    graph_source = graph_view.get("source_graph") if isinstance(graph_view.get("source_graph"), dict) else {}
    flow_source = (
        execution_flow_projection.get("source")
        if isinstance(execution_flow_projection.get("source"), dict)
        else {}
    )
    possible = {
        "label": "DOD-016 possible-transition graph",
        "schema_id": graph_view.get("kind") or "mst-transition-graph-view",
        "artifact_kind": "possible-transition graph",
        "source_of_truth": "dod016_transition_graph",
        "source_provenance": {
            "graph_id": graph_source.get("id"),
            "graph_version": graph_source.get("version"),
            "graph_hash": graph_source.get("hash"),
            "source_graph_path": graph_view.get("source_graph_path"),
        },
        "coverage": {
            "covered_states": list(graph_view.get("covered_states") or []),
            "covered_transitions": list(graph_view.get("covered_transitions") or []),
        },
        "transition_authority": True,
    }
    actual = {
        "label": "DOD-017 actual execution-flow",
        "schema_id": execution_flow_projection.get("projection_kind") or PROJECTION_KIND,
        "artifact_kind": "actual execution-flow",
        "source_of_truth": SOURCE_KIND,
        "source_provenance": {
            "ledger_path": flow_source.get("ledger_path"),
            "history_head": flow_source.get("history_head"),
            "source_hash": flow_source.get("source_hash") or flow_source.get("cumulative_hash"),
            "projection_hash": execution_flow_projection.get("projection_hash"),
            "projection_schema_version": execution_flow_projection.get("projection_schema_version"),
        },
        "coverage": _coverage_summary(execution_flow_projection),
        "display_only": True,
        "next_action_authority": False,
    }
    return _ok(
        separated=True,
        possible_transition_graph=possible,
        actual_execution_flow=actual,
        transition_authority="dod016_transition_graph",
        display_context="dod017.execution-flow",
    )
def validate_execution_flow_source_boundary(envelope: dict[str, Any]) -> dict[str, Any]:
    ledger = envelope.get("verified_history_ledger") if isinstance(envelope, dict) else None
    graph = envelope.get("dod016_transition_graph") if isinstance(envelope, dict) else None
    if not isinstance(ledger, dict):
        return _failure(
            "verified_history_ledger_missing",
            diagnostics=[
                _diagnostic(
                    "verified_history_ledger_missing",
                    field="verified_history_ledger",
                    reason="actual execution-flow source must be the verified history ledger",
                )
            ],
        )
    if not isinstance(graph, dict):
        return _failure(
            "dod016_transition_graph_missing",
            diagnostics=[
                _diagnostic(
                    "dod016_transition_graph_missing",
                    field="dod016_transition_graph",
                    reason="transition authority must be the DOD-016 graph",
                )
            ],
        )
    return _ok(
        source_of_truth={
            "actual_execution_flow": SOURCE_KIND,
            "transition_authority": "dod016_transition_graph",
        },
        generated_artifacts_used_for_decision=False,
        decision_sources=[SOURCE_KIND, "dod016_transition_graph"],
        rejected_sources=[
            "execution-flow.json",
            "execution-flow.d2",
            "dashboard/CLI view",
            "compaction handoff summary",
            "snapshot/cache/prompt summary",
        ],
        artifact_roles={
            "execution_flow_json": "derived_only",
            "execution_flow_d2": "display_only",
            "dashboard_cli_view": "display_only",
            "compaction_handoff_summary": "derived_only",
            "snapshot_cache": "auxiliary_only",
            "prompt_summary": "auxiliary_only",
        },
        decision_consumers=list(envelope.get("decision_consumers") or []),
    )
def evaluate_projection_transition_authority(
    attempt: dict[str, Any],
    projection: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    from scripts.mst_cmds import transition_graph

    graph_result = transition_graph.validate_attempted_transition(dict(attempt), graph)
    transition_id = attempt.get("attempted_transition")
    transition = graph.get("transitions", {}).get(transition_id) if isinstance(graph.get("transitions"), dict) else None
    if graph_result.get("accepted") is not True:
        return _failure(
            "transition_graph_rejected",
            diagnostics=[
                _diagnostic(
                    "transition_graph_rejected",
                    field="attempted_transition",
                    reason="DOD-016 transition graph rejected the attempted transition",
                    attempted_transition=transition_id,
                )
            ],
            attempted_transition=transition_id,
            authority="dod016_transition_graph",
            projection_authorized=False,
            projection_used_as_authority=False,
            on_reject=transition.get("on_reject") if isinstance(transition, dict) else graph_result.get("on_reject"),
            graph_result=graph_result,
            trusted_projection_payload=None,
        )
    return _ok(
        attempted_transition=transition_id,
        authority="dod016_transition_graph",
        projection_authorized=False,
        projection_used_as_authority=False,
        graph_result=graph_result,
        projection_observed=projection,
    )
def evaluate_hook_hot_path(envelope: dict[str, Any], *, operations: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = envelope if isinstance(envelope, dict) else {}
    cursor = payload.get("cursor_state") if isinstance(payload.get("cursor_state"), dict) else None
    cache = payload.get("cache_state") if isinstance(payload.get("cache_state"), dict) else None
    current_head = payload.get("current_head_evidence") if isinstance(payload.get("current_head_evidence"), dict) else {}
    queued_action = payload.get("queued_action") if isinstance(payload.get("queued_action"), dict) else None
    no_full_work = {
        "hot_path_full_ledger_replay": False,
        "hot_path_execution_flow_projection": False,
        "hot_path_d2_rendering": False,
        "hot_path_dashboard_rendering": False,
    }

    head_result = validate_source_ledger_head(current_head)
    if head_result.get("status") != "ok":
        return dict(head_result) | no_full_work | {
            "status": "validation_failed",
            "accepted": False,
            "fail_closed": True,
            "write_allowed": False,
            "next_route": "terminal.state_inconsistency",
            "next_safe_action": "inspect-only state/history consistency verification",
            "mismatch_subject": "current_head_evidence",
            "mst_session_id": payload.get("mst_session_id"),
            "current_history_head": current_head.get("history_head"),
            "queued_action": queued_action,
        }

    current_history_head = current_head.get("history_head")
    current_cumulative_hash = current_head.get("cumulative_hash")
    current_session_id = current_head.get("mst_session_id")
    valid_statuses = {"ok", "fresh", "hit", "valid", "current"}
    stale_statuses = {"stale", "miss", "missing", "invalid", "mismatch", "expired"}

    diagnostics: list[dict[str, Any]] = []

    def state_status(state: dict[str, Any] | None) -> str:
        if state is None:
            return "missing"
        return str(state.get("status") or "").strip().lower() or "missing"

    def state_history_head(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("history_head") or state.get("current_history_head") or source.get("history_head") or provenance.get("history_head")

    def state_cumulative_hash(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("cumulative_hash") or state.get("source_hash") or source.get("cumulative_hash") or source.get("source_hash") or provenance.get("cumulative_hash")

    def state_session_id(state: dict[str, Any] | None) -> Any:
        if not isinstance(state, dict):
            return None
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        return state.get("mst_session_id") or source.get("mst_session_id") or provenance.get("mst_session_id")

    def provenance_for(state: dict[str, Any] | None, default_source: str) -> dict[str, Any]:
        if not isinstance(state, dict):
            return {"source": default_source, "status": "missing"}
        provenance = state.get("provenance") if isinstance(state.get("provenance"), dict) else {}
        merged = dict(provenance)
        merged.setdefault("source", state.get("source_name") or state.get("source_kind") or default_source)
        merged.setdefault("status", state_status(state))
        merged.setdefault("history_head", state_history_head(state))
        return {key: value for key, value in merged.items() if value not in (None, "")}

    def validate_current_state(name: str, state: dict[str, Any] | None) -> None:
        status_value = state_status(state)
        if status_value not in valid_statuses:
            code = "hook_current_state_cache_missing" if status_value in stale_statuses else "hook_current_state_cache_invalid"
            diagnostics.append(
                _diagnostic(
                    code,
                    field=name,
                    reason="hook hot path requires fresh precomputed current-state cursor/cache",
                    actual=status_value,
                    expected=sorted(valid_statuses),
                )
            )
            return
        state_head = state_history_head(state)
        if state_head != current_history_head:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_stale",
                    field=f"{name}.history_head",
                    reason="hook current-state cursor/cache history_head does not match current ledger head evidence",
                    expected=current_history_head,
                    actual=state_head,
                )
            )
        state_hash = state_cumulative_hash(state)
        if state_hash is not None and state_hash != current_cumulative_hash:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_stale",
                    field=f"{name}.cumulative_hash",
                    reason="hook current-state cursor/cache cumulative_hash does not match current ledger head evidence",
                    expected=current_cumulative_hash,
                    actual=state_hash,
                )
            )
        state_sid = state_session_id(state)
        if state_sid is not None and state_sid != current_session_id:
            diagnostics.append(
                _diagnostic(
                    "hook_current_state_cache_mismatch",
                    field=f"{name}.mst_session_id",
                    reason="hook current-state cursor/cache belongs to a different MST session",
                    expected=current_session_id,
                    actual=state_sid,
                )
            )

    validate_current_state("cursor_state", cursor)
    validate_current_state("cache_state", cache)
    if diagnostics:
        first_field = str(diagnostics[0].get("field") or "hook_current_state_cache")
        return _failure(
            diagnostics[0]["code"],
            diagnostics=diagnostics,
            status="inspect_only",
            **no_full_work,
            mst_session_id=payload.get("mst_session_id") or current_session_id,
            current_history_head=current_history_head,
            history_head=current_history_head,
            current_head_evidence=current_head,
            write_allowed=False,
            next_route="guard.inspect_only_verification",
            on_stale_transition="guard.inspect_only_verification",
            next_safe_action="inspect-only state/history consistency verification",
            mismatch_subject=first_field.split(".", 1)[0],
            queued_action=queued_action,
            trusted_cursor_state=None,
        )

    source_state = cursor if isinstance(cursor, dict) else cache
    cache_state = cache if isinstance(cache, dict) else cursor
    next_action = source_state.get("next_action") if isinstance(source_state.get("next_action"), dict) else None
    return _ok(
        **no_full_work,
        mst_session_id=payload.get("mst_session_id") or current_session_id,
        current_history_head=current_history_head,
        history_head=current_history_head,
        current_head_evidence=current_head,
        current_node=source_state.get("current_node"),
        last_transition=source_state.get("last_transition"),
        next_action=next_action or queued_action,
        queued_action=queued_action,
        write_allowed=True,
        next_route="continue.queued_action" if queued_action else None,
        hot_path_current_state_source="cursor_state" if isinstance(cursor, dict) else "cache_state",
        provenance={
            "cursor_state": provenance_for(cursor, "cursor_state"),
            "cache_state": provenance_for(cache_state, "cache_state"),
        },
        trusted_cursor_state={
            "cursor_state": cursor,
            "cache_state": cache,
        },
    )
def validate_source_ledger_for_projection(ledger: dict[str, Any], projection_source: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return _failure("ledger_invalid", diagnostics=[_diagnostic("ledger_invalid", field="ledger", reason="ledger must be a JSON object")])
    if ledger.get("verified") is not True:
        return _failure(
            "ledger_not_verified",
            diagnostics=[_diagnostic("ledger_not_verified", field="verified", reason="history ledger must be verified before projection source validation")],
            trusted_projection_payload=None,
        )
    current_head = _source_from_ledger(ledger)
    head_result = validate_source_ledger_head(current_head)
    if head_result.get("status") != "ok":
        return head_result | {"trusted_projection_payload": None}
    row_diagnostics = _validate_rows_against_source(ledger, current_head)
    if row_diagnostics:
        return _failure(
            row_diagnostics[0]["code"],
            diagnostics=row_diagnostics,
            ledger_path=current_head.get("ledger_path"),
            mst_session_id=current_head.get("mst_session_id"),
            current_head_evidence=current_head,
            trusted_projection_payload=None,
        )
    if projection_source is None:
        return validate_source_ledger_head(current_head)
    return validate_projection_consumption({"source": projection_source}, current_head, consumers=DECISION_CONSUMERS)
def validate_source_ledger_projection_source(
    ledger: dict[str, Any],
    projection_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_source_ledger_for_projection(ledger, projection_source)
def _identity_observed_source(value: object, *, validate: bool = True) -> dict[str, Any]:
    text = value.strip() if isinstance(value, str) else ""
    observed = {
        "present": bool(text),
        "value": text or None,
        "valid": False,
    }
    if not text:
        return observed
    if not validate:
        observed["valid"] = True
        return observed
    try:
        observed["canonical_value"] = session_cmds.validate_mst_session_id(text).mst_session_id
        observed["valid"] = True
    except Exception as exc:
        observed["error"] = str(exc)
    return observed
def _snapshot_path_session_id(snapshot_path: str | None) -> str:
    text = str(snapshot_path or "").strip()
    if not text:
        return ""
    parts = Path(text).parts
    try:
        state_index = parts.index("state")
    except ValueError:
        return ""
    if state_index + 2 >= len(parts):
        return ""
    if parts[state_index + 2] != "snapshot.json":
        return ""
    return parts[state_index + 1]
def _canonical_identity_result(
    *,
    status: str,
    valid: bool,
    reason: str,
    action: str,
    invocation_class: str,
    source_precedence: list[str],
    observed_sources: dict[str, dict[str, Any]],
    selected_source: str | None = None,
    selected_mst_session_id: str | None = None,
    legacy_diagnostics: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    **details: Any,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "accepted": valid,
        "fail_closed": not valid,
        "valid": valid,
        "reason": reason,
        "action": action,
        "source_precedence": source_precedence,
        "observed_sources": observed_sources,
        "invocation_class": invocation_class,
        "canonical_mst_session_id": selected_mst_session_id,
        "mst_session_id": selected_mst_session_id,
        "selected_source": selected_source,
        "legacy_diagnostics": legacy_diagnostics or {},
        "diagnostics": diagnostics or [],
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    return payload
def resolve_canonical_mst_session_identity(
    payload: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    *,
    session_metadata: dict[str, Any] | None = None,
    snapshot_payload: dict[str, Any] | None = None,
    snapshot_path: str | None = None,
    invocation_class: str = "diagnostic_invocation",
    allow_generate: bool = False,
    root_mst_id: str | None = None,
    started_at: datetime | None = None,
    generated_mst_session_id: str | None = None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    env = env if env is not None else os.environ
    session_metadata = session_metadata if isinstance(session_metadata, dict) else {}
    snapshot_payload = snapshot_payload if isinstance(snapshot_payload, dict) else {}
    env_value = str(env.get("MST_SESSION_ID") or "").strip()
    payload_value = payload.get("mst_session_id")
    payload_value = payload_value.strip() if isinstance(payload_value, str) else ""
    session_value = session_metadata.get("mst_session_id")
    session_value = session_value.strip() if isinstance(session_value, str) else ""
    snapshot_body_value = snapshot_payload.get("mst_session_id")
    snapshot_body_value = snapshot_body_value.strip() if isinstance(snapshot_body_value, str) else ""
    snapshot_path_value = _snapshot_path_session_id(snapshot_path)
    legacy_diagnostics: dict[str, Any] = {}
    legacy_env_keys = ("MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID")
    legacy_payload_keys = ("session_id", "sessionId", "owner_ppid", "owner_pid", "owner_session_id")
    for key in legacy_env_keys:
        value = env.get(key)
        if isinstance(value, str) and value.strip():
            legacy_diagnostics[key] = value.strip()
    for key in legacy_payload_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            legacy_diagnostics[key] = value.strip()
        elif isinstance(value, int) and not isinstance(value, bool):
            legacy_diagnostics[key] = value
    transcript_path = payload.get("transcript_path")
    if isinstance(transcript_path, str) and transcript_path.strip():
        transcript_stem = Path(transcript_path).name
        legacy_diagnostics["hook_transcript_stem"] = transcript_stem[:-6] if transcript_stem.endswith(".jsonl") else Path(transcript_stem).stem
    for key in ("hook_transcript_uuid", "transcript_uuid"):
        value = payload.get(key) or env.get(key)
        if isinstance(value, str) and value.strip():
            legacy_diagnostics[key] = value.strip()
    source_precedence = _common.canonical_session_source_precedence()
    observed_sources = {
        "env:MST_SESSION_ID": _identity_observed_source(env_value),
        "structured:mst_session_id": _identity_observed_source(payload_value),
        "session_metadata:mst_session_id": _identity_observed_source(session_value),
        "snapshot_path:mst_session_id": _identity_observed_source(snapshot_path_value),
        "snapshot_body:mst_session_id": _identity_observed_source(snapshot_body_value),
    }
    valid_candidates = [
        (source_name, observed_sources[source_name]["canonical_value"])
        for source_name in source_precedence
        if observed_sources[source_name].get("valid") and observed_sources[source_name].get("canonical_value")
    ]
    invalid_sources = [source_name for source_name, observed in observed_sources.items() if observed.get("present") and not observed.get("valid")]

    if valid_candidates:
        selected_source, selected_session_id = valid_candidates[0]
        conflicting_sources = [
            source_name
            for source_name, candidate_session_id in valid_candidates[1:]
            if candidate_session_id != selected_session_id
        ]
        if conflicting_sources:
            return _canonical_identity_result(
                status="error",
                valid=False,
                reason="canonical_identity_conflict",
                action="repair_canonical_identity_conflict",
                invocation_class=invocation_class,
                source_precedence=source_precedence,
                observed_sources=observed_sources,
                selected_source=selected_source,
                selected_mst_session_id=selected_session_id,
                legacy_diagnostics=legacy_diagnostics or _common.legacy_session_diagnostics(),
                diagnostics=[
                    _diagnostic(
                        "canonical_mst_session_id_mismatch",
                        field="mst_session_id",
                        reason="canonical MST session identity sources disagree",
                        expected=selected_session_id,
                        conflicting_sources=conflicting_sources,
                    )
                ],
                code="canonical_mst_session_id_mismatch",
            )
        parsed = session_cmds.validate_mst_session_id(selected_session_id)
        return _canonical_identity_result(
            status="ok",
            valid=True,
            reason="canonical_identity_resolved",
            action="accept_canonical_identity",
            invocation_class=invocation_class,
            source_precedence=source_precedence,
            observed_sources=observed_sources,
            selected_source=selected_source,
            selected_mst_session_id=parsed.mst_session_id,
            legacy_diagnostics=legacy_diagnostics,
            diagnostics=[],
            root_mst_id=parsed.root_mst_id,
            identity_source=selected_source,
            ignored_legacy_identity_sources=sorted(legacy_diagnostics),
        )

    if invalid_sources:
        return _canonical_identity_result(
            status="error",
            valid=False,
            reason="invalid_canonical_identity",
            action="emit_diagnostic_no_mutation",
            invocation_class=invocation_class,
            source_precedence=source_precedence,
            observed_sources=observed_sources,
            legacy_diagnostics=legacy_diagnostics or _common.legacy_session_diagnostics(),
            diagnostics=[
                _diagnostic(
                    "invalid_mst_session_id",
                    field="mst_session_id",
                    reason="observed canonical identity source is invalid",
                    invalid_sources=invalid_sources,
                )
            ],
            code="invalid_mst_session_id",
        )

    if (allow_generate or generated_mst_session_id) and invocation_class == "normal_entry" and root_mst_id:
        generated = generated_mst_session_id if generated_mst_session_id else session_cmds.generate_mst_session_id(root_mst_id, started_at=started_at)
        parsed = session_cmds.validate_mst_session_id(generated)
        observed_sources["generated:root_mst_id"] = {
            "present": True,
            "value": parsed.mst_session_id,
            "valid": True,
            "canonical_value": parsed.mst_session_id,
        }
        return _canonical_identity_result(
            status="ok",
            valid=True,
            reason="generated_canonical_identity",
            action="generate_canonical_mst_session_id",
            invocation_class=invocation_class,
            source_precedence=source_precedence + ["generated:root_mst_id"],
            observed_sources=observed_sources,
            selected_source="generated:root_mst_id",
            selected_mst_session_id=parsed.mst_session_id,
            legacy_diagnostics=legacy_diagnostics,
            diagnostics=[],
            root_mst_id=parsed.root_mst_id,
            identity_source="generated:root_mst_id",
            ignored_legacy_identity_sources=sorted(legacy_diagnostics),
        )

    if legacy_diagnostics:
        return _canonical_identity_result(
            status="error",
            valid=False,
            reason="legacy_identity_not_canonical_source",
            action="emit_diagnostic_no_mutation",
            invocation_class=invocation_class,
            source_precedence=source_precedence,
            observed_sources=observed_sources,
            legacy_diagnostics=legacy_diagnostics or _common.legacy_session_diagnostics(),
            diagnostics=[
                _diagnostic(
                    "legacy_identity_not_canonical_source",
                    field="mst_session_id",
                    reason="legacy identity inputs are diagnostic-only and cannot become canonical",
                )
            ],
            code="legacy_identity_not_canonical_source",
        )

    return _canonical_identity_result(
        status="error",
        valid=False,
        reason="missing_canonical_identity",
        action="emit_diagnostic_no_mutation" if invocation_class != "normal_entry" else "block_missing_canonical_identity",
        invocation_class=invocation_class,
        source_precedence=source_precedence,
        observed_sources=observed_sources,
        legacy_diagnostics=legacy_diagnostics or _common.legacy_session_diagnostics(),
        diagnostics=[
            _diagnostic(
                "missing_canonical_mst_session_id",
                field="mst_session_id",
                reason="canonical MST session identity is missing",
            )
        ],
        code="missing_canonical_mst_session_id",
    )
def resolve_canonical_mst_session_id(
    payload: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return resolve_canonical_mst_session_identity(payload, env)
