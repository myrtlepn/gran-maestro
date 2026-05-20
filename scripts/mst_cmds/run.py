from __future__ import annotations

import argparse
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import session as session_mod
from scripts.mst_cmds._common import is_path_safe_mst_session_id, load_json, resolve_started_by_pid
from scripts.mst_cmds.dispatch import _coerce_positive_int, _dispatch_state_path, _load_dispatch_config, _now_iso
from scripts.mst_cmds.dispatch import _process_start_time, record_delegate_io_attention
from scripts.mst_cmds.dispatch import (
    _apply_lifecycle_paths,
    _collect_context_files_read,
    _lifecycle_attempt_id,
    _lifecycle_label,
    _parent_session_id,
    _status_from_final_state,
    _structured_error_payload,
    _sync_attempt_payload,
)


def _atomic_save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _load_state(task_id: str) -> dict:
    payload = load_json(_dispatch_state_path(task_id))
    if isinstance(payload, dict):
        return payload
    return {"task_id": task_id}


def _heartbeat_interval(args) -> int:
    if getattr(args, "heartbeat_interval", None) is not None:
        return _coerce_positive_int(args.heartbeat_interval, 30)
    dispatch_cfg = _load_dispatch_config()
    return _coerce_positive_int(dispatch_cfg.get("heartbeat_interval_sec"), 30)


def _wrapper_timeout_sec(args) -> int | None:
    if getattr(args, "timeout", None) is not None:
        value = int(args.timeout)
        return value if value > 0 else None

    dispatch_cfg = _load_dispatch_config()
    raw = dispatch_cfg.get("wrapper_timeout_sec")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _started_by_pid() -> int:
    return resolve_started_by_pid()


def _run_session_metadata_fields(session_id: str) -> dict[str, str | int]:
    fields: dict[str, str | int] = {"mst_session_id": session_id}
    try:
        parsed = session_mod.validate_mst_session_id(session_id)
    except ValueError:
        return fields
    fields["schema_version"] = 1
    fields["root_mst_id"] = parsed.root_mst_id
    return fields


def _register_state(
    args,
    session_id: str,
    *,
    raw_context: str,
    log_dir: Path,
    running_log_path: Path,
    stdout_log_path: Path,
    stderr_log_path: Path,
) -> str:
    now = _now_iso()
    pid = os.getpid()
    pid_start_time = _process_start_time(pid) or f"pid:{pid}:started_at:{now}"
    task_id = str(args.task_id).strip()
    payload = {
        "task_id": task_id,
        "attempt_id": _lifecycle_attempt_id(task_id, getattr(args, "attempt_id", None), None),
        "pid": pid,
        "pid_start_time": pid_start_time,
        "started_by_pid": _started_by_pid(),
        "started_at": now,
        "phase": "running",
        "status": "running",
        "provider": str(args.provider).strip().lower(),
        "skill": str(getattr(args, "skill", "")).strip(),
        "label": _lifecycle_label(
            task_id,
            str(getattr(args, "skill", "")).strip(),
            getattr(args, "label", None),
        ),
        "model": str(args.model).strip(),
        "worktree_dir": str(Path.cwd()),
        "parent_session_id": _parent_session_id(
            raw_context,
            session_id,
            getattr(args, "parent_session_id", None),
        ),
        "last_heartbeat": now,
        "provider_task_id": str(getattr(args, "provider_task_id", "") or os.environ.get("MST_PROVIDER_TASK_ID", "")).strip(),
        "fallback_from": str(getattr(args, "fallback_from", "") or "").strip() or None,
        "context_files_read": _collect_context_files_read(raw_context, getattr(args, "context_file", None)),
    }
    payload = _apply_lifecycle_paths(
        payload,
        running_log_path=str(running_log_path),
        stdout_log_path=str(stdout_log_path),
        stderr_log_path=str(stderr_log_path),
        transcript_summary_path=getattr(args, "transcript_summary_path", None),
        output_path=str(Path(getattr(args, "output_path", "")).resolve())
        if getattr(args, "output_path", None)
        else str(stdout_log_path),
    )
    payload.update(_run_session_metadata_fields(session_id))
    payload["log_dir"] = str(log_dir)
    payload = _sync_attempt_payload(payload)
    _atomic_save_json(_dispatch_state_path(payload["task_id"]), payload)
    return now


def _write_heartbeat(
    task_id: str,
    *,
    session_id: str,
    raw_context: str,
    phase: str | None = None,
    final: bool = False,
    exit_code: int | None = None,
    trace_path: Path | None = None,
) -> None:
    now = _now_iso()
    payload = _load_state(task_id)
    payload["task_id"] = task_id
    payload.update(_run_session_metadata_fields(session_id))
    payload["last_heartbeat"] = now
    payload["attempt_id"] = _lifecycle_attempt_id(task_id, payload.get("attempt_id"), payload)
    payload["label"] = _lifecycle_label(task_id, str(payload.get("skill") or ""), payload.get("label"))
    payload["parent_session_id"] = _parent_session_id(
        raw_context,
        session_id,
        payload.get("parent_session_id"),
    )
    payload["context_files_read"] = _collect_context_files_read(raw_context, None) or payload.get("context_files_read") or []
    if trace_path is not None:
        payload = _apply_lifecycle_paths(payload, trace_path=str(trace_path))
    if phase:
        payload["phase"] = str(phase).strip()

    if final:
        payload["phase"] = "done"
        payload["terminated_at"] = now
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)
        payload["status"] = _status_from_final_state(
            exit_code=payload.get("exit_code"),
            output_path=str(payload.get("output_path") or ""),
            fallback_from=str(payload.get("fallback_from") or ""),
        )
        payload["structured_error"] = _structured_error_payload(
            exit_code=payload.get("exit_code"),
            status=str(payload.get("status") or ""),
        )
    else:
        payload["status"] = "running"

    payload = _sync_attempt_payload(payload)
    _atomic_save_json(_dispatch_state_path(task_id), payload)


def _parse_trace_label(trace: str) -> str:
    parts = [part.strip() for part in str(trace).split("/") if part.strip()]
    if not parts:
        return "trace"
    label = parts[-1]
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in label)
    return safe or "trace"


def _write_trace_file(
    log_dir: Path,
    task_id: str,
    provider: str,
    model: str,
    trace: str,
    started_at: str,
    terminated_at: str,
    duration_ms: int,
    exit_code: int,
    running_log_path: Path,
    session_id: str,
) -> Path:
    traces_dir = log_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    label = _parse_trace_label(trace)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    trace_path = traces_dir / f"{provider}-{label}-{ts}.md"

    content = [
        "---",
        f"task_id: {task_id}",
        f"provider: {provider}",
        f"model: {model}",
        f"mst_session_id: {session_id}",
        f"trace_label: {trace}",
        f"started_at: {started_at}",
        f"terminated_at: {terminated_at}",
        f"duration_ms: {duration_ms}",
        f"exit_code: {exit_code}",
        f"running_log_path: {running_log_path}",
        "---",
        "",
    ]
    metadata = _run_session_metadata_fields(session_id)
    root_mst_id = metadata.get("root_mst_id")
    if isinstance(root_mst_id, str) and root_mst_id:
        content.insert(5, f"root_mst_id: {root_mst_id}")
    trace_path.write_text("\n".join(content), encoding="utf-8")
    return trace_path


def _ensure_context_session_id(context_payload: dict, session_id: str, root_mst_id: str) -> None:
    existing = context_payload.get("mst_session_id")
    if isinstance(existing, str) and existing.strip() and existing.strip() != session_id:
        raise ValueError("MST_SESSION_ID and structured mst_session_id mismatch")
    context_payload["mst_session_id"] = session_id

    existing_root = context_payload.get("root_mst_id")
    if isinstance(existing_root, str) and existing_root.strip() and existing_root.strip() != root_mst_id:
        raise ValueError("MST_SESSION_ID and structured root_mst_id mismatch")
    context_payload.setdefault("root_mst_id", root_mst_id)
    context_payload.setdefault("schema_version", 1)


def _child_env_with_run_context(child_env: dict[str, str], session_id: str) -> dict[str, str]:
    try:
        parsed = session_mod.validate_mst_session_id(session_id)
    except ValueError:
        return child_env

    raw_context = child_env.get("MST_CONTEXT_JSON", "").strip()
    if raw_context:
        try:
            context_payload = json.loads(raw_context)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MST_CONTEXT_JSON must be a JSON object: {exc}") from exc
        if not isinstance(context_payload, dict):
            raise ValueError("MST_CONTEXT_JSON must be a JSON object")
    else:
        context_payload = {}

    _ensure_context_session_id(context_payload, session_id, parsed.root_mst_id)

    core = context_payload.get("core_rehydration")
    if isinstance(core, dict):
        _ensure_context_session_id(core, session_id, parsed.root_mst_id)
        next_execution = core.setdefault("next_execution", {})
        if not isinstance(next_execution, dict):
            raise ValueError("core_rehydration.next_execution must be a JSON object")

        env = next_execution.setdefault("env", {})
        if not isinstance(env, dict):
            raise ValueError("core_rehydration.next_execution.env must be a JSON object")
        existing_env_sid = env.get("MST_SESSION_ID")
        if isinstance(existing_env_sid, str) and existing_env_sid.strip() and existing_env_sid.strip() != session_id:
            raise ValueError("MST_SESSION_ID and recovered next_execution env mismatch")
        env["MST_SESSION_ID"] = session_id

        context = next_execution.setdefault("context", {})
        if not isinstance(context, dict):
            raise ValueError("core_rehydration.next_execution.context must be a JSON object")
        _ensure_context_session_id(context, session_id, parsed.root_mst_id)

    child_env["MST_CONTEXT_JSON"] = json.dumps(context_payload, ensure_ascii=False, separators=(",", ":"))
    return child_env


def _child_env_with_run_session_id() -> dict[str, str]:
    try:
        child_env = session_mod.child_env_with_session_id()
        return _child_env_with_run_context(child_env, child_env["MST_SESSION_ID"])
    except ValueError as exc:
        message = str(exc)
        if "missing MST_SESSION_ID" not in message and "invalid structured mst_session_id" not in message:
            raise

    session_id = os.environ.get("MST_SESSION_ID", "").strip() or str(uuid.uuid4())
    if not is_path_safe_mst_session_id(session_id):
        raise ValueError("invalid MST_SESSION_ID for run wrapper")
    child_env = os.environ.copy()
    child_env["MST_SESSION_ID"] = session_id
    os.environ["MST_SESSION_ID"] = session_id
    return _child_env_with_run_context(child_env, session_id)


def _tee_output(proc: subprocess.Popen, log_fd: int, stream_log_fds: dict[int, int] | None = None) -> None:
    stream_map: dict[int, int] = {}
    stream_log_fds = stream_log_fds or {}

    if proc.stdout is not None:
        out_fd = proc.stdout.fileno()
        os.set_blocking(out_fd, False)
        stream_map[out_fd] = sys.stdout.fileno()

    if proc.stderr is not None:
        err_fd = proc.stderr.fileno()
        os.set_blocking(err_fd, False)
        stream_map[err_fd] = sys.stderr.fileno()

    while stream_map:
        readable, _, _ = select.select(list(stream_map.keys()), [], [], 0.1)
        if not readable:
            continue

        for src_fd in readable:
            try:
                chunk = os.read(src_fd, 65536)
            except BlockingIOError:
                continue

            if not chunk:
                stream_map.pop(src_fd, None)
                continue

            os.write(stream_map[src_fd], chunk)
            os.write(log_fd, chunk)
            if src_fd in stream_log_fds:
                os.write(stream_log_fds[src_fd], chunk)


def cmd_run(args):
    task_id = str(args.task_id).strip()
    provider = str(args.provider).strip().lower()
    model = str(args.model).strip()
    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    running_log_path = log_dir / "running.log"
    stdout_log_path = log_dir / "stdout.log"
    stderr_log_path = log_dir / "stderr.log"

    command = list(getattr(args, "cli_command", []) or [])
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        print("Error: missing CLI command after '--'", file=sys.stderr)
        return 2

    heartbeat_interval = _heartbeat_interval(args)
    timeout_sec = _wrapper_timeout_sec(args)
    state_lock = threading.Lock()
    stop_event = threading.Event()
    child_env = _child_env_with_run_session_id()
    run_session_id = child_env["MST_SESSION_ID"]
    raw_context = child_env.get("MST_CONTEXT_JSON", "")

    _register_state(
        args,
        run_session_id,
        raw_context=raw_context,
        log_dir=log_dir,
        running_log_path=running_log_path,
        stdout_log_path=stdout_log_path,
        stderr_log_path=stderr_log_path,
    )

    def heartbeat_loop() -> None:
        while not stop_event.wait(heartbeat_interval):
            with state_lock:
                _write_heartbeat(
                    task_id,
                    session_id=run_session_id,
                    raw_context=raw_context,
                    phase="running",
                )
                current_state = _load_state(task_id)
                try:
                    record_delegate_io_attention(
                        _dispatch_state_path(task_id),
                        {"stdout": stdout_log_path, "stderr": stderr_log_path},
                        process_identity={
                            "pid": os.getpid(),
                            "pid_start_time": str(current_state.get("pid_start_time") or ""),
                            "pid_alive": True,
                        },
                    )
                except Exception:
                    pass

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    proc: subprocess.Popen | None = None
    signal_state = {"received": None}

    def _signal_handler(signum, _frame):
        signal_state["received"] = signum
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signum)
            except ProcessLookupError:
                pass

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    started_mono = time.time_ns()
    exit_code = 1

    try:
        log_fd = os.open(str(running_log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        stdout_log_fd = os.open(str(stdout_log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        stderr_log_fd = os.open(str(stderr_log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=False,
                env=child_env,
            )
            tee_error: list[BaseException] = []

            def _tee_worker() -> None:
                try:
                    stream_log_fds = {}
                    if proc.stdout is not None:
                        stream_log_fds[proc.stdout.fileno()] = stdout_log_fd
                    if proc.stderr is not None:
                        stream_log_fds[proc.stderr.fileno()] = stderr_log_fd
                    _tee_output(proc, log_fd, stream_log_fds)
                except BaseException as exc:  # pragma: no cover - defensive guard
                    tee_error.append(exc)

            tee_thread = threading.Thread(target=_tee_worker, daemon=True)
            tee_thread.start()
            try:
                proc.wait(timeout=timeout_sec)
                exit_code = int(proc.returncode)
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                exit_code = 143
                print(
                    f"[mst.py run] wrapper timeout after {timeout_sec}s, killed subprocess",
                    file=sys.stderr,
                )
            finally:
                tee_thread.join(timeout=5)
                if tee_error:
                    raise tee_error[0]
        finally:
            os.close(stdout_log_fd)
            os.close(stderr_log_fd)
            os.close(log_fd)
    except FileNotFoundError as exc:
        print(f"Error: failed to execute command ({exc})", file=sys.stderr)
        exit_code = 127
    finally:
        stop_event.set()
        hb_thread.join(timeout=max(1.0, heartbeat_interval + 0.5))
        terminated_at = _now_iso()
        duration_ms = max(0, (time.time_ns() - started_mono) // 1_000_000)
        trace_path: Path | None = None
        if args.trace:
            trace_path = _write_trace_file(
                log_dir=log_dir,
                task_id=task_id,
                provider=provider,
                model=model,
                trace=str(args.trace),
                started_at=_load_state(task_id).get("started_at", ""),
                terminated_at=terminated_at,
                duration_ms=duration_ms,
                exit_code=exit_code,
                running_log_path=running_log_path,
                session_id=run_session_id,
            )
        with state_lock:
            _write_heartbeat(
                task_id,
                session_id=run_session_id,
                raw_context=raw_context,
                final=True,
                exit_code=exit_code,
                trace_path=trace_path,
            )

        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)

    if signal_state["received"] is not None:
        return 128 + int(signal_state["received"])

    if exit_code < 0:
        return 128 + abs(exit_code)
    return exit_code


def register(subparsers):
    run = subparsers.add_parser("run", help="Run external CLI with dispatch state/heartbeat/log tee")
    run.add_argument("--task-id", required=True)
    run.add_argument("--provider", choices=["codex", "gemini", "claude"], required=True)
    run.add_argument("--skill", default="")
    run.add_argument("--model", required=True)
    run.add_argument("--log-dir", required=True)
    run.add_argument("--trace")
    run.add_argument("--heartbeat-interval")
    run.add_argument("--timeout", type=int, help="Subprocess timeout in seconds")
    run.add_argument("--attempt-id")
    run.add_argument("--label")
    run.add_argument("--output-path")
    run.add_argument("--transcript-summary-path")
    run.add_argument("--provider-task-id")
    run.add_argument("--parent-session-id")
    run.add_argument("--fallback-from")
    run.add_argument("--context-file", action="append")
    run.add_argument("cli_command", nargs=argparse.REMAINDER)
