from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts._state_manager import set_status


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_legacy_status_set(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-100"
    request_path = base_dir / "requests" / req_id / "request.json"
    _write_json(request_path, {"id": req_id, "status": "pending"})

    set_status(base_dir, req_id, "completed")

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "done"
    assert "updated_at" in payload


def test_invalid_status_raises_value_error(tmp_path: Path) -> None:
    base_dir = tmp_path / ".gran-maestro"
    req_id = "REQ-101"
    request_path = base_dir / "requests" / req_id / "request.json"
    _write_json(request_path, {"id": req_id, "status": "pending"})

    with pytest.raises(ValueError):
        set_status(base_dir, req_id, "xyz_invalid")
