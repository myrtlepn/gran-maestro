"""DOD-003 multi-axis 회귀: block-then-resume chain 테스트."""

from __future__ import annotations

import json
import os

from tests.fixtures.hook_harness import read_flow_detail, run_hook, stdout_json
from tests.fixtures.session_helper import init_project_root, make_session_id
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot


def _stop_payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "hook_event_name": "Stop",
        "last_assistant_message": "현재 단계 작업 중입니다.",
    }


def test_block_decision_with_return_to_then_next_stop_resumes(tmp_path):
    """returnTo 설정 → block; returnTo 제거 후 → allow + flow-detail chain 이벤트 기록."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    # snapshot.returnTo 설정 (mst namespace, step=total)
    snap1 = build_snapshot("mst:plan", step=3, total=3, return_to={"skill": "plan", "step": 3})
    write_snapshot(project_root, session_id, snap1)

    payload = _stop_payload(session_id)

    # 첫 번째 Stop: returnTo 존재 → block
    r1 = run_hook(project_root, payload)
    d1 = stdout_json(r1)
    assert d1["decision"] == "block"
    assert "return_to" in d1["reason"].lower()

    # 사용자 응답 시뮬레이션: returnTo 제거 (step=total, status=active → unhandled_path 경로)
    snap2 = build_snapshot("mst:plan", step=3, total=3)  # no return_to; status="active"
    write_snapshot(project_root, session_id, snap2)

    # 두 번째 Stop: returnTo 소비 → unhandled_path fallback → allow
    r2 = run_hook(project_root, payload)
    d2 = stdout_json(r2)
    assert d2["decision"] == "approve"

    # AC-003: flow-detail에 chain 추적 이벤트 1건 이상 기록 (unhandled_path = 동등 신호)
    events = read_flow_detail(project_root, session_id)
    assert len(events) >= 1, "chain 복귀 후 flow-detail에 추적 이벤트가 1건 이상 기록되어야 한다"
    assert any(
        e.get("event_type") == "unhandled_path" for e in events
    ), f"unhandled_path 이벤트가 없다: {[e.get('event_type') for e in events]}"


def test_block_count_increment_on_repeated_block_within_threshold(tmp_path):
    """block_count가 0→1→2로 정확히 누적되고 threshold(3) 미만에서 에스컬레이션이 없어야 한다."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    # returnTo 설정 snapshot → 매 Stop마다 persist_block_state 호출
    snap = build_snapshot("mst:plan", step=3, total=3, return_to={"skill": "plan", "step": 3})
    write_snapshot(project_root, session_id, snap)

    payload = _stop_payload(session_id)
    state_file = (
        project_root / ".gran-maestro" / "tmp" / f"mst-state-{os.getpid()}.json"
    )

    # 첫 번째 block: count 0 → 1
    r1 = run_hook(project_root, payload)
    d1 = stdout_json(r1)
    assert d1["decision"] == "block"
    assert state_file.is_file(), "첫 번째 block 후 state file이 생성되어야 한다"
    state1 = json.loads(state_file.read_text(encoding="utf-8"))
    assert state1["block_count"] == 1, (
        f"첫 번째 block 후 block_count=1이어야 한다 (실제: {state1['block_count']})"
    )

    # 두 번째 block: count 1 → 2
    r2 = run_hook(project_root, payload)
    d2 = stdout_json(r2)
    assert d2["decision"] == "block"
    state2 = json.loads(state_file.read_text(encoding="utf-8"))
    assert state2["block_count"] == 2, (
        f"두 번째 block 후 block_count=2이어야 한다 (실제: {state2['block_count']})"
    )

    # threshold(3) 미만 → 에스컬레이션 메시지 없어야 한다
    assert "[자동 중단]" not in d1["reason"]
    assert "[자동 중단]" not in d2["reason"]


def test_block_decision_persists_until_user_message_observed(tmp_path):
    """사용자 응답 없이 어시스턴트만 응답하면 계속 block; snapshot 완료 후 첫 Stop은 allow."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    # returnTo 설정: 반복 block 유도
    snap = build_snapshot("mst:plan", step=2, total=3, return_to={"skill": "plan", "step": 2})
    write_snapshot(project_root, session_id, snap)

    payload = _stop_payload(session_id)

    # 사용자 응답 없음: 연속 block 유지
    r1 = run_hook(project_root, payload)
    assert stdout_json(r1)["decision"] == "block", "사용자 응답 없이 계속 block이어야 한다 (1차)"

    r2 = run_hook(project_root, payload)
    assert stdout_json(r2)["decision"] == "block", "사용자 응답 없이 계속 block이어야 한다 (2차)"

    # 사용자 응답 시뮬레이션: 스킬 완료(committed)로 snapshot 업데이트
    snap_done = build_snapshot("mst:plan", step=3, total=3, completed=True)  # status=committed
    write_snapshot(project_root, session_id, snap_done)

    # 사용자 메시지 감지 후 첫 Stop: allow (completion 경로)
    r3 = run_hook(project_root, payload)
    d3 = stdout_json(r3)
    assert d3["decision"] == "approve", (
        f"snapshot 완료 후 allow여야 한다 (실제: {d3['decision']}, reason: {d3.get('reason')})"
    )
