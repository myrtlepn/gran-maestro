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
from scripts.mst_cmds import session as session_mod
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
            "requires_user_answer": "true|false",
            "question": "...",
            "recommended_answer": "...",
            "recommendation_rationale": "...",
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
def _emit_adversarial_review_payload(
    context_files: List[Path],
    perspective: str,
    *,
    context_source: str = "accepted",
    draft_dir: Path | None = None,
) -> int:
    payload = {
        "context_files": [str(path.resolve()) for path in context_files],
        "role_template": str(_adversarial_review_template_path(perspective)),
        "output_schema": ADVERSARIAL_REVIEW_OUTPUT_SCHEMA,
        "perspective": perspective,
        "context_source": context_source,
        "draft_dir": str(draft_dir.resolve()) if draft_dir is not None else None,
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


def _fresh_bootstrap_agile_identity() -> tuple[str, str] | None:
    mst_session_id = os.environ.get("MST_SESSION_ID", "").strip()
    if not mst_session_id:
        return None
    parsed = session_mod.validate_mst_session_id(mst_session_id)
    if not parsed.root_mst_id.startswith("AGI-"):
        return None
    session_mod.validate_mst_session_metadata_consistency(
        _common.BASE_DIR,
        mst_session_id,
        require_root_metadata=True,
        require_session_metadata=True,
    )
    root_path = session_mod.root_artifact_metadata_path(_common.BASE_DIR, parsed.root_mst_id)
    root_payload = load_json(root_path) or {}
    if root_payload.get("status") or root_payload.get("agi_id"):
        raise ValueError(f"{parsed.root_mst_id} already exists")
    return parsed.root_mst_id, parsed.mst_session_id


def _verify_agile_init_session(agi_id: str, mst_session_id: str) -> dict:
    payload, _ = _load_agile_session(agi_id)
    actual_mst_session_id = str(payload.get("mst_session_id") or "").strip()
    if actual_mst_session_id != mst_session_id:
        raise ValueError(
            f"session identity mismatch for {agi_id}: expected {mst_session_id}, got {actual_mst_session_id or '<missing>'}"
        )
    session_mod.validate_mst_session_metadata_consistency(
        _common.BASE_DIR,
        mst_session_id,
        require_root_metadata=True,
        require_session_metadata=True,
    )
    return payload
def cmd_agile_init(args):
    if args.steering_every < 1:
        print("Error: --steering-every must be >= 1", file=sys.stderr)
        return 1

    try:
        bootstrap_identity = _fresh_bootstrap_agile_identity()
        agi_id = bootstrap_identity[0] if bootstrap_identity else _next_agile_id()
    except (RuntimeError, ValueError) as exc:
        print(f"Error: failed to allocate AGI id ({exc})", file=sys.stderr)
        return 1

    session_dir = _agi_session_dir(agi_id)
    if session_dir.exists() and bootstrap_identity is None:
        print(f"Error: {agi_id} already exists", file=sys.stderr)
        return 1

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
    try:
        if bootstrap_identity:
            created = session_mod.ensure_root_session_artifacts(
                _common.BASE_DIR,
                agi_id,
                root_payload=payload,
                mst_session_id=bootstrap_identity[1],
            )
        else:
            created = session_mod.create_root_session_artifacts(
                _common.BASE_DIR,
                agi_id,
                root_payload=payload,
            )
        mst_session_id = str(created["mst_session_id"])
        session_mod.write_session_history_event(
            _common.BASE_DIR,
            mst_session_id,
            {
                "event_type": "agile.init",
                "artifact_id": agi_id,
                "resource_id": agi_id,
                "status": "active",
                "command": "agile init",
                "steering_every": args.steering_every,
                "idempotency_key": f"{mst_session_id}:agile.init:{agi_id}",
                "created_at": now,
            },
        )
    except Exception as exc:
        if "created" in locals():
            shutil.rmtree(session_dir, ignore_errors=True)
            try:
                shutil.rmtree(Path(created["session_metadata_path"]).parent, ignore_errors=True)
            except Exception:
                pass
        print(f"Error: failed to initialize canonical MST session for {agi_id} ({exc})", file=sys.stderr)
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
    _append_agile_event(
        agi_id,
        "agile.init",
        {
            "steering_every": args.steering_every,
            "mst_session_id": mst_session_id,
        },
    )
    try:
        payload = _verify_agile_init_session(agi_id, mst_session_id)
    except Exception as exc:
        shutil.rmtree(session_dir, ignore_errors=True)
        try:
            shutil.rmtree(Path(created["session_metadata_path"]).parent, ignore_errors=True)
        except Exception:
            pass
        print(f"Error: agile init session verification failed for {agi_id} ({exc})", file=sys.stderr)
        return 1

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
