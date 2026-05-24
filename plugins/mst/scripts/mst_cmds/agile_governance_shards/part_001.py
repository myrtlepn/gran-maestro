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
    _SOURCE_MAPPING_RE,
    _agi_objective_changelog_path,
    _agi_objective_path,
    _agi_session_dir,
    _agile_state_ledger_path,
    _append_agile_event,
    _append_agile_sprint_log,
    _append_ndjson,
    _collect_objective_dod_items,
    _extract_frontmatter_block,
    _extract_objective_surface_entries,
    _extract_yaml_list,
    _extract_yaml_scalar,
    _find_latest_agi_id,
    _load_agile_config_merged,
    _load_agile_int_config,
    _load_agile_session,
    _load_agile_state_payload,
    _load_config_for_get,
    _normalize_agi_id,
    _normalize_drift_surface_entry,
    _normalize_tbd,
    _now_iso,
    _save_agile_session,
    _save_agile_state_payload,
    _split_csv_values,
    _strip_balanced_quotes,
    agile_dir,
    load_json,
    parse_agile_detail_metadata,
    save_json,
)
def _normalize_dod_id(value: str) -> str:
    dod_id = (value or "").strip()
    if not re.fullmatch(r"DOD-[A-Z0-9_-]+", dod_id, flags=re.IGNORECASE):
        raise ValueError(f"Invalid DoD id: {value}")
    return dod_id.upper()
def _generate_drift_report_skeleton(
    agi_id: str,
    sprint_num: int,
    source_plan: Optional[str] = None,
    dod_ref: Optional[str] = None,
    original_dod_text: Optional[str] = None,
) -> Optional[Path]:
    """Sprint 완료 시 drift-report.json skeleton 생성.

    LLM 실제 역추정은 MVP에서 연결하지 않고, pending 플레이스홀더로 남김.
    git 커맨드 실패 시 commits/changed_files는 빈 배열로 graceful degrade.
    return Path on success, None on graceful fail.
    """
    try:
        import subprocess

        sprints_dir_resolver = globals().get("_agi_sprints_dir")
        sprints_dir = (
            sprints_dir_resolver(agi_id)
            if callable(sprints_dir_resolver)
            else _agi_session_dir(agi_id) / "sprints"
        )
        sprint_dir = sprints_dir / f"S{sprint_num:02d}"
        sprint_dir.mkdir(parents=True, exist_ok=True)
        report_path = sprint_dir / "drift-report.json"

        # git commit 수집 (최근 10개 fallback)
        commits = []
        changed_files = []
        try:
            result = subprocess.run(
                ["git", "log", "--pretty=%H", "-10"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1..HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                changed_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            pass

        payload = {
            "sprint": f"S{sprint_num:02d}",
            "dod_ref": dod_ref,
            "classification": "pending",
            "matching_score": None,
            "inferred_intent": None,
            "original_dod_text": original_dod_text,
            "source_plan": source_plan,
            "evidence": {
                "commits": commits,
                "changed_files": changed_files,
            },
            "generated_at": _now_iso(),
            "todo": "LLM intent inference not yet wired",
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path
    except Exception as exc:
        print(f"[warn] drift-report skeleton 생성 실패: {exc}", file=sys.stderr)
        return None
def _generate_recall_patch_manifest_skeleton(
    agi_id: str,
    sprint_num: int,
    classification: str,
    drift_report_path: Optional[Path] = None,
) -> Optional[Path]:
    """drift-report classification에 따라 Level 2/3 recall patch manifest skeleton 생성.

    - drift_warning -> Level 2, requires_user_approval=False, operations=[placeholder+TODO]
    - objective_stale -> Level 3, requires_user_approval=True, operations=[] + TODO 마커

    실제 patch operation apply는 후속 PLN에서 확장.
    return Path on success, None on graceful fail.
    """
    try:
        if classification not in ("drift_warning", "objective_stale"):
            return None

        sprints_dir_resolver = globals().get("_agi_sprints_dir")
        sprints_dir = (
            sprints_dir_resolver(agi_id)
            if callable(sprints_dir_resolver)
            else _agi_session_dir(agi_id) / "sprints"
        )
        sprint_dir = sprints_dir / f"S{sprint_num:02d}"
        sprint_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = sprint_dir / "recall-patch-manifest.json"

        if classification == "drift_warning":
            level = 2
            requires_user_approval = False
            operations = [
                {
                    "type": "dod_refine",
                    "target_dod": None,
                    "detail": "placeholder — 후속 분류 로직 필요",
                }
            ]
            todo = "Level 2 operation 분류 로직은 후속 PLN에서 구체화"
        else:
            level = 3
            requires_user_approval = True
            operations = []
            todo = "Level 3 objective revision — 사용자 승인 필요, 후속 승인 경로 연결 예정"

        payload = {
            "agi_id": agi_id,
            "sprint": f"S{sprint_num:02d}",
            "classification": classification,
            "level": level,
            "requires_user_approval": requires_user_approval,
            "operations": operations,
            "drift_report_path": str(drift_report_path) if drift_report_path else None,
            "generated_at": _now_iso(),
            "todo": todo,
        }
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path
    except Exception as exc:
        print(f"[warn] recall manifest skeleton 생성 실패: {exc}", file=sys.stderr)
        return None
_RECALL_DEFAULT_COOLDOWN_RATIO = 0.10
_RECALL_DEFAULT_CAP_RATIO = 0.10
_RECALL_DEFAULT_LEVEL = 2
_RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER = 2
_RECALL_HARD_FAIL_TOKENS = (
    "hard-fail",
    "hard_fail",
    "smoke-red",
    "smoke_red",
    "entrypoint-down",
    "entrypoint_down",
)
_UNLOCK_FORBIDDEN_REASON_PATTERNS = ("lgtm", "ok", "fix", "asdf")
_UNLOCK_CATEGORY_HINTS = {
    "upstream_evidence_changed": "upstream DoD ID + evidence fingerprint diff",
    "integration_regression": "smoke run ID + failure log",
    "new_dependency_dod": "new dependency DoD ID",
    "objective_precision_fix": "objective precision diff",
}
_RECALL_OBJECTIVE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "when",
    "want",
    "can",
    "user",
    "users",
    "project",
    "sprint",
    "objective",
    "to",
    "is",
    "are",
    "of",
    "on",
    "in",
    "it",
    "be",
    "i",
    "we",
    "you",
    "목표",
    "프로젝트",
    "스프린트",
    "사용자",
}
def _find_top_level_yaml_key_range(lines: list[str], key: str) -> Optional[tuple[int, int]]:
    key_re = re.compile(rf"^{re.escape(str(key))}\s*:")
    top_level_key_re = re.compile(r"^[A-Za-z0-9_-]+\s*:")
    start = None
    for idx, raw_line in enumerate(lines):
        if key_re.match(raw_line):
            start = idx
            break
    if start is None:
        return None

    end = start + 1
    while end < len(lines):
        candidate = lines[end]
        if top_level_key_re.match(candidate):
            break
        end += 1
    return start, end
def _extract_frontmatter_key_block_lines(frontmatter: str, key: str) -> list[str]:
    lines = str(frontmatter or "").splitlines()
    key_range = _find_top_level_yaml_key_range(lines, key)
    if key_range is None:
        return []
    start, end = key_range
    return lines[start:end]
def _upsert_frontmatter_key_block(frontmatter: str, key: str, block_lines: list[str]) -> str:
    lines = str(frontmatter or "").splitlines()
    key_range = _find_top_level_yaml_key_range(lines, key)
    if key_range is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)
    else:
        start, end = key_range
        lines[start:end] = block_lines
    return "\n".join(lines)
def _remove_frontmatter_key_block(frontmatter: str, key: str) -> str:
    lines = str(frontmatter or "").splitlines()
    key_range = _find_top_level_yaml_key_range(lines, key)
    if key_range is None:
        return "\n".join(lines)

    start, end = key_range
    del lines[start:end]

    compact: list[str] = []
    previous_blank = False
    for raw_line in lines:
        blank = not raw_line.strip()
        if blank and previous_blank:
            continue
        compact.append(raw_line)
        previous_blank = blank
    while compact and not compact[-1].strip():
        compact.pop()
    return "\n".join(compact)
def _upsert_detail_frontmatter(content: str, frontmatter_text: str) -> str:
    text = str(content)
    normalized = str(frontmatter_text or "").strip()
    replacement_frontmatter = f"---\n{normalized}\n---\n\n" if normalized else ""
    frontmatter = _extract_frontmatter_block(text)
    if frontmatter.get("errors"):
        raise ValueError("; ".join(str(err) for err in frontmatter["errors"]))

    if frontmatter.get("has_frontmatter"):
        return f"{frontmatter.get('prefix')}{replacement_frontmatter}{frontmatter.get('suffix')}"

    lines = text.splitlines(keepends=True)
    if lines and _SOURCE_MAPPING_RE.fullmatch(lines[0].strip()):
        head = lines[0]
        tail = "".join(lines[1:])
        return f"{head}{replacement_frontmatter}{tail}"

    return f"{replacement_frontmatter}{text}"
def _parse_unlock_history(frontmatter: str) -> list[dict]:
    block = _extract_frontmatter_key_block_lines(frontmatter, "unlock_history")
    if not block:
        return []

    rows: list[dict] = []
    current: Optional[dict] = None
    item_re = re.compile(r"^-\s*([A-Za-z0-9_-]+)\s*:\s*(.*)$")
    field_re = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
    for raw_line in block[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        match = item_re.match(stripped)
        if match:
            if current is not None:
                rows.append(current)
            current = {match.group(1): _strip_balanced_quotes(match.group(2))}
            continue
        if current is None:
            continue
        match = field_re.match(stripped)
        if match:
            current[match.group(1)] = _strip_balanced_quotes(match.group(2))

    if current is not None:
        rows.append(current)
    return rows
def _render_unlock_history_block(rows: list[dict]) -> list[str]:
    lines = ["unlock_history:"]
    for row in rows:
        timestamp = _yaml_quote(str(row.get("timestamp") or "").strip())
        category = _yaml_quote(str(row.get("category") or "").strip())
        reason = _yaml_quote(str(row.get("reason") or "").strip())
        evidence = _yaml_quote(str(row.get("evidence") or "").strip())
        lines.append(f"  - timestamp: {timestamp}")
        lines.append(f"    category: {category}")
        lines.append(f"    reason: {reason}")
        lines.append(f"    evidence: {evidence}")
    return lines
def _yaml_quote(value: str) -> str:
    token = str(value)
    if not token:
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:\-]+", token):
        return token
    return json.dumps(token, ensure_ascii=False)
def _render_agile_detail_evidence_block(evidence: dict) -> list[str]:
    plan = evidence.get("plan") if isinstance(evidence, dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence, dict) else {}
    plan = plan if isinstance(plan, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}

    artifact_paths = plan.get("artifact_paths")
    if not isinstance(artifact_paths, list):
        artifact_paths = []

    lines = ["evidence:", "  plan:", "    artifact_paths:"]
    for item in artifact_paths:
        lines.append(f"      - {_yaml_quote(str(item).strip())}")

    entrypoint_tag = str(plan.get("entrypoint") or "").strip().lower()
    reason = str(plan.get("reason") or "").strip()
    entrypoint_path = str(plan.get("entrypoint_path") or "").strip()
    if entrypoint_tag == "none":
        lines.append("    entrypoint: none")
        lines.append(f"    reason: {_yaml_quote(reason)}")
    else:
        lines.append(f"    entrypoint_path: {_yaml_quote(entrypoint_path)}")

    lines.extend(
        [
            "  runtime:",
            f"    integration_smoke_id: {_yaml_quote(_normalize_tbd(runtime.get('integration_smoke_id')))}",
            f"    verify_cmd: {_yaml_quote(_normalize_tbd(runtime.get('verify_cmd')))}",
            f"    expected_signal: {_yaml_quote(_normalize_tbd(runtime.get('expected_signal')))}",
        ]
    )
    return lines
def upsert_agile_detail_evidence(content: str, evidence: dict) -> str:
    text = str(content)
    frontmatter = _extract_frontmatter_block(text)
    if frontmatter.get("errors"):
        raise ValueError("; ".join(str(err) for err in frontmatter["errors"]))

    current_frontmatter = str(frontmatter.get("frontmatter") or "")
    updated_frontmatter = _upsert_frontmatter_key_block(
        current_frontmatter,
        "evidence",
        _render_agile_detail_evidence_block(evidence),
    )
    return _upsert_detail_frontmatter(text, updated_frontmatter)
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
def _update_objective_dod_status(content: str, dod_id: str, new_status: str):
    pattern = re.compile(
        (
            r"(?P<head><!--\s*dod:\s*(?P<dod>[A-Za-z0-9_-]+)\s+status:\s*)"
            r"(?P<status>\w+)"
            r"(?P<tail>\s+priority:\s*\w+"
            r"(?:\s+domain:\s*[A-Za-z0-9_\-]+)?"
            r"(?:\s+evidence_refs:\[[^\]]*\])?"
            r"\s*-->)"
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
def _extract_dod_ids_from_result_payload(result_payload: dict) -> List[str]:
    if not isinstance(result_payload, dict):
        return []

    raw_candidates: List[str] = []
    completed = result_payload.get("completed")
    if isinstance(completed, list):
        raw_candidates.extend(str(item) for item in completed)
    elif isinstance(completed, str):
        raw_candidates.extend(_split_csv_values(completed))

    target_dod = result_payload.get("target_dod")
    if isinstance(target_dod, str) and target_dod.strip():
        raw_candidates.append(target_dod)

    normalized: List[str] = []
    seen = set()
    for token in raw_candidates:
        try:
            dod_id = _normalize_dod_id(token)
        except ValueError:
            continue
        if dod_id in seen:
            continue
        seen.add(dod_id)
        normalized.append(dod_id)
    return normalized
def _emit_unlock_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "FAIL").upper()
    if status == "PASS":
        print(f"UNLOCKED: {payload.get('dod_id')}")
    else:
        errors = payload.get("errors") or []
        print(str(errors[0]) if errors else "FAIL")
    dependents = payload.get("dependents_marked") or []
    print(f"dependents_marked: {len(dependents)}")
    print(f"reopened_count: {payload.get('reopened_count', 0)}")
def _emit_revalidate_done_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "FAIL").upper()
    if status == "PASS":
        print(f"REVALIDATED: {payload.get('dod_id')}")
    else:
        errors = payload.get("errors") or []
        print(str(errors[0]) if errors else "FAIL")
def _load_agile_recall_config() -> dict:
    agile_config = _load_agile_config_merged()
    recall = agile_config.get("recall")
    return recall if isinstance(recall, dict) else {}
def _load_auto_mode_config() -> dict:
    config = _load_config_for_get()
    auto_mode = config.get("auto_mode") if isinstance(config, dict) else {}
    return auto_mode if isinstance(auto_mode, dict) else {}
def _load_agile_unlock_config() -> dict:
    agile_config = _load_agile_config_merged()
    unlock = agile_config.get("unlock")
    return unlock if isinstance(unlock, dict) else {}
def _agi_recall_dir(agi_id: str) -> Path:
    return _agi_session_dir(agi_id) / "recall"
def _agi_recall_history_path(agi_id: str) -> Path:
    return _agi_recall_dir(agi_id) / "history.json"
def _agi_recall_pending_manifest_path(agi_id: str) -> Path:
    return _agi_recall_dir(agi_id) / "pending-level2-manifest.json"
def _agi_recall_pending_manifest_path_for_level(agi_id: str, level: int) -> Path:
    level_int = max(2, int(level))
    return _agi_recall_dir(agi_id) / f"pending-level{level_int}-manifest.json"
def _agi_recall_invocation_log_path(agi_id: str) -> Path:
    return _agi_recall_dir(agi_id) / "agile-plan-patch.ndjson"
def _safe_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(parsed) or math.isinf(parsed):
        return float(default)
    return parsed
def _clamp_int(min_value: int, max_value: int, value: int) -> int:
    return max(min_value, min(max_value, int(value)))
def _count_session_sprints(agi_id: str) -> int:
    sprint_root = _agi_session_dir(agi_id) / "sprints"
    if not sprint_root.exists():
        return 0
    count = 0
    for candidate in sprint_root.glob("S*"):
        if not candidate.is_dir():
            continue
        if re.fullmatch(r"S\d+", candidate.name):
            count += 1
    return count
def _compute_recall_project_size(session: dict, agi_id: str) -> int:
    current_sprint_raw = 0
    if isinstance(session, dict):
        current_sprint_raw = session.get("current_sprint", 0)
    try:
        current_sprint = int(current_sprint_raw)
    except (TypeError, ValueError):
        current_sprint = 0
    return max(1, current_sprint, _count_session_sprints(agi_id))
def _compute_recall_cooldown(project_size: int, ratio: float) -> int:
    raw = math.ceil(project_size * ratio)
    return _clamp_int(1, 4, raw)
def _compute_recall_cap(project_size: int, ratio: float) -> int:
    raw = math.ceil(project_size * ratio)
    return _clamp_int(3, 6, raw)
def _create_recall_rollback_token() -> Path:
    state_payload = load_json(_agile_state_ledger_path())
    if state_payload is None:
        state_payload = []
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_path = agile_dir() / "snapshots" / f"{token}.json"
    save_json(snapshot_path, state_payload)
    return snapshot_path
def _load_agile_recall_history(agi_id: str) -> list[dict]:
    data = load_json(_agi_recall_history_path(agi_id))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]
def _save_agile_recall_history(agi_id: str, rows: list[dict]):
    save_json(_agi_recall_history_path(agi_id), rows)
def _find_last_successful_recall(history: list[dict]) -> Optional[dict]:
    for entry in reversed(history):
        if str(entry.get("status") or "").upper() == "PASS":
            return entry
    return None
def _is_within_cooldown_window(current_sprint: int, candidate_sprint: int, cooldown_window: int) -> bool:
    window = max(1, int(cooldown_window))
    return current_sprint - int(candidate_sprint) < window
def _is_evidence_hard_fail(reason: str, trigger: str) -> bool:
    if str(reason or "").strip().lower() != "fail":
        return False
    normalized = str(trigger or "").strip().lower()
    if not normalized:
        return False
    if "evidence" not in normalized:
        return False
    return any(token in normalized for token in _RECALL_HARD_FAIL_TOKENS)
def _extract_manifest_dod_actions(manifest: dict) -> list[dict]:
    actions: list[dict] = []

    direct_actions = manifest.get("dod_actions")
    if isinstance(direct_actions, list):
        for item in direct_actions:
            if isinstance(item, dict):
                actions.append(dict(item))

    dod_patch = manifest.get("dod_patch")
    if isinstance(dod_patch, dict):
        for op_name, raw_entries in dod_patch.items():
            if not isinstance(raw_entries, list):
                continue
            for raw_entry in raw_entries:
                if not isinstance(raw_entry, dict):
                    continue
                entry = dict(raw_entry)
                entry.setdefault("op", str(op_name))
                actions.append(entry)
    return actions
def _estimate_done_modifications(manifest: dict, done_dod_ids: set[str]) -> int:
    stats = manifest.get("stats")
    if isinstance(stats, dict):
        raw = stats.get("done_dod_modifications")
        if isinstance(raw, int) and raw >= 0:
            return raw

    count = 0
    for action in _extract_manifest_dod_actions(manifest):
        if bool(action.get("affects_done")):
            raw_count = action.get("count", 1)
            try:
                action_count = int(raw_count)
            except (TypeError, ValueError):
                action_count = 1
            count += max(1, action_count)
            continue

        touched: set[str] = set()
        for key in ("dod_id", "source_dod", "target_dod", "left_dod", "right_dod"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                touched.add(value.strip().upper())
        for key in ("dod_ids", "targets", "sources", "split_from", "merge_from"):
            value = action.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and item.strip():
                    touched.add(item.strip().upper())
        done_hits = touched.intersection(done_dod_ids)
        if done_hits:
            count += len(done_hits)
            continue

        op_name = str(action.get("op") or "").strip().lower()
        status = str(action.get("status") or action.get("target_status") or "").strip().lower()
        if status == "done" and op_name in {"remove", "reorder", "split", "merge"}:
            count += 1
    return count
def _collect_manifest_touched_done_dods(manifest: dict, done_dod_ids: set[str]) -> set[str]:
    touched_done: set[str] = set()
    for action in _extract_manifest_dod_actions(manifest):
        touched: set[str] = set()
        for key in ("dod_id", "source_dod", "target_dod", "left_dod", "right_dod"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                touched.add(value.strip().upper())
        for key in ("dod_ids", "targets", "sources", "split_from", "merge_from"):
            value = action.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and item.strip():
                    touched.add(item.strip().upper())
        for dod_id in touched.intersection(done_dod_ids):
            touched_done.add(dod_id)
    return touched_done
def _extract_objective_scope_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(r"[A-Za-z0-9가-힣]+", str(text or "").lower()):
        token = raw_token.strip()
        if len(token) < 2:
            continue
        if token in _RECALL_OBJECTIVE_STOPWORDS:
            continue
        tokens.add(token)
    return tokens
def _manifest_exceeds_level2_scope(manifest: dict) -> bool:
    if bool(manifest.get("level2_scope_exceeded")):
        return True

    refinements = manifest.get("objective_refinements")
    if not isinstance(refinements, list):
        objective_patch = manifest.get("objective_patch")
        if isinstance(objective_patch, dict):
            refinements = objective_patch.get("refinements")
    if not isinstance(refinements, list):
        return False

    for item in refinements:
        if not isinstance(item, dict):
            continue
        if bool(item.get("semantic_change")):
            return True

        signal = " ".join(
            str(item.get(key) or "")
            for key in ("change_type", "intent", "mode", "type", "note")
        ).lower()
        if any(keyword in signal for keyword in ("semantic", "pivot", "reframe", "essence change", "본질 변경")):
            return True

        before = str(item.get("before") or "").strip()
        after = str(item.get("after") or "").strip()
        if before and after:
            before_tokens = _extract_objective_scope_tokens(before)
            after_tokens = _extract_objective_scope_tokens(after)
            if before_tokens and after_tokens:
                overlap = len(before_tokens.intersection(after_tokens)) / len(before_tokens)
                if overlap < 0.5:
                    return True
    return False
