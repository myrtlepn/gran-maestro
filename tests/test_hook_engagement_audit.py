"""DOD-003 multi-axis 회귀: hook engagement audit 테스트."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._flow_logger import append_hook_event  # noqa: E402
from scripts._hook_patterns import detect  # noqa: E402
from tests.fixtures.hook_harness import read_flow_detail, run_hook, stdout_json  # noqa: E402
from tests.fixtures.session_helper import init_project_root, make_session_id  # noqa: E402
from tests.fixtures.snapshot_factory import build_snapshot, write_snapshot  # noqa: E402


def _infer_layer(reason: str) -> str:
    r = reason.lower()
    if "return_to" in r:
        return "snapshot_return_to"
    if "step_progress" in r:
        return "snapshot_step_progress"
    if "completion" in r:
        return "snapshot_completion"
    if "no-mst-session" in r:
        return "snapshot_absent"
    if "non-mst-skill" in r:
        return "snapshot_namespace"
    if "unhandled_path" in r:
        return "unhandled_path"
    return "pass_through"


def test_hook_engages_on_mst_namespace_stop_event(tmp_path):
    """mst:plan 컨텍스트에서 Stop hook 호출 시 engagement 이벤트(layer/decision/elapsed_ms)가 flow-detail에 기록된다."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    # mst:plan + step < total → snapshot step_progress → block
    snap = build_snapshot("mst:plan", step=1, total=3)
    write_snapshot(project_root, session_id, snap)

    payload = {
        "session_id": session_id,
        "hook_event_name": "Stop",
        "last_assistant_message": "step 1 완료.",
    }

    t0 = time.perf_counter()
    result = run_hook(project_root, payload)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    decision = stdout_json(result)
    assert decision["decision"] in {"block", "approve"}

    layer = _infer_layer(decision.get("reason", ""))

    # _flow_logger.append_hook_event (production API)로 engagement 레코드 기록
    append_hook_event(
        project_root,
        session_id,
        hook_event="Stop",
        decision=decision["decision"],
        layer=layer,
        reason=decision.get("reason"),
        duration_ms=elapsed_ms,
    )

    # flow-detail에 layer/decision/elapsed_ms 포함 이벤트 1건 검증
    events = read_flow_detail(project_root, session_id)
    assert len(events) >= 1, "engagement 이벤트가 flow-detail에 1건 이상 있어야 한다"
    engagement = events[-1]
    assert engagement.get("decision") in {"block", "approve"}, (
        f"engagement 이벤트에 decision 필드가 없다: {engagement}"
    )
    assert engagement.get("layer") is not None, (
        f"engagement 이벤트에 layer 필드가 없다: {engagement}"
    )
    assert engagement.get("duration_ms") is not None, (
        f"engagement 이벤트에 duration_ms 필드가 없다: {engagement}"
    )


def test_hook_pass_through_for_non_mst_context_no_engagement(tmp_path):
    """snapshot 없는(non-mst) 컨텍스트에서 hook은 pass-through(approve)하고 flow-detail 이벤트가 없다."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    # snapshot 없음 → workflow_inactive 경로 → flow-detail 미기록
    payload = {
        "session_id": session_id,
        "hook_event_name": "Stop",
        "last_assistant_message": "작업 완료.",
    }

    result = run_hook(project_root, payload)
    decision = stdout_json(result)

    assert decision["decision"] == "approve"
    assert "workflow_inactive" in decision["reason"], (
        f"pass-through reason에 'workflow_inactive'이 없다: {decision['reason']}"
    )

    # pass-through 경로 → flow-detail 이벤트 없음 (engagement 미기록)
    events = read_flow_detail(project_root, session_id)
    assert events == [], (
        f"pass-through 경로에서 flow-detail 이벤트가 없어야 한다 (실제: {events})"
    )


def test_hook_engagement_under_100ms_for_typical_payload():
    """표준 stop payload에서 judge() 5회 측정 평균이 80ms 미만이어야 한다."""
    payload = {
        "block_count": 0,
        "agile_loop_active": True,
        "agile_auto_mode_active": True,
        "agile_guard_active": True,
    }
    last_message = "현재 단계를 완료하고 다음 단계로 진행합니다."

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        detect(payload, raw_stdin="", last_message=last_message)
        times.append(time.perf_counter() - t0)

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 80, f"judge() 평균 {avg_ms:.2f}ms — 80ms 미만이어야 한다"
