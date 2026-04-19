from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGILE_SKILL = REPO_ROOT / "skills" / "agile" / "SKILL.md"


def _skill_text() -> str:
    return AGILE_SKILL.read_text(encoding="utf-8")


def test_sprint_close_references() -> None:
    text = _skill_text()
    sprint_close_section = re.search(
        r"##### 2\.2\.4\.5 Sprint 종료 정리 \(MANDATORY\)(?P<body>.*?)##### Step 2\.2\.5",
        text,
        flags=re.DOTALL,
    )

    assert len(re.findall(r"Pre-dispatch HEAD 가드", text)) >= 1
    assert len(re.findall(r"2\.2\.4\.5 Sprint 종료 정리", text)) == 1
    assert len(re.findall(r"agile sprint-close", text)) >= 1
    assert sprint_close_section is not None
    assert "known-issues add" in sprint_close_section.group("body")


def test_skill_legacy_anchors_preserved() -> None:
    text = _skill_text()

    assert "2.2.3.D" in text
    assert "2.2.4 Sprint 결과 기록" in text
