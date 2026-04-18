from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts.mst_cmds import _common

INCLUDE_PATTERN = re.compile(
    r"(<!-- @include (_shared/[^\s]+\.md) -->)\n"
    r"(.*?)"
    r"(<!-- @end-include -->)",
    re.DOTALL,
)


def resolve_includes(skill_md_path: Path, shared_dir: Path) -> tuple[str, list[str]]:
    """Resolve inline include markers in a SKILL.md file."""
    try:
        original = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return "", [f"Error: failed to read {skill_md_path}: {exc}"]

    errors: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        include_path = shared_dir.parent / Path(match.group(2))
        try:
            include_text = include_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            errors.append(
                f"Error: include file not found for {skill_md_path}: {include_path}"
            )
            return match.group(0)
        except OSError as exc:
            errors.append(
                f"Error: failed to read include for {skill_md_path}: {include_path}: {exc}"
            )
            return match.group(0)

        return f"{match.group(1)}\n{include_text}{match.group(4)}"

    resolved = INCLUDE_PATTERN.sub(_replace, original)
    return resolved, errors


def build_all(skills_dir: Path, check_only: bool = False, silent: bool = False) -> int:
    shared_dir = skills_dir / "_shared"
    skill_files = sorted(
        path
        for path in skills_dir.glob("*/SKILL.md")
        if path.parent.name != "_shared"
    )

    stale_files: list[Path] = []
    errors: list[str] = []
    updated_files: list[Path] = []

    for skill_file in skill_files:
        resolved, file_errors = resolve_includes(skill_file, shared_dir)
        if file_errors:
            errors.extend(file_errors)
            continue

        original = skill_file.read_text(encoding="utf-8")
        if resolved == original:
            continue

        if check_only:
            stale_files.append(skill_file)
            continue

        try:
            skill_file.write_text(resolved, encoding="utf-8")
        except OSError as exc:
            errors.append(f"Error: failed to write {skill_file}: {exc}")
            continue
        updated_files.append(skill_file)

    if errors:
        if not silent:
            for error in errors:
                print(error, file=sys.stderr)
        return 1

    if check_only:
        if stale_files:
            if not silent:
                for path in stale_files:
                    print(path.as_posix(), file=sys.stderr)
            return 1
        if not silent:
            print("all includes up-to-date")
        return 0

    if not silent:
        print(f"updated {len(updated_files)} skill file(s)")
    return 0


def cmd_skill_build(args) -> int:
    plugin_root = _common._plugin_root()
    skills_dir = plugin_root / "skills"
    return build_all(
        skills_dir,
        check_only=bool(getattr(args, "check", False)),
        silent=bool(getattr(args, "silent", False)),
    )


def register(subparsers):
    sub = subparsers
    skill = sub.add_parser("skill")
    skill_sub = skill.add_subparsers(dest="subcommand")
    skill_build = skill_sub.add_parser("build")
    skill_build.add_argument("--check", action="store_true")
    skill_build.add_argument("--silent", action="store_true")
