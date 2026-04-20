"""REQ-686 T02: agile SKILL.md Step 3 rewrite + handoff framing regression tests."""

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "agile" / "SKILL.md"
HOOK = REPO_ROOT / "hooks" / "mst-stop-hook.sh"


def test_step3_report_framing():
    """AC-001: Step 3.2 '사용자에게 보고' AUTO_MODE 리프레이밍 확인."""
    content = SKILL.read_text(encoding="utf-8")
    # 기존 문장은 보존
    assert "DoD 제안을 사용자에게 보고하고" in content
    # AUTO_MODE 조건부 리프레이밍이 같은 영역에 추가
    assert "AUTO_MODE=true" in content
    assert "진행 로그 산출물" in content
    assert "handoff" in content.lower() or "handoff가 아니" in content


def test_step3_report_recommended_path_branching():
    """AC-002: '다음 추천 경로' 섹션 AUTO_MODE 분기 처리."""
    content = SKILL.read_text(encoding="utf-8")
    assert "다음 Sprint 진행 예정" in content, "AUTO_MODE=true forward-looking 섹션 누락"
    assert "다음 추천 경로" in content, "AUTO_MODE=false 기존 섹션 보존 실패"
    # AUTO_MODE=false 분기가 명시됨
    assert re.search(r"다음\s*추천\s*경로.*AUTO_MODE=false", content, re.DOTALL), \
        "AUTO_MODE=false 분기 조건문 부재"


def test_step3_3_immediate_loop_return_marker():
    """AC-003: Step 3.3 AUTO_MODE 분기 [CRITICAL][IMMEDIATE-LOOP-RETURN] 마커."""
    content = SKILL.read_text(encoding="utf-8")
    assert re.search(r"\[CRITICAL\]\[IMMEDIATE-LOOP-RETURN\]", content), "신규 마커 부재"
    assert "Step 2.2.1" in content, "Step 2.2.1 복귀 지시 부재"
    # 금지 어휘 명시
    assert "handoff 어휘" in content or "재개 안내" in content, "handoff 어휘 금지 명시 부재"


def test_anti_rationalization_handoff_entry():
    """AC-005: Anti-Rationalization 체크리스트 Step 3 handoff 신규 항목."""
    content = SKILL.read_text(encoding="utf-8")
    # 합리화 패턴 라인 스타일 유지
    assert re.search(r"합리화 패턴:.*Step 3.*스티어링.*자연스러운.*단락", content, re.DOTALL) \
        or re.search(r"합리화 패턴:.*자연스러운\s*단락.*--resume", content, re.DOTALL), \
        "신규 Anti-Rationalization 항목 부재"
    # 확인 증거 명시
    assert "contains_self_pause_rationalization" in content


def test_handoff_framing_in_hook_regex():
    """AC-006 보강: stop-hook 정규식 확장 존재 확인."""
    content = HOOK.read_text(encoding="utf-8")
    # 기존 regex OR로 확장된 신규 패턴 존재
    patterns = [
        "새[[:space:]]*세션에서",
        "자연스러운[[:space:]]*검토[[:space:]]*지점",
        "추천[[:space:]]*경로",
    ]
    for pattern_fragment in patterns:
        assert pattern_fragment in content, f"Missing regex extension: {pattern_fragment}"
    # 기존 regex 보존
    assert "stash[^[:cntrl:]]{0,20}squash" in content, "기존 rationalization regex 손실"
