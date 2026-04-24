from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scaffold_name():
    name = f"test-scaffold-{uuid.uuid4().hex[:8]}"
    try:
        yield name
    finally:
        shutil.rmtree(PROJECT_ROOT / "skills" / name, ignore_errors=True)


def _run_skill_scaffold(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "scripts/mst.py", "skill", "scaffold", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_scaffold_help():
    skill_result = subprocess.run(
        ["python3", "scripts/mst.py", "skill", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    scaffold_result = _run_skill_scaffold("--help")

    assert skill_result.returncode == 0
    assert "scaffold" in skill_result.stdout
    assert scaffold_result.returncode == 0
    assert "name" in scaffold_result.stdout
    assert "--description" in scaffold_result.stdout
    assert "--force" in scaffold_result.stdout


def test_scaffold_creates_skill_md(scaffold_name):
    result = _run_skill_scaffold(scaffold_name)

    assert result.returncode == 0
    assert result.stdout == f"Created skills/{scaffold_name}/SKILL.md\n"
    assert result.stderr == ""
    assert (PROJECT_ROOT / "skills" / scaffold_name / "SKILL.md").is_file()


def test_scaffold_contents(scaffold_name):
    description = "테스트 scaffold 스킬"
    result = _run_skill_scaffold(scaffold_name, "--description", description)

    assert result.returncode == 0
    content = (PROJECT_ROOT / "skills" / scaffold_name / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert f"---\nname: {scaffold_name}\n" in content
    assert f"description: {description}" in content
    assert f"# maestro:{scaffold_name}" in content
    assert "## Gate" in content
    assert "### Entry" in content
    assert "### Exit" in content
    assert "### 금지 패턴" in content
    assert "## Anti-Rationalization Checklist" in content
    assert "## 실행 프로토콜" in content
    assert "<!-- @include _shared/path-rules.md -->" in content
    assert "<!-- @include _shared/hooks-sync.md -->" in content
    assert "<!-- @include _shared/skill-execution-marker.md -->" in content
    assert f"`state set --skill {scaffold_name} --step 0 --total N`" in content
    assert (
        f"`state set --skill {scaffold_name} --step 1 --total N "
        "[--return-to {{RETURN_TO}}]`"
    ) in content


def test_scaffold_rejects_existing(scaffold_name):
    first = _run_skill_scaffold(scaffold_name)
    second = _run_skill_scaffold(scaffold_name)

    assert first.returncode == 0
    assert second.returncode != 0
    assert second.stdout == ""
    assert "already exists" in second.stderr


def test_scaffold_force_overwrites(scaffold_name):
    target = PROJECT_ROOT / "skills" / scaffold_name / "SKILL.md"
    first = _run_skill_scaffold(scaffold_name)
    target.write_text("old content\n", encoding="utf-8")
    second = _run_skill_scaffold(scaffold_name, "--force")

    assert first.returncode == 0
    assert second.returncode == 0
    assert second.stdout == f"Created skills/{scaffold_name}/SKILL.md\n"
    content = target.read_text(encoding="utf-8")
    assert "old content" not in content
    assert f"name: {scaffold_name}" in content
