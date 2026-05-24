#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTION_ROOT = REPO_ROOT / "plugins" / "mst"

COPY_PATHS = [
    ".codex-plugin",
    "agents",
    "dashboard",
    "dist",
    "scripts",
    "skills",
    "src",
    "templates",
    "README.md",
    "README.en.md",
    "LICENSE",
    "package.json",
    "package-lock.json",
    "state-schema.json",
]

EXTENSION_PATHS = [
    "dist",
    "icons",
    "manifest.json",
    "package.json",
    "package-lock.json",
]

HOOK_FILES = [
    "enforce-tree.json",
    "stop-agile-gate-reasons.json",
]


def copy_path(source: Path, target: Path) -> None:
    if source.is_dir():
        ignore = shutil.ignore_patterns("node_modules", ".omc", "__pycache__", ".pytest_cache")
        if source.name == "scripts":
            ignore = shutil.ignore_patterns(
                "node_modules",
                ".omc",
                "__pycache__",
                ".pytest_cache",
                "tests",
                "test_*.py",
            )
        shutil.copytree(source, target, symlinks=False, ignore=ignore)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def reset_projection() -> None:
    if PROJECTION_ROOT.exists() or PROJECTION_ROOT.is_symlink():
        if PROJECTION_ROOT.is_symlink() or PROJECTION_ROOT.is_file():
            PROJECTION_ROOT.unlink()
        else:
            shutil.rmtree(PROJECTION_ROOT)
    PROJECTION_ROOT.mkdir(parents=True)


def main() -> int:
    reset_projection()

    for rel in COPY_PATHS:
        copy_path(REPO_ROOT / rel, PROJECTION_ROOT / rel)

    extension_root = PROJECTION_ROOT / "extension"
    extension_root.mkdir()
    for rel in EXTENSION_PATHS:
        source = REPO_ROOT / "extension" / rel
        if source.exists():
            copy_path(source, extension_root / rel)

    hooks_root = PROJECTION_ROOT / "hooks"
    hooks_root.mkdir()
    for filename in HOOK_FILES:
        copy_path(REPO_ROOT / "hooks" / filename, hooks_root / filename)

    print(f"Synced Codex plugin projection: {PROJECTION_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
