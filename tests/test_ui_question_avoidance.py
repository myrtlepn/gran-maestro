from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PLAN_MODE_SIGNALS = ("Entered plan mode", "EnterPlanMode")
FORBIDDEN_GEMINI_RECLASSIFICATION_SIGNALS = (
    "Entered plan mode",
    "EnterPlanMode",
    "routing=plan",
    "routing=request",
    "routing=codex",
)


def _section_between(content: str, start: str, end: str) -> str:
    section_start = content.index(start)
    section_end = content.index(end, section_start)
    return content[section_start:section_end]


def _line_containing(content: str, needle: str) -> str:
    for line in content.splitlines():
        if needle in line:
            return line.strip()
    raise AssertionError(f"missing contract evidence line: {needle!r}")


def test_agile_plan_command_identity_guard_blocks_builtin_plan_mode():
    content = (REPO_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")
    gate_section = _section_between(
        content,
        "### Step 0.5: 의도 분류 게이트",
        "#### 0.5.1 confidence >= 0.8",
    )

    assert "command identity" in gate_section
    assert "`/mst:agile-plan`" in gate_section
    assert "Claude Code 내장 plan mode" in gate_section
    assert "`EnterPlanMode`" in gate_section
    assert "`Entered plan mode`" in gate_section
    assert "진입하지 않는다" in gate_section


def test_agile_plan_change_direction_fixture_stays_in_agile_plan_flow():
    content = (REPO_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")
    gate_section = _section_between(
        content,
        "### Step 0.5: 의도 분류 게이트",
        "#### 0.5.1 confidence >= 0.8",
    )

    assert "/mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘" in gate_section
    assert "현재 구현을 변경" in gate_section
    assert "수정" in gate_section
    assert "구현 변경" in gate_section
    assert "개선" in gate_section
    assert "리팩터링" in gate_section
    assert "agile-plan 절차의 objective/agile planning 입력" in gate_section
    assert "수용 불가 사유" in gate_section


def test_agile_plan_fixture_channels_reject_builtin_plan_mode_signals():
    fixture = {
        "input": "/mst:agile-plan 그럼 현재 구현을 변경하는 방향으로 수정해줘",
        "channels": {
            "transcript": (
                "[MST skill=agile-plan step=0/3 return_to=null]\n"
                "[의도 확인: objective/agile planning 입력으로 처리]\n"
                "command_identity=agile-plan"
            ),
            "captured_output": "routing=agile-plan\nprocedure=objective/agile planning",
            "tool_call_log": "해당 없음: prompt-only markdown regression fixture",
        },
    }

    assert fixture["input"].startswith("/mst:agile-plan")
    for channel_name, channel_content in fixture["channels"].items():
        for signal in FORBIDDEN_PLAN_MODE_SIGNALS:
            assert signal not in channel_content, (
                f"{channel_name} unexpectedly contained builtin plan mode signal {signal!r}"
            )


def test_agile_plan_guard_does_not_reclassify_to_plan_or_request():
    content = (REPO_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")
    gate_section = _section_between(
        content,
        "### Step 0.5: 의도 분류 게이트",
        "#### 0.5.1 confidence >= 0.8",
    )

    assert "`/mst:plan`" in gate_section
    assert "`/mst:request`" in gate_section
    assert "재분류하지 않는다" in gate_section
    assert "`/mst:agile-plan` command identity가 확정된 요청에만 적용" in gate_section
    assert "일반 `/mst:plan` 및 `/mst:request`" in gate_section
    assert "변경하지 않는다" in gate_section


def test_agile_plan_existing_happy_path_objective_flow_is_preserved():
    content = (REPO_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")

    assert "Step 0에서 반드시 `mst.py agile init`" in content
    assert "[의도 확인: objective 생성으로 진행]" in content
    assert "Step 1A: JTBD + 프로젝트 DoD Q&A 생성 모드" in content
    assert "Observable-by-Sprint 사고 프롬프트" in content
    assert "objective 생성 결과를 안내하고 종료한다" in content


def test_gemini_command_identity_guard_preserves_impl_edit_plan_requests():
    content = (REPO_ROOT / "skills" / "gemini" / "SKILL.md").read_text(encoding="utf-8")
    identity_section = _section_between(
        content,
        "## DOD-004 Gemini Identity Protection Contract",
        "## DOD-004 Gemini Delegation Failure and Fallback Contract",
    )

    assert "/mst:gemini 구현" in identity_section
    assert "/mst:gemini 수정" in identity_section
    assert "/mst:gemini 계획" in identity_section
    assert "다른 스킬로 재분류하지 않는다" in identity_section
    assert "/mst:codex" in identity_section
    assert "보호 수준" in identity_section


def test_gemini_identity_contract_evidence_rejects_reclassification_signals():
    content = (REPO_ROOT / "skills" / "gemini" / "SKILL.md").read_text(encoding="utf-8")
    identity_section = _section_between(
        content,
        "## DOD-004 Gemini Identity Protection Contract",
        "## DOD-004 Gemini Delegation Failure and Fallback Contract",
    )
    fixtures = [
        "/mst:gemini 구현",
        "/mst:gemini 수정",
        "/mst:gemini 계획",
    ]
    shared_evidence = {
        "command_identity": _line_containing(identity_section, "command_identity: `mst:gemini`"),
        "path_rules": _line_containing(identity_section, "path rules"),
        "rewrite_guard": _line_containing(identity_section, "rewrite하지 않는다"),
    }

    for fixture_input in fixtures:
        fixture_evidence = {
            "fixture_identity": _line_containing(identity_section, fixture_input),
            **shared_evidence,
        }

        assert fixture_input.startswith("/mst:gemini")
        assert "`mst:gemini`" in fixture_evidence["command_identity"]
        assert "`mst:gemini` command identity를 유지" in fixture_evidence["fixture_identity"]
        assert "다른 스킬로 재분류하지 않는다" in fixture_evidence["fixture_identity"]
        for channel_name, channel_content in fixture_evidence.items():
            for signal in FORBIDDEN_GEMINI_RECLASSIFICATION_SIGNALS:
                assert signal not in channel_content, (
                    f"{channel_name} unexpectedly contained gemini reclassification signal {signal!r}"
                )
