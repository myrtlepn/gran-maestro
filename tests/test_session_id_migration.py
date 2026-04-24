"""REQ-696/T01 T3: session_id snapshot isolation regression tests."""

import hashlib
from pathlib import Path

from tests.fixtures.hook_harness import run_hook, stdout_json
from tests.fixtures.session_helper import pair_sessions
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot


def _hook_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": "Stop",
    }


def _snapshot_path(project_root: Path, session_id: str) -> Path:
    return project_root / ".gran-maestro" / "state" / session_id / "snapshot.json"


def test_session_b_sees_no_a_snapshot(tmp_path):
    project_root, session_a, session_b = pair_sessions(tmp_path)
    write_snapshot(project_root, session_a, build_snapshot("agile-plan", 1, 3))

    result = run_hook(project_root, _hook_payload(session_b))

    payload = stdout_json(result)
    assert payload["decision"] == "approve"
    assert "no-mst-session" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]


def test_session_a_snapshot_integrity_after_b_hook(tmp_path):
    project_root, session_a, session_b = pair_sessions(tmp_path)
    write_snapshot(project_root, session_a, build_snapshot("agile-plan", 1, 3))
    a_path = _snapshot_path(project_root, session_a)
    pre_hash = hashlib.sha256(a_path.read_bytes()).hexdigest()
    pre_content = a_path.read_text(encoding="utf-8")

    run_hook(project_root, _hook_payload(session_b))

    post_hash = hashlib.sha256(a_path.read_bytes()).hexdigest()
    post_content = a_path.read_text(encoding="utf-8")
    assert pre_hash == post_hash
    assert pre_content == post_content
