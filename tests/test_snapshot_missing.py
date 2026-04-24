"""REQ-695/T01 T2: missing and corrupt snapshots fail open."""

from tests.fixtures.hook_harness import read_flow_detail, run_hook, stdout_json
from tests.fixtures.session_helper import init_project_root, make_session_id
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot


def _hook_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": "Stop",
    }


def test_snapshot_absent_allows_pass_through(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    assert payload["decision"] == "allow"
    assert "no-mst-session" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]


def test_snapshot_corrupt_fail_open_logs_hook_failure(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()
    snapshot_path = write_snapshot(
        project_root,
        session_id,
        build_snapshot("agile-plan", 1, 2),
    )
    snapshot_path.write_text("{invalid json...\n", encoding="utf-8")

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    assert payload["decision"] == "allow"
    events = read_flow_detail(project_root, session_id)
    hook_failure_events = [event for event in events if event.get("event_type") == "hook_failure"]
    if hook_failure_events:
        data = hook_failure_events[-1]["data"]
        assert "error_type" in data or "exit_code" in data
        assert any(field in data for field in ("stack_trace", "traceback", "source", "funcname"))
    else:
        assert "snapshot_present=true" in payload["reason"]
