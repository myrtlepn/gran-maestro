from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, Iterable


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import test_dod011_rehydration_contract as dod011


SID = "MST-AGI-030-20260505T040506000Z-dod014aa"
OTHER_SID = "MST-AGI-030-20260505T040507000Z-dod014bb"
ROOT = "AGI-030"
REQ = "REQ-817"
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_stdout_json(stdout: str) -> dict:
    for index, line in enumerate(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            payload = json.loads("\n".join(stdout.splitlines()[index:]))
            assert isinstance(payload, dict)
            return payload
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _canonical_event(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_event(event)).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _history_dir(workspace: Path, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "sessions" / session_id


def _history_path(workspace: Path, session_id: str = SID) -> Path:
    return _history_dir(workspace, session_id) / "history.ndjson"


def _snapshot_path(workspace: Path, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"


def _history_rows(workspace: Path, session_id: str = SID) -> list[dict]:
    return [
        json.loads(line)
        for line in _history_path(workspace, session_id).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _history_events(workspace: Path, session_id: str = SID) -> list[dict]:
    events: list[dict] = []
    for row in _history_rows(workspace, session_id):
        event = row.get("event")
        if isinstance(event, dict):
            events.append(event)
    return events


def _session_dirs(workspace: Path) -> list[str]:
    sessions = workspace / ".gran-maestro" / "sessions"
    return sorted(path.name for path in sessions.iterdir() if path.is_dir()) if sessions.is_dir() else []


def _canonical_fingerprint(workspace: Path, session_id: str = SID) -> dict:
    paths = {
        "history": _history_path(workspace, session_id),
        "head": _history_dir(workspace, session_id) / "history.head",
        "verify": _history_dir(workspace, session_id) / "history.verify",
        "snapshot": _snapshot_path(workspace, session_id),
    }
    return {
        "sessions": _session_dirs(workspace),
        "files": {
            key: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for key, path in paths.items()
        },
    }


def _base_context(head: str, *, session_id: str = SID) -> dict:
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
                "transition_source": "context_compaction",
                "transition_depth": 1,
                "chain_id": "dod014-chain",
                "critical_blocker": None,
            },
            "current_skill": "mst:request",
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


def _run_mst(
    workspace: Path,
    policy_home: Path,
    *args: str,
    session_id: str | None = SID,
    context: dict | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return dod011._run_mst(
        workspace,
        policy_home,
        *args,
        session_id=session_id,
        context=context,
        extra_env=extra_env,
    )


def _run_stop_hook(
    workspace: Path,
    policy_home: Path,
    payload: dict,
    *,
    session_id: str = SID,
    head: str,
) -> subprocess.CompletedProcess[str]:
    return dod011._run_stop_hook(
        workspace,
        policy_home,
        payload,
        session_id=session_id,
        context=_base_context(head, session_id=session_id),
        extra_env={"MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
    )


def _seed_auto_workspace(workspace: Path, policy_home: Path, *, session_id: str = SID) -> str:
    head = dod011._seed_canonical_workspace(
        workspace,
        policy_home,
        session_id=session_id,
        next_skill="mst:approve",
        next_source=REQ,
    )
    snapshot_path = _snapshot_path(workspace, session_id)
    snapshot = _read_json(snapshot_path)
    snapshot["auto"] = True
    snapshot["next_action"] = copy.deepcopy(NEXT_ACTION)
    snapshot["continuation"] = {
        "mode": "continue_unless_critical",
        "next_action": copy.deepcopy(NEXT_ACTION),
        "last_transition": "continue.rehydrate_retry",
        "transition_source": "context_compaction",
        "transition_depth": 1,
        "chain_id": "dod014-chain",
        "critical_blocker": None,
        "circuit_breaker": {"key": None, "count": 0, "limit": 3, "open": False},
    }
    _write_json(snapshot_path, snapshot)
    return head


def _seed_stop_hook_state(workspace: Path, *, session_id: str = SID, next_action: dict | None = None) -> None:
    action = copy.deepcopy(next_action or NEXT_ACTION)
    _write_json(
        workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "workflow_active": True,
            "current_skill": "mst:request",
            "active_req": REQ,
            "iteration": 4,
            "agile_loop_active": True,
            "agile_auto_mode_active": True,
            "next_action": action,
            "continuation": {
                "mode": "continue_unless_critical",
                "next_action": action,
                "transition_source": action.get("transition_source", "context_compaction"),
                "critical_blocker": None,
            },
            "updated_at": "2026-05-05T04:05:09.000Z",
        },
    )


def _append_history_event(workspace: Path, policy_home: Path, event: dict, *, session_id: str = SID) -> str:
    from scripts.mst_cmds import hook as hook_cmds

    hook_cmds.append_history_event(workspace, policy_home, session_id, event)
    return (_history_dir(workspace, session_id) / "history.head").read_text(encoding="utf-8").strip()


def _append_partial_event_without_heads(workspace: Path, event: dict, *, session_id: str = SID) -> str:
    rows = _history_rows(workspace, session_id)
    last = rows[-1]
    prev_hash = last["event_hash"]
    event_hash = _event_hash(prev_hash, event)
    row = {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": ROOT,
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "idempotency_key": event["idempotency_key"],
        "event": event,
        "event_hash": event_hash,
        "prev_hash": prev_hash,
        "seq": int(last["seq"]) + 1,
    }
    with _history_path(workspace, session_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return event_hash


def _set_snapshot_history(workspace: Path, *, head: str, session_id: str = SID) -> None:
    snapshot_path = _snapshot_path(workspace, session_id)
    snapshot = _read_json(snapshot_path)
    snapshot["history"] = {
        "ledger_path": f".gran-maestro/sessions/{session_id}/history.ndjson",
        "last_event_id": head,
        "head_hash": head,
    }
    _write_json(snapshot_path, snapshot)


def _run_history_verify(workspace: Path, policy_home: Path, *, session_id: str = SID) -> subprocess.CompletedProcess[str]:
    from scripts.mst_cmds import hook as hook_cmds

    argv = ["history", "verify", "--session", session_id, "--json"]
    try:
        result = hook_cmds._load_validated_history(
            project_root=workspace,
            policy_home=policy_home,
            raw_session_id=session_id,
        )
    except hook_cmds.HistoryValidationError as exc:
        payload = {"status": "error", "code": exc.code, "message": exc.message, **exc.details}
        return subprocess.CompletedProcess(argv, 2, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", exc.message)
    payload = {
        "status": "ok",
        "mst_session_id": result.session_id,
        "root_mst_id": result.root_mst_id,
        "tail": {"event_hash": result.tail_hash, "seq": result.tail_seq},
        "verify": result.verify,
        "history_path": str(result.history_file),
    }
    return subprocess.CompletedProcess(argv, 0, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", "")


def _is_state_inconsistency_payload(payload: dict) -> bool:
    candidates = {
        str(payload.get("code") or ""),
        str(payload.get("event_type") or ""),
        str(payload.get("terminal_event") or ""),
        str(payload.get("transition") or ""),
        str(payload.get("failure_class") or ""),
    }
    blocker = payload.get("critical_blocker")
    if isinstance(blocker, dict):
        candidates.add(str(blocker.get("type") or ""))
        candidates.add(str(blocker.get("event_type") or ""))
    return bool(candidates & {"terminal.state_inconsistency", "state_inconsistency"})


def _assert_state_inconsistency_non_success(result: subprocess.CompletedProcess[str]) -> dict:
    payload = _read_stdout_json(result.stdout)
    assert result.returncode != 0 or payload.get("status") not in {"ok", "success"}, payload
    assert payload.get("created_new_session") is not True, payload
    assert payload.get("prompt_summary_used_as_source") is not True, payload
    assert _is_state_inconsistency_payload(payload), (
        "DOD-014 inconsistency must be surfaced as terminal.state_inconsistency "
        f"or equivalent critical blocker evidence, got: {payload}"
    )
    return payload


def _assert_no_canonical_mutation(before: dict, workspace: Path, *, session_id: str = SID) -> None:
    assert _canonical_fingerprint(workspace, session_id) == before


def _replay_projection(workspace: Path, *, session_id: str = SID) -> dict:
    projection = {
        "workflow": {"current_skill": "", "next_skill": "", "next_source": "", "status": ""},
        "history": {"last_event_id": "", "head_hash": ""},
    }
    last_hash = ""
    for row in _history_rows(workspace, session_id):
        event = row["event"]
        event_type = str(event.get("event_type") or "")
        last_hash = row["event_hash"]
        if event_type.startswith("skill."):
            projection["workflow"]["current_skill"] = str(event.get("skill") or "")
            projection["workflow"]["status"] = str(event.get("status") or "active")
        next_action = event.get("next_action")
        if isinstance(next_action, dict):
            projection["workflow"]["next_skill"] = str(next_action.get("expected_skill") or next_action.get("skill") or "")
            projection["workflow"]["next_source"] = str(next_action.get("source_id") or next_action.get("source") or "")
    projection["history"] = {"last_event_id": last_hash, "head_hash": last_hash}
    return projection


def test_partial_write_state_inconsistency() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        _set_snapshot_history(workspace, head=head)
        _append_partial_event_without_heads(
            workspace,
            {
                "schema_version": 1,
                "event_id": "evt-dod014-partial",
                "idempotency_key": f"{SID}:skill.step:partial-write",
                "mst_session_id": SID,
                "root_mst_id": ROOT,
                "event_type": "skill.step",
                "type": "skill.step",
                "skill": "mst:request",
                "artifact_id": REQ,
                "created_at": "2026-05-05T04:05:10.000Z",
            },
        )
        before_sessions = _session_dirs(workspace)

        result = _run_history_verify(workspace, policy_home)

        payload = _assert_state_inconsistency_non_success(result)
        assert payload.get("code") not in {"ok", "success", "terminal.completed"}, payload
        assert _session_dirs(workspace) == before_sessions


def test_valid_snapshot_projection_matches_replay() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        action_event = {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "event_type": "continue.queued_action",
            "type": "continue.queued_action",
            "created_at": "2026-05-05T04:05:11.000Z",
            "artifact_id": REQ,
            "next_action": copy.deepcopy(NEXT_ACTION),
            "idempotency_key": f"{SID}:continue.queued_action:valid-projection",
        }
        head = _append_history_event(workspace, policy_home, action_event)
        _set_snapshot_history(workspace, head=head)
        snapshot = _read_json(_snapshot_path(workspace))
        snapshot["workflow"]["current_skill"] = "mst:request"
        snapshot["workflow"]["next_skill"] = "mst:approve"
        snapshot["workflow"]["next_source"] = REQ
        snapshot["workflow"]["status"] = "active"
        _write_json(_snapshot_path(workspace), snapshot)

        result = _run_history_verify(workspace, policy_home)
        replay = _replay_projection(workspace)
        snapshot = _read_json(_snapshot_path(workspace))

        assert result.returncode == 0, result.stderr
        assert replay["history"]["last_event_id"] == snapshot["history"]["last_event_id"]
        assert replay["workflow"]["next_skill"] == snapshot["workflow"]["next_skill"]
        assert replay["workflow"]["next_source"] == snapshot["workflow"]["next_source"]


def test_ledger_head_mismatch_blocks_continuation() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        _set_snapshot_history(workspace, head="e" * 64)
        before = _canonical_fingerprint(workspace)

        result = _run_mst(workspace, policy_home, "recover", ROOT, context=_base_context(head=head))

        payload = _assert_state_inconsistency_non_success(result)
        assert payload.get("mst_session_id") == SID, payload
        assert payload.get("root_mst_id") in {ROOT, None}, payload
        _assert_no_canonical_mutation(before, workspace)


def test_replay_mismatch_is_non_success() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        _seed_auto_workspace(workspace, policy_home)
        head = _append_history_event(
            workspace,
            policy_home,
            {
                "schema_version": 1,
                "mst_session_id": SID,
                "root_mst_id": ROOT,
                "event_type": "continue.queued_action",
                "type": "continue.queued_action",
                "created_at": "2026-05-05T04:05:12.000Z",
                "artifact_id": REQ,
                "next_action": copy.deepcopy(NEXT_ACTION),
                "idempotency_key": f"{SID}:continue.queued_action:replay-mismatch",
            },
        )
        _set_snapshot_history(workspace, head=head)
        snapshot = _read_json(_snapshot_path(workspace))
        snapshot["workflow"]["next_skill"] = "mst:wrong"
        snapshot["workflow"]["next_source"] = "REQ-000"
        snapshot["next_action"] = {"expected_skill": "mst:wrong", "source_id": "REQ-000", "auto": True}
        _write_json(_snapshot_path(workspace), snapshot)
        before = _canonical_fingerprint(workspace)

        result = _run_mst(workspace, policy_home, "recover", ROOT, context=_base_context(head=head))

        payload = _assert_state_inconsistency_non_success(result)
        assert "prompt" not in str(payload.get("source_precedence", "")).lower() or payload.get("prompt_summary_used_as_source") is False
        _assert_no_canonical_mutation(before, workspace)


def test_auto_continuation_state_inconsistency_blocker() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        stale_context = _base_context("e" * 64)
        before = _canonical_fingerprint(workspace)

        result = _run_mst(
            workspace,
            policy_home,
            "state",
            "set",
            "--skill",
            "mst:approve",
            "--step",
            "1",
            "--total",
            "2",
            context=stale_context,
        )

        payload = _assert_state_inconsistency_non_success(result)
        assert payload.get("mst_session_id") == SID, payload
        assert payload.get("root_mst_id") in {ROOT, None}, payload
        assert payload.get("expected_history_head") or payload.get("history_head") or payload.get("critical_blocker"), payload
        assert payload.get("next_safe_action") or payload.get("attempted_recovery") or payload.get("critical_blocker"), payload
        _assert_no_canonical_mutation(before, workspace)
        assert head


def test_recursive_transition_guard_downgrades_write() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        snapshot = _read_json(_snapshot_path(workspace))
        snapshot["continuation"]["transition_source"] = "context_compaction"
        snapshot["continuation"]["transition_depth"] = 99
        snapshot["continuation"]["chain_id"] = "dod014-recursive-chain"
        _write_json(_snapshot_path(workspace), snapshot)
        before = _canonical_fingerprint(workspace)

        result = _run_mst(
            workspace,
            policy_home,
            "state",
            "set",
            "--skill",
            "mst:approve",
            "--step",
            "1",
            "--total",
            "2",
            context=_base_context(head),
        )

        payload = _assert_state_inconsistency_non_success(result)
        assert payload.get("write_allowed") is False or payload.get("next_safe_action") or payload.get("critical_blocker"), payload
        assert "inspect" in json.dumps(payload, ensure_ascii=False).lower(), payload
        _assert_no_canonical_mutation(before, workspace)


def test_fingerprint_circuit_breaker_scopes_repeated_failures() -> None:
    same_failure = {
        "tool": "Bash",
        "command": "python3 -m pytest -q tests/missing.py",
        "normalized_action": "bash:python3 -m pytest -q tests/missing.py",
        "normalized_error": "pytest:file-not-found",
        "transition_source": "context_compaction",
        "expected_skill": "mst:test",
        "source_id": REQ,
        "auto": True,
        "auto_mode": True,
    }
    different_source = {**same_failure, "transition_source": "recover"}

    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)

        attempts = [same_failure, same_failure, different_source, same_failure]
        for index, action in enumerate(attempts, 1):
            _seed_stop_hook_state(workspace, next_action=action)
            result = _run_stop_hook(
                workspace,
                policy_home,
                {
                    "hook_event_name": "Stop",
                    "mst_session_id": SID,
                    "last_assistant_message": f"Recoverable failure attempt {index}",
                    "queued_action": action,
                    "failure": {"normalized_error": action["normalized_error"]},
                },
                head=head,
            )
            assert result.returncode == 0, result.stderr

        circuit_events = [
            event for event in _history_events(workspace)
            if isinstance(event.get("circuit_breaker"), dict)
        ]
        assert circuit_events, f"missing circuit breaker evidence: {_history_events(workspace)}"
        keys = [event["circuit_breaker"]["key"] for event in circuit_events]
        expected_same_key = (
            f"{SID}:context_compaction:{same_failure['normalized_action']}:"
            f"{same_failure['normalized_error']}"
        )
        expected_recover_key = (
            f"{SID}:recover:{same_failure['normalized_action']}:"
            f"{same_failure['normalized_error']}"
        )
        assert expected_same_key in keys, keys
        assert expected_recover_key in keys, keys
        same_counts = [
            event["circuit_breaker"]["count"]
            for event in circuit_events
            if event["circuit_breaker"]["key"] == expected_same_key
        ]
        assert same_counts == [1, 2, 3], same_counts
        terminal_repeat = [
            event for event in _history_events(workspace)
            if event.get("event_type") == "terminal.repeat_failure_limit"
            or (event.get("critical_blocker") or {}).get("type") == "repeat_failure_limit"
        ]
        assert terminal_repeat, f"circuit open must be terminal.repeat_failure_limit, got {_history_events(workspace)}"
        assert not any(event.get("event_type") == "terminal.completed" for event in _history_events(workspace))


TESTS: list[Callable[[], None]] = [
    test_partial_write_state_inconsistency,
    test_valid_snapshot_projection_matches_replay,
    test_ledger_head_mismatch_blocks_continuation,
    test_replay_mismatch_is_non_success,
    test_auto_continuation_state_inconsistency_blocker,
    test_recursive_transition_guard_downgrades_write,
    test_fingerprint_circuit_breaker_scopes_repeated_failures,
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
