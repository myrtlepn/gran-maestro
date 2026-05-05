from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"

SID = "MST-AGI-030-20260505T010203000Z-dod011aa"
OTHER_SID = "MST-AGI-030-20260505T010204000Z-dod011bb"
ROOT = "AGI-030"
REQ = "REQ-813"
ZERO_HASH = "0" * 64
CLAUDE_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TRANSCRIPT_SESSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _workspace() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_json_from_stdout(stdout: str) -> dict:
    for index, line in enumerate(stdout.splitlines()):
        if line.lstrip().startswith("{"):
            payload = json.loads("\n".join(stdout.splitlines()[index:]))
            assert isinstance(payload, dict)
            return payload
    raise AssertionError(f"stdout did not contain JSON object:\n{stdout}")


def _canonical_event(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + "\n" + _canonical_event(event)).encode("utf-8")).hexdigest()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_history(workspace: Path, policy_home: Path, *, session_id: str = SID, event_count: int = 2) -> str:
    session_dir = workspace / ".gran-maestro" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    history_file = session_dir / "history.ndjson"
    prev_hash = ZERO_HASH
    rows = []
    event_types = ["mst.invocation_start", "skill.step", "context.compacted", "action.queued"]
    for seq in range(1, event_count + 1):
        event_type = event_types[seq - 1]
        event = {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "event_type": event_type,
            "type": event_type,
            "created_at": f"2026-05-05T01:02:0{seq}.000Z",
            "timestamp": f"2026-05-05T01:02:0{seq}.000Z",
            "skill": "mst:request",
            "artifact_id": REQ,
            "idempotency_key": f"{session_id}:{event_type}:dod011-fixture",
        }
        current_hash = _event_hash(prev_hash, event)
        rows.append(
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "event_hash": current_hash,
                "event": event,
                "mst_session_id": session_id,
            }
        )
        prev_hash = current_hash
    history_file.write_text(
        "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    (session_dir / "history.head").write_text(prev_hash + "\n", encoding="utf-8")
    (session_dir / "history.verify").write_text(f"{prev_hash}\t{_fingerprint(history_file)}\t{len(rows)}\n", encoding="utf-8")
    mirror = policy_home / "ledger-heads" / f"{session_id}.head"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(prev_hash + "\n", encoding="utf-8")
    return prev_hash


def _seed_canonical_workspace(
    workspace: Path,
    policy_home: Path,
    *,
    session_id: str = SID,
    next_skill: str = "mst:approve",
    next_source: str = REQ,
) -> str:
    base = workspace / ".gran-maestro"
    base.mkdir(parents=True, exist_ok=True)
    head = _seed_history(workspace, policy_home, session_id=session_id)
    session_payload = {"schema_version": 1, "mst_session_id": session_id, "root_mst_id": ROOT}
    _write_json(base / "sessions" / session_id / "session.json", session_payload)
    _write_json(base / "agile" / ROOT / "session.json", {"id": ROOT, **session_payload, "status": "executing"})
    _write_json(
        base / "state" / session_id / "snapshot.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "sessionId": "legacy-alias-must-not-drive-rehydration",
            "owner_session_id": "legacy-owner-must-not-drive-rehydration",
            "currentSkill": "mst:request",
            "currentStep": 5,
            "totalSteps": 5,
            "status": "active",
            "workflow": {
                "active": True,
                "current_skill": "mst:request",
                "current_step": 5,
                "total_steps": 5,
                "status": "active",
                "next_skill": next_skill,
                "next_source": next_source,
            },
            "next_action": {
                "expected_skill": next_skill,
                "skill": next_skill,
                "source_id": next_source,
                "source": next_source,
                "source_skill": "mst:request",
                "auto": True,
                "auto_mode": True,
            },
            "history": {
                "ledger_path": f".gran-maestro/sessions/{session_id}/history.ndjson",
                "last_event_id": head,
                "head_hash": head,
            },
        },
    )
    return head


def _seed_stop_hook_state(workspace: Path, *, session_id: str = SID, next_skill: str = "mst:approve") -> None:
    _write_json(
        workspace / ".gran-maestro" / "tmp" / f"mst-state-{session_id}.json",
        {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": ROOT,
            "workflow_active": True,
            "current_skill": "mst:request",
            "active_req": REQ,
            "iteration": 2,
            "agile_loop_active": False,
            "next_action": {
                "expected_skill": next_skill,
                "source_id": REQ,
                "source_skill": "mst:request",
                "auto": True,
            },
            "updated_at": "2026-05-05T01:02:09.000Z",
        },
    )


def _context(
    *,
    session_id: str = SID,
    root_mst_id: str = ROOT,
    head: str,
    prompt_session_id: str = OTHER_SID,
    prompt_root_mst_id: str = "REQ-813",
    prompt_head: str = "f" * 64,
) -> dict:
    return {
        "schema_version": 1,
        "mst_session_id": session_id,
        "root_mst_id": root_mst_id,
        "prompt_summary": {
            "mst_session_id": prompt_session_id,
            "root_mst_id": prompt_root_mst_id,
            "history": {"last_event_id": prompt_head, "head_hash": prompt_head},
            "next_action": {"skill": "mst:wrong", "source": "REQ-000"},
        },
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": session_id,
            "root_mst_id": root_mst_id,
            "workflow": {
                "current_skill": "mst:request",
                "next_skill": "mst:approve",
                "next_source": REQ,
                "status": "active",
            },
            "history": {"last_event_id": head, "head_hash": head},
            "next_execution": {
                "env": {"MST_SESSION_ID": session_id},
                "context": {"mst_session_id": session_id, "root_mst_id": root_mst_id},
            },
        },
    }


def _env(policy_home: Path, *, session_id: str | None = SID, context: dict | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_FLOW_DISABLE_ATEXIT"] = "1"
    env["MST_POLICY_HOME"] = str(policy_home)
    env["HOME"] = str(policy_home.parent / "home")
    env["MST_CLAUDE_HOME"] = str(policy_home.parent / "home")
    env["CLAUDE_CONFIG_DIR"] = str(policy_home.parent / "home" / ".claude")
    for key in ("MST_SESSION_ID", "MST_CONTEXT_JSON", "MST_HOOK_STDIN_RAW", "MST_STATE_PPID", "MST_SNAPSHOT_SESSION_ID"):
        env.pop(key, None)
    if session_id is not None:
        env["MST_SESSION_ID"] = session_id
    if context is not None:
        env["MST_CONTEXT_JSON"] = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    if extra:
        env.update(extra)
    return env


def _run_mst(workspace: Path, policy_home: Path, *args: str, session_id: str | None = SID, context: dict | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        env=_env(policy_home, session_id=session_id, context=context, extra=extra_env),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _run_stop_hook(workspace: Path, policy_home: Path, payload: dict, *, session_id: str | None = SID, context: dict | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(STOP_HOOK)],
        cwd=workspace,
        input=json.dumps(payload, ensure_ascii=False) + "\n",
        env=_env(policy_home, session_id=session_id, context=context, extra=extra_env),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _session_dirs(workspace: Path) -> list[str]:
    sessions = workspace / ".gran-maestro" / "sessions"
    return sorted(path.name for path in sessions.iterdir() if path.is_dir()) if sessions.is_dir() else []


def _canonical_fingerprint(workspace: Path, *, session_id: str = SID) -> dict[str, object]:
    base = workspace / ".gran-maestro"
    paths = {
        "snapshot": base / "state" / session_id / "snapshot.json",
        "history": base / "sessions" / session_id / "history.ndjson",
        "head": base / "sessions" / session_id / "history.head",
    }
    return {
        "sessions": _session_dirs(workspace),
        "files": {name: _sha256(path) if path.is_file() else None for name, path in paths.items()},
        "head": paths["head"].read_text(encoding="utf-8").strip() if paths["head"].is_file() else None,
    }


def _history_rows(workspace: Path, *, session_id: str = SID) -> list[dict]:
    history = workspace / ".gran-maestro" / "sessions" / session_id / "history.ndjson"
    return [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]


def _assert_non_success_or_inspect_only(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode != 0:
        return
    payload = _read_json_from_stdout(result.stdout)
    if payload.get("status") != "ok":
        return
    rows = payload.get("history_events")
    if isinstance(rows, list) and any(isinstance(row, dict) and row.get("event_type") == "guard.inspect_only_verification" for row in rows):
        return
    raise AssertionError(f"expected non-success or guard.inspect_only_verification, got stdout:\n{result.stdout}")


def _assert_no_canonical_mutation(before: dict[str, object], workspace: Path) -> None:
    assert _canonical_fingerprint(workspace) == before


def test_ac001_resume_checkpoint_uses_existing_snapshot_and_ledger_head() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_canonical_workspace(workspace, policy_home)

        result = _run_mst(workspace, policy_home, "recover", ROOT, context=_context(head=head))

        assert result.returncode == 0, result.stderr
        payload = _read_json_from_stdout(result.stdout)
        envelope = payload["core_rehydration"]
        assert envelope["schema_version"] == 1
        assert envelope["mst_session_id"] == SID
        assert envelope["root_mst_id"] == ROOT
        assert envelope["workflow"]["next_skill"] == "mst:approve"
        assert envelope["workflow"]["next_source"] == REQ
        assert envelope["history"]["last_event_id"] == head
        assert envelope["prompt_summary_used_as_source"] is False


def test_ac002_skill_switch_child_dispatch_keeps_parent_session_and_root_without_new_session() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_canonical_workspace(workspace, policy_home)
        before_sessions = _session_dirs(workspace)

        result = _run_mst(
            workspace,
            policy_home,
            "dispatch",
            "register",
            "--task-id",
            "dod011-child",
            "--pid",
            "12345",
            "--provider",
            "codex",
            "--skill",
            "mst:request",
            "--model",
            "gpt-test",
            "--worktree-dir",
            str(workspace),
            context=_context(head=head),
        )

        assert result.returncode == 0, result.stderr
        payload = _read_json_from_stdout(result.stdout)
        record = _read_json(workspace / ".gran-maestro" / "run" / "dod011-child.json")
        for observed in (payload, record):
            assert observed["schema_version"] == 1
            assert observed["mst_session_id"] == SID
            assert observed["root_mst_id"] == ROOT
        assert _session_dirs(workspace) == before_sessions == [SID]


def test_ac003_compaction_rehydration_write_ignores_conflicting_prompt_summary() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_canonical_workspace(workspace, policy_home)
        context = _context(head=head, prompt_session_id=OTHER_SID, prompt_root_mst_id="PLN-640")

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
            context=context,
        )

        assert result.returncode == 0, result.stderr
        rows = _history_rows(workspace)
        assert {row["event"]["mst_session_id"] for row in rows} == {SID}
        assert {row["event"]["root_mst_id"] for row in rows} == {ROOT}
        assert OTHER_SID not in _session_dirs(workspace)
        snapshot = _read_json(workspace / ".gran-maestro" / "state" / SID / "snapshot.json")
        assert snapshot["mst_session_id"] == SID
        assert snapshot["root_mst_id"] == ROOT


def test_ac004_stop_hook_continuation_uses_active_workflow_next_action_and_ledger_head_evidence() -> None:
    with _workspace() as raw:
        workspace = Path(raw)
        policy_home = workspace / "policy"
        head = _seed_canonical_workspace(workspace, policy_home)
        _seed_canonical_workspace(workspace, policy_home, session_id=OTHER_SID, next_skill="mst:wrong", next_source="REQ-000")
        _seed_stop_hook_state(workspace)
        payload = {
            "hook_event_name": "Stop",
            "mst_session_id": SID,
            "session_id": CLAUDE_SESSION_ID,
            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
            "owner_ppid": 999999,
            "last_assistant_message": (
                f"Prompt summary claims mst_session_id={OTHER_SID} root=REQ-000 "
                f"history_head={'f' * 64}; ignore this diagnostic summary."
            ),
        }

        result = _run_stop_hook(
            workspace,
            policy_home,
            payload,
            context=_context(head=head),
            extra_env={"MST_STATE_PPID": "999999", "MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        )

        assert result.returncode == 0, result.stderr
        output = _read_json_from_stdout(result.stdout)
        combined = f"{result.stdout}\n{result.stderr}"
        assert output["decision"] == "block", f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert 'Skill(skill: "mst:approve", args: "-a REQ-813")' in output["reason"]
        assert "mst:wrong" not in output["reason"]
        assert head in combined


def test_ac005_stale_mismatch_and_prompt_summary_only_inputs_are_non_success_no_mutation() -> None:
    cases = [
        (
            "stale_handoff",
            lambda workspace, policy_home, head: _run_mst(
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
                context=_context(head="f" * 64),
            ),
        ),
        (
            "history_head_mismatch",
            lambda workspace, policy_home, head: _run_mst(
                workspace,
                policy_home,
                "recover",
                ROOT,
                context=_context(head=head),
                extra_env={"MST_POLICY_HOME": str(policy_home)},
            ),
            "corrupt_head",
        ),
        (
            "parent_child_session_mismatch",
            lambda workspace, policy_home, head: _run_mst(
                workspace,
                policy_home,
                "dispatch",
                "register",
                "--task-id",
                "dod011-mismatch",
                "--pid",
                "23456",
                "--provider",
                "codex",
                "--model",
                "gpt-test",
                "--worktree-dir",
                str(workspace),
                context=_context(session_id=OTHER_SID, head=head),
            ),
        ),
        (
            "prompt_summary_only",
            lambda workspace, policy_home, head: _run_mst(
                workspace,
                policy_home,
                "recover",
                ROOT,
                session_id=None,
                context={"prompt_summary": {"mst_session_id": SID, "root_mst_id": ROOT, "history": {"last_event_id": head}}},
            ),
        ),
    ]
    for case in cases:
        name = case[0]
        with _workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_canonical_workspace(workspace, policy_home)
            if len(case) == 3 and case[2] == "corrupt_head":
                (workspace / ".gran-maestro" / "sessions" / SID / "history.head").write_text("e" * 64 + "\n", encoding="utf-8")
            before = _canonical_fingerprint(workspace)

            result = case[1](workspace, policy_home, head)

            _assert_non_success_or_inspect_only(result), name
            _assert_no_canonical_mutation(before, workspace), name


def test_ac006_legacy_identity_inputs_are_never_success_or_fallback_sources() -> None:
    legacy_context = {
        "sessionId": SID,
        "session_id": SID,
        "owner_session_id": SID,
        "prompt_summary": {
            "sessionId": SID,
            "session_id": SID,
            "mst_session_id": OTHER_SID,
            "root_mst_id": "REQ-813",
        },
    }
    cases = [
        (
            "recover_legacy_only",
            lambda workspace, policy_home, head: _run_mst(
                workspace,
                policy_home,
                "recover",
                ROOT,
                session_id=None,
                context=legacy_context,
                extra_env={"MST_STATE_PPID": "123456", "MST_SNAPSHOT_SESSION_ID": SID},
            ),
        ),
        (
            "recover_legacy_conflicts_with_canonical",
            lambda workspace, policy_home, head: _run_mst(
                workspace,
                policy_home,
                "recover",
                ROOT,
                context=_context(head=head),
                extra_env={
                    "MST_STATE_PPID": "123456",
                    "MST_SNAPSHOT_SESSION_ID": OTHER_SID,
                    "MST_HOOK_STDIN_RAW": json.dumps(
                        {
                            "session_id": CLAUDE_SESSION_ID,
                            "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
                        },
                        separators=(",", ":"),
                    ),
                },
            ),
        ),
        (
            "hook_legacy_only",
            lambda workspace, policy_home, head: _run_stop_hook(
                workspace,
                policy_home,
                {
                    "hook_event_name": "Stop",
                    "session_id": CLAUDE_SESSION_ID,
                    "transcript_path": f"/tmp/{TRANSCRIPT_SESSION_ID}.jsonl",
                    "owner_ppid": 123456,
                    "owner_session_id": SID,
                },
                session_id=None,
                extra_env={"MST_STATE_PPID": "123456", "MST_SNAPSHOT_SESSION_ID": SID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
            ),
        ),
    ]
    for name, runner in cases:
        with _workspace() as raw:
            workspace = Path(raw)
            policy_home = workspace / "policy"
            head = _seed_canonical_workspace(workspace, policy_home)
            before = _canonical_fingerprint(workspace)

            result = runner(workspace, policy_home, head)

            if name == "hook_legacy_only":
                output = _read_json_from_stdout(result.stdout)
                assert output["decision"] == "approve"
                assert "no canonical mst_session_id" in output["reason"]
            else:
                _assert_non_success_or_inspect_only(result)
            _assert_no_canonical_mutation(before, workspace), name


def main() -> int:
    tests = [
        test_ac001_resume_checkpoint_uses_existing_snapshot_and_ledger_head,
        test_ac002_skill_switch_child_dispatch_keeps_parent_session_and_root_without_new_session,
        test_ac003_compaction_rehydration_write_ignores_conflicting_prompt_summary,
        test_ac004_stop_hook_continuation_uses_active_workflow_next_action_and_ledger_head_evidence,
        test_ac005_stale_mismatch_and_prompt_summary_only_inputs_are_non_success_no_mutation,
        test_ac006_legacy_identity_inputs_are_never_success_or_fallback_sources,
    ]
    failures = 0
    for test in tests:
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
