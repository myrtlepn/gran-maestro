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
    _fact_check_path,
    _iter_fact_check_paths,
    _normalize_fact_check_id,
    load_json,
    save_json,
)

def _normalize_claim_id(value: str) -> str:
    claim_id = (value or "").strip().upper()
    if not re.fullmatch(r"CL-\d+", claim_id):
        raise ValueError(f"Invalid claim id: {value}")
    return claim_id

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
        str(_common._mst_script_path()),
        "counter",
        "next",
        "--type",
        "fc",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_common.BASE_DIR.parent),
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


def register(subparsers):
    sub = subparsers
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
