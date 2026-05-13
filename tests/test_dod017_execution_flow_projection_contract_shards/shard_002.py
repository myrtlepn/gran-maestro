def test_rehydration_context_prefers_verified_handoff_over_llm_summary() -> None:
    module = _execution_flow_module()
    current_head = _source_head()
    handoff = _projection_fixture()["handoff_summary"]
    handoff["last_transition"] = "context.compacted"
    handoff["auto"] = True
    llm_summary = {
        "current_node": "llm.summary.wrong",
        "last_transition": "terminal.completed",
        "next_action": {"skill": "mst:wrong", "source_id": "REQ-000"},
        "critical_blocker": {"type": "llm_guess"},
        "flow_view": {
            "execution_flow_json": ".gran-maestro/sessions/wrong/execution-flow.json",
            "execution_flow_d2": ".gran-maestro/sessions/wrong/execution-flow.d2",
        },
    }
    core = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "auto": True,
        "continuation": {
            "mode": "continue_unless_critical",
            "next_action": {"skill": "mst:approve", "source_id": REQ},
            "critical_blocker": None,
        },
        "current_skill": "mst:request",
        "current_step": 2,
        "total_steps": 5,
        "history_last_event_id": current_head["history_head"],
    }

    result = _call_required(
        module,
        "assemble_rehydration_continuation_context",
        core,
        handoff,
        llm_summary,
        current_head,
    )

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("context_delivery_order") == [
        "core_rehydration",
        "execution_flow_handoff",
        "prompt_summary",
    ]
    budgeted = result.get("budgeted_context")
    assert isinstance(budgeted, dict), result
    consumed = budgeted.get("execution_flow_handoff")
    assert isinstance(consumed, dict), result
    for field in ("current_node", "last_transition", "next_action", "critical_blocker", "flow_view"):
        assert consumed[field] == handoff[field], (field, consumed, handoff, result)
    assert consumed["current_node"] != llm_summary["current_node"]
    assert consumed["last_transition"] != llm_summary["last_transition"]
    assert consumed["next_action"] != llm_summary["next_action"]
    assert consumed["flow_view"] != llm_summary["flow_view"]
    assert result.get("prompt_summary_used_as_source") is False
    assert result.get("source_precedence") == [
        "verified_history_ledger",
        "verified_execution_flow_handoff",
        "prompt_summary_diagnostic_only",
    ]
    assert result.get("next_action_execution_allowed") is True
    assert result.get("write_allowed") is True
def test_context_compaction_and_rehydration_events_share_session_ledger() -> None:
    module = _execution_flow_module()
    ledger = _ledger_fixture()
    handoff = _projection_fixture()["handoff_summary"]

    result = _call_required(module, "append_context_handoff_evidence_events", ledger, handoff)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    updated = result.get("ledger")
    assert isinstance(updated, dict), result
    rows = updated.get("rows")
    assert isinstance(rows, list), result
    events = [row.get("event") for row in rows if isinstance(row, dict)]
    context_events = [
        event for event in events
        if isinstance(event, dict) and event.get("event_type") in {"context.compacted", "context.rehydrated"}
    ]
    assert {event["event_type"] for event in context_events} >= {"context.compacted", "context.rehydrated"}
    assert {event["mst_session_id"] for event in context_events} == {SID}
    assert {event["root_mst_id"] for event in context_events} == {ROOT}
    assert result.get("mst_session_id") == SID
    assert result.get("same_session_ledger") is True
    assert result.get("event_append_evidence") == {
        "compacted": "context.compacted",
        "rehydrated": "context.rehydrated",
        "handoff_generated": True,
        "handoff_consumed": True,
    }
    rehydrated = [event for event in context_events if event["event_type"] == "context.rehydrated"][-1]
    assert rehydrated["execution_flow_handoff"]["history_head"] == handoff["history_head"]
    assert rehydrated["prompt_summary_used_as_source"] is False
def test_stale_handoff_blocks_auto_write_and_next_action() -> None:
    module = _execution_flow_module()
    current_head = _source_head()
    handoff = _projection_fixture()["handoff_summary"]
    handoff["history_head"] = "e" * 64

    result = _call_required(module, "validate_compaction_handoff_consumption", handoff, current_head)

    _assert_fail_closed(result, expected_code="stale_handoff")
    assert result.get("stale") is True, result
    assert result.get("write_allowed") is False, result
    assert result.get("auto_write_allowed") is False, result
    assert result.get("next_action_execution_allowed") is False, result
    assert result.get("on_stale_transition") == "guard.inspect_only_verification", result
    assert result.get("source_history_head") == "e" * 64, result
    assert result.get("current_history_head") == current_head["history_head"], result
    diagnostic = result["diagnostics"][0]
    assert diagnostic["field"] == "history_head"
    assert diagnostic["reason"]
def test_compaction_handoff_does_not_modify_claude_code_core() -> None:
    module = _execution_flow_module()
    changed_paths = [
        "scripts/mst_cmds/execution_flow.py",
        "scripts/mst_cmds/state.py",
        "hooks/mst-stop-hook.sh",
        "tests/test_dod017_execution_flow_projection_contract.py",
    ]

    result = _call_required(module, "validate_gran_maestro_owned_handoff_scope", changed_paths)

    assert isinstance(result, dict), result
    assert result.get("status") == "ok", result
    assert result.get("claude_code_core_modified") is False, result
    assert result.get("allowed_surface") == "gran_maestro_owned", result

    forbidden = _call_required(
        module,
        "validate_gran_maestro_owned_handoff_scope",
        ["/Users/brandev/git/claude-code/src/query.ts"],
    )
    _assert_fail_closed(forbidden, expected_code="claude_code_core_scope_violation")
    assert forbidden.get("claude_code_core_modified") is True, forbidden
TESTS: list[Callable[[], None]] = [
    test_ledger_replay_accepts_required_event_families,
    test_generated_execution_flow_is_derived_only,
    test_source_ledger_head_requires_minimum_evidence,
    test_projection_generator_writes_json_with_source_provenance,
    test_projection_generator_writes_d2_with_provenance_status,
    test_stale_projection_rejects_decision_consumption,
    test_projection_hash_tracks_generated_payload,
    test_projection_generation_requires_verified_ledger_source,
    test_dashboard_flow_view_reports_execution_flow_provenance,
    test_cli_flow_view_marks_stale_projection_read_only,
    test_graph_and_execution_flow_views_are_separate_artifacts,
    test_projection_never_authorizes_forbidden_graph_transition,
    test_hook_hot_path_never_full_replays_or_renders,
    test_hook_hot_path_uses_cursor_cache_for_current_flow_state,
    test_hook_cache_miss_routes_to_inspect_only_without_replay,
    test_compaction_handoff_contains_cursor_provenance_and_flow_paths,
    test_rehydration_context_prefers_verified_handoff_over_llm_summary,
    test_context_compaction_and_rehydration_events_share_session_ledger,
    test_stale_handoff_blocks_auto_write_and_next_action,
    test_compaction_handoff_does_not_modify_claude_code_core,
]
def _selected_tests(pattern: str | None) -> Iterable[Callable[[], None]]:
    if not pattern:
        return TESTS
    terms = [term.strip() for term in re.split(r"\s+or\s+", pattern) if term.strip()]
    return [test for test in TESTS if any(term in test.__name__ for term in terms)]
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", dest="pattern", default=None)
    args = parser.parse_args()

    selected = list(_selected_tests(args.pattern))
    if not selected:
        print(f"No tests selected for -k {args.pattern!r}", file=sys.stderr)
        return 5

    failures = 0
    for test in selected:
        try:
            test()
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}", file=sys.stderr)
            traceback.print_exc()
        else:
            print(f"PASS {test.__name__}")
    return 1 if failures else 0
if __name__ == "__main__":
    raise SystemExit(main())
