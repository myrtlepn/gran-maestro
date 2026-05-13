"""REQ-712/T01 + REQ-733/PLN-562: stop-hook flow anchor regression coverage.

DOD-005에 따라 stdout JSON은 {"decision","reason"}만 출력한다. anchor는
stderr 로그(`[stop-hook] anchor=...`)로 이동했으므로 anchor 검증은 stderr 기준.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.hook_harness import run_hook, stdout_json
from tests.fixtures.session_helper import init_project_root, make_session_id
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOW_CONSTRAINTS = REPO_ROOT / "docs" / "FLOW-CONSTRAINTS.md"

LAYER_1_ANCHOR = "docs/FLOW-CONSTRAINTS.md#layer-1-mode-gate"
LAYER_2_ANCHOR = "docs/FLOW-CONSTRAINTS.md#layer-2-snapshot-gate"
STEP_PROGRESS_ANCHOR = "docs/FLOW-CONSTRAINTS.md#step-progress"
COMPLETION_ANCHOR = "docs/FLOW-CONSTRAINTS.md#completion"

ALLOWED_FIELDS = {"decision", "reason"}


def _hook_payload(session_id: str | None = None) -> dict:
    payload = {
        "hook_event_name": "Stop",
        "last_assistant_message": "현재 단계 종료를 시도합니다.",
    }
    if session_id is not None:
        payload["session_id"] = session_id
        payload["transcript_path"] = f"/tmp/{session_id}.jsonl"
    return payload


def _assert_anchor_exists(anchor: str | None) -> None:
    if anchor is None:
        return
    assert anchor.startswith("docs/FLOW-CONSTRAINTS.md#")
    slug = anchor.rsplit("#", 1)[1]
    content = FLOW_CONSTRAINTS.read_text(encoding="utf-8")
    assert f"{{#{slug}}}" in content


def _assert_strict_schema(payload: dict) -> None:
    """DOD-005: stdout JSON은 {decision, reason}만 포함."""
    assert set(payload.keys()) == ALLOWED_FIELDS, (
        f"stdout JSON keys must be exactly {ALLOWED_FIELDS}, got {set(payload.keys())}"
    )


def _stderr_anchor(result) -> str | None:
    """stderr에서 [stop-hook] anchor=... 라인의 anchor 추출 (없으면 None)."""
    for line in result.stderr.splitlines():
        if line.startswith("[stop-hook] anchor="):
            return line.split("=", 1)[1].strip()
    return None


def test_layer_1_anchor_for_mst_off(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    result = run_hook(
        project_root,
        {
            "session_id": session_id,
            "stop_hook_active": True,
            "hook_event_name": "Stop",
            "last_assistant_message": "mst off pass-through",
        },
        env={"MST_TEST_FORCE_OFF": "1"},
    )

    payload = stdout_json(result)
    _assert_strict_schema(payload)
    assert payload["decision"] in {"approve", "allow"}
    assert "stop_hook_active_true" in payload["reason"]
    _assert_anchor_exists(_stderr_anchor(result))


def test_layer_2_or_null_for_no_session(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    _assert_strict_schema(payload)
    assert payload["decision"] == "approve"
    assert "workflow_inactive" in payload["reason"]
    assert "snapshot_present=false" in payload["reason"]
    _assert_anchor_exists(_stderr_anchor(result))


def test_completion_or_step_progress_for_mst_session(tmp_path):
    project_root = init_project_root(tmp_path)
    step_session_id = make_session_id()
    write_snapshot(
        project_root,
        step_session_id,
        build_snapshot("agile-plan", 1, 3),
    )

    result = run_hook(project_root, _hook_payload(step_session_id))

    payload = stdout_json(result)
    _assert_strict_schema(payload)
    assert payload["decision"] == "block"
    assert "step_progress" in payload["reason"]
    _assert_anchor_exists(_stderr_anchor(result))

    completion_session_id = make_session_id()
    write_snapshot(
        project_root,
        completion_session_id,
        build_snapshot("agile-plan", 3, 3, completed=True),
    )

    result = run_hook(project_root, _hook_payload(completion_session_id))

    payload = stdout_json(result)
    _assert_strict_schema(payload)
    assert payload["decision"] == "approve"
    assert "completion" in payload["reason"]
    _assert_anchor_exists(_stderr_anchor(result))


def test_decision_and_reason_fields_unchanged(tmp_path):
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    result = run_hook(project_root, _hook_payload(session_id))

    payload = stdout_json(result)
    _assert_strict_schema(payload)
    assert payload["decision"] == "approve"
    assert payload["reason"] == "workflow_inactive snapshot_present=false"
    _assert_anchor_exists(_stderr_anchor(result))
