#!/usr/bin/env python3
"""Measure premature stop rate from session-end snapshots."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _load_snapshot(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _safe_enter_count(value: Any) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _stack_depth(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    depth = 0
    for item in value:
        if isinstance(item, dict):
            depth += 1
    return depth


def measure_stop_rate(snapshots_dir: Path) -> Dict[str, Any]:
    total_enter_count = 0
    stack_residual_termination_count = 0
    processed_snapshot_count = 0

    if snapshots_dir.exists() and snapshots_dir.is_dir():
        for snapshot_file in sorted(snapshots_dir.glob("*.json")):
            snapshot = _load_snapshot(snapshot_file)
            if snapshot is None:
                continue

            processed_snapshot_count += 1
            total_enter_count += _safe_enter_count(snapshot.get("enterCount"))

            if _stack_depth(snapshot.get("skillStack")) > 0:
                stack_residual_termination_count += 1

    premature_stop_rate = 0.0
    if total_enter_count > 0:
        premature_stop_rate = stack_residual_termination_count / total_enter_count

    return {
        "snapshotsDir": str(snapshots_dir),
        "processedSnapshotCount": processed_snapshot_count,
        "stackResidualTerminationCount": stack_residual_termination_count,
        "totalEnterCount": total_enter_count,
        "premature_stop_rate": premature_stop_rate,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute premature_stop_rate from session snapshots."
    )
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=Path(".gran-maestro/state/snapshots"),
        help="Directory containing session snapshot JSON files.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = measure_stop_rate(args.snapshots_dir)
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
