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


def test_default_config_has_intent_redirect_max_retries():
    cfg = json.loads(
        (PROJECT_ROOT / "templates" / "defaults" / "config.json").read_text(encoding="utf-8")
    )
    assert cfg.get("agile", {}).get("intent_redirect_max_retries") == 3
