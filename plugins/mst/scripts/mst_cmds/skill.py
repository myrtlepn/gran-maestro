from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from scripts.mst_cmds import _common

SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

SCAFFOLD_TEMPLATE = """---
name: __NAME__
description: __DESCRIPTION__
---

# maestro:__NAME__

__DESCRIPTION__. 필요한 FLOW 제약은 stop-hook이 자동 처리합니다. 자세한 내용은 docs/FLOW-CONSTRAINTS.md 참조.

## Gate

### Entry
- TODO: 이 스킬 진입 전제 조건을 기입하세요.

### Exit
- TODO: 이 스킬 종료 조건을 기입하세요.

### 금지 패턴
- TODO: 합리화 회피해야 할 패턴을 기입하세요.

## Anti-Rationalization Checklist

- 합리화 패턴: TODO | 확인 증거: TODO.

## 실행 프로토콜

<!-- @include _shared/path-rules.md -->
<!-- @include _shared/hooks-sync.md -->
<!-- @include _shared/skill-execution-marker.md -->

### Step 0: 초기화

`state set --skill __NAME__ --step 0 --total N`

TODO: 스킬 초기화 로직을 기입하세요.

### Step 1: 본체 작업

`state set --skill __NAME__ --step 1 --total N [--return-to {{RETURN_TO}}]`

TODO: 주요 작업 로직을 기입하세요.
"""

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


def _skill_scaffold_project_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "scripts" / "mst.py").is_file() and (cwd / "skills").is_dir():
        return cwd
    if _common.BASE_DIR is not None:
        return _common.BASE_DIR.parent
    return _common._plugin_root()


def _validate_skill_name(name: str) -> str:
    if not SKILL_NAME_PATTERN.fullmatch(name):
        raise ValueError("name must match ^[a-z][a-z0-9-]*$")
    return name


def _skill_name_arg(name: str) -> str:
    try:
        return _validate_skill_name(name)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _render_scaffold_template(name: str, description: str) -> str:
    return (
        SCAFFOLD_TEMPLATE.replace("__NAME__", name)
        .replace("__DESCRIPTION__", description)
    )


def cmd_skill_scaffold(args) -> int:
    try:
        name = _validate_skill_name(args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    description = getattr(args, "description", None) or f"{name} 스킬"
    project_root = _skill_scaffold_project_root()
    target_dir = project_root / "skills" / name
    target_file = target_dir / "SKILL.md"

    if target_file.exists() and not bool(getattr(args, "force", False)):
        target_display = target_file.relative_to(project_root).as_posix()
        print(f"Error: {target_display} already exists", file=sys.stderr)
        return 1

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(
            _render_scaffold_template(name, description),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"Error: failed to create {target_file}: {exc}", file=sys.stderr)
        return 1

    print(f"Created skills/{name}/SKILL.md")
    return 0


def register(subparsers):
    sub = subparsers
    skill = sub.add_parser("skill")
    skill_sub = skill.add_subparsers(dest="subcommand")
    skill_build = skill_sub.add_parser("build")
    skill_build.add_argument("--check", action="store_true")
    skill_build.add_argument("--silent", action="store_true")

    skill_scaffold = skill_sub.add_parser("scaffold")
    skill_scaffold.add_argument("name", type=_skill_name_arg)
    skill_scaffold.add_argument("--description", default=None)
    skill_scaffold.add_argument("--force", action="store_true", default=False)
