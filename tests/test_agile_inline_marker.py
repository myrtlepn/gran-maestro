import json
import time
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_inline_marker_start(path: Path, *, task_id: str, model: str) -> dict:
    now = _now_iso()
    payload = {
        "task_id": task_id,
        "phase": "running",
        "provider": "claude",
        "model": model,
        "started_at": now,
        "last_heartbeat": now,
        "inline": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _write_inline_marker_final(path: Path, *, phase: str, exit_code: int) -> dict:
    current = json.loads(path.read_text(encoding="utf-8"))
    now = _now_iso()
    current["phase"] = phase
    current["terminated_at"] = now
    current["exit_code"] = exit_code
    current["last_heartbeat"] = now
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def test_inline_marker_lifecycle(tmp_path):
    project_root = tmp_path / "workspace"
    task_id = "AGI-001-S01"
    marker_path = project_root / ".gran-maestro" / "run" / f"{task_id}.json"

    started = _write_inline_marker_start(marker_path, task_id=task_id, model="sonnet")
    assert marker_path.exists()
    assert started["phase"] == "running"
    assert started["inline"] is True

    time.sleep(0.01)
    finished = _write_inline_marker_final(marker_path, phase="done", exit_code=0)
    assert finished["phase"] == "done"
    assert finished["exit_code"] == 0
    assert isinstance(finished.get("terminated_at"), str) and finished["terminated_at"]
    assert finished["last_heartbeat"] != started["last_heartbeat"]

    dispatch_result = (
        project_root
        / ".gran-maestro"
        / "agile"
        / "AGI-001"
        / "sprints"
        / "S01"
        / "dispatch-result.json"
    )
    assert not dispatch_result.exists(), "inline marker lifecycle must not create dispatch-result.json"
