#!/usr/bin/env python3
from __future__ import annotations

"""Gran Maestro CLI utility (mst.py) — thin facade."""

import subprocess
import sys
import os
from pathlib import Path

if __package__ in (None, ""):
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _REPO_ROOT = _SCRIPT_DIR.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from scripts.mst_cmds import DISPATCH, build_parser, set_base_dir
from scripts.mst_cmds import _common
from scripts.mst_cmds import session as session_cmds
from scripts.mst_cmds.extension import _dir_content_hash, _ensure_copy_impl
from scripts.mst_cmds.agile_detail import (
    apply_chunk_append,
    build_objective_anchor_manifest,
    compute_coverage,
    extract_h12_slugs,
)
from scripts.mst_cmds.agile_governance import (
    _update_objective_dod_status,
    upsert_agile_detail_evidence,
)
from scripts.mst_cmds.workflow import cmd_workflow_run as _cmd_workflow_run

set_base_dir(None)

BASE_DIR = None
WORKFLOW_MAX_ITERATIONS = _common.WORKFLOW_MAX_ITERATIONS
next_action = _common.next_action
_collect_objective_dod_items = _common._collect_objective_dod_items
parse_agile_detail_metadata = _common.parse_agile_detail_metadata
parse_source_mapping = _common.parse_source_mapping
queue_enqueue = _common.queue_enqueue
queue_peek = _common.queue_peek
queue_pop = _common.queue_pop
queue_list = _common.queue_list
queue_complete = _common.queue_complete
queue_fail = _common.queue_fail
queue_count = _common.queue_count
find_base_dir = _common.find_base_dir
load_json = _common.load_json
save_json = _common.save_json
deep_merge = _common.deep_merge
requests_dir = _common.requests_dir
plans_dir = _common.plans_dir
_plugin_root = _common._plugin_root


def _sync_base_dir() -> None:
    if BASE_DIR is not None and _common.BASE_DIR != BASE_DIR:
        set_base_dir(BASE_DIR)


def cmd_workflow_run(args):
    _sync_base_dir()
    return _cmd_workflow_run(args)


BASE_DIR_OPTIONAL_COMMANDS = {
    ("hooks", "doctor"),
    ("hooks", "sync"),
    ("on", "cleanup"),
    ("session", "resolve"),
    ("skill", "build"),
    ("skill", "scaffold"),
}


def _invocation_command(args) -> str:
    command = [str(getattr(args, "command", "") or "")]
    subcommand = getattr(args, "subcommand", None)
    if subcommand:
        command.append(str(subcommand))
    return " ".join(part for part in command if part)


def _invocation_history_session_id() -> str | None:
    if os.environ.get("MST_INVOCATION_HISTORY_ACTIVE") == "1":
        return None
    if len(sys.argv) > 1 and sys.argv[1] in {"recover"}:
        return None
    if len(sys.argv) > 2 and sys.argv[1:3] == ["state", "recover"]:
        return None
    if BASE_DIR is None:
        return None
    try:
        session_id = _common.canonical_mst_session_id_from_env_or_context()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if not session_id:
        return None
    session_path = session_cmds.session_metadata_path(BASE_DIR, session_id)
    if not session_path.is_file():
        return None
    try:
        session_cmds.validate_mst_session_metadata_consistency(
            BASE_DIR,
            session_id,
            require_session_metadata=True,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return session_id


def _append_invocation_event(session_id: str, event_type: str, args, **extra) -> None:
    previous_guard = os.environ.get("MST_INVOCATION_HISTORY_ACTIVE")
    os.environ["MST_INVOCATION_HISTORY_ACTIVE"] = "1"
    try:
        command = _invocation_command(args)
        invocation_id = f"{os.getpid()}:{command}:{' '.join(sys.argv[1:])}"
        session_cmds.write_session_history_event(
            BASE_DIR,
            session_id,
            {
                "event_type": event_type,
                "command": command,
                "argv": sys.argv[1:],
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "invocation_id": invocation_id,
                "idempotency_key": f"{session_id}:{event_type}:pid={os.getpid()}:argv={' '.join(sys.argv[1:])}",
                **extra,
            },
        )
    finally:
        if previous_guard is None:
            os.environ.pop("MST_INVOCATION_HISTORY_ACTIVE", None)
        else:
            os.environ["MST_INVOCATION_HISTORY_ACTIVE"] = previous_guard


def main():
    global BASE_DIR

    parser = build_parser()
    args = parser.parse_args()

    key = (args.command, getattr(args, "subcommand", None))
    if key in BASE_DIR_OPTIONAL_COMMANDS:
        BASE_DIR = None
    else:
        BASE_DIR = find_base_dir()
        set_base_dir(BASE_DIR)

    fn = DISPATCH.get(key)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    try:
        history_session_id = _invocation_history_session_id()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if history_session_id:
        try:
            _append_invocation_event(history_session_id, "mst.invocation_start", args)
        except Exception as exc:
            print(f"Error: failed to append invocation history: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        exit_code = fn(args) or 0
    except Exception as exc:
        if history_session_id:
            try:
                _append_invocation_event(
                    history_session_id,
                    "mst.invocation_error",
                    args,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            except Exception as append_exc:
                print(f"Error: failed to append invocation error history: {append_exc}", file=sys.stderr)
        raise

    if history_session_id:
        event_type = "mst.invocation_end" if int(exit_code) == 0 else "mst.invocation_error"
        try:
            _append_invocation_event(history_session_id, event_type, args, exit_code=int(exit_code))
        except Exception as exc:
            print(f"Error: failed to append invocation history: {exc}", file=sys.stderr)
            sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
