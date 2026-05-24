from __future__ import annotations

import sys
from typing import Optional

_WARNED_MIGRATIONS: set[str] = set()
_LEGACY_DONE_STATUSES = {"completed", "accepted"}


def _warn_once(raw_status: str, context: Optional[str] = None) -> None:
    key = raw_status.lower()
    if key in _WARNED_MIGRATIONS:
        return
    _WARNED_MIGRATIONS.add(key)
    if context:
        sys.stderr.write(f"[mst-state] migrated '{raw_status}' → 'done' for {context}\n")
        return
    sys.stderr.write(f"[mst-state] migrated '{raw_status}' → 'done'\n")


def migrate_legacy_status(raw_status: str, context: Optional[str] = None) -> str:
    status = str(raw_status)
    if status.lower() in _LEGACY_DONE_STATUSES:
        _warn_once(status, context=context)
        return "done"
    return status
