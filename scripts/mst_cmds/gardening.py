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

GARDENING_REQ_TERMINAL_STATUSES = {"done", "completed", "accepted", "cancelled"}

GARDENING_PLAN_TERMINAL_STATUSES = {"done", "completed", "cancelled"}

GARDENING_DEFAULT_AUTO_ARCHIVE_LOG = ".gran-maestro/gardening/auto-archive.ndjson"

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


def _gardening_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _gardening_read_auto_archive_config():
    defaults = load_json(_common._plugin_root() / "templates" / "defaults" / "config.json")
    overrides = load_json(_common.BASE_DIR / "config.json")

    defaults_payload = defaults if isinstance(defaults, dict) else {}
    overrides_payload = overrides if isinstance(overrides, dict) else {}
    resolved = _common.deep_merge(defaults_payload, overrides_payload)

    gardening_cfg = resolved.get("gardening") if isinstance(resolved, dict) else {}
    if not isinstance(gardening_cfg, dict):
        return {}
    auto_archive_cfg = gardening_cfg.get("auto_archive")
    if not isinstance(auto_archive_cfg, dict):
        return {}
    return auto_archive_cfg


def _gardening_auto_archive_log_path(auto_archive_cfg):
    raw_path = auto_archive_cfg.get("log_file", GARDENING_DEFAULT_AUTO_ARCHIVE_LOG)
    candidate = Path(str(raw_path))
    if candidate.is_absolute():
        return candidate
    return _common.BASE_DIR.parent / candidate


def _gardening_append_ndjson(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False))
        handle.write("\n")


def _gardening_log_action(path: Path, *, action: str, item_id: str, prev_status, new_status, reason: str):
    _gardening_append_ndjson(
        path,
        {
            "timestamp": _gardening_now_iso(),
            "action": action,
            "id": item_id,
            "prev_status": prev_status,
            "new_status": new_status,
            "reason": reason,
        },
    )


def _gardening_read_ndjson(path: Path):
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def _gardening_atomic_write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _gardening_status_normalized(status) -> str:
    return str(status or "").strip().lower()


def _gardening_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "y", "on"}:
            return True
        if token in {"0", "false", "no", "n", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _gardening_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gardening_last_updated(data, json_path: Path):
    if isinstance(data, dict):
        for key in ("updated_at", "created_at"):
            parsed = _parse_utc_datetime(data.get(key))
            if parsed is not None:
                return parsed
    try:
        return datetime.fromtimestamp(json_path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)


def _gardening_elapsed_from(dt, now) -> int:
    delta = now - dt
    if delta < timedelta(0):
        return 0
    return delta.days


def _gardening_resolve_apply_mode(args, auto_archive_cfg) -> bool:
    if _gardening_bool(getattr(args, "dry_run", False), False):
        return False

    enabled = _gardening_bool(auto_archive_cfg.get("enabled"), False)
    if not enabled:
        return False

    if _gardening_bool(getattr(args, "apply", False), False):
        return True

    cfg_dry_run = _gardening_bool(auto_archive_cfg.get("dry_run"), True)
    return not cfg_dry_run


def _gardening_is_exempt(data) -> bool:
    if not isinstance(data, dict):
        return False
    return _gardening_bool(data.get("gardening_exempt"), False)


def _gardening_update_req_status_cache(request_status_map, req_id: str):
    if req_id in request_status_map:
        return request_status_map[req_id]

    req_data = load_json(requests_dir() / req_id / "request.json")
    if isinstance(req_data, dict):
        status = str(req_data.get("status", ""))
        request_status_map[req_id] = status
        return status

    request_status_map[req_id] = ""
    return ""


def cmd_gardening_auto_archive(args):
    auto_archive_cfg = _gardening_read_auto_archive_config()
    apply_mode = _gardening_resolve_apply_mode(args, auto_archive_cfg)
    silent = bool(getattr(args, "silent", False))
    now = datetime.now(timezone.utc)

    thresholds = auto_archive_cfg.get("thresholds")
    thresholds_cfg = thresholds if isinstance(thresholds, dict) else {}
    req_stale_days = _gardening_int(thresholds_cfg.get("req_stale_days"), 14)
    plan_stale_days = _gardening_int(thresholds_cfg.get("plan_stale_days"), 30)
    plan_active_stale_days = _gardening_int(
        thresholds_cfg.get("plan_active_stale_days"),
        plan_stale_days,
    )

    log_path = _gardening_auto_archive_log_path(auto_archive_cfg)

    dry_run_candidates = 0
    cancelled_items = 0
    skipped_items = 0
    cascaded_plans = 0
    request_status_map = {}
    exempt_plan_ids = set()

    for req_json_path in sorted(requests_dir().glob("REQ-*/request.json")):
        req_data = load_json(req_json_path)
        if not isinstance(req_data, dict):
            continue

        req_id = str(req_data.get("id") or req_json_path.parent.name)
        req_status = str(req_data.get("status", ""))
        request_status_map[req_id] = req_status
        normalized_status = _gardening_status_normalized(req_status)

        if normalized_status in GARDENING_REQ_TERMINAL_STATUSES:
            continue

        if _gardening_is_exempt(req_data):
            skipped_items += 1
            _gardening_log_action(
                log_path,
                action="skipped",
                item_id=req_id,
                prev_status=req_status,
                new_status=req_status,
                reason="gardening_exempt=true",
            )
            if not silent:
                print(f"[skip] {req_id}: gardening_exempt=true")
            continue

        elapsed_days = _gardening_elapsed_from(_gardening_last_updated(req_data, req_json_path), now)
        if elapsed_days < req_stale_days:
            continue

        reason = f"auto-gardening: stale {elapsed_days}d"
        if apply_mode:
            req_data["status"] = "cancelled"
            req_data["cancelled_at"] = _gardening_now_iso()
            req_data["cancelled_reason"] = reason
            _gardening_atomic_write_json(req_json_path, req_data)
            request_status_map[req_id] = "cancelled"
            cancelled_items += 1
            _gardening_log_action(
                log_path,
                action="cancel",
                item_id=req_id,
                prev_status=req_status,
                new_status="cancelled",
                reason=reason,
            )
            if not silent:
                print(f"[cancel] {req_id}: {req_status} -> cancelled ({reason})")
            continue

        dry_run_candidates += 1
        _gardening_log_action(
            log_path,
            action="dry_run_candidate",
            item_id=req_id,
            prev_status=req_status,
            new_status="cancelled",
            reason=reason,
        )
        if not silent:
            print(f"[candidate] {req_id}: {req_status} -> cancelled ({reason})")

    for plan_json_path in sorted(plans_dir().glob("PLN-*/plan.json")):
        plan_data = load_json(plan_json_path)
        if not isinstance(plan_data, dict):
            continue

        plan_id = str(plan_data.get("id") or plan_json_path.parent.name)
        plan_status = str(plan_data.get("status", ""))
        normalized_plan_status = _gardening_status_normalized(plan_status)

        if normalized_plan_status in GARDENING_PLAN_TERMINAL_STATUSES:
            continue

        if _gardening_is_exempt(plan_data):
            exempt_plan_ids.add(plan_id)
            skipped_items += 1
            _gardening_log_action(
                log_path,
                action="skipped",
                item_id=plan_id,
                prev_status=plan_status,
                new_status=plan_status,
                reason="gardening_exempt=true",
            )
            if not silent:
                print(f"[skip] {plan_id}: gardening_exempt=true")
            continue

        threshold_days = plan_stale_days
        if normalized_plan_status == "active":
            threshold_days = plan_active_stale_days
        elapsed_days = _gardening_elapsed_from(_gardening_last_updated(plan_data, plan_json_path), now)
        if elapsed_days < threshold_days:
            continue

        reason = f"auto-gardening: stale {elapsed_days}d"
        if apply_mode:
            plan_data["status"] = "cancelled"
            plan_data["cancelled_at"] = _gardening_now_iso()
            plan_data["cancelled_reason"] = reason
            _gardening_atomic_write_json(plan_json_path, plan_data)
            cancelled_items += 1
            _gardening_log_action(
                log_path,
                action="cancel",
                item_id=plan_id,
                prev_status=plan_status,
                new_status="cancelled",
                reason=reason,
            )
            if not silent:
                print(f"[cancel] {plan_id}: {plan_status} -> cancelled ({reason})")
            continue

        dry_run_candidates += 1
        _gardening_log_action(
            log_path,
            action="dry_run_candidate",
            item_id=plan_id,
            prev_status=plan_status,
            new_status="cancelled",
            reason=reason,
        )
        if not silent:
            print(f"[candidate] {plan_id}: {plan_status} -> cancelled ({reason})")

    if apply_mode:
        for plan_json_path in sorted(plans_dir().glob("PLN-*/plan.json")):
            plan_data = load_json(plan_json_path)
            if not isinstance(plan_data, dict):
                continue

            plan_id = str(plan_data.get("id") or plan_json_path.parent.name)
            if plan_id in exempt_plan_ids:
                continue

            plan_status = str(plan_data.get("status", ""))
            normalized_plan_status = _gardening_status_normalized(plan_status)
            if normalized_plan_status in GARDENING_PLAN_TERMINAL_STATUSES:
                continue

            linked = plan_data.get("linked_requests")
            linked_requests = linked if isinstance(linked, list) else []
            if not linked_requests:
                continue

            all_terminal = True
            all_cancelled = True
            for req_id_raw in linked_requests:
                req_id = str(req_id_raw)
                req_status = _gardening_update_req_status_cache(request_status_map, req_id)
                req_status_normalized = _gardening_status_normalized(req_status)
                if req_status_normalized not in GARDENING_REQ_TERMINAL_STATUSES:
                    all_terminal = False
                    break
                if req_status_normalized != "cancelled":
                    all_cancelled = False

            if not all_terminal:
                continue

            new_status = "cancelled" if all_cancelled else "completed"
            if normalized_plan_status == new_status:
                continue

            reason = "auto-gardening: linked_requests terminal"
            prev_status = plan_status
            plan_data["status"] = new_status
            if new_status == "cancelled":
                plan_data["cancelled_at"] = _gardening_now_iso()
                plan_data["cancelled_reason"] = reason
            else:
                plan_data["completed_at"] = _gardening_now_iso()
            _gardening_atomic_write_json(plan_json_path, plan_data)
            cascaded_plans += 1

            _gardening_log_action(
                log_path,
                action="plan_cascade",
                item_id=plan_id,
                prev_status=prev_status,
                new_status=new_status,
                reason=reason,
            )
            if not silent:
                print(f"[plan_cascade] {plan_id}: {prev_status} -> {new_status}")

    if not silent:
        mode = "apply" if apply_mode else "dry-run"
        print(
            f"auto-archive {mode}: "
            f"candidates={dry_run_candidates}, "
            f"cancelled={cancelled_items}, "
            f"skipped={skipped_items}, "
            f"plan_cascade={cascaded_plans}"
        )
    return 0


def _gardening_restore_target_path(target_id: str):
    normalized = str(target_id or "").upper().strip()
    if normalized.startswith("REQ-"):
        return normalized, requests_dir() / normalized / "request.json"
    if normalized.startswith("PLN-"):
        return normalized, plans_dir() / normalized / "plan.json"
    return normalized, None


def cmd_gardening_restore(args):
    target_id, target_path = _gardening_restore_target_path(getattr(args, "target_id", ""))
    if target_path is None:
        print("Error: --id must start with REQ- or PLN-", file=sys.stderr)
        return 1
    if not target_path.exists():
        print(f"Error: target not found: {target_id}", file=sys.stderr)
        return 1

    auto_archive_cfg = _gardening_read_auto_archive_config()
    log_path = _gardening_auto_archive_log_path(auto_archive_cfg)
    if not log_path.exists():
        print("Error: auto-archive log not found.", file=sys.stderr)
        return 1

    restore_source = None
    for row in reversed(_gardening_read_ndjson(log_path)):
        if str(row.get("id", "")).upper() != target_id:
            continue
        if row.get("action") in {"cancel", "plan_cascade"}:
            restore_source = row
            break

    if restore_source is None:
        print(f"Error: restore source not found for {target_id}", file=sys.stderr)
        return 1

    prev_status = restore_source.get("prev_status")
    if not isinstance(prev_status, str) or not prev_status.strip():
        print(f"Error: invalid prev_status in log for {target_id}", file=sys.stderr)
        return 1

    target_data = load_json(target_path)
    if not isinstance(target_data, dict):
        print(f"Error: failed to parse target json: {target_path}", file=sys.stderr)
        return 1

    current_status = str(target_data.get("status", ""))
    target_data["status"] = prev_status
    target_data["restored_at"] = _gardening_now_iso()
    _gardening_atomic_write_json(target_path, target_data)

    _gardening_log_action(
        log_path,
        action="restore",
        item_id=target_id,
        prev_status=current_status,
        new_status=prev_status,
        reason=f"restore from {restore_source.get('action')}",
    )
    print(f"restored {target_id}: {current_status} -> {prev_status}")
    return 0


def register(subparsers):
    sub = subparsers
    gardening = sub.add_parser("gardening")
    gardening_sub = gardening.add_subparsers(dest="subcommand")
    gardening_scan = gardening_sub.add_parser("scan")
    gardening_scan.add_argument("--json", action="store_true")
    gardening_scan.set_defaults(func=cmd_gardening_scan)
    auto_archive = gardening_sub.add_parser("auto-archive")
    auto_archive.add_argument("--apply", action="store_true")
    auto_archive.add_argument("--dry-run", action="store_true")
    auto_archive.add_argument("--silent", action="store_true")
    auto_archive.set_defaults(func=cmd_gardening_auto_archive)
    restore = gardening_sub.add_parser("restore")
    restore.add_argument("--id", dest="target_id", required=True)
    restore.set_defaults(func=cmd_gardening_restore)
