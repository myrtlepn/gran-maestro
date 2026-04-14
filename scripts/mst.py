#!/usr/bin/env python3
from __future__ import annotations

"""Gran Maestro CLI utility (mst.py) — thin facade."""

import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _REPO_ROOT = _SCRIPT_DIR.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

from scripts.mst_cmds import DISPATCH, build_parser, set_base_dir
from scripts.mst_cmds import _common
from scripts.mst_cmds.extension import _dir_content_hash, _ensure_copy_impl
from scripts.mst_cmds.agile_detail import (
    apply_chunk_append,
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


BASE_DIR_OPTIONAL_COMMANDS = {("hooks", "sync")}


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

    sys.exit(fn(args) or 0)


if __name__ == "__main__":
    main()
