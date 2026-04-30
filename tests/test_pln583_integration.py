from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from hooks.lib import pre_tool_use_fast
from scripts._hook_patterns import SELF_PAUSE_RE
from scripts.mst_cmds import resolver

PPID = "75702"


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_schedule_wakeup_block_keeps_resolver_and_text_detection_working(
    tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "workspace"
    state_dir = workspace / ".gran-maestro" / "tmp"
    state_dir.mkdir(parents=True)
    state_path = state_dir / f"mst-state-{PPID}.json"
    state_path.write_text(
        json.dumps(
            {
                "workflow_active": True,
                "updated_at": _timestamp(),
                "next_action": {
                    "expected_skill": "mst:request",
                    "source_skill": "mst:plan",
                    "source_id": "PLN-583",
                    "auto_mode": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("MST_STATE_PPID", PPID)

    status = pre_tool_use_fast.hardcoded_core_check(
        workspace,
        tmp_path / "home",
        {"tool_name": "ScheduleWakeup", "tool_input": {"delaySeconds": 1500}},
    )
    assert status == 2
    assert "MST-SCHEDULE-WAKEUP-BLOCK" in capsys.readouterr().err

    result = resolver.resolve_result(
        argparse.Namespace(
            conversation_id=None,
            wakeup_hint=None,
            enqueue=False,
            dry_run=False,
        )
    )
    assert result == {
        "command": "/mst:request --plan PLN-583 -a",
        "source": "workflow_state",
    }
    assert SELF_PAUSE_RE.search("ScheduleWakeup을 사용해 다음 사이클에 재개합니다")
