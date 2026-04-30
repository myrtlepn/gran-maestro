#!/usr/bin/env python3
"""Detect legacy stop-hook text patterns in one helper call."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, Optional

SELF_PAUSE_RE = re.compile(
    r"stash[^\x00-\x1f\x7f]{0,20}squash[^\x00-\x1f\x7f]{0,20}부담"
    r"|반복\s*stash"
    r"|paused로\s*전환"
    r"|명시적으로\s*paused"
    r"|Sprint[^\x00-\x1f\x7f]{0,40}paused[^\x00-\x1f\x7f]{0,20}boundary"
    r"|sprint\s*[0-9]+\s*boundary"
    r"|새\s*세션에서[^\n]*재개"
    r"|--resume[^\n]{0,30}재개\s*권장"
    r"|추천\s*경로[^\n]{0,30}재개\s*시점"
    r"|사용자\s*검토에\s*자연스러운\s*지점"
    r"|자연스러운\s*검토\s*지점"
    r"|wakeup\s*사이클"
    r"|wakeup\s*cycle"
    r"|\d+\s*분\s*(뒤|후)[^.]*재개"
    r"|다음\s*(사이클|턴)[^.]*재개"
    r"|자동\s*(재개|재진입)"
    r"|wakeup\s*(을|를)\s*(사용|호출)"
    r"|ScheduleWakeup\s*(을|를)"
    r"|wakeup\s*차단[^.]*(종료|마무리|다음\s*세션)",
    re.IGNORECASE,
)

AGILE_TEXT_QUESTION_RE = re.compile(
    r"계속할까요"
    r"|진행할까요"
    r"|계속\s*진행하시겠습니까"
    r"|멈추고"
    r"|중단할까요"
    r"|요약하고\s*계속"
    r"|정리하고\s*계속"
    r"|컨텍스트.*길"
    r"|자연스러운\s*단락"
    r"|여기서\s*(단락|끊|마무리|정지)"
    r"|수동\s*재호출"
    r"|다시\s*호출"
    r"|세션\s*교체"
    r"|자연스럽게\s*(멈|쉬|끊)",
    re.IGNORECASE,
)

ALLOW_PATTERN_RE = re.compile(
    r'"tool_name"\s*:\s*"AskUserQuestion"'
    r'|"name"\s*:\s*"AskUserQuestion"'
    r"|workflow complete"
    r"|final answer delivered"
    r"|user requested stop",
    re.IGNORECASE,
)

AGILE_ALLOW_MARKERS = (
    "[스티어링 체크포인트]",
    "[비상 스티어링]",
    "[Sprint 0]",
    "[자동 중단]",
)


def _parse_payload(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _decision(decision: str, reason: str, pattern_id: Optional[str]) -> Dict[str, Any]:
    return {"decision": decision, "reason": reason, "pattern_id": pattern_id}


def _allow() -> Dict[str, Any]:
    return _decision("allow", "no_pattern_match", None)


def _with_escalation(reason: str, next_block_count: int) -> str:
    reason = f"{reason} Consecutive block count: {next_block_count}."
    if next_block_count >= 3:
        return f"[자동 중단] {reason} Escalate to user for steering."
    return reason


def detect(payload: Dict[str, Any], raw_stdin: str, last_message: str) -> Dict[str, Any]:
    if not last_message:
        last_message = _text(payload.get("last_assistant_message"))
    context = f"{last_message}\n{raw_stdin}"

    self_pause_loop_active = _as_bool(payload.get("agile_loop_active"), default=True)
    self_pause_auto_mode_active = _as_bool(payload.get("agile_auto_mode_active"), default=True)
    agile_loop_active = _as_bool(payload.get("agile_loop_active"))
    agile_auto_mode_active = _as_bool(payload.get("agile_auto_mode_active"))
    steering_disabled = _as_bool(payload.get("steering_disabled"))
    agile_guard_active = _as_bool(payload.get("agile_guard_active"))
    stop_intent_force_block = _as_bool(payload.get("stop_intent_force_block"))
    route_allow_whitelist = _as_bool(payload.get("route_allow_whitelist"))
    allow_pattern_value = payload.get("allow_pattern_found")
    allow_pattern_found = (
        ALLOW_PATTERN_RE.search(context) is not None
        if allow_pattern_value is None
        else _as_bool(allow_pattern_value)
    )
    block_count = _as_int(payload.get("block_count"))
    next_block_count = block_count + 1

    if self_pause_loop_active and self_pause_auto_mode_active and SELF_PAUSE_RE.search(context):
        reason = (
            "[CRITICAL][SELF-PAUSE-DETECTED] 자발 정지 시도 감지: 합리화 텍스트(stash/squash 부담, "
            "paused 전환, Sprint boundary 등)가 발견됨. Sprint loop가 active인 상태에서 자발적 상태 전이 "
            "명령(예: 'mst.py agile update --status paused')을 호출해 루프를 종료하려는 행위는 금지된다. "
            "상태 전이 명령을 호출하지 말고 즉시 다음 sprint step의 tool call을 emit하라."
        )
        return _decision(
            "block",
            _with_escalation(reason, next_block_count),
            "self_pause_rationalization",
        )

    if (
        agile_loop_active
        and (agile_auto_mode_active or steering_disabled)
        and AGILE_TEXT_QUESTION_RE.search(context)
    ):
        reason = (
            "Sprint loop active in AUTO_MODE=true or STEERING_DISABLED=true; text-based question patterns are blocked. "
            "Remove phrases like '계속할까요?', '진행할까요?', '멈추고' and continue autonomously."
        )
        return _decision(
            "block",
            _with_escalation(reason, next_block_count),
            "agile_text_question_in_auto_mode",
        )

    if stop_intent_force_block or not allow_pattern_found or not agile_guard_active:
        return _allow()

    if any(marker in context for marker in AGILE_ALLOW_MARKERS):
        if not route_allow_whitelist:
            return _allow()
        return _decision("allow", "agile_allow_pattern_whitelisted", "agile_allow_pattern_whitelisted")

    remaining_dods = _text(payload.get("next_source")) or _text(payload.get("active_req")) or "continue current sprint backlog"
    reason = f"Sprint loop active; remaining DoDs: {remaining_dods}. AskUserQuestion is allowed only with agile whitelist markers."
    current_skill = _text(payload.get("current_skill"))
    active_req = _text(payload.get("active_req"))
    if current_skill:
        reason = f"{reason} Current skill: {current_skill}."
    if active_req:
        reason = f"{reason} Active request: {active_req}."
    return _decision(
        "block",
        _with_escalation(reason, next_block_count),
        "agile_allow_pattern_missing_marker",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect")
    detect_parser.add_argument("--stdin", action="store_true", help="read hook stdin JSON from stdin")
    detect_parser.add_argument("--last-message", default="")
    detect_parser.add_argument("--agile-loop-active", default=None)
    detect_parser.add_argument("--agile-auto-mode-active", default=None)
    detect_parser.add_argument("--steering-disabled", default=None)
    detect_parser.add_argument("--agile-guard-active", default=None)
    detect_parser.add_argument("--stop-intent-force-block", default=None)
    detect_parser.add_argument("--allow-pattern-found", default=None)
    detect_parser.add_argument("--block-count", default=None)
    detect_parser.add_argument("--next-source", default=None)
    detect_parser.add_argument("--active-req", default=None)
    detect_parser.add_argument("--current-skill", default=None)
    detect_parser.add_argument("--route-allow-whitelist", action="store_true")
    return parser


def _merge_cli_context(payload: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    merged = dict(payload)
    for arg_name, payload_key in (
        ("agile_loop_active", "agile_loop_active"),
        ("agile_auto_mode_active", "agile_auto_mode_active"),
        ("steering_disabled", "steering_disabled"),
        ("agile_guard_active", "agile_guard_active"),
        ("stop_intent_force_block", "stop_intent_force_block"),
        ("allow_pattern_found", "allow_pattern_found"),
        ("block_count", "block_count"),
        ("next_source", "next_source"),
        ("active_req", "active_req"),
        ("current_skill", "current_skill"),
    ):
        value = getattr(args, arg_name)
        if value is not None:
            merged[payload_key] = value
    if args.route_allow_whitelist:
        merged["route_allow_whitelist"] = True
    return merged


def main() -> int:
    args = build_parser().parse_args()
    if args.command != "detect":
        raise SystemExit(2)
    raw_stdin = sys.stdin.read() if args.stdin else ""
    payload = _merge_cli_context(_parse_payload(raw_stdin), args)
    result = detect(payload, raw_stdin, args.last_message)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
