from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterator

from scripts._state_backup import backup_state_file
from scripts._state_normalize import migrate_legacy_status
from scripts._state_schema import TASK_STATUSES
from scripts.mst_cmds import _common

WORKFLOW_STATUSES = frozenset(
    {
        "active",
        "phase1_analysis",
        "spec_ready",
        "phase2_execution",
        "phase3_review",
        "phase4_feedback",
        "phase5_acceptance",
        "done",
        "cancelled",
        "failed",
        "pending_dependency",
    }
)
VALID_STATUSES = frozenset(status.lower() for status in TASK_STATUSES) | WORKFLOW_STATUSES


def _iter_status_entries(payload: object, default_id: str) -> Iterator[tuple[str, str]]:
    if isinstance(payload, dict):
        entity_id = payload.get("id")
        current_id = entity_id if isinstance(entity_id, str) and entity_id else default_id
        status = payload.get("status")
        if isinstance(status, str):
            yield current_id, status
        for value in payload.values():
            yield from _iter_status_entries(value, current_id)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_status_entries(item, default_id)


def _normalize_payload(
    payload: object, default_id: str
) -> tuple[object, int, bool]:
    if isinstance(payload, dict):
        entity_id = payload.get("id")
        current_id = entity_id if isinstance(entity_id, str) and entity_id else default_id
        normalized: dict[object, object] = {}
        normalized_count = 0
        changed = False
        for key, value in payload.items():
            if key == "status" and isinstance(value, str):
                migrated_status = migrate_legacy_status(value, context=current_id)
                if migrated_status != value:
                    normalized_count += 1
                    changed = True
                normalized[key] = migrated_status
                continue
            child_value, child_normalized_count, child_changed = _normalize_payload(
                value, current_id
            )
            normalized[key] = child_value
            normalized_count += child_normalized_count
            changed = changed or child_changed
        return normalized, normalized_count, changed
    if isinstance(payload, list):
        normalized_list: list[object] = []
        normalized_count = 0
        changed = False
        for item in payload:
            child_value, child_normalized_count, child_changed = _normalize_payload(
                item, default_id
            )
            normalized_list.append(child_value)
            normalized_count += child_normalized_count
            changed = changed or child_changed
        return normalized_list, normalized_count, changed
    return payload, 0, False


def _collect_invalid(payload: object, default_id: str, path: Path) -> list[dict]:
    invalid: list[dict] = []
    for entity_id, status in _iter_status_entries(payload, default_id):
        if status.lower() not in VALID_STATUSES:
            invalid.append(
                {
                    "id": entity_id,
                    "status": status,
                    "path": str(path),
                }
            )
    return invalid


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _validate_file(path: Path, default_id: str) -> tuple[int, list[dict], object | None, bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, [{"id": default_id, "status": "<invalid-json>", "path": str(path)}], None, False

    normalized_payload, normalized_count, changed = _normalize_payload(payload, default_id)
    invalid = _collect_invalid(normalized_payload, default_id, path)
    return normalized_count, invalid, normalized_payload, changed


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")


def cmd_state_validate(args: argparse.Namespace) -> int:
    if not args.json:
        print("Error: only --json output is supported.", file=sys.stderr)
        return 2

    base_dir = _common.BASE_DIR or _common.find_base_dir()
    request_files = sorted((base_dir / "requests").glob("REQ-*/request.json"))
    snapshot_files = sorted((base_dir / "state").glob("*/snapshot.json"))

    normalized_count = 0
    invalid: list[dict] = []
    backups_created: list[str] = []

    for request_path in request_files:
        req_id = request_path.parent.name
        file_normalized_count, file_invalid, normalized_payload, changed = _validate_file(
            request_path, req_id
        )
        if args.auto_fix and changed and normalized_payload is not None:
            backup_path = backup_state_file(request_path)
            backups_created.append(str(backup_path))
            _atomic_write_json(request_path, normalized_payload)
        normalized_count += file_normalized_count
        invalid.extend(file_invalid)

    for snapshot_path in snapshot_files:
        snapshot_id = snapshot_path.parent.name
        file_normalized_count, file_invalid, normalized_payload, changed = _validate_file(
            snapshot_path, snapshot_id
        )
        if args.auto_fix and changed and normalized_payload is not None:
            backup_path = backup_state_file(snapshot_path)
            backups_created.append(str(backup_path))
            _atomic_write_json(snapshot_path, normalized_payload)
        normalized_count += file_normalized_count
        invalid.extend(file_invalid)

    if invalid:
        _emit(
            {
                "summary": {
                    "normalized_count": normalized_count,
                    "invalid_count": len(invalid),
                },
                "backups_created": backups_created,
                "invalid": invalid,
            }
        )
        return 1

    _emit(
        {
            "summary": {
                "normalized_count": normalized_count,
                "invalid_count": 0,
            },
            "backups_created": backups_created,
        }
    )
    return 0


def register_state_validate(state_subparsers: argparse._SubParsersAction) -> None:
    state_validate = state_subparsers.add_parser("validate")
    state_validate.add_argument("--json", action="store_true")
    state_validate.add_argument("--auto-fix", action="store_true")
