from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.mst_cmds import _common


def _base_dir() -> Path:
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR
    return _common.find_base_dir()


def _default_input_path(scope: str) -> Path:
    return _base_dir() / "metrics" / f"{scope}.ndjson"


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_rows(path: Path, since: datetime | None) -> list[dict]:
    if not path.exists():
        return []

    rows = []
    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                print(
                    f"warning: skipping invalid JSON line {path}:{line_number}: {exc.msg}",
                    file=sys.stderr,
                )
                continue
            if not isinstance(row, dict):
                continue
            if since is not None:
                timestamp = row.get("timestamp")
                if not isinstance(timestamp, str):
                    continue
                try:
                    parsed = _parse_timestamp(timestamp)
                except ValueError:
                    continue
                if parsed < since:
                    continue
            rows.append(row)
    return rows


def _summary(scope: str, rows: list[dict]) -> dict:
    sample_count = len(rows)
    success_rows = [row for row in rows if row.get("parse_status") == "ok"]
    fallback_rows = [
        row
        for row in rows
        if row.get("fallback_reason") is not None or row.get("parse_status") != "ok"
    ]
    token_counts = [
        row.get("token_count_estimate")
        for row in success_rows
        if isinstance(row.get("token_count_estimate"), (int, float))
    ]
    fallback_reasons: dict[str, int] = {}
    for row in fallback_rows:
        reason = row.get("fallback_reason") or row.get("parse_status")
        if not isinstance(reason, str) or not reason:
            reason = "unknown"
        fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1

    fallback_count = len(fallback_rows)
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else None
    def is_baseline(row: dict) -> bool:
        return isinstance(row.get("tags"), list) and "baseline" in row.get("tags")

    baseline_rows = [row for row in rows if is_baseline(row)]
    baseline_token_counts = [
        row.get("token_count_estimate")
        for row in baseline_rows
        if isinstance(row.get("token_count_estimate"), (int, float))
    ]
    non_baseline_token_counts = [
        row.get("token_count_estimate")
        for row in rows
        if not is_baseline(row)
        and isinstance(row.get("token_count_estimate"), (int, float))
    ]
    baseline_avg = (
        sum(baseline_token_counts) / len(baseline_token_counts)
        if baseline_token_counts
        else None
    )
    non_baseline_avg = (
        sum(non_baseline_token_counts) / len(non_baseline_token_counts)
        if non_baseline_token_counts
        else None
    )
    reduction_rate = (
        (baseline_avg - non_baseline_avg) / baseline_avg
        if baseline_avg and non_baseline_avg is not None
        else None
    )
    return {
        "scope": scope,
        "sample_count": sample_count,
        "parse_success_rate": (len(success_rows) / sample_count) if sample_count else 0,
        "avg_token_count_estimate": avg_tokens,
        "baseline_samples": len(baseline_rows),
        "baseline_avg_token_count_estimate": baseline_avg,
        "reduction_rate": reduction_rate,
        "fallback_count": fallback_count,
        "fallback_rate": (fallback_count / sample_count) if sample_count else 0,
        "fallback_reasons": fallback_reasons,
    }


def _print_human(summary: dict) -> None:
    print(f"Scope: {summary['scope']}")
    print(f"Samples: {summary['sample_count']}")
    print(f"Parse success: {summary['parse_success_rate'] * 100:.1f}%")
    avg_tokens = summary["avg_token_count_estimate"]
    if avg_tokens is None:
        print("Avg token estimate: n/a")
    else:
        print(f"Avg token estimate: {avg_tokens:.0f}")
    print(f"Fallback: {summary['fallback_rate'] * 100:.1f}% ({summary['fallback_count']})")
    if summary["fallback_reasons"]:
        reasons = ", ".join(
            f"{reason}={count}" for reason, count in sorted(summary["fallback_reasons"].items())
        )
        print(f"Fallback reasons: {reasons}")
    else:
        print("Fallback reasons: none")


def cmd_metrics_summary(args):
    if args.scope != "prompt-builder":
        print("Error: unsupported metrics scope", file=sys.stderr)
        return 1

    since = None
    if args.since:
        try:
            since = _parse_timestamp(args.since)
        except ValueError as exc:
            print(f"Error: invalid --since value: {exc}", file=sys.stderr)
            return 1

    input_path = Path(args.input) if args.input else _default_input_path(args.scope)
    rows = _read_rows(input_path, since)
    summary = _summary(args.scope, rows)
    if args.human:
        _print_human(summary)
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def register(subparsers):
    metrics = subparsers.add_parser("metrics")
    metrics_sub = metrics.add_subparsers(dest="subcommand")

    summary = metrics_sub.add_parser("summary")
    summary.add_argument("--scope", required=True, choices=["prompt-builder"])
    summary.add_argument("--input")
    summary.add_argument("--since")
    summary.add_argument("--human", action="store_true")
