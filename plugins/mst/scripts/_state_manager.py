from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Optional

from scripts._state_schema import TASK_STATUSES
from scripts._state_normalize import migrate_legacy_status

KNOWN_TASK_STATUSES = frozenset(TASK_STATUSES)


def timestamp_now() -> str:
    """현재 UTC ISO 8601 타임스탬프 반환."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _find_json_file(base_dir: Path, id: str) -> Optional[Path]:
    """ID 기반으로 request.json / plan.json / session.json 탐색."""
    for candidate in [
        base_dir / "requests" / id / "request.json",
        base_dir / "requests" / "completed" / id / "request.json",
        base_dir / "plans" / id / "plan.json",
        base_dir / "debug" / id / "session.json",
        base_dir / "ideation" / id / "session.json",
        base_dir / "discussion" / id / "session.json",
        base_dir / "explore" / id / "session.json",
    ]:
        if candidate.exists():
            return candidate
    return None


def set_status(base_dir: Path, id: str, status: str) -> None:
    """JSON 파일의 status 필드와 updated_at을 갱신."""
    normalized_status = migrate_legacy_status(status, context=id)
    if normalized_status not in KNOWN_TASK_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    path = _find_json_file(base_dir, id)
    if not path:
        raise FileNotFoundError(f"JSON not found for ID: {id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = normalized_status
    data["updated_at"] = timestamp_now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _propagate_to_captures(base_dir: Path, req_id: str, cap_status: str) -> None:
    """REQ의 linked_captures 대상 캡처들에 상태를 전파."""
    if not req_id.upper().startswith("REQ-"):
        return
    req_path = _find_json_file(base_dir, req_id)
    if not req_path:
        return
    try:
        req_data = json.loads(req_path.read_text(encoding="utf-8"))
    except Exception:
        return

    linked_captures = req_data.get("linked_captures")
    if not isinstance(linked_captures, list) or not linked_captures:
        return

    now = timestamp_now()
    captures_dir = base_dir / "captures"
    for cap_id in linked_captures:
        if not isinstance(cap_id, str) or not cap_id.upper().startswith("CAP-"):
            continue
        cap_path = captures_dir / cap_id / "capture.json"
        try:
            if not cap_path.exists():
                continue
            cap_data = json.loads(cap_path.read_text(encoding="utf-8"))
            cap_data["status"] = cap_status
            cap_data["linked_request"] = req_id
            cap_data["updated_at"] = now
            cap_path.write_text(json.dumps(cap_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            continue


def _unblock_dependents(base_dir: Path, req_id: str) -> None:
    """REQ 완료 시 dependencies.blocks의 후속 REQ blockedBy를 정리."""
    if not req_id.upper().startswith("REQ-"):
        return
    req_path = _find_json_file(base_dir, req_id)
    if not req_path:
        return
    try:
        req_data = json.loads(req_path.read_text(encoding="utf-8"))
    except Exception:
        return

    dependencies = req_data.get("dependencies")
    if not isinstance(dependencies, dict):
        return
    blocks = dependencies.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return

    now = timestamp_now()
    for blocked_req_id in blocks:
        if not isinstance(blocked_req_id, str) or not blocked_req_id.upper().startswith("REQ-"):
            continue
        blocked_path = _find_json_file(base_dir, blocked_req_id)
        try:
            if not blocked_path:
                continue
            blocked_data = json.loads(blocked_path.read_text(encoding="utf-8"))
            blocked_dependencies = blocked_data.get("dependencies")
            if not isinstance(blocked_dependencies, dict):
                continue
            blocked_by = blocked_dependencies.get("blockedBy")
            if not isinstance(blocked_by, list):
                continue
            # 대소문자 불변 비교/제거
            matched = [b for b in blocked_by if b.upper() == req_id.upper()]
            if not matched:
                continue
            for m in matched:
                blocked_by.remove(m)
            if not blocked_by:
                blocked_data["status"] = "phase1_analysis"
                blocked_data["current_phase"] = 0
            blocked_data["updated_at"] = now
            blocked_path.write_text(json.dumps(blocked_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            continue


def complete(base_dir: Path, id: str) -> None:
    """JSON 파일의 status를 completed로 변경하고 completed_at/updated_at 갱신."""
    path = _find_json_file(base_dir, id)
    if not path:
        raise FileNotFoundError(f"JSON not found for ID: {id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    now = timestamp_now()
    data["status"] = "completed"
    data["completed_at"] = now
    data["updated_at"] = now
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _propagate_to_captures(base_dir, id, "done")


def cancel(base_dir: Path, id: str) -> None:
    """JSON 파일의 status를 cancelled로 변경하고 cancelled_at/updated_at 갱신."""
    path = _find_json_file(base_dir, id)
    if not path:
        raise FileNotFoundError(f"JSON not found for ID: {id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    now = timestamp_now()
    data["status"] = "cancelled"
    data["cancelled_at"] = now
    data["updated_at"] = now
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _propagate_to_captures(base_dir, id, "cancelled")


def set_field(base_dir: Path, id: str, field: str, value: str) -> None:
    """JSON 파일의 단일 필드를 업데이트."""
    path = _find_json_file(base_dir, id)
    if not path:
        raise FileNotFoundError(f"JSON not found for ID: {id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_phase(base_dir: Path, id: str, phase: int, status: str) -> None:
    """JSON 파일의 current_phase, status, updated_at을 원자적으로 갱신."""
    path = _find_json_file(base_dir, id)
    if not path:
        raise FileNotFoundError(f"JSON not found for ID: {id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["current_phase"] = phase
    data["status"] = status
    data["updated_at"] = timestamp_now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if phase == 5 and status == "done":
        _unblock_dependents(base_dir, id)


if __name__ == "__main__":
    raise SystemExit("직접 실행 금지. python3 scripts/mst.py를 통해 호출하세요.")
