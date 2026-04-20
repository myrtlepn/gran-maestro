#!/usr/bin/env python3
"""Verify the agile skill Step 2.3 finalization contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


SKILL_PATH = Path("skills/agile/SKILL.md")
GATE_HEADER_RE = re.compile(r"^#{4,5}\s+2\.3\.0\s+Finalization Gate\b")
HEADER_4_OR_5_RE = re.compile(r"^#{4,5}\s+")
STEP_23_HEADER_RE = re.compile(r"^####\s+2\.3\s+루프 종료\b")
NEXT_TOP_SECTION_RE = re.compile(r"^###\s+")
KEYWORDS = [
    "sprints/S",
    "mst:accept",
    "비상 스티어링",
    "detect-orphans",
    "worktree remove",
]
FINAL_TOKENS = ["Finalization Gate", "worktree 정리 완료", "종료"]


def line_no(index: int) -> int:
    return index + 1


def pass_msg(name: str, detail: str) -> bool:
    print(f"[PASS] {name}: {detail}")
    return True


def fail_msg(name: str, detail: str) -> bool:
    print(f"[FAIL] {name}: {detail}")
    return False


def read_skill() -> list[str]:
    if not SKILL_PATH.exists():
        print(f"[FAIL] Setup: missing {SKILL_PATH}")
        sys.exit(1)
    return SKILL_PATH.read_text(encoding="utf-8").splitlines()


def find_gate_headers(lines: list[str]) -> list[int]:
    return [idx for idx, line in enumerate(lines) if GATE_HEADER_RE.search(line)]


def verify_a(gate_headers: list[int]) -> bool:
    if len(gate_headers) == 1:
        return pass_msg(
            "Verify A",
            f"Finalization Gate header (found at line {line_no(gate_headers[0])})",
        )
    locations = ", ".join(str(line_no(idx)) for idx in gate_headers) or "none"
    return fail_msg(
        "Verify A",
        f"expected exactly 1 Finalization Gate header, found {len(gate_headers)} ({locations})",
    )


def gate_section(lines: list[str], gate_idx: int) -> tuple[int, int]:
    end_idx = len(lines)
    for idx in range(gate_idx + 1, len(lines)):
        if HEADER_4_OR_5_RE.search(lines[idx]):
            end_idx = idx
            break
    return gate_idx, end_idx


def verify_b(lines: list[str], gate_headers: list[int]) -> bool:
    if len(gate_headers) != 1:
        return fail_msg("Verify B", "cannot locate a unique Gate section")

    start, end = gate_section(lines, gate_headers[0])
    section = "\n".join(lines[start:end])
    counts = {keyword: section.count(keyword) for keyword in KEYWORDS}
    missing = [keyword for keyword, count in counts.items() if count < 1]
    if missing:
        return fail_msg(
            "Verify B",
            "missing Gate keywords: " + ", ".join(repr(keyword) for keyword in missing),
        )
    counts_text = ", ".join(f"{keyword!r}={count}" for keyword, count in counts.items())
    return pass_msg(
        "Verify B",
        f"all Gate keywords appear in lines {line_no(start)}-{end} ({counts_text})",
    )


def find_completed_update_line(lines: list[str], start_idx: int) -> int | None:
    for idx in range(start_idx + 1, len(lines)):
        line = lines[idx]
        if "agile update" in line and "--status completed" in line:
            return idx
    return None


def is_active_false_line(line: str) -> bool:
    return re.fullmatch(r"\s*--active\s+false\s*\\?\s*", line) is not None


def find_state_set_workflow_line(lines: list[str], start_idx: int) -> int | None:
    for idx in range(start_idx + 1, len(lines)):
        if "state set-workflow" not in lines[idx]:
            continue
        block = lines[idx : min(idx + 10, len(lines))]
        if any("--agile-loop-active false" in line for line in block):
            return idx
        if any(is_active_false_line(line) for line in block):
            return idx
    return None


def verify_c(lines: list[str], gate_headers: list[int]) -> bool:
    if len(gate_headers) != 1:
        return fail_msg("Verify C", "cannot locate a unique Finalization Gate line")

    gate_idx = gate_headers[0]
    update_idx = find_completed_update_line(lines, gate_idx)
    state_idx = find_state_set_workflow_line(lines, gate_idx)

    if update_idx is None or state_idx is None:
        return fail_msg(
            "Verify C",
            "missing required command line(s): "
            f"Gate={line_no(gate_idx)}, "
            f"update={line_no(update_idx) if update_idx is not None else 'missing'}, "
            f"state={line_no(state_idx) if state_idx is not None else 'missing'}",
        )

    if gate_idx < update_idx < state_idx:
        return pass_msg(
            "Verify C",
            f"command order is monotonic (Gate={line_no(gate_idx)}, "
            f"update={line_no(update_idx)}, state={line_no(state_idx)})",
        )

    return fail_msg(
        "Verify C",
        "순서 위반 - "
        f"Gate={line_no(gate_idx)}, update={line_no(update_idx)}, "
        f"state={line_no(state_idx)} (non-monotonic)",
    )


def step_23_section(lines: list[str]) -> tuple[int, int] | None:
    start_idx = None
    for idx, line in enumerate(lines):
        if STEP_23_HEADER_RE.search(line):
            start_idx = idx
            break
    if start_idx is None:
        return None

    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        if NEXT_TOP_SECTION_RE.search(lines[idx]):
            end_idx = idx
            break
    return start_idx, end_idx


def prose_without_fences(lines: list[str]) -> str:
    in_fence = False
    prose_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped or stripped == "---" or stripped.startswith("#"):
            continue
        prose_lines.append(stripped)
    return " ".join(prose_lines)


def last_sentence(text: str) -> str | None:
    sentences = re.findall(r"[^.!?。]+[.!?。]", text)
    if not sentences:
        return None
    return sentences[-1].strip()


def verify_d(lines: list[str]) -> bool:
    section = step_23_section(lines)
    if section is None:
        return fail_msg("Verify D", "missing Step 2.3 loop termination section")

    start, end = section
    sentence = last_sentence(prose_without_fences(lines[start:end]))
    if sentence is None:
        return fail_msg(
            "Verify D",
            f"no natural-language sentence found in lines {line_no(start)}-{end}",
        )

    missing = [token for token in FINAL_TOKENS if token not in sentence]
    if missing:
        return fail_msg(
            "Verify D",
            "last sentence is missing token(s) "
            + ", ".join(repr(token) for token in missing)
            + f": {sentence!r}",
        )

    return pass_msg(
        "Verify D",
        f"last sentence contains required tokens: {sentence}",
    )


def main() -> int:
    lines = read_skill()
    gate_headers = find_gate_headers(lines)
    results = [
        verify_a(gate_headers),
        verify_b(lines, gate_headers),
        verify_c(lines, gate_headers),
        verify_d(lines),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
