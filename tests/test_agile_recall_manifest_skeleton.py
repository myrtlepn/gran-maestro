"""DOD-005: recall patch manifest skeleton tests."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_helper_exists():
    from scripts.mst_cmds.agile_governance import _generate_recall_patch_manifest_skeleton

    assert callable(_generate_recall_patch_manifest_skeleton)


def test_manifest_fields(tmp_path, monkeypatch):
    from scripts.mst_cmds import agile_governance

    def fake_session_dir(agi_id):
        d = tmp_path / agi_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(agile_governance, "_agi_session_dir", fake_session_dir)
    path = agile_governance._generate_recall_patch_manifest_skeleton(
        "AGI-016", 94, "drift_warning"
    )
    assert path is not None
    data = json.loads(Path(path).read_text())
    for field in [
        "agi_id",
        "level",
        "operations",
        "requires_user_approval",
        "generated_at",
        "todo",
    ]:
        assert field in data, f"missing field {field}"
    assert data["level"] == 2
    assert data["requires_user_approval"] is False


def test_level3_branch(tmp_path, monkeypatch):
    from scripts.mst_cmds import agile_governance

    def fake_session_dir(agi_id):
        d = tmp_path / agi_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(agile_governance, "_agi_session_dir", fake_session_dir)
    path = agile_governance._generate_recall_patch_manifest_skeleton(
        "AGI-016", 95, "objective_stale"
    )
    assert path is not None
    data = json.loads(Path(path).read_text())
    assert data["level"] == 3
    assert data["requires_user_approval"] is True


def test_unknown_classification_returns_none(tmp_path, monkeypatch):
    from scripts.mst_cmds import agile_governance

    def fake_session_dir(agi_id):
        d = tmp_path / agi_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(agile_governance, "_agi_session_dir", fake_session_dir)
    path = agile_governance._generate_recall_patch_manifest_skeleton(
        "AGI-016", 96, "aligned"
    )
    assert path is None


def test_config_recall_section():
    cfg = json.loads(
        (PROJECT_ROOT / "templates" / "defaults" / "config.json").read_text()
    )
    recall = cfg.get("recall", {})
    assert recall.get("auto_manifest_enabled") is True
    assert isinstance(recall.get("level2_operations"), list)
    for op in ["dod_add", "dod_remove", "dod_reorder", "dod_merge", "dod_refine"]:
        assert op in recall["level2_operations"]
    assert recall.get("level3_requires_approval") is True


def test_skill_md_recall_integration():
    text = (PROJECT_ROOT / "skills" / "agile" / "SKILL.md").read_text()
    assert "recall-patch-manifest" in text or "recall patch manifest" in text.lower()
    assert "Level 3" in text or "level3" in text.lower()
    assert "requires_user_approval" in text or "사용자 승인" in text


def test_drift_warning_triggers_manifest():
    from scripts.mst_cmds.agile import cmd_agile_result

    source = inspect.getsource(cmd_agile_result)
    assert (
        "_generate_recall_patch_manifest_skeleton" in source
        or "recall_patch_manifest" in source
    )


def test_graceful_fail():
    from scripts.mst_cmds.agile import cmd_agile_result

    source = inspect.getsource(cmd_agile_result)
    # drift-report와 recall manifest 각각 try/except로 감싼다
    assert source.count("try:") >= 2
    assert source.count("except") >= 2
