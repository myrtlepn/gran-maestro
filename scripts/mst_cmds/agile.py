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
from typing import Any, List, Optional
from scripts.mst_cmds import _common
from scripts.mst_cmds import cleanup as cleanup_mod
from scripts.mst_cmds.agile_governance import (
    _generate_drift_report_skeleton,
    _generate_recall_patch_manifest_skeleton,
)
from scripts.mst_cmds.state import _resolve_owner_ppid, _resolve_owner_session_id
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
    plugin_root = _plugin_root()
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
        _plugin_root()
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
        if raw_value is None:
            continue
        if not isinstance(raw_value, str):
            raise ValueError(
                f"invalid --failed JSON: expected string, got {type(raw_value).__name__}"
            )
        if not raw_value.strip():
            continue
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

def _run_sprint_close_git(project_root: Path, git_args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *git_args],
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )

def _sprint_close_error_text(result: subprocess.CompletedProcess, fallback: str) -> str:
    return result.stderr.strip() or result.stdout.strip() or fallback

def _resolve_sprint_close_base(explicit_base: Optional[str]) -> str:
    base = str(explicit_base or "").strip()
    if base:
        return base

    for config_name in ("config.resolved.json", "config.json"):
        data = load_json(_common.BASE_DIR / config_name) or {}
        worktree_config = data.get("worktree") if isinstance(data, dict) else None
        configured = worktree_config.get("base_branch") if isinstance(worktree_config, dict) else None
        configured = str(configured or "").strip()
        if configured:
            return configured
    return "master"

def _validate_sprint_close_base(project_root: Path, base: str) -> Optional[str]:
    result = _run_sprint_close_git(project_root, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    if result.returncode != 0:
        return _sprint_close_error_text(result, f"base branch not found: {base}")
    return None

def _branch_exists(project_root: Path, branch: Optional[str]) -> bool:
    if not branch:
        return False
    result = _run_sprint_close_git(
        project_root,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
    )
    return result.returncode == 0

def _list_sprint_close_branches(project_root: Path, pattern: str) -> List[str]:
    result = _run_sprint_close_git(project_root, ["branch", "--list", pattern])
    if result.returncode != 0:
        raise RuntimeError(_sprint_close_error_text(result, "git branch --list failed"))
    branches = []
    for line in result.stdout.splitlines():
        branch = line.strip()
        if branch.startswith(("* ", "+ ")):
            branch = branch[2:].strip()
        if branch:
            branches.append(branch)
    return branches

def _detect_sprint_close_branch(project_root: Path, agi_id: str, sprint: int) -> Optional[str]:
    patterns = [
        f"gran-maestro/{agi_id}/sprint-{sprint}*",
        f"gran-maestro/*{agi_id}*sprint*{sprint}*",
        f"gran-maestro/*/{agi_id}-sprint-{sprint}*",
    ]
    candidates = []
    seen = set()
    for pattern in patterns:
        for branch in _list_sprint_close_branches(project_root, pattern):
            if branch not in seen:
                seen.add(branch)
                candidates.append(branch)

    if not candidates:
        return None
    if len(candidates) > 1:
        joined = ", ".join(sorted(candidates))
        raise RuntimeError(f"multiple sprint branches matched; pass --branch explicitly: {joined}")
    return candidates[0]

def _default_sprint_worktree_path(project_root: Path, agi_id: str, sprint: int) -> Path:
    return _common.worktrees_dir(project_root) / agi_id / f"sprint-{sprint}"

def _detect_sprint_worktree_path(
    project_root: Path,
    agi_id: str,
    sprint: int,
    explicit_path: Optional[str],
) -> Optional[Path]:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve(strict=False)
    candidate = _default_sprint_worktree_path(project_root, agi_id, sprint)
    if candidate.exists():
        return candidate.resolve(strict=False)
    return None

def _git_rev_parse(project_root: Path, rev: str) -> str:
    result = _run_sprint_close_git(project_root, ["rev-parse", rev])
    if result.returncode != 0:
        raise RuntimeError(_sprint_close_error_text(result, f"git rev-parse failed: {rev}"))
    return result.stdout.strip()

def _find_existing_sprint_squash_commit(
    project_root: Path,
    base: str,
    agi_id: str,
    sprint: int,
    branch_tree: str,
) -> tuple[Optional[str], Optional[str]]:
    marker = f"[{agi_id} Sprint {sprint}] squash-merged:"
    result = _run_sprint_close_git(project_root, ["log", "--format=%H%x00%T%x00%s", base])
    if result.returncode != 0:
        raise RuntimeError(_sprint_close_error_text(result, "git log failed"))

    matching_tree_sha = None
    for line in result.stdout.splitlines():
        parts = line.split("\0", 2)
        if len(parts) != 3:
            continue
        sha, tree, subject = parts
        if marker in subject:
            if tree != branch_tree:
                return None, f"tree mismatch: {branch_tree} != {tree} ({sha})"
            return sha, None
        if tree == branch_tree and matching_tree_sha is None:
            matching_tree_sha = sha
    return matching_tree_sha, None

def _current_git_branch(project_root: Path) -> Optional[str]:
    result = _run_sprint_close_git(project_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None

def _sprint_close_role_worktree_path(project_root: Path, agi_id: str, sprint: int) -> Path:
    return _common.worktrees_dir(project_root) / agi_id / f"sprint-{sprint}-close"


def _create_sprint_close_role_worktree(project_root: Path, path: Path, base: str) -> Optional[str]:
    if path.exists():
        return f"sprint-close role worktree already exists: {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _run_sprint_close_git(project_root, ["worktree", "add", "--detach", str(path), base])
    if result.returncode != 0:
        return _sprint_close_error_text(result, "git worktree add --detach failed")
    return None


def _remove_sprint_close_role_worktree(project_root: Path, path: Path) -> Optional[str]:
    result = _run_sprint_close_git(project_root, ["worktree", "remove", "--force", str(path)])
    if result.returncode != 0:
        return _sprint_close_error_text(result, "git worktree remove failed")
    return None


def _abort_sprint_close_merge(worktree_path: Path) -> None:
    _run_sprint_close_git(worktree_path, ["merge", "--abort"])


def _update_sprint_close_base_ref(project_root: Path, base: str, new_sha: str, old_sha: str) -> Optional[str]:
    result = _run_sprint_close_git(project_root, ["update-ref", f"refs/heads/{base}", new_sha, old_sha])
    if result.returncode != 0:
        return _sprint_close_error_text(result, "git update-ref failed")
    return None


def _current_sprint_close_worktree_is_clean(project_root: Path, base: str) -> bool:
    if _current_git_branch(project_root) != base:
        return False
    status = _run_sprint_close_git(project_root, ["status", "--porcelain"])
    return status.returncode == 0 and not status.stdout.strip()


def _refresh_current_sprint_close_worktree(project_root: Path, new_sha: str) -> Optional[str]:
    result = _run_sprint_close_git(project_root, ["reset", "--hard", new_sha])
    if result.returncode != 0:
        return _sprint_close_error_text(result, "git reset --hard failed")
    return None


def _perform_sprint_close_squash_merge(
    worktree_path: Path,
    branch: str,
    message: str,
) -> str:
    merge_result = _run_sprint_close_git(worktree_path, ["merge", "--squash", branch])
    if merge_result.returncode != 0:
        _abort_sprint_close_merge(worktree_path)
        raise RuntimeError(_sprint_close_error_text(merge_result, "git merge --squash failed"))

    commit_result = _run_sprint_close_git(worktree_path, ["commit", "-m", message])
    if commit_result.returncode != 0:
        _abort_sprint_close_merge(worktree_path)
        raise RuntimeError(_sprint_close_error_text(commit_result, "git commit failed"))
    return _git_rev_parse(worktree_path, "HEAD")

def _append_sprint_close_log(agi_id: str, record: dict) -> None:
    log_path = _common.BASE_DIR / "agile" / agi_id / "sprint-log.json"
    existing = load_json(log_path)
    entries = existing if isinstance(existing, list) else []
    entries.append(record)
    save_json(log_path, entries)

def _print_sprint_close_result(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    status = payload.get("status")
    print(f"sprint-close status: {status}")
    print(f"agi_id: {payload.get('agi_id')}")
    print(f"sprint: {payload.get('sprint')}")
    print(f"base: {payload.get('base')}")
    if payload.get("branch"):
        print(f"branch: {payload.get('branch')}")
    if payload.get("worktree_path"):
        print(f"worktree_path: {payload.get('worktree_path')}")
    if payload.get("squash_commit_sha"):
        print(f"squash_commit_sha: {payload.get('squash_commit_sha')}")
    actions = payload.get("actions")
    if actions:
        print("actions:")
        for action in actions:
            print(f"- {action}")

def cmd_agile_sprint_close(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sprint = int(args.sprint)
    if sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    project_root = Path(_common.BASE_DIR).parent.resolve(strict=False)
    base = _resolve_sprint_close_base(args.base)
    dry_run = bool(getattr(args, "dry_run", False))
    actions = []
    warnings = []

    payload = {
        "agi_id": agi_id,
        "sprint": sprint,
        "base": base,
        "branch": None,
        "worktree_path": None,
        "dry_run": dry_run,
        "actions": actions,
        "branch_deleted": False,
        "worktree_removed": False,
        "squash_commit_sha": None,
        "status": None,
        "warnings": warnings,
    }

    base_error = _validate_sprint_close_base(project_root, base)
    if base_error:
        print(f"Error: {base_error}", file=sys.stderr)
        payload["status"] = "partial"
        _print_sprint_close_result(payload, args.json)
        return 1

    try:
        branch = str(args.branch).strip() if args.branch else _detect_sprint_close_branch(project_root, agi_id, sprint)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        payload["status"] = "partial"
        _print_sprint_close_result(payload, args.json)
        return 1

    worktree_path = _detect_sprint_worktree_path(project_root, agi_id, sprint, args.worktree_path)
    branch_exists = _branch_exists(project_root, branch)
    worktree_exists = bool(worktree_path and worktree_path.exists())
    payload["branch"] = branch
    payload["worktree_path"] = str(worktree_path) if worktree_path else None
    payload["branch_exists"] = branch_exists
    payload["worktree_exists"] = worktree_exists

    if branch_exists:
        actions.append(f"prepare sprint-close role worktree from {base}")
        branch_tree = _git_rev_parse(project_root, f"{branch}^{{tree}}")
        try:
            existing_sha, tree_error = _find_existing_sprint_squash_commit(
                project_root,
                base,
                agi_id,
                sprint,
                branch_tree,
            )
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            payload["status"] = "partial"
            _print_sprint_close_result(payload, args.json)
            return 1

        if tree_error:
            payload["status"] = "aborted_tree_mismatch"
            print(f"Error: {tree_error}", file=sys.stderr)
            if not dry_run:
                _append_sprint_close_log(
                    agi_id,
                    {
                        "sprint": sprint,
                        "closed_at": _now_iso(),
                        "branch_deleted": False,
                        "worktree_removed": False,
                        "squash_commit_sha": None,
                        "status": "aborted_tree_mismatch",
                    },
                )
            _print_sprint_close_result(payload, args.json)
            return 1

        if existing_sha:
            payload["squash_commit_sha"] = existing_sha
            actions.append(f"skip squash merge; tree already present in {base} ({existing_sha})")
        else:
            message = (
                str(args.message)
                if args.message is not None
                else f"[{agi_id} Sprint {sprint}] squash-merged: (자동 생성)"
            )
            actions.append(f"git merge --squash {branch} in sprint-close role worktree")
            actions.append("git commit squash merge in sprint-close role worktree")
            if not dry_run:
                close_worktree_path = _sprint_close_role_worktree_path(project_root, agi_id, sprint)
                refresh_current_root = _current_sprint_close_worktree_is_clean(project_root, base)
                create_error = _create_sprint_close_role_worktree(project_root, close_worktree_path, base)
                if create_error:
                    print(f"Error: {create_error}", file=sys.stderr)
                    payload["status"] = "partial"
                    _print_sprint_close_result(payload, args.json)
                    return 1
                try:
                    old_base_sha = _git_rev_parse(project_root, f"{base}^{{commit}}")
                    squash_sha = _perform_sprint_close_squash_merge(
                        close_worktree_path,
                        branch,
                        message,
                    )
                    update_error = _update_sprint_close_base_ref(project_root, base, squash_sha, old_base_sha)
                    if update_error:
                        raise RuntimeError(update_error)
                    if refresh_current_root:
                        refresh_error = _refresh_current_sprint_close_worktree(project_root, squash_sha)
                        if refresh_error:
                            warnings.append(refresh_error)
                            print(f"Warning: {refresh_error}", file=sys.stderr)
                    payload["squash_commit_sha"] = squash_sha
                except RuntimeError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    payload["status"] = "partial"
                    _append_sprint_close_log(
                        agi_id,
                        {
                            "sprint": sprint,
                            "closed_at": _now_iso(),
                            "branch_deleted": False,
                            "worktree_removed": False,
                            "squash_commit_sha": None,
                            "status": "partial",
                        },
                    )
                    _print_sprint_close_result(payload, args.json)
                    return 1
                finally:
                    remove_error = _remove_sprint_close_role_worktree(project_root, close_worktree_path)
                    if remove_error:
                        warnings.append(remove_error)
                        print(f"Warning: {remove_error}", file=sys.stderr)
    elif branch:
        actions.append(f"skip missing branch {branch}")

    if worktree_exists:
        actions.append(f"remove worktree {worktree_path}")
    if branch_exists:
        actions.append(f"delete branch {branch}")

    if dry_run:
        payload["status"] = "dry_run"
        _print_sprint_close_result(payload, args.json)
        return 0

    partial_failure = False
    if worktree_exists and worktree_path is not None:
        remove_result = subprocess.run(
            [
                sys.executable,
                str(_common._mst_script_path()),
                "worktree",
                "remove",
                "--path",
                str(worktree_path),
                "--force",
            ],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        if remove_result.returncode != 0:
            partial_failure = True
            warning = _sprint_close_error_text(remove_result, "worktree remove failed")
            warnings.append(warning)
            print(f"Warning: {warning}", file=sys.stderr)
        else:
            payload["worktree_removed"] = True

    if branch_exists and branch:
        delete_result = _run_sprint_close_git(project_root, ["branch", "-D", branch])
        if delete_result.returncode != 0:
            partial_failure = True
            warning = _sprint_close_error_text(delete_result, "git branch -D failed")
            warnings.append(warning)
            print(f"Warning: {warning}", file=sys.stderr)
        else:
            payload["branch_deleted"] = True

    if partial_failure:
        payload["status"] = "partial"
    elif not branch_exists and not worktree_exists:
        payload["status"] = "already_closed"
    else:
        payload["status"] = "closed"

    _append_sprint_close_log(
        agi_id,
        {
            "sprint": sprint,
            "closed_at": _now_iso(),
            "branch_deleted": bool(payload["branch_deleted"]),
            "worktree_removed": bool(payload["worktree_removed"]),
            "squash_commit_sha": payload["squash_commit_sha"],
            "status": payload["status"],
        },
    )
    _print_sprint_close_result(payload, args.json)
    return 1 if partial_failure else 0

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
    owner_ppid = _resolve_owner_ppid()
    owner_session_id = _resolve_owner_session_id(owner_ppid)
    payload = {
        "id": agi_id,
        "agi_id": agi_id,
        "status": "active",
        "current_sprint": 0,
        "steering_every": args.steering_every,
        "owner_ppid": owner_ppid,
        "owner_session_id": owner_session_id,
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

def cmd_agile_takeover(args):
    from scripts.mst_cmds.state import cmd_takeover_agile

    return cmd_takeover_agile(args)

def cmd_agile_update(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    changed_fields = {}
    completion_forced_payload = None
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
        if new_status == "completed":
            pending_reqs = []
            seen_req_ids = set()
            sprints_dir = _common.BASE_DIR / "agile" / agi_id / "sprints"
            for result_path in sorted(sprints_dir.glob("S*/result.json")):
                result_data = load_json(result_path) or {}
                req_id = result_data.get("req_id") if isinstance(result_data, dict) else None
                if not req_id or req_id in seen_req_ids:
                    continue
                seen_req_ids.add(req_id)
                request_data = load_json(_common.BASE_DIR / "requests" / req_id / "request.json") or {}
                status = str(request_data.get("status", "")).lower() if isinstance(request_data, dict) else ""
                if status not in {"done", "completed", "accepted"}:
                    pending_reqs.append(req_id)

            active_worktrees = []
            worktrees_dir = _common.BASE_DIR / "worktrees"
            for meta_path in sorted(worktrees_dir.glob("*.meta.json")):
                meta_data = load_json(meta_path) or {}
                if not isinstance(meta_data, dict) or meta_data.get("state") == "cleaned":
                    continue
                raw_path = meta_data.get("path")
                if not raw_path:
                    continue
                worktree_path = Path(str(raw_path)).expanduser()
                if not worktree_path.is_absolute():
                    worktree_path = (_common.BASE_DIR.parent / worktree_path).resolve(strict=False)
                worktree_text = str(worktree_path)
                agi_match = meta_data.get("agi_id") == agi_id
                try:
                    relative_text = str(worktree_path.relative_to(_common.BASE_DIR))
                except ValueError:
                    relative_text = ""
                path_match = relative_text.startswith(f"worktrees/{agi_id}/sprint-")
                if agi_match or path_match:
                    active_worktrees.append(worktree_text)

            if getattr(args, "force", False):
                completion_forced_payload = {
                    "pending_reqs": pending_reqs,
                    "active_worktrees": active_worktrees,
                }
            elif pending_reqs or active_worktrees:
                _append_agile_event(
                    agi_id,
                    "agile.update.blocked",
                    {
                        "pending_reqs": pending_reqs,
                        "active_worktrees": active_worktrees,
                    },
                )
                print(
                    "[agile update] blocked: "
                    f"pending_reqs={json.dumps(pending_reqs, ensure_ascii=False)} "
                    f"active_worktrees={json.dumps(active_worktrees, ensure_ascii=False)}",
                    file=sys.stderr,
                )
                return 2
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
    if completion_forced_payload is not None:
        _append_agile_event(agi_id, "agile.update.forced", completion_forced_payload)
    _append_agile_event(agi_id, "agile.update", {"fields": changed_fields})

    if args.json:
        print(json.dumps(saved, ensure_ascii=False, indent=2))
    else:
        print(agi_id)
    return 0


FINALIZE_ACCEPTED_STATUSES = {"done", "completed", "accepted"}
STALE_LOCK_SECONDS = 3600
ZERO_HASH = "0" * 64


def _diagnostic_payload(category: str, next_action: str, lock_path: Path, **fields: Any) -> dict:
    payload = {
        "category": category,
        "next_action": next_action,
        "lock_path": str(lock_path),
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return payload


def _diagnostic_base_dir(project_root: Path | str | None = None, base_dir: Path | str | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve(strict=False)
    if project_root is not None:
        return Path(project_root).expanduser().resolve(strict=False) / ".gran-maestro"
    if _common.BASE_DIR is not None:
        return Path(_common.BASE_DIR).resolve(strict=False)
    return Path.cwd().resolve(strict=False) / ".gran-maestro"


def _diagnostic_project_root(project_root: Path | str | None = None, base_dir: Path | str | None = None) -> Path:
    if project_root is not None:
        return Path(project_root).expanduser().resolve(strict=False)
    return _diagnostic_base_dir(base_dir=base_dir).parent


def _read_text_stripped(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _history_ledger_status_readonly(
    project_root: Path,
    home: Path,
    session_id: str,
    policy_home: Path | None = None,
) -> dict:
    session_dir = project_root / ".gran-maestro" / "sessions" / session_id
    history_file = session_dir / "history.ndjson"
    local_head = session_dir / "history.head"
    resolved_policy_home = policy_home or home / ".claude" / "gran-maestro-policy"
    mirror_head = resolved_policy_home / "ledger-heads" / f"{session_id}.head"

    expected_prev = ZERO_HASH
    expected_seq = 1
    last_hash = ZERO_HASH
    try:
        lines = history_file.read_text(encoding="utf-8").splitlines() if history_file.is_file() else []
    except OSError as exc:
        return {"ok": False, "reason": f"history read failed: {exc}"}

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            return {"ok": False, "reason": f"invalid json line={line_no}: {exc}"}
        if not isinstance(row, dict):
            return {"ok": False, "reason": f"row is not object line={line_no}"}
        if row.get("seq") != expected_seq:
            return {"ok": False, "reason": f"seq line={line_no}"}
        if row.get("prev_hash") != expected_prev:
            return {"ok": False, "reason": f"prev_hash line={line_no}"}
        event = row.get("event")
        if not isinstance(event, dict):
            return {"ok": False, "reason": f"event line={line_no}"}
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        computed = hashlib.sha256((expected_prev + "\n" + canonical).encode("utf-8")).hexdigest()
        if row.get("event_hash") != computed:
            return {"ok": False, "reason": f"event_hash line={line_no}"}
        expected_prev = computed
        last_hash = computed
        expected_seq += 1

    local_value = _read_text_stripped(local_head)
    mirror_value = _read_text_stripped(mirror_head)
    has_entries = expected_seq > 1
    if not has_entries:
        if local_value is not None and local_value != ZERO_HASH:
            return {"ok": False, "reason": "history.head non-zero for empty ledger"}
        if mirror_value is not None and mirror_value != ZERO_HASH:
            return {"ok": False, "reason": "mirror head non-zero for empty ledger"}
        return {"ok": True, "reason": "ok", "last_hash": ZERO_HASH, "seq": 0}

    if local_value is None:
        return {"ok": False, "reason": "missing history.head"}
    if mirror_value is None:
        return {"ok": False, "reason": "missing home mirror head"}
    if local_value != last_hash:
        return {"ok": False, "reason": "history.head"}
    if mirror_value != last_hash:
        return {"ok": False, "reason": "home mirror head"}
    return {"ok": True, "reason": "ok", "last_hash": last_hash, "seq": expected_seq - 1}


def _history_ledger_mismatch_payload(lock_path: Path, ledger_status: dict) -> dict | None:
    if ledger_status.get("ok"):
        return None
    return _diagnostic_payload(
        "ledger-mismatch",
        "run-ledger-verification",
        lock_path,
        ledger_status=ledger_status,
    )


def _path_has_symlink(path: Path, stop_at: Path) -> bool:
    current = path
    stop = stop_at.resolve(strict=False)
    while True:
        if current.is_symlink():
            return True
        if current.resolve(strict=False) == stop:
            return False
        if current.parent == current:
            return False
        current = current.parent


def _history_scope_status(base_dir: Path, session_id: str, lock_path: Path) -> tuple[bool, str]:
    expected = (base_dir / "sessions" / session_id / "history.lock").resolve(strict=False)
    resolved = lock_path.expanduser().resolve(strict=False)
    if _path_has_symlink(lock_path, base_dir.parent):
        return False, "symlink-lock-path"
    if resolved != expected:
        return False, f"expected={expected}"
    return True, "ok"


def _result_scope_status(base_dir: Path, agi_id: str, sprint_id: str, lock_path: Path) -> tuple[bool, str]:
    expected = (base_dir / "agile" / agi_id / "sprints" / sprint_id / ".result.lock").resolve(strict=False)
    resolved = lock_path.expanduser().resolve(strict=False)
    if _path_has_symlink(lock_path, base_dir.parent):
        return False, "symlink-lock-path"
    if resolved != expected:
        return False, f"expected={expected}"
    return True, "ok"


def _result_partial_artifact(sprint_dir: Path) -> Optional[Path]:
    candidates = []
    for pattern in ("*.tmp", "*.partial", ".*.tmp", "result.json.tmp", "result.md.tmp"):
        candidates.extend(sprint_dir.glob(pattern))
    for path in sorted(set(candidates)):
        if path.name == ".result.lock":
            continue
        if path.exists():
            return path
    result_json = sprint_dir / "result.json"
    if result_json.is_file():
        try:
            json.loads(result_json.read_text(encoding="utf-8"))
        except Exception:
            return result_json
    return None


def _load_lock_owner(lock_path: Path) -> tuple[dict, Optional[str]]:
    owner_path = lock_path / "owner.json"
    if not owner_path.is_file():
        return {}, "missing-owner-metadata"
    try:
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"malformed-owner-metadata: {exc}"
    if not isinstance(owner, dict):
        return {}, "owner-metadata-not-object"
    return owner, None


def _process_status(pid: Any) -> tuple[str, Optional[str]]:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return "unknown", "invalid-owner-pid"
    if pid_int <= 0:
        return "unknown", "invalid-owner-pid"
    try:
        os.kill(pid_int, 0)
        return "live", None
    except ProcessLookupError:
        return "missing", None
    except PermissionError as exc:
        return "inconclusive", str(exc)
    except OSError as exc:
        return "inconclusive", str(exc)


def _diagnose_history_lock(
    *,
    project_root: Path | str | None = None,
    base_dir: Path | str | None = None,
    home: Path | str | None = None,
    policy_home: Path | str | None = None,
    session_id: str | None = None,
    lock_path: Path | str | None = None,
    stale_after_sec: int = STALE_LOCK_SECONDS,
    **_: Any,
) -> dict:
    resolved_base_dir = _diagnostic_base_dir(project_root=project_root, base_dir=base_dir)
    resolved_project_root = _diagnostic_project_root(project_root=project_root, base_dir=resolved_base_dir)
    resolved_home = Path(home).expanduser().resolve(strict=False) if home is not None else Path.home()
    resolved_policy_home = (
        Path(policy_home).expanduser().resolve(strict=False) if policy_home is not None else None
    )
    sid = str(session_id or "").strip()
    resolved_lock_path = Path(lock_path).expanduser() if lock_path is not None else resolved_base_dir / "sessions" / sid / "history.lock"

    scope_ok, scope_status = _history_scope_status(resolved_base_dir, sid, resolved_lock_path)
    if not scope_ok:
        return _diagnostic_payload(
            "scope-mismatch",
            "inspect-lock-owner",
            resolved_lock_path,
            scope_status=scope_status,
        )

    ledger_status = _history_ledger_status_readonly(
        resolved_project_root,
        resolved_home,
        sid,
        policy_home=resolved_policy_home,
    )
    ledger_mismatch = _history_ledger_mismatch_payload(resolved_lock_path, ledger_status)
    if ledger_mismatch is not None:
        return ledger_mismatch

    owner, owner_reason = _load_lock_owner(resolved_lock_path)
    owner_pid = owner.get("owner_pid")
    owner_started_at = owner.get("owner_started_at")
    owner_session_id = owner.get("session_id")
    if owner_reason or owner_pid in (None, "") or owner_started_at in (None, "") or owner_session_id in (None, ""):
        return _diagnostic_payload(
            "owner-unknown",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=owner_reason or "insufficient-owner-identity",
            owner_status="unknown",
        )

    owner_status, status_reason = _process_status(owner_pid)
    if owner_status == "live":
        return _diagnostic_payload(
            "owner-live",
            "wait-for-owner",
            resolved_lock_path,
            owner_pid=int(owner_pid),
            owner_status="live",
        )
    if owner_status == "inconclusive":
        return _diagnostic_payload(
            "diagnosis-inconclusive",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=status_reason or "process lookup failed",
            owner_status="inconclusive",
        )
    if owner_status == "unknown":
        return _diagnostic_payload(
            "owner-unknown",
            "inspect-lock-owner",
            resolved_lock_path,
            reason=status_reason or "insufficient-owner-identity",
            owner_status="unknown",
        )

    try:
        lock_age = max(0.0, time.time() - resolved_lock_path.stat().st_mtime)
    except OSError:
        lock_age = 0.0
    if lock_age >= float(stale_after_sec):
        return _diagnostic_payload(
            "history-lock-stale-candidate",
            "manual-recovery-approval",
            resolved_lock_path,
            lock_age=lock_age,
        )
    return _diagnostic_payload(
        "owner-unknown",
        "inspect-lock-owner",
        resolved_lock_path,
        reason="owner-missing-but-lock-age-below-threshold",
        owner_status="missing",
    )


def _diagnose_result_lock(
    *,
    project_root: Path | str | None = None,
    base_dir: Path | str | None = None,
    agi_id: str | None = None,
    sprint: int | None = None,
    sprint_id: str | None = None,
    lock_path: Path | str | None = None,
    **_: Any,
) -> dict:
    resolved_base_dir = _diagnostic_base_dir(project_root=project_root, base_dir=base_dir)
    agi = str(agi_id or "").strip()
    sid = str(sprint_id or "").strip() or (f"S{int(sprint):02d}" if sprint is not None else "")
    resolved_lock_path = Path(lock_path).expanduser() if lock_path is not None else resolved_base_dir / "agile" / agi / "sprints" / sid / ".result.lock"
    scope_ok, scope_status = _result_scope_status(resolved_base_dir, agi, sid, resolved_lock_path)
    if not scope_ok:
        return _diagnostic_payload(
            "scope-mismatch",
            "inspect-lock-owner",
            resolved_lock_path,
            scope_status=scope_status,
        )

    sprint_dir = resolved_lock_path.parent
    artifact_path = _result_partial_artifact(sprint_dir)
    if artifact_path is not None:
        return _diagnostic_payload(
            "partial-output-detected",
            "inspect-partial-output",
            resolved_lock_path,
            artifact_path=str(artifact_path),
        )

    if resolved_lock_path.exists():
        with open(resolved_lock_path, "a+", encoding="utf-8") as result_lock_file:
            acquired = False
            try:
                _common._lock_exclusive_with_timeout(result_lock_file, timeout_sec=0.0, poll_interval=0.01)
                acquired = True
            except TimeoutError:
                return _diagnostic_payload(
                    "result-lock-contention",
                    "wait-for-owner",
                    resolved_lock_path,
                    agi_id=agi,
                    sprint_id=sid,
                )
            finally:
                if acquired:
                    _common._unlock(result_lock_file)

    return _diagnostic_payload(
        "owner-unknown",
        "inspect-lock-owner",
        resolved_lock_path,
        reason="no-result-lock-contention-detected",
        owner_status="unknown",
        agi_id=agi,
        sprint_id=sid,
    )


def _diagnose_stale_lock(**context: Any) -> dict:
    kind = str(context.get("lock_kind") or context.get("kind") or "").strip().lower()
    lock_path = context.get("lock_path")
    lock_name = Path(lock_path).name if lock_path is not None else ""
    if kind == "result" or lock_name == ".result.lock":
        return _diagnose_result_lock(**context)
    return _diagnose_history_lock(**context)


diagnose_stale_lock = _diagnose_stale_lock


def diagnose_agile_stale_lock(**context: Any) -> dict:
    return _diagnose_stale_lock(**context)


def diagnose_history_lock(**context: Any) -> dict:
    return _diagnose_history_lock(**context)


def _load_first_json_object(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    return value


def _run_finalize_mst_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _finalize_mst_command(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(_common._mst_script_path()), *args]
    return _run_finalize_mst_command(command, cwd=project_root)


def _collect_finalize_req_ids(agi_id: str) -> list[str]:
    req_ids: list[str] = []
    seen: set[str] = set()
    sprints_dir = _agi_session_dir(agi_id) / "sprints"
    for result_path in sorted(sprints_dir.glob("S*/result.json")):
        result = load_json(result_path)
        if not isinstance(result, dict):
            continue
        raw_req_ids: list[str] = []
        req_id = result.get("req_id")
        if isinstance(req_id, str):
            raw_req_ids.append(req_id)
        generated = result.get("generated")
        generated_reqs = generated.get("req") if isinstance(generated, dict) else None
        if isinstance(generated_reqs, list):
            raw_req_ids.extend(value for value in generated_reqs if isinstance(value, str))
        for raw_req_id in raw_req_ids:
            normalized = _normalize_link_id(raw_req_id, "REQ")
            if normalized not in seen:
                seen.add(normalized)
                req_ids.append(normalized)
    return req_ids


def _inspect_request_status(project_root: Path, req_id: str) -> str:
    result = _finalize_mst_command(project_root, "request", "inspect", req_id, "--json")
    if result.returncode != 0 and "unrecognized arguments: --json" in result.stderr:
        result = _finalize_mst_command(project_root, "request", "inspect", req_id)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"request inspect failed: {req_id}"
        raise RuntimeError(message)

    payload = _load_first_json_object(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"request inspect returned invalid JSON: {req_id}")
    return str(payload.get("status") or "")


def _remove_finalize_worktrees(project_root: Path, agi_id: str) -> list[str]:
    removed: list[str] = []
    worktrees_root = _common.BASE_DIR / "worktrees" / agi_id
    if not worktrees_root.is_dir():
        return removed

    for worktree_path in sorted(worktrees_root.glob("sprint-*")):
        if not worktree_path.exists():
            continue
        if not worktree_path.is_dir():
            continue
        normalized_path = str(worktree_path.resolve(strict=False))
        result = _finalize_mst_command(
            project_root,
            "worktree",
            "remove",
            "--path",
            normalized_path,
            "--force",
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"worktree remove failed: {normalized_path}"
            raise RuntimeError(message)
        removed.append(normalized_path)
    return removed


def _run_finalize_orphan_cleanup(project_root: Path) -> tuple[dict, bool]:
    session_id = os.environ.get("MST_SESSION_ID", "").strip() or "phase5"

    def _cleanup(_context: dict) -> dict:
        result = _finalize_mst_command(project_root, "worktree", "detect-orphans", "--clean", "--json")
        payload = _load_first_json_object(result.stdout)
        if not isinstance(payload, dict):
            payload = {"cleaned": [], "failed": []}
        payload.setdefault("cleaned", [])
        payload.setdefault("failed", [])
        if result.returncode != 0 and not payload.get("failed"):
            message = result.stderr.strip() or result.stdout.strip() or "worktree detect-orphans failed"
            raise RuntimeError(message)
        return {
            "status": "ok" if result.returncode == 0 and not payload.get("failed") else "failed",
            "payload": payload,
            "returncode": result.returncode,
        }

    report = cleanup_mod.run_cleanup_with_lock_report(
        project_root=project_root,
        entrypoint="phase5",
        session_id=session_id,
        timeout_seconds=5.0,
        cleanup_fn=_cleanup,
    )
    payload = report.get("payload")
    if not isinstance(payload, dict):
        payload = {"cleaned": [], "failed": []}
    payload.setdefault("cleaned", [])
    payload.setdefault("failed", [])
    return payload, report.get("status") == "ok" and not payload.get("failed")


def _run_finalize_boundary_check(project_root: Path, agi_id: str) -> bool | None:
    result = _finalize_mst_command(project_root, "worktree", "check-boundary", "--agi", agi_id)
    if result.returncode == 0:
        return True

    stderr = result.stderr.strip()
    if (
        "invalid choice" in stderr
        or "unrecognized arguments: --agi" in stderr
        or "the following arguments are required" in stderr
    ):
        return None
    return False


def _print_finalize_payload(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"agi_id: {payload['agi_id']}")
    print(f"accepted_reqs: {', '.join(payload['accepted_reqs']) or '-'}")
    print(f"skipped_reqs: {', '.join(payload['skipped_reqs']) or '-'}")
    print(f"pending_accept_reqs: {', '.join(payload['pending_accept_reqs']) or '-'}")
    print(f"removed_worktrees: {len(payload['removed_worktrees'])}")
    print(f"orphan_cleanup.cleaned: {', '.join(payload['orphan_cleanup'].get('cleaned') or []) or '-'}")
    print(f"orphan_cleanup.failed: {', '.join(payload['orphan_cleanup'].get('failed') or []) or '-'}")
    print(f"boundary_ok: {payload['boundary_ok']}")


def _finalize_report_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, (list, dict, bool)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _write_finalize_final_report(agi_id: str, payload: dict, status: str) -> None:
    orphan_cleanup = payload.get("orphan_cleanup")
    if not isinstance(orphan_cleanup, dict):
        orphan_cleanup = {}
    removed_worktrees = payload.get("removed_worktrees")
    if not isinstance(removed_worktrees, list):
        removed_worktrees = []

    lines = [
        f"# {agi_id} Finalization Report",
        f"- generated_at: {_now_iso()}",
        f"- status: {status}",
        "",
        "## Accepted/Skipped REQs",
        f"- skipped_reqs: {_finalize_report_value(payload.get('skipped_reqs') or [])}",
        f"- pending_accept_reqs: {_finalize_report_value(payload.get('pending_accept_reqs') or [])}",
        "",
        "## Worktree Cleanup",
        f"- removed_worktrees: {len(removed_worktrees)}건 ({_finalize_report_value(removed_worktrees)})",
        "",
        "## Orphan Cleanup",
        f"- cleaned: {_finalize_report_value(orphan_cleanup.get('cleaned') or [])}",
        f"- failed: {_finalize_report_value(orphan_cleanup.get('failed') or [])}",
        "",
        "## Boundary Check",
        f"- boundary_ok: {_finalize_report_value(payload.get('boundary_ok'))}",
        "",
    ]
    report_path = _agi_session_dir(agi_id) / "final-report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def cmd_agile_finalize(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    project_root = _common.BASE_DIR.parent
    payload = {
        "agi_id": agi_id,
        "accepted_reqs": [],
        "skipped_reqs": [],
        "pending_accept_reqs": [],
        "removed_worktrees": [],
        "orphan_cleanup": {"cleaned": [], "failed": []},
        "boundary_ok": None,
    }
    _append_agile_event(agi_id, "agile.finalize.step.load_session", {"ok": True})

    try:
        req_ids = _collect_finalize_req_ids(agi_id)
        _append_agile_event(agi_id, "agile.finalize.step.collect_reqs", {"ok": True, "req_ids": req_ids})

        for req_id in req_ids:
            status = _inspect_request_status(project_root, req_id)
            if status in FINALIZE_ACCEPTED_STATUSES:
                payload["skipped_reqs"].append(req_id)
            else:
                payload["pending_accept_reqs"].append(req_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.inspect_reqs",
            {
                "ok": True,
                "skipped_reqs": payload["skipped_reqs"],
                "pending_accept_reqs": payload["pending_accept_reqs"],
            },
        )

        payload["removed_worktrees"] = _remove_finalize_worktrees(project_root, agi_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.remove_worktrees",
            {"ok": True, "removed_worktrees": payload["removed_worktrees"]},
        )

        orphan_cleanup, orphan_ok = _run_finalize_orphan_cleanup(project_root)
        payload["orphan_cleanup"] = orphan_cleanup
        _append_agile_event(
            agi_id,
            "agile.finalize.step.orphan_cleanup",
            {"ok": orphan_ok, "orphan_cleanup": orphan_cleanup},
        )

        payload["boundary_ok"] = _run_finalize_boundary_check(project_root, agi_id)
        _append_agile_event(
            agi_id,
            "agile.finalize.step.boundary_check",
            {"ok": payload["boundary_ok"] is not False, "boundary_ok": payload["boundary_ok"]},
        )
    except Exception as exc:
        _append_agile_event(agi_id, "agile.finalize.step.failed", {"ok": False, "error": str(exc)})
        print(f"Error: {exc}", file=sys.stderr)
        _write_finalize_final_report(agi_id, payload, "failed")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 1

    if payload["pending_accept_reqs"]:
        pending = ", ".join(payload["pending_accept_reqs"])
        print(f"[finalize] pending accept: {pending}", file=sys.stderr)
        _append_agile_event(
            agi_id,
            "agile.finalize.pending_accept",
            {"pending_accept_reqs": payload["pending_accept_reqs"]},
        )
        _write_finalize_final_report(agi_id, payload, "pending_accept")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 2

    if payload["orphan_cleanup"].get("failed"):
        _append_agile_event(
            agi_id,
            "agile.finalize.failed",
            {"orphan_cleanup": payload["orphan_cleanup"]},
        )
        _write_finalize_final_report(agi_id, payload, "failed")
        _print_finalize_payload(payload, getattr(args, "json", False))
        return 1

    _append_agile_event(agi_id, "agile.finalize.ok", payload)
    _write_finalize_final_report(agi_id, payload, "ok")
    _print_finalize_payload(payload, getattr(args, "json", False))
    return 0


def cmd_agile_result(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    from scripts.mst_cmds.state import _check_read_only

    read_only_status = _check_read_only(agi_id)
    if read_only_status:
        return read_only_status

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
    if getattr(args, "dod_ref", None) is not None:
        payload["dod_ref"] = str(args.dod_ref)
    if getattr(args, "domain", None) is not None:
        payload["domain_ref"] = str(args.domain)
    if args.previous_direction is not None:
        payload["previous_direction"] = str(args.previous_direction)
    if args.previous_lessons is not None:
        payload["previous_lessons"] = str(args.previous_lessons)
    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    result_lock_path = sprint_dir / ".result.lock"
    aux_warnings = []

    def _record_aux_warning(stage, exc):
        aux_warnings.append(
            {
                "stage": stage,
                "error_class": exc.__class__.__name__,
                "message": str(exc)[:500],
            }
        )
        print(f"[warn] {stage} hook 실패: {exc}", file=sys.stderr)

    with open(result_lock_path, "a+", encoding="utf-8") as result_lock_file:
        result_lock_acquired = False
        try:
            _common._lock_exclusive_with_timeout(result_lock_file, timeout_sec=5.0, poll_interval=0.05)
            result_lock_acquired = True
        except TimeoutError as exc:
            diagnostic = _diagnostic_payload(
                "result-lock-contention",
                "wait-for-owner",
                result_lock_path,
                agi_id=agi_id,
                sprint_id=sprint_id,
                compatible_signal="lock-contention",
            )
            print(
                "Error: agile result lock-contention (lock timeout) "
                "category=result-lock-contention next_action=wait-for-owner "
                f"agi_id={agi_id} sprint_id={sprint_id} lock_path={result_lock_path} detail={exc}",
                file=sys.stderr,
            )
            print(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True), file=sys.stderr)
            return 1

        try:
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
                try:
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
                except Exception as exc:
                    _record_aux_warning("links-update", exc)

            # drift report skeleton 생성 (status in [done, failed]일 때만)
            drift_report_path = None
            if args.status in ("done", "failed"):
                try:
                    drift_report_path = _generate_drift_report_skeleton(
                        agi_id=agi_id,
                        sprint_num=args.sprint,
                        source_plan=getattr(args, "pln", None),
                        dod_ref=getattr(args, "dod_ref", None),
                        original_dod_text=None,  # MVP에서는 None, 향후 확장
                    )
                except Exception as exc:
                    _record_aux_warning("drift-report", exc)

                # recall patch manifest skeleton 생성 (drift-report classification 기반)
                try:
                    classification = None
                    if drift_report_path is not None:
                        try:
                            report_data = json.loads(Path(drift_report_path).read_text(encoding="utf-8"))
                            classification = report_data.get("classification")
                        except Exception:
                            classification = None
                    if classification in ("drift_warning", "objective_stale"):
                        _generate_recall_patch_manifest_skeleton(
                            agi_id=agi_id,
                            sprint_num=args.sprint,
                            classification=classification,
                            drift_report_path=drift_report_path,
                        )
                except Exception as exc:
                    _record_aux_warning("recall-manifest", exc)

            payload["aux_status"] = "partial" if aux_warnings else "ok"
            payload["aux_warnings"] = aux_warnings
            save_json(sprint_dir / "result.json", payload)
        finally:
            if result_lock_acquired:
                _common._unlock(result_lock_file)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(sprint_dir / "result.json"))
    return 0


def cmd_agile_diagnose_lock(args):
    context = {
        "project_root": _common.BASE_DIR.parent if _common.BASE_DIR is not None else Path.cwd(),
        "base_dir": _common.BASE_DIR if _common.BASE_DIR is not None else Path.cwd() / ".gran-maestro",
        "home": Path.home(),
        "policy_home": Path.home() / ".claude" / "gran-maestro-policy",
        "session_id": getattr(args, "session_id", None),
        "lock_path": Path(args.lock_path).expanduser() if args.lock_path else None,
        "lock_kind": args.lock_kind,
        "kind": args.lock_kind,
        "agi_id": getattr(args, "agi_id", None),
        "sprint": getattr(args, "sprint", None),
        "sprint_id": getattr(args, "sprint_id", None),
        "stale_after_sec": getattr(args, "stale_after_sec", STALE_LOCK_SECONDS),
    }
    payload = _diagnose_stale_lock(**context)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0

def cmd_agile_dispatch_result(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
        pln_id = _normalize_link_id(args.pln, "PLN") if args.pln else None
        req_id = _normalize_link_id(args.req, "REQ") if args.req else None
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    sprint_id = f"S{args.sprint:02d}"
    payload = {
        "agi_id": agi_id,
        "sprint": int(args.sprint),
        "status": str(args.status),
        "pln_id": pln_id,
        "req_id": req_id,
        "commit_sha": str(args.commit_sha) if args.commit_sha is not None else None,
        "sprint_kind": str(args.sprint_kind) if args.sprint_kind is not None else None,
        "exit_code": int(args.exit_code),
        "failure_reason": str(args.failure_reason) if args.failure_reason is not None else None,
        "result_recorded": bool(args.result_recorded),
        "retrospective_recorded": bool(args.retrospective_recorded),
    }

    sprint_dir = _agi_session_dir(agi_id) / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    dispatch_result_path = sprint_dir / "dispatch-result.json"
    save_json(dispatch_result_path, payload)
    _append_agile_event(
        agi_id,
        "agile.dispatch-result",
        {
            "sprint_id": sprint_id,
            "status": payload["status"],
            "exit_code": payload["exit_code"],
        },
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(dispatch_result_path))
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

    succeeded = _split_csv_values(args.succeeded) if args.succeeded else []

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
    limitations_normalized = str(args.limitations).strip() if args.limitations else ""
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
        "known_limitations": limitations_normalized,
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
        "KNOWN_LIMITATIONS": str(payload["known_limitations"]) or "없음",
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


def cmd_agile_review(args):
    perspective = str(args.perspective).strip()
    enabled_status = _validate_adversarial_review_enabled(perspective)
    if enabled_status:
        return enabled_status

    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        print(f"Error: objective not found: {objective_path}", file=sys.stderr)
        return 1

    context_files = [objective_path]
    details_dir = objective_path.parent / "details"
    if details_dir.exists():
        context_files.extend(sorted(details_dir.glob("*.md")))

    return _emit_adversarial_review_payload(context_files, perspective)


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

    agile_takeover = agile_sub.add_parser("takeover")
    agile_takeover.add_argument("--agi", required=True)

    agile_update = agile_sub.add_parser("update")
    agile_update.add_argument("agi_id")
    agile_update.add_argument("--status")
    agile_update.add_argument("--current-sprint", type=int)
    agile_update.add_argument("--steering-every", type=int)
    agile_update.add_argument("--objective-version", type=int)
    agile_update.add_argument("--user-requested", action="store_true",
        help="사용자가 직접 요청한 pause 전환임을 표시 (LLM 자발 정지 방지 게이트 우회)")
    agile_update.add_argument("--force", action="store_true", help="completion guard 우회")
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
    agile_result.add_argument("--dod-ref", default=None)
    agile_result.add_argument("--domain", default=None)
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

    agile_diagnose_lock = agile_sub.add_parser("diagnose-lock")
    agile_diagnose_lock.add_argument("--lock-kind", choices=["history", "result"], default="history")
    agile_diagnose_lock.add_argument("--lock-path")
    agile_diagnose_lock.add_argument("--session-id")
    agile_diagnose_lock.add_argument("--agi-id")
    agile_diagnose_lock.add_argument("--sprint", type=int)
    agile_diagnose_lock.add_argument("--sprint-id")
    agile_diagnose_lock.add_argument("--stale-after-sec", type=int, default=STALE_LOCK_SECONDS)

    agile_dispatch_result = agile_sub.add_parser("dispatch-result")
    agile_dispatch_result.add_argument("agi_id")
    agile_dispatch_result.add_argument("--sprint", type=int, required=True)
    agile_dispatch_result.add_argument("--status", required=True, choices=["success", "failed"])
    agile_dispatch_result.add_argument("--exit-code", type=int, required=True, dest="exit_code")
    agile_dispatch_result.add_argument("--pln")
    agile_dispatch_result.add_argument("--req")
    agile_dispatch_result.add_argument("--commit-sha", dest="commit_sha")
    agile_dispatch_result.add_argument("--sprint-kind", dest="sprint_kind")
    agile_dispatch_result.add_argument("--failure-reason", dest="failure_reason")
    agile_dispatch_result.add_argument(
        "--result-recorded",
        type=_common._parse_bool_arg,
        default=True,
        metavar="{true,false}",
        dest="result_recorded",
    )
    agile_dispatch_result.add_argument(
        "--retrospective-recorded",
        type=_common._parse_bool_arg,
        default=True,
        metavar="{true,false}",
        dest="retrospective_recorded",
    )
    agile_dispatch_result.add_argument("--json", action="store_true")

    agile_finalize = agile_sub.add_parser("finalize")
    agile_finalize.add_argument("agi_id")
    agile_finalize.add_argument("--json", action="store_true")

    parent_module = sys.modules.get("scripts.mst_cmds")
    dispatch = getattr(parent_module, "DISPATCH", None)
    if isinstance(dispatch, dict):
        dispatch.setdefault(("agile", "finalize"), cmd_agile_finalize)
        dispatch.setdefault(("agile", "diagnose-lock"), cmd_agile_diagnose_lock)

    agile_sprint_close = agile_sub.add_parser("sprint-close")
    agile_sprint_close.add_argument("agi_id")
    agile_sprint_close.add_argument("--sprint", type=int, required=True)
    agile_sprint_close.add_argument("--base")
    agile_sprint_close.add_argument("--branch")
    agile_sprint_close.add_argument("--worktree-path", dest="worktree_path")
    agile_sprint_close.add_argument("--dry-run", action="store_true", dest="dry_run")
    agile_sprint_close.add_argument("--json", action="store_true")
    agile_sprint_close.add_argument("--message")

    agile_retrospective = agile_sub.add_parser("retrospective")
    agile_retrospective.add_argument("agi_id")
    agile_retrospective.add_argument("--sprint", type=int, required=True)
    agile_retrospective.add_argument("--status", required=True)
    agile_retrospective.add_argument("--succeeded", action="append", required=False, default=None)
    agile_retrospective.add_argument("--failed", action="append", required=False, default=None)
    agile_retrospective.add_argument("--velocity-planned", type=int, required=True)
    agile_retrospective.add_argument("--velocity-completed", type=int, required=True)
    agile_retrospective.add_argument("--limitations", required=False, default="")
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

    agile_review = agile_sub.add_parser("review")
    agile_review.add_argument("--agi", dest="agi_id", required=True)
    agile_review.add_argument("--perspective", required=True, choices=ADVERSARIAL_REVIEW_PERSPECTIVES)
    agile_review.add_argument("--json", action="store_true", required=True)

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
    agile_objective_transition.add_argument("--evidence-ref", action="append", default=[])
    agile_objective_transition.add_argument("--json", action="store_true")

    agile_objective_check = agile_sub.add_parser("objective-check")
    agile_objective_check.add_argument("agi_id")
    agile_objective_check.add_argument("--dod-id", default=None)
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
