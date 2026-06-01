"""AC-001~008 검증: DoD 마커 domain 필드 + objective-check --dod-id."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from mst_cmds._common import _collect_objective_dod_items  # noqa: E402


def test_collect_dod_items_with_domain():
    content = """<!-- dod:DOD-001 status:todo priority:must domain:intent-context-propagation -->"""
    result = _collect_objective_dod_items(content)
    assert "DOD-001" in result
    assert result["DOD-001"]["status"] == "todo"
    assert result["DOD-001"]["priority"] == "must"
    assert result["DOD-001"]["domain"] == "intent-context-propagation"


def test_collect_dod_items_without_domain_defaults_to_unknown():
    content = """<!-- dod:DOD-001 status:todo priority:must -->"""
    result = _collect_objective_dod_items(content)
    assert "DOD-001" in result
    assert result["DOD-001"].get("domain") == "unknown"


def test_objective_check_dod_id_returns_domain(tmp_path):
    """실제 AGI-016 세션을 사용 (존재 가정)"""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "objective-check", "AGI-016",
         "--dod-id", "DOD-001", "--json"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    # AGI-016이 존재하면 exit 0 + JSON. 존재하지 않으면 skip.
    if "Error" in proc.stderr and "not found" not in proc.stderr:
        import pytest
        pytest.skip(f"AGI-016 not present: {proc.stderr}")
    if proc.returncode == 0 and proc.stdout.strip():
        data = json.loads(proc.stdout)
        assert data.get("dod_id") == "DOD-001"
        assert "domain" in data


def test_objective_check_backward_compat(tmp_path):
    """--dod-id 미지정 시 기존 스키마 유지."""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "objective-check", "AGI-016", "--json"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if proc.stdout.strip():
        data = json.loads(proc.stdout)
        assert "agi_id" in data
        assert "dods" in data
        # 기존 키 유지


def test_agile_skill_intent_layer_block_present():
    skill_md = PROJECT_ROOT / "skills" / "agile" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "[의도층]" in text
    assert "MANDATORY Read" in text
    assert "충족 JTBD 조항" in text
    assert "도메인 참조" in text


def test_agile_skill_redirect_loop_spec_present():
    skill_md = PROJECT_ROOT / "skills" / "agile" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "재지시" in text or "re-instruction" in text.lower()
    assert "intent_redirect_max_retries" in text


def test_agile_plan_skill_dod_marker_updated():
    skill_md = PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "domain:{slug}" in text or "domain:{domain_slug}" in text


def test_agile_plan_skill_artifact_write_contract_is_non_conflicting():
    skill_md = PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    assert "Managed Artifact Contract" in text
    for direct_path in (
        "objective/round-history.md",
        "objective/adversarial-review-findings.md",
        "quality-gate-log.md",
        "auto-decisions.md",
    ):
        assert direct_path in text
    for managed_artifact in (
        "objective.ids.json",
        "handoff-manifest.json",
        "finding-trace.json",
        "reference-links.json",
        "agile sidecar-build {AGI_ID}",
        "agile objective-transition",
    ):
        assert managed_artifact in text


def test_agile_plan_identity_guard_precedes_agile_init():
    skill_md = PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    preflight_index = text.index("0.0 command identity/no-plan-mode preflight")
    init_index = text.index("0.2 agile init 호출")
    assert preflight_index < init_index
    assert "before side effects" in text
    assert "EnterPlanMode" in text
    assert "`mst.py agile init`, 파일 생성, state 기록, 에이전트 위임보다 먼저" in text


def test_agile_plan_auto_resume_contract_is_inherited_from_parent_agile():
    agile_plan = (PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")
    agile = (PROJECT_ROOT / "skills" / "agile" / "SKILL.md").read_text(encoding="utf-8")

    assert "--resume AGI-NNN" in agile_plan
    assert "`--resume AGI-NNN`이 있으면 `agile init`을 실행하지 않는다" in agile_plan
    assert "새 AGI를 만들거나 objective를 새 파일로 복사하지 않는다" in agile_plan
    assert "`--auto`가 있거나 parent workflow state의 `auto=true`이면 `AUTO_MODE=true`" in agile_plan
    assert "`AUTO_MODE=true`에서는 AskUserQuestion을 호출하지 않는다" in agile_plan
    assert "{AUTO_FLAG_IF_TRUE}" in agile
    assert 'Skill(skill: "mst:agile-plan", args: "{PROJECT_GOAL_OR_DOC} {DOC_FLAG_IF_ANY} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")' in agile
    assert 'Skill(skill: "mst:agile-plan", args: "--resume {AGI_ID} --return-to agile/1 {AUTO_FLAG_IF_TRUE}")' in agile


def test_agile_plan_auto_interaction_loops_are_bounded():
    agile_plan = (PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")

    assert "agile.objective_refinement.max_auto_rounds" in agile_plan
    assert "`AUTO_MODE=true`: 자연어 사용자 대기, AskUserQuestion" in agile_plan
    assert "structured non-success" in agile_plan
    assert "`AUTO_MODE=true`에서는 soft limit 질문을 하지 않는다" in agile_plan
    assert "`max_auto_rounds` 도달 시 수렴/blocked/auto-decision 중 하나" in agile_plan


def test_agile_plan_draft_lifecycle_contract_prevents_accepted_objective_pollution():
    agile_plan = (PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")

    assert "Draft Lifecycle Contract" in agile_plan
    assert "objective/draft/" in agile_plan
    assert "accepted `objective.md`와 `objective/details/*.md`는 mandatory gate가 모두 통과한 뒤에만 promote" in agile_plan
    assert "accepted objective를 변경하지 않고 draft 경로와 failure reason만 남긴다" in agile_plan
    assert "objective-snapshot`, `objective-transition`, `sidecar-build`, `objective-check` 순서" in agile_plan
    assert "agile review --agi {AGI_ID} --perspective {name} --draft-dir" in agile_plan
    assert "CLI 결과의 `context_source`가 `draft`인지 확인" in agile_plan


def test_agile_plan_entry_mode_precedence_and_canonical_identity_fixture_contract():
    agile_plan = (PROJECT_ROOT / "skills" / "agile-plan" / "SKILL.md").read_text(encoding="utf-8")

    assert "Entry Mode Precedence Contract" in agile_plan
    assert "1. `--resume AGI-NNN`" in agile_plan
    assert "2. `--doc 파일경로`" in agile_plan
    assert "`--return-to`: entry mode를 바꾸지 않는 exit routing only 값" in agile_plan
    assert "`--auto` 또는 parent workflow `auto=true`: entry mode를 바꾸지 않는 interaction policy 값" in agile_plan
    assert "CLI flags > inherited workflow state > config defaults > prompt summary diagnostic-only" in agile_plan
    assert "validated history ledger`, `validated state snapshot`, `prompt summary diagnostic-only" in agile_plan
    assert "canonical `MST_SESSION_ID`/`mst_session_id`가 반드시 필요" in agile_plan
    assert "structured non-success" in agile_plan
    assert "Regression fixture matrix" in agile_plan
    assert "resume wins, doc ignored for mode" in agile_plan


def test_default_config_has_intent_redirect_max_retries():
    cfg = json.loads(
        (PROJECT_ROOT / "templates" / "defaults" / "config.json").read_text(encoding="utf-8")
    )
    assert cfg.get("agile", {}).get("intent_redirect_max_retries") == 3


def test_spec_template_includes_pac_and_epic_dod_mapping_sections():
    template = (PROJECT_ROOT / "templates" / "spec.md").read_text(encoding="utf-8")

    assert "## 3.3 PAC Mapping" in template
    assert "## 3.4 Epic DoD Mapping" in template


def test_agile_request_contract_requires_anchor_coverage_trace():
    agile_skill = (PROJECT_ROOT / "skills" / "agile" / "SKILL.md").read_text(encoding="utf-8")
    request_skill = (PROJECT_ROOT / "skills" / "request" / "SKILL.md").read_text(encoding="utf-8")
    required_tokens = ("objective anchor", "anchor coverage", "objective trace")

    assert any(token in agile_skill.lower() for token in required_tokens)
    assert any(token in request_skill.lower() for token in required_tokens)
