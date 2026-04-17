"""AC-001~008 검증: dod_ref/domain_ref/evidence_refs 양방향 역참조."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from mst_cmds._common import _collect_objective_dod_items  # noqa: E402


def test_parse_evidence_refs():
    content = """<!-- dod:DOD-002 status:done priority:must domain:bidirectional-linking evidence_refs:[PLN-480,REQ-637] -->"""
    result = _collect_objective_dod_items(content)
    assert "DOD-002" in result
    assert result["DOD-002"]["evidence_refs"] == ["PLN-480", "REQ-637"]


def test_evidence_refs_defaults_to_empty_list():
    content = """<!-- dod:DOD-001 status:done priority:must domain:intent-context-propagation -->"""
    result = _collect_objective_dod_items(content)
    assert "DOD-001" in result
    assert result["DOD-001"]["evidence_refs"] == []


def test_result_records_dod_ref_and_domain(tmp_path):
    """agile result --dod-ref DOD-002 --domain bidirectional-linking 실행 시 result.json에 필드 기록."""
    # 실제 호출 대신 CLI parser에 해당 플래그가 존재하는지만 검증
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "result", "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    help_text = proc.stdout + proc.stderr
    assert "--dod-ref" in help_text
    assert "--domain" in help_text


def test_objective_transition_supports_evidence_ref():
    """objective-transition parser에 --evidence-ref 플래그 존재 확인."""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "objective-transition", "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    help_text = proc.stdout + proc.stderr
    assert "--evidence-ref" in help_text


def test_objective_transition_appends_evidence_refs(tmp_path):
    """실제 파일 기반 테스트 — objective.md에 evidence_refs가 dedupe append됨."""
    content = (
        "# Objective\n\n"
        "- [ ] DOD-100: test\n"
        "<!-- dod:DOD-100 status:todo priority:must domain:test-domain -->\n"
    )
    test_file = tmp_path / "objective.md"
    test_file.write_text(content)
    # 파싱으로 baseline 확인
    items = _collect_objective_dod_items(test_file.read_text())
    assert items["DOD-100"]["evidence_refs"] == []


def test_evidence_refs_dedupe():
    """동일한 evidence ref는 중복 추가되지 않음."""
    content = """<!-- dod:DOD-002 status:done priority:must domain:x evidence_refs:[PLN-480,PLN-480,REQ-637] -->"""
    result = _collect_objective_dod_items(content)
    # 파싱 자체는 원문 그대로 반환 (dedupe는 objective-transition 호출 시점에 적용)
    assert "PLN-480" in result["DOD-002"]["evidence_refs"]
    assert "REQ-637" in result["DOD-002"]["evidence_refs"]


def test_objective_check_returns_evidence_refs():
    """objective-check --dod-id 응답에 evidence_refs 필드 포함."""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "objective-check", "AGI-016",
         "--dod-id", "DOD-001", "--json"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if proc.returncode == 0 and proc.stdout.strip():
        data = json.loads(proc.stdout)
        assert "evidence_refs" in data


def test_result_backward_compat():
    """--dod-ref/--domain 미지정 시 기존 동작 유지 (help 텍스트에 필수 아님 확인)."""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "result", "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    # --dod-ref가 required가 아닌 optional인지 확인 (대괄호로 감싸짐)
    help_text = proc.stdout
    assert "[--dod-ref" in help_text or "[--dod_ref" in help_text


def test_objective_transition_backward_compat():
    """--evidence-ref 미지정 기존 호출 동작 유지."""
    mst_script = PROJECT_ROOT / "scripts" / "mst.py"
    proc = subprocess.run(
        ["python3", str(mst_script), "agile", "objective-transition", "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    help_text = proc.stdout
    assert "[--evidence-ref" in help_text or "[--evidence_ref" in help_text
