#!/usr/bin/env python3
"""Remove duplicated boilerplate sections from skill documentation."""

import argparse
import pathlib
import re
import sys


INCLUDE_PATTERNS = (
    re.compile(
        r"<!-- @include _shared/skill-execution-marker\.md -->\s*.*?<!-- @end-include -->\n?",
        re.DOTALL | re.MULTILINE,
    ),
    re.compile(
        r"<!-- @include _shared/hooks-sync\.md -->\s*.*?<!-- @end-include -->\n?",
        re.DOTALL | re.MULTILINE,
    ),
)

INLINE_MARKER_PATTERN = re.compile(
    r"^## 스킬 실행 마커 \(MANDATORY\)\n.*?(?=^## |^<!-- @end-include -->|\Z)",
    re.DOTALL | re.MULTILINE,
)

EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def split_frontmatter(text):
    if not text.startswith("---\n"):
        return "", text

    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text

    marker_end = end + len("\n---\n")
    return text[:marker_end], text[marker_end:]


def remove_boilerplate(text):
    frontmatter, body = split_frontmatter(text)
    original_body = body

    for pattern in INCLUDE_PATTERNS:
        body = pattern.sub("", body)

    body = INLINE_MARKER_PATTERN.sub("", body)
    if body != original_body:
        body = EXCESS_BLANK_LINES.sub("\n\n", body)

    return frontmatter + body


def first_diff_preview(before, after, limit=5):
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    max_len = max(len(before_lines), len(after_lines))
    rows = []

    for index in range(max_len):
        old = before_lines[index] if index < len(before_lines) else None
        new = after_lines[index] if index < len(after_lines) else None
        if old == new:
            continue

        line_no = index + 1
        if old is not None:
            rows.append(f"  -{line_no}: {old}")
        if new is not None:
            rows.append(f"  +{line_no}: {new}")
        if len(rows) >= limit:
            return rows[:limit]

    return rows


def changed_line_delta(before, after):
    return before.count("\n") - after.count("\n")


def skill_files(root):
    return sorted(path for path in root.glob("**/SKILL.md") if path.is_file())


def process_file(path, dry_run):
    before = path.read_text(encoding="utf-8")
    after = remove_boilerplate(before)

    if before == after:
        return False

    delta = changed_line_delta(before, after)
    if dry_run:
        print(f"{path}: would change {delta} lines")
        preview = first_diff_preview(before, after)
        if preview:
            print("  preview:")
            for row in preview:
                print(row)
    else:
        path.write_text(after, encoding="utf-8")
        print(f"{path}: changed {delta} lines")

    return True


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Remove skill execution marker and hooks-sync boilerplate from SKILL.md files."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without modifying files.",
    )
    parser.add_argument(
        "--root",
        default="skills",
        help="Root directory to scan for **/SKILL.md files. Defaults to skills.",
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    root = pathlib.Path(args.root)

    if not root.exists():
        print(f"error: root does not exist: {root}", file=sys.stderr)
        return 2

    changed = 0
    for path in skill_files(root):
        if process_file(path, args.dry_run):
            changed += 1

    verb = "would change" if args.dry_run else "changed"
    print(f"{verb} {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
