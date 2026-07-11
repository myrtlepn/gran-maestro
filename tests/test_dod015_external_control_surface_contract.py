from __future__ import annotations

import argparse
import copy
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
import test_dod014_ledger_projection_contract as dod014


REPO_ROOT = Path(__file__).resolve().parents[1]

SID = "MST-AGI-030-20260505T050607000Z-dod015aa"
OTHER_SID = "MST-AGI-030-20260505T050608000Z-dod015bb"
ROOT = "AGI-030"
REQ = "REQ-818"

NEXT_ACTION = {
    "expected_skill": "mst:approve",
    "skill": "mst:approve",
    "source_id": REQ,
    "source": REQ,
    "source_skill": "mst:request",
    "auto": True,
    "auto_mode": True,
    "transition_source": "external_control_surface_contract",
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


def _snapshot_path(workspace: Path, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "state" / session_id / "snapshot.json"


def _history_path(workspace: Path, session_id: str = SID) -> Path:
    return workspace / ".gran-maestro" / "sessions" / session_id / "history.ndjson"


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


def _current_head(workspace: Path, session_id: str = SID) -> str:
    return (
        workspace / ".gran-maestro" / "sessions" / session_id / "history.head"
    ).read_text(encoding="utf-8").strip()


def _set_snapshot_history_head(workspace: Path, head: str, session_id: str = SID) -> None:
    snapshot_path = _snapshot_path(workspace, session_id)
    snapshot = _read_json(snapshot_path)
    snapshot["history"] = {
        "ledger_path": f".gran-maestro/sessions/{session_id}/history.ndjson",
        "last_event_id": head,
        "head_hash": head,
    }
    _write_json(snapshot_path, snapshot)


def _event_types(workspace: Path, session_id: str = SID) -> list[str]:
    return [str(event.get("event_type") or event.get("type") or "") for event in _history_events(workspace, session_id)]


def _find_events(workspace: Path, predicate: Callable[[dict], bool], session_id: str = SID) -> list[dict]:
    return [event for event in _history_events(workspace, session_id) if predicate(event)]


def _context(head: str, *, session_id: str = SID, next_action: dict | None = None) -> dict:
    action = copy.deepcopy(next_action or NEXT_ACTION)
    return {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": ROOT,
        "auto": True,
        "continuation": {
            "mode": "continue_unless_critical",
            "next_action": action,
            "critical_blocker": None,
            "transition_source": "external_control_surface_contract",
            "transition_depth": 1,
            "chain_id": "dod015-chain",
        },
        "prompt_summary": {
            "mst_session_id": OTHER_SID,
            "root_mst_id": "REQ-000",
            "history": {"last_event_id": "f" * 64, "head_hash": "f" * 64},
            "next_action": {"skill": "mst:wrong", "source": "REQ-000"},
            "summary": "This prompt summary is intentionally stale and diagnostic only.",
        },
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "auto": True,
            "continuation": {
                "mode": "continue_unless_critical",
                "next_action": action,
                "critical_blocker": None,
                "transition_source": "external_control_surface_contract",
                "transition_depth": 1,
                "chain_id": "dod015-chain",
            },
            "current_skill": "mst:request",
            "workflow": {
                "current_skill": "mst:request",
                "next_skill": str(action.get("expected_skill") or action.get("skill") or "mst:approve"),
                "next_source": str(action.get("source_id") or action.get("source") or REQ),
                "status": "active",
            },
            "history": {"last_event_id": head, "head_hash": head},
            "next_execution": {
                "env": {"MST_SESSION_ID": session_id, "MST_AUTO_CONTINUE": "true"},
                "context": {"mst_session_id": session_id, "root_mst_id": ROOT, "auto": True},
            },
            "execution_handoff": {
                "mst_session_id": session_id,
                "root_mst_id": ROOT,
                "next_action": action,
                "source": "core_rehydration",
            },
        },
    }


def _seed_auto_workspace(
    workspace: Path,
    policy_home: Path,
    *,
    session_id: str = SID,
    next_action: dict | None = None,
) -> str:
    action = copy.deepcopy(next_action or NEXT_ACTION)
    head = dod011._seed_canonical_workspace(
        workspace,
        policy_home,
        session_id=session_id,
        next_skill=str(action.get("expected_skill") or action.get("skill") or "mst:approve"),
        next_source=str(action.get("source_id") or action.get("source") or REQ),
    )
    snapshot_path = _snapshot_path(workspace, session_id)
    snapshot = _read_json(snapshot_path)
    snapshot["auto"] = True
    snapshot["next_action"] = action
    snapshot["continuation"] = {
        "mode": "continue_unless_critical",
        "next_action": action,
        "critical_blocker": None,
        "last_transition": "continue.rehydrate_retry",
        "transition_source": "external_control_surface_contract",
        "transition_depth": 1,
        "chain_id": "dod015-chain",
        "circuit_breaker": {"key": None, "count": 0, "limit": 3, "open": False},
    }
    _write_json(snapshot_path, snapshot)
    _write_json(
        workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "workflow_active": True,
            "current_skill": "mst:request",
            "active_req": REQ,
            "iteration": 5,
            "agile_loop_active": True,
            "agile_auto_mode_active": True,
            "next_action": action,
            "continuation": {
                "mode": "continue_unless_critical",
                "next_action": action,
                "critical_blocker": None,
                "transition_source": "external_control_surface_contract",
            },
            "updated_at": "2026-05-05T05:06:09.000Z",
        },
    )
    return head


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
    head: str,
    session_id: str = SID,
    next_action: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    return dod011._run_stop_hook(
        workspace,
        policy_home,
        payload,
        session_id=session_id,
        context=_context(head, session_id=session_id, next_action=next_action),
        extra_env={"MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
    )


def _assert_no_new_session_failure(result: subprocess.CompletedProcess[str], *, surface: str) -> dict:
    payload = _read_stdout_json(result.stdout)
    assert result.returncode != 0 or payload.get("status") not in {"ok", "success"}, payload
    assert payload.get("created_new_session") is False, payload
    assert payload.get("prompt_summary_used_as_source") is not True, payload
    assert payload.get("external_control_surface") == surface, (
        f"{surface} failure must identify the enforcing external control surface: {payload}"
    )
    return payload


def _assert_structured_blocker(event: dict) -> dict:
    blocker = event.get("critical_blocker")
    assert isinstance(blocker, dict), f"missing critical_blocker: {event}"
    for field in ("type", "evidence", "attempted_recovery", "next_safe_action", "mst_session_id", "history_head"):
        assert blocker.get(field) not in (None, "", []), f"critical_blocker missing {field}: {blocker}"
    assert blocker["mst_session_id"] == SID, blocker
    return blocker


def test_hook_enforcement_continues_without_user_wait() -> None:
    boundaries = ("Stop", "SubagentStop", "PreToolUse")
    for boundary in boundaries:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_auto_workspace(workspace, policy_home)

            result = _run_stop_hook(
                workspace,
                policy_home,
                {
                    "hook_event_name": boundary,
                    "mst_session_id": SID,
                    "last_assistant_message": f"{boundary} observed; continue queued action.",
                    "hook_output": {"preventContinuation": True, "reason": "recoverable boundary observation"},
                },
                head=head,
            )

            assert result.returncode == 0, result.stderr
            output = _read_stdout_json(result.stdout)
            assert output.get("decision") == "block", output
            assert "Skill(skill:" in str(output.get("reason") or "") or "next action" in str(output.get("reason") or "").lower(), output
            events = _find_events(
                workspace,
                lambda event: str(event.get("event_type") or "").startswith("continue.")
                and event.get("mst_session_id") == SID,
            )
            assert events, f"{boundary}: missing continuation event: {_event_types(workspace)}"
            event = events[-1]
            assert event.get("hook_boundary") == boundary, (
                f"{boundary}: continuation event must preserve Stop/SubagentStop/PreToolUse boundary evidence: {event}"
            )
            assert event.get("external_control_surface") == "hook", event
            assert event.get("critical_blocker") in (None, {}), event


def test_hook_user_wait_requires_structured_critical_blocker() -> None:
    destructive_action = {
        "tool": "Bash",
        "command": "deploy --target shared-production",
        "expected_skill": "mst:deploy",
        "source_id": REQ,
        "auto": True,
        "auto_mode": True,
        "scope": "external_service_credential_required",
        "transition_source": "external_control_surface_contract",
    }
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home, next_action=destructive_action)

        result = _run_stop_hook(
            workspace,
            policy_home,
            {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": "External credential approval is required before continuing.",
                "queued_action": destructive_action,
                "critical_blocker_candidate": {
                    "type": "external_credential_required",
                    "evidence": ["queued action requires external service credentials"],
                    "attempted_recovery": ["classified action scope", "checked read-only alternative"],
                    "next_safe_action": "request explicit credential approval",
                },
            },
            head=head,
            next_action=destructive_action,
        )

        assert result.returncode == 0, result.stderr
        blocker_events = _find_events(workspace, lambda event: isinstance(event.get("critical_blocker"), dict))
        assert blocker_events, f"missing structured blocker event: {_event_types(workspace)}"
        blocker_event = blocker_events[-1]
        blocker = _assert_structured_blocker(blocker_event)
        assert blocker["type"] in {"external_credential_required", "security_confirmation_required"}, blocker
        assert blocker_event.get("user_wait_transition") in {
            "terminal.user_wait",
            "terminal.security_confirmation_required",
        }, blocker_event
        assert blocker_event.get("external_control_surface") == "hook", blocker_event


def test_state_recover_mismatch_fails_closed_without_new_session() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        before_sessions = dod011._session_dirs(workspace)

        snapshot = _read_json(_snapshot_path(workspace))
        snapshot["mst_session_id"] = OTHER_SID
        _write_json(_snapshot_path(workspace), snapshot)
        state_result = _run_mst(workspace, policy_home, "state", "get", context=_context(head))
        _assert_no_new_session_failure(state_result, surface="state")
        assert dod011._session_dirs(workspace) == before_sessions

    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        before_sessions = dod011._session_dirs(workspace)
        (workspace / ".gran-maestro" / "sessions" / SID / "history.head").write_text("e" * 64 + "\n", encoding="utf-8")
        history_result = _run_mst(workspace, policy_home, "history", "verify", "--session", SID, "--json")
        _assert_no_new_session_failure(history_result, surface="history")
        assert dod011._session_dirs(workspace) == before_sessions

    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        before_sessions = dod011._session_dirs(workspace)
        stale_context = _context("f" * 64)
        recover_result = _run_mst(workspace, policy_home, "recover", ROOT, context=stale_context)
        _assert_no_new_session_failure(recover_result, surface="recover")
        assert dod011._session_dirs(workspace) == before_sessions
        assert head


def test_child_dispatch_inherits_parent_session_and_auto_policy() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        context = _context(head)
        (workspace / "prompt.md").write_text("DOD-015 child dispatch prompt\n", encoding="utf-8")

        build_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "build",
            "--provider",
            "codex",
            "--prompt-file",
            str(workspace / "prompt.md"),
            "--task-id",
            "REQ-818-child-artifact",
            "--worktree-dir",
            str(workspace),
            "--log-file",
            str(workspace / "child.log"),
            "--model",
            "gpt-test",
            context=context,
            extra_env={"MST_HOST": "headless"},
        )
        register_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "register",
            "--task-id",
            "REQ-818-child-artifact",
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--skill",
            "mst:child",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            context=context,
        )
        heartbeat_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "heartbeat",
            "--task-id",
            "REQ-818-child-artifact",
            "--phase",
            "running",
            context=context,
        )
        latest_head = _current_head(workspace)
        _set_snapshot_history_head(workspace, latest_head)
        recover_result = _run_mst(workspace, policy_home, "recover", ROOT, context=_context(latest_head))

        assert build_result.returncode == 0, build_result.stderr
        assert register_result.returncode == 0, register_result.stderr
        assert heartbeat_result.returncode == 0, heartbeat_result.stderr
        assert recover_result.returncode == 0, recover_result.stderr
        envelopes = [
            ("build", _read_stdout_json(build_result.stdout)),
            ("register", _read_stdout_json(register_result.stdout)),
            ("heartbeat", _read_stdout_json(heartbeat_result.stdout)),
            ("recover", _read_stdout_json(recover_result.stdout)["core_rehydration"]),
        ]
        for surface, envelope in envelopes:
            assert envelope.get("mst_session_id") == SID, (surface, envelope)
            assert envelope.get("root_mst_id") == ROOT, (surface, envelope)
            assert envelope.get("auto") is True, (surface, envelope)
            continuation = envelope.get("continuation")
            assert isinstance(continuation, dict), (surface, envelope)
            assert continuation.get("next_action", {}).get("source_id") == REQ, (surface, continuation)
            assert envelope.get("child_artifact_id") == "REQ-818-child-artifact", (surface, envelope)
            assert envelope.get("external_control_surface") == "dispatch", (surface, envelope)


def test_dispatch_register_heartbeat_preserve_auto_continuation_policy() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        context = _context(head)
        task_id = "REQ-818-child-artifact"

        register_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "register",
            "--task-id",
            task_id,
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--skill",
            "mst:child",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            context=context,
            extra_env={"MST_STATE_PPID": "77777"},
        )
        heartbeat_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "heartbeat",
            "--task-id",
            task_id,
            "--phase",
            "running",
            context=context,
            extra_env={"MST_PROVIDER_TASK_ID": OTHER_SID, "MST_STATE_PPID": "88888"},
        )

        assert register_result.returncode == 0, register_result.stderr
        assert heartbeat_result.returncode == 0, heartbeat_result.stderr
        for surface, payload in (
            ("register", _read_stdout_json(register_result.stdout)),
            ("heartbeat", _read_stdout_json(heartbeat_result.stdout)),
            ("run_state", _read_json(workspace / ".gran-maestro" / "run" / f"{task_id}.json")),
        ):
            assert payload["mst_session_id"] == SID, (surface, payload)
            assert payload["root_mst_id"] == ROOT, (surface, payload)
            assert payload["child_artifact_id"] == task_id, (surface, payload)
            assert payload["auto"] is True, (surface, payload)
            continuation = payload.get("continuation")
            assert isinstance(continuation, dict), (surface, payload)
            assert continuation.get("mode") == "continue_unless_critical", (surface, continuation)
            assert continuation.get("next_action", {}).get("source_id") == REQ, (surface, continuation)
            assert continuation.get("transition_depth") == 1, (surface, continuation)
            assert continuation.get("chain_id") == "dod015-chain", (surface, continuation)
            assert payload.get("pid") != payload["mst_session_id"], (surface, payload)
            assert str(payload.get("started_by_pid") or "") != payload["mst_session_id"], (surface, payload)
            assert payload.get("provider_task_id") != payload["mst_session_id"], (surface, payload)


def test_dispatch_context_mismatch_fails_closed() -> None:
    cases = [
        ("top_session", lambda context: context.update({"mst_session_id": OTHER_SID})),
        ("top_root", lambda context: context.update({"root_mst_id": "REQ-818"})),
        ("core_session", lambda context: context["core_rehydration"].update({"mst_session_id": OTHER_SID})),
        ("core_root", lambda context: context["core_rehydration"].update({"root_mst_id": "REQ-818"})),
        (
            "next_execution_env",
            lambda context: context["core_rehydration"]["next_execution"]["env"].update({"MST_SESSION_ID": OTHER_SID}),
        ),
        (
            "next_execution_context",
            lambda context: context["core_rehydration"]["next_execution"]["context"].update({"mst_session_id": OTHER_SID}),
        ),
    ]
    for name, mutate in cases:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_auto_workspace(workspace, policy_home)
            before_sessions = dod011._session_dirs(workspace)
            context = _context(head)
            mutate(context)

            result = _run_mst(
                workspace,
                policy_home,
                "dispatch",
                "register",
                "--task-id",
                f"REQ-818-{name}",
                "--pid",
                "12345",
                "--provider",
                "codex",
                "--skill",
                "mst:child",
                "--model",
                "gpt-test",
                "--worktree-dir",
                str(workspace),
                context=context,
            )

            _assert_no_new_session_failure(result, surface="dispatch")
            assert not (workspace / ".gran-maestro" / "run" / f"REQ-818-{name}.json").exists()
            assert dod011._session_dirs(workspace) == before_sessions


def test_core_rehydration_precedes_prompt_summary() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)

        result = _run_mst(workspace, policy_home, "recover", ROOT, context=_context(head))

        assert result.returncode == 0, result.stderr
        payload = _read_stdout_json(result.stdout)
        core = payload["core_rehydration"]
        assert core["mst_session_id"] == SID
        assert core["root_mst_id"] == ROOT
        assert core["next_execution"]["env"]["MST_SESSION_ID"] == SID
        assert core.get("prompt_summary_used_as_source") is False
        order = payload.get("context_delivery_order") or core.get("context_delivery_order")
        assert order == ["core_rehydration", "execution_flow_handoff", "prompt_summary"], payload
        handoff = core.get("execution_flow_handoff")
        assert isinstance(handoff, dict), core
        assert handoff.get("mst_session_id") == SID, handoff
        assert handoff.get("next_action", {}).get("source_id") == REQ, handoff


def _git_changed_files() -> list[str]:
    changed: set[str] = set()
    branch_result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    base_ref = "master"
    if current_branch.endswith(tuple(f"-T{task_id:02d}" for task_id in range(1, 100))):
        candidate = re.sub(r"-T\d{2}$", "", current_branch)
        if subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", candidate],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        ).returncode == 0:
            base_ref = candidate
    base_result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", "HEAD", base_ref],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if base_result.returncode == 0:
        base = base_result.stdout.strip()
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{base}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    for args in (("diff", "--name-only"), ("diff", "--name-only", "--cached"), ("ls-files", "--others", "--exclude-standard")):
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(changed)


def test_no_claude_code_core_source_modification() -> None:
    changed = _git_changed_files()
    allowed_prefixes = (
        ".claude/hooks/",
        "coverage-matrix.json",
        "coverage-matrix.md",
        "evidence-ledger.md",
        "hooks/",
        "scripts/",
        "skills/",
        "templates/state-machine/",
        "tests/",
        "verification-report.md",
    )
    allowed_paths = {
        "dashboard/mst-transition-graph.json",
        "src/flow-watcher.ts",
        "src/routes/flowApi.ts",
        "src/server.ts",
    }
    forbidden = [
        path
        for path in changed
        if path not in allowed_paths
        and not path.startswith(allowed_prefixes)
        or path.startswith(("src/claude-code-core/", "packages/claude-code-core/", "vendor/claude-code/"))
    ]
    assert not forbidden, f"Claude Code core or non-Gran-Maestro surface changed: {forbidden}; all changed={changed}"


def test_recoverable_issue_records_continuation_not_user_wait() -> None:
    scenarios = [
        (
            "transient_tool_failure",
            {"queued_action": {**NEXT_ACTION, "normalized_action": "bash:pytest tests/missing.py"}, "failure": {"normalized_error": "pytest:file-not-found"}},
        ),
        ("child_skill_exit", {"last_assistant_message": "[RETURN-TO] child skill exited return_to=mst:request/5"}),
        ("compaction_summary_missing", {"prompt_summary": None, "failure": {"normalized_error": "compaction:summary-missing"}}),
        ("recoverable_hook_observation", {"hook_output": {"preventContinuation": True, "reason": "temporary hook output"}}),
    ]
    forbidden = {"terminal.user_wait", "terminal.waiting_for_user", "terminal.completed"}
    for name, payload_extra in scenarios:
        with dod011._workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_auto_workspace(workspace, policy_home)
            payload = {
                "hook_event_name": "Stop",
                "mst_session_id": SID,
                "last_assistant_message": f"{name} is recoverable; continue automatically.",
                **payload_extra,
            }

            result = _run_stop_hook(workspace, policy_home, payload, head=head)

            assert result.returncode == 0, f"{name}: {result.stderr}"
            seen = set(_event_types(workspace))
            assert not (seen & forbidden), f"{name}: recoverable issue recorded terminal fallback: {seen & forbidden}"
            events = _find_events(
                workspace,
                lambda event: str(event.get("event_type") or "").startswith("continue.")
                or isinstance(event.get("attempted_recovery"), (dict, list, str)),
            )
            assert events, f"{name}: missing continuation or attempted recovery evidence: {seen}"
            event = events[-1]
            assert event.get("new_session_fallback") is False, event
            assert event.get("external_control_surface") in {"hook", "recover", "context", "history"}, event


def test_external_enforcement_records_same_session_ledger_evidence() -> None:
    with dod011._workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_auto_workspace(workspace, policy_home)
        _run_stop_hook(
            workspace,
            policy_home,
            {"hook_event_name": "Stop", "mst_session_id": SID, "hook_output": {"preventContinuation": True}},
            head=head,
        )
        latest_head = _current_head(workspace)
        _set_snapshot_history_head(workspace, latest_head)
        state_result = _run_mst(workspace, policy_home, "state", "get", context=_context(latest_head))
        register_result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "register",
            "--task-id",
            "REQ-818-child-artifact",
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--skill",
            "mst:child",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            context=_context(latest_head),
        )
        latest_head = _current_head(workspace)
        _set_snapshot_history_head(workspace, latest_head)
        recover_result = _run_mst(workspace, policy_home, "recover", ROOT, context=_context(latest_head))
        latest_head = _current_head(workspace)
        _set_snapshot_history_head(workspace, latest_head)

        assert state_result.returncode == 0, state_result.stderr
        assert register_result.returncode == 0, register_result.stderr
        assert recover_result.returncode == 0, recover_result.stderr
        events = _history_events(workspace)
        assert all(event.get("mst_session_id") == SID for event in events), events
        surfaces = {
            str(event.get("external_control_surface"))
            for event in events
            if event.get("external_control_surface")
        }
        assert {"hook", "state", "dispatch", "context"} <= surfaces, (
            f"missing same-ledger external control surface evidence; surfaces={surfaces} events={events}"
        )
        assert any(str(event.get("event_type") or "").startswith("continue.") for event in events), events
        assert any(isinstance(event.get("circuit_breaker"), dict) for event in events), events
        verify = dod014._run_history_verify(workspace, policy_home, session_id=SID)
        assert verify.returncode == 0, verify.stderr


TESTS: list[Callable[[], None]] = [
    test_hook_enforcement_continues_without_user_wait,
    test_hook_user_wait_requires_structured_critical_blocker,
    test_state_recover_mismatch_fails_closed_without_new_session,
    test_child_dispatch_inherits_parent_session_and_auto_policy,
    test_dispatch_register_heartbeat_preserve_auto_continuation_policy,
    test_dispatch_context_mismatch_fails_closed,
    test_core_rehydration_precedes_prompt_summary,
    test_no_claude_code_core_source_modification,
    test_recoverable_issue_records_continuation_not_user_wait,
    test_external_enforcement_records_same_session_ledger_evidence,
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
