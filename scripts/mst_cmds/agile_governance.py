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

def _default_level2_recall_manifest(reason: str, trigger: str) -> dict:
    trigger_token = str(trigger or "").strip()
    return {
        "level": 2,
        "reason": str(reason or "").strip().lower() or "fail",
        "trigger": trigger_token,
        "generated_at": _now_iso(),
        "dod_patch": {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        },
        "objective_refinements": [
            {
                "field": "objective.wording",
                "change_type": "precision",
                "before": "Keep objective wording precise for iterative delivery.",
                "after": "Keep objective wording precise for iterative delivery and evidence alignment.",
                "semantic_change": False,
            }
        ],
        "integration_sprint": {
            "insert": True,
            "title": "Integration Sprint",
            "rationale": f"trigger={trigger_token or 'n/a'}",
        },
        "stats": {
            "done_dod_modifications": 0,
        },
    }

def _load_level2_recall_manifest(agi_id: str, reason: str, trigger: str) -> dict:
    pending_path = _agi_recall_pending_manifest_path(agi_id)
    loaded = load_json(pending_path)
    if loaded is None:
        return _default_level2_recall_manifest(reason, trigger)
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid recall manifest: {pending_path}")
    manifest = dict(loaded)
    manifest.setdefault("level", 2)
    manifest.setdefault("reason", str(reason or "").strip().lower())
    manifest.setdefault("trigger", str(trigger or "").strip())
    manifest.setdefault("generated_at", _now_iso())
    if not isinstance(manifest.get("dod_patch"), dict):
        manifest["dod_patch"] = {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        }
    if not isinstance(manifest.get("objective_refinements"), list):
        manifest["objective_refinements"] = []
    if not isinstance(manifest.get("integration_sprint"), dict):
        manifest["integration_sprint"] = {"insert": True}
    if not isinstance(manifest.get("stats"), dict):
        manifest["stats"] = {}
    return manifest

def _coerce_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    token = str(value).strip()
    return [token] if token else []

def _normalize_recall_reason_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    return token or "change"

def _load_level3_recall_manifest(agi_id: str, reason: str, trigger: str) -> dict:
    pending_path = _agi_recall_pending_manifest_path_for_level(agi_id, 3)
    loaded = load_json(pending_path)
    if loaded is None:
        raise ValueError(f"level 3 recall manifest not found: {pending_path}")
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid recall manifest: {pending_path}")

    manifest = dict(loaded)
    manifest["level"] = 3
    manifest.setdefault("reason", str(reason or "").strip().lower())
    manifest.setdefault("trigger", str(trigger or "").strip())
    manifest.setdefault("generated_at", _now_iso())
    if not isinstance(manifest.get("dod_patch"), dict):
        manifest["dod_patch"] = {
            "add": [],
            "remove": [],
            "reorder": [],
            "split": [],
            "merge": [],
        }
    if not isinstance(manifest.get("objective_refinements"), list):
        manifest["objective_refinements"] = []
    manifest["affected_dods"] = _coerce_string_list(manifest.get("affected_dods"))
    manifest["drift_evidence"] = _coerce_string_list(manifest.get("drift_evidence"))
    return manifest

def _compute_objective_semantic_hash(content: str) -> str:
    entries = _extract_objective_surface_entries(content)
    if entries:
        canonical = "\n".join(_normalize_drift_surface_entry(entry).lower() for entry in entries)
    else:
        canonical = re.sub(r"\s+", " ", str(content or "").strip()).lower()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

def _upsert_objective_frontmatter_fields(content: str, fields: dict[str, object]) -> str:
    frontmatter = _extract_frontmatter_block(content)
    errors = list(frontmatter.get("errors") or [])
    if errors:
        raise ValueError("; ".join(str(err) for err in errors))

    frontmatter_text = str(frontmatter.get("frontmatter") or "")
    for key, value in fields.items():
        if isinstance(value, bool):
            rendered_value = "true" if value else "false"
        elif isinstance(value, int):
            rendered_value = str(value)
        else:
            rendered_value = _yaml_quote(str(value))
        frontmatter_text = _upsert_frontmatter_key_block(frontmatter_text, key, [f"{key}: {rendered_value}"])
    return _upsert_detail_frontmatter(content, frontmatter_text)

def _apply_level3_objective_refinements(content: str, manifest: dict) -> tuple[str, list[dict]]:
    updated_content = str(content or "")
    diff_rows: list[dict] = []

    refinements = manifest.get("objective_refinements")
    if not isinstance(refinements, list):
        return updated_content, diff_rows

    for raw_item in refinements:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        before = str(item.get("before") or "")
        after = str(item.get("after") or "")
        applied = False
        if before and after and before in updated_content:
            updated_content = updated_content.replace(before, after, 1)
            applied = True
        diff_rows.append(
            {
                "field": str(item.get("field") or ""),
                "change_type": str(item.get("change_type") or ""),
                "before": before,
                "after": after,
                "semantic_change": bool(item.get("semantic_change")),
                "applied": applied,
            }
        )
    return updated_content, diff_rows

def _collect_level3_affected_dods(manifest: dict, done_dod_ids: set[str]) -> list[str]:
    affected: list[str] = []
    seen = set()

    for token in _coerce_string_list(manifest.get("affected_dods")):
        try:
            dod_id = _normalize_dod_id(token)
        except ValueError:
            continue
        if dod_id in seen:
            continue
        seen.add(dod_id)
        affected.append(dod_id)

    for dod_id in sorted(_collect_manifest_touched_done_dods(manifest, done_dod_ids)):
        if dod_id in seen:
            continue
        seen.add(dod_id)
        affected.append(dod_id)
    return affected

def _build_level3_diff_payload(manifest: dict, objective_diff: list[dict]) -> dict:
    dod_patch = manifest.get("dod_patch") if isinstance(manifest.get("dod_patch"), dict) else {}
    dod_summary = {}
    for op_name, entries in dod_patch.items():
        if isinstance(entries, list) and entries:
            dod_summary[str(op_name)] = len(entries)
    return {
        "objective_refinements": objective_diff,
        "dod_patch": dod_summary,
    }

def _build_level3_approval_payload(
    manifest: dict,
    current_objective: str,
    done_dod_ids: set[str],
    *,
    reason: str,
    trigger: str,
    auto_mode_request: bool,
) -> dict:
    preview_content, objective_diff = _apply_level3_objective_refinements(current_objective, manifest)
    before_hash = _compute_objective_semantic_hash(current_objective)
    after_hash = _compute_objective_semantic_hash(preview_content)
    return {
        "approval_required": True,
        "level": 3,
        "reason": str(reason or "").strip(),
        "trigger": str(trigger or "").strip(),
        "before_hash": before_hash,
        "after_hash": after_hash,
        "diff": _build_level3_diff_payload(manifest, objective_diff),
        "affected_dods": _collect_level3_affected_dods(manifest, done_dod_ids),
        "drift_evidence": _coerce_string_list(manifest.get("drift_evidence")),
        "auto_mode": auto_mode_request,
    }

def _write_level3_history_entry(
    agi_id: str,
    *,
    event_token: str,
    reason: str,
    event_id: str,
    before_hash: str,
    after_hash: str,
    diff: dict,
    affected_dods: list[str],
    drift_evidence: list[str],
    approval_ticket: str,
) -> Path:
    history_dir = _agi_session_dir(agi_id) / "objective" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{event_token}_L3_{_normalize_recall_reason_token(reason)}.json"
    save_json(
        history_path,
        {
            "event_id": event_id,
            "level": 3,
            "approval_ticket": str(approval_ticket or "").strip(),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "diff": diff,
            "affected_dods": list(affected_dods),
            "drift_evidence": list(drift_evidence),
        },
    )
    return history_path

def _compute_level3_cooldown(project_size: int, recall_cfg: dict) -> int:
    base_cooldown = _compute_recall_cooldown(
        project_size,
        _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
    )
    multiplier = recall_cfg.get("level3_cooldown_multiplier", _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER)
    try:
        multiplier_value = int(multiplier)
    except (TypeError, ValueError):
        multiplier_value = _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER
    return base_cooldown * max(1, multiplier_value)

def _classify_change_manifest(manifest: dict, recall_cfg: dict) -> dict:
    level = 2
    confidence = 0.78
    summary = "Objective wording remains semantically stable; DoD patch stays within Level 2."

    if _manifest_exceeds_level2_scope(manifest):
        level = 3
        confidence = 0.92
        summary = "JTBD core intent changed; objective essence was redefined and requires Level 3 approval."

    payload = {
        "level": level,
        "confidence": confidence,
        "summary": summary,
    }

    project_size_raw = manifest.get("project_size")
    if project_size_raw is not None:
        try:
            project_size = max(1, int(project_size_raw))
        except (TypeError, ValueError):
            project_size = None
        if project_size is not None:
            level2_cooldown_raw = manifest.get("level2_cooldown")
            if level2_cooldown_raw is not None:
                try:
                    level2_cooldown = max(1, int(level2_cooldown_raw))
                except (TypeError, ValueError):
                    level2_cooldown = _compute_recall_cooldown(
                        project_size,
                        _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
                    )
            else:
                level2_cooldown = _compute_recall_cooldown(
                    project_size,
                    _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO),
                )
            multiplier = recall_cfg.get("level3_cooldown_multiplier", _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER)
            try:
                multiplier_value = max(1, int(multiplier))
            except (TypeError, ValueError):
                multiplier_value = _RECALL_DEFAULT_LEVEL3_COOLDOWN_MULTIPLIER
            payload["cooldown"] = level2_cooldown * multiplier_value
    return payload

def _record_agile_plan_patch_invocation(
    agi_id: str,
    *,
    level: int,
    reason: str,
    trigger: str,
    manifest_path: Path,
) -> dict:
    invocation_id = f"recall-{uuid.uuid4().hex[:12]}"
    payload = {
        "timestamp": _now_iso(),
        "invocation_id": invocation_id,
        "mode": "patch",
        "level": int(level),
        "reason": str(reason or "").strip(),
        "trigger": str(trigger or "").strip(),
        "manifest_path": str(manifest_path),
    }
    _append_ndjson(_agi_recall_invocation_log_path(agi_id), payload)
    return {
        "called": True,
        "invocation_id": invocation_id,
        "log_path": str(_agi_recall_invocation_log_path(agi_id)),
    }

def _emit_recall_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "FAIL").upper()
    if status == "PASS":
        print("PASS")
    elif status == "SKIP":
        print("WARN: recall disabled")
    else:
        errors = payload.get("errors") or []
        print(str(errors[0]) if errors else "FAIL")
    print(f"agi_id: {payload.get('agi_id') or '-'}")
    print(f"reason: {payload.get('reason') or '-'}")
    print(f"trigger: {payload.get('trigger') or '-'}")
    print(f"cooldown: {payload.get('cooldown_window')}")
    print(f"cap: {payload.get('cap_used')}/{payload.get('cap_limit')}")

def _resolve_agi_target(agi_id_raw: Optional[str]) -> str:
    if agi_id_raw:
        agi_id = _normalize_agi_id(str(agi_id_raw))
    else:
        agi_id = _find_latest_agi_id()
        if agi_id is None:
            raise ValueError("AGI session not found; provide --agi-id")
    _load_agile_session(agi_id)
    return agi_id

def _detail_file_for_dod(details_dir: Path, dod_id: str) -> Path:
    direct = details_dir / f"{dod_id}.md"
    if direct.exists() and direct.is_file():
        return direct

    for candidate in sorted(details_dir.glob("*.md")):
        if candidate.stem.upper() == dod_id:
            return candidate
    raise ValueError(f"detail file not found for {dod_id}")

def _detail_frontmatter_or_fail(content: str) -> tuple[dict, str]:
    parsed = parse_agile_detail_metadata(content)
    frontmatter = _extract_frontmatter_block(content)
    errors = list(frontmatter.get("errors") or [])
    errors.extend(parsed.get("errors") or [])
    if errors:
        raise ValueError("; ".join(str(err) for err in errors))
    if not frontmatter.get("has_frontmatter"):
        raise ValueError("detail frontmatter is missing")
    return parsed, str(frontmatter.get("frontmatter") or "")

def _frontmatter_truthy(frontmatter: str, key: str) -> bool:
    value = _extract_yaml_scalar(frontmatter, key)
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}

def _frontmatter_int(frontmatter: str, key: str, default: int = 0) -> int:
    value = _extract_yaml_scalar(frontmatter, key)
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default

def _load_unlock_forbidden_patterns(unlock_cfg: dict) -> list[str]:
    raw_patterns = unlock_cfg.get("forbidden_patterns") if isinstance(unlock_cfg, dict) else None
    if isinstance(raw_patterns, list):
        patterns = [str(token).strip().lower() for token in raw_patterns if str(token).strip()]
        if patterns:
            return patterns
    return list(_UNLOCK_FORBIDDEN_REASON_PATTERNS)

def _reason_has_forbidden_pattern(reason: str, patterns: list[str]) -> bool:
    normalized = str(reason or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9가-힣]+", " ", normalized)
    tokens = {token for token in normalized.split() if token}
    for pattern in patterns:
        target = str(pattern or "").strip().lower()
        if not target:
            continue
        if target in tokens:
            return True
        if re.search(rf"\b{re.escape(target)}\b", normalized):
            return True
    return False

def _validate_unlock_reason(reason: str, forbidden_patterns: list[str]) -> Optional[str]:
    token = str(reason or "").strip()
    if not token:
        return "reason required (min 20 chars)"
    if len(token) < 20 or len(token) > 500:
        return "reason rejected (too short or forbidden pattern)"
    if _reason_has_forbidden_pattern(token, forbidden_patterns):
        return "reason rejected (too short or forbidden pattern)"
    return None

def _validate_unlock_evidence(category: str, evidence: str) -> Optional[str]:
    category_token = str(category or "").strip()
    evidence_token = str(evidence or "").strip()
    hint = _UNLOCK_CATEGORY_HINTS.get(category_token, "supporting evidence")

    fail_message = f"evidence required for category {category_token} ({hint})"
    if not evidence_token:
        return fail_message

    parts = _split_csv_values(evidence_token)
    if category_token == "upstream_evidence_changed":
        if len(parts) < 2:
            return fail_message
        try:
            _normalize_dod_id(parts[0])
        except ValueError:
            return fail_message
        return None
    if category_token == "integration_regression":
        if len(parts) < 2:
            return fail_message
        return None
    if category_token == "new_dependency_dod":
        if not parts:
            return fail_message
        try:
            _normalize_dod_id(parts[0])
        except ValueError:
            return fail_message
        return None
    if category_token == "objective_precision_fix":
        if not parts:
            return fail_message
        return None
    return f"invalid unlock category: {category_token}"

def _increment_agile_state_reopened_count() -> int:
    entries, reopened_count, _ = _load_agile_state_payload()
    updated_count = reopened_count + 1
    _save_agile_state_payload(entries, updated_count, as_dict=True)
    return updated_count

def _recall_done_dods_missing_unlock(agi_id: str, done_dod_ids: set[str]) -> list[str]:
    if not done_dod_ids:
        return []

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    missing: list[str] = []
    for dod_id in sorted(done_dod_ids):
        try:
            detail_file = _detail_file_for_dod(details_dir, dod_id)
            content = detail_file.read_text(encoding="utf-8")
            _, frontmatter = _detail_frontmatter_or_fail(content)
        except (OSError, UnicodeDecodeError, ValueError):
            missing.append(dod_id)
            continue

        status = str(_extract_yaml_scalar(frontmatter, "status") or "").strip().lower()
        history = _parse_unlock_history(frontmatter)
        if status != "in_progress" or not history:
            missing.append(dod_id)
    return missing

def cmd_agile_unlock(args):
    payload = {
        "status": "FAIL",
        "agi_id": None,
        "dod_id": None,
        "detail_path": None,
        "category": str(args.category or "").strip(),
        "reason": str(args.reason or "").strip(),
        "evidence": str(args.evidence or "").strip(),
        "reopened_count": 0,
        "dependents_marked": [],
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_unlock_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    try:
        dod_id = _normalize_dod_id(str(args.dod))
    except ValueError as exc:
        return _fail(str(exc))
    payload["dod_id"] = dod_id

    unlock_cfg = _load_agile_unlock_config()
    if not bool(unlock_cfg.get("enabled", True)):
        return _fail("unlock disabled by config")

    reason_error = _validate_unlock_reason(args.reason, _load_unlock_forbidden_patterns(unlock_cfg))
    if reason_error:
        return _fail(reason_error)

    evidence_error = _validate_unlock_evidence(args.category, args.evidence)
    if evidence_error:
        return _fail(evidence_error)

    try:
        agi_id = _resolve_agi_target(args.agi_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["agi_id"] = agi_id

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    if not details_dir.exists():
        return _fail(f"details dir not found: {details_dir}")
    if not details_dir.is_dir():
        return _fail(f"details dir is not a directory: {details_dir}")

    try:
        detail_path = _detail_file_for_dod(details_dir, dod_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["detail_path"] = str(detail_path)

    try:
        current_content = detail_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"failed to read detail: {exc}")

    try:
        parsed, frontmatter = _detail_frontmatter_or_fail(current_content)
    except ValueError as exc:
        return _fail(str(exc))

    if parsed.get("evidence"):
        current_content = upsert_agile_detail_evidence(current_content, parsed.get("evidence"))
        try:
            _, frontmatter = _detail_frontmatter_or_fail(current_content)
        except ValueError as exc:
            return _fail(str(exc))

    current_status = str(_extract_yaml_scalar(frontmatter, "status") or "").strip().lower()
    if current_status != "done":
        return _fail(f"unlock allowed only for done DoD (current status: {current_status or 'unknown'})")

    history = _parse_unlock_history(frontmatter)
    history.append(
        {
            "timestamp": _now_iso(),
            "category": str(args.category).strip(),
            "reason": str(args.reason).strip(),
            "evidence": str(args.evidence).strip(),
        }
    )

    reopened_count = max(_frontmatter_int(frontmatter, "reopened_count", 0) + 1, len(history))
    updated_frontmatter = _remove_frontmatter_key_block(frontmatter, "revalidation_required")
    updated_frontmatter = _upsert_frontmatter_key_block(updated_frontmatter, "status", ["status: in_progress"])
    updated_frontmatter = _upsert_frontmatter_key_block(
        updated_frontmatter,
        "unlock_history",
        _render_unlock_history_block(history),
    )
    updated_frontmatter = _upsert_frontmatter_key_block(
        updated_frontmatter,
        "reopened_count",
        [f"reopened_count: {reopened_count}"],
    )

    updated_content = _upsert_detail_frontmatter(current_content, updated_frontmatter)
    try:
        detail_path.write_text(updated_content, encoding="utf-8")
    except OSError as exc:
        return _fail(f"failed to write detail: {exc}")

    dependents_marked: list[str] = []
    for candidate in sorted(details_dir.glob("*.md")):
        if candidate == detail_path:
            continue
        try:
            raw = candidate.read_text(encoding="utf-8")
            _, candidate_frontmatter = _detail_frontmatter_or_fail(raw)
        except (OSError, UnicodeDecodeError, ValueError):
            continue

        blocked_by = _extract_yaml_list(candidate_frontmatter, "blocked_by") or []
        blocked_set = set()
        for token in blocked_by:
            try:
                blocked_set.add(_normalize_dod_id(str(token)))
            except ValueError:
                continue
        if dod_id not in blocked_set:
            continue

        if _frontmatter_truthy(candidate_frontmatter, "revalidation_required"):
            dependents_marked.append(candidate.stem.upper())
            continue

        candidate_frontmatter = _upsert_frontmatter_key_block(
            candidate_frontmatter,
            "revalidation_required",
            ["revalidation_required: true"],
        )
        patched = _upsert_detail_frontmatter(raw, candidate_frontmatter)
        try:
            candidate.write_text(patched, encoding="utf-8")
        except OSError:
            continue
        dependents_marked.append(candidate.stem.upper())

    global_reopened_count = _increment_agile_state_reopened_count()
    _append_agile_event(
        agi_id,
        "agile.unlock",
        {
            "dod_id": dod_id,
            "category": str(args.category).strip(),
            "dependents_marked": dependents_marked,
            "reopened_count": global_reopened_count,
        },
    )

    payload["status"] = "PASS"
    payload["dependents_marked"] = dependents_marked
    payload["reopened_count"] = global_reopened_count
    _emit_unlock_payload(payload, args.json)
    return 0

def cmd_agile_revalidate_done(args):
    payload = {
        "status": "FAIL",
        "agi_id": None,
        "dod_id": None,
        "detail_path": None,
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_revalidate_done_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    try:
        dod_id = _normalize_dod_id(str(args.dod))
    except ValueError as exc:
        return _fail(str(exc))
    payload["dod_id"] = dod_id

    try:
        agi_id = _resolve_agi_target(args.agi_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["agi_id"] = agi_id

    details_dir = _agi_session_dir(agi_id) / "objective" / "details"
    if not details_dir.exists():
        return _fail(f"details dir not found: {details_dir}")
    if not details_dir.is_dir():
        return _fail(f"details dir is not a directory: {details_dir}")

    try:
        detail_path = _detail_file_for_dod(details_dir, dod_id)
    except ValueError as exc:
        return _fail(str(exc))
    payload["detail_path"] = str(detail_path)

    try:
        current_content = detail_path.read_text(encoding="utf-8")
        _, frontmatter = _detail_frontmatter_or_fail(current_content)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return _fail(str(exc))

    updated_frontmatter = _remove_frontmatter_key_block(frontmatter, "revalidation_required")
    updated_content = _upsert_detail_frontmatter(current_content, updated_frontmatter)

    try:
        detail_path.write_text(updated_content, encoding="utf-8")
    except OSError as exc:
        return _fail(f"failed to write detail: {exc}")

    _append_agile_event(agi_id, "agile.revalidate_done", {"dod_id": dod_id})
    payload["status"] = "PASS"
    _emit_revalidate_done_payload(payload, args.json)
    return 0

def cmd_agile_classify_change(args):
    manifest_path = Path(str(args.manifest))
    if not manifest_path.exists():
        print(f"Error: manifest not found ({manifest_path})", file=sys.stderr)
        return 1

    loaded = load_json(manifest_path)
    if not isinstance(loaded, dict):
        print(f"Error: invalid manifest ({manifest_path})", file=sys.stderr)
        return 1

    payload = _classify_change_manifest(dict(loaded), _load_agile_recall_config())
    level = int(payload.get("level", 2))
    label = f"Level {level}"
    confidence = float(payload.get("confidence", 0.0))
    summary = str(payload.get("summary") or "").strip()

    print(label)
    print(f"confidence: {confidence:.2f}")
    if payload.get("cooldown") is not None:
        print(f"cooldown: {payload['cooldown']}")
    if summary:
        print(f"summary: {summary}")
    return 0

def cmd_agile_recall(args):
    level_raw = args.level if args.level is not None else _RECALL_DEFAULT_LEVEL
    try:
        level = int(level_raw)
    except (TypeError, ValueError):
        level = _RECALL_DEFAULT_LEVEL

    reason = str(args.reason or "").strip().lower()
    trigger = str(args.trigger or "").strip()
    approval_ticket = str(getattr(args, "approval_ticket", "") or "").strip()
    bypass_requested = bool(args.bypass_cooldown)
    fingerprint = str(args.fingerprint or trigger or "").strip()

    payload = {
        "status": "FAIL",
        "level": level,
        "agi_id": None,
        "reason": reason,
        "trigger": trigger,
        "project_size": 0,
        "sprint_index": 0,
        "cooldown_window": None,
        "cap_limit": None,
        "cap_used": 0,
        "rollback_token": None,
        "manifest_path": None,
        "agile_plan_patch": {"called": False},
        "patch_budget": {
            "done_total": 0,
            "requested_modifications": 0,
            "max_modifications": 0,
        },
        "bypass": {
            "requested": bypass_requested,
            "used": False,
            "fingerprint": fingerprint or None,
        },
        "warnings": [],
        "errors": [],
    }

    def _fail(message: str) -> int:
        payload["status"] = "FAIL"
        payload["errors"] = [str(message)]
        _emit_recall_payload(payload, args.json)
        print(str(message), file=sys.stderr)
        return 1

    if level not in {2, 3}:
        return _fail("recall level must be 2 or 3")
    if reason not in {"fail", "drift"}:
        return _fail("reason must be fail or drift")

    recall_cfg = _load_agile_recall_config()
    enabled = bool(recall_cfg.get("enabled", True))
    if not enabled:
        payload["status"] = "SKIP"
        payload["warnings"].append("recall disabled (agile.recall.enabled=false)")
        _emit_recall_payload(payload, args.json)
        print(payload["warnings"][0], file=sys.stderr)
        return 0

    try:
        if args.agi_id:
            agi_id = _normalize_agi_id(str(args.agi_id))
        else:
            agi_id = _find_latest_agi_id()
            if agi_id is None:
                raise ValueError("AGI session not found; provide --agi-id")
        session, _ = _load_agile_session(agi_id)
    except ValueError as exc:
        return _fail(str(exc))

    payload["agi_id"] = agi_id

    try:
        sprint_index = int(session.get("current_sprint", 0))
    except (TypeError, ValueError):
        sprint_index = 0
    payload["sprint_index"] = max(0, sprint_index)

    project_size = _compute_recall_project_size(session, agi_id)
    cooldown_ratio = _safe_float(recall_cfg.get("cooldown_ratio"), _RECALL_DEFAULT_COOLDOWN_RATIO)
    cap_ratio = _safe_float(recall_cfg.get("cap_ratio"), _RECALL_DEFAULT_CAP_RATIO)
    cooldown_window = (
        _compute_level3_cooldown(project_size, recall_cfg)
        if level == 3
        else _compute_recall_cooldown(project_size, cooldown_ratio)
    )
    cap_limit = _compute_recall_cap(project_size, cap_ratio)
    payload["project_size"] = project_size
    payload["cooldown_window"] = cooldown_window
    payload["cap_limit"] = cap_limit

    rollback_token_path = _create_recall_rollback_token()
    payload["rollback_token"] = str(rollback_token_path)

    history = _load_agile_recall_history(agi_id)
    cap_used = sum(1 for row in history if str(row.get("status") or "").upper() == "PASS")
    payload["cap_used"] = cap_used
    if cap_used >= cap_limit:
        return _fail("Cap exceeded, steering checkpoint required")

    last_success = _find_last_successful_recall(history)
    cooldown_active = False
    if isinstance(last_success, dict):
        try:
            last_sprint = int(last_success.get("sprint_index", -10**6))
        except (TypeError, ValueError):
            last_sprint = -10**6
        try:
            last_window = int(last_success.get("cooldown_window", cooldown_window))
        except (TypeError, ValueError):
            last_window = cooldown_window
        cooldown_active = _is_within_cooldown_window(payload["sprint_index"], last_sprint, last_window)

    if cooldown_active:
        if not bypass_requested:
            return _fail("Cooldown active")
        if not _is_evidence_hard_fail(reason, trigger):
            return _fail("Cooldown bypass allowed only for evidence hard fail")
        if not fingerprint:
            return _fail("Cooldown bypass requires fingerprint")
        for row in reversed(history):
            bypass = row.get("bypass")
            if not isinstance(bypass, dict):
                continue
            if not bool(bypass.get("used")):
                continue
            if str(bypass.get("fingerprint") or "") != fingerprint:
                continue
            try:
                row_sprint = int(row.get("sprint_index", -10**6))
            except (TypeError, ValueError):
                row_sprint = -10**6
            try:
                row_window = int(row.get("cooldown_window", cooldown_window))
            except (TypeError, ValueError):
                row_window = cooldown_window
            if _is_within_cooldown_window(payload["sprint_index"], row_sprint, row_window):
                return _fail("fingerprint already bypassed in cooldown")
        payload["bypass"]["used"] = True
    elif bypass_requested:
        payload["warnings"].append("bypass requested but cooldown inactive")

    objective_path = _agi_objective_path(agi_id)
    if not objective_path.exists():
        return _fail(f"objective file missing: {objective_path}")

    try:
        objective_content = objective_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"failed to read objective: {exc}")

    dod_items = _collect_objective_dod_items(objective_content)
    done_dod_ids = {
        dod_id
        for dod_id, meta in dod_items.items()
        if str(meta.get("status") or "").strip().lower() == "done"
    }
    done_total = len(done_dod_ids)
    patch_budget_max = min(3, math.ceil(done_total * 0.20)) if done_total > 0 else 0
    payload["patch_budget"]["done_total"] = done_total
    payload["patch_budget"]["max_modifications"] = patch_budget_max

    try:
        manifest = (
            _load_level3_recall_manifest(agi_id, reason, trigger)
            if level == 3
            else _load_level2_recall_manifest(agi_id, reason, trigger)
        )
    except ValueError as exc:
        return _fail(str(exc))

    if level == 2 and _manifest_exceeds_level2_scope(manifest):
        return _fail("Level 2 scope exceeded, use Level 3 with user approval")

    touched_done_dods = _collect_manifest_touched_done_dods(manifest, done_dod_ids)
    missing_unlock = _recall_done_dods_missing_unlock(agi_id, touched_done_dods)
    if missing_unlock:
        return _fail(f"unlock required before recall for done DoD: {', '.join(missing_unlock)}")

    requested_mods = _estimate_done_modifications(manifest, done_dod_ids)
    payload["patch_budget"]["requested_modifications"] = requested_mods
    if requested_mods > patch_budget_max:
        return _fail("Patch budget exceeded (max 3 or 20%)")

    recall_dir = _agi_recall_dir(agi_id)
    recall_dir.mkdir(parents=True, exist_ok=True)
    manifest_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = recall_dir / f"manifest-{manifest_token}.json"
    save_json(manifest_path, manifest)
    save_json(recall_dir / "manifest-latest.json", manifest)
    payload["manifest_path"] = str(manifest_path)

    auto_mode_request = bool(_load_auto_mode_config().get("request", False))
    approval_payload = None
    if level == 3:
        approval_payload = _build_level3_approval_payload(
            manifest,
            objective_content,
            done_dod_ids,
            reason=reason,
            trigger=trigger,
            auto_mode_request=auto_mode_request,
        )
        payload["approval_required"] = True
        payload["approval"] = approval_payload
        if not approval_ticket:
            message = "Level 3 requires --approval-ticket (user approval required)"
            payload["status"] = "FAIL"
            payload["errors"] = [message]
            if args.json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                print("USER APPROVAL REQUIRED")
                print(json.dumps(approval_payload, ensure_ascii=False))
            print(message, file=sys.stderr)
            return 1

    patch_call = _record_agile_plan_patch_invocation(
        agi_id,
        level=level,
        reason=reason,
        trigger=trigger,
        manifest_path=manifest_path,
    )
    payload["agile_plan_patch"] = patch_call

    objective_version = None
    event_id = None
    objective_history_path = None
    if level == 3 and approval_payload is not None:
        updated_objective, objective_diff = _apply_level3_objective_refinements(objective_content, manifest)
        event_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        event_id = f"EVT-L3-{event_token}"

        frontmatter = _extract_frontmatter_block(objective_content)
        frontmatter_text = str(frontmatter.get("frontmatter") or "")
        version_raw = _extract_yaml_scalar(frontmatter_text, "version")
        if version_raw is None:
            objective_data = session.get("objective") if isinstance(session.get("objective"), dict) else {}
            version_raw = objective_data.get("version", 0)
        try:
            current_version = int(version_raw)
        except (TypeError, ValueError):
            current_version = 0
        objective_version = current_version + 1

        updated_objective = _upsert_objective_frontmatter_fields(
            updated_objective,
            {
                "version": objective_version,
                "last_event_id": event_id,
                "semantic_hash": approval_payload["after_hash"],
            },
        )
        try:
            objective_path.write_text(updated_objective, encoding="utf-8")
        except OSError as exc:
            return _fail(f"failed to write objective: {exc}")

        objective_data = session.get("objective")
        if not isinstance(objective_data, dict):
            objective_data = {"path": "objective/objective.md"}
            session["objective"] = objective_data
        objective_data["version"] = objective_version
        _save_agile_session(agi_id, session)

        objective_history_path = _write_level3_history_entry(
            agi_id,
            event_token=event_token,
            reason=reason,
            event_id=event_id,
            before_hash=approval_payload["before_hash"],
            after_hash=approval_payload["after_hash"],
            diff=_build_level3_diff_payload(manifest, objective_diff),
            affected_dods=list(approval_payload["affected_dods"]),
            drift_evidence=list(approval_payload["drift_evidence"]),
            approval_ticket=approval_ticket,
        )
        payload["objective"] = {
            "version": objective_version,
            "last_event_id": event_id,
            "semantic_hash": approval_payload["after_hash"],
            "history_path": str(objective_history_path),
        }

    history_entry = {
        "timestamp": _now_iso(),
        "status": "PASS",
        "level": level,
        "agi_id": agi_id,
        "sprint_index": payload["sprint_index"],
        "reason": reason,
        "trigger": trigger,
        "cooldown_window": cooldown_window,
        "cap_limit": cap_limit,
        "rollback_token": str(rollback_token_path),
        "manifest_path": str(manifest_path),
        "bypass": {
            "requested": bypass_requested,
            "used": bool(payload["bypass"]["used"]),
            "fingerprint": fingerprint or None,
        },
        "patch_budget": dict(payload["patch_budget"]),
    }
    if level == 3:
        history_entry["approval_ticket"] = approval_ticket
        history_entry["objective_version"] = objective_version
        history_entry["last_event_id"] = event_id
    history.append(history_entry)
    _save_agile_recall_history(agi_id, history)

    _append_agile_event(
        agi_id,
        "agile.recall",
        {
            "status": "PASS",
            "level": level,
            "reason": reason,
            "trigger": trigger,
            "bypass": bool(payload["bypass"]["used"]),
            "approval_ticket": approval_ticket or None,
            "last_event_id": event_id,
        },
    )
    _append_agile_sprint_log(
        {
            "timestamp": _now_iso(),
            "event": "agile-recall",
            "agi_id": agi_id,
            "reason": reason,
            "trigger": trigger,
            "manifest_path": str(manifest_path),
            "level": level,
        }
    )

    payload["status"] = "PASS"
    _emit_recall_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    return 0

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

    story_upper = str(args.story or "").upper()
    evidence_refs_arg = getattr(args, "evidence_ref", []) or []
    if evidence_refs_arg:
        marker_pattern = re.compile(
            (
                rf"(<!--\s*dod:\s*{re.escape(story_upper)}\s+[^>]*?)"
                r"(?:\s+evidence_refs:\[([^\]]*)\])?"
                r"\s*(-->)"
            ),
            re.IGNORECASE,
        )

        def _replace_marker(match):
            prefix = match.group(1).rstrip()
            existing_refs = match.group(2)
            existing_list = [r.strip() for r in existing_refs.split(",")] if existing_refs else []
            existing_list = [r for r in existing_list if r]
            seen = set(existing_list)
            merged = list(existing_list)
            for ref in evidence_refs_arg:
                ref = str(ref).strip()
                if ref and ref not in seen:
                    merged.append(ref)
                    seen.add(ref)
            evidence_str = ",".join(merged)
            return f"{prefix} evidence_refs:[{evidence_str}] {match.group(3)}"

        updated_content = marker_pattern.sub(_replace_marker, updated_content, count=1)

    deferred_promoted: List[str] = []
    deferred_sprints: List[str] = []

    if getattr(args, "deferred_promote", False):
        if args.sprint is None:
            print("Error: --deferred-promote requires --sprint", file=sys.stderr)
            return 1
        if args.sprint < 0:
            print("Error: --sprint must be >= 0", file=sys.stderr)
            return 1

        streak_limit = _load_agile_int_config("foundational_streak_max", 2) + 1
        sprint_cursor = int(args.sprint) - 1
        chain_payloads: List[tuple[str, dict]] = []
        while sprint_cursor >= 0 and len(chain_payloads) < streak_limit:
            sprint_id = f"S{sprint_cursor:02d}"
            result_path = _agi_session_dir(agi_id) / "sprints" / sprint_id / "result.json"
            result_payload = load_json(result_path)
            if not isinstance(result_payload, dict):
                break
            sprint_kind = str(result_payload.get("sprint_kind", "user_observable")).strip().lower()
            if sprint_kind != "foundational":
                break
            deferred_sprints.append(sprint_id)
            chain_payloads.append((sprint_id, result_payload))
            sprint_cursor -= 1

        working_items = _collect_objective_dod_items(updated_content)
        for _, result_payload in chain_payloads:
            for candidate_dod in _extract_dod_ids_from_result_payload(result_payload):
                status = str(working_items.get(candidate_dod, {}).get("status", "")).strip().lower()
                if status != "proposed_done":
                    continue
                updated_content, candidate_found, candidate_changed = _update_objective_dod_status(
                    updated_content,
                    candidate_dod,
                    "done",
                )
                if not candidate_found or not candidate_changed:
                    continue
                deferred_promoted.append(candidate_dod)
                item = working_items.get(candidate_dod)
                if isinstance(item, dict):
                    item["status"] = "done"

        if deferred_promoted:
            deduped: List[str] = []
            seen = set()
            for dod in deferred_promoted:
                if dod in seen:
                    continue
                seen.add(dod)
                deduped.append(dod)
            deferred_promoted = sorted(deduped)

    overall_changed = changed or bool(deferred_promoted)
    if overall_changed:
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
    if getattr(args, "deferred_promote", False):
        _append_ndjson(
            _agi_objective_changelog_path(agi_id),
            {
                "timestamp": _now_iso(),
                "event": "deferred-promote",
                "sprint": f"S{int(args.sprint):02d}" if args.sprint is not None and args.sprint >= 0 else None,
                "sprints": deferred_sprints,
                "dods": deferred_promoted,
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
    if getattr(args, "deferred_promote", False):
        output["deferred_promote"] = {
            "sprints": deferred_sprints,
            "dods": deferred_promoted,
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

    requested_dod_id = getattr(args, "dod_id", None)
    if requested_dod_id:
        dod_key = requested_dod_id.upper()
        if dod_key not in dod_items:
            print(f"Error: DoD '{requested_dod_id}' not found", file=sys.stderr)
            return 1
        item = dod_items[dod_key]
        single_output = {
            "agi_id": agi_id,
            "dod_id": dod_key,
            "status": item.get("status"),
            "priority": item.get("priority"),
            "domain": item.get("domain", "unknown"),
            "evidence_refs": item.get("evidence_refs", []),
        }
        if args.json:
            print(json.dumps(single_output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(single_output, ensure_ascii=False))
        return 0

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
        return 0

    incomplete = sorted([
        dod_id for dod_id, item in dod_items.items()
        if item.get("status", "").lower() not in {"done", "completed"}
    ])
    status_only = {dod_id: item.get("status") for dod_id, item in dod_items.items()}
    legacy_dods = {}
    for dod_id, item in dod_items.items():
        if not isinstance(item, dict):
            legacy_dods[dod_id] = item
            continue
        item_copy = dict(item)
        item_copy.pop("evidence_refs", None)
        legacy_dods[dod_id] = item_copy
    output = {
        "agi_id": agi_id,
        "all_done": len(incomplete) == 0,
        "incomplete": incomplete,
        "dods": legacy_dods,
        "stories": status_only,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False))
    return 0

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
