from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.intent_store_lib.base import IntentStoreError
from scripts.intent_store_lib.normalize import (
    _normalize_intent_id,
    _normalize_optional_string,
    _normalize_string_list,
)

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency fallback
    yaml = None


def _to_index_entry(metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _normalize_intent_id(metadata.get("id", "")),
        "feature": _normalize_optional_string(metadata.get("feature")) or "",
        "linked_req": _normalize_optional_string(metadata.get("linked_req")),
        "linked_plan": _normalize_optional_string(metadata.get("linked_plan")),
        "related_intent": _normalize_string_list(metadata.get("related_intent")),
        "tags": _normalize_string_list(metadata.get("tags")),
        "files": _normalize_string_list(metadata.get("files")),
        "created_at": _normalize_optional_string(metadata.get("created_at")) or "",
    }


def _render_intent_document(*, metadata: Dict[str, Any], body: str) -> str:
    lines = [
        "---",
        f'id: {json.dumps(_normalize_optional_string(metadata.get("id")) or "", ensure_ascii=False)}',
        f'feature: {json.dumps(_normalize_optional_string(metadata.get("feature")) or "", ensure_ascii=False)}',
        f'linked_req: {_yaml_scalar(_normalize_optional_string(metadata.get("linked_req")))}',
        f'linked_plan: {_yaml_scalar(_normalize_optional_string(metadata.get("linked_plan")))}',
        f'related_intent: {json.dumps(_normalize_string_list(metadata.get("related_intent")), ensure_ascii=False)}',
        f'tags: {json.dumps(_normalize_string_list(metadata.get("tags")), ensure_ascii=False)}',
        f'files: {json.dumps(_normalize_string_list(metadata.get("files")), ensure_ascii=False)}',
        f'created_at: {json.dumps(_normalize_optional_string(metadata.get("created_at")) or "", ensure_ascii=False)}',
        "---",
        "",
        body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def _extract_jtbd_sections(body: str) -> Dict[str, str]:
    lines = body.splitlines()
    when_heading = "## When I..."
    motivation_heading = "## I want to..."
    goal_heading = "## So I can..."

    try:
        when_idx = next(idx for idx, line in enumerate(lines) if line.strip() == when_heading)
        motivation_idx = next(
            idx for idx, line in enumerate(lines) if line.strip() == motivation_heading
        )
        goal_idx = next(idx for idx, line in enumerate(lines) if line.strip() == goal_heading)
    except StopIteration as exc:
        raise IntentStoreError("Invalid intent body format") from exc

    if not (when_idx < motivation_idx < goal_idx):
        raise IntentStoreError("Invalid intent body section order")

    next_section_idx = len(lines)
    for idx in range(goal_idx + 1, len(lines)):
        if lines[idx].strip().startswith("## "):
            next_section_idx = idx
            break

    situation = "\n".join(lines[when_idx + 1 : motivation_idx]).strip()
    motivation = "\n".join(lines[motivation_idx + 1 : goal_idx]).strip()
    goal = "\n".join(lines[goal_idx + 1 : next_section_idx]).strip()
    tail = "\n".join(lines[next_section_idx:]).strip()
    return {
        "situation": situation,
        "motivation": motivation,
        "goal": goal,
        "tail": tail,
    }


def _compose_jtbd_body(*, situation: str, motivation: str, goal: str, tail: str = "") -> str:
    parts = [
        "## When I...",
        (situation or "").strip(),
        "",
        "## I want to...",
        (motivation or "").strip(),
        "",
        "## So I can...",
        (goal or "").strip(),
    ]
    text = "\n".join(parts).rstrip()
    if tail:
        text = f"{text}\n\n{tail.strip()}"
    return text + "\n"


def _split_frontmatter(raw_text: str) -> Tuple[str, str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise IntentStoreError("Missing YAML frontmatter start delimiter")

    frontmatter_lines: List[str] = []
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
        frontmatter_lines.append(line)

    if end_index is None:
        raise IntentStoreError("Missing YAML frontmatter end delimiter")

    body = "\n".join(lines[end_index + 1 :])
    return "\n".join(frontmatter_lines), body


def _yaml_scalar(value: Optional[str]) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def _parse_frontmatter(frontmatter: str, path: Path) -> Dict[str, Any]:
    if yaml is not None:
        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except Exception as exc:  # pragma: no cover - handled fallback below
            raise IntentStoreError(f"Invalid YAML frontmatter in {path}: {exc}") from exc
        if not isinstance(metadata, dict):
            raise IntentStoreError(f"Invalid metadata shape in {path}")
        return metadata

    try:
        return _parse_frontmatter_fallback(frontmatter)
    except Exception as exc:
        raise IntentStoreError(
            f"Invalid frontmatter in {path} (and PyYAML unavailable): {exc}"
        ) from exc


def _parse_frontmatter_fallback(frontmatter: str) -> Dict[str, Any]:
    lines = frontmatter.splitlines()
    metadata: Dict[str, Any] = {}
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        if ":" not in raw_line:
            raise ValueError(f"expected key:value line, got '{raw_line}'")

        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if value:
            metadata[key] = _parse_scalar_or_list(value)
            index += 1
            continue

        list_items: List[str] = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            stripped = candidate.strip()
            if not stripped:
                cursor += 1
                continue
            if stripped.startswith("- "):
                list_items.append(_strip_quotes(stripped[2:].strip()))
                cursor += 1
                continue
            if ":" in candidate and not candidate.startswith((" ", "\t")):
                break
            break

        metadata[key] = list_items if list_items else None
        index = cursor

    return metadata


def _parse_scalar_or_list(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("null", "~"):
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
                return parsed
            except (ValueError, SyntaxError):
                inner = value[1:-1].strip()
                if not inner:
                    return []
                return [item.strip() for item in inner.split(",") if item.strip()]
    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return _strip_quotes(value)
    return value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        return value[1:-1]
    return value

