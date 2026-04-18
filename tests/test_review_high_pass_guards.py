import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_SKILL = ROOT / "skills" / "review" / "SKILL.md"
DEFAULT_CONFIG = ROOT / "templates" / "defaults" / "config.json"


def test_review_minor_only_high_pass_guard_documented():
    assert REVIEW_SKILL.exists(), f"missing file: {REVIEW_SKILL}"
    content = REVIEW_SKILL.read_text(encoding="utf-8")

    assert "MINOR-only high-pass 보호 가드" in content
    assert "auto_accept_guard" in content
    assert "skipped_minor_count" in content
    assert "protection_flags_count" in content
    assert "minor_count <= config.review.severity_auto_fix.minor_skip_threshold" in content


def test_auto_accept_guard_single_source_in_defaults_config():
    assert DEFAULT_CONFIG.exists(), f"missing file: {DEFAULT_CONFIG}"
    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))

    guard = config["workflow"]["auto_accept_guard"]
    assert guard["single_source_of_truth"] == "workflow.auto_accept_guard"
    assert "review_summary.status == passed" in guard["allow_when"]
    assert "review_issues_summary.auto_accept_guard.blocked == false" in guard["allow_when"]
    assert "review_issues_summary.auto_accept_guard.skipped_minor_count > 0" in guard["block_when"]
    assert "review_issues_summary.auto_accept_guard.protection_flags_count > 0" in guard["block_when"]
