from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Callable, Iterable


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import test_dod011_rehydration_contract as dod011


SID = "MST-AGI-030-20260505T020304000Z-dod012aa"
OTHER_SID = "MST-AGI-030-20260505T020305000Z-dod012bb"
ROOT = "AGI-030"
REQ = "REQ-815"
ZERO_HASH = "0" * 64

NEXT_ACTION = {
    "expected_skill": "mst:approve",
    "skill": "mst:approve",
    "source_id": REQ,
    "source": REQ,
    "source_skill": "mst:request",
    "auto": True,
    "auto_mode": True,
}


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_stdout_json(stdout: str) -> dict:
    return dod011._read_json_from_stdout(stdout)


def _seed_auto_workspace(
    workspace: Path,
    policy_home: Path,
    *,
    session_id: str = SID,
    next_action: dict | None = None,
) -> str:
    action = dict(next_action or NEXT_ACTION)
    head = dod011._seed_canonical_workspace(
        workspace,
        policy_home,
        session_id=session_id,
        next_skill=str(action.get("expected_skill") or action.get("skill") or "mst:approve"),
        next_source=str(action.get("source_id") or action.get("source") or REQ),
    )
    snapshot_path = workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"
    snapshot = _read_json(snapshot_path)
    snapshot["auto"] = True
    snapshot["next_action"] = action
    snapshot["continuation"] = {
        "mode": "continue_unless_critical",
        "next_action": action,
        "last_transition": "continue.rehydrate_retry",
        "transition_source": "context_compaction",
        "transition_depth": 1,
        "critical_blocker": None,
        "circuit_breaker": {
            "key": None,
            "count": 0,
            "limit": 3,
            "open": False,
        },
    }
    _write_json(snapshot_path, snapshot)
    return head


def _seed_auto_stop_hook_state(
    workspace: Path,
    *,
    session_id: str = SID,
    next_action: dict | None = None,
) -> None:
    action = dict(next_action or NEXT_ACTION)
    _write_json(
        workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "workflow_active": True,
            "current_skill": "mst:request",
            "active_req": REQ,
            "iteration": 3,
            "agile_loop_active": True,
            "agile_auto_mode_active": True,
            "next_action": action,
            "continuation": {
                "mode": "continue_unless_critical",
                "next_action": action,
                "critical_blocker": None,
            },
            "updated_at": "2026-05-05T02:03:09.000Z",
        },
    )


def _context(head: str, *, session_id: str = SID) -> dict:
    return {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": ROOT,
        "prompt_summary": {
            "mst_session_id": OTHER_SID,
            "root_mst_id": "REQ-000",
            "history": {"last_event_id": "f" * 64, "head_hash": "f" * 64},
            "next_action": {"skill": "mst:wrong", "source": "REQ-000"},
        },
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "auto": True,
            "continuation": {
                "mode": "continue_unless_critical",
                "next_action": NEXT_ACTION,
                "critical_blocker": None,
            },
            "workflow": {
                "current_skill": "mst:request",
                "next_skill": "mst:approve",
                "next_source": REQ,
                "status": "active",
            },
            "history": {"last_event_id": head, "head_hash": head},
            "next_execution": {
                "env": {"MST_SESSION_ID": session_id},
                "context": {"mst_session_id": session_id, "root_mst_id": ROOT},
            },
        },
    }


def _run_recover(workspace: Path, policy_home: Path, head: str, *, session_id: str = SID):
    return dod011._run_mst(workspace, policy_home, "recover", ROOT, session_id=session_id, context=_context(head, session_id=session_id))


def _run_stop_hook(
    workspace: Path,
    policy_home: Path,
    payload: dict,
    *,
    session_id: str = SID,
    head: str,
):
    # These contract scenarios exercise the full Python judge and ledger path.
    # Use the runtime's 5s judge budget so host load cannot turn a behavior
    # assertion into the wrapper's intentional 500ms fail-open fallback.
    return dod011._run_stop_hook(
        workspace,
        policy_home,
        payload,
        session_id=session_id,
        context=_context(head, session_id=session_id),
        extra_env={
            "MST_STOP_HOOK_CLEANUP_DISABLE": "1",
            "MST_HOOK_JUDGE_TIMEOUT_MS": "5000",
        },
    )


def _history_events(workspace: Path, *, session_id: str = SID) -> list[dict]:
    rows = dod011._history_rows(workspace, session_id=session_id)
    events = []
    for row in rows:
        event = row.get("event")
        if isinstance(event, dict):
            events.append(event)
    return events


def _event_types(workspace: Path, *, session_id: str = SID) -> list[str]:
    return [str(event.get("event_type") or event.get("type") or "") for event in _history_events(workspace, session_id=session_id)]


def _find_events(workspace: Path, predicate: Callable[[dict], bool], *, session_id: str = SID) -> list[dict]:
    return [event for event in _history_events(workspace, session_id=session_id) if predicate(event)]


def _assert_has_continue_event(workspace: Path, *, session_id: str = SID) -> dict:
    matches = _find_events(
        workspace,
        lambda event: str(event.get("event_type") or event.get("type") or "").startswith("continue."),
        session_id=session_id,
    )
    assert matches, f"expected continue.* event, got event types: {_event_types(workspace, session_id=session_id)}"
    return matches[-1]


def _assert_no_terminal_user_wait(workspace: Path, *, session_id: str = SID) -> None:
    forbidden = {
        "terminal.user_wait",
        "terminal.waiting_for_user",
        "terminal.ask_user_question",
        "terminal.prevent_continuation",
    }
    seen = set(_event_types(workspace, session_id=session_id))
    assert not (seen & forbidden), f"terminal user-wait event recorded without critical evidence: {seen & forbidden}"


def _critical_blocker(event: dict) -> dict | None:
    blocker = event.get("critical_blocker")
    return blocker if isinstance(blocker, dict) else None


def _assert_structured_blocker(event: dict) -> dict:
    blocker = _critical_blocker(event)
    assert isinstance(blocker, dict), f"missing critical_blocker object: {event}"
    for field in ("type", "evidence", "attempted_recovery", "next_safe_action", "mst_session_id", "history_head"):
        assert field in blocker, f"critical_blocker missing {field}: {blocker}"
        assert blocker[field] not in ("", None, []), f"critical_blocker field {field} is empty: {blocker}"
    assert blocker["mst_session_id"] == SID
    return blocker


def test_auto_continuation_policy_persists_through_recover_bundle() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)

        result = _run_recover(workspace, policy_home, head)

        assert result.returncode == 0, result.stderr
        core = _read_stdout_json(result.stdout)["core_rehydration"]
        assert core["mst_session_id"] == SID
        assert core["root_mst_id"] == ROOT
        assert core["auto"] is True
        continuation = core["continuation"]
        assert continuation["mode"] == "continue_unless_critical"
        assert continuation["next_action"]["expected_skill"] == "mst:approve"
        assert continuation["next_action"]["source_id"] == REQ
        assert continuation["critical_blocker"] is None


def test_recoverable_issue_records_continue_transition_and_next_action_execution_evidence() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        _seed_auto_stop_hook_state(workspace)

        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": "Recoverable hook blocking output observed; continue with queued action.",
                "hook_output": {"preventContinuation": True, "reason": "transient hook output"},
            },
            head=head,
        )

        assert result.returncode == 0, result.stderr
        event = _assert_has_continue_event(workspace)
        assert event["event_type"] in {
            "continue.hook_blocking_observed",
            "continue.queued_action",
            "continue.rehydrate_retry",
            "continue.recoverable_issue",
        }
        assert event.get("next_action") or event.get("next_action_execution"), event
        execution_events = _find_events(
            workspace,
            lambda item: str(item.get("event_type") or "").startswith("action.")
            and item.get("next_action") is not None,
        )
        assert execution_events, f"missing next action execution evidence: {_event_types(workspace)}"


def test_user_wait_guard_redirects_without_critical_evidence() -> None:
    attempts = [
        ("ask_user_question", '{"tool_name":"AskUserQuestion","question":"Continue?"}'),
        ("text_confirmation", "Continue? Waiting for user confirmation before the next step."),
        ("self_paced_stop", "I will pause here and resume in the next session."),
        ("prevent_continuation", "Stop hook preventContinuation requested without critical evidence."),
    ]
    for name, last_message in attempts:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_auto_workspace(workspace, policy_home)
            _seed_auto_stop_hook_state(workspace)

            result = _run_stop_hook(
                workspace,
                policy_home,
                {
                    "hook_event_name": "Stop",
                    "mst_session_id": SID,
                    "last_assistant_message": last_message,
                    "preventContinuation": True,
                },
                head=head,
            )

            assert result.returncode == 0, f"{name}: {result.stderr}"
            output = _read_stdout_json(result.stdout)
            assert output["decision"] == "block", f"{name}: stdout={result.stdout!r}"
            _assert_no_terminal_user_wait(workspace)
            redirect_events = _find_events(
                workspace,
                lambda event: str(event.get("event_type") or event.get("type") or "") in {
                    "continue.queued_action",
                    "guard.inspect_only_verification",
                },
            )
            assert redirect_events, f"{name}: missing redirect evidence, got {_event_types(workspace)}"


def test_blocker_evidence_is_structured_before_user_wait_is_allowed() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        _seed_auto_stop_hook_state(workspace)

        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": (
                    "[MST stop_intent reason=unrecoverable_external_failure] "
                    "External authentication is unavailable after read-only verification."
                ),
                "critical_blocker_candidate": {
                    "type": "external_auth_unavailable",
                    "evidence": ["auth probe returned 401"],
                    "attempted_recovery": ["read-only credential presence check"],
                    "next_safe_action": "request security confirmation",
                },
            },
            head=head,
        )

        assert result.returncode == 0, result.stderr
        blocker_events = _find_events(workspace, lambda event: _critical_blocker(event) is not None)
        assert blocker_events, f"missing critical blocker event: {_event_types(workspace)}"
        blocker = _assert_structured_blocker(blocker_events[-1])
        assert blocker["type"] in {
            "external_auth_unavailable",
            "security_confirmation_required",
            "state_inconsistency",
            "repeat_failure_limit",
        }


def test_security_boundary_records_confirmation_required_and_does_not_start_original_action() -> None:
    destructive_action = {
        "tool": "Bash",
        "command": "rm -rf /shared/release-cache",
        "expected_skill": "mst:run",
        "source_id": REQ,
        "auto": True,
        "auto_mode": True,
        "scope": "destructive_external_shared_state",
    }
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home, next_action=destructive_action)
        _seed_auto_stop_hook_state(workspace, next_action=destructive_action)

        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": "About to execute queued destructive shared-state action.",
                "queued_action": destructive_action,
            },
            head=head,
        )

        assert result.returncode == 0, result.stderr
        security_events = _find_events(
            workspace,
            lambda event: str(event.get("event_type") or "") == "terminal.security_confirmation_required"
            or (_critical_blocker(event) or {}).get("type") == "security_confirmation_required",
        )
        assert security_events, f"missing security confirmation blocker: {_event_types(workspace)}"
        started = _find_events(
            workspace,
            lambda event: str(event.get("event_type") or "") == "action.started"
            and event.get("action") == destructive_action,
        )
        assert not started, f"destructive action must not be started automatically: {started}"


def test_action_classification_precedes_blocker_declaration_from_prose() -> None:
    queued_action = {
        "tool": "Bash",
        "command": "python3 -m pytest -q tests/test_dod011_rehydration_contract.py",
        "expected_skill": "mst:test",
        "source_id": REQ,
        "auto": True,
        "auto_mode": True,
        "scope_hint": "read_only_local_reversible",
    }
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home, next_action=queued_action)
        _seed_auto_stop_hook_state(workspace, next_action=queued_action)

        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": "I am uncertain, so this is a critical blocker.",
                "queued_action": queued_action,
            },
            head=head,
        )

        assert result.returncode == 0, result.stderr
        classification_events = _find_events(
            workspace,
            lambda event: isinstance(event.get("action_classification"), dict),
        )
        assert classification_events, f"missing action classification evidence: {_event_types(workspace)}"
        classification = classification_events[-1]["action_classification"]
        assert classification["source"] == "queued_action_tool_envelope"
        assert classification["scope"] in {"read_only", "local_reversible", "read_only_local_reversible"}
        assert classification.get("classifier_failure_kind") in {
            None,
            "unavailable",
            "parse_failure",
            "transcript_too_long",
            "projection_error",
            "policy_missing",
        }
        alternatives = classification.get("safe_alternatives")
        assert isinstance(alternatives, list) and alternatives, classification
        prose_only_blockers = _find_events(
            workspace,
            lambda event: (_critical_blocker(event) or {}).get("evidence_source") == "assistant_prose_only",
        )
        assert not prose_only_blockers, prose_only_blockers


def test_retry_circuit_key_is_session_action_error_scoped_and_resets_on_progress() -> None:
    same_failure = {
        "tool": "Bash",
        "command": "python3 -m pytest -q tests/missing.py",
        "normalized_action": "bash:python3 -m pytest -q tests/missing.py",
        "normalized_error": "pytest:file-not-found",
    }
    different_action = {**same_failure, "command": "python3 -m pytest -q tests/other_missing.py", "normalized_action": "bash:python3 -m pytest -q tests/other_missing.py"}
    sid_attempts = [
        (SID, same_failure, "pytest:file-not-found"),
        (SID, same_failure, "pytest:file-not-found"),
        (SID, different_action, "pytest:file-not-found"),
        (SID, same_failure, "pytest:assertion-failed"),
    ]

    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        # A root metadata pair names one exact active session. Exercise the
        # other-session key while that pair is authoritative, then activate
        # SID; keeping two same-root sessions "active" at once is invalid
        # under REQ-946 strict persistence corroboration.
        other_head = _seed_auto_workspace(
            workspace, policy_home, session_id=OTHER_SID, next_action=same_failure
        )
        _seed_auto_stop_hook_state(workspace, session_id=OTHER_SID, next_action=same_failure)
        other_result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": OTHER_SID,
                "last_assistant_message": "Recoverable failure in another canonical session.",
                "queued_action": same_failure,
                "failure": {"normalized_error": same_failure["normalized_error"]},
            },
            session_id=OTHER_SID,
            head=other_head,
        )
        assert other_result.returncode == 0, other_result.stderr

        heads = {
            SID: _seed_auto_workspace(workspace, policy_home, session_id=SID, next_action=same_failure),
        }

        for index, (session_id, action, normalized_error) in enumerate(sid_attempts, 1):
            _seed_auto_stop_hook_state(workspace, session_id=session_id, next_action=action)
            result = _run_stop_hook(
                workspace,
                policy_home,
                {
                    "hook_event_name": "Stop",
                    "mst_session_id": session_id,
                    "last_assistant_message": f"Recoverable failure attempt {index}: {normalized_error}",
                    "queued_action": action,
                    "failure": {"normalized_error": normalized_error},
                },
                session_id=session_id,
                head=heads[session_id],
            )
            assert result.returncode == 0, result.stderr
            # REQ-946 strict parent-pair corroboration requires the next hook
            # context to carry the latest persisted history head per session.
            heads[session_id] = (
                workspace / ".gran-maestro" / "sessions" / session_id / "history.head"
            ).read_text(encoding="utf-8").strip()

        progress_event = {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "event_type": "action.completed",
            "type": "action.completed",
            "created_at": "2026-05-05T02:03:59.000Z",
            "action": same_failure,
            "normalized_action": same_failure["normalized_action"],
            "idempotency_key": f"{SID}:action.completed:progress",
        }
        from scripts.mst_cmds import hook as hook_cmds

        hook_cmds.append_history_event(workspace, policy_home, SID, progress_event)
        heads[SID] = (
            workspace / ".gran-maestro" / "sessions" / SID / "history.head"
        ).read_text(encoding="utf-8").strip()
        _seed_auto_stop_hook_state(workspace, session_id=SID, next_action=same_failure)
        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": "Failure after meaningful state progress should start a fresh counter.",
                "queued_action": same_failure,
                "failure": {"normalized_error": same_failure["normalized_error"]},
            },
            session_id=SID,
            head=heads[SID],
        )
        assert result.returncode == 0, result.stderr

        circuit_events = [
            *_find_events(
                workspace,
                lambda event: isinstance(event.get("circuit_breaker"), dict),
                session_id=SID,
            ),
            *_find_events(
                workspace,
                lambda event: isinstance(event.get("circuit_breaker"), dict),
                session_id=OTHER_SID,
            ),
        ]
        assert circuit_events, f"missing circuit breaker events: {_event_types(workspace)}"
        counters: dict[str, list[int]] = {}
        for event in circuit_events:
            circuit = event["circuit_breaker"]
            key = circuit.get("key")
            count = circuit.get("count")
            if isinstance(key, str) and isinstance(count, int):
                counters.setdefault(key, []).append(count)

        expected_key = f"{SID}:{same_failure['normalized_action']}:{same_failure['normalized_error']}"
        assert counters.get(expected_key, [])[:2] == [1, 2], counters
        assert all("history_head" not in key for key in counters), counters
        assert len(counters) >= 4, counters
        assert counters[expected_key][-1] == 1, "counter must reset after action.completed progress"


TESTS: list[Callable[[], None]] = [
    test_auto_continuation_policy_persists_through_recover_bundle,
    test_recoverable_issue_records_continue_transition_and_next_action_execution_evidence,
    test_user_wait_guard_redirects_without_critical_evidence,
    test_blocker_evidence_is_structured_before_user_wait_is_allowed,
    test_security_boundary_records_confirmation_required_and_does_not_start_original_action,
    test_action_classification_precedes_blocker_declaration_from_prose,
    test_retry_circuit_key_is_session_action_error_scoped_and_resets_on_progress,
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
