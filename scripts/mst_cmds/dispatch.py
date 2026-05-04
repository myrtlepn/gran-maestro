from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import _common
from scripts.mst_cmds import cleanup as cleanup_mod
from scripts.mst_cmds import resolve_model as resolve_model_mod
from scripts.mst_cmds import session as session_mod
from scripts.mst_cmds._common import (
    _parse_utc_datetime,
    _plugin_root,
    load_json,
    resolve_started_by_pid,
    run_dir,
    save_json,
)


_TERMINAL_PHASES = {"done", "terminated", "failed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dispatch_session_bootstrap_cmd() -> str:
    normalize_context_py = """
import json
import os
import sys

sid = os.environ.get("MST_SESSION_ID", "").strip()
raw = os.environ.get("MST_CONTEXT_JSON", "").strip()
payload = {}
if raw:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: MST_CONTEXT_JSON must be a JSON object: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(parsed, dict):
        print("Error: MST_CONTEXT_JSON must be a JSON object", file=sys.stderr)
        sys.exit(2)
    existing = parsed.get("mst_session_id")
    if "mst_session_id" in parsed and (
        not isinstance(existing, str) or not existing.strip() or existing.strip() != sid
    ):
        print("Error: MST_SESSION_ID and structured mst_session_id mismatch", file=sys.stderr)
        sys.exit(2)
    payload = dict(parsed)
payload["mst_session_id"] = sid
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
""".strip()
    q = shlex.quote
    return (
        'MST_SESSION_ID="${MST_SESSION_ID:-}"; '
        "export MST_SESSION_ID; "
        'if [ -z "$MST_SESSION_ID" ]; then '
        'echo "Error: missing MST_SESSION_ID before dispatch spawn" >&2; exit 2; '
        "fi; "
        f'MST_CONTEXT_JSON="$(python3 -c {q(normalize_context_py)})" || exit 2; '
        "export MST_CONTEXT_JSON"
    )


def _dispatch_state_path(task_id: str) -> Path:
    return run_dir() / f"{task_id}.json"


def _canonical_dispatch_fields(session_id: str) -> dict:
    return _common.canonical_state_payload_fields(session_id)


def _dispatch_payload_error(payload: dict, session_id: str) -> str | None:
    canonical_fields = _canonical_dispatch_fields(session_id)
    existing_session_id = payload.get("mst_session_id")
    if (
        isinstance(existing_session_id, str)
        and existing_session_id.strip()
        and existing_session_id.strip() != canonical_fields["mst_session_id"]
    ):
        return (
            "dispatch mst_session_id mismatch: "
            f"env={canonical_fields['mst_session_id']} payload={existing_session_id.strip()}"
        )
    existing_schema_version = payload.get("schema_version")
    if existing_schema_version is not None and existing_schema_version != canonical_fields["schema_version"]:
        return "dispatch schema_version mismatch"
    existing_root_mst_id = payload.get("root_mst_id")
    if (
        isinstance(existing_root_mst_id, str)
        and existing_root_mst_id.strip()
        and existing_root_mst_id.strip() != canonical_fields["root_mst_id"]
    ):
        return (
            "dispatch root_mst_id mismatch: "
            f"session={canonical_fields['root_mst_id']} payload={existing_root_mst_id.strip()}"
        )
    return None


def _coerce_positive_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _load_dispatch_config() -> dict:
    config_paths = [
        _common.BASE_DIR / "config.resolved.json",
        _plugin_root() / "templates" / "defaults" / "config.json",
    ]
    for path in config_paths:
        payload = load_json(path)
        if isinstance(payload, dict):
            dispatch = payload.get("dispatch")
            if isinstance(dispatch, dict):
                return dispatch
    return {}


def _dispatch_stale_threshold(args) -> int:
    if getattr(args, "stale_threshold", None) is not None:
        return _coerce_positive_int(args.stale_threshold, 60)
    dispatch_cfg = _load_dispatch_config()
    return _coerce_positive_int(dispatch_cfg.get("stale_threshold_sec"), 60)


def _resolve_provider_model(provider: str, explicit_model: str | None) -> str | None:
    if isinstance(explicit_model, str) and explicit_model.strip():
        return explicit_model.strip()

    config = resolve_model_mod._load_resolve_model_config()
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg, dict) else {}
    provider_cfg = providers_cfg.get(provider) if isinstance(providers_cfg, dict) else None

    if isinstance(provider_cfg, dict):
        default_tier = provider_cfg.get("default_tier")
        if isinstance(default_tier, str):
            resolved = provider_cfg.get(default_tier)
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
            return None

        for candidate in ("premium", "economy", "default"):
            resolved = provider_cfg.get(candidate)
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        return None

    fallback = resolve_model_mod._resolve_provider_default_model(provider, provider_cfg)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return None


def _stdin_kind() -> str:
    try:
        mode = os.fstat(0).st_mode
    except OSError:
        return "unknown"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISFIFO(mode):
        return "pipe"
    if stat.S_ISCHR(mode):
        return "char-device"
    if stat.S_ISREG(mode):
        return "regular-file"
    return "other"


def _heartbeat_age_seconds(last_heartbeat: str, now: datetime) -> int:
    heartbeat_dt = _parse_utc_datetime(last_heartbeat)
    if heartbeat_dt is None:
        return 10**9
    delta = now - heartbeat_dt
    if delta.total_seconds() < 0:
        return 0
    return int(delta.total_seconds())


def _build_status_row(path: Path, stale_threshold: int, now: datetime) -> dict | None:
    payload = load_json(path)
    if not isinstance(payload, dict):
        return None

    task_id = str(payload.get("task_id") or path.stem)
    phase = str(payload.get("phase", "running"))
    last_heartbeat = str(payload.get("last_heartbeat", ""))
    age_sec = _heartbeat_age_seconds(last_heartbeat, now)
    is_stale = phase not in _TERMINAL_PHASES and age_sec >= stale_threshold

    if phase in _TERMINAL_PHASES:
        status = phase
    elif is_stale:
        status = "stale"
    else:
        status = "running"

    return {
        "task_id": task_id,
        "pid": payload.get("pid"),
        "provider": payload.get("provider"),
        "skill": payload.get("skill", ""),
        "model": payload.get("model"),
        "phase": phase,
        "status": status,
        "last_heartbeat": last_heartbeat,
        "age_sec": age_sec,
        "worktree_dir": payload.get("worktree_dir"),
    }


def _collect_dispatch_rows(stale_threshold: int) -> list[dict]:
    directory = run_dir()
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        row = _build_status_row(path, stale_threshold, now)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda item: item.get("task_id", ""))
    return rows


def cmd_dispatch_build(args):
    provider = str(args.provider).strip().lower()
    if provider == "claude":
        print(
            "Error: dispatch build does not support provider 'claude'. Use Task-based claude dispatch.",
            file=sys.stderr,
        )
        return 1

    resolved_model = _resolve_provider_model(provider, args.model)
    if not isinstance(resolved_model, str) or not resolved_model:
        print(f"Error: failed to resolve model for provider '{provider}'", file=sys.stderr)
        return 1

    prompt_file = Path(args.prompt_file).resolve()
    if not prompt_file.exists():
        print(f"Error: prompt file not found: {prompt_file}", file=sys.stderr)
        return 1

    worktree_dir = Path(args.worktree_dir).resolve()
    log_file = Path(args.log_file).resolve()
    task_id = str(args.task_id).strip()
    if not task_id:
        print("Error: task id is required", file=sys.stderr)
        return 1

    mst_script = _common._mst_script_path().resolve()
    q = shlex.quote
    session_bootstrap_cmd = _dispatch_session_bootstrap_cmd()

    register_cmd = (
        f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch register '
        f"--task-id {q(task_id)} --pid $$ --provider {q(provider)} "
        f"--model {q(resolved_model)} --worktree-dir {q(str(worktree_dir))} "
        f'--started-by-pid "${{MST_STATE_PPID:-$PPID}}"'
    )

    if provider == "codex":
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" codex exec --full-auto -m {q(resolved_model)} -C {q(str(worktree_dir))} '
            f"\"$(cat {q(str(prompt_file))})\""
        )
    else:
        cli_cmd = (
            f'MST_SESSION_ID="$MST_SESSION_ID" gemini -p \"$(cat {q(str(prompt_file))})\" --model {q(resolved_model)} '
            "--approval-mode yolo --sandbox=false"
        )

    heartbeat_cmd = (
        f'MST_SESSION_ID="$MST_SESSION_ID" python3 {q(str(mst_script))} dispatch heartbeat '
        f"--task-id {q(task_id)} --final --exit-code \"$EC\""
    )

    command = (
        f"{session_bootstrap_cmd}; "
        f"{register_cmd}; "
        "set -o pipefail; "
        f"{cli_cmd} < /dev/null 2>&1 | tee {q(str(log_file))}; "
        "EC=${PIPESTATUS[0]}; "
        f"echo \"EXIT_CODE:$EC\" >> {q(str(log_file))}; "
        f"{heartbeat_cmd}; "
        "exit $EC"
    )
    print(command)
    return 0


def cmd_dispatch_preflight(args):
    provider = str(args.provider).strip().lower()
    executable = provider
    if shutil.which(executable) is None:
        print(f"Error: required binary '{executable}' not found in PATH", file=sys.stderr)
        return 1

    resolved_model = _resolve_provider_model(provider, args.model)
    if not isinstance(resolved_model, str) or not resolved_model:
        print(f"Error: failed to resolve model for provider '{provider}'", file=sys.stderr)
        return 1

    stdin_kind = _stdin_kind()
    print(f"[dispatch] stdin={stdin_kind}", file=sys.stderr)
    if stdin_kind in {"pipe", "socket"}:
        print(
            f"[dispatch] warning: stdin is {stdin_kind}; background CLI must close stdin explicitly.",
            file=sys.stderr,
        )

    print(
        json.dumps(
            {"provider": provider, "binary": executable, "model": resolved_model, "stdin": stdin_kind},
            ensure_ascii=False,
        )
    )
    return 0


def cmd_dispatch_register(args):
    try:
        child_env = session_mod.child_env_with_required_session_context()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    now = _now_iso()
    task_id = str(args.task_id).strip()
    marker_pid = int(args.pid)
    state_path = _dispatch_state_path(task_id)
    existing_payload = load_json(state_path)
    if isinstance(existing_payload, dict):
        payload_error = _dispatch_payload_error(existing_payload, session_id)
        if payload_error is not None:
            print(f"Error: {payload_error}", file=sys.stderr)
            return 1
    canonical_fields = _canonical_dispatch_fields(session_id)
    payload = {
        **canonical_fields,
        "task_id": task_id,
        "pid": marker_pid,
        "started_at": now,
        "phase": "running",
        "provider": str(args.provider).strip().lower(),
        "skill": str(getattr(args, "skill", "")).strip(),
        "model": str(args.model).strip(),
        "worktree_dir": str(args.worktree_dir),
        "last_heartbeat": now,
    }
    if getattr(args, "started_by_pid", None) is not None:
        try:
            payload["started_by_pid"] = int(args.started_by_pid)
        except (TypeError, ValueError):
            print(
                f"[dispatch] warning: invalid started_by_pid skipped: {args.started_by_pid}",
                file=sys.stderr,
            )
    else:
        payload["started_by_pid"] = resolve_started_by_pid()
    try:
        cleanup_mod.write_active_flow_marker_for_pid(
            project_root=_common.BASE_DIR.parent,
            session_id=session_id,
            pid=marker_pid,
            mode="single-shot",
            extra={
                "entrypoint": "dispatch",
                "task_id": task_id,
                **canonical_fields,
                "provider": payload["provider"],
                "worktree_dir": payload["worktree_dir"],
            },
        )
    except Exception as exc:
        print(f"[dispatch] warning: failed to write active-flow marker ({exc})", file=sys.stderr)
    save_json(state_path, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_dispatch_heartbeat(args):
    try:
        child_env = session_mod.child_env_with_required_session_context()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    session_id = child_env["MST_SESSION_ID"]
    os.environ["MST_SESSION_ID"] = session_id
    os.environ["MST_CONTEXT_JSON"] = child_env["MST_CONTEXT_JSON"]
    task_id = str(args.task_id).strip()
    now = _now_iso()
    state_path = _dispatch_state_path(task_id)
    payload = load_json(state_path)
    if not isinstance(payload, dict):
        payload = {"task_id": task_id}
    payload_error = _dispatch_payload_error(payload, session_id)
    if payload_error is not None:
        print(f"Error: {payload_error}", file=sys.stderr)
        return 1

    payload.update(_canonical_dispatch_fields(session_id))
    payload["task_id"] = task_id
    payload["last_heartbeat"] = now
    if args.phase:
        payload["phase"] = str(args.phase).strip()

    if args.final:
        payload["phase"] = "done"
        payload["terminated_at"] = now
        if args.exit_code is not None:
            payload["exit_code"] = int(args.exit_code)

    try:
        save_json(state_path, payload)
    except Exception as exc:
        print(f"[dispatch] warning: failed to write heartbeat state ({exc})", file=sys.stderr)
        return 0

    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_dispatch_list(args):
    stale_threshold = _dispatch_stale_threshold(args)
    rows = _collect_dispatch_rows(stale_threshold)

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("No dispatch entries found.")
        return 0

    print(f"{'TASK_ID':<32} {'STATUS':<10} {'AGE(s)':<8} {'PID':<8} {'PROVIDER':<8} {'PHASE'}")
    for row in rows:
        print(
            f"{str(row.get('task_id', '')):<32} "
            f"{str(row.get('status', '')):<10} "
            f"{str(row.get('age_sec', '')):<8} "
            f"{str(row.get('pid', '')):<8} "
            f"{str(row.get('provider', '')):<8} "
            f"{str(row.get('phase', ''))}"
        )
    return 0


def _signal_from_name(raw_signal: str) -> int:
    normalized = str(raw_signal or "TERM").strip().upper()
    if normalized == "KILL":
        return signal.SIGKILL
    return signal.SIGTERM


def cmd_dispatch_kill(args):
    stale_threshold = _dispatch_stale_threshold(args)
    signal_name = str(args.signal).strip().upper()
    signal_value = _signal_from_name(signal_name)

    rows: list[dict]
    if args.stale:
        rows = [row for row in _collect_dispatch_rows(stale_threshold) if row.get("status") == "stale"]
    else:
        state_path = _dispatch_state_path(str(args.task_id).strip())
        row = _build_status_row(state_path, stale_threshold, datetime.now(timezone.utc))
        rows = [row] if row is not None else []

    terminated = 0
    for row in rows:
        task_id = str(row.get("task_id", ""))
        pid = row.get("pid")
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            print(f"[dispatch] warning: invalid pid for task '{task_id}'", file=sys.stderr)
            continue

        try:
            os.kill(pid_int, signal_value)
            terminated += 1
        except ProcessLookupError:
            print(f"[dispatch] warning: pid not found for task '{task_id}' ({pid_int})", file=sys.stderr)
        except Exception as exc:
            print(f"[dispatch] warning: failed to signal task '{task_id}' ({exc})", file=sys.stderr)
            continue

        state_path = _dispatch_state_path(task_id)
        payload = load_json(state_path)
        if not isinstance(payload, dict):
            payload = {"task_id": task_id}
        payload["phase"] = "terminated"
        payload["signal"] = signal_name
        payload["terminated_at"] = _now_iso()
        payload["last_heartbeat"] = payload.get("terminated_at")
        try:
            save_json(state_path, payload)
        except Exception as exc:
            print(f"[dispatch] warning: failed to update state for task '{task_id}' ({exc})", file=sys.stderr)

    print(json.dumps({"terminated": terminated}, ensure_ascii=False))
    return 0


def _dispatch_run_dir_no_create() -> Path:
    return _common.run_dir_no_create()


def _cleanup_archive_dir(now: datetime) -> Path:
    base_dir = _common.BASE_DIR if _common.BASE_DIR is not None else _common.cwd_base_dir()
    return base_dir / "archive" / "run" / f"{now.year:04d}-{now.month:02d}"


def _has_valid_started_by_pid(payload: dict) -> bool:
    if "started_by_pid" not in payload:
        return False
    try:
        int(payload.get("started_by_pid"))
    except (TypeError, ValueError):
        return False
    return True


def _cleanup_marker_reason(payload: dict, archive_after_seconds: int, now: datetime, include_legacy: bool) -> str | None:
    if include_legacy and not _has_valid_started_by_pid(payload):
        return "legacy"

    phase = str(payload.get("phase", "")).strip().lower()
    if phase != "done":
        return None

    heartbeat = _parse_utc_datetime(payload.get("last_heartbeat"))
    if heartbeat is None:
        return None

    age_seconds = max(0, int((now - heartbeat).total_seconds()))
    if age_seconds > archive_after_seconds:
        return "stale_done"
    return None


def _dispatch_cleanup_markers(args) -> dict:
    run_directory = _dispatch_run_dir_no_create()
    if not run_directory.is_dir():
        print("SUMMARY: archived=0 legacy=0 stale_done=0 preserved=0")
        return {"status": "ok", "archived": 0, "legacy": 0, "stale_done": 0, "preserved": 0}

    now = datetime.now(timezone.utc)
    archive_after_seconds = max(0, int(args.archive_after_days)) * 86400
    include_legacy = bool(getattr(args, "legacy", False))
    dry_run = bool(getattr(args, "dry_run", False))
    archived = 0
    legacy = 0
    stale_done = 0
    preserved = 0

    for path in sorted(run_directory.glob("*.json")):
        if not path.is_file():
            continue

        payload = load_json(path)
        if not isinstance(payload, dict):
            preserved += 1
            print(f"[dispatch] debug: failed to parse cleanup marker preserved: {path}", file=sys.stderr)
            continue

        reason = _cleanup_marker_reason(payload, archive_after_seconds, now, include_legacy)
        if reason is None:
            preserved += 1
            continue

        if dry_run:
            print(f"[dry-run] would archive: {path} (reason: {reason})")
            archived += 1
            if reason == "legacy":
                legacy += 1
            else:
                stale_done += 1
            continue

        archive_dir = _cleanup_archive_dir(now)
        target = archive_dir / path.name
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except Exception as exc:
            preserved += 1
            print(f"[dispatch] warning: failed to archive marker '{path}' ({exc})", file=sys.stderr)
            continue

        archived += 1
        if reason == "legacy":
            legacy += 1
        else:
            stale_done += 1

    print(f"SUMMARY: archived={archived} legacy={legacy} stale_done={stale_done} preserved={preserved}")
    return {
        "status": "ok",
        "archived": archived,
        "legacy": legacy,
        "stale_done": stale_done,
        "preserved": preserved,
    }


def cmd_dispatch_cleanup(args):
    session_id = os.environ.get("MST_SESSION_ID", "").strip() or "dispatch-cleanup"
    result = cleanup_mod.run_cleanup_with_lock_report(
        project_root=_common.BASE_DIR.parent,
        entrypoint="stale-marker",
        session_id=session_id,
        timeout_seconds=5.0,
        cleanup_fn=lambda _context: _dispatch_cleanup_markers(args),
    )
    if result.get("status") == "skipped":
        print(f"SUMMARY: archived=0 legacy=0 stale_done=0 preserved=0")
        print(f"[dispatch] cleanup skipped: {result.get('reason', 'unknown')}", file=sys.stderr)
    return 0


def register(subparsers):
    sub = subparsers
    dispatch = sub.add_parser("dispatch")
    dispatch_sub = dispatch.add_subparsers(dest="subcommand")

    build = dispatch_sub.add_parser("build")
    build.add_argument("--provider", choices=["codex", "gemini", "claude"], required=True)
    build.add_argument("--prompt-file", required=True)
    build.add_argument("--task-id", required=True)
    build.add_argument("--worktree-dir", required=True)
    build.add_argument("--log-file", required=True)
    build.add_argument("--model")

    preflight = dispatch_sub.add_parser("preflight")
    preflight.add_argument("--provider", choices=["codex", "gemini", "claude"], required=True)
    preflight.add_argument("--model")

    register_cmd = dispatch_sub.add_parser("register")
    register_cmd.add_argument("--task-id", required=True)
    register_cmd.add_argument("--pid", required=True)
    register_cmd.add_argument("--provider", required=True)
    register_cmd.add_argument("--skill", default="")
    register_cmd.add_argument("--model", required=True)
    register_cmd.add_argument("--worktree-dir", required=True)
    register_cmd.add_argument("--started-by-pid")

    heartbeat = dispatch_sub.add_parser("heartbeat")
    heartbeat.add_argument("--task-id", required=True)
    heartbeat.add_argument("--phase")
    heartbeat.add_argument("--final", action="store_true")
    heartbeat.add_argument("--exit-code")

    list_cmd = dispatch_sub.add_parser("list")
    list_cmd.add_argument("--format", choices=["json", "table"], default="table")
    list_cmd.add_argument("--stale-threshold")

    kill = dispatch_sub.add_parser("kill")
    group = kill.add_mutually_exclusive_group(required=True)
    group.add_argument("--task-id")
    group.add_argument("--stale", action="store_true")
    kill.add_argument("--signal", choices=["TERM", "KILL"], default="TERM")
    kill.add_argument("--stale-threshold")

    cleanup = dispatch_sub.add_parser("cleanup")
    cleanup.add_argument("--legacy", action="store_true")
    cleanup.add_argument("--dry-run", action="store_true")
    cleanup.add_argument("--archive-after-days", type=int, default=7)
    cleanup.set_defaults(func=cmd_dispatch_cleanup)
