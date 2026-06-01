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
_ANCHOR_REQUIRED_FIELDS = {"id", "source_file", "text", "kind", "grade", "domain_slug", "dod_refs"}
def _is_canonical_objective_details_path(details_path: Path) -> bool:
    parts = details_path.expanduser().parts
    for index, part in enumerate(parts):
        if part != ".gran-maestro":
            continue
        candidate = parts[index:index + 5]
        if len(candidate) == 5 and candidate[1] == "agile" and candidate[3] == "objective" and candidate[4] == "details":
            return bool(re.fullmatch(r"AGI-\d+", candidate[2], flags=re.IGNORECASE))
    return False
def _resolve_anchor_manifest_path(details_path: Path, explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        return Path(str(explicit_path)).expanduser()

    candidates = [
        details_path.parent / "objective.ids.json",
        details_path.parent / "objective" / "objective.ids.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if _is_canonical_objective_details_path(details_path):
        return details_path.parent / "objective.ids.json"
    return None
def _resolve_downstream_trace_path(details_path: Path, explicit_path: str | None = None) -> Path | None:
    if explicit_path:
        return Path(str(explicit_path)).expanduser()

    candidates = [
        details_path.parent / "downstream" / "plan.trace.json",
        details_path.parent / "plan.trace.json",
        details_path.parent / "finding-trace.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
def _normalize_anchor_id(value) -> str:
    return str(value or "").strip()
def _load_anchor_manifest(manifest_path: Path) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"anchor manifest read error: {manifest_path}: {exc}"]

    if not isinstance(payload, list):
        return [], [f"anchor manifest must be a list: {manifest_path}"]

    anchors: list[dict] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            errors.append(f"anchor manifest item {index} must be an object")
            continue
        missing_fields = sorted(_ANCHOR_REQUIRED_FIELDS - set(item))
        if missing_fields:
            errors.append(
                f"anchor manifest item {index} missing fields: {', '.join(missing_fields)}"
            )
            continue
        anchor_id = _normalize_anchor_id(item.get("id"))
        if not anchor_id:
            errors.append(f"anchor manifest item {index} has empty id")
            continue
        normalized = dict(item)
        normalized["id"] = anchor_id
        normalized["grade"] = str(item.get("grade") or "").strip().upper()
        anchors.append(normalized)
    return anchors, errors
def _load_mapped_anchor_ids(trace_path: Path | None) -> tuple[set[str], list[str]]:
    if trace_path is None:
        return set(), ["downstream trace not found"]
    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return set(), [f"downstream trace read error: {trace_path}: {exc}"]

    mapped: set[str] = set()
    raw_ids = payload.get("mapped_anchor_ids") if isinstance(payload, dict) else None
    if isinstance(raw_ids, list):
        for raw_id in raw_ids:
            anchor_id = _normalize_anchor_id(raw_id)
            if anchor_id:
                mapped.add(anchor_id)

    raw_trace = payload.get("objective_trace") if isinstance(payload, dict) else None
    if isinstance(raw_trace, list):
        for item in raw_trace:
            if not isinstance(item, dict):
                continue
            anchor_id = _normalize_anchor_id(item.get("anchor_id"))
            if anchor_id:
                mapped.add(anchor_id)

    raw_findings = payload.get("findings") if isinstance(payload, dict) else None
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            anchor_refs = item.get("anchor_refs")
            if not isinstance(anchor_refs, list):
                continue
            for raw_id in anchor_refs:
                anchor_id = _normalize_anchor_id(raw_id)
                if anchor_id:
                    mapped.add(anchor_id)

    return mapped, []
def _compute_anchor_coverage(details_path: Path, args) -> dict:
    manifest_path = _resolve_anchor_manifest_path(
        details_path,
        getattr(args, "anchor_manifest", None),
    )
    payload = {
        "anchor_manifest": str(manifest_path) if manifest_path else None,
        "anchor_downstream_trace": None,
        "anchor_total": 0,
        "anchor_mapped": 0,
        "anchor_missing_ids": [],
        "anchor_coverage": None,
        "anchor_errors": [],
    }
    if manifest_path is None:
        return payload
    if not manifest_path.exists():
        payload["anchor_errors"].append(f"anchor manifest not found: {manifest_path}")
        return payload

    anchors, manifest_errors = _load_anchor_manifest(manifest_path)
    payload["anchor_errors"].extend(manifest_errors)
    payload["anchor_total"] = len(anchors)

    trace_path = _resolve_downstream_trace_path(
        details_path,
        getattr(args, "downstream_trace", None),
    )
    payload["anchor_downstream_trace"] = str(trace_path) if trace_path else None
    mapped_anchor_ids, trace_errors = _load_mapped_anchor_ids(trace_path)
    payload["anchor_errors"].extend(trace_errors)

    known_anchor_ids = {_normalize_anchor_id(item.get("id")) for item in anchors}
    payload["anchor_mapped"] = len(known_anchor_ids & mapped_anchor_ids)
    payload["anchor_missing_ids"] = sorted(
        _normalize_anchor_id(item.get("id"))
        for item in anchors
        if str(item.get("grade") or "").strip().upper() == "MUST"
        and _normalize_anchor_id(item.get("id")) not in mapped_anchor_ids
    )
    payload["anchor_coverage"] = (
        payload["anchor_mapped"] / payload["anchor_total"]
        if payload["anchor_total"]
        else 1.0
    )
    return payload
_ANCHOR_DOD_RE = re.compile(r"\bDOD-[A-Za-z0-9_-]+\b")
_ANCHOR_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s*)?(?P<text>.+?)\s*$")
def _classify_anchor_kind(text: str) -> str:
    lowered = str(text).lower()
    if "nfr" in lowered or "성능" in text or "보안" in text:
        return "nfr"
    if "risk" in lowered or "리스크" in text or "위험" in text:
        return "risk"
    if "checklist" in lowered or "체크리스트" in text:
        return "checklist"
    if "dod" in lowered or "완료" in text:
        return "dod"
    if "ad-" in lowered or "결정" in text:
        return "decision"
    if "제약" in text or "constraint" in lowered:
        return "constraint"
    return "detail"
def _classify_anchor_grade(text: str) -> str:
    lowered = str(text).lower()
    must_tokens = ("must", "필수", "반드시", "해야 한다", "해야한다", "금지")
    return "MUST" if any(token in lowered or token in text for token in must_tokens) else "SHOULD"
def _extract_detail_anchor_texts(content: str) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    for line in str(content).splitlines():
        match = _ANCHOR_BULLET_RE.match(line)
        if match is None:
            continue
        text = match.group("text").strip()
        if not text or text.startswith("<!--"):
            continue
        if text in seen:
            continue
        seen.add(text)
        anchors.append(text)
    return anchors
def build_objective_anchor_manifest(details_dir: Path, manifest_path: Path | None = None) -> dict:
    output_path = manifest_path or (details_dir.parent / "objective.ids.json")
    payload = {
        "details_dir": str(details_dir),
        "manifest_path": str(output_path),
        "anchor_total": 0,
        "anchors": [],
        "valid": False,
        "errors": [],
    }

    if not details_dir.exists():
        payload["errors"].append(f"details dir not found: {details_dir}")
        return payload
    if not details_dir.is_dir():
        payload["errors"].append(f"details dir is not a directory: {details_dir}")
        return payload

    anchors: list[dict] = []
    sequence = 1
    for details_file in sorted(details_dir.glob("*.md")):
        try:
            content = details_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            payload["errors"].append(f"failed to read detail: {details_file}: {exc}")
            continue
        doc_dod_refs = sorted(set(_ANCHOR_DOD_RE.findall(content)))
        try:
            source_file = str(details_file.relative_to(output_path.parent))
        except ValueError:
            source_file = str(details_file)
        for text in _extract_detail_anchor_texts(content):
            line_dod_refs = sorted(set(_ANCHOR_DOD_RE.findall(text)))
            anchors.append(
                {
                    "id": f"OAC-{sequence:03d}",
                    "source_file": source_file,
                    "text": text,
                    "kind": _classify_anchor_kind(text),
                    "grade": _classify_anchor_grade(text),
                    "domain_slug": details_file.stem,
                    "dod_refs": line_dod_refs or doc_dod_refs,
                }
            )
            sequence += 1

    payload["anchors"] = anchors
    payload["anchor_total"] = len(anchors)
    payload["valid"] = not payload["errors"]
    return payload
def _emit_anchor_manifest_payload(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    print(f"Manifest: {payload.get('manifest_path')}")
    print(f"Anchors: {payload.get('anchor_total', 0)}")
    print(f"Valid: {'true' if payload.get('valid') else 'false'}")
    errors = payload.get("errors") or []
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
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
        "source_type": None,
        "evidence": None,
        "skip_reason": None,
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
    if payload.get("anchor_manifest"):
        print(
            "Anchor coverage: "
            f"{payload.get('anchor_mapped', 0)}/{payload.get('anchor_total', 0)} "
            f"- Missing MUST: {', '.join(payload.get('anchor_missing_ids') or []) or 'none'}"
        )
    errors = payload.get("errors") or []
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
    anchor_errors = payload.get("anchor_errors") or []
    if anchor_errors:
        print("Anchor evidence warnings:")
        for error in anchor_errors:
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
    for anchor_id in payload.get("anchor_missing_ids", []):
        print(f"[coverage-check] missing objective anchor: {anchor_id}", file=sys.stderr)
    for error in payload.get("anchor_errors", []):
        print(f"[coverage-check] objective anchor error: {error}", file=sys.stderr)
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
        "anchor_manifest": None,
        "anchor_downstream_trace": None,
        "anchor_total": 0,
        "anchor_mapped": 0,
        "anchor_missing_ids": [],
        "anchor_coverage": None,
        "anchor_errors": [],
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
    payload.update(_compute_anchor_coverage(details_path, args))
    if payload.get("anchor_manifest") and (
        payload.get("anchor_missing_ids") or payload.get("anchor_errors")
    ):
        payload["valid"] = False

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
