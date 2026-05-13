def _validate_recover_snapshot(snapshot: dict, session_id: str, root_mst_id: str, history_result) -> Optional[dict]:
    validation_error = _common.canonical_state_payload_error(snapshot, session_id)
    if validation_error is not None:
        code = "snapshot_root_mismatch" if "root_mst_id mismatch" in validation_error else "state_history_linkage_mismatch"
        return _recover_non_success(
            code,
            f"snapshot {validation_error}",
            session_id=session_id,
            root_mst_id=root_mst_id,
        )
    refs = _snapshot_history_refs(snapshot)
    if not refs:
        return _recover_non_success(
            "missing_history_linkage",
            "snapshot history head or last event reference is required",
            session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if history_result.tail_hash not in refs and not _history_tail_is_wrapper_completion_after_refs(history_result, refs):
        return _recover_non_success(
            "stale_history_head",
            "snapshot history reference does not match validated ledger head",
            session_id=session_id,
            root_mst_id=root_mst_id,
            details={"expected_history_head": history_result.tail_hash, "snapshot_history_refs": sorted(refs)},
        )
    projection_error = _validate_snapshot_projection_matches_replay(snapshot, session_id, root_mst_id, history_result)
    if projection_error is not None:
        return projection_error
    return None
def _workflow_from_snapshot(snapshot: Optional[dict], root_payload: Optional[dict]) -> dict:
    if isinstance(snapshot, dict):
        workflow = snapshot.get("workflow")
        if isinstance(workflow, dict):
            return {
                "current_skill": workflow.get("current_skill") or snapshot.get("currentSkill") or "",
                "current_step": workflow.get("current_step", snapshot.get("currentStep", 0)),
                "total_steps": workflow.get("total_steps", snapshot.get("totalSteps", 0)),
                "status": workflow.get("status") or snapshot.get("status") or "",
            }
        return {
            "current_skill": snapshot.get("currentSkill") or "",
            "current_step": snapshot.get("currentStep", 0),
            "total_steps": snapshot.get("totalSteps", 0),
            "status": snapshot.get("status") or "",
        }
    return {
        "current_skill": "",
        "current_step": 0,
        "total_steps": 0,
        "status": root_payload.get("status") if isinstance(root_payload, dict) else "",
    }
def _next_skill_from_snapshot(snapshot: Optional[dict]) -> dict:
    next_action_value = snapshot.get("next_action") if isinstance(snapshot, dict) else None
    next_action_payload = next_action_value if isinstance(next_action_value, dict) else {}
    name = (
        next_action_payload.get("expected_skill")
        or next_action_payload.get("skill")
        or next_action_payload.get("next_skill")
        or ""
    )
    source_id = next_action_payload.get("source_id") or next_action_payload.get("source") or ""
    return {
        "name": name,
        "source_id": source_id,
        "auto": bool(next_action_payload.get("auto") or next_action_payload.get("auto_mode")),
        "metadata": next_action_payload,
    }
def _recovery_fingerprint(agi_id: str, session_id: str) -> str:
    context = _json_object_env("MST_CONTEXT_JSON")
    direct = context.get("recovery_fingerprint")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    core = context.get("core_rehydration")
    if isinstance(core, dict):
        nested = core.get("recovery_fingerprint")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    material = f"{session_id}:{agi_id}:recover"
    return "recover:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
def _history_head_for_session(base_dir: Path, session_id: str) -> str:
    from scripts.mst_cmds import session as session_mod

    try:
        head = session_mod.session_history_head_path(base_dir, session_id).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head if re.fullmatch(r"[0-9a-f]{64}", head) else ""
def _snapshot_continuation_evidence(snapshot: Optional[dict]) -> tuple[dict, dict]:
    if not isinstance(snapshot, dict):
        return {}, {}
    continuation = copy.deepcopy(snapshot.get("continuation")) if isinstance(snapshot.get("continuation"), dict) else {}
    next_action = copy.deepcopy(snapshot.get("next_action")) if isinstance(snapshot.get("next_action"), dict) else {}
    if not next_action and isinstance(continuation.get("next_action"), dict):
        next_action = copy.deepcopy(continuation["next_action"])
    if next_action and "next_action" not in continuation:
        continuation["next_action"] = copy.deepcopy(next_action)
    return continuation, next_action
def _append_state_history_event(
    base_dir: Path,
    session_id: str,
    *,
    snapshot: dict,
    command: str,
) -> None:
    from scripts.mst_cmds import session as session_mod

    parsed = session_mod.validate_mst_session_id(session_id)
    history_head = _history_head_for_session(base_dir, session_id)
    continuation, next_action = _snapshot_continuation_evidence(snapshot)
    idempotency_material = f"{session_id}:state.evidence:{command}:{os.getpid()}:{history_head}"
    idempotency_key = f"{session_id}:state.evidence:{hashlib.sha256(idempotency_material.encode('utf-8')).hexdigest()[:24]}"
    event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": "state.evidence",
        "type": "state.evidence",
        "artifact_id": parsed.mst_session_id,
        "resource_id": parsed.root_mst_id,
        "external_control_surface": "state",
        "command": command,
        "history_head": history_head or None,
        "new_session_fallback": False,
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
        "pid": os.getpid(),
        "ppid": _resolve_owner_ppid(),
        "idempotency_key": idempotency_key,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    if continuation:
        event["continuation"] = continuation
        if isinstance(continuation.get("critical_blocker"), dict):
            event["critical_blocker"] = continuation["critical_blocker"]
        if isinstance(continuation.get("circuit_breaker"), dict):
            event["circuit_breaker"] = continuation["circuit_breaker"]
    if next_action:
        event["next_action"] = next_action
        event["next_action_execution"] = {"status": "observed", "next_action": next_action}
    session_mod.write_session_history_event(base_dir, session_id, event)
def _append_recover_history_event(
    base_dir: Path,
    session_id: str,
    agi_id: str,
    recovery_fingerprint: str,
    *,
    previous_history_head: str = "",
    snapshot: Optional[dict] = None,
) -> None:
    from scripts.mst_cmds import session as session_mod

    parsed = session_mod.validate_mst_session_id(session_id)
    idempotency_key = f"{session_id}:skill.recover:{recovery_fingerprint}"
    continuation, next_action = _snapshot_continuation_evidence(snapshot)
    event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": "skill.recover",
        "skill": "mst:recover",
        "resource_id": agi_id,
        "artifact_id": agi_id,
        "status": "rehydrated",
        "recovery_fingerprint": recovery_fingerprint,
        "external_control_surface": "context",
        "history_head": previous_history_head or _history_head_for_session(base_dir, session_id) or None,
        "attempted_recovery": ["validated history ledger and rebuilt core rehydration envelope"],
        "new_session_fallback": False,
        "created_new_session": False,
        "prompt_summary_used_as_source": False,
        "idempotency_key": idempotency_key,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    if continuation:
        event["continuation"] = continuation
        if isinstance(continuation.get("critical_blocker"), dict):
            event["critical_blocker"] = continuation["critical_blocker"]
        if isinstance(continuation.get("circuit_breaker"), dict):
            event["circuit_breaker"] = continuation["circuit_breaker"]
    if next_action:
        event["next_action"] = next_action
        event["next_action_execution"] = {"status": "handoff_prepared", "next_action": next_action}
    session_mod.write_session_history_event(
        base_dir,
        session_id,
        event,
    )
def _append_context_rehydrated_history_event(
    base_dir: Path,
    session_id: str,
    recovery_fingerprint: str,
    *,
    previous_history_head: str,
    snapshot: Optional[dict] = None,
) -> None:
    from scripts.mst_cmds import session as session_mod

    parsed = session_mod.validate_mst_session_id(session_id)
    continuation, next_action = _snapshot_continuation_evidence(snapshot)
    idempotency_key = f"{session_id}:context.rehydrated:{recovery_fingerprint}"
    event = {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24],
        "mst_session_id": parsed.mst_session_id,
        "root_mst_id": parsed.root_mst_id,
        "event_type": "context.rehydrated",
        "type": "context.rehydrated",
        "skill": "mst:recover",
        "resource_id": parsed.root_mst_id,
        "artifact_id": parsed.root_mst_id,
        "external_control_surface": "context",
        "history_head": previous_history_head,
        "rehydration_transition": "continue.rehydrate_retry",
        "handoff_consumption_evidence": {
            "source": "verified_history_ledger",
            "handoff_history_head": previous_history_head,
            "prompt_summary_used_as_source": False,
        },
        "prompt_summary_used_as_source": False,
        "idempotency_key": idempotency_key,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    if continuation:
        event["continuation"] = continuation
        if isinstance(continuation.get("critical_blocker"), dict):
            event["critical_blocker"] = continuation["critical_blocker"]
    if next_action:
        event["next_action"] = next_action
        event["next_action_execution"] = {"status": "handoff_consumed", "next_action": next_action}
    session_mod.write_session_history_event(base_dir, session_id, event)
def _update_snapshot_history_head(state_base_dir: Path, session_id: str, snapshot: Optional[dict], previous_head: str, current_head: str) -> None:
    if not isinstance(snapshot, dict):
        return
    history = _history_ref_from_snapshot(snapshot)
    changed = False
    if history.get("head_hash") != current_head:
        history["head_hash"] = current_head
        changed = True
    if not isinstance(history.get("last_event_id"), str) or not history.get("last_event_id"):
        history["last_event_id"] = previous_head
        changed = True
    if changed:
        updated = dict(snapshot)
        updated["history"] = history
        _atomic_json_write(_snapshot_path_for_session(state_base_dir, session_id), updated)
def _latest_dispatch_context_for_session(session_id: str) -> dict:
    run_directory = _common.run_dir_no_create()
    if not run_directory.is_dir():
        return {}
    candidates: list[tuple[str, dict]] = []
    for path in sorted(run_directory.glob("*.json")):
        payload = _common.load_json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get("mst_session_id") != session_id:
            continue
        task_id = str(payload.get("child_artifact_id") or payload.get("task_id") or path.stem).strip()
        if not task_id:
            continue
        timestamp = str(payload.get("last_heartbeat") or payload.get("started_at") or "")
        candidates.append((timestamp, {"child_artifact_id": task_id, "external_control_surface": "dispatch"}))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]
def _recover_rehydration_bundle(
    *,
    session_id: str,
    root_mst_id: str,
    snapshot: Optional[dict],
    root_payload: Optional[dict],
    history_result,
    previous_history_head: str,
    recovery_fingerprint: str,
) -> dict:
    workflow = _workflow_from_snapshot(snapshot, root_payload)
    next_skill = _next_skill_from_snapshot(snapshot)
    workflow["next_skill"] = next_skill.get("name") or ""
    workflow["next_source"] = next_skill.get("source_id") or ""
    continuation = {}
    if isinstance(snapshot, dict) and isinstance(snapshot.get("continuation"), dict):
        continuation = copy.deepcopy(snapshot["continuation"])
    next_action = None
    if isinstance(snapshot, dict) and isinstance(snapshot.get("next_action"), dict):
        next_action = copy.deepcopy(snapshot["next_action"])
    if next_action is not None:
        continuation.setdefault("next_action", next_action)
    if isinstance(snapshot, dict) and snapshot.get("auto") is True:
        continuation.setdefault("mode", "continue_unless_critical")
        continuation.setdefault("critical_blocker", None)
    handoff_next_action = copy.deepcopy(continuation.get("next_action")) if isinstance(continuation.get("next_action"), dict) else {}
    if not handoff_next_action and isinstance(next_skill.get("metadata"), dict):
        handoff_next_action = copy.deepcopy(next_skill["metadata"])
    current_node = ""
    if workflow.get("current_skill"):
        current_node = f"{workflow.get('current_skill')}.step-{workflow.get('current_step', 0)}"
    last_transition = ""
    blocker = None
    for row in history_result.rows:
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("type") or "")
        if isinstance(event.get("current_node"), str) and event["current_node"].strip():
            current_node = event["current_node"].strip()
        if event_type.startswith(("continue.", "guard.", "terminal.", "context.")):
            last_transition = str(event.get("transition") or event_type)
        candidate_blocker = event.get("critical_blocker") or event.get("blocker")
        if isinstance(candidate_blocker, dict):
            blocker = copy.deepcopy(candidate_blocker)
    if not last_transition:
        last_transition = "continue.rehydrate_retry"
    flow_view = {
        "execution_flow_json": str(history_result.history_file.parent / "execution-flow.json"),
        "execution_flow_d2": str(history_result.history_file.parent / "execution-flow.d2"),
    }
    execution_flow_handoff = {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "history_head": history_result.tail_hash,
        "current_node": current_node,
        "last_transition": last_transition,
        "rehydration_transition": "continue.rehydrate_retry",
        "next_action": handoff_next_action,
        "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
        "blocker": blocker,
        "critical_blocker": blocker if isinstance(blocker, dict) and blocker.get("critical") is True else None,
        "flow_view": flow_view,
    }
    current_work_handoff = _recover_current_work_handoff(
        session_id=session_id,
        root_mst_id=root_mst_id,
        workflow=workflow,
        next_skill=next_skill,
        history_head=history_result.tail_hash,
        snapshot=snapshot,
    )
    context = {
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
        "recovery_fingerprint": recovery_fingerprint,
        "execution_flow_handoff": execution_flow_handoff,
        "current_work_handoff": current_work_handoff,
    }
    context_delivery_order = ["core_rehydration", "execution_flow_handoff", "prompt_summary"]
    env = {"MST_SESSION_ID": session_id}
    if isinstance(snapshot, dict) and snapshot.get("auto") is True:
        env["MST_AUTO_CONTINUE"] = "true"
    envelope = {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
        "continuation": continuation,
        "workflow": workflow,
        "current_skill": {
            "name": workflow.get("current_skill") or "",
            "step": workflow.get("current_step", 0),
            "total_steps": workflow.get("total_steps", 0),
            "status": workflow.get("status") or "",
        },
        "skill_stack": snapshot.get("skillStack", []) if isinstance(snapshot, dict) and isinstance(snapshot.get("skillStack"), list) else [],
        "next_skill": next_skill,
        "history": {
            "head_hash": history_result.tail_hash,
            "last_event_id": previous_history_head,
            "seq": history_result.tail_seq,
            "path": str(history_result.history_file),
        },
        "next_execution": {
            "env": env,
            "context": context,
        },
        "execution_handoff": {
            "mst_session_id": session_id,
            "root_mst_id": root_mst_id,
            "history_head": history_result.tail_hash,
            "current_node": current_node,
            "last_transition": last_transition,
            "rehydration_transition": "continue.rehydrate_retry",
            "next_action": handoff_next_action,
            "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
            "blocker": blocker,
            "critical_blocker": blocker if isinstance(blocker, dict) and blocker.get("critical") is True else None,
            "flow_view": flow_view,
            "source": "core_rehydration",
        },
        "execution_flow_handoff": execution_flow_handoff,
        "current_work_handoff": current_work_handoff,
        "budgeted_context": {
            "execution_flow_handoff": execution_flow_handoff,
            "current_work_handoff": current_work_handoff,
            "omissions": [
                "full execution-flow nodes omitted; use flow_view.execution_flow_json for details",
                "full execution-flow D2 omitted; use flow_view.execution_flow_d2 for details",
                "raw history rows and transcript content omitted; use current_work_handoff.evidence_paths for source inspection",
            ],
        },
        "context_delivery_order": context_delivery_order,
        "source_precedence": ["validated_history_ledger", "validated_state_snapshot", "prompt_summary_diagnostic_only"],
        "prompt_summary_used_as_source": False,
        "recovery_fingerprint": recovery_fingerprint,
        "created_new_session": False,
    }
    dispatch_context = _latest_dispatch_context_for_session(session_id)
    if dispatch_context:
        envelope.update(dispatch_context)
    return envelope
def _recover_current_work_handoff(
    *,
    session_id: str,
    root_mst_id: str,
    workflow: dict,
    next_skill: dict,
    history_head: str,
    snapshot: Optional[dict],
) -> dict:
    from scripts.mst_cmds.current_work_handoff import project_current_work_handoff

    current_skill = str(workflow.get("current_skill") or "").strip()
    current_step = str(workflow.get("current_step") or "").strip()
    next_name = str(next_skill.get("name") or "").strip()
    next_source = str(next_skill.get("source_id") or "").strip()
    auto = bool(next_skill.get("auto"))
    source_evidence = f".gran-maestro/state/{session_id}/snapshot.json"
    task_id = next_source or root_mst_id
    task_sources = []
    if current_skill or next_source:
        task_sources.append(
            {
                "kind": "recover_resume",
                "id": task_id,
                "title": f"Recover {task_id}",
                "status": str(workflow.get("status") or "active"),
                "owner": "mst:recover",
                "phase": f"step-{current_step}" if current_step else "unknown",
                "source": "state_snapshot",
                "evidence_path": source_evidence,
            }
        )
    action_type = "resume_workflow" if next_name else "no_action_available"
    command_hint = f"/{next_name}" if next_name.startswith("mst:") else (f"/mst:{next_name}" if next_name else "")
    if command_hint and next_source:
        command_hint = f"{command_hint} {next_source}"
    if command_hint and auto:
        command_hint = f"{command_hint} -a"
    return project_current_work_handoff(
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "canonical_mst_session_id": session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "source_history_head": history_head,
            "current_history_head": history_head,
            "history_head_evidence_path": f".gran-maestro/sessions/{session_id}/history.head",
            "identity": {
                "env": {"MST_SESSION_ID": session_id},
                "context": {"mst_session_id": session_id, "root_mst_id": root_mst_id},
                "legacy_diagnostics": {},
            },
            "active_workflow": {
                "skill": current_skill or "mst:recover",
                "source_id": root_mst_id,
                "auto": bool(isinstance(snapshot, dict) and snapshot.get("auto") is True),
                "status": str(workflow.get("status") or "active"),
                "evidence_path": source_evidence,
            },
            "task_sources": task_sources,
            "resume_queue": {
                "skill": next_name,
                "args": f"{next_source} -a".strip() if auto and next_source else next_source,
                "source_skill": current_skill,
                "source_id": next_source,
                "auto": auto,
                "evidence_path": source_evidence,
            },
            "next_action_source": {
                "action_type": action_type,
                "label": f"Resume {next_name}" if next_name else "No current-work action available",
                "target": next_source,
                "command_hint": command_hint,
                "reason": "recover/resume envelope projected a bounded current-work handoff",
                "confidence": 0.85 if next_name else 0.0,
                "evidence_path": source_evidence,
            },
            "blocker_sources": [],
            "writer_coverage": {
                "source_history_head": history_head,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "writers": [],
            },
        }
    )
def _structured_legacy_alias_conflict(session_id: str) -> Optional[dict]:
    diagnostics = _common.legacy_session_diagnostics()
    snapshot_alias = diagnostics.get("MST_SNAPSHOT_SESSION_ID")
    if isinstance(snapshot_alias, str) and snapshot_alias.strip():
        try:
            from scripts.mst_cmds.session import validate_mst_session_id

            alias_session_id = validate_mst_session_id(snapshot_alias.strip()).mst_session_id
        except ValueError:
            alias_session_id = ""
        if alias_session_id and alias_session_id != session_id:
            return _recover_non_success(
                "legacy_identity_not_canonical_source",
                "MST_SNAPSHOT_SESSION_ID conflicts with canonical MST_SESSION_ID",
                session_id=session_id,
                details={"legacy_conflict_source": "MST_SNAPSHOT_SESSION_ID"},
            )
    return None
def _context_core_history_refs() -> set[str]:
    context = _json_object_env("MST_CONTEXT_JSON")
    core = context.get("core_rehydration")
    if not isinstance(core, dict):
        return set()
    history = core.get("history")
    if not isinstance(history, dict):
        return set()
    refs: set[str] = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = history.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    return refs
def _recover_context_contract_failure(
    *,
    session_id: str,
    root_mst_id: str,
    history_result,
    snapshot: Optional[dict],
) -> Optional[dict]:
    context = _json_object_env("MST_CONTEXT_JSON")
    if not context:
        return None
    handoff = context.get("current_work_handoff")
    if isinstance(handoff, dict):
        handoff_error = _current_work_handoff_contract_failure(
            handoff,
            session_id=session_id,
            root_mst_id=root_mst_id,
        )
        if handoff_error is not None:
            return handoff_error
    if context.get("schema_version") is not None and context.get("schema_version") != 1:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="schema_version",
            reason="recover bundle schema_version must be 1",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    core = context.get("core_rehydration")
    has_legacy_identity = any(
        isinstance(context.get(key), str) and context.get(key, "").strip()
        for key in ("session_id", "sessionId", "owner_session_id")
    )
    if isinstance(core, dict):
        has_legacy_identity = has_legacy_identity or any(
            isinstance(core.get(key), str) and core.get(key, "").strip()
            for key in ("session_id", "sessionId", "owner_session_id")
        )
    if has_legacy_identity:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="legacy_identity",
            reason="legacy session identity is not a canonical source",
            code="legacy_identity_not_canonical_source",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if not isinstance(core, dict):
        return None
    if core.get("schema_version") != 1:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.schema_version",
            reason="core_rehydration.schema_version is required and must be 1",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if core.get("mst_session_id") != session_id:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.mst_session_id",
            reason="core_rehydration.mst_session_id must match MST_SESSION_ID",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    if core.get("root_mst_id") != root_mst_id:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.root_mst_id",
            reason="core_rehydration.root_mst_id must match session root",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    next_execution = core.get("next_execution")
    if isinstance(next_execution, dict):
        env = next_execution.get("env")
        if isinstance(env, dict):
            env_session_id = env.get("MST_SESSION_ID")
            if isinstance(env_session_id, str) and env_session_id.strip() and env_session_id.strip() != session_id:
                return _common.validation_failure_payload(
                    target="recover_bundle",
                    field="core_rehydration.next_execution.env.MST_SESSION_ID",
                    reason="next_execution env MST_SESSION_ID must match canonical session",
                    mst_session_id=session_id,
                    root_mst_id=root_mst_id,
                )
        handoff_context = next_execution.get("context")
        if isinstance(handoff_context, dict):
            context_session_id = handoff_context.get("mst_session_id")
            if (
                isinstance(context_session_id, str)
                and context_session_id.strip()
                and context_session_id.strip() != session_id
            ):
                return _common.validation_failure_payload(
                    target="recover_bundle",
                    field="core_rehydration.next_execution.context.mst_session_id",
                    reason="next_execution context mst_session_id must match canonical session",
                    mst_session_id=session_id,
                    root_mst_id=root_mst_id,
                )
            context_root = handoff_context.get("root_mst_id")
            if isinstance(context_root, str) and context_root.strip() and context_root.strip() != root_mst_id:
                return _common.validation_failure_payload(
                    target="recover_bundle",
                    field="core_rehydration.next_execution.context.root_mst_id",
                    reason="next_execution context root_mst_id must match session root",
                    mst_session_id=session_id,
                    root_mst_id=root_mst_id,
                )
    execution_handoff = core.get("execution_handoff")
    if isinstance(execution_handoff, dict):
        handoff_session_id = execution_handoff.get("mst_session_id")
        if isinstance(handoff_session_id, str) and handoff_session_id.strip() and handoff_session_id.strip() != session_id:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.execution_handoff.mst_session_id",
                reason="execution_handoff mst_session_id must match canonical session",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
        handoff_root = execution_handoff.get("root_mst_id")
        if isinstance(handoff_root, str) and handoff_root.strip() and handoff_root.strip() != root_mst_id:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.execution_handoff.root_mst_id",
                reason="execution_handoff root_mst_id must match session root",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )

    history = core.get("history")
    if not isinstance(history, dict):
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.history_last_event_id",
            reason="core_rehydration.history is required",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    refs = set()
    for key in ("head_hash", "last_event_id", "event_hash"):
        value = history.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            refs.add(value.strip())
    if history_result.tail_hash not in refs:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="core_rehydration.history_last_event_id",
            reason="core_rehydration history reference does not match validated ledger head",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
            expected_history_head=history_result.tail_hash,
            core_rehydration_history_refs=sorted(refs),
        )

    workflow = core.get("workflow")
    snapshot_next = _next_skill_from_snapshot(snapshot) if isinstance(snapshot, dict) else {}
    core_next_source = workflow.get("next_source") if isinstance(workflow, dict) else None
    core_next_skill = workflow.get("next_skill") if isinstance(workflow, dict) else None
    strict_current_fields = (
        "auto" in core
        or "continuation" in core
        or "current_skill" in core
        or (
            isinstance(snapshot_next, dict)
            and (
                (snapshot_next.get("source_id") and core_next_source and snapshot_next.get("source_id") != core_next_source)
                or (snapshot_next.get("name") and core_next_skill and snapshot_next.get("name") != core_next_skill)
            )
        )
    )
    if strict_current_fields:
        auto_missing = not isinstance(core.get("auto"), bool)
        continuation_missing = not isinstance(core.get("continuation"), dict)
        core_current_skill = core.get("current_skill")
        workflow_current_skill = workflow.get("current_skill") if isinstance(workflow, dict) else None
        current_skill_missing = not (
            (isinstance(core_current_skill, str) and core_current_skill.strip())
            or (isinstance(workflow_current_skill, str) and workflow_current_skill.strip())
        )
        if auto_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.auto",
                reason="core_rehydration.auto is required and must be boolean",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
        if continuation_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.continuation",
                reason="core_rehydration.continuation object is required",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
        if current_skill_missing:
            return _common.validation_failure_payload(
                target="recover_bundle",
                field="core_rehydration.current_skill",
                reason="core_rehydration.current_skill is required",
                mst_session_id=session_id,
                root_mst_id=root_mst_id,
            )
    return None
def _current_work_handoff_contract_failure(
    handoff: dict,
    *,
    session_id: str,
    root_mst_id: str,
) -> Optional[dict]:
    if handoff.get("schema_version") != 1:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="current_work_handoff.schema_version",
            reason="current_work_handoff schema_version is required and must be 1",
            code="schema_invalid",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    handoff_session_id = handoff.get("canonical_mst_session_id") or handoff.get("mst_session_id")
    if isinstance(handoff_session_id, str) and handoff_session_id.strip() and handoff_session_id.strip() != session_id:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="current_work_handoff.mst_session_id",
            reason="current_work_handoff mst_session_id must match canonical session",
            code="identity_mismatch",
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    freshness = handoff.get("projection_freshness")
    freshness_status = freshness.get("status") if isinstance(freshness, dict) else None
    blocker_types = {
        str(blocker.get("blocker_type") or "")
        for blocker in handoff.get("blockers", [])
        if isinstance(blocker, dict)
    } if isinstance(handoff.get("blockers"), list) else set()
    blocking_types = {
        "stale_projection",
        "identity_mismatch",
        "missing_source",
        "schema_invalid",
    }
    blocked = blocker_types & blocking_types
    if freshness_status == "stale" and "stale_projection" not in blocked:
        blocked.add("stale_projection")
    if freshness_status == "identity_mismatch" and "identity_mismatch" not in blocked:
        blocked.add("identity_mismatch")
    if blocked:
        return _common.validation_failure_payload(
            target="recover_bundle",
            field="current_work_handoff.blockers",
            reason="current_work_handoff is not safe for automatic recovery consumption",
            code=sorted(blocked)[0],
            mst_session_id=session_id,
            root_mst_id=root_mst_id,
        )
    return None
def _history_tail_is_current_invocation_after_refs(history_result, refs: set[str]) -> bool:
    if not history_result.rows or not history_result.projections:
        return False
    current_pid = str(os.getpid())
    seen_ref = False
    for row, projection in zip(history_result.rows, history_result.projections):
        if row.get("event_hash") in refs:
            seen_ref = True
            continue
        if not seen_ref:
            continue
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            return False
        event_type = str(projection.get("event_type") or event.get("event_type") or "")
        if event_type not in {"mst.invocation_start", "mst.invocation_end", "mst.invocation_error"}:
            return False
        if str(event.get("pid") or "") != current_pid:
            return False
    return seen_ref and history_result.tail_hash not in refs
def _history_tail_is_wrapper_completion_after_refs(history_result, refs: set[str]) -> bool:
    if not history_result.rows or not history_result.projections:
        return False
    seen_ref = False
    for row, projection in zip(history_result.rows, history_result.projections):
        if row.get("event_hash") in refs:
            seen_ref = True
            continue
        if not seen_ref:
            continue
        event = row.get("event") if isinstance(row, dict) else None
        if not isinstance(event, dict):
            return False
        event_type = str(projection.get("event_type") or event.get("event_type") or "")
        if event_type not in {"mst.invocation_end", "mst.invocation_error"}:
            return False
    return seen_ref and history_result.tail_hash not in refs
