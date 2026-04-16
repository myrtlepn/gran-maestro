from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds._common import (
    TYPE_DIRS,
    _agi_events_path,
    _agi_links_path,
    _agi_objective_changelog_path,
    _agi_objective_path,
    _agi_session_dir,
    _agi_session_path,
    _append_agile_event,
    _load_agile_session,
    _normalize_agi_id,
    _normalize_link_id,
    _now_iso,
    _plugin_root,
    _save_agile_session,
    _split_csv_values,
    get_counter_path,
    load_json,
    save_json,
)

def _normalize_known_issue_id(value: str) -> str:
    issue_id = (value or "").strip().upper()
    if not re.fullmatch(r"KI-\d+", issue_id):
        raise ValueError(f"Invalid known issue id: {value}")
    return issue_id

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

def _next_agile_id() -> str:
    counter_path = get_counter_path("agi")
    scan_root = _common.BASE_DIR / TYPE_DIRS["agi"][0]
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
        new_status = str(args.status)
        current_status = session.get("status")
        auto_mode = bool(session.get("auto_mode", False))
        if current_status == "active" and new_status == "paused" and auto_mode:
            authorized = (
                os.environ.get("MST_AGILE_PAUSE_AUTHORIZED") == "1"
                or getattr(args, "user_requested", False)
            )
            if not authorized:
                print(
                    "Error: 자발 정지 시도 차단 — AUTO_MODE sprint loop가 active인 상태에서 "
                    "권한 플래그 없이 paused로 전환할 수 없습니다. "
                    "사용자 직접 요청인 경우 --user-requested 또는 "
                    "MST_AGILE_PAUSE_AUTHORIZED=1 환경변수를 설정하세요.",
                    file=sys.stderr,
                )
                return 1
        session["status"] = new_status
        changed_fields["status"] = new_status
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
        "sprint_kind": str(args.sprint_kind or "user_observable"),
        "user_observable_change": None,
        "foundational_reason": None,
    }
    if payload["sprint_kind"] == "foundational":
        if args.foundational_reason is not None:
            payload["foundational_reason"] = str(args.foundational_reason)
    else:
        if args.user_observable_change is not None:
            payload["user_observable_change"] = str(args.user_observable_change)
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


def register(subparsers):
    sub = subparsers
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
    agile_update.add_argument("--user-requested", action="store_true",
        help="사용자가 직접 요청한 pause 전환임을 표시 (LLM 자발 정지 방지 게이트 우회)")
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
    agile_result.add_argument(
        "--sprint-kind",
        choices=["user_observable", "foundational"],
        default="user_observable",
    )
    agile_result.add_argument("--user-observable-change", dest="user_observable_change")
    agile_result.add_argument("--foundational-reason", dest="foundational_reason")
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

    agile_detail = agile_sub.add_parser("detail")
    agile_detail_sub = agile_detail.add_subparsers(dest="detail_subcommand")

    agile_detail_validate_mapping = agile_detail_sub.add_parser("validate-mapping")
    agile_detail_validate_mapping.add_argument("details_path")
    agile_detail_validate_mapping.add_argument("--json", action="store_true")

    agile_detail_validate_evidence = agile_detail_sub.add_parser("validate-evidence")
    agile_detail_validate_evidence.add_argument("details_path")
    agile_detail_validate_evidence.add_argument("--json", action="store_true")

    agile_detail_append = agile_detail_sub.add_parser("append")
    agile_detail_append.add_argument("--domain", required=True)
    agile_detail_append.add_argument("--chunk-id", type=int, required=True, dest="chunk_id")
    agile_detail_append.add_argument("--content-file", required=True, dest="content_file")
    agile_detail_append.add_argument("--target-dir", default=".", dest="target_dir")
    agile_detail_append.add_argument("--json", action="store_true")

    agile_evidence_check = agile_sub.add_parser("evidence-check")
    agile_evidence_check_scope = agile_evidence_check.add_mutually_exclusive_group(required=True)
    agile_evidence_check_scope.add_argument("--sprint")
    agile_evidence_check_scope.add_argument("--details-dir", dest="details_dir")
    agile_evidence_check.add_argument("--agi-id", dest="agi_id")
    agile_evidence_check.add_argument("--accept-evidence-gap", dest="accept_evidence_gap")
    agile_evidence_check.add_argument("--json", action="store_true")

    agile_drift_check = agile_sub.add_parser("drift-check")
    agile_drift_check_scope = agile_drift_check.add_mutually_exclusive_group(required=True)
    agile_drift_check_scope.add_argument("--sprint")
    agile_drift_check_scope.add_argument("--details-dir", dest="details_dir")
    agile_drift_check.add_argument("--agi-id", dest="agi_id")
    agile_drift_check.add_argument("--json", action="store_true")

    agile_recall = agile_sub.add_parser("recall")
    agile_recall.add_argument("--agi-id", dest="agi_id")
    agile_recall.add_argument("--level", type=int, default=2)
    agile_recall.add_argument("--reason", required=True, choices=["fail", "drift"])
    agile_recall.add_argument("--trigger", default="")
    agile_recall.add_argument("--approval-ticket", dest="approval_ticket")
    agile_recall.add_argument("--bypass-cooldown", action="store_true", dest="bypass_cooldown")
    agile_recall.add_argument("--fingerprint")
    agile_recall.add_argument("--json", action="store_true")

    agile_classify_change = agile_sub.add_parser("classify-change")
    agile_classify_change.add_argument("manifest")

    agile_unlock = agile_sub.add_parser("unlock")
    agile_unlock.add_argument("--dod", required=True)
    agile_unlock.add_argument(
        "--category",
        required=True,
        choices=[
            "upstream_evidence_changed",
            "integration_regression",
            "new_dependency_dod",
            "objective_precision_fix",
        ],
    )
    agile_unlock.add_argument("--reason")
    agile_unlock.add_argument("--evidence")
    agile_unlock.add_argument("--agi-id", dest="agi_id")
    agile_unlock.add_argument("--json", action="store_true")

    agile_revalidate_done = agile_sub.add_parser("revalidate-done")
    agile_revalidate_done.add_argument("dod")
    agile_revalidate_done.add_argument("--agi-id", dest="agi_id")
    agile_revalidate_done.add_argument("--json", action="store_true")

    agile_coverage_check = agile_sub.add_parser("coverage-check")
    agile_coverage_check.add_argument("original_path")
    agile_coverage_check.add_argument("--details-dir", required=True, dest="details_dir")
    agile_coverage_check.add_argument("--threshold", type=float)
    agile_coverage_check.add_argument("--json", action="store_true")

    agile_objective_transition = agile_sub.add_parser("objective-transition")
    agile_objective_transition.add_argument("agi_id")
    agile_objective_transition.add_argument("--story", required=True)
    agile_objective_transition.add_argument("--status", required=True)
    agile_objective_transition.add_argument("--deferred-promote", action="store_true")
    agile_objective_transition.add_argument("--sprint", type=int)
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

    agile_integration_review = agile_sub.add_parser("integration-review")
    agile_integration_review.add_argument("agi_id")
    agile_integration_review.add_argument("--sprint", type=int, required=True)
    agile_integration_review.add_argument("--depth", type=int, default=None)
    agile_integration_review.add_argument("--threshold", type=float, default=None)
    agile_integration_review.add_argument("--escape-reason", default=None)
    agile_integration_review.add_argument("--reference-pattern", default=None)
    agile_integration_review.add_argument("--json", action="store_true")

    agile_alignment_package = agile_sub.add_parser("alignment-package")
    agile_alignment_package.add_argument("agi_id")
    agile_alignment_package.add_argument("--sprint", type=int, required=True)
    agile_alignment_package.add_argument("--depth", type=int, default=3)
    agile_alignment_package.add_argument("--json", action="store_true")

    agile_stop_audit = agile_sub.add_parser("stop-audit")
    agile_stop_audit_sub = agile_stop_audit.add_subparsers(dest="stop_audit_subcommand")
    agile_stop_audit_list = agile_stop_audit_sub.add_parser("list")
    agile_stop_audit_list.add_argument("--agi", required=True)
    agile_stop_audit_list.add_argument("--classification", choices=["blocked", "allowed", "pass_through"])
    agile_stop_audit_list.add_argument("--json", action="store_true")
    agile_stop_audit_aggregate = agile_stop_audit_sub.add_parser("aggregate")
    agile_stop_audit_aggregate.add_argument("--agi", required=True)
    agile_stop_audit_aggregate.add_argument(
        "--group-by",
        required=True,
        choices=["declared_reason", "classification"],
    )
