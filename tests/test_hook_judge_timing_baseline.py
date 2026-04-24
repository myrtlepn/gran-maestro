"""DOD-011 hook judge timing baseline 회귀: soft 100ms 상한 3축 관찰."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._hook_patterns import detect  # noqa: E402
from tests.fixtures.session_helper import init_project_root, make_session_id  # noqa: E402


def test_judge_typical_payload_under_100ms_soft():
    """일반 stop payload (snapshot 존재 + active workflow) 에서 detect() 5회 평균이 80ms 미만이어야 한다."""
    payload = {
        "block_count": 0,
        "agile_loop_active": True,
        "agile_auto_mode_active": True,
        "agile_guard_active": True,
        "next_source": "DOD-005",
        "active_req": "REQ-709",
        "current_skill": "mst:plan",
    }
    last_message = "현재 단계를 완료하고 다음 단계로 진행합니다."

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        detect(payload, raw_stdin="", last_message=last_message)
        times.append(time.perf_counter() - t0)

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 80, f"judge() 평균 {avg_ms:.2f}ms — 80ms 미만이어야 한다"


def test_judge_large_flow_detail_under_100ms_soft(tmp_path):
    """flow-detail.ndjson에 100 이벤트 pre-seed 후 detect() 5회 평균이 80ms 미만이어야 한다."""
    project_root = init_project_root(tmp_path)
    session_id = make_session_id()

    flow_path = project_root / ".gran-maestro" / "state" / session_id / "flow-detail.ndjson"
    flow_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "type": "hook_event",
            "decision": "allow",
            "layer": "snapshot_step_progress",
            "duration_ms": i * 1.5,
            "session_id": session_id,
        })
        for i in range(100)
    ]
    flow_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    raw_stdin = flow_path.read_text(encoding="utf-8")

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
        detect(payload, raw_stdin=raw_stdin, last_message=last_message)
        times.append(time.perf_counter() - t0)

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 80, f"judge() 평균 {avg_ms:.2f}ms — 대용량 flow-detail에서 80ms 미만이어야 한다"


def test_judge_without_snapshot_fast_pass_through():
    """snapshot 없음(Layer 2 pass-through) 환경에서 detect() 5회 평균이 50ms 미만이어야 한다."""
    payload = {}
    last_message = "작업 완료."

    times = []
    last_result = None
    for _ in range(5):
        t0 = time.perf_counter()
        last_result = detect(payload, raw_stdin="", last_message=last_message)
        times.append(time.perf_counter() - t0)

    assert last_result["decision"] == "allow", (
        f"pass-through 경로는 allow를 반환해야 한다: {last_result}"
    )
    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 50, f"judge() 평균 {avg_ms:.2f}ms — pass-through 경로는 50ms 미만이어야 한다"
