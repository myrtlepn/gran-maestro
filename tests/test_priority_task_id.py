from __future__ import annotations

import argparse
import json

from scripts.mst_cmds import _common
from scripts.mst_cmds.priority import cmd_priority


def test_priority_uses_parse_task_id_for_multi_segment_task(tmp_path, monkeypatch) -> None:
    base_dir = tmp_path / ".gran-maestro"
    monkeypatch.setattr(_common, "BASE_DIR", base_dir)
    status_path = base_dir / "requests" / "REQ-100" / "tasks" / "T01-X" / "status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"id": "REQ-100-T01-X", "priority": "normal"}), encoding="utf-8")

    result = cmd_priority(argparse.Namespace(task_id="REQ-100-T01-X", before=None, after=None))

    assert result == 0
    updated = json.loads(status_path.read_text(encoding="utf-8"))
    assert updated["priority"] == "normal"
    assert "priority_before" not in updated
    assert "priority_after" not in updated
