#!/usr/bin/env python3
"""Gran Maestro CLI utility (mst.py)

Usage:
  python3 scripts/mst.py <subcommand> [options]

Subcommands:
  request list        [--active | --all | --completed] [--format table|json]
  request inspect     <REQ-ID>
  request history     [--all]
  request filter      [--phase N] [--status STATUS] [--priority LEVEL] [--format json]
  request count       [--active | --all | --completed]
  request cancel      <REQ-ID>
  workflow run        <PLN-NNN|REQ-NNN>
  worktree create     --path PATH --branch BRANCH [--base BASE]
  worktree remove     --path PATH [--force]

  plan list
  plan inspect       <PLN-ID>
  plan complete      <PLN-ID>
  plan count         [--active | --all]
  intent add         --feature TEXT --situation TEXT --goal TEXT [--motivation TEXT] [--req REQ-NNN] [--plan PLN-NNN]
  intent get         <INTENT-ID>
  intent list        [--req REQ-NNN] [--plan PLN-NNN]
  intent update      <INTENT-ID> [--feature TEXT] [--situation TEXT] [--motivation TEXT] [--goal TEXT]
                     [--req REQ-NNN] [--plan PLN-NNN] [--related-intent INTENT-ID] [--tag TAG] [--file PATH]
  intent delete      <INTENT-ID>
  intent search      <KEYWORD>
  intent lookup      --files <PATH...>
  intent related     <INTENT-ID> [--depth N]
  intent rebuild
  fact-check add     --plan PLN-NNN [--status STATUS] [--json]
  fact-check get     <FC-ID> [--json]
  fact-check list    [--plan PLN-NNN] [--status STATUS] [--json]
  fact-check search  <KEYWORD> [--tag TAG] [--status STATUS] [--plan PLN-NNN] [--limit N] [--json]
  fact-check update  <FC-ID> [--status STATUS] [--json]
  fact-check claim-update <FC-ID> <CL-ID> [--status STATUS] [--add-evidence URL SNIPPET] [--json]
  reference add      --topic TEXT --url URL --summary TEXT [--content TEXT] [--json]
  reference get      <REF-ID> [--json]
  reference list     [--json]
  reference search   --keyword TEXT [--json]
  reference update   <REF-ID> [--topic TEXT] [--url URL] [--summary TEXT] [--content TEXT] [--json]

  agile init         [--steering-every N] [--json]
  agile status       <AGI-ID> [--json]
  agile update       <AGI-ID> [--status TEXT] [--current-sprint N] [--steering-every N] [--objective-version N] [--json]
  agile result       <AGI-ID> --sprint N --status TEXT [--planned IDS] [--completed IDS] [--pln IDS] [--req IDS] [--summary TEXT] [--outcome TEXT] [--sprint-goals JSON] [--json]
  agile retrospective <AGI-ID> --sprint N --status TEXT --succeeded IDS --failed JSON [--failed JSON ...] --velocity-planned N --velocity-completed N --limitations TEXT --lessons TEXT --direction TEXT [--json]
  agile known-issues add <AGI-ID> --description TEXT --severity MINOR|MAJOR|CRITICAL --sprint N [--json]
  agile known-issues resolve <AGI-ID> --issue-id KI-NNN [--json]
  agile known-issues list <AGI-ID> [--status open|resolved] [--json]
  agile objective-transition <AGI-ID> --story DOD-ID --status TEXT [--json]
  agile objective-check <AGI-ID> [--json]
  agile objective-snapshot <AGI-ID> --reason TEXT [--json]
  agile link         <AGI-ID> [--pln PLN-NNN] [--req REQ-NNN] [--json]

  archive run         [--type req|idn|dsc|dbg|exp|pln|des|cap|agi] [--max N] [--dir PATH]
  archive run-all     [--max N]
  archive list        [--type TYPE]
  archive restore     <ARCHIVE-ID>
  gardening scan      [--json]
  capture ttl-check
  capture mark-consumed --caps <CAP-ID[,CAP-ID...]> --plan <PLN-ID> [--json]

  counter next        [--type req|idn|dsc|dbg|exp|pln|des|cap|fc|ref|intent|agi] [--dir PATH]
  counter peek        [--type req|idn|dsc|dbg|exp|pln|des|cap|fc|ref|intent|agi]

  version get
  version check
  version bump        <patch|minor|major>

  context gather      [--diff N] [--skills] [--agents] [--format text|json]
  state set          --skill NAME --step N --total M [--return-to SKILL/STEP]
  state set-workflow --active true|false [--skill NAME] [--req REQ-NNN]
                     [--next-skill NAME] [--next-source ID] [--source-skill NAME] [--auto true|false]
                     [--agile-loop-active true|false] [--steering-disabled true|false]
  state get
  state clear
  measure stop-rate   [--snapshots-dir PATH] [--pretty]

  task set-commit     <TASK-ID> <commit hash> <commit message>
  explore index       --report PATH [--output PATH]

  agents check
  agents sync

  cleanup             [--dry-run]

  session list        [--type ideation|discussion|debug]
  session inspect     <SESSION-ID>
  session complete    <SESSION-ID>

  priority            <TASK-ID> [--before TASK-ID | --after TASK-ID]

  wait-files          <file1> [file2 ...] [--timeout SECONDS]
  resolve-model       <provider> <tier_or_section>
  config get          <key.path> [--default VALUE] [--json]
"""

import argparse
import copy
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import glob
import tarfile
import time
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Base directory discovery
# ---------------------------------------------------------------------------

def find_base_dir(start: Path = None) -> Path:
    """Walk up from start (or cwd) to find .gran-maestro/"""
    if start is None:
        start = Path.cwd()
    current = start.resolve()
    while True:
        candidate = current / ".gran-maestro"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            print("Error: .gran-maestro/ directory not found in any ancestor directory.", file=sys.stderr)
            sys.exit(1)
        current = parent


BASE_DIR: Path = None  # resolved in main()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _plugin_root():
    """플러그인 루트 경로 반환 (scripts/ 상위)."""
    return Path(__file__).resolve().parent.parent


def deep_merge(base, override, depth=0):
    if depth > 20:
        return override

    if not isinstance(base, dict) or not isinstance(override, dict):
        return override

    result = dict(base)
    for key, override_value in override.items():
        base_value = base.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            result[key] = deep_merge(base_value, override_value, depth + 1)
        elif isinstance(override_value, list):
            result[key] = override_value
        else:
            result[key] = override_value
    return result


def requests_dir() -> Path:
    return BASE_DIR / "requests"


def plans_dir() -> Path:
    return BASE_DIR / "plans"


def iter_request_dirs(include_completed=False):
    """Yield (req_id, path, data) tuples."""
    for req_path in sorted(requests_dir().glob("REQ-*")):
        if not req_path.is_dir():
            continue
        rj = load_json(req_path / "request.json")
        if rj:
            yield rj.get("id", req_path.name), req_path, rj
    if include_completed:
        archived = type_archived_dir("req")
        if archived.exists():
            for arc_file in sorted(archived.glob("*.tar.gz")):
                try:
                    with tarfile.open(arc_file, "r:gz") as tar:
                        for member in tar.getmembers():
                            if (member.name.endswith("/request.json")
                                    and member.name.count("/") == 1):
                                f = tar.extractfile(member)
                                if f:
                                    rj = json.loads(f.read().decode("utf-8"))
                                    yield rj.get("id", member.name.split("/")[0]), arc_file, rj
                except Exception:
                    pass


def iter_plan_dirs():
    """Yield (pln_id, path, data) tuples."""
    pd = plans_dir()
    if not pd.exists():
        return
    for pln_path in sorted(pd.glob("PLN-*")):
        if not pln_path.is_dir():
            continue
        pj = load_json(pln_path / "plan.json")
        if pj:
            yield pj.get("id", pln_path.name), pln_path, pj


def format_table_row(req_id, data):
    status = data.get("status", "?")
    phase = data.get("current_phase", "?")
    title = (data.get("title") or "")[:55]
    return f"{req_id:<12} P{phase:<3} {status:<28} {title}"


# ---------------------------------------------------------------------------
# request subcommands
# ---------------------------------------------------------------------------

def cmd_request_list(args):
    rows = []
    include_completed = (args.scope == "all")
    for req_id, path, data in iter_request_dirs(include_completed):
        status = data.get("status", "")
        if args.scope == "active" and status == "completed":
            continue
        if args.scope == "completed" and status != "completed":
            continue
        rows.append((req_id, data))

    if args.format == "json":
        for req_id, data in rows:
            print(json.dumps({"id": req_id, **data}))
    else:
        print(f"{'ID':<12} {'Phase':<4} {'Status':<28} {'Title'}")
        print("-" * 80)
        for req_id, data in rows:
            print(format_table_row(req_id, data))
    return 0


def cmd_request_inspect(args):
    req_id = args.req_id.upper()
    for rid, path, data in iter_request_dirs(include_completed=True):
        if rid == req_id:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            # also show task specs if present
            tasks_dir = path / "tasks"
            if tasks_dir.exists():
                for task_path in sorted(tasks_dir.iterdir()):
                    spec = task_path / "spec.md"
                    if spec.exists():
                        print(f"\n--- {task_path.name}/spec.md ---")
                        print(spec.read_text(encoding="utf-8")[:2000])
            return 0
    print(f"Error: {req_id} not found.", file=sys.stderr)
    return 1


def cmd_request_history(args):
    rows = []
    for req_id, path, data in iter_request_dirs(include_completed=True):
        if data.get("status") == "completed":
            rows.append((req_id, data))
    if not rows:
        print("No completed requests found.")
        return 0
    print(f"{'ID':<12} {'Status':<28} {'Title'}")
    print("-" * 80)
    for req_id, data in rows:
        print(format_table_row(req_id, data))
    return 0


def cmd_request_filter(args):
    for req_id, path, data in iter_request_dirs(include_completed=False):
        if args.phase is not None and data.get("current_phase") != args.phase:
            continue
        # pending_dependency는 --status 명시 없는 한 기본 제외
        if not args.status and data.get("status") == "pending_dependency":
            continue
        if args.status and data.get("status") != args.status:
            continue
        if args.priority and data.get("priority", "normal") != args.priority:
            continue
        if args.format == "json":
            print(json.dumps({"id": req_id, **data}))
        else:
            print(format_table_row(req_id, data))
    return 0


def cmd_request_count(args):
    count = 0
    include_completed = (args.scope == "all")
    for req_id, path, data in iter_request_dirs(include_completed):
        status = data.get("status", "")
        if args.scope == "active" and status == "completed":
            continue
        if args.scope == "completed" and status != "completed":
            continue
        count += 1
    print(count)
    return 0


def cmd_request_cancel(args):
    req_id = args.req_id.upper()
    for rid, path, data in iter_request_dirs(include_completed=True):
        if rid == req_id:
            if data.get("status") == "cancelled":
                print(f"{req_id} is already cancelled.")
                return 0
            from _state_manager import cancel
            cancel(BASE_DIR, req_id)
            print(f"Cancelled: {req_id}")
            return 0
    print(f"Error: {req_id} not found.", file=sys.stderr)
    return 1


WORKFLOW_MAX_ITERATIONS = 20
WORKFLOW_STALL_LIMIT = 3
WORKFLOW_TERMINAL_STATUSES = {"done", "completed", "accepted", "cancelled"}


def _request_json_path(req_id: str) -> Path:
    return BASE_DIR / "requests" / req_id / "request.json"


def _plan_json_path(pln_id: str) -> Path:
    return BASE_DIR / "plans" / pln_id / "plan.json"


def _load_request(req_id: str):
    return load_json(_request_json_path(req_id))


def _load_plan(pln_id: str):
    return load_json(_plan_json_path(pln_id))


def _phase_value(raw_phase) -> Optional[int]:
    try:
        return int(raw_phase)
    except (TypeError, ValueError):
        return None


def _phase_status_tuple(data):
    return _phase_value(data.get("current_phase")), str(data.get("status", ""))


def _is_terminal(phase: Optional[int], status: str) -> bool:
    status_normalized = (status or "").lower()
    return status_normalized in WORKFLOW_TERMINAL_STATUSES or (
        phase == 5 and status_normalized in {"done", "completed", "accepted"}
    )


def next_action(current_phase, status):
    phase = _phase_value(current_phase)
    status_normalized = (status or "").lower()
    if status_normalized in WORKFLOW_TERMINAL_STATUSES:
        return None
    if phase == 1 and status_normalized in {"phase1_analysis", "spec_ready"}:
        return "mst:approve"
    if phase == 2 and status_normalized == "phase2_execution":
        return "mst:approve"
    if phase == 3 and status_normalized == "phase3_review":
        return "mst:approve"
    if phase == 5:
        return "mst:accept"
    return None


def _run_claude(cmd):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR.parent),
    )
    if result.stdout:
        print(result.stdout.rstrip("\n"))
    if result.stderr:
        print(result.stderr.rstrip("\n"), file=sys.stderr)
    return result.returncode


def _run_req_workflow(req_id: str, max_iterations: int = WORKFLOW_MAX_ITERATIONS) -> int:
    unchanged_count = 0
    req_id = req_id.upper()

    for _ in range(max_iterations):
        before = _load_request(req_id)
        if not before:
            print(f"[workflow] Request not found: {req_id}", file=sys.stderr)
            return 1
        before_phase, before_status = _phase_status_tuple(before)
        if _is_terminal(before_phase, before_status):
            return 0

        action = next_action(before_phase, before_status)
        if action is None:
            print(
                f"[workflow] No action for state (phase={before_phase}, status={before_status})",
                file=sys.stderr,
            )
            return 1

        _run_claude(["claude", f"/{action}", req_id, "-a"])

        after = _load_request(req_id)
        if not after:
            print(f"[workflow] Request not found after action: {req_id}", file=sys.stderr)
            return 1
        after_phase, after_status = _phase_status_tuple(after)

        if _is_terminal(after_phase, after_status):
            return 0

        if (after_phase, after_status) == (before_phase, before_status):
            unchanged_count += 1
            if unchanged_count >= WORKFLOW_STALL_LIMIT:
                print(
                    f"[workflow] Stalled: (phase={after_phase}, status={after_status}) unchanged for 3 iterations",
                    file=sys.stderr,
                )
                return 1
        else:
            unchanged_count = 0

    print(f"[workflow] Max iterations ({max_iterations}) reached", file=sys.stderr)
    return 1


def _plan_linked_requests(pln_id: str):
    plan = _load_plan(pln_id)
    if not plan:
        return []
    linked = plan.get("linked_requests")
    if not isinstance(linked, list):
        return []
    return [req_id.upper() for req_id in linked if isinstance(req_id, str)]


def _incomplete_requests(req_ids):
    incomplete = []
    for req_id in req_ids:
        req = _load_request(req_id)
        if not req:
            continue
        phase, status = _phase_status_tuple(req)
        if not _is_terminal(phase, status):
            incomplete.append(req_id)
    return incomplete


def _topo_sort_requests(req_ids):
    index_map = {req_id: idx for idx, req_id in enumerate(req_ids)}
    indegree = {req_id: 0 for req_id in req_ids}
    graph = {req_id: [] for req_id in req_ids}

    for req_id in req_ids:
        req = _load_request(req_id) or {}
        deps = req.get("dependencies")
        if not isinstance(deps, dict):
            continue
        blocked_by = deps.get("blockedBy")
        if not isinstance(blocked_by, list):
            continue
        for dep in blocked_by:
            dep_id = dep.upper() if isinstance(dep, str) else None
            if dep_id not in indegree:
                continue
            indegree[req_id] += 1
            graph[dep_id].append(req_id)

    ready = sorted(
        [req_id for req_id, degree in indegree.items() if degree == 0],
        key=lambda req_id: index_map[req_id],
    )
    ordered = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for nxt in graph[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda req_id: index_map[req_id])

    if len(ordered) == len(req_ids):
        return ordered
    return sorted(req_ids, key=lambda req_id: index_map[req_id])


def cmd_workflow_run(args):
    target = args.target.upper()

    if target.startswith("REQ-"):
        return _run_req_workflow(target)

    if not target.startswith("PLN-"):
        print("Error: target must be PLN-NNN or REQ-NNN.", file=sys.stderr)
        return 1

    linked = _plan_linked_requests(target)
    pending = _incomplete_requests(linked)

    if not pending:
        _run_claude(["claude", "/mst:request", "--plan", target, "-a"])
        linked = _plan_linked_requests(target)
        pending = _incomplete_requests(linked)
        if not pending:
            print(f"[workflow] No runnable requests linked to {target}", file=sys.stderr)
            return 1

    for req_id in _topo_sort_requests(pending):
        result = _run_req_workflow(req_id)
        if result != 0:
            return result
    return 0


def cmd_timestamp(args):
    """현재 UTC ISO 타임스탬프를 stdout 출력."""
    from _state_manager import timestamp_now
    print(timestamp_now())
    return 0


def cmd_set_status(args):
    """지정 ID의 status 필드 + updated_at 갱신."""
    from _state_manager import set_status
    set_status(BASE_DIR, args.id, args.status)
    return 0


def cmd_set_field(args):
    """지정 ID의 단일 JSON 필드 업데이트."""
    from _state_manager import set_field
    set_field(BASE_DIR, args.id, args.field, args.value)
    return 0


def _skill_state_base_dir() -> Path:
    local_base_dir = Path.cwd().resolve() / ".gran-maestro"
    if local_base_dir.exists():
        return local_base_dir
    if BASE_DIR and os.access(BASE_DIR, os.W_OK):
        return BASE_DIR
    return local_base_dir


def _parse_bool_arg(value):
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Expected true/false.")


def _workflow_state_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _workflow_state_default_payload(now: str):
    return {
        "workflow_active": False,
        "next_action": {
            "skill": "",
            "source": "",
            "auto": False,
            "expected_skill": "",
            "source_skill": "",
            "source_id": "",
            "auto_mode": False,
        },
        "current_skill": "",
        "active_req": "",
        "iteration": 0,
        "agile_loop_active": False,
        "steering_disabled": False,
        "block_count": 0,
        "last_block_reason": "",
        "updated_at": now,
    }


def _workflow_state_file(base_dir: Path) -> Path:
    parent_pid = os.getenv("MST_STATE_PPID")
    if not (isinstance(parent_pid, str) and parent_pid.isdigit()):
        parent_pid = str(os.getppid())
    return base_dir / "tmp" / f"mst-state-{parent_pid}.json"


def _workflow_state_load(path: Path):
    payload = load_json(path)
    if isinstance(payload, dict):
        return payload
    return None


def _workflow_state_atomic_write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def cmd_state_set_workflow(args):
    state_base_dir = _skill_state_base_dir()
    state_path = _workflow_state_file(state_base_dir)
    now = _workflow_state_timestamp()

    try:
        payload = _workflow_state_load(state_path)
        if not isinstance(payload, dict):
            payload = _workflow_state_default_payload(now)

        next_action = payload.get("next_action")
        if not isinstance(next_action, dict):
            next_action = {}

        payload["workflow_active"] = bool(args.active)
        payload["current_skill"] = args.skill if args.active else ""
        payload["active_req"] = args.req if args.active else ""
        payload["iteration"] = payload.get("iteration") if isinstance(payload.get("iteration"), int) else 0
        payload["agile_loop_active"] = (
            payload.get("agile_loop_active")
            if isinstance(payload.get("agile_loop_active"), bool)
            else False
        )
        payload["steering_disabled"] = (
            payload.get("steering_disabled")
            if isinstance(payload.get("steering_disabled"), bool)
            else False
        )
        block_count = payload.get("block_count")
        payload["block_count"] = (
            block_count
            if isinstance(block_count, int) and not isinstance(block_count, bool)
            else 0
        )
        payload["last_block_reason"] = (
            payload.get("last_block_reason")
            if isinstance(payload.get("last_block_reason"), str)
            else ""
        )

        if args.agile_loop_active is not None:
            payload["agile_loop_active"] = bool(args.agile_loop_active)
            if not payload["agile_loop_active"]:
                payload["block_count"] = 0
        if args.steering_disabled is not None:
            payload["steering_disabled"] = bool(args.steering_disabled)

        payload["updated_at"] = now

        if args.active:
            expected_skill = args.next_skill or ""
            source_id = args.next_source or ""
            source_skill = args.source_skill or args.skill or ""
            auto_mode = bool(args.auto)
            next_action.update(
                {
                    "skill": expected_skill,
                    "source": source_id,
                    "auto": auto_mode,
                    "expected_skill": expected_skill,
                    "source_skill": source_skill,
                    "source_id": source_id,
                    "auto_mode": auto_mode,
                }
            )
        else:
            next_action.update(
                {
                    "skill": "",
                    "source": "",
                    "auto": False,
                    "expected_skill": "",
                    "source_skill": "",
                    "source_id": "",
                    "auto_mode": False,
                }
            )

        payload["next_action"] = next_action
        _workflow_state_atomic_write(state_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[mst] warning: failed to update workflow state: {exc}", file=sys.stderr)
        return 0

    return 0


def cmd_state_set(args):
    from _skill_state import set_snapshot

    state_base_dir = _skill_state_base_dir()
    data = set_snapshot(
        state_base_dir,
        skill=args.skill,
        step=args.step,
        total=args.total,
        return_to=args.return_to,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_get(args):
    from _skill_state import get_snapshot

    data = get_snapshot(_skill_state_base_dir())
    if data is None:
        print("스냅샷 없음")
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_state_clear(args):
    from _skill_state import clear_snapshot

    clear_snapshot(_skill_state_base_dir())
    print("스냅샷 초기화 완료")
    return 0


def cmd_measure_stop_rate(args):
    script_path = Path(__file__).resolve().parent / "measure_stop_rate.py"
    cmd = [sys.executable, str(script_path)]

    if args.snapshots_dir:
        cmd.extend(["--snapshots-dir", args.snapshots_dir])
    if args.pretty:
        cmd.append("--pretty")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR.parent),
    )

    if result.stdout:
        print(result.stdout.rstrip("\n"))
    if result.stderr:
        print(result.stderr.rstrip("\n"), file=sys.stderr)
    return result.returncode


def cmd_request_set_phase(args):
    """REQ의 current_phase와 status를 원자적으로 변경."""
    from _state_manager import set_phase
    set_phase(BASE_DIR, args.req_id, args.phase, args.status)
    print(f"{args.req_id}: phase={args.phase}, status={args.status}")
    return 0


def cmd_plan_list(args):
    rows = []
    for pln_id, path, data in iter_plan_dirs():
        status = data.get("status", "")
        if args.scope == "active" and status not in ("active", "in_progress"):
            continue
        rows.append((pln_id, data))

    print(f"{'ID':<10} {'Status':<12} {'Linked':<6} {'Title'}")
    print("-" * 80)
    for pln_id, data in rows:
        linked = data.get("linked_requests", [])
        linked_count = len(linked) if isinstance(linked, list) else 0
        title = (data.get("title") or "")[:55]
        print(f"{pln_id:<10} {data.get('status', ''):<12} {linked_count:<6} {title}")
    return 0


def cmd_plan_count(args):
    count = 0
    for pln_id, path, data in iter_plan_dirs():
        status = data.get("status", "")
        if args.scope == "active" and status not in ("active", "in_progress"):
            continue
        if args.scope == "completed" and status != "completed":
            continue
        count += 1
    print(count)
    return 0


def cmd_plan_inspect(args):
    pln_id = args.pln_id.upper()
    for pid, path, data in iter_plan_dirs():
        if pid == pln_id:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
    print(f"Error: {pln_id} not found.", file=sys.stderr)
    return 1


def cmd_plan_sync(args):
    """plan.json의 linked_requests 전체가 done/completed이면 plan을 completed로 업데이트"""
    plan_id = args.plan_id.upper()
    for pid, path, data in iter_plan_dirs():
        if pid == plan_id:
            linked = data.get("linked_requests", [])
            if not linked:
                print(f"{plan_id}: linked_requests 없음, 스킵")
                return 0
            all_done = True
            for req_id in linked:
                req_path = requests_dir() / req_id / "request.json"
                if req_path.exists():
                    req_data = load_json(req_path)
                    st = req_data.get("status", "") if req_data else ""
                    if st not in ("done", "completed", "cancelled"):
                        all_done = False
                        break
                # 파일 없으면(아카이브된 경우) 완료로 간주
            if all_done:
                data["status"] = "completed"
                from datetime import datetime, timezone
                data["completed_at"] = datetime.now(timezone.utc).isoformat()
                save_json(path / "plan.json", data)
                print(f"{plan_id}: completed")
            else:
                print(f"{plan_id}: 미완료 REQ 있음, 스킵")
            return 0
    print(f"Error: {plan_id} not found.", file=sys.stderr)
    return 1


def cmd_plan_complete(args):
    pln_id = args.pln_id.upper()
    for pid, path, data in iter_plan_dirs():
        if pid == pln_id:
            if data.get("status") == "completed":
                print(f"{pln_id} is already completed.")
                return 0
            from _state_manager import complete
            complete(BASE_DIR, pln_id)
            print(f"Completed: {pln_id}")
            return 0
    print(f"Error: {pln_id} not found.", file=sys.stderr)
    return 1


def cmd_plan_render_review(args):
    """plan-review 템플릿을 치환해 prompts/review-{role}.md 파일로 생성한다."""
    pln_id = args.pln_id.upper()

    # 1. PLN 디렉토리 확인
    pln_dir = plans_dir() / pln_id
    if not pln_dir.exists():
        print(f"Error: {pln_id} not found.", file=sys.stderr)
        return 1

    # 2. plan_draft 취득 (파일 우선, 없으면 인라인 인자)
    if args.plan_draft_file:
        plan_draft = Path(args.plan_draft_file).read_text(encoding="utf-8")
    else:
        plan_draft = args.plan_draft or ""
    qa_summary = args.qa_summary or ""

    # 3. config에서 활성 역할 결정 (기본값 True = 모두 활성)
    config = load_json(BASE_DIR / "config.json") or {}
    plan_review = config.get("plan_review", {})
    roles_config = plan_review.get("roles", {})
    all_roles = ["architect", "devils_advocate", "completeness", "ux_reviewer"]
    active_roles = [
        r for r in all_roles
        if roles_config.get(r, {}).get("enabled", True)
    ]

    # 4. 템플릿 디렉토리 (PROJECT_ROOT/templates/plan-review/)
    # Path(__file__)을 기준으로 project_root 계산: scripts/mst.py → scripts/ → project_root
    # BASE_DIR.parent는 워크트리에서 항상 메인 repo 루트를 가리키므로 사용 불가
    project_root = Path(__file__).parent.parent
    template_dir = project_root / "templates" / "plan-review"

    # 5. prompts/ 디렉토리 생성
    prompts_dir = pln_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # 6. 각 역할별 템플릿 읽기 → 치환 → 파일 쓰기 → stdout 출력
    generated = []
    for role in active_roles:
        tmpl_path = template_dir / f"{role}.md"
        if not tmpl_path.exists():
            print(f"Warning: template not found: {tmpl_path}", file=sys.stderr)
            continue
        content = tmpl_path.read_text(encoding="utf-8")
        content = content.replace("{{PLAN_DRAFT}}", plan_draft)
        content = content.replace("{{QA_SUMMARY}}", qa_summary)
        content = content.replace("{{PLN_ID}}", pln_id)

        out_path = prompts_dir / f"review-{role}.md"
        out_path.write_text(content, encoding="utf-8")
        generated.append(str(out_path))
        print(str(out_path))

    return 0 if generated else 1


def _create_intent_store():
    try:
        from intent_store import IntentStoreError, SqliteIntentStore
        store = SqliteIntentStore(BASE_DIR.parent)
    except ImportError as exc:
        print(
            f"Error: intent store dependency missing ({exc}). Install with: pip install pyyaml",
            file=sys.stderr,
        )
        return None, Exception
    except Exception as exc:
        print(f"Error: failed to initialize intent store ({exc})", file=sys.stderr)
        return None, Exception
    return store, IntentStoreError


def _next_intent_id():
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "counter",
        "next",
        "--type",
        "intent",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "counter next failed")

    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("counter next produced no id")


def fact_checks_dir() -> Path:
    return BASE_DIR / "fact-checks"


def _normalize_fact_check_id(value: str) -> str:
    fc_id = (value or "").strip().upper()
    if not re.fullmatch(r"FC-\d+", fc_id):
        raise ValueError(f"Invalid fact-check id: {value}")
    return fc_id


def _normalize_claim_id(value: str) -> str:
    claim_id = (value or "").strip().upper()
    if not re.fullmatch(r"CL-\d+", claim_id):
        raise ValueError(f"Invalid claim id: {value}")
    return claim_id


def _fact_check_path(fc_id: str) -> Path:
    return fact_checks_dir() / fc_id / "fact-check.json"


def _iter_fact_check_paths():
    pattern = str(fact_checks_dir() / "FC-*" / "fact-check.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]


def _compute_fact_check_summary(claims):
    summary = {"total": 0, "verified": 0, "failed": 0, "unverified": 0}
    if not isinstance(claims, list):
        return summary

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status", "unverified")).strip().lower()
        if status == "verified":
            summary["verified"] += 1
        elif status == "failed":
            summary["failed"] += 1
        else:
            summary["unverified"] += 1
    summary["total"] = summary["verified"] + summary["failed"] + summary["unverified"]
    return summary


def _load_fact_check(fc_id: str):
    normalized_id = _normalize_fact_check_id(fc_id)
    fc_path = _fact_check_path(normalized_id)
    data = load_json(fc_path)
    if not isinstance(data, dict):
        raise ValueError(f"{normalized_id} not found")
    claims = data.get("claims")
    if not isinstance(claims, list):
        claims = []
        data["claims"] = claims
    data["id"] = normalized_id
    data["summary"] = _compute_fact_check_summary(claims)
    return data, fc_path


def _save_fact_check(data):
    fc_id = _normalize_fact_check_id(data.get("id", ""))
    claims = data.get("claims")
    if not isinstance(claims, list):
        claims = []
        data["claims"] = claims
    data["summary"] = _compute_fact_check_summary(claims)
    save_json(_fact_check_path(fc_id), data)


def _next_fact_check_id():
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "counter",
        "next",
        "--type",
        "fc",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "counter next failed")

    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("counter next produced no id")


def cmd_fact_check_add(args):
    plan_id = (args.plan or "").strip().upper()
    if not re.fullmatch(r"PLN-\d+", plan_id):
        print("Error: --plan must be PLN-NNN", file=sys.stderr)
        return 1

    try:
        fact_check_id = _next_fact_check_id()
    except RuntimeError as exc:
        print(f"Error: failed to allocate fact-check id ({exc})", file=sys.stderr)
        return 1

    payload = {
        "id": fact_check_id,
        "linked_plan": plan_id,
        "status": str(args.status or "in_progress"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claims": [],
        "summary": {"total": 0, "verified": 0, "failed": 0, "unverified": 0},
    }
    _save_fact_check(payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(fact_check_id)
    return 0


def cmd_fact_check_get(args):
    try:
        data, _ = _load_fact_check(args.fact_check_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        summary = data.get("summary", {})
        print(
            f"{data.get('id', '')} "
            f"plan={data.get('linked_plan', '-')}, "
            f"status={data.get('status', '-')}, "
            f"claims={summary.get('total', 0)}"
        )
    return 0


def cmd_fact_check_list(args):
    entries = []
    plan_filter = (args.plan or "").strip().upper() if args.plan else None
    status_filter = (args.status or "").strip().lower() if args.status else None

    for fc_path in _iter_fact_check_paths():
        data = load_json(fc_path)
        if not isinstance(data, dict):
            continue
        fc_id = str(data.get("id") or fc_path.parent.name).upper()
        linked_plan = str(data.get("linked_plan", "")).upper()
        fc_status = str(data.get("status", "")).lower()

        if plan_filter and linked_plan != plan_filter:
            continue
        if status_filter and fc_status != status_filter:
            continue

        claims = data.get("claims")
        summary = _compute_fact_check_summary(claims)
        entries.append(
            {
                "id": fc_id,
                "linked_plan": linked_plan,
                "status": data.get("status", ""),
                "created_at": data.get("created_at", ""),
                "summary": summary,
            }
        )

    entries.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No fact-checks found.")
        return 0

    print(f"{'ID':<8} {'Plan':<10} {'Status':<12} {'Claims':<7} {'Created'}")
    print("-" * 80)
    for entry in entries:
        print(
            f"{entry.get('id', ''):<8} {entry.get('linked_plan', ''):<10} "
            f"{entry.get('status', ''):<12} {entry.get('summary', {}).get('total', 0):<7} "
            f"{entry.get('created_at', '')}"
        )
    return 0


def cmd_fact_check_search(args):
    keyword = (args.keyword or "").strip().lower()
    if not keyword:
        print("[]")
        return 0

    plan_filter = (args.plan or "").strip().upper() if args.plan else None
    status_filter = (args.status or "").strip().lower() if args.status else None
    tag_filter = (args.tag or "").strip().lower() if args.tag else None
    limit = args.limit if args.limit and args.limit > 0 else None

    matches = []
    stop = False
    for fc_path in _iter_fact_check_paths():
        data = load_json(fc_path)
        if not isinstance(data, dict):
            continue

        fc_id = str(data.get("id") or fc_path.parent.name).upper()
        linked_plan = str(data.get("linked_plan", "")).upper()
        if plan_filter and linked_plan != plan_filter:
            continue

        claims = data.get("claims")
        if not isinstance(claims, list):
            continue

        for claim in claims:
            if not isinstance(claim, dict):
                continue

            claim_text = str(claim.get("text", ""))
            claim_status = str(claim.get("status", "unverified")).lower()
            claim_tags = claim.get("tags") if isinstance(claim.get("tags"), list) else []
            claim_tags_normalized = [str(tag).strip().lower() for tag in claim_tags]

            if keyword not in claim_text.lower():
                continue
            if tag_filter and tag_filter not in claim_tags_normalized:
                continue
            if status_filter and claim_status != status_filter:
                continue

            evidence = claim.get("evidence")
            if not isinstance(evidence, list):
                evidence = []

            matches.append(
                {
                    "fact_check_id": fc_id,
                    "linked_plan": linked_plan,
                    "fact_check_status": data.get("status", ""),
                    "claim": {
                        "id": claim.get("id"),
                        "text": claim_text,
                        "source_reliability": claim.get("source_reliability"),
                        "status": claim.get("status", "unverified"),
                        "tags": claim_tags,
                        "evidence": evidence,
                    },
                }
            )

            if limit is not None and len(matches) >= limit:
                stop = True
                break
        if stop:
            break

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if not matches:
        print("No matching claims found.")
        return 0

    for item in matches:
        claim = item.get("claim", {})
        print(
            f"{item.get('fact_check_id', '')} {claim.get('id', '')} "
            f"[{claim.get('status', '')}] {claim.get('text', '')}"
        )
    return 0


def cmd_fact_check_update(args):
    try:
        data, _ = _load_fact_check(args.fact_check_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed = False
    if args.status is not None:
        data["status"] = str(args.status)
        changed = True

    if not changed:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    _save_fact_check(data)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data.get("id"))
    return 0


def cmd_fact_check_claim_update(args):
    try:
        fc_data, _ = _load_fact_check(args.fact_check_id)
        target_claim_id = _normalize_claim_id(args.claim_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    claims = fc_data.get("claims")
    if not isinstance(claims, list):
        claims = []
        fc_data["claims"] = claims

    claim = None
    for item in claims:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("id", "")).strip().upper()
        if candidate_id == target_claim_id:
            claim = item
            break
    if claim is None:
        print(f"Error: {target_claim_id} not found in {fc_data.get('id')}", file=sys.stderr)
        return 1

    changed = False
    if args.status is not None:
        claim["status"] = str(args.status)
        changed = True

    if args.add_evidence:
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
            claim["evidence"] = evidence
        for url, snippet in args.add_evidence:
            evidence.append(
                {
                    "type": args.evidence_type,
                    "url": str(url),
                    "snippet": str(snippet),
                    "accessed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            changed = True

    if not changed:
        print("Error: no claim fields to update", file=sys.stderr)
        return 1

    _save_fact_check(fc_data)

    if args.json:
        print(json.dumps({"fact_check_id": fc_data.get("id"), "claim": claim}, ensure_ascii=False, indent=2))
    else:
        print(f"{fc_data.get('id')} {target_claim_id}")
    return 0


DEFAULT_REFERENCE_KEYWORDS = [
    "library",
    "framework",
    "api",
    "sdk",
    "protocol",
    "version",
    "dependency",
    "react",
    "next.js",
    "typescript",
    "python",
    "node",
    "라이브러리",
    "프레임워크",
    "의존성",
    "버전",
]
DEFAULT_REFERENCE_CONFIG = {
    "cache_ttl_days": 7,
    "cutoff_threshold_months": 1,
    "auto_search": True,
    "max_searches_per_step": 3,
}


def references_dir() -> Path:
    return BASE_DIR / "references"


def _normalize_reference_id(value: str) -> str:
    ref_id = (value or "").strip().upper()
    if not re.fullmatch(r"REF-\d+", ref_id):
        raise ValueError(f"Invalid reference id: {value}")
    return ref_id


def _reference_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "reference.json"


def _reference_content_path(ref_id: str) -> Path:
    return references_dir() / ref_id / "content.md"


def _iter_reference_paths():
    pattern = str(references_dir() / "REF-*" / "reference.json")
    return [Path(p) for p in sorted(glob.glob(pattern))]


def _coerce_positive_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _load_reference_config():
    config = dict(DEFAULT_REFERENCE_CONFIG)
    config["keywords_whitelist"] = list(DEFAULT_REFERENCE_KEYWORDS)

    resolved = load_json(BASE_DIR / "config.resolved.json")
    if not isinstance(resolved, dict):
        defaults = load_json(_plugin_root() / "templates" / "defaults" / "config.json") or {}
        overrides = load_json(BASE_DIR / "config.json") or {}
        resolved = deep_merge(defaults, overrides)

    raw_reference = resolved.get("reference")
    if not isinstance(raw_reference, dict):
        return config

    config["cache_ttl_days"] = _coerce_positive_int(
        raw_reference.get("cache_ttl_days"),
        DEFAULT_REFERENCE_CONFIG["cache_ttl_days"],
    )
    config["cutoff_threshold_months"] = _coerce_positive_int(
        raw_reference.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )
    config["auto_search"] = bool(raw_reference.get("auto_search", DEFAULT_REFERENCE_CONFIG["auto_search"]))
    config["max_searches_per_step"] = _coerce_positive_int(
        raw_reference.get("max_searches_per_step"),
        DEFAULT_REFERENCE_CONFIG["max_searches_per_step"],
    )

    keywords = raw_reference.get("keywords_whitelist")
    if isinstance(keywords, list):
        normalized = []
        for keyword in keywords:
            text = str(keyword).strip()
            if text:
                normalized.append(text)
        if normalized:
            config["keywords_whitelist"] = normalized

    return config


def _compute_reference_expires_at(searched_at, cache_ttl_days: int):
    searched_dt = _parse_utc_datetime(searched_at)
    if searched_dt is None:
        return None
    return (searched_dt + timedelta(days=cache_ttl_days)).isoformat()


def _check_reference_freshness(reference_data, config=None, now=None):
    if not isinstance(reference_data, dict):
        return "expired"

    searched_dt = _parse_utc_datetime(reference_data.get("searched_at"))
    if searched_dt is None:
        return "expired"

    if config is None:
        config = _load_reference_config()
    ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])
    cutoff_months = _coerce_positive_int(
        config.get("cutoff_threshold_months"),
        DEFAULT_REFERENCE_CONFIG["cutoff_threshold_months"],
    )

    now_dt = now or datetime.now(timezone.utc)
    freshness = "fresh"
    if searched_dt + timedelta(days=ttl_days) < now_dt:
        freshness = "stale"

    cutoff_delta = timedelta(days=cutoff_months * 30)
    if (now_dt - searched_dt) > cutoff_delta:
        freshness = "expired"
    return freshness


def _detect_reference_keywords(text: str, keywords_whitelist=None):
    if not isinstance(text, str) or not text.strip():
        return []

    keywords = keywords_whitelist
    if keywords is None:
        keywords = _load_reference_config().get("keywords_whitelist", [])
    if not isinstance(keywords, list):
        return []

    lowered = text.lower()
    matches = []
    for keyword in keywords:
        candidate = str(keyword).strip()
        if not candidate:
            continue
        if candidate.lower() in lowered:
            matches.append(candidate)
    return sorted(set(matches))


def _build_reference_prompt_block(reference_entries, model_cutoff_date: str, now=None):
    now_dt = now or datetime.now(timezone.utc)
    lines = [
        "[REFERENCE_CONTEXT]",
        f"current_date: {now_dt.date().isoformat()}",
        f"model_cutoff: {model_cutoff_date}",
    ]
    if not isinstance(reference_entries, list) or not reference_entries:
        lines.append("references: none")
    else:
        lines.append("references:")
        for entry in reference_entries:
            if not isinstance(entry, dict):
                continue
            lines.append(
                "- {id} ({freshness}) {topic} | {url}".format(
                    id=entry.get("id", "-"),
                    freshness=entry.get("freshness", "unknown"),
                    topic=entry.get("topic", "-"),
                    url=entry.get("url", "-"),
                )
            )
    lines.append("[/REFERENCE_CONTEXT]")
    return "\n".join(lines)


def _load_reference(ref_id: str):
    normalized_id = _normalize_reference_id(ref_id)
    ref_path = _reference_path(normalized_id)
    content_path = _reference_content_path(normalized_id)
    data = load_json(ref_path)
    if not isinstance(data, dict):
        raise ValueError(f"{normalized_id} not found")

    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    data["id"] = normalized_id
    data["topic"] = str(data.get("topic", ""))
    data["url"] = str(data.get("url", ""))
    data["summary"] = str(data.get("summary", ""))
    data["searched_at"] = str(data.get("searched_at", ""))
    expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
    data["expires_at"] = expires_at or str(data.get("expires_at", ""))
    data["freshness"] = _check_reference_freshness(data, config=config)
    data["content_path"] = str(Path(".gran-maestro") / "references" / normalized_id / "content.md")
    try:
        if content_path.exists():
            content = content_path.read_text(encoding="utf-8")
            data["content"] = content if content else None
        else:
            data["content"] = None
    except (OSError, UnicodeDecodeError):
        data["content"] = None
    return data, ref_path


def _save_reference(data, content=None):
    ref_id = _normalize_reference_id(data.get("id", ""))
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    payload = dict(data)
    payload["id"] = ref_id
    payload["topic"] = str(payload.get("topic", ""))
    payload["url"] = str(payload.get("url", ""))
    payload["summary"] = str(payload.get("summary", ""))
    searched_at = str(payload.get("searched_at", "")).strip()
    if not searched_at:
        searched_at = datetime.now(timezone.utc).isoformat()
    payload["searched_at"] = searched_at
    expires_at = _compute_reference_expires_at(searched_at, cache_ttl_days)
    payload["expires_at"] = expires_at or str(payload.get("expires_at", ""))
    payload["freshness"] = _check_reference_freshness(payload, config=config)
    payload["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
    save_json(_reference_path(ref_id), payload)

    content_path = _reference_content_path(ref_id)
    content_path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        if not content_path.exists():
            content_path.write_text("", encoding="utf-8")
    else:
        content_path.write_text(str(content), encoding="utf-8")


def _next_reference_id():
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "counter",
        "next",
        "--type",
        "ref",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "counter next failed")

    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            return line.strip()
    raise RuntimeError("counter next produced no id")


def cmd_reference_add(args):
    try:
        reference_id = _next_reference_id()
    except RuntimeError as exc:
        print(f"Error: failed to allocate reference id ({exc})", file=sys.stderr)
        return 1

    payload = {
        "id": reference_id,
        "topic": str(args.topic),
        "url": str(args.url),
        "summary": str(args.summary),
        "searched_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_reference(payload, content=args.content)
    data, _ = _load_reference(reference_id)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(reference_id)
    return 0


def cmd_reference_get(args):
    try:
        data, _ = _load_reference(args.reference_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(
            f"{data.get('id', '')} "
            f"[{data.get('freshness', 'unknown')}] "
            f"{data.get('topic', '')} - {data.get('url', '')}"
        )
    return 0


def cmd_reference_list(args):
    entries = []
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])

    for ref_path in _iter_reference_paths():
        data = load_json(ref_path)
        if not isinstance(data, dict):
            continue

        ref_id = str(data.get("id") or ref_path.parent.name).upper()
        data["id"] = ref_id
        data["topic"] = str(data.get("topic", ""))
        data["url"] = str(data.get("url", ""))
        data["summary"] = str(data.get("summary", ""))
        data["searched_at"] = str(data.get("searched_at", ""))
        expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
        data["expires_at"] = expires_at or str(data.get("expires_at", ""))
        data["freshness"] = _check_reference_freshness(data, config=config)
        data["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
        entries.append(data)

    entries.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No references found.")
        return 0

    print(f"{'ID':<8} {'Freshness':<10} {'Topic':<32} {'URL'}")
    print("-" * 100)
    for entry in entries:
        topic = entry.get("topic", "")
        if len(topic) > 31:
            topic = topic[:28] + "..."
        print(
            f"{entry.get('id', ''):<8} "
            f"{entry.get('freshness', 'unknown'):<10} "
            f"{topic:<32} "
            f"{entry.get('url', '')}"
        )
    return 0


def cmd_reference_search(args):
    keyword = (args.keyword or "").strip().lower()
    if not keyword:
        if args.json:
            print("[]")
        else:
            print("No matching references found.")
        return 0

    matches = []
    config = _load_reference_config()
    cache_ttl_days = _coerce_positive_int(config.get("cache_ttl_days"), DEFAULT_REFERENCE_CONFIG["cache_ttl_days"])
    for ref_path in _iter_reference_paths():
        data = load_json(ref_path)
        if not isinstance(data, dict):
            continue

        topic = str(data.get("topic", ""))
        summary = str(data.get("summary", ""))
        if keyword not in topic.lower() and keyword not in summary.lower():
            continue

        ref_id = str(data.get("id") or ref_path.parent.name).upper()
        data["id"] = ref_id
        data["url"] = str(data.get("url", ""))
        data["topic"] = topic
        data["summary"] = summary
        data["searched_at"] = str(data.get("searched_at", ""))
        expires_at = _compute_reference_expires_at(data.get("searched_at"), cache_ttl_days)
        data["expires_at"] = expires_at or str(data.get("expires_at", ""))
        data["freshness"] = _check_reference_freshness(data, config=config)
        data["content_path"] = str(Path(".gran-maestro") / "references" / ref_id / "content.md")
        matches.append(data)

    matches.sort(key=lambda item: item.get("id", ""))

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if not matches:
        print("No matching references found.")
        return 0

    for item in matches:
        print(
            f"{item.get('id', '')} [{item.get('freshness', 'unknown')}] "
            f"{item.get('topic', '')} - {item.get('url', '')}"
        )
    return 0


def cmd_reference_update(args):
    try:
        data, _ = _load_reference(args.reference_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed = False
    if args.topic is not None:
        data["topic"] = str(args.topic)
        changed = True
    if args.url is not None:
        data["url"] = str(args.url)
        changed = True
    if args.summary is not None:
        data["summary"] = str(args.summary)
        changed = True
    if args.searched_at is not None:
        data["searched_at"] = str(args.searched_at)
        changed = True
    if args.content is not None:
        changed = True

    if not changed:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_reference(data, content=args.content)
    updated, _ = _load_reference(data.get("id", ""))

    if args.json:
        print(json.dumps(updated, ensure_ascii=False, indent=2))
    else:
        print(updated.get("id"))
    return 0


def agile_dir() -> Path:
    return BASE_DIR / "agile"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_agi_id(value: str) -> str:
    agi_id = (value or "").strip().upper()
    if not re.fullmatch(r"AGI-\d+", agi_id):
        raise ValueError(f"Invalid AGI id: {value}")
    return agi_id


def _normalize_dod_id(value: str) -> str:
    dod_id = (value or "").strip()
    if not re.fullmatch(r"DOD-[A-Z0-9_-]+", dod_id, flags=re.IGNORECASE):
        raise ValueError(f"Invalid DoD id: {value}")
    return dod_id.upper()


def _normalize_known_issue_id(value: str) -> str:
    issue_id = (value or "").strip().upper()
    if not re.fullmatch(r"KI-\d+", issue_id):
        raise ValueError(f"Invalid known issue id: {value}")
    return issue_id


def _normalize_link_id(value: str, prefix: str) -> str:
    token = (value or "").strip().upper()
    if not token:
        raise ValueError(f"Invalid {prefix} id: {value}")
    if not token.startswith(f"{prefix}-"):
        raise ValueError(f"Invalid {prefix} id: {value}")
    return token


def _split_csv_values(raw_values) -> List[str]:
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    values = []
    for raw_value in raw_values:
        for token in str(raw_value).split(","):
            cleaned = token.strip()
            if cleaned:
                values.append(cleaned)
    return values


def _parse_agile_failed_items(raw_values) -> List[dict]:
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]

    parsed_items = []
    for raw_value in raw_values:
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid --failed JSON: {exc}")

        entries = decoded if isinstance(decoded, list) else [decoded]
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid --failed JSON: each item must be an object")

            tried_approach = str(entry.get("tried_approach", "")).strip()
            failure_reason = str(entry.get("failure_reason", "")).strip()
            if not tried_approach:
                raise ValueError("invalid --failed JSON: missing tried_approach")
            if not failure_reason:
                raise ValueError("invalid --failed JSON: missing failure_reason")

            normalized = dict(entry)
            normalized["tried_approach"] = tried_approach
            normalized["failure_reason"] = failure_reason
            parsed_items.append(normalized)

    return parsed_items


def _parse_agile_sprint_goals(raw_value) -> List[dict]:
    if raw_value is None:
        return []
    raw_text = str(raw_value).strip()
    if not raw_text:
        return []

    try:
        decoded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid --sprint-goals JSON: {exc}")
    if not isinstance(decoded, list):
        raise ValueError("invalid --sprint-goals JSON: expected array")

    parsed_items = []
    for entry in decoded:
        if not isinstance(entry, dict):
            raise ValueError("invalid --sprint-goals JSON: each item must be an object")

        goal = str(entry.get("goal", "")).strip()
        status = str(entry.get("status", "")).strip()
        change_summary = str(entry.get("change_summary", "")).strip()
        if not goal:
            raise ValueError("invalid --sprint-goals JSON: missing goal")
        if not status:
            raise ValueError("invalid --sprint-goals JSON: missing status")
        if not change_summary:
            raise ValueError("invalid --sprint-goals JSON: missing change_summary")

        raw_evidence = entry.get("evidence")
        evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
        screenshots = evidence.get("screenshots")
        if screenshots is None:
            screenshots = []
        if not isinstance(screenshots, list):
            raise ValueError("invalid --sprint-goals JSON: evidence.screenshots must be an array")
        test_results = evidence.get("test_results")
        if test_results is None:
            test_results = {}
        if not isinstance(test_results, dict):
            raise ValueError("invalid --sprint-goals JSON: evidence.test_results must be an object")
        diff = evidence.get("diff")
        if diff is None:
            diff = {}
        if not isinstance(diff, dict):
            raise ValueError("invalid --sprint-goals JSON: evidence.diff must be an object")

        normalized = dict(entry)
        normalized["goal"] = goal
        normalized["status"] = status
        normalized["change_summary"] = change_summary
        normalized["evidence"] = {
            "screenshots": [str(item) for item in screenshots],
            "test_results": test_results,
            "diff": diff,
        }
        parsed_items.append(normalized)

    return parsed_items


def _render_sprint_goals_md_lines(sprint_goals: List[dict]) -> List[str]:
    lines = [
        "## 목표 달성 현황",
        "",
    ]
    if not sprint_goals:
        lines.extend([
            "- 없음",
            "",
        ])
        return lines

    for index, goal_item in enumerate(sprint_goals, start=1):
        goal = str(goal_item.get("goal", "-"))
        status = str(goal_item.get("status", "-"))
        change_summary = str(goal_item.get("change_summary", "-"))
        evidence = goal_item.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        screenshots = evidence.get("screenshots")
        screenshots = screenshots if isinstance(screenshots, list) else []
        test_results = evidence.get("test_results")
        test_results = test_results if isinstance(test_results, dict) else {}
        diff = evidence.get("diff")
        diff = diff if isinstance(diff, dict) else {}

        lines.extend([
            f"### Goal {index}",
            f"- goal: {goal}",
            f"- status: {status}",
            f"- change_summary: {change_summary}",
            f"- evidence.screenshots: {', '.join(str(item) for item in screenshots) if screenshots else '-'}",
            f"- evidence.test_results: {json.dumps(test_results, ensure_ascii=False) if test_results else '-'}",
            f"- evidence.diff: {json.dumps(diff, ensure_ascii=False) if diff else '-'}",
            "",
        ])
    return lines


def _agi_session_dir(agi_id: str) -> Path:
    return agile_dir() / agi_id


def _agi_session_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "session.json"


def _agi_events_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "events.ndjson"


def _agi_objective_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "objective.md"


def _agi_objective_changelog_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "objective" / "changelog.ndjson"


def _agi_links_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "index" / "links.json"


def _agi_known_issues_path(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "known-issues.json"


def _load_agile_known_issues(agi_id: str) -> List[dict]:
    data = load_json(_agi_known_issues_path(agi_id))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _next_known_issue_id(issues: List[dict]) -> str:
    max_number = 0
    for issue in issues:
        issue_id = str(issue.get("id", "")).strip().upper()
        match = re.fullmatch(r"KI-(\d+)", issue_id)
        if not match:
            continue
        max_number = max(max_number, int(match.group(1)))
    return f"KI-{max_number + 1:03d}"


def _append_ndjson(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))
        f.write("\n")


def _append_agile_event(agi_id: str, event: str, payload=None):
    event_data = {
        "timestamp": _now_iso(),
        "event": event,
    }
    if isinstance(payload, dict):
        event_data.update(payload)
    _append_ndjson(_agi_events_path(agi_id), event_data)


def _load_agile_session(agi_id: str):
    session_path = _agi_session_path(agi_id)
    data = load_json(session_path)
    if not isinstance(data, dict):
        raise ValueError(f"{agi_id} session not found")
    return data, session_path


def _save_agile_session(agi_id: str, data):
    payload = dict(data)
    payload["id"] = agi_id
    payload["updated_at"] = _now_iso()
    save_json(_agi_session_path(agi_id), payload)
    return payload


def _next_agile_id() -> str:
    counter_path = get_counter_path("agi")
    scan_root = BASE_DIR / TYPE_DIRS["agi"][0]
    disk_max = 0
    for path in scan_root.glob("AGI-*"):
        if not path.is_dir():
            continue
        try:
            n = int(path.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if n > disk_max:
            disk_max = n

    scan_root.mkdir(parents=True, exist_ok=True)
    data = load_json(counter_path) or {}
    last_id = max(data.get("last_id", 0), disk_max)
    next_id = last_id + 1
    save_json(counter_path, {"last_id": next_id})
    return f"AGI-{next_id:03d}"


def _extract_objective_frontmatter(content: str):
    if not content.startswith("---"):
        return None

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines, idx
    return None


def _extract_yaml_story_statuses(content: str) -> dict[str, str]:
    extracted = _extract_objective_frontmatter(content)
    if extracted is None:
        return {}

    lines, end_index = extracted
    frontmatter_lines = lines[1:end_index]
    story_id_re = re.compile(r"^\s*-\s*id:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")
    status_re = re.compile(r"^\s*status:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")

    statuses = {}
    current_story = None
    current_status = None
    for line in frontmatter_lines:
        story_match = story_id_re.match(line.strip("\r\n"))
        if story_match:
            if current_story:
                statuses[current_story] = (current_status or "todo").lower()
            current_story = story_match.group(1).upper()
            current_status = None
            continue

        if current_story:
            status_match = status_re.match(line.strip("\r\n"))
            if status_match:
                current_status = status_match.group(1)

    if current_story:
        statuses[current_story] = (current_status or "todo").lower()
    return statuses


def _extract_marker_story_statuses(content: str) -> dict[str, str]:
    pattern = re.compile(r"story:(?P<story>[A-Za-z0-9_-]+)\s+status:(?P<status>[A-Za-z0-9_-]+)")
    statuses = {}
    for match in pattern.finditer(content):
        story_id = match.group("story").upper()
        statuses[story_id] = match.group("status").lower()
    return statuses


def _update_yaml_story_status(content: str, story_id: str, new_status: str):
    extracted = _extract_objective_frontmatter(content)
    if extracted is None:
        return content, False, False

    lines, end_index = extracted
    frontmatter_lines = lines[1:end_index]
    story_id_re = re.compile(r"^(\s*)-\s*id:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")
    status_re = re.compile(r"^(\s*)status:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")

    story_start_indexes = []
    for idx, line in enumerate(frontmatter_lines):
        if story_id_re.match(line.strip("\r\n")):
            story_start_indexes.append(idx)
    story_start_indexes.append(len(frontmatter_lines))

    found = False
    changed = False

    for pos in range(len(story_start_indexes) - 1):
        start = story_start_indexes[pos]
        end = story_start_indexes[pos + 1]
        story_line = frontmatter_lines[start].strip("\r\n")
        story_match = story_id_re.match(story_line)
        if not story_match:
            continue
        current_story_id = story_match.group(2).upper()
        if current_story_id != story_id:
            continue

        found = True
        status_found = False
        for line_idx in range(start + 1, end):
            status_line = frontmatter_lines[line_idx].strip("\r\n")
            status_match = status_re.match(status_line)
            if not status_match:
                continue

            status_found = True
            if status_match.group(2).lower() != new_status:
                indent = status_match.group(1)
                line_ending = "\r\n" if frontmatter_lines[line_idx].endswith("\r\n") else "\n"
                frontmatter_lines[line_idx] = f"{indent}status: {new_status}{line_ending}"
                changed = True
            break

        if not status_found:
            indent = f"{story_match.group(1)}  "
            line_ending = "\r\n" if frontmatter_lines[start].endswith("\r\n") else "\n"
            frontmatter_lines.insert(start + 1, f"{indent}status: {new_status}{line_ending}")
            changed = True
            for i in range(pos + 1, len(story_start_indexes)):
                story_start_indexes[i] += 1
            end_index += 1
        break

    if not found:
        return content, False, False

    updated_lines = [lines[0]] + frontmatter_lines + lines[end_index:]
    return "".join(updated_lines), True, changed


def _update_marker_story_status(content: str, story_id: str, new_status: str):
    pattern = re.compile(r"(story:(?P<story>[A-Za-z0-9_-]+)\s+status:)(?P<status>[A-Za-z0-9_-]+)")
    found = False
    changed = False

    def _replace(match):
        nonlocal found, changed
        if match.group("story").upper() != story_id:
            return match.group(0)
        found = True
        if match.group("status").lower() != new_status:
            changed = True
        return f"{match.group(1)}{new_status}"

    updated = pattern.sub(_replace, content)
    return updated, found, changed


def _update_objective_story_status(content: str, story_id: str, new_status: str):
    updated_content, marker_found, marker_changed = _update_marker_story_status(content, story_id, new_status)
    updated_content, yaml_found, yaml_changed = _update_yaml_story_status(updated_content, story_id, new_status)

    found = marker_found or yaml_found
    changed = marker_changed or yaml_changed
    return updated_content, found, changed


def _collect_objective_story_statuses(content: str) -> dict[str, str]:
    statuses = _extract_yaml_story_statuses(content)
    marker_statuses = _extract_marker_story_statuses(content)
    statuses.update(marker_statuses)
    return statuses


def _collect_objective_dod_items(content: str) -> dict[str, dict[str, str]]:
    pattern = re.compile(
        (
            r"<!--\s*"
            r"dod:\s*(?P<dod>[A-Za-z0-9_-]+)\s+"
            r"status:\s*(?P<status>\w+)\s+"
            r"priority:\s*(?P<priority>\w+)\s*"
            r"-->"
        ),
        re.IGNORECASE,
    )
    items = {}
    for match in pattern.finditer(content):
        dod_id = match.group("dod").upper()
        items[dod_id] = {
            "status": match.group("status").lower(),
            "priority": match.group("priority").lower(),
        }
    return items


def _update_objective_dod_status(content: str, dod_id: str, new_status: str):
    pattern = re.compile(
        (
            r"(?P<head><!--\s*dod:\s*(?P<dod>[A-Za-z0-9_-]+)\s+status:\s*)"
            r"(?P<status>\w+)"
            r"(?P<tail>\s+priority:\s*\w+\s*-->)"
        ),
        re.IGNORECASE,
    )
    found = False
    changed = False

    def _replace(match):
        nonlocal found, changed
        if match.group("dod").upper() != dod_id:
            return match.group(0)
        found = True
        if match.group("status").lower() != new_status:
            changed = True
        return f"{match.group('head')}{new_status}{match.group('tail')}"

    updated = pattern.sub(_replace, content)
    return updated, found, changed


def cmd_agile_init(args):
    if args.steering_every < 1:
        print("Error: --steering-every must be >= 1", file=sys.stderr)
        return 1

    try:
        agi_id = _next_agile_id()
    except RuntimeError as exc:
        print(f"Error: failed to allocate AGI id ({exc})", file=sys.stderr)
        return 1

    session_dir = _agi_session_dir(agi_id)
    if session_dir.exists():
        print(f"Error: {agi_id} already exists", file=sys.stderr)
        return 1

    (session_dir / "objective" / "history").mkdir(parents=True, exist_ok=True)
    (session_dir / "sprints").mkdir(parents=True, exist_ok=True)
    (session_dir / "index").mkdir(parents=True, exist_ok=True)

    objective_content = """# Objective

## Project DoD

- [ ] DOD-001: Define first executable objective item.
<!-- dod:DOD-001 status:todo priority:must -->
"""
    objective_path = _agi_objective_path(agi_id)
    objective_path.write_text(objective_content, encoding="utf-8")
    save_json(_agi_links_path(agi_id), {"agi_id": agi_id, "pln": [], "req": []})
    _agi_objective_changelog_path(agi_id).touch()
    _agi_events_path(agi_id).touch()

    now = _now_iso()
    payload = {
        "id": agi_id,
        "agi_id": agi_id,
        "status": "active",
        "current_sprint": 0,
        "steering_every": args.steering_every,
        "objective": {
            "path": "objective/objective.md",
            "version": 1,
        },
        "queue": [],
        "refs": [],
        "created_at": now,
        "updated_at": now,
    }
    save_json(_agi_session_path(agi_id), payload)
    _append_agile_event(agi_id, "agile.init", {"steering_every": args.steering_every})

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0


def cmd_agile_status(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(session, ensure_ascii=False, indent=2))
        return 0

    objective = session.get("objective", {}) if isinstance(session.get("objective"), dict) else {}
    print(f"id: {session.get('id', agi_id)}")
    print(f"status: {session.get('status', '')}")
    print(f"current_sprint: {session.get('current_sprint', 0)}")
    print(f"steering_every: {session.get('steering_every', 0)}")
    print(f"objective.version: {objective.get('version', 0)}")
    return 0


def cmd_agile_update(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed_fields = {}
    if args.status is not None:
        session["status"] = str(args.status)
        changed_fields["status"] = str(args.status)
    if args.current_sprint is not None:
        if args.current_sprint < 0:
            print("Error: current_sprint must be >= 0", file=sys.stderr)
            return 1
        session["current_sprint"] = int(args.current_sprint)
        changed_fields["current_sprint"] = int(args.current_sprint)
    if args.steering_every is not None:
        if args.steering_every < 1:
            print("Error: --steering-every must be >= 1", file=sys.stderr)
            return 1
        session["steering_every"] = int(args.steering_every)
        changed_fields["steering_every"] = int(args.steering_every)
    if args.objective_version is not None:
        objective_data = session.get("objective")
        if not isinstance(objective_data, dict):
            objective_data = {"path": "objective/objective.md"}
            session["objective"] = objective_data
        objective_data["version"] = int(args.objective_version)
        changed_fields["objective_version"] = int(args.objective_version)

    if not changed_fields:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    saved = _save_agile_session(agi_id, session)
    _append_agile_event(agi_id, "agile.update", {"fields": changed_fields})

    if args.json:
        print(json.dumps(saved, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0


def cmd_agile_result(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    planned = _split_csv_values(args.planned)
    completed = _split_csv_values(args.completed)
    try:
        pln_ids = [_normalize_link_id(value, "PLN") for value in _split_csv_values(args.pln)]
        req_ids = [_normalize_link_id(value, "REQ") for value in _split_csv_values(args.req)]
        sprint_goals = _parse_agile_sprint_goals(args.sprint_goals)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    sprint_id = f"S{args.sprint:02d}"
    timestamp = _now_iso()

    payload = {
        "sprint_id": sprint_id,
        "status": str(args.status),
        "planned": planned,
        "completed": completed,
        "generated": {
            "pln": pln_ids,
            "req": req_ids,
        },
        "sprint_goals": sprint_goals,
        "timestamp": timestamp,
    }
    if args.summary is not None:
        payload["summary"] = str(args.summary)
    if args.outcome is not None:
        payload["outcome"] = str(args.outcome)
    if args.sprint_purpose is not None:
        payload["sprint_purpose"] = str(args.sprint_purpose)
    if args.selection_reason is not None:
        payload["selection_reason"] = str(args.selection_reason)
    if args.target_dod is not None:
        payload["target_dod"] = str(args.target_dod)
    if args.target_dod_text is not None:
        payload["target_dod_text"] = str(args.target_dod_text)
    if args.previous_direction is not None:
        payload["previous_direction"] = str(args.previous_direction)
    if args.previous_lessons is not None:
        payload["previous_lessons"] = str(args.previous_lessons)
    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    save_json(sprint_dir / "result.json", payload)

    result_md_path = sprint_dir / "result.md"
    result_md_lines = [
        f"# {sprint_id} Result",
        "",
    ]
    why_keys = (
        "sprint_purpose",
        "selection_reason",
        "target_dod",
        "target_dod_text",
        "previous_direction",
        "previous_lessons",
    )
    has_why = any(key in payload for key in why_keys)
    if has_why:
        target_dod = payload.get("target_dod") or "-"
        target_dod_text = payload.get("target_dod_text") or "-"
        if target_dod == "-" and target_dod_text == "-":
            target_dod_line = "-"
        elif target_dod_text == "-":
            target_dod_line = target_dod
        elif target_dod == "-":
            target_dod_line = target_dod_text
        else:
            target_dod_line = f"{target_dod} — {target_dod_text}"
        result_md_lines.extend(
            [
                "## 이 스프린트를 왜 했는가",
                f"- 스프린트 목적: {payload.get('sprint_purpose') or '-'}",
                f"- 대상 DoD: {target_dod_line}",
                f"- 선택 근거: {payload.get('selection_reason') or '-'}",
                f"- 직전 회고 방향: {payload.get('previous_direction') or '-'}",
                f"- 직전 교훈: {payload.get('previous_lessons') or '-'}",
                "",
            ]
        )
    result_md_lines.extend(
        [
            f"- status: {payload['status']}",
            f"- planned: {', '.join(planned) if planned else '-'}",
            f"- completed: {', '.join(completed) if completed else '-'}",
            f"- generated PLN: {', '.join(pln_ids) if pln_ids else '-'}",
            f"- generated REQ: {', '.join(req_ids) if req_ids else '-'}",
            f"- summary: {payload.get('summary', '-')}",
            f"- outcome: {payload.get('outcome', '-')}",
            f"- timestamp: {timestamp}",
            "",
        ]
    )
    result_md_lines.extend(_render_sprint_goals_md_lines(sprint_goals))
    result_md_path.write_text("\n".join(result_md_lines), encoding="utf-8")
    _append_agile_event(
        agi_id,
        "agile.result",
        {
            "sprint_id": sprint_id,
            "status": payload["status"],
        },
    )

    # Auto-update index/links.json when PLN/REQ IDs are provided
    if pln_ids or req_ids:
        links_path = _agi_links_path(agi_id)
        links = load_json(links_path) or {}
        if not isinstance(links, dict):
            links = {}
        links["agi_id"] = agi_id
        links.setdefault("pln", [])
        links.setdefault("req", [])
        for plan_id in pln_ids:
            if plan_id not in links["pln"]:
                links["pln"].append(plan_id)
        for req_id in req_ids:
            if req_id not in links["req"]:
                links["req"].append(req_id)
        links["updated_at"] = _now_iso()
        save_json(links_path, links)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(sprint_dir / "result.json"))
    return 0


def cmd_agile_retrospective(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1
    if args.velocity_planned < 0:
        print("Error: --velocity-planned must be >= 0", file=sys.stderr)
        return 1
    if args.velocity_completed < 0:
        print("Error: --velocity-completed must be >= 0", file=sys.stderr)
        return 1

    succeeded = _split_csv_values(args.succeeded)
    if not succeeded:
        print("Error: --succeeded is required", file=sys.stderr)
        return 1

    try:
        failed = _parse_agile_failed_items(args.failed)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sprint_id = f"S{args.sprint:02d}"
    velocity_rate = 0 if args.velocity_planned == 0 else round(
        args.velocity_completed / args.velocity_planned,
        4,
    )
    payload = {
        "sprint_id": sprint_id,
        "status": str(args.status),
        "succeeded": succeeded,
        "failed": failed,
        "velocity": {
            "planned": int(args.velocity_planned),
            "completed": int(args.velocity_completed),
            "rate": velocity_rate,
        },
        "known_limitations": str(args.limitations),
        "lessons_learned": str(args.lessons),
        "direction": str(args.direction),
        "timestamp": _now_iso(),
    }

    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    retrospective_path = sprint_dir / "retrospective.json"
    save_json(retrospective_path, payload)
    known_issues = [
        issue
        for issue in _load_agile_known_issues(agi_id)
        if str(issue.get("status", "")).strip().lower() == "open"
    ]

    succeeded_lines = "\n".join(f"- {item}" for item in succeeded) if succeeded else "- 없음"
    failed_lines = (
        "\n".join(
            (
                f"- 시도한 접근: {entry.get('tried_approach', '-')}"
                f" | 실패 원인: {entry.get('failure_reason', '-')}"
            )
            for entry in failed
        )
        if failed
        else "- 없음"
    )
    known_issue_lines = (
        "\n".join(
            (
                f"- {str(issue.get('id', '-')).upper()} "
                f"[{str(issue.get('severity', '-')).upper()}] "
                f"{str(issue.get('description', '-')).strip()} "
                f"(sprint: {str(issue.get('sprint_id', '-')).strip()}, status: {str(issue.get('status', '-')).strip()})"
            )
            for issue in known_issues
        )
        if known_issues
        else "- 없음"
    )
    template_path = _plugin_root() / "templates" / "retrospective.md"
    try:
        template_content = template_path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"Error: retrospective template not found: {template_path} ({e})", file=sys.stderr)
        return 1
    replacements = {
        "SPRINT_ID": sprint_id,
        "STATUS": str(payload["status"]),
        "TIMESTAMP": str(payload["timestamp"]),
        "SUCCEEDED_ITEMS": succeeded_lines,
        "FAILED_ITEMS": failed_lines,
        "VELOCITY_PLANNED": str(payload["velocity"]["planned"]),
        "VELOCITY_COMPLETED": str(payload["velocity"]["completed"]),
        "VELOCITY_RATE": str(payload["velocity"]["rate"]),
        "KNOWN_LIMITATIONS": str(payload["known_limitations"]),
        "LESSONS_LEARNED": str(payload["lessons_learned"]),
        "DIRECTION": str(payload["direction"]),
        "KNOWN_ISSUES": known_issue_lines,
    }
    retrospective_md_content = template_content
    for key, value in replacements.items():
        retrospective_md_content = retrospective_md_content.replace(f"{{{{{key}}}}}", value)
    (sprint_dir / "retrospective.md").write_text(retrospective_md_content, encoding="utf-8")

    _append_agile_event(
        agi_id,
        "agile.retrospective",
        {
            "sprint_id": sprint_id,
            "status": payload["status"],
        },
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(retrospective_path))
    return 0


def cmd_agile_known_issues_add(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    description = str(args.description).strip()
    if not description:
        print("Error: --description is required", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    issue = {
        "id": _next_known_issue_id(issues),
        "description": description,
        "severity": str(args.severity).strip().upper(),
        "sprint_id": f"S{args.sprint:02d}",
        "status": "open",
        "created_at": _now_iso(),
    }
    issues.append(issue)
    save_json(_agi_known_issues_path(agi_id), issues)
    _append_agile_event(
        agi_id,
        "agile.known-issues.add",
        {
            "issue_id": issue["id"],
            "severity": issue["severity"],
            "status": issue["status"],
        },
    )

    if args.json:
        print(json.dumps(issue, ensure_ascii=False, indent=2))
    else:
        print(issue["id"])
    return 0


def cmd_agile_known_issues_resolve(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
        issue_id = _normalize_known_issue_id(args.issue_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    target_issue = None
    changed = False
    for issue in issues:
        normalized_id = str(issue.get("id", "")).strip().upper()
        if normalized_id != issue_id:
            continue
        target_issue = issue
        if str(issue.get("status", "")).strip().lower() != "resolved":
            issue["status"] = "resolved"
            issue["resolved_at"] = _now_iso()
            changed = True
        elif "resolved_at" not in issue:
            issue["resolved_at"] = _now_iso()
            changed = True
        break

    if target_issue is None:
        print(f"Error: known issue not found ({issue_id})", file=sys.stderr)
        return 1

    if changed:
        save_json(_agi_known_issues_path(agi_id), issues)

    _append_agile_event(
        agi_id,
        "agile.known-issues.resolve",
        {
            "issue_id": issue_id,
            "status": "resolved",
        },
    )

    if args.json:
        print(json.dumps(target_issue, ensure_ascii=False, indent=2))
    else:
        print(issue_id)
    return 0


def cmd_agile_known_issues_list(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    issues = _load_agile_known_issues(agi_id)
    if args.status:
        status_filter = str(args.status).strip().lower()
        issues = [
            issue
            for issue in issues
            if str(issue.get("status", "")).strip().lower() == status_filter
        ]

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return 0

    for issue in issues:
        print(
            (
                f"{str(issue.get('id', '')).strip().upper()}\t"
                f"{str(issue.get('status', '')).strip().lower()}\t"
                f"{str(issue.get('severity', '')).strip().upper()}\t"
                f"{str(issue.get('sprint_id', '')).strip()}\t"
                f"{str(issue.get('description', '')).strip()}"
            )
        )
    return 0


def cmd_agile_known_issues(args):
    subcommand = getattr(args, "known_issues_subcommand", None)
    dispatch = {
        "add": cmd_agile_known_issues_add,
        "resolve": cmd_agile_known_issues_resolve,
        "list": cmd_agile_known_issues_list,
    }
    fn = dispatch.get(subcommand)
    if fn is None:
        print("Error: known-issues subcommand is required (add|resolve|list)", file=sys.stderr)
        return 1
    return fn(args)


def cmd_agile_objective_transition(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        dod_id = _normalize_dod_id(args.story)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    current_content = objective_path.read_text(encoding="utf-8")
    before_items = _collect_objective_dod_items(current_content)
    updated_content, found, changed = _update_objective_dod_status(
        current_content,
        dod_id,
        str(args.status).strip().lower(),
    )
    if not found:
        print(f"Error: DoD item not found ({dod_id})", file=sys.stderr)
        return 1

    if changed:
        objective_path.write_text(updated_content, encoding="utf-8")

    after_items = _collect_objective_dod_items(updated_content)
    from_status = before_items.get(dod_id, {}).get("status")
    to_status = after_items.get(dod_id, {}).get("status")
    priority = after_items.get(dod_id, {}).get("priority")
    _append_ndjson(
        _agi_objective_changelog_path(agi_id),
        {
            "timestamp": _now_iso(),
            "event": "objective-transition",
            "dod": dod_id,
            "from_status": from_status,
            "to_status": to_status,
            "priority": priority,
            "changed": changed,
        },
    )
    _append_agile_event(
        agi_id,
        "agile.objective-transition",
        {
            "dod": dod_id,
            "from_status": from_status,
            "to_status": to_status,
            "priority": priority,
            "changed": changed,
        },
    )

    output = {
        "agi_id": agi_id,
        "story": dod_id,
        "dod": dod_id,
        "status": to_status,
        "priority": priority,
        "changed": changed,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0


def cmd_agile_objective_check(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    content = objective_path.read_text(encoding="utf-8")
    dod_items = _collect_objective_dod_items(content)
    if not dod_items:
        output = {
            "agi_id": agi_id,
            "all_done": False,
            "incomplete": [],
            "dods": {},
            "warning": "no DoD items found",
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(output, ensure_ascii=False))
        return 1

    incomplete = sorted([
        dod_id for dod_id, item in dod_items.items()
        if item.get("status", "").lower() not in {"done", "completed"}
    ])
    status_only = {dod_id: item.get("status") for dod_id, item in dod_items.items()}
    output = {
        "agi_id": agi_id,
        "all_done": len(incomplete) == 0,
        "incomplete": incomplete,
        "dods": dod_items,
        "stories": status_only,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0 if not incomplete else 1


def cmd_agile_objective_snapshot(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective file missing ({objective_path})", file=sys.stderr)
        return 1

    history_dir = objective_path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    highest_version = 0
    for candidate in history_dir.glob("v*.md"):
        match = re.fullmatch(r"v(\d+)\.md", candidate.name)
        if not match:
            continue
        highest_version = max(highest_version, int(match.group(1)))

    snapshot_version = highest_version + 1
    snapshot_path = history_dir / f"v{snapshot_version}.md"
    shutil.copyfile(objective_path, snapshot_path)

    _append_ndjson(
        _agi_objective_changelog_path(agi_id),
        {
            "timestamp": _now_iso(),
            "version": snapshot_version,
            "reason": str(args.reason),
        },
    )

    objective_data = session.get("objective")
    if not isinstance(objective_data, dict):
        objective_data = {"path": "objective/objective.md", "version": 0}
        session["objective"] = objective_data

    try:
        current_objective_version = int(objective_data.get("version", 0))
    except (TypeError, ValueError):
        current_objective_version = 0
    objective_data["version"] = current_objective_version + 1

    saved_session = _save_agile_session(agi_id, session)
    _append_agile_event(
        agi_id,
        "agile.objective-snapshot",
        {
            "version": snapshot_version,
            "reason": str(args.reason),
            "objective_version": objective_data["version"],
        },
    )

    output = {
        "agi_id": agi_id,
        "version": snapshot_version,
        "reason": str(args.reason),
        "snapshot": str(snapshot_path),
        "objective_version": objective_data["version"],
        "updated_at": saved_session.get("updated_at"),
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0


def cmd_agile_link(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        pln_ids = [_normalize_link_id(value, "PLN") for value in _split_csv_values(args.pln)]
        req_ids = [_normalize_link_id(value, "REQ") for value in _split_csv_values(args.req)]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not pln_ids and not req_ids:
        print("Error: provide at least one --pln or --req", file=sys.stderr)
        return 1

    links_path = _agi_links_path(agi_id)
    links = load_json(links_path) or {}
    if not isinstance(links, dict):
        links = {}
    links["agi_id"] = agi_id
    links.setdefault("pln", [])
    links.setdefault("req", [])

    for plan_id in pln_ids:
        if plan_id not in links["pln"]:
            links["pln"].append(plan_id)
    for req_id in req_ids:
        if req_id not in links["req"]:
            links["req"].append(req_id)

    links["updated_at"] = _now_iso()
    save_json(links_path, links)
    _append_agile_event(
        agi_id,
        "agile.link",
        {
            "pln": pln_ids,
            "req": req_ids,
        },
    )

    if args.json:
        print(json.dumps(links, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0


def cmd_intent_add(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    try:
        intent_id = _next_intent_id()
        motivation = args.motivation if args.motivation is not None else args.goal
        created = store.add(
            intent_id,
            feature=args.feature,
            situation=args.situation,
            motivation=motivation,
            goal=args.goal,
            linked_req=args.req,
            linked_plan=args.plan,
            related_intent=args.related_intent,
            tags=args.tag,
            files=args.file,
        )
    except RuntimeError as exc:
        print(f"Error: failed to allocate intent id ({exc})", file=sys.stderr)
        return 1
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(created, ensure_ascii=False, indent=2))
    else:
        print(created["id"])
    return 0


def cmd_intent_get(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        data = store.get(args.intent_id)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if data is None:
        print(f"Error: {args.intent_id} not found.", file=sys.stderr)
        return 1

    if args.json:
        output = {k: v for k, v in data.items() if k != "raw"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        meta = data.get("metadata", {})
        body = data.get("body", data.get("raw", ""))
        lines = ["---"]
        for key in ("id", "feature", "linked_req", "linked_plan", "related_intent", "tags", "files", "created_at"):
            val = meta.get(key)
            if isinstance(val, list):
                lines.append(f'{key}: {json.dumps(val, ensure_ascii=False)}')
            else:
                lines.append(f'{key}: {json.dumps(val, ensure_ascii=False)}')
        lines.append("---")
        lines.append(body)
        print("\n".join(lines))
    return 0


def cmd_intent_list(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        entries = store.list()
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.req:
        entries = [entry for entry in entries if entry.get("linked_req") == args.req]
    if args.plan:
        entries = [entry for entry in entries if entry.get("linked_plan") == args.plan]

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print("No intents found.")
        return 0

    print(f"{'ID':<12} {'Created':<12} {'Feature'}")
    print("-" * 80)
    for entry in entries:
        print(
            f"{entry.get('id', ''):<12} {entry.get('created_at', ''):<12} "
            f"{entry.get('feature', '')}"
        )
    return 0


def cmd_intent_update(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    update_fields = {}
    for key in ("feature", "situation", "motivation", "goal", "created_at"):
        value = getattr(args, key, None)
        if value is not None:
            update_fields[key] = value
    if args.req is not None:
        update_fields["linked_req"] = args.req
    if args.plan is not None:
        update_fields["linked_plan"] = args.plan
    if args.related_intent is not None:
        update_fields["related_intent"] = args.related_intent
    if args.tag is not None:
        update_fields["tags"] = args.tag
    if args.file is not None:
        update_fields["files"] = args.file

    if not update_fields:
        print("Error: no fields to update", file=sys.stderr)
        return 1

    try:
        updated = store.update(args.intent_id, **update_fields)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(updated, ensure_ascii=False, indent=2))
    else:
        print(updated["id"])
    return 0


def cmd_intent_delete(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1

    try:
        deleted = store.delete(args.intent_id)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Deleted {deleted['id']}")
    return 0


def cmd_intent_search(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        matches = store.search(args.keyword)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    for match in matches:
        print(f"{match.get('id')}:{match.get('line')}:{match.get('text')}")
    return 0


def cmd_intent_lookup(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        entries = store.lookup(args.files)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    for entry in entries:
        files = ", ".join(entry.get("files", []))
        print(f"{entry.get('id')}: {files}")
    return 0


def cmd_intent_related(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        related = store.related(args.intent_id, depth=args.depth)
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(related, ensure_ascii=False, indent=2))
        return 0

    print(f"Source: {related.get('source')} (depth={related.get('depth')})")
    for item in related.get("related", []):
        reasons = ", ".join(item.get("reasons", []))
        print(f"{item.get('id')} [depth={item.get('depth')}] {reasons}")
    return 0


def cmd_intent_rebuild(args):
    store, store_error = _create_intent_store()
    if store is None:
        return 1
    try:
        index = store.rebuild()
    except store_error as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    entry_count = len(index.get("entries", []))
    print(f"Rebuilt .gran-maestro/intent/intent.db ({entry_count} entries)")
    return 0


def cmd_session_split_prompts(args):
    if not args.prompts_dir:
        print("Error: directory not found", file=sys.stderr)
        return 1

    prompts_dir = Path(args.prompts_dir)
    if not prompts_dir.exists():
        print("Error: directory not found", file=sys.stderr)
        return 1

    combined_path = prompts_dir / "combined-prompts.txt"
    if not combined_path.exists():
        print("Error: combined-prompts.txt not found", file=sys.stderr)
        return 1

    content = combined_path.read_text(encoding="utf-8")
    marker_re = re.compile(r"^===SPLIT: (.+)===$")
    generated = []
    target_name = None
    target_lines = []

    for raw_line in content.splitlines(keepends=True):
        m = marker_re.match(raw_line.strip())
        if m:
            if target_name is not None:
                out_path = prompts_dir / target_name
                out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
                generated.append(str(out_path))
                print(str(out_path))
            target_name = m.group(1)
            target_lines = []
            continue

        if target_name is not None:
            target_lines.append(raw_line)

    if target_name is not None:
        out_path = prompts_dir / target_name
        out_path.write_text("".join(target_lines).strip("\n\r"), encoding="utf-8")
        generated.append(str(out_path))
        print(str(out_path))

    return 0


# ---------------------------------------------------------------------------
# counter subcommands
# ---------------------------------------------------------------------------

TYPE_DIRS = {
    "req": ("requests", "REQ"),
    "idn": ("ideation", "IDN"),
    "dsc": ("discussion", "DSC"),
    "dbg": ("debug", "DBG"),
    "exp": ("explore",   "EXP"),
    "pln": ("plans",     "PLN"),
    "des": ("designs",   "DES"),
    "cap": ("captures", "CAP"),
    "fc": ("fact-checks", "FC"),
    "ref": ("references", "REF"),
    "intent": ("intent", "INTENT"),
    "agi": ("agile", "AGI"),
}
JSON_FILE_MAP = {
    "req": "request.json",
    "pln": "plan.json",
    "des": "design.json",
    "cap": "capture.json",
    "fc": "fact-check.json",
    "ref": "reference.json",
}


def type_archived_dir(type_key: str) -> Path:
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "archived"


def get_counter_path(type_key: str, dir_override: str = None) -> Path:
    if dir_override:
        return Path(dir_override) / "counter.json"
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    return BASE_DIR / subdir / "counter.json"


def cmd_counter_next(args):
    counter_path = get_counter_path(args.type, args.dir)
    subdir, prefix = TYPE_DIRS.get(args.type, ("requests", "REQ"))
    scan_root = Path(args.dir) if args.dir else BASE_DIR / subdir
    disk_max = 0
    for path in scan_root.glob(f"{prefix}-*"):
        if args.type != "intent" and not path.is_dir():
            continue
        if args.type == "intent" and not (path.is_dir() or path.is_file()):
            continue
        try:
            n = int(path.name.split("-")[1])
        except (IndexError, ValueError):
            continue
        if n > disk_max:
            disk_max = n

    scan_root.mkdir(parents=True, exist_ok=True)
    data = load_json(counter_path) or {}
    last_id = max(data.get("last_id", 0), disk_max)
    next_id = last_id + 1
    save_json(counter_path, {"last_id": next_id})
    print(f"{prefix}-{next_id:03d}")
    return 0


def cmd_counter_peek(args):
    counter_path = get_counter_path(args.type, args.dir)
    data = load_json(counter_path) or {"last_id": 0}
    _, prefix = TYPE_DIRS.get(args.type, ("requests", "REQ"))
    last_id = data.get("last_id", 0)
    print(f"{prefix}-{last_id + 1:03d} (next, current last_id={last_id})")
    return 0


def _parse_utc_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        normalized = value
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


GARDENING_INACTIVE_STATUSES = {"done", "completed", "cancelled"}
GARDENING_STALE_DAYS = 90


def _gardening_add_warning(warnings, message, section_warnings=None):
    if section_warnings is not None and message not in section_warnings:
        section_warnings.append(message)
    if message not in warnings:
        warnings.append(message)


def _gardening_elapsed_days(created_at, now):
    created_dt = _parse_utc_datetime(created_at)
    if created_dt is None:
        return None
    elapsed = now - created_dt
    if elapsed < timedelta(0):
        return None
    return elapsed.days


def _gardening_linked_request_status(req_id, request_status_map, warnings, section_warnings):
    req_id = str(req_id)
    cached_status = request_status_map.get(req_id)
    if cached_status is not None:
        return cached_status

    req_path = requests_dir() / req_id / "request.json"
    if not req_path.exists():
        request_status_map[req_id] = "done"
        return "done"

    req_data = load_json(req_path)
    if not isinstance(req_data, dict):
        _gardening_add_warning(
            warnings,
            f"[경고] {req_path} 파싱 실패 (스킵)",
            section_warnings,
        )
        return None

    status = req_data.get("status", "")
    request_status_map[req_id] = status
    return status


def _gardening_display_date(value):
    dt = _parse_utc_datetime(value)
    if dt is None:
        return str(value or "-")
    return dt.date().isoformat()


def cmd_gardening_scan(args):
    now = datetime.now(timezone.utc)
    warnings = []
    plan_warnings = []
    request_warnings = []
    intent_warnings = []

    stale_plans = []
    stale_requests = []
    stale_intents = []

    plan_section_message = None
    request_section_message = None
    intent_section_message = None

    request_status_map = {}

    req_root = requests_dir()
    if not req_root.exists():
        request_section_message = "requests 디렉토리가 없습니다 (스킵)"
        _gardening_add_warning(warnings, request_section_message)
    else:
        for req_dir in sorted(req_root.glob("REQ-*")):
            if not req_dir.is_dir():
                continue
            req_json_path = req_dir / "request.json"
            if req_json_path.exists() and load_json(req_json_path) is None:
                _gardening_add_warning(
                    warnings,
                    f"[경고] {req_json_path} 파싱 실패 (스킵)",
                    request_warnings,
                )

        for req_id, req_path, req_data in iter_request_dirs(include_completed=False):
            status = req_data.get("status", "")
            request_status_map[req_id] = status
            if status in GARDENING_INACTIVE_STATUSES:
                continue

            elapsed_days = _gardening_elapsed_days(req_data.get("created_at"), now)
            if elapsed_days is None or elapsed_days < GARDENING_STALE_DAYS:
                continue

            stale_requests.append(
                {
                    "id": req_id,
                    "title": req_data.get("title", ""),
                    "status": status,
                    "created_at": req_data.get("created_at"),
                    "elapsed_days": elapsed_days,
                }
            )

    pln_root = plans_dir()
    if not pln_root.exists():
        plan_section_message = "plans 디렉토리가 없습니다 (스킵)"
        _gardening_add_warning(warnings, plan_section_message)
    else:
        for pln_dir in sorted(pln_root.glob("PLN-*")):
            if not pln_dir.is_dir():
                continue
            plan_json_path = pln_dir / "plan.json"
            if plan_json_path.exists() and load_json(plan_json_path) is None:
                _gardening_add_warning(
                    warnings,
                    f"[경고] {plan_json_path} 파싱 실패 (스킵)",
                    plan_warnings,
                )

        for plan_id, plan_path, plan_data in (iter_plan_dirs() or []):
            if plan_data.get("status") != "active":
                continue

            elapsed_days = _gardening_elapsed_days(plan_data.get("created_at"), now)
            if elapsed_days is None or elapsed_days < GARDENING_STALE_DAYS:
                continue

            linked_requests = plan_data.get("linked_requests")
            if not isinstance(linked_requests, list):
                linked_requests = []

            linked_statuses = []
            all_linked_inactive = True
            for linked_req in linked_requests:
                linked_req_id = str(linked_req)
                linked_status = _gardening_linked_request_status(
                    linked_req_id,
                    request_status_map,
                    warnings,
                    plan_warnings,
                )
                if linked_status is None:
                    all_linked_inactive = False
                    linked_statuses.append((linked_req_id, "unknown"))
                    continue
                linked_statuses.append((linked_req_id, linked_status))
                if linked_status not in GARDENING_INACTIVE_STATUSES:
                    all_linked_inactive = False

            if linked_requests and not all_linked_inactive:
                continue

            stale_plans.append(
                {
                    "id": plan_id,
                    "title": plan_data.get("title", ""),
                    "created_at": plan_data.get("created_at"),
                    "elapsed_days": elapsed_days,
                    "linked_requests": [str(req_id) for req_id in linked_requests],
                    "_linked_statuses": linked_statuses,
                }
            )

    store, store_error = _create_intent_store()
    if store is None:
        intent_section_message = "intent 조회 실패 (스킵)"
        _gardening_add_warning(warnings, intent_section_message)
    else:
        try:
            intent_entries = store.list()
        except store_error:
            intent_section_message = "intent 조회 실패 (스킵)"
            _gardening_add_warning(warnings, intent_section_message)
            intent_entries = []
        except Exception:
            intent_section_message = "intent 조회 실패 (스킵)"
            _gardening_add_warning(warnings, intent_section_message)
            intent_entries = []

        for entry in intent_entries:
            if entry.get("status", "active") != "active":
                continue

            elapsed_days = _gardening_elapsed_days(entry.get("created_at"), now)
            if elapsed_days is None or elapsed_days < GARDENING_STALE_DAYS:
                continue

            linked_req = entry.get("linked_req")
            linked_req_status = None
            is_stale = False
            if linked_req in (None, ""):
                is_stale = True
            else:
                linked_req_status = _gardening_linked_request_status(
                    str(linked_req),
                    request_status_map,
                    warnings,
                    intent_warnings,
                )
                if linked_req_status in GARDENING_INACTIVE_STATUSES:
                    is_stale = True

            if not is_stale:
                continue

            stale_intents.append(
                {
                    "id": entry.get("id", ""),
                    "feature": entry.get("feature", ""),
                    "created_at": entry.get("created_at"),
                    "elapsed_days": elapsed_days,
                    "linked_req": linked_req,
                    "_linked_req_status": linked_req_status,
                }
            )

    summary = {
        "plans": len(stale_plans),
        "requests": len(stale_requests),
        "intents": len(stale_intents),
        "total": len(stale_plans) + len(stale_requests) + len(stale_intents),
    }

    if args.json:
        stale_plans_json = []
        for plan in stale_plans:
            stale_plans_json.append(
                {
                    "id": plan.get("id", ""),
                    "title": plan.get("title", ""),
                    "created_at": plan.get("created_at"),
                    "elapsed_days": plan.get("elapsed_days", 0),
                    "linked_requests": plan.get("linked_requests", []),
                }
            )
        stale_intents_json = []
        for intent in stale_intents:
            stale_intents_json.append(
                {
                    "id": intent.get("id", ""),
                    "feature": intent.get("feature", ""),
                    "created_at": intent.get("created_at"),
                    "elapsed_days": intent.get("elapsed_days", 0),
                    "linked_req": intent.get("linked_req"),
                }
            )

        payload = {
            "stale_plans": stale_plans_json,
            "stale_requests": stale_requests,
            "stale_intents": stale_intents_json,
            "warnings": warnings,
            "summary": summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("Gran Maestro -- Gardening Report")
    print("=======================================")
    print("")

    if plan_section_message:
        print(f"[Plans] {plan_section_message}")
    elif stale_plans:
        print(f"[Plans] {len(stale_plans)}개 stale 항목")
        for plan in stale_plans:
            print(
                f"  {plan.get('id', '')}: {plan.get('title', '')} "
                f"(생성: {_gardening_display_date(plan.get('created_at'))}, "
                f"{plan.get('elapsed_days', 0)}일 경과)"
            )
            linked_statuses = plan.get("_linked_statuses", [])
            if not linked_statuses:
                print("    linked_requests: [] (없음)")
            else:
                linked_summary = ", ".join(
                    f"{req_id}({status})" for req_id, status in linked_statuses
                )
                print(f"    linked_requests: [{linked_summary}]")
    else:
        print("[Plans] stale 항목 없음")
    for warning in plan_warnings:
        print(warning)
    print("")

    if request_section_message:
        print(f"[Requests] {request_section_message}")
    elif stale_requests:
        print(f"[Requests] {len(stale_requests)}개 stale 항목")
        for req in stale_requests:
            print(
                f"  {req.get('id', '')}: {req.get('title', '')} "
                f"(상태: {req.get('status', '')}, "
                f"생성: {_gardening_display_date(req.get('created_at'))}, "
                f"{req.get('elapsed_days', 0)}일 경과)"
            )
    else:
        print("[Requests] stale 항목 없음")
    for warning in request_warnings:
        print(warning)
    print("")

    if intent_section_message:
        print(f"[Intents] {intent_section_message}")
    elif stale_intents:
        print(f"[Intents] {len(stale_intents)}개 stale 항목")
        for intent in stale_intents:
            print(
                f"  {intent.get('id', '')}: {intent.get('feature', '')} "
                f"(생성: {_gardening_display_date(intent.get('created_at'))}, "
                f"{intent.get('elapsed_days', 0)}일 경과)"
            )
            linked_req = intent.get("linked_req")
            if linked_req in (None, ""):
                print("    linked_req: 없음")
            else:
                linked_status = intent.get("_linked_req_status")
                if linked_status:
                    print(f"    linked_req: {linked_req}({linked_status})")
                else:
                    print(f"    linked_req: {linked_req}")
    else:
        print("[Intents] stale 항목 없음")
    for warning in intent_warnings:
        print(warning)
    print("")

    print("=======================================")
    if summary["total"] > 0:
        print(f"총 {summary['total']}개 stale 항목 발견")
        print("")
        print("정리가 필요합니다:")
        print("  Plans/Requests -> /mst:archive --run 또는 /mst:cleanup --run")
        print("  Intents -> /mst:intent delete INTENT-NNN")
    else:
        print("stale 항목이 없습니다. 프로젝트가 건강합니다.")

    return 0


def _capture_is_plan_active(plan_id):
    if not plan_id:
        return False
    plan_data = load_json(plans_dir() / str(plan_id) / "plan.json")
    if not isinstance(plan_data, dict):
        return False
    return plan_data.get("status") in ("active", "in_progress")


def _capture_linked_requests_done(plan_id):
    if not plan_id:
        return False
    plan_data = load_json(plans_dir() / str(plan_id) / "plan.json")
    if not isinstance(plan_data, dict):
        return False
    linked_requests = plan_data.get("linked_requests")
    if not isinstance(linked_requests, list) or not linked_requests:
        return False

    for req_id in linked_requests:
        request_paths = [
            requests_dir() / req_id / "request.json",
            requests_dir() / "completed" / req_id / "request.json",
        ]
        req_path = next((p for p in request_paths if p.exists()), None)
        if req_path is None:
            return False
        req_data = load_json(req_path) or {}
        if req_data.get("status") not in ("completed", "cancelled"):
            return False
    return True


def _capture_expired(meta, now):
    created_at = _parse_utc_datetime(meta.get("created_at", "")) if isinstance(meta, dict) else None
    if created_at is None:
        return False
    ttl_expires_at = _parse_utc_datetime(meta.get("ttl_expires_at", ""))
    expires_at = ttl_expires_at or (created_at + timedelta(days=7))
    return now >= expires_at


def cmd_capture_ttl_check(args):
    captures_dir = BASE_DIR / "captures"
    if not captures_dir.exists():
        print("No captures directory.")
        return 0

    now = datetime.now(timezone.utc)
    warn_threshold = timedelta(hours=24)
    expired = []

    for cap_dir in sorted(captures_dir.glob("CAP-*")):
        if not cap_dir.is_dir():
            continue
        cap_path = cap_dir / "capture.json"
        meta = load_json(cap_path) or {}

        changed = False
        created_at = _parse_utc_datetime(meta.get("created_at", ""))
        if created_at is None:
            continue

        ttl_warned_at = _parse_utc_datetime(meta.get("ttl_warned_at", ""))
        if ttl_warned_at is None and now - created_at >= warn_threshold:
            meta["ttl_warned_at"] = now.isoformat()
            changed = True

        if _capture_expired(meta, now):
            linked_plan = (meta.get("linked_plan") or "").upper()
            if not _capture_is_plan_active(linked_plan):
                expired.append(cap_dir.name)

        if _capture_linked_requests_done(meta.get("linked_plan")):
            if meta.get("status") not in ("done", "cancelled"):
                meta["status"] = "done"
                changed = True

        if changed:
            save_json(cap_path, meta)

    if expired:
        print("Expired captures:")
        for name in expired:
            print(name)
    else:
        print("No expired captures.")
    return 0


def _parse_capture_ids(raw_caps):
    cap_ids = []
    skipped = []
    seen = set()
    for token in str(raw_caps or "").split(","):
        raw_token = token.strip()
        if not raw_token:
            continue
        cap_id = raw_token.upper()
        if cap_id in seen:
            continue
        seen.add(cap_id)
        if not re.fullmatch(r"^CAP-\d+$", cap_id):
            skipped.append(raw_token)
            print(f"[WARN] invalid CAP ID format skipped: {raw_token}", file=sys.stderr)
            continue
        cap_ids.append(cap_id)
    return cap_ids, skipped


def _capture_status_enum():
    schema_path = Path(__file__).resolve().parent.parent / "templates" / "defaults" / "capture-schema.json"
    schema = load_json(schema_path)
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    status_def = properties.get("status")
    if not isinstance(status_def, dict):
        return None
    enum = status_def.get("enum")
    if not isinstance(enum, list):
        return None
    statuses = {status for status in enum if isinstance(status, str)}
    return statuses or None


def cmd_capture_mark_consumed(args):
    cap_ids, parse_skipped = _parse_capture_ids(args.caps)
    if not cap_ids and not parse_skipped:
        print("Error: --caps requires at least one CAP ID", file=sys.stderr)
        return 1

    plan_id = str(args.plan or "").strip().upper()
    if not plan_id:
        print("Error: --plan is required", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    captures_dir = BASE_DIR / "captures"
    schema_statuses = _capture_status_enum()
    updated = []
    skipped = list(parse_skipped)

    if schema_statuses is None:
        print("[WARN] capture status enum unavailable from schema; validation skipped", file=sys.stderr)

    for cap_id in cap_ids:
        cap_path = captures_dir / cap_id / "capture.json"
        capture = load_json(cap_path)
        if not isinstance(capture, dict):
            skipped.append(cap_id)
            print(f"[WARN] capture not found: {cap_id}", file=sys.stderr)
            continue

        current_status = capture.get("status")
        if current_status == "consumed":
            skipped.append(cap_id)
            print(f"[WARN] capture already consumed: {cap_id}", file=sys.stderr)
            continue
        if schema_statuses is not None and current_status not in schema_statuses:
            print(
                f"[WARN] capture has invalid status: {cap_id} ({current_status!r})",
                file=sys.stderr,
            )

        capture["status"] = "consumed"
        capture["consumed_at"] = now
        capture["linked_plan"] = plan_id
        try:
            save_json(cap_path, capture)
        except Exception as exc:
            skipped.append(cap_id)
            print(f"[WARN] failed to save capture: {cap_id} ({exc})", file=sys.stderr)
            continue
        updated.append(cap_id)

    if args.json:
        print(json.dumps({"updated": updated, "skipped": skipped, "plan": plan_id}, ensure_ascii=False))
        return 0

    if updated:
        print("Updated captures:")
        for cap_id in updated:
            print(cap_id)
    if skipped:
        print("Skipped captures:")
        for cap_id in skipped:
            print(cap_id)
    return 0


# ---------------------------------------------------------------------------
# version subcommands
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    cwd = Path.cwd().resolve()
    worktrees_root = BASE_DIR / "worktrees"

    candidate = cwd
    while (
        candidate != BASE_DIR
        and candidate != worktrees_root
        and candidate.parent != worktrees_root
        and candidate.parent != candidate
    ):
        candidate = candidate.parent

    if candidate.parent == worktrees_root:
        return candidate

    return BASE_DIR.parent


def _read_versions() -> dict:
    """5파일에서 버전 읽기."""
    root = _project_root()
    pkg = load_json(root / "package.json") or {}
    plugin = load_json(root / ".claude-plugin" / "plugin.json") or {}
    market = load_json(root / ".claude-plugin" / "marketplace.json") or {}
    ext_manifest = load_json(root / "extension" / "manifest.json") or {}
    ext_package = load_json(root / "extension" / "package.json") or {}
    return {
        "package":     pkg.get("version", ""),
        "plugin":      plugin.get("version", ""),
        "marketplace": (market.get("plugins") or [{}])[0].get("version", ""),
        "ext_manifest": ext_manifest.get("version", ""),
        "ext_package":  ext_package.get("version", ""),
    }


def cmd_version_get(args):
    versions = _read_versions()
    print(versions["package"])
    return 0


def cmd_version_check(args):
    versions = _read_versions()
    pkg = versions["package"]
    plugin = versions["plugin"]
    market = versions["marketplace"]
    ext_manifest = versions["ext_manifest"]
    ext_package = versions["ext_package"]
    if (
        pkg == plugin == market == ext_manifest == ext_package
        and pkg != ""
    ):
        print(f"✓ {pkg} (동기화됨)")
        return 0
    else:
        print(f"✗ 버전 불일치:")
        print(f"  package.json:              {pkg}")
        print(f"  plugin.json:               {plugin}")
        print(f"  marketplace.json:          {market}")
        print(f"  extension/manifest.json:   {ext_manifest}")
        print(f"  extension/package.json:    {ext_package}")
        return 1


def cmd_version_bump(args):
    versions = _read_versions()
    current = versions["package"]
    if not (
        current == versions["plugin"] == versions["marketplace"] == versions["ext_manifest"] == versions["ext_package"]
    ):
        print("Error: version mismatch")
        print(f"  package.json:              {versions['package']}")
        print(f"  plugin.json:               {versions['plugin']}")
        print(f"  marketplace.json:          {versions['marketplace']}")
        print(f"  extension/manifest.json:   {versions['ext_manifest']}")
        print(f"  extension/package.json:    {versions['ext_package']}")
        return 1

    parts = current.split(".")
    if len(parts) != 3:
        print(f"Error: cannot parse version '{current}'", file=sys.stderr)
        return 1
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        print(f"Error: cannot parse version '{current}'", file=sys.stderr)
        return 1

    level = args.level
    if level == "patch":
        patch += 1
    elif level == "minor":
        minor += 1
        patch = 0
    elif level == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        print(f"Error: unknown bump level '{level}'", file=sys.stderr)
        return 1

    new_version = f"{major}.{minor}.{patch}"
    root = _project_root()

    # Update package.json
    pkg_path = root / "package.json"
    pkg_data = load_json(pkg_path) or {}
    pkg_data["version"] = new_version
    save_json(pkg_path, pkg_data)

    # Update plugin.json
    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_data["version"] = new_version
    save_json(plugin_path, plugin_data)

    # Update marketplace.json
    market_path = root / ".claude-plugin" / "marketplace.json"
    market_data = load_json(market_path) or {}
    plugins = market_data.get("plugins") or [{}]
    plugins[0]["version"] = new_version
    market_data["plugins"] = plugins
    save_json(market_path, market_data)

    # Update extension manifest
    ext_manifest_path = root / "extension" / "manifest.json"
    ext_manifest_data = load_json(ext_manifest_path) or {}
    ext_manifest_data["version"] = new_version
    save_json(ext_manifest_path, ext_manifest_data)

    # Update extension package.json
    ext_package_path = root / "extension" / "package.json"
    ext_package_data = load_json(ext_package_path) or {}
    ext_package_data["version"] = new_version
    save_json(ext_package_path, ext_package_data)

    print(new_version)
    return 0


# ---------------------------------------------------------------------------
# context subcommands
# ---------------------------------------------------------------------------

def cmd_context_gather(args):
    root = _project_root()

    # Git Status
    git_status_data = {"modified": 0, "added": 0, "deleted": 0}
    git_status_raw = None
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(root)
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            for line in lines:
                if len(line) >= 2:
                    xy = line[:2]
                    if "M" in xy:
                        git_status_data["modified"] += 1
                    elif "A" in xy or "?" in xy:
                        git_status_data["added"] += 1
                    elif "D" in xy:
                        git_status_data["deleted"] += 1
            git_status_raw = lines
        else:
            git_status_raw = None
    except Exception:
        git_status_raw = None

    # Recent Changes
    diff_n = getattr(args, "diff", 1) or 1
    recent_changes = []
    try:
        result = subprocess.run(
            ["git", "diff", f"HEAD~{diff_n}..HEAD", "--name-only"],
            capture_output=True, text=True, cwd=str(root)
        )
        if result.returncode == 0:
            recent_changes = [l for l in result.stdout.splitlines() if l.strip()]
        else:
            recent_changes = None
    except Exception:
        recent_changes = None

    # Version
    versions = _read_versions()
    version_synced = (
        versions["package"]
        == versions["plugin"]
        == versions["marketplace"]
        == versions["ext_manifest"]
        == versions["ext_package"]
        and versions["package"] != ""
    )

    # Skills
    skills_list = []
    skills_dir = root / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                skill_name = None
                try:
                    for line in skill_md.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("name:"):
                            skill_name = line[5:].strip().strip('"').strip("'")
                            break
                except Exception:
                    pass
                skills_list.append(skill_name if skill_name else skill_dir.name)
            else:
                skills_list.append(skill_dir.name)

    # Agents
    agents_list = []
    agents_dir = root / "agents"
    if agents_dir.exists():
        for agent_file in sorted(agents_dir.glob("*.md")):
            agents_list.append(agent_file.stem)

    fmt = getattr(args, "format", "text") or "text"
    include_skills = getattr(args, "skills", True)
    include_agents = getattr(args, "agents", True)

    if fmt == "json":
        output = {
            "git_status": git_status_data if git_status_raw is not None else "(git 없음)",
            "recent_changes": recent_changes if recent_changes is not None else "(git 없음)",
            "version": {
                "package":     versions["package"],
                "plugin":      versions["plugin"],
                "marketplace": versions["marketplace"],
                "synced":      version_synced,
            },
        }
        if include_skills:
            output["skills"] = skills_list
        if include_agents:
            output["agents"] = agents_list
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # text format
        print("## Git Status")
        if git_status_raw is None:
            print("(git 없음)")
        else:
            print(f"Modified: {git_status_data['modified']} | Added: {git_status_data['added']} | Deleted: {git_status_data['deleted']}")
        print()

        print(f"## Recent Changes (HEAD~{diff_n}..HEAD)")
        if recent_changes is None:
            print("(git 없음)")
        elif recent_changes:
            for f in recent_changes:
                print(f)
        else:
            print("(변경 없음)")
        print()

        print("## Version")
        print(f"package.json:      {versions['package']}")
        print(f"plugin.json:       {versions['plugin']}")
        print(f"marketplace.json:  {versions['marketplace']}")
        print("✓ 동기화됨" if version_synced else "✗ 불일치")
        print()

        if include_skills:
            print(f"## Skills ({len(skills_list)})")
            print(", ".join(skills_list) if skills_list else "(없음)")
            print()

        if include_agents:
            print(f"## Agents ({len(agents_list)})")
            print(", ".join(agents_list) if agents_list else "(없음)")
            print()

    return 0


# ---------------------------------------------------------------------------
# agents subcommands
# ---------------------------------------------------------------------------

def cmd_agents_check(args):
    root = _project_root()
    agents_dir = root / "agents"
    fs_agents = set()
    if agents_dir.exists():
        for f in agents_dir.glob("*.md"):
            fs_agents.add(f"./agents/{f.name}")

    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_agents = set(plugin_data.get("agents") or [])

    missing = fs_agents - plugin_agents   # in fs but not in plugin.json
    ghost = plugin_agents - fs_agents     # in plugin.json but not in fs

    if not missing and not ghost:
        print(f"✓ agents 배열 동기화됨 ({len(fs_agents)}개)")
        return 0

    for entry in sorted(missing):
        print(f"+ {entry}")
    for entry in sorted(ghost):
        print(f"- {entry}")
    return 1


def cmd_agents_sync(args):
    root = _project_root()
    agents_dir = root / "agents"
    fs_agents = []
    if agents_dir.exists():
        for f in sorted(agents_dir.glob("*.md")):
            fs_agents.append(f"./agents/{f.name}")

    plugin_path = root / ".claude-plugin" / "plugin.json"
    plugin_data = load_json(plugin_path) or {}
    plugin_data["agents"] = fs_agents
    save_json(plugin_path, plugin_data)
    print(f"Updated agents: {fs_agents}")
    return 0


# ---------------------------------------------------------------------------
# archive subcommands
# ---------------------------------------------------------------------------

def cmd_archive_run(args):
    type_key = getattr(args, "type", None) or "req"
    max_active = _load_archive_max_active(args.max, type_key)
    _archive_run_type(type_key, max_active, emit_output=True)
    return 0


def _resolve_archive_max_active(max_active_cfg, type_key: Optional[str]) -> int:
    value = max_active_cfg
    if isinstance(max_active_cfg, dict):
        value = max_active_cfg.get(type_key) if type_key else None
        if value is None:
            value = max_active_cfg.get("default", 20)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 20


def _load_archive_max_active(cli_max: Optional[int], type_key: Optional[str] = None) -> int:
    if cli_max is not None:
        return cli_max

    config_paths = [
        BASE_DIR / ".." / ".gran-maestro" / "config.json",
        BASE_DIR.parent / "config.json",
    ]
    cfg = None
    for path in config_paths:
        loaded = load_json(path)
        if loaded is not None:
            cfg = loaded
            break

    max_active_cfg = 20
    if isinstance(cfg, dict):
        max_active_cfg = cfg.get("archive", {}).get("max_active_sessions", 20)
    return _resolve_archive_max_active(max_active_cfg, type_key)


def _archive_run_type(type_key: str, max_active: int, emit_output: bool) -> int:
    subdir, prefix = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    src_dir = BASE_DIR / subdir
    dst_dir = type_archived_dir(type_key)
    dst_dir.mkdir(parents=True, exist_ok=True)

    dirs = sorted(src_dir.glob(f"{prefix}-*"))
    json_file = JSON_FILE_MAP.get(type_key, "session.json")

    if type_key == "cap":
        now = datetime.now(timezone.utc)
        to_archive = []
        for d in dirs:
            if not d.is_dir():
                continue
            data = load_json(d / json_file) or {}
            if not _capture_expired(data, now):
                continue
            linked_plan = (data.get("linked_plan") or "").upper()
            if not _capture_is_plan_active(linked_plan):
                to_archive.append(d)
    else:
        completed = [d for d in dirs if d.is_dir() and
                     (load_json(d / json_file) or {}).get("status") in ("completed", "cancelled", "done", "consensus_reached", "converged")]

        if len(dirs) - len(completed) <= max_active:
            if emit_output:
                print("No archiving needed.")
            return 0

        to_archive = completed[:len(dirs) - max_active]

    if not to_archive:
        if emit_output:
            if type_key == "cap":
                print("No captures to archive.")
            else:
                print("No completed sessions to archive.")
        return 0

    ids = [d.name for d in to_archive]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"{subdir}-{ids[0]}-to-{ids[-1]}-{timestamp}.tar.gz"
    archive_path = dst_dir / archive_name

    if type_key == "cap":
        for d in to_archive:
            cap_json = d / json_file
            cap_data = load_json(cap_json) or {}
            cap_data["status"] = "archived"
            save_json(cap_json, cap_data)

    with tarfile.open(archive_path, "w:gz") as tar:
        for d in to_archive:
            tar.add(d, arcname=d.name)

    for d in to_archive:
        shutil.rmtree(d)

    if emit_output:
        print(f"Archived {len(to_archive)} sessions → {archive_name}")
    return len(to_archive)


def cmd_archive_run_all(args):
    counts = {}
    had_error = False
    for type_key in TYPE_DIRS:
        try:
            max_active = _load_archive_max_active(args.max, type_key)
            counts[type_key] = _archive_run_type(type_key, max_active=max_active, emit_output=False)
        except Exception as exc:
            print(f"[Archive] {type_key} 정리 실패: {exc}", file=sys.stderr)
            counts[type_key] = 0
            had_error = True

    if sum(counts.values()) == 0 and not had_error:
        print("[Archive] 정리 대상 없음")
        return 0

    summary = ", ".join(f"{k}:{counts[k]}" for k in counts.keys())
    print(f"[Archive] 전체 정리 완료 — {summary}")
    return 0


def cmd_archive_list(args):
    has_any = False
    filter_type = getattr(args, "type", None)
    for type_key, (subdir, _) in TYPE_DIRS.items():
        if filter_type and filter_type != type_key:
            continue
        archived = type_archived_dir(type_key)
        if not archived.exists():
            continue
        for a in sorted(archived.glob("*.tar.gz")):
            size_kb = a.stat().st_size // 1024
            print(f"{a.name:<60} {size_kb:>6} KB")
            has_any = True
    if not has_any:
        print("No archives found.")
    return 0


def cmd_archive_restore(args):
    target = args.archive_id.upper()
    prefix = target[:3]
    prefix_to_type = {"REQ": "req", "IDN": "idn", "DSC": "dsc", "DBG": "dbg", "CAP": "cap"}
    type_key = prefix_to_type.get(prefix, "req")
    subdir, _ = TYPE_DIRS.get(type_key, ("requests", "REQ"))
    archived = type_archived_dir(type_key)
    restore_dir = BASE_DIR / subdir

    for arc in sorted(archived.glob("*.tar.gz")):
        with tarfile.open(arc, "r:gz") as tar:
            names = tar.getnames()
            matching = [n for n in names if n.startswith(target + "/") or n == target]
            if matching:
                tar.extractall(path=restore_dir, members=[tar.getmember(n) for n in matching])
                print(f"Restored {target} from {arc.name}")
                return 0
    print(f"Error: {args.archive_id} not found in any archive.", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# cleanup subcommand
# ---------------------------------------------------------------------------

def cmd_cleanup(args):
    dirs = sorted(requests_dir().glob("REQ-*"))
    stale = []
    for d in dirs:
        if not d.is_dir():
            continue
        data = load_json(d / "request.json") or {}
        if data.get("status") in ("completed", "cancelled"):
            stale.append((d, data))

    if not stale:
        print("Nothing to clean up.")
        return 0

    print(f"Found {len(stale)} completed/cancelled sessions:")
    for d, data in stale:
        print(f"  {d.name}: {data.get('title', '')[:50]}")

    if args.dry_run:
        print("[dry-run] No changes made.")
        return 0

    dst_dir = type_archived_dir("req")
    dst_dir.mkdir(parents=True, exist_ok=True)
    ids = [d.name for d in stale]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if len(ids) == 1:
        archive_name = f"requests-{ids[0]}-{timestamp}.tar.gz"
    else:
        archive_name = f"requests-{ids[0]}-to-{ids[-1]}-{timestamp}.tar.gz"
    archive_path = dst_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as tar:
        for d, _ in stale:
            tar.add(d, arcname=d.name)

    for d, _ in stale:
        shutil.rmtree(d)

    print(f"Archived {len(stale)} sessions → {archive_name}")
    return 0


# ---------------------------------------------------------------------------
# session subcommands
# ---------------------------------------------------------------------------

def cmd_session_list(args):
    session_type = args.type
    type_map = {"ideation": ("ideation", "IDN"), "discussion": ("discussion", "DSC"), "debug": ("debug", "DBG")}
    types_to_scan = [type_map[session_type]] if session_type in type_map else list(type_map.values())

    for subdir, prefix in types_to_scan:
        sdir = BASE_DIR / subdir
        if not sdir.exists():
            continue
        for sess in sorted(sdir.glob(f"{prefix}-*")):
            if not sess.is_dir():
                continue
            sj = load_json(sess / "session.json") or {}
            topic = (sj.get("topic") or sj.get("title") or "")[:50]
            print(f"{sess.name:<15} {subdir:<12} {topic}")
    return 0


def cmd_session_inspect(args):
    sess_id = args.session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix, "ideation")
    sess_path = BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj:
        print(json.dumps(sj, ensure_ascii=False, indent=2))
    return 0


def cmd_session_complete(args):
    sess_id = args.session_id.upper()
    prefix = sess_id[:3]
    type_map = {"IDN": "ideation", "DSC": "discussion", "DBG": "debug"}
    subdir = type_map.get(prefix)
    if subdir is None:
        print(f"Error: Unknown session type '{prefix}'. Expected IDN/DSC/DBG.", file=sys.stderr)
        return 1
    sess_path = BASE_DIR / subdir / sess_id
    if not sess_path.exists():
        print(f"Error: {sess_id} not found.", file=sys.stderr)
        return 1
    sj = load_json(sess_path / "session.json")
    if sj is None:
        print(f"Error: session.json not found for {sess_id}.", file=sys.stderr)
        return 1
    if sj.get("status") == "completed":
        print(f"{sess_id} is already completed.")
        return 0
    from _state_manager import complete
    complete(BASE_DIR, sess_id)
    print(f"Completed: {sess_id}")
    return 0


# ---------------------------------------------------------------------------
# notify subcommand
# ---------------------------------------------------------------------------

def cmd_notify(args):
    from _notifier import notify
    data = json.loads(args.data) if args.data else {}
    ok = notify(args.event_type, data)
    if ok:
        print(f"notify: {args.event_type} 전송됨")
    else:
        print(f"notify: {args.event_type} 실패 (서버 미실행 또는 연결 오류)")
    return 0


# ---------------------------------------------------------------------------
# wait-files subcommand
# ---------------------------------------------------------------------------

def cmd_wait_files(args):
    files = args.files
    total = len(files)

    # 타임아웃 우선순위: CLI 인자 > config.json > 기본값 600s
    cfg = load_json(BASE_DIR / "config.json") or {}
    if args.timeout is not None:
        timeout_s = args.timeout
    else:
        timeout_ms = cfg.get("timeouts", {}).get("wait_files_ms", 600000)
        timeout_s = timeout_ms / 1000
    min_content_wait = cfg.get("min_content_wait", 5)
    try:
        min_content_wait = float(min_content_wait)
    except (TypeError, ValueError):
        min_content_wait = 5

    completed = set()
    empty_files_seen = {}
    start = time.time()

    while time.time() - start < timeout_s:
        for f in files:
            if f in completed:
                continue

            if os.path.exists(f):
                size = os.path.getsize(f)
                if size > 0:
                    completed.add(f)
                    name = os.path.basename(f)
                    print(f"[{len(completed)}/{total}] {name} 완료", flush=True)
                else:
                    now = time.time()
                    if f not in empty_files_seen:
                        empty_files_seen[f] = now
                    elif min_content_wait > 0 and now - empty_files_seen[f] < min_content_wait:
                        continue
                    # 빈 파일이 생성되어도 즉시 완료로 처리하지 않고 재확인
            else:
                empty_files_seen.pop(f, None)

        if len(completed) == total:
            print("ALL_READY", flush=True)
            return 0

        time.sleep(1)

    print(f"TIMEOUT ({len(completed)}/{total})", flush=True)
    return 1


_EXPLORE_INDEX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._-])(?:\.{1,2}/|/)?(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"
)
_EXPLORE_INDEX_STOPWORDS = {
    "and", "are", "for", "from", "into", "that", "the", "this", "with",
    "있는", "으로", "에서", "이다", "하는", "사항", "결과", "요약", "추가", "탐색",
    "범위", "구조적", "관계", "영역", "제안", "파일", "경로", "기준", "확인",
}


def _extract_markdown_section(text: str, title: str) -> str:
    heading_re = re.compile(
        rf"^\s{{0,3}}#{{1,6}}\s+(?:\*\*)?{re.escape(title)}(?:\*\*)?\s*$",
        re.MULTILINE,
    )
    match = heading_re.search(text)
    if not match:
        return ""

    section_start = match.end()
    remainder = text[section_start:]
    next_heading = re.search(r"^\s{0,3}#{1,6}\s+.+$", remainder, re.MULTILINE)
    section_end = section_start + (next_heading.start() if next_heading else len(remainder))
    return text[section_start:section_end].strip()


def _normalize_path_candidate(raw: str):
    candidate = (raw or "").strip().strip("`*\"'()[]{}<>.,;:")
    if not candidate:
        return None
    if "://" in candidate or candidate.startswith("/mst:"):
        return None
    if "/" not in candidate:
        return None
    return candidate


def _extract_paths(text: str):
    seen = set()
    paths = []
    for raw in _EXPLORE_INDEX_PATH_RE.findall(text or ""):
        candidate = _normalize_path_candidate(raw)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        paths.append(candidate)
    return paths


def _extract_keywords(text: str, limit: int = 30):
    cleaned = re.sub(r"`[^`]+`", " ", text or "")
    cleaned = _EXPLORE_INDEX_PATH_RE.sub(" ", cleaned)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[가-힣]{2,}", cleaned)

    frequencies = {}
    for token in tokens:
        keyword = token.lower()
        if keyword in _EXPLORE_INDEX_STOPWORDS or keyword.startswith("exp-"):
            continue
        frequencies[keyword] = frequencies.get(keyword, 0) + 1

    ranked = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
    return [keyword for keyword, _ in ranked[:limit]]


def cmd_explore_index(args):
    report_path = Path(args.report).expanduser()
    if not report_path.is_absolute():
        report_path = (Path.cwd() / report_path).resolve()
    if not report_path.exists() or not report_path.is_file():
        print(f"Error: report file not found: {report_path}", file=sys.stderr)
        return 1

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to read report file ({exc})", file=sys.stderr)
        return 1

    scope_section = _extract_markdown_section(report_text, "탐색 범위")
    findings_section = _extract_markdown_section(report_text, "발견 사항")
    relations_section = _extract_markdown_section(report_text, "구조적 관계")

    scope_files = _extract_paths(scope_section)
    finding_keywords = _extract_keywords(findings_section)
    related_paths = _extract_paths("\n".join([findings_section, relations_section]))
    if not related_paths:
        related_paths = _extract_paths(report_text)

    payload = {
        "탐색 범위 파일 목록": scope_files,
        "발견 사항 키워드": finding_keywords,
        "관련 파일 경로": related_paths,
    }

    output_path = Path(args.output).expanduser() if args.output else report_path.with_name("index.json")
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()

    try:
        save_json(output_path, payload)
    except OSError as exc:
        print(f"Error: failed to write index file ({exc})", file=sys.stderr)
        return 1

    print(str(output_path))
    return 0


def cmd_stitch_sleep(args):
    """Stitch 비동기 생성 대기용 인터벌 sleep."""
    interval = args.interval
    print(f"[Stitch] {interval}초 대기 중...", flush=True)
    time.sleep(interval)
    print("SLEEP_DONE", flush=True)
    return 0


# ---------------------------------------------------------------------------
# priority subcommand
# ---------------------------------------------------------------------------

def cmd_priority(args):
    task_id = args.task_id.upper()
    parts = task_id.split("-")
    if len(parts) != 3:
        print(f"Error: invalid task ID '{args.task_id}'. Expected REQ-XXX-YY format.", file=sys.stderr)
        return 1

    req_id = f"{parts[0]}-{parts[1]}"
    task_num = parts[2]

    status_paths = [
        BASE_DIR / "requests" / req_id / "tasks" / task_num / "status.json",
        BASE_DIR / "requests" / "completed" / req_id / "tasks" / task_num / "status.json",
    ]
    status_path = next((p for p in status_paths if p.exists()), None)
    if status_path is None:
        print(f"Error: task {args.task_id} not found", file=sys.stderr)
        return 1

    data = load_json(status_path)
    if data is None:
        print(f"Error: failed to load status.json for {args.task_id}", file=sys.stderr)
        return 1

    if args.before:
        data["priority"] = "high"
        data["priority_before"] = args.before.upper()
        data.pop("priority_after", None)
    elif args.after:
        data["priority"] = "low"
        data["priority_after"] = args.after.upper()
        data.pop("priority_before", None)
    else:
        data["priority"] = "normal"
        data.pop("priority_before", None)
        data.pop("priority_after", None)

    save_json(status_path, data)
    print(f"priority updated: {task_id}")
    return 0


def cmd_task_set_commit(args):
    task_id = args.task_id.upper()
    match = re.match(r"^(REQ-\d+)-T(\d{2})$", task_id)
    if not match:
        print(
            f"Error: invalid task ID '{args.task_id}'. "
            "Expected REQ-NNN-TNN format.",
            file=sys.stderr
        )
        return 1

    if not args.commit_hash:
        print("Error: commit hash is required.", file=sys.stderr)
        return 1

    req_id = match.group(1)

    request_paths = [
        BASE_DIR / "requests" / req_id / "request.json",
        BASE_DIR / "requests" / "completed" / req_id / "request.json",
    ]
    request_path = next((p for p in request_paths if p.exists()), None)
    if request_path is None:
        print(f"Error: request.json not found for {req_id}", file=sys.stderr)
        return 1

    data = load_json(request_path)
    if data is None:
        print(f"Error: failed to load request.json for {req_id}", file=sys.stderr)
        return 1

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        print(f"Error: tasks field not found in {request_path}", file=sys.stderr)
        return 1

    for task in tasks:
        if isinstance(task, dict) and task.get("id", "").upper() == task_id:
            task["commit_hash"] = args.commit_hash
            task["commit_message"] = args.commit_message or ""
            break
    else:
        print(f"Error: task {task_id} not found in request.json", file=sys.stderr)
        return 1

    save_json(request_path, data)
    print(f"commit metadata saved: {task_id}")
    return 0


def _load_resolve_model_config():
    plugin_root = _plugin_root()
    config_paths = [
        BASE_DIR / "config.resolved.json",
        plugin_root / "templates" / "defaults" / "config.json",
    ]
    for path in config_paths:
        config = load_json(path)
        if isinstance(config, dict):
            return config
    return {}


def _resolve_provider_default_model(provider, provider_cfg):
    if isinstance(provider_cfg, dict):
        default_tier = provider_cfg.get("default_tier")
        if isinstance(default_tier, str):
            default_model = provider_cfg.get(default_tier)
            if isinstance(default_model, str) and default_model:
                return default_model

    hardcoded = {
        "codex": "gpt-5.3-codex",
        "gemini": "gemini-3.1-pro-preview",
        "claude": "claude-sonnet-4-6",
    }
    return hardcoded.get(provider, hardcoded["codex"])


def cmd_resolve_model(args):
    provider = str(args.provider or "").strip().lower()
    tier_or_section = str(args.tier_or_section or "").strip().lower()

    config = _load_resolve_model_config()
    models_cfg = config.get("models", {}) if isinstance(config, dict) else {}
    providers_cfg = models_cfg.get("providers", {}) if isinstance(models_cfg, dict) else {}
    provider_cfg = providers_cfg.get(provider) if isinstance(providers_cfg, dict) else None

    fallback_model = _resolve_provider_default_model(provider, provider_cfg)

    if not isinstance(provider_cfg, dict):
        print(f"Warning: unknown provider '{provider}', using fallback model", file=sys.stderr)
        print(fallback_model)
        return 0

    default_tier = provider_cfg.get("default_tier")
    if not isinstance(default_tier, str):
        default_tier = None

    resolved_tier = None

    if tier_or_section == "default":
        resolved_tier = default_tier
    else:
        section_cfg = config.get(tier_or_section, {})
        is_section = isinstance(section_cfg, dict) and isinstance(section_cfg.get("agents"), dict)
        if is_section:
            agents_cfg = section_cfg.get("agents", {})
            provider_agent_cfg = agents_cfg.get(provider, {})
            if isinstance(provider_agent_cfg, dict):
                section_tier = provider_agent_cfg.get("tier")
                if isinstance(section_tier, str):
                    resolved_tier = section_tier
            if not isinstance(resolved_tier, str):
                resolved_tier = default_tier
        else:
            resolved_tier = tier_or_section

    model = provider_cfg.get(resolved_tier) if isinstance(resolved_tier, str) else None
    if isinstance(model, str) and model:
        print(model)
        return 0

    print(
        f"Warning: unknown tier/section '{tier_or_section}' for provider '{provider}', "
        "using fallback model",
        file=sys.stderr,
    )
    print(fallback_model)
    return 0


LEGACY_AGENT_SECTIONS = ["debug", "explore", "discussion", "ideation", "prereview"]
LEGACY_MODEL_KEYS = ["claude", "codex", "gemini", "developer", "reviewer"]
CLAUDE_MODEL_TO_TIER = {
    "opus": "premium",
    "sonnet": "economy",
    "haiku": "economy",
}


def _load_json_strict(path: Path, required=True):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            print(f"Error: file not found: {path}", file=sys.stderr)
            raise SystemExit(1)
        return None
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as exc:
        print(f"Error: failed to read {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _has_legacy_format(config):
    if not isinstance(config, dict):
        return False

    for section in LEGACY_AGENT_SECTIONS:
        agents = config.get(section, {}).get("agents", {})
        if not isinstance(agents, dict):
            continue
        for value in agents.values():
            if isinstance(value, (int, float)):
                return True

    models = config.get("models", {})
    if isinstance(models, dict):
        for legacy_key in LEGACY_MODEL_KEYS:
            if legacy_key in models:
                return True

    code_review = config.get("code_review", {})
    if isinstance(code_review, dict) and isinstance(code_review.get("agent_roster"), str):
        return True

    phase1 = config.get("phase1_exploration", {})
    roles = phase1.get("roles", {}) if isinstance(phase1, dict) else {}
    if isinstance(roles, dict):
        for role_cfg in roles.values():
            if isinstance(role_cfg, dict) and "model" in role_cfg:
                return True

    return False


def _provider_model_to_tier(provider, model_name, default_providers):
    if not isinstance(provider, str) or not isinstance(model_name, str):
        return None

    if provider == "claude" and model_name in CLAUDE_MODEL_TO_TIER:
        return CLAUDE_MODEL_TO_TIER[model_name]

    provider_defaults = default_providers.get(provider)
    if isinstance(provider_defaults, dict):
        for tier, tier_model in provider_defaults.items():
            if tier == "default_tier":
                continue
            if isinstance(tier_model, str) and tier_model == model_name:
                return tier

    return None


def _prune_empty_dicts(node):
    if not isinstance(node, dict):
        return
    for key in list(node.keys()):
        value = node.get(key)
        if isinstance(value, dict):
            _prune_empty_dicts(value)
            if not value:
                del node[key]


def _ensure_roles_dict(models):
    roles = models.get("roles")
    if roles is None:
        models["roles"] = {}
        return models["roles"]
    if isinstance(roles, dict):
        return roles
    return None


def _default_section_claude_tier(defaults, section):
    section_cfg = defaults.get(section, {}) if isinstance(defaults, dict) else {}
    agents = section_cfg.get("agents", {}) if isinstance(section_cfg, dict) else {}
    claude_cfg = agents.get("claude", {}) if isinstance(agents, dict) else {}
    if isinstance(claude_cfg, dict):
        tier = claude_cfg.get("tier")
        if isinstance(tier, str):
            return tier
    return None


def _migrate_config(config, defaults):
    migrated = copy.deepcopy(config) if isinstance(config, dict) else {}
    warnings = []

    def warn(message):
        warnings.append(message)

    defaults_models = defaults.get("models", {}) if isinstance(defaults, dict) else {}
    default_providers = defaults_models.get("providers", {}) if isinstance(defaults_models, dict) else {}
    default_roles = defaults_models.get("roles", {}) if isinstance(defaults_models, dict) else {}

    for section in LEGACY_AGENT_SECTIONS:
        section_cfg = migrated.get(section)
        if not isinstance(section_cfg, dict):
            continue
        agents = section_cfg.get("agents")
        if not isinstance(agents, dict):
            continue

        for provider, raw_value in list(agents.items()):
            if not isinstance(raw_value, (int, float)):
                continue

            provider_defaults = default_providers.get(provider)
            if not isinstance(provider_defaults, dict):
                warn(
                    f"수동 확인 필요: {section}.agents.{provider}={_compact_json(raw_value)}"
                )
                continue

            if isinstance(raw_value, bool):
                count = int(raw_value)
                warn(
                    f"{section}.agents.{provider}: bool 값을 count={count}로 보정"
                )
            else:
                count = int(raw_value)
                if raw_value < 0 or (
                    isinstance(raw_value, float) and not raw_value.is_integer()
                ):
                    warn(
                        f"{section}.agents.{provider}: {raw_value} 값을 count={max(0, count)}로 보정"
                    )
                if count < 0:
                    count = 0

            if count == 0:
                agents[provider] = {"count": 0}
                continue

            default_tier = provider_defaults.get("default_tier")
            if not isinstance(default_tier, str) or not default_tier:
                warn(
                    f"수동 확인 필요: {section}.agents.{provider}={_compact_json(raw_value)}"
                )
                continue
            agents[provider] = {"count": count, "tier": default_tier}

    models = migrated.get("models")
    if isinstance(models, dict):
        legacy_claude = models.get("claude")
        if isinstance(legacy_claude, dict):
            for role, model_name in list(legacy_claude.items()):
                legacy_key = f"models.claude.{role}"
                if role in LEGACY_AGENT_SECTIONS:
                    mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                    if not isinstance(mapped_tier, str):
                        warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                        continue

                    section_cfg = migrated.get(role)
                    agents = section_cfg.get("agents") if isinstance(section_cfg, dict) else None
                    claude_cfg = agents.get("claude") if isinstance(agents, dict) else None

                    count = 0
                    if isinstance(claude_cfg, dict):
                        raw_count = claude_cfg.get("count")
                        if isinstance(raw_count, bool):
                            count = int(raw_count)
                        elif isinstance(raw_count, (int, float)):
                            count = int(raw_count)
                    elif isinstance(claude_cfg, bool):
                        count = int(claude_cfg)
                    elif isinstance(claude_cfg, (int, float)):
                        count = int(claude_cfg)

                    if count > 0:
                        default_section_tier = _default_section_claude_tier(defaults, role)
                        if mapped_tier != default_section_tier:
                            if isinstance(claude_cfg, dict):
                                if "tier" not in claude_cfg:
                                    claude_cfg["tier"] = mapped_tier
                            elif isinstance(agents, dict) and "claude" not in agents:
                                agents["claude"] = {"count": count, "tier": mapped_tier}
                            else:
                                warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                                continue

                    del legacy_claude[role]
                    continue

                roles_cfg = models.get("roles")
                if isinstance(roles_cfg, dict) and role in roles_cfg:
                    del legacy_claude[role]
                    continue

                mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                    continue

                default_role_cfg = default_roles.get(role) if isinstance(default_roles, dict) else None
                if isinstance(default_role_cfg, dict):
                    default_provider = default_role_cfg.get("provider")
                    default_tier = default_role_cfg.get("tier")
                    if default_provider == "claude" and default_tier == mapped_tier:
                        del legacy_claude[role]
                        continue

                roles_cfg = _ensure_roles_dict(models)
                if roles_cfg is None:
                    warn(f"수동 확인 필요: {legacy_key}={_compact_json(model_name)}")
                    continue
                if role not in roles_cfg:
                    roles_cfg[role] = {"tier": mapped_tier}
                del legacy_claude[role]

        for provider in ["codex", "gemini"]:
            legacy_provider = models.get(provider)
            if not isinstance(legacy_provider, dict):
                continue
            if "default" not in legacy_provider:
                continue

            value = legacy_provider.get("default")
            provider_defaults = default_providers.get(provider)
            default_premium_model = (
                provider_defaults.get("premium")
                if isinstance(provider_defaults, dict)
                else None
            )
            if isinstance(default_premium_model, str) and value == default_premium_model:
                del legacy_provider["default"]
                continue

            warn(f"수동 확인 필요: models.{provider}.default={_compact_json(value)}")

        def migrate_legacy_role_array(legacy_key, role_key):
            legacy_cfg = models.get(legacy_key)
            if not isinstance(legacy_cfg, dict):
                return

            roles_cfg = models.get("roles")
            role_preexisting = isinstance(roles_cfg, dict) and role_key in roles_cfg
            role_defaults = (
                default_roles.get(role_key)
                if isinstance(default_roles, dict)
                else None
            )

            for index, field in enumerate(["primary", "fallback"]):
                if field not in legacy_cfg:
                    continue
                legacy_leaf = f"models.{legacy_key}.{field}"
                if role_preexisting:
                    del legacy_cfg[field]
                    continue

                model_name = legacy_cfg.get(field)
                default_provider = None
                default_tier = None
                if isinstance(role_defaults, list) and index < len(role_defaults):
                    default_role = role_defaults[index]
                    if isinstance(default_role, dict):
                        default_provider = default_role.get("provider")
                        default_tier = default_role.get("tier")

                expected_model = None
                provider_defaults = (
                    default_providers.get(default_provider)
                    if isinstance(default_provider, str)
                    else None
                )
                if isinstance(provider_defaults, dict) and isinstance(default_tier, str):
                    expected_model = provider_defaults.get(default_tier)

                if isinstance(expected_model, str) and model_name == expected_model:
                    del legacy_cfg[field]
                    continue

                if not isinstance(default_provider, str):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                mapped_tier = _provider_model_to_tier(default_provider, model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                roles_cfg = _ensure_roles_dict(models)
                if roles_cfg is None:
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                role_override = roles_cfg.get(role_key)
                if role_override is None:
                    if isinstance(role_defaults, list):
                        role_override = copy.deepcopy(role_defaults)
                    else:
                        role_override = []
                    roles_cfg[role_key] = role_override
                if not isinstance(role_override, list):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                while len(role_override) <= index:
                    role_override.append({})
                if not isinstance(role_override[index], dict):
                    warn(f"수동 확인 필요: {legacy_leaf}={_compact_json(model_name)}")
                    continue

                if "tier" not in role_override[index]:
                    role_override[index]["tier"] = mapped_tier
                del legacy_cfg[field]

        migrate_legacy_role_array("developer", "developer")
        migrate_legacy_role_array("reviewer", "reviewer")

        legacy_developer = models.get("developer")
        if isinstance(legacy_developer, dict):
            claude_dev = legacy_developer.get("claude_dev")
            if isinstance(claude_dev, dict) and "model" in claude_dev:
                model_name = claude_dev.get("model")
                roles_cfg = models.get("roles")
                if isinstance(roles_cfg, dict) and "developer_claude" in roles_cfg:
                    del claude_dev["model"]
                else:
                    mapped_tier = _provider_model_to_tier("claude", model_name, default_providers)
                    if not isinstance(mapped_tier, str):
                        warn(
                            "수동 확인 필요: "
                            f"models.developer.claude_dev.model={_compact_json(model_name)}"
                        )
                    else:
                        roles_cfg = _ensure_roles_dict(models)
                        if roles_cfg is None:
                            warn(
                                "수동 확인 필요: "
                                f"models.developer.claude_dev.model={_compact_json(model_name)}"
                            )
                        else:
                            role_cfg = roles_cfg.get("developer_claude")
                            if role_cfg is None:
                                roles_cfg["developer_claude"] = {"tier": mapped_tier}
                            elif isinstance(role_cfg, dict) and "tier" not in role_cfg:
                                role_cfg["tier"] = mapped_tier
                            del claude_dev["model"]

    code_review = migrated.get("code_review")
    if isinstance(code_review, dict):
        agent_roster = code_review.get("agent_roster")
        if isinstance(agent_roster, str):
            tokens = []
            seen = set()
            for item in agent_roster.split(","):
                token = item.strip()
                if not token or token in seen:
                    continue
                seen.add(token)
                tokens.append(token)
            code_review["agent_roster"] = tokens

    phase1 = migrated.get("phase1_exploration")
    if isinstance(phase1, dict):
        roles = phase1.get("roles")
        if isinstance(roles, dict):
            for role_name, role_cfg in roles.items():
                if not isinstance(role_cfg, dict):
                    continue
                if "model" not in role_cfg:
                    continue
                model_name = role_cfg.get("model")
                provider = role_cfg.get("agent")
                if not isinstance(provider, str) or not isinstance(
                    default_providers.get(provider), dict
                ):
                    warn(
                        "수동 확인 필요: "
                        f"phase1_exploration.roles.{role_name}.model={_compact_json(model_name)}"
                    )
                    continue
                mapped_tier = _provider_model_to_tier(provider, model_name, default_providers)
                if not isinstance(mapped_tier, str):
                    warn(
                        "수동 확인 필요: "
                        f"phase1_exploration.roles.{role_name}.model={_compact_json(model_name)}"
                    )
                    continue
                role_cfg["tier"] = mapped_tier
                del role_cfg["model"]

    for root_key in ["models", "code_review", "phase1_exploration"]:
        root_cfg = migrated.get(root_key)
        if not isinstance(root_cfg, dict):
            continue
        _prune_empty_dicts(root_cfg)
        if not root_cfg:
            del migrated[root_key]

    return migrated, warnings


def _path_exists(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _format_migrate_value(value):
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return _compact_json(value)
    return str(value)


def cmd_config_migrate(args):
    plugin_root = _plugin_root()
    defaults_path = plugin_root / "templates" / "defaults" / "config.json"
    config_path = BASE_DIR / "config.json"

    defaults = _load_json_strict(defaults_path, required=True)
    if not isinstance(defaults, dict):
        print(f"Error: invalid defaults format: {defaults_path}", file=sys.stderr)
        return 1

    overrides = _load_json_strict(config_path, required=False)
    if overrides is None:
        print("변환할 항목 없음")
        return 0
    if not isinstance(overrides, dict):
        print(f"Error: invalid config format: {config_path}", file=sys.stderr)
        return 1

    migrated, warnings = _migrate_config(overrides, defaults)
    changed = _flat_diff(overrides, migrated)
    if not changed:
        print("변환할 항목 없음")
        for message in warnings:
            print(f"[WARN]    {message}")
        print(f"총 0건 변환, {len(warnings)}건 경고")
        return 0

    for key, (old_value, new_value) in changed.items():
        if key == "<root>":
            old_text = _format_migrate_value(old_value)
            new_text = _format_migrate_value(new_value)
        else:
            old_text = "(added)" if not _path_exists(overrides, key) else _format_migrate_value(old_value)
            new_text = "(deleted)" if not _path_exists(migrated, key) else _format_migrate_value(new_value)
        print(f"[MIGRATE] {key}: {old_text} → {new_text}")

    for message in warnings:
        print(f"[WARN]    {message}")
    print(f"총 {len(changed)}건 변환, {len(warnings)}건 경고")

    if not args.apply:
        return 0

    save_json(config_path, migrated)
    resolved = deep_merge(defaults, migrated)
    save_json(BASE_DIR / "config.resolved.json", resolved)
    print("config.json updated")
    print("config.resolved.json updated")
    return 0


def cmd_config_resolve(args):
    plugin_root = Path(__file__).resolve().parent.parent
    defaults_path = plugin_root / "templates" / "defaults" / "config.json"
    defaults = load_json(defaults_path) or {}
    overrides = load_json(BASE_DIR / "config.json") or {}
    if _has_legacy_format(overrides):
        print(
            "⚠ 구 포맷 설정 감지. `python3 scripts/mst.py config migrate` 실행을 권장합니다.",
            file=sys.stderr,
        )
    resolved = deep_merge(defaults, overrides)
    save_json(BASE_DIR / "config.resolved.json", resolved)
    print(f"config.resolved.json updated ({len(resolved)} top-level keys)")
    return 0


def _load_config_for_get():
    resolved = load_json(BASE_DIR / "config.resolved.json")
    if isinstance(resolved, dict):
        return resolved

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json")
    overrides = load_json(BASE_DIR / "config.json")
    if isinstance(defaults, dict) and isinstance(overrides, dict):
        return deep_merge(defaults, overrides)
    if isinstance(defaults, dict):
        return defaults
    if isinstance(overrides, dict):
        return overrides
    return {}


def _get_dotted_path(data, dotted_path):
    current = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def cmd_config_get(args):
    key_path = str(args.key_path or "").strip()
    if not key_path:
        print("Error: key.path is required", file=sys.stderr)
        return 1

    config = _load_config_for_get()
    found, value = _get_dotted_path(config, key_path)
    if not found:
        if args.default_value is None:
            print(f"Error: key not found: {key_path}", file=sys.stderr)
            return 1
        value = args.default_value

    if args.json:
        print(json.dumps({"key": key_path, "value": value}, ensure_ascii=False))
        return 0

    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False))
    else:
        print(value)
    return 0


def _load_preset(preset_id):
    plugin_root = _plugin_root()
    manifest = load_json(plugin_root / "templates" / "defaults" / "presets" / "manifest.json")

    # 1) built-in preset lookup from manifest
    if isinstance(manifest, dict):
        presets = manifest.get("presets")
        if isinstance(presets, list):
            for entry in presets:
                if not isinstance(entry, dict):
                    continue
                if entry.get("id") != preset_id:
                    continue
                rel_file = entry.get("file")
                if isinstance(rel_file, str):
                    return load_json(plugin_root / "templates" / "defaults" / "presets" / rel_file)

    # 2) user preset lookup (path traversal guard)
    if not re.match(r"^[a-z0-9-]+$", preset_id):
        return None
    user_file = BASE_DIR / "presets" / f"{preset_id}.json"
    if user_file.is_file():
        return load_json(user_file)

    return None


def _diff_from_base(base, current):
    diff = {}
    if not isinstance(base, dict) or not isinstance(current, dict):
        return diff

    for key, current_value in current.items():
        base_value = base.get(key)
        if isinstance(base_value, dict) and isinstance(current_value, dict):
            nested = _diff_from_base(base_value, current_value)
            if nested:
                diff[key] = nested
        elif current_value != base_value:
            diff[key] = current_value
    return diff


def _flat_diff(old, new, prefix=""):
    changes = {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        if old != new:
            changes[prefix or "<root>"] = (old, new)
        return changes

    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        full_key = f"{prefix}.{key}" if prefix else key
        old_value = old.get(key)
        new_value = new.get(key)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changes.update(_flat_diff(old_value, new_value, full_key))
        elif old_value != new_value:
            changes[full_key] = (old_value, new_value)
    return changes


def cmd_preset_list(args):
    plugin_root = _plugin_root()
    builtin_manifest = load_json(plugin_root / "templates" / "defaults" / "presets" / "manifest.json")

    presets = []
    if isinstance(builtin_manifest, dict):
        for p in builtin_manifest.get("presets", []):
            if isinstance(p, dict):
                presets.append({**p, "source": "builtin"})

    user_dir = BASE_DIR / "presets"
    if user_dir.is_dir():
        for preset_path in sorted(user_dir.glob("*.json")):
            presets.append({
                "id": preset_path.stem,
                "name": preset_path.stem,
                "source": "user",
                "file": str(preset_path),
            })

    if args.format == "json":
        print(json.dumps(presets, ensure_ascii=False, indent=2))
        return 0

    print(f"{'TYPE':<10} {'ID':<32} {'NAME'}")
    print("-" * 80)
    for preset in presets:
        source = "[builtin]" if preset.get("source") == "builtin" else "[user]"
        print(
            f"{source:<10} "
            f"{preset.get('id', ''):<32} "
            f"{preset.get('name', '')}"
        )
    return 0


def cmd_preset_apply(args):
    preset_data = _load_preset(args.preset_id)
    if not isinstance(preset_data, dict):
        print(f"Error: preset '{args.preset_id}' not found", file=sys.stderr)
        return 1

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    overrides = load_json(BASE_DIR / "config.json") or {}
    current_resolved = deep_merge(defaults, overrides)
    merged = deep_merge(current_resolved, preset_data)
    if "agent_assignments" in preset_data:
        merged["agent_assignments"] = preset_data["agent_assignments"]
    next_overrides = _diff_from_base(defaults, merged)
    save_json(BASE_DIR / "config.json", next_overrides)
    save_json(BASE_DIR / "config.resolved.json", merged)

    changed = _flat_diff(current_resolved, merged)
    if changed:
        print(f"Applied preset '{args.preset_id}': {len(changed)} settings changed")
        for key, (old, new) in changed.items():
            print(f"  {key}: {old} → {new}")
    else:
        print(f"Preset '{args.preset_id}' has no changes")
    return 0


def cmd_preset_diff(args):
    preset_data = _load_preset(args.preset_id)
    if not isinstance(preset_data, dict):
        print(f"Error: preset '{args.preset_id}' not found", file=sys.stderr)
        return 1

    plugin_root = _plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    overrides = load_json(BASE_DIR / "config.json") or {}
    current_resolved = deep_merge(defaults, overrides)
    merged = deep_merge(current_resolved, preset_data)

    changed = _flat_diff(current_resolved, merged)
    if not changed:
        print(f"No changes — current config already matches preset '{args.preset_id}'")
        return 0

    print(f"Preset '{args.preset_id}' would change {len(changed)} settings:")
    for key, (old, new) in changed.items():
        print(f"  {key}: {old} → {new}")
    return 0


def cmd_preset_save(args):
    if not re.match(r"^[a-z0-9-]+$", args.preset_id):
        print(
            f"Error: preset ID must match ^[a-z0-9-]+$ (got '{args.preset_id}')",
            file=sys.stderr,
        )
        return 1

    user_dir = BASE_DIR / "presets"
    user_dir.mkdir(parents=True, exist_ok=True)

    target = user_dir / f"{args.preset_id}.json"
    if target.is_file():
        print(f"Warning: overwriting existing user preset '{args.preset_id}'", file=sys.stderr)

    current = load_json(BASE_DIR / "config.json") or {}
    save_json(target, current)
    print(f"Saved current config as user preset '{args.preset_id}'")
    return 0


def cmd_hooks_post_skill(args):
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            return 0

        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return 0

        skill = tool_input.get("skill", "")
        if not isinstance(skill, str):
            return 0

        # --- return_to continuation guard ---
        # Check snapshot for returnTo BEFORE archiving (archive may clear state)
        _hooks_post_skill_continuation(skill)

        if skill not in {"mst:accept", "mst:ideation", "mst:discussion", "mst:debug"}:
            return 0

        resolved = load_json(BASE_DIR / "config.resolved.json") or {}
        archive_cfg = resolved.get("archive", {})
        if not isinstance(archive_cfg, dict):
            archive_cfg = {}

        if not archive_cfg.get("auto_archive_on_complete", True):
            return 0

        max_active_cfg = archive_cfg.get("max_active_sessions", 20)

        for type_key in TYPE_DIRS:
            try:
                max_active = _resolve_archive_max_active(max_active_cfg, type_key)
                _archive_run_type(type_key, max_active=max_active, emit_output=False)
            except Exception:
                pass
    except Exception:
        return 0
    return 0


def _hooks_post_skill_continuation(completed_skill: str) -> None:
    """If the snapshot has returnTo, emit a mandatory continuation message."""
    try:
        from _skill_state import load_snapshot

        state_base_dir = _skill_state_base_dir()
        snapshot = load_snapshot(state_base_dir)
        if snapshot is None:
            return

        return_to = snapshot.get("returnTo")
        if not isinstance(return_to, dict):
            return

        parent_skill = return_to.get("skill", "")
        parent_step = return_to.get("step")
        if not parent_skill:
            return

        # Only emit when the completed skill is NOT the parent itself
        # (avoid loop when the parent skill completes normally)
        skill_short = completed_skill.replace("mst:", "")
        if skill_short == parent_skill:
            return

        step_info = f"/{parent_step}" if parent_step is not None else ""
        print(
            f"\n⚠️ MANDATORY CONTINUATION: "
            f"return_to={parent_skill}{step_info} detected. "
            f"The sub-skill '{completed_skill}' has completed and MUST return control to the parent skill. "
            f"You MUST immediately call Skill(skill: \"mst:{parent_skill}\") to resume. "
            f"Do NOT end the conversation or ask the user — continue NOW.\n"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# extension subcommands
# ---------------------------------------------------------------------------

def _dir_content_hash(directory: Path) -> str:
    EXCLUDED_HASH_PARTS = {"node_modules", ".git", ".omc"}

    if not directory.exists():
        return ""

    hasher = hashlib.sha256()

    try:
        entries = sorted(
            [entry for entry in directory.rglob("*") if entry.is_file() and not entry.is_symlink()],
            key=lambda entry: str(entry.relative_to(directory).as_posix()),
        )
    except Exception:
        return ""

    for path in entries:
        relative_path = path.relative_to(directory)
        if relative_path.name == ".content-hash":
            continue
        if any(part in EXCLUDED_HASH_PARTS for part in relative_path.parts):
            continue
        try:
            hasher.update(str(relative_path.as_posix()).encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(path.read_bytes())
        except Exception:
            continue

    return hasher.hexdigest()


def _ensure_copy_impl(plugin_root: Path, home_dir: Path) -> int:
    if sys.platform == "win32":
        print("미지원 OS", file=sys.stderr)
        return 1

    src = plugin_root / "extension"
    dst = home_dir / "chrome-extension"

    is_project = (plugin_root / ".git").exists() and src.is_dir()
    if is_project:
        print("프로젝트 설치 감지. 직접 경로 사용 권장", file=sys.stderr)
        print("skipped")
        return 0

    if not src.exists():
        if dst.exists():
            print("경고: 플러그인 extension/ 경로가 없어 stale 상태일 수 있습니다.", file=sys.stderr)
        print("unchanged")
        return 0

    try:
        home_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[extension ensure-copy] 대상 상위 디렉토리 생성 실패: {exc}", file=sys.stderr)
        print("unchanged")
        return 0

    if not dst.exists():
        try:
            shutil.copytree(src, dst)
        except Exception as exc:
            print(f"[extension ensure-copy] extension 복사 실패: {exc}", file=sys.stderr)
            print("unchanged")
            return 0
        try:
            (dst / ".content-hash").write_text(_dir_content_hash(src), encoding="utf-8")
        except Exception:
            pass
        print("created")
        return 0

    src_hash = _dir_content_hash(src)
    dst_hash = ""
    try:
        dst_hash = (dst / ".content-hash").read_text(encoding="utf-8").strip()
    except Exception:
        pass

    if src_hash != dst_hash:
        try:
            shutil.rmtree(dst)
            shutil.copytree(src, dst)
        except Exception as exc:
            print(f"[extension ensure-copy] 버전 변경 반영 실패: {exc}", file=sys.stderr)
            print("unchanged")
            return 0
        try:
            (dst / ".content-hash").write_text(src_hash, encoding="utf-8")
        except Exception:
            pass
        print("updated")
        return 0

    print("unchanged")
    return 0


def cmd_extension_ensure_copy(args):
    plugin_root = Path(__file__).resolve().parent.parent
    home_dir = Path.home() / ".gran-maestro"
    return _ensure_copy_impl(plugin_root, home_dir)


# ---------------------------------------------------------------------------
# worktree subcommands
# ---------------------------------------------------------------------------

def _copy_worktree_support_files(project_root: Path, worktree_path: Path) -> int:
    source_claude_dir = project_root / ".claude"
    source_hooks_dir = source_claude_dir / "hooks"
    target_claude_dir = worktree_path / ".claude"
    target_hooks_dir = target_claude_dir / "hooks"

    if not source_hooks_dir.is_dir():
        print(f"Error: source hooks directory not found: {source_hooks_dir}", file=sys.stderr)
        return 1

    hook_sources = sorted(source_hooks_dir.glob("mst-*.sh"))
    if not hook_sources:
        print(f"Error: no mst hook scripts found in {source_hooks_dir}", file=sys.stderr)
        return 1

    settings_source = source_claude_dir / "settings.local.json"
    if not settings_source.is_file():
        print(f"Error: source settings file not found: {settings_source}", file=sys.stderr)
        return 1

    target_hooks_dir.mkdir(parents=True, exist_ok=True)

    try:
        for hook_source in hook_sources:
            target_path = target_hooks_dir / hook_source.name
            shutil.copy2(hook_source, target_path)
            target_path.chmod(0o755)

        hook_version_source = source_hooks_dir / ".mst-hook-version"
        if hook_version_source.is_file():
            shutil.copy2(hook_version_source, target_hooks_dir / ".mst-hook-version")

        target_claude_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings_source, target_claude_dir / "settings.local.json")
    except Exception as exc:
        print(f"Error: failed to copy worktree support files ({exc})", file=sys.stderr)
        return 1

    return 0


def _resolve_worktree_source_root() -> Path:
    project_root = _project_root()
    source_claude_dir = project_root / ".claude"
    if (source_claude_dir / "hooks").is_dir() and (source_claude_dir / "settings.local.json").is_file():
        return project_root
    return BASE_DIR.parent


def cmd_worktree_create(args):
    project_root = BASE_DIR.parent
    source_root = _resolve_worktree_source_root()
    worktree_path = Path(args.path).expanduser().resolve()
    branch = str(args.branch or "").strip()
    base = str(args.base or "").strip()

    if not branch:
        print("Error: --branch is required", file=sys.stderr)
        return 1
    if not base:
        print("Error: --base is required", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path), base],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if result.returncode != 0:
        print(result.stderr.strip() or result.stdout.strip() or "git worktree add failed", file=sys.stderr)
        return result.returncode or 1

    copy_result = _copy_worktree_support_files(source_root, worktree_path)
    if copy_result != 0:
        return copy_result

    print(str(worktree_path))
    return 0


def cmd_worktree_remove(args):
    project_root = BASE_DIR.parent
    worktree_path = Path(args.path).expanduser().resolve()

    remove_cmd = ["git", "worktree", "remove"]
    if getattr(args, "force", False):
        remove_cmd.append("--force")
    remove_cmd.append(str(worktree_path))

    remove_result = subprocess.run(
        remove_cmd,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if remove_result.returncode != 0:
        print(remove_result.stderr.strip() or remove_result.stdout.strip() or "git worktree remove failed", file=sys.stderr)
        return remove_result.returncode or 1

    prune_result = subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    if prune_result.returncode != 0:
        print(prune_result.stderr.strip() or prune_result.stdout.strip() or "git worktree prune failed", file=sys.stderr)
        return prune_result.returncode or 1

    print(str(worktree_path))
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="mst.py",
        description="Gran Maestro CLI utility"
    )
    sub = parser.add_subparsers(dest="command")

    # --- request ---
    req = sub.add_parser("request")
    req_sub = req.add_subparsers(dest="subcommand")

    req_list = req_sub.add_parser("list")
    req_list.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    req_list.add_argument("--all", dest="scope", action="store_const", const="all")
    req_list.add_argument("--completed", dest="scope", action="store_const", const="completed")
    req_list.add_argument("--format", choices=["table", "json"], default="table")

    req_inspect = req_sub.add_parser("inspect")
    req_inspect.add_argument("req_id")

    req_history = req_sub.add_parser("history")
    req_history.add_argument("--all", action="store_true")

    req_filter = req_sub.add_parser("filter")
    req_filter.add_argument("--phase", type=int)
    req_filter.add_argument("--status")
    req_filter.add_argument("--priority")
    req_filter.add_argument("--format", choices=["table", "json"], default="table")

    req_count = req_sub.add_parser("count")
    req_count.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    req_count.add_argument("--all", dest="scope", action="store_const", const="all")
    req_count.add_argument("--completed", dest="scope", action="store_const", const="completed")

    req_cancel = req_sub.add_parser("cancel")
    req_cancel.add_argument("req_id")

    req_set_phase = req_sub.add_parser("set-phase")
    req_set_phase.add_argument("req_id")
    req_set_phase.add_argument("phase", type=int)
    req_set_phase.add_argument("status")

    # --- workflow ---
    workflow = sub.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="subcommand")
    workflow_run = workflow_sub.add_parser("run")
    workflow_run.add_argument("target", help="PLN-NNN 또는 REQ-NNN")

    # --- worktree ---
    worktree = sub.add_parser("worktree")
    worktree_sub = worktree.add_subparsers(dest="subcommand")

    worktree_create = worktree_sub.add_parser("create")
    worktree_create.add_argument("--path", required=True)
    worktree_create.add_argument("--branch", required=True)
    worktree_create.add_argument("--base", default="master")

    worktree_remove = worktree_sub.add_parser("remove")
    worktree_remove.add_argument("--path", required=True)
    worktree_remove.add_argument("--force", action="store_true")

    # --- timestamp ---
    ts = sub.add_parser("timestamp")
    ts_sub = ts.add_subparsers(dest="subcommand")

    ts_now = ts_sub.add_parser("now")
    ts_now.set_defaults(func=cmd_timestamp)

    # --- set-status ---
    set_status_cmd = sub.add_parser("set-status")
    set_status_cmd.add_argument("id", help="REQ-NNN / PLN-NNN / DBG-NNN 등")
    set_status_cmd.add_argument("status", help="새 상태값")
    set_status_cmd.set_defaults(func=cmd_set_status)

    # --- set-field ---
    set_field_cmd = sub.add_parser("set-field")
    set_field_cmd.add_argument("id", help="REQ-NNN / PLN-NNN / DBG-NNN 등")
    set_field_cmd.add_argument("field", help="JSON 필드명")
    set_field_cmd.add_argument("value", help="새 값 (문자열)")
    set_field_cmd.set_defaults(func=cmd_set_field)

    # --- state ---
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="subcommand")

    state_set = state_sub.add_parser("set")
    state_set.add_argument("--skill", required=True)
    state_set.add_argument("--step", type=int, required=True)
    state_set.add_argument("--total", type=int, required=True)
    state_set.add_argument("--return-to", dest="return_to")

    state_set_workflow = state_sub.add_parser("set-workflow")
    state_set_workflow.add_argument("--active", type=_parse_bool_arg, required=True)
    state_set_workflow.add_argument("--skill", default="")
    state_set_workflow.add_argument("--req", default="")
    state_set_workflow.add_argument("--next-skill", dest="next_skill", default="")
    state_set_workflow.add_argument("--next-source", dest="next_source", default="")
    state_set_workflow.add_argument("--source-skill", dest="source_skill", default="")
    state_set_workflow.add_argument("--auto", type=_parse_bool_arg, default=False)
    state_set_workflow.add_argument("--agile-loop-active", dest="agile_loop_active", type=_parse_bool_arg)
    state_set_workflow.add_argument("--steering-disabled", dest="steering_disabled", type=_parse_bool_arg)

    state_sub.add_parser("get")
    state_sub.add_parser("clear")

    # --- measure ---
    measure = sub.add_parser("measure")
    measure_sub = measure.add_subparsers(dest="subcommand")
    measure_stop_rate = measure_sub.add_parser("stop-rate")
    measure_stop_rate.add_argument("--snapshots-dir")
    measure_stop_rate.add_argument("--pretty", action="store_true")

    # --- plan ---
    plan = sub.add_parser("plan")
    plan_sub = plan.add_subparsers(dest="subcommand")

    plan_list = plan_sub.add_parser("list")
    plan_list.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    plan_list.add_argument("--all", dest="scope", action="store_const", const="all")

    plan_count = plan_sub.add_parser("count")
    plan_count.add_argument("--active", dest="scope", action="store_const", const="active", default="active")
    plan_count.add_argument("--all", dest="scope", action="store_const", const="all")
    plan_count.add_argument("--completed", dest="scope", action="store_const", const="completed")

    plan_inspect = plan_sub.add_parser("inspect")
    plan_inspect.add_argument("pln_id")

    plan_complete = plan_sub.add_parser("complete")
    plan_complete.add_argument("pln_id")

    p_plan_sync = plan_sub.add_parser("sync", help="Plan 완료 여부 동기화")
    p_plan_sync.add_argument("plan_id", help="Plan ID (예: PLN-068)")

    plan_render_review = plan_sub.add_parser("render-review", help="plan-review 프롬프트 파일 생성")
    plan_render_review.add_argument("--pln", dest="pln_id", required=True)
    plan_render_review.add_argument("--plan-draft", dest="plan_draft", default="")
    plan_render_review.add_argument("--plan-draft-file", dest="plan_draft_file", default=None)
    plan_render_review.add_argument("--qa-summary", dest="qa_summary", default="")

    # --- intent ---
    intent = sub.add_parser("intent")
    intent_sub = intent.add_subparsers(dest="subcommand")

    intent_add = intent_sub.add_parser("add")
    intent_add.add_argument("--req", dest="req")
    intent_add.add_argument("--plan", dest="plan")
    intent_add.add_argument("--feature", required=True)
    intent_add.add_argument("--situation", required=True)
    intent_add.add_argument("--motivation")
    intent_add.add_argument("--goal", required=True)
    intent_add.add_argument("--related-intent", dest="related_intent", action="append", default=[])
    intent_add.add_argument("--tag", dest="tag", action="append", default=[])
    intent_add.add_argument("--file", dest="file", action="append", default=[])
    intent_add.add_argument("--json", action="store_true")

    intent_get = intent_sub.add_parser("get")
    intent_get.add_argument("intent_id")
    intent_get.add_argument("--json", action="store_true")

    intent_list = intent_sub.add_parser("list")
    intent_list.add_argument("--req", dest="req")
    intent_list.add_argument("--plan", dest="plan")
    intent_list.add_argument("--json", action="store_true")

    intent_update = intent_sub.add_parser("update")
    intent_update.add_argument("intent_id")
    intent_update.add_argument("--feature")
    intent_update.add_argument("--situation")
    intent_update.add_argument("--motivation")
    intent_update.add_argument("--goal")
    intent_update.add_argument("--req", dest="req")
    intent_update.add_argument("--plan", dest="plan")
    intent_update.add_argument("--related-intent", dest="related_intent", action="append")
    intent_update.add_argument("--tag", dest="tag", action="append")
    intent_update.add_argument("--file", dest="file", action="append")
    intent_update.add_argument("--created-at", dest="created_at")
    intent_update.add_argument("--json", action="store_true")

    intent_delete = intent_sub.add_parser("delete")
    intent_delete.add_argument("intent_id")

    intent_search = intent_sub.add_parser("search")
    intent_search.add_argument("keyword")
    intent_search.add_argument("--json", action="store_true")

    intent_lookup = intent_sub.add_parser("lookup")
    intent_lookup.add_argument("--files", nargs="+", required=True)
    intent_lookup.add_argument("--json", action="store_true")

    intent_related = intent_sub.add_parser("related")
    intent_related.add_argument("intent_id")
    intent_related.add_argument("--depth", type=int, default=1)
    intent_related.add_argument("--json", action="store_true")

    intent_sub.add_parser("rebuild")

    # --- fact-check ---
    fact_check = sub.add_parser("fact-check")
    fact_check_sub = fact_check.add_subparsers(dest="subcommand")

    fact_check_add = fact_check_sub.add_parser("add")
    fact_check_add.add_argument("--plan", required=True, help="PLN-ID")
    fact_check_add.add_argument("--status", default="in_progress")
    fact_check_add.add_argument("--json", action="store_true")

    fact_check_get = fact_check_sub.add_parser("get")
    fact_check_get.add_argument("fact_check_id")
    fact_check_get.add_argument("--json", action="store_true")

    fact_check_list = fact_check_sub.add_parser("list")
    fact_check_list.add_argument("--plan")
    fact_check_list.add_argument("--status")
    fact_check_list.add_argument("--json", action="store_true")

    fact_check_search = fact_check_sub.add_parser("search")
    fact_check_search.add_argument("keyword")
    fact_check_search.add_argument("--tag")
    fact_check_search.add_argument("--status")
    fact_check_search.add_argument("--plan")
    fact_check_search.add_argument("--limit", type=int, default=100)
    fact_check_search.add_argument("--json", action="store_true")

    fact_check_update = fact_check_sub.add_parser("update")
    fact_check_update.add_argument("fact_check_id")
    fact_check_update.add_argument("--status")
    fact_check_update.add_argument("--json", action="store_true")

    fact_check_claim_update = fact_check_sub.add_parser("claim-update")
    fact_check_claim_update.add_argument("fact_check_id")
    fact_check_claim_update.add_argument("claim_id")
    fact_check_claim_update.add_argument("--status")
    fact_check_claim_update.add_argument(
        "--add-evidence",
        nargs=2,
        action="append",
        metavar=("URL", "SNIPPET"),
    )
    fact_check_claim_update.add_argument(
        "--evidence-type",
        choices=["web", "code", "official"],
        default="web",
    )
    fact_check_claim_update.add_argument("--json", action="store_true")

    # --- reference ---
    reference = sub.add_parser("reference")
    reference_sub = reference.add_subparsers(dest="subcommand")

    reference_add = reference_sub.add_parser("add")
    reference_add.add_argument("--topic", required=True)
    reference_add.add_argument("--url", required=True)
    reference_add.add_argument("--summary", required=True)
    reference_add.add_argument("--content")
    reference_add.add_argument("--json", action="store_true")

    reference_get = reference_sub.add_parser("get")
    reference_get.add_argument("reference_id")
    reference_get.add_argument("--json", action="store_true")

    reference_list = reference_sub.add_parser("list")
    reference_list.add_argument("--json", action="store_true")

    reference_search = reference_sub.add_parser("search")
    reference_search.add_argument("--keyword", required=True)
    reference_search.add_argument("--json", action="store_true")

    reference_update = reference_sub.add_parser("update")
    reference_update.add_argument("reference_id")
    reference_update.add_argument("--topic")
    reference_update.add_argument("--url")
    reference_update.add_argument("--summary")
    reference_update.add_argument("--searched-at")
    reference_update.add_argument("--content")
    reference_update.add_argument("--json", action="store_true")

    # --- agile ---
    agile = sub.add_parser("agile")
    agile_sub = agile.add_subparsers(dest="subcommand")

    agile_init = agile_sub.add_parser("init")
    agile_init.add_argument("--steering-every", type=int, default=3)
    agile_init.add_argument("--json", action="store_true")

    agile_status = agile_sub.add_parser("status")
    agile_status.add_argument("agi_id")
    agile_status.add_argument("--json", action="store_true")

    agile_update = agile_sub.add_parser("update")
    agile_update.add_argument("agi_id")
    agile_update.add_argument("--status")
    agile_update.add_argument("--current-sprint", type=int)
    agile_update.add_argument("--steering-every", type=int)
    agile_update.add_argument("--objective-version", type=int)
    agile_update.add_argument("--json", action="store_true")

    agile_result = agile_sub.add_parser("result")
    agile_result.add_argument("agi_id")
    agile_result.add_argument("--sprint", type=int, required=True)
    agile_result.add_argument("--status", required=True)
    agile_result.add_argument("--planned")
    agile_result.add_argument("--completed")
    agile_result.add_argument("--pln", action="append")
    agile_result.add_argument("--req", action="append")
    agile_result.add_argument("--summary")
    agile_result.add_argument("--outcome")
    agile_result.add_argument("--sprint-goals")
    agile_result.add_argument("--sprint-purpose")
    agile_result.add_argument("--selection-reason")
    agile_result.add_argument("--target-dod")
    agile_result.add_argument("--target-dod-text")
    agile_result.add_argument("--previous-direction")
    agile_result.add_argument("--previous-lessons")
    agile_result.add_argument("--json", action="store_true")

    agile_retrospective = agile_sub.add_parser("retrospective")
    agile_retrospective.add_argument("agi_id")
    agile_retrospective.add_argument("--sprint", type=int, required=True)
    agile_retrospective.add_argument("--status", required=True)
    agile_retrospective.add_argument("--succeeded", action="append", required=True)
    agile_retrospective.add_argument("--failed", action="append", required=True)
    agile_retrospective.add_argument("--velocity-planned", type=int, required=True)
    agile_retrospective.add_argument("--velocity-completed", type=int, required=True)
    agile_retrospective.add_argument("--limitations", required=True)
    agile_retrospective.add_argument("--lessons", required=True)
    agile_retrospective.add_argument("--direction", required=True)
    agile_retrospective.add_argument("--json", action="store_true")

    agile_known_issues = agile_sub.add_parser("known-issues")
    agile_known_issues_sub = agile_known_issues.add_subparsers(dest="known_issues_subcommand")

    agile_known_issues_add = agile_known_issues_sub.add_parser("add")
    agile_known_issues_add.add_argument("agi_id")
    agile_known_issues_add.add_argument("--description", required=True)
    agile_known_issues_add.add_argument(
        "--severity",
        required=True,
        choices=["MINOR", "MAJOR", "CRITICAL"],
    )
    agile_known_issues_add.add_argument("--sprint", type=int, required=True)
    agile_known_issues_add.add_argument("--json", action="store_true")

    agile_known_issues_resolve = agile_known_issues_sub.add_parser("resolve")
    agile_known_issues_resolve.add_argument("agi_id")
    agile_known_issues_resolve.add_argument("--issue-id", required=True)
    agile_known_issues_resolve.add_argument("--json", action="store_true")

    agile_known_issues_list = agile_known_issues_sub.add_parser("list")
    agile_known_issues_list.add_argument("agi_id")
    agile_known_issues_list.add_argument("--status", choices=["open", "resolved"])
    agile_known_issues_list.add_argument("--json", action="store_true")

    agile_objective_transition = agile_sub.add_parser("objective-transition")
    agile_objective_transition.add_argument("agi_id")
    agile_objective_transition.add_argument("--story", required=True)
    agile_objective_transition.add_argument("--status", required=True)
    agile_objective_transition.add_argument("--json", action="store_true")

    agile_objective_check = agile_sub.add_parser("objective-check")
    agile_objective_check.add_argument("agi_id")
    agile_objective_check.add_argument("--json", action="store_true")

    agile_objective_snapshot = agile_sub.add_parser("objective-snapshot")
    agile_objective_snapshot.add_argument("agi_id")
    agile_objective_snapshot.add_argument("--reason", required=True)
    agile_objective_snapshot.add_argument("--json", action="store_true")

    agile_link = agile_sub.add_parser("link")
    agile_link.add_argument("agi_id")
    agile_link.add_argument("--pln", action="append")
    agile_link.add_argument("--req", action="append")
    agile_link.add_argument("--json", action="store_true")

    # --- counter ---
    ctr = sub.add_parser("counter")
    ctr_sub = ctr.add_subparsers(dest="subcommand")

    ctr_next = ctr_sub.add_parser("next")
    ctr_next.add_argument(
        "--type",
        choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "fc", "ref", "intent", "agi"],
        default="req",
    )
    ctr_next.add_argument("--dir")

    ctr_peek = ctr_sub.add_parser("peek")
    ctr_peek.add_argument(
        "--type",
        choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "fc", "ref", "intent", "agi"],
        default="req",
    )
    ctr_peek.add_argument("--dir")

    # --- archive ---
    arc = sub.add_parser("archive")
    arc_sub = arc.add_subparsers(dest="subcommand")

    arc_run = arc_sub.add_parser("run")
    arc_run.add_argument("--type", choices=["req", "idn", "dsc", "dbg", "exp", "pln", "des", "cap", "agi"], default="req")
    arc_run.add_argument("--max", type=int)
    arc_run.add_argument("--dir")

    arc_run_all = arc_sub.add_parser("run-all")
    arc_run_all.add_argument("--max", type=int)

    arc_list = arc_sub.add_parser("list")
    arc_list.add_argument("--type")

    arc_restore = arc_sub.add_parser("restore")
    arc_restore.add_argument("archive_id")

    # --- gardening ---
    gardening = sub.add_parser("gardening")
    gardening_sub = gardening.add_subparsers(dest="subcommand")
    gardening_scan = gardening_sub.add_parser("scan")
    gardening_scan.add_argument("--json", action="store_true")

    # --- capture ---
    cap = sub.add_parser("capture")
    cap_sub = cap.add_subparsers(dest="subcommand")
    cap_ttl_check = cap_sub.add_parser("ttl-check")
    cap_ttl_check.set_defaults(func=cmd_capture_ttl_check)
    cap_mark_consumed = cap_sub.add_parser("mark-consumed")
    cap_mark_consumed.add_argument("--caps", required=True, help="comma-separated CAP IDs")
    cap_mark_consumed.add_argument("--plan", required=True, help="PLN-ID")
    cap_mark_consumed.add_argument("--json", action="store_true")

    # --- version ---
    ver = sub.add_parser("version")
    ver_sub = ver.add_subparsers(dest="subcommand")

    ver_get = ver_sub.add_parser("get")
    ver_check = ver_sub.add_parser("check")
    ver_bump = ver_sub.add_parser("bump")
    ver_bump.add_argument("level", choices=["patch", "minor", "major"])

    # --- context ---
    ctx = sub.add_parser("context")
    ctx_sub = ctx.add_subparsers(dest="subcommand")

    ctx_gather = ctx_sub.add_parser("gather")
    ctx_gather.add_argument("--diff", type=int, default=1)
    ctx_gather.add_argument("--skills", action="store_true", default=True)
    ctx_gather.add_argument("--no-skills", dest="skills", action="store_false")
    ctx_gather.add_argument("--agents", action="store_true", default=True)
    ctx_gather.add_argument("--no-agents", dest="agents", action="store_false")
    ctx_gather.add_argument("--format", choices=["text", "json"], default="text")

    # --- agents ---
    agt = sub.add_parser("agents")
    agt_sub = agt.add_subparsers(dest="subcommand")

    agt_check = agt_sub.add_parser("check")
    agt_sync = agt_sub.add_parser("sync")

    # --- cleanup ---
    cln = sub.add_parser("cleanup")
    cln.add_argument("--dry-run", action="store_true")

    # --- session ---
    sess = sub.add_parser("session")
    sess_sub = sess.add_subparsers(dest="subcommand")

    sess_list = sess_sub.add_parser("list")
    sess_list.add_argument("--type", choices=["ideation", "discussion", "debug"])

    sess_inspect = sess_sub.add_parser("inspect")
    sess_inspect.add_argument("session_id")

    sess_complete = sess_sub.add_parser("complete")
    sess_complete.add_argument("session_id")

    sess_split = sess_sub.add_parser("split-prompts", help="combined-prompts.txt를 개별 프롬프트 파일로 분리")
    sess_split.add_argument("--dir", dest="prompts_dir", required=False, help="prompts 디렉토리 경로")

    # --- priority ---
    pri = sub.add_parser("priority")
    pri.add_argument("task_id")
    pri.add_argument("--before")
    pri.add_argument("--after")

    # --- task ---
    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="subcommand")
    task_set_commit = task_sub.add_parser("set-commit")
    task_set_commit.add_argument("task_id")
    task_set_commit.add_argument("commit_hash", nargs="?")
    task_set_commit.add_argument("commit_message", nargs="?")

    # --- explore ---
    explore = sub.add_parser("explore")
    explore_sub = explore.add_subparsers(dest="subcommand")
    explore_index = explore_sub.add_parser("index", help="explore-report.md 파싱 후 index.json 생성")
    explore_index.add_argument("--report", required=True, help="입력 explore-report.md 경로")
    explore_index.add_argument("--output", help="출력 index.json 경로 (기본: report 파일과 동일 디렉토리)")

    # --- wait-files ---
    wf = sub.add_parser("wait-files")
    wf.add_argument("files", nargs="+", help="대기할 파일 경로 목록")
    wf.add_argument("--timeout", type=float, default=None,
                    help="타임아웃 (초). 미지정 시 config.json의 timeouts.wait_files_ms 사용")

    # --- resolve-model ---
    resolve_model = sub.add_parser("resolve-model")
    resolve_model.add_argument("provider")
    resolve_model.add_argument("tier_or_section")

    # --- stitch ---
    stitch = sub.add_parser("stitch")
    stitch_sub = stitch.add_subparsers(dest="subcommand")

    stitch_sleep = stitch_sub.add_parser("sleep")
    stitch_sleep.add_argument(
        "--interval", type=float, default=30.0,
        help="대기 시간(초). 기본값 30."
    )

    # --- notify ---
    notify_parser = sub.add_parser("notify")
    notify_parser.add_argument("event_type")
    notify_parser.add_argument("data", nargs="?", default=None)

    # --- extension ---
    ext = sub.add_parser("extension")
    ext_sub = ext.add_subparsers(dest="subcommand")
    ext_sub.add_parser("ensure-copy")

    # --- config ---
    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="subcommand")
    cfg_resolve = cfg_sub.add_parser("resolve", help="defaults + overrides → config.resolved.json")
    cfg_resolve.set_defaults(func=cmd_config_resolve)
    cfg_get = cfg_sub.add_parser("get", help="read config value by dot-path")
    cfg_get.add_argument("key_path")
    cfg_get.add_argument("--default", dest="default_value")
    cfg_get.add_argument("--json", action="store_true")
    cfg_migrate = cfg_sub.add_parser("migrate", help="구 포맷 config를 신 포맷으로 마이그레이션")
    cfg_migrate.add_argument("--apply", action="store_true", help="실제 적용 (기본: dry-run)")
    cfg_migrate.set_defaults(func=cmd_config_migrate)

    # --- preset ---
    preset = sub.add_parser("preset")
    preset_sub = preset.add_subparsers(dest="subcommand")
    preset_list = preset_sub.add_parser("list", help="built-in and user presets")
    preset_list.add_argument("--format", choices=["table", "json"], default="table")
    preset_apply = preset_sub.add_parser("apply", help="apply preset to config overrides")
    preset_apply.add_argument("preset_id")
    preset_diff = preset_sub.add_parser("diff", help="preview preset diff against current config")
    preset_diff.add_argument("preset_id")
    preset_save = preset_sub.add_parser("save", help="save current config as user preset")
    preset_save.add_argument("preset_id")

    # --- hooks ---
    hooks = sub.add_parser("hooks")
    hooks_sub = hooks.add_subparsers(dest="subcommand")
    hooks_post_skill = hooks_sub.add_parser("post-skill")
    hooks_post_skill.set_defaults(func=cmd_hooks_post_skill)

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global BASE_DIR
    BASE_DIR = find_base_dir()

    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        ("request", "list"): cmd_request_list,
        ("request", "inspect"): cmd_request_inspect,
        ("request", "history"): cmd_request_history,
        ("request", "filter"): cmd_request_filter,
        ("request", "count"): cmd_request_count,
        ("request", "cancel"): cmd_request_cancel,
        ("request", "set-phase"): cmd_request_set_phase,
        ("workflow", "run"): cmd_workflow_run,
        ("worktree", "create"): cmd_worktree_create,
        ("worktree", "remove"): cmd_worktree_remove,
        ("timestamp", "now"): cmd_timestamp,
        ("set-status", None): cmd_set_status,
        ("set-field", None): cmd_set_field,
        ("state", "set"): cmd_state_set,
        ("state", "set-workflow"): cmd_state_set_workflow,
        ("state", "get"): cmd_state_get,
        ("state", "clear"): cmd_state_clear,
        ("measure", "stop-rate"): cmd_measure_stop_rate,
        ("plan", "list"): cmd_plan_list,
        ("plan", "count"): cmd_plan_count,
        ("plan", "inspect"): cmd_plan_inspect,
        ("plan", "complete"): cmd_plan_complete,
        ("plan", "sync"): cmd_plan_sync,
        ("plan", "render-review"): cmd_plan_render_review,
        ("intent", "add"): cmd_intent_add,
        ("intent", "get"): cmd_intent_get,
        ("intent", "list"): cmd_intent_list,
        ("intent", "update"): cmd_intent_update,
        ("intent", "delete"): cmd_intent_delete,
        ("intent", "search"): cmd_intent_search,
        ("intent", "lookup"): cmd_intent_lookup,
        ("intent", "related"): cmd_intent_related,
        ("intent", "rebuild"): cmd_intent_rebuild,
        ("fact-check", "add"): cmd_fact_check_add,
        ("fact-check", "get"): cmd_fact_check_get,
        ("fact-check", "list"): cmd_fact_check_list,
        ("fact-check", "search"): cmd_fact_check_search,
        ("fact-check", "update"): cmd_fact_check_update,
        ("fact-check", "claim-update"): cmd_fact_check_claim_update,
        ("reference", "add"): cmd_reference_add,
        ("reference", "get"): cmd_reference_get,
        ("reference", "list"): cmd_reference_list,
        ("reference", "search"): cmd_reference_search,
        ("reference", "update"): cmd_reference_update,
        ("agile", "init"): cmd_agile_init,
        ("agile", "status"): cmd_agile_status,
        ("agile", "update"): cmd_agile_update,
        ("agile", "result"): cmd_agile_result,
        ("agile", "retrospective"): cmd_agile_retrospective,
        ("agile", "known-issues"): cmd_agile_known_issues,
        ("agile", "objective-transition"): cmd_agile_objective_transition,
        ("agile", "objective-check"): cmd_agile_objective_check,
        ("agile", "objective-snapshot"): cmd_agile_objective_snapshot,
        ("agile", "link"): cmd_agile_link,
        ("counter", "next"): cmd_counter_next,
        ("counter", "peek"): cmd_counter_peek,
        ("version", "get"):    cmd_version_get,
        ("version", "check"):  cmd_version_check,
        ("version", "bump"):   cmd_version_bump,
        ("context", "gather"): cmd_context_gather,
        ("agents", "check"):   cmd_agents_check,
        ("agents", "sync"):    cmd_agents_sync,
        ("capture", "ttl-check"): cmd_capture_ttl_check,
        ("capture", "mark-consumed"): cmd_capture_mark_consumed,
        ("archive", "run"): cmd_archive_run,
        ("archive", "run-all"): cmd_archive_run_all,
        ("archive", "list"): cmd_archive_list,
        ("archive", "restore"): cmd_archive_restore,
        ("gardening", "scan"): cmd_gardening_scan,
        ("cleanup", None): cmd_cleanup,
        ("session", "list"): cmd_session_list,
        ("session", "inspect"): cmd_session_inspect,
        ("session", "complete"): cmd_session_complete,
        ("session", "split-prompts"): cmd_session_split_prompts,
        ("priority", None): cmd_priority,
        ("task", "set-commit"): cmd_task_set_commit,
        ("explore", "index"): cmd_explore_index,
        ("notify", None): cmd_notify,
        ("stitch", "sleep"): cmd_stitch_sleep,
        ("wait-files", None): cmd_wait_files,
        ("resolve-model", None): cmd_resolve_model,
        ("extension", "ensure-copy"): cmd_extension_ensure_copy,
        ("config", "resolve"): cmd_config_resolve,
        ("config", "get"): cmd_config_get,
        ("config", "migrate"): cmd_config_migrate,
        ("preset", "list"): cmd_preset_list,
        ("preset", "apply"): cmd_preset_apply,
        ("preset", "diff"): cmd_preset_diff,
        ("preset", "save"): cmd_preset_save,
        ("hooks", "post-skill"): cmd_hooks_post_skill,
    }

    key = (args.command, getattr(args, "subcommand", None))
    fn = dispatch.get(key)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(fn(args) or 0)


if __name__ == "__main__":
    main()
