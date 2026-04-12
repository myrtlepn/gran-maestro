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
    _create_intent_store,
    _parse_utc_datetime,
    iter_plan_dirs,
    iter_request_dirs,
    load_json,
    plans_dir,
    requests_dir,
)

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


def register(subparsers):
    sub = subparsers
    gardening = sub.add_parser("gardening")
    gardening_sub = gardening.add_subparsers(dest="subcommand")
    gardening_scan = gardening_sub.add_parser("scan")
    gardening_scan.add_argument("--json", action="store_true")
