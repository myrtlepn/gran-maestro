from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from scripts.intent_store_lib.base import IntentStoreError


def _normalize_intent_id(value: str) -> str:
    text = (value or "").strip().upper()
    if not text:
        raise IntentStoreError("intent_id is required")
    if not re.fullmatch(r"INTENT-\d+", text):
        raise IntentStoreError(f"Invalid intent id: {value}")
    return text


def _intent_id_from_filename(file_name: str) -> str:
    match = re.match(r"(INTENT-\d+)", file_name.upper())
    if not match:
        raise IntentStoreError(f"Invalid intent filename: {file_name}")
    return match.group(1)


def _normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        normalized: List[str] = []
        for item in value:
            text = _normalize_optional_string(item)
            if text:
                normalized.append(text)
        return normalized
    single = _normalize_optional_string(value)
    return [single] if single else []


def _normalize_file_path(value: str) -> str:
    text = str(value).strip().replace("\\", "/")
    return re.sub(r"/+", "/", text)


def _slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"[^0-9a-z가-힣_-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "intent"


def _json_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return _normalize_string_list(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return _normalize_string_list(raw)
        return _normalize_string_list(parsed)
    return _normalize_string_list(raw)

