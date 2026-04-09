from __future__ import annotations

import argparse
import copy
import fcntl
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
    _agi_links_path,
    _agi_objective_path,
    _agi_session_dir,
    _agile_state_ledger_path,
    _append_agile_event,
    _append_agile_sprint_log,
    _collect_objective_dod_items,
    _extract_objective_surface_entries,
    _find_latest_agi_id,
    _load_agile_config_cast,
    _load_agile_config_merged,
    _load_agile_int_config,
    _load_agile_session,
    _load_agile_state_payload,
    _normalize_agi_id,
    _normalize_link_id,
    _normalize_tbd,
    _now_iso,
    _plugin_root,
    _save_agile_state_payload,
    _split_csv_values,
    load_json,
    parse_agile_detail_metadata,
    parse_source_mapping,
    save_json,
)

_H12_HEADER_RE = re.compile(r"^(#{1,2})\s+(.+?)$", flags=re.MULTILINE)

_CHUNK_MARKER_RE = re.compile(r"<!-- chunk:(\d+) -->")

_EVIDENCE_LEGACY_WARNING = "evidence fields not defined (legacy format)"

_GOODHART_DUMMY_VERIFY_ERROR = "Goodhart linter: verify_cmd rejected (dummy command)"

_DEFAULT_REQUIRED_GLOBS_BY_PROJECT_TYPE = {
    "plugin": ["skills/*/SKILL.md"],
}

_DRIFT_SURFACE_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")

_DRIFT_SURFACE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "when",
    "want",
    "can",
    "to",
    "so",
    "is",
    "are",
    "of",
    "on",
    "in",
    "it",
    "do",
    "be",
    "i",
    "we",
    "you",
    "사용자",
    "프로젝트",
    "기준",
    "완료",
    "레이어",
}

def _is_dummy_verify_cmd(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(value).strip().lower())
    if normalized in {"true", "exit 0"}:
        return True
    if not normalized.startswith("echo"):
        return False
    shell_control_tokens = ("&&", "||", ";", "|", "`", "$(")
    return not any(token in normalized for token in shell_control_tokens)

def _render_agile_detail_evidence_frontmatter(evidence: dict) -> str:
    return "\n".join(["---", *_render_agile_detail_evidence_block(evidence), "---", ""])

def validate_agile_detail_evidence(parsed_metadata: dict) -> dict:
    warnings = []
    errors = list(parsed_metadata.get("errors") or [])
    evidence = parsed_metadata.get("evidence") if isinstance(parsed_metadata, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}

    if not evidence:
        warnings.append(_EVIDENCE_LEGACY_WARNING)
        return {
            "valid": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
            "legacy": True,
            "evidence": {},
        }

    plan = evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {}
    runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else {}

    artifact_paths = plan.get("artifact_paths")
    normalized_artifacts = []
    if isinstance(artifact_paths, list):
        for item in artifact_paths:
            token = str(item).strip()
            if token:
                normalized_artifacts.append(token)
    elif artifact_paths is not None:
        token = str(artifact_paths).strip()
        if token:
            normalized_artifacts = [token]

    if not normalized_artifacts:
        errors.append("artifact_paths missing")

    entrypoint_path = str(plan.get("entrypoint_path") or "").strip()
    entrypoint = str(plan.get("entrypoint") or "").strip().lower()
    reason = str(plan.get("reason") or "").strip()
    if not entrypoint_path:
        if entrypoint == "none":
            if not reason:
                errors.append("entrypoint reason missing")
        else:
            errors.append("entrypoint_path missing")
            errors.append("For exceptions, use entrypoint: none + reason")

    normalized_runtime = {
        "integration_smoke_id": _normalize_tbd(runtime.get("integration_smoke_id")),
        "verify_cmd": _normalize_tbd(runtime.get("verify_cmd")),
        "expected_signal": _normalize_tbd(runtime.get("expected_signal")),
    }
    if normalized_runtime["verify_cmd"] != "TBD" and _is_dummy_verify_cmd(normalized_runtime["verify_cmd"]):
        errors.append(_GOODHART_DUMMY_VERIFY_ERROR)

    normalized_plan = {
        "artifact_paths": normalized_artifacts,
    }
    if entrypoint_path:
        normalized_plan["entrypoint_path"] = entrypoint_path
    if entrypoint == "none":
        normalized_plan["entrypoint"] = "none"
        normalized_plan["reason"] = reason

    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "legacy": False,
        "evidence": {
            "plan": normalized_plan,
            "runtime": normalized_runtime,
        },
    }

def _slugify_header_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", str(text))
    normalized = normalized.lower()
    normalized = re.sub(r"[\t ]+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9가-힣\-]", "", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")

def extract_h12_slugs(markdown_text: str) -> List[str]:
    slugs: List[str] = []
    seen = set()
    for match in _H12_HEADER_RE.finditer(str(markdown_text)):
        slug = _slugify_header_text(match.group(2))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs

def compute_coverage(original_slugs: List[str], mapped_slugs: set[str]) -> dict:
    unique_original = set(original_slugs)
    mapped = set(mapped_slugs)
    matched = unique_original & mapped
    missing = sorted(unique_original - mapped)
    total_sections = len(original_slugs)
    matched_sections = len(matched)
    coverage = (matched_sections / total_sections) if total_sections > 0 else 1.0
    return {
        "coverage": coverage,
        "total_sections": total_sections,
        "matched_sections": matched_sections,
        "missing_sections": missing,
    }

def _load_coverage_threshold_default() -> float:
    fallback = 0.85
    config_paths = [
        _common.BASE_DIR / "config.resolved.json",
        _plugin_root() / "templates" / "defaults" / "config.json",
    ]
    for path in config_paths:
        config = load_json(path)
        if not isinstance(config, dict):
            continue
        agile_config = config.get("agile")
        if not isinstance(agile_config, dict):
            continue
        raw_threshold = agile_config.get("coverage_threshold")
        try:
            return float(raw_threshold)
        except (TypeError, ValueError):
            continue
    return fallback

def _source_mapping_failure_payload(path: str, reason: str) -> dict:
    return {
        "path": path,
        "original": None,
        "sections": [],
        "valid": False,
        "errors": [reason],
    }

def _emit_source_mapping_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(f"Path: {payload.get('path')}")
    print(f"Valid: {'true' if payload.get('valid') else 'false'}")
    print(f"Original: {payload.get('original') or '-'}")
    sections = payload.get("sections") or []
    print(f"Sections: {', '.join(str(item) for item in sections) if sections else '-'}")
    errors = payload.get("errors") or []
    print(f"Errors: {'; '.join(str(item) for item in errors) if errors else 'none'}")

def _emit_evidence_validation_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(f"Path: {payload.get('path')}")
    print(f"Valid: {'true' if payload.get('valid') else 'false'}")
    print(f"Legacy: {'true' if payload.get('legacy') else 'false'}")

    source_mapping = payload.get("source_mapping") or {}
    print(f"Source Mapping Valid: {'true' if source_mapping.get('valid') else 'false'}")
    print(f"Source Original: {source_mapping.get('original') or '-'}")
    source_sections = source_mapping.get("sections") or []
    print(f"Source Sections: {', '.join(str(item) for item in source_sections) if source_sections else '-'}")

    evidence = payload.get("evidence") or {}
    print(f"Evidence: {'present' if evidence else 'none'}")
    warnings = payload.get("warnings") or []
    print(f"Warnings: {'; '.join(str(item) for item in warnings) if warnings else 'none'}")
    errors = payload.get("errors") or []
    print(f"Errors: {'; '.join(str(item) for item in errors) if errors else 'none'}")

def _emit_coverage_check_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(
        "Coverage: "
        f"{payload.get('coverage', 0.0):.2%} "
        f"({payload.get('matched_sections', 0)}/{payload.get('total_sections', 0)}) "
        f"- Threshold: {payload.get('threshold', 0.0):.2%} "
        f"- Valid: {'true' if payload.get('valid') else 'false'}"
    )
    missing_sections = payload.get("missing_sections") or []
    if missing_sections:
        print("Missing sections:")
        for slug in missing_sections:
            print(f"- {slug}")
    errors = payload.get("errors") or []
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")

def _emit_evidence_check_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "FAIL")
    warnings = payload.get("warnings") or []
    violations = payload.get("violations") or []
    details_dir = payload.get("details_dir")

    if status == "BYPASSED":
        print(f"BYPASSED: {payload.get('bypass_reason')}")
    elif status == "WARN" and payload.get("gate_enabled") is False:
        print("WARN: evidence gate disabled")
    elif status == "FAIL" and any(
        "required_globs unsatisfied" in str(item) for item in violations
    ):
        print("FAIL: required_globs unsatisfied")
    else:
        print(status)

    print(f"details_dir: {details_dir or '-'}")
    print(f"checked_files: {len(payload.get('checked_files') or [])}")
    print(f"warnings: {len(warnings)}")
    print(f"violations: {len(violations)}")

    required_globs = payload.get("required_globs") if isinstance(payload.get("required_globs"), dict) else {}
    patterns = required_globs.get("patterns") or []
    if patterns:
        print(f"required_globs: {', '.join(str(pattern) for pattern in patterns)}")

def _emit_drift_check_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    status = str(payload.get("status") or "WARN").upper()
    if status == "SKIP":
        print("WARN: drift-check skipped")
    else:
        print(str(payload.get("warn_level") or status))

    if payload.get("escalate_flag"):
        print("ESCALATE")

    drift_score = payload.get("drift_score")
    if isinstance(drift_score, (int, float)):
        print(f"drift_score: {float(drift_score):.4f}")
    else:
        print("drift_score: -")
    print(f"covered_surface: {len(payload.get('covered_surface') or [])}")
    print(f"uncovered_surface: {len(payload.get('uncovered_surface') or [])}")
    print(f"warn_streak: {payload.get('warn_streak', 0)}")
    print(f"threshold: {payload.get('threshold')}")
    print(f"warn_streak_limit: {payload.get('warn_streak_limit')}")

def _read_first_line(path: Path) -> str:
    with path.open("r", encoding="utf-8") as file:
        return file.readline().strip()

def _chunk_append_payload(target_path: Path, chunk_id: int, action: str, valid: bool, errors: list[str]) -> dict:
    return {
        "target_path": str(target_path),
        "chunk_id": chunk_id,
        "action": action,
        "valid": valid,
        "errors": errors,
    }

def _find_chunk_markers(text: str) -> list[dict]:
    markers: list[dict] = []
    for match in _CHUNK_MARKER_RE.finditer(text):
        marker_end = match.end()
        if marker_end < len(text) and text[marker_end] == "\n":
            marker_end += 1
        markers.append(
            {
                "chunk_id": int(match.group(1)),
                "start": match.start(),
                "end": marker_end,
            }
        )
    return markers

def _replace_chunk_content(existing_text: str, markers: list[dict], marker_index: int, replacement_text: str) -> str:
    current_marker = markers[marker_index]
    region_end = current_marker["end"]
    if marker_index == 0:
        region_start = 0
    else:
        previous_marker = markers[marker_index - 1]
        region_start = previous_marker["end"]
        if region_start < len(existing_text) and existing_text[region_start] == "\n":
            region_start += 1

    return f"{existing_text[:region_start]}{replacement_text}{existing_text[region_end:]}"

def apply_chunk_append(target_path, chunk_id, content) -> dict:
    path = Path(target_path)
    chunk_number = int(chunk_id)
    chunk_content = str(content)

    if chunk_number < 1:
        return _chunk_append_payload(
            path,
            chunk_number,
            "",
            False,
            ["chunk-id must be >= 1"],
        )

    if chunk_number >= 2 and not path.exists():
        return _chunk_append_payload(
            path,
            chunk_number,
            "",
            False,
            ["target not found, run chunk-id=1 first"],
        )

    marker_line = f"<!-- chunk:{chunk_number} -->"
    replacement = f"{chunk_content}\n{marker_line}\n"

    if chunk_number == 1:
        if path.exists():
            try:
                existing_text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return _chunk_append_payload(
                    path,
                    chunk_number,
                    "",
                    False,
                    [f"failed to read target: {exc}"],
                )

            markers = _find_chunk_markers(existing_text)
            for marker_index, marker in enumerate(markers):
                if marker["chunk_id"] != 1:
                    continue
                updated_text = _replace_chunk_content(existing_text, markers, marker_index, replacement)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(updated_text, encoding="utf-8")
                except OSError as exc:
                    return _chunk_append_payload(
                        path,
                        chunk_number,
                        "",
                        False,
                        [f"failed to write target: {exc}"],
                    )
                return _chunk_append_payload(path, chunk_number, "replaced", True, [])

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(replacement, encoding="utf-8")
        except OSError as exc:
            return _chunk_append_payload(
                path,
                chunk_number,
                "",
                False,
                [f"failed to write target: {exc}"],
            )
        return _chunk_append_payload(path, chunk_number, "created", True, [])

    try:
        existing_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _chunk_append_payload(
            path,
            chunk_number,
            "",
            False,
            [f"failed to read target: {exc}"],
        )

    markers = _find_chunk_markers(existing_text)
    for marker_index, marker in enumerate(markers):
        if marker["chunk_id"] != chunk_number:
            continue
        updated_text = _replace_chunk_content(existing_text, markers, marker_index, replacement)
        try:
            path.write_text(updated_text, encoding="utf-8")
        except OSError as exc:
            return _chunk_append_payload(
                path,
                chunk_number,
                "",
                False,
                [f"failed to write target: {exc}"],
            )
        return _chunk_append_payload(path, chunk_number, "replaced", True, [])

    appended_text = f"{existing_text}\n{replacement}"
    try:
        path.write_text(appended_text, encoding="utf-8")
    except OSError as exc:
        return _chunk_append_payload(
            path,
            chunk_number,
            "",
            False,
            [f"failed to write target: {exc}"],
        )
    return _chunk_append_payload(path, chunk_number, "appended", True, [])

def _emit_chunk_append_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(f"Target: {payload.get('target_path')}")
    print(f"Chunk ID: {payload.get('chunk_id')}")
    print(f"Action: {payload.get('action') or '-'}")
    print(f"Valid: {'true' if payload.get('valid') else 'false'}")
    errors = payload.get("errors") or []
    print(f"Errors: {'; '.join(str(item) for item in errors) if errors else 'none'}")

def _print_coverage_check_fail(payload: dict):
    print(
        f"[coverage-check] FAIL — {payload.get('coverage', 0.0):.2%} < {payload.get('threshold', 0.0):.2%}",
        file=sys.stderr,
    )
    for slug in payload.get("missing_sections", []):
        print(f"[coverage-check] missing: {slug}", file=sys.stderr)

def cmd_agile_coverage_check(args):
    original = str(args.original_path)
    details_dir = str(args.details_dir)
    threshold = float(args.threshold) if args.threshold is not None else _load_coverage_threshold_default()
    payload = {
        "original": original,
        "details_dir": details_dir,
        "total_sections": 0,
        "matched_sections": 0,
        "missing_sections": [],
        "coverage": 0.0,
        "threshold": threshold,
        "valid": False,
        "errors": [],
    }

    original_path = Path(original)
    if not original_path.exists():
        payload["errors"].append(f"original not found: {original}")
        _emit_coverage_check_payload(payload, args.json)
        _print_coverage_check_fail(payload)
        return 1
    if not original_path.is_file():
        payload["errors"].append(f"original is not a file: {original}")
        _emit_coverage_check_payload(payload, args.json)
        _print_coverage_check_fail(payload)
        return 1

    details_path = Path(details_dir)
    if not details_path.exists():
        payload["errors"].append(f"details dir not found: {details_dir}")
        _emit_coverage_check_payload(payload, args.json)
        _print_coverage_check_fail(payload)
        return 1
    if not details_path.is_dir():
        payload["errors"].append(f"details dir is not a directory: {details_dir}")
        _emit_coverage_check_payload(payload, args.json)
        _print_coverage_check_fail(payload)
        return 1

    try:
        original_content = original_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload["errors"].append(f"failed to read original: {exc}")
        _emit_coverage_check_payload(payload, args.json)
        _print_coverage_check_fail(payload)
        return 1

    original_slugs = extract_h12_slugs(original_content)
    mapped_slugs = set()

    for details_file in sorted(details_path.glob("*.md")):
        try:
            first_line = _read_first_line(details_file)
        except (OSError, UnicodeDecodeError) as exc:
            payload["errors"].append(f"mapping read error: {details_file}: {exc}")
            continue
        parsed = parse_source_mapping(first_line)
        if not bool(parsed.get("valid")):
            errors = parsed.get("errors") or ["unknown mapping error"]
            payload["errors"].append(
                f"mapping invalid: {details_file}: {'; '.join(str(err) for err in errors)}"
            )
            continue

        for raw_section in parsed.get("sections", []):
            slug = _slugify_header_text(raw_section)
            if slug:
                mapped_slugs.add(slug)

    coverage_result = compute_coverage(original_slugs, mapped_slugs)
    payload["total_sections"] = coverage_result["total_sections"]
    payload["matched_sections"] = coverage_result["matched_sections"]
    payload["missing_sections"] = coverage_result["missing_sections"]
    payload["coverage"] = coverage_result["coverage"]
    payload["valid"] = payload["coverage"] >= threshold

    _emit_coverage_check_payload(payload, args.json)
    if not payload["valid"]:
        _print_coverage_check_fail(payload)
        return 1
    return 0

def _normalize_required_glob_patterns(raw_value) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        raw_items = [raw_value]
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        return []

    normalized = []
    for item in raw_items:
        token = str(item).strip()
        if token and token not in normalized:
            normalized.append(token)
    return normalized

def _load_agile_evidence_gate_config() -> dict:
    agile_config = _load_agile_config_merged()
    evidence_gate = agile_config.get("evidence_gate")
    return evidence_gate if isinstance(evidence_gate, dict) else {}

def _resolve_required_globs_config(evidence_gate_cfg: dict) -> tuple[str, list[str]]:
    project_type = str(evidence_gate_cfg.get("project_type") or "plugin").strip().lower() or "plugin"
    configured = evidence_gate_cfg.get("required_globs")

    # fallback when missing or empty (defaults config may inject []): use project-type defaults
    if configured is None or (isinstance(configured, list) and len(configured) == 0):
        defaults = (
            _DEFAULT_REQUIRED_GLOBS_BY_PROJECT_TYPE.get(project_type)
            or _DEFAULT_REQUIRED_GLOBS_BY_PROJECT_TYPE.get("plugin")
            or []
        )
        return project_type, _normalize_required_glob_patterns(defaults)

    if isinstance(configured, dict):
        selected = configured.get(project_type)
        if selected is None:
            selected = configured.get("default")
        if selected is None:
            selected = (
                _DEFAULT_REQUIRED_GLOBS_BY_PROJECT_TYPE.get(project_type)
                or _DEFAULT_REQUIRED_GLOBS_BY_PROJECT_TYPE.get("plugin")
                or []
            )
        return project_type, _normalize_required_glob_patterns(selected)

    return project_type, _normalize_required_glob_patterns(configured)

def _normalize_sprint_id_token(raw_value: str) -> str:
    token = str(raw_value or "").strip()
    if not token:
        raise ValueError("sprint is required")

    if re.fullmatch(r"s\d+", token, flags=re.IGNORECASE):
        number = int(token[1:])
    elif re.fullmatch(r"\d+", token):
        number = int(token)
    else:
        raise ValueError(f"invalid sprint id: {raw_value}")

    if number < 0:
        raise ValueError("sprint must be >= 0")
    return f"S{number:02d}"

def _resolve_evidence_check_target(args) -> tuple[Optional[str], Path]:
    if args.details_dir:
        agi_id = None
        if args.agi_id:
            agi_id = _normalize_agi_id(str(args.agi_id))
        return agi_id, Path(str(args.details_dir))

    if not args.sprint:
        raise ValueError("either --sprint or --details-dir is required")

    if args.agi_id:
        agi_id = _normalize_agi_id(str(args.agi_id))
    else:
        agi_id = _find_latest_agi_id()
        if agi_id is None:
            raise ValueError("AGI session not found; provide --agi-id or --details-dir")

    _load_agile_session(agi_id)
    return agi_id, _agi_session_dir(agi_id) / "objective" / "details"

def _relpath_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)

def _resolve_project_matches(project_root: Path, expression: str) -> list[Path]:
    token = str(expression or "").strip()
    if not token:
        return []

    candidate_path = Path(token)
    if candidate_path.is_absolute():
        return [candidate_path] if candidate_path.exists() else []

    is_glob = any(ch in token for ch in "*?[")
    if is_glob:
        return sorted(path for path in project_root.glob(token) if path.exists())

    candidate = project_root / token
    return [candidate] if candidate.exists() else []

def _load_agile_drift_config() -> dict:
    agile_config = _load_agile_config_merged()
    drift = agile_config.get("drift")
    return drift if isinstance(drift, dict) else {}

def _extract_drift_surface_tokens(text: str) -> list[str]:
    tokens = []
    seen = set()
    for token in _DRIFT_SURFACE_TOKEN_RE.findall(str(text or "").lower()):
        cleaned = token.strip()
        if len(cleaned) < 2:
            continue
        if cleaned in _DRIFT_SURFACE_STOPWORDS:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        tokens.append(cleaned)
    return tokens

def _collect_drift_corpus_tokens(details_dir: Path) -> tuple[set[str], list[Path], list[str]]:
    tokens: set[str] = set()
    warnings: list[str] = []
    detail_files = sorted(details_dir.glob("*.md"))

    for detail_file in detail_files:
        try:
            content = detail_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"{detail_file.name}: failed to read detail ({exc})")
            continue

        tokens.update(_extract_drift_surface_tokens(content))
        parsed = parse_agile_detail_metadata(content)
        validation = validate_agile_detail_evidence(parsed)
        evidence = validation.get("evidence") if isinstance(validation.get("evidence"), dict) else {}
        plan = evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {}
        artifacts = plan.get("artifact_paths") if isinstance(plan.get("artifact_paths"), list) else []
        for artifact in artifacts:
            tokens.update(_extract_drift_surface_tokens(str(artifact)))

    return tokens, detail_files, warnings

def _compute_drift_surface_coverage(surface_entries: list[str], corpus_tokens: set[str]) -> tuple[list[str], list[str]]:
    covered: list[str] = []
    uncovered: list[str] = []

    for entry in surface_entries:
        entry_tokens = set(_extract_drift_surface_tokens(entry))
        if entry_tokens and entry_tokens.intersection(corpus_tokens):
            covered.append(entry)
        else:
            uncovered.append(entry)
    return covered, uncovered

def _load_agile_state_ledger_entries() -> list[dict]:
    entries, _, _ = _load_agile_state_payload()
    return entries

def _previous_drift_warn_streak(entries: list[dict]) -> int:
    if not entries:
        return 0

    latest = entries[-1]
    latest_level = str(latest.get("warn_level") or "").strip().upper()
    if latest_level != "WARN":
        return 0

    raw_streak = latest.get("warn_streak")
    if isinstance(raw_streak, int) and raw_streak >= 0:
        return raw_streak

    streak = 0
    for row in reversed(entries):
        level = str(row.get("warn_level") or "").strip().upper()
        if level != "WARN":
            break
        streak += 1
    return streak

def _append_agile_state_ledger_entry(entry: dict) -> list[dict]:
    rows, reopened_count, state_format = _load_agile_state_payload()
    rows.append(entry)
    _save_agile_state_payload(rows, reopened_count, as_dict=(state_format == "dict"))
    return rows

def _resolve_drift_check_target(args) -> tuple[Optional[str], Path, Path]:
    agi_id, details_dir = _resolve_evidence_check_target(args)
    objective_path = _agi_objective_path(agi_id) if agi_id else details_dir.parent / "objective.md"
    return agi_id, details_dir, objective_path

def cmd_agile_drift_check(args):
    sprint_id = None
    if args.sprint:
        try:
            sprint_id = _normalize_sprint_id_token(str(args.sprint))
        except ValueError as exc:
            payload = {
                "status": "FAIL",
                "warn_level": "WARN",
                "sprint_id": None,
                "agi_id": None,
                "details_dir": None,
                "objective_path": None,
                "threshold": None,
                "warn_streak_limit": 2,
                "drift_score": None,
                "surface_total": 0,
                "covered_surface": [],
                "uncovered_surface": [],
                "warn_streak": 0,
                "escalate_flag": False,
                "ledger_path": str(_agile_state_ledger_path()),
                "checked_files": [],
                "warnings": [],
                "errors": [str(exc)],
            }
            _emit_drift_check_payload(payload, args.json)
            print(str(exc), file=sys.stderr)
            return 1

    drift_cfg = _load_agile_drift_config()
    enabled = bool(drift_cfg.get("enabled", True))
    try:
        warn_streak_limit = int(drift_cfg.get("warn_streak_limit", 2))
    except (TypeError, ValueError):
        warn_streak_limit = 2
    if warn_streak_limit < 1:
        warn_streak_limit = 2

    payload = {
        "status": "SKIP",
        "warn_level": "WARN",
        "sprint_id": sprint_id,
        "agi_id": None,
        "details_dir": None,
        "objective_path": None,
        "threshold": drift_cfg.get("threshold"),
        "warn_streak_limit": warn_streak_limit,
        "drift_score": None,
        "surface_total": 0,
        "covered_surface": [],
        "uncovered_surface": [],
        "warn_streak": 0,
        "escalate_flag": False,
        "ledger_path": str(_agile_state_ledger_path()),
        "checked_files": [],
        "warnings": [],
        "errors": [],
    }

    if not enabled:
        payload["warnings"].append("drift-check skipped: agile.drift.enabled=false")
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0

    threshold_raw = drift_cfg.get("threshold")
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        threshold = None
    if threshold is None:
        payload["warnings"].append("drift-check skipped: agile.drift.threshold is missing")
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0
    if threshold < 0.0 or threshold > 1.0:
        payload["warnings"].append("drift-check skipped: agile.drift.threshold must be between 0 and 1")
        payload["threshold"] = threshold
        _emit_drift_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0
    payload["threshold"] = threshold

    try:
        agi_id, details_dir, objective_path = _resolve_drift_check_target(args)
    except ValueError as exc:
        payload["status"] = "FAIL"
        payload["errors"].append(str(exc))
        _emit_drift_check_payload(payload, args.json)
        print(str(exc), file=sys.stderr)
        return 1

    payload["agi_id"] = agi_id
    payload["details_dir"] = str(details_dir)
    payload["objective_path"] = str(objective_path)

    if not details_dir.exists():
        reason = f"details dir not found: {details_dir}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1
    if not details_dir.is_dir():
        reason = f"details dir is not a directory: {details_dir}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1
    if not objective_path.exists():
        reason = f"objective file missing: {objective_path}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    try:
        objective_content = objective_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"failed to read objective: {exc}"
        payload["status"] = "FAIL"
        payload["errors"].append(reason)
        _emit_drift_check_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    surface_entries = _extract_objective_surface_entries(objective_content)
    payload["surface_total"] = len(surface_entries)
    if not surface_entries:
        payload["warnings"].append("objective surface not found (JTBD + Project DoD)")

    corpus_tokens, detail_files, detail_warnings = _collect_drift_corpus_tokens(details_dir)
    payload["checked_files"] = [_relpath_display(path, _common.BASE_DIR.parent) for path in detail_files]
    payload["warnings"].extend(detail_warnings)
    if not detail_files:
        payload["warnings"].append(f"no detail files found: {details_dir}")

    covered_surface, uncovered_surface = _compute_drift_surface_coverage(surface_entries, corpus_tokens)
    drift_score = (len(covered_surface) / len(surface_entries)) if surface_entries else 0.0
    warn_level = "PASS" if surface_entries and drift_score >= threshold else "WARN"

    existing_entries = _load_agile_state_ledger_entries()
    prev_warn_streak = _previous_drift_warn_streak(existing_entries)
    warn_streak = (prev_warn_streak + 1) if warn_level == "WARN" else 0
    escalate_flag = warn_level == "WARN" and warn_streak >= warn_streak_limit

    ledger_entry = {
        "timestamp": _now_iso(),
        "agi_id": agi_id,
        "sprint_id": sprint_id,
        "drift_score": drift_score,
        "covered_surface": covered_surface,
        "uncovered_surface": uncovered_surface,
        "warn_level": warn_level,
        "warn_streak": warn_streak,
        "escalate_flag": escalate_flag,
    }
    _append_agile_state_ledger_entry(ledger_entry)

    payload.update(
        {
            "status": warn_level,
            "warn_level": warn_level,
            "drift_score": drift_score,
            "covered_surface": covered_surface,
            "uncovered_surface": uncovered_surface,
            "warn_streak": warn_streak,
            "escalate_flag": escalate_flag,
        }
    )
    if escalate_flag:
        payload["warnings"].append("warn streak limit reached; ESCALATE")

    _emit_drift_check_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    return 0

def cmd_agile_evidence_check(args):
    sprint_id = None
    if args.sprint:
        try:
            sprint_id = _normalize_sprint_id_token(str(args.sprint))
        except ValueError as exc:
            payload = {
                "status": "FAIL",
                "tier": "FAIL",
                "gate_enabled": False,
                "sprint_id": None,
                "agi_id": None,
                "details_dir": None,
                "project_root": str(_common.BASE_DIR.parent),
                "checked_files": [],
                "warnings": [],
                "violations": [str(exc)],
                "required_globs": {"project_type": "plugin", "patterns": [], "matches": {}},
                "bypass_reason": None,
            }
            _emit_evidence_check_payload(payload, args.json)
            print(str(exc), file=sys.stderr)
            return 1

    evidence_gate_cfg = _load_agile_evidence_gate_config()
    gate_enabled = bool(evidence_gate_cfg.get("enabled", True))
    project_root = _common.BASE_DIR.parent

    payload = {
        "status": "FAIL",
        "tier": "FAIL",
        "gate_enabled": gate_enabled,
        "sprint_id": sprint_id,
        "agi_id": None,
        "details_dir": None,
        "project_root": str(project_root),
        "checked_files": [],
        "warnings": [],
        "violations": [],
        "required_globs": {"project_type": "plugin", "patterns": [], "matches": {}},
        "bypass_reason": None,
    }

    if not gate_enabled:
        payload["status"] = "WARN"
        payload["tier"] = "WARN"
        payload["warnings"].append("evidence gate disabled by config (agile.evidence_gate.enabled=false)")
        _emit_evidence_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        return 0

    try:
        agi_id, details_dir = _resolve_evidence_check_target(args)
    except ValueError as exc:
        payload["violations"].append(str(exc))
        _emit_evidence_check_payload(payload, args.json)
        print(str(exc), file=sys.stderr)
        return 1

    payload["agi_id"] = agi_id
    payload["details_dir"] = str(details_dir)

    if not details_dir.exists():
        payload["violations"].append(f"details dir not found: {details_dir}")
        _emit_evidence_check_payload(payload, args.json)
        print(payload["violations"][-1], file=sys.stderr)
        return 1
    if not details_dir.is_dir():
        payload["violations"].append(f"details dir is not a directory: {details_dir}")
        _emit_evidence_check_payload(payload, args.json)
        print(payload["violations"][-1], file=sys.stderr)
        return 1

    project_type, required_globs = _resolve_required_globs_config(evidence_gate_cfg)
    payload["required_globs"]["project_type"] = project_type
    payload["required_globs"]["patterns"] = list(required_globs)

    if not required_globs:
        payload["warnings"].append("required_globs not configured; contract artifact check skipped")

    required_matches = {}
    for pattern in required_globs:
        matched = [path for path in project_root.glob(pattern) if path.is_file()]
        required_matches[pattern] = [_relpath_display(path, project_root) for path in matched]
        if not matched:
            payload["violations"].append(f"required_globs unsatisfied: {pattern}")
    payload["required_globs"]["matches"] = required_matches

    detail_files = sorted(details_dir.glob("*.md"))
    if not detail_files:
        payload["violations"].append(f"no detail files found: {details_dir}")

    for detail_file in detail_files:
        detail_label = _relpath_display(detail_file, project_root)
        payload["checked_files"].append(detail_label)
        try:
            content = detail_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            payload["violations"].append(f"{detail_label}: failed to read detail ({exc})")
            continue

        parsed = parse_agile_detail_metadata(content)
        validation = validate_agile_detail_evidence(parsed)

        for warning in validation.get("warnings", []):
            payload["warnings"].append(f"{detail_label}: {warning}")
        for error in validation.get("errors", []):
            payload["violations"].append(f"{detail_label}: {error}")

        if not validation.get("valid"):
            continue

        evidence = validation.get("evidence") if isinstance(validation.get("evidence"), dict) else {}
        plan = evidence.get("plan") if isinstance(evidence.get("plan"), dict) else {}
        runtime = evidence.get("runtime") if isinstance(evidence.get("runtime"), dict) else {}

        artifacts = plan.get("artifact_paths") if isinstance(plan.get("artifact_paths"), list) else []
        for artifact in artifacts:
            artifact_token = str(artifact).strip()
            if not artifact_token:
                continue
            matches = _resolve_project_matches(project_root, artifact_token)
            if not matches:
                payload["violations"].append(f"{detail_label}: artifact missing: {artifact_token}")

        entrypoint_path = str(plan.get("entrypoint_path") or "").strip()
        if entrypoint_path:
            entrypoint_file = entrypoint_path.split(":", 1)[0].strip()
            if entrypoint_file and not _resolve_project_matches(project_root, entrypoint_file):
                payload["violations"].append(f"{detail_label}: entrypoint missing: {entrypoint_file}")

        for field in ("integration_smoke_id", "verify_cmd", "expected_signal"):
            normalized = _normalize_tbd(runtime.get(field))
            if normalized == "TBD":
                payload["warnings"].append(f"{detail_label}: {field} is TBD")

    if payload["violations"]:
        payload["tier"] = "FAIL"
    elif payload["warnings"]:
        payload["tier"] = "WARN"
    else:
        payload["tier"] = "PASS"

    bypass_reason = str(args.accept_evidence_gap or "").strip()
    if payload["tier"] == "FAIL" and bypass_reason:
        payload["status"] = "BYPASSED"
        payload["bypass_reason"] = bypass_reason
        _append_agile_sprint_log(
            {
                "timestamp": _now_iso(),
                "event": "evidence-gap-accepted",
                "reason": bypass_reason,
                "agi_id": agi_id,
                "sprint_id": sprint_id,
                "details_dir": str(details_dir),
                "violations": list(payload["violations"]),
            }
        )
        _emit_evidence_check_payload(payload, args.json)
        for warning in payload["warnings"]:
            print(str(warning), file=sys.stderr)
        for violation in payload["violations"]:
            print(str(violation), file=sys.stderr)
        return 0

    payload["status"] = payload["tier"]
    _emit_evidence_check_payload(payload, args.json)
    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    for violation in payload["violations"]:
        print(str(violation), file=sys.stderr)
    return 1 if payload["status"] == "FAIL" else 0

def cmd_agile_detail_validate_mapping(args):
    details_path = str(args.details_path)
    details_file = Path(details_path)
    if not details_file.exists():
        payload = _source_mapping_failure_payload(details_path, f"file not found: {details_path}")
        _emit_source_mapping_payload(payload, args.json)
        return 1
    if not details_file.is_file():
        payload = _source_mapping_failure_payload(details_path, f"not a file: {details_path}")
        _emit_source_mapping_payload(payload, args.json)
        return 1

    try:
        content = details_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload = _source_mapping_failure_payload(details_path, f"failed to read file: {exc}")
        _emit_source_mapping_payload(payload, args.json)
        return 1

    parsed = parse_source_mapping(content)
    payload = {
        "path": details_path,
        "original": parsed.get("original"),
        "sections": parsed.get("sections", []),
        "valid": bool(parsed.get("valid")),
        "errors": parsed.get("errors", []),
    }
    _emit_source_mapping_payload(payload, args.json)
    return 0 if payload["valid"] else 1

def cmd_agile_detail_validate_evidence(args):
    details_path = str(args.details_path)
    details_file = Path(details_path)
    if not details_file.exists():
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, f"file not found: {details_path}"),
            "evidence": {},
            "warnings": [],
            "errors": [f"file not found: {details_path}"],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(payload["errors"][0], file=sys.stderr)
        return 1
    if not details_file.is_file():
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, f"not a file: {details_path}"),
            "evidence": {},
            "warnings": [],
            "errors": [f"not a file: {details_path}"],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(payload["errors"][0], file=sys.stderr)
        return 1

    try:
        content = details_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = f"failed to read file: {exc}"
        payload = {
            "path": details_path,
            "valid": False,
            "legacy": False,
            "source_mapping": _source_mapping_failure_payload(details_path, reason),
            "evidence": {},
            "warnings": [],
            "errors": [reason],
        }
        _emit_evidence_validation_payload(payload, args.json)
        print(reason, file=sys.stderr)
        return 1

    parsed = parse_agile_detail_metadata(content)
    validation = validate_agile_detail_evidence(parsed)
    payload = {
        "path": details_path,
        "valid": bool(validation.get("valid")),
        "legacy": bool(validation.get("legacy")),
        "source_mapping": parsed.get("source_mapping"),
        "evidence": validation.get("evidence"),
        "warnings": validation.get("warnings", []),
        "errors": validation.get("errors", []),
    }
    _emit_evidence_validation_payload(payload, args.json)

    for warning in payload["warnings"]:
        print(str(warning), file=sys.stderr)
    for error in payload["errors"]:
        print(str(error), file=sys.stderr)

    return 0 if payload["valid"] else 1

def cmd_agile_detail_append(args):
    target_dir = Path(str(args.target_dir)).resolve()
    target_path = target_dir / f"{args.domain}.md"
    chunk_id = int(args.chunk_id)
    content_path = Path(str(args.content_file))
    if not content_path.exists():
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"content-file not found: {content_path}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1
    if not content_path.is_file():
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"content-file not found: {content_path}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1

    try:
        content = content_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload = _chunk_append_payload(
            target_path,
            chunk_id,
            "",
            False,
            [f"failed to read content-file: {exc}"],
        )
        _emit_chunk_append_payload(payload, args.json)
        return 1

    payload = apply_chunk_append(target_path, chunk_id, content)
    _emit_chunk_append_payload(payload, args.json)
    return 0 if payload.get("valid") else 1

def cmd_agile_detail(args):
    subcommand = getattr(args, "detail_subcommand", None)
    dispatch = {
        "validate-mapping": cmd_agile_detail_validate_mapping,
        "validate-evidence": cmd_agile_detail_validate_evidence,
        "append": cmd_agile_detail_append,
    }
    fn = dispatch.get(subcommand)
    if fn is None:
        print("Error: detail subcommand is required (validate-mapping|validate-evidence|append)", file=sys.stderr)
        return 1
    return fn(args)

def _window_sprint_ids(sprint: int, depth: int) -> List[str]:
    return [f"S{idx:02d}" for idx in range(max(0, sprint - depth + 1), sprint + 1)]

def _load_agile_float_config(key: str, fallback: float) -> float:
    return _load_agile_config_cast(key, fallback, float)

def _git_output(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout

def _resolve_git_window_refs(repo_root: Path, depth: int) -> tuple[str, str]:
    commits = [line.strip() for line in _git_output(repo_root, "rev-list", "--max-count", str(depth + 1), "HEAD").splitlines() if line.strip()]
    if not commits:
        raise RuntimeError("no commits found")
    return (commits[-1] if len(commits) > depth else "4b825dc642cb6eb9a060e54bf8d69288fbee4904", "HEAD")

def _classify_changed_files(repo_root, since_ref, until_ref, reference_pattern=None):
    diff_range = f"{since_ref}..{until_ref}"
    changed = [line.split("\t")[-1].strip() for line in _git_output(repo_root, "diff", "--name-status", "--diff-filter=AM", diff_range).splitlines() if "\t" in line]
    changed = sorted({path for path in changed if path})
    added = {line.strip() for line in _git_output(repo_root, "diff", "--name-only", "--diff-filter=A", diff_range).splitlines() if line.strip()}
    tracked = [line.strip() for line in _git_output(repo_root, "ls-files").splitlines() if line.strip() and not line.startswith(".gran-maestro/")]
    content_cache: dict[str, str] = {}

    def _regex_for(path: str):
        stem = re.escape(Path(path).stem)
        dotted = re.escape(str(Path(path).with_suffix("")).replace("/", "."))
        escaped_path = re.escape(path)
        if reference_pattern:
            try:
                return re.compile(str(reference_pattern).format(module=stem, module_path=dotted, path=escaped_path), flags=re.IGNORECASE)
            except Exception:
                return re.compile(str(reference_pattern), flags=re.IGNORECASE)
        pattern = "|".join(
            [
                rf"\bfrom\s+{stem}\b",
                rf"\bimport\s+{stem}\b",
                rf"\bfrom\s+{dotted}\b",
                rf"\bimport\s+{dotted}\b",
                rf"require\([^)]*{stem}[^)]*\)",
                rf"\b{escaped_path}\b",
                rf"\]\({escaped_path}\)",
            ]
        )
        return re.compile(pattern, flags=re.IGNORECASE)

    def _refs_for(path: str) -> List[str]:
        regex = _regex_for(path)
        refs = []
        for candidate in tracked:
            if candidate == path:
                continue
            if candidate not in content_cache:
                p = repo_root / candidate
                content_cache[candidate] = p.read_text(encoding="utf-8", errors="ignore") if p.exists() and p.is_file() else ""
            text = content_cache[candidate]
            match = regex.search(text)
            if match:
                refs.append(f"{candidate}:{text.count(chr(10), 0, match.start()) + 1}")
        return refs

    modify_files: List[str] = []
    wire_files: List[str] = []
    new_island_files: List[str] = []
    wire_refs: dict[str, List[str]] = {}
    for path in changed:
        if path not in added:
            modify_files.append(path)
            continue
        if path.startswith("tests/"):
            wire_files.append(path)
            wire_refs[path] = ["tests/* 신규 파일은 wire로 분류"]
            continue
        refs = _refs_for(path)
        if refs:
            wire_files.append(path)
            wire_refs[path] = refs
        else:
            new_island_files.append(path)

    entrypoint_prefix = ("scripts/", "skills/", "templates/", "hooks/", "agents/", "src/", "extension/", "frontend/")
    return {
        "total": len(changed),
        "modify": len(modify_files),
        "wire": len(wire_files),
        "new_island": len(new_island_files),
        "new_island_files": sorted(new_island_files),
        "modify_files": sorted(modify_files),
        "wire_files": sorted(wire_files),
        "wire_references": wire_refs,
        "entrypoint_touched_count": sum(1 for path in changed if path.startswith(entrypoint_prefix)),
    }

def _compute_integration_verdict(classification, threshold):
    total = int(classification.get("total", 0))
    ratio = (float(classification.get("new_island", 0)) / total) if total > 0 else 0.0
    exceeded = ratio > float(threshold)
    return {"new_island_threshold": float(threshold), "exceeded": exceeded, "force_wire_recommended": exceeded}

def _render_integration_context_md(payload, output_path):
    files = payload.get("files", {})
    ratios = payload.get("ratios", {})
    verdict = payload.get("verdict", {})
    lines = [f"# Integration Context ({payload.get('sprint', '-')})", "", "## 1. 변경 파일 트리 (분류별)", ""]
    lines.extend([f"- total: {files.get('total', 0)}", f"- modify: {files.get('modify', 0)}"])
    lines.extend([f"  - {path}" for path in payload.get("modify_files", [])])
    lines.append(f"- wire: {files.get('wire', 0)}")
    lines.extend([f"  - {path}" for path in payload.get("wire_files", [])])
    lines.append(f"- new_island: {files.get('new_island', 0)}")
    lines.extend([f"  - {path}" for path in payload.get("new_island_files", [])])
    lines.extend(
        [
            "",
            "## 2. Entrypoint 상태",
            "",
            f"- entrypoint_touched_ratio: {ratios.get('entrypoint_touched', 0.0):.2%}",
            f"- new_island_ratio: {ratios.get('new_island', 0.0):.2%}",
            f"- threshold: {verdict.get('new_island_threshold', 0.0):.2f}",
            f"- force_wire_recommended: {verdict.get('force_wire_recommended', False)}",
            "",
            "## 3. 직전 Sprint 사용자 관찰 변화 요약",
        ]
    )
    changes = payload.get("recent_user_observable_changes", [])
    lines.extend([f"- {item.get('sprint', '-')}: {item.get('user_observable_change', '-')}" for item in changes] if changes else ["- 없음"])
    lines.extend(["", "## 4. wire 파일별 통합 지점"])
    if payload.get("wire_files"):
        for path in payload.get("wire_files", []):
            lines.append(f"- {path}")
            lines.extend([f"  - {ref}" for ref in payload.get("wire_references", {}).get(path, [])] or ["  - reference not found"])
    else:
        lines.append("- 없음")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _collect_alignment_payload(agi_id, sprint, depth):
    sprint_id = f"S{int(sprint):02d}"
    window_sprints = _window_sprint_ids(int(sprint), max(1, int(depth)))
    session_dir = _agi_session_dir(agi_id)
    objective_path = _agi_objective_path(agi_id)
    dods = []
    warning = None
    if objective_path.exists():
        dods = [{"id": dod_id, "status": item.get("status"), "priority": item.get("priority")} for dod_id, item in sorted(_collect_objective_dod_items(objective_path.read_text(encoding="utf-8")).items())]
    else:
        warning = "objective file missing"
    payload = {
        "agi_id": agi_id,
        "sprint": sprint_id,
        "depth": max(1, int(depth)),
        "objective_dods": dods,
        "integration_context_path": str(session_dir / "sprints" / sprint_id / "integration-context.md"),
        "recent_results": [],
        "recent_retrospectives": [],
    }
    for sid in reversed(window_sprints):
        result_path = session_dir / "sprints" / sid / "result.json"
        retro_path = session_dir / "sprints" / sid / "retrospective.json"
        if result_path.exists():
            payload["recent_results"].append(str(result_path))
        if retro_path.exists():
            payload["recent_retrospectives"].append(str(retro_path))
    if warning:
        payload["warning"] = warning
    return payload

def cmd_agile_integration_review(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.sprint < 0:
        print("Error: --sprint must be >= 0", file=sys.stderr)
        return 1

    depth = int(args.depth) if args.depth is not None else _load_agile_int_config("integration_review_depth", 3)
    threshold = float(args.threshold) if args.threshold is not None else _load_agile_float_config("new_island_threshold", 0.20)
    if depth < 1:
        print("Error: --depth must be >= 1", file=sys.stderr)
        return 1

    try:
        since_ref, until_ref = _resolve_git_window_refs(Path.cwd().resolve(), depth)
        classification = _classify_changed_files(Path.cwd().resolve(), since_ref, until_ref, args.reference_pattern)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    verdict = _compute_integration_verdict(classification, threshold)
    escape_reason = str(args.escape_reason).strip() if args.escape_reason else None
    verdict["escape_hatch_used"] = bool(escape_reason) and bool(verdict.get("exceeded"))
    verdict["escape_reason"] = escape_reason

    total = int(classification.get("total", 0))
    ratios = {
        "new_island": (float(classification.get("new_island", 0)) / total) if total else 0.0,
        "entrypoint_touched": (float(classification.get("entrypoint_touched_count", 0)) / total) if total else 0.0,
    }
    sprint_id = f"S{args.sprint:02d}"
    window_sprints = _window_sprint_ids(args.sprint, depth)
    session_dir = _agi_session_dir(agi_id)
    sprint_dir = session_dir / "sprints" / sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)

    streak_max = max(1, _load_agile_int_config("integration_wire_streak_max", 3))
    streak = 0
    for idx in range(args.sprint, -1, -1):
        if idx == args.sprint:
            force_wire = bool(verdict.get("force_wire_recommended"))
        else:
            prev = load_json(session_dir / "sprints" / f"S{idx:02d}" / "integration-review.json")
            force_wire = bool(prev.get("verdict", {}).get("force_wire_recommended")) if isinstance(prev, dict) else False
        if not force_wire:
            break
        streak += 1

    payload = {
        "sprint": sprint_id,
        "depth": depth,
        "window_sprints": window_sprints,
        "files": {k: classification.get(k, 0) for k in ("total", "modify", "wire", "new_island")} | {"new_island_files": classification.get("new_island_files", [])},
        "ratios": ratios,
        "verdict": verdict,
        "wire_streak": {"current": streak, "max": streak_max, "exceeded": streak >= streak_max},
    }
    save_json(sprint_dir / "integration-review.json", payload)

    changes = []
    for sid in reversed(window_sprints):
        result = load_json(session_dir / "sprints" / sid / "result.json")
        change = result.get("user_observable_change") if isinstance(result, dict) else None
        if change:
            changes.append({"sprint": sid, "user_observable_change": str(change)})
    _render_integration_context_md(
        {
            **payload,
            "modify_files": classification.get("modify_files", []),
            "wire_files": classification.get("wire_files", []),
            "new_island_files": classification.get("new_island_files", []),
            "wire_references": classification.get("wire_references", {}),
            "recent_user_observable_changes": changes,
        },
        sprint_dir / "integration-context.md",
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(str(sprint_dir / "integration-context.md"))
    return 0

def cmd_agile_alignment_package(args):
    try:
        agi_id = _normalize_agi_id(args.agi_id)
        _load_agile_session(agi_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.sprint < 0 or args.depth < 1:
        print("Error: --sprint must be >= 0 and --depth must be >= 1", file=sys.stderr)
        return 1
    payload = _collect_alignment_payload(agi_id, args.sprint, args.depth)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
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
