def _infer_guard_pass(guard: str, envelope: dict[str, Any], evidence: dict[str, Any]) -> bool:
    explicit = _coerce_guard_pass(_explicit_guard_value(envelope, guard))
    if explicit is not None:
        return explicit
    if guard == "next_action_present":
        return _value_present(evidence.get("next_action"))
    if guard == "no_critical_blocker":
        return not _value_present(evidence.get("critical_blocker"))
    if guard == "all_required_dod_done":
        result = evidence.get("objective_check_result")
        if isinstance(result, dict):
            for key in ("done", "passed", "accepted", "ok"):
                if isinstance(result.get(key), bool):
                    return bool(result[key])
        return bool(result)
    if guard == "no_next_action":
        return not _value_present(evidence.get("next_action"))
    if guard == "history_verified":
        return _value_present(evidence.get("history_head"))
    if guard == "core_rehydration_available":
        return _value_present(evidence.get("mst_session_id") or envelope.get("mst_session_id")) and _value_present(
            evidence.get("root_mst_id") or envelope.get("root_mst_id")
        )
    if guard == "history_head_matches_snapshot":
        history_head = evidence.get("history_head")
        last_event_id = evidence.get("history_last_event_id")
        return _value_present(last_event_id) and (not _value_present(history_head) or history_head == last_event_id)
    if guard == "state_inconsistency_suspected":
        return _value_present(evidence.get("mismatch_subject"))
    if guard == "action_is_destructive_or_external":
        return _value_present(evidence.get("action_scope"))
    if guard == "classifier_failed_or_permission_unknown":
        return _value_present(evidence.get("classifier_failure_kind"))
    if guard == "state_contract_failed":
        return _value_present(evidence.get("mismatch_subject"))
    if guard == "repeat_limit_exceeded":
        return _value_present(evidence.get("reject_loop_key")) and _value_present(evidence.get("attempt_count"))
    return True
def _guard_checks(
    transition: dict[str, Any],
    envelope: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    failed: list[str] = []
    for guard in transition.get("guards") or []:
        passed = _infer_guard_pass(str(guard), envelope, evidence)
        check = {
            "guard": guard,
            "passed": passed,
            "source": "explicit" if _explicit_guard_value(envelope, str(guard)) is not None else "inferred",
        }
        checks.append(check)
        if not passed:
            failed.append(str(guard))
    return checks, failed
def _any_bool(envelope: dict[str, Any], names: tuple[str, ...]) -> bool:
    return any(envelope.get(name) is True for name in names)
def _evidence_is_stale(value: Any) -> bool:
    if isinstance(value, dict):
        status = value.get("status")
        return (
            value.get("stale") is True
            or value.get("is_stale") is True
            or (isinstance(status, str) and status.strip().lower() in {"stale", "expired"})
        )
    return False
def _evidence_is_mismatch(key: str, value: Any, envelope: dict[str, Any]) -> bool:
    if isinstance(value, dict):
        status = value.get("status")
        if (
            value.get("mismatch") is True
            or value.get("mismatched") is True
            or value.get("confirmed_mismatch") is True
            or (isinstance(status, str) and status.strip().lower() in {"mismatch", "mismatched"})
        ):
            return True
        evidence_session = value.get("mst_session_id")
        if isinstance(evidence_session, str) and envelope.get("mst_session_id") and evidence_session != envelope.get("mst_session_id"):
            return True
        if value.get("expected") is not None and value.get("actual") is not None and value.get("expected") != value.get("actual"):
            return True
        if key == "mismatch_subject" and value.get("confirmed") is True:
            return True
    return key == "mismatch_subject" and _value_present(value)
def _completion_reject_path(
    transition_id: Any,
    transition: dict[str, Any],
    *,
    failed_guards: list[str],
    missing_evidence: list[str],
    stale_evidence: list[str],
    mismatched_evidence: list[str],
) -> Any:
    if mismatched_evidence:
        return "terminal.state_inconsistency"
    if transition_id == "terminal.completed":
        evidence_failure_keys = {"objective_check_result", "history_head"}
        if evidence_failure_keys.intersection(missing_evidence) or evidence_failure_keys.intersection(stale_evidence):
            return "guard.inspect_only_verification"
        if "history_verified" in failed_guards:
            return "guard.inspect_only_verification"
        if "no_next_action" in failed_guards:
            return "continue.queued_action"
    return transition.get("on_reject")
def validate_attempted_transition(envelope: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(graph, dict):
        graph = {}
    if not isinstance(envelope, dict):
        diagnostics.append(
            _attempt_diag(
                "payload",
                field="payload",
                path="$",
                reason="attempted transition envelope must be an object",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph)

    graph_validation = validate_transition_graph(graph, source="attempted_transition.graph")
    if graph_validation.get("accepted") is not True:
        return _attempt_failure(list(graph_validation.get("diagnostics") or []), graph=graph, envelope=envelope)

    identity = _graph_identity(envelope)
    for field in ("id", "version", "hash"):
        expected = graph.get(field)
        actual = identity.get(field)
        if not _value_present(actual):
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"graph {field} is required in the explicit attempt envelope",
                    graph=graph,
                )
            )
        elif actual != expected:
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"attempt envelope graph {field} does not match canonical graph",
                    graph=graph,
                )
                | {"actual": actual, "expected": expected}
            )

    for field in ("mst_session_id", "root_mst_id", "current_state", "attempted_transition"):
        if not _value_present(envelope.get(field)):
            diagnostics.append(
                _attempt_diag(
                    field,
                    field=field,
                    path=field,
                    reason=f"{field} is required in the explicit attempt envelope",
                    graph=graph,
                )
            )

    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    current_state = envelope.get("current_state")
    transition_id = envelope.get("attempted_transition")
    transition = transitions.get(transition_id) if isinstance(transition_id, str) else None
    if isinstance(current_state, str) and current_state not in states:
        diagnostics.append(
            _attempt_diag(
                "current_state",
                field="current_state",
                path="current_state",
                reason=f"current_state is not declared in the graph: {current_state}",
                graph=graph,
            )
        )
    if not isinstance(transition, dict):
        diagnostics.append(
            _attempt_diag(
                "attempted_transition",
                field="attempted_transition",
                path="attempted_transition",
                reason=f"attempted_transition is not declared in the graph: {transition_id}",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph, envelope=envelope)
    if isinstance(current_state, str) and current_state not in (transition.get("from") or []):
        diagnostics.append(
            _attempt_diag(
                "transition.from",
                field="from",
                path=f"transitions.{transition_id}.from",
                reason=f"transition {transition_id} is not allowed from {current_state}",
                graph=graph,
            )
        )

    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
        diagnostics.append(
            _attempt_diag(
                "evidence",
                field="evidence",
                path="evidence",
                reason="evidence map is required in the explicit attempt envelope",
                graph=graph,
            )
        )

    required_evidence = [str(item) for item in transition.get("required_evidence") or []]
    missing_evidence = [key for key in required_evidence if key not in evidence or not _value_present(evidence.get(key))]
    stale_evidence = [key for key in required_evidence if key in evidence and _evidence_is_stale(evidence.get(key))]
    mismatched_evidence = [
        key
        for key, value in evidence.items()
        if isinstance(key, str) and _evidence_is_mismatch(key, value, envelope)
    ]
    for key in missing_evidence:
        diagnostics.append(
            _attempt_diag(
                "required_evidence",
                field="required_evidence",
                path=f"evidence.{key}",
                reason=f"required evidence is missing: {key}",
                graph=graph,
            )
        )
    for key in stale_evidence:
        diagnostics.append(
            _attempt_diag(
                "stale_evidence",
                field="required_evidence",
                path=f"evidence.{key}",
                reason=f"required evidence is stale: {key}",
                graph=graph,
            )
        )
    for key in mismatched_evidence:
        diagnostics.append(
            _attempt_diag(
                "evidence_mismatch",
                field="evidence",
                path=f"evidence.{key}",
                reason=f"evidence is confirmed mismatched: {key}",
                graph=graph,
            )
        )

    guard_results, failed_guards = _guard_checks(transition, envelope, evidence)
    for guard in failed_guards:
        diagnostics.append(
            _attempt_diag(
                f"guard.{guard}",
                field="guards",
                path=f"transitions.{transition_id}.guards",
                reason=f"guard failed: {guard}",
                graph=graph,
            )
        )
    auto_requested = _any_bool(envelope, ("auto", "auto_attempt", "auto_continuation", "auto_requested"))
    write_requested = _any_bool(envelope, ("write", "write_attempt", "write_requested", "mutation_attempt"))
    if auto_requested and transition.get("auto_allowed") is not True:
        diagnostics.append(
            _attempt_diag(
                "auto_allowed",
                field="auto_allowed",
                path=f"transitions.{transition_id}.auto_allowed",
                reason="transition is not allowed for automatic continuation",
                graph=graph,
            )
        )
    if write_requested and transition.get("write_allowed") is not True:
        diagnostics.append(
            _attempt_diag(
                "write_allowed",
                field="write_allowed",
                path=f"transitions.{transition_id}.write_allowed",
                reason="transition is not allowed to authorize write mutation",
                graph=graph,
            )
        )

    base = {
        "mst_session_id": envelope.get("mst_session_id"),
        "root_mst_id": envelope.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "current_state": current_state,
        "transition": transition_id,
        "target_state": transition.get("to"),
        "required_evidence": required_evidence,
        "required_evidence_checks": [
            {"key": key, "present": key not in missing_evidence} for key in required_evidence
        ],
        "guard_results": guard_results,
        "auto_allowed": transition.get("auto_allowed"),
        "write_allowed": transition.get("write_allowed"),
        "auto_requested": auto_requested,
        "write_requested": write_requested,
        "created_new_session": False,
    }
    if diagnostics:
        on_reject = _completion_reject_path(
            transition_id,
            transition,
            failed_guards=failed_guards,
            missing_evidence=missing_evidence,
            stale_evidence=stale_evidence,
            mismatched_evidence=mismatched_evidence,
        )
        return {
            **base,
            "status": "rejected",
            "accepted": False,
            "fail_closed": True,
            "write_permission_granted": False,
            "auto_continuation_allowed": False,
            "auto_terminal_write": False,
            "failed_guards": failed_guards,
            "missing_evidence": missing_evidence,
            "stale_evidence": stale_evidence,
            "mismatched_evidence": mismatched_evidence,
            "on_reject": on_reject,
            "diagnostics": diagnostics,
        }
    return {
        **base,
        "status": "accepted",
        "accepted": True,
        "fail_closed": False,
        "write_permission_granted": bool(transition.get("write_allowed")),
        "auto_continuation_allowed": bool(transition.get("auto_allowed")),
        "auto_terminal_write": bool(str(transition_id).startswith("terminal.") and transition.get("write_allowed")),
        "failed_guards": [],
        "missing_evidence": [],
        "stale_evidence": [],
        "mismatched_evidence": [],
        "on_reject": None,
        "diagnostics": [],
    }
def _normalized_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
def _reject_loop_fingerprint(attempt: dict[str, Any]) -> str:
    fingerprint = attempt.get("evidence_fingerprint")
    if isinstance(fingerprint, str) and fingerprint.strip():
        return fingerprint.strip()
    evidence = attempt.get("evidence")
    if isinstance(evidence, dict):
        return hashlib.sha256(_normalized_json(evidence).encode("utf-8")).hexdigest()
    return hashlib.sha256(_normalized_json(attempt.get("required_evidence") or {}).encode("utf-8")).hexdigest()
def _reject_loop_key(attempt: dict[str, Any]) -> str:
    parts = [
        str(attempt.get("mst_session_id") or ""),
        str(attempt.get("attempted_transition") or attempt.get("transition") or ""),
        str(attempt.get("failed_guard") or ",".join(attempt.get("failed_guards") or []) or ""),
        _reject_loop_fingerprint(attempt),
    ]
    encoded = "\x1f".join(parts)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"reject-loop:{digest}"
def apply_on_reject_loop_guard(
    attempt: dict[str, Any],
    prior: list[dict[str, Any]],
    graph: dict[str, Any],
    limit: int = 3,
) -> dict[str, Any]:
    if not isinstance(attempt, dict):
        attempt = {}
    prior = prior if isinstance(prior, list) else []
    idempotency_key = _reject_loop_key(attempt)
    previous_count = 0
    for item in prior:
        if not isinstance(item, dict):
            continue
        prior_key = item.get("idempotency_key")
        result = item.get("result")
        if not isinstance(prior_key, str) and isinstance(result, dict):
            prior_key = result.get("idempotency_key")
        if prior_key is None:
            prior_key = _reject_loop_key(item)
        if prior_key == idempotency_key:
            previous_count += 1
    attempt_count = previous_count + 1
    terminal_transition = (
        "terminal.repeat_failure_limit"
        if isinstance(graph.get("transitions"), dict) and "terminal.repeat_failure_limit" in graph["transitions"]
        else "terminal.state_inconsistency"
    )
    base = {
        "idempotency_key": idempotency_key,
        "mst_session_id": attempt.get("mst_session_id"),
        "attempted_transition": attempt.get("attempted_transition") or attempt.get("transition"),
        "failed_guard": attempt.get("failed_guard"),
        "evidence_fingerprint": _reject_loop_fingerprint(attempt),
        "attempt_count": attempt_count,
        "limit": limit,
        "completed": False,
        "created_new_session": False,
        "graph_id": graph.get("id") if isinstance(graph, dict) else None,
        "graph_version": graph.get("version") if isinstance(graph, dict) else None,
        "graph_hash": graph.get("hash") if isinstance(graph, dict) else None,
    }
    if attempt_count > limit:
        return {
            **base,
            "status": "terminal",
            "accepted": False,
            "fail_closed": True,
            "terminal_transition": terminal_transition,
            "on_reject_retry_allowed": False,
            "critical_blocker": {
                "type": terminal_transition.removeprefix("terminal."),
                "idempotency_key": idempotency_key,
                "attempt_count": attempt_count,
                "limit": limit,
            },
            "diagnostics": [
                _attempt_diag(
                    "reject_loop_limit",
                    field="on_reject",
                    path="on_reject",
                    reason="repeated on_reject attempt exceeded the configured limit",
                    graph=graph if isinstance(graph, dict) else {},
                )
            ],
        }
    return {
        **base,
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "terminal_transition": None,
        "on_reject_retry_allowed": True,
        "diagnostics": [],
    }
def _fixture_value(fixture: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = fixture.get(key)
        if _value_present(value):
            return value
    tool_input = fixture.get("tool_input")
    if isinstance(tool_input, dict):
        for key in keys:
            value = tool_input.get(key)
            if _value_present(value):
                return value
    return None
def classify_hook_attempt(boundary: str, fixture: dict[str, Any]) -> str | None:
    fixture = fixture if isinstance(fixture, dict) else {}
    explicit = fixture.get("attempted_transition")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    tool_name = str(_fixture_value(fixture, "tool_name", "name") or "").strip()
    message = str(
        _fixture_value(fixture, "last_assistant_message", "assistant_message", "message", "reason") or ""
    ).lower()
    if boundary == "PreToolUse" and tool_name == "AskUserQuestion":
        if fixture.get("awaiting_user_input") is True:
            return "user_wait.prepared"
        return "user_wait"
    if boundary == "PreToolUse" and tool_name == "ScheduleWakeup":
        return "self_paced_stop"
    if "askuserquestion" in message:
        return "user_wait"
    if "schedulewakeup" in message or "stop here" in message or "pause" in message:
        return "self_paced_stop"
    if "premature" in message and "complete" in message:
        return "premature_completed"
    if "final answer" in message or "workflow complete" in message or "completed" in message or "all done" in message:
        return "terminal.completed"
    return None
def _graph_transition(graph: dict[str, Any], transition_id: Any) -> dict[str, Any]:
    transitions = graph.get("transitions") if isinstance(graph, dict) else None
    if not isinstance(transitions, dict) or not isinstance(transition_id, str):
        return {}
    transition = transitions.get(transition_id)
    return transition if isinstance(transition, dict) else {}
def _required_response_for_transition(transition_id: str | None) -> str:
    if not isinstance(transition_id, str):
        return "inspect_only"
    if transition_id.startswith("continue."):
        return "continue"
    if transition_id.startswith("guard."):
        return "inspect_only"
    return "terminal_blocker"
def _first_string(values: Any) -> str | None:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(values, str) and values.strip():
        return values.strip()
    return None
def build_hook_continuation_block(
    boundary: str,
    fixture: dict[str, Any],
    reject_result: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    fixture = fixture if isinstance(fixture, dict) else {}
    reject_result = reject_result if isinstance(reject_result, dict) else {}
    graph = graph if isinstance(graph, dict) else {}

    attempted_transition = classify_hook_attempt(str(boundary or ""), fixture) or reject_result.get("transition")
    graph_transition = reject_result.get("transition")
    on_reject = reject_result.get("on_reject")
    on_reject_transition = _graph_transition(graph, on_reject)
    required_evidence = list(reject_result.get("required_evidence") or on_reject_transition.get("required_evidence") or [])
    failed_guard = _first_string(reject_result.get("failed_guards")) or _first_string(
        reject_result.get("failed_guard")
    )
    next_action = (
        reject_result.get("next_action")
        or fixture.get("next_action")
        or fixture.get("queued_action")
        or {"transition": on_reject}
    )
    required_response = _required_response_for_transition(on_reject if isinstance(on_reject, str) else None)

    return {
        "decision": "block",
        "reason": "graph_transition_rejected",
        "hook_boundary": boundary,
        "attempted_transition": attempted_transition,
        "graph_transition": graph_transition,
        "failed_guard": failed_guard,
        "failed_guards": list(reject_result.get("failed_guards") or ([] if failed_guard is None else [failed_guard])),
        "required_evidence": required_evidence,
        "on_reject_transition": on_reject,
        "mst_session_id": reject_result.get("mst_session_id") or fixture.get("mst_session_id"),
        "root_mst_id": reject_result.get("root_mst_id") or fixture.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "same_session_evidence": bool(reject_result.get("mst_session_id") or fixture.get("mst_session_id")),
        "continuation": {
            "required_response": required_response,
            "transition": on_reject,
            "next_action": next_action,
            "write_allowed": on_reject_transition.get("write_allowed"),
            "auto_allowed": on_reject_transition.get("auto_allowed"),
        },
        "full_state_prompt_injection": False,
        "hot_path_full_graph_validation": False,
        "hot_path_d2_rendering": False,
        "hot_path_full_ledger_replay": False,
    }
def build_hook_pass_result(boundary: str, fixture: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    fixture = fixture if isinstance(fixture, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    return {
        "decision": "approve",
        "reason": "graph_transition_pass",
        "hook_boundary": boundary,
        "attempted_transition": classify_hook_attempt(str(boundary or ""), fixture),
        "mst_session_id": fixture.get("mst_session_id"),
        "root_mst_id": fixture.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "full_state_prompt_injection": False,
        "hot_path_full_graph_validation": False,
        "hot_path_d2_rendering": False,
        "hot_path_full_ledger_replay": False,
    }
def validate_hook_attempted_transition(envelope: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Validate a hook boundary attempt with cached graph lookup only.

    This intentionally avoids validate_transition_graph(), generated view checks,
    and ledger replay so hook hot paths can fail closed without doing heavy work.
    """

    graph = graph if isinstance(graph, dict) else {}
    envelope = envelope if isinstance(envelope, dict) else {}
    diagnostics: list[dict[str, Any]] = []
    identity = _graph_identity(envelope)
    for field in ("id", "version", "hash"):
        expected = graph.get(field)
        actual = identity.get(field)
        if not _value_present(actual) or actual != expected:
            diagnostics.append(
                _attempt_diag(
                    f"graph.{field}",
                    field=f"graph.{field}",
                    path=f"graph.{field}",
                    reason=f"hook attempt graph {field} does not match pinned graph",
                    graph=graph,
                )
                | {"actual": actual, "expected": expected}
            )

    transitions = graph.get("transitions") if isinstance(graph.get("transitions"), dict) else {}
    states = graph.get("states") if isinstance(graph.get("states"), dict) else {}
    transition_id = envelope.get("attempted_transition")
    current_state = envelope.get("current_state")
    transition = transitions.get(transition_id) if isinstance(transition_id, str) else None
    if not isinstance(current_state, str) or current_state not in states:
        diagnostics.append(
            _attempt_diag(
                "current_state",
                field="current_state",
                path="current_state",
                reason="hook attempt current_state is missing or not declared",
                graph=graph,
            )
        )
    if not isinstance(transition, dict):
        diagnostics.append(
            _attempt_diag(
                "attempted_transition",
                field="attempted_transition",
                path="attempted_transition",
                reason="hook attempted_transition is missing or not declared",
                graph=graph,
            )
        )
        return _attempt_failure(diagnostics, graph=graph, envelope=envelope)
    if isinstance(current_state, str) and current_state not in (transition.get("from") or []):
        diagnostics.append(
            _attempt_diag(
                "transition.from",
                field="from",
                path=f"transitions.{transition_id}.from",
                reason=f"transition {transition_id} is not allowed from {current_state}",
                graph=graph,
            )
        )

    evidence = envelope.get("evidence") if isinstance(envelope.get("evidence"), dict) else {}
    required_evidence = [str(item) for item in transition.get("required_evidence") or []]
    missing_evidence = [key for key in required_evidence if key not in evidence or not _value_present(evidence.get(key))]
    for key in missing_evidence:
        diagnostics.append(
            _attempt_diag(
                "required_evidence",
                field="required_evidence",
                path=f"evidence.{key}",
                reason=f"required evidence is missing: {key}",
                graph=graph,
            )
        )
    guard_results, failed_guards = _guard_checks(transition, envelope, evidence)
    for guard in failed_guards:
        diagnostics.append(
            _attempt_diag(
                f"guard.{guard}",
                field="guards",
                path=f"transitions.{transition_id}.guards",
                reason=f"guard failed: {guard}",
                graph=graph,
            )
        )

    base = {
        "mst_session_id": envelope.get("mst_session_id"),
        "root_mst_id": envelope.get("root_mst_id"),
        "graph_id": graph.get("id"),
        "graph_version": graph.get("version"),
        "graph_hash": graph.get("hash"),
        "current_state": current_state,
        "transition": transition_id,
        "target_state": transition.get("to"),
        "required_evidence": required_evidence,
        "guard_results": guard_results,
        "created_new_session": False,
    }
    if diagnostics:
        return {
            **base,
            "status": "rejected",
            "accepted": False,
            "fail_closed": True,
            "failed_guards": failed_guards,
            "missing_evidence": missing_evidence,
            "on_reject": transition.get("on_reject"),
            "diagnostics": diagnostics,
        }
    return {
        **base,
        "status": "accepted",
        "accepted": True,
        "fail_closed": False,
        "failed_guards": [],
        "missing_evidence": [],
        "on_reject": None,
        "diagnostics": [],
    }
def scan_no_dod017_execution_flow_artifacts(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    found = sorted(str(path) for path in base.rglob("execution-flow.*") if path.is_file())
    if found:
        return {
            "status": "validation_failed",
            "accepted": False,
            "fail_closed": True,
            "created_new_session": False,
            "target": "dod017_no_go_scope",
            "found": found,
            "diagnostics": [
                {
                    "code": "dod017_execution_flow_artifact",
                    "field": "path",
                    "path": path,
                    "reason": "DOD-017 execution-flow artifacts are out of scope for DOD-016",
                }
                for path in found
            ],
        }
    return {
        "status": "ok",
        "accepted": True,
        "fail_closed": False,
        "created_new_session": False,
        "target": "dod017_no_go_scope",
        "found": [],
        "diagnostics": [],
    }
