#!/usr/bin/env python3
from __future__ import annotations

"""Thin facade for intent store implementations."""

from scripts.intent_store_lib.base import IntentStore, IntentStoreError
from scripts.intent_store_lib.markdown import (
    _compose_jtbd_body,
    _extract_jtbd_sections,
    _parse_frontmatter,
    _parse_frontmatter_fallback,
    _parse_scalar_or_list,
    _render_intent_document,
    _split_frontmatter,
    _strip_quotes,
    _to_index_entry,
    _yaml_scalar,
)
from scripts.intent_store_lib.normalize import (
    _intent_id_from_filename,
    _json_list,
    _normalize_file_path,
    _normalize_intent_id,
    _normalize_optional_string,
    _normalize_string_list,
    _slugify,
)
from scripts.intent_store_lib.sqlite import SqliteIntentStore

__all__ = [
    "IntentStoreError",
    "IntentStore",
    "SqliteIntentStore",
    "_normalize_intent_id",
    "_intent_id_from_filename",
    "_normalize_optional_string",
    "_normalize_string_list",
    "_normalize_file_path",
    "_slugify",
    "_json_list",
    "_to_index_entry",
    "_render_intent_document",
    "_extract_jtbd_sections",
    "_compose_jtbd_body",
    "_split_frontmatter",
    "_parse_frontmatter",
    "_parse_frontmatter_fallback",
    "_parse_scalar_or_list",
    "_strip_quotes",
    "_yaml_scalar",
]
