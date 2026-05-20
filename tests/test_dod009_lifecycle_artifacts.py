from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
SID = "MST-AGI-040-20260520T061430000Z-dod009a1"
PARENT_SID = "MST-AGI-040-20260520T061431000Z-dod009p1"
ROOT = "AGI-040"


def _context(extra: Optional[dict] = None) -> dict:
    payload = {
        "schema_version": 1,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
        "core_rehydration": {
            "schema_version": 1,
            "mst_session_id": SID,
            "root_mst_id": ROOT,
            "next_execution": {
                "env": {"MST_SESSION_ID": SID},
                "context": {"mst_session_id": SID, "root_mst_id": ROOT},
            },
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _env(*, context: Optional[dict] = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MST_SESSION_ID"] = SID
    env["MST_CONTEXT_JSON"] = json.dumps(
        _context() if context is None else context,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return env


def _run_mst(workspace: Path, *args: str, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MST_SCRIPT), *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _state_file(workspace: Path, task_id: str) -> Path:
    return workspace / ".gran-maestro" / "run" / f"{task_id}.json"


def _read_state(workspace: Path, task_id: str) -> dict:
    return json.loads(_state_file(workspace, task_id).read_text(encoding="utf-8"))


def _attempts_by_id(payload: dict) -> dict[str, dict]:
    attempts = payload.get("attempts")
    assert isinstance(attempts, list)
    result: dict[str, dict] = {}
    for attempt in attempts:
        assert isinstance(attempt, dict)
        attempt_id = str(attempt.get("attempt_id") or "").strip()
        assert attempt_id
        result[attempt_id] = attempt
    return result


def _project_lifecycle_consumer_summary(payload: dict) -> dict:
    from scripts.mst_cmds.current_work_handoff import project_lifecycle_artifact_consumer_summary

    summary = project_lifecycle_artifact_consumer_summary(payload)
    assert isinstance(summary, dict)
    return summary


def test_dispatch_register_records_lifecycle_schema_and_context_files_read(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    prompt_file = workspace / "prompt.md"
    prompt_file.write_text("REQ-920 prompt", encoding="utf-8")
    spec_file = workspace / "spec.md"
    spec_file.write_text("REQ-920 spec", encoding="utf-8")
    running_log = workspace / "running.log"

    env = _env(context=_context({"context_files": [str(spec_file)]}))
    result = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        "req-920-02-register",
        "--attempt-id",
        "req-920-02-a1",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--skill",
        "mst:request",
        "--model",
        "gpt-test",
        "--label",
        "phase2-impl",
        "--worktree-dir",
        str(workspace),
        "--running-log-path",
        str(running_log),
        "--parent-session-id",
        PARENT_SID,
        "--context-file",
        str(prompt_file),
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = _read_state(workspace, "req-920-02-register")
    assert payload["task_id"] == "req-920-02-register"
    assert payload["attempt_id"] == "req-920-02-a1"
    assert payload["provider"] == "codex"
    assert payload["model"] == "gpt-test"
    assert payload["label"] == "phase2-impl"
    assert payload["phase"] == "running"
    assert payload["status"] == "running"
    assert payload["running_log_path"] == str(running_log)
    assert payload["log_path"] == str(running_log)
    assert payload["worktree_dir"] == str(workspace)
    assert payload["parent_session_id"] == PARENT_SID
    assert payload["mst_session_id"] == SID
    assert payload["root_mst_id"] == ROOT
    assert isinstance(payload.get("started_at"), str) and payload["started_at"]
    assert isinstance(payload.get("last_heartbeat"), str) and payload["last_heartbeat"]

    context_files = payload["context_files_read"]
    assert isinstance(context_files, list)
    by_path = {entry["path"]: entry for entry in context_files}
    assert set(by_path) == {str(prompt_file), str(spec_file)}
    for path, entry in by_path.items():
        expected = Path(path)
        assert entry["exists"] is True
        assert entry["hash"].startswith("sha256:")
        assert entry["version"] == f"{expected.stat().st_size}:{expected.stat().st_mtime_ns}"

    attempts = _attempts_by_id(payload)
    assert attempts["req-920-02-a1"]["status"] == "running"
    assert attempts["req-920-02-a1"]["parent_session_id"] == PARENT_SID


def test_dispatch_heartbeat_and_finalization_record_logs_trace_and_structured_error(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    task_id = "req-920-02-heartbeat"
    running_log = workspace / "running.log"
    stdout_log = workspace / "stdout.log"
    stderr_log = workspace / "stderr.log"
    trace_path = workspace / "trace.md"
    transcript_path = workspace / "transcript.md"
    output_path = workspace / "output.json"
    running_log.write_text("running\n", encoding="utf-8")
    stdout_log.write_text("stdout payload\n", encoding="utf-8")
    stderr_log.write_text("stderr payload\n", encoding="utf-8")
    trace_path.write_text("trace payload\n", encoding="utf-8")
    transcript_path.write_text("summary payload\n", encoding="utf-8")
    output_path.write_text('{"ok":false}\n', encoding="utf-8")

    env = _env()
    register = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--attempt-id",
        "req-920-02-a2",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert register.returncode == 0, register.stderr

    first_payload = _read_state(workspace, task_id)
    first_heartbeat = first_payload["last_heartbeat"]
    time.sleep(0.02)

    heartbeat = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--phase",
        "running",
        "--running-log-path",
        str(running_log),
        "--stdout-log-path",
        str(stdout_log),
        "--stderr-log-path",
        str(stderr_log),
        "--trace-path",
        str(trace_path),
        "--transcript-summary-path",
        str(transcript_path),
        env=env,
    )
    assert heartbeat.returncode == 0, heartbeat.stderr

    heartbeat_payload = _read_state(workspace, task_id)
    assert heartbeat_payload["last_heartbeat"] != first_heartbeat
    assert heartbeat_payload["running_log_path"] == str(running_log)
    assert heartbeat_payload["stdout_log_path"] == str(stdout_log)
    assert heartbeat_payload["stderr_log_path"] == str(stderr_log)
    assert heartbeat_payload["trace_path"] == str(trace_path)
    assert heartbeat_payload["transcript_summary_path"] == str(transcript_path)
    assert all(path.exists() for path in (running_log, stdout_log, stderr_log, trace_path, transcript_path))

    final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "17",
        "--status",
        "failed",
        "--output-path",
        str(output_path),
        "--structured-error-json",
        '{"code":"provider_failed","message":"fixture failure"}',
        env=env,
    )
    assert final.returncode == 0, final.stderr

    final_payload = _read_state(workspace, task_id)
    assert final_payload["phase"] == "done"
    assert final_payload["status"] == "failed"
    assert final_payload["exit_code"] == 17
    assert isinstance(final_payload.get("terminated_at"), str) and final_payload["terminated_at"]
    assert final_payload["output_path"] == str(output_path)
    assert final_payload["structured_error"] == {
        "code": "provider_failed",
        "message": "fixture failure",
    }
    attempts = _attempts_by_id(final_payload)
    assert attempts["req-920-02-a2"]["status"] == "failed"
    assert attempts["req-920-02-a2"]["output_path"] == str(output_path)


def test_dispatch_fallback_attempts_preserve_distinct_attempt_ids_and_linkage(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    task_id = "req-920-02-fallback"
    env = _env()

    primary = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--attempt-id",
        "req-920-02-primary",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert primary.returncode == 0, primary.stderr

    primary_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "0",
        "--status",
        "empty_result",
        env=env,
    )
    assert primary_final.returncode == 0, primary_final.stderr

    fallback = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--attempt-id",
        "req-920-02-fallback",
        "--pid",
        "12345",
        "--provider",
        "gemini",
        "--model",
        "gpt-fallback",
        "--worktree-dir",
        str(workspace),
        "--fallback-from",
        "req-920-02-primary",
        env=env,
    )
    assert fallback.returncode == 0, fallback.stderr

    fallback_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "0",
        "--status",
        "fallback_completed",
        env=env,
    )
    assert fallback_final.returncode == 0, fallback_final.stderr

    payload = _read_state(workspace, task_id)
    assert payload["task_id"] == task_id
    assert payload["attempt_id"] == "req-920-02-fallback"
    assert payload["fallback_from"] == "req-920-02-primary"
    attempts = _attempts_by_id(payload)
    assert set(attempts) == {"req-920-02-primary", "req-920-02-fallback"}
    assert attempts["req-920-02-primary"]["status"] == "empty_result"
    assert attempts["req-920-02-primary"]["fallback_to"] == "req-920-02-fallback"
    assert attempts["req-920-02-fallback"]["fallback_from"] == "req-920-02-primary"
    assert attempts["req-920-02-fallback"]["status"] == "fallback_completed"


def test_run_wrapper_records_trace_completed_and_empty_result_artifacts(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    context_file = workspace / "context.md"
    context_file.write_text("context payload", encoding="utf-8")
    env = _env()

    success_log_dir = workspace / "logs-success"
    success = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-02-run-success",
        "--attempt-id",
        "req-920-02-run-a1",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--label",
        "phase2-impl",
        "--log-dir",
        str(success_log_dir),
        "--trace",
        "phase2/impl",
        "--parent-session-id",
        PARENT_SID,
        "--context-file",
        str(context_file),
        "--",
        "bash",
        "-lc",
        "printf 'dispatch output\\n'; printf 'stderr output\\n' >&2",
        env=env,
    )
    assert success.returncode == 0, success.stderr

    success_payload = _read_state(workspace, "req-920-02-run-success")
    assert success_payload["attempt_id"] == "req-920-02-run-a1"
    assert success_payload["status"] == "completed"
    assert success_payload["phase"] == "done"
    assert success_payload["label"] == "phase2-impl"
    assert success_payload["parent_session_id"] == PARENT_SID
    assert success_payload["output_path"] == str(success_log_dir / "stdout.log")
    assert success_payload["running_log_path"] == str(success_log_dir / "running.log")
    assert success_payload["stdout_log_path"] == str(success_log_dir / "stdout.log")
    assert success_payload["stderr_log_path"] == str(success_log_dir / "stderr.log")
    assert isinstance(success_payload.get("trace_path"), str) and success_payload["trace_path"]
    assert Path(success_payload["trace_path"]).exists()
    assert success_payload["structured_error"] is None
    assert success_payload["context_files_read"][0]["path"] == str(context_file)

    empty_log_dir = workspace / "logs-empty"
    empty = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-02-run-empty",
        "--attempt-id",
        "req-920-02-run-a2",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--log-dir",
        str(empty_log_dir),
        "--trace",
        "phase2/empty",
        "--",
        "bash",
        "-lc",
        "exit 0",
        env=env,
    )
    assert empty.returncode == 0, empty.stderr

    empty_payload = _read_state(workspace, "req-920-02-run-empty")
    assert empty_payload["status"] == "empty_result"
    assert empty_payload["output_path"] == str(empty_log_dir / "stdout.log")
    assert Path(empty_payload["trace_path"]).exists()


def test_run_wrapper_records_failed_status_and_structured_error(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    env = _env()

    log_dir = workspace / "logs-failed"
    result = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-02-run-failed",
        "--attempt-id",
        "req-920-02-run-a3",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--log-dir",
        str(log_dir),
        "--trace",
        "phase2/failed",
        "--",
        "bash",
        "-lc",
        "printf 'boom\\n' >&2; exit 3",
        env=env,
    )

    assert result.returncode == 3
    payload = _read_state(workspace, "req-920-02-run-failed")
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 3
    assert payload["structured_error"]["kind"] == "non_zero_exit"
    assert payload["structured_error"]["exit_code"] == 3
    assert payload["output_path"] == str(log_dir / "stdout.log")


def test_lifecycle_artifact_consumer_success_projects_register_heartbeat_trace_and_linkage(tmp_path):
    from scripts.mst_cmds.current_work_handoff import project_current_work_handoff

    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    context_file = workspace / "context.md"
    context_file.write_text("context payload", encoding="utf-8")
    env = _env()

    log_dir = workspace / "logs-success"
    result = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-03-consumer-success",
        "--attempt-id",
        "req-920-03-consumer-a1",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--label",
        "phase2-impl",
        "--log-dir",
        str(log_dir),
        "--trace",
        "phase2/success-consumer",
        "--parent-session-id",
        PARENT_SID,
        "--context-file",
        str(context_file),
        "--",
        "bash",
        "-lc",
        "printf 'dispatch output\\n'; printf 'stderr output\\n' >&2",
        env=env,
    )
    assert result.returncode == 0, result.stderr

    payload = _read_state(workspace, "req-920-03-consumer-success")
    summary = _project_lifecycle_consumer_summary(payload)
    assert summary["consumer_status"] == "success"
    assert summary["task_id"] == "req-920-03-consumer-success"
    assert summary["lifecycle_status"] == "completed"
    assert summary["attempt_linkage"] == {
        "task_id": "req-920-03-consumer-success",
        "attempt_id": "req-920-03-consumer-a1",
        "parent_session_id": PARENT_SID,
        "mst_session_id": SID,
        "root_mst_id": ROOT,
    }
    assert summary["current_attempt"]["attempt_id"] == "req-920-03-consumer-a1"
    assert summary["current_attempt"]["status"] == "completed"
    assert summary["artifacts"]["running_log"]["exists"] is True
    assert summary["artifacts"]["trace"]["exists"] is True
    assert summary["artifacts"]["output"]["exists"] is True
    assert summary["context_files_read"][0]["path"] == str(context_file)
    assert summary["gaps"] == []

    handoff = project_current_work_handoff(
        {
            "schema_version": 1,
            "mst_session_id": SID,
            "canonical_mst_session_id": SID,
            "generated_at": "2026-05-20T06:43:00Z",
            "identity": {
                "env": {"MST_SESSION_ID": SID},
                "context": {"mst_session_id": SID, "root_mst_id": ROOT},
            },
            "active_workflow": {
                "skill": "mst:request",
                "source_id": "REQ-920",
                "auto": True,
                "status": "active",
                "evidence_path": ".gran-maestro/requests/REQ-920/request.json",
            },
            "task_sources": [
                {
                    "kind": "request_task",
                    "id": "REQ-920-03",
                    "title": "Lifecycle consumer success",
                    "status": "running",
                    "owner": "codex-dev",
                    "phase": "phase2",
                    "source": "request.json",
                    "evidence_path": ".gran-maestro/requests/REQ-920/tasks/03/spec.md",
                }
            ],
            "dispatch_lifecycle_artifact": payload,
        }
    )
    lifecycle_consumer = handoff.get("lifecycle_artifact_consumer")
    assert isinstance(lifecycle_consumer, dict)
    assert lifecycle_consumer["consumer_status"] == "success"
    assert lifecycle_consumer["artifacts"]["running_log"]["path"] == str(log_dir / "running.log")


def test_lifecycle_artifact_consumer_failure_projects_structured_recovery_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    env = _env()

    log_dir = workspace / "logs-failed"
    result = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-03-consumer-failure",
        "--attempt-id",
        "req-920-03-consumer-a2",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--log-dir",
        str(log_dir),
        "--trace",
        "phase2/failure-consumer",
        "--",
        "bash",
        "-lc",
        "printf 'boom\\n' >&2; exit 3",
        env=env,
    )
    assert result.returncode == 3

    payload = _read_state(workspace, "req-920-03-consumer-failure")
    summary = _project_lifecycle_consumer_summary(payload)
    assert summary["consumer_status"] == "non_success"
    assert summary["lifecycle_status"] == "failed"
    assert summary["failure"] == {
        "status": "failed",
        "exit_code": 3,
        "structured_error": payload["structured_error"],
        "evidence_paths": [
            str(log_dir / "stdout.log"),
            str(log_dir / "stderr.log"),
            payload["trace_path"],
        ],
    }
    assert summary["artifacts"]["stderr_log"]["exists"] is True
    assert summary["artifacts"]["trace"]["exists"] is True
    assert summary["gaps"] == []


def test_lifecycle_artifact_consumer_fallback_preserves_distinct_attempt_relations(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    task_id = "req-920-03-consumer-fallback"
    env = _env()
    primary_log_dir = workspace / "logs-primary"
    primary_log_dir.mkdir(parents=True, exist_ok=True)
    primary_running = primary_log_dir / "running.log"
    primary_stdout = primary_log_dir / "stdout.log"
    primary_stderr = primary_log_dir / "stderr.log"
    primary_trace = primary_log_dir / "trace.md"
    primary_running.write_text("primary running\n", encoding="utf-8")
    primary_stdout.write_text("", encoding="utf-8")
    primary_stderr.write_text("", encoding="utf-8")
    primary_trace.write_text("primary trace\n", encoding="utf-8")

    primary = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--attempt-id",
        "req-920-03-primary",
        "--pid",
        "12345",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--worktree-dir",
        str(workspace),
        env=env,
    )
    assert primary.returncode == 0, primary.stderr
    primary_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "0",
        "--status",
        "empty_result",
        "--running-log-path",
        str(primary_running),
        "--stdout-log-path",
        str(primary_stdout),
        "--stderr-log-path",
        str(primary_stderr),
        "--trace-path",
        str(primary_trace),
        "--output-path",
        str(primary_stdout),
        env=env,
    )
    assert primary_final.returncode == 0, primary_final.stderr

    fallback_log_dir = workspace / "logs-fallback"
    fallback_log_dir.mkdir(parents=True, exist_ok=True)
    fallback_running = fallback_log_dir / "running.log"
    fallback_stdout = fallback_log_dir / "stdout.log"
    fallback_stderr = fallback_log_dir / "stderr.log"
    fallback_trace = fallback_log_dir / "trace.md"
    fallback_running.write_text("fallback running\n", encoding="utf-8")
    fallback_stdout.write_text("fallback output\n", encoding="utf-8")
    fallback_stderr.write_text("", encoding="utf-8")
    fallback_trace.write_text("fallback trace\n", encoding="utf-8")

    fallback = _run_mst(
        workspace,
        "dispatch",
        "register",
        "--task-id",
        task_id,
        "--attempt-id",
        "req-920-03-fallback",
        "--pid",
        "12345",
        "--provider",
        "gemini",
        "--model",
        "gpt-fallback",
        "--worktree-dir",
        str(workspace),
        "--fallback-from",
        "req-920-03-primary",
        env=env,
    )
    assert fallback.returncode == 0, fallback.stderr
    fallback_final = _run_mst(
        workspace,
        "dispatch",
        "heartbeat",
        "--task-id",
        task_id,
        "--final",
        "--exit-code",
        "0",
        "--status",
        "fallback_completed",
        "--running-log-path",
        str(fallback_running),
        "--stdout-log-path",
        str(fallback_stdout),
        "--stderr-log-path",
        str(fallback_stderr),
        "--trace-path",
        str(fallback_trace),
        "--output-path",
        str(fallback_stdout),
        env=env,
    )
    assert fallback_final.returncode == 0, fallback_final.stderr

    payload = _read_state(workspace, task_id)
    summary = _project_lifecycle_consumer_summary(payload)
    assert summary["consumer_status"] == "success"
    assert summary["lifecycle_status"] == "fallback_completed"
    attempts = {attempt["attempt_id"]: attempt for attempt in summary["attempts"]}
    assert set(attempts) == {"req-920-03-primary", "req-920-03-fallback"}
    assert attempts["req-920-03-primary"]["status"] == "empty_result"
    assert attempts["req-920-03-primary"]["fallback_to"] == "req-920-03-fallback"
    assert attempts["req-920-03-fallback"]["fallback_from"] == "req-920-03-primary"
    assert attempts["req-920-03-fallback"]["status"] == "fallback_completed"
    assert summary["gaps"] == []


def test_lifecycle_artifact_consumer_missing_fields_and_paths_report_structured_gap_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / ".gran-maestro").mkdir(parents=True, exist_ok=True)
    env = _env()

    log_dir = workspace / "logs-gap"
    result = _run_mst(
        workspace,
        "run",
        "--task-id",
        "req-920-03-consumer-gap",
        "--attempt-id",
        "req-920-03-consumer-a4",
        "--provider",
        "codex",
        "--model",
        "gpt-test",
        "--log-dir",
        str(log_dir),
        "--trace",
        "phase2/gap-consumer",
        "--",
        "bash",
        "-lc",
        "printf 'dispatch output\\n'",
        env=env,
    )
    assert result.returncode == 0, result.stderr

    payload = _read_state(workspace, "req-920-03-consumer-gap")
    trace_path = Path(payload["trace_path"])
    trace_path.unlink()
    payload.pop("attempt_id")

    summary = _project_lifecycle_consumer_summary(payload)
    assert summary["consumer_status"] == "gap"
    gap_codes = {gap["code"] for gap in summary["gaps"]}
    assert gap_codes == {"missing_referenced_file", "missing_required_field"}
    gap_fields = {gap["field"] for gap in summary["gaps"]}
    assert "attempt_id" in gap_fields
    assert "trace_path" in gap_fields
