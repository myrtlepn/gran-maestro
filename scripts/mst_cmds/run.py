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
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds._common import load_json, resolve_started_by_pid
from scripts.mst_cmds.dispatch import _coerce_positive_int, _dispatch_state_path, _load_dispatch_config, _now_iso


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


def _register_state(args) -> str:
    now = _now_iso()
    payload = {
        "task_id": str(args.task_id).strip(),
        "pid": os.getpid(),
        "started_by_pid": _started_by_pid(),
        "started_at": now,
        "phase": "running",
        "provider": str(args.provider).strip().lower(),
        "skill": str(getattr(args, "skill", "")).strip(),
        "model": str(args.model).strip(),
        "worktree_dir": str(Path.cwd()),
        "last_heartbeat": now,
    }
    _atomic_save_json(_dispatch_state_path(payload["task_id"]), payload)
    return now


def _write_heartbeat(task_id: str, *, phase: str | None = None, final: bool = False, exit_code: int | None = None) -> None:
    now = _now_iso()
    payload = _load_state(task_id)
    payload["task_id"] = task_id
    payload["last_heartbeat"] = now
    if phase:
        payload["phase"] = str(phase).strip()

    if final:
        payload["phase"] = "done"
        payload["terminated_at"] = now
        if exit_code is not None:
            payload["exit_code"] = int(exit_code)

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
) -> None:
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
        f"trace_label: {trace}",
        f"started_at: {started_at}",
        f"terminated_at: {terminated_at}",
        f"duration_ms: {duration_ms}",
        f"exit_code: {exit_code}",
        f"running_log_path: {running_log_path}",
        "---",
        "",
    ]
    trace_path.write_text("\n".join(content), encoding="utf-8")


def _tee_output(proc: subprocess.Popen, log_fd: int) -> None:
    stream_map: dict[int, int] = {}

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


def cmd_run(args):
    task_id = str(args.task_id).strip()
    provider = str(args.provider).strip().lower()
    model = str(args.model).strip()
    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    running_log_path = log_dir / "running.log"

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

    _register_state(args)

    def heartbeat_loop() -> None:
        while not stop_event.wait(heartbeat_interval):
            with state_lock:
                _write_heartbeat(task_id, phase="running")

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
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=False,
            )
            tee_error: list[BaseException] = []

            def _tee_worker() -> None:
                try:
                    _tee_output(proc, log_fd)
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
            os.close(log_fd)
    except FileNotFoundError as exc:
        print(f"Error: failed to execute command ({exc})", file=sys.stderr)
        exit_code = 127
    finally:
        stop_event.set()
        hb_thread.join(timeout=max(1.0, heartbeat_interval + 0.5))

        with state_lock:
            _write_heartbeat(task_id, final=True, exit_code=exit_code)

        terminated_at = _now_iso()
        duration_ms = max(0, (time.time_ns() - started_mono) // 1_000_000)
        if args.trace:
            _write_trace_file(
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
    run.add_argument("cli_command", nargs=argparse.REMAINDER)
