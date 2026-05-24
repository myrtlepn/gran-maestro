#!/usr/bin/env python3
"""Format pre-check error output into an agent-friendly structure.

Input:
  - Trimmed pre-check output text (tsc/test)
Output:
  - Structured lines: "path:line — CODE — message"
  - Fail-safe passthrough when parsing yields no entries
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


TSC_ERROR_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*error\s+(?P<code>TS\d+):\s*(?P<message>.+)$"
)
FAIL_LINE_RE = re.compile(r"^\s*FAIL\s+(?P<detail>.+)$")
TEST_CASE_RE = re.compile(r"^\s*[●✕×]\s+(?P<name>.+)$")
STACK_LINE_RE = re.compile(
    r"(?P<file>(?:[A-Za-z]:)?[^\s:()]+?\.(?:ts|tsx|js|jsx|mjs|cjs)):(?P<line>\d+):(?P<column>\d+)"
)
TEST_MESSAGE_RE = re.compile(
    r"^(AssertionError:|TypeError:|ReferenceError:|Error:|Expected:|Received:|expect\()"
)


Entry = Tuple[str, str, str]


def _looks_like_file(token: str) -> bool:
    return bool(re.search(r"\.(ts|tsx|js|jsx|mjs|cjs)$", token))


def _add_entry(entries: List[Entry], seen: set[Entry], location: str, code: str, message: str) -> None:
    normalized: Entry = (location.strip(), code.strip(), " ".join(message.strip().split()))
    if not all(normalized):
        return
    if normalized in seen:
        return
    seen.add(normalized)
    entries.append(normalized)


def format_precheck_errors(text: str) -> str:
    try:
        lines = text.splitlines()
        entries: List[Entry] = []
        seen: set[Entry] = set()
        current_suite: Optional[str] = None
        last_test_case: Optional[str] = None

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue

            tsc_match = TSC_ERROR_RE.match(stripped)
            if tsc_match:
                location = f"{tsc_match.group('file')}:{tsc_match.group('line')}"
                _add_entry(entries, seen, location, tsc_match.group("code"), tsc_match.group("message"))
                continue

            fail_match = FAIL_LINE_RE.match(raw_line)
            if fail_match:
                detail = fail_match.group("detail").strip()
                if " > " in detail:
                    chunks = [chunk.strip() for chunk in detail.split(" > ") if chunk.strip()]
                    if chunks:
                        first = chunks[0]
                        current_suite = first
                        if len(chunks) > 1:
                            _add_entry(entries, seen, first, "TEST_FAIL", " > ".join(chunks[1:]))
                    else:
                        current_suite = detail
                else:
                    current_suite = detail
                continue

            case_match = TEST_CASE_RE.match(raw_line)
            if case_match:
                last_test_case = case_match.group("name").strip()
                location = current_suite if current_suite else f"test:{last_test_case}"
                _add_entry(entries, seen, location, "TEST_FAIL", last_test_case)
                continue

            stack_match = STACK_LINE_RE.search(raw_line)
            if stack_match:
                stack_file = stack_match.group("file")
                stack_line = stack_match.group("line")
                if _looks_like_file(stack_file):
                    message = last_test_case or "test failure"
                    _add_entry(entries, seen, f"{stack_file}:{stack_line}", "TEST_FAIL", message)
                continue

            if TEST_MESSAGE_RE.match(stripped):
                location = current_suite or f"test:{last_test_case or 'unknown'}"
                _add_entry(entries, seen, location, "TEST_FAIL", stripped)

        if not entries:
            return text

        return "\n".join(f"{location} — {code} — {message}" for location, code, message in entries)
    except Exception:
        return text


def _read_input(input_file: Optional[str]) -> str:
    if input_file:
        return Path(input_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Format pre-check tsc/test errors for re-outsourcing prompts.")
    parser.add_argument("--input-file", help="Read raw error text from file instead of stdin.")
    args = parser.parse_args()

    raw = _read_input(args.input_file)
    sys.stdout.write(format_precheck_errors(raw))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
