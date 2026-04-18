import re
import shutil
from pathlib import Path

from scripts.mst_cmds import skill as skill_cmd


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
INCLUDE_RE = re.compile(
    r"(<!-- @include (_shared/[^\s]+\.md) -->)\n(.*?)(<!-- @end-include -->)",
    re.DOTALL,
)


def _iter_skill_files(skills_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in skills_dir.glob("*/SKILL.md")
        if path.parent.name != "_shared"
    )


def _snapshot(skills_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(skills_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in _iter_skill_files(skills_dir)
    }


def _extract_include_body(content: str, include_target: str) -> str:
    pattern = re.compile(
        rf"<!-- @include {re.escape(include_target)} -->\n(.*?)<!-- @end-include -->",
        re.DOTALL,
    )
    match = pattern.search(content)
    assert match, f"include block not found: {include_target}"
    return match.group(1).rstrip("\n")


def test_content_equivalence(tmp_path):
    """마커 삽입 후 skill build 실행 시 마커 외부 콘텐츠 보존 확인"""

    tmp_skills = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, tmp_skills)
    expected = _snapshot(tmp_skills)

    for path in _iter_skill_files(tmp_skills):
        original = path.read_text(encoding="utf-8")
        mutated = INCLUDE_RE.sub(
            lambda match: (
                f"{match.group(1)}\n"
                f"stale include body for {match.group(2)}\n"
                f"{match.group(4)}"
            ),
            original,
        )
        path.write_text(mutated, encoding="utf-8")

    assert skill_cmd.build_all(tmp_skills, silent=True) == 0
    assert _snapshot(tmp_skills) == expected


def test_reference_lookup_variants():
    """reference-lookup 변이 처리: plan은 공통+확장, 나머지는 공통만"""

    shared_reference = (SKILLS_DIR / "_shared" / "reference-lookup.md").read_text(
        encoding="utf-8"
    ).rstrip("\n")

    plan_content = (SKILLS_DIR / "plan" / "SKILL.md").read_text(encoding="utf-8")
    assert (
        _extract_include_body(plan_content, "_shared/reference-lookup.md")
        == shared_reference
    )
    assert "#### Plan-specific Reference Guidance" in plan_content
    for keyword in ("현재 plan 텍스트", "예시 A (인용):", "PM lazy-Read 트리거"):
        assert keyword in plan_content

    for skill_name in ("approve", "request", "review"):
        content = (SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert (
            _extract_include_body(content, "_shared/reference-lookup.md")
            == shared_reference
        )
        assert "#### Plan-specific Reference Guidance" not in content


def test_idempotent_build(tmp_path):
    """skill build 2회 실행 시 변경 없음"""

    tmp_skills = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, tmp_skills)
    before = _snapshot(tmp_skills)

    assert skill_cmd.build_all(tmp_skills, silent=True) == 0
    after_first = _snapshot(tmp_skills)
    assert after_first == before

    assert skill_cmd.build_all(tmp_skills, silent=True) == 0
    after_second = _snapshot(tmp_skills)
    assert after_second == after_first


def test_shared_file_count():
    """_shared/ 디렉토리에 5개 이상 파일 존재"""

    assert len(list((SKILLS_DIR / "_shared").glob("*.md"))) >= 5


def test_config_get_cli_preserved():
    """마커 삽입 후에도 mst.py config get 호출이 보존됨"""

    count = sum(
        path.read_text(encoding="utf-8").count("mst.py config get")
        for path in _iter_skill_files(SKILLS_DIR)
    )
    assert count >= 49
