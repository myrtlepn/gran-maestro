"""REQ-695/T01 T1: snapshot returnTo guards missing return_to markers."""

from tests.fixtures.hook_harness import read_flow_detail, run_hook, stdout_json
from tests.fixtures.session_helper import init_project_root, make_session_id
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot


def _hook_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": f"/tmp/{session_id}.jsonl",
        "hook_event_name": "Stop",
        "last_assistant_message": "작업을 마무리합니다.",
    }


def test_returnto_snapshot_only_blocks(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()
    write_snapshot(
        project_root,
        session_id,
        build_snapshot(
            "agile-plan",
            3,
            5,
            return_to={"skill": "agile-plan", "step": 3},
        ),
    )

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    assert payload["decision"] == "block"
    assert "snapshot return_to" in payload["reason"] or "snapshot_return_to" in payload["reason"]
    assert "snapshot_present=true" in payload["reason"]


def test_returnto_missing_and_no_snapshot_allows(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    assert payload["decision"] == "allow"
    assert "no-mst-session" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]
    assert read_flow_detail(project_root, session_id) == []
