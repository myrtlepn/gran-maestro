"""DOD-004 T5: _snapshot_probe.probe() cross-session isolation regression tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
for candidate in (PROJECT_ROOT, SCRIPTS_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from scripts._snapshot_probe import probe  # noqa: E402
from scripts._flow_logger import safe_session_id  # noqa: E402


SID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _write_snapshot(project_root: Path, session_id: str, payload: dict) -> Path:
    state_dir = project_root / ".gran-maestro" / "state" / safe_session_id(session_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_isolated_sessions_do_not_leak(tmp_path):
    _write_snapshot(tmp_path, SID_A, {"currentSkill": "skillA", "status": "running"})

    raw = json.dumps({"session_id": SID_B, "hook_event_name": "Stop"})
    result = probe(tmp_path, raw)

    assert result["session_id"] == SID_B
    assert result["snapshot_present"] is False
    assert result["current_skill"] == ""
    assert result["status"] == ""


def test_session_specific_digest(tmp_path):
    _write_snapshot(tmp_path, SID_A, {"currentSkill": "skillA"})
    _write_snapshot(tmp_path, SID_B, {"currentSkill": "skillB"})

    raw_a = json.dumps({"session_id": SID_A, "hook_event_name": "Stop"})
    raw_b = json.dumps({"session_id": SID_B, "hook_event_name": "Stop"})
    result_a = probe(tmp_path, raw_a)
    result_b = probe(tmp_path, raw_b)

    assert result_a["snapshot_present"] is True
    assert result_b["snapshot_present"] is True
    assert result_a["snapshot_digest"] != ""
    assert result_b["snapshot_digest"] != ""
    assert result_a["snapshot_digest"] != result_b["snapshot_digest"]
    assert result_a["current_skill"] == "skillA"
    assert result_b["current_skill"] == "skillB"


def test_unknown_session_fallback_isolated(tmp_path):
    raw = json.dumps({"hook_event_name": "Stop"})
    result = probe(tmp_path, raw)

    assert result["session_id"] == "unknown"
    assert result["session_id_resolution_failed"] is True
    assert result["snapshot_present"] is False
    assert result["current_skill"] == ""


def test_transcript_path_uuid_recovery(tmp_path):
    sid = "12345678-1234-4234-8234-123456789abc"
    raw = json.dumps({
        "transcript_path": f"/some/abs/path/{sid}.jsonl",
        "hook_event_name": "Stop",
    })
    result = probe(tmp_path, raw)

    assert result["session_id"] == sid
    assert result["session_id_source"] == "transcript_path"
    assert result["session_id_resolution_failed"] is False
