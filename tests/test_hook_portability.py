"""DOD-004 회귀 테스트 — hook 스크립트가 어떤 환경에서 실행되어도 의도된
PROJECT_ROOT를 인식하고 fail-open으로 동작하는지 정적·동적으로 검증.

AD-003: 4개 hook 모두 resolve_project_root + git rev-parse fallback 패턴 사용,
$CLAUDE_PROJECT_DIR 직접 의존 없음.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "hooks"

HOOK_NAMES = [
    "mst-stop-hook.sh",
    "mst-session-init.sh",
    "mst-pre-tool-use.sh",
    "mst-auto-chain-context.sh",
]


def _hook_text(name: str) -> str:
    return (HOOKS_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_defines_resolve_project_root(hook_name):
    text = _hook_text(hook_name)
    assert re.search(r"^resolve_project_root\(\)\s*\{", text, re.MULTILINE), (
        f"{hook_name}: resolve_project_root function definition missing"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_uses_git_rev_parse_fallback(hook_name):
    text = _hook_text(hook_name)
    assert "git rev-parse --show-toplevel" in text, (
        f"{hook_name}: git rev-parse fallback pattern missing"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_searches_gran_maestro_ancestor(hook_name):
    text = _hook_text(hook_name)
    assert ".gran-maestro" in text, (
        f"{hook_name}: .gran-maestro ancestor search missing"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_does_not_directly_reference_claude_project_dir(hook_name):
    """AD-003: $CLAUDE_PROJECT_DIR 직접 참조가 함수 본문에 0건이어야 한다."""
    text = _hook_text(hook_name)
    matches = re.findall(r"\$CLAUDE_PROJECT_DIR", text)
    assert not matches, (
        f"{hook_name}: $CLAUDE_PROJECT_DIR direct reference found ({len(matches)} occurrences)"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_fail_open_in_non_git_dir(tmp_path, hook_name):
    """비-git 디렉토리에서 hook을 실행해도 exit 0 fail-open."""
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    proc = subprocess.run(
        ["/bin/bash", str(HOOKS_DIR / hook_name)],
        cwd=str(tmp_path),
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"{hook_name} not fail-open in non-git dir. exit={proc.returncode} "
        f"stderr={proc.stderr[:300]}"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_fail_open_in_subdirectory(tmp_path, hook_name):
    """서브디렉토리(.gran-maestro 미포함)에서도 exit 0 fail-open."""
    sub = tmp_path / "deeply" / "nested" / "subdir"
    sub.mkdir(parents=True)
    proc = subprocess.run(
        ["/bin/bash", str(HOOKS_DIR / hook_name)],
        cwd=str(sub),
        input="{}",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"{hook_name} not fail-open in subdir. exit={proc.returncode} "
        f"stderr={proc.stderr[:300]}"
    )


@pytest.mark.parametrize("hook_name", HOOK_NAMES)
def test_hook_fail_open_via_symlink(tmp_path, hook_name):
    """심볼릭 링크 디렉토리에서도 exit 0 fail-open."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    proc = subprocess.run(
        ["/bin/bash", str(HOOKS_DIR / hook_name)],
        cwd=str(link),
        input="{}",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"{hook_name} not fail-open via symlink. exit={proc.returncode} "
        f"stderr={proc.stderr[:300]}"
    )
