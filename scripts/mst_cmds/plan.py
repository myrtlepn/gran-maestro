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
    iter_plan_dirs,
    load_json,
    plans_dir,
    requests_dir,
    save_json,
)

ADVERSARIAL_REVIEW_PERSPECTIVES = ("edge", "flow", "persona", "nfr", "integration")
ADVERSARIAL_REVIEW_OUTPUT_SCHEMA = {
    "findings": [
        {
            "type": "...",
            "description": "...",
            "suggested_dod": "...",
            "severity": "critical|major|minor",
        }
    ]
}


def _load_adversarial_review_config() -> dict:
    plugin_root = _common._plugin_root()
    defaults = load_json(plugin_root / "templates" / "defaults" / "config.json") or {}
    resolved = load_json(_common.BASE_DIR / "config.resolved.json") or {}
    overrides = load_json(_common.BASE_DIR / "config.json") or {}
    merged = _common.deep_merge(defaults, resolved)
    merged = _common.deep_merge(merged, overrides)
    agile_cfg = merged.get("agile") if isinstance(merged, dict) else {}
    review_cfg = agile_cfg.get("adversarial_review") if isinstance(agile_cfg, dict) else {}
    return review_cfg if isinstance(review_cfg, dict) else {}


def _validate_adversarial_review_enabled(perspective: str) -> int:
    review_cfg = _load_adversarial_review_config()
    if review_cfg.get("enabled", True) is False:
        print("adversarial_review is globally disabled", file=sys.stderr)
        return 2
    perspectives = review_cfg.get("perspectives")
    perspectives = perspectives if isinstance(perspectives, dict) else {}
    perspective_cfg = perspectives.get(perspective)
    perspective_cfg = perspective_cfg if isinstance(perspective_cfg, dict) else {}
    if perspective_cfg.get("enabled", True) is False:
        print(f"perspective '{perspective}' is disabled", file=sys.stderr)
        return 2
    return 0


def _adversarial_review_template_path(perspective: str) -> Path:
    return (
        _common._plugin_root()
        / "scripts"
        / "adversarial_review"
        / "perspectives"
        / f"{perspective}.md"
    ).resolve()


def _emit_adversarial_review_payload(context_files: List[Path], perspective: str) -> int:
    payload = {
        "context_files": [str(path.resolve()) for path in context_files],
        "role_template": str(_adversarial_review_template_path(perspective)),
        "output_schema": ADVERSARIAL_REVIEW_OUTPUT_SCHEMA,
        "perspective": perspective,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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
            from scripts._state_manager import complete
            complete(_common.BASE_DIR, pln_id)
            print(f"Completed: {pln_id}")
            return 0
    print(f"Error: {pln_id} not found.", file=sys.stderr)
    return 1

def cmd_plan_takeover(args):
    from scripts.mst_cmds.state import cmd_takeover_plan

    return cmd_takeover_plan(args)

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
    config = load_json(_common.BASE_DIR / "config.json") or {}
    plan_review = config.get("plan_review", {})
    roles_config = plan_review.get("roles", {})
    all_roles = ["architect", "devils_advocate", "completeness", "ux_reviewer"]
    active_roles = [
        r for r in all_roles
        if roles_config.get(r, {}).get("enabled", True)
    ]

    # 4. 템플릿 디렉토리 (PROJECT_ROOT/templates/plan-review/)
    # Path(__file__)을 기준으로 project_root 계산: scripts/mst.py → scripts/ → project_root
    # _common.BASE_DIR.parent는 워크트리에서 항상 메인 repo 루트를 가리키므로 사용 불가
    project_root = _common._project_root()
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


def cmd_plan_review(args):
    perspective = str(args.perspective).strip()
    enabled_status = _validate_adversarial_review_enabled(perspective)
    if enabled_status:
        return enabled_status

    plan_path = Path(args.plan_path).expanduser().resolve()
    if not plan_path.exists() or not plan_path.is_file():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        return 1

    return _emit_adversarial_review_payload([plan_path], perspective)


def register(subparsers):
    sub = subparsers
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

    plan_takeover = plan_sub.add_parser("takeover")
    plan_takeover.add_argument("--id", required=True)

    p_plan_sync = plan_sub.add_parser("sync", help="Plan 완료 여부 동기화")
    p_plan_sync.add_argument("plan_id", help="Plan ID (예: PLN-068)")

    plan_render_review = plan_sub.add_parser("render-review", help="plan-review 프롬프트 파일 생성")
    plan_render_review.add_argument("--pln", dest="pln_id", required=True)
    plan_render_review.add_argument("--plan-draft", dest="plan_draft", default="")
    plan_render_review.add_argument("--plan-draft-file", dest="plan_draft_file", default=None)
    plan_render_review.add_argument("--qa-summary", dest="qa_summary", default="")

    plan_review = plan_sub.add_parser("review")
    plan_review.add_argument("--plan-path", required=True)
    plan_review.add_argument("--perspective", required=True, choices=ADVERSARIAL_REVIEW_PERSPECTIVES)
    plan_review.add_argument("--json", action="store_true", required=True)
