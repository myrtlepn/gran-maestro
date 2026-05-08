import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from scripts.mst_cmds import dispatch


REPO_ROOT = Path(__file__).resolve().parents[1]
MST_SCRIPT = REPO_ROOT / "scripts" / "mst.py"
STOP_HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"
SESSION_ID = "MST-AGI-835-20260508T000000000Z-abcdef12"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _state(pid: int = 1234, pid_start_time: str = "start-1") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "task_id": "task-monitor-001",
        "provider": "codex",
        "pid": pid,
        "pid_start_time": pid_start_time,
        "phase": "running",
        "last_heartbeat": now,
    }


def _identity(pid: int = 1234, pid_start_time: str = "start-1", alive: bool = True) -> dict:
    return {"pid": pid, "pid_start_time": pid_start_time, "pid_alive": alive}


def test_output_stalled_event_after_two_idle_windows(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "same output\n")
    stderr = _write(tmp_path / "stderr.log", "")
    payload = _state()

    first = dispatch.evaluate_delegate_io_attention(
        payload,
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )
    assert first["appended"] == []

    second = dispatch.evaluate_delegate_io_attention(
        first["state"],
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )
    assert second["appended"] == []

    third = dispatch.evaluate_delegate_io_attention(
        second["state"],
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )

    assert len(third["appended"]) == 1
    event = third["appended"][0]
    assert event["kind"] == "delegate_io_attention"
    assert event["signal"] == "output_stalled"
    assert "output_unchanged" in event["reason_codes"]
    assert event["evidence"]["idle_windows"] == 2


def test_no_output_stalled_event_for_empty_streams_with_healthy_heartbeat(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "")
    stderr = _write(tmp_path / "stderr.log", "")
    payload = _state()

    result = {"state": payload, "appended": []}
    for index in range(4):
        state = dict(result["state"])
        state["last_heartbeat"] = (datetime.now(timezone.utc) + timedelta(seconds=index)).isoformat()
        result = dispatch.evaluate_delegate_io_attention(
            state,
            {"stdout": stdout, "stderr": stderr},
            process_identity=_identity(),
        )
        assert result["appended"] == []

    assert result["state"].get("delegate_io_attention_events", []) == []
    assert result["state"]["delegate_monitor"]["idle_windows"] >= 2


def test_prompt_suspect_events_include_stream_evidence_and_redaction(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "")
    stderr = _write(tmp_path / "stderr.log", "API_KEY=secret123\nDo you want to continue? [y/N]\n")

    result = dispatch.evaluate_delegate_io_attention(
        _state(),
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )

    assert len(result["appended"]) == 1
    event = result["appended"][0]
    assert event["signal"] == "stdin_prompt_suspected"
    assert "prompt_like_stderr" in event["reason_codes"]
    streams = event["evidence"]["streams"]
    assert streams["stderr"]["output_offset"] > 0
    assert streams["stderr"]["normalized_tail_hash"]
    assert "[REDACTED]" in streams["stderr"]["redacted_tail"]
    assert "secret123" not in streams["stderr"]["redacted_tail"]
    assert streams["stdout"]["output_offset"] == 0


def test_delegate_event_schema_required_fields(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "Continue? yes/no\n")
    stderr = _write(tmp_path / "stderr.log", "")

    event = dispatch.evaluate_delegate_io_attention(
        _state(),
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )["appended"][0]

    required = {
        "event_id",
        "task_id",
        "provider",
        "pid",
        "pid_start_time",
        "kind",
        "signal",
        "reason_codes",
        "confidence",
        "observed_at",
        "expires_at",
        "dedup_key",
        "evidence",
        "allowed_actions",
        "forbidden_reasons",
        "attempt_count",
        "max_attempts",
        "cooldown_until",
    }
    assert required <= set(event)
    assert event["kind"] == "delegate_io_attention"
    assert event["signal"] in {"output_stalled", "stdin_prompt_suspected", "heartbeat_stale"}
    assert event["allowed_actions"] == ["observe", "wait", "mark_blocked", "terminate_gracefully"]
    assert "stdin_write_disallowed" in event["forbidden_reasons"]


def test_suppression_and_duplicate_coalesce(tmp_path):
    stdout = _write(tmp_path / "stdout.log", "Continue? yes/no\n")
    stderr = _write(tmp_path / "stderr.log", "")
    paths = {"stdout": stdout, "stderr": stderr}

    terminal = dispatch.evaluate_delegate_io_attention(
        {**_state(), "phase": "done"},
        paths,
        process_identity=_identity(),
    )
    assert terminal["appended"] == []

    final_heartbeat = dispatch.evaluate_delegate_io_attention(
        {**_state(), "terminated_at": datetime.now(timezone.utc).isoformat()},
        paths,
        process_identity=_identity(),
    )
    assert final_heartbeat["appended"] == []

    pid_mismatch = dispatch.evaluate_delegate_io_attention(
        _state(),
        paths,
        process_identity=_identity(pid_start_time="other-start"),
    )
    assert pid_mismatch["appended"] == []

    first = dispatch.evaluate_delegate_io_attention(_state(), paths, process_identity=_identity())
    duplicate = dispatch.evaluate_delegate_io_attention(first["state"], paths, process_identity=_identity())
    assert duplicate["appended"] == []
    assert duplicate["coalesced"]
    stored = duplicate["state"]["delegate_io_attention_events"][0]
    assert stored["coalesce"]["count"] == 2
    assert stored["coalesce"]["last_seen_at"]


def test_monitor_does_not_write_stdin_or_run_remediation(tmp_path, monkeypatch):
    stdout = _write(tmp_path / "stdout.log", "Continue? yes/no\n")
    stderr = _write(tmp_path / "stderr.log", "")
    calls: list[tuple] = []

    monkeypatch.setattr(os, "write", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(os, "kill", lambda *args, **kwargs: calls.append(args))

    result = dispatch.evaluate_delegate_io_attention(
        _state(),
        {"stdout": stdout, "stderr": stderr},
        process_identity=_identity(),
    )

    assert len(result["appended"]) == 1
    assert calls == []


def _run_hook(project_root: Path, state: dict, run_state: Optional[dict] = None) -> dict:
    (project_root / ".git").write_text("gitdir: .\n", encoding="utf-8")
    (project_root / ".gran-maestro" / "tmp").mkdir(parents=True, exist_ok=True)
    (project_root / ".gran-maestro" / "run").mkdir(parents=True, exist_ok=True)
    state_path = project_root / ".gran-maestro" / "tmp" / f"mst-state-{SESSION_ID}.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if run_state is not None:
        run_path = project_root / ".gran-maestro" / "run" / f"{run_state['task_id']}.json"
        run_path.write_text(json.dumps(run_state), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(STOP_HOOK)],
        input=json.dumps({"last_assistant_message": "", "stop_hook_active": False}),
        cwd=project_root,
        capture_output=True,
        text=True,
        env={**os.environ, "MST_SESSION_ID": SESSION_ID, "MST_STOP_HOOK_CLEANUP_DISABLE": "1"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _pending_run_state() -> dict:
    now = datetime.now(timezone.utc)
    event = {
        "event_id": "evt-pending",
        "task_id": "task-monitor-001",
        "provider": "codex",
        "pid": 1234,
        "pid_start_time": "start-1",
        "kind": "delegate_io_attention",
        "signal": "stdin_prompt_suspected",
        "reason_codes": ["prompt_like_stdout"],
        "confidence": 0.82,
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "dedup_key": "dedup",
        "evidence": {"idle_windows": 0},
        "allowed_actions": ["observe", "wait", "mark_blocked", "terminate_gracefully"],
        "forbidden_reasons": ["stdin_write_disallowed"],
        "attempt_count": 1,
        "max_attempts": 3,
        "cooldown_until": (now + timedelta(minutes=2)).isoformat(),
    }
    return {
        "task_id": "task-monitor-001",
        "phase": "running",
        "provider": "codex",
        "pid": 1234,
        "delegate_io_attention_events": [event],
    }


def test_stop_hook_attaches_pending_delegate_event_when_no_higher_priority_context(tmp_path):
    decision = _run_hook(
        tmp_path,
        {"workflow_active": False, "agile_loop_active": False},
        _pending_run_state(),
    )

    assert decision["decision"] == "block"
    assert "delegate_io_attention" in decision["reason"]
    assert "task-monitor-001" in decision["reason"]


def test_stop_hook_preserves_higher_priority_next_action(tmp_path):
    decision = _run_hook(
        tmp_path,
        {
            "workflow_active": True,
            "agile_loop_active": False,
            "current_skill": "mst:plan",
            "next_action": {"skill": "mst:plan", "source": "PLN-663", "auto": True},
        },
        _pending_run_state(),
    )

    assert decision["decision"] == "block"
    assert "Workflow active" in decision["reason"]
    assert "delegate_io_attention" not in decision["reason"]


def test_run_wrapper_records_prompt_event_without_changing_stdin_transport(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".gran-maestro").mkdir(parents=True)
    log_dir = tmp_path / "task"
    log_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(MST_SCRIPT),
            "run",
            "--task-id",
            "T-DELEGATE-PROMPT",
            "--provider",
            "codex",
            "--model",
            "test",
            "--log-dir",
            str(log_dir),
            "--heartbeat-interval",
            "1",
            "--",
            sys.executable,
            "-c",
            "import sys,time; print('Do you want to continue? [y/N]', file=sys.stderr, flush=True); time.sleep(2)",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        env={**os.environ, "MST_SESSION_ID": SESSION_ID},
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    state = json.loads((workspace / ".gran-maestro" / "run" / "T-DELEGATE-PROMPT.json").read_text())
    events = state.get("delegate_io_attention_events", [])
    assert any(event.get("signal") == "stdin_prompt_suspected" for event in events)
