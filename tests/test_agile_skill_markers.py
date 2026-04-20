"""REQ-686 T01: agile SKILL baseline marker regression tests."""

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "agile" / "SKILL.md"


def test_existing_critical_markers_present():
    content = SKILL.read_text(encoding="utf-8")

    marker_patterns = [
        r"\[CRITICAL\]\[NO-SELF-MOTIVATED-PAUSE\]",
        r"\[CRITICAL\]\[NO-AD-HOC-PAUSE\]",
        r"\[CRITICAL\]\[STEERING-CHECK-ON-INCREMENTED-SPRINT\]",
        r"\[MANDATORY\]\[STEERING-DUE\]",
    ]
    missing = [
        pattern
        for pattern in marker_patterns
        if not re.search(pattern, content, flags=re.MULTILINE)
    ]
    assert not missing, f"Missing agile SKILL baseline markers: {missing}"

    anti_rationalization_baselines = [
        "## Anti-Rationalization Checklist",
        '합리화 패턴: "컨텍스트가 길어졌으니/자연스러운 단락이니 여기서 끊자."',
        "Sprint 간 '자연스러운 단락'이라며 paused 상태 전이 명령",
        "[CRITICAL][SELF-PAUSE-DETECTED]",
    ]
    missing_baselines = [
        text for text in anti_rationalization_baselines if text not in content
    ]
    assert not missing_baselines, (
        f"Missing agile SKILL Anti-Rationalization baselines: {missing_baselines}"
    )
